"""Download reuse must never reuse model outputs or source-bound test results."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import json
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import verify_analysis_assets
import verify_v2


def production_steps(text):
    host = text.split('\n  android-background:', 1)[0]
    return re.split(r'(?m)^      - ', host)[1:]


class VerificationDownloadCacheTest(unittest.TestCase):
    def test_cache_key_covers_inline_and_file_dependency_pins(self):
        steps = production_steps((ROOT / '.github/workflows/verify-v2.yml').read_text())
        setup = next(step for step in steps if step.startswith('uses: actions/setup-python@'))
        self.assertIn('cache: pip\n', setup)
        self.assertIn('cache-dependency-path: |\n', setup)
        for path in ('tools/model-requirements.txt', '.github/workflows/verify-v2.yml'):
            self.assertIn('            ' + path + '\n', setup)
        # setup-python caches pip downloads, not a hand-selected mutable tree.
        self.assertNotIn('actions/cache@', '\n'.join(steps))

    def test_cache_hit_cannot_skip_installs_conversions_or_regression(self):
        steps = production_steps((ROOT / '.github/workflows/verify-v2.yml').read_text())
        commands = (
            'python3 -m pip install pip==26.2.1 setuptools==83.0.0',
            'python3 -m pip install torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu',
            'python3 -m pip install -r tools/model-requirements.txt',
            'python3 tools/prepare_game.py',
            'python3 tools/prepare_deux.py',
            'run: npm test',
        )
        text = '\n'.join(steps)
        positions = []
        for command in commands:
            matching = [step for step in steps if command in step]
            self.assertEqual(len(matching), 1, command)
            self.assertNotRegex(matching[0], r'(?m)^\s+if:')
            self.assertNotIn('continue-on-error:', matching[0])
            positions.append(text.index(command))
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn('--no-cache-dir', text)
        self.assertNotIn('cache-hit', text)

    def run_gate(self, temporary, source_snapshots, assets):
        output = Path(temporary) / 'receipts'
        output.mkdir()
        success = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        with patch.object(verify_v2, 'OUT', output), \
                patch.object(verify_v2, 'hashes', side_effect=source_snapshots), \
                patch.object(verify_v2.subprocess, 'run', return_value=success), \
                patch.object(verify_v2, 'run_python_scripts') as quality, \
                patch.object(verify_v2, 'verify_assets', side_effect=assets), \
                patch.object(verify_v2, 'digest', return_value='current-manifest-digest'), \
                redirect_stdout(StringIO()):
            status = verify_v2.main()
        receipt = json.loads((output / 'regression-verification.json').read_text())
        quality.assert_called_once()
        return status, receipt

    def test_missing_model_still_fails_after_all_test_layers_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / 'web/analysis'
            base.mkdir(parents=True)
            (base / 'ASSET_MANIFEST.json').write_text(json.dumps({
                'models/deux/required.onnx': {'bytes': 1, 'sha256': '0' * 64},
            }))
            with patch.object(verify_analysis_assets, 'ROOT', Path(temporary)):
                status, receipt = self.run_gate(
                    temporary, [{'tools/current.py': 'before'}], verify_analysis_assets.verify)
        self.assertEqual(status, 1)
        self.assertFalse(receipt['passed'])
        self.assertEqual(len(receipt['checks']), 3)
        self.assertIn('models/deux/required.onnx', receipt['errors'][0])
        self.assertNotIn('analysis_manifest_sha256', receipt)

    def test_source_mutation_still_fails_after_assets_and_tests_pass(self):
        for after in ({'tools/current.py': 'changed'}, {},
                      {'tools/current.py': 'before', 'tools/added.py': 'new'}):
            with self.subTest(after=after), tempfile.TemporaryDirectory() as temporary:
                status, receipt = self.run_gate(
                    temporary, [{'tools/current.py': 'before'}, after], lambda: 85)
            self.assertEqual(status, 1)
            self.assertFalse(receipt['passed'])
            self.assertIn('Sources changed during verification:', receipt['errors'][0])
            self.assertEqual(receipt['source_hashes'], {'tools/current.py': 'before'})

    def test_success_receipt_is_bound_to_this_invocations_exact_sources(self):
        for identity in ('first-source', 'next-source'):
            source = {'tools/current.py': identity, '.github/workflows/verify-v2.yml': identity}
            with self.subTest(identity=identity), tempfile.TemporaryDirectory() as temporary:
                status, receipt = self.run_gate(temporary, [source, dict(source)], lambda: 85)
            self.assertEqual(status, 0)
            self.assertTrue(receipt['passed'])
            self.assertEqual(receipt['source_hashes'], source)
            self.assertEqual(receipt['analysis_manifest_sha256'], 'current-manifest-digest')
            self.assertEqual(receipt['errors'], [])
            self.assertIn('completedAt', receipt)
            self.assertEqual(receipt['selected_test_suites']['node'], verify_v2.TESTS)
            self.assertEqual(receipt['selected_test_suites']['python_archive'], verify_v2.PYTHON_TESTS)


if __name__ == '__main__':
    unittest.main()
