"""Fresh, source-bound native GAME consumer-equivalence evidence (not speed proof)."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OUT = 'qa/release-2.3.2/'
RELEASE = '2.3.2'
SCHEMA = 'lightforge.native-game-verification.v1'
RETAINED_SCHEMA = 'lightforge.native-game-retained-output.v1'
GRAPHS = ('encoder', 'dur2bd', 'segmenter', 'bd2dur', 'estimator')
INPUTS = (
    {'id': 'demo', 'source': 'web/demo/glass-castle.wav'},
    {'id': 'falcon', 'source': 'qa/release-1.6.0/fixtures/falcon-mix.wav'},
)
SOURCES = frozenset({
    'version.json', 'android/native-runtime.json',
    'android/src/com/cyberbasslord/lightforge/NativeGame.java', 'tests/NativeGameTest.java',
    'web/analysis/game.js', 'web/analysis/wav-reader.js',
    'web/analysis/models/game/manifest.json', 'web/demo/glass-castle.wav',
    'qa/release-1.6.0/fixtures/falcon-mix.wav',
    'qa/release-1.6.0/musdb-fixture-provenance.json',
    'tools/bootstrap_toolchain.py', 'tools/bootstrap_native_runtime.py',
    'tools/bootstrap_testdeps.py', 'tools/game_benchmark/benchmark_native_process.py',
    'tools/game_benchmark/NativeGameBenchmark.java',
    'tools/game_benchmark/process_capture.cjs', 'tools/game_benchmark/capture_web.cjs',
    'tools/game_benchmark/compare.py',
    OUT + 'prepare-game-input.cjs', OUT + 'verify-native-game.py',
    OUT + 'native_game_evidence.py', OUT + 'verify-analysis.py',
})
SCOPE = (
    'Fresh Linux/JVM production NativeGame.java versus bundled CPU WASM using the '
    'original GAME graphs, eight steps and production passage context/seeds. '
    'The complete public demo and licensed Falcon mixture are direct transcription '
    'inputs, not separated stems or a quality corpus. Exact final consumer output '
    'and checkpoint resume are required; unrounded pitch differences are retained. '
    'Native intermediate tensors are not observed. Android lifecycle, ARM accuracy, '
    'physical-device performance and a 75% speedup are not established here.'
)
HEX = re.compile(r'[0-9a-f]{64}\Z')
MAX_RETAINED_BYTES = 32 * 1024 * 1024
EXPERIMENT_SOURCES = frozenset({
    'web/analysis/game.js', 'web/analysis/vendor/ort.wasm.min.js',
    'web/analysis/vendor/ort-wasm-simd-threaded.wasm',
    'tools/game_benchmark/NativeGameBenchmark.java',
    'tools/game_benchmark/capture_web.cjs', 'tools/game_benchmark/compare.py',
    'tools/game_benchmark/process_capture.cjs', 'tools/game_benchmark/benchmark_native_process.py',
    'android/src/com/cyberbasslord/lightforge/NativeGame.java', 'tests/NativeGameTest.java',
})


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'Duplicate JSON key: ' + key)
        value[key] = item
    return value


def loads(text):
    def invalid(value):
        raise ValueError('Nonfinite JSON constant: ' + value)
    def finite_float(value):
        result = float(value)
        require(math.isfinite(result), 'Nonfinite JSON number: ' + value)
        return result
    return json.loads(text, object_pairs_hook=_pairs, parse_constant=invalid,
                      parse_float=finite_float)


def load(path):
    return loads(Path(path).read_text(encoding='utf-8'))


def hash_sources(root=ROOT):
    return {name: digest(root / name) for name in sorted(SOURCES)}


def hash_assets(root=ROOT):
    manifest = load(root / 'web/analysis/models/game/manifest.json')
    require(manifest.get('id') == 'game-large-1.0.3-lightforge-1' and
            manifest.get('steps') == 8 and manifest.get('sampleRate') == 44100,
            'GAME model contract changed')
    names = {'web/analysis/models/game/' + graph + '.onnx' for graph in GRAPHS} | {
        'web/analysis/vendor/ort.wasm.min.js',
        'web/analysis/vendor/ort-wasm-simd-threaded.wasm',
    }
    result = {name: digest(root / name) for name in sorted(names)}
    for graph in GRAPHS:
        name = graph + '.onnx'
        path = root / 'web/analysis/models/game' / name
        expected = manifest['files'][name]
        require(path.stat().st_size == expected['bytes'] and
                result['web/analysis/models/game/' + name] == expected['sha256'],
                'Original GAME graph integrity failure: ' + name)
    return result


def retain_json(directory, fixture):
    """Retain exact receipt bytes, never PCM, graph tensors, or private audio."""
    files = {}
    for path in sorted(directory.rglob('*.json')):
        relative = path.relative_to(directory).as_posix()
        if relative.startswith('source-snapshots/'):
            continue
        data = path.read_bytes()
        text = data.decode('utf-8')
        loads(text)
        files[relative] = {'utf8': text, 'bytes': len(data),
                           'sha256': hashlib.sha256(data).hexdigest()}
    return {'schema': RETAINED_SCHEMA, 'fixture': fixture, 'files': files}


def unpack_json(retained, directory):
    require(isinstance(retained, dict) and set(retained) == {'schema', 'fixture', 'files'} and
            retained['schema'] == RETAINED_SCHEMA, 'Invalid retained GAME schema')
    files = retained['files']
    require(isinstance(files, dict) and 4 <= len(files) <= 128,
            'Incomplete or excessive retained GAME files')
    total = 0
    for name, item in files.items():
        require(isinstance(name, str), 'Invalid retained GAME path')
        path = PurePosixPath(name)
        require(not path.is_absolute() and path.as_posix() == name and
                all(part not in {'', '.', '..'} for part in name.split('/')) and
                '\\' not in name and name.endswith('.json') and len(path.parts) <= 3,
                'Invalid retained GAME path: ' + name)
        require(isinstance(item, dict) and set(item) == {'utf8', 'bytes', 'sha256'} and
                isinstance(item['utf8'], str), 'Invalid retained GAME JSON entry')
        data = item['utf8'].encode('utf-8')
        total += len(data)
        require(type(item['bytes']) is int and item['bytes'] == len(data) and
                hashlib.sha256(data).hexdigest() == item['sha256'] and
                total <= MAX_RETAINED_BYTES, 'Retained GAME JSON integrity failure')
        loads(item['utf8'])
        output = directory / name
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('xb') as stream:
            stream.write(data)
    require({'experiment.json', 'capture-input.json', 'summary.json',
             'production-process-comparison.json'}.issubset(files),
            'Missing required retained GAME outputs')


def verify_retained(root, retained, expected_input):
    fixture = retained.get('fixture', {})
    require(isinstance(fixture, dict) and set(fixture) == {
        'id', 'source', 'sourceSha256', 'monoPcmSha256', 'samples', 'sampleRate',
        'channels', 'monoDerivation', 'separationApplied'}, 'Invalid GAME fixture binding')
    require(all(fixture.get(key) == value for key, value in expected_input.items()) and
            fixture['sourceSha256'] == digest(root / expected_input['source']) and
            isinstance(fixture['monoPcmSha256'], str) and HEX.fullmatch(fixture['monoPcmSha256']) and
            type(fixture['samples']) is int and 0 < fixture['samples'] <= 120 * 44100 and
            fixture['sampleRate'] == 44100 and type(fixture['channels']) is int and
            1 <= fixture['channels'] <= 8 and
            fixture['monoDerivation'] == 'production-stereo44100-float32-mean-v1' and
            fixture['separationApplied'] is False, 'GAME fixture changed')
    with tempfile.TemporaryDirectory(prefix='lightforge-game-receipt-check-') as temporary:
        directory = Path(temporary)
        unpack_json(retained, directory)
        prepared = loads(subprocess.check_output([
            'node', str(root / OUT / 'prepare-game-input.cjs'), expected_input['id'],
            str(directory / 'reconstructed-public-input.f32')], cwd=root, text=True, timeout=60))
        require(prepared == fixture, 'GAME fixture does not cover the exact complete public source')
        experiment = load(directory / 'experiment.json')
        require(experiment.get('schema') == 'lightforge-game-native-process-experiment-1' and
                experiment.get('nativeImplementation') == 'production-NativeGame' and
                experiment.get('sourceSha256') == {
                    name: digest(root / name) for name in sorted(EXPERIMENT_SOURCES)} and
                experiment.get('inputSha256') == fixture['monoPcmSha256'] and
                experiment.get('modelManifestSha256') == digest(root / 'web/analysis/models/game/manifest.json') and
                experiment.get('totalSamples') == fixture['samples'] and
                experiment.get('sampleRate') == 44100 and experiment.get('language') == 0,
                'GAME experiment implementation, source, models or complete input changed')
        runtime = load(root / 'android/native-runtime.json')
        require(runtime.get('version') == '1.25.1' and experiment.get('dependencySha256') == {
            'onnxruntime-1.25.1.jar': runtime['host']['sha256'],
            'test-json.jar': 'c243f45f9590c12694a4142ed3f07fc70dfb71e4daebd05ae234bf92a2da92a6',
            'android.jar': '4566663c3876e022b4fa4ced8c8697c4ab1688267f090114fd92d027b32e619b',
        }, 'GAME executed host dependency identity changed')
        capture = load(directory / 'capture-input.json')
        require(capture.get('schema') == 'lightforge-game-production-process-input-1' and
                capture.get('inputPcmSha256') == fixture['monoPcmSha256'] and
                capture.get('totalSamples') == fixture['samples'] and capture.get('language') == 0,
                'GAME captured PCM clock/language binding changed')
        require(capture.get('modelManifest') == load(root / 'web/analysis/models/game/manifest.json'),
                'GAME captured model manifest changed')
        measured = load(directory / 'production-process-comparison.json')
        require(measured.get('schema') == 'lightforge-game-production-process-comparison-1' and
                measured.get('productionTranscriptionIdentical') is True and
                measured.get('nativeCheckpointResumeIdentical') is True and
                measured.get('freshNativeCallbackInputsRevalidated') is True and
                measured.get('verificationMode') == 'fresh-pcm-native-callback-replay' and
                measured.get('nativeCalls') == (fixture['samples'] + 12 * 44100 - 1) // (12 * 44100) and
                measured.get('rawNativeTensorCaptureAvailable') is False and
                measured.get('rawTensorParityAsserted') is False,
                'Fresh native GAME consumer/checkpoint comparison did not pass')
        # The separate replay has no audio. It verifies retained notes through
        # current production stitching/checkpoint code, not fresh JNI execution.
        replay_path = directory / 'recomputed.json'
        subprocess.run(['node', str(root / 'tools/game_benchmark/process_capture.cjs'),
                        '--production-receipts', str(directory / 'capture-input.json'),
                        str(replay_path)], cwd=root, check=True, capture_output=True,
                       text=True, timeout=120)
        replay = load(replay_path)
        require(replay.get('verificationMode') == 'receipt-only-checkpoint-replay' and
                replay.get('freshNativeCallbackInputsRevalidated') is False and
                replay.get('productionTranscriptionIdentical') is True and
                replay.get('nativeCheckpointResumeIdentical') is True,
                'Retained native GAME consumer/checkpoint replay failed')
        for key in ('wasm', 'native', 'totalSamples', 'passageCount', 'rawNoteDiagnostics',
                    'captureInputSha256', 'productionAdapterSha256', 'declaredRuntimeDifference'):
            require(replay.get(key) == measured.get(key),
                    'GAME measured output differs from recomputed consumer output: ' + key)
        require(isinstance(replay.get('wasm'), dict) and
                isinstance(replay['wasm'].get('notes'), list) and replay['wasm']['notes'],
                'GAME fixture produced no transcription coverage')
        return {'fixture': fixture, 'passages': replay['passageCount'],
                'notes': len(replay['wasm']['notes']),
                'productionTranscriptionIdentical': True,
                'nativeCheckpointResumeIdentical': True,
                'rawNativeTensorCaptureAvailable': False}


def verify_receipt(root, receipt, evidence_session, hashes):
    require(isinstance(receipt, dict) and receipt.get('schema') == SCHEMA and
            receipt.get('release') == RELEASE and receipt.get('passed') is True and
            receipt.get('errors') == [] and receipt.get('evidenceSessionSchema') ==
            'lightforge.evidence-session.v1' and receipt.get('evidenceSession') == evidence_session,
            'Native GAME receipt is missing, failed, or stale')
    require(isinstance(evidence_session, str) and re.fullmatch(r'[0-9a-f]{32,128}', evidence_session),
            'Native GAME requires a fresh evidence session')
    expected_sources, expected_assets = hash_sources(root), hash_assets(root)
    require(receipt.get('source_hashes') == expected_sources and
            receipt.get('source_hashes_after') == expected_sources,
            'Native GAME source bytes changed')
    require(receipt.get('analysis_asset_hashes') == expected_assets and
            receipt.get('analysis_asset_hashes_after') == expected_assets,
            'Native GAME model/runtime assets changed')
    hashes.update(expected_sources)
    runs = receipt.get('runs')
    require(isinstance(runs, list) and len(runs) == len(INPUTS), 'Native GAME input coverage changed')
    measured = []
    for run, expected_input in zip(runs, INPUTS):
        relative = OUT + 'native-game-' + expected_input['id'] + '-output.json'
        path = root / relative
        require(isinstance(run, dict) and run.get('path') == relative and
                type(run.get('bytes')) is int and 0 < run['bytes'] <= MAX_RETAINED_BYTES and
                path.stat().st_size == run['bytes'] and digest(path) == run.get('sha256'),
                'Native GAME retained output differs from its bound receipt')
        result = verify_retained(root, load(path), expected_input)
        require(run.get('result') == result, 'Native GAME summary differs from recomputed evidence')
        hashes[relative] = run['sha256']
        measured.append(result)
    require(receipt.get('scope') == SCOPE and receipt.get('performanceTargetProven') is False and
            receipt.get('androidIntegrationApproved') is False and
            receipt.get('fullAnalysisQualityApproved') is False,
            'Native GAME qualification scope was relabeled')
    return measured
