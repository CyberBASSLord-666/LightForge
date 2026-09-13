#!/usr/bin/env python3
"""Bind 2.2.4's fresh native runtime comparison and source-clock evidence.

The native predictor source and Balanced execution path changed, so these
comparisons are newly executed. This gate binds the measured host predictions,
the complete current analysis inventory, and a fresh source-clock regression. It
does not claim a new corpus accuracy benchmark or an ARM64 crash reproduction.
"""
from pathlib import Path
import datetime
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OUT = 'qa/release-2.2.4/'
COMPARISON_SHA256 = 'e74c12ca08132182f7cb971a98a6280401fcbfb5220a403e690e276c21c91712'
ASSET_MANIFEST_SHA256 = '234bae8dad897ece2f22999a0901e920db934e42772c258b9cd1558a4e0e39b9'
ASSET_MANIFEST_ENTRY_COUNT = 85
OLD_RUNTIME_SHA256 = 'e0ab4a1af57d2da09097202f2dfd691e390c82e81183314788ccde4cf7c3cc38'
NEW_RUNTIME_SHA256 = '749793ebed63743fec853d093da7987a86ea5cd592d54fba898cd3233100c381'
SAMPLES = 573300
THRESHOLDS = {'max_absolute_error': 1e-4, 'rmse': 1e-5, 'relative_rmse': 1e-3}
COMPARISON_SOURCES = {
    'android/src/com/cyberbasslord/lightforge/NativeDeux.java',
    'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java',
    'tests/NativeDeuxTest.java', 'android/native-runtime.json',
    'web/analysis/models/deux/manifest.json', 'web/demo/glass-castle.wav',
    OUT + 'compare-native-runtime.py',
}
# The immutable 2.2.4 comparison predates the observer. A newly measured comparison
# must compile the observer because NativeDeux now references its package-private
# type, but that newer evidence is still required to run the enabled-profile gate.
PROFILED_COMPARISON_SOURCES = COMPARISON_SOURCES | {
    'android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java',
}
PROFILE_EQUIVALENCE_PATH = OUT + 'native-inference-profile-equivalence.json'
PROFILE_EQUIVALENCE_SCHEMA = 'lightforge.native-inference-profile-equivalence.v2'
EVIDENCE_SESSION_SCHEMA = 'lightforge.evidence-session.v1'
EVIDENCE_SESSION_PATTERN = re.compile(r'[0-9a-f]{32,128}\Z')
PROFILE_PAIR_CRITERIA = {
    'stems': 2, 'samples_per_stem': SAMPLES, 'output_bytes': 2 * SAMPLES * 4,
    'finite_required': True, 'byte_identity_required': True,
    'max_absolute_error': 0.0, 'rmse': 0.0, 'relative_rmse': 0.0,
}
PROFILE_EXPECTED_STAGES = sorted([
    'inference-gate-wait', 'cache-preflight', 'buffer-init', 'runtime-setup',
    'pcm-read', 'feature-encode', 'model-init', 'tensor-bind', 'inference',
    'pack', 'scatter', 'decode', 'output-write', 'output-flush', 'output-commit',
])
PROFILE_EXPECTED_GRAPHS = sorted(['front', 'head-0', 'head-1'] + [
    'block-%02d-%s' % (block, axis) for block in range(12)
    for axis in ('time', 'frequency')
])
# The immutable 2.2.4 comparison is a separate unprofiled quality binding. These
# are the only historical comparison sources permitted to differ before a fresh
# v2 same-session paired proof binds their current observer/test/gate contract.
PROFILED_COMPARISON_MUTABLE_SOURCES = {
    'android/src/com/cyberbasslord/lightforge/NativeDeux.java',
    'android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java',
    OUT + 'compare-native-runtime.py',
}
PROFILE_EQUIVALENCE_SOURCES = {
    'android/src/com/cyberbasslord/lightforge/NativeDeux.java',
    'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java',
    'android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java',
    'android/src/com/cyberbasslord/lightforge/NativeInferenceProfileOutputComparison.java',
    'android/src/com/cyberbasslord/lightforge/NativePassageTask.java',
    'android/src/com/cyberbasslord/lightforge/AppDiagnostics.java',
    'tests/NativeInferenceProfileEquivalenceTest.java',
    'tests/NativeInferenceProfilePairComparisonTest.java',
    'tests/NativeInferenceProfileTest.java', 'tests/verify_native_release.py',
    'tests/test_native_inference_profile_evidence.py',
    'android/native-runtime.json', 'web/analysis/models/deux/manifest.json',
    'web/demo/glass-castle.wav', OUT + 'native-runtime-comparison-verification.json',
    OUT + 'compare-native-runtime.py', OUT + 'verify-native-inference-profile.py', OUT + 'verify-analysis.py',
}
CLOCK_SOURCES = {
    'web/analysis/separator-deux.js', 'web/analysis/dsp.js',
    'web/analysis/models/deux/manifest.json', OUT + 'test-source-clock.cjs',
}
BROWSER_SOURCES = {
    OUT + 'browser.cjs', 'qa/release-1.6.0/actual-music-user-glass-prefix64-analysis.json',
    'version.json', 'web/cockpit.js', 'web/cockpit.css',
    'web/version.js', 'web/app.js', 'web/diagnostics.js', 'web/diagnostics.css',
    'web/index.html', 'web/styles.css', 'web/precision-studio.js',
    'web/engine/worker.js', 'web/engine/client.js', 'web/engine/show-engine.js',
    'web/engine/light-planner.js', 'web/engine/music-cues.js',
    'web/engine/sync-review.js',
}
ANALYSIS_BROWSER_SOURCES = {
    OUT + 'analysis-browser.cjs', OUT + 'analysis-performance.cjs', 'version.json',
    'qa/release-1.6.0/fixtures/falcon-mix.wav',
    'web/index.html', 'web/analysis/ASSET_MANIFEST.json',
    'web/analysis/diagnostic-clock.js', 'web/analysis/resource-diagnostics.js',
    'web/analysis/telemetry.js', 'web/analysis/scheduler.js', 'web/analysis/worker.js',
    'web/analysis/analyzer.js', 'web/analysis/feature-store.js', 'web/analysis/game.js',
    'web/analysis/salience.js', 'web/analysis/semantic-timeline.js',
    'web/analysis/separator-deux.js', 'web/analysis/stem-cache.js',
    'web/analysis/stem-routing.js', 'web/analysis/work-store.js',
    'web/analysis/vocal.js', 'web/analysis/vocal-detail.js',
    'web/analysis/bass-notes.js', 'web/analysis/models/game/manifest.json',
    'web/analysis/models/deux/manifest.json', 'web/engine/show-engine.js',
    'web/engine/light-planner.js', 'web/engine/music-cues.js',
    'web/engine/sync-review.js', 'web/engine/worker.js',
}
EVIDENCE_SESSION_UNSET = object()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_atomic(path, value):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def file(root, relative):
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute(), 'Invalid source path')
    path = (root / relative).resolve()
    require(path.is_relative_to(root) and path.is_file() and path.relative_to(root).as_posix() == relative,
            'Missing, noncanonical or external source: ' + relative)
    return path


def bind(root, relative, expected, hashes):
    require(isinstance(expected, str) and re.fullmatch(r'[0-9a-f]{64}', expected), 'Invalid source hash: ' + relative)
    path = file(root, relative)
    actual = digest(path)
    require(actual == expected, 'Source differs from measured evidence: ' + relative)
    hashes[relative] = actual
    return path


def current_evidence_session():
    session = os.environ.get('LIGHTFORGE_EVIDENCE_SESSION')
    require(session is None or isinstance(session, str) and EVIDENCE_SESSION_PATTERN.fullmatch(session),
            'Invalid LIGHTFORGE_EVIDENCE_SESSION')
    return session


def bind_session_receipt(root, relative, immutable_sha256, hashes, session, label):
    """Bind an immutable historical receipt or a fresh, exact-session receipt.

    Session mode deliberately does not trust an old file digest: the receipt must
    itself identify the CI session and every source/model/output claim below is
    revalidated against current bytes. No-session mode remains a strict static
    pin and explicitly rejects a session-bound receipt.
    """
    path = file(root, relative)
    result = json.loads(path.read_text())
    require(isinstance(result, dict), label + ' receipt is not a JSON object')
    if session is None:
        require('evidenceSession' not in result and 'evidenceSessionSchema' not in result,
                label + ' receipt is session-bound and cannot satisfy no-session verification')
        bind(root, relative, immutable_sha256, hashes)
        return path, result
    require(result.get('evidenceSessionSchema') == EVIDENCE_SESSION_SCHEMA and
            result.get('evidenceSession') == session,
            label + ' receipt is stale, absent, or belongs to a different evidence session')
    hashes[relative] = digest(path)
    return path, result


def verify_fresh_receipt(root, relative, hashes, session, label, sources):
    """Fail closed on any stale, mixed-session, failed, or incomplete producer."""
    require(session is not None, label + ' fresh receipt requires an evidence session')
    _, result = bind_session_receipt(root, relative, '0' * 64, hashes, session, label)
    require(result.get('release') == '2.2.4' and result.get('passed') is True and
            result.get('errors') == [] and isinstance(result.get('completedAt'), str) and
            result['completedAt'], label + ' receipt did not pass cleanly')
    require(isinstance(result.get('source_hashes'), dict) and
            set(result['source_hashes']) == sources,
            label + ' receipt source coverage changed')
    for source, expected in result['source_hashes'].items():
        bind(root, source, expected, hashes)
    return result


def finite_number(value):
    return type(value) in {int, float} and math.isfinite(value)


def verify_comparison(root, hashes):
    path = bind(root, OUT + 'native-runtime-comparison-verification.json', COMPARISON_SHA256, hashes)
    result = json.loads(path.read_text())
    require(result.get('release') == '2.2.4' and result.get('passed') is True and not result.get('failure'),
            'Current native runtime comparison did not pass')
    source_set = set(result.get('source_hashes', {}))
    require(source_set in (COMPARISON_SOURCES, PROFILED_COMPARISON_SOURCES),
            'Native comparison source coverage changed')
    mutable = set()
    for relative, expected in result['source_hashes'].items():
        actual = digest(file(root, relative))
        if relative in PROFILED_COMPARISON_MUTABLE_SOURCES and actual != expected:
            hashes[relative] = actual
            mutable.add(relative)
        else:
            require(actual == expected, 'Source differs from measured evidence: ' + relative)
            hashes[relative] = actual
    require(result.get('start_sample') == -66150 and result.get('sample_rate') == 44100 and
            result.get('samples_per_stem') == SAMPLES, 'Native comparison does not cover the reported passage boundary')
    require(result.get('thresholds') == THRESHOLDS, 'Native comparison thresholds changed')
    runtime = json.loads(file(root, 'android/native-runtime.json').read_text())
    require(runtime.get('version') == '1.25.1' and runtime['host']['sha256'] == NEW_RUNTIME_SHA256 and
            runtime['host']['bytes'] == 41804437, 'Current native runtime pins changed')
    runs = result.get('runs', [])
    require(len(runs) == 2 and [run.get('version') for run in runs] == ['1.23.2', '1.25.1'],
            'Native comparison versions changed')
    for run, expected, size in zip(runs, [OLD_RUNTIME_SHA256, NEW_RUNTIME_SHA256], [75255976, 41804437]):
        require(run.get('runtime_jar_sha256') == expected and run.get('runtime_jar_bytes') == size,
                'Native comparison runtime identity changed')
        require(run.get('samplesPerStem') == SAMPLES and run['output_bytes'] == 2 * SAMPLES * 4,
                'Native comparison output is incomplete')
        require(finite_number(run.get('seconds')) and run['seconds'] > 0 and
                type(run.get('peakRssBytes')) is int and run['peakRssBytes'] > 0 and
                isinstance(run.get('sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', run['sha256']),
                'Native comparison output metadata is invalid')
    stems = result.get('comparison', [])
    require(len(stems) == 2 and [stem.get('stem') for stem in stems] == ['vocals', 'accompaniment'],
            'Native comparison stem coverage changed')
    for stem in stems:
        require(stem.get('finite') is True and stem.get('samples') == SAMPLES, 'Native comparison contains invalid samples')
        for key, limit in THRESHOLDS.items():
            value = stem.get(key)
            require(finite_number(value) and 0 <= value <= limit, 'Native comparison numerical threshold failed: ' + key)
        require(not stem.get('identical') or stem['max_absolute_error'] == 0, 'Native comparison identity assertion conflicts with metrics')
    if all(stem.get('identical') for stem in stems):
        require(runs[0]['sha256'] == runs[1]['sha256'], 'Identical native predictions have different digests')
    model_files = json.loads(file(root, 'web/analysis/models/deux/manifest.json').read_text())['files']
    expected_models = {'web/analysis/models/deux/' + name: item['sha256'] for name, item in model_files.items()}
    require(len(expected_models) == 27 and result.get('model_asset_hashes') == expected_models,
            'Native comparison model inventory differs from current Deux models')
    return result, mutable


def verify_profile_equivalence(root, hashes, comparison, mutable, evidence_session=EVIDENCE_SESSION_UNSET):
    # The ordinary comparison exercises an unprofiled public entry point. Once the
    # collector exists, a fresh paired proof is mandatory even when no historical
    # comparison source changed: only that same-invocation pair proves observer
    # noninterference without relying on a flaky cross-run output digest.
    file(root, 'android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java')
    require(mutable.issubset(PROFILED_COMPARISON_MUTABLE_SOURCES), 'Unreviewed historical comparison source changed')
    path = file(root, PROFILE_EQUIVALENCE_PATH)
    result = json.loads(path.read_text())
    expected_keys = {
        'schema', 'release', 'passed', 'created_utc', 'evidence_session', 'scope', 'source_hashes',
        'baseline', 'criteria', 'checks', 'model_asset_hashes', 'runtime_bindings', 'result',
        'source_hashes_after', 'model_asset_hashes_after',
    }
    require(set(result) == expected_keys and result.get('schema') == PROFILE_EQUIVALENCE_SCHEMA and
            result.get('release') == '2.2.4' and result.get('passed') is True,
            'Profile-enabled native equivalence did not pass')
    expected_session = (current_evidence_session() if evidence_session is EVIDENCE_SESSION_UNSET
                        else evidence_session)
    require(expected_session is None or EVIDENCE_SESSION_PATTERN.fullmatch(expected_session),
            'LIGHTFORGE_EVIDENCE_SESSION is invalid')
    if expected_session is None:
        require(result.get('evidence_session') is None,
                'A session-bound profile receipt cannot satisfy a no-session verification')
    else:
        require(result.get('evidence_session') == expected_session,
                'Profile receipt was generated for a different or stale evidence session')
    require(set(result.get('source_hashes', {})) == PROFILE_EQUIVALENCE_SOURCES,
            'Profile equivalence source coverage changed')
    for relative, expected in result['source_hashes'].items():
        bind(root, relative, expected, hashes)
    require(result.get('source_hashes_after') == result['source_hashes'],
            'Profile source/test/gate bindings changed during paired verification')
    runtime = json.loads(file(root, 'android/native-runtime.json').read_text())
    expected_run = next((run for run in comparison['runs'] if run.get('version') == runtime.get('version')), None)
    require(expected_run is not None, 'Profile equivalence has no approved current-runtime baseline')
    baseline = {
        'comparison_path': OUT + 'native-runtime-comparison-verification.json',
        'comparison_sha256': COMPARISON_SHA256,
        'runtime_version': '1.25.1', 'historical_approved_output_sha256': expected_run['sha256'],
        'start_sample': -66150, 'input_audio_sha256': digest(file(root, 'web/demo/glass-castle.wav')),
        'input_audio_bytes': file(root, 'web/demo/glass-castle.wav').stat().st_size,
    }
    require(result.get('baseline') == baseline, 'Profile equivalence baseline differs from approved runtime output')
    require(result.get('criteria') == PROFILE_PAIR_CRITERIA, 'Profile paired-output criteria changed')
    measured = result.get('result')
    expected_result_keys = {
        'evidenceSession', 'historicalApprovedSha256', 'unprofiledOutputSha256', 'profiledOutputSha256',
        'unprofiledOutputBytes', 'profiledOutputBytes', 'byteIdentical', 'unprofiledMatchesHistorical',
        'profiledMatchesHistorical', 'criteria', 'profile', 'comparison',
    }
    require(isinstance(measured, dict) and set(measured) == expected_result_keys,
            'Profile paired-result schema changed')
    require(measured.get('evidenceSession') == result.get('evidence_session') and
            measured.get('historicalApprovedSha256') == expected_run['sha256'] and
            measured.get('criteria') == PROFILE_PAIR_CRITERIA,
            'Profile paired-result session, historical context or criteria changed')
    for key in ['unprofiledOutputSha256', 'profiledOutputSha256']:
        require(isinstance(measured.get(key), str) and re.fullmatch(r'[0-9a-f]{64}', measured[key]),
                'Profile paired output digest is invalid: ' + key)
    require(measured.get('unprofiledOutputBytes') == 2 * SAMPLES * 4 and
            measured.get('profiledOutputBytes') == 2 * SAMPLES * 4 and
            measured.get('byteIdentical') is True and
            measured['unprofiledOutputSha256'] == measured['profiledOutputSha256'],
            'Profile observer changed paired output bytes')
    require(measured.get('unprofiledMatchesHistorical') is (measured['unprofiledOutputSha256'] == expected_run['sha256']) and
            measured.get('profiledMatchesHistorical') is (measured['profiledOutputSha256'] == expected_run['sha256']),
            'Profile historical digest context was relabeled')
    comparisons = measured.get('comparison')
    require(isinstance(comparisons, list) and len(comparisons) == 2 and
            [item.get('stem') for item in comparisons] == ['vocals', 'accompaniment'],
            'Profile paired stem coverage changed')
    for item in comparisons:
        require(item.get('samples') == SAMPLES and item.get('finite') is True and item.get('identical') is True,
                'Profile paired output is incomplete, nonfinite or nonidentical')
        for metric in ['max_absolute_error', 'rmse', 'relative_rmse']:
            require(finite_number(item.get(metric)) and item[metric] == 0.0,
                    'Profile paired output exceeds the predeclared zero ' + metric)
    profile = measured.get('profile')
    expected_profile_keys = {'record_sha256', 'record_bytes', 'records', 'stage_records', 'graph_records', 'topology'}
    require(isinstance(profile, dict) and set(profile) == expected_profile_keys and
            isinstance(profile.get('record_sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', profile['record_sha256']) and
            type(profile.get('record_bytes')) is int and profile['record_bytes'] > 0 and
            profile.get('records') == 43 and profile.get('stage_records') == 15 and profile.get('graph_records') == 27,
            'Canonical profile record binding is incomplete')
    expected_topology = {
        'summary_schema': 'native-inference-profile-v2', 'stage_schema': 'native-inference-stage-v1',
        'graph_schema': 'native-inference-graph-v2', 'stages': PROFILE_EXPECTED_STAGES,
        'graphs': PROFILE_EXPECTED_GRAPHS,
    }
    require(profile.get('topology') == expected_topology, 'Canonical profile record topology changed')
    models = json.loads(file(root, 'web/analysis/models/deux/manifest.json').read_text())['files']
    expected_models = {'web/analysis/models/deux/' + name: item['sha256'] for name, item in models.items()}
    require(len(expected_models) == 27 and result.get('model_asset_hashes') == expected_models and
            result.get('model_asset_hashes_after') == expected_models,
            'Profile equivalence did not bind every reviewed Deux graph')
    runtime_bindings = result.get('runtime_bindings')
    require(isinstance(runtime_bindings, dict) and set(runtime_bindings) == {
        'android_api_jar_sha256', 'android_api_jar_bytes', 'host_onnx_runtime_sha256',
        'host_onnx_runtime_bytes', 'test_json_jar_sha256', 'test_json_jar_bytes',
    }, 'Profile host-runtime binding changed')
    for key in ['android_api_jar_sha256', 'host_onnx_runtime_sha256', 'test_json_jar_sha256']:
        require(isinstance(runtime_bindings[key], str) and re.fullmatch(r'[0-9a-f]{64}', runtime_bindings[key]),
                'Profile host-runtime digest is invalid: ' + key)
    for key in ['android_api_jar_bytes', 'host_onnx_runtime_bytes', 'test_json_jar_bytes']:
        require(type(runtime_bindings[key]) is int and runtime_bindings[key] > 0,
                'Profile host-runtime byte count is invalid: ' + key)
    require(runtime_bindings['host_onnx_runtime_sha256'] == runtime['host']['sha256'] and
            runtime_bindings['host_onnx_runtime_bytes'] == runtime['host']['bytes'],
            'Profile host ONNX Runtime differs from the native runtime pin')
    checks = result.get('checks')
    require(isinstance(checks, list) and len(checks) >= 5 and all(isinstance(item, str) and item for item in checks),
            'Profile equivalence receipt is incomplete')
    hashes[PROFILE_EQUIVALENCE_PATH] = digest(path)
    return result


def verify_asset(root, relative, metadata, hashes):
    require(isinstance(metadata, dict) and set(metadata) == {'bytes', 'sha256'} and
            type(metadata['bytes']) is int and metadata['bytes'] > 0, 'Invalid asset metadata: ' + relative)
    path = bind(root, 'web/analysis/' + relative, metadata['sha256'], hashes)
    require(path.stat().st_size == metadata['bytes'], 'Analysis asset byte count changed: ' + relative)


def verify_assets(root, hashes):
    manifest_path = bind(root, 'web/analysis/ASSET_MANIFEST.json', ASSET_MANIFEST_SHA256, hashes)
    manifest = json.loads(manifest_path.read_text())
    require(len(manifest) == ASSET_MANIFEST_ENTRY_COUNT, 'Analysis asset inventory changed')
    base = root / 'web/analysis'
    actual = {path.relative_to(base).as_posix() for path in base.rglob('*') if path.is_file()
              and path.name != 'ASSET_MANIFEST.json' and
              not any(part.startswith('.') or part == '__pycache__' for part in path.relative_to(base).parts)}
    require(actual == set(manifest), 'Installed analysis inventory differs from the reviewed manifest')
    assets = {}
    for relative, metadata in manifest.items():
        verify_asset(root, relative, metadata, assets)
    for model in ['deux', 'game']:
        directory = base / 'models' / model
        expected = set(json.loads((directory / 'manifest.json').read_text())['files'])
        actual_graphs = {path.relative_to(directory).as_posix() for path in directory.rglob('*.onnx')}
        require({name for name in expected if name.endswith('.onnx')} == actual_graphs,
                'Model graph inventory changed: ' + model)
        # These manifests are tracked source; generated ONNX files remain asset bindings.
        relative = 'web/analysis/models/' + model + '/manifest.json'
        hashes[relative] = assets[relative]
    return assets


def verify_clock(root, hashes, evidence_session=None):
    relative = OUT + 'source-clock-verification.json'
    if evidence_session is None:
        path = file(root, relative)
        result = json.loads(path.read_text())
        require(isinstance(result, dict), 'Source-clock receipt is not a JSON object')
        require('evidenceSession' not in result and 'evidenceSessionSchema' not in result,
                'A session-bound source-clock receipt cannot satisfy no-session verification')
    else:
        result = verify_fresh_receipt(root, relative, hashes, evidence_session,
                                      'Source-clock', CLOCK_SOURCES)
    require(result.get('release') == '2.2.4' and result.get('passed') is True and not result.get('errors'),
            'Fresh 2.2.4 source-clock check did not pass')
    require(result.get('samples') == 932143 and result.get('chunks') == 4 and
            result.get('contiguousSourceSamples') is True and result.get('monotonicProgress') is True and
            finite_number(result.get('maxAbsError')) and 0 <= result['maxAbsError'] < 2e-6,
            'Fresh source-clock boundaries failed')
    require(isinstance(result.get('source_hashes'), dict) and
            set(result['source_hashes']) == CLOCK_SOURCES,
            'Fresh source-clock source coverage changed')
    if evidence_session is None:
        for source, expected in result['source_hashes'].items():
            bind(root, source, expected, hashes)
        hashes[relative] = digest(path)
    return result


def verify_browser_receipt(root, hashes, evidence_session):
    return verify_fresh_receipt(root, OUT + 'browser-verification.json', hashes,
                                 evidence_session, 'Browser', BROWSER_SOURCES)


def verify_analysis_browser_receipt(root, hashes, evidence_session):
    return verify_fresh_receipt(root, OUT + 'analysis-browser-verification.json', hashes,
                                 evidence_session, 'Analysis-browser', ANALYSIS_BROWSER_SOURCES)


MDX_COMPARISON_SHA256 = '3e8dc72c4f2659ff6404294c92bb77eb773e7bdf8e7043ca5ca5e916e64fa9ef'
MDX_SOURCES = {
    'version.json', 'android/native-runtime.json',
    'android/src/com/cyberbasslord/lightforge/NativeMdxTask.java',
    'android/src/com/cyberbasslord/lightforge/NativeRuntimeGuard.java',
    'android/src/com/cyberbasslord/lightforge/NativeDeux.java',
    'web/analysis/dsp.js', 'web/analysis/wav-reader.js',
    'web/analysis/separator-mdx.js', 'web/analysis/models/separator-mdx-model.json',
    'web/demo/glass-castle.wav', 'qa/release-1.6.0/fixtures/falcon-mix.wav',
    'qa/release-1.6.0/musdb-fixture-provenance.json', OUT + 'NativeMdxComparisonMain.java',
    OUT + 'compare-mdx-wasm.cjs', OUT + 'compare-native-mdx.py', OUT + 'mdx_numeric.py',
    OUT + 'initial-mdx-absolute-only/compare-native-mdx.py',
    OUT + 'initial-mdx-absolute-only/native-mdx-comparison-verification.json',
    OUT + 'initial-mdx-absolute-only/native-mdx-comparison.log',
    OUT + 'revised-mdx-first-run/compare-native-mdx.py',
    OUT + 'revised-mdx-first-run/mdx_numeric.py',
    OUT + 'revised-mdx-first-run/native-mdx-comparison-verification.json',
    OUT + 'revised-mdx-first-run/native-mdx-comparison.log',
}


def verify_mdx(root, hashes, profile_equivalence, evidence_session=None):
    relative = OUT + 'native-mdx-comparison-verification.json'
    path, result = bind_session_receipt(root, relative, MDX_COMPARISON_SHA256, hashes,
                                        evidence_session, 'MDX comparison')
    require(result.get('release') == '2.2.4' and result.get('passed') is True and not result.get('errors'),
            'Fresh production MDX numerical comparison did not pass')
    adapters = {p.relative_to(root).as_posix() for p in (root / 'tests/native-mdx-host').rglob('*.java')}
    require(bool(adapters) and set(result.get('source_hashes', {})) == MDX_SOURCES | adapters,
            'MDX comparison source coverage changed')
    for source, expected in result['source_hashes'].items():
        if source == 'android/src/com/cyberbasslord/lightforge/NativeDeux.java' and profile_equivalence is not None:
            require(source in hashes and digest(file(root, source)) == hashes[source],
                    'Profiled native predictor differs from its exact-byte equivalence proof')
        else:
            bind(root, source, expected, hashes)
    assets = {'web/analysis/models/uvr-mdx-voc-ft.onnx'} | {
        p.relative_to(root).as_posix() for p in (root / 'web/analysis/vendor').glob('*') if p.is_file()}
    require(set(result.get('analysis_asset_hashes', {})) == assets, 'MDX comparison asset coverage changed')
    for source, expected in result['analysis_asset_hashes'].items():
        bind(root, source, expected, hashes)
    inputs = [{'id': 'demo-start', 'source': 'web/demo/glass-castle.wav', 'start_sample': -3840},
              {'id': 'demo-20s', 'source': 'web/demo/glass-castle.wav', 'start_sample': 878160},
              {'id': 'falcon-start', 'source': 'qa/release-1.6.0/fixtures/falcon-mix.wav', 'start_sample': -3840}]
    require(result.get('inputs') == inputs and result.get('sample_rate') == 44100 and
            result.get('spectrum_floats') == 3145728 and result.get('waveform_samples') == 261120,
            'MDX comparison used a different source boundary or geometry')
    require(result.get('native_runtime') == '1.25.1' and result.get('native_runtime_sha256') == NEW_RUNTIME_SHA256 and
            result.get('wasm_runtime') == '1.20.1', 'MDX comparison runtime identity changed')
    spectral = {'absolute_tolerance': 1e-4, 'relative_tolerance': 1e-5, 'rmse': 1e-5, 'relative_rmse': 1e-3}
    waveform = {'max_absolute_error': 1e-6, 'rmse': 1e-7, 'relative_rmse': 1e-4}
    require(result.get('thresholds') == {'spectrum': spectral, 'waveform': waveform}, 'MDX comparison thresholds changed')
    passages = result.get('passages', [])
    require(len(passages) == 3, 'MDX comparison passage coverage changed')
    for passage, expected_input in zip(passages, inputs):
        require(all(passage.get(k) == v for k, v in expected_input.items()) and passage.get('source_sha256') == hashes[expected_input['source']], 'MDX comparison input binding changed')
        comparisons = passage.get('comparisons', [])
        require(len(comparisons) == 3 and [c.get('output') for c in comparisons] == ['positive', 'negative', 'waveform'],
                'MDX comparison output coverage changed')
        for item, count in zip(comparisons, [3145728, 3145728, 261120]):
            require(item.get('samples') == count and item.get('finite') is True, 'MDX output incomplete or nonfinite')
            for metric in ['max_absolute_error', 'rmse', 'reference_rms', 'relative_rmse']:
                require(finite_number(item.get(metric)) and item[metric] >= 0, 'MDX numerical metric invalid: ' + metric)
            if item['output'] == 'waveform':
                require(item.get('within_thresholds') is True, 'MDX decoded waveform comparison failed')
                for metric, limit in waveform.items():
                    require(item[metric] <= limit, 'MDX decoded waveform threshold failed: ' + metric)
            else:
                violations = item.get('coefficient_violations')
                scaled = item.get('maximum_scaled_error')
                require(type(violations) is int and 0 <= violations <= count and finite_number(scaled) and scaled >= 0, 'MDX coefficient diagnostic invalid')
                require((violations == 0) == (scaled <= 1), 'MDX coefficient diagnostic conflicts with its count')
                diagnostic_pass = violations == 0 and item['rmse'] <= spectral['rmse'] and item['relative_rmse'] <= spectral['relative_rmse']
                require(item.get('within_thresholds') is diagnostic_pass, 'MDX spectral diagnostic was relabeled')
        runs = passage.get('runs', {})
        require(set(runs) == {'native', 'wasm'}, 'MDX runtime run coverage changed')
        for runtime, version in [('native', '1.25.1'), ('wasm', '1.20.1')]:
            require([r.get('polarity') for r in runs[runtime]] == ['positive', 'negative'], 'MDX polarity coverage changed')
            for run in runs[runtime]:
                require(run.get('runtime') == version and finite_number(run.get('seconds')) and run['seconds'] > 0,
                        'MDX runtime metrics are invalid')
        outputs = passage.get('output_hashes', {})
        expected_outputs = {runtime + '-' + kind + '.float32le': count * 4
            for runtime in ['native', 'wasm'] for kind, count in [('positive', 3145728), ('negative', 3145728), ('waveform', 261120)]}
        require(set(outputs) == set(expected_outputs), 'MDX output digest coverage changed')
        for name, count in expected_outputs.items():
            require(outputs[name].get('bytes') == count and re.fullmatch(r'[0-9a-f]{64}', outputs[name].get('sha256', '')),
                    'MDX output digest metadata invalid')
    require(result.get('decoded_waveform_passed') is True, 'MDX decoded waveform qualification missing')
    spectral_pass = all(c['within_thresholds'] for p in passages for c in p['comparisons'] if c['output'] != 'waveform')
    require(result.get('spectral_diagnostic_passed') is spectral_pass, 'MDX aggregate spectral diagnostic was relabeled')
    revision = result.get('protocol_revision', {})
    require(revision.get('revision') == 3 and revision.get('after_prior_failures') is True, 'MDX protocol revision disclosure missing')
    require(revision.get('prior_revised_failure_path') == OUT + 'revised-mdx-first-run/native-mdx-comparison-verification.json', 'Revised MDX failure provenance missing')
    previous_path = bind(root, revision['prior_revised_failure_path'], revision.get('prior_revised_failure_sha256'), hashes)
    previous = json.loads(previous_path.read_text())
    require(previous.get('passed') is False and previous['thresholds'] == result['thresholds'], 'Earlier MDX diagnostic failure was relabeled or tolerances changed')
    require(digest(file(root, OUT + 'revised-mdx-first-run/compare-native-mdx.py')) == previous['source_hashes'][OUT + 'compare-native-mdx.py'], 'Earlier MDX comparator differs from its measured source')
    review = result.get('criterion_review', {})
    require(review.get('initial_failure_path') == OUT + 'initial-mdx-absolute-only/native-mdx-comparison-verification.json', 'Initial MDX criterion failure provenance missing')
    initial_path = bind(root, review['initial_failure_path'], review.get('initial_failure_sha256'), hashes)
    initial = json.loads(initial_path.read_text())
    require(initial.get('passed') is False and bool(initial.get('errors')), 'Original spectral failure was relabeled')
    require(review.get('initial_comparator_path') == OUT + 'initial-mdx-absolute-only/compare-native-mdx.py', 'Initial MDX comparator provenance missing')
    require(review.get('initial_comparator_sha256') == initial['source_hashes'][OUT + 'compare-native-mdx.py'], 'Initial MDX comparator differs from the failed measurement')
    bind(root, review['initial_comparator_path'], review.get('initial_comparator_sha256'), hashes)
    return result



DOWNSTREAM_SHA256 = '8742d94afae00533041e8bac86ce53bfb05c7df695eb5a864b5f32169a221468'
DOWNSTREAM_SOURCES = {
    'version.json', OUT + 'verify-mdx-downstream.cjs', OUT + 'mdx-downstream-compare.cjs',
    'tests/mdx-downstream-compare.test.cjs', 'web/analysis/vocal.js',
    'web/analysis/vocal-detail.js', 'web/analysis/game.js', 'web/analysis/dsp.js',
    'web/analysis/stem-cache.js', 'web/analysis/wav-reader.js', 'web/analysis/separator-mdx.js',
    'web/analysis/worker.js', 'web/analysis/models/features.json',
    'web/analysis/models/vocal-model.json', 'web/analysis/models/vocal-frontend.json',
    'web/analysis/models/game/manifest.json', 'web/analysis/models/separator-mdx-model.json',
    'web/demo/glass-castle.wav',
}


def verify_downstream_upstream(result, hashes, evidence_session):
    if evidence_session is None:
        require('upstreamMdx' not in result,
                'A session-bound downstream receipt cannot satisfy no-session verification')
        return
    expected_upstream = {
        'path': OUT + 'native-mdx-comparison-verification.json',
        'sha256': hashes[OUT + 'native-mdx-comparison-verification.json'],
        'evidenceSession': evidence_session,
    }
    require(result.get('upstreamMdx') == expected_upstream,
            'Downstream receipt is not bound to the current MDX receipt, session, and outputs')


def verify_downstream(root, hashes, mdx, evidence_session=None):
    relative = OUT + 'native-mdx-downstream-verification.json'
    path, result = bind_session_receipt(root, relative, DOWNSTREAM_SHA256, hashes,
                                        evidence_session, 'Downstream')
    require(result.get('release') == '2.2.4' and result.get('passed') is True and not result.get('errors'),
            'Mandatory paired downstream GAME and vocal-feature verification did not pass')
    require(set(result.get('source_hashes', {})) == DOWNSTREAM_SOURCES,
            'Downstream verification source coverage changed')
    for source, expected in result['source_hashes'].items():
        bind(root, source, expected, hashes)
    game = json.loads(file(root, 'web/analysis/models/game/manifest.json').read_text())
    vocal = json.loads(file(root, 'web/analysis/models/vocal-model.json').read_text())
    assets = {'web/analysis/models/game/' + name for name in game['files']} | {
        'web/analysis/models/' + vocal['file']} | {
        p.relative_to(root).as_posix() for p in (root / 'web/analysis/vendor').glob('*') if p.is_file()}
    require(set(result.get('analysis_asset_hashes', {})) == assets, 'Downstream model/runtime asset coverage changed')
    for source, expected in result['analysis_asset_hashes'].items():
        bind(root, source, expected, hashes)
    fixture = {'id': 'demo-20s', 'source': 'web/demo/glass-castle.wav',
        'sourceSha256': hashes['web/demo/glass-castle.wav'], 'contextReadStart': 878160,
        'contextReadSamples': 261120, 'coreStart': 882000, 'coreSamples': 253440, 'sampleRate': 44100}
    require(result.get('fixture') == fixture, 'Downstream fixture/source-clock coverage changed')
    verify_downstream_upstream(result, hashes, evidence_session)
    measured = next(p for p in mdx['passages'] if p['id'] == fixture['id'])
    require(set(result.get('inputs', {})) == {'native', 'wasm'} and set(result.get('runs', {})) == {'native', 'wasm'},
            'Downstream paired-runtime coverage changed')
    outputs = []
    for runtime in ['native', 'wasm']:
        name = runtime + '-waveform.float32le'
        require(result['inputs'][runtime] == {'file': name, **measured['output_hashes'][name]},
                'Downstream input is not the measured production MDX waveform')
        run = result['runs'][runtime]
        require(run.get('runtime') == '1.20.1', 'Downstream runtime identity changed')
        expected_clock = {'fixture': 'demo-20s', 'source': fixture['source'], 'coreStartSample': 882000,
            'coreSamples': 253440, 'sampleRate': 44100, 'contextReadStart': 878160, 'contextReadSamples': 261120}
        require(run.get('sourceClock') == expected_clock, 'Downstream retained output changed source clock')
        expected_executions = {'segmenter': 8, 'encoder': 1, 'dur2bd': 1, 'bd2dur': 1, 'estimator': 1, 'frameMn10': 1}
        require(run.get('executions') == expected_executions, 'Downstream did not execute every required graph step')
        require(bool(run.get('loadedModels')), 'Downstream model execution inventory missing')
        for source, expected in run['loadedModels'].items():
            require(source in assets and result['analysis_asset_hashes'][source] == expected,
                    'Downstream executed an unbound model')
        output = run.get('output', {})
        filename = OUT + 'native-mdx-downstream-' + runtime + '.json'
        measured_output = bind(root, filename, output.get('sha256'), hashes)
        require(type(output.get('bytes')) is int and output['bytes'] > 0 and measured_output.stat().st_size == output['bytes'],
                'Downstream measured output byte count changed')
        details = json.loads(measured_output.read_text())
        require(details.get('waveformSha256') == result['inputs'][runtime]['sha256'] and
                details.get('executions') == run['executions'] and details.get('loadedModels') == run['loadedModels'] and
                details.get('samples44100') == 253440 and details.get('samples22050') == 126720,
                'Downstream output provenance or sample geometry changed')
        outputs.append(measured_output)
    # Recompute the full fixed comparison from exact retained model outputs.
    # This validates all categorical decisions, notes, arrays, tolerances,
    # nonempty singing coverage and eight-step execution without rerunning ORT.
    script = "const fs=require('fs');const {compare,thresholds}=require(process.argv[1]);const read=p=>{const {waveformSha256,...value}=JSON.parse(fs.readFileSync(p));return value;};process.stdout.write(JSON.stringify({comparison:compare(read(process.argv[2]),read(process.argv[3])),thresholds}));"
    verification = json.loads(subprocess.check_output(['node', '-e', script,
        str(file(root, OUT + 'mdx-downstream-compare.cjs')), *map(str, outputs)], cwd=root, text=True))
    require(verification['comparison'].get('passed') is True and not verification['comparison'].get('errors'),
            'Retained downstream outputs fail the full fixed comparison')
    require(result.get('comparison') == verification['comparison'] and result.get('thresholds') == verification['thresholds'],
            'Downstream receipt differs from recomputed output metrics, coverage or fixed thresholds')
    return result


def verify_release(root=ROOT):
    root = Path(root).resolve()
    version_path = file(root, 'version.json')
    require(json.loads(version_path.read_text()) == {'name': '2.2.4', 'code': 20204},
            'This evidence protocol belongs only to 2.2.4 / 20204')
    evidence_session = current_evidence_session()
    hashes = {'version.json': digest(version_path)}
    comparison, mutable_comparison_sources = verify_comparison(root, hashes)
    profile_equivalence = verify_profile_equivalence(root, hashes, comparison,
                                                      mutable_comparison_sources, evidence_session)
    assets = verify_assets(root, hashes)
    clock = verify_clock(root, hashes, evidence_session)
    browser = analysis_browser = None
    if evidence_session is not None:
        browser = verify_browser_receipt(root, hashes, evidence_session)
        analysis_browser = verify_analysis_browser_receipt(root, hashes, evidence_session)
    mdx = verify_mdx(root, hashes, profile_equivalence, evidence_session)
    downstream = verify_downstream(root, hashes, mdx, evidence_session)
    hashes[OUT + 'verify-analysis.py'] = digest(file(root, OUT + 'verify-analysis.py'))
    for relative, expected in {**hashes, **assets}.items():
        require(digest(file(root, relative)) == expected, 'Source changed during analysis verification: ' + relative)
    receipt = {
        'release': '2.2.4', 'passed': True, 'errors': [], 'source_hashes': hashes,
        'analysis_asset_hashes': assets,
        'analysis_asset_binding': {'manifest_path': 'web/analysis/ASSET_MANIFEST.json',
            'manifest_sha256': ASSET_MANIFEST_SHA256, 'verified_asset_count': len(assets),
            'scope': f'All {len(assets)} installed analysis assets passed complete byte-count and SHA-256 checks. Generated model graphs are bound separately from checkout source files; the release publisher independently verifies their packaged bytes.'},
        'scope': 'Pinned matched Linux/JVM full-passage Deux runtime comparison, a mandatory same-session exact-byte unprofiled-versus-profiled Deux observer proof, fresh production native MDX versus CPU WASM comparison, fresh production source-clock regression, and exact verification of all bundled analysis assets. This is not a new corpus accuracy benchmark, Android/ARM64 crash reproduction, phone performance result, or validation of background compatibility fallback.',
        'checks': [
            'Pinned host evidence compares actually loaded ONNX Runtime 1.23.2 and 1.25.1 using the originally measured production predictor code, original unquantized models, source audio, and startSample=-66150.',
            'Both runtime runs completed two finite 573300-sample stems and satisfy the predeclared absolute and relative numerical thresholds; exact differences are recorded in the bound comparison.',
            'The native profile collector always has a fresh same-JVM 13-second unprofiled-versus-profiled proof: both complete finite stems must be byte-identical with zero predeclared numerical error, while the historical 1.25.1 SHA-256 remains context only. A canonical full profile-record digest/topology and source/model/session bindings are mandatory.',
            f'All {len(assets)} analysis assets match the current reviewed inventory, including all 27 Deux graphs and every GAME graph.',
            'Fresh 2.2.4 source-clock execution preserves all 932143 samples across four overlapping windows, including the final odd sample.',
            'Fresh production NativeMdxTask and bundled CPU WASM compare three fixed inputs with unchanged graph weights and both polarity passes. Strict decoded waveform equivalence is mandatory; internal spectral diagnostics retain any failed coefficient comparisons, with protocol revision history preserved.',
            'The same measured demo-20s waveforms pass separately executed production resampling, voice classification, vocal features and all eight GAME transcription steps; the complete retained downstream outputs are re-compared, including nonempty singing coverage and categorical decisions.',
            'Current full-browser inference, Android background lifecycle and native-crash fallback tests are separate mandatory release gates.'
        ],
        'fresh_native_runtime_comparison': {'path': OUT + 'native-runtime-comparison-verification.json',
            'sha256': COMPARISON_SHA256, 'runs': comparison['runs'], 'comparison': comparison['comparison'],
            'scope': comparison['scope']},
        'native_inference_profile_equivalence': {
            'path': PROFILE_EQUIVALENCE_PATH, 'sha256': hashes[PROFILE_EQUIVALENCE_PATH],
            'evidence_session': profile_equivalence['evidence_session'], 'criteria': profile_equivalence['criteria'],
            'result': profile_equivalence['result'], 'scope': profile_equivalence['scope']},
        'fresh_native_mdx_comparison': {'path': OUT + 'native-mdx-comparison-verification.json', 'sha256': hashes[OUT + 'native-mdx-comparison-verification.json'], 'passages': mdx['passages'], 'scope': mdx['scope'], 'decoded_waveform_passed': mdx['decoded_waveform_passed'], 'spectral_diagnostic_passed': mdx['spectral_diagnostic_passed'], 'protocol_revision': mdx['protocol_revision']},
        'fresh_native_mdx_downstream': {'path': OUT + 'native-mdx-downstream-verification.json', 'sha256': hashes[OUT + 'native-mdx-downstream-verification.json'], 'scope': downstream.get('scope'), 'fixture': downstream['fixture'], 'coverage': downstream['comparison']['coverage'], 'thresholds': downstream['thresholds']},
        'evidence_session': evidence_session,
        'fresh_source_clock': {'path': OUT + 'source-clock-verification.json',
            'sha256': hashes[OUT + 'source-clock-verification.json'], 'samples': clock['samples'],
            'chunks': clock['chunks'], 'maxAbsError': clock['maxAbsError'], 'scope': clock.get('scope')},
        'limitations': ['No previous release execution is relabeled as current; the old runtime is only the newly executed comparison baseline.',
                       'The native prediction comparison ran on Linux x86_64 and does not exercise ARM instruction dispatch.',
                       'No claim of physical phone crash resolution, full-song performance or Tesla timing is implied.'],
        'completedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    if evidence_session is not None:
        receipt['session_evidence_receipts'] = {
            'source_clock': {'path': OUT + 'source-clock-verification.json',
                             'sha256': hashes[OUT + 'source-clock-verification.json'],
                             'evidenceSession': evidence_session},
            'browser': {'path': OUT + 'browser-verification.json',
                        'sha256': hashes[OUT + 'browser-verification.json'],
                        'evidenceSession': evidence_session, 'scope': browser.get('scope')},
            'analysis_browser': {'path': OUT + 'analysis-browser-verification.json',
                                 'sha256': hashes[OUT + 'analysis-browser-verification.json'],
                                 'evidenceSession': evidence_session,
                                 'scope': analysis_browser.get('scope')},
            'native_mdx': {'path': OUT + 'native-mdx-comparison-verification.json',
                           'sha256': hashes[OUT + 'native-mdx-comparison-verification.json'],
                           'evidenceSession': evidence_session},
            'native_mdx_downstream': {'path': OUT + 'native-mdx-downstream-verification.json',
                                      'sha256': hashes[OUT + 'native-mdx-downstream-verification.json'],
                                      'evidenceSession': evidence_session},
            'native_profile_equivalence': {'path': PROFILE_EQUIVALENCE_PATH,
                                           'sha256': hashes[PROFILE_EQUIVALENCE_PATH],
                                           'evidenceSession': evidence_session},
        }
    return receipt


def main():
    output = ROOT / OUT / 'analysis-verification.json'
    # Replace any old pass before reading a producer receipt. A killed or failed
    # refresh therefore remains visibly failed rather than inheriting stale proof.
    write_atomic(output, {'release': '2.2.4', 'passed': False, 'errors': []})
    try:
        receipt = verify_release()
    except Exception as error:
        # Never leave a stale passing receipt after a failed refresh.
        receipt = {'release': '2.2.4', 'passed': False, 'errors': [str(error)]}
        write_atomic(output, receipt)
        raise
    write_atomic(output, receipt)
    print(json.dumps({'passed': True, 'release': receipt['release'], 'checks': receipt['checks']}, indent=2))


if __name__ == '__main__':
    main()

