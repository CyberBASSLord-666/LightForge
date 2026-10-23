"""Synthetic falsification fixtures, never host/model/performance evidence.

The experimental lane remains rejected by the normal production build gate.
Every passing observation below is explicitly a unit fixture in a temp folder.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GATE = load('portable_gate_subject', ROOT / 'tools/verify_inference_improvement.py')
BENCH = load('portable_benchmark_subject', ROOT / 'tools/benchmark_deux_parallel.py')
FIXTURE = load('portable_host_fixtures', ROOT / 'tests/test_portable_inference_host.py')
PROFILE = load('portable_profile_fixtures', ROOT / 'tests/test_native_scheduler_evidence.py')


def bind_declaration(record):
    record['protocolDeclaration'] = dict(schema='lightforge.portable-qualification-declaration.v1',
        protocol=GATE.PORTABLE_PROTOCOL, declaredAt=record['createdAt'], scope=GATE.PORTABLE_SCOPE,
        releaseAdmissible=False, geometry=copy.deepcopy(record['geometry']), criteria=copy.deepcopy(record['criteria']),
        maxAllowedThrottleToWallRatio=.05, hostControls=copy.deepcopy(record['hostControls']),
        sourceBindings=copy.deepcopy(record['sourceBindings']), compiledClassHashes=copy.deepcopy(record['compiledClassHashes']))
    text = json.dumps(record['protocolDeclaration'], indent=2) + '\n'
    record['protocolDeclarationSha256'] = hashlib.sha256(text.encode()).hexdigest()
    return text


def child_resource_identity(controls):
    return dict(procCgroup=controls['procCgroup'], cgroupNamespace=controls['namespace']['link'])


def valid_record(**host_options):
    controls, before, after = FIXTURE.valid_observations(**host_options)
    record = dict(schema=GATE.PORTABLE_SCHEMA, protocol=GATE.PORTABLE_PROTOCOL, scope=GATE.PORTABLE_SCOPE,
        passed=True, allOutputsByteIdentical=True, releaseAdmissible=False, eightWorkerSpeedupProven=False,
        androidSpeedupProven=False, wholeAnalysisSpeedupProven=False,
        createdAt='2026-10-23T18:00:00+00:00', finishedAt='2026-10-23T18:10:00+00:00',
        geometry=copy.deepcopy(GATE.PORTABLE_GEOMETRY), criteria=copy.deepcopy(GATE.CRITERIA),
        maxAllowedThrottleToWallRatio=.05, hostControls=controls,
        sourceBindings={name: 'a' * 64 for name in GATE.PORTABLE_SOURCE_PATHS},
        compiledClassHashes={'com/fixture/UnitOnly.class': 'a' * 64}, runs=[])
    record['sourceBindingsAfter'] = copy.deepcopy(record['sourceBindings'])
    record['compiledClassHashesAfter'] = copy.deepcopy(record['compiledClassHashes'])
    for phase, count in [('warmup', 1), ('measurement', 3)]:
        for index in range(count):
            for order, variant in enumerate(('candidate4', 'baseline') if index % 2 else ('baseline', 'candidate4')):
                record['runs'].append(dict(phase=phase, pairIndex=index, orderInPair=order, variant=variant,
                    wallNanos=100000000 if variant == 'baseline' else 75000000,
                    processCpuNanos=200000000, peakRssBytes=1000000000,
                    output=dict(sha256='a' * 64, bytes=4586400, floats=1146600, finite=True),
                    coverage=GATE.portable_coverage(variant), profileSha256='b' * 64,
                    artifacts={key: 'c' * 64 for key in ('logSha256', 'processSha256',
                               'countersBeforeSha256', 'countersAfterSha256')},
                    executionContext=dict(cpuAffinity=controls['childCpuAffinity'].copy(), availableProcessors=3,
                        referenceIntraThreads=3, protocol=GATE.PORTABLE_PROTOCOL, hostVariant=variant,
                        resourceIdentityBefore=child_resource_identity(controls),
                        resourceIdentityAfter=child_resource_identity(controls)),
                    hostCountersBefore=copy.deepcopy(before), hostCountersAfter=copy.deepcopy(after)))
    BENCH.summarize_portable(record, FIXTURE.HOST)
    bind_declaration(record)
    return record


def write_artifacts(directory):
    """Build synthetic files for verifier integrity tests, never run inference."""
    root, work = directory / 'synthetic-repository', directory / 'synthetic-observations'
    record = valid_record()
    for name in GATE.PORTABLE_SOURCE_PATHS:
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
    models = root / 'web/analysis/models/deux'
    models.mkdir(parents=True)
    manifest = dict(frames=1301, samples=573300, files={})
    for graph in sorted(GATE.GRAPH_NAMES):
        path = models / (graph + '.onnx')
        path.write_bytes(b'SYNTHETIC UNIT FIXTURE, NOT A MODEL: ' + graph.encode())
        manifest['files'][path.name] = dict(bytes=path.stat().st_size, sha256=GATE.sha(path))
    (models / 'manifest.json').write_text(json.dumps(manifest))
    audio = root / 'web/demo/glass-castle.wav'
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b'SYNTHETIC UNIT FIXTURE, NOT AUDIO')
    runtime = json.loads((root / 'android/native-runtime.json').read_text())
    record.update(runtime=dict(version='1.25.1', hostJarSha256=runtime['host']['sha256']),
        models=dict(manifestSha256=GATE.sha(models / 'manifest.json'),
                    graphHashes={name: entry['sha256'] for name, entry in manifest['files'].items()}),
        audio=dict(sha256=GATE.sha(audio), startSample=661500), host={'scope': 'synthetic unit fixture only'})
    record['sourceBindings'] = {name: GATE.sha(root / name) for name in GATE.PORTABLE_SOURCE_PATHS}
    record['sourceBindingsAfter'] = copy.deepcopy(record['sourceBindings'])
    for name in record['sourceBindings']:
        snapshot = work / 'source-snapshots' / name
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_bytes((root / name).read_bytes())
    classes = work / 'classes'
    compiled = classes / 'com/fixture/UnitOnly.class'
    compiled.parent.mkdir(parents=True)
    compiled.write_bytes(b'SYNTHETIC UNIT FIXTURE, NOT JAVA BYTECODE')
    record['compiledClassHashes'] = {'com/fixture/UnitOnly.class': GATE.sha(compiled)}
    record['compiledClassHashesAfter'] = copy.deepcopy(record['compiledClassHashes'])
    output_bytes = bytes(4586400)
    for run in record['runs']:
        prefix = run['phase'] + '-' + str(run['pairIndex'])
        destination = work / run['variant']
        destination.mkdir(exist_ok=True)
        output, profile = destination / (prefix + '.f32'), destination / (prefix + '.profile.txt')
        output.write_bytes(output_bytes)
        parallel = run['variant'] == 'candidate4'
        records = PROFILE.SchedulerEvidenceTest().run_record(workers=4 if parallel else 1,
                                                             frequency_parallel=parallel)['profileRecords']
        records[0] = records[0].replace('cpu-i4-j1-d0-sequential', 'cpu-i3-j1-d0-sequential')
        records[0] += ' inferenceWallMs=1 modelInitWallMs=1'
        profile.write_text('\n'.join(records) + '\n')
        run['output']['sha256'] = GATE.sha(output)
        run['profileSha256'] = GATE.sha(profile)
        child = dict(wallNanos=run['wallNanos'], processCpuNanos=run['processCpuNanos'],
            peakRssBytes=run['peakRssBytes'], cpuAffinityList='0-2', availableProcessors=3,
            referenceIntraThreads=3, protocol=GATE.PORTABLE_PROTOCOL, hostVariant=run['variant'],
            resourceIdentityBefore=copy.deepcopy(run['executionContext']['resourceIdentityBefore']),
            resourceIdentityAfter=copy.deepcopy(run['executionContext']['resourceIdentityAfter']))
        stdout, stderr = json.dumps(child) + '\n', 'Synthetic unit fixture diagnostic stderr.\n'
        artifact_text = dict(logSha256=stdout + stderr,
            processSha256=json.dumps(dict(returncode=0, stdout=stdout, stderr=stderr)),
            countersBeforeSha256=json.dumps(run['hostCountersBefore']),
            countersAfterSha256=json.dumps(run['hostCountersAfter']))
        for key, suffix in (('logSha256', '.log'), ('processSha256', '.process.json'),
                            ('countersBeforeSha256', '.resources-before.json'),
                            ('countersAfterSha256', '.resources-after.json')):
            artifact = destination / (prefix + suffix)
            artifact.write_text(artifact_text[key])
            run['artifacts'][key] = GATE.sha(artifact)
    (work / 'protocol.json').write_text(bind_declaration(record))
    receipt = work / 'receipt.json'
    receipt.write_text(json.dumps(record))
    return root, work, record


class PortableQualificationTest(unittest.TestCase):
    def test_independent_contract_constants_match(self):
        for key in ('PORTABLE_PROTOCOL', 'PORTABLE_SCHEMA', 'PORTABLE_SOURCE_PATHS', 'PORTABLE_GEOMETRY',
                    'PORTABLE_SCOPE', 'CRITERIA'):
            self.assertEqual(getattr(GATE, key), getattr(BENCH, key))
        self.assertEqual(GATE.portable_coverage('baseline')['inferenceCalls'], 335)
        self.assertEqual(GATE.portable_coverage('candidate4')['inferenceCalls'], 1727)
        for variant in ('baseline', 'candidate4'):
            self.assertEqual(GATE.portable_coverage(variant)['graphRunCounts']['head-0'], 11)
            self.assertEqual(GATE.portable_coverage(variant)['graphRunCounts']['head-1'], 11)

    def test_valid_finite_and_explicit_unlimited_profiles(self):
        for quota in ('400000 100000\n', 'max 100000\n'):
            self.assertEqual(GATE.validate_portable_measurements(valid_record(quota=quota)), 25.)

    def test_every_changed_claim_clock_geometry_or_pair_fails(self):
        transformations = [
            lambda r: r.update(schema='lightforge.production-parallel-qualification.v3'),
            lambda r: r.update(protocol='auto-select-fastest'),
            lambda r: r.update(scope='production acceleration'),
            lambda r: r.update(releaseAdmissible=True),
            lambda r: r.update(eightWorkerSpeedupProven=True),
            lambda r: r.update(androidSpeedupProven=True),
            lambda r: r.update(wholeAnalysisSpeedupProven=True),
            lambda r: r.update(passed=1),
            lambda r: r['geometry']['candidate4'].update(workers=8),
            lambda r: r['geometry']['baseline'].update(workers=True),
            lambda r: r['geometry'].update(frames=512),
            lambda r: r['criteria'].update(measuredPairs=2),
            lambda r: r.update(maxAllowedThrottleToWallRatio=.06),
            lambda r: r['runs'].pop(),
            lambda r: r['runs'][3].update(variant='candidate'),
            lambda r: r['runs'][3].update(orderInPair=0),
            lambda r: r['runs'][0].update(pairIndex=False),
            lambda r: r['runs'][3].update(wallNanos=0),
            lambda r: r['runs'][3].update(processCpuNanos=-1),
            lambda r: r['runs'][3].update(peakRssBytes=True),
            lambda r: r['runs'][3]['output'].update(sha256='c' * 64),
            lambda r: r['runs'][3]['output'].update(bytes=4),
            lambda r: r['runs'][3]['output'].update(finite=False),
            lambda r: r['runs'][3].pop('artifacts'),
            lambda r: r['runs'][3]['coverage']['graphRunCounts'].update({'head-0': 82}),
            lambda r: r['runs'][3]['coverage']['schedulerConfigurations'].update(temporalConfig='cpu-i1-j1-d0-sequential-w8-b1'),
            lambda r: r['runs'][3]['executionContext'].update(referenceIntraThreads=4),
            lambda r: r['runs'][3]['executionContext'].update(availableProcessors=7),
            lambda r: r['runs'][3]['executionContext'].update(cpuAffinity=[1, 2, 3]),
            lambda r: r['runs'][3]['executionContext'].update(protocol='production-v3'),
            lambda r: r.update(finishedAt='2026-10-23T17:00:00+00:00'),
            lambda r: r['protocolDeclaration'].update(declaredAt='2026-10-23T18:09:00+00:00'),
            lambda r: r.update(compiledClassHashesAfter={'changed.class': 'a' * 64}),
            lambda r: r['sourceBindingsAfter'].pop('tools/portable_inference_host.py'),
            lambda r: r['sourceBindings'].pop('tools/verify_inference_improvement.py'),
        ]
        for number, change in enumerate(transformations):
            with self.subTest(case=number):
                record = valid_record()
                change(record)
                with self.assertRaises((ValueError, KeyError)):
                    GATE.validate_portable_measurements(record)

    def test_actual_child_ancestry_must_match_parent_before_and_after(self):
        for phase in ('resourceIdentityBefore', 'resourceIdentityAfter'):
            for mutation in (lambda context, p: context.pop(p),
                             lambda context, p: context.update({p: None}),
                             lambda context, p: context[p].update(procCgroup='0::/job/nested-child\n'),
                             lambda context, p: context[p].update(procCgroup='0::/unobserved-sibling\n'),
                             lambda context, p: context[p].update(cgroupNamespace='cgroup:[12345678]'),
                             lambda context, p: context[p].pop('procCgroup')):
                with self.subTest(phase=phase, mutation=mutation):
                    record = valid_record()
                    mutation(record['runs'][3]['executionContext'], phase)
                    with self.assertRaisesRegex(ValueError, 'JVM execution'):
                        GATE.validate_portable_measurements(record)

    def test_one_slow_pair_cannot_hide_behind_good_median(self):
        record = valid_record()
        record['runs'][3]['wallNanos'] = 97000000
        BENCH.summarize_portable(record, FIXTURE.HOST)
        self.assertFalse(record['passed'])
        record['passed'] = True
        with self.assertRaisesRegex(ValueError, 'five-percent'):
            GATE.validate_portable_measurements(record)

    def test_wrong_summary_or_prospective_declaration_fails(self):
        for change in (lambda r: r.update(medianWallReductionPercent=75),
                       lambda r: r['medians']['baseline'].update(wallNanos=300000000),
                       lambda r: r['pairedReductions'][1].update(wallReductionPercent=50),
                       lambda r: r['resourcePairs'].pop(),
                       lambda r: r['protocolDeclaration']['compiledClassHashes'].update({'unexpected.class': 'a' * 64})):
            record = valid_record()
            change(record)
            with self.assertRaises(ValueError):
                GATE.validate_portable_measurements(record)

    def test_pressure_throttle_and_unknown_observations_never_default_to_zero(self):
        for filename, key, value in (('cpu.stat', 'throttled_usec', 100000),
                                     ('memory.events', 'oom_kill', 1), ('memory.events', 'high', 1),
                                     ('memory.stat', 'pgscan_direct', 1), ('memory.pressure', 'some', 101)):
            with self.subTest(filename=filename, key=key):
                record = valid_record()
                FIXTURE.change_counter(record['runs'][3]['hostCountersAfter'], -1, filename, key, value)
                with self.assertRaises(ValueError):
                    GATE.validate_portable_measurements(record)
        record = valid_record()
        del record['runs'][3]['hostCountersBefore']['ancestors'][-1]['raw']['cpu.stat']
        with self.assertRaises(ValueError):
            GATE.validate_portable_measurements(record)

    def test_default_production_gate_rejects_even_passing_portable_evidence(self):
        record = valid_record()
        with self.assertRaisesRegex(ValueError, 'Unknown inference evidence schema'):
            GATE.validate_measurements(record)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / GATE.RECEIPT
            receipt.parent.mkdir(parents=True)
            receipt.write_text(json.dumps(record))
            result = subprocess.run([sys.executable, str(ROOT / 'tools/verify_inference_improvement.py'),
                                     '--root', str(root)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Release held: Unknown inference evidence schema', result.stderr)

    def test_portable_selection_is_explicit_without_fallback_or_receipt_export(self):
        source = (ROOT / 'tools/benchmark_deux_parallel.py').read_text()
        self.assertIn('default=LEGACY_PROTOCOL', source)
        with tempfile.TemporaryDirectory() as directory:
            args = type('Args', (), {'receipt': Path(directory) / 'forbidden.json',
                                     'output': Path(directory) / 'observations'})()
            with mock.patch.object(BENCH, 'portable_host') as host:
                with self.assertRaisesRegex(ValueError, 'legacy-only'):
                    BENCH.run_portable(args)
                host.assert_not_called()
            self.assertFalse(args.receipt.exists())

    def test_child_command_does_not_spoof_processors_and_requires_observed_metadata(self):
        controls, before, after = FIXTURE.valid_observations()
        host = SimpleNamespace(validate_controls=FIXTURE.HOST.validate_controls,
            observe_controls=lambda: copy.deepcopy(controls),
            observe_counters=lambda _: copy.deepcopy(before))
        observation = dict(wallNanos=75000000, processCpuNanos=200000000, peakRssBytes=1000000000,
            cpuAffinityList='0-2', availableProcessors=3, protocol=GATE.PORTABLE_PROTOCOL,
            hostVariant='candidate4', referenceIntraThreads=3,
            resourceIdentityBefore=child_resource_identity(controls),
            resourceIdentityAfter=child_resource_identity(controls))
        calls = []

        def run(command, **options):
            calls.append(command)
            self.assertEqual(command[-2:], ['candidate4', GATE.PORTABLE_PROTOCOL])
            self.assertFalse(any('ActiveProcessorCount' in argument for argument in command))
            self.assertIn('preexec_fn', options)
            Path(command[-5]).write_bytes(bytes(4586400))
            records = PROFILE.SchedulerEvidenceTest().run_record(workers=4, frequency_parallel=True)['profileRecords']
            records[0] += ' inferenceWallMs=1 modelInitWallMs=1'
            Path(command[-3]).write_text('\n'.join(records) + '\n')
            return SimpleNamespace(returncode=0, stdout=json.dumps(observation) + '\n', stderr='')

        original_observation = copy.deepcopy(observation)
        mutations = (None, lambda o: o.update(availableProcessors=7),
                     lambda o: o['resourceIdentityBefore'].update(procCgroup='0::/different\n'),
                     lambda o: o['resourceIdentityAfter'].update(procCgroup='0::/job/nested\n'),
                     lambda o: o['resourceIdentityAfter'].update(cgroupNamespace='cgroup:[12345]'),
                     lambda o: o.pop('resourceIdentityBefore'))
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                observation = copy.deepcopy(original_observation)
                if mutation:
                    mutation(observation)
                args = ('candidate4', 0, 1, 'warmup', Path('/unit/classes'), Path(directory),
                        Path('/unit/java'), [], Path('/unit/models'), Path('/unit/audio'), controls)
                if mutation:
                    with self.assertRaisesRegex(ValueError, 'Observed portable JVM|Invalid portable resource'):
                        BENCH.measure_portable(*args, host=host, run_process=run)
                else:
                    result = BENCH.measure_portable(*args, host=host, run_process=run)
                    self.assertEqual(result['coverage'], GATE.portable_coverage('candidate4'))
                    self.assertEqual(result['executionContext']['referenceIntraThreads'], 3)
                    self.assertTrue((Path(directory) / 'candidate4/warmup-0.resources-before.json').is_file())
        self.assertEqual(len(calls), len(mutations))

    def test_changed_host_or_undeclared_candidate_stops_before_launch(self):
        controls, _, _ = FIXTURE.valid_observations()
        host = SimpleNamespace(validate_controls=FIXTURE.HOST.validate_controls, observe_controls=lambda: {})
        with tempfile.TemporaryDirectory() as directory:
            process = mock.Mock()
            for variant in ('candidate4', 'candidate'):
                with self.subTest(variant=variant), self.assertRaises(ValueError):
                    BENCH.measure_portable(variant, 0, 1, 'warmup', Path('/unit/classes'), Path(directory),
                        Path('/unit/java'), [], Path('/unit/models'), Path('/unit/audio'), controls,
                        host=host, run_process=process)
            process.assert_not_called()

    def test_retained_artifacts_replay_and_every_modified_binding_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root, work, record = write_artifacts(Path(directory))
            self.assertEqual(GATE.verify_portable(work / 'receipt.json', root), 25.)
            targets = [root / 'android/src/com/cyberbasslord/lightforge/NativeDeux.java',
                       work / 'source-snapshots/tools/portable_inference_host.py',
                       work / 'classes/com/fixture/UnitOnly.class', work / 'protocol.json',
                       root / 'web/analysis/models/deux/front.onnx', root / 'web/demo/glass-castle.wav',
                       work / 'candidate4/measurement-0.f32', work / 'candidate4/measurement-0.profile.txt',
                       *[work / ('candidate4/measurement-0' + suffix) for suffix in
                         ('.log', '.process.json', '.resources-before.json', '.resources-after.json')]]
            for path in targets:
                with self.subTest(path=path.relative_to(Path(directory))):
                    original = path.read_bytes()
                    path.write_bytes(original + b'corrupt')
                    try:
                        with self.assertRaises(ValueError):
                            GATE.verify_portable(work / 'receipt.json', root)
                    finally:
                        path.write_bytes(original)
            for suffix in ('.log', '.process.json', '.resources-before.json', '.resources-after.json'):
                path = work / ('candidate4/measurement-0' + suffix)
                original = path.read_bytes()
                path.unlink()
                try:
                    with self.assertRaisesRegex(ValueError, 'raw observation'):
                        GATE.verify_portable(work / 'receipt.json', root)
                finally:
                    path.write_bytes(original)
            (work / 'classes/unexpected.class').write_bytes(b'unexpected')
            with self.assertRaisesRegex(ValueError, 'compiled classes'):
                GATE.verify_portable(work / 'receipt.json', root)

    def test_self_consistent_receipt_cannot_override_retained_child_or_counter_observations(self):
        with tempfile.TemporaryDirectory() as directory:
            root, work, original = write_artifacts(Path(directory))
            changed = copy.deepcopy(original)
            changed['runs'][3]['wallNanos'] = 70000000
            BENCH.summarize_portable(changed, FIXTURE.HOST)
            (work / 'receipt.json').write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, 'retained child observation'):
                GATE.verify_portable(work / 'receipt.json', root)
            changed = copy.deepcopy(original)
            FIXTURE.change_counter(changed['runs'][3]['hostCountersAfter'], -1, 'cpu.stat', 'usage_usec', 1001)
            BENCH.summarize_portable(changed, FIXTURE.HOST)
            (work / 'receipt.json').write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, 'resource counters conflict'):
                GATE.verify_portable(work / 'receipt.json', root)

    def test_retained_child_ancestry_cannot_conflict_with_valid_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root, work, original = write_artifacts(Path(directory))
            for phase in ('resourceIdentityBefore', 'resourceIdentityAfter'):
                changed = copy.deepcopy(original)
                run = changed['runs'][3]
                process_path = work / 'candidate4/measurement-0.process.json'
                log_path = work / 'candidate4/measurement-0.log'
                previous_process, previous_log = process_path.read_bytes(), log_path.read_bytes()
                try:
                    process = json.loads(previous_process)
                    child = json.loads(process['stdout'].strip().splitlines()[-1])
                    child[phase]['procCgroup'] = '0::/unobserved-child\n'
                    process['stdout'] = json.dumps(child) + '\n'
                    process_path.write_text(json.dumps(process))
                    log_path.write_text(process['stdout'] + process['stderr'])
                    run['artifacts']['processSha256'] = GATE.sha(process_path)
                    run['artifacts']['logSha256'] = GATE.sha(log_path)
                    (work / 'receipt.json').write_text(json.dumps(changed))
                    with self.subTest(phase=phase), self.assertRaisesRegex(ValueError, 'retained child observation'):
                        GATE.verify_portable(work / 'receipt.json', root)
                finally:
                    process_path.write_bytes(previous_process)
                    log_path.write_bytes(previous_log)

    def test_actual_profile_slot_and_reference_configuration_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            _, work, _ = write_artifacts(Path(directory))
            profile = work / 'candidate4/measurement-0.profile.txt'
            self.assertEqual(BENCH.portable_profile(profile, 'candidate4'), GATE.portable_coverage('candidate4'))
            original = profile.read_text()
            for old, new in (('tensorBindCount=4', 'tensorBindCount=8'),
                             ('tensorBindCount=5', 'tensorBindCount=9'),
                             ('-w4-b16', '-w8-b16')):
                profile.write_text(original.replace(old, new))
                with self.assertRaises(ValueError):
                    BENCH.portable_profile(profile, 'candidate4')
            baseline = work / 'baseline/measurement-0.profile.txt'
            baseline.write_text(baseline.read_text().replace('cpu-i3-j1-d0-sequential', 'cpu-i4-j1-d0-sequential'))
            with self.assertRaisesRegex(ValueError, 'declared reference'):
                BENCH.portable_profile(baseline, 'baseline')


if __name__ == '__main__':
    unittest.main()
