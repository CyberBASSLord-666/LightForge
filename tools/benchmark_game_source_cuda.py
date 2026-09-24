#!/usr/bin/env python3
"""Bounded complete-source GAME CPU/CUDA diagnostics; never a timing or quality approval.

Runs the original CPU/ALL and already-qualified deterministic heavy-only CUDA
snapshots in six fresh processes. Each process reuses one original NativeGame
object across the complete production 12-second core/2-second halo schedule;
the original engine still creates and retires sessions for every prediction.
All original float32 models, eight diffusion steps and unrounded passage notes
are retained. Captured/profiled twins preserve every raw tensor. No timing ratio
is calculated even if every observed byte agrees. Input is bounded to 64 seconds
and this first experiment rejects wholly silent passages before any execution.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('game_source_accelerator', ROOT / 'tools/benchmark_game_accelerator.py')
game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(game)
accel, profiler, comparator = game.accel, game.profiler, game.comparator
require, sha, write_json = game.require, game.sha, game.write_json
RATE, CORE, HALO, MAX_SAMPLES = 44100, 12 * 44100, 2 * 44100, 64 * 44100
VARIANTS, MODES = ('cpu_all', 'cuda_basic'), game.MODES
RUNNER = ROOT / 'tools/game_benchmark/GameSourceRunner.java'
CAPTURE = ROOT / 'tools/game_benchmark/GameAcceleratorCapture.java'
SOURCE_BINDINGS = (
    'tools/benchmark_game_source_cuda.py', 'tools/game_benchmark/GameSourceRunner.java',
    'tools/game_benchmark/GameAcceleratorCapture.java', 'tools/benchmark_game_accelerator.py',
    'tools/game_benchmark/compare.py', 'tools/benchmark_deux_accelerator.py',
    'tools/profile_deux_operators.py', 'tools/benchmark_deux_execution.py',
    'android/src/com/cyberbasslord/lightforge/NativeGame.java', 'android/native-runtime.json',
    'web/analysis/models/game/manifest.json', 'web/analysis/game.js',
    'tools/game_benchmark/process_capture.cjs', 'tools/game_benchmark/replay_cuda_source.cjs',
)


def passage_plan(samples, language=0):
    require(type(samples) is int and 0 < samples <= MAX_SAMPLES and type(language) is int and 0 <= language <= 4,
            'Expected a valid complete source clock of at most 64 seconds and language 0..4.')
    return [dict(index=i, key=f'game-{language}-{i}', first=max(0, i * CORE - HALO),
                 last=min(samples, (i + 1) * CORE + HALO), seed=(2025 + i * 104729) & 0xffffffff)
            for i in range((samples + CORE - 1) // CORE)]


def validate_input(pcm, provenance_path):
    require(pcm.is_file() and not pcm.is_symlink() and 0 < pcm.stat().st_size <= MAX_SAMPLES * 4
            and pcm.stat().st_size % 4 == 0, 'Expected complete <=64-second mono Float32 PCM.')
    data = pcm.read_bytes()
    require(all(math.isfinite(x) for (x,) in struct.iter_unpack('<f', data)), 'Nonfinite full-source PCM.')
    provenance = profiler.strict_json(provenance_path)
    require(provenance.get('schema') == 'lightforge.game-source-input.v1', 'Missing full-source input provenance.')
    require(type(provenance.get('sampleRate')) is int and provenance['sampleRate'] == RATE and
            type(provenance.get('sourceSamples')) is int and provenance['sourceSamples'] == len(data) // 4,
            'Full PCM does not match its original complete source clock.')
    plan = passage_plan(provenance['sourceSamples'], provenance.get('language'))
    for name in ('pcmSHA256', 'sourceSHA256'):
        require(isinstance(provenance.get(name), str) and re.fullmatch('[a-f0-9]{64}', provenance[name]),
                'Missing complete PCM/source digest: ' + name)
    require(provenance['pcmSHA256'] == sha(pcm), 'Full PCM digest mismatch.')
    require(provenance.get('sourceKind') in ('public-mixture', 'public-separated-vocals', 'synthetic'),
            'Explicit public/synthetic source kind required; no private audio ingestion.')
    require(isinstance(provenance.get('derivation'), str) and 0 < len(provenance['derivation']) <= 4096,
            'Describe complete-source PCM derivation, not only its first passage.')
    for row in plan:
        passage = data[row['first'] * 4:row['last'] * 4]
        peak = max(abs(value) for (value,) in struct.iter_unpack('<f', passage))
        require(peak > 1e-5, 'Silent passage unsupported by complete-capture experiment: ' + str(row['index']))
        row['pcmSha256'] = hashlib.sha256(passage).hexdigest()
    return provenance, plan


def execution_identity(variant):
    require(variant in VARIANTS, 'Unknown full-source variant.')
    cuda = variant == 'cuda_basic'
    return dict(runtime='onnxruntime-java-1.25.1', package='gpu' if cuda else 'cpu',
                provider='CUDAExecutionProvider' if cuda else 'CPUExecutionProvider',
                optimization='BASIC_OPT' if cuda else 'ALL_OPT', cudaHeavyOnly=cuda, cudaDeterministicCompute=cuda)


def source_snapshot(source, variant, mode, traces=None):
    require(variant in VARIANTS and mode in MODES, 'Unknown full-source snapshot arm/mode.')
    require((traces is not None) == (mode == 'profiled'), 'Trace directory must match profiled mode.')
    snapshot = game.variant_source(source, variant, True, True)
    return game.observed_source(snapshot, traces) if mode != 'plain' else snapshot


def compile_snapshot(directory, source, java, dependencies):
    directory.mkdir()
    snapshot = directory / 'NativeGame.java'
    snapshot.write_text(source, encoding='utf-8')
    sources = [snapshot]
    for helper in (RUNNER, CAPTURE):
        target = directory / helper.name
        shutil.copyfile(helper, target)
        require(sha(target) == sha(helper), 'Copied research helper changed.')
        sources.append(target)
    classes = directory / 'classes'
    classes.mkdir()
    command = [str(java / 'javac'), '--release', '8', '-encoding', 'UTF-8', '-cp',
               os.pathsep.join(map(str, dependencies)), '-d', str(classes), *map(str, sources)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    (directory / 'compile.log').write_text(result.stdout + result.stderr)
    require(result.returncode == 0, 'Source GAME compilation failed: ' + str(directory / 'compile.log'))
    return classes, sources + list(classes.rglob('*.class'))


def run_process(command, log, timeout):
    """Retire the entire fresh JVM process group even when timeout/observer fails."""
    with log.open('x') as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            result = process.wait(timeout=timeout)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    require(result == 0, 'Full-source GAME process failed: ' + str(log))


def validate_run(directory, mode, provenance, plan, manifest):
    receipt = profiler.strict_json(directory / 'receipt.json')
    require(receipt.get('schema') == 'lightforge-game-source-run-1' and
            receipt.get('runtime') == 'onnxruntime-java-1.25.1' and receipt.get('samples') == provenance['sourceSamples'] and
            receipt.get('pcmSHA256') == provenance['pcmSHA256'] and receipt.get('sampleRate') == RATE and
            receipt.get('steps') == 8 and receipt.get('language') == provenance['language'] and
            receipt.get('modelFiles') == manifest['files'] and receipt.get('engineObjects') == 1 and
            receipt.get('capture') is (mode != 'plain') and receipt.get('profiled') is (mode == 'profiled') and
            receipt.get('retirementConfirmed') is True and receipt.get('passageCount') == len(plan) and
            type(receipt.get('wallNanos')) is int and receipt['wallNanos'] > 0,
            'Invalid complete-source execution receipt.')
    require(isinstance(receipt.get('passages'), list) and len(receipt['passages']) == len(plan), 'Incomplete passage receipt list.')
    for row, nested in zip(plan, receipt['passages']):
        path = directory / f"passage-{row['index']:03d}"
        item = profiler.strict_json(path / 'receipt.json')
        require(item == nested, 'Nested passage evidence differs from saved receipt.')
        expected = dict(schema='lightforge-game-benchmark-1', runtime='onnxruntime-java-1.25.1', sampleRate=RATE,
            samples=row['last'] - row['first'], pcmSHA256=row['pcmSha256'], sourcePcmSHA256=provenance['pcmSHA256'],
            sourceSamples=provenance['sourceSamples'], passageIndex=row['index'], firstSample=row['first'],
            lastSample=row['last'], modelFiles=manifest['files'], seed=row['seed'], language=provenance['language'], steps=8)
        require(all(item.get(key) == value for key, value in expected.items()) and
                item.get('capture') is (mode != 'plain') and item.get('retirementConfirmed') is True and
                type(item.get('wallNanos')) is int and item['wallNanos'] > 0,
                'Invalid source-bound passage receipt: ' + str(row['index']))
        require(isinstance(item.get('notes'), list) and all(isinstance(note, dict) and
                set(note) == {'start', 'end', 'midi'} and all(type(note[k]) in (int, float) and math.isfinite(note[k])
                for k in note) for note in item['notes']), 'Invalid unrounded passage notes.')
        if mode != 'plain':
            _, tensors = comparator.load(path)
            require(len(tensors) == 16, 'Every non-silent GAME passage requires all 16 raw tensors.')
            for stage in item['stages']:
                label = stage['label']
                expected_label = ('segmenter-' + str(row['index'] * 8 + int(label.split('-')[1]))) \
                    if label.startswith('segmenter-') else label
                require(stage.get('captureOriginalLabel') == expected_label, 'Global capture identity changed.')
        else:
            require(item.get('stages') == [] and item.get('inferenceSeconds') is None, 'Plain execution contains observer data.')
    return receipt


def compare_observers(outputs, plan):
    comparisons = []
    for variant in VARIANTS:
        for row in plan:
            paths = {mode: outputs[variant][mode] / f"passage-{row['index']:03d}" for mode in MODES}
            plain = profiler.strict_json(paths['plain'] / 'receipt.json')
            captured = profiler.strict_json(paths['captured'] / 'receipt.json')
            comparison = comparator.compare(paths['captured'], paths['profiled'])
            comparisons.extend([
                dict(variant=variant, passageIndex=row['index'], kind='plain-vs-capture', rawTensorsByteIdentical=None,
                     unroundedNotesIdentical=plain['notes'] == captured['notes']),
                dict(variant=variant, passageIndex=row['index'], kind='capture-vs-profile',
                     rawTensorsByteIdentical=comparison['exactParity'],
                     unroundedNotesIdentical=comparison['unroundedNotesIdentical'], rawComparison=comparison)])
    return comparisons


def verify_bound_files(hashes):
    for path, expected in hashes.items():
        require(path.is_file() and not path.is_symlink() and sha(path) == expected,
                'Bound source/model/runtime/input/evidence changed: ' + str(path))


def execute(args, receipt):
    require(sys.platform.startswith('linux'), 'Native-library evidence and process-group cleanup require Linux.')
    require(not any(os.environ.get(key) for key in ('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS')),
            'Unset Java option injection variables.')
    for key, value in (('CUBLAS_WORKSPACE_CONFIG', ':4096:8'), ('NVIDIA_TF32_OVERRIDE', '0')):
        require(os.environ.get(key, value) == value, 'Unexpected ' + key)
        os.environ[key] = value
    provenance, plan = validate_input(args.input, args.input_provenance)
    manifest = game.verify_models(args.models)
    runtime = profiler.strict_json(ROOT / 'android/native-runtime.json')
    require(runtime['version'] == '1.25.1', 'Production ORT changed.')
    java = args.toolchain / 'jdk17/bin'
    host, gpu = args.toolchain / 'onnx' / runtime['host']['name'], args.gpu_runtime or args.toolchain / 'onnx' / accel.GPU_RUNTIME['name']
    shared = [args.toolchain / 'test-json.jar', args.toolchain / 'android-sdk/platforms/android-35/android.jar']
    accel.verify_runtime(host, runtime['host'])
    accel.verify_runtime(gpu, accel.GPU_RUNTIME)
    for path in shared:
        require(path.is_file() and not path.is_symlink(), 'Missing compilation dependency.')
    dependencies = dict(cpu_all=[*shared, host], cuda_basic=[*shared, gpu])
    bound_source = [ROOT / path for path in SOURCE_BINDINGS]
    require(all(path.is_file() and not path.is_symlink() for path in bound_source), 'Missing required source/replay binding.')
    bound = set(bound_source + [args.input, args.input_provenance, *shared, host, gpu, args.models / 'manifest.json'] +
                [args.models / name for name in manifest['files']])
    hashes = {path: sha(path) for path in bound}
    receipt.update(inputProvenance=provenance, inputProvenanceSha256=sha(args.input_provenance), passagePlan=plan,
        sourceHashes={str(path.relative_to(ROOT)): hashes[path] for path in bound_source},
        dependencyHashes={path.name: hashes[path] for path in [*shared, host, gpu]},
        modelManifestSha256=sha(args.models / 'manifest.json'), modelHashes={name: entry['sha256'] for name, entry in manifest['files'].items()},
        host=accel.benchmark.host_metadata(), gpuInventory=accel.gpu_inventory(),
        variants=list(VARIANTS), modes=list(MODES), executionIdentity={v: execution_identity(v) for v in VARIANTS},
        cudaOptions=accel.CUDA_OPTIONS, cudaHeavyOnly=True, cudaDeterministicCompute=True,
        requestedGraphProviders={v: game.requested_graph_providers(v, True) for v in VARIANTS},
        cublasWorkspaceConfig=':4096:8', nvidiaTf32Override='0',
        cudaVisibility={key: os.environ.get(key) for key in ('CUDA_VISIBLE_DEVICES', 'CUDA_DEVICE_ORDER')},
        requestedCudaLogicalDevice=0, gpuMappingNote='Physical inventory does not independently establish logical device 0 mapping.',
        deterministicCompute='Same qualified heavy-only deterministic-compute option; GPU kernel request is not a universal determinism guarantee.',
        runs=[], observerComparisons=[], crossVariantComparisons=[], providerTraces={}, placement={}, runtimeProbes=[])
    for variant in VARIANTS:
        accel.verify_java_api(java, dependencies[variant][-1])
        receipt['runtimeProbes'].append(accel.probe_runtime(java, dependencies[variant], args.output / (variant + '-runtime-probe'), variant == 'cuda_basic'))
    write_json(args.output / 'receipt.json', receipt)
    if args.check_readiness:
        # Compile every exact arm/observer combination before authorizing a long
        # source run. These snapshots are distinct readiness artifacts and are
        # never executed or reused as completed inference evidence.
        source = game.SOURCE.read_text()
        compiled = {}
        for variant in VARIANTS:
            for mode in MODES:
                directory = args.output / ('readiness_' + variant + '_' + mode)
                traces = args.output / ('readiness_' + variant + '_active_traces') if mode == 'profiled' else None
                if traces is not None:
                    traces.mkdir()
                _, artifacts = compile_snapshot(directory, source_snapshot(source, variant, mode, traces), java, dependencies[variant])
                for path in artifacts:
                    hashes[path] = sha(path)
                    compiled[str(path.relative_to(args.output))] = hashes[path]
        verify_bound_files(hashes)
        receipt.update(status='PREFLIGHT_READY', inputsRecheckedAfterQualification=True,
                       readinessCompiledSnapshotHashes=compiled, readinessSnapshotCount=6,
                       inferenceExecuted=False)
        return
    source = game.SOURCE.read_text()
    outputs = {variant: {} for variant in VARIANTS}
    for variant in VARIANTS:
        for mode in MODES:
            directory = args.output / (variant + '_' + mode)
            traces = args.output / (variant + '_active_traces') if mode == 'profiled' else None
            if traces is not None:
                traces.mkdir()
            classes, artifacts = compile_snapshot(directory, source_snapshot(source, variant, mode, traces), java, dependencies[variant])
            hashes.update({path: sha(path) for path in artifacts})
            output, maps = directory / 'output', directory / 'cuda-jvm-loaded-library-maps.txt'
            command = [str(java / 'java'), '-Xmx2g', '-XX:MaxDirectMemorySize=2g', '-cp',
                os.pathsep.join(map(str, [classes, *dependencies[variant]])), 'com.cyberbasslord.lightforge.GameSourceRunner',
                str(args.models), str(args.input), str(output), str(provenance['language']), str(mode != 'plain').lower(),
                str(maps) if variant == 'cuda_basic' and mode == 'profiled' else '', str(traces) if traces else '']
            print(variant + ' ' + mode + ' complete source: ' + str(len(plan)) + ' passages', flush=True)
            started = time.perf_counter_ns()
            run_process(command, directory / 'run.log', 1200 * len(plan))
            process_wall = time.perf_counter_ns() - started
            item = validate_run(output, mode, provenance, plan, manifest)
            outputs[variant][mode] = output
            receipt['runs'].append(dict(variant=variant, mode=mode, receipt=str((output / 'receipt.json').relative_to(args.output)),
                receiptSha256=sha(output / 'receipt.json'), wallNanos=item['wallNanos'],
                processWallIncludingStartupAndInspectionNanos=process_wall, passageCount=len(plan), timingEligible=False))
            for path in output.rglob('*'):
                require(not path.is_symlink(), 'Unexpected symlink in output evidence.')
                if path.is_file():
                    hashes[path] = sha(path)
            if mode == 'profiled':
                summaries, placements = [], []
                for row in plan:
                    summary = game.summarize_traces(output / f"passage-{row['index']:03d}" / 'traces')
                    placement = game.validate_placement(summary, variant, True)
                    summaries.append(dict(passageIndex=row['index'], **summary))
                    placements.append(dict(passageIndex=row['index'], **placement))
                receipt['providerTraces'][variant], receipt['placement'][variant] = summaries, placements
                require(not list(traces.iterdir()), 'Completed traces were not fully moved into passage evidence.')
                if variant == 'cuda_basic':
                    libraries = accel.native_library_paths(maps)
                    receipt['gpuNativeLibraries'] = {str(path): dict(bytes=path.stat().st_size, sha256=sha(path)) for path in libraries}
                    receipt['gpuNativeLibraryVersions'] = accel.native_library_versions(libraries)
                    hashes.update({path: sha(path) for path in [maps, *libraries]})
            write_json(args.output / 'receipt.json', receipt)
    receipt['observerComparisons'] = compare_observers(outputs, plan)
    for row in plan:
        paths = [outputs[v]['captured'] / f"passage-{row['index']:03d}" for v in VARIANTS]
        comparison = comparator.compare(*paths)
        receipt['crossVariantComparisons'].append(dict(passageIndex=row['index'], reference='cpu_all', candidate='cuda_basic',
            qualityApproved=False, tolerance=None, **comparison))
    verify_bound_files(hashes)
    receipt['artifactHashes'] = {str(path.relative_to(args.output)): digest for path, digest in hashes.items() if path.is_relative_to(args.output)}
    receipt['inputsRecheckedAfterQualification'] = True
    game.validate_observers(receipt['observerComparisons'])
    receipt['observerComparisonsPassed'] = True
    receipt['rawOutputsByteIdenticalAcrossVariants'] = all(row['exactParity'] for row in receipt['crossVariantComparisons'])
    receipt['status'] = 'COMPLETE_DIAGNOSTIC' if receipt['rawOutputsByteIdenticalAcrossVariants'] else 'NUMERICAL_EQUIVALENCE_UNPROVEN'


def replay_manifest(args, receipt):
    """Emit only after the immutable experiment receipt is final; replay owns a separate result."""
    require(receipt.get('observerComparisonsPassed') is True and receipt.get('inputsRecheckedAfterQualification') is True,
            'Observer/input verification required before replay handoff.')
    def descriptor(path):
        return str(path.relative_to(args.output)), sha(path)
    arms = {}
    for name, variant in (('cpu', 'cpu_all'), ('cuda', 'cuda_basic')):
        arm = dict(executionIdentity=execution_identity(variant), profilePlacement=receipt['placement'][variant])
        for key, path in (
                ('aggregateReceipt', args.output / (variant + '_captured') / 'output/receipt.json'),
                ('profiledAggregateReceipt', args.output / (variant + '_profiled') / 'output/receipt.json'),
                ('sourceSnapshot', args.output / (variant + '_captured') / 'NativeGame.java')):
            arm[key], arm[key + 'Sha256'] = descriptor(path)
        arms[name] = arm
    passages = []
    for row in receipt['passagePlan']:
        entry = dict(row)
        for name, variant in (('cpu', 'cpu_all'), ('cuda', 'cuda_basic')):
            entry[name + 'Receipt'], entry[name + 'ReceiptSha256'] = descriptor(
                args.output / (variant + '_captured') / 'output' / f"passage-{row['index']:03d}" / 'receipt.json')
        passages.append(entry)
    manifest = dict(schema='lightforge-game-cuda-source-input-1', totalSamples=receipt['inputProvenance']['sourceSamples'],
        language=receipt['inputProvenance']['language'], inputPcmSha256=receipt['inputProvenance']['pcmSHA256'],
        modelManifest=profiler.strict_json(args.models / 'manifest.json'), modelManifestSha256=receipt['modelManifestSha256'],
        sourceBindings=[dict(path=path, sha256=digest) for path, digest in receipt['sourceHashes'].items()],
        inputProvenance=receipt['inputProvenance'], arms=arms, passages=passages,
        experimentReceipt='receipt.json', experimentReceiptSha256=sha(args.output / 'receipt.json'),
        qualityApproved=False, benchmarkTimingAdmitted=False, target75Proven=False, releaseAuthorized=False)
    write_json(args.output / 'replay-manifest.json', manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ('models', 'input', 'input-provenance', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--toolchain', type=Path, default=ROOT.parent / 'toolchain')
    parser.add_argument('--gpu-runtime', type=Path)
    parser.add_argument('--check-readiness', action='store_true')
    args = parser.parse_args()
    for field in ('models', 'input', 'input_provenance', 'output', 'toolchain', 'gpu_runtime'):
        if getattr(args, field) is not None:
            setattr(args, field, getattr(args, field).resolve())
    require(not args.output.exists(), 'Use a new full-source evidence directory.')
    args.output.mkdir(parents=True)
    receipt = dict(schema='lightforge.game-source-cuda-experiment.v1', status='INCOMPLETE',
        createdUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(), measured=False,
        qualityApproved=False, benchmarkTimingAdmitted=False, target75Proven=False, wholeSongSpeedupProven=False,
        fullVocalStageSpeedupProven=False, androidSpeedupProven=False, releaseAuthorized=False,
        scope='One complete bounded public source through original GAME only; same-object CPU and deterministic heavy-only CUDA. '
              'Public mixture is not separated-vocal or whole-stage quality evidence. No timing ratio or release decision.')
    write_json(args.output / 'receipt.json', receipt)
    try:
        execute(args, receipt)
        write_json(args.output / 'receipt.json', receipt)
        if not args.check_readiness:
            replay_manifest(args, receipt)
    except Exception as error:
        receipt.update(status='OBSERVER_COMPARISON_INVALID' if isinstance(error, accel.InvalidObserver) else 'BLOCKED_OR_REJECTED',
                       failure=str(error))
        write_json(args.output / 'receipt.json', receipt)
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps({key: receipt[key] for key in ('status', 'qualityApproved', 'benchmarkTimingAdmitted', 'target75Proven')}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
