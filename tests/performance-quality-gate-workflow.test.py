import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/performance-quality-gate.yml"


class PerformanceQualityGateWorkflowTest(unittest.TestCase):
    def test_dispatch_comparison_has_explicit_artifact_provenance_and_permissions(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("actions: read", text)
        for name in (
            "baseline_artifact:",
            "baseline_run_id:",
            "candidate_artifact:",
            "candidate_run_id:",
        ):
            self.assertRegex(text, re.escape(name) + r"\n\s+description:.*\n\s+required: true")
        self.assertEqual(2, text.count("repository: ${{ github.repository }}"))
        self.assertNotIn("baseline_repository:", text)
        self.assertNotIn("candidate_repository:", text)
        self.assertIn("run-id: ${{ inputs.baseline_run_id }}", text)
        self.assertIn("run-id: ${{ inputs.candidate_run_id }}", text)
        self.assertIn("environment: lightforge-release-quality", text)
        self.assertIn('test "$GITHUB_REF" = "refs/heads/main"', text)
        self.assertIn('test "$LIGHTFORGE_REF_PROTECTED" = "true"', text)
        for secret in (
            "LIGHTFORGE_RELEASE_POLICY_JSON: ${{ secrets.LIGHTFORGE_RELEASE_POLICY_JSON }}",
            "LIGHTFORGE_RELEASE_CORPUS_MANIFEST_JSON: ${{ secrets.LIGHTFORGE_RELEASE_CORPUS_MANIFEST_JSON }}",
            "LIGHTFORGE_RELEASE_POLICY_SHA256: ${{ secrets.LIGHTFORGE_RELEASE_POLICY_SHA256 }}",
        ):
            self.assertIn(secret, text)
        self.assertIn("--locked-corpus-manifest gate/trusted/locked-corpus-manifest.json", text)
        self.assertIn("--policy gate/trusted/performance-gate-policy.json", text)
        self.assertIn('--trusted-release-policy-sha256 "$LIGHTFORGE_RELEASE_POLICY_SHA256"', text)
        self.assertNotIn("gate/candidate/locked-corpus-manifest.json", text)
        self.assertNotIn("gate/candidate/performance-gate-policy.json", text)

    def test_all_actions_references_are_immutable_commit_shas(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        # Match both shorthand ``- uses:`` and a conditional step's subsequent
        # indented ``uses:`` field. Otherwise a tag can hide behind ``if:``.
        refs = re.findall(r"^\s*(?:-\s*)?uses: ([^@\s]+)@([^\s]+)\s*$", text, flags=re.MULTILINE)
        self.assertGreaterEqual(len(refs), 4)
        self.assertEqual(
            {
                "actions/checkout",
                "actions/setup-python",
                "actions/download-artifact",
                "actions/upload-artifact",
            },
            {action for action, _ in refs},
        )
        for action, revision in refs:
            self.assertRegex(revision, r"^[0-9a-f]{40}$", f"{action} is not pinned to a full immutable SHA")


if __name__ == "__main__":
    unittest.main()
