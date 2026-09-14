import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/performance-quality-gate.yml"


class PerformanceQualityGateWorkflowTest(unittest.TestCase):
    def test_pull_requests_always_run_the_quality_contract(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("  pull_request:\n  workflow_dispatch:", text)
        self.assertNotIn("  pull_request:\n    paths:", text)

    def test_dispatch_comparison_has_explicit_artifact_provenance_and_permissions(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("actions: read", text)
        for name in (
            "baseline_artifact:",
            "baseline_run_id:",
            "candidate_artifact:",
            "candidate_run_id:",
            "release_candidate_run_id:",
            "release_version:",
        ):
            self.assertRegex(text, re.escape(name) + r"\n\s+description:.*\n\s+required: false")
        self.assertGreaterEqual(text.count("repository: ${{ github.repository }}"), 3)
        self.assertNotIn("baseline_repository:", text)
        self.assertNotIn("candidate_repository:", text)
        self.assertIn("run-id: ${{ inputs.baseline_run_id }}", text)
        self.assertIn("run-id: ${{ inputs.candidate_run_id }}", text)
        self.assertIn("inputs.baseline_artifact != ''", text)
        self.assertIn("inputs.release_version != ''", text)
        self.assertIn("environment: lightforge-release-quality", text)
        self.assertIn('test "$GITHUB_REF" = "refs/heads/main"', text)
        self.assertIn('test "$LIGHTFORGE_REF_PROTECTED" = "true"', text)
        for secret in (
            "LIGHTFORGE_RELEASE_POLICY_JSON: ${{ secrets.LIGHTFORGE_RELEASE_POLICY_JSON }}",
            "LIGHTFORGE_RELEASE_CORPUS_MANIFEST_JSON: ${{ secrets.LIGHTFORGE_RELEASE_CORPUS_MANIFEST_JSON }}",
            "LIGHTFORGE_RELEASE_POLICY_ATTESTATION_JSON: ${{ secrets.LIGHTFORGE_RELEASE_POLICY_ATTESTATION_JSON }}",
        ):
            self.assertIn(secret, text)
        self.assertIn("--locked-corpus-manifest gate/trusted/locked-corpus-manifest.json", text)
        self.assertIn("--policy gate/trusted/performance-gate-policy.json", text)
        self.assertIn(
            "--release-policy-attestation gate/trusted/release-policy-attestation.json",
            text,
        )
        self.assertIn(
            "printf '%s' \"$LIGHTFORGE_RELEASE_POLICY_ATTESTATION_JSON\" > gate/trusted/release-policy-attestation.json",
            text,
        )
        self.assertNotIn("--trusted-release-policy-sha256", text)
        self.assertNotIn("LIGHTFORGE_RELEASE_POLICY_SHA256", text)
        self.assertIn('test -n "$LIGHTFORGE_RELEASE_POLICY_ATTESTATION_JSON"', text)
        self.assertNotIn("gate/candidate/locked-corpus-manifest.json", text)
        self.assertNotIn("gate/candidate/performance-gate-policy.json", text)

    def test_only_protected_locked_runner_can_produce_benchmark_artifacts(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        for name in (
            "benchmark_diagnostics_artifact:",
            "benchmark_diagnostics_run_id:",
            "benchmark_artifact:",
            "benchmark_protocol_id:",
            "benchmark_cache_mode:",
            "benchmark_cache_setup_id:",
            "benchmark_pair_order:",
            "benchmark_thermal_cycle_id:",
            "benchmark_report_side:",
            "benchmark_change_classification:",
            "benchmark_change_id:",
        ):
            self.assertRegex(text, re.escape(name) + r"\n\s+description:.*\n\s+required: false")
        self.assertIn("Aggregate diagnostics with the protected locked runner", text)
        self.assertIn("tools/locked_benchmark_runner.py aggregate", text)
        self.assertIn('--report-side "$BENCHMARK_REPORT_SIDE"', text)
        self.assertIn('--cache-setup-id "$BENCHMARK_CACHE_SETUP_ID"', text)
        self.assertIn('--pair-order "$BENCHMARK_PAIR_ORDER"', text)
        self.assertIn('--thermal-cycle-id "$BENCHMARK_THERMAL_CYCLE_ID"', text)
        self.assertIn('test -n "$BENCHMARK_CACHE_SETUP_ID"', text)
        self.assertIn('test -n "$BENCHMARK_THERMAL_CYCLE_ID"', text)
        self.assertIn('test "$BENCHMARK_PAIR_ORDER" = baseline-first', text)
        self.assertIn("candidate-output-differential.json", text)
        self.assertIn("--reports gate/diagnostics/reports", text)
        self.assertIn("gate/diagnostics/human-perceptual-review.json", text)
        self.assertIn("environment: lightforge-release-quality", text)
        self.assertIn("if-no-files-found: error", text)
        self.assertIn("gh api --paginate", text)
        self.assertIn("expected exactly one baseline benchmark artifact", text)
        self.assertIn("expected exactly one candidate benchmark artifact", text)
        self.assertIn("artifact-ids: ${{ steps.baseline-artifact.outputs.id }}", text)
        self.assertIn("artifact-ids: ${{ steps.candidate-artifact.outputs.id }}", text)
        self.assertNotIn("name: ${{ inputs.baseline_artifact }}\n          path: gate/baseline", text)
        self.assertNotIn("name: ${{ inputs.candidate_artifact }}\n          path: gate/candidate", text)

    def test_pass_target_artifact_records_release_candidate_provenance(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("tools/release_quality_gate.py create-provenance", text)
        self.assertIn("gate/quality-gate-provenance.json", text)
        self.assertIn("--source-commit \"$GITHUB_SHA\"", text)
        self.assertIn("--source-tree-sha \"$(git rev-parse \"$GITHUB_SHA^{tree}\")\"", text)
        self.assertIn("--release-declaration-json \"releases/v$RELEASE_VERSION/quality-gate-declaration.json\"", text)
        self.assertIn('test -f "releases/v$RELEASE_VERSION/quality-gate-declaration.json"', text)
        self.assertIn("--candidate-run-json gate/candidate-run.json", text)
        self.assertIn("--candidate-commit-json gate/candidate-commit.json", text)
        self.assertIn("--candidate-artifact \"$CANDIDATE_ARTIFACT\"", text)
        self.assertIn("--baseline-artifact-json gate/baseline-artifact.json", text)
        self.assertIn("--candidate-artifact-json gate/candidate-artifact.json", text)
        self.assertIn("--candidate-benchmark gate/candidate/benchmark.json", text)
        self.assertIn("--release-candidate-run-json gate/release-candidate-run.json", text)
        self.assertIn("--release-candidate-commit-json gate/release-candidate-commit.json", text)
        self.assertIn("--release-candidate-artifact \"lightforge-$RELEASE_VERSION-ci-candidate\"", text)
        self.assertIn('test "$GITHUB_REF" = "refs/heads/main"', text)
        self.assertIn('test "$LIGHTFORGE_REF_PROTECTED" = "true"', text)
        self.assertIn("--require-production-ready", text)

    def test_manual_dispatch_is_complete_and_jobs_wait_for_unit_contract(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("Reject incomplete manual gate requests", text)
        self.assertIn("manual dispatch must request exactly one complete operation", text)
        self.assertIn('("benchmark aggregation", aggregate)', text)
        self.assertIn('("release comparison", compare)', text)
        self.assertIn('raise SystemExit(f"incomplete manual {name} request")', text)
        self.assertRegex(
            text,
            r"(?ms)^  benchmark:\n.*?^    needs: unit$",
        )
        self.assertRegex(
            text,
            r"(?ms)^  compare:\n.*?^    needs: unit$",
        )

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


    def test_exact_id_benchmark_downloads_are_merged_to_the_direct_compare_paths(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        baseline = text.index("artifact-ids: ${{ steps.baseline-artifact.outputs.id }}")
        candidate = text.index("artifact-ids: ${{ steps.candidate-artifact.outputs.id }}")
        compare = text.index("Compare with protected release policy and corpus")
        baseline_block = text[baseline:candidate]
        candidate_block = text[candidate:compare]
        self.assertIn("path: gate/baseline", baseline_block)
        self.assertIn("merge-multiple: true", baseline_block)
        self.assertIn("path: gate/candidate", candidate_block)
        self.assertIn("merge-multiple: true", candidate_block)
        self.assertIn("test -f gate/baseline/benchmark.json", text[compare:])
        self.assertIn("test -f gate/candidate/benchmark.json", text[compare:])


if __name__ == "__main__":
    unittest.main()
