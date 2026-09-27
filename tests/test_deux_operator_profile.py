"""Reject incomplete, misbound and misleading ORT operator diagnostics."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('profile_deux_operators', ROOT / 'tools/profile_deux_operators.py')
profiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profiler)


def event(name, category='Node', elapsed=7, provider='CPUExecutionProvider', operator='MatMul'):
    return dict(name=name, cat=category, ph='X', ts=0, dur=elapsed,
                args=dict(provider=provider, op_name=operator))


class OperatorProfileTest(unittest.TestCase):
    def trace(self, directory, graph='front'):
        path = Path(directory) / (graph + '_2026-09-20_00-00-00.json')
        data = [event('model_run', 'Session', 20) for _ in range(profiler.graph_calls(graph))]
        data += [event('matmul_kernel_time'), event('matmul_kernel_time', elapsed=3),
                 event('matmul_fence_before', elapsed=99), event('reshape_kernel_time', operator='Reshape', elapsed=2)]
        path.write_text(json.dumps(data))
        return path, data

    def test_operator_aggregation_excludes_fences_and_session_spans(self):
        with tempfile.TemporaryDirectory() as directory:
            path, _ = self.trace(directory)
            result = profiler.summarize_trace(path, 'front')
            self.assertEqual(result['modelRuns'], 1)
            self.assertEqual(result['kernelEvents'], 3)
            self.assertEqual(result['operators'][0], dict(provider='CPUExecutionProvider', operator='MatMul', calls=2, durationUs=10))
            self.assertEqual(result['modelRunDurationUs'], 20)

    def test_provider_is_observed_not_assumed(self):
        with tempfile.TemporaryDirectory() as directory:
            path, data = self.trace(directory)
            data.append(event('cuda_kernel_time', provider='CUDAExecutionProvider'))
            path.write_text(json.dumps(data))
            result = profiler.summarize_trace(path, 'front')
            self.assertEqual({row['provider'] for row in result['operators']}, {'CPUExecutionProvider', 'CUDAExecutionProvider'})

    def test_rejects_missing_provider_operator_or_empty_kernel_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            path, data = self.trace(directory)
            for bad in [None, {}, dict(op_name='MatMul'), dict(provider='CPUExecutionProvider')]:
                altered = json.loads(json.dumps(data))
                altered[1]['args'] = bad
                path.write_text(json.dumps(altered))
                with self.assertRaisesRegex(ValueError, 'metadata|provider|operator'):
                    profiler.summarize_trace(path, 'front')
            path.write_text(json.dumps(data[:1]))
            with self.assertRaisesRegex(ValueError, 'no timed operator'):
                profiler.summarize_trace(path, 'front')

    def test_rejects_duplicate_fields_nonfinite_and_non_list_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path, _ = self.trace(directory)
            for text in ['[{"a":1,"a":2}]', '[NaN]', '[Infinity]', '[1e1000]', '{}', '[]', 'not json']:
                path.write_text(text)
                with self.assertRaises(ValueError):
                    profiler.summarize_trace(path, 'front')

    def test_rejects_invalid_event_times(self):
        with tempfile.TemporaryDirectory() as directory:
            path, data = self.trace(directory)
            for key in ('dur', 'ts'):
                for value in [None, True, '7', -1]:
                    altered = json.loads(json.dumps(data))
                    altered[1][key] = value
                    path.write_text(json.dumps(altered))
                    with self.assertRaisesRegex(ValueError, 'duration or timestamp'):
                        profiler.summarize_trace(path, 'front')

    def test_full_topology_requires_every_graph_and_all_335_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            for graph in profiler.GRAPH_NAMES:
                self.trace(directory, graph)
            result = profiler.summarize_traces(Path(directory))
            self.assertEqual(result['graphCount'], 27)
            self.assertEqual(result['modelRuns'], 335)
            self.assertIn('not GPU device kernel time', result['durationMeaning'])
            path = next(Path(directory).glob('block-00-time_*'))
            data = json.loads(path.read_text())
            path.write_text(json.dumps(data[1:]))
            with self.assertRaisesRegex(ValueError, 'model_run count'):
                profiler.summarize_traces(Path(directory))
            path.unlink()
            with self.assertRaisesRegex(ValueError, '27 regular'):
                profiler.summarize_traces(Path(directory))

    def test_duplicate_or_unknown_trace_cannot_replace_missing_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            for graph in profiler.GRAPH_NAMES:
                self.trace(directory, graph)
            head = next(Path(directory).glob('head-0_*'))
            front = next(Path(directory).glob('front_*'))
            head.rename(Path(directory) / 'front_duplicate.json')
            with self.assertRaisesRegex(ValueError, 'Duplicate graph'):
                profiler.summarize_traces(Path(directory))
            front.rename(Path(directory) / 'unknown.json')
            with self.assertRaisesRegex(ValueError, 'Unknown graph'):
                profiler.summarize_traces(Path(directory))

    def test_instrumentation_changes_only_session_profiling_in_snapshot(self):
        source = (ROOT / 'android/src/com/cyberbasslord/lightforge/NativeDeux.java').read_text()
        modified = profiler.instrument_source(source, Path('/tmp/trace space'))
        inserted = '            options.enableProfiling(new File("/tmp/trace space",name).getAbsolutePath());\n'
        self.assertEqual(modified.count(inserted), 1)
        self.assertEqual(modified.replace(inserted, ''), source)
        with self.assertRaisesRegex(ValueError, 'anchor changed'):
            profiler.instrument_source('unrecognized source', Path('/tmp/test'))
        with self.assertRaisesRegex(ValueError, 'already contains'):
            profiler.instrument_source(modified, Path('/tmp/test'))


if __name__ == '__main__':
    unittest.main()
