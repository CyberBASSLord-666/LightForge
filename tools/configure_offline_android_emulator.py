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
# First-boot radio/service callbacks can outlast a 30-second observation window.
# This fixture-only budget does not change any Android instrumentation deadline.
STATE_TIMEOUT_SECONDS = 120
COMMAND_TIMEOUT_SECONDS = 10
POLL_SECONDS = 1
SERIAL_PATTERN = re.compile(r"emulator-[0-9]+", re.ASCII)


class SetupError(RuntimeError):
    pass


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def output_summary(stdout, stderr):
    """Retain fixed diagnostic tokens, never network names or raw service dumps."""
    combined = stdout + "\n" + stderr
    signals = {
        "permission-denied": r"permission denied|permission denial|not allowed|requires .*permission",
        "security-exception": r"securityexception|security exception",
        "unknown-command": r"unknown command|unrecognized command|invalid command",
        "service-unavailable": r"can't find service|cannot find service|service .*not found|no service published",
        "exception": r"\bexception\b|[A-Za-z]+Exception\b",
        "error": r"(?m)^\s*(?:error|failed)\b",
    }
    return {
        "stdout_bytes": len(stdout.encode("utf-8")),
        "stderr_bytes": len(stderr.encode("utf-8")),
        "stdout_lines": len(stdout.splitlines()),
        "stderr_lines": len(stderr.splitlines()),
        "signals": sorted(name for name, pattern in signals.items() if re.search(pattern, combined, re.IGNORECASE)),
    }


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
        began = self.monotonic()
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
        entry["elapsed_ms"] = round((self.monotonic() - began) * 1000)
        entry["output"] = output_summary(result.stdout, result.stderr)
        if result.returncode != 0:
            entry["status"] = "failed"
            if allow_unavailable:
                return None
            raise SetupError("adb command failed: " + " ".join(args))
        # Some Android shell wrappers print failures but exit successfully.
        # Query dumps contain historical errors, so classify those for diagnosis
        # without mistaking them for the current shell command's result.
        mutation = (
            args[:4] == ("shell", "cmd", "connectivity", "airplane-mode") and len(args) == 5
            or args[:4] == ("shell", "cmd", "wifi", "set-wifi-enabled")
            or args[:4] == ("shell", "cmd", "phone", "data")
            or args == ("shell", "settings", "put", "global", "mobile_data", "0")
        )
        if mutation:
            if result.stdout.strip() or result.stderr.strip():
                entry["status"] = "reported-error"
                raise SetupError("Android service returned unexpected mutation output: " + " ".join(args))
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
                    self.receipt["mobile_data_setting_key"] = "mobile_data"
                    return
            self.pause(deadline)

    def observe(self, deadline):
        airplane = self.command("shell", "cmd", "connectivity", "airplane-mode", deadline=deadline)
        airplane_setting = self.command("shell", "settings", "get", "global", "airplane_mode_on", deadline=deadline)
        wifi = self.command("shell", "cmd", "wifi", "status", deadline=deadline)
        wifi_setting = self.command("shell", "settings", "get", "global", "wifi_on", deadline=deadline)
        mobile_data = self.command("shell", "settings", "get", "global", "mobile_data", deadline=deadline)
        connectivity = self.command("shell", "dumpsys", "connectivity", deadline=deadline)
        default_networks = re.findall(r"^[ \t]*Active default network:[ \t]*(\S+)[ \t]*$", connectivity, re.MULTILINE)
        wifi_states = re.findall(r"^[ \t]*(?:Wifi|Wi-Fi) is (enabled|disabled)[ \t]*$", wifi, re.MULTILINE)
        self.receipt["state_parse"] = {
            "wifi_status_lines": len(wifi_states),
            "default_network_lines": len(default_networks),
            "numeric_default_networks": sum(bool(re.fullmatch(r"[0-9]+", value)) for value in default_networks),
        }
        observed = {
            "airplane_mode": airplane if airplane in {"enabled", "disabled"} else "unknown",
            "airplane_mode_setting": airplane_setting if airplane_setting in {"0", "1"} else "unknown",
            "wifi": wifi_states[0] if len(wifi_states) == 1 else "unverified",
            "wifi_setting": wifi_setting if wifi_setting in {"0", "1", "2", "3"} else "unknown",
            "mobile_data_setting": mobile_data if mobile_data in {"0", "1"} else "unknown",
            "default_network": "none" if default_networks == ["none"] else (
                "present" if len(default_networks) == 1 and re.fullmatch(r"[0-9]+", default_networks[0]) else "unverified"
            ),
        }
        self.receipt["observed_state"] = observed
        history = self.receipt.setdefault("state_history", [])
        history.append({"at": utc_now(), **observed})
        del history[:-16]
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
        # Airplane mode can reject Wi-Fi toggles or preserve an enabled Wi-Fi
        # override. Settle the user radio settings before enabling it. A retry
        # of this disposable fixture may start with airplane mode already on.
        airplane = self.command("shell", "cmd", "connectivity", "airplane-mode", deadline=deadline)
        if airplane not in {"enabled", "disabled"}:
            raise SetupError("Cannot read the emulator airplane-mode state")
        if airplane == "enabled":
            self.command("shell", "cmd", "connectivity", "airplane-mode", "disable", deadline=deadline)
        phase = "disable-radios"
        while True:
            self.receipt["setup_phase"] = phase
            state = self.receipt.get("observed_state", {})
            if phase == "disable-radios":
                # The default Phone can appear after sys.boot_completed.
                # Reapply only states still enabled/unknown, within this budget.
                if state.get("wifi") != "disabled" or state.get("wifi_setting") != "0":
                    self.command("shell", "cmd", "wifi", "set-wifi-enabled", "disabled", deadline=deadline)
                if state.get("mobile_data_setting") != "0":
                    self.command("shell", "cmd", "phone", "data", "disable", deadline=deadline)
            verified = self.observe(deadline)
            state = self.receipt["observed_state"]
            if phase == "disable-radios" and state["mobile_data_setting"] == "1":
                # Android 15 TelephonyShellCommand discards the boolean from
                # PhoneInterfaceManager.disableDataConnectivity(): a missing
                # default-subscription Phone silently leaves this preference
                # enabled. Only on our verified single-SIM disposable emulator,
                # set the desired preference explicitly after observing that
                # no-op. This is not proof of disconnection: the next observations
                # must still confirm every radio/setting and no default network.
                self.command("shell", "settings", "put", "global", "mobile_data", "0", deadline=deadline)
                self.receipt["mobile_data_preference_fallback"] = True
            radios_disabled = state["wifi"] == "disabled" and state["wifi_setting"] == "0" and state["mobile_data_setting"] == "0"
            if phase == "disable-radios" and radios_disabled:
                self.command("shell", "cmd", "connectivity", "airplane-mode", "enable", deadline=deadline)
                phase = "verify-offline"
                continue
            if phase == "verify-offline" and verified:
                return
            if phase == "verify-offline":
                if not radios_disabled:
                    self.command("shell", "cmd", "connectivity", "airplane-mode", "disable", deadline=deadline)
                    phase = "disable-radios"
                elif state["airplane_mode"] != "enabled" or state["airplane_mode_setting"] != "1":
                    self.command("shell", "cmd", "connectivity", "airplane-mode", "enable", deadline=deadline)
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
