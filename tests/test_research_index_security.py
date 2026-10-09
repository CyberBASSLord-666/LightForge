import importlib.util
import io
from pathlib import Path
import pickle
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / 'research/upstream/vocal-candidates/EfficientAT'
spec = importlib.util.spec_from_file_location('safe_index', RESEARCH / 'helpers/safe_index.py')
safe_index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(safe_index)
EXECUTION_MARKERS = []


def harmless_execution_marker():
    EXECUTION_MARKERS.append('executed')
    return {'sample.wav': 0}


class ExecutablePayload:
    def __reduce__(self):
        return harmless_execution_marker, ()


class ResearchIndexSecurityTest(unittest.TestCase):
    def test_legacy_primitive_dictionary_protocols(self):
        expected = {'song.wav': 0, 'unicode-音.wav': 1024, 'large.wav': 2**40}
        for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.subTest(protocol=protocol):
                self.assertEqual(safe_index.load_filename_index(io.BytesIO(pickle.dumps(expected, protocol))), expected)

    def test_executable_reduce_is_rejected_without_execution(self):
        EXECUTION_MARKERS.clear()
        data = pickle.dumps(ExecutablePayload())
        with self.assertRaisesRegex(ValueError, 'Forbidden'):
            safe_index.load_filename_index(io.BytesIO(data))
        self.assertEqual(EXECUTION_MARKERS, [])

    def test_extension_and_persistent_opcodes_are_rejected(self):
        for data in (b'\x80\x02\x82\x01.', b'Pexternal\n.'):
            with self.assertRaisesRegex(ValueError, 'Forbidden'):
                safe_index.load_filename_index(io.BytesIO(data))

    def test_invalid_shapes_values_and_trailing_content(self):
        cyclic = {}; cyclic['cycle'] = cyclic
        for value in ([], {'x': -1}, {'x': True}, {1: 0}, {'x': '0'}, cyclic):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(ValueError):
                    safe_index.load_filename_index(io.BytesIO(pickle.dumps(value)))
        with self.assertRaisesRegex(ValueError, 'trailing'):
            safe_index.load_filename_index(io.BytesIO(pickle.dumps({'x': 0}) + b'extra'))
        with self.assertRaises(ValueError):
            safe_index.load_filename_index(io.BytesIO(b''))

    def test_sparse_memo_and_oversized_frame_rejected_before_unpickling(self):
        # Tiny payloads must not provoke giant memo allocations or frame reads.
        for data in (b'\x80\x02}r\xff\xff\xff\xff.',
                     b'\x80\x02}j\xff\xff\xff\xff.',
                     b'\x80\x04\x95' + (2**63).to_bytes(8, 'little') + b'}.'):
            with patch.object(safe_index, '_IndexUnpickler') as unpickler:
                with self.assertRaises(ValueError):
                    safe_index.load_filename_index(io.BytesIO(data))
                unpickler.assert_not_called()

    def test_implicit_memo_table_is_bounded(self):
        with patch.object(safe_index, 'MAX_MEMO_INDEX', 2), patch.object(safe_index, '_IndexUnpickler') as unpickler:
            with self.assertRaisesRegex(ValueError, 'memo table'):
                safe_index.load_filename_index(io.BytesIO(b'\x80\x04}\x94\x94\x94.'))
            unpickler.assert_not_called()

    def test_input_size_is_bounded(self):
        with patch.object(safe_index, 'MAX_INDEX_BYTES', 8):
            with self.assertRaisesRegex(ValueError, 'maximum size'):
                safe_index.load_filename_index(io.BytesIO(b'x' * 9))

    def test_training_entry_points_use_restricted_reader(self):
        for name in ('ex_audioset.py', 'ex_pl_audioset.py'):
            source = (RESEARCH / name).read_text()
            self.assertIn('load_filename_index(f)', source)
            self.assertNotIn('pickle.load(', source)

    def test_other_research_manifests_exclude_known_vulnerable_minima(self):
        source = (ROOT / 'research/upstream/pretrained-sed/requirements.txt').read_text()
        for requirement in ('datasets>=5.0.1', 'pytorch-lightning>=2.6.6', 'torch>=2.13.0',
                            'torchaudio>=2.11.0', 'torchvision>=0.28.0'):
            self.assertIn(requirement, source.splitlines())
        script = (ROOT / 'research/upstream/beat_this/ckpt2onnx.py').read_text()
        self.assertIn('"torch>=2.13.0"', script)
        self.assertIn('"onnx>=1.22.0"', script)


if __name__ == '__main__':
    unittest.main()
