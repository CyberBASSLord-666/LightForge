#!/usr/bin/env python3
"""Bounded host-only full-source GAME session reuse diagnostics, never timing approval.

Run default/reuse within each explicitly selected provider in fresh plain,
captured and profiled JVMs. The persistent-session observer binds serial ORT
model_run ordinals to original-call and source-passage markers. No app edit,
numerical tolerance, speed ratio, release or Android lifecycle approval occurs.
"""
import argparse
import datetime
import difflib
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

ROOT = Path(__file__).resolve().parents[1]

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

baseline = module('game_reuse_baseline', ROOT / 'tools/benchmark_game_source_cuda.py')
candidate = module('game_reuse_generator', ROOT / 'tools/game_benchmark/session_reuse_candidate.py')
game, accel, profiler, comparator = baseline.game, baseline.accel, baseline.profiler, baseline.comparator
require, sha, write_json = baseline.require, baseline.sha, baseline.write_json
VARIANTS, MODES, ARMS = baseline.VARIANTS, baseline.MODES, ('default', 'reuse')
HELPERS = tuple(ROOT / 'tools/game_benchmark' / name for name in
    ('GameSessionReuseRunner.java', 'GameSessionReuseTrace.java', 'GameAcceleratorCapture.java'))
SOURCE_BINDINGS = tuple(dict.fromkeys((*baseline.SOURCE_BINDINGS, 'tools/benchmark_game_session_reuse.py',
    'tools/game_benchmark/session_reuse_candidate.py', *(str(p.relative_to(ROOT)) for p in HELPERS))))
CREATE_END = '                            new File(modelDirectory,GRAPHS[i]+".onnx").getAbsolutePath(),options));'
ORDER = ['encoder', 'dur2bd', *(['segmenter'] * 8), 'bd2dur', 'estimator']


def source_snapshot(original, variant, arm, mode, samples, language=0, traces=None):
    require(variant in VARIANTS and arm in ARMS and mode in MODES, 'Unknown session-reuse arm/mode.')
    require((traces is not None) == (mode == 'profiled'), 'Trace directory must match profiled mode.')
    require(hashlib.sha256(original.encode()).hexdigest() == candidate.ORIGINAL_SHA256,
            'Original source changed; isolated candidate review required.')
    source = candidate.generate(original, variant, source_samples=samples, language=language) if arm == 'reuse' else \
        game.variant_source(original, variant, True, True)
    if mode == 'plain':
        return source
    source = game.observed_source(source)
    if traces is not None:
        require(traces.is_absolute(), 'Absolute trace directory required.')
        require(source.count(game.CREATE_ANCHOR) == 1 and source.count(CREATE_END) == 1 and
                source.count(game.RUN_ANCHOR) == 1, 'Trace session/call anchors changed.')
        source = source.replace(game.CREATE_ANCHOR,
            '                    options.enableProfiling(GameSessionReuseTrace.nextPrefix(GRAPHS[i]));\n' + game.CREATE_ANCHOR)
        source = source.replace(CREATE_END, CREATE_END + '\n                    GameSessionReuseTrace.sessionCreated(GRAPHS[i],sessions.get(GRAPHS[i]));')
        source = source.replace(game.RUN_ANCHOR,
            '        int researchTicket=GameSessionReuseTrace.before(graph,sessions.get(graph));\n' + game.RUN_ANCHOR)
        # Marker completion and capture both remain inside the original result
        # ownership guard: either observer failure retires the returned result.
        source = source.replace('try{GameAcceleratorCapture.record(',
                                'try{GameSessionReuseTrace.after(researchTicket);GameAcceleratorCapture.record(')
    return source


def compile_snapshot(directory, source, java, dependencies):
    directory.mkdir()
    path = directory / 'NativeGame.java'
    path.write_text(source, encoding='utf-8')
    sources = [path]
    for helper in HELPERS:
        target = directory / helper.name
        shutil.copyfile(helper, target)
        require(sha(helper) == sha(target), 'Research helper changed while copied.')
        sources.append(target)
    classes = directory / 'classes'
    classes.mkdir()
    result = subprocess.run([str(java / 'javac'), '--release', '8', '-encoding', 'UTF-8', '-cp',
        os.pathsep.join(map(str, dependencies)), '-d', str(classes), *map(str, sources)],
        capture_output=True, text=True, timeout=90)
    (directory / 'compile.log').write_text(result.stdout + result.stderr)
    require(result.returncode == 0, 'Session-reuse snapshot compilation failed: ' + str(directory / 'compile.log'))
    return classes, sources + [directory / 'compile.log'] + list(classes.rglob('*.class'))


def validate_run(directory, mode, arm, provenance, plan, manifest):
    receipt = profiler.strict_json(directory / 'receipt.json')
    require(receipt.get('schema') == 'lightforge-game-session-reuse-run-1' and receipt.get('lifecycleArm') == arm and
            receipt.get('hostOnly') is True and receipt.get('appLifecycleEquivalent') is False and
            receipt.get('runtime') == 'onnxruntime-java-1.25.1' and receipt.get('samples') == provenance['sourceSamples'] and
            receipt.get('pcmSHA256') == provenance['pcmSHA256'] and receipt.get('sampleRate') == baseline.RATE and
            receipt.get('steps') == 8 and receipt.get('language') == provenance['language'] and
            receipt.get('modelFiles') == manifest['files'] and receipt.get('engineObjects') == 1 and
            receipt.get('capture') is (mode != 'plain') and receipt.get('profiled') is (mode == 'profiled') and
            receipt.get('retirementConfirmed') is True and receipt.get('passageCount') == len(plan) and
            type(receipt.get('wallNanos')) is int and receipt['wallNanos'] > 0,
            'Invalid session-reuse full-source receipt.')
    require(all(receipt.get(k) is False for k in ('benchmarkTimingAdmitted', 'qualityApproved', 'target75Proven', 'releaseAuthorized')),
            'Diagnostic receipt may not grant approval.')
    require(isinstance(receipt.get('passages'), list) and len(receipt['passages']) == len(plan), 'Incomplete passage receipts.')
    for row, nested in zip(plan, receipt['passages']):
        path = directory / f"passage-{row['index']:03d}"
        item = profiler.strict_json(path / 'receipt.json')
        require(item == nested, 'Nested passage receipt mismatch.')
        expected = dict(schema='lightforge-game-benchmark-1', runtime='onnxruntime-java-1.25.1', sampleRate=baseline.RATE,
            samples=row['last'] - row['first'], pcmSHA256=row['pcmSha256'], sourcePcmSHA256=provenance['pcmSHA256'],
            sourceSamples=provenance['sourceSamples'], passageIndex=row['index'], firstSample=row['first'],
            lastSample=row['last'], modelFiles=manifest['files'], seed=row['seed'], language=provenance['language'], steps=8)
        require(all(item.get(k) == v for k, v in expected.items()) and item.get('capture') is (mode != 'plain') and
                item.get('retirementConfirmed') is True and type(item.get('wallNanos')) is int and item['wallNanos'] > 0,
                'Invalid source-bound reuse passage receipt.')
        # The unchanged comparator checks tensor inventory, finite unrounded
        # notes, dimensions and exact byte digests for captured evidence.
        if mode != 'plain':
            _, tensors = comparator.load(path)
            require(len(tensors) == 16 and len(item['stages']) == 12, 'All 16 tensors and 12 calls required per passage.')
            require([s['graph'] for s in item['stages']] == ORDER, 'Original graph-call order changed.')
            for stage in item['stages']:
                label = stage['label']
                original_label = 'segmenter-' + str(row['index'] * 8 + int(label.split('-')[1])) if label.startswith('segmenter-') else label
                require(stage.get('captureOriginalLabel') == original_label, 'Original global capture identity changed.')
        else:
            require(item.get('stages') == [] and item.get('inferenceSeconds') is None, 'Plain run contains observer output.')
            require(isinstance(item.get('notes'), list) and all(isinstance(n, dict) and set(n) == {'start', 'end', 'midi'} and
                all(type(n[k]) in (int, float) and baseline.math.isfinite(n[k]) for k in n) for n in item['notes']), 'Invalid plain notes.')
    return receipt


def summarize_session_traces(directory, marker_path, arm, variant, provenance, plan):
    """Partition serial ORT calls by explicit original-call markers, fail closed.

    Marker nanoseconds establish serial call ownership, not an ORT clock offset.
    Within one session the synchronous original calls have exactly one model_run
    each. Ordered non-overlapping trace intervals bind those graphRunOrdinals;
    every kernel event must be wholly inside exactly one such interval.
    """
    markers = profiler.strict_json(marker_path)
    require(markers.get('schema') == 'lightforge.game-session-reuse-trace-markers.v1' and
            markers.get('sourcePcmSha256') == provenance['pcmSHA256'] and
            markers.get('sourceSamples') == provenance['sourceSamples'] and
            markers.get('language') == provenance['language'] and markers.get('singleThreadOwner') is True,
            'Invalid full-source trace-marker identity.')
    sessions, passages = markers.get('sessions'), markers.get('passages')
    expected_sessions = 5 if arm == 'reuse' else 5 * len(plan)
    require(isinstance(sessions, list) and len(sessions) == expected_sessions and
            isinstance(passages, list) and len(passages) == len(plan), 'Incomplete trace sessions/passages.')
    calls_by_session = {i: [] for i in range(expected_sessions)}
    prior_end = 0
    for row, passage in zip(plan, passages):
        require(all(passage.get(k) == row[k] for k in ('index', 'first', 'last', 'seed', 'pcmSha256')),
                'Trace marker passage clock or PCM changed.')
        begin, end = passage.get('beginNanos'), passage.get('endNanos')
        require(type(begin) is int and type(end) is int and prior_end <= begin <= end, 'Overlapping/incomplete passage marker.')
        calls = passage.get('calls')
        require(isinstance(calls, list) and len(calls) == 12 and [c.get('graph') for c in calls] == ORDER,
                'Original 12-call passage schedule changed.')
        last = begin
        for index, call in enumerate(calls):
            sid, ordinal = call.get('sessionIndex'), call.get('graphRunOrdinal')
            require(type(sid) is int and sid in calls_by_session and type(ordinal) is int and
                    ordinal == len(calls_by_session[sid]) and call.get('callIndex') == index,
                    'Unbound/duplicate/nonserial graph-call marker.')
            start, stop = call.get('beginNanos'), call.get('endNanos')
            require(type(start) is int and type(stop) is int and last <= start <= stop <= end,
                    'Incomplete/overlapping original-call marker.')
            require(sessions[sid].get('graph') == call['graph'], 'Session graph identity mismatch.')
            calls_by_session[sid].append(dict(passageIndex=row['index'], **call))
            last = stop
        prior_end = end
    paths = list(directory.iterdir())
    require(len(paths) == expected_sessions and all(p.is_file() and not p.is_symlink() for p in paths),
            'Unexpected or missing lifetime trace files.')
    grouped = {row['index']: [] for row in plan}
    inventory, used, graph_ordinals = [], set(), {g: 0 for g in game.GRAPHS}
    process_ids, run_threads = set(), set()
    for sid, session in enumerate(sessions):
        graph = session.get('graph')
        require(graph == game.GRAPHS[sid % 5] and session.get('sessionIndex') == sid and
                session.get('sessionOrdinal') == graph_ordinals[graph], 'Invalid session construction order/identity.')
        ordinal = graph_ordinals[graph]; graph_ordinals[graph] += 1
        prefix = f'{graph}_s{ordinal:03d}'
        require(session.get('prefix') == prefix and session.get('createdPassage') == (0 if arm == 'reuse' else ordinal),
                'Session prefix or lifetime changed.')
        bound = calls_by_session[sid]
        require(session.get('calls') == len(bound) == game.CALLS[graph] * (len(plan) if arm == 'reuse' else 1),
                'Wrong graph lifetime call count.')
        require({c['passageIndex'] for c in bound} == ({r['index'] for r in plan} if arm == 'reuse' else {ordinal}),
                'Graph reused across an undeclared passage.')
        matches = [p for p in paths if p.name.startswith(prefix + '_') and p.suffix == '.json']
        require(len(matches) == 1 and matches[0] not in used, 'Missing/duplicate bound graph lifetime trace.')
        path = matches[0]; used.add(path)
        events = profiler.strict_json(path)
        require(isinstance(events, list) and events, 'Empty lifetime trace.')
        runs, kernels = [], []
        for event in events:
            require(isinstance(event, dict), 'Invalid trace event.')
            if event.get('ph') != 'X':
                continue
            elapsed, timestamp = profiler.duration(event.get('dur')), profiler.duration(event.get('ts'))
            require(baseline.math.isfinite(timestamp + elapsed), 'Nonfinite trace interval endpoint.')
            require(type(event.get('pid')) is int and event['pid'] > 0 and type(event.get('tid')) is int and event['tid'] > 0,
                    'Missing trace process/thread identity.')
            process_ids.add(event['pid'])
            if event.get('cat') == 'Session' and event.get('name') == 'model_run':
                run_threads.add(event['tid'])
                runs.append(dict(start=timestamp, stop=timestamp + elapsed, durationUs=elapsed))
            if event.get('cat') == 'Node' and str(event.get('name', '')).endswith('_kernel_time'):
                args = event.get('args')
                require(isinstance(args, dict), 'Missing kernel metadata.')
                provider, operator = args.get('provider'), args.get('op_name')
                require(isinstance(provider, str) and re.fullmatch('[A-Za-z0-9_]{1,100}ExecutionProvider', provider) and
                        isinstance(operator, str) and re.fullmatch('[A-Za-z0-9_.:]{1,128}', operator), 'Invalid kernel provider/operator.')
                kernels.append(dict(start=timestamp, stop=timestamp + elapsed, provider=provider, operator=operator,
                                    calls=1, durationUs=elapsed))
        runs.sort(key=lambda r: r['start'])
        require(len(runs) == len(bound) and all(r['durationUs'] > 0 for r in runs) and
                all(a['stop'] <= b['start'] for a, b in zip(runs, runs[1:])), 'Incomplete/overlapping serial ORT calls.')
        buckets = [[] for _ in runs]
        for kernel in kernels:
            owners = [i for i, run in enumerate(runs) if run['start'] <= kernel['start'] and kernel['stop'] <= run['stop']]
            require(len(owners) == 1, 'Kernel is outside/ambiguous between bound model_run intervals.')
            buckets[owners[0]].append({k: kernel[k] for k in ('provider', 'operator', 'calls', 'durationUs')})
        for run, call, bucket in zip(runs, bound, buckets):
            require(bucket and sum(k['durationUs'] for k in bucket) > 0, 'Bound call lacks substantive kernel trace.')
            grouped[call['passageIndex']].append(dict(graph=graph, sessionIndex=sid,
                graphRunOrdinal=call['graphRunOrdinal'], modelRunDurationUs=run['durationUs'], operators=profiler.aggregate(bucket)))
        inventory.append(dict(graph=graph, sessionIndex=sid, sessionOrdinal=ordinal, traceFile=path.name,
            traceSha256=sha(path), traceBytes=path.stat().st_size, modelRuns=len(runs)))
    require(len(process_ids) == 1 and len(run_threads) == 1, 'Mixed trace process or original-run owner identity.')
    summaries, placements = [], []
    for row in plan:
        calls = grouped[row['index']]
        graphs = []
        for graph in game.GRAPHS:
            selected = [c for c in calls if c['graph'] == graph]
            require(len(selected) == game.CALLS[graph], 'Incomplete partitioned passage graph calls.')
            graphs.append(dict(graph=graph, modelRuns=len(selected), operators=profiler.aggregate(
                op for call in selected for op in call['operators'])))
        summary = dict(graphCount=5, modelRuns=12, graphs=graphs, operators=profiler.aggregate(
            op for g in graphs for op in g['operators']), durationMeaning='ORT host event time, not device time or admitted timing.')
        placements.append(dict(passageIndex=row['index'], **game.validate_placement(summary, variant, True)))
        summaries.append(dict(passageIndex=row['index'], **summary))
    return dict(sessionCount=len(sessions), graphCount=5, modelRuns=sum(s['modelRuns'] for s in inventory),
                markersSha256=sha(marker_path), processId=next(iter(process_ids)), runThreadId=next(iter(run_threads)),
                traces=inventory, passages=summaries, placement=placements,
                binding='Source-bound serial original-call markers and non-overlapping per-session ORT model_run ordinals.')


def execute(args, receipt):
    require(sys.platform.startswith('linux'), 'Native maps and process-group ownership require Linux.')
    require(not any(os.environ.get(k) for k in ('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS')), 'Unset Java option injections.')
    for key, value in (('CUBLAS_WORKSPACE_CONFIG', ':4096:8'), ('NVIDIA_TF32_OVERRIDE', '0')):
        require(os.environ.get(key, value) == value, 'Unexpected ' + key); os.environ[key] = value
    provenance, plan = baseline.validate_input(args.input, args.input_provenance)
    manifest = game.verify_models(args.models)
    runtime = profiler.strict_json(ROOT / 'android/native-runtime.json')
    require(runtime['version'] == '1.25.1', 'Production runtime changed.')
    java = args.toolchain / 'jdk17/bin'
    shared = [args.toolchain / 'test-json.jar', args.toolchain / 'android-sdk/platforms/android-35/android.jar']
    require(all(p.is_file() and not p.is_symlink() for p in shared), 'Missing compile dependency.')
    runtimes, dependencies = {}, {}
    for variant in args.variants:
        spec = runtime['host'] if variant == 'cpu_all' else accel.GPU_RUNTIME
        path = args.toolchain / 'onnx' / spec['name'] if variant == 'cpu_all' or args.gpu_runtime is None else args.gpu_runtime
        accel.verify_runtime(path, spec); runtimes[variant] = path; dependencies[variant] = [*shared, path]
    sources = [ROOT / name for name in SOURCE_BINDINGS]
    require(all(p.is_file() and not p.is_symlink() for p in sources), 'Missing source binding.')
    bound = set(sources + [args.input, args.input_provenance, *shared, *runtimes.values(), args.models / 'manifest.json'] +
                [args.models / name for name in manifest['files']])
    hashes = {p: sha(p) for p in bound}
    receipt.update(inputProvenance=provenance, inputProvenanceSha256=sha(args.input_provenance), passagePlan=plan,
        variants=args.variants, lifecycleArms=list(ARMS), modes=list(MODES),
        sourceHashes={str(p.relative_to(ROOT)): hashes[p] for p in sources},
        dependencyHashes={p.name: hashes[p] for p in [*shared, *runtimes.values()]},
        modelManifestSha256=sha(args.models / 'manifest.json'), modelHashes={n: e['sha256'] for n, e in manifest['files'].items()},
        host=accel.benchmark.host_metadata(), gpuInventory=accel.gpu_inventory() if 'cuda_basic' in args.variants else None,
        executionIdentity={v: baseline.execution_identity(v) for v in args.variants},
        requestedGraphProviders={v: game.requested_graph_providers(v, True) for v in args.variants},
        cudaOptions=accel.CUDA_OPTIONS if 'cuda_basic' in args.variants else None,
        cublasWorkspaceConfig=':4096:8', nvidiaTf32Override='0',
        cudaVisibility={k: os.environ.get(k) for k in ('CUDA_VISIBLE_DEVICES', 'CUDA_DEVICE_ORDER')},
        gpuQualificationIncluded='cuda_basic' in args.variants, runs=[], providerTraces={}, observerComparisons=[],
        withinProviderComparisons=[], generatedSources={}, runtimeProbes=[])
    for variant in args.variants:
        accel.verify_java_api(java, runtimes[variant])
        probe_dir = args.output / (variant + '-runtime-probe')
        receipt['runtimeProbes'].append(accel.probe_runtime(java, dependencies[variant], probe_dir, variant == 'cuda_basic'))
        for path in probe_dir.rglob('*'):
            require(not path.is_symlink(), 'Unexpected runtime-probe symlink.')
            if path.is_file(): hashes[path] = sha(path)
    write_json(args.output / 'receipt.json', receipt)
    original = game.SOURCE.read_text()
    outputs = {v: {a: {} for a in ARMS} for v in args.variants}
    for variant in args.variants:
        for arm in ARMS:
            for mode in MODES:
                key = variant + '_' + arm + '_' + mode
                directory = args.output / (('readiness_' if args.check_readiness else '') + key)
                traces = args.output / (key + '_lifetime_traces') if mode == 'profiled' else None
                if traces is not None: traces.mkdir()
                snapshot = source_snapshot(original, variant, arm, mode, provenance['sourceSamples'], provenance['language'], traces)
                classes, artifacts = compile_snapshot(directory, snapshot, java, dependencies[variant])
                qualified = game.variant_source(original, variant, True, True)
                patch = directory / 'generated.patch'
                patch.write_text(''.join(difflib.unified_diff(qualified.splitlines(True), snapshot.splitlines(True),
                    fromfile='qualified/NativeGame.java', tofile='research/NativeGame.java')))
                artifacts.append(patch)
                hashes.update({p: sha(p) for p in artifacts})
                receipt['generatedSources'][key] = dict(originalSha256=sha(game.SOURCE),
                    qualifiedSha256=hashlib.sha256(qualified.encode()).hexdigest(), snapshotSha256=sha(directory / 'NativeGame.java'),
                    diffSha256=sha(patch))
                if args.check_readiness: continue
                output, maps = directory / 'output', directory / 'cuda-jvm-loaded-library-maps.txt'
                command = [str(java / 'java'), '-Xmx2g', '-XX:MaxDirectMemorySize=2g', '-cp',
                    os.pathsep.join(map(str, [classes, *dependencies[variant]])), 'com.cyberbasslord.lightforge.GameSessionReuseRunner',
                    str(args.models), str(args.input), str(output), str(provenance['language']), str(mode != 'plain').lower(),
                    str(maps) if variant == 'cuda_basic' and mode == 'profiled' else '', str(traces) if traces else '', arm]
                print(key + ': ' + str(len(plan)) + ' complete source passages', flush=True)
                started = time.perf_counter_ns()
                baseline.run_process(command, directory / 'run.log', 1200 * len(plan))
                process_wall = time.perf_counter_ns() - started
                hashes[directory / 'run.log'] = sha(directory / 'run.log')
                item = validate_run(output, mode, arm, provenance, plan, manifest)
                outputs[variant][arm][mode] = output
                receipt['runs'].append(dict(variant=variant, lifecycleArm=arm, mode=mode,
                    receipt=str((output / 'receipt.json').relative_to(args.output)), receiptSha256=sha(output / 'receipt.json'),
                    wallNanos=item['wallNanos'], processWallIncludingStartupAndInspectionNanos=process_wall,
                    passageCount=len(plan), timingEligible=False))
                if mode == 'profiled':
                    receipt['providerTraces'][variant + '_' + arm] = summarize_session_traces(
                        traces, output / 'trace-markers.json', arm, variant, provenance, plan)
                    if variant == 'cuda_basic':
                        libraries = accel.native_library_paths(maps)
                        receipt.setdefault('gpuNativeLibraries', {})[arm] = {str(p): dict(bytes=p.stat().st_size, sha256=sha(p)) for p in libraries}
                        receipt.setdefault('gpuNativeLibraryVersions', {})[arm] = accel.native_library_versions(libraries)
                        hashes.update({p: sha(p) for p in [maps, *libraries]})
                for root in [output] + ([traces] if traces else []):
                    for path in root.rglob('*'):
                        require(not path.is_symlink(), 'Unexpected evidence symlink.')
                        if path.is_file(): hashes[path] = sha(path)
                write_json(args.output / 'receipt.json', receipt)
    baseline.verify_bound_files(hashes)
    receipt['artifactHashes'] = {str(p.relative_to(args.output)): h for p, h in hashes.items() if p.is_relative_to(args.output)}
    receipt['inputsRecheckedAfterQualification'] = True
    if args.check_readiness:
        receipt.update(status='PREFLIGHT_READY', inferenceExecuted=False, readinessSnapshotCount=len(args.variants)*6)
        return
    for variant in args.variants:
        for arm in ARMS:
            for row in plan:
                paths = {m: outputs[variant][arm][m] / f"passage-{row['index']:03d}" for m in MODES}
                plain, captured = (profiler.strict_json(paths[m] / 'receipt.json') for m in ('plain', 'captured'))
                comparison = comparator.compare(paths['captured'], paths['profiled'])
                receipt['observerComparisons'].extend([
                    dict(variant=variant, lifecycleArm=arm, passageIndex=row['index'], kind='plain-vs-capture',
                        rawTensorsByteIdentical=None, unroundedNotesIdentical=plain['notes'] == captured['notes']),
                    dict(variant=variant, lifecycleArm=arm, passageIndex=row['index'], kind='capture-vs-profile',
                        rawTensorsByteIdentical=comparison['exactParity'], unroundedNotesIdentical=comparison['unroundedNotesIdentical'], rawComparison=comparison)])
        for row in plan:
            comparison = comparator.compare(*(outputs[variant][a]['captured'] / f"passage-{row['index']:03d}" for a in ARMS))
            receipt['withinProviderComparisons'].append(dict(variant=variant, passageIndex=row['index'],
                reference='default', candidate='reuse', qualityApproved=False, tolerance=None, **comparison))
    baseline.verify_bound_files(hashes)
    game.validate_observers(receipt['observerComparisons'])
    receipt['observerComparisonsPassed'] = True
    receipt['withinProviderRawAndUnroundedParityProven'] = all(c['exactParity'] and c['unroundedNotesIdentical'] for c in receipt['withinProviderComparisons'])
    receipt['status'] = 'COMPLETE_DIAGNOSTIC' if receipt['withinProviderRawAndUnroundedParityProven'] else 'WITHIN_PROVIDER_EQUIVALENCE_UNPROVEN'


def install_termination_handler():
    """Let Python unwind the active run_process owner on ordinary SIGTERM."""
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Session-reuse collector received SIGTERM')
    signal.signal(signal.SIGTERM, interrupted)


def main():
    install_termination_handler()
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('models', 'input', 'input-provenance', 'output'): parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--toolchain', type=Path, default=ROOT.parent / 'toolchain')
    parser.add_argument('--gpu-runtime', type=Path)
    parser.add_argument('--variants', nargs='+', choices=VARIANTS, default=list(VARIANTS))
    parser.add_argument('--check-readiness', action='store_true')
    args = parser.parse_args()
    require(len(set(args.variants)) == len(args.variants), 'Duplicate provider selection.')
    for field in ('models', 'input', 'input_provenance', 'output', 'toolchain', 'gpu_runtime'):
        if getattr(args, field) is not None: setattr(args, field, getattr(args, field).resolve())
    require(not args.output.exists(), 'Use a new isolated session-reuse evidence directory.')
    args.output.mkdir(parents=True)
    receipt = dict(schema='lightforge.game-session-reuse-experiment.v1', status='INCOMPLETE',
        createdUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(), hostOnly=True,
        appLifecycleEquivalent=False, cancellationAndCloseMayBlock=True, measured=False,
        qualityApproved=False, benchmarkTimingAdmitted=False, target75Proven=False,
        wholeSongSpeedupProven=False, fullVocalStageSpeedupProven=False, androidSpeedupProven=False, releaseAuthorized=False,
        scope='Original float32 GAME only; source-bound complete public/synthetic <=64s fixture. Default/reuse compared within each explicitly selected provider. No prior archive is timing or equivalence evidence; no speed ratio calculated.')
    write_json(args.output / 'receipt.json', receipt)
    try:
        execute(args, receipt)
    except KeyboardInterrupt as error:
        receipt.update(status='INTERRUPTED', failure=str(error) or 'Execution interrupted; active JVM process group retired.')
        write_json(args.output / 'receipt.json', receipt)
        print(receipt['failure'], file=sys.stderr)
        return 130
    except Exception as error:
        receipt.update(status='OBSERVER_COMPARISON_INVALID' if isinstance(error, accel.InvalidObserver) else 'BLOCKED_OR_REJECTED', failure=str(error))
        write_json(args.output / 'receipt.json', receipt)
        print(str(error), file=sys.stderr)
        return 1
    write_json(args.output / 'receipt.json', receipt)
    print(json.dumps({k: receipt[k] for k in ('status', 'qualityApproved', 'benchmarkTimingAdmitted', 'target75Proven')}))
    return 0

if __name__ == '__main__':
    sys.exit(main())
