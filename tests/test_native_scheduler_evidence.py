"""Release admission rejects unqualified work, partial graphs and unsafe JNI retirement."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('scheduler_release', ROOT / 'qa/release-2.4.1/verify-analysis.py')
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


class SchedulerEvidenceTest(unittest.TestCase):
    def run_record(self, workers=1, policy=False):
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
                       schedulerCalibrationCount='unavailable', schedulerCalibrationWallMs='unavailable')
        policy_record = ('schema=native-passage-policy-v1 state=provisional workers=0 reason=unmeasured '
                         'extraNanos=0 extraCapNanos=360000000000 projectedAccruedSavingsNanos=0 qualificationPairs=0 currentJobPairs=0 '
                         'seeded=false activePassages=0 leasePassages=8 paybackScope=projected-not-measured')
        if policy:
            summary['passagePolicy'] = policy_record.replace(' ', ',')
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
        if policy:
            records.append(policy_record)
        return dict(outputSha256='a' * 64, outputBytes=4586400, finite=True, inferenceCalls=calls, profileRecords=records)

    def valid(self):
        cancellation = [dict(mode=mode, observedNativeWorkers=4, allObservedWorkersRetired=True,
                             ownerRetired=True, noOutputCommitted=True, gateHeldWhileNative=True, gateReleased=True,
                             interruptionReported=True, ownerInterruptPreserved=preserved)
                        for mode, preserved in [('runner-cancel', None), ('owner-interrupt', True)]]
        automatic = self.run_record()
        header = ('schema=native-passage-policy-v1 state=provisional workers=8 reason=qualification-pending '
                  'extraNanos=50000000000 extraCapNanos=360000000000 projectedAccruedSavingsNanos=0 qualificationPairs=1 currentJobPairs=1 '
                  'seeded=false activePassages=0 leasePassages=8 paybackScope=projected-not-measured')
        pair = ('schema=native-passage-pair-v1 role=qualification index=0 ordinal=0 candidateFirst=false workers=8 '
                'baselineNanos=60000000000 candidateNanos=40000000000 extraNanos=41000000000 outputSha256=' + 'a' * 64 +
                ' finite=true exact=true fullGeometry=true coldSessions=true')
        automatic['profileRecords'][0] = automatic['profileRecords'][0].replace('schedulerCalibrationCount=unavailable',
            'schedulerCalibrationCount=2').replace('schedulerCalibrationWallMs=unavailable', 'schedulerCalibrationWallMs=50000')
        automatic['profileRecords'][0] += ' passagePolicy=' + '|'.join(row.replace(' ', ',') for row in [header, pair])
        automatic['profileRecords'] += [header, pair]
        return dict(schema='lightforge.native-scheduler-calibration.v3', passed=True,
                    samplesPerStem=573300, outputBytes=4586400, startSample=661500, availableProcessors=8,
                    runs=dict(reference=self.run_record(), unknownWork=self.run_record(1, True),
                              shortWork=self.run_record(1, True), automaticFirstPassage=automatic,
                              forcedFour=self.run_record(4), recoveredEight=self.run_record(8)),
                    forcedWorkers=[4, 8], forcedTimeBatch=1, unknownWorkNoProbe=True, shortWorkNoProbe=True,
                    legacyPolicyIgnored=True, legacyCacheFixture='synthetic-v2-warmgraph', legacyCacheBytes=116,
                    automaticRemainingUseful=35, automaticPairObserved=True, automaticCacheNotQualified=True,
                    cancelledPassageIsolated=True, noPartialOutputs=True, duringNativeCancellation=cancellation,
                    finite=True, byteIdentical=True)

    def reject(self, value):
        with self.assertRaises(ValueError):
            VERIFY.verify_scheduler_calibration(value)

    def test_complete_unfunded_work_and_concurrent_retirement_contract(self):
        self.assertEqual(VERIFY.verify_scheduler_calibration(self.valid()), self.valid())

    def test_captured_current_original_graph_result_matches_the_contract(self):
        path = ROOT / 'research/inference-device-regression-20260928/native-passage-integration.raw.json'
        observed = json.loads(path.read_text())
        self.assertEqual(VERIFY.verify_scheduler_calibration(observed), observed)
        self.assertTrue(observed['automaticPairObserved'])
        for name in ['unknownWork', 'shortWork', 'automaticFirstPassage']:
            value = json.loads(path.read_text())
            value['runs'][name]['profileRecords'] = [line.replace('projectedAccruedSavingsNanos=0',
                'projectedAccruedSavingsNanos=1') for line in value['runs'][name]['profileRecords']]
            self.reject(value)

    def test_unqualified_work_cannot_claim_projected_accrued_savings(self):
        for name in ['unknownWork', 'shortWork', 'automaticFirstPassage']:
            for replacement in ['projectedAccruedSavingsNanos=1', '', 'projectedAccruedSavingsNanos=0 projectedAccruedSavingsNanos=0']:
                value = self.valid()
                value['runs'][name]['profileRecords'] = [line.replace('projectedAccruedSavingsNanos=0', replacement)
                    for line in value['runs'][name]['profileRecords']]
                self.reject(value)

    def test_low_core_cpu_admission_still_requires_explicit_parallel_fixtures(self):
        value = self.valid()
        value['availableProcessors'] = 2
        VERIFY.verify_scheduler_calibration(value)
        value['runs']['forcedFour'] = self.run_record()
        self.reject(value)

    def test_unknown_work_cannot_admit_parallel_and_partial_bands_are_rejected(self):
        for name in ['unknownWork', 'shortWork']:
            value = self.valid()
            value['runs'][name] = self.run_record(8, True)
            self.reject(value)
        value = self.valid()
        value['runs']['unknownWork']['profileRecords'] = [line.replace('graph=block-00-time runCount=15',
            'graph=block-00-time runCount=14') for line in value['runs']['unknownWork']['profileRecords']]
        self.reject(value)

    def test_changed_output_partial_geometry_or_false_success_fails(self):
        mutations = [('samplesPerStem', 573299), ('outputBytes', 4), ('startSample', 0),
                     ('availableProcessors', True), ('forcedWorkers', [8]), ('forcedTimeBatch', 4),
                     ('legacyCacheBytes', 8192), ('legacyCacheFixture', 'measured-passage'),
                     ('legacyPolicyIgnored', False), ('unknownWorkNoProbe', False), ('shortWorkNoProbe', False),
                     ('cancelledPassageIsolated', False), ('noPartialOutputs', False),
                     ('automaticRemainingUseful', 34), ('automaticPairObserved', 1), ('automaticCacheNotQualified', False),
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

    def test_waves_cannot_be_counted_as_calls_or_probes_relabelled(self):
        for before, after in [('inferenceCount=875', 'inferenceCount=96'),
                              ('inferenceWorkerRunCount=720', 'inferenceWorkerRunCount=96'),
                              ('schedulerCalibrationCount=unavailable', 'schedulerCalibrationCount=2'),
                              ('schedulerCalibrationWallMs=unavailable', 'schedulerCalibrationWallMs=25')]:
            value = self.valid()
            name = 'recoveredEight' if before.startswith('inference') else 'unknownWork'
            value['runs'][name]['profileRecords'][0] = value['runs'][name]['profileRecords'][0].replace(before, after)
            self.reject(value)
        value = self.valid()
        records = value['runs']['recoveredEight']['profileRecords']
        records[-1] = records[-2]
        self.reject(value)

    def test_controller_evidence_must_be_unfunded_complete_and_durably_bound(self):
        for before, after in [('extraNanos=0', 'extraNanos=1'), ('workers=0', 'workers=4'),
                              ('qualificationPairs=0', 'qualificationPairs=1'),
                              ('currentJobPairs=0', 'currentJobPairs=1'), ('seeded=false', 'seeded=true'),
                              ('state=provisional', 'state=qualified'), ('reason=unmeasured', 'reason=arbitrary')]:
            value = self.valid()
            value['runs']['unknownWork']['profileRecords'][-1] = value['runs']['unknownWork']['profileRecords'][-1].replace(before, after)
            self.reject(value)
        value = self.valid()
        value['runs']['unknownWork']['profileRecords'][-1] += ' extraNanos=0'
        self.reject(value)

    def test_automatic_pair_preserves_timing_output_geometry_budget_and_evidence(self):
        for before, after in [('coldSessions=true', 'coldSessions=false'), ('finite=true', 'finite=false'),
                              ('exact=true', 'exact=false'), ('fullGeometry=true', 'fullGeometry=false'),
                              ('ordinal=0', 'ordinal=1'), ('candidateFirst=false', 'candidateFirst=true'),
                              ('candidateNanos=40000000000', 'candidateNanos=0'),
                              ('extraNanos=41000000000', 'extraNanos=999999999999'),
                              ('outputSha256=' + 'a' * 64, 'outputSha256=' + 'b' * 64)]:
            value = self.valid()
            rows = value['runs']['automaticFirstPassage']['profileRecords']
            rows[-1] = rows[-1].replace(before, after)
            self.reject(value)
        for before, after in [('extraNanos=50000000000', 'extraNanos=360000000001'),
                              ('state=provisional', 'state=qualified'), ('qualificationPairs=1', 'qualificationPairs=3')]:
            value = self.valid()
            rows = value['runs']['automaticFirstPassage']['profileRecords']
            rows[-2] = rows[-2].replace(before, after)
            self.reject(value)

    def test_automatic_decline_does_not_claim_an_unobserved_pair(self):
        value = self.valid()
        value['automaticPairObserved'] = False
        rows = value['runs']['automaticFirstPassage']['profileRecords']
        rows.pop()
        rows[-1] = rows[-1].replace('workers=8', 'workers=0').replace('reason=qualification-pending', 'reason=screen-no-win').replace(
            'qualificationPairs=1', 'qualificationPairs=0').replace('currentJobPairs=1', 'currentJobPairs=0')
        rows[0] = rows[0].split(' passagePolicy=')[0].replace('schedulerCalibrationCount=2', 'schedulerCalibrationCount=1')
        rows[0] += ' passagePolicy=' + rows[-1].replace(' ', ',')
        VERIFY.verify_scheduler_calibration(value)
        value['automaticPairObserved'] = True
        self.reject(value)
        value = self.valid()
        value['runs']['unknownWork']['profileRecords'][0] = value['runs']['unknownWork']['profileRecords'][0].split(' passagePolicy=')[0]
        self.reject(value)
        value = self.valid()
        value['runs']['unknownWork']['profileRecords'].append(value['runs']['unknownWork']['profileRecords'][-1])
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
