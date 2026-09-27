"""Meaningful safety checks for the frozen public Deux wrapper and export boundary."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'research/performance/2026-09-25/deux-full-source'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


driver = load('deux_local_test_driver', DIRECTORY / 'run_local.py')
exporter = load('deux_local_test_exporter', DIRECTORY / 'export_evidence.py')


class DeuxLocalDriverTest(unittest.TestCase):
    def fixture(self):
        qualification = dict(schema='lightforge.deux-source-cuda-experiment.v1', status='CPU_SOURCE_DIAGNOSTIC_COMPLETE',
            variants=['cpu_all'], modes=['plain', 'profiled'], gpuRuntime=None, rawOutputsByteIdenticalAcrossVariants=None,
            crossVariantComparisons=[], audioFrames=64 * 44100, audioSha256=driver.WAV['sha256'], passagePlan=[{}] * 12,
            runs=[dict(label='cpu_all_' + mode, passageCount=12, freshProcessExited=True) for mode in ('plain', 'profiled')],
            observerComparisonsPassed=True, inputsRecheckedAfterQualification=True, allInputAndArtifactHashesRechecked=True,
            observerComparisons=[dict(passageIndex=i, variant='cpu_all', byteIdentical=True) for i in range(12)],
            measured=False, wholeSongSpeedupProven=False, fullVocalStageSpeedupProven=False, androidSpeedupProven=False)
        replay = dict(schema='lightforge-deux-source-consumer-replay-1', status='CPU_SOURCE_CONSUMER_DIAGNOSTIC_COMPLETE',
            variants=['cpu_all'], passageCount=12, audioSha256=driver.WAV['sha256'], audioSamples=64 * 44100,
            gpuCaptureConsumed=False, crossProviderComparisonPerformed=False, comparison=None, completeStemBytesIdentical=None,
            fullVocalStageExecuted=False, observerComparisonsIndependentlyByteChecked=12, checkpointResumeIdentical=True,
            originalProductionArithmetic=True, capturedInputSourceBytesRevalidated=True, persistedOutputBytesRechecked=True,
            fullAnalysisQualityApproved=False, androidIntegrationApproved=False)
        for evidence in (qualification, replay):
            evidence.update({key: False for key in driver.FLAGS})
        return qualification, replay

    def test_complete_cpu_scope_rejects_missing_predictions_observers_recovery_and_approvals(self):
        original = self.fixture()
        driver.validate_completion(*original)
        mutations = (
            lambda q, r: q['runs'][0].update(passageCount=11),
            lambda q, r: q['observerComparisons'][11].update(passageIndex=10),
            lambda q, r: q['observerComparisons'][0].update(byteIdentical=False),
            lambda q, r: q.update(gpuRuntime={}),
            lambda q, r: q.update(target75Proven=True),
            lambda q, r: q.update(measured=True),
            lambda q, r: r.update(checkpointResumeIdentical=False),
            lambda q, r: r.update(persistedOutputBytesRechecked=False),
            lambda q, r: r.update(gpuCaptureConsumed=True),
            lambda q, r: r.update(androidIntegrationApproved=True),
        )
        for mutate in mutations:
            evidence = copy.deepcopy(original)
            mutate(*evidence)
            with self.assertRaises(ValueError):
                driver.validate_completion(*evidence)

    def test_allowlist_accepts_expected_outputs_and_rejects_models_credentials_foreign_audio(self):
        allowed = (
            'glass-castle.wav', 'consumer/cpu_all/vocals.wav', 'consumer/cpu_all/voice-full.wav',
            'qualification/cpu_all_profiled/passage-011/traces/block-11-time_2026-09-25_00-00-00.json',
            'qualification/cpu_all_profiled_active_traces/front_2026.json',
            'qualification/cpu_all_plain/passage-000/receipt.json.partial', 'qualification/receipt.partial',
            'readiness/snapshots/cpu_all_plain/classes/com/cyberbasslord/lightforge/NativeDeux$State.class',
        )
        for name in allowed:
            self.assertTrue(exporter.allowed(Path(name), {}), name)
        blocked = (
            'private.wav', 'model.onnx', 'qualification/model.onnx', 'qualification/credentials.json',
            'qualification/cpu_all_plain/passage-012/stems.f32', 'consumer/cpu_all/private.wav',
            'execution-source/unbound.py', 'readiness/snapshots/cpu_all_plain/runtime.jar',
            'qualification/cuda_basic_plain/passage-000/stems.f32',
        )
        for name in blocked:
            self.assertFalse(exporter.allowed(Path(name), {}), name)
        self.assertTrue(exporter.allowed(Path('execution-source/tools/frozen.py'), {'tools/frozen.py': {}}))

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux descendant ownership test')
    def test_shared_deadline_retires_separately_sessioned_descendant(self):
        cleanup = load('deux_cleanup_test', ROOT / driver.CLEANUP)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            pids = directory / 'pids.json'
            child = (
                'import json,os,signal,subprocess,sys,time; from pathlib import Path; '
                "grandchild=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],start_new_session=True); "
                'Path(sys.argv[1]).write_text(json.dumps([os.getpid(),grandchild.pid])); time.sleep(60)'
            )
            started = time.monotonic()
            try:
                with self.assertRaises(TimeoutError):
                    driver.stage([sys.executable, '-c', child, pids], directory / 'stage.log',
                                 directory / 'absent.json', time.monotonic() + .5, cleanup)
                self.assertLess(time.monotonic() - started, 12)
                self.assertTrue(pids.is_file())
                for pid in json.loads(pids.read_text()):
                    stat = Path(f'/proc/{pid}/stat')
                    # SIGKILL delivery can precede task retirement by a scheduler
                    # turn; permit bounded observation, never a live process.
                    stopped_by = time.monotonic() + 1
                    while stat.exists() and stat.read_text().rsplit(')', 1)[1].split()[0] != 'Z' and time.monotonic() < stopped_by:
                        time.sleep(.01)
                    if stat.exists():
                        self.assertEqual(stat.read_text().rsplit(')', 1)[1].split()[0], 'Z', f'Live descendant: {pid}')
                with self.assertRaises(ValueError):
                    driver.stage([sys.executable, '-c', 'raise Exception("must not launch")'], directory / 'not-created.log',
                                 directory / 'absent.json', started, cleanup)
                self.assertFalse((directory / 'not-created.log').exists())
            finally:
                # Clean only test PIDs, never global JVMs or other sessions.
                if pids.exists():
                    import os
                    import signal
                    for pid in json.loads(pids.read_text()):
                        try:
                            os.kill(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass

    def test_jdk_escape_link_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'escape').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):
                driver.jdk_inventory(directory)


if __name__ == '__main__':
    unittest.main()
