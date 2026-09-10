#!/usr/bin/env python3
"""Compare the production Deux predictor across pinned host ONNX runtimes.

This is Linux/JVM numerical evidence, not an Android or ARM64 crash test.
The production predictor's Context-free constructor is used with identical
model weights, source audio, and the phone log's first passage offset.
"""
from pathlib import Path
import argparse
import array
import datetime
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
TOOLS = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain'))
OLD = {
    'version': '1.23.2',
    'name': 'onnxruntime-1.23.2.jar',
    'url': 'https://repo.maven.apache.org/maven2/com/microsoft/onnxruntime/onnxruntime/1.23.2/onnxruntime-1.23.2.jar',
    'bytes': 75255976,
    'sha256': 'e0ab4a1af57d2da09097202f2dfd691e390c82e81183314788ccde4cf7c3cc38',
}
SAMPLES_PER_STEM = 573300
START_SAMPLE = -66150


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def dependency(item):
    target = TOOLS / 'onnx' / item['name']
    def valid(path):
        return path.is_file() and path.stat().st_size == item['bytes'] and sha(path) == item['sha256']
    if not valid(target):
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
            temp = Path(output.name)
            try:
                with urllib.request.urlopen(item['url'], timeout=60) as source:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
                if not valid(temp):
                    raise RuntimeError('Runtime integrity check failed: ' + item['name'])
                os.replace(temp, target)
            finally:
                temp.unlink(missing_ok=True)
    return target


def run(command, log, **kwargs):
    with log.open('w') as stream:
        result = subprocess.run([str(value) for value in command], stdout=stream,
                                stderr=subprocess.STDOUT, cwd=ROOT, **kwargs)
    if result.returncode:
        raise RuntimeError('Command failed; see ' + str(log))


def floats(path):
    if path.stat().st_size != 2 * SAMPLES_PER_STEM * 4:
        raise RuntimeError('Incomplete prediction: ' + str(path))
    result = array.array('f')
    result.frombytes(path.read_bytes())
    if sys.byteorder != 'little':
        result.byteswap()
    if not all(math.isfinite(value) for value in result):
        raise RuntimeError('Nonfinite prediction: ' + str(path))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT.parent / 'native-runtime-comparison-2.2.4')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    gate = Path(__file__).with_name('native-runtime-comparison-verification.json')
    models = ROOT / 'web/analysis/models/deux'
    audio = ROOT / 'web/demo/glass-castle.wav'
    runtime_manifest = ROOT / 'android/native-runtime.json'
    manifest = json.loads(runtime_manifest.read_text())
    current = {'version': manifest['version'], **manifest['host']}
    if current['version'] != '1.25.1':
        raise RuntimeError('Review comparison before changing the target runtime')
    java = Path(os.environ.get('LIGHTFORGE_JAVA_HOME', TOOLS / 'jdk17')) / 'bin'
    android = Path(os.environ.get('ANDROID_SDK_ROOT', TOOLS / 'android-sdk')) / 'platforms/android-35/android.jar'
    source_files = [ROOT / 'android/src/com/cyberbasslord/lightforge/NativeDeux.java',
                    ROOT / 'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java',
                    ROOT / 'tests/NativeDeuxTest.java',
                    ROOT / 'android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java', runtime_manifest,
                    models / 'manifest.json', audio, Path(__file__).resolve()]
    bound = {str(path.relative_to(ROOT)): sha(path) for path in source_files}
    evidence = {
        'release': '2.2.4', 'passed': False,
        'scope': 'Fresh matched Linux/JVM full-passage inference comparison; no Android, ARM64, phone, background-service, or SIGILL-reproduction execution.',
        'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'host': {'system': platform.system(), 'machine': platform.machine()},
        'source_hashes': bound,
        'start_sample': START_SAMPLE,
        'sample_rate': 44100,
        'samples_per_stem': SAMPLES_PER_STEM,
        'model_quality': 'Original unquantized Deux weights and complete 13-second context, identical production batching in both runtimes.',
        'host_diagnostics_note': 'Only AppDiagnostics has a no-op host compile shim. Context is null, so the production predictor never calls it. Production transforms, inference, model verification, PCM I/O and session options run unchanged.',
        'thresholds': {'max_absolute_error': 1e-4, 'rmse': 1e-5, 'relative_rmse': 1e-3},
        'runs': [], 'checks': [],
    }
    gate.write_text(json.dumps(evidence, indent=2) + '\n')
    try:
        inventory = json.loads((models / 'manifest.json').read_text())['files']
        hashes = {}
        for key, item in inventory.items():
            model = models / key
            actual = sha(model)
            if model.stat().st_size != item['bytes'] or actual != item['sha256']:
                raise RuntimeError('Changed Deux model: ' + key)
            hashes[str(model.relative_to(ROOT))] = actual
        evidence['model_asset_hashes'] = hashes
        evidence['checks'].append('Every full-passage model matches the unchanged pinned Deux manifest.')
        jars = [dependency(item) for item in [OLD, current]]
        run([sys.executable, ROOT / 'tools/bootstrap_testdeps.py'], output / 'testdeps.log')
        classes = output / 'classes'
        classes.mkdir(exist_ok=True)
        stub = output / 'AppDiagnostics.java'
        stub.write_text('package com.cyberbasslord.lightforge; public final class AppDiagnostics { public static void log(android.content.Context c,String l,String s,String m){} public static boolean flush(long timeout){return true;} }\n')
        probe = output / 'RuntimeComparisonMain.java'
        probe.write_text('package com.cyberbasslord.lightforge; public final class RuntimeComparisonMain { public static void main(String[] args) throws Exception {String actual=ai.onnxruntime.OrtEnvironment.getEnvironment().getVersion(); System.out.println("Actual ONNX runtime="+actual); if(!actual.equals(args[0]))throw new AssertionError("Runtime mismatch"); NativeDeuxTest.main(java.util.Arrays.copyOfRange(args,1,args.length));} }\n')
        compile_cp = os.pathsep.join(map(str, [android, jars[0], TOOLS / 'test-json.jar']))
        run([java / 'javac', '-encoding', 'UTF-8', '--release', '8', '-classpath', compile_cp,
             '-d', classes, *source_files[:4], stub, probe], output / 'compile.log')
        predictions = []
        for item, jar in zip([OLD, current], jars):
            name = item['version']
            log = output / ('ort-' + name + '.log')
            prediction = output / ('ort-' + name + '.float32le')
            cp = os.pathsep.join(map(str, [classes, TOOLS / 'test-json.jar', android, jar]))
            run([java / 'java', '-cp', cp, 'com.cyberbasslord.lightforge.RuntimeComparisonMain',
                 name, models, audio, prediction, START_SAMPLE], log)
            metrics = [json.loads(line) for line in log.read_text().splitlines() if line.startswith('{"seconds":')]
            if len(metrics) != 1:
                raise RuntimeError('Missing prediction metrics for ' + name)
            actual = metrics[0]
            if sha(prediction) != actual['sha256']:
                raise RuntimeError('Changed prediction output')
            evidence['runs'].append({'version': name, 'runtime_jar_sha256': item['sha256'],
                                     'runtime_jar_bytes': item['bytes'], **actual,
                                     'output_bytes': prediction.stat().st_size,
                                     'log_sha256': sha(log)})
            predictions.append(floats(prediction))
            print(name + ': ' + json.dumps(actual), flush=True)
        evidence['comparison'] = []
        for i, stem in enumerate(['vocals', 'accompaniment']):
            start, end = i * SAMPLES_PER_STEM, (i + 1) * SAMPLES_PER_STEM
            before, after = predictions[0][start:end], predictions[1][start:end]
            errors = [float(x) - float(y) for x, y in zip(after, before)]
            max_error = max(map(abs, errors))
            rmse = math.sqrt(math.fsum(x * x for x in errors) / SAMPLES_PER_STEM)
            signal_rms = math.sqrt(math.fsum(float(x) * x for x in before) / SAMPLES_PER_STEM)
            relative_rmse = rmse / max(signal_rms, 1e-12)
            snr = 20 * math.log10(signal_rms / rmse) if rmse and signal_rms else None
            evidence['comparison'].append({'stem': stem, 'finite': True, 'samples': SAMPLES_PER_STEM,
                'max_absolute_error': max_error, 'rmse': rmse, 'reference_rms': signal_rms,
                'relative_rmse': relative_rmse, 'snr_db': snr, 'identical': max_error == 0})
            if max_error > 1e-4 or rmse > 1e-5 or relative_rmse > 1e-3:
                raise RuntimeError('Prediction difference exceeds reviewed thresholds: ' + stem)
        evidence['checks'].append('Both runtimes completed the same full passage at startSample=-66150 and produced two finite 573300-sample stems.')
        evidence['checks'].append('Both stems satisfy predeclared absolute and relative floating-point comparison thresholds.')
        for path in source_files:
            if sha(path) != bound[str(path.relative_to(ROOT))]:
                raise RuntimeError('Source changed during comparison: ' + str(path))
        evidence['checks'].append('Source bindings remained unchanged throughout both runs.')
        evidence['passed'] = True
        print(json.dumps(evidence['comparison'], indent=2))
    except Exception as error:
        evidence['failure'] = str(error)
        raise
    finally:
        gate.write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    main()
