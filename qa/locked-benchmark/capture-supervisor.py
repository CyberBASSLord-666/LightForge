#!/usr/bin/env python3
"""Own and bound a Linux capture subprocess and its ordinary descendants.

The helper is a child subreaper. Normal monitoring only reaps owned children;
it does not enumerate procfs while the capture is being measured. During
cleanup, procfs suggests direct-child PIDs, but non-consuming waitid provides
the ownership proof before a pidfd is opened. Detached descendants become
direct children when their parents exit. This is lifecycle supervision of
trusted capture code, not a hostile sandbox.
"""

import ctypes
import json
import os
import signal
import subprocess
import sys
import time


CLEANUP_NS = 3_000_000_000
TERM_GRACE_NS = 150_000_000
STOP = False


def request_stop(_signum, _frame):
    global STOP
    STOP = True


def stat_record(pid):
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as stream:
            raw = stream.read(8192)
        fields = raw[raw.rfind(")") + 2:].split()
        return {"pid": pid, "state": fields[0], "ppid": int(fields[1]),
                "start": fields[19]}
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None


def namespace_ids(proc_path):
    with open(proc_path + "/status", encoding="ascii", errors="replace") as stream:
        # NSpid is in the fixed header; do not read an unbounded Groups line.
        for _ in range(64):
            line = stream.readline(4096)
            if not line:
                break
            if line.startswith("NSpid:"):
                return [int(value) for value in line.split()[1:]]
    raise RuntimeError("procfs NSpid mapping is required")


class OwnedProcesses:
    def __init__(self):
        # procfs may be mounted in an outer PID namespace. Tree traversal uses
        # procfs-visible IDs; pidfd_open and waitpid use this helper's namespace.
        identifiers = namespace_ids("/proc/self")
        if identifiers[-1] != os.getpid():
            raise RuntimeError("cannot identify supervisor PID namespace")
        self.parent = identifiers[0]
        self.namespace_depth = len(identifiers) - 1
        self.handles = {}
        self.main_pid = None
        self.main_status = None
        self.reaped = 0
        self.cleanup_discovery_scans = 0
        self.discovery_deadline_exhausted = False
        self.children_path = "/proc/thread-self/children"
        self.discovery = "procfs_direct_children"
        try:
            with open(self.children_path, encoding="ascii") as stream:
                stream.read(1)
        except FileNotFoundError:
            self.children_path = f"/proc/self/task/{self.parent}/children"
            try:
                with open(self.children_path, encoding="ascii") as stream:
                    stream.read(1)
            except FileNotFoundError:
                # Kernels without CONFIG_CHECKPOINT_RESTORE omit children.
                # This fallback is used exclusively during forced cleanup.
                self.children_path = None
                self.discovery = "procfs_ppid_hints_at_cleanup_only"

    def before_deadline(self, deadline_ns):
        if time.monotonic_ns() >= deadline_ns:
            self.discovery_deadline_exhausted = True
            return False
        return True

    def proc_pid_hints(self, deadline_ns):
        """Stream bounded hints; never eagerly consume a host process table."""
        if self.children_path is not None:
            with open(self.children_path, encoding="ascii") as stream:
                pending = ""
                while self.before_deadline(deadline_ns):
                    chunk = stream.read(4096)
                    if not chunk:
                        if pending and self.before_deadline(deadline_ns):
                            yield int(pending)
                        return
                    tokens = (pending + chunk).split()
                    pending = "" if chunk[-1].isspace() else tokens.pop()
                    if len(pending) > 32:
                        raise RuntimeError("invalid procfs child PID token")
                    for token in tokens:
                        if not self.before_deadline(deadline_ns):
                            return
                        yield int(token)
        else:
            with os.scandir("/proc") as entries:
                while self.before_deadline(deadline_ns):
                    try:
                        entry = next(entries)
                    except StopIteration:
                        return
                    if entry.name.isascii() and entry.name.isdigit():
                        record = stat_record(int(entry.name))
                        if record is not None and record["ppid"] == self.parent:
                            yield record["pid"]

    def candidate_pids(self, deadline_ns):
        """Discover hints, not ownership; called only during forced cleanup."""
        self.cleanup_discovery_scans += 1
        for proc_pid in self.proc_pid_hints(deadline_ns):
            if not self.before_deadline(deadline_ns):
                return
            try:
                identifiers = namespace_ids(f"/proc/{proc_pid}")
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
            if len(identifiers) > self.namespace_depth:
                yield identifiers[self.namespace_depth]

    def pin_direct(self, pid):
        """Pin only an unreaped direct child, as authenticated by the kernel.

        This process is single-threaded and its signal handlers never reap.
        Once waitid succeeds, nobody can reap/reuse the child PID before
        pidfd_open. A PPid hint or its intermediate ancestor is never trusted.
        """
        try:
            os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        except ChildProcessError:
            return False
        if pid not in self.handles:
            self.handles[pid] = os.pidfd_open(pid)
        return True

    def discover_direct_children(self, deadline_ns):
        for pid in self.candidate_pids(deadline_ns):
            if not self.before_deadline(deadline_ns):
                return False
            self.pin_direct(pid)
        return not self.discovery_deadline_exhausted and self.before_deadline(deadline_ns)

    def signal_all(self, signum):
        for handle in self.handles.values():
            try:
                signal.pidfd_send_signal(handle, signum)
            except ProcessLookupError:
                pass

    def reap(self):
        """Return true only when the kernel reports no owned children remain."""
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return True
            if pid == 0:
                return False
            self.reaped += 1
            handle = self.handles.pop(pid, None)
            if handle is not None:
                os.close(handle)
            if pid == self.main_pid:
                self.main_status = os.waitstatus_to_exitcode(status)

    def remaining(self):
        result = []
        for pid in self.handles:
            try:
                os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                result.append(pid)
            except ChildProcessError:
                pass
        return sorted(result)

    def close(self):
        for handle in self.handles.values():
            os.close(handle)
        self.handles.clear()


def supervise(deadline_ns, command):
    owned = OwnedProcesses()
    child = None
    timed_out = False
    cleanup_required = False
    cleanup_attempted = False
    verified = False
    errors = []
    try:
        if sys.platform != "linux" or not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            raise RuntimeError("Linux pidfd support is required")
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
            raise OSError(ctypes.get_errno(), "cannot become child subreaper")
        if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
            raise OSError(ctypes.get_errno(), "cannot set parent death signal")
        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)
        # Fail before spawning if procfs or pidfd signaling is unavailable.
        own_record = stat_record(owned.parent)
        if own_record is None:
            raise RuntimeError("readable Linux procfs is required")
        probe = os.pidfd_open(os.getpid())
        try:
            signal.pidfd_send_signal(probe, 0)
        finally:
            os.close(probe)
        if time.monotonic_ns() >= deadline_ns or STOP:
            timed_out = not STOP
            verified = True
        else:
            child = subprocess.Popen(command, start_new_session=True, close_fds=True)
            owned.main_pid = child.pid
            if not owned.pin_direct(child.pid):
                raise RuntimeError("spawned process was not an owned direct child")
            while True:
                empty = owned.reap()
                now = time.monotonic_ns()
                if now >= deadline_ns:
                    timed_out = True
                    break
                if STOP:
                    errors.append("supervisor interrupted")
                    break
                if owned.main_status is not None:
                    verified = empty
                    cleanup_required = not empty
                    break
                time.sleep(min(0.05, max(0, (deadline_ns - now) / 1_000_000_000)))
    except Exception as error:
        errors.append(f"{type(error).__name__}: {str(error)[:400]}")
    finally:
        if child is not None and not verified:
            cleanup_attempted = True
            started = time.monotonic_ns()
            cleanup_deadline = started + CLEANUP_NS
            while time.monotonic_ns() < cleanup_deadline:
                try:
                    signum = signal.SIGTERM if time.monotonic_ns() - started < TERM_GRACE_NS else signal.SIGKILL
                    # Signal pinned parents first. Exiting parents cause their
                    # detached descendants to be adopted by this subreaper.
                    owned.signal_all(signum)
                    if owned.reap():
                        verified = True
                        break
                    if not owned.discover_direct_children(cleanup_deadline):
                        # Exhausted discovery cannot justify leaving identities
                        # already proven and pinned running after only TERM.
                        owned.signal_all(signal.SIGKILL)
                        break
                    owned.signal_all(signum)
                    if owned.reap():
                        verified = True
                        break
                except Exception as error:
                    message = f"cleanup {type(error).__name__}: {str(error)[:400]}"
                    if message not in errors:
                        errors.append(message)
                time.sleep(0.01)
        elif child is None:
            verified = True
        if child is not None and owned.main_status is not None:
            child.returncode = owned.main_status

    status = owned.main_status
    target_signal = signal.Signals(-status).name if status is not None and status < 0 else None
    exit_code = 124 if timed_out else (128 - status if status is not None and status < 0 else status)
    if exit_code is None or (exit_code == 0 and (errors or cleanup_required or not verified)):
        exit_code = 1
    result = {
        "exit_code": exit_code,
        "signal": target_signal,
        "timed_out": timed_out,
        "termination": {
            "attempted": cleanup_attempted,
            "verified": verified,
            "remaining_pids": owned.remaining(),
            "cleanup_required": cleanup_required,
            "reaped_processes": owned.reaped,
            "process_discovery": owned.discovery,
            "cleanup_discovery_scans": owned.cleanup_discovery_scans,
            "discovery_deadline_exhausted": owned.discovery_deadline_exhausted,
            "scope": "Linux subreaper; waitid-owned direct children; pidfd signals; kernel waitpid confirmation",
        },
    }
    if errors:
        result["errors"] = errors[:8]
    owned.close()
    return result


def main():
    if len(sys.argv) < 4 or sys.argv[2] != "--":
        raise SystemExit("expected monotonic deadline, --, executable and arguments")
    result = supervise(int(sys.argv[1]), sys.argv[3:])
    os.write(3, (json.dumps(result, allow_nan=False, separators=(",", ":")) + "\n").encode())
    return min(255, max(0, result["exit_code"]))


if __name__ == "__main__":
    raise SystemExit(main())
