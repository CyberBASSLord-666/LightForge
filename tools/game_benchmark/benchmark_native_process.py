#!/usr/bin/env python3
"""Capture original GAME graphs over production windows and replay actual stitching.

Development-only feasibility evidence, not an Android backend or quality approval.
Input is full-source mono float32 LE at 44.1 kHz. Keep private input/output outside git.
"""
import argparse
import array
import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / 'tools/game_benchmark'
GRAPHS = ('encoder', 'dur2bd', 'segmenter', 'bd2dur', 'estimator')


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def write_json(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def validate_input(path):
    size = path.stat().st_size
    if not size or size % 4 or size > 600 * 44100 * 4:
        raise ValueError('Expected nonempty <=10-minute mono float32 LE source at 44.1 kHz')
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            values = array.array('f')
            values.frombytes(block)
            if sys.byteorder != 'little':
                values.byteswap()
            if any(not math.isfinite(value) for value in values):
                raise ValueError('Input PCM contains nonfinite values')
    return size // 4


def run_logged(command, log, valid=(0,)):
    with log.open('x') as stream:
        result = subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=1200)
    if result.returncode not in valid:
        raise RuntimeError('Command failed with ' + str(result.returncode) + '; see ' + str(log))
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='Full-source mono float32 LE, 44100 Hz')
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New private evidence directory')
    parser.add_argument('--input-provenance', type=Path, help='Optional recorded origin/license metadata, not a quality attestation')
    parser.add_argument('--language', type=int, default=0, choices=range(5))
    parser.add_argument('--threads', type=int, default=4, choices=range(1,65))
    parser.add_argument('--toolchain', type=Path, default=ROOT.parent / 'toolchain')
    parser.add_argument('--production-engine', action='store_true',
                        help='Execute actual NativeGame.java and new nativeInfer path instead of historical prototype')
    args = parser.parse_args()
    args.input, args.models, args.output, args.toolchain = (p.resolve() for p in (args.input,args.models,args.output,args.toolchain))
    total = validate_input(args.input)
    manifest_bytes = (args.models / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get('id') != 'game-large-1.0.3-lightforge-1' or manifest.get('steps') != 8 or manifest.get('sampleRate') != 44100:
        raise ValueError('Unexpected original GAME contract')
    for graph in GRAPHS:
        name = graph + '.onnx'
        path = args.models / name
        if path.stat().st_size != manifest['files'][name]['bytes'] or digest(path) != manifest['files'][name]['sha256']:
            raise ValueError('Model integrity failure: ' + name)
    plan = json.loads(subprocess.check_output(['node', str(TOOL / 'process_capture.cjs'), '--plan', str(total), str(args.language)], cwd=ROOT, text=True))
    # process_capture validates the proposed plan using the actual production adapter
    # before any inference or publication-like receipt is created.
    args.output.mkdir(parents=True, exist_ok=False)
    java = args.toolchain / 'jdk17/bin/java'
    javac = args.toolchain / 'jdk17/bin/javac'
    dependencies = [args.toolchain / 'onnx/onnxruntime-1.25.1.jar', args.toolchain / 'test-json.jar']
    if args.production_engine:
        dependencies.append(args.toolchain / 'android-sdk/platforms/android-35/android.jar')
    classes = args.output / 'classes'
    classes.mkdir()
    sources = ['web/analysis/game.js', 'web/analysis/vendor/ort.wasm.min.js',
               'web/analysis/vendor/ort-wasm-simd-threaded.wasm',
               'tools/game_benchmark/NativeGameBenchmark.java',
               'tools/game_benchmark/capture_web.cjs', 'tools/game_benchmark/compare.py',
               'tools/game_benchmark/process_capture.cjs', 'tools/game_benchmark/benchmark_native_process.py']
    if args.production_engine:
        sources.extend(['android/src/com/cyberbasslord/lightforge/NativeGame.java', 'tests/NativeGameTest.java'])
    provenance = {
        'schema': 'lightforge-game-native-process-experiment-1',
        'startedUtc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'sourceRoot': str(ROOT),
        'nativeImplementation': 'production-NativeGame' if args.production_engine else 'historical-NativeGameBenchmark',
        'sourceSha256': {name: digest(ROOT / name) for name in sources},
        'dependencySha256': {path.name:digest(path) for path in dependencies},
        'inputSha256': digest(args.input), 'totalSamples': total, 'sampleRate': 44100,
        'modelManifestSha256': hashlib.sha256(manifest_bytes).hexdigest(),
        'inputProvenance': json.loads(args.input_provenance.read_text()) if args.input_provenance else None,
        'language': args.language, 'requestedThreads': args.threads, 'effectiveThreads': None,
        'host': {'platform':platform.platform(), 'cpuAffinity':sorted(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else None},
        'capturePairsPerPassage': 1, 'warmups': 0,
        'wholePipelineTimingComparable': False,
        'notes': ['Single captured pair per production passage; kernel timings are diagnostic, not a controlled speedup result.',
                  'Raw tensors are always retained and compared. Different floats are not auto-approved.',
                  'Final transcription equality alone is not full musical-quality or Android integration approval.']
    }
    for key, path in [('cpuMax', Path('/sys/fs/cgroup/cpu.max')), ('memoryMax', Path('/sys/fs/cgroup/memory.max'))]:
        provenance['host'][key] = path.read_text().strip() if path.exists() else None
    write_json(args.output / 'experiment.json', provenance)
    snapshot = args.output / 'source-snapshots'
    for name in sources:
        destination = snapshot / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    classpath = os.pathsep.join(map(str, dependencies))
    compile_sources = ([ROOT / 'android/src/com/cyberbasslord/lightforge/NativeGame.java', ROOT / 'tests/NativeGameTest.java']
                       if args.production_engine else [TOOL / 'NativeGameBenchmark.java'])
    compile_options = ['--release', '8', '-encoding', 'UTF-8'] if args.production_engine else []
    run_logged([javac, *compile_options, '-cp', classpath, '-d', classes, *compile_sources], args.output / 'compile.log')
    classpath = os.pathsep.join([str(classes), classpath])
    comparator_spec = importlib.util.spec_from_file_location('game_capture_comparator', TOOL / 'compare.py')
    comparator = importlib.util.module_from_spec(comparator_spec)
    comparator_spec.loader.exec_module(comparator)
    captured, diagnostic = [], []
    with args.input.open('rb') as source:
        for passage in plan:
            index = passage['index']
            directory = args.output / ('passage-' + str(index))
            directory.mkdir()
            pcm = directory / 'input.f32'
            source.seek(passage['first'] * 4)
            data = source.read((passage['last'] - passage['first']) * 4)
            if len(data) != (passage['last'] - passage['first']) * 4:
                raise ValueError('Source PCM changed or was truncated')
            with pcm.open('xb') as stream:
                stream.write(data)
            item = {**passage, 'pcmSha256':hashlib.sha256(data).hexdigest()}
            # Alternate order between passages. They contain different audio and are
            # not repeated timing pairs; no confidence interval is inferred from this.
            for side in (('wasm','native') if index % 2 == 0 else ('native','wasm')):
                print('passage ' + str(index) + ' ' + side, flush=True)
                output = directory / side
                common = [args.models, pcm, output, str(passage['seed']), str(args.language), str(args.threads), 'true']
                if side == 'wasm':
                    command = ['node', TOOL / 'capture_web.cjs', *common]
                elif args.production_engine:
                    output.mkdir()
                    command = [java, '-Xmx2g', '-XX:MaxDirectMemorySize=2g', '-cp', classpath,
                               'com.cyberbasslord.lightforge.NativeGameTest', 'infer', args.models, pcm,
                               output / 'receipt.json', str(passage['seed']), str(args.language)]
                else:
                    command = [java, '-Xmx2g', '-XX:MaxDirectMemorySize=2g', '-cp', classpath, 'NativeGameBenchmark', *common]
                run_logged(command, directory / (side + '.log'))
                receipt = output / 'receipt.json'
                item[side + 'Receipt'] = str(receipt.relative_to(args.output))
                item[side + 'ReceiptSha256'] = digest(receipt)
            comparison = directory / 'raw-comparison.json'
            if args.production_engine:
                # Validate every retained WASM tensor against its own receipt without
                # pretending the production engine captured matching native tensors.
                wasm, _ = comparator.load(directory / 'wasm')
                native = json.loads((directory / 'native/receipt.json').read_text())
                for key in ('samples','seed','language','steps'):
                    if native[key] != wasm[key]:
                        raise ValueError('Production engine returned different ' + key)
                same_count = len(native['notes']) == len(wasm['notes'])
                note_diagnostics = {
                    'sameCount':same_count,
                    'boundariesIdentical':same_count and all(a['start']==b['start'] and a['end']==b['end'] for a,b in zip(wasm['notes'],native['notes'])),
                    'maxAcceptedPitchDifferenceMidi':max((abs(a['midi']-b['midi']) for a,b in zip(wasm['notes'],native['notes'])),default=0) if same_count else None}
                report = {'schema':'lightforge-game-production-note-comparison-1',
                          'rawNativeTensorCaptureAvailable':False, 'exactParity':None,
                          'wasmRawTensorIntegrityVerified':True,
                          'unroundedNotesIdentical':wasm['notes']==native['notes'],
                          'leftNoteCount':len(wasm['notes']), 'rightNoteCount':len(native['notes']),
                          'noteDiagnostics':note_diagnostics,
                          'wasmUnroundedNotes':wasm['notes'], 'nativeUnroundedNotes':native['notes'],
                          'scope':'Raw note differences from fresh production Java execution versus fresh WASM; no native raw-tensor observation or parity assertion.'}
                write_json(comparison, report)
            else:
                run_logged([sys.executable, TOOL / 'compare.py', directory / 'wasm', directory / 'native', '--output', comparison],
                           directory / 'comparison.log', (0,2))
                report = json.loads(comparison.read_text())
            item['rawComparison'] = str(comparison.relative_to(args.output))
            item['rawComparisonSha256'] = digest(comparison)
            captured.append(item)
            # Save each completed passage independently so an interrupted experiment
            # never loses its source-bound evidence or pretends the full song passed.
            write_json(directory / 'completion.json', item)
            diagnostic.append({'index':index, 'exactRawParity':report['exactParity'],
                               'notes':report['noteDiagnostics'],
                               'noteCounts':[report['leftNoteCount'],report['rightNoteCount']]})
    for name, expected in provenance['sourceSha256'].items():
        if digest(ROOT / name) != expected:
            raise ValueError('Benchmark source changed during capture: ' + name)
    if digest(args.input) != provenance['inputSha256']:
        raise ValueError('Source PCM changed during capture')
    capture_input = {'schema':('lightforge-game-production-process-input-1' if args.production_engine else 'lightforge-game-native-process-input-1'), 'modelManifest':manifest,
                     'inputPcmSha256':provenance['inputSha256'], 'totalSamples':total,
                     'language':args.language, 'passages':captured}
    input_path = args.output / 'capture-input.json'
    write_json(input_path, capture_input)
    final = args.output / 'production-process-comparison.json'
    replay_args = ['--production', input_path, args.input, final] if args.production_engine else [input_path, final]
    run_logged(['node', TOOL / 'process_capture.cjs', *replay_args], args.output / 'process-comparison.log', (0,2))
    processed = json.loads(final.read_text())
    result = {'schema':'lightforge-game-native-process-summary-1',
              'finishedUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'experimentSha256':digest(args.output / 'experiment.json'),
              'captureInputSha256':digest(input_path), 'processComparisonSha256':digest(final),
              'productionTranscriptionIdentical':processed['productionTranscriptionIdentical'],
              'nativeImplementation':provenance['nativeImplementation'],
              'nativeCheckpointResumeIdentical':processed.get('nativeCheckpointResumeIdentical'),
              'freshNativeCallbackInputsRevalidated':processed.get('freshNativeCallbackInputsRevalidated',False),
              'rawNativeTensorCaptureAvailable':not args.production_engine,
              'notes':[len(processed['wasm']['notes']),len(processed['native']['notes'])],
              'passages':diagnostic, 'fullAnalysisQualityApproved':False,
              'androidIntegrationApproved':False, 'performanceTargetProven':False}
    write_json(args.output / 'summary.json', result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
