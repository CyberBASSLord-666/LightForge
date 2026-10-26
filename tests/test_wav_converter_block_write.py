"""Keep exact host PCM/output checks in ordinary Python test discovery."""
import unittest

from tools import benchmark_wav_converter


class WavConverterBlockWriteTest(unittest.TestCase):
    def test_current_converter_matches_frozen_reference_without_timing(self):
        result = benchmark_wav_converter.run(seconds=None)
        self.assertTrue(result["byte_identical"])
        self.assertEqual(result["differential_cases"], 43)
        self.assertEqual(result["outputs_per_case"], 2)
        self.assertEqual(result["benchmark"], [])
        self.assertEqual(result["baseline_source_sha256"], benchmark_wav_converter.BASELINE_SHA256)
        self.assertIn("PASS:", result["existing_native_audio_test"])
        self.assertIn("throwing compile-only stubs", result["existing_test_scope"])


if __name__ == "__main__":
    unittest.main()
