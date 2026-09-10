"""Regression coverage for deterministic analysis-asset manifest regeneration."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools/regenerate_analysis_asset_manifest.py"
spec = importlib.util.spec_from_file_location("regenerate_analysis_asset_manifest", SOURCE)
manifest_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manifest_tool)


class AnalysisAssetManifestTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.analysis = self.root / "web" / "analysis"
        (self.analysis / "models" / "deux").mkdir(parents=True)
        (self.analysis / "README.md").write_bytes(b"licensed source\n")
        (self.analysis / "separator-deux.js").write_bytes(b"export const enabled = false;\n")
        (self.analysis / "models" / "deux" / "front.onnx").write_bytes(b"model-bytes")
        (self.analysis / ".ignored").write_bytes(b"not an asset")
        (self.analysis / "__pycache__").mkdir()
        (self.analysis / "__pycache__" / "ignored.pyc").write_bytes(b"not an asset")

    def test_write_then_check_is_canonical_and_byte_bound(self):
        first = manifest_tool.execute(self.root, write=True)
        self.assertEqual(first["assetCount"], 3)
        self.assertEqual(first["mode"], "write")
        data = json.loads((self.analysis / "ASSET_MANIFEST.json").read_text())
        self.assertEqual(list(data), ["README.md", "models/deux/front.onnx", "separator-deux.js"])
        self.assertEqual(data["separator-deux.js"], {
            "bytes": 30,
            "sha256": hashlib.sha256(b"export const enabled = false;\n").hexdigest(),
        })
        checked = manifest_tool.execute(self.root, write=False)
        self.assertEqual(checked["mode"], "check")
        self.assertEqual(checked["generatedManifestSha256"], first["generatedManifestSha256"])
        self.assertTrue(checked["upToDate"])

    def test_check_rejects_an_unbound_asset_change(self):
        manifest_tool.execute(self.root, write=True)
        (self.analysis / "separator-deux.js").write_bytes(b"export const enabled = true;\n")
        with self.assertRaisesRegex(ValueError, "manifest is stale"):
            manifest_tool.execute(self.root, write=False)
        _, _, report = manifest_tool.inspect(self.root)
        self.assertEqual(report["differences"]["changed"], ["separator-deux.js"])

    def test_check_rejects_noncanonical_manifest_serialization(self):
        manifest_tool.execute(self.root, write=True)
        path = self.analysis / "ASSET_MANIFEST.json"
        path.write_text(json.dumps(json.loads(path.read_text())))
        with self.assertRaisesRegex(ValueError, "manifest is stale"):
            manifest_tool.execute(self.root, write=False)


if __name__ == "__main__":
    unittest.main()
