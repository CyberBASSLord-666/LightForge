"""Complete-source CUDA diagnostics must retain source clock and fail closed."""
import copy
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('game_source_cuda', ROOT / 'tools/benchmark_game_source_cuda.py')
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)


class GameSourceCudaTest(unittest.TestCase):
    def fixture(self, root, samples=64 * 44100):
        pcm = root / 'full.f32'
        pcm.write_bytes(struct.pack('<f', .25) * samples)
        provenance = dict(schema='lightforge.game-source-input.v1', sampleRate=44100, sourceSamples=samples,
            pcmSHA256=source.sha(pcm), sourceSHA256='a' * 64, language=0, sourceKind='synthetic',
            derivation='Complete synthetic mono source; no crop or real-model quality evidence.')
        path = root / 'provenance.json'
        path.write_text(json.dumps(provenance))
        return pcm, path, provenance

    def test_production_plan_preserves_complete_clock_halos_and_seeds(self):
        rows = source.passage_plan(64 * 44100)
        self.assertEqual([(r['first'] // 44100, r['last'] // 44100) for r in rows],
                         [(0, 14), (10, 26), (22, 38), (34, 50), (46, 62), (58, 64)])
        self.assertEqual([r['seed'] for r in rows], [2025 + i * 104729 for i in range(6)])
        self.assertEqual([r['key'] for r in rows], ['game-0-' + str(i) for i in range(6)])
        short = source.passage_plan(12 * 44100 + 1, 4)
        self.assertEqual(short[-1], dict(index=1, key='game-4-1', first=10 * 44100,
                                        last=12 * 44100 + 1, seed=106754))
        for samples in (0, True, 64 * 44100 + 1):
            with self.assertRaises(ValueError):
                source.passage_plan(samples)

    def test_full_source_binding_detects_changes_beyond_first_passage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pcm, path, original = self.fixture(root)
            provenance, plan = source.validate_input(pcm, path)
            self.assertEqual(provenance, original)
            self.assertEqual(len(plan), 6)
            data = bytearray(pcm.read_bytes())
            data[-4:] = struct.pack('<f', .5)
            pcm.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                source.validate_input(pcm, path)
            changed = dict(original, pcmSHA256=source.sha(pcm))
            path.write_text(json.dumps(changed))
            _, next_plan = source.validate_input(pcm, path)
            self.assertEqual(plan[:-1], next_plan[:-1])
            self.assertNotEqual(plan[-1]['pcmSha256'], next_plan[-1]['pcmSha256'])

    def test_provenance_rejects_truncated_clock_private_source_and_silent_windows(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pcm, path, original = self.fixture(root, 44100)
            for key, value in [('sourceSamples', 64 * 44100), ('language', True),
                               ('sourceKind', 'private-audio'), ('derivation', '')]:
                path.write_text(json.dumps(dict(original, **{key: value})))
                with self.assertRaises(ValueError, msg=key):
                    source.validate_input(pcm, path)
            pcm.write_bytes(struct.pack('<f', 0) * 44100)
            path.write_text(json.dumps(dict(original, pcmSHA256=source.sha(pcm))))
            with self.assertRaisesRegex(ValueError, 'Silent passage'):
                source.validate_input(pcm, path)

    def test_qualified_variant_generator_and_capture_guard_are_unchanged(self):
        original = source.game.SOURCE.read_text()
        self.assertEqual(source.source_snapshot(original, 'cpu_all', 'plain'), original)
        for variant in source.VARIANTS:
            qualified = source.game.variant_source(original, variant, True, True)
            self.assertEqual(source.source_snapshot(original, variant, 'plain'), qualified)
            self.assertEqual(source.source_snapshot(original, variant, 'captured'), source.game.observed_source(qualified))
            traces = Path('/tmp/full-source-proof')
            profiled = source.source_snapshot(original, variant, 'profiled', traces)
            self.assertEqual(profiled, source.game.observed_source(qualified, traces))
            self.assertIn('catch(Exception|Error error){retire(result);throw error;}', profiled)
            self.assertEqual(qualified.split('    private JSONArray infer(', 1)[1],
                             original.split('    private JSONArray infer(', 1)[1])
        with self.assertRaises(ValueError):
            source.source_snapshot(original, 'cpu_all', 'profiled')
        with self.assertRaises(ValueError):
            source.source_snapshot(original, 'cpu_all', 'plain', Path('/tmp/trace'))

    def test_observer_failure_is_not_softened_by_full_source_execution(self):
        for broken in [dict(kind='plain-vs-capture', unroundedNotesIdentical=False),
                       dict(kind='capture-vs-profile', unroundedNotesIdentical=True, rawTensorsByteIdentical=False)]:
            with self.assertRaises(source.accel.InvalidObserver):
                source.game.validate_observers([broken])
        source.game.validate_observers([
            dict(kind='plain-vs-capture', unroundedNotesIdentical=True),
            dict(kind='capture-vs-profile', unroundedNotesIdentical=True, rawTensorsByteIdentical=True)])

    def minimal_run(self, root):
        pcm, _, provenance = self.fixture(root, 1)
        plan = source.passage_plan(1)
        plan[0]['pcmSha256'] = source.sha(pcm)
        manifest = dict(files={})
        passage = dict(schema='lightforge-game-benchmark-1', runtime='onnxruntime-java-1.25.1', sampleRate=44100,
            samples=1, pcmSHA256=source.sha(pcm), sourcePcmSHA256=source.sha(pcm), sourceSamples=1, passageIndex=0,
            firstSample=0, lastSample=1, modelFiles={}, seed=2025, language=0, steps=8, capture=False,
            retirementConfirmed=True, wallNanos=1, notes=[], stages=[], inferenceSeconds=None)
        directory = root / 'output'
        (directory / 'passage-000').mkdir(parents=True)
        (directory / 'passage-000/receipt.json').write_text(json.dumps(passage))
        receipt = dict(schema='lightforge-game-source-run-1', runtime='onnxruntime-java-1.25.1', samples=1,
            pcmSHA256=source.sha(pcm), sampleRate=44100, steps=8, language=0, modelFiles={}, engineObjects=1,
            capture=False, profiled=False, retirementConfirmed=True, passageCount=1, wallNanos=1, passages=[passage])
        (directory / 'receipt.json').write_text(json.dumps(receipt))
        return directory, provenance, plan, manifest, receipt

    def test_each_saved_passage_is_bound_to_full_pcm_clock_and_nested_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory, provenance, plan, manifest, receipt = self.minimal_run(Path(temporary))
            source.validate_run(directory, 'plain', provenance, plan, manifest)
            for field, value in [('sourcePcmSHA256', 'b' * 64), ('firstSample', 1), ('seed', 1), ('language', 1)]:
                changed = copy.deepcopy(receipt)
                changed['passages'][0][field] = value
                (directory / 'receipt.json').write_text(json.dumps(changed))
                (directory / 'passage-000/receipt.json').write_text(json.dumps(changed['passages'][0]))
                with self.assertRaisesRegex(ValueError, 'source-bound passage'):
                    source.validate_run(directory, 'plain', provenance, plan, manifest)
            (directory / 'receipt.json').write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, 'Nested passage'):
                source.validate_run(directory, 'plain', provenance, plan, manifest)

    def test_changed_bound_helper_is_rejected_and_cuda_not_mislabeled_as_cpu(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'helper.java'
            path.write_text('original')
            hashes = {path: source.sha(path)}
            source.verify_bound_files(hashes)
            path.write_text('modified')
            with self.assertRaisesRegex(ValueError, 'changed'):
                source.verify_bound_files(hashes)
        self.assertEqual(source.execution_identity('cpu_all')['optimization'], 'ALL_OPT')
        cuda = source.execution_identity('cuda_basic')
        self.assertEqual(cuda['provider'], 'CUDAExecutionProvider')
        self.assertTrue(cuda['cudaHeavyOnly'] and cuda['cudaDeterministicCompute'])

    def test_java_same_engine_lifecycle_and_raw_capture_helper_remain_explicit(self):
        runner = source.RUNNER.read_text()
        self.assertEqual(runner.count('new NativeGame('), 1)
        self.assertIn('finally {engine.close();}', runner)
        self.assertIn('engine.isRetired()', runner)
        self.assertIn('engine.predict(passage,language,seed,null,()->false)', runner)
        self.assertNotIn('Math.round', runner)
        self.assertNotIn('setOptimizationLevel', runner)


if __name__ == '__main__':
    unittest.main()
