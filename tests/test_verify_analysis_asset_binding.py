"""Fail early when the reviewed analysis inventory pin has not been refreshed."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]
RELEASE = json.loads((ROOT / 'version.json').read_text())['name']
VERIFY = ROOT / f'qa/release-{RELEASE}/verify-analysis.py'
EXPECTED_MANIFEST_SHA256 = 'c0dc1d56b53cf7f316697d45f0a2cb5a63c4bf7068ba89829619cadfe46ff790'
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


if __name__ == '__main__':
    unittest.main()
