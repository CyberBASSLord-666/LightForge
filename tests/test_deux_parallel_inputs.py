"""Independent-output reproduction fails closed before model work on stale inputs."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('parallel_inputs', ROOT / 'tools/verify_deux_parallel_inputs.py')
HELPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPER)
RESEARCH = ROOT / 'research/inference-2.4.1'


class ParallelInputReproductionTest(unittest.TestCase):
    def setUp(self):
        self.performance = json.loads((RESEARCH / 'production-parallel-qualification.json').read_text())
        self.canonical = json.loads((RESEARCH / 'separator-divergent-inputs.json').read_text())

    def test_committed_reference_needs_no_build_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_references(root)
            references = HELPER.load_canonical(root, self.performance)
            self.assertEqual({case['id'] for case in references[0]['cases']}, {'falcon', 'stella'})
            self.assertFalse((root / 'build').exists())

    def copy_references(self, root):
        for relative in ['research/inference-2.4.1/separator-divergent-inputs.json',
                         'research/inference-2.4.1/separator-scheduler-paired.json',
                         'qa/release-1.6.0/musdb-fixture-provenance.json']:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())

    def test_missing_fixture_explains_restoration_and_creates_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, 'Missing licensed fixture.*restore MUSDB'):
                HELPER.prepare_fixture(self.canonical['cases'][0], root, root / 'output.wav')
            self.assertFalse((root / 'output.wav').exists())

    def test_wrong_fixture_hash_rejected_before_decoder_or_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'falcon-mix.wav').write_bytes(b'incorrect fixture bytes')
            with self.assertRaisesRegex(ValueError, 'Original Float32 fixture hash differs'):
                HELPER.prepare_fixture(self.canonical['cases'][0], root, root / 'output.wav')
            self.assertFalse((root / 'output.wav').exists())

    def test_original_source_or_graph_hash_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_references(root)
            path = root / 'research/inference-2.4.1/separator-scheduler-paired.json'
            frozen = json.loads(path.read_text())
            frozen['frozenSourceSnapshots']['baseline/NativeDeux.java'] += '\nchanged'
            path.write_text(json.dumps(frozen))
            with self.assertRaisesRegex(ValueError, 'original implementation provenance differs'):
                HELPER.load_canonical(root, self.performance)
        performance = copy.deepcopy(self.performance)
        performance['models']['graphHashes']['front.onnx'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'original graph provenance differs'):
            HELPER.load_canonical(ROOT, performance)

    def test_incomplete_reference_output_or_changed_fixture_provenance_rejected(self):
        for mutation, message in [
            (lambda case: case['runs'][0].update(outputBytes=4), 'complete output hash or size'),
            (lambda case: case['runs'][0].update(outputSha256='invalid'), 'complete output hash or size'),
            (lambda case: case['fixtureProvenance'].update(sampleRate=48000), 'fixture provenance differs'),
        ]:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.copy_references(root)
                canonical = copy.deepcopy(self.canonical)
                mutation(canonical['cases'][0])
                (root / 'research/inference-2.4.1/separator-divergent-inputs.json').write_text(json.dumps(canonical))
                with self.assertRaisesRegex(ValueError, message):
                    HELPER.load_canonical(root, self.performance)


if __name__ == '__main__':
    unittest.main()
