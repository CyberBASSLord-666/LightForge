"""Negative controls for accepting execution-speed evidence."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('execution_benchmark', ROOT / 'tools/benchmark_deux_execution.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class ExecutionBenchmarkEvidenceTest(unittest.TestCase):
    def test_complete_outputs_must_be_finite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'output.f32'
            path.write_bytes(bytes(benchmark.SAMPLES * 4))
            self.assertEqual(len(benchmark.read_output(path)), 64)
            with path.open('r+b') as stream:
                stream.write(bytes.fromhex('0000c07f'))
            with self.assertRaisesRegex(ValueError, 'nonfinite'):
                benchmark.read_output(path)
            path.write_bytes(bytes(12))
            with self.assertRaisesRegex(ValueError, 'complete'):
                benchmark.read_output(path)

    def profile(self):
        lines = ['schema=native-inference-profile-v2 outcome=completed graphRecords=27 stageRecords=15 '
                 'droppedGraphRecords=0 droppedStageRecords=0 inferenceWallMs=100 modelInitWallMs=10']
        lines += ['schema=native-inference-stage-v1 stage=' + name for name in sorted(benchmark.STAGE_NAMES)]
        lines += ['schema=native-inference-graph-v2 graph=' + name + ' runCount=' +
                  str(1 if name == 'front' else 15 if name.endswith('-time') else 11)
                  for name in sorted(benchmark.GRAPH_NAMES)]
        return '\n'.join(lines) + '\n'

    def test_dropped_graphs_and_reduced_batches_cannot_claim_full_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profile.txt'
            original = self.profile()
            path.write_text(original)
            self.assertEqual(benchmark.profile_fields(path)['inferenceWallMs'], '100')
            for malformed in [original.replace('droppedGraphRecords=0', 'droppedGraphRecords=1'),
                              original.replace('graph=block-00-time runCount=15', 'graph=block-00-time runCount=14'),
                              original.replace('stage=decode', 'stage=unknown'),
                              original.replace('inferenceWallMs=100', 'inferenceWallMs=nan')]:
                path.write_text(malformed)
                with self.assertRaises(ValueError):
                    benchmark.profile_fields(path)

    def runs(self):
        return [dict(variant=name, phase='measurement', round=number, outputSha256='a' * 64,
                     wallNanos=100 if name == 'baseline' else 80, inferenceMillis=90 if name == 'baseline' else 70,
                     modelInitMillis=5, processCpuNanos=None, peakRssBytes=None)
                for number in range(3) for name in ('baseline', 'candidate')]

    def test_warmup_is_excluded_from_speed_but_included_in_quality(self):
        runs = self.runs()
        runs.append(dict(runs[0], phase='warmup', wallNanos=1, outputSha256='b' * 64))
        summary = benchmark.summarize(runs)
        self.assertEqual(summary['medians']['baseline']['wallNanos'], 100)
        self.assertFalse(summary['allOutputsByteIdentical'])
        self.assertFalse(summary['speedupProvenOnAndroid'])
        self.assertFalse(summary['wholeSongSpeedupProven'])

    def test_faster_different_pcm_fails_quality(self):
        runs = self.runs()
        runs[-1]['outputSha256'] = 'c' * 64
        summary = benchmark.summarize(runs)
        self.assertFalse(summary['allOutputsByteIdentical'])
        self.assertFalse(summary['pairs'][-1]['byteIdentical'])
        self.assertIsNone(summary['medians']['baseline']['processCpuNanos'])

    def test_incomplete_repetition_fails(self):
        with self.assertRaisesRegex(ValueError, 'three'):
            benchmark.summarize(self.runs()[:-1])


if __name__ == '__main__':
    unittest.main()
