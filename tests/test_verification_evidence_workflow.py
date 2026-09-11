#!/usr/bin/env python3
"""Static safety checks for the sealed non-Android verify-v2 handoff."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/verify-v2.yml").read_text(encoding="utf-8")


class VerificationEvidenceWorkflowTest(unittest.TestCase):
    def test_only_the_diagnostic_archive_uses_always(self):
        generic = WORKFLOW.index("name: lightforge-${{ env.LIGHTFORGE_RELEASE }}-verification\n")
        self.assertIn("if: always()", WORKFLOW[max(0, generic - 180):generic])
        content = WORKFLOW.index("name: lightforge-${{ env.LIGHTFORGE_RELEASE }}-verification-evidence-${{ github.run_id }}-${{ github.run_attempt }}")
        wrapper = WORKFLOW.index("name: lightforge-${{ env.LIGHTFORGE_RELEASE }}-verification-evidence-manifest-${{ github.run_id }}-${{ github.run_attempt }}")
        self.assertNotIn("if: always()", WORKFLOW[max(0, content - 220):content])
        self.assertNotIn("if: always()", WORKFLOW[max(0, wrapper - 220):wrapper])

    def test_receipts_are_purged_before_tests_and_sealed_after_candidate_upload(self):
        purge = WORKFLOW.index("Remove checked-in core receipts before fresh verification")
        tests = WORKFLOW.index("Production regression, diagnostics, and quality-tool suites")
        candidate = WORKFLOW.index("id: upload_candidate")
        seal = WORKFLOW.index("Seal success-only non-Android verification evidence")
        self.assertLess(purge, tests)
        self.assertLess(candidate, seal)
        for name in (
            "regression-verification.json", "browser-verification.json", "native-verification.json",
            "analysis-browser-verification.json", "analysis-verification.json",
        ):
            self.assertIn('"$receipt_root/' + name + '"', WORKFLOW)
        self.assertIn("--source-root \"$GITHUB_WORKSPACE\"", WORKFLOW)

    def test_wrapper_binds_action_output_identity_and_candidate_retry_contract(self):
        for value in (
            "candidate_artifact_id", "candidate_artifact_digest", "candidate_identity_sha256",
            "candidate_run_id", "candidate_run_attempt", "candidate_evidence_session",
            "verification_evidence_artifact_id", "verification_evidence_wrapper_artifact_id",
            "steps.upload_candidate.outputs.artifact-id", "steps.upload_candidate.outputs.artifact-digest",
            "steps.upload_verification_evidence.outputs.artifact-id",
            "steps.upload_verification_evidence.outputs.artifact-digest",
            "write-wrapper", "--run-attempt \"$GITHUB_RUN_ATTEMPT\"",
        ):
            self.assertIn(value, WORKFLOW)


if __name__ == "__main__":
    unittest.main()
