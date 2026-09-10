"""Fail early when the reviewed analysis inventory pin has not been refreshed."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / 'qa/release-2.2.4/verify-analysis.py'
SPEC = spec_from_file_location('lightforge_verify_analysis_2_2_4', VERIFY)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AssetBindingTest(unittest.TestCase):
    def test_reviewed_asset_inventory_pin_matches_current_bytes(self):
        manifest = MODULE.ROOT / 'web/analysis/ASSET_MANIFEST.json'
        self.assertEqual(MODULE.digest(manifest), MODULE.ASSET_MANIFEST_SHA256)


if __name__ == '__main__':
    unittest.main()
