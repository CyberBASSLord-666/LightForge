"""Synthetic bounded proof falsification, never real host or model evidence."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import traceback
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


P = load('bounded_portable_fixtures', ROOT / 'tests/test_portable_inference_qualification.py')
G, B = P.GATE, P.BENCH
C = load('bounded_campaign_subject', ROOT / 'tools/host_inference_campaign.py')


def fixture(directory):
    root, work, record = P.write_artifacts(directory)
    policy = json.loads((ROOT / C.POLICY_PATH).read_text())
    for name in policy['executionClosurePaths']:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        original = ROOT / name
        if not original.is_file() and name == 'qa/release-2.4.2/verify-analysis.py':
            original = ROOT / G.CURRENT_ANALYSIS_VERIFIER
        target.write_bytes(original.read_bytes())
    (root / 'version.json').write_text('{"name":"2.4.2","code":20402}\n')
    record.update(schema=G.BOUNDED_SCHEMA, protocol=G.BOUNDED_PROTOCOL, scope=G.BOUNDED_SCOPE,
                  campaignState='terminal-pass', campaignId=policy['campaignId'],
                  measurementStartedAt='2026-10-23T18:02:00+00:00', pairOrder=B.bounded_pair_order(),
                  childProtocol=copy.deepcopy(policy['childProtocol']))
    record['host'] = dict(platform='Linux synthetic-unit-only', machine='x86_64', cpuCount=4,
                          cpuAffinity=[0, 1, 2, 3], cpuQuota=None, memoryLimit=None, cpuModel='SYNTHETIC UNIT FIXTURE')
    record['sourceBindings'] = {name: G.sha(root / name) for name in policy['sourcePaths']}
    record['sourceBindingsAfter'] = copy.deepcopy(record['sourceBindings'])
    for name in record['sourceBindings']:
        target = work / 'source-snapshots' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / name).read_bytes())
    record['runtimeBindings'] = dict(schema='lightforge.host-runtime-bindings.v1',
        childEnvironment=copy.deepcopy(B.BOUNDED_CHILD_ENV), jdkSymlinks={},
        jdkFiles={name: 'a' * 64 for name in ('bin/java', 'bin/javac', 'lib/modules', 'lib/server/libjvm.so', 'release')},
        dependencyFiles={'test-json.jar': 'b' * 64, 'android.jar': 'c' * 64,
                         'onnxruntime-1.25.1.jar': record['runtime']['hostJarSha256']})
    record['protocolDeclaration'].update(schema='lightforge.bounded-host-protocol-declaration.v1',
        protocol=G.BOUNDED_PROTOCOL, scope=G.BOUNDED_SCOPE, sourceBindings=record['sourceBindings'])
    (work / 'protocol.json').write_text(json.dumps(record['protocolDeclaration'], indent=2) + '\n')
    record['protocolDeclarationSha256'] = G.sha(work / 'protocol.json')
    for run in record['runs']:
        run['executionContext']['protocol'] = G.BOUNDED_PROTOCOL
        prefix = work / run['variant'] / (run['phase'] + '-' + str(run['pairIndex']))
        process = json.loads(prefix.with_suffix('.process.json').read_text())
        lines = process['stdout'].splitlines()
        child = json.loads(lines[-1])
        child['protocol'] = G.BOUNDED_PROTOCOL
        lines[-1] = json.dumps(child)
        process['stdout'] = '\n'.join(lines) + '\n'
        prefix.with_suffix('.process.json').write_text(json.dumps(process))
        prefix.with_suffix('.log').write_text(process['stdout'] + process['stderr'])
        run['artifacts']['logSha256'] = G.sha(prefix.with_suffix('.log'))
        run['artifacts']['processSha256'] = G.sha(prefix.with_suffix('.process.json'))
    producer = dict(runId=123, runAttempt=1, headSha='1' * 40, event=policy['producerEvents'][0],
                    headBranch='main', workflowPath=policy['workflowPath'])
    declaration = C.create_declaration(root, record, producer)
    record['campaignDeclaration'] = declaration
    (work / 'declaration.json').write_bytes(C.canonical_bytes(declaration))
    record['campaignDeclarationSha256'] = G.sha(work / 'declaration.json')
    record['registrationCheck'] = dict(purpose='producer', measurementAuthorized=True, checkedAt='2026-10-23T18:01:00+00:00')
    (work / 'registration-check.json').write_text(json.dumps(record['registrationCheck']))
    (work / 'measurement-started.json').write_text(json.dumps(dict(campaignId=record['campaignId'],
        startedAt=record['measurementStartedAt'], declarationSha256=record['campaignDeclarationSha256'])))
    (work / 'receipt.json').write_text(json.dumps(record))
    return root, work, record


class BoundedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root, self.work, self.record = fixture(Path(self.tmp.name))

    def replay(self, record=None):
        if record is not None:
            (self.work / 'receipt.json').write_text(json.dumps(record))
        return G.verify_bounded(self.work / 'receipt.json', self.root)

    def test_complete_local_replay_is_not_campaign_admission(self):
        self.assertEqual(self.replay(), 25.)
        target = self.root / G.RECEIPT
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(self.record))
        with self.assertRaisesRegex(ValueError, 'Unknown inference evidence schema'):
            G.verify(self.root)

    def test_old_experimental_cannot_be_relabelled(self):
        for field, value in [('schema', G.PORTABLE_SCHEMA), ('protocol', G.PORTABLE_PROTOCOL),
                             ('scope', G.PORTABLE_SCOPE), ('campaignState', 'terminal-failure')]:
            changed = copy.deepcopy(self.record)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.replay(changed)
        changed = copy.deepcopy(self.record)
        changed['runs'][0]['executionContext']['protocol'] = G.PORTABLE_PROTOCOL
        with self.assertRaisesRegex(ValueError, 'Observed portable JVM'):
            self.replay(changed)

    def test_all_original_thresholds_and_resource_gates_still_fail_closed(self):
        mutations = [lambda r: r['criteria'].update(minMedianWallReductionPercent=14),
            lambda r: r['criteria'].update(minEachPairWallReductionPercent=4),
            lambda r: r['geometry']['candidate4'].update(workers=8),
            lambda r: r['geometry'].update(frames=512), lambda r: r['runs'].pop(),
            lambda r: r['runs'][2]['output'].update(sha256='f' * 64),
            lambda r: r['runs'][2].update(hostCountersAfter={}),
            lambda r: r.update(releaseAdmissible=True), lambda r: r.update(androidSpeedupProven=True)]
        for index, change in enumerate(mutations):
            record = copy.deepcopy(self.record)
            change(record)
            with self.subTest(index=index), self.assertRaises((ValueError, KeyError)):
                self.replay(record)

    def test_declaration_marker_environment_and_raw_data_mutations_rejected(self):
        for relative in ('declaration.json', 'registration-check.json', 'measurement-started.json',
                         'baseline/measurement-0.log', 'candidate4/measurement-2.resources-after.json'):
            path = self.work / relative
            original = path.read_bytes()
            path.write_bytes(b'{}')
            with self.subTest(relative=relative), self.assertRaises((ValueError, KeyError)):
                self.replay(self.record)
            path.write_bytes(original)
        changed = copy.deepcopy(self.record)
        changed['runtimeBindings']['childEnvironment']['JAVA_TOOL_OPTIONS'] = '-Xint'
        with self.assertRaises(ValueError):
            self.replay(changed)
        changed = copy.deepcopy(self.record)
        changed['host']['cpuModel'] = 'DIFFERENT SYNTHETIC HOST'
        with self.assertRaisesRegex(ValueError, 'declared experiment'):
            self.replay(changed)
        changed = copy.deepcopy(self.record)
        changed['measurementStartedAt'] = '2026-10-23T17:00:00+00:00'
        with self.assertRaises(ValueError):
            self.replay(changed)

    def test_current_version_and_execution_closure_drift_rejected(self):
        for name in ('version.json', '.github/workflows/verify-v2.yml', 'tools/bootstrap_toolchain.py'):
            path = self.root / name
            original = path.read_bytes()
            path.write_bytes(original + b'\n')
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.replay()
            path.write_bytes(original)

    def test_duplicate_and_nonfinite_json_are_rejected(self):
        path = self.work / 'bad.json'
        for data in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}'):
            path.write_text(data)
            with self.assertRaises(ValueError):
                G.read_bounded_json(path)

    def test_unregistered_execution_never_calls_inference(self):
        record = copy.deepcopy(self.record)
        record.update(campaignState='declared-not-measured', runs=[])
        (self.work / 'receipt.json').write_text(json.dumps(record))
        (self.work / 'measurement-started.json').unlink()
        helper = SimpleNamespace(check_online_admission=mock.Mock(side_effect=ValueError('unregistered')))
        with mock.patch.object(B, 'campaign_module', return_value=helper), mock.patch.object(B, 'measure_portable') as measure:
            with self.assertRaisesRegex(ValueError, 'unregistered'):
                B.execute_bounded(SimpleNamespace(output=self.work))
            measure.assert_not_called()

    def test_repeated_execution_cannot_start_again(self):
        with mock.patch.object(B, 'measure_portable') as measure:
            with self.assertRaisesRegex(ValueError, 'cannot be restarted'):
                B.execute_bounded(SimpleNamespace(output=self.work))
            measure.assert_not_called()

    def test_complete_valid_threshold_failure_is_retained_and_never_retried(self):
        prepared = copy.deepcopy(self.record)
        prepared.update(campaignState='declared-not-measured', runs=[])
        (self.work / 'receipt.json').write_text(json.dumps(prepared))
        (self.work / 'measurement-started.json').unlink()
        observations = copy.deepcopy(self.record['runs'])
        for run in observations:
            run['wallNanos'] = 100000000 if run['variant'] == 'baseline' else 92000000
        helper = SimpleNamespace(check_online_admission=mock.Mock(return_value=self.record['registrationCheck']),
                                 canonical_bytes=C.canonical_bytes)
        host = SimpleNamespace(observe_controls=lambda: self.record['hostControls'],
                               validate_resource_pair=P.FIXTURE.HOST.validate_resource_pair)
        with mock.patch.object(B, 'campaign_module', return_value=helper), \
             mock.patch.object(B, 'bounded_inputs'), \
             mock.patch.object(B, 'portable_host', return_value=host), \
             mock.patch.object(B, 'source_bindings', return_value=prepared['sourceBindings']), \
             mock.patch.object(B, 'portable_class_hashes', return_value=prepared['compiledClassHashes']), \
             mock.patch.object(B, 'measure_portable', side_effect=observations) as measure:
            with self.assertRaisesRegex(ValueError, 'Terminal campaign thresholds failed'):
                B.execute_bounded(SimpleNamespace(output=self.work))
            self.assertEqual(measure.call_count, 8)
            saved = json.loads((self.work / 'receipt.json').read_text())
            self.assertEqual(saved['campaignState'], 'terminal-failure')
            self.assertFalse(saved['passed'])
            self.assertEqual(len(saved['runs']), 8)
            with self.assertRaisesRegex(ValueError, 'cannot be restarted'):
                B.execute_bounded(SimpleNamespace(output=self.work))
            self.assertEqual(measure.call_count, 8)

    def test_rehashed_duplicate_raw_process_json_is_rejected(self):
        run = self.record['runs'][0]
        path = self.work / run['variant'] / 'warmup-0.process.json'
        value = path.read_text()
        path.write_text(value[:-1] + ',"returncode":0}')
        run['artifacts']['processSha256'] = G.sha(path)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.replay(self.record)

    def test_prepare_rejects_malformed_secret_bearing_producer_without_reflection(self):
        secret = 'DO_NOT_DISCLOSE_PRODUCER_SENTINEL'
        helper = SimpleNamespace(load_policy=lambda _: json.loads((ROOT / C.POLICY_PATH).read_text()),
                                 producer_from_environment=C.producer_from_environment)
        environment = {'GITHUB_RUN_ID': secret, 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': '1' * 40,
                       'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF_NAME': 'main', 'GITHUB_REPOSITORY': C.REPOSITORY}
        with mock.patch.dict(os.environ, environment), mock.patch.object(B, 'campaign_module', return_value=helper), \
             mock.patch.object(B, 'portable_host') as observe, mock.patch.object(B, 'compile_production') as compile_source:
            try:
                B.prepare_bounded(SimpleNamespace(output=self.work / 'never-created'))
            except ValueError as error:
                self.assertNotIn(secret, ''.join(traceback.format_exception(error)))
            else:
                self.fail('Malformed producer identity was accepted')
            observe.assert_not_called()
            compile_source.assert_not_called()
        self.assertFalse((self.work / 'never-created').exists())

    def test_runtime_override_secrets_are_rejected_without_reflection(self):
        secret = 'DO_NOT_DISCLOSE_TEST_CREDENTIAL'
        for name in B.BOUNDED_OVERRIDE_KEYS:
            with self.subTest(name=name), mock.patch.dict(os.environ, {name: secret}):
                with self.assertRaises(ValueError) as caught:
                    B.reject_bounded_runtime_overrides()
                self.assertNotIn(secret, str(caught.exception))
        self.assertEqual(set(B.BOUNDED_CHILD_ENV), {'PATH', 'LANG', 'LC_ALL', 'TZ'})

    def test_only_observed_parent_python_loader_is_accepted(self):
        clean = {name: '' for name in B.BOUNDED_OVERRIDE_KEYS}
        with mock.patch.dict(os.environ, clean):
            B.reject_bounded_runtime_overrides()
            for value in (B.BOUNDED_PARENT_PYTHON_LOADER,):
                with mock.patch.dict(os.environ, {'LD_LIBRARY_PATH': value}):
                    B.reject_bounded_runtime_overrides()
            for value in (B.BOUNDED_PARENT_PYTHON_LOADER + ':/tmp/unreviewed',
                          B.BOUNDED_PARENT_PYTHON_LOADER + '/',
                          B.BOUNDED_PARENT_PYTHON_LOADER.replace('3.12.14', '3.12.15')):
                with self.subTest(value=value), mock.patch.dict(os.environ, {'LD_LIBRARY_PATH': value}):
                    with self.assertRaisesRegex(ValueError, 'Unapproved'):
                        B.reject_bounded_runtime_overrides()
        self.assertNotIn('LD_LIBRARY_PATH', B.BOUNDED_CHILD_ENV)

    def test_bounded_java_child_never_inherits_parent_credentials(self):
        controls, before, after = P.FIXTURE.valid_observations()
        identity = P.child_resource_identity(controls)
        host = SimpleNamespace(validate_controls=P.FIXTURE.HOST.validate_controls,
            observe_controls=lambda: controls, observe_counters=mock.Mock(side_effect=[before, after]))
        def child(command, **kwargs):
            self.assertEqual(kwargs['env'], B.BOUNDED_CHILD_ENV)
            self.assertNotIn('GITHUB_TOKEN', kwargs['env'])
            self.assertNotIn('CUSTOM_SECRET', kwargs['env'])
            self.assertNotIn('LD_LIBRARY_PATH', kwargs['env'])
            Path(command[-5]).write_bytes(bytes(4586400))
            Path(command[-3]).write_text('SYNTHETIC UNIT PROFILE')
            return SimpleNamespace(returncode=0, stderr='', stdout=json.dumps(dict(wallNanos=100000000,
                processCpuNanos=200000000, peakRssBytes=1000000000, cpuAffinityList='0-2',
                availableProcessors=3, protocol=B.BOUNDED_PROTOCOL, hostVariant='baseline', referenceIntraThreads=3,
                resourceIdentityBefore=identity, resourceIdentityAfter=identity)))
        with mock.patch.dict(os.environ, {'GITHUB_TOKEN': 'TOKEN_SENTINEL', 'CUSTOM_SECRET': 'SECRET_SENTINEL',
                                        'LD_LIBRARY_PATH': B.BOUNDED_PARENT_PYTHON_LOADER}), \
             mock.patch.object(B.b, 'read_output', return_value='a' * 64), \
             mock.patch.object(B, 'portable_profile', return_value=G.portable_coverage('baseline')):
            result = B.measure_portable('baseline', 0, 0, 'privacy-unit-only', self.work / 'classes', self.work,
                Path('/synthetic/java'), [], Path('/synthetic/models'), Path('/synthetic/audio'), controls,
                host=host, run_process=child, protocol=B.BOUNDED_PROTOCOL)
        self.assertNotIn('TOKEN_SENTINEL', json.dumps(result))
        self.assertNotIn('SECRET_SENTINEL', json.dumps(result))
        self.assertNotIn(B.BOUNDED_PARENT_PYTHON_LOADER, json.dumps(result))

    def test_jdk_links_bind_contained_target_bytes_and_reject_escape(self):
        jdk = self.work / 'synthetic-jdk'
        for name in ('bin/java', 'bin/javac', 'lib/modules', 'lib/server/libjvm.so', 'release', 'legal/base/LICENSE'):
            path = jdk / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'SYNTHETIC RUNTIME FILE')
        link = jdk / 'legal/other/LICENSE'
        link.parent.mkdir(parents=True)
        link.symlink_to('../base/LICENSE')
        dependencies = []
        for name in ('android.jar', 'test-json.jar', 'onnxruntime-1.25.1.jar'):
            path = self.work / name
            path.write_bytes(b'SYNTHETIC DEPENDENCY')
            dependencies.append(path)
        with mock.patch.dict(os.environ, {'LD_LIBRARY_PATH': B.BOUNDED_PARENT_PYTHON_LOADER}):
            binding = B.bounded_runtime_bindings(jdk / 'bin', dependencies)
        self.assertNotIn(B.BOUNDED_PARENT_PYTHON_LOADER, json.dumps(binding))
        self.assertEqual(binding['childEnvironment'], B.BOUNDED_CHILD_ENV)
        self.assertEqual(binding['jdkSymlinks'], {'legal/other/LICENSE': '../base/LICENSE'})
        self.assertEqual(binding['jdkFiles']['legal/other/LICENSE'], binding['jdkFiles']['legal/base/LICENSE'])
        outside = self.work / 'outside'
        outside.write_bytes(b'SYNTHETIC OUTSIDE FILE')
        link.unlink()
        link.symlink_to('../../../outside')
        with self.assertRaisesRegex(ValueError, 'contained'):
            B.bounded_runtime_bindings(jdk / 'bin', dependencies)

    def test_prepare_has_no_measure_call_and_explicit_phase_required(self):
        import ast
        tree = ast.parse((ROOT / 'tools/benchmark_deux_parallel.py').read_text())
        prepare = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'prepare_bounded')
        names = {n.func.id for n in ast.walk(prepare) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertNotIn('measure_portable', names)
        self.assertNotIn('execute_bounded', names)
        self.assertEqual(G.BOUNDED_PROTOCOL, B.BOUNDED_PROTOCOL)
        self.assertEqual(G.BOUNDED_SCHEMA, B.BOUNDED_SCHEMA)
        self.assertEqual(G.BOUNDED_SCOPE, B.BOUNDED_SCOPE)


if __name__ == '__main__':
    unittest.main()
