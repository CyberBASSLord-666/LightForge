import importlib.util
import json
from pathlib import Path
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


class ReleaseQualityPublicationWiringTest(unittest.TestCase):
    def test_source_pinned_nonperformance_policy_needs_no_protected_corpus(self):
        declaration = nonperformance_declaration()
        request = {"quality_gate_policy": declaration_receipt(declaration)}
        with patch.object(publisher, "run", return_value=json.dumps(declaration)) as run:
            returned = publisher.verify_release_quality(request, VERSION, "CyberBASSLord-666/LightForge", {}, COMMIT, TREE)
        self.assertEqual(returned["requirement"], "not_required")
        self.assertEqual(returned["classification"], "non-performance")
        run.assert_called_once_with("git", "show", COMMIT + ":releases/v2.2.5/quality-gate-declaration.json")

    def test_policy_is_candidate_bound_and_performance_requires_quality_run(self):
        source = (ROOT / "tools/publish_github_release.py").read_text(encoding="utf-8")
        self.assertIn("source_release_declaration(source_commit, version)", source)
        self.assertIn("validate_declaration_receipt(", source)
        self.assertIn("Performance release requires exactly quality_gate.run_id", source)
        self.assertIn("QUALITY_ARTIFACT", source)
        self.assertIn("validate_publication_evidence(", source)
        for path in (
            ".github/workflows/publish-release.yml",
            "tools/publish_github_release.py",
            "tools/release_quality_gate.py",
            "tools/apk_archive.py",
            "tools/apk_delta.py",
            "tools/package_release.py",
        ):
            self.assertIn(repr(path), source)
        declaration = nonperformance_declaration()
        receipt = declaration_receipt(declaration)
        receipt["source_tree_sha"] = "c" * 40
        with patch.object(publisher, "run", return_value=json.dumps(declaration)):
            with self.assertRaisesRegex(ValueError, "source tree"):
                publisher.verify_release_quality(
                    {"quality_gate_policy": receipt},
                    VERSION,
                    "CyberBASSLord-666/LightForge",
                    {},
                    COMMIT,
                    TREE,
                )


if __name__ == "__main__":
    unittest.main()
