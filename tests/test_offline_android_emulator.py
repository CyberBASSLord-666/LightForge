"""Disposable-target safety and observed offline-state regressions."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("offline_emulator", ROOT / "tools/configure_offline_android_emulator.py")
offline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(offline)


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeAdb:
    def __init__(self):
        self.calls = []
        self.overrides = {}
        self.responses = {
            ("get-state",): "device\n",
            ("shell", "getprop", "ro.kernel.qemu"): "1\n",
            ("shell", "getprop", "sys.boot_completed"): "1\n",
            ("shell", "getprop", "persist.radio.multisim.config"): "\n",
            ("shell", "cmd", "connectivity", "airplane-mode", "enable"): "",
            ("shell", "svc", "wifi", "disable"): "",
            ("shell", "svc", "data", "disable"): "",
            ("shell", "cmd", "connectivity", "airplane-mode"): "enabled\n",
            ("shell", "settings", "get", "global", "airplane_mode_on"): "1\n",
            ("shell", "cmd", "wifi", "status"): "Wifi is disabled\nWifi scanning is always available\n",
            ("shell", "settings", "get", "global", "wifi_on"): "0\n",
            ("shell", "settings", "get", "global", "mobile_data"): "0\n",
            ("shell", "dumpsys", "connectivity"): "Network factories:\nActive default network: none\nCurrent Networks:\n",
        }

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        if command[:3] != ["/sdk/adb", "-s", "emulator-5554"]:
            raise AssertionError("adb did not explicitly select the fixture emulator")
        if not 0 < kwargs["timeout"] <= offline.COMMAND_TIMEOUT_SECONDS:
            raise AssertionError("adb command timeout must be bounded")
        args = tuple(command[3:])
        if args not in self.responses:
            raise AssertionError("unexpected adb command " + repr(args))
        value = self.overrides.get(args, self.responses[args])
        if isinstance(value, list):
            value = value.pop(0)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, tuple):
            code, stdout = value
        else:
            code, stdout = 0, value
        return subprocess.CompletedProcess(command, code, stdout, "")

    def mutations(self):
        return [call for call in self.calls if call[-1] in {"enable", "disable"}]


class OfflineEmulatorTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.adb = FakeAdb()
        self.receipt = {"commands": []}
        self.fixture = offline.OfflineEmulator(
            "/sdk/adb", "emulator-5554", self.receipt,
            run=self.adb, monotonic=self.clock.monotonic, sleep=self.clock.sleep,
        )

    def test_verified_emulator_requires_observed_offline_state(self):
        self.fixture.configure()
        self.assertTrue(self.receipt["emulator_verified"])
        self.assertEqual(self.receipt["observed_state"]["default_network"], "none")
        self.assertEqual(len(self.adb.mutations()), 3)
        self.assertTrue(all(call[1:3] == ["-s", "emulator-5554"] for call in self.adb.calls))

    def test_physical_network_and_ambiguous_targets_never_reach_adb(self):
        for serial in ["", "0123456789ABCDEF", "192.0.2.10:5555", "-d", "emulator-5554 extra", "emulator-５５５４"]:
            with self.subTest(serial=serial), self.assertRaises(offline.SetupError):
                offline.OfflineEmulator("/sdk/adb", serial, self.receipt, run=self.adb)
        self.assertEqual(self.adb.calls, [])

    def test_qemu_identity_is_required_before_mutation(self):
        for identity in ["0", "", "unknown"]:
            with self.subTest(identity=identity):
                self.adb.overrides[("shell", "getprop", "ro.kernel.qemu")] = identity
                with self.assertRaisesRegex(offline.SetupError, "QEMU"):
                    self.fixture.configure()
                self.assertEqual(self.adb.mutations(), [])

    def test_boot_wait_retries_an_unavailable_emulator_without_mutation(self):
        self.adb.overrides[("get-state",)] = [(1, ""), "device"]
        self.fixture.configure()
        self.assertGreater(self.clock.now, 0)
        self.assertEqual(self.receipt["commands"][0]["status"], "failed")
        self.assertTrue(self.receipt["emulator_verified"])

    def test_multisim_or_unknown_subscription_configuration_is_rejected_before_mutation(self):
        for configuration in ["dsds", "dsda", "tsts", "unknown"]:
            with self.subTest(configuration=configuration):
                self.adb.overrides[("shell", "getprop", "persist.radio.multisim.config")] = configuration
                with self.assertRaisesRegex(offline.SetupError, "single-SIM"):
                    self.fixture.configure()
                self.assertEqual(self.adb.mutations(), [])

    def test_boot_deadline_fails_without_mutation(self):
        self.adb.overrides[("shell", "getprop", "sys.boot_completed")] = ""
        with mock.patch.object(offline, "BOOT_TIMEOUT_SECONDS", 2), self.assertRaisesRegex(offline.SetupError, "deadline"):
            self.fixture.configure()
        self.assertEqual(self.adb.mutations(), [])
        self.assertEqual(self.clock.now, 2)

    def test_failed_mutation_stops_and_cannot_report_verified_state(self):
        for command in [
            ("shell", "cmd", "connectivity", "airplane-mode", "enable"),
            ("shell", "svc", "wifi", "disable"),
            ("shell", "svc", "data", "disable"),
        ]:
            with self.subTest(command=command):
                self.setUp()
                self.adb.overrides[command] = (1, "")
                with self.assertRaisesRegex(offline.SetupError, "command failed"):
                    self.fixture.configure()
                self.assertEqual(tuple(self.adb.calls[-1][3:]), command)
                self.assertNotIn("observed_state", self.receipt)

    def test_settings_success_does_not_substitute_for_observed_state(self):
        failures = [
            (("shell", "cmd", "connectivity", "airplane-mode"), "disabled"),
            (("shell", "settings", "get", "global", "airplane_mode_on"), "0"),
            (("shell", "cmd", "wifi", "status"), "Wifi is enabled\nWifiInfo: private-ssid"),
            (("shell", "cmd", "wifi", "status"), "unsupported"),
            (("shell", "settings", "get", "global", "wifi_on"), "1"),
            (("shell", "settings", "get", "global", "wifi_on"), "3"),
            (("shell", "settings", "get", "global", "wifi_on"), "null"),
            (("shell", "settings", "get", "global", "mobile_data"), "1"),
            (("shell", "settings", "get", "global", "mobile_data"), "null"),
            (("shell", "dumpsys", "connectivity"), "Active default network: 100\n"),
            (("shell", "dumpsys", "connectivity"), "unsupported\n"),
            (("shell", "dumpsys", "connectivity"), "Active default network: none\nActive default network: 100\n"),
        ]
        for command, response in failures:
            with self.subTest(command=command, response=response):
                self.setUp()
                self.adb.overrides[command] = response
                with mock.patch.object(offline, "STATE_TIMEOUT_SECONDS", 2), self.assertRaisesRegex(offline.SetupError, "deadline"):
                    self.fixture.configure()
                self.assertLessEqual(self.clock.now, 2)
                self.assertNotIn("private-ssid", json.dumps(self.receipt))

    def test_waits_for_network_disconnection_after_airplane_setting_changes(self):
        self.adb.overrides[("shell", "dumpsys", "connectivity")] = [
            "Active default network: 100\n", "Active default network: none\n",
        ]
        self.fixture.configure()
        self.assertGreater(self.clock.now, 0)
        self.assertEqual(self.receipt["observed_state"]["default_network"], "none")

    def test_state_read_failure_is_fatal(self):
        self.adb.overrides[("shell", "cmd", "wifi", "status")] = (1, "Wifi is disabled")
        with self.assertRaisesRegex(offline.SetupError, "command failed"):
            self.fixture.configure()

    def test_hung_command_is_bounded_and_retained(self):
        self.adb.overrides[("shell", "svc", "data", "disable")] = subprocess.TimeoutExpired("adb", 10)
        with self.assertRaisesRegex(offline.SetupError, "timed out"):
            self.fixture.configure()
        self.assertEqual(self.receipt["commands"][-1]["status"], "timeout")

    def test_missing_adb_is_reported_without_mutation(self):
        self.adb.overrides[("get-state",)] = FileNotFoundError("private host path")
        with self.assertRaisesRegex(offline.SetupError, "Cannot execute adb"):
            self.fixture.configure()
        self.assertEqual(self.adb.mutations(), [])
        self.assertNotIn("private host path", json.dumps(self.receipt))

    def run_cli(self, output, *extra):
        return offline.main([
            "--adb", "/sdk/adb", "--serial", "emulator-5554",
            "--head-sha", "a" * 40, "--run-id", "1234", "--run-attempt", "2",
            "--evidence-session", "b" * 64, "--output", str(output), *extra,
        ])

    def test_cli_success_binds_observed_state_to_source_and_session(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "setup.json"
            with mock.patch.object(offline.subprocess, "run", self.adb):
                self.assertEqual(self.run_cli(output), 0)
            receipt = json.loads(output.read_text())
        self.assertEqual(receipt["status"], "verified-offline")
        self.assertEqual(receipt["head_sha"], "a" * 40)
        self.assertEqual(receipt["evidence_session"], "b" * 64)
        self.assertEqual(receipt["run_id"], "1234")
        self.assertEqual(receipt["run_attempt"], "2")
        self.assertRegex(receipt["helper_sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(receipt["diagnostic_only"])

    def test_cli_failure_replaces_stale_success_and_retains_command_failure(self):
        self.adb.overrides[("shell", "svc", "data", "disable")] = (1, "")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "setup.json"
            output.write_text('{"status":"verified-offline"}')
            with mock.patch.object(offline.subprocess, "run", self.adb):
                self.assertEqual(self.run_cli(output), 1)
            receipt = json.loads(output.read_text())
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["commands"][-1]["status"], "failed")

    def test_invalid_source_binding_fails_before_adb(self):
        for option, value in [("--head-sha", "main"), ("--run-id", "0"), ("--run-attempt", "-1"), ("--evidence-session", "old")]:
            with self.subTest(option=option), tempfile.TemporaryDirectory() as directory:
                with mock.patch.object(offline.subprocess, "run", self.adb):
                    self.assertEqual(self.run_cli(Path(directory) / "setup.json", option, value), 1)
        self.assertEqual(self.adb.calls, [])


if __name__ == "__main__":
    unittest.main()
