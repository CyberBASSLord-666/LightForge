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
            "baseline_repository:",
            "baseline_run_id:",
            "candidate_artifact:",
            "candidate_repository:",
            "candidate_run_id:",
        ):
            self.assertRegex(text, re.escape(name) + r"\n\s+description:.*\n\s+required: true")
        self.assertIn("repository: ${{ inputs.baseline_repository }}", text)
        self.assertIn("repository: ${{ inputs.candidate_repository }}", text)
        self.assertIn("run-id: ${{ inputs.baseline_run_id }}", text)
        self.assertIn("run-id: ${{ inputs.candidate_run_id }}", text)
        self.assertIn("--locked-corpus-manifest gate/candidate/locked-corpus-manifest.json", text)
        self.assertIn("test -f gate/candidate/locked-corpus-manifest.json", text)

    def test_all_actions_references_are_immutable_commit_shas(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        refs = re.findall(r"^\s*- uses: ([^@\s]+)@([^\s]+)\s*$", text, flags=re.MULTILINE)
        self.assertGreaterEqual(len(refs), 4)
        for action, revision in refs:
            self.assertRegex(revision, r"^[0-9a-f]{40}$", f"{action} is not pinned to a full immutable SHA")


if __name__ == "__main__":
    unittest.main()
