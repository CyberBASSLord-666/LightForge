"""GAME GPU diagnostics must preserve full passage geometry and useful evidence."""
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('game_accelerator', ROOT / 'tools/benchmark_game_accelerator.py')
game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(game)


class GameAcceleratorTest(unittest.TestCase):
    def test_original_engine_is_baseline_and_cuda_preserves_eight_steps(self):
        source = game.SOURCE.read_text()
        self.assertEqual(game.variant_source(source, 'cpu_all'), source)
        basic = game.variant_source(source, 'cpu_basic')
        self.assertEqual(game.variant_source(source, 'gpu_package_cpu_basic'), basic)
        cuda = game.variant_source(source, 'cuda_basic')
        self.assertIn('cuda.add("use_tf32","0")', cuda)
        self.assertIn('cuda.add("enable_cuda_graph","0")', cuda)
        self.assertIn('options.addCUDA(cuda)', cuda)
        self.assertIn('OrtProvider.CUDA', cuda)
        for value in ['STEPS=8', 'MAX_SAMPLES=16*SAMPLE_RATE', 'k<STEPS', 'noise(frames,(seed+k*2654435761L)&0xffffffffL)']:
            self.assertIn(value, cuda)
        self.assertIn('BASIC_OPT', cuda)
        self.assertNotIn('ALL_OPT', cuda)

    def test_capture_failure_is_inside_original_result_retirement_guard(self):
        source = game.SOURCE.read_text()
        captured = game.observed_source(source)
        self.assertIn('try{GameAcceleratorCapture.record(', captured)
        self.assertIn('catch(Exception|Error error){retire(result);throw error;}', captured)
        self.assertNotIn('enableProfiling', captured)
        self.assertIn('options.enableProfiling', game.observed_source(source, Path('/tmp/trace')))
        for changed in [source + game.RUN_ANCHOR, source.replace(game.RETURN_ANCHOR, '')]:
            with self.assertRaises(ValueError):
                game.observed_source(changed)
        with self.assertRaises(ValueError):
            game.variant_source(source + game.OPT_ANCHOR, 'cuda_basic')

    def test_heavy_only_preserves_all_cpu_controls_and_original_inference(self):
        source = game.SOURCE.read_text()
        for variant in game.VARIANTS[:3]:
            self.assertEqual(game.variant_source(source, variant, True), game.variant_source(source, variant))
            self.assertEqual(set(game.requested_graph_providers(variant, True).values()), {'CPUExecutionProvider'})
        cuda = game.variant_source(source, 'cuda_basic', True)
        original_cuda = game.variant_source(source, 'cuda_basic')
        self.assertIn('if("encoder".equals(GRAPHS[i])||"segmenter".equals(GRAPHS[i])||"estimator".equals(GRAPHS[i])){', cuda)
        self.assertNotIn('if("encoder".equals(GRAPHS[i])', original_cuda)
        self.assertEqual(cuda.split('    private JSONArray infer(', 1)[1], source.split('    private JSONArray infer(', 1)[1])
        self.assertEqual(game.requested_graph_providers('cuda_basic', True), {
            'encoder':'CUDAExecutionProvider', 'dur2bd':'CPUExecutionProvider',
            'segmenter':'CUDAExecutionProvider', 'bd2dur':'CPUExecutionProvider', 'estimator':'CUDAExecutionProvider'})
        self.assertEqual(set(game.requested_graph_providers('cuda_basic').values()), {'CUDAExecutionProvider'})

    def test_deterministic_false_preserves_every_default_and_heavy_only_snapshot(self):
        source = game.SOURCE.read_text()
        for variant in game.VARIANTS:
            for heavy_only in (False, True):
                baseline = game.variant_source(source, variant, heavy_only)
                explicit = game.variant_source(source, variant, heavy_only, False)
                self.assertEqual(explicit, baseline)
                self.assertNotIn('setDeterministicCompute', baseline)
                for trace_directory in (None, Path('/tmp/game-deterministic-trace')):
                    self.assertEqual(game.observed_source(explicit, trace_directory),
                                     game.observed_source(baseline, trace_directory))

    def test_deterministic_candidate_is_one_cuda_heavy_only_line(self):
        source = game.SOURCE.read_text()
        for variant in game.VARIANTS[:3]:
            baseline = game.variant_source(source, variant)
            candidate = game.variant_source(source, variant, True, True)
            self.assertEqual(candidate, baseline)
            for trace_directory in (None, Path('/tmp/game-deterministic-trace')):
                self.assertEqual(game.observed_source(candidate, trace_directory),
                                 game.observed_source(baseline, trace_directory))
        baseline = game.variant_source(source, 'cuda_basic', True)
        candidate = game.variant_source(source, 'cuda_basic', True, True)
        line = '                            options.setDeterministicCompute(true);\n'
        self.assertEqual(candidate.count(line), 1)
        self.assertIn(line + '                            options.addCUDA(cuda);\n', candidate)
        self.assertEqual(candidate.replace(line, ''), baseline)
        self.assertEqual(candidate.split('    private JSONArray infer(', 1)[1],
                         source.split('    private JSONArray infer(', 1)[1])
        for trace_directory in (None, Path('/tmp/game-deterministic-trace')):
            self.assertEqual(game.observed_source(candidate, trace_directory).replace(line, ''),
                             game.observed_source(baseline, trace_directory))
        with self.assertRaisesRegex(ValueError, 'requires --cuda-heavy-only'):
            game.variant_source(source, 'cuda_basic', False, True)

    def test_invalid_deterministic_flags_are_rejected_before_output_or_execution(self):
        combinations = [('--cuda-deterministic',),
                        ('--cuda-deterministic', '--cpu-control-only'),
                        ('--cuda-deterministic', '--cuda-heavy-only', '--cpu-control-only'),
                        ('--cuda-heavy-only', '--cpu-control-only')]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / 'output'
            required = ['--models', str(root / 'models'), '--input', str(root / 'pcm.f32'),
                        '--input-provenance', str(root / 'provenance.json'), '--output', str(output)]
            for flags in combinations:
                with self.subTest(flags=flags), patch.object(game.sys, 'argv', ['benchmark_game_accelerator.py', *required, *flags]), \
                        patch.object(game.sys, 'stderr', io.StringIO()), patch.object(game, 'execute') as execute:
                    with self.assertRaises(SystemExit) as error:
                        game.main()
                    self.assertEqual(error.exception.code, 2)
                    execute.assert_not_called()
                    self.assertFalse(output.exists())

    def fixture(self, directory, total=20*44100, index=1):
        first, last = max(0,(index*12-2)*44100), min(total,((index+1)*12+2)*44100)
        pcm = directory / 'pcm.f32'
        pcm.write_bytes(struct.pack('<f', .25) * (last-first))
        provenance = dict(schema='lightforge.game-passage-input.v1', pcmSHA256=game.sha(pcm),
            sourceSHA256='a'*64, sourceSamples=total, passageIndex=index, firstSample=first,
            lastSample=last, sampleRate=44100, seed=(2025+index*104729)&0xffffffff,
            language=0, derivation='Public synthetic fixture for input validation, not real-model proof.')
        path = directory / 'provenance.json'
        path.write_text(json.dumps(provenance))
        return pcm, path, provenance

    def test_original_context_and_seed_are_mandatory(self):
        with tempfile.TemporaryDirectory() as temporary:
            pcm, path, provenance = self.fixture(Path(temporary))
            self.assertEqual(game.validate_input(pcm,path), provenance)
            for key, value in [('firstSample', provenance['firstSample']+1), ('seed',2025),
                               ('sampleRate',22050), ('language',5), ('sourceSamples',0),
                               ('pcmSHA256','b'*64), ('derivation',''), ('passageIndex',True)]:
                broken = dict(provenance); broken[key] = value
                path.write_text(json.dumps(broken))
                with self.assertRaises(ValueError, msg=key):
                    game.validate_input(pcm,path)

    def test_nonfinite_pcm_is_rejected_before_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            pcm,path,_ = self.fixture(Path(temporary))
            with pcm.open('r+b') as stream:
                stream.write(struct.pack('<f',float('nan')))
            with self.assertRaisesRegex(ValueError,'Nonfinite'):
                game.validate_input(pcm,path)

    def test_original_config_asset_is_bound_alongside_all_five_graphs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);directory=root/'web/analysis/models/game';directory.mkdir(parents=True)
            inventory={}
            for name in [*(g+'.onnx' for g in game.GRAPHS),'config.json']:
                path=directory/name;path.write_bytes(name.encode())
                inventory[name]=dict(bytes=path.stat().st_size,sha256=game.sha(path))
            manifest=dict(id='game-large-1.0.3-lightforge-1',steps=8,sampleRate=44100,files=inventory)
            (directory/'manifest.json').write_text(json.dumps(manifest))
            with patch.object(game,'ROOT',root):
                self.assertEqual(game.verify_models(directory),manifest)
                (directory/'config.json').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'digest mismatch'):
                    game.verify_models(directory)

    def summary(self):
        graphs = []
        for name in game.GRAPHS:
            gpu = name in game.HEAVY_GRAPHS
            graphs.append(dict(graph=name, operators=[dict(provider='CUDAExecutionProvider' if gpu else 'CPUExecutionProvider',
                operator='MatMul' if gpu else 'Where', calls=game.CALLS[name],durationUs=10)]))
        return dict(graphs=graphs, graphCount=5, modelRuns=12, durationMeaning='host event durations')

    def test_tiny_conversion_graphs_can_use_cpu_but_all_heavy_graphs_need_cuda(self):
        summary = self.summary()
        placement = game.validate_placement(summary,'cuda_basic')
        self.assertTrue(placement['heavyGraphsExecuteCudaArithmetic'])
        self.assertEqual(placement['cpuFallbackKernelEvents'],2)
        for name in game.HEAVY_GRAPHS:
            changed = self.summary()
            row = next(g for g in changed['graphs'] if g['graph']==name)['operators'][0]
            row['operator']='MemcpyFromHost'
            with self.assertRaisesRegex(ValueError,'substantive CUDA'):
                game.validate_placement(changed,'cuda_basic')
        with self.assertRaisesRegex(ValueError,'Unexpected'):
            game.validate_placement(summary,'cpu_basic')

    def test_trace_counts_require_all_eight_diffusion_steps(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            for name in game.GRAPHS:
                events=[dict(ph='X',cat='Session',name='model_run',ts=i,dur=2) for i in range(game.CALLS[name])]
                events.append(dict(ph='X',cat='Node',name='op_kernel_time',ts=0,dur=1,
                    args=dict(provider='CPUExecutionProvider',op_name='MatMul')))
                (directory/(name+'_trace.json')).write_text(json.dumps(events))
            self.assertEqual(game.summarize_traces(directory)['modelRuns'],12)
            path=directory/'segmenter_trace.json'; data=json.loads(path.read_text());data.pop(0);path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'Incomplete GAME'):
                game.summarize_traces(directory)

    def test_heavy_only_rejects_cuda_conversion_and_heavy_cpu_substitution(self):
        placement = game.validate_placement(self.summary(), 'cuda_basic', True)
        self.assertTrue(placement['durationBoundaryGraphsRequiredOnCpu'])
        for name in set(game.GRAPHS) - game.HEAVY_GRAPHS:
            changed = self.summary()
            next(g for g in changed['graphs'] if g['graph'] == name)['operators'][0]['provider'] = 'CUDAExecutionProvider'
            # The old policy remains reproducible; the new request requires CPU conversions.
            game.validate_placement(changed, 'cuda_basic')
            with self.assertRaisesRegex(ValueError, 'Conversion graph must execute only on CPU'):
                game.validate_placement(changed, 'cuda_basic', True)
        for name in game.HEAVY_GRAPHS:
            changed = self.summary()
            next(g for g in changed['graphs'] if g['graph'] == name)['operators'][0]['provider'] = 'CPUExecutionProvider'
            with self.assertRaisesRegex(ValueError, 'No substantive CUDA'):
                game.validate_placement(changed, 'cuda_basic', True)

    def test_observer_note_and_raw_differences_are_never_quality_approval(self):
        valid=[dict(kind='plain-vs-capture',unroundedNotesIdentical=True,rawTensorsByteIdentical=None),
               dict(kind='capture-vs-profile',unroundedNotesIdentical=True,rawTensorsByteIdentical=True)]
        game.validate_observers(valid)
        for field in ['unroundedNotesIdentical','rawTensorsByteIdentical']:
            changed=[dict(x) for x in valid];changed[1][field]=False
            with self.assertRaises(game.accel.InvalidObserver):
                game.validate_observers(changed)
        with self.assertRaises(game.accel.InvalidObserver):
            game.validate_observers([])


if __name__ == '__main__':
    unittest.main()
