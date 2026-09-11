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


def performance_declaration(version):
    return {
        "schema_version": 1,
        "release": version,
        "requirement": "performance_quality_gate",
        "classification": "performance",
        "reason": "Music-analysis and choreography behavior changed in this candidate.",
    }


class ReleaseQualityGateTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.version = {"name": "2.2.5", "code": 20205}
        self.declaration = performance_declaration(self.version)
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
            release_declaration=self.declaration,
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
            source_declaration=self.declaration,
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
        self.assertEqual(
            provenance["release_declaration"]["sha256"],
            gate.sha256_canonical_json(self.declaration),
        )

    def test_rejects_non_authoritative_report_and_wrong_commit_or_tree(self):
        bad = report()
        bad["production_ready"] = False
        with self.assertRaisesRegex(ValueError, "production_ready"):
            gate.build_provenance(
                report=bad, report_sha256=gate.sha256_file(self.report_path), version=self.version, release_declaration=self.declaration, source_commit=COMMIT, source_tree_sha=TREE,
                ref="refs/heads/main", ref_protected=True, quality_run_id=303,
                baseline_run=self.baseline_run, baseline_commit=git_commit(BASELINE_TREE), baseline_artifact="baseline-benchmark", baseline_benchmark=self.baseline_benchmark,
                candidate_run=self.candidate_run, candidate_commit=git_commit(TREE), candidate_artifact="candidate-benchmark", candidate_benchmark=self.candidate_benchmark,
            )
        provenance = self.provenance()
        wrong = run(303, "e" * 40, gate.QUALITY_WORKFLOW)
        with self.assertRaisesRegex(ValueError, "not on the release source"):
            gate.validate_publication_evidence(
                self.report, provenance, version=self.version, source_declaration=self.declaration, source_commit=COMMIT, source_tree_sha=TREE,
                quality_run=wrong, quality_commit=git_commit(TREE),
                release_candidate_run=run(404, COMMIT, gate.RELEASE_WORKFLOW), release_candidate_commit=git_commit(TREE),
                report_sha256=gate.sha256_file(self.report_path),
            )

    def test_rejects_declaration_tampering_and_nonperformance_pass_receipts(self):
        provenance = self.provenance()
        changed = dict(self.declaration, reason="A materially different release classification explanation.")
        with self.assertRaisesRegex(ValueError, "declaration differs"):
            gate.validate_publication_evidence(
                self.report,
                provenance,
                version=self.version,
                source_declaration=changed,
                source_commit=COMMIT,
                source_tree_sha=TREE,
                quality_run=run(303, COMMIT, gate.QUALITY_WORKFLOW),
                quality_commit=git_commit(TREE),
                release_candidate_run=run(404, COMMIT, gate.RELEASE_WORKFLOW),
                release_candidate_commit=git_commit(TREE),
                report_sha256=gate.sha256_file(self.report_path),
            )
        nonperformance = {
            "schema_version": 1,
            "release": self.version,
            "requirement": "not_required",
            "classification": "non-performance",
            "reason": "Documentation-only publication metadata correction.",
        }
        with self.assertRaisesRegex(ValueError, "requires a performance"):
            gate.build_provenance(
                report=self.report,
                report_sha256=gate.sha256_file(self.report_path),
                version=self.version,
                release_declaration=nonperformance,
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
        with self.assertRaisesRegex(ValueError, "not on the release source"):
            gate.validate_publication_evidence(
                self.report, provenance, version=self.version, source_declaration=self.declaration, source_commit=COMMIT, source_tree_sha=TREE,
                quality_run=run(303, COMMIT, gate.QUALITY_WORKFLOW), quality_commit=git_commit("f" * 40),
                release_candidate_run=run(404, COMMIT, gate.RELEASE_WORKFLOW), release_candidate_commit=git_commit(TREE),
                report_sha256=gate.sha256_file(self.report_path),
            )

    def test_declaration_and_later_receipt_explicitly_bind_nonperformance_coverage(self):
        declaration = {
            "schema_version": 1,
            "release": self.version,
            "requirement": "not_required",
            "classification": "non-performance",
            "reason": "Documentation-only publication metadata correction.",
        }
        self.assertEqual(gate.validate_release_declaration(declaration, version=self.version)["requirement"], "not_required")
        receipt = {
            "schema_version": 1,
            "source_commit": COMMIT,
            "source_tree_sha": TREE,
            "declaration_sha256": gate.sha256_canonical_json(declaration),
        }
        self.assertEqual(
            gate.validate_declaration_receipt(
                receipt,
                version=self.version,
                source_commit=COMMIT,
                source_tree_sha=TREE,
                declaration=declaration,
            )["source_tree_sha"],
            TREE,
        )
        receipt["declaration_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "digest differs"):
            gate.validate_declaration_receipt(
                receipt,
                version=self.version,
                source_commit=COMMIT,
                source_tree_sha=TREE,
                declaration=declaration,
            )
        declaration["classification"] = "performance"
        with self.assertRaisesRegex(ValueError, "disagree"):
            gate.validate_release_declaration(declaration, version=self.version)


if __name__ == "__main__":
    unittest.main()
