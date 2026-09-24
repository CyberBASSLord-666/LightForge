#!/usr/bin/env python3
"""Source-bound original GAME CUDA diagnostic, with no performance/quality approval.

One complete production-selected 44.1 kHz mono Float32 passage is run in four
fresh-process controls: CPU/ALL, CPU/BASIC, GPU-package CPU/BASIC, CUDA/BASIC.
Each control has a plain production snapshot, a raw-capture twin, and a separate
raw-capture/profile twin. Final unrounded notes must match between observers;
all 16 captured tensors must match with profiling off/on. Cross-provider tensor
differences are retained as diagnostics, never rounded into quality approval.
No repeated timing, model conversion, source edit, upload or release occurs.

Required input provenance schema: lightforge.game-passage-input.v1, with
pcmSHA256, sourceSHA256, sourceSamples, passageIndex, firstSample, lastSample,
sampleRate=44100, seed, language, and a nonempty derivation description. The
passage must follow the original 12-second core / 2-second halo schedule.
sourceSHA256 identifies the full source file or full source PCM before slicing;
the derivation describes which. This metadata is a binding, not proof of origin.
"""
import argparse
import datetime
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


accel = module('deux_accelerator_reuse', ROOT / 'tools/benchmark_deux_accelerator.py')
comparator = module('game_raw_comparator', ROOT / 'tools/game_benchmark/compare.py')
profiler = accel.profiler
require, sha, write_json = accel.require, accel.sha, accel.write_json
SOURCE = ROOT / 'android/src/com/cyberbasslord/lightforge/NativeGame.java'
HELPERS = [ROOT / 'tools/game_benchmark' / name for name in
           ('GameAcceleratorCapture.java', 'GameAcceleratorRunner.java')]
GRAPHS = ('encoder', 'dur2bd', 'segmenter', 'bd2dur', 'estimator')
CALLS = {name: 8 if name == 'segmenter' else 1 for name in GRAPHS}
HEAVY_GRAPHS = {'encoder', 'segmenter', 'estimator'}
VARIANTS = accel.VARIANTS
OPT_ANCHOR = '                    options.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT);'
CREATE_ANCHOR = '                    sessions.put(GRAPHS[i],environment.createSession('
RUN_ANCHOR = '        OrtSession.Result result=sessions.get(graph).run(input,activeRun);'
RETURN_ANCHOR = '        try{check(cancellation);return result;}catch(Exception|Error error){retire(result);throw error;}'
MODES = ('plain', 'captured', 'profiled')


def requested_graph_providers(variant, cuda_heavy_only=False):
    require(variant in VARIANTS, 'Unknown GAME variant.')
    return {graph: ('CUDAExecutionProvider' if variant == 'cuda_basic' and
                   (not cuda_heavy_only or graph in HEAVY_GRAPHS) else 'CPUExecutionProvider')
            for graph in GRAPHS}


def variant_source(source, variant, cuda_heavy_only=False):
    require(variant in VARIANTS, 'Unknown GAME variant.')
    require(source.count(OPT_ANCHOR) == 1 and source.count(CREATE_ANCHOR) == 1,
            'Production GAME session anchors changed; review the experiment.')
    require('addCUDA(' not in source and 'enableProfiling(' not in source and
            'GameAcceleratorCapture' not in source, 'Production GAME already contains experiment changes.')
    if variant == 'cpu_all':
        return source
    changed = source.replace(OPT_ANCHOR, OPT_ANCHOR.replace('ALL_OPT', 'BASIC_OPT'))
    if variant == 'cuda_basic':
        options = ''.join('                        cuda.add(' + json.dumps(key) + ',' + json.dumps(value) + ');\n'
                          for key, value in accel.CUDA_OPTIONS.items())
        injected = ('                    if(!OrtEnvironment.getAvailableProviders().contains(ai.onnxruntime.OrtProvider.CUDA))\n'
                    '                        throw new IllegalStateException("CUDA unavailable; no CPU substitution");\n'
                    '                    try(ai.onnxruntime.providers.OrtCUDAProviderOptions cuda=new ai.onnxruntime.providers.OrtCUDAProviderOptions(0)){\n'
                    + options + '                        options.addCUDA(cuda);\n                    }\n')
        if cuda_heavy_only:
            selected = requested_graph_providers(variant, cuda_heavy_only)
            condition = '||'.join(json.dumps(graph) + '.equals(GRAPHS[i])' for graph in GRAPHS
                                 if selected[graph] == 'CUDAExecutionProvider')
            injected = ('                    if(' + condition + '){\n' +
                        ''.join('    ' + line for line in injected.splitlines(keepends=True)) +
                        '                    }\n')
        changed = changed.replace(CREATE_ANCHOR, injected + CREATE_ANCHOR)
    return changed


def observed_source(source, trace_directory=None):
    require(source.count(RUN_ANCHOR) == 1 and source.count(RETURN_ANCHOR) == 1 and
            'GameAcceleratorCapture' not in source, 'GAME capture anchor changed.')
    # Capture is inside the original exception guard: its failure must retire
    # the just-returned JNI result using the unchanged production owner.
    changed = source.replace(RUN_ANCHOR, '        long researchStarted=System.nanoTime();\n' + RUN_ANCHOR)
    changed = changed.replace(RETURN_ANCHOR,
        '        try{GameAcceleratorCapture.record(graph,result,System.nanoTime()-researchStarted);check(cancellation);return result;}'
        'catch(Exception|Error error){retire(result);throw error;}')
    if trace_directory is not None:
        require(trace_directory.is_absolute() and source.count(CREATE_ANCHOR) == 1 and
                'enableProfiling(' not in source, 'Invalid GAME profiling anchor.')
        changed = changed.replace(CREATE_ANCHOR,
            '                    options.enableProfiling(new File(' + json.dumps(str(trace_directory)) +
            ',GRAPHS[i]).getAbsolutePath());\n' + CREATE_ANCHOR)
    return changed


def validate_input(pcm, provenance_path):
    require(pcm.is_file() and not pcm.is_symlink() and 0 < pcm.stat().st_size <= 16 * 44100 * 4 and
            pcm.stat().st_size % 4 == 0, 'Expected one complete <=16-second mono Float32 passage.')
    data = pcm.read_bytes()
    require(all(math.isfinite(x) for (x,) in struct.iter_unpack('<f', data)), 'Nonfinite GAME input.')
    provenance = profiler.strict_json(provenance_path)
    require(provenance.get('schema') == 'lightforge.game-passage-input.v1', 'Missing source-bound GAME provenance.')
    fields = ('sourceSamples', 'passageIndex', 'firstSample', 'lastSample', 'sampleRate', 'seed', 'language')
    require(all(type(provenance.get(key)) is int for key in fields), 'Invalid GAME passage clock/settings.')
    total, index = provenance['sourceSamples'], provenance['passageIndex']
    require(0 < total <= 44100 * 600 and 0 <= index < math.ceil(total / (44100 * 12)),
            'Invalid full-source clock or passage index; research input is bounded to ten minutes.')
    first, last = max(0, (index * 12 - 2) * 44100), min(total, ((index + 1) * 12 + 2) * 44100)
    require(provenance['firstSample'] == first and provenance['lastSample'] == last and
            len(data) == (last - first) * 4 and provenance['sampleRate'] == 44100 and
            provenance['seed'] == (2025 + index * 104729) & 0xffffffff and
            0 <= provenance['language'] <= 4, 'Input does not match original GAME core/halo/seed schedule.')
    for field in ('pcmSHA256', 'sourceSHA256'):
        require(isinstance(provenance.get(field), str) and re.fullmatch('[0-9a-f]{64}', provenance[field]),
                'Missing PCM/source SHA256 provenance.')
    require(provenance['pcmSHA256'] == sha(pcm), 'GAME PCM digest mismatch.')
    require(isinstance(provenance.get('derivation'), str) and 0 < len(provenance['derivation']) <= 4096,
            'Describe the source and PCM derivation.')
    return provenance


def verify_models(directory):
    source_manifest = ROOT / 'web/analysis/models/game/manifest.json'
    manifest_path = directory / 'manifest.json'
    require(manifest_path.is_file() and not manifest_path.is_symlink() and sha(manifest_path) == sha(source_manifest),
            'GAME manifest differs from the bound production source.')
    manifest = profiler.strict_json(manifest_path)
    require(manifest.get('id') == 'game-large-1.0.3-lightforge-1' and manifest.get('steps') == 8 and
            manifest.get('sampleRate') == 44100 and
            set(manifest['files']) == {name + '.onnx' for name in GRAPHS} | {'config.json'},
            'Original GAME model inventory and eight steps required.')
    for name, entry in manifest['files'].items():
        path = directory / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == entry['bytes'] and
                sha(path) == entry['sha256'], 'GAME model digest mismatch: ' + name)
    return manifest


def summarize_traces(directory):
    paths = list(directory.iterdir())
    require(len(paths) == 5 and all(path.is_file() and not path.is_symlink() for path in paths),
            'Exactly five regular GAME traces required.')
    graphs = []
    for name in GRAPHS:
        matches = [path for path in paths if path.name.startswith(name + '_') and path.suffix == '.json']
        require(len(matches) == 1, 'Missing or duplicate GAME trace: ' + name)
        path = matches[0]
        events = profiler.strict_json(path)
        require(isinstance(events, list) and events, 'Empty GAME trace.')
        kernels, runs = [], []
        for event in events:
            require(isinstance(event, dict), 'Invalid GAME trace event.')
            if event.get('ph') != 'X':
                continue
            elapsed = profiler.duration(event.get('dur'))
            profiler.duration(event.get('ts'))
            if event.get('cat') == 'Session' and event.get('name') == 'model_run':
                runs.append(elapsed)
            if event.get('cat') == 'Node' and str(event.get('name', '')).endswith('_kernel_time'):
                args = event.get('args')
                require(isinstance(args, dict), 'Missing GAME kernel metadata.')
                provider, operator = args.get('provider'), args.get('op_name')
                require(isinstance(provider, str) and re.fullmatch('[A-Za-z0-9_]{1,100}ExecutionProvider', provider)
                        and isinstance(operator, str) and re.fullmatch('[A-Za-z0-9_.:]{1,128}', operator),
                        'Invalid GAME kernel provider/operator.')
                kernels.append(dict(provider=provider, operator=operator, calls=1, durationUs=elapsed))
        require(len(runs) == CALLS[name] and kernels and sum(x['durationUs'] for x in kernels) > 0,
                'Incomplete GAME graph trace: ' + name)
        graphs.append(dict(graph=name, modelRuns=len(runs), traceSha256=sha(path), traceBytes=path.stat().st_size,
                           traceFile=path.name, operators=profiler.aggregate(kernels)))
    operators = profiler.aggregate(item for graph in graphs for item in graph['operators'])
    return dict(graphs=graphs, graphCount=5, modelRuns=12, operators=operators,
                durationMeaning='ORT host kernel-event duration including dispatch/scheduling; not GPU device time or wall-time speedup.')


def validate_placement(summary, variant, cuda_heavy_only=False):
    require(summary.get('graphCount') == 5 and summary.get('modelRuns') == 12 and
            {row['graph'] for row in summary['graphs']} == set(GRAPHS), 'Complete 5-graph/12-call GAME traces required.')
    rows = [item for graph in summary['graphs'] for item in graph['operators']]
    providers = {row['provider'] for row in rows}
    allowed = {'CPUExecutionProvider', 'CUDAExecutionProvider'} if variant == 'cuda_basic' else {'CPUExecutionProvider'}
    require(providers and providers <= allowed, 'Unexpected GAME execution provider.')
    if variant == 'cuda_basic':
        for graph in summary['graphs']:
            if graph['graph'] in HEAVY_GRAPHS:
                require(any(row['provider'] == 'CUDAExecutionProvider' and row['operator'] in accel.HEAVY_OPERATORS and
                            row['calls'] > 0 and row['durationUs'] > 0 for row in graph['operators']),
                        'No substantive CUDA arithmetic for GAME ' + graph['graph'])
            elif cuda_heavy_only:
                require(graph['operators'] and all(row['provider'] == 'CPUExecutionProvider'
                        for row in graph['operators']),
                        'Conversion graph must execute only on CPU: ' + graph['graph'])
    placement = dict(observedProviders=sorted(providers),
                heavyGraphsExecuteCudaArithmetic=variant == 'cuda_basic',
                cpuFallbackKernelEvents=sum(row['calls'] for row in rows if row['provider'] == 'CPUExecutionProvider')
                    if variant == 'cuda_basic' else 0,
                durationBoundaryGraphsMayRemainOnCpu=True, timingMeaning=summary['durationMeaning'])
    if cuda_heavy_only:
        placement['durationBoundaryGraphsRequiredOnCpu'] = True
    return placement


def compile_snapshot(directory, source, java, dependencies):
    directory.mkdir()
    snapshot = directory / 'NativeGame.java'
    snapshot.write_text(source, encoding='utf-8')
    copied = [snapshot]
    for helper in HELPERS:
        target = directory / helper.name
        shutil.copyfile(helper, target)
        copied.append(target)
    classes = directory / 'classes'
    classes.mkdir()
    command = [str(java / 'javac'), '--release', '8', '-encoding', 'UTF-8', '-cp',
               os.pathsep.join(map(str, dependencies)), '-d', str(classes), *map(str, copied)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    (directory / 'compile.log').write_text(result.stdout + result.stderr)
    require(result.returncode == 0, 'GAME snapshot compilation failed: ' + str(directory / 'compile.log'))
    return classes, copied + list(classes.rglob('*.class'))


def run_once(variant, mode, directory, classes, java, dependencies, args, provenance, manifest):
    output = directory / 'output'
    maps = directory / 'cuda-jvm-loaded-library-maps.txt'
    command = [str(java / 'java'), '-Xmx2g', '-XX:MaxDirectMemorySize=2g', '-cp',
               os.pathsep.join(map(str, [classes, *dependencies])), 'com.cyberbasslord.lightforge.GameAcceleratorRunner',
               str(args.models), str(args.input), str(output), str(provenance['seed']), str(provenance['language']),
               str(mode != 'plain').lower(), str(maps) if variant == 'cuda_basic' and mode == 'profiled' else '']
    print(variant + ' ' + mode, flush=True)
    started = time.perf_counter_ns()
    result = subprocess.run(command, capture_output=True, text=True, timeout=1200)
    process_wall = time.perf_counter_ns() - started
    (directory / 'run.log').write_text(result.stdout + result.stderr)
    require(result.returncode == 0, 'GAME inference failed: ' + str(directory / 'run.log'))
    receipt_path = output / 'receipt.json'
    receipt = profiler.strict_json(receipt_path)
    require(receipt.get('schema') == 'lightforge-game-benchmark-1' and receipt.get('steps') == 8 and
            receipt.get('pcmSHA256') == provenance['pcmSHA256'] and receipt.get('modelFiles') == manifest['files'] and
            receipt.get('samples') == provenance['lastSample'] - provenance['firstSample'] and
            receipt.get('sampleRate') == 44100 and receipt.get('seed') == provenance['seed'] and
            receipt.get('language') == provenance['language'] and receipt.get('capture') is (mode != 'plain') and
            receipt.get('retirementConfirmed') is True and receipt.get('runtime') == 'onnxruntime-java-1.25.1' and
            type(receipt.get('wallNanos')) is int and receipt['wallNanos'] > 0, 'Invalid GAME execution receipt.')
    if mode != 'plain':
        comparator.load(output)
    return dict(variant=variant, mode=mode, receipt=str(receipt_path.relative_to(args.output)),
                receiptSha256=sha(receipt_path), wallNanos=receipt['wallNanos'], notes=receipt['notes'],
                capturedGraphInferenceSeconds=receipt['inferenceSeconds'],
                processWallIncludingStartupAndInspectionNanos=process_wall, timingEligible=False), receipt


def validate_observers(comparisons):
    if not comparisons or not all(item.get('unroundedNotesIdentical') is True for item in comparisons):
        raise accel.InvalidObserver('GAME observer changed final notes; observer comparison invalid.')
    if not all(item.get('rawTensorsByteIdentical') is True for item in comparisons
               if item.get('kind') == 'capture-vs-profile'):
        raise accel.InvalidObserver('GAME profiling changed raw tensors; observer comparison invalid.')


def execute(args, receipt):
    require(not any(os.environ.get(key) for key in ('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS')),
            'Unset Java option injection variables.')
    for key, value in [('CUBLAS_WORKSPACE_CONFIG', ':4096:8'), ('NVIDIA_TF32_OVERRIDE', '0')]:
        require(os.environ.get(key, value) == value, 'Unexpected ' + key)
        os.environ[key] = value
    provenance = validate_input(args.input, args.input_provenance)
    manifest = verify_models(args.models)
    runtime = profiler.strict_json(ROOT / 'android/native-runtime.json')
    require(runtime['version'] == '1.25.1', 'Production ORT version changed.')
    java = args.toolchain.resolve() / 'jdk17/bin'
    host = args.toolchain / 'onnx' / runtime['host']['name']
    gpu = args.gpu_runtime or args.toolchain / 'onnx' / accel.GPU_RUNTIME['name']
    shared = [args.toolchain / 'test-json.jar', args.toolchain / 'android-sdk/platforms/android-35/android.jar']
    require(all(path.is_file() and not path.is_symlink() for path in shared), 'Missing compilation dependencies.')
    accel.verify_runtime(host, runtime['host'])
    variants = VARIANTS[:2] if args.cpu_control_only else VARIANTS
    if not args.cpu_control_only:
        require(sys.platform.startswith('linux'), 'CUDA library observations require Linux.')
        accel.verify_runtime(gpu, accel.GPU_RUNTIME)
        receipt['gpuInventory'] = accel.gpu_inventory()
    dependencies = {name: [*shared, gpu if name in VARIANTS[2:] else host] for name in variants}
    bound_source = [SOURCE, *HELPERS, Path(__file__), ROOT / 'tools/game_benchmark/compare.py',
                    ROOT / 'tools/benchmark_deux_accelerator.py', ROOT / 'tools/profile_deux_operators.py',
                    ROOT / 'tools/benchmark_deux_execution.py', ROOT / 'android/native-runtime.json',
                    ROOT / 'web/analysis/models/game/manifest.json']
    files = set(bound_source + [args.input, args.input_provenance, *shared, host, args.models / 'manifest.json'] +
                [args.models / name for name in manifest['files']] + ([] if args.cpu_control_only else [gpu]))
    hashes = {path: sha(path) for path in files}
    receipt.update(host=accel.benchmark.host_metadata(), inputProvenance=provenance,
        inputProvenanceSha256=sha(args.input_provenance), modelManifestSha256=sha(args.models / 'manifest.json'),
        modelHashes={name: entry['sha256'] for name, entry in manifest['files'].items()},
        sourceHashes={str(path.relative_to(ROOT)): hashes[path] for path in bound_source},
        dependencyHashes={path.name: hashes[path] for path in [*shared, host, *([] if args.cpu_control_only else [gpu])]},
        variants=list(variants), modes=list(MODES), cudaOptions=accel.CUDA_OPTIONS,
        cudaHeavyOnly=args.cuda_heavy_only,
        requestedGraphProviders={name: requested_graph_providers(name, args.cuda_heavy_only) for name in variants},
        cublasWorkspaceConfig=':4096:8', nvidiaTf32Override='0',
        deterministicCompute='Runtime default; no guarantee that all CUDA kernels are deterministic.',
        requestedCudaLogicalDevice=0,
        cudaVisibility={key: os.environ.get(key) for key in ('CUDA_VISIBLE_DEVICES', 'CUDA_DEVICE_ORDER')},
        gpuMappingNote='Physical inventory does not independently establish logical device 0 mapping.',
        runs=[], observerComparisons=[], crossVariantComparisons=[], providerTraces={}, placement={},
        observerScope='Plain/capture compares final unrounded notes; capture/profile compares every raw tensor and final note. '
                      'Raw tensors are unobserved in plain production snapshots.',
        runtimeProbes=[accel.probe_runtime(java, dependencies['cpu_all'], args.output / 'cpu-runtime-probe', False)])
    accel.verify_java_api(java, host)
    if not args.cpu_control_only:
        accel.verify_java_api(java, gpu)
        receipt['runtimeProbes'].append(accel.probe_runtime(java, dependencies['cuda_basic'], args.output / 'gpu-runtime-probe', True))
    write_json(args.output / 'receipt.json', receipt)
    if args.check_readiness:
        receipt['status'] = 'PREFLIGHT_READY'
        return
    outputs = {}
    source = SOURCE.read_text()
    for variant in variants:
        mode_receipts = {}
        for mode in MODES:
            directory = args.output / (variant + '_' + mode)
            snapshot = variant_source(source, variant, args.cuda_heavy_only)
            trace_dir = args.output / (variant + '_traces')
            if mode == 'profiled':
                trace_dir.mkdir()
            if mode != 'plain':
                snapshot = observed_source(snapshot, trace_dir if mode == 'profiled' else None)
            classes, artifacts = compile_snapshot(directory, snapshot, java, dependencies[variant])
            for path in artifacts:
                hashes[path] = sha(path)
            row, mode_receipts[mode] = run_once(variant, mode, directory, classes, java, dependencies[variant], args, provenance, manifest)
            receipt['runs'].append(row)
            for path in (directory / 'output').iterdir():
                require(path.is_file() and not path.is_symlink(), 'Unexpected GAME output artifact.')
                hashes[path] = sha(path)
            write_json(args.output / 'receipt.json', receipt)
        outputs[variant] = args.output / (variant + '_captured') / 'output'
        observed = comparator.compare(outputs[variant], args.output / (variant + '_profiled') / 'output')
        receipt['observerComparisons'].extend([
            dict(variant=variant, kind='plain-vs-capture', rawTensorsByteIdentical=None,
                 unroundedNotesIdentical=mode_receipts['plain']['notes'] == mode_receipts['captured']['notes']),
            dict(variant=variant, kind='capture-vs-profile', rawTensorsByteIdentical=observed['exactParity'],
                 unroundedNotesIdentical=observed['unroundedNotesIdentical'], rawComparison=observed)])
        summary = summarize_traces(trace_dir)
        receipt['providerTraces'][variant] = summary
        receipt['placement'][variant] = validate_placement(summary, variant, args.cuda_heavy_only)
        for path in trace_dir.iterdir():
            hashes[path] = sha(path)
        if variant == 'cuda_basic':
            maps = args.output / (variant + '_profiled') / 'cuda-jvm-loaded-library-maps.txt'
            libraries = accel.native_library_paths(maps)
            receipt['gpuNativeLibraries'] = {str(path): dict(bytes=path.stat().st_size, sha256=sha(path)) for path in libraries}
            receipt['gpuNativeLibraryVersions'] = accel.native_library_versions(libraries)
            for path in [maps, *libraries]:
                hashes[path] = sha(path)
        write_json(args.output / 'receipt.json', receipt)
    for left, right in list(zip(variants, variants[1:])) + ([] if len(variants) < 4 else [('cpu_all', 'cuda_basic')]):
        comparison = comparator.compare(outputs[left], outputs[right])
        comparison.update(reference=left, candidate=right, qualityApproved=False, tolerance=None)
        receipt['crossVariantComparisons'].append(comparison)
    for path, expected in hashes.items():
        require(path.is_file() and sha(path) == expected, 'Bound GAME source/model/runtime/input changed: ' + str(path))
    receipt['compiledSnapshotHashes'] = {str(path.relative_to(args.output)): digest for path, digest in hashes.items()
                                         if path.is_relative_to(args.output)}
    receipt['inputsRecheckedAfterQualification'] = True
    validate_observers(receipt['observerComparisons'])
    receipt['observerComparisonsPassed'] = True
    receipt['rawOutputsByteIdenticalAcrossVariants'] = all(row['exactParity'] for row in receipt['crossVariantComparisons'])
    receipt['status'] = ('CPU_CONTROL_DIAGNOSTIC_COMPLETE' if args.cpu_control_only else 'CUDA_DIAGNOSTIC_COMPLETE')
    if not receipt['rawOutputsByteIdenticalAcrossVariants']:
        receipt['status'] = 'NUMERICAL_EQUIVALENCE_UNPROVEN'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--input-provenance', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--toolchain', type=Path, default=ROOT.parent / 'toolchain')
    parser.add_argument('--gpu-runtime', type=Path)
    parser.add_argument('--check-readiness', action='store_true')
    parser.add_argument('--cpu-control-only', action='store_true')
    parser.add_argument('--cuda-heavy-only', action='store_true',
                        help='Request CUDA only for encoder/segmenter/estimator; run the unchanged conversion graphs on CPU.')
    args = parser.parse_args()
    if args.cuda_heavy_only and args.cpu_control_only:
        parser.error('--cuda-heavy-only requires the full CUDA controls, not --cpu-control-only.')
    for field in ('models', 'input', 'input_provenance', 'output', 'toolchain'):
        setattr(args, field, getattr(args, field).resolve())
    if args.gpu_runtime:
        args.gpu_runtime = args.gpu_runtime.resolve()
    require(not args.output.exists(), 'Use a new GAME evidence directory.')
    args.output.mkdir(parents=True)
    receipt = dict(schema='lightforge.game-accelerator-experiment.v1',
        createdUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(), status='INCOMPLETE',
        measured=False, qualityApproved=False, target75Proven=False, wholeSongSpeedupProven=False,
        fullVocalStageSpeedupProven=False, androidSpeedupProven=False, releaseAuthorized=False,
        scope='One source-bound original GAME passage; single diagnostic observations only; '
              'excludes classification, vocal detail/fusion, network, queueing and Android.')
    write_json(args.output / 'receipt.json', receipt)
    try:
        execute(args, receipt)
    except Exception as error:
        receipt.update(status='OBSERVER_COMPARISON_INVALID' if isinstance(error, accel.InvalidObserver)
                       else 'BLOCKED_OR_REJECTED', failure=str(error))
        write_json(args.output / 'receipt.json', receipt)
        print(str(error), file=sys.stderr)
        return 1
    write_json(args.output / 'receipt.json', receipt)
    print(json.dumps({key: receipt[key] for key in ('status', 'measured', 'qualityApproved', 'target75Proven')}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
