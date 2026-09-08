"""Corruption cases for the version-specific reviewed diagnostics transition."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'qa/release-2.2.2/verify-analysis.py'
spec = importlib.util.spec_from_file_location('analysis_evidence_2_2_2', SOURCE)
protocol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(protocol)


class ReviewedAdapterEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for relative in ['web/analysis/ASSET_MANIFEST.json', 'web/analysis/analyzer.js', 'web/analysis/worker.js',
                         'qa/release-2.2.2/prior-source/ASSET_MANIFEST.json',
                         'qa/release-2.2.2/prior-source/analyzer.js', 'qa/release-2.2.2/prior-source/worker.js']:
            self.copy(relative)
        self.manifest = json.loads((ROOT / 'web/analysis/ASSET_MANIFEST.json').read_text())

    def copy(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, path)
        return path

    def change_first_byte(self, path):
        data = path.read_bytes()
        path.write_bytes(bytes([data[0] ^ 1]) + data[1:])

    def test_only_the_exact_reviewed_source_transition_passes(self):
        hashes = {}
        result = protocol.verify_transition(self.root, hashes)
        self.assertEqual(result, self.manifest)
        for name, pins in protocol.ADAPTERS.items():
            self.assertEqual(hashes['web/analysis/' + name], pins['after'])
            self.assertEqual(hashes[protocol.OUT + 'prior-source/' + name], pins['before'])

    def test_further_adapter_edit_fails_even_with_same_byte_count(self):
        for name in ['analyzer.js', 'worker.js']:
            with self.subTest(name=name):
                path = self.root / 'web/analysis' / name
                original = path.read_bytes()
                self.change_first_byte(path)
                with self.assertRaisesRegex(ValueError, 'Source differs'):
                    protocol.verify_transition(self.root, {})
                path.write_bytes(original)

    def test_regenerated_manifest_cannot_bless_unreviewed_adapter(self):
        path = self.root / 'web/analysis/worker.js'
        self.change_first_byte(path)
        changed = dict(self.manifest)
        changed['worker.js'] = {'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        (self.root / 'web/analysis/ASSET_MANIFEST.json').write_text(json.dumps(changed, indent=2) + '\n')
        with self.assertRaisesRegex(ValueError, 'ASSET_MANIFEST.json'):
            protocol.verify_transition(self.root, {})

    def test_changed_other_adapter_or_inventory_is_rejected(self):
        for change in ['bass-notes.js', 'added.js']:
            with self.subTest(change=change):
                altered = dict(self.manifest)
                altered[change] = {'bytes': 9, 'sha256': hashlib.sha256(b'changed();').hexdigest()}
                (self.root / 'web/analysis/ASSET_MANIFEST.json').write_text(json.dumps(altered, indent=2) + '\n')
                with self.assertRaisesRegex(ValueError, 'ASSET_MANIFEST.json'):
                    protocol.verify_transition(self.root, {})
        # Keeping the manifest intact cannot hide a changed unreviewed adapter.
        path = self.copy('web/analysis/bass-notes.js')
        protocol.verify_asset(self.root, 'bass-notes.js', self.manifest['bass-notes.js'], {})
        self.change_first_byte(path)
        with self.assertRaisesRegex(ValueError, 'bass-notes.js'):
            protocol.verify_asset(self.root, 'bass-notes.js', self.manifest['bass-notes.js'], {})

    def test_modified_numeric_kernel_and_pinned_graph_are_rejected(self):
        kernel = 'android/src/com/cyberbasslord/lightforge/NativeDeux.java'
        original = json.loads((ROOT / 'qa/release-2.2.1/analysis-verification.json').read_text())
        expected = original['source_hashes'][kernel]
        path = self.copy(kernel)
        protocol.verify_bound(self.root, kernel, expected, {})
        self.change_first_byte(path)
        with self.assertRaisesRegex(ValueError, 'NativeDeux.java'):
            protocol.verify_bound(self.root, kernel, expected, {})
        graph = 'models/game/dur2bd.onnx'
        path = self.copy('web/analysis/' + graph)
        protocol.verify_asset(self.root, graph, self.manifest[graph], {})
        self.change_first_byte(path)
        with self.assertRaisesRegex(ValueError, 'dur2bd.onnx'):
            protocol.verify_asset(self.root, graph, self.manifest[graph], {})

    def test_mutated_predecessor_manifest_or_receipt_is_rejected(self):
        path = self.root / protocol.OUT / 'prior-source/ASSET_MANIFEST.json'
        self.change_first_byte(path)
        with self.assertRaisesRegex(ValueError, 'prior-source/ASSET_MANIFEST.json'):
            protocol.verify_transition(self.root, {})
        relative = protocol.OUT + 'prior-source/analysis-verification.json'
        path = self.copy(relative)
        original = path.read_bytes()
        value = json.loads(original)
        value['passed'] = False
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'analysis-verification.json'):
            protocol.verify_bound(self.root, relative, protocol.PRIOR_RECEIPT_SHA256, {})
        self.assertEqual((ROOT / relative).read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
