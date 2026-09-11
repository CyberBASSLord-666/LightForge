"""Regression guard for production-verifier runtime report filtering."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import verify_v2


class VerifyV2SourceGuardTest(unittest.TestCase):
    def test_only_declared_current_release_receipts_are_excluded(self):
        generated=verify_v2.OUT/'movement-verification.json'
        self.assertTrue(verify_v2.is_generated_runtime_report(generated))
        self.assertTrue(verify_v2.is_generated_runtime_report(verify_v2.OUT/'native-mdx-downstream-wasm.json'))
        self.assertFalse(verify_v2.is_generated_runtime_report(verify_v2.OUT/'reference-golden-small.json'))
        self.assertFalse(verify_v2.is_generated_runtime_report(ROOT/'qa/release-1.6.0/movement-verification.json'))
        self.assertFalse(verify_v2.is_generated_runtime_report(verify_v2.OUT/'unlisted-verification.json'))

    def test_only_explicit_historical_evidence_contracts_are_excluded(self):
        historical=frozenset({
            'test_analysis_evidence_2_2_2',
            'test_analysis_evidence_2_2_3',
        })
        self.assertEqual(verify_v2.HISTORICAL_PYTHON_TESTS, historical)
        discovered={path.stem for path in (ROOT/'tests').glob('test_*.py')}
        self.assertTrue(historical <= discovered)
        self.assertEqual(set(verify_v2.PYTHON_TESTS), discovered-historical)
        self.assertIn('test_verify_analysis_asset_binding', verify_v2.PYTHON_TESTS)
        self.assertIn('test_verify_analysis_session_evidence', verify_v2.PYTHON_TESTS)


if __name__=='__main__':
    unittest.main()
