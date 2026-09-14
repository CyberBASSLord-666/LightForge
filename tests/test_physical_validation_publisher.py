import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import publish_github_release as publisher


COMMIT = "a" * 40
TREE = "b" * 40
VERSION = {"name": "2.2.5", "code": 20205}
APK = "LightForge-2.2.5.apk"
VEHICLE_SOURCE = (
    b"(function(root){const profile=Object.freeze({id:'model3-highland-2025-na',"
    b"version:'1.5.0'});})(this);"
)
MANIFEST_SOURCE = b'<manifest package="com.cyberbasslord.lightforge"/>'


def android_evidence():
    candidate = {
        "artifact_id": 501,
        "artifact_digest": "c" * 64,
        "identity_sha256": "d" * 64,
        "pipeline": {"run_id": 101, "run_attempt": 2, "evidence_session": "e" * 64},
        "files": {APK: {"bytes": 1, "sha256": "f" * 64}},
    }
    return {
        "android_artifact_id": 502,
        "android_artifact_digest": "1" * 64,
        "android_evidence_manifest_sha256": "2" * 64,
        "manifest": {
            "pipeline": {
                "workflow": ".github/workflows/verify-v2.yml",
                "run_id": 101,
                "run_attempt": 2,
                "evidence_session": "3" * 64,
            },
            "candidate": candidate,
            "receipts": {
                "android-background-verification.json": {"sha256": "4" * 64},
                "android-diagnostics-verification.json": {"sha256": "5" * 64},
            },
        },
    }


class PhysicalValidationPublisherTest(unittest.TestCase):
    def test_publisher_derives_every_sealed_and_source_bound_value(self):
        evidence = android_evidence()

        def source_file(commit, path):
            self.assertEqual(commit, COMMIT)
            if path == "web/engine/vehicle-profile.js":
                return VEHICLE_SOURCE
            if path == "android/AndroidManifest.xml":
                return MANIFEST_SOURCE
            self.fail("unexpected source path " + path)

        with patch.object(publisher, "_source_file_bytes", side_effect=source_file), \
                patch.object(
                    publisher,
                    "verify_physical_validation_attestation",
                    return_value={"status": "verified"},
                ) as verify:
            returned = publisher.verify_physical_validation(
                {"opaque": "attestation"}, VERSION, COMMIT, TREE, evidence
            )

        self.assertEqual(returned, {"status": "verified"})
        kwargs = verify.call_args.kwargs
        self.assertEqual(kwargs["release"], VERSION)
        self.assertEqual(kwargs["source"], {"commit": COMMIT, "tree_sha": TREE})
        self.assertEqual(
            kwargs["candidate"],
            {
                "workflow": ".github/workflows/verify-v2.yml",
                "run_id": 101,
                "run_attempt": 2,
                "evidence_session": "e" * 64,
                "artifact_id": 501,
                "artifact_digest": "c" * 64,
                "identity_sha256": "d" * 64,
                "apk_sha256": "f" * 64,
            },
        )
        self.assertEqual(
            kwargs["android_evidence"],
            {
                "workflow": ".github/workflows/verify-v2.yml",
                "run_id": 101,
                "run_attempt": 2,
                "evidence_session": "3" * 64,
                "artifact_id": 502,
                "artifact_digest": "1" * 64,
                "manifest_sha256": "2" * 64,
                "receipt_sha256": {
                    "android-background-verification.json": "4" * 64,
                    "android-diagnostics-verification.json": "5" * 64,
                },
            },
        )
        self.assertEqual(kwargs["expected_package_name"], "com.cyberbasslord.lightforge")
        self.assertEqual(
            kwargs["expected_vehicle_profile"],
            {
                "source_path": "web/engine/vehicle-profile.js",
                "source_sha256": hashlib.sha256(VEHICLE_SOURCE).hexdigest(),
                "id": "model3-highland-2025-na",
                "version": "1.5.0",
            },
        )

    def test_publisher_requires_sealed_android_evidence(self):
        with self.assertRaisesRegex(ValueError, "requires sealed Android evidence"):
            publisher.verify_physical_validation({}, VERSION, COMMIT, TREE, None)


if __name__ == "__main__":
    unittest.main()
