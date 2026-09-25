#!/usr/bin/env python3
"""Locate Deux operator costs without changing production execution or claiming speedup.

Runs one unprofiled and one instrumented complete production passage in separate
fresh JVMs. The instrumented source is an isolated snapshot, not a production
edit. All 27 graphs and 335 calls, exact original model/runtime hashes, and
complete byte-identical float32 outputs are mandatory. Trace time includes
instrumentation overhead; this diagnostic is not a performance benchmark or a
release/quality-policy authorization. Use public or explicitly authorized audio.
"""
import argparse
import datetime
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'android/src/com/cyberbasslord/lightforge'
SPEC = importlib.util.spec_from_file_location('deux_execution_benchmark', ROOT / 'tools/benchmark_deux_execution.py')
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)
require, sha = benchmark.require, benchmark.sha
GRAPH_NAMES = benchmark.GRAPH_NAMES
PINNED_API_SOURCE = 'https://github.com/microsoft/onnxruntime/blob/v1.25.1/java/src/main/java/ai/onnxruntime/OrtSession.java'
MAX_TRACE_BYTES = 512 * 1024 * 1024


def strict_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON field.')
            result[key] = value
        return result

    def floating(value):
        result = float(value)
        require(math.isfinite(result), 'Nonfinite JSON number.')
        return result

    def constant(value):
        raise ValueError('Nonfinite JSON constant.')

    require(path.is_file() and 0 < path.stat().st_size <= MAX_TRACE_BYTES, 'Missing, empty or oversized JSON input.')
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs,
                      parse_float=floating, parse_constant=constant)


def duration(value):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            'Invalid trace duration or timestamp.')
    return value


def graph_calls(graph):
    return 1 if graph == 'front' else 15 if graph.endswith('-time') else 11


def aggregate(records):
    combined = {}
    for record in records:
        key = record['provider'], record['operator']
        item = combined.setdefault(key, dict(provider=key[0], operator=key[1], calls=0, durationUs=0))
        item['calls'] += record['calls']
        item['durationUs'] += record['durationUs']
        duration(item['durationUs'])
    return sorted(combined.values(), key=lambda item: (-item['durationUs'], item['provider'], item['operator']))


def summarize_trace(path, graph):
    require(graph in GRAPH_NAMES, 'Unknown graph.')
    events = strict_json(path)
    require(isinstance(events, list) and events, 'ORT trace must contain a nonempty event list.')
    kernels, model_runs = [], []
    for event in events:
        require(isinstance(event, dict), 'Invalid trace event.')
        if event.get('ph') != 'X':
            continue
        elapsed = duration(event.get('dur'))
        duration(event.get('ts'))
        if event.get('cat') == 'Session' and event.get('name') == 'model_run':
            model_runs.append(elapsed)
        if event.get('cat') != 'Node' or not str(event.get('name', '')).endswith('_kernel_time'):
            continue
        args = event.get('args')
        require(isinstance(args, dict), 'Kernel event lacks metadata.')
        provider, operator = args.get('provider'), args.get('op_name')
        require(isinstance(provider, str) and re.fullmatch(r'[A-Za-z0-9_]{1,100}ExecutionProvider', provider),
                'Kernel event lacks a valid execution provider.')
        require(isinstance(operator, str) and re.fullmatch(r'[A-Za-z0-9_.:]{1,128}', operator),
                'Kernel event lacks a valid operator.')
        kernels.append(dict(provider=provider, operator=operator, calls=1, durationUs=elapsed))
    require(len(model_runs) == graph_calls(graph), 'Trace model_run count differs from full production topology.')
    require(kernels and sum(item['durationUs'] for item in kernels) > 0, 'Trace contains no timed operator kernels.')
    return dict(graph=graph, traceFile=path.name, traceSha256=sha(path), traceBytes=path.stat().st_size,
                modelRuns=len(model_runs), modelRunDurationUs=sum(model_runs), kernelEvents=len(kernels),
                operators=aggregate(kernels))


def summarize_traces(directory):
    files = sorted(directory.iterdir())
    require(len(files) == len(GRAPH_NAMES) and all(path.is_file() and not path.is_symlink() for path in files),
            'Exactly 27 regular graph trace files are required.')
    graphs = {}
    for path in files:
        matches = [name for name in GRAPH_NAMES if path.name.startswith(name + '_') and path.suffix == '.json']
        require(len(matches) == 1, 'Unknown graph trace filename.')
        graph = matches[0]
        require(graph not in graphs, 'Duplicate graph trace.')
        graphs[graph] = path
    require(set(graphs) == GRAPH_NAMES, 'Missing graph traces.')
    ordered = [summarize_trace(graphs[name], name) for name in sorted(graphs)]
    operators = aggregate(item for graph in ordered for item in graph['operators'])
    providers = {}
    for item in operators:
        record = providers.setdefault(item['provider'], dict(provider=item['provider'], calls=0, durationUs=0))
        record['calls'] += item['calls']
        record['durationUs'] += item['durationUs']
    return dict(graphs=ordered, operators=operators, providers=list(providers.values()),
                graphCount=len(ordered), modelRuns=sum(g['modelRuns'] for g in ordered),
                kernelEvents=sum(g['kernelEvents'] for g in ordered),
                durationUnit='microseconds',
                durationMeaning='ORT host kernel-event durations, including dispatch/scheduling overhead; '
                                'not GPU device kernel time, critical-path wall time or measured speedup.')


def instrument_source(source, trace_directory):
    anchor = '            OrtSession session=environment.createSession(model.getAbsolutePath(),options);'
    require(source.count(anchor) == 1, 'Production session-construction anchor changed; review instrumentation.')
    require('enableProfiling(' not in source, 'Production source already contains profiling.')
    require(trace_directory.is_absolute(), 'Trace directory must be absolute.')
    literal = json.dumps(str(trace_directory), ensure_ascii=True)
    return source.replace(anchor, '            options.enableProfiling(new File(' + literal + ',name).getAbsolutePath());\n' + anchor)


def verify_java_api(java, runtime):
    result = subprocess.run([str(java / 'javap'), '-classpath', str(runtime),
                             'ai.onnxruntime.OrtSession$SessionOptions'], capture_output=True, text=True, timeout=30)
    require(result.returncode == 0 and 'public void enableProfiling(java.lang.String)' in result.stdout,
            'Pinned runtime does not expose the verified Java profiling API.')


def verify_models(directory):
    manifest_path = directory / 'manifest.json'
    manifest = strict_json(manifest_path)
    require(manifest.get('execution') == 'bounded-independent-batches-v1' and
            manifest.get('frames') == 1301 and manifest.get('samples') == 573300 and
            manifest.get('headFrames') == 128, 'Original full-context geometry is required.')
    inventory = manifest.get('files')
    require(isinstance(inventory, dict) and set(inventory) == {name + '.onnx' for name in GRAPH_NAMES},
            'Exact original graph inventory required.')
    for name, entry in inventory.items():
        require(isinstance(entry, dict) and type(entry.get('bytes')) is int and entry['bytes'] > 0 and
                isinstance(entry.get('sha256'), str) and re.fullmatch('[0-9a-f]{64}', entry['sha256']),
                'Invalid graph inventory entry.')
        graph = directory / name
        require(graph.is_file() and graph.stat().st_size == entry['bytes'] and sha(graph) == entry['sha256'],
                'Graph integrity failed: ' + name)
    # The model manifest is itself bound to the current checked-in source, not caller-defined.
    require(sha(manifest_path) == sha(ROOT / 'web/analysis/models/deux/manifest.json'),
            'Model manifest differs from the current production source.')
    return manifest


def profile_records(path):
    benchmark.profile_fields(path)
    return [dict(piece.split('=', 1) for piece in line.split()) for line in path.read_text().splitlines()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--models', type=Path, default=ROOT / 'web/analysis/models/deux')
    parser.add_argument('--start-sample', type=int, default=-66150)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output, args.models, args.audio = args.output.resolve(), args.models.resolve(), args.audio.resolve()
    require(not args.output.exists(), 'Use a new output directory; existing evidence cannot be replaced.')
    toolchain = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain'))
    java = Path(os.environ.get('LIGHTFORGE_JAVA_HOME', toolchain / 'jdk17')) / 'bin'
    runtime = strict_json(ROOT / 'android/native-runtime.json')
    host = toolchain / 'onnx' / runtime['host']['name']
    require(host.is_file() and host.stat().st_size == runtime['host']['bytes'] and sha(host) == runtime['host']['sha256'],
            'Host runtime does not match the checked-in binary pin.')
    dependencies = [toolchain / 'test-json.jar',
                    Path(os.environ.get('ANDROID_SDK_ROOT', toolchain / 'android-sdk')) / 'platforms/android-35/android.jar', host]
    for path in [*dependencies, args.audio]:
        require(path.is_file(), 'Required input is missing: ' + path.name)
    verify_java_api(java, host)
    manifest = verify_models(args.models)
    source = SOURCE / 'NativeDeux.java'
    bound_sources = [source, SOURCE / 'NativeDeuxTransform.java', SOURCE / 'NativeInferenceProfile.java',
                     ROOT / 'tests/NativeDeuxExecutionBenchmark.java', ROOT / 'tools/benchmark_deux_execution.py',
                     ROOT / 'android/native-runtime.json', ROOT / 'web/analysis/models/deux/manifest.json', Path(__file__)]
    sources = {str(path.relative_to(ROOT)): sha(path) for path in bound_sources}
    inputs = {path: sha(path) for path in [args.audio, *dependencies, args.models / 'manifest.json',
                                         *(args.models / name for name in manifest['files'])]}
    args.output.mkdir(parents=True)
    traces = args.output / 'traces'
    traces.mkdir()
    snapshot = args.output / 'NativeDeux.instrumented.java'
    snapshot.write_text(instrument_source(source.read_text(), traces), encoding='utf-8')
    receipt = dict(schema='lightforge.deux-operator-profile.v1',
                   createdUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   host=benchmark.host_metadata(), runtimeVersion=runtime['version'], runtimeSha256=sha(host),
                   apiSource=PINNED_API_SOURCE, audioSha256=sha(args.audio), startSample=args.start_sample,
                   samplesPerStem=573300, modelManifestSha256=sha(args.models / 'manifest.json'),
                   modelHashes={name: entry['sha256'] for name, entry in manifest['files'].items()},
                   sourceHashes=sources, dependencyHashes={path.name: sha(path) for path in dependencies},
                   variantSourceHashes={}, runs=[], releaseAuthorized=False, target75Proven=False,
                   benchmark=False, scope='One host passage; observational operator cost diagnostic only.')
    classes = {}
    for name, src in [('baseline', source), ('profiled', snapshot)]:
        classes[name], receipt['variantSourceHashes'][name] = benchmark.compile_variant(name, src, args.output, java, dependencies)
    for name in ('baseline', 'profiled'):
        run = benchmark.measure(name, 0, 'diagnostic', classes[name], args.output, java, dependencies,
                                args.models, args.audio, args.start_sample)
        run['graphAndStageTiming'] = profile_records(args.output / name / 'diagnostic-0.profile.txt')
        receipt['runs'].append(run)
    receipt['traceSummary'] = summarize_traces(traces)
    for path, expected in inputs.items():
        require(sha(path) == expected, 'A benchmark input changed during profiling.')
    for name, expected in sources.items():
        require(sha(ROOT / name) == expected, 'A source input changed during profiling: ' + name)
    require(sha(snapshot) == receipt['variantSourceHashes']['profiled'], 'Instrumented snapshot changed during profiling.')
    equivalent = receipt['runs'][0]['outputSha256'] == receipt['runs'][1]['outputSha256']
    receipt['outputByteIdentical'] = equivalent
    receipt['diagnosticValid'] = equivalent
    receipt['timingCaution'] = ('Profiled wall/operator durations include instrumentation overhead. The pair is not '
                                'a repeated speed experiment and does not establish Android, whole-song or 75% improvement.')
    with (args.output / 'receipt.json').open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(diagnosticValid=equivalent, outputByteIdentical=equivalent,
                          graphCount=receipt['traceSummary']['graphCount'], modelRuns=receipt['traceSummary']['modelRuns'],
                          operators=receipt['traceSummary']['operators'][:12], releaseAuthorized=False, target75Proven=False), indent=2))
    require(equivalent, 'Profiled output differs from unprofiled output; diagnostic equivalence failed.')


if __name__ == '__main__':
    main()
