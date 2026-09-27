#!/usr/bin/env python3
"""Qualify the exact production Deux passage on CUDA before timing it.

No model conversion, upload, job submission or production-source edit occurs.
Four fresh-process controls separate optimization, runtime packaging and CUDA:
production CPU/ALL, CPU/BASIC, GPU-package CPU/BASIC, GPU-package CUDA/BASIC.
CUDA uses use_tf32=0. All 27 original graphs and 335 calls are mandatory.
Complete Float32 output bytes must agree before any repeated timing runs.
Different outputs retain numerical diagnostics and are NOT quality-approved;
different bits alone do not prove audible degradation. Timing admission here
is conservative experiment policy, not an additional publication gate.

Examples (the GPU JAR must be obtained separately from GPU_RUNTIME['url']):
  python tools/benchmark_deux_accelerator.py --check-readiness --models MODELS \
    --audio PUBLIC.wav --output NEW_DIRECTORY
  python tools/benchmark_deux_accelerator.py --cpu-control-only --models MODELS \
    --audio PUBLIC.wav --output NEW_DIRECTORY
  python tools/benchmark_deux_accelerator.py --models MODELS --audio PUBLIC.wav \
    --output NEW_DIRECTORY

Timing excludes JVM startup, network, queueing and Android integration. This is
a host passage experiment, never PASS_TARGET or release authorization.
"""
import argparse
import array
import datetime
import importlib.util
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('deux_operator_profile', ROOT / 'tools/profile_deux_operators.py')
profiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profiler)
benchmark = profiler.benchmark
require, sha = benchmark.require, benchmark.sha
SOURCE = benchmark.SOURCE
GPU_RUNTIME = {
    'version': '1.25.1', 'name': 'onnxruntime_gpu-1.25.1.jar',
    'url': 'https://repo.maven.apache.org/maven2/com/microsoft/onnxruntime/onnxruntime_gpu/1.25.1/onnxruntime_gpu-1.25.1.jar',
    'bytes': 397558371,
    'sha256': '0a22d140ee2a064944b7ee45b7f7a8deb113f58e9be514da85c6dfbe85262649',
    'officialSha1': '91e39a9757d8141e000356f5eebbb1b0b17e5e8e',
    'pinProvenance': 'Downloaded from the official Maven Central URL on 2026-09-20; '
                     'size checked and published .sha1 verified; SHA256 computed over the complete JAR.',
}
VARIANTS = ('cpu_all', 'cpu_basic', 'gpu_package_cpu_basic', 'cuda_basic')
CUDA_OPTIONS = {'use_tf32': '0', 'do_copy_in_default_stream': '1',
                'enable_cuda_graph': '0', 'enable_skip_layer_norm_strict_mode': '1'}
HEAVY_OPERATORS = {'MatMul', 'Gemm', 'FusedMatMul', 'Conv', 'ConvTranspose', 'Attention', 'MultiHeadAttention'}
OPT_ANCHOR = '            options.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT);'
CREATE_ANCHOR = '            OrtSession session=environment.createSession(model.getAbsolutePath(),options);'


class NumericalEquivalenceUnproven(ValueError):
    """A diagnostic difference, not proof of perceptual regression."""


class InvalidObserver(ValueError):
    """The instrumentation changed output and cannot explain an unchanged run."""


def write_json(path, value):
    temporary = path.with_suffix('.partial')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def verify_runtime(path, pin):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size == pin['bytes']
            and sha(path) == pin['sha256'], 'Missing or incorrect pinned runtime: ' + pin['name'])


def validate_audio(path):
    # NativeDeuxTransform consumes PCM16 WAV; silently feeding a different format
    # would make both variants agree on the wrong input.
    with wave.open(str(path), 'rb') as audio:
        require(audio.getnchannels() == 2 and audio.getsampwidth() == 2 and
                audio.getframerate() == 44100 and audio.getcomptype() == 'NONE' and
                audio.getnframes() > 0, 'Expected nonempty 44.1 kHz stereo PCM16 WAV.')
        frames = audio.getnframes()
        require(len(audio.readframes(frames)) == frames * 4, 'Truncated PCM input.')
    return frames


def variant_source(source, variant):
    require(variant in VARIANTS, 'Unknown accelerator variant.')
    require(source.count(OPT_ANCHOR) == 1 and source.count(CREATE_ANCHOR) == 1,
            'Production session anchors changed; review the experiment.')
    require('addCUDA(' not in source and 'enableProfiling(' not in source,
            'Production source already selects CUDA or profiling.')
    if variant == 'cpu_all':
        return source  # Preserve the complete production CPU source byte-for-byte.
    changed = source.replace(OPT_ANCHOR, OPT_ANCHOR.replace('ALL_OPT', 'BASIC_OPT'))
    if variant == 'cuda_basic':
        options = ''.join('                cuda.add(' + json.dumps(key) + ',' + json.dumps(value) + ');\n'
                          for key, value in CUDA_OPTIONS.items())
        injected = ('            if(!OrtEnvironment.getAvailableProviders().contains(ai.onnxruntime.OrtProvider.CUDA))\n'
                    '                throw new IllegalStateException("CUDA provider unavailable; no CPU substitution");\n'
                    '            try(ai.onnxruntime.providers.OrtCUDAProviderOptions cuda=new ai.onnxruntime.providers.OrtCUDAProviderOptions(0)) {\n'
                    + options + '                options.addCUDA(cuda);\n            }\n')
        changed = changed.replace(CREATE_ANCHOR, injected + CREATE_ANCHOR)
    return changed


def compare_outputs(reference, candidate):
    reference_sha, candidate_sha = benchmark.read_output(reference), benchmark.read_output(candidate)
    left = array.array('f', reference.read_bytes())
    right = array.array('f', candidate.read_bytes())
    if sys.byteorder != 'little':
        left.byteswap(); right.byteswap()
    # read_output already checks exact sample count and finiteness. Hash equality
    # deliberately distinguishes +0 from -0 even when numerical error is zero.
    count = len(left)
    max_abs = sum_abs = sum_squared = 0.0
    unequal = 0
    for a, b in zip(left, right):
        delta = abs(float(a) - float(b))
        max_abs = max(max_abs, delta)
        sum_abs += delta
        sum_squared += delta * delta
        unequal += a != b
    return dict(referenceSha256=reference_sha, candidateSha256=candidate_sha,
                byteIdentical=reference_sha == candidate_sha, samples=count,
                numericallyUnequalSamples=unequal, maximumAbsoluteError=max_abs,
                meanAbsoluteError=sum_abs / count, rootMeanSquaredError=math.sqrt(sum_squared / count),
                tolerance=None, qualityApproved=False,
                interpretation='Raw Float32 differences only; no tolerance or musical-quality approval is inferred.')


def require_output_qualification(comparisons):
    if any(str(item.get('candidate', '')).endswith('_profiled') and item.get('byteIdentical') is not True
           for item in comparisons):
        raise InvalidObserver('Profiling changed output bytes; this observer comparison is invalid. '
                              'Raw results are retained, and repeated speed measurement is withheld.')
    if not comparisons or not all(item.get('byteIdentical') is True for item in comparisons):
        raise NumericalEquivalenceUnproven(
            'Numerical equivalence is unproven; repeated performance measurement is prohibited by this experiment. '
            'Inspect retained raw outputs. Different bits alone do not prove audible degradation. '
            'This research experiment does not decide publication readiness.')


def validate_placement(summary, variant):
    require(summary.get('graphCount') == 27 and summary.get('modelRuns') == 335,
            'Complete 27-graph/335-call provider traces are required.')
    providers = {row['provider'] for row in summary['providers']}
    expected = {'CPUExecutionProvider', 'CUDAExecutionProvider'} if variant == 'cuda_basic' else {'CPUExecutionProvider'}
    require(providers and providers <= expected, 'Unexpected execution provider in trace.')
    if variant == 'cuda_basic':
        require('CUDAExecutionProvider' in providers, 'CUDA candidate executed only CPU fallback.')
        # One copied tensor or trivial GPU operation must not certify a whole
        # CPU fallback run. Every original graph must execute substantive CUDA
        # arithmetic. Remaining CPU nodes are reported, never hidden.
        for graph in summary['graphs']:
            require(any(row['provider'] == 'CUDAExecutionProvider' and
                        row['operator'] in HEAVY_OPERATORS and row['calls'] > 0 and row['durationUs'] > 0
                        for row in graph['operators']),
                    'No substantive CUDA arithmetic observed for ' + graph['graph'])
    return dict(observedProviders=sorted(providers),
                cpuFallbackKernelEvents=sum(row['calls'] for row in summary['providers']
                                            if row['provider'] == 'CPUExecutionProvider') if variant == 'cuda_basic' else 0,
                allGraphsExecuteCudaArithmetic=variant == 'cuda_basic',
                timingMeaning=summary['durationMeaning'])


def verify_java_api(java, runtime):
    profiler.verify_java_api(java, runtime)
    for name, signatures in [
        ('ai.onnxruntime.OrtSession$SessionOptions',
         ['addCUDA(ai.onnxruntime.providers.OrtCUDAProviderOptions)']),
        ('ai.onnxruntime.providers.OrtCUDAProviderOptions', ['add(java.lang.String, java.lang.String)'])]:
        result = subprocess.run([str(java / 'javap'), '-classpath', str(runtime), name],
                                capture_output=True, text=True, timeout=30)
        require(result.returncode == 0 and all(value in result.stdout for value in signatures),
                'Pinned runtime lacks the explicit CUDA V2 provider-options API.')


def probe_runtime(java, dependencies, directory, expect_cuda):
    directory.mkdir()
    source = directory / 'RuntimeProbe.java'
    source.write_text('import ai.onnxruntime.*; public final class RuntimeProbe {\n'
                      'public static void main(String[] args) throws Exception {\n'
                      'OrtEnvironment env=OrtEnvironment.getEnvironment();\n'
                      'if(!"1.25.1".equals(env.getVersion())) throw new IllegalStateException("Unexpected loaded ORT version");\n'
                      'if(Boolean.parseBoolean(args[0])&&!OrtEnvironment.getAvailableProviders().contains(OrtProvider.CUDA))\n'
                      'throw new IllegalStateException("CUDA unavailable");\n'
                      'System.out.println(env.getVersion()); System.out.println(OrtEnvironment.getAvailableProviders());}}\n')
    classpath = os.pathsep.join(map(str, dependencies))
    compile_result = subprocess.run([str(java / 'javac'), '--release', '8', '-cp', classpath,
                                     str(source)], capture_output=True, text=True, timeout=30)
    (directory / 'compile.log').write_text(compile_result.stdout + compile_result.stderr)
    require(compile_result.returncode == 0, 'Runtime probe compilation failed.')
    result = subprocess.run([str(java / 'java'), '-cp', os.pathsep.join([str(directory), classpath]),
                             'RuntimeProbe', str(expect_cuda).lower()], capture_output=True, text=True, timeout=60)
    (directory / 'probe.log').write_text(result.stdout + result.stderr)
    require(result.returncode == 0, 'Pinned runtime/provider probe failed; see ' + str(directory / 'probe.log'))
    return dict(runtimeVersion='1.25.1', output=result.stdout.strip(),
                cudaRequested=expect_cuda, cudaKernelExecutionProven=False)


def gpu_inventory():
    try:
        result = subprocess.run(['nvidia-smi', '--query-gpu=name,uuid,pci.bus_id,driver_version,memory.total',
                                 '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise ValueError('An accessible NVIDIA GPU and nvidia-smi are required; no accelerator timing was run.') from error
    require(result.returncode == 0 and result.stdout.strip(), 'No accessible NVIDIA GPU reported by nvidia-smi.')
    capability = subprocess.run(['nvidia-smi', '--query-gpu=compute_cap', '--format=csv,noheader'],
                                capture_output=True, text=True, timeout=30)
    return dict(nameUuidPciDriverMemoryRows=result.stdout.strip().splitlines(),
                computeCapabilityRows=capability.stdout.strip().splitlines() if capability.returncode == 0 else None,
                computeCapabilityAvailable=capability.returncode == 0,
                driverIsNotCudaRuntimeVersion=True)


def capture_library_maps(source, path):
    """The diagnostic twin appends mapped libraries after EVERY completed run.

    Lazy libraries used by later graphs or changing batch sizes are therefore
    included. Capturing only session construction could silently miss them.
    """
    anchor = '                if(first){firstGraphRun=false;phase("session-run-complete; graph="+activeGraph);}'
    require(source.count(anchor) == 1 and path.is_absolute(), 'Invalid library-map capture anchor.')
    injected = ('                StringBuilder gpuMaps=new StringBuilder();\n'
                '                for(String mapping:java.nio.file.Files.readAllLines(java.nio.file.Paths.get("/proc/self/maps")))\n'
                '                    if(mapping.contains("/libcuda")||mapping.contains("/libcudnn")||mapping.contains("/libcublas")||mapping.contains("/libnvrtc")||mapping.contains("/libnvJitLink"))\n'
                '                        gpuMaps.append(mapping).append("\\n");\n'
                '                java.nio.file.Files.write(java.nio.file.Paths.get(' + json.dumps(str(path)) + '),\n'
                '                    gpuMaps.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8),\n'
                '                    java.nio.file.StandardOpenOption.CREATE,java.nio.file.StandardOpenOption.APPEND);\n')
    return source.replace(anchor, anchor + '\n' + injected)


def native_library_paths(path):
    require(path.is_file() and 0 < path.stat().st_size < 64 * 1024 * 1024, 'CUDA JVM library map is missing or invalid.')
    names = set()
    for line in path.read_text().splitlines():
        pieces = line.split(None, 5)
        if len(pieces) == 6 and pieces[5].startswith('/'):
            candidate = Path(pieces[5])
            if candidate.name.startswith(('libcuda', 'libcudnn', 'libcublas', 'libnvrtc', 'libnvJitLink')):
                require(candidate.is_file(), 'A mapped GPU library is no longer available: ' + candidate.name)
                names.add(candidate.resolve())
    for prefix in ('libcudart.so', 'libcudnn.so', 'libcublas.so'):
        require(sum(name.name.startswith(prefix) for name in names) == 1,
                'Exactly one actually mapped ' + prefix + ' library is required.')
    return sorted(names)


def native_library_versions(paths):
    """Query the files observed in the actual CUDA JVM, never guess from its driver."""
    selected = [next(str(path) for path in paths if path.name.startswith(prefix))
                for prefix in ('libcudart.so', 'libcudnn.so', 'libcublas.so')]
    script = '''import ctypes,json,sys
cuda=ctypes.CDLL(sys.argv[1]); cudnn=ctypes.CDLL(sys.argv[2]); cublas=ctypes.CDLL(sys.argv[3])
version=ctypes.c_int(); cuda.cudaRuntimeGetVersion.argtypes=[ctypes.POINTER(ctypes.c_int)]
assert cuda.cudaRuntimeGetVersion(ctypes.byref(version))==0
cudnn.cudnnGetVersion.restype=ctypes.c_size_t
parts=[]
cublas.cublasGetProperty.argtypes=[ctypes.c_int,ctypes.POINTER(ctypes.c_int)]
for prop in (0,1,2):
 value=ctypes.c_int(); assert cublas.cublasGetProperty(prop,ctypes.byref(value))==0; parts.append(value.value)
print(json.dumps(dict(cudaRuntimeVersion=version.value,cudnnVersion=cudnn.cudnnGetVersion(),cublasVersion=parts)))
'''
    result = subprocess.run([sys.executable, '-c', script, *selected], capture_output=True, text=True, timeout=60)
    require(result.returncode == 0, 'Cannot observe actual mapped CUDA/cuDNN/cuBLAS versions; qualification withheld.')
    versions = json.loads(result.stdout)
    require(type(versions.get('cudaRuntimeVersion')) is int and 12000 <= versions['cudaRuntimeVersion'] < 13000,
            'Pinned ORT GPU 1.25.1 requires the recorded CUDA 12.x runtime family.')
    require(type(versions.get('cudnnVersion')) is int and 90000 <= versions['cudnnVersion'] < 100000,
            'Pinned ORT GPU 1.25.1 requires the recorded cuDNN 9.x runtime family.')
    require(isinstance(versions.get('cublasVersion'), list) and len(versions['cublasVersion']) == 3 and
            all(type(value) is int and value >= 0 for value in versions['cublasVersion']), 'Invalid cuBLAS version.')
    return versions


def run_once(variant, phase, round_number, classes, output, java, dependencies, models, audio, start):
    process_started = time.perf_counter_ns()
    result = benchmark.measure(variant, round_number, phase, classes, output, java, dependencies, models, audio, start)
    result['processWallIncludingStartupAndInspectionNanos'] = time.perf_counter_ns() - process_started
    result['timingEligible'] = phase in ('warmup', 'measurement')
    return result


def performance_summary(runs, variants):
    result = {}
    for variant in variants:
        selected = [row for row in runs if row['variant'] == variant and row['phase'] == 'measurement']
        require(len(selected) >= 3, 'Three complete measurements per variant are required.')
        result[variant] = {key: statistics.median(row[key] for row in selected)
                           for key in ('wallNanos', 'inferenceMillis', 'modelInitMillis',
                                       'processWallIncludingStartupAndInspectionNanos')}
    baseline = result['cpu_all']['wallNanos']
    return dict(medians=result,
                hostPassageWallReductionPercent={name: 100 * (1 - row['wallNanos'] / baseline)
                                                for name, row in result.items()},
                target75Proven=False, wholeSongSpeedupProven=False, androidSpeedupProven=False,
                scope='Full 13-second model passage on one host; excludes network/queue/Android; '
                      'profiled diagnostic runs excluded from speed ratios.')


def execute(args, receipt):
    # Do not allow a hidden java property to substitute native libraries for the
    # pinned JAR while retaining apparently valid evidence.
    require(not any(os.environ.get(key) for key in ('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS')),
            'Unset Java option injection variables before qualification.')
    require(os.environ.get('CUBLAS_WORKSPACE_CONFIG', ':4096:8') == ':4096:8',
            'Use CUBLAS_WORKSPACE_CONFIG=:4096:8 for the recorded reproducibility configuration.')
    os.environ['CUBLAS_WORKSPACE_CONFIG'] = ':4096:8'
    require(os.environ.get('NVIDIA_TF32_OVERRIDE', '0') == '0', 'Unset NVIDIA_TF32_OVERRIDE or set it to 0.')
    os.environ['NVIDIA_TF32_OVERRIDE'] = '0'
    toolchain = args.toolchain.resolve()
    java = toolchain / 'jdk17/bin'
    runtime = profiler.strict_json(ROOT / 'android/native-runtime.json')
    require(runtime['version'] == GPU_RUNTIME['version'], 'Production runtime version changed; requalify the GPU binary pin.')
    host = toolchain / 'onnx' / runtime['host']['name']
    gpu = args.gpu_runtime.resolve() if args.gpu_runtime else toolchain / 'onnx' / GPU_RUNTIME['name']
    verify_runtime(host, runtime['host'])
    shared = [toolchain / 'test-json.jar', toolchain / 'android-sdk/platforms/android-35/android.jar']
    require(all(path.is_file() for path in shared), 'Missing benchmark compilation dependencies.')
    variants = VARIANTS[:2] if args.cpu_control_only else VARIANTS
    if not args.cpu_control_only:
        require(sys.platform.startswith('linux'), 'CUDA qualification currently requires Linux /proc library evidence.')
        verify_runtime(gpu, GPU_RUNTIME)
    frame_count = validate_audio(args.audio)
    require(-573300 < args.start_sample < frame_count, 'Passage must overlap actual input audio.')
    manifest = profiler.verify_models(args.models)
    dependencies = {variant: [*shared, gpu if variant in VARIANTS[2:] else host] for variant in variants}
    source = SOURCE / 'NativeDeux.java'
    source_text = source.read_text(encoding='utf-8')
    bound = [source, SOURCE / 'NativeDeuxTransform.java', SOURCE / 'NativeInferenceProfile.java',
             ROOT / 'tests/NativeDeuxExecutionBenchmark.java', ROOT / 'tools/benchmark_deux_execution.py',
             ROOT / 'tools/profile_deux_operators.py', ROOT / 'android/native-runtime.json',
             ROOT / 'web/analysis/models/deux/manifest.json', Path(__file__)]
    hashes = {path: sha(path) for path in {*bound, args.audio, *shared, host,
              *([gpu] if not args.cpu_control_only else []), args.models / 'manifest.json',
              *(args.models / name for name in manifest['files'])}}
    receipt.update(host=benchmark.host_metadata(), audioSha256=hashes[args.audio],
                   audioFrames=frame_count, startSample=args.start_sample, samplesPerStem=573300,
                   runtimeVersion=runtime['version'], cpuRuntime=runtime['host'], gpuRuntime=GPU_RUNTIME,
                   sourceHashes={str(path.relative_to(ROOT)): hashes[path] for path in bound},
                   dependencyHashes={path.name: hashes[path] for path in {*shared, host, *([gpu] if not args.cpu_control_only else [])}},
                   modelManifestSha256=hashes[args.models / 'manifest.json'],
                   modelHashes={name: entry['sha256'] for name, entry in manifest['files'].items()},
                   cudaOptions=CUDA_OPTIONS, cublasWorkspaceConfig=':4096:8', nvidiaTf32Override='0',
                   requestedCudaLogicalDevice=0,
                   cudaVisibility={key: os.environ.get(key) for key in ('CUDA_VISIBLE_DEVICES', 'CUDA_DEVICE_ORDER')},
                   gpuMappingNote='Inventory rows describe physical GPUs. Logical device 0 mapping is not independently proven.',
                   deterministicCompute={variant: dict(explicitlyRequested=None,
                       note='No setDeterministicCompute override; retains runtime default. '
                            'CUBLAS workspace configuration does not guarantee all CUDA kernels are deterministic.')
                       for variant in variants},
                   variants=list(variants), variantSourceHashes={}, providerTraces={}, placement={},
                   runtimeProbes=[], comparisons=[], runs=[])
    write_json(args.output / 'receipt.json', receipt)
    verify_java_api(java, host)
    receipt['runtimeProbes'].append(probe_runtime(java, dependencies['cpu_all'], args.output / 'cpu-runtime-probe', False))
    if not args.cpu_control_only:
        verify_java_api(java, gpu)
        receipt['gpuInventory'] = gpu_inventory()
        receipt['runtimeProbes'].append(probe_runtime(java, dependencies['cuda_basic'], args.output / 'gpu-runtime-probe', True))
    if args.check_readiness:
        receipt.update(status='PREFLIGHT_READY', measured=False,
                       note='Inputs and runtime discovery verified; graph execution and output qualification are still untested.')
        return
    classes = {}
    for variant in variants:
        snapshot = args.output / (variant + '.java')
        snapshot.write_text(variant_source(source_text, variant), encoding='utf-8')
        classes[variant], receipt['variantSourceHashes'][variant] = benchmark.compile_variant(
            variant, snapshot, args.output, java, dependencies[variant])
        for path in [snapshot, args.output / variant / 'NativeDeux.java', *classes[variant].rglob('*.class')]:
            hashes[path] = sha(path)
    outputs = {}
    for variant in variants:
        row = run_once(variant, 'qualification', 0, classes[variant], args.output, java,
                       dependencies[variant], args.models, args.audio, args.start_sample)
        receipt['runs'].append(row)
        outputs[variant] = args.output / variant / 'qualification-0.f32'
        # Profile separately so instrumentation overhead never enters a speed ratio.
        traced = variant + '_profiled'
        traces = args.output / (traced + '_traces')
        traces.mkdir()
        snapshot = args.output / (traced + '.java')
        traced_source = profiler.instrument_source(variant_source(source_text, variant), traces)
        maps = args.output / 'cuda-jvm-loaded-library-maps.txt'
        if variant == 'cuda_basic':
            traced_source = capture_library_maps(traced_source, maps)
        snapshot.write_text(traced_source, encoding='utf-8')
        traced_classes, receipt['variantSourceHashes'][traced] = benchmark.compile_variant(
            traced, snapshot, args.output, java, dependencies[variant])
        for path in [snapshot, args.output / traced / 'NativeDeux.java', *traced_classes.rglob('*.class')]:
            hashes[path] = sha(path)
        receipt['runs'].append(run_once(traced, 'diagnostic', 0, traced_classes, args.output, java,
                                       dependencies[variant], args.models, args.audio, args.start_sample))
        comparison = compare_outputs(outputs[variant], args.output / traced / 'diagnostic-0.f32')
        comparison.update(reference=variant, candidate=traced)
        receipt['comparisons'].append(comparison)
        summary = profiler.summarize_traces(traces)
        receipt['providerTraces'][variant] = summary
        receipt['placement'][variant] = validate_placement(summary, variant)
        if variant == 'cuda_basic':
            paths = native_library_paths(maps)
            receipt['gpuNativeLibraries'] = {
                str(path): dict(bytes=path.stat().st_size, sha256=sha(path)) for path in paths}
            receipt['gpuNativeLibraryVersions'] = native_library_versions(paths)
            for path in [maps, *paths]:
                hashes[path] = sha(path)
        write_json(args.output / 'receipt.json', receipt)
    # Include the packaging/optimization pairwise controls, not only CPU vs GPU.
    for left, right in zip(variants, variants[1:]):
        comparison = compare_outputs(outputs[left], outputs[right])
        comparison.update(reference=left, candidate=right)
        receipt['comparisons'].append(comparison)
    write_json(args.output / 'receipt.json', receipt)
    # Retain source and binary integrity evidence even when output differences
    # reject timing admission; changes cannot masquerade as numerical variance.
    for path, expected in hashes.items():
        require(path.is_file() and sha(path) == expected, 'Bound source, runtime, model or audio changed: ' + path.name)
    receipt['compiledSnapshotHashes'] = {str(path.relative_to(args.output)): expected
                                        for path, expected in hashes.items() if path.is_relative_to(args.output)}
    receipt['inputsRecheckedAfterQualification'] = True
    require_output_qualification(receipt['comparisons'])
    receipt['outputBytesQualifiedForTiming'] = True
    if args.cpu_control_only:
        receipt.update(status='CPU_CONTROL_ONLY', measured=False,
                       note='CPU optimization controls completed; CUDA remains untested.')
    else:
        for phase, count in [('warmup', args.warmups), ('measurement', args.repeats)]:
            for number in range(count):
                order = variants if number % 2 == 0 else tuple(reversed(variants))
                for variant in order:
                    row = run_once(variant, phase, number, classes[variant], args.output, java,
                                   dependencies[variant], args.models, args.audio, args.start_sample)
                    receipt['runs'].append(row)
                    write_json(args.output / 'receipt.json', receipt)
                    require_output_qualification([dict(byteIdentical=row['outputSha256'] == receipt['runs'][0]['outputSha256'])])
        receipt['performance'] = performance_summary(receipt['runs'], variants)
        receipt.update(status='HOST_PASSAGE_EXPERIMENT_COMPLETE', measured=True)
    for path, expected in hashes.items():
        require(path.is_file() and sha(path) == expected, 'Bound source, runtime, model or audio changed: ' + path.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--models', type=Path, default=ROOT / 'web/analysis/models/deux')
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--toolchain', type=Path, default=Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain')))
    parser.add_argument('--gpu-runtime', type=Path)
    parser.add_argument('--start-sample', type=int, default=-66150)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--warmups', type=int, default=1)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check-readiness', action='store_true')
    mode.add_argument('--cpu-control-only', action='store_true')
    args = parser.parse_args()
    require(3 <= args.repeats <= 10 and 1 <= args.warmups <= 3, 'Use 3-10 repetitions and 1-3 warmups.')
    args.models, args.audio, args.output = (path.resolve() for path in (args.models, args.audio, args.output))
    require(not args.output.exists(), 'Use a new output directory; existing evidence cannot be replaced.')
    args.output.mkdir(parents=True)
    receipt = dict(schema='lightforge.deux-accelerator-experiment.v1',
                   createdUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   status='INCOMPLETE', measured=False, outputBytesQualifiedForTiming=False,
                   qualityApproved=False, releaseAuthorized=False, target75Proven=False,
                   wholeSongSpeedupProven=False, androidSpeedupProven=False)
    try:
        execute(args, receipt)
    except Exception as error:
        status = ('OBSERVER_COMPARISON_INVALID' if isinstance(error, InvalidObserver) else
                  'NUMERICAL_EQUIVALENCE_UNPROVEN' if isinstance(error, NumericalEquivalenceUnproven)
                  else 'BLOCKED_OR_REJECTED')
        receipt.update(status=status, failure=str(error), measured=False, outputBytesQualifiedForTiming=False)
        receipt.pop('performance', None)
        write_json(args.output / 'receipt.json', receipt)
        print(str(error), file=sys.stderr)
        return 1
    write_json(args.output / 'receipt.json', receipt)
    print(json.dumps({key: receipt[key] for key in ('status', 'measured', 'outputBytesQualifiedForTiming',
                                                    'qualityApproved', 'target75Proven', 'releaseAuthorized')}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
