"""Fail early when the reviewed analysis inventory pin has not been refreshed."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / 'qa/release-2.2.4/verify-analysis.py'
EXPECTED_MANIFEST_SHA256 = '390b2d28d89e1d0dddfe4b7246b295d327e87d8dccf87aa695d1e27bb64a8d61'
EXPECTED_MANIFEST_ENTRY_COUNT = 84
SPEC = spec_from_file_location('lightforge_verify_analysis_2_2_4', VERIFY)
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
