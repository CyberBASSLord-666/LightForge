#!/usr/bin/env python3
"""Release-publisher tests for sealed, non-Android verify-v2 evidence."""
from __future__ import annotations

import hashlib
import copy
import io
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock


ROOT = Path(__file__).resolve().parents[1]
sys_path = __import__("sys").path
sys_path.insert(0, str(ROOT / "tools"))
PUBLISHER_SPEC = importlib.util.spec_from_file_location("publisher", ROOT / "tools/publish_github_release.py")
publisher = importlib.util.module_from_spec(PUBLISHER_SPEC)
PUBLISHER_SPEC.loader.exec_module(publisher)
EVIDENCE_SPEC = importlib.util.spec_from_file_location("verification_evidence", ROOT / "tools/verification_evidence_manifest.py")
evidence = importlib.util.module_from_spec(EVIDENCE_SPEC)
EVIDENCE_SPEC.loader.exec_module(evidence)
if __package__:
    from .test_verification_evidence_manifest import host_admission
    from .test_host_inference_campaign import FakeGitHub, archive as host_archive
else:
    from test_verification_evidence_manifest import host_admission
    from test_host_inference_campaign import FakeGitHub, archive as host_archive
import host_inference_campaign as campaign
import verify_inference_improvement as host_verifier


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
    def _artifacts(self, root: Path, attempt=1, host=False):
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
        host_path = root / "host-admission.json" if host else None
        if host_path:
            host_path.write_text(json.dumps(host_admission()))
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
                host_admission=host_path,
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

    def _host_proof(self, root, *, indented=False):
        # The synthetic proof below is deliberately not numerical evidence.
        # This fixture exercises the publisher's trusted transport boundary;
        # the separately tested numerical verifier must always be invoked.
        source = root / "source"
        policy_bytes = (ROOT / campaign.POLICY_PATH).read_bytes()
        policy = json.loads(policy_bytes)
        for name in policy["executionClosurePaths"]:
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"SYNTHETIC UNIT FIXTURE: " + name.encode())
        (source / campaign.POLICY_PATH).write_bytes(policy_bytes)
        (source / "version.json").write_text('{"name":"2.4.2","code":20402}')
        fake = FakeGitHub(source)
        fake.status, fake.conclusion = "completed", "success"
        if indented:
            fake.proof_zip = host_archive({
                "declaration.json": campaign.canonical_bytes(fake.declaration),
                "receipt.json": (json.dumps(fake.receipt, indent=2) + "\n").encode(),
            })
        _, receipt, _, check = campaign.fetch_proof(source, api=fake, output_dir=root / "initial-proof")
        admission = campaign.seal_admission(
            check, receipt, candidate_source_commit=HEAD, candidate_source_tree_sha=TREE,
            evidence_session=SESSION, recompiled_class_hashes=receipt["compiledClassHashes"],
        )
        fake.calls.clear()
        return source, fake, admission

    def test_host_publication_revalidates_api_provenance_then_runs_full_raw_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, fake, admission = self._host_proof(root)
            with patch.object(publisher, "ROOT", source), \
                    patch.object(publisher, "_HostAdmissionAPI", return_value=fake), \
                    patch.object(host_verifier, "verify_bounded", return_value=20.0) as replay:
                result = publisher.verify_host_release_admission(evidence.REPOSITORY, {"admission": admission}, pipeline())
            replay.assert_called_once_with(source / "build/release-host-proof/receipt.json", root=source)
            self.assertIn("/branches/main", fake.calls)
            self.assertIn("/actions/artifacts/456", fake.calls)
            self.assertIn("/actions/artifacts/789", fake.calls)
            self.assertEqual(result["admission"], admission)
            self.assertNotEqual(admission["producer"]["headSha"], HEAD)

    def test_host_receipt_digest_binds_exact_original_bytes_not_reserialized_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, fake, admission = self._host_proof(root, indented=True)
            original_bytes = (json.dumps(fake.receipt, indent=2) + "\n").encode()
            self.assertEqual(admission["proofReceiptSha256"], hashlib.sha256(original_bytes).hexdigest())
            self.assertNotEqual(admission["proofReceiptSha256"],
                                hashlib.sha256(campaign.canonical_bytes(fake.receipt)).hexdigest())
            with patch.object(publisher, "ROOT", source), \
                    patch.object(publisher, "_HostAdmissionAPI", return_value=fake), \
                    patch.object(host_verifier, "verify_bounded", return_value=20.0) as replay:
                publisher.verify_host_release_admission(evidence.REPOSITORY, {"admission": admission}, pipeline())
            replay.assert_called_once()
            self.assertEqual((source / "build/release-host-proof/receipt.json").read_bytes(), original_bytes)

    def test_host_file_changed_after_trusted_fetch_is_rejected_before_numeric_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, fake, admission = self._host_proof(root)
            fetch = campaign.fetch_proof

            def changed(*args, **kwargs):
                result = fetch(*args, **kwargs)
                (result[2] / "receipt.json").write_text('{"passed":true}')
                return result

            with patch.object(publisher, "ROOT", source), \
                    patch.object(publisher, "_HostAdmissionAPI", return_value=fake), \
                    patch.object(campaign, "fetch_proof", side_effect=changed), \
                    patch.object(host_verifier, "verify_bounded") as replay:
                with self.assertRaisesRegex(ValueError, "receipt digest differs"):
                    publisher.verify_host_release_admission(evidence.REPOSITORY, {"admission": admission}, pipeline())
            replay.assert_not_called()

    def test_host_publication_rejects_contradictory_live_provenance_before_raw_replay(self):
        changes = (
            lambda f, a: setattr(f, "protected", False),
            lambda f, a: setattr(f, "missing_registration", True),
            lambda f, a: f.missing_artifacts.add(456),
            lambda f, a: f.missing_artifacts.add(789),
            lambda f, a: f.overrides.update({"/actions/artifacts/789": dict(f.metadata(789), digest="sha256:" + "0" * 64)}),
            lambda f, a: f.overrides.update({"/actions/artifacts/789": dict(f.metadata(789), expired=True)}),
            lambda f, a: f.overrides.update({"/actions/artifacts/789": dict(f.metadata(789), workflow_run={"id": 124})}),
            lambda f, a: f.source_corruption.add("tools/benchmark_deux_parallel.py"),
            lambda f, a: a["declarationArtifact"].update(sha256="0" * 64),
            lambda f, a: a["proofArtifact"].update(sha256="0" * 64),
            lambda f, a: a.update(proofReceiptSha256="0" * 64),
            lambda f, a: a["registration"].update(sha256="0" * 64),
            lambda f, a: a.update(policySha256="0" * 64),
            lambda f, a: a.update(declarationSha256="0" * 64),
            lambda f, a: a.update(recompiledClassHashes={"other.class": "0" * 64}),
            lambda f, a: a.update(measurementFinishedAt="2026-10-22T12:00:00Z"),
        )
        for index, change in enumerate(changes):
            with self.subTest(mutation=index), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source, fake, admission = self._host_proof(root)
                change(fake, admission)
                with patch.object(publisher, "ROOT", source), \
                        patch.object(publisher, "_HostAdmissionAPI", return_value=fake), \
                        patch.object(host_verifier, "verify_bounded") as replay:
                    with self.assertRaises(ValueError):
                        publisher.verify_host_release_admission(evidence.REPOSITORY, {"admission": admission}, pipeline())
                replay.assert_not_called()

    def test_host_publication_never_trusts_pass_json_when_numerical_replay_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, fake, admission = self._host_proof(root)
            with patch.object(publisher, "ROOT", source), \
                    patch.object(publisher, "_HostAdmissionAPI", return_value=fake), \
                    patch.object(host_verifier, "verify_bounded", side_effect=ValueError("raw numerical replay failed")):
                with self.assertRaisesRegex(ValueError, "raw numerical replay failed"):
                    publisher.verify_host_release_admission(evidence.REPOSITORY, {"admission": admission}, pipeline())

    def test_current_host_record_is_downloaded_and_replayed_in_addition_to_seven_receipts(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(RELEASE, {"name": "2.4.2", "code": 20402}):
            root = Path(temporary)
            content_root, wrapper_root, content, _ = self._artifacts(root, host=True)
            result_value = {"admission": host_admission(), "median_wall_reduction_percent": 20.0}
            with patch.object(publisher, "verify_host_release_admission", return_value=result_value) as replay:
                result, _, download, _, _ = self._run(root, content_root, wrapper_root, content["candidate"])
            self.assertIn(evidence.HOST_ADMISSION_PATH, download.call_args.args[3])
            replay.assert_called_once_with(evidence.REPOSITORY, content["host_admission"], pipeline())
            self.assertEqual(result["host_admission"], result_value)
            self.assertEqual(set(result["manifest"]["receipts"]), set(evidence.RECEIPTS))

    def test_wrapper_host_record_cannot_disagree_with_content_even_with_plausible_hashes(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(RELEASE, {"name": "2.4.2", "code": 20402}):
            root = Path(temporary)
            content_root, wrapper_root, content, wrapped = self._artifacts(root, host=True)
            changed = copy.deepcopy(wrapped)
            changed["host_admission"]["admission"]["proofArtifact"]["sha256"] = "0" * 64
            (wrapper_root / evidence.WRAPPER_MANIFEST).write_text(json.dumps(changed))
            with patch.object(publisher, "verify_host_release_admission") as replay:
                with self.assertRaisesRegex(ValueError, "content differs from its sealed wrapper"):
                    self._run(root, content_root, wrapper_root, content["candidate"])
            replay.assert_not_called()

    def test_current_missing_host_or_legacy_schema_cannot_reach_replay(self):
        for condition in ("missing", "null", "legacy"):
            with self.subTest(condition=condition), tempfile.TemporaryDirectory() as temporary, \
                    patch.dict(RELEASE, {"name": "2.4.2", "code": 20402}):
                root = Path(temporary)
                content_root, wrapper_root, content, wrapped = self._artifacts(root, host=True)
                changed = copy.deepcopy(wrapped)
                if condition == "null":
                    changed["host_admission"] = None
                else:
                    changed.pop("host_admission")
                    if condition == "legacy":
                        changed["schema_version"] = 2
                (wrapper_root / evidence.WRAPPER_MANIFEST).write_text(json.dumps(changed))
                with patch.object(publisher, "verify_host_release_admission") as replay:
                    with self.assertRaises(ValueError):
                        self._run(root, content_root, wrapper_root, content["candidate"])
                replay.assert_not_called()

    def test_host_api_adapter_uses_only_pinned_repository_and_bounded_download(self):
        adapter = publisher._HostAdmissionAPI(evidence.REPOSITORY, 8)
        with patch.object(publisher, "api", return_value={"id": 701}) as api:
            self.assertEqual(adapter.get("/actions/runs/701"), {"id": 701})
        api.assert_called_once_with("repos/" + evidence.REPOSITORY + "/actions/runs/701")
        for route in ("https://example.com", "//other/actions", "/actions\\x", "/actions#x", "/actions\nx"):
            with self.subTest(route=route), self.assertRaises(ValueError):
                adapter.get(route)
        with self.assertRaisesRegex(ValueError, "repository differs"):
            publisher._HostAdmissionAPI("other/repository", 8)
        process = MagicMock()
        process.__enter__.return_value = process
        process.stdout = io.BytesIO(b"123456789")
        with patch.object(publisher.subprocess, "Popen", return_value=process):
            with self.assertRaisesRegex(ValueError, "safe download limit"):
                adapter.download(802)
        process.kill.assert_called_once()
        process.wait.assert_called_once()

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
            deux = source_root / "web/analysis/models/deux/block-00-frequency.onnx"
            deux.parent.mkdir(parents=True)
            deux.write_bytes(b"deux")
            runtime = source_root / "qa/release-2.2.5/source-clock-verification.json"
            runtime.parent.mkdir(parents=True)
            runtime.write_bytes(b'{"fresh":true}')
            fixture_hash, game_hash, deux_hash, runtime_hash = map(evidence.sha256_file, (fixture, game, deux, runtime))
            hashes = {
                "web/app.js": SOURCE_HASH,
                "qa/release-1.6.0/fixtures/falcon-mix.wav": fixture_hash,
                "web/analysis/models/game/bd2dur.onnx": game_hash,
                "web/analysis/models/deux/block-00-frequency.onnx": deux_hash,
                "qa/release-2.2.5/source-clock-verification.json": runtime_hash,
            }
            for name in evidence.RECEIPTS:
                (receipt_dir / name).write_text(json.dumps(receipt(name, hashes)), encoding="utf-8")
            fixture_provenance = json.dumps({"tracks": [{"id": "falcon", "pcmSHA256": {"falcon-mix.wav": fixture_hash}}]}).encode()
            game_provenance = json.dumps({"files": {"bd2dur.onnx": {"bytes": game.stat().st_size, "sha256": game_hash}}}).encode()
            deux_provenance = json.dumps({"files": {"block-00-frequency.onnx": {"bytes": deux.stat().st_size, "sha256": deux_hash}}}).encode()

            def candidate_bytes(_root, _commit, relative):
                return {
                    "web/app.js": SOURCE_BYTES,
                    "qa/release-1.6.0/musdb-fixture-provenance.json": fixture_provenance,
                    "web/analysis/models/game/manifest.json": game_provenance,
                    "web/analysis/models/deux/manifest.json": deux_provenance,
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
                    "web/analysis/models/deux/manifest.json": deux_provenance,
                }[requested]

            with patch.object(publisher, "ROOT", source_root), patch.object(publisher, "run_bytes", side_effect=source):
                publisher._validate_verification_source_hashes(
                    HEAD, content["receipts"], content["source_bindings"], root / "content"
                )
            self.assertNotIn(("git", "show", HEAD + ":qa/release-2.2.5/source-clock-verification.json"), commands)
            self.assertIn(("git", "show", HEAD + ":web/analysis/models/deux/manifest.json"), commands)
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
