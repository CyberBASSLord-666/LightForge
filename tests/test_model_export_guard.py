import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from model_export_guard import cached_graph_matches, exporter_identity, verify_digest


class ModelExportGuardTest(unittest.TestCase):
    def test_tampered_checkpoint_rejected_before_torch_import_even_optimized(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / 'tampered.ckpt'
            checkpoint.write_bytes(b'not the approved checkpoint')
            harness = '''
import importlib.abc, runpy, sys
class NoTorch(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'torch' or fullname.startswith('torch.'):
            raise RuntimeError('TORCH_IMPORT_WAS_ATTEMPTED')
sys.meta_path.insert(0, NoTorch())
sys.path.insert(0, sys.argv[1])
sys.argv = [sys.argv[2], '--checkpoint', sys.argv[3]]
runpy.run_path(sys.argv[0], run_name='__main__')
'''
            result = subprocess.run([sys.executable, '-O', '-c', harness,
                                     str(ROOT / 'tools'), str(ROOT / 'tools/prepare_deux.py'),
                                     str(checkpoint)], text=True, capture_output=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('ValueError: Deux checkpoint hash mismatch', result.stderr)
            self.assertNotIn('TORCH_IMPORT_WAS_ATTEMPTED', result.stderr)

    def test_wrong_python_is_rejected_before_distribution_or_cache_checks(self):
        with patch('model_export_guard.platform.python_version', return_value='3.12.13'), \
             patch('model_export_guard.metadata.version') as lookup:
            with self.assertRaisesRegex(ValueError, 'Python mismatch'):
                exporter_identity(ROOT)
            lookup.assert_not_called()

    def test_wrong_installed_exporter_is_rejected(self):
        with patch('model_export_guard.metadata.version', return_value='2.6.0'):
            with self.assertRaisesRegex(ValueError, 'toolchain mismatch'):
                exporter_identity(ROOT)

    def test_cache_requires_toolchain_source_and_graph_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            graph = Path(tmp) / 'graph.onnx'
            graph.write_bytes(b'original graph bytes')
            identity = {'distributions': {'torch': '2.13.0+cpu'},
                        'sourceSHA256': {'config.yaml': 'source-digest'}}
            previous = {'converterSHA256': 'converter', 'exporterIdentity': identity,
                        'files': {graph.name: {'bytes': graph.stat().st_size,
                                  'sha256': hashlib.sha256(graph.read_bytes()).hexdigest()}}}
            self.assertTrue(cached_graph_matches(graph, previous, 'converter', identity))
            altered = json.loads(json.dumps(identity))
            altered['distributions']['torch'] = '2.6.0+cpu'
            self.assertFalse(cached_graph_matches(graph, previous, 'converter', altered))
            altered = json.loads(json.dumps(identity))
            altered['sourceSHA256']['config.yaml'] = 'different-source'
            self.assertFalse(cached_graph_matches(graph, previous, 'converter', altered))
            self.assertFalse(cached_graph_matches(graph, previous, 'different-converter', identity))
            missing_identity = {k: v for k, v in previous.items() if k != 'exporterIdentity'}
            self.assertFalse(cached_graph_matches(graph, missing_identity, 'converter', identity))
            graph.write_bytes(b'tampered graph bytes')
            self.assertFalse(cached_graph_matches(graph, previous, 'converter', identity))
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                verify_digest(graph, previous['files'][graph.name]['sha256'], 'graph')


if __name__ == '__main__':
    unittest.main()
