"""Fail early when the reviewed analysis inventory pin has not been refreshed."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RELEASE = json.loads((ROOT / 'version.json').read_text())['name']
VERIFY = ROOT / f'qa/release-{RELEASE}/verify-analysis.py'
# Reviewed current source inventory only, never a passing execution receipt.
EXPECTED_MANIFEST_SHA256 = '2fa86a5307f071c437c70d09f18ff072069f6f1aa4cb90446849dd449a07909f'
EXPECTED_MANIFEST_ENTRY_COUNT = 85
SPEC = spec_from_file_location('lightforge_verify_analysis_current_inventory', VERIFY)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AssetBindingTest(unittest.TestCase):
    def test_reviewed_asset_inventory_pin_matches_current_bytes(self):
        manifest = MODULE.ROOT / 'web/analysis/ASSET_MANIFEST.json'
        self.assertEqual(MODULE.ASSET_MANIFEST_SHA256, EXPECTED_MANIFEST_SHA256)
        self.assertEqual(MODULE.ASSET_MANIFEST_ENTRY_COUNT, EXPECTED_MANIFEST_ENTRY_COUNT)
        self.assertEqual(MODULE.digest(manifest), EXPECTED_MANIFEST_SHA256)
        self.assertEqual(len(json.loads(manifest.read_text())), EXPECTED_MANIFEST_ENTRY_COUNT)

    def test_unreviewed_manifest_change_still_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = 'web/analysis/ASSET_MANIFEST.json'
            manifest = root / relative
            manifest.parent.mkdir(parents=True)
            manifest.write_bytes((ROOT / relative).read_bytes() + b'\n')
            with self.assertRaisesRegex(ValueError, 'Source differs from measured evidence'):
                MODULE.bind(root, relative, MODULE.ASSET_MANIFEST_SHA256, {})

    def test_reviewed_frontend_sources_still_reject_individual_byte_tampering(self):
        manifest = json.loads((ROOT / 'web/analysis/ASSET_MANIFEST.json').read_text())
        for name in ('analyzer.js', 'dsp.js', 'game.js', 'wav-reader.js', 'worker.js'):
            with self.subTest(source=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / 'web/analysis' / name
                source.parent.mkdir(parents=True)
                data = (ROOT / 'web/analysis' / name).read_bytes()
                source.write_bytes(data)
                MODULE.verify_asset(root, name, manifest[name], {})
                source.write_bytes(data + b'\n')
                with self.assertRaisesRegex(ValueError, 'Source differs from measured evidence'):
                    MODULE.verify_asset(root, name, manifest[name], {})

    def test_reviewed_source_inventory_cannot_substitute_for_fresh_execution_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = 'web/analysis/ASSET_MANIFEST.json'
            manifest = root / relative
            manifest.parent.mkdir(parents=True)
            manifest.write_bytes((ROOT / relative).read_bytes())
            hashes = {}
            MODULE.bind(root, relative, MODULE.ASSET_MANIFEST_SHA256, hashes)
            # An exact inventory proves the reviewed bytes, not that any model,
            # browser, or Android verification completed for this source.
            receipt = root / 'inventory-only.json'
            receipt.write_text(json.dumps({'passed': True, 'analysis_asset_binding': {
                'manifest_sha256': MODULE.ASSET_MANIFEST_SHA256,
                'verified_asset_count': EXPECTED_MANIFEST_ENTRY_COUNT,
            }}))
            with self.assertRaisesRegex(ValueError, 'stale, absent, or belongs to a different evidence session'):
                MODULE.verify_fresh_receipt(root, receipt.name, hashes, 'a' * 64,
                                            'Native comparison', set())


if __name__ == '__main__':
    unittest.main()
