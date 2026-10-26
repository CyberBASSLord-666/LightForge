"""Cross-release authority-boundary tests; synthetic fixtures are not measurements."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
SPEC = importlib.util.spec_from_file_location('release_replay_bridge', ROOT / 'tools/replay_inference_proof.py')
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)
if __package__:
    from . import test_host_inference_campaign as fixtures
else:
    import test_host_inference_campaign as fixtures


class ReplayMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.original = self.directory / 'original'
        self.current = self.directory / 'candidate'
        policy = json.loads((ROOT / B.OLD_POLICY).read_text())
        # Real frozen source bytes exercise bootstrap pinning; no original
        # classes, outputs or timings are manufactured by this unit fixture.
        for name in policy['executionClosurePaths']:
            path = self.original / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if name == 'version.json':
                path.write_bytes(b'{"name":"2.4.2","code":20402}\n')
            elif name == '.github/workflows/verify-v2.yml':
                path.write_bytes(b'SYNTHETIC ORIGINAL WORKFLOW - UNIT TEST ONLY\n')
            else:
                path.write_bytes((ROOT / name).read_bytes())
        head = patch.object(fixtures, 'HEAD', B.BASE_COMMIT)
        head.start()
        self.addCleanup(head.stop)
        self.api = fixtures.FakeGitHub(self.original)
        self.api.status, self.api.conclusion = 'completed', 'success'
        shutil.copytree(self.original, self.current)
        (self.current / 'version.json').write_text(json.dumps(B.TARGET))
        (self.current / '.github/workflows/verify-v2.yml').write_bytes(b'REVIEWED UNIT WORKFLOW; NOT A REAL RUN\n')
        registration = self.current / B.REGISTRATION
        registration.parent.mkdir(parents=True, exist_ok=True)
        registration.write_bytes(fixtures.C.canonical_bytes(self.api.registration))
        registration_pin = patch.object(B, 'REGISTRATION_SHA', B.sha(registration.read_bytes()))
        registration_pin.start()
        self.addCleanup(registration_pin.stop)
        replay_policy = dict(schema='lightforge.inference-replay-policy.v1',
            baselineCampaignId=B.CAMPAIGN, baselineSourceCommit=B.BASE_COMMIT,
            baselinePolicySha256=B.OLD_POLICY_SHA, targetRelease=B.TARGET,
            permittedMetadataChanges=sorted(B.METADATA_PATHS),
            currentWorkflowSha256=B.sha((self.current / '.github/workflows/verify-v2.yml').read_bytes()), scope=B.SCOPE)
        (self.current / B.POLICY).write_text(json.dumps(replay_policy))
        manifest = self.current / 'web/analysis/models/deux/manifest.json'
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({'files': {name: {'bytes': 4, 'sha256': 'unit-only'} for name in B.GRAPH_FILES}}))
        for name in B.GRAPH_FILES:
            (manifest.parent / name).write_bytes(b'UNIT')
        audio = self.current / 'web/demo/glass-castle.wav'
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b'UNIT AUDIO - NOT REAL EVIDENCE')
        self.identity = ('a' * 40, 'b' * 40)
        self.session = 'c' * 64

    def test_projection_preserves_original_metadata_and_rejects_any_other_closure_change(self):
        result = B.current_projection(self.current)
        self.assertEqual(len(result['unchangedExecutionSources']), 25)
        self.assertEqual(set(result['declaredMetadataChanges']), set(B.METADATA_PATHS))
        self.assertEqual(result['targetRelease'], B.TARGET)
        name = 'android/src/com/cyberbasslord/lightforge/NativeDeux.java'
        source = self.current / name
        source.write_bytes(source.read_bytes() + b'\nchanged numerical code')
        with self.assertRaisesRegex(ValueError, 'numerical/execution closure'):
            B.current_projection(self.current)

    def test_no_policy_can_whitelist_another_changed_execution_path(self):
        path = self.current / B.POLICY
        value = json.loads(path.read_text())
        value['permittedMetadataChanges'].append('tools/prepare_deux.py')
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'Unreviewed'):
            B.current_projection(self.current)

    def test_metadata_version_and_workflow_are_exact_not_ignored(self):
        version = self.current / 'version.json'
        version.write_text(json.dumps(dict(B.TARGET, code=20404)))
        with self.assertRaisesRegex(ValueError, 'target release'):
            B.current_projection(self.current)
        version.write_text(json.dumps(B.TARGET))
        path = self.current / '.github/workflows/verify-v2.yml'
        path.write_bytes(path.read_bytes() + b'\nchanged')
        with self.assertRaisesRegex(ValueError, 'workflow differs'):
            B.current_projection(self.current)

    def test_bootstrap_helper_registration_and_policy_cannot_be_swapped(self):
        for name in (B.OLD_HELPER, B.OLD_POLICY, B.REGISTRATION):
            path = self.current / name
            original = path.read_bytes()
            path.write_bytes(original + b'\nchanged')
            with self.subTest(path=name), self.assertRaises(ValueError):
                B.current_projection(self.current)
            path.write_bytes(original)

    def test_source_snapshot_is_original_and_current_checkout_is_never_version_edited(self):
        before = {name: (self.current / name).read_bytes() for name in B.METADATA_PATHS}
        with B.original_source(self.current, self.api) as (_, original):
            self.assertEqual(original.parent, self.current.parent)
            self.assertEqual(json.loads((original / 'version.json').read_text())['name'], '2.4.2')
            for name, checksum in self.api.declaration['executionClosure'].items():
                self.assertEqual(B.sha((original / name).read_bytes()), checksum)
            self.assertTrue(all((self.current / name).read_bytes() == raw for name, raw in before.items()))
        self.assertFalse(original.exists())

    def _replay(self, *, mutate_classes=False, numerical_failure=False):
        real_load = B.load
        numerical = Mock(return_value=18.8, side_effect=ValueError('raw proof failed') if numerical_failure else None)
        def load(name, path):
            if name == 'frozen_inference_numerical_replay':
                return SimpleNamespace(verify_bounded=numerical)
            return real_load(name, path)
        classes = dict(self.api.receipt['compiledClassHashes'])
        if mutate_classes:
            classes['changed.class'] = 'e' * 64
        with patch.object(B, 'git_identity', return_value=self.identity), \
                patch.object(B, 'load', side_effect=load), \
                patch.object(B, 'rebuild_current_classes', return_value=classes) as compile_current:
            result = B.replay(self.current, api=self.api, output_dir=self.directory / 'proof',
                              evidence_session=self.session, rebuild_classes=True)
        return result, numerical, compile_current

    def test_sealing_calls_real_authority_then_numeric_replay_and_current_compile(self):
        result, numerical, compile_current = self._replay()
        numerical.assert_called_once()
        compile_current.assert_called_once()
        self.assertEqual(Path(compile_current.call_args.args[0]), self.current)
        self.assertNotEqual(Path(compile_current.call_args.args[0]), Path(compile_current.call_args.args[1]))
        self.assertEqual(result['admission']['candidate'], dict(sourceCommit=self.identity[0],
            sourceTreeSha=self.identity[1], evidenceSession=self.session))
        self.assertEqual(result['admission']['producer'], self.api.declaration['producer'])
        self.assertEqual(result['measurementSourceRelease'], '2.4.2')
        self.assertEqual(result['measurementSourceCommit'], B.BASE_COMMIT)
        self.assertFalse(result['newMeasurementPerformed'])
        self.assertEqual(result['medianWallReductionPercent'], 18.8)
        self.assertIn(('download', 456), self.api.calls)
        self.assertIn(('download', 789), self.api.calls)

    def test_false_pass_or_wrong_current_classes_cannot_seal(self):
        with self.assertRaisesRegex(ValueError, 'Current admitted classes'):
            self._replay(mutate_classes=True)
        shutil.rmtree(self.directory / 'proof')
        with self.assertRaisesRegex(ValueError, 'raw proof failed'):
            self._replay(numerical_failure=True)

    def test_missing_expired_or_failed_original_proof_has_no_fallback(self):
        for state in ('missing', 'failed', 'unprotected'):
            self.api.missing_artifacts = {789} if state == 'missing' else set()
            self.api.conclusion = 'failure' if state == 'failed' else 'success'
            self.api.protected = state != 'unprotected'
            with self.subTest(state=state), self.assertRaises(ValueError):
                self._replay()

    def test_corrupted_original_remote_source_is_not_accepted_from_local_hashes(self):
        self.api.source_corruption.add('tools/prepare_deux.py')
        with self.assertRaisesRegex(ValueError, 'committed source'):
            self._replay()

    def test_publisher_candidate_and_session_binding_are_mandatory(self):
        result, _, _ = self._replay()
        admission = copy.deepcopy(result['admission'])
        admission['candidate']['evidenceSession'] = 'd' * 64
        with self.assertRaisesRegex(ValueError, 'evidenceSession'):
            B.verify_release_admission(self.current, admission,
                dict(head_sha=self.identity[0], tree_sha=self.identity[1], evidence_session=self.session),
                api=self.api, output_dir=self.directory / 'publisher-proof')

    def test_actual_current_class_rebuild_not_the_copied_historical_sources(self):
        receipt = dict(self.api.receipt, runtimeBindings=self.api.declaration['runtimeBindings'])
        fake = SimpleNamespace(ROOT=None, BOUNDED_CHILD_ENV={'PATH': '/usr/bin:/bin'},
            bounded_toolchain=Mock(return_value=('JAVA', ['DEPS'])),
            bounded_runtime_bindings=Mock(return_value=receipt['runtimeBindings']),
            compile_production=Mock(return_value='CLASSES'),
            portable_class_hashes=Mock(return_value=receipt['compiledClassHashes']))
        with patch.object(B, 'load', return_value=fake):
            actual = B.rebuild_current_classes(self.current, self.original, receipt)
        self.assertEqual(fake.ROOT, self.current)
        expected = {name: value for name, value in receipt['sourceBindings'].items() if name.endswith('.java')}
        self.assertEqual(fake.compile_production.call_args.args[3], expected)
        self.assertEqual(actual, receipt['compiledClassHashes'])
        fake.portable_class_hashes.return_value = {'wrong.class': 'f' * 64}
        with patch.object(B, 'load', return_value=fake), self.assertRaisesRegex(ValueError, 'CURRENT compiled'):
            B.rebuild_current_classes(self.current, self.original, receipt)


if __name__ == '__main__':
    unittest.main()
