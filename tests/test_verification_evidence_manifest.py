#!/usr/bin/env python3
"""Adversarial tests for the success-only non-Android evidence chain."""
from __future__ import annotations

import importlib.util
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
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


def candidate_manifest(path: Path, attempt=1, release=RELEASE):
    files = {
        name: {"bytes": 1, "sha256": SOURCE_HASH}
        for name in evidence._candidate_files(release)
    }
    path.write_text(json.dumps({
        "schema_version": evidence.CANDIDATE_SCHEMA_VERSION,
        "kind": evidence.CANDIDATE_KIND,
        "release": release,
        "source": {"commit": HEAD, "tree_sha": TREE},
        "pipeline": {"run_id": 741, "run_attempt": attempt, "evidence_session": SESSION},
        "source_hashes": {"web/app.js": SOURCE_HASH},
        "files": files,
    }), encoding="utf-8")
    return evidence.sha256_file(path)


def receipt(name, session=SESSION, release=RELEASE):
    value = {
        "release": release,
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


def host_admission():
    """A structurally valid seal, not authority without trusted API replay."""
    campaign = "lightforge-2.4.2-neural-four-worker-host-001"
    return {
        "schema": "lightforge.host-inference-admission.v1",
        "campaignId": campaign,
        "policySha256": "1" * 64,
        "declarationSha256": "2" * 64,
        "registration": {
            "commit": "3" * 40, "path": "tools/host-inference-campaigns/" + campaign + ".json",
            "blobSha": "4" * 40, "sha256": "5" * 64,
        },
        "request": {
            "commit": "d" * 40, "path": "tools/host-inference-campaigns/" + campaign + ".request.json",
            "blobSha": "a" * 40, "sha256": "a" * 64,
        },
        "producer": {
            "runId": 701, "runAttempt": 1, "headSha": "d" * 40,
            "event": "push", "headBranch": "main", "workflowPath": evidence.WORKFLOW,
        },
        "declarationArtifact": {"id": 801, "sha256": "6" * 64},
        "proofArtifact": {"id": 802, "sha256": "7" * 64},
        "proofReceiptSha256": "8" * 64,
        "measurementFinishedAt": "2026-10-23T12:00:00Z",
        "admissionCheckedAt": "2026-10-23T12:01:00Z",
        "candidate": {"sourceCommit": HEAD, "sourceTreeSha": TREE, "evidenceSession": SESSION},
        "knownLineage": [{"runId": 701, "runAttempt": 1, "declarationArtifactId": 801, "proofArtifactId": 802}],
        "recompiledClassHashes": {"NativeDeuxParallelBenchmark.class": "9" * 64},
    }


class VerificationEvidenceManifestTest(unittest.TestCase):
    def test_native_game_runtime_materials_remain_sealed_for_current_release(self):
        current = json.loads((ROOT / 'version.json').read_text())['name']
        names = {'native-game-verification.json', 'native-game-demo-output.json',
                 'native-game-falcon-output.json'}
        for release in ('2.3.2', '2.4.0', '2.4.1', '2.4.2', current):
            with self.subTest(release=release):
                expected = {f'qa/release-{release}/{name}' for name in names}
                self.assertTrue(expected <= evidence._runtime_evidence_materials(release))
        for release in ('2.3.1', '2.4.4', '3.0.0'):
            with self.subTest(unlisted_release=release):
                self.assertFalse(any('native-game-' in name
                                     for name in evidence._runtime_evidence_materials(release)))

    def _make_content(self, root: Path, attempt=1, release=RELEASE, admission=None):
        candidate = root / "candidate-manifest.json"
        identity = candidate_manifest(candidate, attempt, release)
        receipts = root / "receipts-input"
        receipts.mkdir()
        source_root = root / "source"
        (source_root / "web").mkdir(parents=True)
        (source_root / "web/app.js").write_bytes(SOURCE_BYTES)
        for name in evidence.RECEIPTS:
            (receipts / name).write_text(json.dumps(receipt(name, release=release)), encoding="utf-8")
        content = root / "content"
        args = SimpleNamespace(
            output_dir=content,
            receipt_dir=receipts,
            source_root=source_root,
            candidate_manifest=candidate,
            candidate_artifact_id=911,
            candidate_artifact_digest="sha256:" + "f" * 64,
            candidate_identity_sha256=identity,
            release=release,
            host_admission=admission,
            run_id=741,
            run_attempt=attempt,
            head_sha=HEAD,
            tree_sha=TREE,
            evidence_session=SESSION,
        )
        with patch.object(evidence, "_candidate_tree_bytes", side_effect=lambda _root, _commit, relative: SOURCE_BYTES if relative == "web/app.js" else None):
            manifest = evidence.write_content(args)
        return candidate, receipts, content, manifest

    def _make_wrapper(self, root: Path, content: Path, attempt=1, release=RELEASE):
        wrapper = root / "wrapper"
        return wrapper, evidence.write_wrapper(SimpleNamespace(
            output_dir=wrapper,
            content_dir=content,
            evidence_artifact_id=912,
            evidence_artifact_digest="sha256:" + "1" * 64,
            release=release,
            pipeline=pipeline(attempt),
        ))

    def test_success_chain_is_candidate_bound_and_uses_original_retry_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate_path, _, content, manifest = self._make_content(root, attempt=1)
            wrapper, wrapped = self._make_wrapper(root, content, attempt=1)
            self.assertEqual(
                json.loads(candidate_path.read_text(encoding="utf-8"))["schema_version"],
                evidence.CANDIDATE_SCHEMA_VERSION,
            )
            self.assertEqual(manifest["schema_version"], evidence.CONTENT_SCHEMA_VERSION)
            self.assertEqual(wrapped["schema_version"], evidence.WRAPPER_SCHEMA_VERSION)
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

    def _make_host_content(self, root):
        admission = root / "fresh-host-admission.json"
        admission.write_text(json.dumps(host_admission()))
        return self._make_content(root, release="2.4.2", admission=admission)

    def test_host_admission_is_additive_sealed_and_preserves_original_producer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, content, manifest = self._make_host_content(root)
            wrapper, wrapped = self._make_wrapper(root, content, release="2.4.2")
            self.assertEqual(len(manifest["receipts"]), 7)
            self.assertEqual(wrapped["host_admission"], manifest["host_admission"])
            self.assertEqual((content / evidence.HOST_ADMISSION_PATH).read_bytes(),
                             (root / "fresh-host-admission.json").read_bytes())
            admission = manifest["host_admission"]["admission"]
            self.assertNotEqual(admission["producer"]["headSha"], admission["candidate"]["sourceCommit"])
            self.assertEqual(admission["producer"]["headSha"], "d" * 40)
            self.assertEqual(evidence.verify_content(content, release="2.4.2", pipeline=pipeline()), manifest)
            self.assertEqual(evidence.verify_wrapper(wrapper, release="2.4.2", pipeline=pipeline()), wrapped)

    def test_host_record_candidate_session_schema_lineage_and_reference_mutations_fail_closed(self):
        mutations = [
            lambda a: a.update(schema="lightforge.experimental-portable-parallel-qualification.v1"),
            lambda a: a.update(schema="lightforge.production-parallel-qualification.v3"),
            lambda a: a.update(schema="lightforge.host-inference-admission.v2"),
            lambda a: a["candidate"].update(sourceCommit="e" * 40),
            lambda a: a["candidate"].update(sourceTreeSha="e" * 40),
            lambda a: a["candidate"].update(evidenceSession="e" * 64),
            lambda a: a.pop("registration"),
            lambda a: a.pop("request"),
            lambda a: a["request"].update(commit="e" * 40),
            lambda a: a["request"].update(sha256="bad"),
            lambda a: a["registration"].update(path="tools/host-inference-campaigns/other.json"),
            lambda a: a["registration"].update(sha256="bad"),
            lambda a: a["declarationArtifact"].update(id=0),
            lambda a: a["declarationArtifact"].update(id=802),
            lambda a: a["proofArtifact"].update(id=True),
            lambda a: a["proofArtifact"].update(sha256="bad"),
            lambda a: a.update(proofReceiptSha256="bad"),
            lambda a: a.update(policySha256="bad"),
            lambda a: a.update(knownLineage=[]),
            lambda a: a["knownLineage"].append(dict(a["knownLineage"][0])),
            lambda a: a["knownLineage"][0].update(proofArtifactId=803),
            lambda a: a["producer"].update(runAttempt=2),
            lambda a: a["producer"].update(headBranch="feature"),
            lambda a: a.update(admissionCheckedAt="2026-10-23T11:59:00Z"),
            lambda a: a.pop("recompiledClassHashes"),
            lambda a: a.update(recompiledClassHashes={}),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                value = host_admission()
                mutate(value)
                with self.assertRaises(ValueError):
                    evidence._validate_host_admission(value, pipeline())

    def test_host_outer_record_and_file_mutations_fail_closed(self):
        for mutation in ("absent", "null", "path", "size", "digest", "missing-file", "tampered-file", "changed-record"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _, _, content, manifest = self._make_host_content(root)
                value = copy.deepcopy(manifest)
                host = value["host_admission"]
                if mutation == "absent":
                    value.pop("host_admission")
                elif mutation == "null":
                    value["host_admission"] = None
                elif mutation == "path":
                    host["path"] = "../host-admission.json"
                elif mutation == "size":
                    host["bytes"] += 1
                elif mutation == "digest":
                    host["sha256"] = "0" * 64
                elif mutation == "missing-file":
                    (content / evidence.HOST_ADMISSION_PATH).unlink()
                elif mutation == "tampered-file":
                    (content / evidence.HOST_ADMISSION_PATH).write_text("{}")
                else:
                    host["admission"]["proofArtifact"]["sha256"] = "0" * 64
                (content / evidence.CONTENT_MANIFEST).write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    evidence.verify_content(content, release="2.4.2", pipeline=pipeline())

    def test_current_release_requires_additive_host_admission_and_preserves_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "Host admission is required"):
                self._make_content(root, release="2.4.2")
            self.assertFalse((root / "content").exists())
            self.assertEqual({path.name for path in (root / "receipts-input").iterdir()}, set(evidence.RECEIPTS))
            self.assertEqual(len(evidence.RECEIPTS), 7)
            self.assertEqual(evidence.CANDIDATE_SCHEMA_VERSION, 1)

    def test_legacy_schema_is_narrowly_supported_and_cannot_admit_current_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, content, manifest = self._make_content(root)
            legacy = dict(manifest, schema_version=2)
            legacy.pop("host_admission")
            (content / evidence.CONTENT_MANIFEST).write_text(json.dumps(legacy))
            self.assertEqual(evidence.verify_content(content, release=RELEASE, pipeline=pipeline()), legacy)
            wrapper, wrapped = self._make_wrapper(root, content)
            self.assertEqual(wrapped["schema_version"], 2)
            self.assertNotIn("host_admission", wrapped)
            self.assertEqual(evidence.verify_wrapper(wrapper, release=RELEASE, pipeline=pipeline()), wrapped)
            for verifier, directory in ((evidence.verify_content, content), (evidence.verify_wrapper, wrapper)):
                with self.subTest(kind=verifier.__name__):
                    with self.assertRaisesRegex(ValueError, "Legacy evidence schema cannot admit"):
                        verifier(directory, release="2.4.2", pipeline=pipeline())

    def test_unsupported_or_boolean_envelope_schemas_fail_closed(self):
        for schema in (0, 1, 4, "3", True, None):
            with self.subTest(schema=schema), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _, _, content, manifest = self._make_content(root)
                wrapper, wrapped = self._make_wrapper(root, content)
                for directory, filename, original, verifier in (
                    (content, evidence.CONTENT_MANIFEST, manifest, evidence.verify_content),
                    (wrapper, evidence.WRAPPER_MANIFEST, wrapped, evidence.verify_wrapper),
                ):
                    (directory / filename).write_text(json.dumps(dict(original, schema_version=schema)))
                    with self.assertRaisesRegex(ValueError, "schema is invalid"):
                        verifier(directory, release=RELEASE, pipeline=pipeline())

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

    def test_deux_reconstruction_policy_is_explicit_and_manifest_bound(self):
        manifest_path = ROOT / "web/analysis/models/deux/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = {
            "web/analysis/models/deux/" + name: "web/analysis/models/deux/manifest.json"
            for name in manifest["files"]
        }
        actual = {
            relative: provenance
            for relative, provenance in evidence.RECONSTRUCTED_MATERIAL_PROVENANCE.items()
            if relative.startswith("web/analysis/models/deux/")
        }
        self.assertEqual(actual, expected)
        relative = "web/analysis/models/deux/block-00-frequency.onnx"
        record = manifest["files"]["block-00-frequency.onnx"]
        provenance = manifest_path.read_bytes()
        evidence.validate_reconstructed_material_provenance(
            relative, record["sha256"], record["bytes"], provenance
        )
        with self.assertRaisesRegex(ValueError, "manifest differs"):
            evidence.validate_reconstructed_material_provenance(
                relative, record["sha256"], record["bytes"] + 1, provenance
            )
        with self.assertRaisesRegex(ValueError, "not approved"):
            evidence._reconstructed_provenance_path("web/analysis/models/deux/evil.onnx")

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
            deux = source_root / "web/analysis/models/deux/block-00-frequency.onnx"
            deux.parent.mkdir(parents=True)
            deux.write_bytes(b"deux")
            runtime = source_root / "qa/release-2.2.5/source-clock-verification.json"
            runtime.parent.mkdir(parents=True)
            runtime.write_bytes(b'{"fresh":true}')
            background_runtime = source_root / "qa/release-2.2.5/background-ui-verification.json"
            background_runtime.write_bytes(b'{"fresh":"background"}')
            restore_runtime = source_root / "qa/release-2.2.5/restore-preview-verification.json"
            restore_runtime.write_bytes(b'{"fresh":"restore"}')
            fixture_hash = evidence.sha256_file(fixture)
            game_hash = evidence.sha256_file(game)
            deux_hash = evidence.sha256_file(deux)
            runtime_hash = evidence.sha256_file(runtime)
            background_runtime_hash = evidence.sha256_file(background_runtime)
            restore_runtime_hash = evidence.sha256_file(restore_runtime)
            sources = {
                "web/app.js": SOURCE_HASH,
                "qa/release-1.6.0/fixtures/falcon-mix.wav": fixture_hash,
                "web/analysis/models/game/bd2dur.onnx": game_hash,
                "web/analysis/models/deux/block-00-frequency.onnx": deux_hash,
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
            deux_provenance = json.dumps({"files": {"block-00-frequency.onnx": {"bytes": deux.stat().st_size, "sha256": deux_hash}}}).encode()

            def tree_bytes(_root, _commit, relative):
                return {
                    "web/app.js": SOURCE_BYTES,
                    "qa/release-1.6.0/musdb-fixture-provenance.json": fixture_provenance,
                    "web/analysis/models/game/manifest.json": game_provenance,
                    "web/analysis/models/deux/manifest.json": deux_provenance,
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
            self.assertEqual(bindings["web/analysis/models/deux/block-00-frequency.onnx"]["origin"], "reconstructed_material")
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
