"""Release admission rejects incomplete parallel, cache and native cancellation proofs."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('scheduler_release', ROOT / 'qa/release-2.4.1/verify-analysis.py')
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


class SchedulerEvidenceTest(unittest.TestCase):
    def run_record(self, workers=1, calibration=False):
        graph_counts = {name: (15 if workers == 1 else 60) if name.endswith('-time') else
                        (1 if name == 'front' else 11) for name in VERIFY.PROFILE_EXPECTED_GRAPHS}
        calls = sum(graph_counts.values())
        summary = dict(schema='native-inference-profile-v2', outcome='completed', stageRecords='15',
                       graphRecords='27', droppedStageRecords='0', droppedGraphRecords='0',
                       inferenceCount=str(calls), inferenceWorkerRunCount='0' if workers == 1 else '720',
                       temporalConfig='cpu-i4-j1-d0-sequential' if workers == 1 else
                       'cpu-i1-j1-d0-sequential-w%d-b1' % workers,
                       inferenceWorkScope='run-and-wave-coordination' if workers == 1 else 'run-and-pipeline-coordination',
                       instrumentedCpuScope='nonoverlapping-calling-thread',
                       schedulerCalibrationCount='2' if calibration else 'unavailable',
                       schedulerCalibrationWallMs='25000' if calibration else 'unavailable')
        records = [' '.join(key + '=' + value for key, value in summary.items())]
        records += ['schema=native-inference-stage-v1 stage=' + stage +
                    (' workScope=' + summary['inferenceWorkScope'] + ' samples=' + ('335' if workers == 1 else '167')
                     if stage == 'inference' else '')
                    for stage in VERIFY.PROFILE_EXPECTED_STAGES]
        for name, count in graph_counts.items():
            record = 'schema=native-inference-graph-v2 graph=%s runCount=%d' % (name, count)
            if name.endswith('-time'):
                scope = 'sequential-intervals' if workers == 1 else 'nested-in-inference-pipeline'
                record += ' tensorBindCount=%d packWallScope=%s scatterWallScope=%s' % (15 if workers == 1 else workers, scope, scope)
                if workers > 1:
                    record += ' packProcessCpuScope=unavailable-overlapping-intervals scatterProcessCpuScope=unavailable-overlapping-intervals packProcessCpuMs=unavailable scatterProcessCpuMs=unavailable'
            records.append(record)
        return dict(outputSha256='a' * 64, outputBytes=4586400, finite=True, inferenceCalls=calls, profileRecords=records)

    def valid(self):
        cancellation = [dict(mode=mode, observedNativeWorkers=4, allObservedWorkersRetired=True,
                             ownerRetired=True, noOutputCommitted=True, gateHeldWhileNative=True, gateReleased=True,
                             interruptionReported=True, ownerInterruptPreserved=preserved)
                        for mode, preserved in [('runner-cancel', None), ('owner-interrupt', True)]]
        return dict(schema='lightforge.native-scheduler-calibration.v2', passed=True,
                    samplesPerStem=573300, outputBytes=4586400, startSample=661500, availableProcessors=8,
                    runs=dict(reference=self.run_record(), calibrated=self.run_record(8, True),
                              cached=self.run_record(8), forcedFour=self.run_record(4), recoveredEight=self.run_record(8)),
                    forcedWorkers=[4, 8], forcedTimeBatch=1, cacheReused=True, cacheBytes=116,
                    cancelledCalibrationIsolated=True, duringNativeCancellation=cancellation,
                    finite=True, byteIdentical=True)

    def reject(self, value):
        with self.assertRaises(ValueError):
            VERIFY.verify_scheduler_calibration(value)

    def test_complete_actual_calibration_and_concurrent_retirement_contract(self):
        self.assertEqual(VERIFY.verify_scheduler_calibration(self.valid()), self.valid())

    def test_low_core_cpu_admission_still_requires_explicit_parallel_fixtures(self):
        value = self.valid()
        value['availableProcessors'] = 2
        value['runs']['calibrated'] = self.run_record(1, True)
        value['runs']['calibrated']['profileRecords'][0] = value['runs']['calibrated']['profileRecords'][0].replace(
            'schedulerCalibrationCount=2', 'schedulerCalibrationCount=1')
        value['runs']['cached'] = self.run_record()
        VERIFY.verify_scheduler_calibration(value)
        value['runs']['forcedFour'] = self.run_record()
        self.reject(value)

    def test_complete_per_graph_memory_fallback_is_valid_but_partial_bands_are_not(self):
        value = self.valid()
        for name in ['calibrated', 'cached']:
            run = value['runs'][name]
            run['inferenceCalls'] = 830
            run['profileRecords'][0] = run['profileRecords'][0].replace('inferenceCount=875', 'inferenceCount=830').replace(
                'inferenceWorkerRunCount=720', 'inferenceWorkerRunCount=660')
            run['profileRecords'] = [line.replace('runCount=60', 'runCount=15').replace('tensorBindCount=8', 'tensorBindCount=15')
                                     .replace('nested-in-inference-pipeline', 'sequential-intervals')
                                     if 'graph=block-00-time ' in line else line for line in run['profileRecords']]
            run['profileRecords'] = [line.replace('samples=167', 'samples=181') for line in run['profileRecords']]
        VERIFY.verify_scheduler_calibration(value)
        value['runs']['calibrated']['profileRecords'] = [line.replace('graph=block-00-time runCount=15',
            'graph=block-00-time runCount=14') for line in value['runs']['calibrated']['profileRecords']]
        self.reject(value)

    def test_changed_output_partial_geometry_or_false_success_fails(self):
        mutations = [('samplesPerStem', 573299), ('outputBytes', 4), ('startSample', 0),
                     ('availableProcessors', True), ('forcedWorkers', [8]), ('forcedTimeBatch', 4),
                     ('cacheBytes', 8192), ('cacheReused', False), ('cancelledCalibrationIsolated', False),
                     ('finite', False), ('byteIdentical', False), ('passed', 1)]
        for key, bad in mutations:
            with self.subTest(key=key):
                value = self.valid()
                value[key] = bad
                self.reject(value)
        for name in self.valid()['runs']:
            for key, bad in [('outputSha256', 'b' * 64), ('outputBytes', 4), ('finite', False), ('inferenceCalls', 874)]:
                with self.subTest(run=name, key=key):
                    value = self.valid()
                    value['runs'][name][key] = bad
                    self.reject(value)

    def test_waves_cannot_be_counted_as_calls_or_cached_probes_relabelled(self):
        for before, after in [('inferenceCount=875', 'inferenceCount=96'),
                              ('inferenceWorkerRunCount=720', 'inferenceWorkerRunCount=96'),
                              ('schedulerCalibrationCount=unavailable', 'schedulerCalibrationCount=2'),
                              ('schedulerCalibrationWallMs=unavailable', 'schedulerCalibrationWallMs=25')]:
            value = self.valid()
            value['runs']['cached']['profileRecords'][0] = value['runs']['cached']['profileRecords'][0].replace(before, after)
            self.reject(value)
        value = self.valid()
        records = value['runs']['recoveredEight']['profileRecords']
        records[-1] = records[-2]
        self.reject(value)

    def test_cancellation_must_observe_parallel_jni_and_fully_retire(self):
        for index in range(2):
            for key, bad in [('observedNativeWorkers', 1), ('observedNativeWorkers', 9), ('observedNativeWorkers', True),
                             ('allObservedWorkersRetired', False), ('ownerRetired', False), ('noOutputCommitted', False),
                             ('gateHeldWhileNative', False), ('gateReleased', False), ('interruptionReported', False), ('mode', 'before-run')]:
                with self.subTest(index=index, key=key):
                    value = self.valid()
                    value['duringNativeCancellation'][index][key] = bad
                    self.reject(value)
        value = self.valid()
        value['duringNativeCancellation'][1]['ownerInterruptPreserved'] = False
        self.reject(value)

    def test_persistent_bindings_and_nested_pipeline_scopes_are_not_relabelled(self):
        for before, after in [('tensorBindCount=8', 'tensorBindCount=60'),
                              ('tensorBindCount=8', 'tensorBindCount=4'),
                              ('packWallScope=nested-in-inference-pipeline', 'packWallScope=sequential-intervals'),
                              ('scatterWallScope=nested-in-inference-pipeline', 'scatterWallScope=sequential-intervals'),
                              ('packProcessCpuMs=unavailable', 'packProcessCpuMs=10'),
                              ('scatterProcessCpuScope=unavailable-overlapping-intervals', 'scatterProcessCpuScope=all-app-threads'),
                              ('samples=167', 'samples=251'),
                              ('samples=167', 'samples=875'),
                              ('inferenceWorkScope=run-and-pipeline-coordination', 'inferenceWorkScope=run-and-wave-coordination'),
                              ('instrumentedCpuScope=nonoverlapping-calling-thread', 'instrumentedCpuScope=all-app-threads')]:
            with self.subTest(before=before):
                value = self.valid()
                value['runs']['recoveredEight']['profileRecords'] = [line.replace(before, after)
                    for line in value['runs']['recoveredEight']['profileRecords']]
                self.reject(value)

    def test_absent_or_extra_fields_do_not_become_success(self):
        for value in [None, {}, {**self.valid(), 'unreviewed': True}]:
            self.reject(value)
        for key in self.valid():
            value = self.valid()
            del value[key]
            self.reject(value)
        for name in self.valid()['runs']:
            value = self.valid()
            del value['runs'][name]
            self.reject(value)
        for key in self.valid()['runs']['reference']:
            value = self.valid()
            del value['runs']['reference'][key]
            self.reject(value)
        for key in self.valid()['duringNativeCancellation'][0]:
            value = self.valid()
            del value['duringNativeCancellation'][0][key]
            self.reject(value)


if __name__ == '__main__':
    unittest.main()
