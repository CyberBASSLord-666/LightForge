#!/usr/bin/env python3
"""Own and bound a Linux capture subprocess and its ordinary descendants.

The helper is a child subreaper. Detached descendants are therefore adopted
when their parents exit. Signals use pidfds, never a reused PID or host group.
This is lifecycle supervision of trusted capture code, not a hostile sandbox.
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
        for line in stream:
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

    def observe(self):
        records = {}
        for name in os.listdir("/proc"):
            if name.isascii() and name.isdigit():
                record = stat_record(int(name))
                if record is not None:
                    records[record["pid"]] = record
        owned = {self.parent}
        pending = list(records.values())
        while pending:
            rest = []
            added = False
            for record in pending:
                if record["ppid"] in owned:
                    owned.add(record["pid"])
                    self.pin(record)
                    added = True
                else:
                    rest.append(record)
            if not added:
                break
            pending = rest
        for pid, (start, handle) in list(self.handles.items()):
            current = records.get(pid)
            if current is None or current["start"] != start:
                os.close(handle)
                del self.handles[pid]

    def pin(self, record):
        pid = record["pid"]
        existing = self.handles.get(pid)
        if existing is not None and existing[0] == record["start"]:
            return
        try:
            identifiers = namespace_ids(f"/proc/{pid}")
            if len(identifiers) <= self.namespace_depth:
                raise RuntimeError("owned process is outside supervisor PID namespace")
            handle = os.pidfd_open(identifiers[self.namespace_depth])
        except (FileNotFoundError, ProcessLookupError):
            return
        current = stat_record(pid)
        if current is None or current["start"] != record["start"]:
            os.close(handle)
            return
        if existing is not None:
            os.close(existing[1])
        self.handles[pid] = (record["start"], handle)

    def signal_all(self, signum):
        for _start, handle in self.handles.values():
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
            if pid == self.main_pid:
                self.main_status = os.waitstatus_to_exitcode(status)

    def remaining(self):
        result = []
        for pid, (start, _handle) in self.handles.items():
            current = stat_record(pid)
            if current is not None and current["start"] == start:
                result.append(pid)
        return sorted(result)

    def close(self):
        for _start, handle in self.handles.values():
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
            while True:
                owned.observe()
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
                time.sleep(min(0.01, max(0, (deadline_ns - now) / 1_000_000_000)))
    except Exception as error:
        errors.append(f"{type(error).__name__}: {str(error)[:400]}")
    finally:
        if child is not None and not verified:
            cleanup_attempted = True
            started = time.monotonic_ns()
            cleanup_deadline = started + CLEANUP_NS
            while time.monotonic_ns() < cleanup_deadline:
                try:
                    owned.observe()
                    signum = signal.SIGTERM if time.monotonic_ns() - started < TERM_GRACE_NS else signal.SIGKILL
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
            "scope": "Linux child subreaper descendants; pidfd signals; kernel waitpid confirmation",
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
