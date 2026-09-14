#!/usr/bin/env python3
"""Adversarial coverage for the unprivileged-to-publisher data boundary."""

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location("release_material_handoff", ROOT / "tools/release_material_handoff.py")
handoff = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(handoff)


class ReleaseMaterialHandoffTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lightforge-material-handoff-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.producer = self.root / "producer"
        self.producer.mkdir()
        self.data = {path: ("test material: " + path + "\n").encode() for path in handoff.MATERIAL_PATHS}
        records = {path: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                   for path, data in self.data.items()}
        for provenance in sorted(set(handoff.RECONSTRUCTED_MATERIAL_PROVENANCE.values())):
            selected = [path for path, source in handoff.RECONSTRUCTED_MATERIAL_PROVENANCE.items()
                        if source == provenance]
            if provenance.endswith("manifest.json"):
                document = {"files": {Path(path).name: records[path] for path in selected}}
            else:
                document = {"tracks": [{"id": "falcon", "pcmSHA256": {
                    "falcon-mix.wav": records[selected[0]]["sha256"]}}]}
            path = self.producer / provenance
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document), encoding="utf-8")
        (self.producer / ".gitignore").write_text("*.onnx\n*.wav\n*.cache\n", encoding="utf-8")
        self.git(self.producer, "init", "-q")
        self.git(self.producer, "add", ".")
        self.git(self.producer, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-qm", "Synthetic immutable material provenance")
        self.commit = self.git(self.producer, "rev-parse", "HEAD").decode().strip()
        self.consumer = self.root / "consumer"
        shutil.copytree(self.producer, self.consumer)
        for relative, data in self.data.items():
            path = self.producer / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.archive = self.root / "materials.zip"

    @staticmethod
    def git(root, *arguments):
        return subprocess.check_output(["git", "-C", str(root), *arguments], stderr=subprocess.PIPE)

    def write(self):
        return handoff.write_handoff(self.producer, self.commit, self.archive)

    def install(self, archive=None):
        return handoff.install_handoff(self.consumer, self.commit, archive or self.archive)

    def rewrite(self, transform):
        output = self.root / "mutated.zip"
        with zipfile.ZipFile(self.archive) as source, zipfile.ZipFile(output, "w") as target:
            entries = [(entry, source.read(entry)) for entry in source.infolist()]
            for entry, data in transform(entries):
                target.writestr(entry, data)
        return output

    def manifest_change(self, change):
        def transform(entries):
            output = []
            for entry, data in entries:
                if entry.filename == handoff.MANIFEST_NAME:
                    document = json.loads(data)
                    change(document)
                    data = (handoff.canonical_json(document) + "\n").encode()
                output.append((entry, data))
            return output
        return self.rewrite(transform)

    def assert_no_install(self):
        self.assertEqual(handoff._generated_inventory(self.consumer), set())

    def test_roundtrip_and_cli_verify(self):
        expected = self.write()
        self.assertEqual(len(expected["files"]), 33)
        self.assertEqual(self.install(), expected)
        self.assertEqual(handoff.verify_installed(self.consumer, self.commit), expected)
        for relative, data in self.data.items():
            self.assertEqual((self.consumer / relative).read_bytes(), data)
        result = subprocess.run(
            [sys.executable, "-E", "-S", str(ROOT / "tools/release_material_handoff.py"), "verify",
             "--source-root", str(self.consumer), "--source-commit", self.commit],
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(json.loads(result.stdout), {"materials": 33, "source_commit": self.commit})

    def test_producer_extras_are_not_transferred(self):
        for name in ("download.cache", "unexpected.txt", "stem.wav"):
            (self.producer / "web/analysis/models/game" / name).write_bytes(b"extra")
        self.write()
        with zipfile.ZipFile(self.archive) as archive:
            self.assertEqual(set(archive.namelist()), handoff.MATERIAL_PATHS | {handoff.MANIFEST_NAME})
        self.install()

    def test_producer_tampering_fails_against_immutable_git_provenance(self):
        relative = "web/analysis/models/game/encoder.onnx"
        (self.producer / relative).write_bytes(b"mutated")
        path = self.producer / handoff.RECONSTRUCTED_MATERIAL_PROVENANCE[relative]
        manifest = json.loads(path.read_bytes())
        manifest["files"]["encoder.onnx"] = {"bytes": 7, "sha256": hashlib.sha256(b"mutated").hexdigest()}
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "manifest differs"):
            self.write()
        self.assertFalse(self.archive.exists())

    def test_full_source_commit_and_head_binding_are_required(self):
        for invalid in (self.commit[:7], "A" * 40, "a" * 40, "main", "../HEAD"):
            with self.subTest(source=invalid), self.assertRaises(ValueError):
                handoff.write_handoff(self.producer, invalid, self.archive)

    def test_missing_extra_traversal_and_duplicate_members_are_rejected(self):
        self.write()
        transforms = [lambda entries: entries[:-1]]
        for name in ("extra.txt", "../escape", "/absolute", "web/analysis/models/game/../escape"):
            transforms.append(lambda entries, name=name: entries + [(handoff._zip_info(name), b"extra")])
        transforms.append(lambda entries: entries + [entries[-1]])
        for transform in transforms:
            with self.subTest(transform=transform), warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive = self.rewrite(transform)
                with self.assertRaisesRegex(ValueError, "inventory differs"):
                    self.install(archive)
                self.assert_no_install()

    def test_symlink_special_and_compressed_members_are_rejected(self):
        self.write()
        for mode in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFDIR, 0):
            def transform(entries, mode=mode):
                entry, data = entries[-1]
                entry.external_attr = (mode | 0o600) << 16
                return entries[:-1] + [(entry, data)]
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "regular files"):
                self.install(self.rewrite(transform))
            self.assert_no_install()
        def compress(entries):
            entries[-1][0].compress_type = zipfile.ZIP_DEFLATED
            return entries
        with self.assertRaisesRegex(ValueError, "compression"):
            self.install(self.rewrite(compress))
        self.assert_no_install()

    def test_encryption_flags_are_rejected(self):
        self.write()
        with zipfile.ZipFile(self.archive) as archive:
            entries = archive.infolist()
            entries[-1].flag_bits |= 1
            with mock.patch.object(archive, "infolist", return_value=entries):
                with self.assertRaisesRegex(ValueError, "encryption"):
                    handoff._read_manifest(archive, self.commit, handoff._provenance(self.consumer, self.commit))

    def test_wrong_source_hash_size_and_schema_fail_before_install(self):
        self.write()
        relative = "web/analysis/models/game/encoder.onnx"
        changes = [lambda document: document.update(source_commit="a" * 40),
                   lambda document: document["files"][relative].update(sha256="0" * 64),
                   lambda document: document["files"][relative].update(bytes=1),
                   lambda document: document["files"][relative].update(bytes=True),
                   lambda document: document.update(schema_version=True),
                   lambda document: document.update(extra="untrusted")]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.install(self.manifest_change(change))
            self.assert_no_install()

    def test_corrupt_payload_fails_before_any_install(self):
        self.write()
        def corrupt(entries):
            entry, data = entries[-1]
            return entries[:-1] + [(entry, b"X" * len(data))]
        with self.assertRaisesRegex(ValueError, "digest differs"):
            self.install(self.rewrite(corrupt))
        self.assert_no_install()

    def test_manifest_duplicate_keys_and_oversize_are_rejected(self):
        self.write()
        for payload in (b'{"kind":"first","kind":"second"}', b" " * (handoff.MAX_MANIFEST_BYTES + 1)):
            def transform(entries, payload=payload):
                return [(entry, payload if entry.filename == handoff.MANIFEST_NAME else data)
                        for entry, data in entries]
            with self.subTest(size=len(payload)), self.assertRaises(ValueError):
                self.install(self.rewrite(transform))
            self.assert_no_install()

    def test_archive_and_material_symlinks_are_rejected(self):
        self.write()
        archive_link = self.root / "archive-link.zip"
        archive_link.symlink_to(self.archive)
        with self.assertRaises(OSError):
            self.install(archive_link)
        relative = "web/analysis/models/game/encoder.onnx"
        target = self.consumer / relative
        target.symlink_to(self.producer / relative)
        with self.assertRaises(ValueError):
            self.install()
        self.assertTrue(target.is_symlink())

    def test_symlink_ancestor_is_rejected_even_when_target_is_inside_root(self):
        self.write()
        fixtures = self.consumer / "qa/release-1.6.0/fixtures"
        fixtures.symlink_to(self.consumer / "web/analysis/models/game", target_is_directory=True)
        with self.assertRaises(ValueError):
            self.install()

    def test_producer_symlink_and_special_file_are_rejected(self):
        relative = "web/analysis/models/game/encoder.onnx"
        target = self.producer / relative
        target.unlink()
        target.symlink_to(self.producer / "web/analysis/models/game/bd2dur.onnx")
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.write()
        target.unlink()
        import os
        os.mkfifo(target)
        with self.assertRaisesRegex(ValueError, "regular file"):
            self.write()

    def test_existing_material_is_never_overwritten(self):
        self.write()
        self.install()
        with self.assertRaisesRegex(ValueError, "empty generated"):
            self.install()
        for relative, data in self.data.items():
            self.assertEqual((self.consumer / relative).read_bytes(), data)
        with self.assertRaises(FileExistsError):
            self.write()

    def test_consumer_ignored_and_unignored_extras_are_rejected(self):
        self.write()
        self.install()
        for name in ("extra.cache", "extra.txt"):
            target = self.consumer / "web/analysis/models/game" / name
            target.write_bytes(b"extra")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "inventory differs"):
                handoff.verify_installed(self.consumer, self.commit)
            target.unlink()

    def test_total_size_limit_is_enforced_on_both_sides(self):
        self.write()
        with mock.patch.object(handoff, "MAX_TOTAL_BYTES", 100):
            with self.assertRaisesRegex(ValueError, "size|limit"):
                handoff.write_handoff(self.producer, self.commit, self.root / "too-big.zip")
            with self.assertRaisesRegex(ValueError, "size|limit"):
                self.install()
        self.assert_no_install()


if __name__ == "__main__":
    unittest.main()
