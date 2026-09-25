"""Reject unsafe paths, fabricated upstream scope, and orphaned audit processes."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('voice_auditor', ROOT /
    'research/performance/2026-09-25/game-separated-voice/verify_evidence.py')
auditor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auditor)


class SeparatedVoiceAuditorTests(unittest.TestCase):
    def test_unsafe_or_linked_input_never_resolves(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'real').write_text('safe')
            (root / 'link').symlink_to(root / 'real')
            for name in ('../real', '/real', 'a/../real', './real', 'a//real', 'C:/real', 'a\\real', 'link'):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    auditor.safe_file(root, name)

    def test_duplicate_or_nonfinite_receipt_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'receipt.json'
            for payload in ('{"status":"REJECTED","status":"VERIFIED"}', '{"x":NaN}', '{"x":1e999}'):
                path.write_text(payload)
                with self.assertRaises(ValueError):
                    auditor.strict_json(path)

    def test_upstream_audit_cannot_replace_actual_completed_cpu_gate_with_flags(self):
        value = dict(schema='lightforge.deux-source-independent-verification.v1', status='VERIFIED_CPU_DIAGNOSTIC',
            completedPredictions=24, exactObserverPassages=12, profiledGraphCalls=4020,
            productionReplayReceiptsExactlyEqual=True, savedStemFilesReproduced=3,
            cudaExecuted=False, modelInferenceExecuted=False, **{k: False for k in auditor.FLAGS})
        auditor.audit_scope(value)
        for mutation in (dict(status='REJECTED'), dict(completedPredictions=23), dict(profiledGraphCalls=335),
                         dict(exactObserverPassages=11), dict(productionReplayReceiptsExactlyEqual=False),
                         dict(savedStemFilesReproduced=2), dict(cudaExecuted=True), dict(target75Proven=True)):
            candidate = copy.deepcopy(value)
            candidate.update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                auditor.audit_scope(candidate)

    def test_trace_files_require_one_integer_original_call_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            event = dict(cat='Session', name='model_run', ph='X', pid=17, tid=19)
            for index in range(30):
                count = 3 if index < 12 else 2
                (root / f'{index:02d}.json').write_text(json.dumps([event] * count))
            self.assertEqual(auditor.independent_trace_owners(root), dict(processId=17, runThreadId=19, modelRuns=72))
            last = root / '29.json'
            for changed in ({**event, 'pid': 18}, {**event, 'tid': 20}, {**event, 'pid': True},
                            {key: value for key, value in event.items() if key != 'tid'}):
                last.write_text(json.dumps([event, changed]))
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    auditor.independent_trace_owners(root)
            last.write_text(json.dumps([event]))
            with self.assertRaises(ValueError):
                auditor.independent_trace_owners(root)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Owned Linux process group cleanup')
    def test_timeout_allows_upstream_handler_to_retire_separate_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / 'upstream.py'
            script.write_text('''import os,signal,subprocess,sys,time
from pathlib import Path
child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],start_new_session=True)
def stop(signum,frame):
    os.killpg(child.pid,signal.SIGKILL)
    child.wait()
    raise SystemExit(130)
signal.signal(signal.SIGTERM,stop)
Path(sys.argv[1]).write_text(str(child.pid))
time.sleep(60)
''')
            pid_file = root / 'pid'
            with self.assertRaises(subprocess.TimeoutExpired):
                auditor.run_child([sys.executable, script, pid_file], root / 'audit.log', timeout=.5)
            self.assertTrue(pid_file.exists())
            self.assertFalse(Path('/proc/' + pid_file.read_text()).exists())


if __name__ == '__main__':
    unittest.main()
