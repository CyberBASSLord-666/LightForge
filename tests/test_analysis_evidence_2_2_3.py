"""Reject altered fresh native parity evidence and stale release/source bindings."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'qa/release-2.2.3/verify-analysis.py'
spec = importlib.util.spec_from_file_location('analysis_evidence_2_2_3', SOURCE)
protocol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(protocol)


class FreshRuntimeEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for relative in protocol.COMPARISON_SOURCES | {protocol.OUT + 'native-runtime-comparison-verification.json'}:
            self.copy(relative)

    def copy(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        # Archived source must still satisfy the immutable 2.2.3 evidence hash.
        archived = ROOT / "qa/release-2.2.3/prior-source" / relative
        shutil.copyfile(archived if archived.is_file() else ROOT / relative, path)
        return path

    def flip_first_byte(self, path):
        content = path.read_bytes()
        path.write_bytes(bytes([content[0] ^ 1]) + content[1:])

    def test_exact_fresh_comparison_and_its_measured_sources_pass(self):
        hashes = {}
        receipt = protocol.verify_comparison(self.root, hashes)
        self.assertEqual([run['version'] for run in receipt['runs']], ['1.23.2', '1.25.1'])
        self.assertEqual(len(receipt['model_asset_hashes']), 27)
        self.assertTrue(all(stem['identical'] for stem in receipt['comparison']))
        self.assertEqual(hashes[protocol.OUT + 'native-runtime-comparison-verification.json'], protocol.COMPARISON_SHA256)

    def test_modified_receipt_cannot_relabel_a_different_runtime_as_passing(self):
        path = self.root / protocol.OUT / 'native-runtime-comparison-verification.json'
        receipt = json.loads(path.read_text())
        receipt['runs'][1]['version'] = '1.23.2'
        path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, 'Source differs.*native-runtime-comparison'):
            protocol.verify_comparison(self.root, {})

    def test_same_size_predictor_change_rejects_previous_comparison(self):
        self.flip_first_byte(self.root / 'android/src/com/cyberbasslord/lightforge/NativeDeux.java')
        with self.assertRaisesRegex(ValueError, 'Source differs.*NativeDeux.java'):
            protocol.verify_comparison(self.root, {})

    def test_changed_dependency_pins_reject_previous_comparison(self):
        path = self.root / 'android/native-runtime.json'
        manifest = json.loads(path.read_text())
        manifest['version'] = '1.23.2'
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'Source differs.*native-runtime.json'):
            protocol.verify_comparison(self.root, {})

    def test_old_release_version_is_not_accepted(self):
        (self.root / 'version.json').write_text(json.dumps({'name': '2.2.2', 'code': 20202}))
        with self.assertRaisesRegex(ValueError, 'only to 2.2.3'):
            protocol.verify_release(self.root)

    def test_altered_outer_inventory_cannot_bless_changed_models(self):
        path = self.copy('web/analysis/ASSET_MANIFEST.json')
        manifest = json.loads(path.read_text())
        manifest['models/deux/front.onnx']['sha256'] = 'a' * 64
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'Source differs.*ASSET_MANIFEST.json'):
            protocol.verify_assets(self.root, {})

    def test_real_pinned_model_corruption_is_rejected(self):
        relative = 'models/game/dur2bd.onnx'
        path = self.copy('web/analysis/' + relative)
        metadata = json.loads((ROOT / 'web/analysis/ASSET_MANIFEST.json').read_text())[relative]
        protocol.verify_asset(self.root, relative, metadata, {})
        self.flip_first_byte(path)
        with self.assertRaisesRegex(ValueError, 'Source differs.*dur2bd.onnx'):
            protocol.verify_asset(self.root, relative, metadata, {})

    def test_fresh_clock_must_match_current_release_and_exact_sources(self):
        for relative in protocol.CLOCK_SOURCES:
            self.copy(relative)
        clock_path = self.copy(protocol.OUT + 'source-clock-verification.json')
        original = clock_path.read_bytes()
        self.assertTrue(protocol.verify_clock(self.root, {})['passed'])
        clock = json.loads(original)
        clock['release'] = '2.2.2'
        clock_path.write_text(json.dumps(clock))
        with self.assertRaisesRegex(ValueError, 'Fresh 2.2.3'):
            protocol.verify_clock(self.root, {})
        clock_path.write_bytes(original)
        self.flip_first_byte(self.root / 'web/analysis/separator-deux.js')
        with self.assertRaisesRegex(ValueError, 'Source differs.*separator-deux.js'):
            protocol.verify_clock(self.root, {})

    def test_nonfinite_clock_error_cannot_pass_numeric_comparison(self):
        path = self.copy(protocol.OUT + 'source-clock-verification.json')
        clock = json.loads(path.read_text())
        clock['maxAbsError'] = float('nan')
        path.write_text(json.dumps(clock))
        with self.assertRaisesRegex(ValueError, 'clock boundaries'):
            protocol.verify_clock(self.root, {})

    def test_external_binding_paths_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'external source'):
            protocol.bind(self.root, '../outside', hashlib.sha256(b'x').hexdigest(), {})


if __name__ == '__main__':
    unittest.main()
