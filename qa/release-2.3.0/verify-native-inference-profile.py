#!/usr/bin/env python3
"""Prove that native Deux profiling is an exact same-runtime observer.

The historical current-runtime digest remains in this receipt as reproducibility
context. It is deliberately not the profile pass condition: the profile gate
compares fresh unprofiled and profiled full passages from the same JVM/runtime,
then fails closed unless both complete float outputs are finite and byte-identical.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import re
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RELEASE = '2.3.0'
HISTORICAL_OUT = ROOT / 'qa/release-2.2.4'
START_SAMPLE = -66150
SAMPLES_PER_STEM = 573300
SCHEMA = 'lightforge.native-inference-profile-equivalence.v2'
SESSION_PATTERN = re.compile(r'[0-9a-f]{32,128}\Z')
PROFILE_RECORD_MAGIC = b'lightforge.native-inference-profile-records.v1\0'
PAIR_CRITERIA = {
    'stems': 2,
    'samples_per_stem': SAMPLES_PER_STEM,
    'output_bytes': 2 * SAMPLES_PER_STEM * 4,
    'finite_required': True,
    'byte_identity_required': True,
    'max_absolute_error': 0.0,
    'rmse': 0.0,
    'relative_rmse': 0.0,
}
EXPECTED_STAGES = sorted([
    'inference-gate-wait', 'cache-preflight', 'buffer-init', 'runtime-setup',
    'pcm-read', 'feature-encode', 'model-init', 'tensor-bind', 'inference',
    'pack', 'scatter', 'decode', 'output-write', 'output-flush', 'output-commit',
])
EXPECTED_GRAPHS = sorted(['front', 'head-0', 'head-1'] + [
    'block-%02d-%s' % (block, axis) for block in range(12)
    for axis in ('time', 'frequency')
])
SOURCE_NAMES = (
    'android/src/com/cyberbasslord/lightforge/NativeDeux.java',
    'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java',
    'android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java',
    'android/src/com/cyberbasslord/lightforge/NativeInferenceProfileOutputComparison.java',
    'android/src/com/cyberbasslord/lightforge/NativePassageTask.java',
    'android/src/com/cyberbasslord/lightforge/AppDiagnostics.java',
    'tests/NativeInferenceProfileEquivalenceTest.java',
    'tests/NativeInferenceProfilePairComparisonTest.java',
    'tests/NativeInferenceProfileTest.java',
    'tests/verify_native_release.py',
    'tests/test_native_inference_profile_evidence.py',
    'android/native-runtime.json',
    'web/analysis/models/deux/manifest.json',
    'web/demo/glass-castle.wav',
    'qa/release-2.2.4/native-runtime-comparison-verification.json',
    'qa/release-2.2.4/compare-native-runtime.py',
    'qa/release-2.3.0/verify-native-inference-profile.py',
    'qa/release-2.3.0/verify-analysis.py',
)
TOOLS = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain'))
JAVA = Path(os.environ.get('LIGHTFORGE_JAVA_HOME', TOOLS / 'jdk17')) / 'bin'


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def write_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
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


def hash_sources():
    return {name: sha256(ROOT / name) for name in SOURCE_NAMES}


def profile_models(models):
    manifest = json.loads((models / 'manifest.json').read_text())
    inventory = manifest.get('files', {})
    require(len(inventory) == 27, 'The required complete Deux graph inventory is unavailable.')
    hashes = {}
    for name, item in inventory.items():
        graph = models / name
        require(graph.is_file() and graph.stat().st_size == item.get('bytes') and sha256(graph) == item.get('sha256'),
                'A profiled graph differs from the reviewed inventory: ' + name)
        hashes['web/analysis/models/deux/' + name] = item['sha256']
    return hashes


def parse_profile_records(path):
    data = path.read_bytes()
    require(data.startswith(PROFILE_RECORD_MAGIC), 'Canonical profile record header is absent.')
    offset = len(PROFILE_RECORD_MAGIC)
    require(offset + 4 <= len(data), 'Canonical profile record count is absent.')
    count = struct.unpack_from('>I', data, offset)[0]
    offset += 4
    records = []
    for _ in range(count):
        require(offset + 4 <= len(data), 'Canonical profile record length is truncated.')
        length = struct.unpack_from('>I', data, offset)[0]
        offset += 4
        require(length <= len(data) - offset, 'Canonical profile record payload is truncated.')
        raw = data[offset:offset + length]
        offset += length
        record = raw.decode('utf-8')
        require('\n' not in record and '\r' not in record, 'Canonical profile record contains a line separator.')
        records.append(record)
    require(offset == len(data), 'Canonical profile record payload has trailing bytes.')
    return records


def profile_topology(records):
    require(len(records) == 43, 'Profile record inventory is incomplete.')
    summary = records[0]
    for token in ('schema=native-inference-profile-v2', 'outcome=completed', 'stageRecords=15', 'graphRecords=27',
                  'droppedStageRecords=0', 'droppedGraphRecords=0', 'acceleratorTelemetry=unavailable'):
        require(token in summary, 'Profile summary is missing required telemetry: ' + token)
    stages, graphs = [], []
    for record in records[1:]:
        fields = dict(piece.split('=', 1) for piece in record.split(' ') if '=' in piece)
        if record.startswith('schema=native-inference-stage-v1 '):
            require({'stage', 'samples', 'wallMs', 'cpuTelemetry', 'cpuMs', 'heapTelemetry', 'heapObservedBytes'} <= set(fields),
                    'Profile stage record is incomplete.')
            stages.append(fields['stage'])
        elif record.startswith('schema=native-inference-graph-v2 '):
            require({'graph', 'cpuTelemetry', 'heapTelemetry', 'heapObservedBytes', 'runCount', 'runWallMs', 'runCpuMs'} <= set(fields),
                    'Profile graph record is incomplete.')
            require(fields['runCount'] != '0', 'Profile graph was not executed.')
            graphs.append(fields['graph'])
        else:
            raise RuntimeError('Canonical profile record uses an unknown schema.')
    require(sorted(stages) == EXPECTED_STAGES and len(set(stages)) == len(stages), 'Profile stage topology changed.')
    require(sorted(graphs) == EXPECTED_GRAPHS and len(set(graphs)) == len(graphs), 'Profile graph topology changed.')
    return {
        'summary_schema': 'native-inference-profile-v2',
        'stage_schema': 'native-inference-stage-v1',
        'graph_schema': 'native-inference-graph-v2',
        'stages': EXPECTED_STAGES,
        'graphs': EXPECTED_GRAPHS,
    }


def validate_pair_result(measured, evidence_session, approved_historical, unprofiled, profiled, records):
    expected_keys = {
        'evidenceSession', 'historicalApprovedSha256', 'unprofiledOutputSha256', 'profiledOutputSha256',
        'unprofiledOutputBytes', 'profiledOutputBytes', 'byteIdentical', 'unprofiledMatchesHistorical',
        'profiledMatchesHistorical', 'criteria', 'profile', 'comparison',
    }
    require(set(measured) == expected_keys, 'Paired profile result schema changed.')
    require(measured['evidenceSession'] == evidence_session, 'Paired profile result used a different evidence session.')
    require(measured['historicalApprovedSha256'] == approved_historical, 'Paired profile result lost historical context.')
    require(measured['criteria'] == PAIR_CRITERIA, 'Paired profile criteria changed.')
    unprofiled_digest, profiled_digest = sha256(unprofiled), sha256(profiled)
    require(unprofiled.stat().st_size == PAIR_CRITERIA['output_bytes'] and profiled.stat().st_size == PAIR_CRITERIA['output_bytes'],
            'Paired profile output is incomplete.')
    require(measured['unprofiledOutputBytes'] == unprofiled.stat().st_size and measured['profiledOutputBytes'] == profiled.stat().st_size and
            measured['unprofiledOutputSha256'] == unprofiled_digest and measured['profiledOutputSha256'] == profiled_digest,
            'Paired profile output digest binding failed.')
    require(measured['byteIdentical'] is True and unprofiled_digest == profiled_digest,
            'Profile observer changed same-runtime output bytes.')
    require(measured['unprofiledMatchesHistorical'] is (unprofiled_digest == approved_historical) and
            measured['profiledMatchesHistorical'] is (profiled_digest == approved_historical),
            'Historical digest context was relabeled.')
    comparisons = measured['comparison']
    require(isinstance(comparisons, list) and len(comparisons) == 2 and
            [item.get('stem') for item in comparisons] == ['vocals', 'accompaniment'],
            'Paired profile stem coverage changed.')
    for item in comparisons:
        require(item.get('samples') == SAMPLES_PER_STEM and item.get('finite') is True and item.get('identical') is True,
                'Paired profile output is incomplete, nonfinite or nonidentical.')
        for metric in ('max_absolute_error', 'rmse', 'relative_rmse'):
            value = item.get(metric)
            require(type(value) in {int, float} and value == 0.0, 'Paired profile comparison exceeds zero ' + metric + '.')
    profile = measured['profile']
    require(set(profile) == {'record_sha256', 'record_bytes', 'records', 'stage_records', 'graph_records', 'topology'},
            'Profile receipt result schema changed.')
    require(profile['record_sha256'] == sha256(records) and profile['record_bytes'] == records.stat().st_size,
            'Canonical profile record digest binding failed.')
    topology = profile_topology(parse_profile_records(records))
    require(profile['records'] == 43 and profile['stage_records'] == 15 and profile['graph_records'] == 27 and
            profile['topology'] == topology, 'Canonical profile topology differs from the production passage.')


def _run(output, evidence_session):
    require(evidence_session is None or SESSION_PATTERN.fullmatch(evidence_session), 'LIGHTFORGE_EVIDENCE_SESSION is invalid.')
    runtime = json.loads((ROOT / 'android/native-runtime.json').read_text())
    comparison_path = HISTORICAL_OUT / 'native-runtime-comparison-verification.json'
    comparison = json.loads(comparison_path.read_text())
    baseline = next((item for item in comparison.get('runs', []) if item.get('version') == runtime.get('version')), None)
    require(baseline is not None and isinstance(baseline.get('sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', baseline['sha256']),
            'The historical current-runtime output digest is unavailable.')
    models = ROOT / 'web/analysis/models/deux'
    audio = ROOT / 'web/demo/glass-castle.wav'
    evidence = {
        'schema': SCHEMA,
        'release': RELEASE,
        'passed': False,
        'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'evidence_session': evidence_session,
        'scope': 'Fresh same-JVM 13-second unprofiled-versus-profiled native Deux observer proof. Complete outputs must be finite and byte-identical at zero predeclared numerical error. The historical current-runtime SHA-256 is reproducibility context only, not a profile pass criterion. This is not Android/ARM64, full-song, thermal or performance measurement.',
        'source_hashes': hash_sources(),
        'baseline': {
            'comparison_path': 'qa/release-2.2.4/native-runtime-comparison-verification.json',
            'comparison_sha256': sha256(comparison_path),
            'runtime_version': runtime.get('version'),
            'historical_approved_output_sha256': baseline['sha256'],
            'start_sample': START_SAMPLE,
            'input_audio_sha256': sha256(audio),
            'input_audio_bytes': audio.stat().st_size,
        },
        'criteria': PAIR_CRITERIA,
        'checks': [],
    }
    try:
        for command in [JAVA / 'javac', JAVA / 'java']:
            require(command.is_file(), 'Pinned host JDK is unavailable: ' + command.name)
        android = Path(os.environ.get('ANDROID_SDK_ROOT', TOOLS / 'android-sdk')) / 'platforms/android-35/android.jar'
        host_runtime = TOOLS / 'onnx' / runtime['host']['name']
        json_jar = TOOLS / 'test-json.jar'
        for dependency in [android, host_runtime, json_jar, models / 'manifest.json', audio]:
            require(dependency.is_file(), 'Required verified host dependency is unavailable: ' + dependency.name)
        require(host_runtime.stat().st_size == runtime['host']['bytes'] and sha256(host_runtime) == runtime['host']['sha256'],
                'Pinned host ONNX Runtime differs from android/native-runtime.json.')
        predictor_source = (ROOT / 'android/src/com/cyberbasslord/lightforge/NativeDeux.java').read_text()
        require('public static final String RUNTIME_VERSION="1.25.1";' in predictor_source,
                'The profile-enabled predictor no longer exposes the reviewed native runtime identity.')
        comparator = (HISTORICAL_OUT / 'compare-native-runtime.py').read_text()
        require('NativeInferenceProfile.java' in comparator and '*source_files[:4]' in comparator,
                'The maintained full-runtime comparator does not compile the profile collector.')
        evidence['model_asset_hashes'] = profile_models(models)
        evidence['runtime_bindings'] = {
            'android_api_jar_sha256': sha256(android),
            'android_api_jar_bytes': android.stat().st_size,
            'host_onnx_runtime_sha256': sha256(host_runtime),
            'host_onnx_runtime_bytes': host_runtime.stat().st_size,
            'test_json_jar_sha256': sha256(json_jar),
            'test_json_jar_bytes': json_jar.stat().st_size,
        }
        with tempfile.TemporaryDirectory(prefix='lightforge-native-profile-') as temporary:
            work = Path(temporary)
            classes = work / 'classes'
            classes.mkdir()
            stub = work / 'AppDiagnostics.java'
            stub.write_text('package com.cyberbasslord.lightforge; public final class AppDiagnostics { public static void log(android.content.Context c,String l,String s,String m){} public static boolean flush(long timeout){return true;} }\n')
            sources = [
                ROOT / 'android/src/com/cyberbasslord/lightforge/NativeDeux.java',
                ROOT / 'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java',
                ROOT / 'android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java',
                ROOT / 'android/src/com/cyberbasslord/lightforge/NativeInferenceProfileOutputComparison.java',
                ROOT / 'tests/NativeInferenceProfileEquivalenceTest.java',
                ROOT / 'tests/NativeInferenceProfilePairComparisonTest.java', stub,
            ]
            compile_cp = os.pathsep.join(map(str, [android, host_runtime, json_jar]))
            compiled = subprocess.run([str(JAVA / 'javac'), '--release', '8', '-encoding', 'UTF-8', '-classpath', compile_cp,
                                        '-d', str(classes), *map(str, sources)], cwd=ROOT, capture_output=True, text=True, timeout=90)
            require(compiled.returncode == 0, 'Profile equivalence host compile failed: ' + (compiled.stdout + compiled.stderr)[-2000:])
            classpath = os.pathsep.join(map(str, [classes, json_jar, android, host_runtime]))
            comparator_test = subprocess.run([str(JAVA / 'java'), '-cp', classpath,
                                              'com.cyberbasslord.lightforge.NativeInferenceProfilePairComparisonTest'],
                                             cwd=ROOT, capture_output=True, text=True, timeout=30)
            require(comparator_test.returncode == 0 and 'passed' in comparator_test.stdout,
                    'Profile pair comparator contract test failed: ' + (comparator_test.stdout + comparator_test.stderr)[-2000:])
            unprofiled_path, profiled_path, records_path = work / 'unprofiled.float32le', work / 'profiled.float32le', work / 'profile-records.bin'
            executed = subprocess.run([str(JAVA / 'java'), '-cp', classpath,
                                        'com.cyberbasslord.lightforge.NativeInferenceProfileEquivalenceTest',
                                        str(models), str(audio), str(unprofiled_path), str(profiled_path), str(records_path),
                                        str(START_SAMPLE), baseline['sha256'], evidence_session or '-'],
                                       cwd=ROOT, capture_output=True, text=True, timeout=900)
            require(executed.returncode == 0, 'Profile equivalence execution failed: ' + (executed.stdout + executed.stderr)[-4000:])
            rows = [json.loads(line) for line in executed.stdout.splitlines() if line.startswith('{"evidenceSession":')]
            require(len(rows) == 1, 'Profile equivalence did not emit exactly one bounded paired receipt.')
            measured = rows[0]
            validate_pair_result(measured, evidence_session, baseline['sha256'], unprofiled_path, profiled_path, records_path)
            evidence['result'] = measured
        evidence['source_hashes_after'] = hash_sources()
        evidence['model_asset_hashes_after'] = profile_models(models)
        require(evidence['source_hashes_after'] == evidence['source_hashes'], 'Profile source/test/gate bindings changed during verification.')
        require(evidence['model_asset_hashes_after'] == evidence['model_asset_hashes'], 'Profile model bindings changed during verification.')
        evidence['checks'].extend([
            'All 27 reviewed Deux ONNX graph bytes match the current model manifest before and after inference.',
            'The paired production predictor and strict float comparator compiled with the pinned Android API, org.json dependency and host ONNX Runtime.',
            'The complete fixed passage ran once unprofiled and once with NativeInferenceProfile in the same JVM/runtime; both float outputs are complete, finite and byte-identical with zero max/RMS/relative error.',
            'The canonical full profile record stream is SHA-256-bound and has one summary, 15 host-observable stages and exactly 27 executed graph records; no graph was dropped.',
            'The historical current-runtime digest is retained as context only; it is not required to match either fresh paired output.',
        ])
        evidence['passed'] = True
    except Exception as error:
        evidence['failure'] = str(error)
        raise
    finally:
        write_atomic(output, evidence)
    print(json.dumps({'passed': evidence['passed'], 'evidence_session': evidence_session, 'result': evidence.get('result'), 'checks': evidence['checks']}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUT / 'native-inference-profile-equivalence.json')
    args = parser.parse_args()
    output = args.output.resolve()
    evidence_session = os.environ.get('LIGHTFORGE_EVIDENCE_SESSION')
    failure = {'schema': SCHEMA, 'release': RELEASE, 'passed': False, 'errors': []}
    write_atomic(output, failure)
    try:
        _run(output, evidence_session)
    except Exception as error:
        try:
            current = json.loads(output.read_text())
        except (OSError, UnicodeError, json.JSONDecodeError):
            current = failure
        if not isinstance(current, dict) or current.get('schema') != SCHEMA or current.get('passed') is not False:
            current = failure
        if not current.get('failure'):
            current['failure'] = str(error)
            current.setdefault('errors', []).append(str(error))
            write_atomic(output, current)
        raise


if __name__ == '__main__':
    main()
