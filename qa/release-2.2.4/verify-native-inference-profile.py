#!/usr/bin/env python3
"""Run profile-enabled production Deux once and require its approved output bytes.

This is deliberately an equivalence gate, not a performance claim. It uses the
same 13-second fixture and current pinned host runtime as the immutable 2.2.4
comparison, but enables the new timing collector so observational work cannot
silently alter audio output or omit a graph from the diagnostic receipt.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RELEASE = '2.2.4'
START_SAMPLE = -66150
SAMPLES_PER_STEM = 573300
SCHEMA = 'lightforge.native-inference-profile-equivalence.v1'
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUT / 'native-inference-profile-equivalence.json')
    args = parser.parse_args()
    output = args.output.resolve()
    runtime = json.loads((ROOT / 'android/native-runtime.json').read_text())
    comparison_path = OUT / 'native-runtime-comparison-verification.json'
    comparison = json.loads(comparison_path.read_text())
    baseline = next((item for item in comparison.get('runs', []) if item.get('version') == runtime.get('version')), None)
    require(baseline is not None and isinstance(baseline.get('sha256'), str) and len(baseline['sha256']) == 64,
            'The approved current-runtime output digest is unavailable.')
    models = ROOT / 'web/analysis/models/deux'
    audio = ROOT / 'web/demo/glass-castle.wav'
    source_names = [
        'android/src/com/cyberbasslord/lightforge/NativeDeux.java',
        'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java',
        'android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java',
        'tests/NativeInferenceProfileEquivalenceTest.java',
        'android/native-runtime.json', 'web/analysis/models/deux/manifest.json',
        'web/demo/glass-castle.wav',
        'qa/release-2.2.4/native-runtime-comparison-verification.json',
        'qa/release-2.2.4/compare-native-runtime.py',
        'qa/release-2.2.4/verify-native-inference-profile.py',
    ]
    evidence = {
        'schema': SCHEMA, 'release': RELEASE, 'passed': False,
        'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'scope': 'Fresh Linux/JVM 13-second exact-byte equivalence with NativeInferenceProfile enabled; not an Android/ARM64, full-song, thermal or performance measurement.',
        'source_hashes': {name: sha256(ROOT / name) for name in source_names},
        'baseline': {
            'comparison_path': 'qa/release-2.2.4/native-runtime-comparison-verification.json',
            'comparison_sha256': sha256(comparison_path),
            'runtime_version': runtime.get('version'),
            'approved_output_sha256': baseline['sha256'],
            'start_sample': START_SAMPLE,
        },
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
        manifest = json.loads((models / 'manifest.json').read_text())
        inventory = manifest.get('files', {})
        require(len(inventory) == 27, 'The required complete Deux graph inventory is unavailable.')
        predictor_source = (ROOT / 'android/src/com/cyberbasslord/lightforge/NativeDeux.java').read_text()
        require('public static final String RUNTIME_VERSION="1.25.1";' in predictor_source,
                'The profile-enabled predictor no longer exposes the reviewed native runtime identity.')
        comparator = (OUT / 'compare-native-runtime.py').read_text()
        require('NativeInferenceProfile.java' in comparator and '*source_files[:4]' in comparator,
                'The maintained full-runtime comparator does not compile the profile collector.')
        model_hashes = {}
        for name, item in inventory.items():
            graph = models / name
            require(graph.is_file() and graph.stat().st_size == item.get('bytes') and sha256(graph) == item.get('sha256'),
                    'A profiled graph differs from the reviewed inventory: ' + name)
            model_hashes['web/analysis/models/deux/' + name] = item['sha256']
        evidence['model_asset_hashes'] = model_hashes
        with tempfile.TemporaryDirectory(prefix='lightforge-native-profile-') as temporary:
            work = Path(temporary)
            classes = work / 'classes'; classes.mkdir()
            stub = work / 'AppDiagnostics.java'
            stub.write_text('package com.cyberbasslord.lightforge; public final class AppDiagnostics { public static void log(android.content.Context c,String l,String s,String m){} public static boolean flush(long timeout){return true;} }\n')
            sources = [
                ROOT / 'android/src/com/cyberbasslord/lightforge/NativeDeux.java',
                ROOT / 'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java',
                ROOT / 'android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java',
                ROOT / 'tests/NativeInferenceProfileEquivalenceTest.java', stub,
            ]
            compile_cp = os.pathsep.join(map(str, [android, host_runtime, json_jar]))
            compiled = subprocess.run([str(JAVA / 'javac'), '--release', '8', '-encoding', 'UTF-8', '-classpath', compile_cp,
                                        '-d', str(classes), *map(str, sources)], cwd=ROOT, capture_output=True, text=True, timeout=90)
            require(compiled.returncode == 0, 'Profile equivalence host compile failed: ' + (compiled.stdout + compiled.stderr)[-2000:])
            result_path = work / 'profiled.float32le'
            classpath = os.pathsep.join(map(str, [classes, json_jar, android, host_runtime]))
            executed = subprocess.run([str(JAVA / 'java'), '-cp', classpath,
                                        'com.cyberbasslord.lightforge.NativeInferenceProfileEquivalenceTest',
                                        str(models), str(audio), str(result_path), str(START_SAMPLE), baseline['sha256']],
                                       cwd=ROOT, capture_output=True, text=True, timeout=900)
            require(executed.returncode == 0, 'Profile equivalence execution failed: ' + (executed.stdout + executed.stderr)[-4000:])
            rows = [json.loads(line) for line in executed.stdout.splitlines() if line.startswith('{"outputSha256":')]
            require(len(rows) == 1, 'Profile equivalence did not emit exactly one bounded receipt.')
            measured = rows[0]
            require(measured == {
                'outputSha256': baseline['sha256'], 'outputBytes': 2 * SAMPLES_PER_STEM * 4,
                'profileRecords': 43, 'stageRecords': 15, 'graphRecords': 27,
            }, 'Profile receipt or exact output differs from the approved baseline.')
            evidence['result'] = measured
        evidence['checks'].extend([
            'All 27 reviewed Deux ONNX graph bytes match the current model manifest before inference.',
            'The profile-enabled production predictor compiled with the pinned Android API, org.json dependency and host ONNX Runtime.',
            'The full 13-second passage at startSample=-66150 exactly matches the approved current-runtime SHA-256 output.',
            'The emitted profile contains one summary, 15 host-observable stages and exactly 27 graph records; no graph was dropped.',
        ])
        evidence['passed'] = True
    except Exception as error:
        evidence['failure'] = str(error)
        raise
    finally:
        write_atomic(output, evidence)
    print(json.dumps({'passed': evidence['passed'], 'result': evidence.get('result'), 'checks': evidence['checks']}, indent=2))


if __name__ == '__main__':
    main()
