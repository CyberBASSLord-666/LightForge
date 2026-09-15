#!/usr/bin/env python3
"""Execute a real Linux workload and collect explicitly scoped resource evidence.

This produces measurement evidence, never a release qualification. Complete
process-tree projection requires an explicitly delegated cgroup-v2 directory.
No command, environment, private path, stdout, or stderr enters the receipt.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time
import uuid

TOKEN = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
MAX_COUNTER = 2**63 - 1
MAX_SAMPLES = 100000


class MeasurementError(ValueError):
    pass


def counter(text):
    if not re.fullmatch(r"[0-9]+\n?", text) or len(text.strip()) > 19:
        raise MeasurementError("invalid_counter")
    value = int(text)
    if value > MAX_COUNTER:
        raise MeasurementError("counter_out_of_range")
    return value


def read_text(path, limit=65536):
    # A path may resolve to a FIFO/device. Nonblocking open plus fstat rejects
    # those before any read; procfs/sysfs counter nodes are regular files.
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise MeasurementError("counter_not_regular_file")
        with os.fdopen(descriptor, "r", encoding="ascii") as stream:
            descriptor = None
            text = stream.read(limit + 1)
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(text) > limit:
        raise MeasurementError("counter_input_too_large")
    return text


def pairs(text):
    result = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 2 or fields[0] in result:
            raise MeasurementError("invalid_counter_table")
        result[fields[0]] = counter(fields[1])
    return result


def io_totals(text):
    total = {"read_bytes": 0, "write_bytes": 0}
    seen = set()
    for line in text.splitlines():
        fields = line.split()
        if not fields or not re.fullmatch(r"\d+:\d+", fields[0]) or fields[0] in seen:
            raise MeasurementError("invalid_io_table")
        seen.add(fields[0])
        values = {}
        for field in fields[1:]:
            key, sep, value = field.partition("=")
            if not sep or key in values:
                raise MeasurementError("invalid_io_table")
            values[key] = counter(value)
        if not {"rbytes", "wbytes"}.issubset(values):
            raise MeasurementError("incomplete_io_table")
        total["read_bytes"] += values["rbytes"]
        total["write_bytes"] += values["wbytes"]
    if any(value > MAX_COUNTER for value in total.values()):
        raise MeasurementError("counter_out_of_range")
    return total


def nonnegative_delta(first, last):
    if type(first) is not int or type(last) is not int or not 0 <= first <= last <= MAX_COUNTER:
        raise MeasurementError("counter_reset_or_wrap")
    return last - first


class Cgroup:
    """Only a new child cgroup is touched; parent settings are never modified."""
    def __init__(self, parent):
        parent = Path(parent).absolute()
        if parent != parent.resolve(strict=True):
            raise MeasurementError("cgroup_parent_symlink")
        mounts = []
        for line in read_text("/proc/self/mountinfo", 1048576).splitlines():
            left, sep, right = line.partition(" - ")
            if sep and right.split()[0] == "cgroup2":
                mount = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), left.split()[4])
                mounts.append(Path(mount).resolve())
        if not any(parent.is_relative_to(mount) for mount in mounts):
            raise MeasurementError("not_cgroup_v2")
        if read_text(parent / "cgroup.type").strip() != "domain":
            raise MeasurementError("unsupported_cgroup_type")
        if pairs(read_text(parent / "cgroup.events")).get("frozen") != 0:
            raise MeasurementError("frozen_cgroup_parent")
        self.path = parent / ("lightforge-measure-" + uuid.uuid4().hex)
        self.path.mkdir(mode=0o700)
        try:
            required = ("cgroup.procs", "cgroup.events", "cgroup.kill", "cpu.stat", "memory.peak", "io.stat")
            if not all((self.path / name).is_file() for name in required):
                raise MeasurementError("cgroup_controllers_not_delegated")
            if read_text(self.path / "cgroup.procs").strip():
                raise MeasurementError("new_cgroup_not_empty")
            if pairs(read_text(self.path / "cgroup.events")).get("frozen") != 0:
                raise MeasurementError("frozen_child_cgroup")
            self.initial = self.sample()
        except BaseException:
            self.path.rmdir()
            raise

    def child_command(self, command, capacity_fd):
        # No Python preexec_fn: entering a concurrently frozen cgroup there
        # would block Popen before its timeout loop can run. Exec a constant
        # bootstrap first, then attach only itself before execing the workload.
        bootstrap = ("import os,sys\n"
                     "with open(sys.argv[1],'w',encoding='ascii') as f: f.write(str(os.getpid()))\n"
                     "fd=int(sys.argv[2]);os.write(fd,(str(len(os.sched_getaffinity(0)))+'\\n').encode('ascii'));os.close(fd)\n"
                     "os.execvpe(sys.argv[3],sys.argv[3:],os.environ)\n")
        return [sys.executable, "-I", "-S", "-c", bootstrap, str(self.path / "cgroup.procs"), str(capacity_fd), *command]

    def sample(self):
        cpu = pairs(read_text(self.path / "cpu.stat"))
        if "usage_usec" not in cpu:
            raise MeasurementError("cpu_counter_missing")
        return {"cpu_microseconds": cpu["usage_usec"],
                "peak_memory_bytes": counter(read_text(self.path / "memory.peak")),
                **io_totals(read_text(self.path / "io.stat"))}

    def populated(self):
        events = pairs(read_text(self.path / "cgroup.events"))
        if events.get("populated") not in (0, 1):
            raise MeasurementError("invalid_cgroup_population")
        return events["populated"] == 1

    def kill(self):
        with open(self.path / "cgroup.kill", "w", encoding="ascii") as stream:
            stream.write("1")

    def remove(self):
        self.path.rmdir()


class Sensors:
    def __init__(self, energy=None, energy_id=None, thermal=None, thermal_id=None):
        self.energy, self.energy_id = energy, energy_id
        self.thermal, self.thermal_id = thermal, thermal_id
        self.energy_first = self.energy_last = None
        self.thermal_samples = []
        self.errors = {}
        for path, identity in ((energy, energy_id), (thermal, thermal_id)):
            if bool(path) != bool(identity) or identity and not TOKEN.fullmatch(identity):
                raise MeasurementError("sensor_identity_required")

    def sample(self, elapsed):
        if self.energy and "energy" not in self.errors:
            try:
                value = counter(read_text(self.energy, 128))
                if self.energy_last is not None:
                    nonnegative_delta(self.energy_last, value)
                self.energy_last = value
                if self.energy_first is None:
                    self.energy_first = value
            except (OSError, ValueError):
                self.errors["energy"] = "unavailable_invalid_or_reset_counter"
        if self.thermal and "thermal" not in self.errors:
            try:
                raw = read_text(self.thermal, 128)
                if not re.fullmatch(r"-?[0-9]+\n?", raw) or len(raw.strip()) > 12:
                    raise MeasurementError("invalid_temperature")
                value = int(raw) / 1000.0
                if not -273.15 <= value <= 1000 or len(self.thermal_samples) >= MAX_SAMPLES:
                    raise MeasurementError("invalid_temperature_or_sample_limit")
                if self.thermal_samples and elapsed <= self.thermal_samples[-1]["elapsed_seconds"]:
                    raise MeasurementError("nonmonotonic_sample")
                self.thermal_samples.append({"elapsed_seconds": elapsed, "celsius": value})
            except (OSError, ValueError):
                self.errors["thermal"] = "unavailable_invalid_or_unbounded_sensor"

    def evidence(self):
        result = {}
        if self.energy and "energy" not in self.errors:
            result["energy"] = {"counter_id": self.energy_id,
                                "start_microjoules": self.energy_first,
                                "end_microjoules": self.energy_last}
        if self.thermal and "thermal" not in self.errors and len(self.thermal_samples) >= 2:
            result["thermal"] = {"sensor_id": self.thermal_id, "samples": self.thermal_samples}
        return result


def root_sample(pid):
    # /proc/PID/stat names may contain ')' and spaces. Start after the last ')'.
    fields = read_text(f"/proc/{pid}/stat").rsplit(")", 1)[1].split()
    ticks = int(fields[11]) + int(fields[12])
    result = {"cpu_seconds": ticks / os.sysconf("SC_CLK_TCK"),
              "rss_bytes": max(0, int(fields[21])) * os.sysconf("SC_PAGE_SIZE")}
    # Some hosts deny child /proc I/O despite readable stat. Keep those domains
    # independent; an inaccessible I/O counter is not a measured zero.
    try:
        values = pairs(read_text(f"/proc/{pid}/io").replace(":", ""))
        result.update({"read_bytes": values["read_bytes"], "write_bytes": values["write_bytes"]})
    except (OSError, ValueError, KeyError):
        pass
    return result


def collect(command, *, timeout=3600.0, interval=0.1, cgroup_parent=None,
            energy=None, energy_id=None, thermal=None, thermal_id=None):
    if not command or not all(isinstance(value, str) and "\0" not in value for value in command):
        raise MeasurementError("invalid_command")
    if not math.isfinite(timeout) or not 0.1 <= timeout <= 86400:
        raise MeasurementError("invalid_timeout")
    if not math.isfinite(interval) or not 0.01 <= interval <= 10 or math.ceil(timeout / interval) + 3 > MAX_SAMPLES:
        raise MeasurementError("invalid_sampling_bound")
    sensors = Sensors(energy, energy_id, thermal, thermal_id)
    capacity = len(os.sched_getaffinity(0))
    if not 1 <= capacity <= 65536:
        raise MeasurementError("invalid_cpu_capacity")
    report = {"schema_version": 1, "kind": "lightforge-process-resource-observation",
              "release_qualified": False, "status": "launch_failed", "exit_code": None,
              "accounting_scope": "root-process-incomplete", "process_tree_accounting_complete": False,
              "limitations": [], "errors": [], "observations": {}, "contract_projection": None}
    group = None
    if cgroup_parent is not None:
        try:
            group = Cgroup(cgroup_parent)
        except (OSError, ValueError):
            report["errors"].append("cgroup_setup_failed")
            return report
    if group:
        report["accounting_scope"] = "dedicated-cgroup-v2"
        report["limitations"].append("pre-attachment-bootstrap-cpu-excluded-from-cgroup-counters")
    else:
        report["limitations"].extend(["root-samples-omit-descendants", "short-lived-root-io-may-be-unobserved",
                                        "process-group-cleanup-cannot-cover-session-escaping-descendants"])
    report["limitations"].extend(["allocation-and-accelerator-counters-unobserved",
                                    "no-musical-quality-or-release-qualification"])
    if energy:
        report["limitations"].append("energy-is-host-package-scope-not-process-attribution")
    process = None
    root_pid_reserved = False
    root_observed = []
    usage = None
    capacity_read = capacity_write = None
    started = finished = None
    old_handlers = {}
    interrupted = [None]

    def interrupt(signum, _frame):
        interrupted[0] = signum

    def reap():
        nonlocal usage, root_pid_reserved
        if process is None or process.returncode is not None:
            return
        try:
            if not group:
                # Keep the exited leader unreaped while cleaning its own
                # process group: its PID/PGID cannot be reused in this window.
                exited = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if exited is None:
                    return
                signal_unreaped_group()
            pid, status, result = os.wait4(process.pid, os.WNOHANG)
        except ChildProcessError:
            root_pid_reserved = False
            raise
        if pid:
            process.returncode = os.waitstatus_to_exitcode(status)
            root_pid_reserved = False
            usage = result

    def signal_unreaped_group():
        nonlocal root_pid_reserved
        if process is None or process.returncode is not None or not root_pid_reserved:
            return
        # Confirm it remains our waitable child. Losing wait ownership must
        # never turn a stale numeric PGID into authority to signal a new group.
        try:
            os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        except ChildProcessError:
            root_pid_reserved = False
            raise
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def terminate_owned_work():
        # The bootstrap may still be outside the cgroup while attaching. Kill
        # its group only while the leader's PID is still reserved. After reap,
        # surviving descendants can be targeted only by the owned cgroup.
        signal_error = None
        try:
            signal_unreaped_group()
        except (OSError, ValueError) as error:
            signal_error = error
        if group and group.populated():
            group.kill()
        if signal_error is not None:
            raise signal_error

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            old_handlers[sig] = signal.signal(sig, interrupt)
        sensors.sample(0.0)
        started = time.monotonic()
        if group:
            capacity_read, capacity_write = os.pipe2(os.O_CLOEXEC | os.O_NONBLOCK)
        process = subprocess.Popen(group.child_command(command, capacity_write) if group else command,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True,
                                   pass_fds=(capacity_write,) if group else ())
        root_pid_reserved = True
        if capacity_write is not None:
            os.close(capacity_write)
            capacity_write = None
        report["status"] = "running"
        next_sample = started
        while True:
            now = time.monotonic()
            if interrupted[0] is not None or now - started >= timeout:
                report["status"] = "cancelled" if interrupted[0] is not None else "timeout"
                terminate_owned_work()
                break
            if now >= next_sample:
                if not group and process.returncode is None:
                    try:
                        root_observed.append(root_sample(process.pid))
                    except (OSError, ValueError, IndexError, KeyError):
                        pass  # A fast-exiting process is explicitly unobserved.
                sensors.sample(now - started)
                next_sample = now + interval
            reap()
            if process.returncode is not None and (not group or not group.populated()):
                report["status"] = "completed" if process.returncode == 0 else "command_failed"
                break
            time.sleep(min(0.02, max(0.001, next_sample - time.monotonic())))
        cleanup_deadline = time.monotonic() + 5.0
        while (process.returncode is None or group and group.populated()) and time.monotonic() < cleanup_deadline:
            reap()
            time.sleep(0.01)
        if process.returncode is None or group and group.populated():
            report["errors"].append("process_cleanup_incomplete")
        finished = time.monotonic()
        elapsed = finished - started
        sensors.sample(elapsed)
        report["exit_code"] = process.returncode
        observation = report["observations"]
        observation["wall_clock_seconds"] = elapsed
        if not group:
            observation["logical_cpu_count"] = capacity
            observation["cpu_capacity_basis"] = "inherited-sched-getaffinity-count-not-quota-adjusted"
        observation["sensor_boundary_basis"] = "sequential-counter-reads-at-window-boundaries"
        observation["sensor_counters"] = sensors.evidence()
        observation["sensor_errors"] = sensors.errors
        observation["energy_scope"] = "host-package" if energy else "unobserved"
        if group:
            attached_capacity = None
            try:
                raw_capacity = os.read(capacity_read, 32)
                if raw_capacity:
                    attached_capacity = counter(raw_capacity.decode("ascii"))
                    if not 1 <= attached_capacity <= 65536:
                        raise MeasurementError("invalid_attached_cpu_capacity")
            except BlockingIOError:
                pass
            if report["status"] == "completed" and attached_capacity is None:
                raise MeasurementError("attached_cpu_capacity_unobserved")
            if attached_capacity is not None:
                observation["logical_cpu_count"] = attached_capacity
                observation["cpu_capacity_basis"] = "bootstrap-sched-getaffinity-after-cgroup-attachment-not-quota-adjusted"
            final = group.sample()
            observation["cgroup_counters"] = {"start": group.initial, "end": final,
                                               "cpu_counter_unit": "microseconds", "io_counter_unit": "bytes"}
            cpu_seconds = nonnegative_delta(group.initial["cpu_microseconds"], final["cpu_microseconds"]) / 1e6
            if attached_capacity is not None and cpu_seconds > elapsed * attached_capacity:
                raise MeasurementError("cpu_counter_exceeds_observed_capacity")
            observation.update({"cpu_seconds": cpu_seconds, "peak_memory_bytes": final["peak_memory_bytes"],
                                "memory_basis": "cgroup-memory-peak-includes-cache-and-kernel-not-rss",
                                "read_bytes": nonnegative_delta(group.initial["read_bytes"], final["read_bytes"]),
                                "write_bytes": nonnegative_delta(group.initial["write_bytes"], final["write_bytes"])})
            report["process_tree_accounting_complete"] = report["status"] == "completed" and not report["errors"]
            if report["process_tree_accounting_complete"]:
                counters = {"schema_version": 1, "protocol": "lightforge-resource-counters-v1",
                            "elapsed_seconds": elapsed, "cpu": {"logical_cpu_count": attached_capacity}, **sensors.evidence()}
                report["contract_projection"] = {"execution": {"wall_clock_seconds": elapsed,
                                                     "cpu_seconds": cpu_seconds, "resource_counters": counters},
                                                 "scope": "dedicated-cgroup-v2-external-workload"}
        else:
            observation["root_procfs_samples"] = len(root_observed)
            if root_observed:
                observation["root_sampled_peak_rss_bytes"] = max(row["rss_bytes"] for row in root_observed)
            io_observed = [row for row in root_observed if "read_bytes" in row]
            observation["root_procfs_io_samples"] = len(io_observed)
            if io_observed:
                observation["root_sampled_read_bytes"] = max(row["read_bytes"] for row in io_observed)
                observation["root_sampled_write_bytes"] = max(row["write_bytes"] for row in io_observed)
            if usage is not None:
                observation["wait4_cpu_seconds"] = usage.ru_utime + usage.ru_stime
                observation["wait4_user_cpu_seconds"] = usage.ru_utime
                observation["wait4_system_cpu_seconds"] = usage.ru_stime
                observation["wait4_peak_rss_bytes"] = int(usage.ru_maxrss) * 1024
                observation["wait4_input_blocks"] = usage.ru_inblock
                observation["wait4_output_blocks"] = usage.ru_oublock
                observation["wait4_scope"] = "root-plus-descendants-it-reaped-not-complete-process-tree"
    except (OSError, ValueError, subprocess.SubprocessError, IndexError, KeyError):
        report["errors"].append("measurement_or_launch_failed")
        report["status"] = "measurement_failed"
    finally:
        for descriptor in (capacity_read, capacity_write):
            if descriptor is not None:
                os.close(descriptor)
        if process is not None:
            try:
                # This is a no-op for a reaped root and empty owned cgroup.
                # A failed population read is an explicit cleanup failure;
                # it never authorizes a fallback signal to a stale PGID.
                terminate_owned_work()
                deadline = time.monotonic() + 5
                while ((root_pid_reserved and process.returncode is None) or group and group.populated()) and time.monotonic() < deadline:
                    reap()
                    time.sleep(0.01)
                if (root_pid_reserved and process.returncode is None) or group and group.populated():
                    if "process_cleanup_incomplete" not in report["errors"]:
                        report["errors"].append("process_cleanup_incomplete")
            except (OSError, ValueError):
                report["errors"].append("process_cleanup_failed")
        if group:
            try:
                group.remove()
            except OSError:
                report["errors"].append("cgroup_cleanup_failed")
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        if report["errors"]:
            report["process_tree_accounting_complete"] = False
            report["contract_projection"] = None
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("--interval", type=float, default=0.1)
    parser.add_argument("--cgroup-parent")
    parser.add_argument("--energy-counter")
    parser.add_argument("--energy-counter-id")
    parser.add_argument("--thermal-sensor")
    parser.add_argument("--thermal-sensor-id")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    try:
        # Claim a new private receipt before executing any workload.
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        print("resource_receipt_output_unavailable", file=sys.stderr)
        return 2
    try:
        report = collect(command, timeout=args.timeout, interval=args.interval,
                         cgroup_parent=args.cgroup_parent, energy=args.energy_counter,
                         energy_id=args.energy_counter_id, thermal=args.thermal_sensor,
                         thermal_id=args.thermal_sensor_id)
    except (OSError, ValueError):
        report = {"schema_version": 1, "kind": "lightforge-process-resource-observation",
                  "release_qualified": False, "status": "invalid_configuration", "errors": ["invalid_configuration"]}
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"status": report["status"], "release_qualified": False,
                      "process_tree_accounting_complete": report.get("process_tree_accounting_complete", False)}))
    return 0 if report["status"] == "completed" and not report.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
