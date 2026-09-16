import importlib.util
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location("publisher", ROOT / "tools/publish_github_release.py")
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)
GATE_SPEC = importlib.util.spec_from_file_location("release_quality_gate", ROOT / "tools/release_quality_gate.py")
gate = importlib.util.module_from_spec(GATE_SPEC)
GATE_SPEC.loader.exec_module(gate)


COMMIT = "a" * 40
TREE = "b" * 40
VERSION = {"name": "2.2.5", "code": 20205}
BASE_COMMIT = "c" * 40
BASE_TREE = "d" * 40
TARGET_COMMIT = "e" * 40


def nonperformance_declaration():
    return {
        "schema_version": 1,
        "release": VERSION,
        "requirement": "not_required",
        "classification": "non-performance",
        "reason": "Documentation-only publication metadata correction.",
    }


def automated_declaration():
    return dict(
        nonperformance_declaration(),
        requirement="automated_verification_only",
        classification="performance",
        reason="Owner authorized automated verification; comparative performance and musical quality remain unverified.",
    )


def declaration_receipt(declaration):
    return {
        "schema_version": 1,
        "source_commit": COMMIT,
        "source_tree_sha": TREE,
        "declaration_sha256": gate.sha256_canonical_json(declaration),
    }


def nonperformance_scope():
    return {
        "schema_version": 1,
        "kind": "lightforge-release-scope",
        "base_release": {
            "tag": "v2.2.4",
            "target_commit": TARGET_COMMIT,
            "source_commit": BASE_COMMIT,
            "source_tree_sha": BASE_TREE,
            "version": {"name": "2.2.4", "code": 20204},
        },
        "source": {"commit": COMMIT, "tree_sha": TREE},
        "release": VERSION,
        "changes": [],
        "classification": "non-performance",
        "sha256": "f" * 64,
    }


def performance_scope():
    scope = nonperformance_scope()
    scope["classification"] = "performance"
    return scope


class ReleaseQualityPublicationWiringTest(unittest.TestCase):
    def test_automated_only_policy_discloses_unverified_qualification_without_external_calls(self):
        declaration = automated_declaration()
        with patch.object(publisher, "run", return_value=json.dumps(declaration)), \
                patch.object(publisher, "_derive_published_release_scope", return_value=performance_scope()) as scope, \
                patch.object(publisher, "api") as api:
            returned = publisher.verify_release_quality(
                {"quality_gate_policy": declaration_receipt(declaration)}, VERSION, gate.REPOSITORY, {}, COMMIT, TREE
            )
        self.assertEqual(returned["requirement"], "automated_verification_only")
        self.assertEqual(returned["classification"], "performance")
        for field in (
            "qualification_status", "comparative_performance", "performance_target_75_percent_reduction",
            "musical_quality_non_regression", "blinded_human_review", "hardware_energy_and_thermal_measurements",
        ):
            self.assertEqual(returned[field], "unverified")
        self.assertNotIn("production_ready", returned)
        self.assertNotIn("PASS_TARGET", json.dumps(returned))
        scope.assert_called_once_with(gate.REPOSITORY, COMMIT, TREE, VERSION)
        api.assert_not_called()

    def test_automated_only_rejects_forged_receipt_and_unused_quality_run(self):
        declaration = automated_declaration()
        receipt = declaration_receipt(declaration)
        cases = [({"quality_gate_policy": receipt, "quality_gate": {"run_id": 44}}, "unused quality-gate")]
        for field, value in (("source_commit", "9" * 40), ("source_tree_sha", "9" * 40), ("declaration_sha256", "9" * 64)):
            cases.append(({"quality_gate_policy": dict(receipt, **{field: value})}, "source commit|source tree|digest differs"))
        # A receipt for the old strict declaration cannot silently opt out.
        strict = dict(declaration, requirement="performance_quality_gate")
        cases.append(({"quality_gate_policy": declaration_receipt(strict)}, "digest differs"))
        for request, message in cases:
            with self.subTest(request=request), \
                    patch.object(publisher, "run", return_value=json.dumps(declaration)), \
                    patch.object(publisher, "_derive_published_release_scope", return_value=performance_scope()), \
                    patch.object(publisher, "api") as api:
                with self.assertRaisesRegex(ValueError, message):
                    publisher.verify_release_quality(request, VERSION, gate.REPOSITORY, {}, COMMIT, TREE)
                api.assert_not_called()

    def _run_automated_publication(self, *, ci_changes=None, failing_guard=None, bad_delta=False):
        """Exercise main's ordering with small artifacts and isolated external boundaries."""
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            original_cwd = Path.cwd()
            stack.callback(os.chdir, original_cwd)
            candidate_root = root / "candidate"
            candidate_root.mkdir()
            candidate_apk = candidate_root / "LightForge-2.2.5.apk"
            candidate_apk.write_bytes(b"test candidate payload")
            apk_digest = hashlib.sha256(candidate_apk.read_bytes()).hexdigest()
            delta = root / "releases/v2.2.5/signed-apk.delta.json"
            delta.parent.mkdir(parents=True)
            delta.write_text("{}")
            declaration = automated_declaration()
            request = {
                "version": VERSION, "run_id": 404, "source_commit": COMMIT,
                "delta_sha256": "0" * 64 if bad_delta else hashlib.sha256(delta.read_bytes()).hexdigest(),
                "quality_gate_policy": declaration_receipt(declaration),
            }
            (root / "request.json").write_text(json.dumps(request))
            (root / "version.json").write_text(json.dumps(VERSION))
            (root / "RELEASE_NOTES.md").write_text("Qualification remains unverified.\n")
            (root / "release-verification.json").write_text(json.dumps({
                "release": {"sha256": apk_digest},
                "quality_gate": {"status": "PASS_TARGET", "production_ready": True},
            }))
            ci = {
                "id": 404, "run_attempt": 1, "status": "completed", "conclusion": "success",
                "head_sha": COMMIT, "head_repository": {"full_name": gate.REPOSITORY},
                "path": gate.RELEASE_WORKFLOW, "event": "push", "head_branch": "main",
                **(ci_changes or {}),
            }
            def api(path):
                if path.endswith("/actions/runs/404"):
                    return ci
                if path.endswith("/git/commits/" + COMMIT):
                    return {"tree": {"sha": TREE}}
                self.fail("Unexpected API operation: " + path)
            stack.enter_context(patch.object(publisher, "ROOT", root))
            stack.enter_context(patch.dict(os.environ, {
                "GH_REPO": gate.REPOSITORY, "GITHUB_REF": "refs/heads/main", "LIGHTFORGE_REF_PROTECTED": "true",
            }))
            stack.enter_context(patch.object(publisher, "api", side_effect=api))
            stack.enter_context(patch.object(publisher, "run", return_value=json.dumps(declaration)))
            stack.enter_context(patch.object(publisher, "_derive_published_release_scope", return_value=performance_scope()))
            guards = {}
            for name, value in (
                ("require_candidate_worktree", None),
                ("verify_android_release_evidence", {"manifest": {"candidate": {}}, "candidate_root": candidate_root}),
                ("verify_nonandroid_release_evidence", {"verified": True}),
                ("verify_candidate_payload_equivalence", None),
                ("verify_apk", None),
            ):
                guards[name] = stack.enter_context(patch.object(
                    publisher, name, return_value=value,
                    side_effect=ValueError("rejected by " + name) if name == failing_guard else None,
                ))
            stack.enter_context(patch.object(publisher, "verify_physical_validation", return_value={"status": "unverified"}))
            stack.enter_context(patch.object(publisher, "apply_delta", side_effect=lambda source, delta, dest: shutil.copyfile(source, dest)))
            release = {"id": 123, "draft": False, "html_url": "https://example.invalid/release", "assets": [
                {"name": candidate_apk.name, "browser_download_url": "https://example.invalid/apk"},
            ]}
            draft = stack.enter_context(patch.object(publisher, "create_draft", return_value=release))
            stack.enter_context(patch.object(publisher, "asset_plan", return_value=[]))
            stack.enter_context(patch.object(publisher, "update_metadata", return_value=release))
            stack.enter_context(patch.object(publisher, "lookup_release", return_value=release))
            stack.enter_context(patch.object(publisher, "verify_uploaded"))
            stack.enter_context(patch("builtins.print"))
            if failing_guard or ci_changes or bad_delta:
                with self.assertRaises(ValueError):
                    publisher.main([str(root / "request.json")])
                draft.assert_not_called()
                return
            publisher.main([str(root / "request.json")])
            for guard in guards.values():
                guard.assert_called_once()
            draft.assert_called_once()
            receipt = json.loads((root / "release-verification.json").read_text())
            self.assertEqual(receipt["quality_gate"]["qualification_status"], "unverified")
            self.assertNotIn("PASS_TARGET", json.dumps(receipt))
            self.assertNotIn("production_ready", receipt["quality_gate"])

    def test_automated_only_publication_runs_all_mandatory_gates_and_overwrites_false_qualification(self):
        self._run_automated_publication()

    def test_automated_only_does_not_publish_when_any_integrity_or_evidence_gate_fails(self):
        for guard in (
            "require_candidate_worktree", "verify_android_release_evidence", "verify_nonandroid_release_evidence",
            "verify_candidate_payload_equivalence", "verify_apk",
        ):
            with self.subTest(guard=guard):
                self._run_automated_publication(failing_guard=guard)
        self._run_automated_publication(bad_delta=True)

    def test_automated_only_does_not_publish_without_successful_main_source_bound_ci(self):
        for changes in (
            {"conclusion": "failure"}, {"status": "in_progress"}, {"head_sha": "9" * 40},
            {"head_repository": {"full_name": "someone/fork"}}, {"path": "another.yml"},
            {"event": "workflow_dispatch"}, {"head_branch": "feature"},
        ):
            with self.subTest(changes=changes):
                self._run_automated_publication(ci_changes=changes)

    def test_nonperformance_policy_needs_a_derived_prose_only_scope(self):
        declaration = nonperformance_declaration()
        request = {"quality_gate_policy": declaration_receipt(declaration)}
        with patch.object(publisher, "run", return_value=json.dumps(declaration)) as run, \
                patch.object(publisher, "_derive_published_release_scope", return_value=nonperformance_scope()) as scope:
            returned = publisher.verify_release_quality(request, VERSION, "CyberBASSLord-666/LightForge", {}, COMMIT, TREE)
        self.assertEqual(returned["requirement"], "not_required")
        self.assertEqual(returned["classification"], "non-performance")
        self.assertEqual(returned["scope"]["base_release"]["source_commit"], BASE_COMMIT)
        run.assert_called_once_with("git", "show", COMMIT + ":releases/v2.2.5/quality-gate-declaration.json")
        scope.assert_called_once_with("CyberBASSLord-666/LightForge", COMMIT, TREE, VERSION)

    def test_source_authored_nonperformance_label_cannot_waive_runtime_scope(self):
        declaration = nonperformance_declaration()
        request = {"quality_gate_policy": declaration_receipt(declaration)}
        with patch.object(publisher, "run", return_value=json.dumps(declaration)), \
                patch.object(publisher, "_derive_published_release_scope", return_value=performance_scope()):
            with self.assertRaisesRegex(ValueError, "cannot waive"):
                publisher.verify_release_quality(request, VERSION, "CyberBASSLord-666/LightForge", {}, COMMIT, TREE)

    def test_a_source_can_request_the_stricter_gate_for_a_docs_only_scope(self):
        declaration = dict(nonperformance_declaration(), requirement="performance_quality_gate", classification="performance")
        request = {"quality_gate_policy": declaration_receipt(declaration)}
        with patch.object(publisher, "run", return_value=json.dumps(declaration)), \
                patch.object(publisher, "_derive_published_release_scope", return_value=nonperformance_scope()):
            with self.assertRaisesRegex(ValueError, "Performance release requires exactly"):
                publisher.verify_release_quality(request, VERSION, "CyberBASSLord-666/LightForge", {}, COMMIT, TREE)

    def test_policy_is_candidate_bound_and_performance_requires_quality_run(self):
        source = (ROOT / "tools/publish_github_release.py").read_text(encoding="utf-8")
        self.assertIn("source_release_declaration(source_commit, version)", source)
        self.assertIn("validate_declaration_receipt(", source)
        self.assertIn("Performance release requires exactly quality_gate.run_id", source)
        self.assertIn("QUALITY_ARTIFACT", source)
        self.assertIn("validate_publication_evidence(", source)
        self.assertIn("_derive_published_release_scope(repo, source_commit, source_tree_sha, version)", source)
        self.assertIn("--raw", source)
        self.assertIn("--no-renames", source)
        self.assertIn("-z", source)
        self.assertIn("merge-base", source)
        self.assertIn("rev-parse", source)
        self.assertIn("Prior published release has no valid source-bound request ledger", source)
        for path in (
            ".github/workflows/publish-release.yml",
            "tools/publish_github_release.py",
            "tools/release_quality_gate.py",
            "tools/apk_archive.py",
            "tools/apk_delta.py",
            "tools/package_release.py",
            "tools/performance_quality_gate.py",
            "tools/analysis_benchmark_contract.py",
            "tools/locked_benchmark_runner.py",
            "tools/differential_analysis.py",
            ".github/workflows/performance-quality-gate.yml",
        ):
            self.assertIn(repr(path), source)
        declaration = nonperformance_declaration()
        receipt = declaration_receipt(declaration)
        receipt["source_tree_sha"] = "c" * 40
        with patch.object(publisher, "run", return_value=json.dumps(declaration)), \
                patch.object(publisher, "_derive_published_release_scope", return_value=nonperformance_scope()):
            with self.assertRaisesRegex(ValueError, "source tree"):
                publisher.verify_release_quality(
                    {"quality_gate_policy": receipt},
                    VERSION,
                    "CyberBASSLord-666/LightForge",
                    {},
                    COMMIT,
                    TREE,
                )

    def test_publisher_revalidates_exact_benchmark_artifact_id_and_run(self):
        receipt = {
            "run_id": 202,
            "artifact": "candidate-benchmark",
            "artifact_id": 502,
            "artifact_digest": "2" * 64,
            "artifact_size_bytes": 123,
        }
        run_record = {
            "id": 202,
            "status": "completed",
            "conclusion": "success",
            "head_repository": {"full_name": gate.REPOSITORY},
            "head_sha": COMMIT,
            "head_branch": "main",
            "path": gate.BENCHMARK_WORKFLOW,
            "event": "workflow_dispatch",
        }
        artifact = {
            "id": 502,
            "name": "candidate-benchmark",
            "expired": False,
            "size_in_bytes": 123,
            "digest": "sha256:" + "2" * 64,
            "workflow_run": {"id": 202, "head_sha": COMMIT, "head_branch": "main"},
        }

        def api(path):
            if path.endswith("/actions/runs/202"):
                return run_record
            if path.endswith("/git/commits/" + COMMIT):
                return {"tree": {"sha": TREE}}
            if path.endswith("/actions/artifacts/502"):
                return artifact
            self.fail("unexpected API path " + path)

        with patch.object(publisher, "api", side_effect=api):
            live_run, live_commit, live_artifact = publisher._live_benchmark_artifact(
                gate.REPOSITORY, {"candidate": receipt}, "candidate"
            )
        self.assertEqual(live_run["id"], 202)
        self.assertEqual(live_commit["tree"]["sha"], TREE)
        self.assertEqual(live_artifact["digest"], "sha256:" + "2" * 64)

        unrelated = dict(artifact, workflow_run={"id": 999, "head_sha": COMMIT, "head_branch": "main"})
        with patch.object(publisher, "api", side_effect=lambda path: (
            run_record if path.endswith("/actions/runs/202")
            else {"tree": {"sha": TREE}} if path.endswith("/git/commits/" + COMMIT)
            else unrelated if path.endswith("/actions/artifacts/502")
            else self.fail("unexpected API path " + path)
        )):
            with self.assertRaisesRegex(ValueError, "does not belong"):
                publisher._live_benchmark_artifact(gate.REPOSITORY, {"candidate": receipt}, "candidate")

    def test_published_baseline_is_recovered_from_immutable_target_ledger_and_verified_ci(self):
        release = {
            "tag_name": "v2.2.4",
            "draft": False,
            "prerelease": False,
            "target_commitish": TARGET_COMMIT,
        }
        ledger = {
            "version": {"name": "2.2.4", "code": 20204},
            "run_id": 99,
            "source_commit": BASE_COMMIT,
            "delta_sha256": "a" * 64,
        }
        run = {
            "status": "completed",
            "conclusion": "success",
            "head_repository": {"full_name": "CyberBASSLord-666/LightForge"},
            "head_sha": BASE_COMMIT,
            "path": gate.RELEASE_WORKFLOW,
        }
        def api(path):
            if path.endswith("/releases?per_page=100&page=1"):
                return [release]
            if path.endswith("/git/commits/" + TARGET_COMMIT):
                return {"tree": {"sha": "1" * 40}}
            if path.endswith("/actions/runs/99"):
                return run
            if path.endswith("/git/commits/" + BASE_COMMIT):
                return {"tree": {"sha": BASE_TREE}}
            self.fail("unexpected API path " + path)
        def command(*args):
            if args[:3] == ("git", "fetch", "--no-tags"):
                return ""
            self.assertEqual(args, ("git", "show", TARGET_COMMIT + ":releases/v2.2.4/request.json"))
            return json.dumps(ledger)
        with patch.object(publisher, "api", side_effect=api), \
                patch.object(publisher, "run", side_effect=command) as command_mock:
            baseline = publisher._verified_published_baseline("CyberBASSLord-666/LightForge", VERSION)
        self.assertEqual(baseline["target_commit"], TARGET_COMMIT)
        self.assertEqual(baseline["source_commit"], BASE_COMMIT)
        self.assertEqual(baseline["source_tree_sha"], BASE_TREE)
        self.assertEqual(command_mock.call_count, 2)

    def test_baseline_fails_closed_without_a_prior_published_release_or_valid_ledger(self):
        with patch.object(publisher, "api", return_value=[]):
            with self.assertRaisesRegex(ValueError, "No prior canonical"):
                publisher._verified_published_baseline("CyberBASSLord-666/LightForge", VERSION)
        release = {
            "tag_name": "v2.2.4",
            "draft": False,
            "prerelease": False,
            "target_commitish": TARGET_COMMIT,
        }
        def api(path):
            if path.endswith("/releases?per_page=100&page=1"):
                return [release]
            if path.endswith("/git/commits/" + TARGET_COMMIT):
                return {"tree": {"sha": "1" * 40}}
            self.fail("unexpected API path " + path)
        def missing_ledger(*args):
            if args[:3] == ("git", "fetch", "--no-tags"):
                return ""
            raise subprocess.CalledProcessError(1, ["git", "show"])
        with patch.object(publisher, "api", side_effect=api), \
                patch.object(publisher, "run", side_effect=missing_ledger):
            with self.assertRaisesRegex(ValueError, "source-bound request ledger"):
                publisher._verified_published_baseline("CyberBASSLord-666/LightForge", VERSION)

        ledger = {
            "version": {"name": "2.2.4", "code": 20204},
            "run_id": 99,
            "source_commit": BASE_COMMIT,
            "delta_sha256": "a" * 64,
        }
        def malformed_run_api(path):
            if path.endswith("/releases?per_page=100&page=1"):
                return [release]
            if path.endswith("/git/commits/" + TARGET_COMMIT):
                return {"tree": {"sha": "1" * 40}}
            if path.endswith("/actions/runs/99"):
                return {
                    "status": "completed",
                    "conclusion": "success",
                    "head_repository": None,
                    "head_sha": BASE_COMMIT,
                    "path": gate.RELEASE_WORKFLOW,
                }
            self.fail("unexpected API path " + path)
        def malformed_run_command(*args):
            if args[:3] == ("git", "fetch", "--no-tags"):
                return ""
            self.assertEqual(args, ("git", "show", TARGET_COMMIT + ":releases/v2.2.4/request.json"))
            return json.dumps(ledger)
        with patch.object(publisher, "api", side_effect=malformed_run_api), \
                patch.object(publisher, "run", side_effect=malformed_run_command):
            with self.assertRaisesRegex(ValueError, "repository differs"):
                publisher._verified_published_baseline("CyberBASSLord-666/LightForge", VERSION)

    def test_missing_baseline_derives_performance_and_never_waives_it(self):
        with patch.object(publisher, "_verified_published_baseline", side_effect=ValueError("legacy release")):
            scope = publisher._derive_published_release_scope(
                "CyberBASSLord-666/LightForge", COMMIT, TREE, VERSION
            )
        self.assertEqual(scope["classification"], "performance")
        self.assertEqual(scope["waiver_blocker"], "unavailable_or_unverifiable_published_baseline")
        self.assertIsNone(scope["base_release"])
        declaration = nonperformance_declaration()
        with patch.object(publisher, "run", return_value=json.dumps(declaration)), \
                patch.object(publisher, "_derive_published_release_scope", return_value=scope):
            with self.assertRaisesRegex(ValueError, "cannot waive"):
                publisher.verify_release_quality(
                    {"quality_gate_policy": declaration_receipt(declaration)},
                    VERSION,
                    "CyberBASSLord-666/LightForge",
                    {},
                    COMMIT,
                    TREE,
                )
        stricter = dict(declaration, requirement="performance_quality_gate", classification="performance")
        with patch.object(publisher, "run", return_value=json.dumps(stricter)), \
                patch.object(publisher, "_derive_published_release_scope", return_value=scope):
            with self.assertRaisesRegex(ValueError, "Performance release requires exactly"):
                publisher.verify_release_quality(
                    {"quality_gate_policy": declaration_receipt(stricter)},
                    VERSION,
                    "CyberBASSLord-666/LightForge",
                    {},
                    COMMIT,
                    TREE,
                )

    def test_fetched_baseline_tree_must_match_the_verified_release_receipt(self):
        baseline = {
            "tag": "v2.2.4",
            "target_commit": TARGET_COMMIT,
            "source_commit": BASE_COMMIT,
            "source_tree_sha": BASE_TREE,
            "version": {"name": "2.2.4", "code": 20204},
        }

        def command(*args):
            if args[:3] == ("git", "fetch", "--no-tags"):
                return ""
            if args[:2] == ("git", "rev-parse"):
                # The fetched object disagrees with the API/verified-run tree
                # record.  A malformed provenance baseline may never waive.
                return "e" * 40
            self.fail("unexpected command " + repr(args))

        with patch.object(publisher, "_verified_published_baseline", return_value=baseline), \
                patch.object(publisher, "run", side_effect=command), \
                patch.object(publisher, "run_bytes") as raw_diff:
            scope = publisher._derive_published_release_scope(
                "CyberBASSLord-666/LightForge", COMMIT, TREE, VERSION
            )
        self.assertEqual(scope["classification"], "performance")
        self.assertEqual(scope["waiver_blocker"], "unavailable_or_unverifiable_published_baseline")
        raw_diff.assert_not_called()

    def test_publication_workflow_requires_protected_main_and_complete_history(self):
        workflow = (ROOT / ".github/workflows/publish-release.yml").read_text(encoding="utf-8")
        self.assertIn("environment: lightforge-release-quality", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("LIGHTFORGE_REF_PROTECTED: ${{ github.ref_protected }}", workflow)
        self.assertIn('test "$GITHUB_REF" = "refs/heads/main"', workflow)
        self.assertIn('test "$LIGHTFORGE_REF_PROTECTED" = "true"', workflow)

    def test_publisher_itself_rejects_unprotected_or_non_main_environment(self):
        publisher.require_protected_main({"GITHUB_REF": "refs/heads/main", "LIGHTFORGE_REF_PROTECTED": "true"})
        for environment in (
            {"GITHUB_REF": "refs/heads/main"},
            {"GITHUB_REF": "refs/heads/main", "LIGHTFORGE_REF_PROTECTED": "false"},
            {"GITHUB_REF": "refs/heads/release", "LIGHTFORGE_REF_PROTECTED": "true"},
        ):
            with self.subTest(environment=environment):
                with self.assertRaisesRegex(ValueError, "protected main|only from main"):
                    publisher.require_protected_main(environment)


if __name__ == "__main__":
    unittest.main()
