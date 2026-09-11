import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location("publisher", ROOT / "tools/publish_github_release.py")
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


COMMIT = "a" * 40
TREE = "b" * 40
VERSION = {"name": "2.2.5", "code": 20205}


def nonperformance_policy():
    return {
        "schema_version": 1,
        "release": VERSION,
        "source_commit": COMMIT,
        "source_tree_sha": TREE,
        "requirement": "not_required",
        "classification": "non-performance",
        "reason": "Documentation-only publication metadata correction.",
    }


class ReleaseQualityPublicationWiringTest(unittest.TestCase):
    def test_source_pinned_nonperformance_policy_needs_no_protected_corpus(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy_path = root / "releases/v2.2.5/quality-gate-policy.json"
            policy_path.parent.mkdir(parents=True)
            policy = nonperformance_policy()
            policy_path.write_text(json.dumps(policy))
            with patch.object(publisher, "ROOT", root), patch.object(publisher, "run", return_value=json.dumps(policy)) as run:
                returned = publisher.verify_release_quality({}, VERSION, "CyberBASSLord-666/LightForge", {}, COMMIT, TREE)
            self.assertEqual(returned["requirement"], "not_required")
            self.assertEqual(returned["classification"], "non-performance")
            run.assert_called_once_with("git", "show", COMMIT + ":releases/v2.2.5/quality-gate-policy.json")

    def test_policy_is_candidate_bound_and_performance_requires_quality_run(self):
        source = (ROOT / "tools/publish_github_release.py").read_text(encoding="utf-8")
        self.assertIn("source_quality_policy(source_commit, source_tree_sha, version)", source)
        self.assertIn("Performance release requires exactly quality_gate.run_id", source)
        self.assertIn("QUALITY_ARTIFACT", source)
        self.assertIn("validate_publication_evidence(", source)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "releases/v2.2.5/quality-gate-policy.json"
            path.parent.mkdir(parents=True)
            policy = nonperformance_policy()
            path.write_text(json.dumps(policy))
            changed = dict(policy, source_tree_sha="c" * 40)
            with patch.object(publisher, "ROOT", root), patch.object(publisher, "run", return_value=json.dumps(changed)):
                with self.assertRaisesRegex(ValueError, "source tree"):
                    publisher.source_quality_policy(COMMIT, TREE, VERSION)


if __name__ == "__main__":
    unittest.main()
