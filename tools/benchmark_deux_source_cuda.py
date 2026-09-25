#!/usr/bin/env python3
"""Complete <=64-second public-source Deux CPU/CUDA diagnostic collection.

Four fresh JVMs each execute the original production passage schedule with one
NativeDeux object: CPU/ALL plain and profiled, CUDA/BASIC plain and profiled.
All original Float32 graphs, 335 calls per passage, context, padding and batching
are retained. Same-provider output bytes must match exactly. Cross-provider
differences remain unapproved diagnostics; this tool never computes a speed
ratio or authorizes quality, Android use or a release. The actual unchanged
production separator owns later overlap/checkpoint/stem-cache replay.
"""
import argparse
import array
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('deux_source_accelerator', ROOT / 'tools/benchmark_deux_accelerator.py')
accel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(accel)
profiler, benchmark = accel.profiler, accel.benchmark
require, sha, write_json = accel.require, accel.sha, accel.write_json
RATE, SAMPLES, HALO, CORE, STRIDE, MAX_SAMPLES = 44100, 573300, 66150, 441000, 220500, 64 * 44100
VARIANTS, MODES = ('cpu_all', 'cuda_basic'), ('plain', 'profiled')
RUNNER = ROOT / 'tools/deux_benchmark/DeuxSourceRunner.java'
TRACE = ROOT / 'tools/deux_benchmark/DeuxSourceTrace.java'
TRACE_LAYOUT = 'passage-owned-no-move-v1'
SOURCE_BINDINGS = (
    'tools/benchmark_deux_source_cuda.py', 'tools/deux_benchmark/DeuxSourceRunner.java',
    'tools/deux_benchmark/DeuxSourceTrace.java',
    'tools/benchmark_deux_accelerator.py', 'tools/profile_deux_operators.py',
    'tools/benchmark_deux_execution.py', 'android/native-runtime.json',
    'android/src/com/cyberbasslord/lightforge/NativeDeux.java',
    'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java',
    'android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java',
    'web/analysis/models/deux/manifest.json', 'web/analysis/models/features.json',
    'web/analysis/separator-deux.js', 'web/analysis/dsp.js', 'web/analysis/wav-reader.js',
    'web/analysis/stem-cache.js', 'web/analysis/work-store.js', 'tools/deux_benchmark/replay_source.cjs',
)


def passage_plan(samples):
    require(type(samples) is int and 0 < samples <= MAX_SAMPLES,
            'Expected a complete source clock of at most 64 seconds.')
    count = 1 + max(0, (samples - CORE + STRIDE - 1) // STRIDE)
    return [dict(index=i, startSample=i * STRIDE - HALO, outputOffset=i * STRIDE,
                 emitSamples=min(CORE, samples - i * STRIDE) if i == count - 1 else STRIDE)
            for i in range(count)]


def stereo_proof(pcm16, row):
    """Independent PCM16 / 32768 reader, retaining channel order and exact zero padding."""
    frame_count = len(pcm16) // 4
    first, last = max(0, row['startSample']), min(frame_count, row['startSample'] + SAMPLES)
    require(last > first, 'Production context must overlap the input.')
    integers = array.array('h', pcm16[first * 4:last * 4])
    if sys.byteorder != 'little':
        integers.byteswap()
    prefix = first - row['startSample']
    suffix = SAMPLES - prefix - (last - first)
    digest = hashlib.sha256()
    peak = max(abs(value) for value in integers) / 32768
    for channel in (0, 1):
        values = array.array('f', (value / 32768 for value in integers[channel::2]))
        if sys.byteorder != 'little':
            values.byteswap()
        digest.update(b'\0' * (prefix * 4))
        digest.update(values.tobytes())
        digest.update(b'\0' * (suffix * 4))
    return digest.hexdigest(), peak


def validate_input(audio, provenance_path):
    require(audio.is_file() and not audio.is_symlink() and 44 <= audio.stat().st_size <= 16 * 1024 * 1024,
            'Expected a bounded regular public PCM16 WAV.')
    frames = accel.validate_audio(audio)
    plan = passage_plan(frames)
    provenance = profiler.strict_json(provenance_path)
    require(provenance.get('schema') == 'lightforge.deux-source-input.v1' and
            type(provenance.get('sampleRate')) is int and provenance['sampleRate'] == RATE and
            type(provenance.get('sourceSamples')) is int and provenance['sourceSamples'] == frames,
            'Provenance does not bind the complete original stereo source clock.')
    require(isinstance(provenance.get('audioSha256'), str) and re.fullmatch('[a-f0-9]{64}', provenance['audioSha256']) and
            provenance['audioSha256'] == sha(audio), 'Complete WAV digest mismatch.')
    require(provenance.get('sourceKind') in ('public-mixture', 'synthetic'), 'Explicit public or synthetic input required.')
    require(isinstance(provenance.get('derivation'), str) and 0 < len(provenance['derivation']) <= 4096,
            'Describe the complete public source provenance.')
    with wave.open(str(audio), 'rb') as stream:
        pcm16 = stream.readframes(frames)
    for row in plan:
        row['inputStereoSha256'], peak = stereo_proof(pcm16, row)
        # Actual production skips a silent context. This initial collector only
        # handles sources requiring every planned inference; never invent calls.
        require(peak >= 1e-7, 'Silent context unsupported by complete-capture experiment: ' + str(row['index']))
    return provenance, plan


def execution_identity(variant):
    require(variant in VARIANTS, 'Unknown complete-source variant.')
    cuda = variant == 'cuda_basic'
    return dict(runtime='onnxruntime-java-1.25.1', package='gpu' if cuda else 'cpu',
                provider='CUDAExecutionProvider' if cuda else 'CPUExecutionProvider',
                optimization='BASIC_OPT' if cuda else 'ALL_OPT',
                deterministicComputeOverride=None,
                deterministicComputeNote='Unchanged runtime default, matching the qualified Deux snapshot; no universal kernel determinism guarantee.')


def bind_java_identity(java):
    """Bind the compiler, JVM and Java modules actually used by every child."""
    jdk = java.parent
    required = ('bin/java', 'bin/javac', 'bin/javap', 'lib/modules', 'lib/server/libjvm.so',
                'lib/libjava.so', 'lib/libjli.so', 'release', 'conf/security/java.security')
    paths = [jdk / relative for relative in required]
    require(all(path.is_file() and not path.is_symlink() for path in paths), 'Missing regular Java 17 runtime/compiler identity files.')
    hashes = {path: sha(path) for path in paths}
    versions = {}
    for name, option in (('java', '-version'), ('javac', '-version'), ('javap', '-version')):
        result = subprocess.run([str(java / name), option], capture_output=True, text=True, timeout=30)
        observed = (result.stdout + result.stderr).strip()
        require(result.returncode == 0 and len(observed) < 16384 and
                re.search(r'(?:version \"|javac |^)17\.', observed), 'Expected observed Java 17 executable: ' + name)
        versions[name] = observed
    return dict(executables=versions,
                files={str(path.relative_to(jdk)): dict(bytes=path.stat().st_size, sha256=hashes[path]) for path in paths},
                scope='Observed Java launchers, compiler modules, JVM, core native libraries, release metadata and security configuration; rechecked after execution.'), hashes


def source_snapshot(original, variant, mode, traces=None, maps=None):
    require(variant in VARIANTS and mode in MODES, 'Unknown variant or observation mode.')
    require((traces is not None) == (mode == 'profiled'), 'Profiling requires its own trace directory.')
    require((maps is not None) == (mode == 'profiled' and variant == 'cuda_basic'), 'Unexpected CUDA library-map observer.')
    source = accel.variant_source(original, variant)
    if traces is not None:
        source = profiler.instrument_source(source, traces)
        anchor = 'options.enableProfiling(new File(' + json.dumps(str(traces), ensure_ascii=True) + ',name).getAbsolutePath());'
        require(source.count(anchor) == 1, 'Exact profiling observer anchor changed.')
        source = source.replace(anchor, 'options.enableProfiling(DeuxSourceTrace.prefix(name,' +
                                json.dumps(str(traces), ensure_ascii=True) + '));')
    if maps is not None:
        source = accel.capture_library_maps(source, maps)
    return source


def compile_snapshot(directory, source, java, dependencies):
    directory.mkdir(parents=True)
    snapshot = directory / 'NativeDeux.java'
    snapshot.write_text(source, encoding='utf-8')
    stub = directory / 'AppDiagnostics.java'
    stub.write_text('package com.cyberbasslord.lightforge; public final class AppDiagnostics {'
                    'public static void log(android.content.Context c,String l,String s,String m){}'
                    'public static boolean flush(long timeout){return true;}}\n')
    sources = [snapshot, stub]
    for helper in (RUNNER, TRACE, accel.SOURCE / 'NativeDeuxTransform.java', accel.SOURCE / 'NativeInferenceProfile.java'):
        target = directory / helper.name
        shutil.copyfile(helper, target)
        require(sha(target) == sha(helper), 'Copied original/research helper changed.')
        sources.append(target)
    classes = directory / 'classes'
    classes.mkdir()
    result = subprocess.run([str(java / 'javac'), '--release', '8', '-encoding', 'UTF-8', '-cp',
        os.pathsep.join(map(str, dependencies)), '-d', str(classes), *map(str, sources)],
        capture_output=True, text=True, timeout=90)
    (directory / 'compile.log').write_text(result.stdout + result.stderr)
    require(result.returncode == 0, 'Complete-source Deux compilation failed: ' + str(directory / 'compile.log'))
    return classes, sources + list(classes.rglob('*.class'))


def run_process(command, log, timeout):
    """Always retire the complete fresh JVM group, including cancellation/timeout."""
    with log.open('x') as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    require(code == 0, 'Full-source Deux process failed: ' + str(log))


def validate_run(directory, mode, provenance, plan, manifest):
    receipt = profiler.strict_json(directory / 'receipt.json')
    require(receipt.get('schema') == 'lightforge-deux-source-run-1' and
            receipt.get('runtime') == 'onnxruntime-java-1.25.1' and receipt.get('sampleRate') == RATE and
            receipt.get('audioFrames') == provenance['sourceSamples'] and receipt.get('audioSha256') == provenance['audioSha256'] and
            receipt.get('modelFiles') == manifest['files'] and receipt.get('profiled') is (mode == 'profiled') and
            receipt.get('engineObjects') == 1 and receipt.get('engineCloseReturned') is True and
            receipt.get('traceLayout') == (TRACE_LAYOUT if mode == 'profiled' else None) and
            receipt.get('allPredictionsReturned') is True and receipt.get('passageCount') == len(plan) and
            type(receipt.get('wallNanos')) is int and receipt['wallNanos'] > 0,
            'Invalid complete-source execution receipt.')
    require(all(receipt.get(key) is False for key in ('qualityApproved', 'benchmarkTimingAdmitted', 'target75Proven', 'releaseAuthorized')),
            'Unexpected approval in a diagnostic run.')
    require(isinstance(receipt.get('passages'), list) and len(receipt['passages']) == len(plan), 'Incomplete passage receipts.')
    require({path.name for path in directory.iterdir()} == {'receipt.json', *(f"passage-{row['index']:03d}" for row in plan)},
            'Unexpected complete-source output member.')
    for row, nested in zip(plan, receipt['passages']):
        path = directory / f"passage-{row['index']:03d}"
        item = profiler.strict_json(path / 'receipt.json')
        expected = dict(schema='lightforge-deux-source-passage-1', **row, sampleRate=RATE, samplesPerStem=SAMPLES,
            sourceSamples=provenance['sourceSamples'], sourceSha256=provenance['audioSha256'],
            outputFile=f"passage-{row['index']:03d}/stems.f32", outputBytes=2 * SAMPLES * 4)
        require(item == nested and all(item.get(key) == value for key, value in expected.items()) and
                item.get('profiled') is (mode == 'profiled') and item.get('predictReturned') is True and
                item.get('traceLayout') == (TRACE_LAYOUT if mode == 'profiled' else None) and
                item.get('benchmarkTimingAdmitted') is False and type(item.get('wallNanos')) is int and item['wallNanos'] > 0,
                'Invalid source-bound passage receipt: ' + str(row['index']))
        require(benchmark.read_output(path / 'stems.f32') == item.get('outputSha256') and
                sha(path / 'profile.txt') == item.get('profileSha256'), 'Passage output/profile digest mismatch.')
        benchmark.profile_fields(path / 'profile.txt')
        require((path / 'traces').is_dir() is (mode == 'profiled'), 'Unexpected or absent ORT trace observer.')
        require({child.name for child in path.iterdir()} ==
                {'receipt.json', 'profile.txt', 'stems.f32', *(['traces'] if mode == 'profiled' else [])},
                'Unexpected passage output member.')
        if mode == 'profiled':
            verify_trace_inventory(path / 'traces', item.get('traceFiles'))
        else:
            require(item.get('traceFiles') is None, 'Plain passage contains trace inventory.')
    return receipt


def verify_trace_inventory(directory, expected):
    require(isinstance(expected, dict) and len(expected) == 27, 'Exactly 27 receipt-bound passage traces required.')
    actual = list(directory.iterdir())
    require(len(actual) == 27 and all(path.is_file() and not path.is_symlink() for path in actual),
            'Exactly 27 regular owned passage traces required.')
    require({path.name: sha(path) for path in actual} == expected, 'Passage trace inventory changed after prediction.')
    graphs = []
    for path in actual:
        matches = [name for name in profiler.GRAPH_NAMES if path.name.startswith(name + '_') and path.suffix == '.json']
        require(len(matches) == 1, 'Unknown graph trace filename.')
        graphs.extend(matches)
    require(set(graphs) == profiler.GRAPH_NAMES and len(graphs) == len(set(graphs)), 'Missing or duplicate owned graph trace.')


def compare_observers(outputs, plan, variants=VARIANTS):
    rows = []
    for variant in variants:
        for row in plan:
            name = f"passage-{row['index']:03d}/stems.f32"
            comparison = accel.compare_outputs(outputs[variant]['plain'] / name, outputs[variant]['profiled'] / name)
            rows.append(dict(variant=variant, passageIndex=row['index'], reference=variant + '_plain',
                             candidate=variant + '_profiled', **comparison))
    return rows


def validate_observers(rows, plan, variants=VARIANTS):
    require(len(rows) == len(plan) * len(variants) and
            {(row.get('variant'), row.get('passageIndex')) for row in rows} ==
            {(variant, passage['index']) for variant in variants for passage in plan}, 'Incomplete observer comparison matrix.')
    if any(row.get('byteIdentical') is not True for row in rows):
        raise accel.InvalidObserver('Profiling changed complete passage output bytes; observer evidence is invalid.')


def verify_bound_files(hashes):
    for path, digest in hashes.items():
        require(path.is_file() and not path.is_symlink() and sha(path) == digest, 'Bound source/input/runtime/model/evidence changed: ' + str(path))


def execute(args, receipt):
    require(sys.platform.startswith('linux'), 'Process cleanup and native-library evidence require Linux.')
    require(not any(os.environ.get(key) for key in ('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS')), 'Unset Java option injection variables.')
    require(not os.environ.get('LD_PRELOAD'), 'Unset native preload injection before collecting runtime evidence.')
    for key, value in (('CUBLAS_WORKSPACE_CONFIG', ':4096:8'), ('NVIDIA_TF32_OVERRIDE', '0')):
        require(os.environ.get(key, value) == value, 'Unexpected ' + key)
        os.environ[key] = value
    variants = VARIANTS[:1] if args.cpu_only else VARIANTS
    provenance, plan = validate_input(args.audio, args.input_provenance)
    manifest = profiler.verify_models(args.models)
    runtime = profiler.strict_json(ROOT / 'android/native-runtime.json')
    require(runtime['version'] == '1.25.1', 'Production runtime changed; requalify the pinned binary.')
    java = args.toolchain / 'jdk17/bin'
    java_identity, java_hashes = bind_java_identity(java)
    host = args.toolchain / 'onnx' / runtime['host']['name']
    gpu = args.gpu_runtime or args.toolchain / 'onnx' / accel.GPU_RUNTIME['name']
    accel.verify_runtime(host, runtime['host'])
    shared = [args.toolchain / 'test-json.jar', args.toolchain / 'android-sdk/platforms/android-35/android.jar']
    jars = [host]
    if not args.cpu_only:
        accel.verify_runtime(gpu, accel.GPU_RUNTIME)
        jars.append(gpu)
    dependencies = {variant: [*shared, gpu if variant == 'cuda_basic' else host] for variant in variants}
    sources = [ROOT / path for path in SOURCE_BINDINGS]
    bound = set(sources + [args.audio, args.input_provenance, *shared, *jars, args.models / 'manifest.json'] +
                [args.models / name for name in manifest['files']])
    require(all(path.is_file() and not path.is_symlink() for path in bound), 'Missing regular source/input/model/dependency binding.')
    hashes = {path: sha(path) for path in bound}
    hashes.update(java_hashes)
    receipt.update(inputProvenance=provenance, inputProvenanceSha256=sha(args.input_provenance), passagePlan=plan,
        audioFrames=provenance['sourceSamples'], audioSha256=provenance['audioSha256'], samplesPerStem=SAMPLES,
        sourceHashes={str(path.relative_to(ROOT)): hashes[path] for path in sources},
        javaIdentity=java_identity,
        dependencyHashes={path.name: hashes[path] for path in [*shared, *jars]}, runtimeVersion=runtime['version'],
        cpuRuntime=runtime['host'], gpuRuntime=accel.GPU_RUNTIME if not args.cpu_only else None,
        modelManifestSha256=sha(args.models / 'manifest.json'), modelHashes={name: entry['sha256'] for name, entry in manifest['files'].items()},
        host=benchmark.host_metadata(), variants=list(variants), modes=list(MODES),
        executionIdentity={variant: execution_identity(variant) for variant in variants},
        cudaOptions=accel.CUDA_OPTIONS if not args.cpu_only else None, cublasWorkspaceConfig=':4096:8', nvidiaTf32Override='0',
        cudaVisibility={key: os.environ.get(key) for key in ('CUDA_VISIBLE_DEVICES', 'CUDA_DEVICE_ORDER')},
        requestedCudaLogicalDevice=0 if not args.cpu_only else None,
        gpuMappingNote='Inventory rows do not independently establish the logical-device mapping.',
        runs=[], observerComparisons=[], crossVariantComparisons=[], providerTraces={}, placement={}, runtimeProbes=[])
    if not args.cpu_only:
        receipt['gpuInventory'] = accel.gpu_inventory()
    write_json(args.output / 'receipt.json', receipt)
    for variant in variants:
        accel.verify_java_api(java, dependencies[variant][-1])
        receipt['runtimeProbes'].append(accel.probe_runtime(java, dependencies[variant], args.output / (variant + '-runtime-probe'), variant == 'cuda_basic'))
    plan_path = args.output / 'source-plan.json'
    write_json(plan_path, dict(audioFrames=provenance['sourceSamples'], audioSha256=provenance['audioSha256'], passagePlan=plan))
    hashes[plan_path] = sha(plan_path)
    source = (accel.SOURCE / 'NativeDeux.java').read_text()
    outputs = {variant: {} for variant in variants}
    compiled = {}
    for variant in variants:
        for mode in MODES:
            label = variant + '_' + mode
            directory = args.output / 'snapshots' / label
            traces = args.output / (label + '_active_traces') if mode == 'profiled' else None
            maps = directory / 'cuda-jvm-loaded-library-maps.txt' if variant == 'cuda_basic' and mode == 'profiled' else None
            if traces is not None:
                traces.mkdir()
            classes, artifacts = compile_snapshot(directory, source_snapshot(source, variant, mode, traces, maps), java, dependencies[variant])
            for path in artifacts:
                hashes[path] = sha(path)
                compiled[str(path.relative_to(args.output))] = hashes[path]
            if args.check_readiness:
                continue
            output = args.output / label
            command = [str(java / 'java'), '-Xmx1g', '-XX:MaxDirectMemorySize=512m', '-cp',
                os.pathsep.join(map(str, [classes, *dependencies[variant]])), 'com.cyberbasslord.lightforge.DeuxSourceRunner',
                str(args.models), str(args.audio), str(plan_path), str(output), str(traces) if traces else '']
            print(label + ' complete source: ' + str(len(plan)) + ' passages', flush=True)
            started = time.perf_counter_ns()
            run_process(command, directory / 'run.log', 1200 * len(plan))
            process_wall = time.perf_counter_ns() - started
            item = validate_run(output, mode, provenance, plan, manifest)
            outputs[variant][mode] = output
            receipt['runs'].append(dict(label=label, variant=variant, provider=execution_identity(variant)['provider'],
                observation=mode, outputDirectory=label, receipt=label + '/receipt.json', receiptSha256=sha(output / 'receipt.json'),
                wallNanos=item['wallNanos'], processWallIncludingStartupAndInspectionNanos=process_wall,
                passageCount=len(plan), passages=item['passages'], freshProcessExited=True, timingEligible=False))
            for path in output.rglob('*'):
                require(not path.is_symlink(), 'Unexpected output evidence symlink.')
                if path.is_file():
                    hashes[path] = sha(path)
            if mode == 'profiled':
                summaries, placements = [], []
                for row in plan:
                    summary = profiler.summarize_traces(output / f"passage-{row['index']:03d}" / 'traces')
                    summaries.append(dict(passageIndex=row['index'], **summary))
                    placements.append(dict(passageIndex=row['index'], **accel.validate_placement(summary, variant)))
                receipt['providerTraces'][variant], receipt['placement'][variant] = summaries, placements
                require(not list(traces.iterdir()), 'Not all completed graph traces were moved into passage evidence.')
                if variant == 'cuda_basic':
                    libraries = accel.native_library_paths(maps)
                    receipt['gpuNativeLibraries'] = {str(path): dict(bytes=path.stat().st_size, sha256=sha(path)) for path in libraries}
                    receipt['gpuNativeLibraryVersions'] = accel.native_library_versions(libraries)
                    hashes.update({path: sha(path) for path in [maps, *libraries]})
            write_json(args.output / 'receipt.json', receipt)
    verify_bound_files(hashes)
    receipt.update(inputsRecheckedAfterQualification=True, compiledSnapshotHashes=compiled)
    if args.check_readiness:
        receipt.update(status='PREFLIGHT_READY', inferenceExecuted=False, readinessSnapshotCount=len(variants) * len(MODES))
        return
    receipt['observerComparisons'] = compare_observers(outputs, plan, variants)
    if not args.cpu_only:
        for row in plan:
            name = f"passage-{row['index']:03d}/stems.f32"
            comparison = accel.compare_outputs(outputs['cpu_all']['plain'] / name, outputs['cuda_basic']['plain'] / name)
            receipt['crossVariantComparisons'].append(dict(passageIndex=row['index'], reference='cpu_all_plain', candidate='cuda_basic_plain', **comparison))
    # Recheck again after reading raw evidence for all comparisons.
    verify_bound_files(hashes)
    receipt['artifactHashes'] = {str(path.relative_to(args.output)): digest for path, digest in hashes.items() if path.is_relative_to(args.output)}
    receipt['allInputAndArtifactHashesRechecked'] = True
    validate_observers(receipt['observerComparisons'], plan, variants)
    receipt['observerComparisonsPassed'] = True
    receipt['rawOutputsByteIdenticalAcrossVariants'] = None if args.cpu_only else all(row['byteIdentical'] for row in receipt['crossVariantComparisons'])
    receipt['status'] = ('CPU_SOURCE_DIAGNOSTIC_COMPLETE' if args.cpu_only else 'COMPLETE_DIAGNOSTIC'
        if receipt['rawOutputsByteIdenticalAcrossVariants'] else 'NUMERICAL_EQUIVALENCE_UNPROVEN')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ('models', 'audio', 'input-provenance', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--toolchain', type=Path, default=ROOT.parent / 'toolchain')
    parser.add_argument('--gpu-runtime', type=Path)
    parser.add_argument('--check-readiness', action='store_true')
    parser.add_argument('--cpu-only', action='store_true', help='Complete CPU observer diagnostics only; does not produce CUDA evidence.')
    args = parser.parse_args()
    for field in ('models', 'audio', 'input_provenance', 'output', 'toolchain', 'gpu_runtime'):
        if getattr(args, field) is not None:
            setattr(args, field, getattr(args, field).absolute())
    require(not args.output.exists() and not args.output.is_symlink(), 'Use a new evidence directory; never overwrite prior work.')
    args.output.mkdir(parents=True)
    receipt = dict(schema='lightforge.deux-source-cuda-experiment.v1', status='INCOMPLETE',
        createdUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(), measured=False,
        qualityApproved=False, benchmarkTimingAdmitted=False, target75Proven=False, wholeSongSpeedupProven=False,
        fullVocalStageSpeedupProven=False, androidSpeedupProven=False, releaseAuthorized=False,
        scope='Complete bounded public-source Deux model passages, before unchanged production overlap/stem-cache replay. '
              'Plain runs still retain original service profiling. No timing ratio, quality tolerance or release decision.')
    write_json(args.output / 'receipt.json', receipt)
    def terminate(signum, _frame):
        # Raising through run_process executes its JVM-group cleanup. Leaving
        # SIGTERM at the Python default could orphan a long native inference.
        raise KeyboardInterrupt('Received signal ' + str(signum))
    previous_terminate = signal.signal(signal.SIGTERM, terminate)
    try:
        execute(args, receipt)
    except (Exception, KeyboardInterrupt) as error:
        receipt.update(status='OBSERVER_COMPARISON_INVALID' if isinstance(error, accel.InvalidObserver) else 'BLOCKED_OR_REJECTED',
                       failure=type(error).__name__ + ': ' + str(error))
        write_json(args.output / 'receipt.json', receipt)
        print(receipt['failure'], file=sys.stderr)
        return 130 if isinstance(error, KeyboardInterrupt) else 1
    finally:
        signal.signal(signal.SIGTERM, previous_terminate)
    write_json(args.output / 'receipt.json', receipt)
    print(json.dumps({key: receipt[key] for key in ('status', 'qualityApproved', 'benchmarkTimingAdmitted', 'target75Proven')}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
