"""Accelerator experiments must reject substitutions and unsupported claims."""
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('benchmark_deux_accelerator', ROOT / 'tools/benchmark_deux_accelerator.py')
experiment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(experiment)


class AcceleratorTest(unittest.TestCase):
    def test_production_baseline_is_unchanged_and_controls_are_separate(self):
        source = (experiment.SOURCE / 'NativeDeux.java').read_text()
        self.assertEqual(experiment.variant_source(source, 'cpu_all'), source)
        basic = source.replace(experiment.OPT_ANCHOR, experiment.OPT_ANCHOR.replace('ALL_OPT', 'BASIC_OPT'))
        for variant in ('cpu_basic', 'gpu_package_cpu_basic'):
            self.assertEqual(experiment.variant_source(source, variant), basic)
        cuda = experiment.variant_source(source, 'cuda_basic')
        self.assertIn('cuda.add("use_tf32","0")', cuda)
        self.assertIn('OptLevel.BASIC_OPT', cuda)
        self.assertNotIn('OptLevel.ALL_OPT', cuda)
        self.assertIn('OrtProvider.CUDA', cuda)
        self.assertIn('options.addCUDA(cuda)', cuda)
        self.assertEqual(cuda.count(experiment.CREATE_ANCHOR), 1)

    def test_changed_source_anchors_reject_instrumentation(self):
        source = (experiment.SOURCE / 'NativeDeux.java').read_text()
        for bad in ('', source + experiment.OPT_ANCHOR, source + '\naddCUDA('):
            with self.assertRaises(ValueError):
                experiment.variant_source(bad, 'cuda_basic')

    def compare(self, values, other):
        with tempfile.TemporaryDirectory() as directory, patch.object(experiment.benchmark, 'SAMPLES', 4):
            a, b = Path(directory) / 'a', Path(directory) / 'b'
            a.write_bytes(struct.pack('<4f', *values))
            b.write_bytes(struct.pack('<4f', *other))
            return experiment.compare_outputs(a, b)

    def test_complete_raw_output_difference_has_no_implicit_tolerance(self):
        result = self.compare([0, 1, 2, 3], [0, 1, 2.5, 3])
        self.assertFalse(result['byteIdentical'])
        self.assertEqual(result['numericallyUnequalSamples'], 1)
        self.assertEqual(result['maximumAbsoluteError'], .5)
        self.assertEqual(result['rootMeanSquaredError'], .25)
        self.assertFalse(result['qualityApproved'])
        self.assertIsNone(result['tolerance'])
        with self.assertRaisesRegex(ValueError, 'prohibited'):
            experiment.require_output_qualification([result])

    def test_signed_zero_remains_byte_difference_despite_zero_numeric_error(self):
        result = self.compare([0, 1, 2, 3], [-0.0, 1, 2, 3])
        self.assertFalse(result['byteIdentical'])
        self.assertEqual(result['maximumAbsoluteError'], 0)
        with self.assertRaises(ValueError):
            experiment.require_output_qualification([result])

    def test_nonfinite_and_incomplete_outputs_reject(self):
        for value in (float('nan'), float('inf'), -float('inf')):
            with self.assertRaisesRegex(ValueError, 'nonfinite'):
                self.compare([0, 1, 2, 3], [0, 1, value, 3])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'short.f32'
            path.write_bytes(b'\x00' * 4)
            with self.assertRaisesRegex(ValueError, 'complete'):
                experiment.compare_outputs(path, path)

    def test_only_exact_comparison_allows_timing_and_never_quality_approval(self):
        result = self.compare([0, 1, 2, 3], [0, 1, 2, 3])
        experiment.require_output_qualification([result])
        self.assertFalse(result['qualityApproved'])
        for values in ([], [dict(byteIdentical=1)], [dict(byteIdentical='true')]):
            with self.assertRaises(ValueError):
                experiment.require_output_qualification(values)

    def test_observer_mismatch_is_invalid_not_a_cross_provider_quality_decision(self):
        with self.assertRaises(experiment.InvalidObserver):
            experiment.require_output_qualification([dict(candidate='cpu_all_profiled', byteIdentical=False)])
        with self.assertRaises(experiment.NumericalEquivalenceUnproven):
            experiment.require_output_qualification([dict(candidate='cuda_basic', byteIdentical=False)])

    def summary(self, provider='CUDAExecutionProvider', operator='MatMul'):
        row = dict(provider=provider, operator=operator, calls=3, durationUs=20)
        return dict(graphCount=27, modelRuns=335, providers=[dict(provider=provider, calls=81, durationUs=540)],
                    graphs=[dict(graph=name, operators=[dict(row)]) for name in experiment.profiler.GRAPH_NAMES],
                    durationMeaning='host event time, not device time')

    def test_cuda_fallback_or_trivial_gpu_ops_cannot_claim_acceleration(self):
        for summary in (self.summary(provider='CPUExecutionProvider'), self.summary(operator='MemcpyFromHost')):
            with self.assertRaisesRegex(ValueError, 'CPU fallback|substantive CUDA'):
                experiment.validate_placement(summary, 'cuda_basic')
        summary = self.summary()
        summary['graphs'][0]['operators'] = []
        with self.assertRaisesRegex(ValueError, 'substantive CUDA'):
            experiment.validate_placement(summary, 'cuda_basic')
        summary = self.summary(); summary['modelRuns'] = 334
        with self.assertRaisesRegex(ValueError, '335'):
            experiment.validate_placement(summary, 'cuda_basic')

    def test_provider_placement_records_cpu_fallback(self):
        summary = self.summary()
        summary['providers'].append(dict(provider='CPUExecutionProvider', calls=42, durationUs=10))
        result = experiment.validate_placement(summary, 'cuda_basic')
        self.assertEqual(result['cpuFallbackKernelEvents'], 42)
        with self.assertRaisesRegex(ValueError, 'Unexpected'):
            experiment.validate_placement(summary, 'cpu_basic')

    def test_wrong_runtime_digest_rejects_even_when_size_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / 'runtime.jar'; runtime.write_bytes(b'abcd')
            pin = dict(name='runtime.jar', bytes=4, sha256='0' * 64)
            with self.assertRaisesRegex(ValueError, 'incorrect pinned'):
                experiment.verify_runtime(runtime, pin)

    def test_missing_gpu_fails_without_substituting_cpu(self):
        with patch.object(experiment.subprocess, 'run', side_effect=FileNotFoundError):
            with self.assertRaisesRegex(ValueError, 'no accelerator timing'):
                experiment.gpu_inventory()

    def test_library_map_requires_actual_cuda_runtime_cudnn_and_cublas_files(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); maps = folder / 'maps'
            entries = []
            for name in ('libcudart.so.12.8', 'libcudnn.so.9.12', 'libcublas.so.12.8'):
                path = folder / name; path.write_bytes(b'fixture')
                entries.append('7a-7b r-xp 00000 00:00 0 ' + str(path))
            maps.write_text('\n'.join(entries))
            self.assertEqual(len(experiment.native_library_paths(maps)), 3)
            maps.write_text('\n'.join(entries[:2]))
            with self.assertRaisesRegex(ValueError, 'libcublas'):
                experiment.native_library_paths(maps)

    def test_versions_come_from_mapped_files_and_reject_wrong_runtime_family(self):
        paths = [Path('/tmp/libcudart.so.12'), Path('/tmp/libcudnn.so.9'), Path('/tmp/libcublas.so.12')]
        result = dict(cudaRuntimeVersion=12080, cudnnVersion=91200, cublasVersion=[12, 8, 4])
        with patch.object(experiment.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(result), '')) as run:
            self.assertEqual(experiment.native_library_versions(paths), result)
            self.assertEqual(run.call_args.args[0][-3:], list(map(str, paths)))
        for field, value in [('cudaRuntimeVersion', 13000), ('cudnnVersion', 8900)]:
            bad = dict(result); bad[field] = value
            with patch.object(experiment.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(bad), '')):
                with self.assertRaises(ValueError):
                    experiment.native_library_versions(paths)

    def test_library_capture_is_only_a_separate_diagnostic_snapshot(self):
        source = (experiment.SOURCE / 'NativeDeux.java').read_text()
        cuda = experiment.variant_source(source, 'cuda_basic')
        captured = experiment.capture_library_maps(cuda, Path('/tmp/qualification/maps'))
        self.assertEqual(captured.count('/proc/self/maps'), 1)
        self.assertNotIn('/proc/self/maps', cuda)
        self.assertEqual(captured.count(experiment.CREATE_ANCHOR), 1)
        self.assertGreater(captured.index('/proc/self/maps'), captured.index('result=session.run('))
        self.assertIn('StandardOpenOption.APPEND', captured)

    def test_profiled_runs_are_excluded_from_performance_results(self):
        rows = []
        for name in ('cpu_all', 'cuda_basic'):
            for phase in ('measurement', 'diagnostic'):
                for _ in range(3):
                    value = 100 if phase == 'measurement' else 999999
                    rows.append(dict(variant=name, phase=phase, wallNanos=value, inferenceMillis=value,
                                     modelInitMillis=value, processWallIncludingStartupAndInspectionNanos=value))
        result = experiment.performance_summary(rows, ('cpu_all', 'cuda_basic'))
        self.assertEqual(result['medians']['cuda_basic']['wallNanos'], 100)
        self.assertFalse(result['target75Proven'])
        self.assertFalse(result['wholeSongSpeedupProven'])
        self.assertFalse(result['androidSpeedupProven'])


if __name__ == '__main__':
    unittest.main()
