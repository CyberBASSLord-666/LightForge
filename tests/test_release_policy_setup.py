"""Policy setup security boundaries, using ephemeral test-only identities."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import release_policy_setup as setup

spec = importlib.util.spec_from_file_location("quality_fixture", ROOT / "tests/performance-quality-gate.test.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class PolicySetupTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lightforge-policy-setup-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.manifest = fixture.release_manifest()
        self.policy = fixture.release_policy(self.manifest)
        self.addCleanup(patch.stopall)
        patch.object(setup, "gate", fixture.gate).start()
        self.key = self.root / "test-only-key.pem"
        self.key.write_bytes(fixture._TEST_REVIEW_PRIVATE_KEY_PEM)
        self.key.chmod(0o600)

    def test_real_signature_matches_gate_and_does_not_claim_qualification(self):
        receipt = setup.sign_bundle(self.policy, self.manifest, self.key)
        summary = setup.validate_bundle(self.policy, self.manifest, receipt)
        self.assertTrue(summary["policy_attestation_verified"])
        self.assertEqual("not_evaluated", summary["qualification_status"])
        self.assertNotIn("production_ready", summary)
        output = self.root / "receipt.json"
        setup.write_new_receipt(output, receipt)
        self.assertEqual(0o600, output.stat().st_mode & 0o777)
        self.assertEqual(receipt, setup.load_json(output))
        with self.assertRaisesRegex(setup.SetupError, "must_be_new"):
            setup.write_new_receipt(output, {"replaced": True})
        self.assertEqual(receipt, setup.load_json(output))

    def test_replay_after_policy_change_and_signature_tampering_are_rejected(self):
        receipt = setup.sign_bundle(self.policy, self.manifest, self.key)
        changed = copy.deepcopy(self.policy)
        changed["bootstrap"]["seed"] = "different-committed-seed"
        with self.assertRaisesRegex(setup.SetupError, "not_verified"):
            setup.validate_bundle(changed, self.manifest, receipt)
        receipt["signature_base64"] = "A" * 86 + "=="
        with self.assertRaisesRegex(setup.SetupError, "not_verified"):
            setup.validate_bundle(self.policy, self.manifest, receipt)

    def test_source_registry_required_and_candidate_reference_cannot_replace_it(self):
        with patch.object(fixture.gate, "RELEASE_POLICY_AUTHORITY_KEYS", {}):
            with self.assertRaisesRegex(setup.SetupError, "unconfigured"):
                setup.sign_bundle(self.policy, self.manifest, self.key)
        self.policy["release_profile"]["policy_authority"]["verification_key_sha256"] = fixture.sha("other-key")
        with self.assertRaisesRegex(setup.SetupError, "binding_mismatch"):
            setup.sign_bundle(self.policy, self.manifest, self.key)

    def test_key_file_must_be_private_and_cannot_be_a_symlink(self):
        self.key.chmod(0o644)
        with self.assertRaisesRegex(setup.SetupError, "owner_only"):
            setup.sign_bundle(self.policy, self.manifest, self.key)
        self.key.chmod(0o600)
        alias = self.root / "alias.pem"
        alias.symlink_to(self.key)
        with self.assertRaisesRegex(setup.SetupError, "unreadable"):
            setup.sign_bundle(self.policy, self.manifest, alias)

    def test_invalid_corpus_and_relaxed_policy_fail_before_key_access(self):
        missing_key = self.root / "not-a-key.pem"
        changed = copy.deepcopy(self.manifest)
        changed["tracks"].pop()
        with self.assertRaisesRegex(setup.SetupError, "invalid_locked_corpus"):
            setup.sign_bundle(self.policy, changed, missing_key)
        for field, value in (("minimum_pairs_per_track", 3),
                             ("release_profile", {"mode": "template"})):
            with self.subTest(field=field):
                policy = copy.deepcopy(self.policy)
                policy[field] = value
                with self.assertRaises(setup.SetupError):
                    setup.sign_bundle(policy, self.manifest, missing_key)

    def test_strict_json_and_errors_never_echo_secret_input(self):
        policy = self.root / "policy.json"
        manifest = self.root / "manifest.json"
        receipt = self.root / "receipt.json"
        marker = "DO-NOT-PRINT-PRIVATE-INPUT"
        for raw in ('{"duplicate":1,"duplicate":2}', '{"value":NaN}',
                    '{"bad":' + marker, '"' + marker + '"',
                    ' ' * (setup.MAX_SECRET_BYTES + 1)):
            with self.subTest(raw_length=len(raw)):
                policy.write_text(raw)
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    result = setup.main(["validate", "--policy", str(policy),
                                         "--manifest", str(manifest), "--attestation", str(receipt)])
                self.assertEqual(1, result)
                self.assertNotIn(marker, out.getvalue() + err.getvalue())


if __name__ == "__main__":
    unittest.main()
