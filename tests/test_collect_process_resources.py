#!/usr/bin/env python3
"""Counter rejection and real external-workload collector checks."""
import importlib.util
from contextlib import contextmanager
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import analysis_benchmark_contract as CONTRACT
SPEC = importlib.util.spec_from_file_location("collector", ROOT / "tools/collect_process_resources.py")
C = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(C)


class ProcFixture:
    """Synthetic namespace table for binding rejection tests, never evidence."""
    def __init__(self, nested=True):
        self.files, self.reads = {}, []
        self.parent = 1000 if nested else 5
        self.files["/proc/self/status"] = self.status(self.parent, 1, [1000, 5] if nested else [5])

    @staticmethod
    def status(pid, parent, namespace_ids):
        return f"Name:\tignored-private-name\nPid:\t{pid}\nTgid:\t{pid}\nPPid:\t{parent}\nNSpid:\t" + "\t".join(map(str, namespace_ids)) + "\n"

    @staticmethod
    def stat(pid, parent, start=200, rss=17, cpu=13):
        fields = ["0"] * 22
        fields[0], fields[1], fields[11], fields[12] = "S", str(parent), str(cpu), "5"
        fields[19], fields[21] = str(start), str(rss)
        return f"{pid} (ignored ) private name) " + " ".join(fields)

    def child(self, outer=1007, namespace_ids=(1007, 7), parent=None, start=200):
        parent = self.parent if parent is None else parent
        self.files[f"/proc/{outer}/status"] = self.status(outer, parent, namespace_ids)
        self.files[f"/proc/{outer}/stat"] = self.stat(outer, parent, start)
        self.files[f"/proc/{outer}/io"] = "read_bytes: 8192\nwrite_bytes: 16384\n"

    def read(self, path, limit=65536):
        path = str(path)
        self.reads.append(path)
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    @contextmanager
    def patched(self):
        names = {path.split("/")[2] for path in self.files if path.startswith("/proc/")}
        scan = mock.MagicMock()
        scan.__enter__.return_value = (SimpleNamespace(name=name) for name in names)
        with mock.patch.object(C, "read_text", side_effect=self.read), \
                mock.patch.object(C.os, "getpid", return_value=5), \
                mock.patch.object(C.os, "waitid", return_value=None), \
                mock.patch.object(C.os, "scandir", return_value=scan):
            yield


class CollectorTests(unittest.TestCase):
    def assert_runtime_process_exited(self, pid):
        # pidfd_open uses the same PID namespace as Popen/kill, unlike the
        # mounted procfs. Readable pidfds include exited, unreaped zombies.
        try:
            descriptor = os.pidfd_open(pid, 0)
        except ProcessLookupError:
            return
        try:
            poller = select.poll()
            poller.register(descriptor, select.POLLIN)
            ready = poller.poll(1000)
            self.assertTrue(ready and ready[0][1] & select.POLLIN,
                            "same-session descendant must have exited")
        finally:
            os.close(descriptor)

    def test_nested_proc_namespace_maps_owned_child_not_same_numeric_outer_pid(self):
        fixture = ProcFixture()
        fixture.child()
        fixture.child(outer=7, namespace_ids=(7,), parent=1)
        with fixture.patched():
            sampler = C.RootProcSampler(7, deadline=time.monotonic() + 1)
            sample = sampler.sample()
        self.assertEqual(sampler.proc_pid, 1007)
        self.assertEqual(sample["rss_bytes"], 17 * os.sysconf("SC_PAGE_SIZE"))
        self.assertEqual(sample["write_bytes"], 16384)
        self.assertIn("/proc/1007/io", fixture.reads)
        self.assertNotIn("/proc/7/io", fixture.reads)
        self.assertNotIn("private", json.dumps(sample))

    def test_same_namespace_direct_pid_and_children_index_bind(self):
        for nested in (False, True):
            with self.subTest(nested=nested):
                fixture = ProcFixture(nested)
                outer = 1007 if nested else 7
                fixture.child(outer, (1007, 7) if nested else (7,))
                fixture.files["/proc/thread-self/children"] = str(outer)
                with fixture.patched(), mock.patch.object(C.os, "scandir", side_effect=AssertionError("bounded child index should avoid scan")):
                    sampler = C.RootProcSampler(7, deadline=time.monotonic() + 1)
                    self.assertEqual(sampler.sample()["read_bytes"], 8192)

    def test_proc_binding_rejects_wrong_namespace_parent_and_ambiguity(self):
        for mutation in ("namespace", "parent", "ambiguity", "own-namespace", "deadline", "not-owned"):
            with self.subTest(mutation=mutation):
                fixture = ProcFixture()
                fixture.child(namespace_ids=(1007, 8) if mutation == "namespace" else (1007, 7),
                              parent=999 if mutation == "parent" else 1000)
                if mutation == "ambiguity":
                    fixture.child(outer=1008, namespace_ids=(1008, 7))
                if mutation == "own-namespace":
                    fixture.files["/proc/self/status"] = fixture.status(1000, 1, [1000, 6])
                with fixture.patched():
                    if mutation == "not-owned":
                        C.os.waitid.side_effect = ChildProcessError()
                    with self.assertRaises((C.MeasurementError, ChildProcessError)):
                        C.RootProcSampler(7, deadline=time.monotonic() + (-1 if mutation == "deadline" else 1))
                self.assertFalse(any(path.endswith("/io") for path in fixture.reads))

    def test_proc_enumeration_is_bounded_before_materializing_full_table(self):
        for expired in (False, True):
            with self.subTest(expired=expired):
                fixture = ProcFixture()
                consumed = []
                def entries():
                    for index in range(1000000):
                        consumed.append(index)
                        yield SimpleNamespace(name="non-pid-entry")
                with fixture.patched():
                    scanner = C.os.scandir.return_value
                    scanner.__enter__.return_value = entries()
                    expected = "proc_identity_scan_deadline" if expired else "proc_identity_scan_limit"
                    with self.assertRaisesRegex(C.MeasurementError, expected):
                        C.RootProcSampler(7, deadline=0 if expired else float("inf"))
                    scanner.__exit__.assert_called_once()
                self.assertEqual(len(consumed), 1 if expired else 65537)

    def test_proc_sample_revalidates_start_parent_namespace_and_wait_ownership(self):
        for mutation in ("start", "parent", "namespace", "ownership"):
            with self.subTest(mutation=mutation):
                fixture = ProcFixture()
                fixture.child()
                with fixture.patched():
                    sampler = C.RootProcSampler(7, deadline=time.monotonic() + 1)
                    def changing_read(path, limit=65536):
                        result = fixture.read(path, limit)
                        if str(path).endswith("/io"):
                            if mutation == "start":
                                fixture.child(start=201)
                            elif mutation == "parent":
                                fixture.child(parent=999)
                            elif mutation == "namespace":
                                fixture.child(namespace_ids=(1007, 8))
                            else:
                                C.os.waitid.side_effect = ChildProcessError()
                        return result
                    with mock.patch.object(C, "read_text", side_effect=changing_read):
                        with self.assertRaises((C.MeasurementError, ChildProcessError)):
                            sampler.sample()

    def test_unavailable_proc_binding_omits_counters_and_preserves_wait4(self):
        with mock.patch.object(C, "RootProcSampler", side_effect=C.MeasurementError("unverified")):
            report = C.collect([sys.executable, "-c", "sum(i*i for i in range(100000))"], timeout=2)
        observations = report["observations"]
        self.assertEqual(report["status"], "completed", report)
        self.assertEqual(observations["root_procfs_binding"]["status"], "unobserved")
        self.assertTrue(observations["root_procfs_binding"]["binding_unavailable_or_changed"])
        self.assertEqual(observations["root_procfs_samples"], 0)
        self.assertEqual(observations["root_procfs_io_samples"], 0)
        for key in ("root_sampled_peak_rss_bytes", "root_sampled_read_bytes", "root_sampled_write_bytes"):
            self.assertNotIn(key, observations)
        self.assertGreater(observations["wait4_cpu_seconds"], 0)
        self.assertGreater(observations["wait4_peak_rss_bytes"], 0)
        self.assertIsNone(report["contract_projection"])

    def test_actual_child_reports_same_outer_pid_as_bound_proc_record(self):
        # The child independently reports its procfs PID. On hosts with nested
        # PID namespaces this differs from Popen.pid; both must map correctly.
        with tempfile.TemporaryDirectory() as directory:
            identity_path = Path(directory) / "child-identity"
            code = "import os,time;from pathlib import Path;p=Path('/proc/self/stat').read_text().split(' ',1)[0];Path(" + repr(str(identity_path)) + ").write_text(p);time.sleep(5)"
            process = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 2
                while not identity_path.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                outer_pid = int(identity_path.read_text())
                sampler = C.RootProcSampler(process.pid, deadline=deadline)
                self.assertEqual(sampler.proc_pid, outer_pid)
                self.assertGreater(sampler.sample()["rss_bytes"], 0)
                self.assertIsNone(process.poll())
            finally:
                process.kill()
                process.wait(timeout=2)

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
            self.assert_runtime_process_exited(int(pidfile.read_text()))
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
            def kill(self): raise AssertionError("completed empty cgroup must not be killed")
            def remove(self): pass
            def sample(self): return {"cpu_microseconds": 123, "peak_memory_bytes": 4096, "read_bytes": 17, "write_bytes": 29}
        with mock.patch.object(C, "Cgroup", FakeGroup), mock.patch.object(C.os, "killpg", side_effect=AssertionError("completed reaped root must not be signaled")):
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

    def test_reaped_root_with_pending_descendants_kills_only_owned_cgroup(self):
        groups = []
        class PendingGroup:
            def __init__(self, parent):
                self.initial = {"cpu_microseconds": 0, "read_bytes": 0, "write_bytes": 0}
                self.pending, self.kill_count = True, 0
                groups.append(self)
            def child_command(self, command, capacity_fd):
                bootstrap = "import os,sys;f=int(sys.argv[1]);os.write(f,b'1\\n');os.close(f);os.execvpe(sys.argv[2],sys.argv[2:],os.environ)"
                return [sys.executable, "-I", "-S", "-c", bootstrap, str(capacity_fd), *command]
            def populated(self): return self.pending
            def kill(self): self.kill_count += 1; self.pending = False
            def remove(self):
                if self.pending: raise OSError("still populated")
            def sample(self): return {"cpu_microseconds": 123, "peak_memory_bytes": 4096, "read_bytes": 17, "write_bytes": 29}
        with mock.patch.object(C, "Cgroup", PendingGroup), mock.patch.object(C.os, "killpg", side_effect=AssertionError("reaped leader's PGID is stale")):
            result = C.collect([sys.executable, "-c", "pass"], cgroup_parent="fake-kernel", timeout=.3)
        self.assertEqual(result["status"], "timeout", result)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(groups[0].kill_count, 1)
        self.assertEqual(result["errors"], [])
        self.assertIsNone(result["contract_projection"])

    def test_population_error_after_reap_never_signals_stale_group(self):
        class BrokenPopulation:
            def __init__(self, parent):
                self.initial = {"cpu_microseconds": 0, "read_bytes": 0, "write_bytes": 0}
            def child_command(self, command, capacity_fd): return command
            def populated(self): raise OSError("population inaccessible")
            def kill(self): raise AssertionError("unknown population does not authorize kill")
            def remove(self): pass
        with mock.patch.object(C, "Cgroup", BrokenPopulation), mock.patch.object(C.os, "killpg", side_effect=AssertionError("reaped leader's PGID is stale")):
            started = time.monotonic()
            result = C.collect([sys.executable, "-c", "pass"], cgroup_parent="fake-kernel", timeout=2)
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(result["status"], "measurement_failed")
        self.assertIn("process_cleanup_failed", result["errors"])
        self.assertFalse(result["process_tree_accounting_complete"])
        self.assertIsNone(result["contract_projection"])

    def test_fallback_descendants_are_signaled_before_root_is_reaped(self):
        original_wait4, original_killpg = os.wait4, os.killpg
        reaped, signaled = set(), []
        def observed_wait4(pid, flags):
            result = original_wait4(pid, flags)
            if result[0]: reaped.add(result[0])
            return result
        def owned_killpg(pid, sig):
            self.assertNotIn(pid, reaped, "collector must not signal a reaped PGID")
            observation = os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            self.assertIsNotNone(observation)
            self.assertEqual(observation.si_pid, pid)
            signaled.append(pid)
            original_killpg(pid, sig)
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory)/"child-pid"
            code = "import subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);open(" + repr(str(pidfile)) + ",'w').write(str(p.pid))"
            with mock.patch.object(C.os, "wait4", side_effect=observed_wait4), mock.patch.object(C.os, "killpg", side_effect=owned_killpg):
                report = C.collect([sys.executable, "-c", code], timeout=2, interval=.02)
            self.assertEqual(report["status"], "completed", report)
            self.assertTrue(signaled)
            self.assertEqual(set(signaled), reaped)
            self.assert_runtime_process_exited(int(pidfile.read_text()))

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
