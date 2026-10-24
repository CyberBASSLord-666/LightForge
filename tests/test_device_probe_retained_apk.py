"""Portable retained-artifact verifier tests; synthetic APKs, no Android execution.

Only these tests replace the reviewed-audit allowlist. Production callers cannot
provide new trusted hashes through receipts, APK metadata, or CLI arguments.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import stat
import struct
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("retained_probe_reference", ROOT / "tools/analyze_inference_device_probe.py")
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)
ARCHIVE = ROOT / "research/inference-device-regression-20260928/device-probe-v2-79dba57cc55d"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


class RetainedApkReferenceTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.repo, self.archive = self.root / "repo", self.root / "archive"
        self.repo.mkdir(); self.archive.mkdir()
        self.apk = self.root / "probe.apk"
        self.source, _ = PROBE.load(ARCHIVE / "source-receipt.json")
        self.build, _ = PROBE.load(ARCHIVE / "build.json")
        self.audit, _ = PROBE.load(ARCHIVE / "verification.json")
        fixture = self.source["fixture"]
        paths = list(self.source["sourceHashes"]) + [
            "qa/inference-device-probe/build_probe.py", "qa/inference-device-probe/AndroidManifest.xml",
            "android/native-runtime.json", "web/analysis/models/deux/manifest.json", fixture["sourceProvenancePath"],
        ]
        for path in paths:
            destination = self.repo / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, destination)
            if path in self.source["sourceHashes"]:
                self.source["sourceHashes"][path] = sha(destination.read_bytes())
        original = self.repo / fixture["sourcePath"]
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(b"synthetic original Float32 fixture; not real inference evidence")
        fixture["sourceSha256"] = sha(original.read_bytes())
        # Correct byte geometry but deliberately synthetic content, stored without compression.
        pcm = b"\x00" * (44 + 300032 * 2 * 2)
        fixture["pcm16Sha256"] = sha(pcm)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(PROBE, "FIXTURE_SHA", fixture["pcm16Sha256"]).start()
        self.allowlist = {}
        mock.patch.object(PROBE, "RETAINED_APK_AUDITS", self.allowlist).start()
        self.members = {"AndroidManifest.xml": b"synthetic compiled XML", "resources.arsc": b"synthetic resources",
                        "META-INF/PROBE.SF": b"synthetic signature descriptor",
                        "META-INF/PROBE.RSA": b"synthetic certificate; not a valid signature",
                        "META-INF/MANIFEST.MF": b"synthetic JAR manifest",
                        "classes.dex": b"dex\n035\x00synthetic DEX fixture",
                        "assets/probe/falcon-mix.wav": pcm}
        for name, pin in self.source["runtime"]["files"].items():
            if name.startswith("jni/"):
                data = ("synthetic native library " + name).encode()
                pin.update(bytes=len(data), sha256=sha(data))
                self.members["lib/" + name[len("jni/"):]] = data
        for name, pin in self.source["runtime"]["notices"].items():
            data = ("synthetic notice " + name).encode()
            pin.update(bytes=len(data), sha256=sha(data))
            self.members["assets/probe/" + name] = data
        self.members["assets/probe/source-receipt.json"] = encoded(self.source)
        self.members["assets/probe/fixture-provenance.json"] = encoded(fixture)
        (self.archive / "source-receipt.json").write_bytes(encoded(self.source))
        shutil.copyfile(ARCHIVE / "AndroidManifest.xml", self.archive / "AndroidManifest.xml")
        (self.archive / "build.log").write_text("Synthetic original inspection for unit tests only.\n")
        self.source_sha = sha(encoded(self.source))
        self.audit["dexHashes"] = {"classes.dex": sha(self.members["classes.dex"])}
        self.write_apk()

    def write_apk(self, entries=None):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)  # Duplicate-member rejection tests are intentional.
            with zipfile.ZipFile(self.apk, "w", compression=zipfile.ZIP_STORED) as archive:
                for name, data in entries if entries is not None else self.members.items():
                    archive.writestr(name, data)
        self.seal_test_audit()

    def seal_test_audit(self):
        """Test-only independent trust root; production has a literal reviewed allowlist."""
        self.build.update(bytes=self.apk.stat().st_size, sha256=sha(self.apk.read_bytes()), sourceReceiptSha256=self.source_sha)
        (self.archive / "build.json").write_bytes(encoded(self.build))
        self.audit["artifact"] = copy.deepcopy(self.build)
        self.audit["sourceBinding"].update(source_reference_sha256=self.source_sha, apk_sha256=self.build["sha256"],
                                           fixture_pcm16_sha256=self.source["fixture"]["pcm16Sha256"])
        self.audit["archiveReceipts"] = {name: sha((self.archive / name).read_bytes()) for name in
                                         ("AndroidManifest.xml", "build.json", "build.log", "source-receipt.json")}
        (self.archive / "verification.json").write_bytes(encoded(self.audit))
        self.allowlist.clear()
        self.allowlist[sha(encoded(self.audit))] = {
            "commit": "synthetic-unit-test-only", "apk_sha256": self.build["sha256"], "apk_bytes": self.build["bytes"],
            "source_sha256": self.source_sha, "build_sha256": sha(encoded(self.build)),
        }

    def verify(self, source=None, build=None):
        return PROBE.verify_retained_apk_reference(source or self.source, build or self.build, self.source_sha,
                                                  self.repo, self.apk, self.archive / "verification.json")

    def test_explicit_identity_scopes_do_not_claim_rebuilt_classes_or_new_signature_check(self):
        result = self.verify()
        self.assertTrue(result["retained_apk_binding_passed"])
        self.assertTrue(result["current_source_binding_passed"])
        self.assertEqual(len(result["newly_verified_apk_members"]), 19)
        self.assertEqual(result["repository_source_files_verified"], 15)
        self.assertFalse(result["original_build_bytes_reconstructed"])
        self.assertFalse(result["signature_verification_performed_now"])
        self.assertFalse(result["release_qualification_performed"])
        self.assertNotIn("historical_binding_passed", result)
        self.assertNotIn("historical_compiled_classes_verified", result)
        self.assertEqual(result["historical_only_checks"]["original_compiled_class_count"], 75)

    def test_current_source_drift_remains_an_explicit_failed_gate(self):
        path = self.repo / "android/src/com/cyberbasslord/lightforge/NativeDeux.java"
        path.write_text("changed\n")
        (self.repo / self.source["fixture"]["sourcePath"]).unlink()
        result = self.verify()
        self.assertTrue(result["retained_apk_binding_passed"])
        self.assertFalse(result["current_source_binding_passed"])
        self.assertEqual({row["reason"] for row in result["current_source_mismatches"]},
                         {"sha256-mismatch", "missing-or-unsafe-reference-file"})

    def test_tampered_full_apk_is_rejected_before_zip_parsing(self):
        with self.apk.open("r+b") as stream:
            stream.seek(100); stream.write(b"X")
        with self.assertRaisesRegex(ValueError, "Retained APK hash mismatch"):
            self.verify()

    def test_unreviewed_audit_cannot_supply_its_own_trust(self):
        audit = self.archive / "verification.json"
        audit.write_bytes(audit.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "Unreviewed retained APK audit"):
            self.verify()

    def test_archive_receipt_tampering_is_rejected(self):
        for name in ("build.json", "source-receipt.json", "AndroidManifest.xml", "build.log"):
            path = self.archive / name
            original = path.read_bytes()
            with self.subTest(name=name):
                path.write_bytes(original + b" ")
                try:
                    with self.assertRaisesRegex(ValueError, "Frozen file hash mismatch"):
                        self.verify()
                finally:
                    path.write_bytes(original)

    def test_claimed_reference_objects_cannot_replace_bound_archive(self):
        source = copy.deepcopy(self.source)
        source["runtimeVersion"] = "untrusted"
        with self.assertRaisesRegex(ValueError, "Claimed source differs"):
            self.verify(source=source)
        with self.assertRaisesRegex(ValueError, "Claimed build differs"):
            self.verify(build={**self.build, "bytes": self.build["bytes"] + 1})

    def test_unsafe_linked_apk_is_rejected(self):
        real = self.root / "real.apk"
        self.apk.rename(real); self.apk.symlink_to(real)
        with self.assertRaisesRegex(ValueError, "Missing or linked retained APK"):
            self.verify()

    def test_duplicate_and_unexpected_zip_entries_are_rejected(self):
        for added in (("classes.dex", b"duplicate"), ("assets/probe/unreviewed.json", b"{}"), ("../escape", b"bad")):
            with self.subTest(added=added[0]):
                self.write_apk([*self.members.items(), added])
                with self.assertRaisesRegex(ValueError, "Duplicate APK entries|Unexpected APK member inventory"):
                    self.verify()

    def test_individual_source_dex_native_fixture_notice_pins_are_checked(self):
        for name in ("assets/probe/source-receipt.json", "classes.dex", "lib/arm64-v8a/libonnxruntime.so",
                     "assets/probe/falcon-mix.wav", "assets/probe/onnxruntime-native-LICENSE.txt"):
            with self.subTest(name=name):
                changed = dict(self.members)
                data = changed[name]; changed[name] = bytes([data[0] ^ 1]) + data[1:]
                self.write_apk(changed.items())
                with self.assertRaisesRegex(ValueError, "APK member pin mismatch"):
                    self.verify()

    def test_fixture_metadata_is_compared_and_duplicate_json_keys_rejected(self):
        for raw, message in ((b'{"channels": 999}', "APK fixture provenance mismatch"),
                             (b'{"channels": 2, "channels": 1}', "Duplicate JSON key"),
                             (b'{"value": NaN}', "Non-finite APK JSON")):
            with self.subTest(raw=raw):
                self.write_apk({**self.members, "assets/probe/fixture-provenance.json": raw}.items())
                with self.assertRaisesRegex(ValueError, message):
                    self.verify()

    def test_zip_member_symlinks_and_unsupported_compression_rejected(self):
        for mode in ("symlink", "bzip2"):
            with self.subTest(mode=mode):
                entries = []
                for name, data in self.members.items():
                    if name == "resources.arsc":
                        info = zipfile.ZipInfo(name)
                        if mode == "symlink":
                            info.external_attr = (stat.S_IFLNK | 0o777) << 16
                        else:
                            info.compress_type = zipfile.ZIP_BZIP2
                        name = info
                    entries.append((name, data))
                self.write_apk(entries)
                with self.assertRaisesRegex(ValueError, "Unsupported APK member type or encoding"):
                    self.verify()

    def test_central_directory_and_decompression_are_bounded(self):
        data = bytearray(self.apk.read_bytes())
        struct.pack_into("<HH", data, len(data) - 22 + 8, 65, 65)
        self.apk.write_bytes(data); self.seal_test_audit()
        with self.assertRaisesRegex(ValueError, "oversized APK central directory"):
            self.verify()
        entries = []
        for name, content in self.members.items():
            if name == "resources.arsc":
                name = zipfile.ZipInfo(name); name.compress_type = zipfile.ZIP_DEFLATED
                content = b"\x00" * (PROBE.LIMIT + 1)
            entries.append((name, content))
        self.write_apk(entries)
        with self.assertRaisesRegex(ValueError, "size or compression exceeds bounds"):
            self.verify()

    def test_cli_recovery_requires_explicit_references_and_excludes_frozen_mode(self):
        base = ["probe", "--report", "r.json", "--output", "o.json"]
        cases = [["--retained-apk", "p.apk"], ["--reference-audit", "a.json"],
                 ["--retained-apk", "p.apk", "--reference-audit", "a.json"],
                 ["--retained-apk", "p.apk", "--frozen-build", "build"]]
        for extra in cases:
            with self.subTest(extra=extra), mock.patch("sys.argv", base + extra), mock.patch("sys.stderr"):
                with self.assertRaises(SystemExit) as error:
                    PROBE.main()
                self.assertEqual(error.exception.code, 2)

    def test_cli_current_source_gate_still_fails_and_never_calls_frozen_verifier(self):
        (self.repo / self.source["fixture"]["sourcePath"]).unlink()
        report = self.root / "report.json"
        report.write_text("{}")
        output = self.root / "analysis.json"
        argv = ["probe", "--report", str(report), "--output", str(output), "--repo", str(self.repo),
                "--retained-apk", str(self.apk), "--reference-audit", str(self.archive / "verification.json"),
                "--reference-source", str(self.archive / "source-receipt.json"),
                "--reference-build", str(self.archive / "build.json"), "--require-current-source"]
        structural = {"integrity": {"passed": True}, "run": {"outcome": "cancelled", "completed_passages": 0}}
        with mock.patch("sys.argv", argv), mock.patch.object(PROBE, "analyze", return_value=structural), \
                mock.patch.object(PROBE, "verify_reference", side_effect=AssertionError("strict mode must not be replaced")), \
                mock.patch("builtins.print"):
            self.assertEqual(PROBE.main(), 1)
        stored = json.loads(output.read_text())
        self.assertTrue(stored["current_source_gate"]["required"])
        self.assertFalse(stored["current_source_gate"]["passed"])


class ReviewedAuditPinTest(unittest.TestCase):
    def test_real_reviewed_archive_has_literal_approved_identity(self):
        # No synthetic replacements in this class. No recovered APK is required for CI.
        audit, audit_sha = PROBE.load(ARCHIVE / "verification.json")
        approved = PROBE.RETAINED_APK_AUDITS[audit_sha]
        self.assertEqual(approved["commit"], "6a91949a060f7bb8543266242ca01f4d2904c069")
        self.assertEqual(audit["artifact"]["sha256"], approved["apk_sha256"])
        self.assertEqual(sha((ARCHIVE / "source-receipt.json").read_bytes()), approved["source_sha256"])
        self.assertEqual(sha((ARCHIVE / "build.json").read_bytes()), approved["build_sha256"])


if __name__ == "__main__":
    unittest.main()
