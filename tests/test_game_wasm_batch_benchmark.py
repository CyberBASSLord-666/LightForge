"""Fail-closed checks for a fixed-batch GAME timing experiment."""
import copy
import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    'game_wasm_batch', Path(__file__).resolve().parents[1] / 'tools/game_benchmark/benchmark_wasm_batch.py')
benchmark = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(benchmark)


def receipt():
    result = {'schema': 'lightforge-game-benchmark-1', 'sampleRate': 44100, 'samples': 705600,
              'pcmSHA256': '0' * 64, 'modelFiles': {}, 'seed': 2025, 'language': 0, 'steps': 8,
              'runtime': 'same-bundled-runtime', 'requestedThreads': 4, 'runtimeReportedWasmThreads': 4,
              'shapeContractSHA256': '1' * 64, 'inferenceSeconds': 12,
              'notes': [{'start': 0, 'end': .2, 'midi': 61.123456789}], 'stages': []}
    for label in benchmark.LABELS:
        graph = label.split('-')[0]
        result['stages'].append({'label': label, 'graph': graph, 'seconds': 1,
                                 'outputs': [{'name': name, 'type': 'float32', 'dims': [1],
                                              'bytes': 4, 'sha256': '2' * 64, 'finite': True}
                                             for name in sorted(benchmark.OUTPUTS[graph])]})
    return result


class WasmBatchEvidenceTests(unittest.TestCase):
    def test_complete_identical_outputs_are_accepted_without_raw_file_paths(self):
        reference = receipt()
        benchmark.require_exact(reference, copy.deepcopy(reference))

    def test_one_intermediate_digest_difference_rejects_matching_notes(self):
        reference, candidate = receipt(), receipt()
        candidate['stages'][4]['outputs'][0]['sha256'] = '3' * 64
        with self.assertRaisesRegex(ValueError, 'stage output'):
            benchmark.require_exact(reference, candidate)

    def test_identical_missing_diffusion_step_is_not_accepted(self):
        reference = receipt()
        reference['stages'].pop(4)
        reference['inferenceSeconds'] -= 1
        with self.assertRaisesRegex(ValueError, 'inference stages'):
            benchmark.require_exact(reference, copy.deepcopy(reference))

    def test_identical_missing_graph_output_is_not_accepted(self):
        reference = receipt()
        reference['stages'][0]['outputs'].pop()
        with self.assertRaisesRegex(ValueError, 'outputs'):
            benchmark.require_exact(reference, copy.deepcopy(reference))

    def test_same_notes_with_different_unrounded_pitch_are_not_equal(self):
        reference, candidate = receipt(), receipt()
        candidate['notes'][0]['midi'] += 1e-9
        with self.assertRaisesRegex(ValueError, 'Unrounded'):
            benchmark.require_exact(reference, candidate)

    def test_different_thread_runtime_or_contract_cannot_be_reported_as_shape_speedup(self):
        for field in ('runtime', 'requestedThreads', 'runtimeReportedWasmThreads', 'shapeContractSHA256'):
            with self.subTest(field=field):
                reference, candidate = receipt(), receipt()
                candidate[field] = 'different'
                with self.assertRaisesRegex(ValueError, 'binding differs: ' + field):
                    benchmark.require_exact(reference, candidate)

    def test_missing_finite_check_or_byte_count_is_rejected(self):
        for key, value in (('finite', False), ('bytes', 8)):
            with self.subTest(field=key):
                reference = receipt()
                reference['stages'][0]['outputs'][0][key] = value
                with self.assertRaisesRegex(ValueError, 'finite output'):
                    benchmark.require_exact(reference, copy.deepcopy(reference))

    def test_partial_inference_timing_is_rejected(self):
        reference = receipt()
        reference['inferenceSeconds'] = 1
        with self.assertRaisesRegex(ValueError, 'complete graph-call sum'):
            benchmark.require_exact(reference, copy.deepcopy(reference))

    def test_nonfinite_notes_are_rejected_even_on_both_sides(self):
        reference = receipt()
        reference['notes'][0]['midi'] = float('inf')
        with self.assertRaisesRegex(ValueError, 'notes'):
            benchmark.require_exact(reference, copy.deepcopy(reference))

    def test_pair_order_alternates_and_warmup_is_separate(self):
        self.assertEqual(benchmark.run_order(1, 3), [
            ('warmup', 1, ('baseline', 'batch-one')),
            ('measured', 1, ('batch-one', 'baseline')),
            ('measured', 2, ('baseline', 'batch-one')),
            ('measured', 3, ('batch-one', 'baseline'))])

    def test_summarize_excludes_warmup_and_reports_actual_inference(self):
        runs = []
        for phase, pair, modes in benchmark.run_order(1, 3):
            for mode in modes:
                seconds = 1000 if phase == 'warmup' else 10 if mode == 'baseline' else 8
                runs.append({'phase': phase, 'pair': pair, 'mode': mode, 'inferenceSeconds': seconds,
                             'initializationSeconds': 999, 'inferenceProcessCpuSeconds': seconds * 2,
                             'processPeakRssKiB': 123, 'wallSeconds': seconds + 999})
        summary = benchmark.summarize(runs)
        self.assertAlmostEqual(summary['medianPairedInferenceReductionPercent'], 20)
        self.assertEqual(summary['medians']['baseline']['inferenceSecondsMedian'], 10)
        self.assertTrue(summary['everyMeasuredPairFaster'])


if __name__ == '__main__':
    unittest.main()
