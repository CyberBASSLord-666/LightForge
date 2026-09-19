import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('game_native_process', Path(__file__).resolve().parents[1] / 'benchmark_native_process.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class InputContractTest(unittest.TestCase):
    def check_bytes(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.f32'
            path.write_bytes(data)
            return module.validate_input(path)

    def test_finite_little_endian_source(self):
        self.assertEqual(self.check_bytes(struct.pack('<3f', -0.5, 0, 1)), 3)

    def test_empty_and_incomplete_samples_rejected(self):
        for data in (b'', b'123'):
            with self.assertRaises(ValueError):
                self.check_bytes(data)

    def test_nonfinite_source_rejected(self):
        for value in (float('nan'), float('inf'), -float('inf')):
            with self.assertRaises(ValueError):
                self.check_bytes(struct.pack('<f', value))


if __name__ == '__main__':
    unittest.main()
