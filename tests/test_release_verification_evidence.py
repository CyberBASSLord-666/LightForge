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
        "schema_version": evidence.CANDIDATE_SCHEMA_VERSION,
        "kind": evidence.CANDIDATE_KIND,
        "release": RELEASE["name"],
        "source": {"commit": HEAD, "tree_sha": TREE},
        "pipeline": {"run_id": 741, "run_attempt": attempt, "evidence_session": SESSION},
        "source_hashes": {"web/app.js": SOURCE_HASH},
        "files": {name: {"bytes": 1, "sha256": "d" * 64} for name in evidence._candidate_files(RELEASE["name"])},
    }), encoding="utf-8")
    return evidence.sha256_file(path)


def receipt(name, source_hashes=None, session=SESSION):
    value = {
        "release": RELEASE["name"],
        "passed": True,
        "errors": [],
        "source_hashes": {"web/app.js": SOURCE_HASH} if source_hashes is None else source_hashes,
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
            (input_dir / name).write_text(json.dumps(receipt(name)), encoding="utf-8")
        content_root = root / "content"
        with patch.object(evidence, "_candidate_tree_bytes", side_effect=lambda _root, _commit, relative: SOURCE_BYTES if relative == "web/app.js" else None):
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
            with self.assertRaisesRegex(ValueError, "missing"):
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
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            content_root, wrapper_root, content, _ = self._artifacts(root)
            wrapper_path = wrapper_root / evidence.WRAPPER_MANIFEST
            value = json.loads(wrapper_path.read_text(encoding="utf-8"))
            value["receipts"]["restore-preview-verification.json"]["session_evidence"]["evidenceSession"] = "d" * 64
            wrapper_path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "session differs"):
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

    def test_ci_only_materials_are_checked_from_sealed_or_reconstructed_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate_path = root / "candidate-manifest.json"
            identity = candidate_manifest(candidate_path)
            receipt_dir = root / "receipts"
            receipt_dir.mkdir()
            source_root = root / "publisher-checkout"
            app = source_root / "web/app.js"
            app.parent.mkdir(parents=True)
            app.write_bytes(SOURCE_BYTES)
            fixture = source_root / "qa/release-1.6.0/fixtures/falcon-mix.wav"
            fixture.parent.mkdir(parents=True)
            fixture.write_bytes(b"falcon")
            game = source_root / "web/analysis/models/game/bd2dur.onnx"
            game.parent.mkdir(parents=True)
            game.write_bytes(b"game")
            runtime = source_root / "qa/release-2.2.5/source-clock-verification.json"
            runtime.parent.mkdir(parents=True)
            runtime.write_bytes(b'{"fresh":true}')
            fixture_hash, game_hash, runtime_hash = map(evidence.sha256_file, (fixture, game, runtime))
            hashes = {
                "web/app.js": SOURCE_HASH,
                "qa/release-1.6.0/fixtures/falcon-mix.wav": fixture_hash,
                "web/analysis/models/game/bd2dur.onnx": game_hash,
                "qa/release-2.2.5/source-clock-verification.json": runtime_hash,
            }
            for name in evidence.RECEIPTS:
                (receipt_dir / name).write_text(json.dumps(receipt(name, hashes)), encoding="utf-8")
            fixture_provenance = json.dumps({"tracks": [{"id": "falcon", "pcmSHA256": {"falcon-mix.wav": fixture_hash}}]}).encode()
            game_provenance = json.dumps({"files": {"bd2dur.onnx": {"bytes": game.stat().st_size, "sha256": game_hash}}}).encode()

            def candidate_bytes(_root, _commit, relative):
                return {
                    "web/app.js": SOURCE_BYTES,
                    "qa/release-1.6.0/musdb-fixture-provenance.json": fixture_provenance,
                    "web/analysis/models/game/manifest.json": game_provenance,
                    "qa/release-2.2.5/source-clock-verification.json": b"historical-output",
                }.get(relative)

            with patch.object(evidence, "_candidate_tree_bytes", side_effect=candidate_bytes):
                content = evidence.write_content(SimpleNamespace(
                    output_dir=root / "content", receipt_dir=receipt_dir, source_root=source_root,
                    candidate_manifest=candidate_path, candidate_artifact_id=911,
                    candidate_artifact_digest="sha256:" + "f" * 64,
                    candidate_identity_sha256=identity, release=RELEASE["name"], run_id=741,
                    run_attempt=1, head_sha=HEAD, tree_sha=TREE, evidence_session=SESSION,
                ))
            # A later release-request checkout may contain a stale same-named
            # QA output.  The publisher must use the sealed material copy.
            runtime.write_bytes(b'{"stale":true}')
            commands = []

            def source(*args):
                commands.append(args)
                requested = args[-1].split(":", 1)[1]
                return {
                    "web/app.js": SOURCE_BYTES,
                    "qa/release-1.6.0/musdb-fixture-provenance.json": fixture_provenance,
                    "web/analysis/models/game/manifest.json": game_provenance,
                }[requested]

            with patch.object(publisher, "ROOT", source_root), patch.object(publisher, "run_bytes", side_effect=source):
                publisher._validate_verification_source_hashes(
                    HEAD, content["receipts"], content["source_bindings"], root / "content"
                )
            self.assertNotIn(("git", "show", HEAD + ":qa/release-2.2.5/source-clock-verification.json"), commands)
            wrapper_root = root / "wrapper"
            evidence.write_wrapper(SimpleNamespace(
                output_dir=wrapper_root, content_dir=root / "content", evidence_artifact_id=912,
                evidence_artifact_digest="sha256:" + "1" * 64, release=RELEASE["name"], pipeline=pipeline(),
            ))
            expected_wrapper = evidence.wrapper_artifact_name(RELEASE["name"], pipeline())
            requested_members = []

            def download(_repo, artifact, destination, expected_names):
                requested_members.append(set(expected_names))
                shutil.copytree(wrapper_root if artifact["id"] == 1001 else root / "content", destination)
                return destination

            with patch.object(publisher, "ROOT", source_root), \
                    patch.object(publisher, "_run_artifacts", return_value=[{"name": expected_wrapper, "id": 1001}]), \
                    patch.object(publisher, "_artifact_metadata", side_effect=[
                        {"id": 1001, "digest": "sha256:" + "2" * 64},
                        {"id": 912, "digest": "sha256:" + "1" * 64},
                    ]), \
                    patch.object(publisher, "_download_exact_artifact", side_effect=download), \
                    patch.object(publisher, "run_bytes", side_effect=source):
                publisher.verify_nonandroid_release_evidence(
                    "CyberBASSLord-666/LightForge", {"id": 741, "run_attempt": 1}, RELEASE,
                    HEAD, TREE, content["candidate"]
                )
            sealed = content["source_bindings"]["qa/release-2.2.5/source-clock-verification.json"]
            self.assertIn(sealed["path"], requested_members[1])
            (root / "content" / sealed["path"]).write_bytes(b"tampered")
            with patch.object(publisher, "ROOT", source_root), patch.object(publisher, "run_bytes", side_effect=source), \
                    self.assertRaisesRegex(ValueError, "sealed runtime material differs"):
                publisher._validate_verification_source_hashes(
                    HEAD, content["receipts"], content["source_bindings"], root / "content"
                )


if __name__ == "__main__":
    unittest.main()
