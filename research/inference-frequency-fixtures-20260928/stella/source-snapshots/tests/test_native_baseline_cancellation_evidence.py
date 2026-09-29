"""A baseline cancellation proof must retain native failure provenance and exact recovery."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
try:
    SPEC = importlib.util.spec_from_file_location('baseline_cancellation_evidence', ROOT / 'tools/verify_deux_passage.py')
    VERIFY = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(VERIFY)
finally:
    sys.path.pop(0)


class BaselineCancellationEvidenceTest(unittest.TestCase):
    def valid(self):
        # Existing real full-output data supplies only the recovery shape here.
        # Synthetic cancellation flags test validation; they are not JNI evidence.
        reference = json.loads((ROOT / 'research/inference-device-regression-20260928/native-passage-integration.raw.json').read_text())
        self.digest = reference['runs']['reference']['outputSha256']
        flags = ['observedNativeOwner', 'activeRunOptionsObserved', 'gateHeldWhileNative', 'exclusiveGate',
                 'ownerRetired', 'runOptionsClosed', 'gateReleased', 'interruptionReported',
                 'originalOrtCauseRetained', 'noSuppressedCleanupFailures', 'noOutputCommitted', 'noTemporaryOutputs']
        return dict(schema='lightforge.native-baseline-cancellation.v1', passed=True, samplesPerStem=573300,
                    outputBytes=4586400, startSample=661500,
                    cancellation=dict(mode='baseline-runner-cancel', **dict.fromkeys(flags, True)),
                    recovery=reference['runs']['reference'])

    def reject(self, value, digest=None):
        with self.assertRaises(ValueError):
            VERIFY.verify_baseline_cancellation(value, self.digest if digest is None else digest)

    def test_complete_schema_accepts_exact_baseline_recovery(self):
        value = self.valid()
        self.assertEqual(VERIFY.verify_baseline_cancellation(value, self.digest), value)

    def test_native_observations_and_clean_retirement_are_all_required(self):
        valid = self.valid()
        for key in valid['cancellation']:
            for bad in [False, 1, None, 'true']:
                with self.subTest(key=key, bad=bad):
                    value = copy.deepcopy(valid)
                    value['cancellation'][key] = bad
                    self.reject(value)
            value = copy.deepcopy(valid)
            del value['cancellation'][key]
            self.reject(value)

    def test_pre_run_cancel_and_unknown_cleanup_cannot_be_relabelled(self):
        for key, bad in [('mode', 'before-run'), ('originalOrtCauseRetained', False),
                         ('noSuppressedCleanupFailures', False), ('activeRunOptionsObserved', False)]:
            value = self.valid()
            value['cancellation'][key] = bad
            self.reject(value)
        value = self.valid()
        value['cancellation']['cleanupFailure'] = 'ignored'
        self.reject(value)

    def test_complete_original_geometry_and_digest_are_required(self):
        for key, bad in [('passed', 1), ('samplesPerStem', 573299), ('outputBytes', 4),
                         ('startSample', 0), ('schema', 'unknown')]:
            value = self.valid()
            value[key] = bad
            self.reject(value)
        for key, bad in [('outputSha256', 'b' * 64), ('outputBytes', 4), ('finite', 1),
                         ('inferenceCalls', 875), ('inferenceCalls', True)]:
            value = self.valid()
            value['recovery'][key] = bad
            self.reject(value)
        value = self.valid()
        self.reject(value, 'invalid')
        self.reject(value, 'b' * 64)

    def test_partial_or_parallel_recovery_is_rejected(self):
        value = self.valid()
        value['recovery']['profileRecords'] = [record.replace('runCount=15', 'runCount=14')
            if 'graph=block-00-time ' in record else record for record in value['recovery']['profileRecords']]
        self.reject(value)
        value = self.valid()
        value['recovery']['profileRecords'][0] = value['recovery']['profileRecords'][0].replace(
            'schedulerCalibrationCount=unavailable', 'schedulerCalibrationCount=1')
        self.reject(value)
        value = self.valid()
        value['recovery']['profileRecords'].pop()
        self.reject(value)


if __name__ == '__main__':
    unittest.main()
