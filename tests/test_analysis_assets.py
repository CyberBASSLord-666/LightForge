"""The asset manifest cannot legitimize graphs absent from a model registry."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import verify_analysis_assets as assets


class AnalysisAssetTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.base = self.root / 'web/analysis'
        for model in ['deux', 'game']:
            directory = self.base / 'models' / model
            directory.mkdir(parents=True)
            graph = directory / 'front.onnx'
            graph.write_bytes(b'fixture executable model graph')
            (directory / 'manifest.json').write_text(json.dumps({'files': {
                graph.name: self.identity(graph)}}))
        self.regenerate_assets()

    @staticmethod
    def identity(path):
        return {'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def regenerate_assets(self):
        manifest = {p.relative_to(self.base).as_posix(): self.identity(p)
                    for p in self.base.rglob('*') if p.is_file() and p.name != 'ASSET_MANIFEST.json'}
        (self.base / 'ASSET_MANIFEST.json').write_text(json.dumps(manifest))

    def verify(self):
        with patch.object(assets, 'ROOT', self.root):
            return assets.verify()

    def test_declared_model_graphs_pass(self):
        self.assertEqual(self.verify(), 4)

    def test_regenerated_outer_manifest_cannot_legitimize_an_obsolete_graph(self):
        for model in ['deux', 'game']:
            with self.subTest(model=model):
                obsolete = self.base / 'models' / model / 'block-00.onnx'
                obsolete.write_bytes(b'old combined attention graph')
                self.regenerate_assets()
                with self.assertRaisesRegex(RuntimeError, 'Model graph inventory mismatch for ' + model):
                    self.verify()
                obsolete.unlink()
                self.regenerate_assets()

    def test_regenerated_outer_manifest_cannot_hide_a_missing_model_graph(self):
        (self.base / 'models/deux/front.onnx').unlink()
        self.regenerate_assets()
        with self.assertRaisesRegex(RuntimeError, 'Model graph inventory mismatch for deux'):
            self.verify()


if __name__ == '__main__':
    unittest.main()
