#!/usr/bin/env python3
"""Configure a disposable CI emulator offline, retaining setup diagnostics.

This does not validate an APK or replace Android instrumentation evidence. All
adb calls select an explicit emulator serial, and mutations additionally require
the emulator's ro.kernel.qemu property. No physical device is a supported target.
"""

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time


BOOT_TIMEOUT_SECONDS = 180
STATE_TIMEOUT_SECONDS = 30
COMMAND_TIMEOUT_SECONDS = 10
POLL_SECONDS = 1
SERIAL_PATTERN = re.compile(r"emulator-[0-9]+", re.ASCII)


class SetupError(RuntimeError):
    pass


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class OfflineEmulator:
    def __init__(self, adb, serial, receipt, *, run=None, monotonic=None, sleep=None):
        # This check must precede even read-only adb commands. An environment's
        # implicit/default adb device selection is never used.
        if not SERIAL_PATTERN.fullmatch(serial):
            raise SetupError("Target must be an explicit emulator-N serial")
        self.adb = adb
        self.serial = serial
        self.receipt = receipt
        self.run = run or subprocess.run
        self.monotonic = monotonic or time.monotonic
        self.sleep = sleep or time.sleep

    def command(self, *args, deadline, allow_unavailable=False):
        remaining = deadline - self.monotonic()
        if remaining <= 0:
            raise SetupError("Emulator setup deadline expired")
        entry = {"arguments": list(args)}
        self.receipt["commands"].append(entry)
        try:
            result = self.run(
                [str(self.adb), "-s", self.serial, *args],
                capture_output=True, text=True,
                timeout=min(COMMAND_TIMEOUT_SECONDS, remaining), check=False,
            )
        except subprocess.TimeoutExpired as error:
            entry["status"] = "timeout"
            raise SetupError("adb command timed out: " + " ".join(args)) from error
        except OSError as error:
            entry["status"] = "unavailable"
            raise SetupError("Cannot execute adb") from error
        entry["returncode"] = result.returncode
        if result.returncode != 0:
            entry["status"] = "failed"
            if allow_unavailable:
                return None
            raise SetupError("adb command failed: " + " ".join(args))
        entry["status"] = "completed"
        # Full service output can contain network identifiers. The receipt keeps
        # only the narrowly parsed state, never raw dumpsys/settings output.
        return result.stdout.strip()

    def pause(self, deadline):
        remaining = deadline - self.monotonic()
        if remaining <= 0:
            raise SetupError("Emulator setup deadline expired")
        self.sleep(min(POLL_SECONDS, remaining))

    def wait_for_emulator(self):
        deadline = self.monotonic() + BOOT_TIMEOUT_SECONDS
        while True:
            state = self.command("get-state", deadline=deadline, allow_unavailable=True)
            if state == "device":
                if self.command("shell", "getprop", "ro.kernel.qemu", deadline=deadline) != "1":
                    raise SetupError("Target did not identify itself as a QEMU emulator")
                if self.command("shell", "getprop", "sys.boot_completed", deadline=deadline) == "1":
                    # svc data operates on the default subscription. The base
                    # mobile_data setting is authoritative only for this
                    # fixture's default single-SIM configuration; refuse an
                    # image configured for multiple subscriptions.
                    if self.command("shell", "getprop", "persist.radio.multisim.config", deadline=deadline) != "":
                        raise SetupError("Only the default single-SIM emulator configuration is supported")
                    self.receipt["emulator_verified"] = True
                    self.receipt["subscription_configuration"] = "default-single-sim"
                    return
            self.pause(deadline)

    def observe(self, deadline):
        airplane = self.command("shell", "cmd", "connectivity", "airplane-mode", deadline=deadline)
        airplane_setting = self.command("shell", "settings", "get", "global", "airplane_mode_on", deadline=deadline)
        wifi = self.command("shell", "cmd", "wifi", "status", deadline=deadline)
        wifi_setting = self.command("shell", "settings", "get", "global", "wifi_on", deadline=deadline)
        mobile_data = self.command("shell", "settings", "get", "global", "mobile_data", deadline=deadline)
        connectivity = self.command("shell", "dumpsys", "connectivity", deadline=deadline)
        default_networks = re.findall(r"^\s*Active default network:\s*(\S+)\s*$", connectivity, re.MULTILINE)
        observed = {
            "airplane_mode": airplane if airplane in {"enabled", "disabled"} else "unknown",
            "airplane_mode_setting": airplane_setting if airplane_setting in {"0", "1"} else "unknown",
            "wifi": "disabled" if wifi.splitlines()[:1] == ["Wifi is disabled"] else "unverified",
            "wifi_setting": wifi_setting if wifi_setting in {"0", "1", "2", "3"} else "unknown",
            "mobile_data_setting": mobile_data if mobile_data in {"0", "1"} else "unknown",
            "default_network": "none" if default_networks == ["none"] else "present-or-unverified",
        }
        self.receipt["observed_state"] = observed
        return observed == {
            "airplane_mode": "enabled",
            "airplane_mode_setting": "1",
            "wifi": "disabled",
            "wifi_setting": "0",
            "mobile_data_setting": "0",
            "default_network": "none",
        }

    def configure(self):
        self.wait_for_emulator()
        deadline = self.monotonic() + STATE_TIMEOUT_SECONDS
        self.command("shell", "cmd", "connectivity", "airplane-mode", "enable", deadline=deadline)
        self.command("shell", "svc", "wifi", "disable", deadline=deadline)
        self.command("shell", "svc", "data", "disable", deadline=deadline)
        while not self.observe(deadline):
            self.pause(deadline)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--adb", required=True)
    result.add_argument("--serial", required=True)
    result.add_argument("--head-sha", required=True)
    result.add_argument("--run-id", required=True)
    result.add_argument("--run-attempt", required=True)
    result.add_argument("--evidence-session", required=True)
    result.add_argument("--output", required=True, type=Path)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    receipt = {
        "schema": "lightforge-offline-emulator-setup-v1",
        "diagnostic_only": True,
        "status": "failed",
        "started_at": utc_now(),
        "head_sha": args.head_sha,
        "run_id": args.run_id,
        "run_attempt": args.run_attempt,
        "evidence_session": args.evidence_session,
        "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "serial": args.serial,
        "emulator_verified": False,
        "commands": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Invalidate a stale successful record before attempting any setup command.
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    try:
        if not re.fullmatch(r"[0-9a-f]{40}", args.head_sha, re.ASCII):
            raise SetupError("A complete source commit is required")
        if not all(re.fullmatch(r"[1-9][0-9]*", value, re.ASCII) for value in (args.run_id, args.run_attempt)):
            raise SetupError("Positive CI run and attempt identifiers are required")
        if not re.fullmatch(r"[0-9a-f]{64}", args.evidence_session, re.ASCII):
            raise SetupError("A complete Android evidence session is required")
        OfflineEmulator(args.adb, args.serial, receipt).configure()
        receipt["status"] = "verified-offline"
    except SetupError as error:
        receipt["error"] = str(error)
    finally:
        receipt["completed_at"] = utc_now()
        args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print("Disposable emulator connectivity: " + receipt["status"])
    return 0 if receipt["status"] == "verified-offline" else 1


if __name__ == "__main__":
    sys.exit(main())
