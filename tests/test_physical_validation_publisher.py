import hashlib
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
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

        self.assertEqual(returned, {"status": "verified", "requirement": "optional"})
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

    def test_absent_observations_remain_unverified_without_authority_lookup(self):
        with patch.object(publisher, "verify_physical_validation_attestation") as verify, \
                patch.object(publisher, "_source_file_bytes") as source:
            result = publisher.verify_physical_validation(None, VERSION, COMMIT, TREE, None)
        self.assertEqual(result["requirement"], "optional")
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["source"], {"commit": COMMIT, "tree_sha": TREE})
        self.assertNotIn("review", result)
        verify.assert_not_called()
        source.assert_not_called()

    def test_supplied_invalid_observations_are_not_silently_ignored(self):
        with patch.object(publisher, "_source_android_package", return_value="com.cyberbasslord.lightforge"), \
                patch.object(publisher, "_source_vehicle_profile", return_value={}), \
                patch.object(publisher, "verify_physical_validation_attestation", side_effect=ValueError("invalid signature")):
            with self.assertRaisesRegex(ValueError, "invalid signature"):
                publisher.verify_physical_validation({}, VERSION, COMMIT, TREE, android_evidence())

    def test_cli_can_publish_without_observations_and_replaces_unverified_public_claim(self):
        """Exercise the absent CLI option through publication with sealed gates mocked."""
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            root = Path(temporary)
            old_cwd = Path.cwd()
            stack.callback(os.chdir, old_cwd)
            (root / "version.json").write_text(json.dumps(VERSION))
            (root / "RELEASE_NOTES.md").write_text("Candidate notes\n")
            candidate_root = root / "candidate"
            candidate_root.mkdir()
            candidate_apk = candidate_root / APK
            candidate_apk.write_bytes(b"verified application bytes")
            receipt_path = root / "release-verification.json"
            receipt_path.write_text(json.dumps({
                "release": {"sha256": publisher.digest(candidate_apk)},
                "physical_validation": {"status": "verified", "review": {"verdict": "pass"}},
            }))
            delta_path = root / "releases/v2.2.5/signed-apk.delta.json"
            delta_path.parent.mkdir(parents=True)
            delta_path.write_text("{}")
            request_path = root / "request.json"
            request_path.write_text(json.dumps({
                "source_commit": COMMIT, "version": VERSION, "run_id": 101,
                "delta_sha256": publisher.digest(delta_path),
            }))
            ci = {"id": 101, "run_attempt": 2, "status": "completed", "conclusion": "success",
                  "head_sha": COMMIT, "head_repository": {"full_name": "CyberBASSLord-666/LightForge"},
                  "path": ".github/workflows/verify-v2.yml", "event": "push", "head_branch": "main"}
            evidence = android_evidence()
            evidence["candidate_root"] = candidate_root
            draft = {"id": 22, "draft": True, "tag_name": "v2.2.5"}
            published = {**draft, "draft": False, "html_url": "https://example.test/release",
                         "assets": [{"name": APK, "browser_download_url": "https://example.test/app.apk"}]}
            stack.enter_context(patch.object(publisher, "ROOT", root))
            stack.enter_context(patch.dict(os.environ, {
                "GH_REPO": "CyberBASSLord-666/LightForge", "GITHUB_REF": "refs/heads/main",
                "LIGHTFORGE_REF_PROTECTED": "true",
            }))
            mocks = {}
            for name, kwargs in {
                "require_candidate_worktree": {},
                "load_physical_validation_attestation": {},
                "verify_physical_validation_attestation": {},
                "api": {"side_effect": lambda path: {"tree": {"sha": TREE}} if "/git/commits/" in path else ci},
                "verify_release_quality": {"return_value": {"requirement": "performance_quality_gate"}},
                "verify_android_release_evidence": {"return_value": evidence},
                "verify_nonandroid_release_evidence": {"return_value": {"status": "verified"}},
                "apply_delta": {"side_effect": lambda source, delta, target: shutil.copyfile(source, target)},
                "verify_candidate_payload_equivalence": {},
                "verify_apk": {}, "create_draft": {"return_value": draft},
                "asset_plan": {"return_value": []}, "update_metadata": {},
                "lookup_release": {"side_effect": [draft, published]}, "verify_uploaded": {},
            }.items():
                mocks[name] = stack.enter_context(patch.object(publisher, name, **kwargs))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                publisher.main([str(request_path)])
            public_result = json.loads(output.getvalue())["physical_validation"]
            self.assertEqual(public_result["status"], "unverified")
            self.assertEqual(public_result["requirement"], "optional")
            self.assertNotIn("review", public_result)
            self.assertEqual(json.loads(receipt_path.read_text())["physical_validation"], public_result)
            for name in ("require_candidate_worktree", "verify_release_quality", "verify_android_release_evidence",
                         "verify_nonandroid_release_evidence", "verify_candidate_payload_equivalence", "verify_apk", "create_draft"):
                mocks[name].assert_called_once()
            mocks["load_physical_validation_attestation"].assert_not_called()
            mocks["verify_physical_validation_attestation"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
