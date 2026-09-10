"""Parity checks must distinguish unnormalized spectrum and decoded audio units."""
from pathlib import Path
import importlib.util,unittest
import numpy as np
P=Path(__file__).resolve().parents[1]/'qa/release-2.2.4/mdx_numeric.py'
spec=importlib.util.spec_from_file_location('mdx_numeric_2_2_4',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class MdxNumericTest(unittest.TestCase):
    def test_nonfinite_values_rejected(self):
        for value in [np.nan,np.inf,-np.inf]:
            with self.assertRaisesRegex(ValueError,'Nonfinite'):m.compare([value],[1],'waveform')
    def test_absolute_plus_relative_coefficient_limit_checked_individually(self):
        ref=np.full(100000,100.0);native=ref.copy();native[0]+=0.0002
        result=m.compare(native,ref,'positive')
        self.assertTrue(result['within_thresholds']);self.assertGreater(result['max_absolute_error'],1e-4)
        native[0]=100.002
        result=m.compare(native,ref,'positive')
        self.assertFalse(result['within_thresholds']);self.assertEqual(result['coefficient_violations'],1)
    def test_normalized_waveform_is_strict_even_with_low_average_error(self):
        ref=np.full(1000,0.2);native=ref.copy();native[0]+=2e-6
        self.assertFalse(m.compare(native,ref,'waveform')['within_thresholds'])
    def test_rmse_and_relative_error_are_independent_gates(self):
        ref=np.full(1000,100.0);self.assertFalse(m.compare(ref+2e-5,ref,'positive')['within_thresholds'])
        ref=np.full(1000,1e-9);self.assertFalse(m.compare(ref+1e-9,ref,'positive')['within_thresholds'])
    def test_changed_shape_rejected(self):
        with self.assertRaisesRegex(ValueError,'Incomplete'):m.compare([1],[1,2],'waveform')
if __name__=='__main__':unittest.main()
