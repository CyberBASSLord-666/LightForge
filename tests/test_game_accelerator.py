"""GAME GPU diagnostics must preserve full passage geometry and useful evidence."""
import importlib.util
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
