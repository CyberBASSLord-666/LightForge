import base64
import copy
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import sys
import tempfile
from types import MappingProxyType
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import physical_validation_gate as gate


NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
RELEASE = {"name": "2.2.5", "code": 20205}
SOURCE = {"commit": "a" * 40, "tree_sha": "b" * 40}
CANDIDATE = {
    "workflow": gate.VERIFY_WORKFLOW,
    "run_id": 501,
    "run_attempt": 2,
    "evidence_session": "c" * 64,
    "artifact_id": 502,
    "artifact_digest": "d" * 64,
    "identity_sha256": "e" * 64,
    "apk_sha256": "f" * 64,
}
ANDROID_EVIDENCE = {
    "workflow": gate.VERIFY_WORKFLOW,
    "run_id": 501,
    "run_attempt": 2,
    "evidence_session": "1" * 64,
    "artifact_id": 503,
    "artifact_digest": "2" * 64,
    "manifest_sha256": "3" * 64,
    "receipt_sha256": {
        "android-background-verification.json": "4" * 64,
        "android-diagnostics-verification.json": "5" * 64,
    },
}
PROFILE = {
    "source_path": gate.VEHICLE_PROFILE_SOURCE_PATH,
    "source_sha256": "6" * 64,
    "id": "model3-highland-2025-na",
    "version": "1.5.0",
}
PACKAGE = "com.cyberbasslord.lightforge"


def authority():
    key = bytes(range(32))
    return MappingProxyType(
        {
            "physical-lab-a": {
                "protocol": gate.PHYSICAL_VALIDATION_PROTOCOL,
                "algorithm": gate.PHYSICAL_VALIDATION_ALGORITHM,
                "verification_key_base64": base64.b64encode(key).decode("ascii"),
                "verification_key_sha256": hashlib.sha256(key).hexdigest(),
            }
        }
    )


def attestation():
    key_sha256 = authority()["physical-lab-a"]["verification_key_sha256"]
    value = {
        "schema_version": gate.PHYSICAL_VALIDATION_SCHEMA_VERSION,
        "protocol": gate.PHYSICAL_VALIDATION_PROTOCOL,
        "authority_id": "physical-lab-a",
        "algorithm": gate.PHYSICAL_VALIDATION_ALGORITHM,
        "verification_key_sha256": key_sha256,
        "release": copy.deepcopy(RELEASE),
        "source": copy.deepcopy(SOURCE),
        "candidate": copy.deepcopy(CANDIDATE),
        "android_evidence": copy.deepcopy(ANDROID_EVIDENCE),
        "private_evidence": {
            "manifest_sha256": "7" * 64,
            "reference": "physical-lab-record-001",
        },
        "installed_apk": {
            "apk_sha256": CANDIDATE["apk_sha256"],
            "package_name": PACKAGE,
            "version_name": RELEASE["name"],
            "version_code": RELEASE["code"],
        },
        "device": {
            "fingerprint": "google/panther/panther:15/AP4A.250205.002/1234567:userdebug/test-keys",
            "manufacturer": "Google",
            "model": "Pixel 7",
            "api_level": 35,
            "abi": "arm64-v8a",
            "package_name": PACKAGE,
        },
        "vehicle": {
            "vehicle_id": "fleet-opaque-01",
            "firmware_version": "2026.8.4",
            "profile": copy.deepcopy(PROFILE),
        },
        "measurements": {
            "android": {
                "installation_passed": True,
                "launch_passed": True,
                "background_analysis_passed": True,
                "resume_recovery_passed": True,
                "diagnostics_passed": True,
            },
            "vehicle": {
                "tesla_playback_passed": True,
                "actuator_feasibility_passed": True,
                "safety_incident_count": 0,
                "uncommanded_event_count": 0,
            },
            "timing": {
                "samples": gate.MINIMUM_PHYSICAL_TIMING_SAMPLES,
                "percentile_method": gate.PHYSICAL_VALIDATION_PERCENTILE_METHOD,
                "command_timestamp_error_ms": {
                    "p50": 1,
                    "p90": 2,
                    "p95": 3,
                    "p99": 4,
                    "max": 5,
                },
                "perceptual_response_error_ms": {
                    "p50": 2,
                    "p90": 3,
                    "p95": 4,
                    "p99": 5,
                    "max": 6,
                },
                "per_class": {
                    "lighting": {
                        "samples": gate.MINIMUM_PHYSICAL_CLASS_TIMING_SAMPLES["lighting"],
                        "command_timestamp_error_ms": {"p50": 1, "p90": 2, "p95": 3, "p99": 4, "max": 5},
                        "perceptual_response_error_ms": {"p50": 2, "p90": 3, "p95": 4, "p99": 5, "max": 6},
                    },
                    "mechanical": {
                        "samples": gate.MINIMUM_PHYSICAL_CLASS_TIMING_SAMPLES["mechanical"],
                        "command_timestamp_error_ms": {"p50": 1, "p90": 2, "p95": 3, "p99": 4, "max": 5},
                        "perceptual_response_error_ms": {"p50": 2, "p90": 3, "p95": 4, "p99": 5, "max": 6},
                    },
                },
            },
            "coverage": {
                "lighting": {"eligible_events": 100, "realized_events": 95},
                "mechanical": {"eligible_events": 100, "realized_events": 90},
            },
        },
        "review": {
            "reviewer_id": "physical-lab-a",
            "observed_at": "2026-09-11T10:00:00Z",
            "issued_at": "2026-09-11T11:00:00Z",
            "expires_at": "2026-10-01T11:00:00Z",
            "verdict": "pass",
        },
        "signed_payload_sha256": None,
        "signature_base64": base64.b64encode(bytes(64)).decode("ascii"),
    }
    value["signed_payload_sha256"] = hashlib.sha256(
        gate.canonical_json(gate.signed_payload(value)).encode("utf-8")
    ).hexdigest()
    return value


def verify(value):
    return gate.verify_physical_validation_attestation(
        value,
        release=RELEASE,
        source=SOURCE,
        candidate=CANDIDATE,
        android_evidence=ANDROID_EVIDENCE,
        expected_package_name=PACKAGE,
        expected_vehicle_profile=PROFILE,
        now=NOW,
    )


def reseal(value):
    value["signed_payload_sha256"] = hashlib.sha256(
        gate.canonical_json(gate.signed_payload(value)).encode("utf-8")
    ).hexdigest()
    return value


class PhysicalValidationGateTest(unittest.TestCase):
    def test_registry_is_deliberately_unconfigured_and_fails_closed(self):
        self.assertEqual(dict(gate.PHYSICAL_VALIDATION_AUTHORITY_KEYS), {})
        with self.assertRaisesRegex(ValueError, "unconfigured"):
            verify(attestation())

    def test_verified_attestation_binds_the_complete_sealed_envelope(self):
        value = attestation()
        with patch.object(gate, "PHYSICAL_VALIDATION_AUTHORITY_KEYS", authority()), \
                patch.object(gate, "_verify_ed25519_signature", return_value=True) as verifier:
            receipt = verify(value)
        self.assertEqual(receipt["status"], "verified")
        self.assertEqual(receipt["candidate_identity_sha256"], CANDIDATE["identity_sha256"])
        self.assertEqual(
            receipt["android_evidence_manifest_sha256"],
            ANDROID_EVIDENCE["manifest_sha256"],
        )
        self.assertNotIn("fingerprint", receipt)
        self.assertNotIn("device_binding_sha256", receipt)
        self.assertNotIn("device", receipt)
        self.assertNotIn("private_evidence", receipt)
        self.assertNotIn("reference", receipt)
        self.assertNotIn("signed_payload_sha256", receipt)
        self.assertNotIn("signature_base64", receipt)
        self.assertEqual(
            receipt["physical_evidence_manifest_sha256"],
            value["private_evidence"]["manifest_sha256"],
        )
        self.assertEqual(verifier.call_count, 1)

    def test_candidate_android_and_profile_binding_cannot_drift(self):
        mutations = (
            ("candidate", lambda value: value["candidate"].update(apk_sha256="0" * 64), "candidate differs"),
            (
                "android",
                lambda value: value["android_evidence"]["receipt_sha256"].update(
                    {"android-background-verification.json": "0" * 64}
                ),
                "Android evidence differs",
            ),
            (
                "profile",
                lambda value: value["vehicle"]["profile"].update(source_sha256="0" * 64),
                "profile differs",
            ),
            (
                "package",
                lambda value: value["device"].update(package_name="com.example.wrong"),
                "package",
            ),
        )
        for label, mutate, message in mutations:
            with self.subTest(label=label):
                value = attestation()
                mutate(value)
                with patch.object(gate, "PHYSICAL_VALIDATION_AUTHORITY_KEYS", authority()), \
                        patch.object(gate, "_verify_ed25519_signature", return_value=True):
                    with self.assertRaisesRegex(ValueError, message):
                        verify(value)

    def test_measurements_and_review_are_strict_fail_closed_contracts(self):
        mutations = (
            (
                "incident",
                lambda value: value["measurements"]["vehicle"].update(safety_incident_count=1),
                "must be explicitly zero",
            ),
            (
                "uncommanded",
                lambda value: value["measurements"]["vehicle"].update(uncommanded_event_count=1),
                "must be explicitly zero",
            ),
            (
                "percentile",
                lambda value: value["measurements"]["timing"]["perceptual_response_error_ms"].update(
                    p95=1
                ),
                "percentiles must be ordered",
            ),
            (
                "expired",
                lambda value: value["review"].update(expires_at="2026-09-11T11:30:00Z"),
                "has expired",
            ),
            (
                "too-long",
                lambda value: value["review"].update(expires_at="2026-10-12T11:00:00Z"),
                "no more than 30 days",
            ),
        )
        for label, mutate, message in mutations:
            with self.subTest(label=label):
                value = attestation()
                mutate(value)
                with patch.object(gate, "PHYSICAL_VALIDATION_AUTHORITY_KEYS", authority()), \
                        patch.object(gate, "_verify_ed25519_signature", return_value=True):
                    with self.assertRaisesRegex(ValueError, message):
                        verify(value)

    def test_timing_evidence_floor_and_tail_limits_are_source_pinned(self):
        command = gate.COMMAND_TIMESTAMP_ERROR_LIMITS_MS
        perceptual = gate.PERCEPTUAL_RESPONSE_ERROR_LIMITS_MS
        mutations = (
            (
                "insufficient-samples",
                lambda value: value["measurements"]["timing"].update(
                    samples=gate.MINIMUM_PHYSICAL_TIMING_SAMPLES - 1
                ),
                "timing.samples must be at least",
            ),
            (
                "command-p95",
                lambda value: value["measurements"]["timing"]["command_timestamp_error_ms"].update(
                    p95=command["p95"] + 1,
                    p99=command["p99"],
                    max=command["max"],
                ),
                "command timestamp error.p95 exceeds source-pinned maximum",
            ),
            (
                "command-p99",
                lambda value: value["measurements"]["timing"]["command_timestamp_error_ms"].update(
                    p95=command["p95"],
                    p99=command["p99"] + 1,
                    max=command["max"],
                ),
                "command timestamp error.p99 exceeds source-pinned maximum",
            ),
            (
                "command-max",
                lambda value: value["measurements"]["timing"]["command_timestamp_error_ms"].update(
                    p95=command["p95"],
                    p99=command["p99"],
                    max=command["max"] + 1,
                ),
                "command timestamp error.max exceeds source-pinned maximum",
            ),
            (
                "perceptual-p95",
                lambda value: value["measurements"]["timing"]["perceptual_response_error_ms"].update(
                    p95=perceptual["p95"] + 1,
                    p99=perceptual["p99"],
                    max=perceptual["max"],
                ),
                "perceptual response error.p95 exceeds source-pinned maximum",
            ),
            (
                "perceptual-p99",
                lambda value: value["measurements"]["timing"]["perceptual_response_error_ms"].update(
                    p95=perceptual["p95"],
                    p99=perceptual["p99"] + 1,
                    max=perceptual["max"],
                ),
                "perceptual response error.p99 exceeds source-pinned maximum",
            ),
            (
                "perceptual-max",
                lambda value: value["measurements"]["timing"]["perceptual_response_error_ms"].update(
                    p95=perceptual["p95"],
                    p99=perceptual["p99"],
                    max=perceptual["max"] + 1,
                ),
                "perceptual response error.max exceeds source-pinned maximum",
            ),
        )
        for label, mutate, message in mutations:
            with self.subTest(label=label):
                value = attestation()
                mutate(value)
                with patch.object(gate, "PHYSICAL_VALIDATION_AUTHORITY_KEYS", authority()), \
                        patch.object(gate, "_verify_ed25519_signature", return_value=True):
                    with self.assertRaisesRegex(ValueError, message):
                        verify(value)

    def test_private_evidence_and_installed_identity_are_signed_and_fail_closed(self):
        value = attestation()
        payload = gate.signed_payload(value)
        self.assertEqual(
            payload["private_evidence"]["manifest_sha256"],
            value["private_evidence"]["manifest_sha256"],
        )
        self.assertEqual(
            payload["private_evidence"]["reference"],
            value["private_evidence"]["reference"],
        )
        mutations = (
            (
                "private-evidence-digest",
                lambda item: item["private_evidence"].update(manifest_sha256="0" * 64),
                "signed payload digest differs",
            ),
            (
                "private-evidence-reference",
                lambda item: item["private_evidence"].update(reference="physical-lab-record-002"),
                "signed payload digest differs",
            ),
            (
                "installed-apk",
                lambda item: item["installed_apk"].update(apk_sha256="0" * 64),
                "installed APK digest differs",
            ),
            (
                "installed-package",
                lambda item: item["installed_apk"].update(package_name="com.example.wrong"),
                "installed APK package differs",
            ),
            (
                "installed-version",
                lambda item: item["installed_apk"].update(version_code=RELEASE["code"] + 1),
                "installed APK version differs",
            ),
        )
        for label, mutate, message in mutations:
            with self.subTest(label=label):
                item = attestation()
                mutate(item)
                with patch.object(gate, "PHYSICAL_VALIDATION_AUTHORITY_KEYS", authority()), \
                        patch.object(gate, "_verify_ed25519_signature", return_value=True) as verifier:
                    with self.assertRaisesRegex(ValueError, message):
                        verify(item)
                verifier.assert_not_called()

    def test_percentile_method_and_per_class_coverage_are_source_pinned(self):
        mutations = (
            (
                "method",
                lambda value: value["measurements"]["timing"].update(percentile_method="other-v1"),
                "percentile method is unsupported",
            ),
            (
                "lighting-coverage",
                lambda value: value["measurements"]["coverage"]["lighting"].update(realized_events=94),
                "lighting coverage is below source-pinned minimum",
            ),
            (
                "mechanical-coverage",
                lambda value: value["measurements"]["coverage"]["mechanical"].update(realized_events=89),
                "mechanical coverage is below source-pinned minimum",
            ),
        )
        for label, mutate, message in mutations:
            with self.subTest(label=label):
                value = attestation()
                mutate(value)
                with patch.object(gate, "PHYSICAL_VALIDATION_AUTHORITY_KEYS", authority()), \
                        patch.object(gate, "_verify_ed25519_signature", return_value=True) as verifier:
                    with self.assertRaisesRegex(ValueError, message):
                        verify(value)
                verifier.assert_not_called()

    def test_per_class_coverage_requires_representative_eligible_counts(self):
        self.assertEqual(
            dict(gate.MINIMUM_PHYSICAL_ELIGIBLE_EVENT_COUNTS),
            {"lighting": 50, "mechanical": 50},
        )
        for event_class, minimum in gate.MINIMUM_PHYSICAL_ELIGIBLE_EVENT_COUNTS.items():
            with self.subTest(event_class=event_class, boundary="below"):
                value = attestation()
                value["measurements"]["coverage"][event_class].update(
                    eligible_events=minimum - 1,
                    realized_events=minimum - 1,
                )
                with patch.object(gate, "PHYSICAL_VALIDATION_AUTHORITY_KEYS", authority()), \
                        patch.object(gate, "_verify_ed25519_signature", return_value=True) as verifier:
                    with self.assertRaisesRegex(ValueError, "eligible_events must be at least source-pinned minimum"):
                        verify(value)
                verifier.assert_not_called()
            with self.subTest(event_class=event_class, boundary="at"):
                value = attestation()
                percent = gate.MINIMUM_PHYSICAL_EVENT_COVERAGE_PERCENT[event_class]
                realized = (minimum * percent + 99) // 100
                value["measurements"]["coverage"][event_class].update(
                    eligible_events=minimum,
                    realized_events=realized,
                )
                reseal(value)
                with patch.object(gate, "PHYSICAL_VALIDATION_AUTHORITY_KEYS", authority()), \
                        patch.object(gate, "_verify_ed25519_signature", return_value=True) as verifier:
                    self.assertEqual(verify(value)["status"], "verified")
                self.assertEqual(verifier.call_count, 1)

    def test_per_class_timing_requires_sample_floors_and_existing_tail_limits(self):
        self.assertEqual(
            dict(gate.MINIMUM_PHYSICAL_CLASS_TIMING_SAMPLES),
            {"lighting": 50, "mechanical": 50},
        )
        command = gate.COMMAND_TIMESTAMP_ERROR_LIMITS_MS
        perceptual = gate.PERCEPTUAL_RESPONSE_ERROR_LIMITS_MS
        mutations = (
            (
                "lighting-samples",
                lambda value: value["measurements"]["timing"]["per_class"]["lighting"].update(
                    samples=gate.MINIMUM_PHYSICAL_CLASS_TIMING_SAMPLES["lighting"] - 1
                ),
                "lighting timing.samples must be at least source-pinned minimum",
            ),
            (
                "mechanical-samples",
                lambda value: value["measurements"]["timing"]["per_class"]["mechanical"].update(
                    samples=gate.MINIMUM_PHYSICAL_CLASS_TIMING_SAMPLES["mechanical"] - 1
                ),
                "mechanical timing.samples must be at least source-pinned minimum",
            ),
            (
                "lighting-command-tail",
                lambda value: value["measurements"]["timing"]["per_class"]["lighting"][
                    "command_timestamp_error_ms"
                ].update(
                    p95=command["p95"] + 1,
                    p99=command["p99"],
                    max=command["max"],
                ),
                "lighting command timestamp error.p95 exceeds source-pinned maximum",
            ),
            (
                "mechanical-perceptual-tail",
                lambda value: value["measurements"]["timing"]["per_class"]["mechanical"][
                    "perceptual_response_error_ms"
                ].update(
                    p95=perceptual["p95"],
                    p99=perceptual["p99"] + 1,
                    max=perceptual["max"],
                ),
                "mechanical perceptual response error.p99 exceeds source-pinned maximum",
            ),
        )
        for label, mutate, message in mutations:
            with self.subTest(label=label):
                value = attestation()
                mutate(value)
                with patch.object(gate, "PHYSICAL_VALIDATION_AUTHORITY_KEYS", authority()), \
                        patch.object(gate, "_verify_ed25519_signature", return_value=True) as verifier:
                    with self.assertRaisesRegex(ValueError, message):
                        verify(value)
                verifier.assert_not_called()
        for event_class, minimum in gate.MINIMUM_PHYSICAL_CLASS_TIMING_SAMPLES.items():
            with self.subTest(event_class=event_class, boundary="at"):
                value = attestation()
                value["measurements"]["timing"]["per_class"][event_class]["samples"] = minimum
                reseal(value)
                with patch.object(gate, "PHYSICAL_VALIDATION_AUTHORITY_KEYS", authority()), \
                        patch.object(gate, "_verify_ed25519_signature", return_value=True) as verifier:
                    self.assertEqual(verify(value)["status"], "verified")
                self.assertEqual(verifier.call_count, 1)

    def test_review_freshness_is_source_pinned_and_checked_before_signature(self):
        mutations = (
            (
                "stale-before-issue",
                lambda value: value["review"].update(observed_at="2026-09-10T10:59:59Z"),
                "observed evidence is older than source-pinned maximum at issue",
            ),
            (
                "stale-issued",
                lambda value: value["review"].update(
                    observed_at="2026-09-10T10:00:00Z",
                    issued_at="2026-09-10T11:59:59Z",
                ),
                "issuance is older than source-pinned maximum at verification",
            ),
            (
                "stale-at-publish-despite-recent-issue",
                lambda value: value["review"].update(
                    observed_at="2026-09-10T11:00:00Z",
                    issued_at="2026-09-10T12:30:00Z",
                ),
                "observation is older than source-pinned maximum at verification",
            ),
        )
        for label, mutate, message in mutations:
            with self.subTest(label=label):
                value = attestation()
                mutate(value)
                with patch.object(gate, "PHYSICAL_VALIDATION_AUTHORITY_KEYS", authority()), \
                        patch.object(gate, "_verify_ed25519_signature", return_value=True) as verifier:
                    with self.assertRaisesRegex(ValueError, message):
                        verify(value)
                verifier.assert_not_called()

    def test_real_ed25519_signature_is_verified_when_backend_is_available(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        except ImportError:
            self.skipTest("cryptography backend unavailable")
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        key_sha256 = hashlib.sha256(public_key).hexdigest()
        configured = MappingProxyType(
            {
                "physical-lab-a": {
                    "protocol": gate.PHYSICAL_VALIDATION_PROTOCOL,
                    "algorithm": gate.PHYSICAL_VALIDATION_ALGORITHM,
                    "verification_key_base64": base64.b64encode(public_key).decode("ascii"),
                    "verification_key_sha256": key_sha256,
                }
            }
        )
        value = attestation()
        value["verification_key_sha256"] = key_sha256
        value["signed_payload_sha256"] = hashlib.sha256(
            gate.canonical_json(gate.signed_payload(value)).encode("utf-8")
        ).hexdigest()
        value["signature_base64"] = base64.b64encode(
            private_key.sign(gate.canonical_json(gate.signed_payload(value)).encode("utf-8"))
        ).decode("ascii")
        with patch.object(gate, "PHYSICAL_VALIDATION_AUTHORITY_KEYS", configured):
            self.assertEqual(verify(value)["status"], "verified")

    def test_signature_is_not_replaced_by_a_digest_check(self):
        with patch.object(gate, "PHYSICAL_VALIDATION_AUTHORITY_KEYS", authority()):
            with self.assertRaisesRegex(ValueError, "signature is invalid"):
                verify(attestation())

    def test_attestation_file_requires_private_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "physical-validation.json"
            path.write_text("{}", encoding="utf-8")
            path.chmod(0o600)
            self.assertEqual(gate.load_attestation(path), {})
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "mode 0600"):
                gate.load_attestation(path)

    def test_attestation_loader_rejects_duplicate_keys_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"first":1,"first":2}', encoding="utf-8")
            duplicate.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "duplicate object keys"):
                gate.load_attestation(duplicate)
            if not hasattr(os, "O_NOFOLLOW"):
                self.skipTest("O_NOFOLLOW is unavailable on this platform")
            target = root / "target.json"
            target.write_text("{}", encoding="utf-8")
            target.chmod(0o600)
            link = root / "attestation-link.json"
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "file is invalid"):
                gate.load_attestation(link)


if __name__ == "__main__":
    unittest.main()
