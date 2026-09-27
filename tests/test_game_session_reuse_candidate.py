"""The host-only reuse proposal must preserve numerics and expose lifecycle changes."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('game_session_reuse', ROOT / 'tools/game_benchmark/session_reuse_candidate.py')
reuse = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reuse)


class GameSessionReuseCandidateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = reuse.game.SOURCE.read_text()

    def candidate(self, variant='cpu_all', **settings):
        return reuse.generate(self.original, variant, source_samples=settings.get('source_samples', 64 * 44100),
                              language=settings.get('language', 0))

    def test_changed_original_or_ambiguous_anchor_fails_closed(self):
        for altered in (self.original + '\n', self.original.replace('STEPS=8', 'STEPS=4'),
                        self.original.replace('retire(result);throw error;', 'throw error;')):
            with self.assertRaisesRegex(ValueError, 'bytes changed'):
                reuse.generate(altered, 'cpu_all', source_samples=44100)
        for value in ('absent', 'anchor anchor'):
            with self.assertRaisesRegex(ValueError, 'anchor changed'):
                reuse.replace_once(value, 'anchor', 'replacement')

    def test_models_diffusion_notes_jni_result_ownership_are_byte_identical(self):
        for variant in reuse.VARIANTS:
            candidate = self.candidate(variant)
            self.assertEqual(candidate.split('    private JSONArray infer(', 1)[1].split('    /** HOST RESEARCH ONLY: requests termination', 1)[0],
                             self.original.split('    private JSONArray infer(', 1)[1].split('    /** Stops kernels cooperatively;', 1)[0])
            self.assertEqual(candidate.split('    private void check(', 1)[1], self.original.split('    private void check(', 1)[1])
            self.assertIn('STEPS=8', candidate)
            self.assertIn('prepareModels(cancellation);', candidate)
            self.assertEqual(candidate.count('activeRun=new OrtSession.RunOptions();'), 1)
            self.assertIn('activeRun;activeRun=null;', candidate)
            self.assertIn('if(retiringRun!=null)try{retire(retiringRun);}', candidate)

    def test_cpu_and_cuda_keep_their_qualified_session_options_exactly(self):
        for variant in reuse.VARIANTS:
            candidate = self.candidate(variant)
            qualified = reuse.game.variant_source(self.original, variant, True, True)
            start = '                try(Owned<OrtSession.SessionOptions> resource='
            end = '                check(cancellation);\n            }'
            self.assertEqual(candidate.split(start, 1)[1].split(end, 1)[0],
                             qualified.split(start, 1)[1].split(end, 1)[0])
        self.assertNotIn('addCUDA', self.candidate('cpu_all'))
        cuda = self.candidate('cuda_basic')
        self.assertIn('setDeterministicCompute(true)', cuda)
        self.assertIn('if("encoder".equals(GRAPHS[i])||"segmenter".equals(GRAPHS[i])||"estimator".equals(GRAPHS[i]))', cuda)

    def test_host_only_bound_clock_language_seed_and_owner_are_explicit(self):
        candidate = self.candidate(source_samples=2822400, language=3)
        self.assertIn('RESEARCH_SOURCE_SAMPLES=2822400, RESEARCH_LANGUAGE=3', candidate)
        self.assertIn('if(context!=null)throw new IOException', candidate)
        self.assertIn('Thread.currentThread()!=researchOwner', candidate)
        self.assertIn('int first=Math.max(0,index*core-halo),last=Math.min(RESEARCH_SOURCE_SAMPLES,(index+1)*core+halo);', candidate)
        self.assertIn('seed!=((2025L+index*104729L)&0xffffffffL)', candidate)
        for values in [dict(source_samples=0), dict(source_samples=64 * 44100 + 1),
                       dict(source_samples=True), dict(language=True), dict(language=5)]:
            with self.assertRaises(ValueError):
                self.candidate(**values)
        with self.assertRaises(ValueError):
            self.candidate('cpu_basic')

    def test_cancellation_terminates_before_waiting_and_never_retires_reentrant_active_run(self):
        candidate = self.candidate()
        cancel = candidate.split('    public void cancel() {', 1)[1].split('    /** HOST RESEARCH ONLY: blocking', 1)[0]
        self.assertLess(cancel.index('activeRun.setTerminate(true)'), cancel.index('researchDrainWhenIdle();'))
        # The closing brace releases lifecycle before acquiring the predictor
        # monitor: cancellation cannot wait while blocking run-handle detachment.
        self.assertIn('        }\n        researchDrainWhenIdle();', cancel)
        self.assertIn('private synchronized void researchDrainWhenIdle()', candidate)
        self.assertIn('if(running||researchDraining)return;', candidate)
        self.assertIn('if(failure!=null||cancelled||closed||retirement!=null)', candidate)
        self.assertIn('if(!cleanupConfirmed){researchResourcesRetired=false;retirementUnconfirmed=true;cancelled=true;}', candidate)
        self.assertIn('public void close(){synchronized(lifecycle){closed=true;}cancel();}', candidate)

    def test_retirement_requires_explicit_completed_drain_not_only_idle_state(self):
        candidate = self.candidate()
        self.assertIn('private boolean researchResourcesRetired=true,researchDraining;', candidate)
        self.assertIn('running=true;researchResourcesRetired=false;', candidate)
        query = candidate.split('    public boolean isRetired()', 1)[1].split('\n\n', 1)[0]
        self.assertIn('synchronized(lifecycle)', query)
        self.assertIn('closed&&!running&&!researchDraining&&researchResourcesRetired&&!retirementUnconfirmed', query)
        self.assertNotIn('sessions.', query)
        drain = candidate.split('    private synchronized void researchDrainWhenIdle()', 1)[1].split('    /** False after', 1)[0]
        self.assertLess(drain.index('researchDraining=true;researchResourcesRetired=false;'), drain.index('researchRetireSessions(null)'))
        self.assertIn('boolean cleanupConfirmed=false;', drain)
        self.assertIn('try{cleanupConfirmed=researchRetireSessions(null)==null;}', drain)
        self.assertIn('researchResourcesRetired=cleanupConfirmed&&activeRun==null&&!retirementUnconfirmed;', drain)
        self.assertIn('if(!cleanupConfirmed){retirementUnconfirmed=true;cancelled=true;}', drain)
        self.assertIn('else if(sessionsDrained)researchResourcesRetired=activeRun==null&&!retirementUnconfirmed;', candidate)

    def test_reentrant_predict_rejects_before_claiming_outer_ownership(self):
        candidate = self.candidate()
        begin = candidate.split('public synchronized JSONArray predict(', 1)[1].split('            prepareModels(cancellation);', 1)[0]
        guard = begin.split('if(running||researchDraining){', 1)[1].split('            running=true;', 1)[0]
        self.assertIn('cancelled=true;', guard)
        self.assertIn('activeRun.setTerminate(true)', guard)
        self.assertIn('throw new IOException("Reentrant prediction forbidden; outer owner retains cleanup")', guard)
        self.assertNotIn('researchRetireSessions', guard)
        self.assertNotIn('activeRun=', guard)
        self.assertNotIn('running=', guard)
        self.assertLess(begin.index('Reentrant prediction forbidden'), begin.index('Throwable failure=null;'))
        self.assertLess(begin.index('Reentrant prediction forbidden'), begin.index('check(cancellation);'))

    def test_invalid_inputs_fail_within_terminal_cleanup_scope(self):
        candidate = self.candidate()
        begin = candidate.split('public synchronized JSONArray predict(', 1)[1].split('            prepareModels(cancellation);', 1)[0]
        self.assertLess(begin.index('try {'), begin.index('check(cancellation);'))
        self.assertLess(begin.index('try {'), begin.index('validatedPcm(pcm,language,seed)'))
        self.assertLess(begin.index('try {'), begin.index('Bound complete-source passage count exceeded'))
        self.assertIn('failure=error;\n            synchronized(lifecycle){cancelled=true;}\n            throw error;', candidate)
        self.assertIn('for(OrtSession session:sessions.values())try{retire(session);}catch(Throwable error){if(first==null)first=error;}\n        sessions.clear();', candidate)


if __name__ == '__main__':
    unittest.main()
