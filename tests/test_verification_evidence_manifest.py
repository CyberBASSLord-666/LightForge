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
from unittest.mock import patch


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
        "schema_version": evidence.CANDIDATE_SCHEMA_VERSION,
        "kind": evidence.CANDIDATE_KIND,
        "release": RELEASE,
        "source": {"commit": HEAD, "tree_sha": TREE},
        "pipeline": {"run_id": 741, "run_attempt": attempt, "evidence_session": SESSION},
        "source_hashes": {"web/app.js": SOURCE_HASH},
        "files": files,
    }), encoding="utf-8")
    return evidence.sha256_file(path)


def receipt(name, session=SESSION):
    value = {
        "release": RELEASE,
        "passed": True,
        "errors": [],
        "source_hashes": {"web/app.js": SOURCE_HASH},
    }
    if name in {
        "browser-verification.json",
        "analysis-browser-verification.json",
        "background-ui-verification.json",
        "restore-preview-verification.json",
    }:
        value.update({
            "evidenceSessionSchema": evidence.EVIDENCE_SESSION_SCHEMA,
            "evidenceSession": session,
        })
    elif name == "analysis-verification.json":
        value["evidence_session"] = session
    return value


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
        with patch.object(evidence, "_candidate_tree_bytes", side_effect=lambda _root, _commit, relative: SOURCE_BYTES if relative == "web/app.js" else None):
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

    def test_session_bound_receipts_and_wrappers_reject_absent_or_mismatched_nonces(self):
        session_cases = (
            ("browser-verification.json", "evidenceSession"),
            ("analysis-browser-verification.json", "evidenceSession"),
            ("background-ui-verification.json", "evidenceSession"),
            ("restore-preview-verification.json", "evidenceSession"),
            ("analysis-verification.json", "evidence_session"),
        )
        for name, field in session_cases:
            with self.subTest(receipt=name, condition="mismatched"):
                value = receipt(name, session="d" * 64)
                with self.assertRaisesRegex(ValueError, "evidence session differs"):
                    evidence._receipt(value, name, RELEASE, SESSION)
            with self.subTest(receipt=name, condition="missing"):
                value = receipt(name)
                if field == "evidenceSession":
                    value.pop("evidenceSessionSchema")
                    value.pop("evidenceSession")
                else:
                    value.pop(field)
                with self.assertRaisesRegex(ValueError, "evidence session differs"):
                    evidence._receipt(value, name, RELEASE, SESSION)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, content, manifest = self._make_content(root)
            wrapper, wrapped = self._make_wrapper(root, content)
            self.assertEqual(manifest["schema_version"], evidence.CONTENT_SCHEMA_VERSION)
            self.assertEqual(wrapped["schema_version"], evidence.WRAPPER_SCHEMA_VERSION)
            self.assertEqual(
                manifest["receipts"]["restore-preview-verification.json"]["session_evidence"],
                {"evidenceSessionSchema": evidence.EVIDENCE_SESSION_SCHEMA, "evidenceSession": SESSION},
            )
            self.assertEqual(
                wrapped["receipts"]["analysis-verification.json"]["session_evidence"],
                {"evidence_session": SESSION},
            )
            wrapper_path = wrapper / evidence.WRAPPER_MANIFEST
            tampered = json.loads(wrapper_path.read_text(encoding="utf-8"))
            tampered["receipts"]["background-ui-verification.json"]["session_evidence"]["evidenceSession"] = "d" * 64
            wrapper_path.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "session differs"):
                evidence.verify_wrapper(
                    wrapper, release=RELEASE, pipeline=pipeline(),
                    expected_candidate=manifest["candidate"],
                )

    def test_partial_or_tampered_content_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, content, manifest = self._make_content(root)
            (content / evidence.RECEIPTS["native-verification.json"]).unlink()
            with self.assertRaisesRegex(ValueError, "missing"):
                evidence.verify_content(content, release=RELEASE, pipeline=pipeline(), expected_candidate=manifest["candidate"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, content, manifest = self._make_content(root)
            path = content / evidence.CONTENT_MANIFEST
            value = json.loads(path.read_text(encoding="utf-8"))
            value.pop("source_bindings")
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "fields are invalid"):
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

    def test_ci_only_materials_are_explicitly_classified_sealed_and_reconstructed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = root / "candidate-manifest.json"
            identity = candidate_manifest(candidate)
            receipt_dir = root / "receipts"
            receipt_dir.mkdir()
            source_root = root / "source"
            app = source_root / "web/app.js"
            app.parent.mkdir(parents=True)
            app.write_bytes(SOURCE_BYTES)
            fixture = source_root / "qa/release-1.6.0/fixtures/falcon-mix.wav"
            fixture.parent.mkdir(parents=True)
            fixture.write_bytes(b"fresh-falcon")
            game = source_root / "web/analysis/models/game/bd2dur.onnx"
            game.parent.mkdir(parents=True)
            game.write_bytes(b"game")
            runtime = source_root / "qa/release-2.2.5/source-clock-verification.json"
            runtime.parent.mkdir(parents=True)
            runtime.write_bytes(b'{"fresh":true}')
            background_runtime = source_root / "qa/release-2.2.5/background-ui-verification.json"
            background_runtime.write_bytes(b'{"fresh":"background"}')
            restore_runtime = source_root / "qa/release-2.2.5/restore-preview-verification.json"
            restore_runtime.write_bytes(b'{"fresh":"restore"}')
            fixture_hash = evidence.sha256_file(fixture)
            game_hash = evidence.sha256_file(game)
            runtime_hash = evidence.sha256_file(runtime)
            background_runtime_hash = evidence.sha256_file(background_runtime)
            restore_runtime_hash = evidence.sha256_file(restore_runtime)
            sources = {
                "web/app.js": SOURCE_HASH,
                "qa/release-1.6.0/fixtures/falcon-mix.wav": fixture_hash,
                "web/analysis/models/game/bd2dur.onnx": game_hash,
                "qa/release-2.2.5/source-clock-verification.json": runtime_hash,
                "qa/release-2.2.5/background-ui-verification.json": background_runtime_hash,
                "qa/release-2.2.5/restore-preview-verification.json": restore_runtime_hash,
            }
            for name in evidence.RECEIPTS:
                value = receipt(name)
                value["source_hashes"] = sources
                (receipt_dir / name).write_text(json.dumps(value), encoding="utf-8")
            fixture_provenance = json.dumps({"tracks": [{"id": "falcon", "pcmSHA256": {"falcon-mix.wav": fixture_hash}}]}).encode()
            game_provenance = json.dumps({"files": {"bd2dur.onnx": {"bytes": game.stat().st_size, "sha256": game_hash}}}).encode()

            def tree_bytes(_root, _commit, relative):
                return {
                    "web/app.js": SOURCE_BYTES,
                    "qa/release-1.6.0/musdb-fixture-provenance.json": fixture_provenance,
                    "web/analysis/models/game/manifest.json": game_provenance,
                    "qa/release-2.2.5/source-clock-verification.json": b"historical-output",
                    "qa/release-2.2.5/background-ui-verification.json": b"historical-background-output",
                    "qa/release-2.2.5/restore-preview-verification.json": b"historical-restore-output",
                }.get(relative)

            with patch.object(evidence, "_candidate_tree_bytes", side_effect=tree_bytes):
                content = evidence.write_content(SimpleNamespace(
                    output_dir=root / "content", receipt_dir=receipt_dir, source_root=source_root,
                    candidate_manifest=candidate, candidate_artifact_id=911,
                    candidate_artifact_digest="sha256:" + "f" * 64,
                    candidate_identity_sha256=identity, release=RELEASE, run_id=741,
                    run_attempt=1, head_sha=HEAD, tree_sha=TREE, evidence_session=SESSION,
                ))
            bindings = content["source_bindings"]
            self.assertEqual(bindings["web/app.js"]["origin"], "candidate_tree")
            self.assertEqual(bindings["qa/release-1.6.0/fixtures/falcon-mix.wav"]["origin"], "reconstructed_material")
            self.assertEqual(bindings["web/analysis/models/game/bd2dur.onnx"]["origin"], "reconstructed_material")
            sealed = bindings["qa/release-2.2.5/source-clock-verification.json"]
            self.assertEqual(sealed["origin"], "sealed_runtime_material")
            self.assertEqual((root / "content" / sealed["path"]).read_bytes(), runtime.read_bytes())
            for relative, material in (
                ("qa/release-2.2.5/background-ui-verification.json", background_runtime),
                ("qa/release-2.2.5/restore-preview-verification.json", restore_runtime),
            ):
                self.assertIn(relative, evidence._runtime_evidence_materials(RELEASE))
                sealed_runtime = bindings[relative]
                self.assertEqual(sealed_runtime["origin"], "sealed_runtime_material")
                self.assertEqual((root / "content" / sealed_runtime["path"]).read_bytes(), material.read_bytes())
            self.assertEqual(
                evidence.verify_content(root / "content", release=RELEASE, pipeline=pipeline(), expected_candidate=content["candidate"]),
                content,
            )
            (root / "content" / sealed["path"]).write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "runtime material differs"):
                evidence.verify_content(root / "content", release=RELEASE, pipeline=pipeline(), expected_candidate=content["candidate"])

    def test_unapproved_non_tree_source_fails_sealing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = root / "candidate-manifest.json"
            identity = candidate_manifest(candidate)
            receipt_dir = root / "receipts"
            receipt_dir.mkdir()
            source_root = root / "source"
            bad = source_root / "qa/release-2.2.5/unreviewed-output.json"
            bad.parent.mkdir(parents=True)
            bad.write_bytes(b"unreviewed")
            checksum = evidence.sha256_file(bad)
            for name in evidence.RECEIPTS:
                value = receipt(name)
                value["source_hashes"] = {"qa/release-2.2.5/unreviewed-output.json": checksum}
                (receipt_dir / name).write_text(json.dumps(value), encoding="utf-8")
            with patch.object(evidence, "_candidate_tree_bytes", return_value=None), \
                    self.assertRaisesRegex(ValueError, "approved CI material"):
                evidence.write_content(SimpleNamespace(
                    output_dir=root / "content", receipt_dir=receipt_dir, source_root=source_root,
                    candidate_manifest=candidate, candidate_artifact_id=911,
                    candidate_artifact_digest="sha256:" + "f" * 64,
                    candidate_identity_sha256=identity, release=RELEASE, run_id=741,
                    run_attempt=1, head_sha=HEAD, tree_sha=TREE, evidence_session=SESSION,
                ))


if __name__ == "__main__":
    unittest.main()
