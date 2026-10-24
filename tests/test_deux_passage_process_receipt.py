"""Native validation receipts distinguish subprocess attempts from verified inference."""
import ast
import copy
from contextlib import ExitStack
import json
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

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


class PassageSourceBindingTest(unittest.TestCase):
    """Exercise the real main/snapshot path; javac alone is a mocked boundary."""
    def required_additions(self):
        return {
            'version.json', 'tests/NativeDeuxCalibrationTest.java', 'tools/verify_deux_passage.py',
            VERIFY.CURRENT_ANALYSIS_VERIFIER, 'tests/test_native_scheduler_evidence.py',
            'tests/test_native_baseline_cancellation_evidence.py', 'tests/test_deux_passage_process_receipt.py',
        }

    def invoke_compile(self, parent, mutate=None):
        root = parent / 'repository'
        root.mkdir()
        original_sources = set(VERIFY.benchmark.SOURCE_PATHS)
        expected = original_sources | self.required_additions()
        for name in expected:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('isolated binding fixture: ' + name + '\n')
        dependencies = [parent / 'toolchain' / name for name in (
            'test-json.jar', 'android-sdk/platforms/android-35/android.jar', 'onnx/onnxruntime-1.25.1.jar')]
        for dependency in dependencies:
            dependency.parent.mkdir(parents=True, exist_ok=True)
            dependency.write_bytes(b'isolated dependency fixture')
        frozen = root / 'research/inference-2.4.1/separator-scheduler-paired.json'
        frozen.parent.mkdir(parents=True)
        frozen.write_text(json.dumps({'dependencyHashes': {p.name: VERIFY.b.sha(p) for p in dependencies}}))
        output = parent / 'scratch-observation'

        def javac(command, **kwargs):
            self.assertEqual(Path(command[0]).name, 'javac')
            if mutate:
                (root / mutate).write_text('changed during mocked compiler execution\n')
            return subprocess.CompletedProcess(command, 0, stdout='', stderr='')

        with ExitStack() as stack:
            stack.enter_context(patch.object(VERIFY, 'ROOT', root))
            stack.enter_context(patch.object(VERIFY.benchmark, 'ROOT', root))
            stack.enter_context(patch.object(VERIFY.benchmark, 'SOURCE_PATHS', set(original_sources)))
            stack.enter_context(patch.object(sys, 'argv', ['verify_deux_passage.py', '--compile-only', '--output', str(output)]))
            stack.enter_context(patch.object(VERIFY.benchmark.subprocess, 'run', side_effect=javac))
            stack.enter_context(patch('builtins.print'))
            VERIFY.main()
            sources_after = set(VERIFY.benchmark.SOURCE_PATHS)
        return output, expected, sources_after, original_sources

    def test_main_compiles_and_receipts_every_passage_source_with_exact_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            output, expected, sources_after, original_sources = self.invoke_compile(Path(temporary))
            receipt = json.loads((output / 'receipt.json').read_text())
            self.assertEqual(set(receipt['sourceBindings']), expected)
            self.assertEqual(sources_after, original_sources, 'Passage verification must not mutate the benchmark inventory')
            for name, digest in receipt['sourceBindings'].items():
                self.assertEqual(VERIFY.b.sha(output / 'source-snapshots' / name), digest)
            self.assertFalse(receipt['inferencePerformed'])
            self.assertFalse(receipt['passed'])

    def test_real_compile_snapshot_rejects_each_changed_passage_only_source(self):
        for name in sorted(self.required_additions()):
            with self.subTest(source=name), tempfile.TemporaryDirectory() as temporary:
                with self.assertRaisesRegex(ValueError, 'Production sources changed during compilation'):
                    self.invoke_compile(Path(temporary), mutate=name)

    def test_all_passage_source_rechecks_use_the_same_explicit_inventory(self):
        tree = ast.parse((ROOT / 'tools/verify_deux_passage.py').read_text())
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == 'source_bindings']
        self.assertEqual(len(calls), 3)
        for call in calls:
            self.assertEqual(len(call.args), 1)
            self.assertIsInstance(call.args[0], ast.Name)
            self.assertEqual(call.args[0].id, 'passage_sources')


if __name__ == '__main__':
    unittest.main()
