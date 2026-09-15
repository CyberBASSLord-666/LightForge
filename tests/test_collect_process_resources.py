#!/usr/bin/env python3
"""Counter rejection and real external-workload collector checks."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import analysis_benchmark_contract as CONTRACT
SPEC = importlib.util.spec_from_file_location("collector", ROOT / "tools/collect_process_resources.py")
C = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(C)


class CollectorTests(unittest.TestCase):
    def test_strict_counter_tables_and_monotonicity(self):
        self.assertEqual(C.io_totals("8:0 rbytes=12 wbytes=19 rios=1 wios=2\n8:1 rbytes=3 wbytes=5\n"),
                         {"read_bytes": 15, "write_bytes": 24})
        self.assertEqual(C.io_totals(""), {"read_bytes": 0, "write_bytes": 0})
        for value in ("-1", "1.0", "nan", "1\n2", str(2**63)):
            with self.assertRaises(C.MeasurementError):
                C.counter(value)
        for value in ("8:0 rbytes=1", "8:0 rbytes=1 rbytes=2 wbytes=3", "8:0 rbytes=1 wbytes=2\n8:0 rbytes=3 wbytes=4"):
            with self.assertRaises(C.MeasurementError):
                C.io_totals(value)
        with self.assertRaises(C.MeasurementError):
            C.nonnegative_delta(200, 1)

    def test_real_child_cpu_io_and_private_output(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "private-workload-data"
            code = "import os,time; print('PRIVATE_COMMAND_OUTPUT'); f=open(" + repr(str(target)) + ", 'wb'); f.write(b'x'*(8*1024*1024)); f.flush(); os.fsync(f.fileno()); end=time.monotonic()+0.25\nwhile time.monotonic()<end: sum(i*i for i in range(4000))\ntime.sleep(0.05)"
            before = time.process_time()
            report = C.collect([sys.executable, "-c", code], timeout=5, interval=.01)
            parent_cpu = time.process_time() - before
            self.assertEqual(report["status"], "completed", report)
            self.assertEqual(report["exit_code"], 0)
            self.assertGreater(report["observations"]["wait4_cpu_seconds"], .15)
            self.assertGreater(report["observations"]["wait4_cpu_seconds"], parent_cpu * 2)
            self.assertEqual(target.stat().st_size, 8*1024*1024)
            # Restricted procfs may deny child io counters. The kernel wait4
            # block count remains a genuine external-process observation.
            self.assertGreater(report["observations"]["wait4_output_blocks"], 0)
            if report["observations"]["root_procfs_io_samples"]:
                self.assertGreaterEqual(report["observations"]["root_sampled_write_bytes"], 8*1024*1024)
            else:
                self.assertNotIn("root_sampled_write_bytes", report["observations"])
            self.assertIsNone(report["contract_projection"])
            self.assertFalse(report["process_tree_accounting_complete"])
            self.assertFalse(report["release_qualified"])
            self.assertEqual(report["observations"]["sensor_counters"], {})
            text = json.dumps(report)
            self.assertNotIn(str(target), text)
            self.assertNotIn("PRIVATE_COMMAND_OUTPUT", text)

    def test_timeout_kills_same_session_descendant(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / "pid"
            code = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);open(" + repr(str(pidfile)) + ",'w').write(str(p.pid));time.sleep(30)"
            start = time.monotonic()
            report = C.collect([sys.executable, "-c", code], timeout=.3, interval=.02)
            self.assertEqual(report["status"], "timeout", report)
            self.assertLess(time.monotonic()-start, 3)
            child = int(pidfile.read_text())
            stat = Path(f"/proc/{child}/stat")
            if stat.exists():
                self.assertEqual(stat.read_text().rsplit(")", 1)[1].split()[0], "Z")
            self.assertIsNone(report["contract_projection"])

    def test_signal_cancellation_restores_handlers(self):
        handler = signal.getsignal(signal.SIGTERM)
        code = "import os,signal,time;os.kill(os.getppid(),signal.SIGTERM);time.sleep(30)"
        report = C.collect([sys.executable, "-c", code], timeout=5, interval=.02)
        self.assertEqual(report["status"], "cancelled", report)
        self.assertEqual(signal.getsignal(signal.SIGTERM), handler)
        self.assertIsNone(report["contract_projection"])

    def test_nonzero_and_missing_command_are_not_success(self):
        failed = C.collect([sys.executable, "-c", "raise SystemExit(7)"], timeout=2)
        self.assertEqual(failed["status"], "command_failed")
        self.assertEqual(failed["exit_code"], 7)
        missing = C.collect(["/missing/private/command"], timeout=2)
        self.assertEqual(missing["status"], "measurement_failed")
        self.assertNotIn("/missing", json.dumps(missing))

    def test_sensor_raw_values_reset_and_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            energy, thermal = Path(directory)/"energy", Path(directory)/"thermal"
            energy.write_text("1000000\n"); thermal.write_text("41000\n")
            sensor = C.Sensors(energy, "rapl-package0", thermal, "cpu-temperature")
            sensor.sample(0)
            energy.write_text("1250000\n"); thermal.write_text("43500\n")
            sensor.sample(1)
            result = sensor.evidence()
            self.assertEqual(result["energy"]["end_microjoules"] - result["energy"]["start_microjoules"], 250000)
            self.assertEqual(result["thermal"]["samples"][-1], {"elapsed_seconds": 1, "celsius": 43.5})
            energy.write_text("10\n"); thermal.unlink()
            sensor.sample(2)
            self.assertEqual(sensor.evidence(), {})
            self.assertEqual(set(sensor.errors), {"energy", "thermal"})

    def test_sample_bounds_and_sensor_identity_fail_before_launch(self):
        for timeout, interval in ((float("nan"), .1), (86401, .1), (3600, .01), (1, .001)):
            with self.assertRaises(C.MeasurementError):
                C.collect(["never-executed"], timeout=timeout, interval=interval)
        with self.assertRaises(C.MeasurementError):
            C.collect(["never-executed"], energy="/private", energy_id="not/a/token")

    def test_fifo_sensor_is_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            fifo = Path(directory)/"fifo"
            os.mkfifo(fifo)
            start = time.monotonic()
            report = C.collect([sys.executable, "-c", "pass"], timeout=.5,
                               energy=fifo, energy_id="blocked-energy-source")
            self.assertLess(time.monotonic()-start, 1)
            self.assertEqual(report["status"], "completed")
            self.assertNotIn("energy", report["observations"]["sensor_counters"])
            self.assertIn("energy", report["observations"]["sensor_errors"])

    def test_non_cgroup_parent_never_executes_or_changes_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory)/"marker"
            code = "from pathlib import Path;Path(" + repr(str(marker)) + ").touch()"
            report = C.collect([sys.executable, "-c", code], cgroup_parent=directory)
            self.assertEqual(report["errors"], ["cgroup_setup_failed"])
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_cgroup_projection_uses_group_cpu_not_parent_or_wait4(self):
        # Fake kernel reads test projection only; this is never qualification.
        class FakeGroup:
            def __init__(self, parent):
                self.initial = {"cpu_microseconds": 0, "read_bytes": 0, "write_bytes": 0}
            def child_command(self, command, capacity_fd):
                bootstrap = "import os,sys;f=int(sys.argv[1]);os.write(f,b'1\\n');os.close(f);os.execvpe(sys.argv[2],sys.argv[2:],os.environ)"
                return [sys.executable, "-I", "-S", "-c", bootstrap, str(capacity_fd), *command]
            def populated(self): return False
            def kill(self): pass
            def remove(self): pass
            def sample(self): return {"cpu_microseconds": 123, "peak_memory_bytes": 4096, "read_bytes": 17, "write_bytes": 29}
        with mock.patch.object(C, "Cgroup", FakeGroup):
            result = C.collect([sys.executable, "-c", "pass"], cgroup_parent="fake-kernel", timeout=2)
        self.assertTrue(result["process_tree_accounting_complete"])
        projection = result["contract_projection"]
        self.assertEqual(projection["execution"]["cpu_seconds"], .000123)
        self.assertEqual(projection["execution"]["resource_counters"]["cpu"]["logical_cpu_count"], 1)
        self.assertEqual(projection["execution"]["resource_counters"]["elapsed_seconds"], projection["execution"]["wall_clock_seconds"])
        errors = []
        bindings = CONTRACT._resource_counter_bindings(projection["execution"], errors)
        self.assertEqual(errors, [])
        self.assertIn("resources.cpu_utilization_percent", bindings)
        self.assertNotIn("resources.energy_joules", bindings)
        self.assertNotIn("resources.thermal_delta_celsius", bindings)
        self.assertNotIn("peak_ram_bytes", projection)
        self.assertFalse(result["release_qualified"])

    def test_blocked_cgroup_attachment_remains_under_timeout(self):
        class BlockedGroup:
            def __init__(self, parent):
                self.path = Path(parent)
                self.initial = {"cpu_microseconds": 0, "read_bytes": 0, "write_bytes": 0}
            child_command = C.Cgroup.child_command
            def populated(self): return False
            def kill(self): pass
            def remove(self): pass
            def sample(self): return {"cpu_microseconds": 0, "peak_memory_bytes": 0, "read_bytes": 0, "write_bytes": 0}
        with tempfile.TemporaryDirectory() as directory:
            os.mkfifo(Path(directory)/"cgroup.procs")
            with mock.patch.object(C, "Cgroup", BlockedGroup):
                started = time.monotonic()
                report = C.collect(["never-executed"], cgroup_parent=directory, timeout=.2)
        self.assertLess(time.monotonic()-started, 1)
        self.assertEqual(report["status"], "timeout")
        self.assertIsNone(report["contract_projection"])

    def test_real_bootstrap_attaches_own_pid_before_workload_exec(self):
        bootstrap_command = C.Cgroup.child_command
        class StubGroup:
            def __init__(self, parent):
                self.path = Path(parent)
                self.initial = {"cpu_microseconds": 0, "read_bytes": 0, "write_bytes": 0}
            def child_command(self, command, capacity_fd):
                # Actually narrow the child's affinity, independently of the
                # collector parent. This stands in for a delegated cpuset.
                inner = bootstrap_command(self, command, capacity_fd)
                wrapper = "import os,sys;os.sched_setaffinity(0,{" + str(min(os.sched_getaffinity(0))) + "});os.execvpe(sys.argv[1],sys.argv[1:],os.environ)"
                return [sys.executable, "-I", "-S", "-c", wrapper, *inner]
            def populated(self): return False
            def kill(self): pass
            def remove(self): pass
            def sample(self): return {"cpu_microseconds": 0, "peak_memory_bytes": 0, "read_bytes": 0, "write_bytes": 0}
        with tempfile.TemporaryDirectory() as directory:
            attached = Path(directory)/"cgroup.procs"
            workload = Path(directory)/"workload-pid"
            code = "import os;open(" + repr(str(workload)) + ",'w').write(str(os.getpid()))"
            with mock.patch.object(C, "Cgroup", StubGroup):
                report = C.collect([sys.executable, "-c", code], cgroup_parent=directory, timeout=2)
            self.assertEqual(report["status"], "completed", report)
            self.assertEqual(attached.read_text(), workload.read_text())
            self.assertGreater(int(attached.read_text()), 0)
            self.assertNotEqual(int(attached.read_text()), os.getpid())
            self.assertEqual(report["observations"]["logical_cpu_count"], 1)
            self.assertIn("after-cgroup-attachment", report["observations"]["cpu_capacity_basis"])
            self.assertNotIn(directory, json.dumps(report))

    def test_cli_refuses_overwrite_and_writes_private_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"receipt.json"
            args = [sys.executable, str(ROOT/"tools/collect_process_resources.py"), "--output", str(output), "--", sys.executable, "-c", "pass"]
            first = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            original = output.read_bytes()
            second = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(second.returncode, 2)
            self.assertEqual(output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
