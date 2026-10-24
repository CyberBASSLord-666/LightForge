"""Native validation receipts distinguish subprocess attempts from verified inference."""
import copy
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
try:
    SPEC = importlib.util.spec_from_file_location('passage_process_receipt', ROOT / 'tools/verify_deux_passage.py')
    VERIFY = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(VERIFY)
finally:
    sys.path.pop(0)


class PassageProcessReceiptTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.log = Path(self.temporary.name) / 'process.log'
        self.record = dict(passed=False, inferencePerformed=False)
        self.checkpoints = []

    def invoke(self, command, timeout=5):
        return VERIFY.run_native_process(self.record, lambda: self.checkpoints.append(copy.deepcopy(self.record)),
            'fixture-child', self.log, command, capture_output=True, text=True, timeout=timeout)

    def test_nonzero_exit_retains_prelaunch_checkpoint_and_actual_failure(self):
        result = self.invoke([sys.executable, '-c', 'import sys; print("child ran"); sys.exit(7)'])
        self.assertEqual(result.returncode, 7)
        first = self.checkpoints[0]
        self.assertIsNone(first['inferencePerformed'])
        self.assertFalse(first['passed'])
        self.assertEqual(first['nativeProcessAttempts'][0]['status'], 'launch-attempted')
        self.assertIsNone(first['nativeProcessAttempts'][0]['launched'])
        attempt = self.checkpoints[-1]['nativeProcessAttempts'][0]
        self.assertEqual(attempt['status'], 'exited')
        self.assertTrue(attempt['launched'])
        self.assertTrue(attempt['processCompleted'])
        self.assertEqual(attempt['exitCode'], 7)
        self.assertIsNone(self.record['inferencePerformed'])
        self.assertFalse(self.record['passed'])
        self.assertEqual(self.log.read_text(), 'child ran\n')

    def test_zero_exit_does_not_itself_claim_validated_neural_work(self):
        self.invoke([sys.executable, '-c', 'pass'])
        self.assertEqual(self.record['nativeProcessAttempts'][0]['exitCode'], 0)
        self.assertIsNone(self.record['inferencePerformed'])
        self.assertFalse(self.record['passed'])

    def test_timeout_retains_partial_log_without_claiming_completion(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.invoke([sys.executable, '-c', 'import time; print("started", flush=True); time.sleep(5)'], timeout=.2)
        attempt = self.record['nativeProcessAttempts'][0]
        self.assertEqual(attempt['status'], 'timed-out')
        self.assertTrue(attempt['launched'])
        self.assertFalse(attempt['processCompleted'])
        self.assertIsNone(attempt['exitCode'])
        self.assertIsNone(self.record['inferencePerformed'])
        self.assertFalse(self.record['passed'])
        self.assertEqual(self.log.read_text(), 'started\n')

    def test_launch_failure_preserves_known_absence_of_inference(self):
        with self.assertRaises(FileNotFoundError):
            self.invoke([str(Path(self.temporary.name) / 'missing-executable')])
        attempt = self.record['nativeProcessAttempts'][0]
        self.assertEqual(attempt['status'], 'launch-failed')
        self.assertFalse(attempt['launched'])
        self.assertFalse(attempt['processCompleted'])
        self.assertIsNone(attempt['exitCode'])
        self.assertFalse(self.record['inferencePerformed'])
        self.assertFalse(self.record['passed'])

    def test_a_later_failed_attempt_does_not_erase_prior_verified_inference(self):
        self.record['inferencePerformed'] = True
        self.invoke([sys.executable, '-c', 'raise SystemExit(1)'])
        self.assertTrue(self.record['inferencePerformed'])
        self.assertFalse(self.record['passed'])
        self.assertEqual(self.record['nativeProcessAttempts'][0]['exitCode'], 1)


if __name__ == '__main__':
    unittest.main()
