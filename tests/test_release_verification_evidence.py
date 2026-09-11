#!/usr/bin/env python3
"""Release-publisher tests for sealed, non-Android verify-v2 evidence."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys_path = __import__("sys").path
sys_path.insert(0, str(ROOT / "tools"))
PUBLISHER_SPEC = importlib.util.spec_from_file_location("publisher", ROOT / "tools/publish_github_release.py")
publisher = importlib.util.module_from_spec(PUBLISHER_SPEC)
PUBLISHER_SPEC.loader.exec_module(publisher)
EVIDENCE_SPEC = importlib.util.spec_from_file_location("verification_evidence", ROOT / "tools/verification_evidence_manifest.py")
evidence = importlib.util.module_from_spec(EVIDENCE_SPEC)
EVIDENCE_SPEC.loader.exec_module(evidence)


RELEASE = {"name": "2.2.5", "code": 20205}
HEAD = "a" * 40
TREE = "b" * 40
SESSION = "c" * 64
SOURCE_BYTES = b"candidate-source-bytes"
SOURCE_HASH = hashlib.sha256(SOURCE_BYTES).hexdigest()


def pipeline(attempt=1):
    return {
        "workflow": evidence.WORKFLOW,
        "run_id": 741,
        "run_attempt": attempt,
        "head_sha": HEAD,
        "tree_sha": TREE,
        "evidence_session": SESSION,
    }


def candidate_manifest(path: Path, attempt=1):
    path.write_text(json.dumps({
        "schema_version": 1,
        "kind": evidence.CANDIDATE_KIND,
        "release": RELEASE["name"],
        "source": {"commit": HEAD, "tree_sha": TREE},
        "pipeline": {"run_id": 741, "run_attempt": attempt, "evidence_session": SESSION},
        "source_hashes": {"web/app.js": SOURCE_HASH},
        "files": {name: {"bytes": 1, "sha256": "d" * 64} for name in evidence._candidate_files(RELEASE["name"])},
    }), encoding="utf-8")
    return evidence.sha256_file(path)


class ReleaseVerificationEvidenceTest(unittest.TestCase):
    def _artifacts(self, root: Path, attempt=1):
        candidate_path = root / "candidate-manifest.json"
        identity = candidate_manifest(candidate_path, attempt)
        input_dir = root / "receipts-input"
        input_dir.mkdir()
        source_root = root / "source"
        (source_root / "web").mkdir(parents=True)
        (source_root / "web/app.js").write_bytes(SOURCE_BYTES)
        for name in evidence.RECEIPTS:
            (input_dir / name).write_text(json.dumps({
                "release": RELEASE["name"], "passed": True, "errors": [],
                "source_hashes": {"web/app.js": SOURCE_HASH},
            }), encoding="utf-8")
        content_root = root / "content"
        content = evidence.write_content(SimpleNamespace(
            output_dir=content_root,
            receipt_dir=input_dir,
            source_root=source_root,
            candidate_manifest=candidate_path,
            candidate_artifact_id=911,
            candidate_artifact_digest="sha256:" + "f" * 64,
            candidate_identity_sha256=identity,
            release=RELEASE["name"],
            run_id=741,
            run_attempt=attempt,
            head_sha=HEAD,
            tree_sha=TREE,
            evidence_session=SESSION,
        ))
        wrapper_root = root / "wrapper"
        wrapper = evidence.write_wrapper(SimpleNamespace(
            output_dir=wrapper_root,
            content_dir=content_root,
            evidence_artifact_id=912,
            evidence_artifact_digest="sha256:" + "1" * 64,
            release=RELEASE["name"],
            pipeline=pipeline(attempt),
        ))
        return content_root, wrapper_root, content, wrapper

    def _run(self, root, content_root, wrapper_root, candidate, *, ci_attempt=2):
        ci = {"id": 741, "run_attempt": ci_attempt}
        expected_wrapper = evidence.wrapper_artifact_name(RELEASE["name"], pipeline(candidate["pipeline"]["run_attempt"]))
        metadata = [
            {"id": 1001, "digest": "sha256:" + "2" * 64},
            {"id": 912, "digest": "sha256:" + "1" * 64},
        ]
        commands = []

        def source(*args):
            commands.append(args)
            self.assertEqual(args, ("git", "show", HEAD + ":web/app.js"))
            return SOURCE_BYTES

        def download(*args):
            source = wrapper_root if args[2].name.endswith("wrapper") else content_root
            shutil.copytree(source, args[2])
            return args[2]

        with patch.object(publisher, "ROOT", root / "publisher-checkout"), \
                patch.object(publisher, "_run_artifacts", return_value=[{"name": expected_wrapper, "id": 1001}]) as inventory, \
                patch.object(publisher, "_artifact_metadata", side_effect=metadata), \
                patch.object(publisher, "_download_exact_artifact", side_effect=download) as download, \
                patch.object(publisher, "run_bytes", side_effect=source):
            result = publisher.verify_nonandroid_release_evidence(
                "CyberBASSLord-666/LightForge", ci, RELEASE, HEAD, TREE, candidate
            )
        return result, inventory, download, commands, expected_wrapper

    def test_stale_checkout_receipts_are_ignored_and_source_is_read_from_candidate_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            content_root, wrapper_root, content, _ = self._artifacts(root, attempt=1)
            # This is deliberately a plausible historic pass.  Publication must
            # use neither it nor any checkout QA path.
            stale = root / "publisher-checkout/qa/release-2.2.5"
            stale.mkdir(parents=True)
            (stale / "analysis-verification.json").write_text(json.dumps({
                "release": RELEASE["name"], "passed": True, "errors": [], "source_hashes": {"web/app.js": "0" * 64},
            }), encoding="utf-8")
            result, inventory, download, commands, expected_wrapper = self._run(
                root, content_root, wrapper_root, content["candidate"], ci_attempt=2
            )
            self.assertEqual(result["content_artifact_id"], 912)
            self.assertEqual(commands, [("git", "show", HEAD + ":web/app.js")])
            self.assertEqual(inventory.call_args.args[1], 741)
            self.assertIn("-741-1", expected_wrapper)
            self.assertNotIn("-741-2", expected_wrapper)
            self.assertEqual(download.call_count, 2)

    def test_partial_or_tampered_artifact_cannot_be_promoted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            content_root, wrapper_root, content, _ = self._artifacts(root)
            (content_root / evidence.RECEIPTS["native-verification.json"]).unlink()
            with self.assertRaisesRegex(ValueError, "unexpected or missing"):
                self._run(root, content_root, wrapper_root, content["candidate"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            content_root, wrapper_root, content, _ = self._artifacts(root)
            wrapper_path = wrapper_root / evidence.WRAPPER_MANIFEST
            value = json.loads(wrapper_path.read_text(encoding="utf-8"))
            value["evidence_artifact"]["digest"] = "0" * 64
            wrapper_path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifest is not canonical|artifact digest differs"):
                self._run(root, content_root, wrapper_root, content["candidate"])

    def test_cross_run_candidate_binding_and_source_tampering_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            content_root, wrapper_root, content, _ = self._artifacts(root, attempt=1)
            foreign = json.loads(json.dumps(content["candidate"]))
            foreign["pipeline"]["run_id"] = 742
            with self.assertRaisesRegex(ValueError, "another Actions run"):
                self._run(root, content_root, wrapper_root, foreign)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            content_root, wrapper_root, content, _ = self._artifacts(root, attempt=1)
            with patch.object(publisher, "ROOT", root / "publisher-checkout"), \
                    patch.object(publisher, "_run_artifacts", return_value=[{
                        "name": evidence.wrapper_artifact_name(RELEASE["name"], pipeline(1)), "id": 1001
                    }]), \
                    patch.object(publisher, "_artifact_metadata", side_effect=[
                        {"id": 1001, "digest": "sha256:" + "2" * 64},
                        {"id": 912, "digest": "sha256:" + "1" * 64},
                    ]), \
                    patch.object(publisher, "_download_exact_artifact", side_effect=lambda *args: (shutil.copytree(wrapper_root if args[2].name.endswith("wrapper") else content_root, args[2]) or args[2])), \
                    patch.object(publisher, "run_bytes", return_value=b"tampered-source"):
                with self.assertRaisesRegex(ValueError, "source hash differs"):
                    publisher.verify_nonandroid_release_evidence(
                        "CyberBASSLord-666/LightForge", {"id": 741, "run_attempt": 2}, RELEASE,
                        HEAD, TREE, content["candidate"]
                    )


if __name__ == "__main__":
    unittest.main()
