#!/usr/bin/env python3
"""Adversarial coverage for Android candidate/source provenance."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from android_evidence_binding import EvidenceError, verify_provenance, write_provenance


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AndroidEvidenceBindingTest(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / "version.json").write_text('{"name":"2.2.4"}\n')
        source_paths = []
        for relative, text in {
            "android/src/Thing.java": "class Thing {}\n",
            "web/app.js": "window.lightforge=true;\n",
            "tools/runner.py": "print('runner')\n",
        }.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            source_paths.append(path)
        candidate = root / "candidate"
        candidate.mkdir()
        for name, content in {
            "LightForge-2.2.4.apk": b"production apk",
            "background-tests.apk": b"background tests",
            "diagnostics-tests.apk": b"diagnostics tests",
        }.items():
            (candidate / name).write_bytes(content)
        app = candidate / "LightForge-2.2.4.apk"
        (candidate / "LightForge-2.2.4.apk.json").write_text(json.dumps({"bytes": app.stat().st_size, "sha256": digest(app)}))
        return temporary, root, candidate, source_paths

    def test_matching_candidate_is_accepted(self):
        temporary, root, candidate, sources = self.fixture()
        with temporary:
            write_provenance(root, candidate, source_paths=sources, commit="abc123")
            result = verify_provenance(root, candidate, source_paths=sources, expected_commit="abc123")
            self.assertEqual(result["commit"], "abc123")
            self.assertEqual(result["artifactNames"], ["LightForge-2.2.4.apk", "background-tests.apk", "diagnostics-tests.apk"])

    def test_changed_source_is_rejected(self):
        temporary, root, candidate, sources = self.fixture()
        with temporary:
            write_provenance(root, candidate, source_paths=sources, commit="abc123")
            (root / "web/app.js").write_text("window.lightforge=false;\n")
            with self.assertRaises(EvidenceError):
                verify_provenance(root, candidate, source_paths=sources, expected_commit="abc123")

    def test_tampered_artifact_or_commit_is_rejected(self):
        temporary, root, candidate, sources = self.fixture()
        with temporary:
            write_provenance(root, candidate, source_paths=sources, commit="abc123")
            with self.assertRaises(EvidenceError):
                verify_provenance(root, candidate, source_paths=sources, expected_commit="different")
            (candidate / "background-tests.apk").write_bytes(b"substituted")
            with self.assertRaises(EvidenceError):
                verify_provenance(root, candidate, source_paths=sources, expected_commit="abc123")


if __name__ == "__main__":
    unittest.main()
