"""Fail-closed contract tests for profile-enabled native output equivalence evidence."""
from pathlib import Path
import hashlib
import importlib.util
import json
import tempfile
import unittest


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

    def fixture(self, root):
        paths = {
            'android/src/com/cyberbasslord/lightforge/NativeDeux.java': 'profile observer only',
            'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java': 'transform',
            'android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java': 'profile',
            'tests/NativeInferenceProfileEquivalenceTest.java': 'equivalence',
            'android/native-runtime.json': json.dumps({'version': '1.25.1'}),
            'web/analysis/models/deux/manifest.json': '',
            'web/demo/glass-castle.wav': 'fixture',
            'qa/release-2.2.4/native-runtime-comparison-verification.json': 'historical evidence',
            'qa/release-2.2.4/compare-native-runtime.py': 'comparator',
            'qa/release-2.2.4/verify-native-inference-profile.py': 'profile gate',
        }
        models = {f'graph-{index}.onnx': {'sha256': f'{index:064x}'} for index in range(27)}
        paths['web/analysis/models/deux/manifest.json'] = json.dumps({'files': models})
        for relative, text in paths.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        source_hashes = {relative: digest(root / relative) for relative in VERIFY.PROFILE_EQUIVALENCE_SOURCES}
        expected_models = {'web/analysis/models/deux/' + name: item['sha256'] for name, item in models.items()}
        approved = 'b5db5b5f8bcc576e1af22b0a9fca837dc9e809195ada006af1581458283578b7'
        report = {
            'schema': VERIFY.PROFILE_EQUIVALENCE_SCHEMA, 'release': '2.2.4', 'passed': True,
            'source_hashes': source_hashes,
            'baseline': {
                'comparison_path': 'qa/release-2.2.4/native-runtime-comparison-verification.json',
                'comparison_sha256': VERIFY.COMPARISON_SHA256, 'runtime_version': '1.25.1',
                'approved_output_sha256': approved, 'start_sample': -66150,
            },
            'model_asset_hashes': expected_models,
            'result': {'outputSha256': approved, 'outputBytes': 2 * VERIFY.SAMPLES * 4,
                       'profileRecords': 43, 'stageRecords': 15, 'graphRecords': 27},
            'checks': ['models', 'compile', 'exact output', 'bounded receipt'],
            'scope': 'host proof',
        }
        report_path = root / VERIFY.PROFILE_EQUIVALENCE_PATH
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report))
        return report_path, approved

    def test_exact_output_and_bounded_receipt_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_path, approved = self.fixture(root)
            comparison = {'runs': [{'version': '1.25.1', 'sha256': approved}]}
            result = VERIFY.verify_profile_equivalence(
                root, {}, comparison,
                {'android/src/com/cyberbasslord/lightforge/NativeDeux.java'},
            )
            self.assertTrue(result['passed'])
            report = json.loads(report_path.read_text())
            report['result']['stageRecords'] = 14
            report_path.write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                VERIFY.verify_profile_equivalence(
                    root, {}, comparison,
                    {'android/src/com/cyberbasslord/lightforge/NativeDeux.java'},
                )

    def test_newly_measured_profiler_source_still_requires_enabled_profile_proof(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, approved = self.fixture(root)
            comparison = {
                'runs': [{'version': '1.25.1', 'sha256': approved}],
                'source_hashes': {
                    'android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java': 'newly-measured'
                },
            }
            result = VERIFY.verify_profile_equivalence(root, {}, comparison, set())
            self.assertTrue(result['passed'])


if __name__ == '__main__':
    unittest.main()
