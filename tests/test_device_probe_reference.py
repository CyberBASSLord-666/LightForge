"""Frozen probe evidence remains attributable after production source changes."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("frozen_probe_reference", ROOT / "tools/analyze_inference_device_probe.py")
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)
SOURCE, SOURCE_SHA = PROBE.load(ROOT / (PROBE.REFERENCE + "device-probe-sources.json"))
BUILD, _ = PROBE.load(ROOT / (PROBE.REFERENCE + "device-probe-build.json"))
FROZEN = ROOT / "build/inference-device-probe/run-w6e3elh2"


class FrozenProbeReferenceTest(unittest.TestCase):
    @unittest.skipUnless(FROZEN.is_dir(), "Retained diagnostic build is not present")
    def test_historical_source_is_independent_of_current_changes(self):
        changed = "android/src/com/cyberbasslord/lightforge/NativeDeux.java"
        original_safe_file = PROBE.safe_file
        with tempfile.TemporaryDirectory() as directory:
            replacement = Path(directory) / "changed.java"
            replacement.write_text("// Intentional current-source change\n")

            def select(root, relative):
                return replacement if root == ROOT and relative == changed else original_safe_file(root, relative)

            with mock.patch.object(PROBE, "safe_file", side_effect=select):
                result = PROBE.verify_reference(SOURCE, BUILD, SOURCE_SHA, ROOT, frozen_dir=FROZEN)
        self.assertTrue(result["historical_binding_passed"])
        self.assertEqual(result["historical_source_files_verified"], 15)
        self.assertEqual(result["historical_compiled_classes_verified"], 67)
        self.assertEqual(result["qualification_ordinals"], [0, 4, 8])
        self.assertFalse(result["current_source_binding_passed"])
        mismatch = next(item for item in result["current_source_mismatches"] if item["path"] == changed)
        self.assertEqual(mismatch["reason"], "sha256-mismatch")
        self.assertEqual(mismatch["expected_sha256"], SOURCE["sourceHashes"][changed])

    @unittest.skipUnless(FROZEN.is_dir(), "Retained diagnostic build is not present")
    def test_tampered_frozen_source_class_runtime_and_apk_are_rejected(self):
        original_digest = PROBE.digest
        paths = ["java-src/com/cyberbasslord/lightforge/NativeDeux.java",
                 "classes/com/cyberbasslord/lightforge/NativeDeux.class", "classes.jar",
                 "runtime/jni/arm64-v8a/libonnxruntime.so", "LightForge-inference-probe.apk"]
        for relative in paths:
            with self.subTest(relative=relative):
                target = FROZEN / relative
                with mock.patch.object(PROBE, "digest", side_effect=lambda path: "0" * 64 if path == target else original_digest(path)):
                    with self.assertRaisesRegex(ValueError, "Frozen file hash mismatch"):
                        PROBE.verify_reference(SOURCE, BUILD, SOURCE_SHA, ROOT, frozen_dir=FROZEN)

    @unittest.skipUnless(FROZEN.is_dir(), "Retained diagnostic build is not present")
    def test_frozen_receipts_cannot_be_replaced_by_claimed_receipts(self):
        source = copy.deepcopy(SOURCE)
        source["sourceHashes"]["android/src/com/cyberbasslord/lightforge/NativeDeux.java"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Frozen source receipt identity mismatch"):
            PROBE.verify_reference(source, BUILD, SOURCE_SHA, ROOT, frozen_dir=FROZEN)
        build = {**BUILD, "bytes": BUILD["bytes"] + 1}
        with self.assertRaisesRegex(ValueError, "Frozen build receipt identity mismatch"):
            PROBE.verify_reference(SOURCE, build, SOURCE_SHA, ROOT, frozen_dir=FROZEN)

    def test_path_traversal_and_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "file").write_text("test")
            (root / "linked").symlink_to(root / "file")
            for path in ("../file", "/file", "sub\\file", "linked"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    PROBE.safe_file(root, path)

    def test_only_recognized_consistent_frozen_schedule_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = Path(directory) / "NativePassagePolicy.java"
            for spacing, expected in (("*4", [0, 4, 8]), ("", [0, 1, 2])):
                policy.write_text("int due=qualificationCount" + spacing + ";\n"
                                  "if(pair.ordinal!=qualificationCount" + spacing + "||bad){}")
                self.assertEqual(PROBE.bound_qualification_ordinals(policy), expected)
            for code in ("int due=qualificationCount; if(pair.ordinal!=qualificationCount*4||bad){}",
                         "int due=somethingElse;"):
                policy.write_text(code)
                with self.assertRaises(ValueError):
                    PROBE.bound_qualification_ordinals(policy)


if __name__ == "__main__":
    unittest.main()
