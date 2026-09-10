"""Fail-closed contract tests for paired native profile evidence."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('native_profile_verify', ROOT / 'qa/release-2.2.4/verify-analysis.py')
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NativeInferenceProfileEvidenceTest(unittest.TestCase):
    def test_profile_emission_is_retained_for_release_and_failure_paths(self):
        passage = (ROOT / 'android/src/com/cyberbasslord/lightforge/NativePassageTask.java').read_text()
        diagnostics = (ROOT / 'android/src/com/cyberbasslord/lightforge/AppDiagnostics.java').read_text()
        self.assertIn('emitProfile(inferenceProfile,"released")', passage)
        self.assertIn('emitProfile(profile,"completed")', passage)
        self.assertIn('emitProfile(profile,outcome)', passage)
        self.assertIn('emitProfile(profile,"cancelled")', passage)
        self.assertIn('AppDiagnostics.profile(context,snapshot)', passage)
        self.assertIn('public static void profile(Context context, NativeInferenceProfile.Snapshot profile)', diagnostics)

    def test_stage_telemetry_contract_is_bounded_and_marks_missing_metrics(self):
        profile = (ROOT / 'android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java').read_text()
        deux = (ROOT / 'android/src/com/cyberbasslord/lightforge/NativeDeux.java').read_text()
        diagnostics = (ROOT / 'android/src/com/cyberbasslord/lightforge/AppDiagnostics.java').read_text()
        pair = (ROOT / 'android/src/com/cyberbasslord/lightforge/NativeInferenceProfileOutputComparison.java').read_text()
        for token in [
            'MAX_STAGE_RECORDS = 16', 'MAX_RECORDS = 1 + MAX_STAGE_RECORDS + MAX_GRAPH_RECORDS',
            'schema=native-inference-profile-v2', 'schema=native-inference-stage-v1',
            'cpuTelemetry=', 'memoryTelemetry=', 'acceleratorTelemetry=unavailable',
            'modelInitWallMs=', 'inferenceWallMs=', 'preprocessWallMs=', 'postprocessWallMs=',
            'waitWallMs=', 'cacheTelemetry=', 'cacheModelHits=', 'cacheModelMisses=',
            'directBufferTelemetry=', 'valueOrUnavailable', 'bytesOrUnavailable', 'countOrUnavailable',
            'noteCacheModelHit', 'noteCacheModelMiss',
        ]:
            self.assertIn(token, profile)
        self.assertIn('if (!Boolean.TRUE.equals(enabled.invoke(bean))) return unavailableCpuClock()', profile)
        self.assertNotIn('setThreadCpuTimeEnabled', profile)
        self.assertIn('preflightCache(check,profile)', deux)
        self.assertIn('profile.noteCacheModelHit(bytes)', deux)
        self.assertIn('profile.noteCacheModelMiss(bytes)', deux)
        for stage in ['addGateWait', 'addPreflight', 'addBufferInit', 'addRuntimeInit', 'addRead',
                      'addEncode', 'addPack', 'addScatter', 'addDecode', 'addWrite', 'addFlush',
                      'addOutputCommit']:
            self.assertIn('finally { if(profile!=null)profile.' + stage, deux)
        self.assertIn('NativeInferenceProfile.MAX_RECORDS', diagnostics)
        self.assertIn('BYTE_IDENTITY_REQUIRED = true', pair)
        self.assertIn('MAX_ABSOLUTE_ERROR = 0D', pair)
        self.assertIn('!stem.finite || !stem.identical', pair)

    def fixture(self, root, session=None, paired_sha=None):
        models = {f'graph-{index}.onnx': {'sha256': f'{index:064x}'} for index in range(27)}
        for relative in VERIFY.PROFILE_EQUIVALENCE_SOURCES:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if relative == 'android/native-runtime.json':
                path.write_text(json.dumps({'version': '1.25.1', 'host': {'sha256': '1' * 64, 'bytes': 41804437}}))
            elif relative == 'web/analysis/models/deux/manifest.json':
                path.write_text(json.dumps({'files': models}))
            elif relative == 'web/demo/glass-castle.wav':
                path.write_bytes(b'fixture')
            else:
                path.write_text('bound source: ' + relative + '\n')
        source_hashes = {relative: digest(root / relative) for relative in VERIFY.PROFILE_EQUIVALENCE_SOURCES}
        expected_models = {'web/analysis/models/deux/' + name: item['sha256'] for name, item in models.items()}
        approved = 'b5db5b5f8bcc576e1af22b0a9fca837dc9e809195ada006af1581458283578b7'
        paired_sha = paired_sha or ('a' * 64)
        result = {
            'evidenceSession': session,
            'historicalApprovedSha256': approved,
            'unprofiledOutputSha256': paired_sha,
            'profiledOutputSha256': paired_sha,
            'unprofiledOutputBytes': 2 * VERIFY.SAMPLES * 4,
            'profiledOutputBytes': 2 * VERIFY.SAMPLES * 4,
            'byteIdentical': True,
            'unprofiledMatchesHistorical': paired_sha == approved,
            'profiledMatchesHistorical': paired_sha == approved,
            'criteria': VERIFY.PROFILE_PAIR_CRITERIA,
            'profile': {
                'record_sha256': 'c' * 64, 'record_bytes': 100, 'records': 43,
                'stage_records': 15, 'graph_records': 27,
                'topology': {
                    'summary_schema': 'native-inference-profile-v2',
                    'stage_schema': 'native-inference-stage-v1',
                    'graph_schema': 'native-inference-graph-v2',
                    'stages': VERIFY.PROFILE_EXPECTED_STAGES,
                    'graphs': VERIFY.PROFILE_EXPECTED_GRAPHS,
                },
            },
            'comparison': [{
                'stem': stem, 'samples': VERIFY.SAMPLES, 'finite': True, 'identical': True,
                'max_absolute_error': 0.0, 'rmse': 0.0, 'relative_rmse': 0.0,
            } for stem in ['vocals', 'accompaniment']],
        }
        report = {
            'schema': VERIFY.PROFILE_EQUIVALENCE_SCHEMA, 'release': '2.2.4', 'passed': True,
            'created_utc': '2026-09-10T00:00:00+00:00', 'evidence_session': session,
            'scope': 'same-runtime paired observer proof', 'source_hashes': source_hashes,
            'source_hashes_after': source_hashes,
            'baseline': {
                'comparison_path': 'qa/release-2.2.4/native-runtime-comparison-verification.json',
                'comparison_sha256': VERIFY.COMPARISON_SHA256, 'runtime_version': '1.25.1',
                'historical_approved_output_sha256': approved, 'start_sample': -66150,
                'input_audio_sha256': digest(root / 'web/demo/glass-castle.wav'),
                'input_audio_bytes': (root / 'web/demo/glass-castle.wav').stat().st_size,
            },
            'criteria': VERIFY.PROFILE_PAIR_CRITERIA,
            'model_asset_hashes': expected_models, 'model_asset_hashes_after': expected_models,
            'runtime_bindings': {
                'android_api_jar_sha256': '2' * 64, 'android_api_jar_bytes': 1,
                'host_onnx_runtime_sha256': '1' * 64, 'host_onnx_runtime_bytes': 41804437,
                'test_json_jar_sha256': '3' * 64, 'test_json_jar_bytes': 1,
            },
            'result': result,
            'checks': ['models', 'compile', 'same-JVM pair', 'canonical profile', 'historical context'],
        }
        report_path = root / VERIFY.PROFILE_EQUIVALENCE_PATH
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report))
        return report_path, approved

    def verify_fixture(self, root, mutable=None):
        comparison = {'runs': [{'version': '1.25.1', 'sha256': 'b5db5b5f8bcc576e1af22b0a9fca837dc9e809195ada006af1581458283578b7'}]}
        return VERIFY.verify_profile_equivalence(root, {}, comparison, mutable or set())

    def test_same_runtime_exact_pair_and_canonical_topology_required(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('LIGHTFORGE_EVIDENCE_SESSION', None)
            root = Path(temporary)
            report_path, _ = self.fixture(root)
            result = self.verify_fixture(root, {'android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java'})
            self.assertTrue(result['passed'])
            report = json.loads(report_path.read_text())
            report['result']['profile']['stage_records'] = 14
            report_path.write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                self.verify_fixture(root)

    def test_historical_digest_is_context_not_paired_pass_gate(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('LIGHTFORGE_EVIDENCE_SESSION', None)
            root = Path(temporary)
            _, approved = self.fixture(root, paired_sha='a' * 64)
            result = self.verify_fixture(root)
            self.assertTrue(result['passed'])
            self.assertFalse(result['result']['unprofiledMatchesHistorical'])
            self.assertNotEqual(result['result']['unprofiledOutputSha256'], approved)

    def test_any_paired_byte_or_numeric_regression_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('LIGHTFORGE_EVIDENCE_SESSION', None)
            root = Path(temporary)
            report_path, _ = self.fixture(root)
            report = json.loads(report_path.read_text())
            report['result']['comparison'][0]['max_absolute_error'] = 1e-12
            report_path.write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                self.verify_fixture(root)
            report = json.loads(report_path.read_text())
            report['result']['comparison'][0]['max_absolute_error'] = 0.0
            report['result']['byteIdentical'] = False
            report_path.write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                self.verify_fixture(root)

    def test_session_mode_rejects_wrong_and_stale_receipts(self):
        session = '0' * 64
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {'LIGHTFORGE_EVIDENCE_SESSION': session}, clear=False):
            root = Path(temporary)
            report_path, _ = self.fixture(root, session=session)
            self.assertTrue(self.verify_fixture(root)['passed'])
            report = json.loads(report_path.read_text())
            report['evidence_session'] = '1' * 64
            report['result']['evidenceSession'] = '1' * 64
            report_path.write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                self.verify_fixture(root)
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('LIGHTFORGE_EVIDENCE_SESSION', None)
            root = Path(temporary)
            self.fixture(root, session=session)
            with self.assertRaises(ValueError):
                self.verify_fixture(root)

    def test_profile_proof_is_mandatory_and_comparison_allowlist_is_narrow(self):
        self.assertIn('android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java',
                      VERIFY.PROFILED_COMPARISON_MUTABLE_SOURCES)
        self.assertNotIn('tests/NativeInferenceProfileEquivalenceTest.java',
                         VERIFY.PROFILED_COMPARISON_MUTABLE_SOURCES)
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('LIGHTFORGE_EVIDENCE_SESSION', None)
            root = Path(temporary)
            report_path, _ = self.fixture(root)
            report_path.unlink()
            with self.assertRaises(ValueError):
                self.verify_fixture(root)


if __name__ == '__main__':
    unittest.main()
