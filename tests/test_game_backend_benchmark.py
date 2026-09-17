"""Regression checks for the benchmark's fail-closed evidence comparator."""
import hashlib
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    'game_backend_compare', Path(__file__).resolve().parents[1] / 'tools/game_benchmark/compare.py')
compare = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare)


class ComparisonEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.left, self.right = self.root / 'left', self.root / 'right'
        for directory in (self.left, self.right):
            directory.mkdir()
            receipt = {'schema': 'lightforge-game-benchmark-1', 'runtime': 'fixture', 'capture': True,
                       'sampleRate': 44100, 'samples': 44100, 'pcmSHA256': '0' * 64, 'modelFiles': {},
                       'seed': 2025, 'language': 0, 'steps': 8,
                       'notes': [{'start': 0, 'end': .5, 'midi': 60}], 'stages': []}
            for label in compare.LABELS:
                graph = label.split('-')[0]
                stage = {'graph': graph, 'label': label, 'outputs': []}
                for name in sorted(compare.OUTPUTS[graph]):
                    data = struct.pack('<f', 1)
                    filename = label + '-' + name + '.bin'
                    (directory / filename).write_bytes(data)
                    stage['outputs'].append({'name': name, 'file': filename, 'type': 'float32',
                                             'dims': [1], 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
                receipt['stages'].append(stage)
            self.write(directory, receipt)

    def tearDown(self):
        self.temporary.cleanup()

    def read(self, directory):
        return json.loads((directory / 'receipt.json').read_text())

    def write(self, directory, receipt):
        (directory / 'receipt.json').write_text(json.dumps(receipt))

    def test_complete_equal_evidence_passes(self):
        self.assertTrue(compare.compare(self.left, self.right)['exactParity'])

    def test_matching_notes_cannot_hide_an_intermediate_float_difference(self):
        receipt = self.read(self.right)
        tensor = receipt['stages'][0]['outputs'][0]
        data = struct.pack('<f', 1.0000001192092896)
        (self.right / tensor['file']).write_bytes(data)
        tensor['sha256'] = hashlib.sha256(data).hexdigest()
        self.write(self.right, receipt)
        result = compare.compare(self.left, self.right)
        self.assertFalse(result['exactParity'])
        self.assertTrue(result['unroundedNotesIdentical'])
        self.assertGreater(result['tensors'][0]['maxAbsoluteDifference'], 0)

    def test_missing_diffusion_step_is_rejected_even_when_both_sides_match(self):
        for directory in (self.left, self.right):
            receipt = self.read(directory)
            receipt['stages'].pop(4)
            self.write(directory, receipt)
        with self.assertRaisesRegex(ValueError, 'stages'):
            compare.compare(self.left, self.right)

    def test_changed_seed_does_not_become_a_backend_difference(self):
        receipt = self.read(self.right)
        receipt['seed'] += 1
        self.write(self.right, receipt)
        with self.assertRaisesRegex(ValueError, 'binding: seed'):
            compare.compare(self.left, self.right)

    def test_wrong_model_inventory_is_rejected(self):
        receipt = self.read(self.right)
        receipt['modelFiles'] = {'encoder.onnx': {'sha256': '1' * 64}}
        self.write(self.right, receipt)
        with self.assertRaisesRegex(ValueError, 'binding: modelFiles'):
            compare.compare(self.left, self.right)

    def test_nonfinite_raw_value_is_rejected_even_with_valid_hash(self):
        receipt = self.read(self.right)
        tensor = receipt['stages'][0]['outputs'][0]
        data = struct.pack('<f', float('nan'))
        (self.right / tensor['file']).write_bytes(data)
        tensor['sha256'] = hashlib.sha256(data).hexdigest()
        self.write(self.right, receipt)
        with self.assertRaisesRegex(ValueError, 'Nonfinite'):
            compare.compare(self.left, self.right)

    def test_matching_rounded_notes_do_not_hide_unrounded_pitch_difference(self):
        receipt = self.read(self.right)
        receipt['notes'][0]['midi'] += .000001
        self.write(self.right, receipt)
        self.assertEqual(round(receipt['notes'][0]['midi'], 2), 60)
        result = compare.compare(self.left, self.right)
        self.assertFalse(result['exactParity'])
        self.assertFalse(result['unroundedNotesIdentical'])

    def test_untrusted_capture_digest_is_rejected(self):
        tensor = self.read(self.right)['stages'][0]['outputs'][0]
        (self.right / tensor['file']).write_bytes(struct.pack('<f', 2))
        with self.assertRaisesRegex(ValueError, 'integrity'):
            compare.compare(self.left, self.right)

    def test_missing_output_is_rejected_on_both_sides(self):
        for directory in (self.left, self.right):
            receipt = self.read(directory)
            receipt['stages'][0]['outputs'].pop()
            self.write(directory, receipt)
        with self.assertRaisesRegex(ValueError, 'outputs'):
            compare.compare(self.left, self.right)


if __name__ == '__main__':
    unittest.main()
