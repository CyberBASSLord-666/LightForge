#!/usr/bin/env python3
"""Adversarial tests for the success-only non-Android evidence chain."""
from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verification_evidence_manifest", ROOT / "tools/verification_evidence_manifest.py")
evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evidence)


RELEASE = "2.2.5"
HEAD = "a" * 40
TREE = "b" * 40
SESSION = "c" * 64
SOURCE_BYTES = b"fresh verifier source"
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
    files = {
        name: {"bytes": 1, "sha256": SOURCE_HASH}
        for name in evidence._candidate_files(RELEASE)
    }
    path.write_text(json.dumps({
        "schema_version": 1,
        "kind": evidence.CANDIDATE_KIND,
        "release": RELEASE,
        "source": {"commit": HEAD, "tree_sha": TREE},
        "pipeline": {"run_id": 741, "run_attempt": attempt, "evidence_session": SESSION},
        "source_hashes": {"web/app.js": SOURCE_HASH},
        "files": files,
    }), encoding="utf-8")
    return evidence.sha256_file(path)


def receipt(name):
    return {
        "release": RELEASE,
        "passed": True,
        "errors": [],
        "source_hashes": {"web/app.js": SOURCE_HASH},
    }


class VerificationEvidenceManifestTest(unittest.TestCase):
    def _make_content(self, root: Path, attempt=1):
        candidate = root / "candidate-manifest.json"
        identity = candidate_manifest(candidate, attempt)
        receipts = root / "receipts-input"
        receipts.mkdir()
        source_root = root / "source"
        (source_root / "web").mkdir(parents=True)
        (source_root / "web/app.js").write_bytes(SOURCE_BYTES)
        for name in evidence.RECEIPTS:
            (receipts / name).write_text(json.dumps(receipt(name)), encoding="utf-8")
        content = root / "content"
        args = SimpleNamespace(
            output_dir=content,
            receipt_dir=receipts,
            source_root=source_root,
            candidate_manifest=candidate,
            candidate_artifact_id=911,
            candidate_artifact_digest="sha256:" + "f" * 64,
            candidate_identity_sha256=identity,
            release=RELEASE,
            run_id=741,
            run_attempt=attempt,
            head_sha=HEAD,
            tree_sha=TREE,
            evidence_session=SESSION,
        )
        manifest = evidence.write_content(args)
        return candidate, receipts, content, manifest

    def _make_wrapper(self, root: Path, content: Path, attempt=1):
        wrapper = root / "wrapper"
        return wrapper, evidence.write_wrapper(SimpleNamespace(
            output_dir=wrapper,
            content_dir=content,
            evidence_artifact_id=912,
            evidence_artifact_digest="sha256:" + "1" * 64,
            release=RELEASE,
            pipeline=pipeline(attempt),
        ))

    def test_success_chain_is_candidate_bound_and_uses_original_retry_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, content, manifest = self._make_content(root, attempt=1)
            wrapper, wrapped = self._make_wrapper(root, content, attempt=1)
            self.assertEqual(manifest["candidate"]["pipeline"]["run_attempt"], 1)
            # A later Android-only retry may be attempt 2.  Core evidence must
            # retain the candidate's attempt 1 identity and deterministic name.
            self.assertEqual(
                evidence.wrapper_artifact_name(RELEASE, manifest["pipeline"]),
                "lightforge-2.2.5-verification-evidence-manifest-741-1",
            )
            self.assertEqual(wrapped["candidate"], manifest["candidate"])
            self.assertEqual(wrapped["receipts"], manifest["receipts"])
            self.assertEqual(
                evidence.verify_content(content, release=RELEASE, pipeline=pipeline(1), expected_candidate=manifest["candidate"]),
                manifest,
            )
            self.assertEqual(
                evidence.verify_wrapper(wrapper, release=RELEASE, pipeline=pipeline(1), expected_candidate=manifest["candidate"]),
                wrapped,
            )

    def test_partial_or_tampered_content_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, content, manifest = self._make_content(root)
            (content / evidence.RECEIPTS["native-verification.json"]).unlink()
            with self.assertRaisesRegex(ValueError, "unexpected or missing"):
                evidence.verify_content(content, release=RELEASE, pipeline=pipeline(), expected_candidate=manifest["candidate"])

    def test_missing_post_purge_receipt_cannot_be_sealed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = root / "candidate-manifest.json"
            identity = candidate_manifest(candidate)
            receipts = root / "receipts-input"
            receipts.mkdir()
            source_root = root / "source"
            (source_root / "web").mkdir(parents=True)
            (source_root / "web/app.js").write_bytes(SOURCE_BYTES)
            for name in evidence.RECEIPTS:
                if name != "analysis-verification.json":
                    (receipts / name).write_text(json.dumps(receipt(name)), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "receipt is missing"):
                evidence.write_content(SimpleNamespace(
                    output_dir=root / "content", receipt_dir=receipts, source_root=source_root,
                    candidate_manifest=candidate, candidate_artifact_id=911,
                    candidate_artifact_digest="sha256:" + "f" * 64,
                    candidate_identity_sha256=identity, release=RELEASE, run_id=741,
                    run_attempt=1, head_sha=HEAD, tree_sha=TREE, evidence_session=SESSION,
                ))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, content, manifest = self._make_content(root)
            target = content / evidence.RECEIPTS["browser-verification.json"]
            changed = receipt("browser-verification.json")
            changed["passed"] = False
            target.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "digest differs"):
                evidence.verify_content(content, release=RELEASE, pipeline=pipeline(), expected_candidate=manifest["candidate"])

    def test_cross_run_or_cross_candidate_wrapper_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, content, manifest = self._make_content(root, attempt=1)
            wrapper, _ = self._make_wrapper(root, content, attempt=1)
            path = wrapper / evidence.WRAPPER_MANIFEST
            value = json.loads(path.read_text(encoding="utf-8"))
            value["pipeline"]["run_attempt"] = 2
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pipeline differs"):
                evidence.verify_wrapper(wrapper, release=RELEASE, pipeline=pipeline(1), expected_candidate=manifest["candidate"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, content, manifest = self._make_content(root, attempt=1)
            wrapper, _ = self._make_wrapper(root, content, attempt=1)
            path = wrapper / evidence.WRAPPER_MANIFEST
            value = json.loads(path.read_text(encoding="utf-8"))
            value["candidate"]["identity_sha256"] = "0" * 64
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "candidate differs"):
                evidence.verify_wrapper(wrapper, release=RELEASE, pipeline=pipeline(1), expected_candidate=manifest["candidate"])

    def test_stale_candidate_or_receipt_source_binding_is_rejected_at_seal_time(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = root / "candidate-manifest.json"
            identity = candidate_manifest(candidate, attempt=1)
            receipts = root / "receipts-input"
            receipts.mkdir()
            source_root = root / "source"
            (source_root / "web").mkdir(parents=True)
            (source_root / "web/app.js").write_bytes(SOURCE_BYTES)
            for name in evidence.RECEIPTS:
                (receipts / name).write_text(json.dumps(receipt(name)), encoding="utf-8")
            bad = receipt("native-verification.json")
            bad["source_hashes"] = {}
            (receipts / "native-verification.json").write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source hashes"):
                evidence.write_content(SimpleNamespace(
                    output_dir=root / "content",
                    receipt_dir=receipts,
                    source_root=source_root,
                    candidate_manifest=candidate,
                    candidate_artifact_id=911,
                    candidate_artifact_digest="sha256:" + "f" * 64,
                    candidate_identity_sha256=identity,
                    release=RELEASE,
                    run_id=741,
                    run_attempt=1,
                    head_sha=HEAD,
                    tree_sha=TREE,
                    evidence_session=SESSION,
                ))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = root / "candidate-manifest.json"
            identity = candidate_manifest(candidate, attempt=1)
            receipts = root / "receipts-input"
            receipts.mkdir()
            source_root = root / "source"
            (source_root / "web").mkdir(parents=True)
            (source_root / "web/app.js").write_bytes(SOURCE_BYTES)
            for name in evidence.RECEIPTS:
                stale = receipt(name)
                stale["source_hashes"] = {"web/app.js": "0" * 64}
                (receipts / name).write_text(json.dumps(stale), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differs from the verifier checkout"):
                evidence.write_content(SimpleNamespace(
                    output_dir=root / "content",
                    receipt_dir=receipts,
                    source_root=source_root,
                    candidate_manifest=candidate,
                    candidate_artifact_id=911,
                    candidate_artifact_digest="sha256:" + "f" * 64,
                    candidate_identity_sha256=identity,
                    release=RELEASE,
                    run_id=741,
                    run_attempt=1,
                    head_sha=HEAD,
                    tree_sha=TREE,
                    evidence_session=SESSION,
                ))


if __name__ == "__main__":
    unittest.main()
