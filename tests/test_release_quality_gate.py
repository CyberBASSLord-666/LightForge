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
        "head_branch": "main",
    }


def git_commit(tree):
    return {"tree": {"sha": tree}}


def artifact(artifact_id, name, run_id, commit, digest):
    return {
        "id": artifact_id,
        "name": name,
        "expired": False,
        "size_in_bytes": 123,
        "digest": "sha256:" + digest,
        "workflow_run": {"id": run_id, "head_sha": commit, "head_branch": "main"},
    }


def performance_declaration(version):
    return {
        "schema_version": 1,
        "release": version,
        "requirement": "performance_quality_gate",
        "classification": "performance",
        "reason": "Music-analysis and choreography behavior changed in this candidate.",
    }


def raw_change(status, path, old_mode="100644", new_mode="100644"):
    old_sha = "0" * 40 if status == "A" else "1" * 40
    new_sha = "0" * 40 if status == "D" else "2" * 40
    return f":{old_mode} {new_mode} {old_sha} {new_sha} {status}\0{path}\0".encode()


def scope_baseline():
    return {
        "tag": "v2.2.4",
        "target_commit": "3" * 40,
        "source_commit": COMMIT,
        "source_tree_sha": TREE,
        "version": {"name": "2.2.4", "code": 20204},
    }


def safe_nonperformance_diff(version):
    declaration = "releases/v" + version["name"] + "/quality-gate-declaration.json"
    return b"".join([
        raw_change("M", "README.md"),
        raw_change("M", "version.json"),
        raw_change("M", "web/version.js"),
        raw_change("A", declaration, "000000", "100644"),
    ])


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
        self.baseline_run = run(101, BASELINE_COMMIT, gate.BENCHMARK_WORKFLOW)
        self.candidate_run = run(202, COMMIT, gate.BENCHMARK_WORKFLOW)
        self.baseline_artifact_record = artifact(501, "baseline-benchmark", 101, BASELINE_COMMIT, "1" * 64)
        self.candidate_artifact_record = artifact(502, "candidate-benchmark", 202, COMMIT, "2" * 64)

    def tearDown(self):
        self.temporary.cleanup()

    def test_automated_only_policy_is_explicit_and_limited_to_authorized_releases(self):
        declaration = dict(self.declaration, requirement="automated_verification_only")
        self.assertEqual(gate.validate_release_declaration(declaration, version=self.version), declaration)
        next_version = {"name": "2.3.0", "code": 20300}
        next_declaration = dict(declaration, release=next_version)
        self.assertEqual(gate.validate_release_declaration(next_declaration, version=next_version), next_declaration)
        for version in (
            {"name": "2.2.6", "code": 20206},
            {"name": "2.2.5", "code": 20206},
            {"name": "2.2.4", "code": 20204},
            {"name": "2.3.0", "code": 20205},
            {"name": "2.3.1", "code": 20301},
        ):
            with self.subTest(version=version):
                with self.assertRaisesRegex(ValueError, "authorized only"):
                    gate.validate_release_declaration(dict(declaration, release=version), version=version)
        with self.assertRaisesRegex(ValueError, "classification disagree"):
            gate.validate_release_declaration(dict(declaration, classification="non-performance"), version=self.version)
        with self.assertRaisesRegex(ValueError, "unexpected or missing fields"):
            gate.validate_release_declaration(dict(declaration, production_ready=True), version=self.version)
        for schema in (True, 1.0, "1"):
            with self.subTest(schema=schema):
                with self.assertRaisesRegex(ValueError, "schema is unsupported"):
                    gate.validate_release_declaration(dict(declaration, schema_version=schema), version=self.version)
                with self.assertRaisesRegex(ValueError, "schema is unsupported"):
                    gate.validate_declaration_receipt(
                        {"schema_version": schema, "source_commit": COMMIT, "source_tree_sha": TREE,
                         "declaration_sha256": gate.sha256_canonical_json(declaration)},
                        version=self.version, source_commit=COMMIT, source_tree_sha=TREE, declaration=declaration,
                    )

    def test_automated_only_cannot_generate_a_pass_target_qualification_receipt(self):
        for version in ({"name": "2.2.5", "code": 20205}, {"name": "2.3.0", "code": 20300}):
            with self.subTest(version=version):
                self.version = version
                self.declaration.update(release=version, requirement="automated_verification_only")
                with self.assertRaisesRegex(ValueError, "PASS_TARGET provenance requires"):
                    self.provenance()

    def test_230_publication_declaration_requires_exact_source_and_digest_binding(self):
        version = {"name": "2.3.0", "code": 20300}
        declaration = json.loads((ROOT / "releases/v2.3.0/quality-gate-declaration.json").read_text())
        self.assertEqual(gate.validate_release_declaration(declaration, version=version), declaration)
        receipt = {"schema_version": 1, "source_commit": COMMIT, "source_tree_sha": TREE,
                   "declaration_sha256": gate.sha256_canonical_json(declaration)}
        kwargs = dict(version=version, source_commit=COMMIT, source_tree_sha=TREE, declaration=declaration)
        self.assertEqual(gate.validate_declaration_receipt(receipt, **kwargs), receipt)
        for field, value in (("source_commit", "f" * 40), ("source_tree_sha", "e" * 40),
                             ("declaration_sha256", "d" * 64)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                gate.validate_declaration_receipt(dict(receipt, **{field: value}), **kwargs)

    def test_automated_only_cannot_reuse_a_performance_qualification_receipt(self):
        provenance = self.provenance()
        declaration = dict(self.declaration, requirement="automated_verification_only")
        with self.assertRaisesRegex(ValueError, "performance quality provenance cannot authorize"):
            gate.validate_publication_evidence(
                self.report, provenance, version=self.version, source_declaration=declaration,
                source_commit=COMMIT, source_tree_sha=TREE,
                quality_run=run(303, COMMIT, gate.QUALITY_WORKFLOW), quality_commit=git_commit(TREE),
                baseline_run=self.baseline_run, baseline_commit=git_commit(BASELINE_TREE),
                baseline_artifact_record=self.baseline_artifact_record,
                candidate_run=self.candidate_run, candidate_commit=git_commit(TREE),
                candidate_artifact_record=self.candidate_artifact_record,
                release_candidate_run=run(404, COMMIT, gate.RELEASE_WORKFLOW),
                release_candidate_commit=git_commit(TREE), report_sha256=gate.sha256_file(self.report_path),
            )

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
            baseline_artifact_record=self.baseline_artifact_record,
            baseline_benchmark=self.baseline_benchmark,
            candidate_run=self.candidate_run,
            candidate_commit=git_commit(TREE),
            candidate_artifact="candidate-benchmark",
            candidate_artifact_record=self.candidate_artifact_record,
            candidate_benchmark=self.candidate_benchmark,
            release_candidate_run=run(404, COMMIT, gate.RELEASE_WORKFLOW),
            release_candidate_commit=git_commit(TREE),
            release_candidate_artifact="lightforge-2.2.5-ci-candidate",
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
            baseline_run=self.baseline_run,
            baseline_commit=git_commit(BASELINE_TREE),
            baseline_artifact_record=self.baseline_artifact_record,
            candidate_run=self.candidate_run,
            candidate_commit=git_commit(TREE),
            candidate_artifact_record=self.candidate_artifact_record,
            release_candidate_run=run(404, COMMIT, gate.RELEASE_WORKFLOW),
            release_candidate_commit=git_commit(TREE),
            report_sha256=gate.sha256_file(self.report_path),
        )
        self.assertEqual(result["quality_gate_run_id"], 303)
        self.assertEqual(result["candidate_benchmark_artifact"], "candidate-benchmark")
        self.assertEqual(result["candidate_benchmark_artifact_id"], 502)
        self.assertEqual(result["candidate_benchmark_artifact_digest"], "2" * 64)
        self.assertEqual(result["release_candidate_run_id"], 404)
        self.assertEqual(result["release_candidate_artifact"], "lightforge-2.2.5-ci-candidate")
        self.assertEqual(result["report_sha256"], gate.sha256_file(self.report_path))
        self.assertEqual(
            provenance["release_declaration"]["sha256"],
            gate.sha256_canonical_json(self.declaration),
        )
        provenance["release_candidate"]["artifact"] = "other-artifact"
        with self.assertRaisesRegex(ValueError, "artifact being published"):
            gate.validate_publication_evidence(
                self.report,
                provenance,
                version=self.version,
                source_declaration=self.declaration,
                source_commit=COMMIT,
                source_tree_sha=TREE,
                quality_run=run(303, COMMIT, gate.QUALITY_WORKFLOW),
                quality_commit=git_commit(TREE),
                baseline_run=self.baseline_run,
                baseline_commit=git_commit(BASELINE_TREE),
                baseline_artifact_record=self.baseline_artifact_record,
                candidate_run=self.candidate_run,
                candidate_commit=git_commit(TREE),
                candidate_artifact_record=self.candidate_artifact_record,
                release_candidate_run=run(404, COMMIT, gate.RELEASE_WORKFLOW),
                release_candidate_commit=git_commit(TREE),
                report_sha256=gate.sha256_file(self.report_path),
            )

    def test_rejects_non_authoritative_report_and_wrong_commit_or_tree(self):
        bad = report()
        bad["production_ready"] = False
        with self.assertRaisesRegex(ValueError, "production_ready"):
            gate.build_provenance(
                report=bad, report_sha256=gate.sha256_file(self.report_path), version=self.version, release_declaration=self.declaration, source_commit=COMMIT, source_tree_sha=TREE,
                ref="refs/heads/main", ref_protected=True, quality_run_id=303,
                baseline_run=self.baseline_run, baseline_commit=git_commit(BASELINE_TREE), baseline_artifact="baseline-benchmark", baseline_artifact_record=self.baseline_artifact_record, baseline_benchmark=self.baseline_benchmark,
                candidate_run=self.candidate_run, candidate_commit=git_commit(TREE), candidate_artifact="candidate-benchmark", candidate_artifact_record=self.candidate_artifact_record, candidate_benchmark=self.candidate_benchmark,
                release_candidate_run=run(404, COMMIT, gate.RELEASE_WORKFLOW), release_candidate_commit=git_commit(TREE), release_candidate_artifact="lightforge-2.2.5-ci-candidate",
            )
        provenance = self.provenance()
        wrong = run(303, "e" * 40, gate.QUALITY_WORKFLOW)
        with self.assertRaisesRegex(ValueError, "not on the release source"):
            gate.validate_publication_evidence(
                self.report, provenance, version=self.version, source_declaration=self.declaration, source_commit=COMMIT, source_tree_sha=TREE,
                quality_run=wrong, quality_commit=git_commit(TREE),
                baseline_run=self.baseline_run, baseline_commit=git_commit(BASELINE_TREE), baseline_artifact_record=self.baseline_artifact_record,
                candidate_run=self.candidate_run, candidate_commit=git_commit(TREE), candidate_artifact_record=self.candidate_artifact_record,
                release_candidate_run=run(404, COMMIT, gate.RELEASE_WORKFLOW), release_candidate_commit=git_commit(TREE),
                report_sha256=gate.sha256_file(self.report_path),
            )

    def test_rejects_arbitrary_successful_workflow_and_wrong_live_artifact(self):
        arbitrary = run(202, COMMIT, ".github/workflows/unrelated-success.yml")
        with self.assertRaisesRegex(ValueError, "canonical locked benchmark workflow"):
            gate.build_provenance(
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
                baseline_artifact_record=self.baseline_artifact_record,
                baseline_benchmark=self.baseline_benchmark,
                candidate_run=arbitrary,
                candidate_commit=git_commit(TREE),
                candidate_artifact="candidate-benchmark",
                candidate_artifact_record=self.candidate_artifact_record,
                candidate_benchmark=self.candidate_benchmark,
                release_candidate_run=run(404, COMMIT, gate.RELEASE_WORKFLOW),
                release_candidate_commit=git_commit(TREE),
                release_candidate_artifact="lightforge-2.2.5-ci-candidate",
            )
        wrong_name = dict(self.candidate_artifact_record, name="other-artifact")
        with self.assertRaisesRegex(ValueError, "name differs"):
            gate.build_provenance(
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
                baseline_artifact_record=self.baseline_artifact_record,
                baseline_benchmark=self.baseline_benchmark,
                candidate_run=self.candidate_run,
                candidate_commit=git_commit(TREE),
                candidate_artifact="candidate-benchmark",
                candidate_artifact_record=wrong_name,
                candidate_benchmark=self.candidate_benchmark,
                release_candidate_run=run(404, COMMIT, gate.RELEASE_WORKFLOW),
                release_candidate_commit=git_commit(TREE),
                release_candidate_artifact="lightforge-2.2.5-ci-candidate",
            )
        provenance = self.provenance()
        replacement = dict(self.candidate_artifact_record, digest="sha256:" + "9" * 64)
        with self.assertRaisesRegex(ValueError, "differs from the live artifact identity"):
            gate.validate_publication_evidence(
                self.report,
                provenance,
                version=self.version,
                source_declaration=self.declaration,
                source_commit=COMMIT,
                source_tree_sha=TREE,
                quality_run=run(303, COMMIT, gate.QUALITY_WORKFLOW),
                quality_commit=git_commit(TREE),
                baseline_run=self.baseline_run,
                baseline_commit=git_commit(BASELINE_TREE),
                baseline_artifact_record=self.baseline_artifact_record,
                candidate_run=self.candidate_run,
                candidate_commit=git_commit(TREE),
                candidate_artifact_record=replacement,
                release_candidate_run=run(404, COMMIT, gate.RELEASE_WORKFLOW),
                release_candidate_commit=git_commit(TREE),
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
                baseline_run=self.baseline_run,
                baseline_commit=git_commit(BASELINE_TREE),
                baseline_artifact_record=self.baseline_artifact_record,
                candidate_run=self.candidate_run,
                candidate_commit=git_commit(TREE),
                candidate_artifact_record=self.candidate_artifact_record,
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
                baseline_artifact_record=self.baseline_artifact_record,
                baseline_benchmark=self.baseline_benchmark,
                candidate_run=self.candidate_run,
                candidate_commit=git_commit(TREE),
                candidate_artifact="candidate-benchmark",
                candidate_artifact_record=self.candidate_artifact_record,
                candidate_benchmark=self.candidate_benchmark,
                release_candidate_run=run(404, COMMIT, gate.RELEASE_WORKFLOW),
                release_candidate_commit=git_commit(TREE),
                release_candidate_artifact="lightforge-2.2.5-ci-candidate",
            )
        with self.assertRaisesRegex(ValueError, "not on the release source"):
            gate.validate_publication_evidence(
                self.report, provenance, version=self.version, source_declaration=self.declaration, source_commit=COMMIT, source_tree_sha=TREE,
                quality_run=run(303, COMMIT, gate.QUALITY_WORKFLOW), quality_commit=git_commit("f" * 40),
                baseline_run=self.baseline_run, baseline_commit=git_commit(BASELINE_TREE), baseline_artifact_record=self.baseline_artifact_record,
                candidate_run=self.candidate_run, candidate_commit=git_commit(TREE), candidate_artifact_record=self.candidate_artifact_record,
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

    def test_full_tree_scope_allows_only_regular_docs_and_release_identity(self):
        scope = gate.derive_release_scope(
            base_release=scope_baseline(),
            source_commit="4" * 40,
            source_tree_sha="5" * 40,
            version=self.version,
            raw_tree_diff=safe_nonperformance_diff(self.version),
            generated_web_version_valid=True,
        )
        self.assertEqual(scope["classification"], "non-performance")
        self.assertEqual(scope["base_release"]["source_commit"], COMMIT)
        self.assertEqual(scope["source"], {"commit": "4" * 40, "tree_sha": "5" * 40})
        without_digest = dict(scope)
        digest = without_digest.pop("sha256")
        self.assertEqual(digest, gate.sha256_canonical_json(without_digest))

    def test_scope_forces_gate_for_runtime_security_and_unknown_paths(self):
        for path in (
            "web/analysis/worker.js",
            "android/src/com/cyberbasslord/lightforge/MainActivity.java",
            "web/analysis/models/deux/manifest.json",
            "tools/publish_github_release.py",
            ".github/workflows/publish-release.yml",
            "tests/test_release_quality_gate.py",
            "qa/performance-gate-policy.json",
            "package-lock.json",
            "SOURCE_MANIFEST.json",
        ):
            with self.subTest(path=path):
                scope = gate.derive_release_scope(
                    base_release=scope_baseline(),
                    source_commit="4" * 40,
                    source_tree_sha="5" * 40,
                    version=self.version,
                    raw_tree_diff=safe_nonperformance_diff(self.version) + raw_change("M", path),
                    generated_web_version_valid=True,
                )
                self.assertEqual(scope["classification"], "performance")

    def test_scope_rejects_mode_changes_and_cannot_hide_runtime_rename(self):
        cases = {
            "symlink": safe_nonperformance_diff(self.version) + raw_change("T", "docs/guide.md", "100644", "120000"),
            "executable": safe_nonperformance_diff(self.version) + raw_change("M", "docs/guide.md", "100644", "100755"),
            "submodule": safe_nonperformance_diff(self.version) + raw_change("T", "docs/guide.md", "100644", "160000"),
            "runtime-to-docs": safe_nonperformance_diff(self.version)
            + raw_change("D", "web/analysis/worker.js", "100644", "000000")
            + raw_change("A", "docs/worker.md", "000000", "100644"),
        }
        for name, diff in cases.items():
            with self.subTest(name=name):
                scope = gate.derive_release_scope(
                    base_release=scope_baseline(),
                    source_commit="4" * 40,
                    source_tree_sha="5" * 40,
                    version=self.version,
                    raw_tree_diff=diff,
                    generated_web_version_valid=True,
                )
                self.assertEqual(scope["classification"], "performance")

    def test_scope_fails_closed_on_missing_identity_or_invalid_generated_version(self):
        missing_declaration = b"".join([
            raw_change("M", "README.md"),
            raw_change("M", "version.json"),
        ])
        for diff, valid in (
            (missing_declaration, True),
            (safe_nonperformance_diff(self.version), False),
        ):
            with self.subTest(valid=valid):
                scope = gate.derive_release_scope(
                    base_release=scope_baseline(),
                    source_commit="4" * 40,
                    source_tree_sha="5" * 40,
                    version=self.version,
                    raw_tree_diff=diff,
                    generated_web_version_valid=valid,
                )
                self.assertEqual(scope["classification"], "performance")
        bad_base = scope_baseline()
        bad_base["version"] = self.version
        bad_base["tag"] = "v" + self.version["name"]
        with self.assertRaisesRegex(ValueError, "not older"):
            gate.derive_release_scope(
                base_release=bad_base,
                source_commit="4" * 40,
                source_tree_sha="5" * 40,
                version=self.version,
                raw_tree_diff=safe_nonperformance_diff(self.version),
                generated_web_version_valid=True,
            )

    def test_raw_tree_parser_rejects_rename_and_malformed_nul_streams(self):
        with self.assertRaisesRegex(ValueError, "unsupported status"):
            gate.parse_raw_tree_diff(
                b":" + b"100644 100644 " + b"1" * 40 + b" " + b"2" * 40 + b" R100\0docs/old.md\0"
            )
        with self.assertRaisesRegex(ValueError, "NUL-delimited"):
            gate.parse_raw_tree_diff(b":100644 100644 " + b"1" * 40)


if __name__ == "__main__":
    unittest.main()
