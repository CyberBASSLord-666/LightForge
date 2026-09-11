import importlib.util
import json
from pathlib import Path
import subprocess
import sys
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
