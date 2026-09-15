import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = (ROOT / "tools/publish_github_release.py").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github/workflows/publish-release.yml").read_text(encoding="utf-8")
GATE = (ROOT / "tools/physical_validation_gate.py").read_text(encoding="utf-8")


class PhysicalValidationPublicationWiringTest(unittest.TestCase):
    def test_source_pinned_authority_and_complete_binding_contract_are_present(self):
        self.assertIn("PHYSICAL_VALIDATION_AUTHORITY_KEYS = MappingProxyType({})", GATE)
        self.assertIn("lightforge-physical-validation-attestation-v1", GATE)
        self.assertIn("signed_payload_sha256", GATE)
        self.assertIn("signature_base64", GATE)
        self.assertIn("ed25519", GATE)
        self.assertIn("MINIMUM_PHYSICAL_TIMING_SAMPLES = 100", GATE)
        self.assertIn("COMMAND_TIMESTAMP_ERROR_LIMITS_MS", GATE)
        self.assertIn("PERCEPTUAL_RESPONSE_ERROR_LIMITS_MS", GATE)
        self.assertIn("MAX_PHYSICAL_VALIDATION_OBSERVED_TO_ISSUED_AGE = timedelta(hours=24)", GATE)
        self.assertIn("MAX_PHYSICAL_VALIDATION_ISSUED_TO_VERIFICATION_AGE = timedelta(hours=24)", GATE)
        self.assertIn("MAX_PHYSICAL_VALIDATION_OBSERVED_TO_VERIFICATION_AGE = timedelta(hours=24)", GATE)
        self.assertIn("PHYSICAL_VALIDATION_PERCENTILE_METHOD", GATE)
        self.assertIn("MINIMUM_PHYSICAL_EVENT_COVERAGE_PERCENT", GATE)
        self.assertIn("MINIMUM_PHYSICAL_ELIGIBLE_EVENT_COUNTS", GATE)
        self.assertIn("MINIMUM_PHYSICAL_CLASS_TIMING_SAMPLES", GATE)
        self.assertIn("per_class", GATE)
        self.assertIn("private_evidence", GATE)
        self.assertIn("installed_apk", GATE)
        self.assertIn("os.O_NOFOLLOW", GATE)
        self.assertIn("os.O_CLOEXEC", GATE)
        self.assertIn("os.fstat", GATE)
        self.assertIn("object_pairs_hook=_reject_duplicate_json_object_keys", GATE)
        self.assertIn("observed evidence is older than source-pinned maximum", GATE)
        self.assertIn("issuance is older than source-pinned maximum", GATE)
        self.assertIn("observation is older than source-pinned maximum", GATE)
        self.assertIn("exceeds source-pinned maximum", GATE)
        self.assertNotIn("device_binding_sha256", GATE)
        self.assertNotIn('canonical_json(attestation["device"])', GATE)
        for required in (
            "artifact_digest",
            "identity_sha256",
            "apk_sha256",
            "manifest_sha256",
            "android-background-verification.json",
            "android-diagnostics-verification.json",
            "tesla_playback_passed",
            "actuator_feasibility_passed",
            "safety_incident_count",
            "uncommanded_event_count",
            "command_timestamp_error_ms",
            "perceptual_response_error_ms",
            "expires_at",
        ):
            self.assertIn(required, GATE)

    def test_publisher_derives_source_profile_and_checks_before_draft_creation(self):
        self.assertIn("from physical_validation_gate import", PUBLISHER)
        self.assertIn("'tools/physical_validation_gate.py'", PUBLISHER)
        self.assertIn("def _source_vehicle_profile(", PUBLISHER)
        self.assertIn("def _source_android_package(", PUBLISHER)
        self.assertIn("def verify_physical_validation(", PUBLISHER)
        call = PUBLISHER.index("physical_validation = verify_physical_validation(")
        android = PUBLISHER.index("android_evidence = verify_android_release_evidence(")
        draft = PUBLISHER.index("release = create_draft(")
        self.assertLess(android, call)
        self.assertLess(call, draft)
        self.assertIn("'android_evidence_manifest_sha256'", PUBLISHER)
        self.assertIn("'android_artifact_digest'", PUBLISHER)

    def test_secret_is_materialized_only_inside_final_publisher_step_and_removed(self):
        final_step = WORKFLOW[WORKFLOW.index("- name: Verify provenance, reconstruct exact signed APK and publish"):]
        prior_steps = WORKFLOW[:WORKFLOW.index("- name: Verify provenance, reconstruct exact signed APK and publish")]
        self.assertIn(
            "LIGHTFORGE_PHYSICAL_VALIDATION_ATTESTATION_JSON: ${{ secrets.LIGHTFORGE_PHYSICAL_VALIDATION_ATTESTATION_JSON }}",
            final_step,
        )
        self.assertNotIn("LIGHTFORGE_PHYSICAL_VALIDATION_ATTESTATION_JSON", prior_steps)
        self.assertNotIn("GITHUB_ENV", final_step)
        self.assertEqual(WORKFLOW.count("secrets.LIGHTFORGE_PHYSICAL_VALIDATION_ATTESTATION_JSON"), 1)
        self.assertNotIn("LIGHTFORGE_PHYSICAL_VALIDATION_ATTESTATION_PATH", WORKFLOW)
        self.assertIn('target="$(mktemp "$RUNNER_TEMP/lightforge-physical-validation-attestation.XXXXXX")"', final_step)
        self.assertIn("trap cleanup EXIT HUP INT TERM", final_step)
        self.assertIn('rm -f -- "$target"', final_step)
        self.assertIn("unset LIGHTFORGE_PHYSICAL_VALIDATION_ATTESTATION_JSON", final_step)
        self.assertIn("set -euo pipefail", final_step)
        self.assertIn("chmod 600", final_step)
        self.assertIn('python3 -I -S -m json.tool "$target" > /dev/null', final_step)
        self.assertIn("--physical-validation-attestation", final_step)
        self.assertIn('if [[ -n "${LIGHTFORGE_PHYSICAL_VALIDATION_ATTESTATION_JSON:-}" ]]; then', final_step)
        self.assertNotIn('test -n "$LIGHTFORGE_PHYSICAL_VALIDATION_ATTESTATION_JSON"', final_step)
        self.assertLess(
            final_step.index("unset LIGHTFORGE_PHYSICAL_VALIDATION_ATTESTATION_JSON"),
            final_step.index("python3 -E -S tools/publish_github_release.py"),
        )

    def run_final_step(self, secret):
        """Run the literal shell step; substitute only the final publisher process."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / "bin"
            binary.mkdir()
            launcher = binary / "python3"
            launcher.write_text("#!" + sys.executable + "\n" + textwrap.dedent('''\
                import json, os, pathlib, stat, sys
                if "tools/publish_github_release.py" not in sys.argv:
                    os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
                result = {"args": sys.argv[1:], "secret_available": "LIGHTFORGE_PHYSICAL_VALIDATION_ATTESTATION_JSON" in os.environ}
                if "--physical-validation-attestation" in sys.argv:
                    target = pathlib.Path(sys.argv[-1])
                    result["mode"] = stat.S_IMODE(target.stat().st_mode)
                    result["content"] = json.loads(target.read_text())
                pathlib.Path(os.environ["TEST_RESULT"]).write_text(json.dumps(result))
                '''))
            launcher.chmod(0o755)
            env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ["PATH"],
                       LIGHTFORGE_RELEASE_SOURCE=str(root), LIGHTFORGE_RELEASE_REQUEST="request.json",
                       RUNNER_TEMP=str(root), TEST_RESULT=str(root / "result.json"))
            env.pop("LIGHTFORGE_PHYSICAL_VALIDATION_ATTESTATION_JSON", None)
            if secret is not None:
                env["LIGHTFORGE_PHYSICAL_VALIDATION_ATTESTATION_JSON"] = secret
            step = WORKFLOW.split("      - name: Verify provenance, reconstruct exact signed APK and publish\n", 1)[1]
            script = textwrap.dedent(step.split("        run: |\n", 1)[1])
            process = subprocess.run(["bash", "-c", script], env=env, text=True, capture_output=True)
            result = json.loads((root / "result.json").read_text()) if (root / "result.json").exists() else None
            self.assertEqual(list(root.glob("lightforge-physical-validation-attestation.*")), [])
            return process, result

    def test_unset_and_empty_secrets_allow_publication_without_attestation_argument(self):
        for secret in (None, ""):
            with self.subTest(secret=secret):
                process, result = self.run_final_step(secret)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(result["args"], ["-E", "-S", "tools/publish_github_release.py", "request.json"])
                self.assertFalse(result["secret_available"])

    def test_supplied_secret_is_private_and_removed_after_publication(self):
        process, result = self.run_final_step('{"synthetic_test":true}')
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(result["mode"], 0o600)
        self.assertEqual(result["content"], {"synthetic_test": True})
        self.assertFalse(result["secret_available"])
        self.assertIn("--physical-validation-attestation", result["args"])

    def test_malformed_supplied_secret_aborts_before_publication_and_is_removed(self):
        process, result = self.run_final_step("invalid-json")
        self.assertNotEqual(process.returncode, 0)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
