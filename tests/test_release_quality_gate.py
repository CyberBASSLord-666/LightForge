import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("release_quality_gate", ROOT / "tools/release_quality_gate.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


COMMIT = "a" * 40
TREE = "b" * 40
BASELINE_COMMIT = "c" * 40
BASELINE_TREE = "d" * 40


def report():
    return {
        "status": "PASS_TARGET",
        "production_ready": True,
        "quality_regressions_detected": False,
        "blockers": [],
        "release_profile": {"mode": "release"},
        "release_policy_authority": {"verified": True},
    }


def run(run_id, commit, workflow):
    return {
        "id": run_id,
        "status": "completed",
        "conclusion": "success",
        "head_sha": commit,
        "head_repository": {"full_name": gate.REPOSITORY},
        "path": workflow,
        "event": "workflow_dispatch",
    }


def git_commit(tree):
    return {"tree": {"sha": tree}}


class ReleaseQualityGateTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.version = {"name": "2.2.5", "code": 20205}
        self.report = report()
        self.report_path = self.root / "quality-gate-report.json"
        self.report_path.write_text(json.dumps(self.report, sort_keys=True, indent=2) + "\n")
        self.baseline_benchmark = self.root / "baseline.json"
        self.candidate_benchmark = self.root / "candidate.json"
        self.baseline_benchmark.write_text('{"baseline":true}\n')
        self.candidate_benchmark.write_text('{"candidate":true}\n')
        self.baseline_run = run(101, BASELINE_COMMIT, ".github/workflows/benchmark.yml")
        self.candidate_run = run(202, COMMIT, ".github/workflows/benchmark.yml")

    def tearDown(self):
        self.temporary.cleanup()

    def provenance(self):
        return gate.build_provenance(
            report=self.report,
            report_sha256=gate.sha256_file(self.report_path),
            version=self.version,
            source_commit=COMMIT,
            source_tree_sha=TREE,
            ref="refs/heads/main",
            ref_protected=True,
            quality_run_id=303,
            baseline_run=self.baseline_run,
            baseline_commit=git_commit(BASELINE_TREE),
            baseline_artifact="baseline-benchmark",
            baseline_benchmark=self.baseline_benchmark,
            candidate_run=self.candidate_run,
            candidate_commit=git_commit(TREE),
            candidate_artifact="candidate-benchmark",
            candidate_benchmark=self.candidate_benchmark,
        )

    def test_pass_target_provenance_binds_release_commit_tree_and_artifacts(self):
        provenance = self.provenance()
        result = gate.validate_publication_evidence(
            self.report,
            provenance,
            version=self.version,
            source_commit=COMMIT,
            source_tree_sha=TREE,
            quality_run=run(303, COMMIT, gate.QUALITY_WORKFLOW),
            quality_commit=git_commit(TREE),
            release_candidate_run=run(404, COMMIT, gate.RELEASE_WORKFLOW),
            release_candidate_commit=git_commit(TREE),
            report_sha256=gate.sha256_file(self.report_path),
        )
        self.assertEqual(result["quality_gate_run_id"], 303)
        self.assertEqual(result["candidate_benchmark_artifact"], "candidate-benchmark")
        self.assertEqual(result["report_sha256"], gate.sha256_file(self.report_path))

    def test_rejects_non_authoritative_report_and_wrong_commit_or_tree(self):
        bad = report()
        bad["production_ready"] = False
        with self.assertRaisesRegex(ValueError, "production_ready"):
            gate.build_provenance(
                report=bad, report_sha256=gate.sha256_file(self.report_path), version=self.version, source_commit=COMMIT, source_tree_sha=TREE,
                ref="refs/heads/main", ref_protected=True, quality_run_id=303,
                baseline_run=self.baseline_run, baseline_commit=git_commit(BASELINE_TREE), baseline_artifact="baseline-benchmark", baseline_benchmark=self.baseline_benchmark,
                candidate_run=self.candidate_run, candidate_commit=git_commit(TREE), candidate_artifact="candidate-benchmark", candidate_benchmark=self.candidate_benchmark,
            )
        provenance = self.provenance()
        wrong = run(303, "e" * 40, gate.QUALITY_WORKFLOW)
        with self.assertRaisesRegex(ValueError, "not on the release source"):
            gate.validate_publication_evidence(
                self.report, provenance, version=self.version, source_commit=COMMIT, source_tree_sha=TREE,
                quality_run=wrong, quality_commit=git_commit(TREE),
                release_candidate_run=run(404, COMMIT, gate.RELEASE_WORKFLOW), release_candidate_commit=git_commit(TREE),
                report_sha256=gate.sha256_file(self.report_path),
            )
        with self.assertRaisesRegex(ValueError, "not on the release source"):
            gate.validate_publication_evidence(
                self.report, provenance, version=self.version, source_commit=COMMIT, source_tree_sha=TREE,
                quality_run=run(303, COMMIT, gate.QUALITY_WORKFLOW), quality_commit=git_commit("f" * 40),
                release_candidate_run=run(404, COMMIT, gate.RELEASE_WORKFLOW), release_candidate_commit=git_commit(TREE),
                report_sha256=gate.sha256_file(self.report_path),
            )

    def test_release_policy_requires_explicit_source_pinned_nonperformance_coverage(self):
        policy = {
            "schema_version": 1,
            "release": self.version,
            "source_commit": COMMIT,
            "source_tree_sha": TREE,
            "requirement": "not_required",
            "classification": "non-performance",
            "reason": "Documentation-only publication metadata correction.",
        }
        self.assertEqual(gate.validate_release_policy(policy, version=self.version, source_commit=COMMIT, source_tree_sha=TREE)["requirement"], "not_required")
        policy["classification"] = "performance"
        with self.assertRaisesRegex(ValueError, "disagree"):
            gate.validate_release_policy(policy, version=self.version, source_commit=COMMIT, source_tree_sha=TREE)


if __name__ == "__main__":
    unittest.main()
