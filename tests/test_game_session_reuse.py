"""Isolated session reuse must preserve exact calls and reject ambiguous trace evidence."""
import copy
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('session_reuse_collector', ROOT / 'tools/benchmark_game_session_reuse.py')
reuse = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reuse)


class SessionReuseCollectorTest(unittest.TestCase):
    def fixture(self, root, arm='reuse', variant='cpu_all'):
        provenance = dict(sourceSamples=64*44100, pcmSHA256='a'*64, language=0)
        plan = reuse.baseline.passage_plan(provenance['sourceSamples'])
        for row in plan: row['pcmSha256'] = str(row['index'])*64
        markers = dict(schema='lightforge.game-session-reuse-trace-markers.v1', sourcePcmSha256='a'*64,
            sourceSamples=provenance['sourceSamples'], language=0, singleThreadOwner=True, sessions=[], passages=[])
        clocks, graph_counts = {}, {graph:0 for graph in reuse.game.GRAPHS}
        events, session_ids, java_clock = {}, {}, 100
        for row in plan:
            if arm == 'default' or row['index'] == 0:
                for graph in reuse.game.GRAPHS:
                    sid = len(markers['sessions']); ordinal = graph_counts[graph]; graph_counts[graph] += 1
                    session_ids[graph] = sid; clocks[sid] = 1000; events[sid] = []
                    markers['sessions'].append(dict(graph=graph, sessionOrdinal=ordinal, prefix=f'{graph}_s{ordinal:03d}',
                        createdPassage=row['index'], sessionIndex=sid, calls=0))
            passage = {k:row[k] for k in ('index','first','last','seed','pcmSha256')}
            passage.update(beginNanos=java_clock, calls=[]); java_clock += 1
            for index, graph in enumerate(reuse.ORDER):
                sid = session_ids[graph]; session = markers['sessions'][sid]
                passage['calls'].append(dict(callIndex=index, graph=graph, sessionIndex=sid,
                    graphRunOrdinal=session['calls'], beginNanos=java_clock, endNanos=java_clock+1))
                java_clock += 2; session['calls'] += 1
                # ORT has an independent session clock; these timestamps are not
                # comparable to Java markers (which may be arbitrarily offset).
                timestamp = clocks[sid]; clocks[sid] += 20
                provider = 'CUDAExecutionProvider' if variant == 'cuda_basic' and graph in reuse.game.HEAVY_GRAPHS else 'CPUExecutionProvider'
                events[sid].extend([
                    dict(cat='Session', name='model_run', ph='X', ts=timestamp, dur=10, pid=42, tid=43),
                    dict(cat='Node', name='node_kernel_time', ph='X', ts=timestamp+2, dur=5, pid=42, tid=43,
                         args=dict(provider=provider, op_name='MatMul'))])
            passage['endNanos'] = java_clock; java_clock += 1; markers['passages'].append(passage)
        traces=root/'traces'; traces.mkdir()
        for sid, session in enumerate(markers['sessions']):
            (traces/(session['prefix']+'_2026.json')).write_text(json.dumps(events[sid]))
        marker_path=root/'markers.json'; marker_path.write_text(json.dumps(markers))
        return traces, marker_path, provenance, plan, markers

    def summarize(self, fixture, arm='reuse', variant='cpu_all'):
        traces, path, provenance, plan, _ = fixture
        return reuse.summarize_session_traces(traces,path,arm,variant,provenance,plan)

    def test_exact_72_calls_are_partitioned_for_both_lifetimes_and_providers(self):
        for arm in reuse.ARMS:
            for variant in reuse.VARIANTS:
                with self.subTest(arm=arm,variant=variant), tempfile.TemporaryDirectory() as temp:
                    summary=self.summarize(self.fixture(Path(temp),arm,variant),arm,variant)
                    self.assertEqual(summary['sessionCount'],5 if arm=='reuse' else 30)
                    self.assertEqual(summary['modelRuns'],72)
                    self.assertEqual([r['modelRuns'] for r in summary['passages']],[12]*6)
                    self.assertEqual(len(summary['placement']),6)

    def test_markers_reject_wrong_pcm_seed_call_order_session_and_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture=self.fixture(Path(temp)); path, original=fixture[1], fixture[4]
            mutations = [lambda x:x['passages'][1].update(pcmSha256='f'*64),
                lambda x:x['passages'][1].update(seed=1),
                lambda x:x['passages'][1]['calls'][0].update(graph='estimator'),
                lambda x:x['passages'][1]['calls'][0].update(sessionIndex=4),
                lambda x:x['passages'][1]['calls'][0].update(graphRunOrdinal=0),
                lambda x:x['passages'][1]['calls'][0].pop('endNanos'),
                lambda x:x['sessions'][0].update(createdPassage=1),
                lambda x:x['passages'][1].update(beginNanos=0)]
            for mutate in mutations:
                changed=copy.deepcopy(original); mutate(changed); path.write_text(json.dumps(changed))
                with self.assertRaises((ValueError,KeyError)): self.summarize(fixture)

    def test_trace_rejects_missing_extra_overlapping_or_unbound_ort_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture=self.fixture(Path(temp)); path=next(fixture[0].glob('encoder*')); original=json.loads(path.read_text())
            mutations=[lambda x:x.pop(0), lambda x:x.append(copy.deepcopy(x[0])),
                lambda x:x[2].update(ts=x[0]['ts']+1), lambda x:x[1].update(ts=x[0]['ts']-1),
                lambda x:x[1].update(dur=100), lambda x:x[0].update(pid=99),
                lambda x:x[0].update(tid=999), lambda x:x[0].pop('pid'), lambda x:x[1]['args'].update(provider='UnknownExecutionProvider')]
            for mutate in mutations:
                changed=copy.deepcopy(original); mutate(changed); path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError): self.summarize(fixture)

    def test_ort_clock_origin_is_never_compared_to_java_clock(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture=self.fixture(Path(temp)); markers=fixture[4]
            for p in markers['passages']:
                p['beginNanos']+=10**15;p['endNanos']+=10**15
                for c in p['calls']:c['beginNanos']+=10**15;c['endNanos']+=10**15
            fixture[1].write_text(json.dumps(markers))
            self.assertEqual(self.summarize(fixture)['modelRuns'],72)

    def test_wrong_lifetime_and_foreign_trace_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture=self.fixture(Path(temp))
            with self.assertRaises(ValueError):self.summarize(fixture,'default')
            (fixture[0]/'unbound.json').write_text('[]')
            with self.assertRaises(ValueError):self.summarize(fixture)

    def test_default_and_reuse_observers_leave_numerical_source_unchanged(self):
        original=reuse.game.SOURCE.read_text()
        for variant in reuse.VARIANTS:
            for arm in reuse.ARMS:
                plain=reuse.source_snapshot(original,variant,arm,'plain',64*44100)
                if arm=='default':self.assertEqual(plain,reuse.game.variant_source(original,variant,True,True))
                captured=reuse.source_snapshot(original,variant,arm,'captured',64*44100)
                self.assertEqual(captured,reuse.game.observed_source(plain))
                profiled=reuse.source_snapshot(original,variant,arm,'profiled',64*44100,traces=Path('/tmp/reuse-traces'))
                self.assertIn('try{GameSessionReuseTrace.after(researchTicket);GameAcceleratorCapture.record(',profiled)
                self.assertIn('catch(Exception|Error error){retire(result);throw error;}',profiled)
                self.assertIn('options.enableProfiling(GameSessionReuseTrace.nextPrefix(GRAPHS[i]));',profiled)
                self.assertEqual(profiled.count('GameSessionReuseTrace.before('),1)
                self.assertEqual(plain.split('    private JSONArray infer(',1)[1].split('    /** ',1)[0],
                    original.split('    private JSONArray infer(',1)[1].split('    /** ',1)[0])
        with self.assertRaises(ValueError):reuse.source_snapshot(original,'cuda_basic','reuse','profiled',64*44100)
        with self.assertRaises(ValueError):reuse.source_snapshot(original+'\n','cpu_all','default','plain',64*44100)


    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux process-group ownership check')
    def test_sigterm_unwinds_and_retires_child_process_group(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); pids=root/'pids.json'; log=root/'child.log'
            child="import json,os,subprocess,sys,time; from pathlib import Path; grandchild=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); Path(sys.argv[1]+'.tmp').write_text(json.dumps([os.getpid(),grandchild.pid])); Path(sys.argv[1]+'.tmp').replace(sys.argv[1]); time.sleep(60)"
            driver="""import importlib.util,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('termination_test',sys.argv[1]); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.install_termination_handler()
try:m.baseline.run_process([sys.executable,'-c',sys.argv[2],sys.argv[3]],Path(sys.argv[4]),60)
except KeyboardInterrupt:sys.exit(130)
"""
            process=subprocess.Popen([sys.executable,'-c',driver,str(ROOT/'tools/benchmark_game_session_reuse.py'),child,str(pids),str(log)],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            descendants=[]
            try:
                deadline=time.monotonic()+5
                while not pids.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(pids.exists(),'Child did not reach the guarded run')
                descendants=json.loads(pids.read_text())
                os.kill(process.pid,signal.SIGTERM)
                stdout,stderr=process.communicate(timeout=5)
                self.assertEqual(process.returncode,130,(stdout,stderr))
                for pid in descendants:
                    stat=Path(f'/proc/{pid}/stat')
                    # An orphaned grandchild can briefly await init reaping; it
                    # must never remain executable after group termination.
                    if stat.exists():self.assertEqual(stat.read_text().rsplit(')',1)[1].split()[0],'Z')
            finally:
                if process.poll() is None:process.kill();process.wait()
                for pid in descendants:
                    try:os.kill(pid,signal.SIGKILL)
                    except ProcessLookupError:pass

    def test_new_runner_requires_final_retirement_and_never_moves_per_passage_traces(self):
        text=reuse.HELPERS[0].read_text()
        self.assertEqual(text.count('new NativeGame('),1)
        self.assertIn('finally {engine.close();}',text)
        self.assertIn('if(!engine.isRetired())',text)
        self.assertNotIn('moveTraces',text)
        self.assertIn('GameSessionReuseTrace.finish()',text)
        self.assertNotIn('Math.round',text)

if __name__=='__main__':unittest.main()
