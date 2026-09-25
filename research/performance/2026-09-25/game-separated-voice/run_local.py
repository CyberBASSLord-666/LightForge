#!/usr/bin/env python3
"""Frozen original-lifetime CPU GAME reference on independently verified Deux voice.

Only three fresh JVMs run. Models, numerical settings, application source and
per-passage session retirement are unchanged. This is never a timing approval.
"""
import argparse
import datetime
import difflib
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[4]
PREFIX = 'research/performance/2026-09-25/game-separated-voice/'
HERE = PREFIX + 'run_local.py'
COLLECTOR = 'tools/benchmark_game_session_reuse.py'
UPSTREAM_VERIFIER = 'research/performance/2026-09-25/deux-full-source/verify_evidence.py'
CLEANUP = 'research/performance/2026-09-24/game-full-source/colab_run.py'
JDK_INVENTORY = 'research/performance/2026-09-25/session-reuse/run_local.py'
APP_BASELINE = 'ae7ed37ad7539b71ea84f783470c174f1297346e'
APP_FILES = ('android/src/com/cyberbasslord/lightforge/NativeGame.java', 'android/native-runtime.json',
    'web/analysis/game.js', 'web/analysis/wav-reader.js', 'web/analysis/models/game/manifest.json',
    'web/analysis/models/game/config.json')
FLAGS = dict(measured=False, qualityApproved=False, target75Proven=False, benchmarkTimingAdmitted=False,
             releaseAuthorized=False, fullVocalStageExecuted=False, androidIntegrationApproved=False,
             wholeSongSpeedupProven=False, fullVocalStageSpeedupProven=False, androidSpeedupProven=False)
PYTHON_IMPORTS = (COLLECTOR, 'tools/benchmark_game_source_cuda.py', 'tools/benchmark_game_accelerator.py',
    'tools/game_benchmark/session_reuse_candidate.py', 'tools/game_benchmark/compare.py',
    'tools/benchmark_deux_accelerator.py', 'tools/profile_deux_operators.py', 'tools/benchmark_deux_execution.py')
EXTRA_SOURCES = (HERE, PREFIX+'input_voice.cjs', PREFIX+'replay_voice.cjs', PREFIX+'verify_evidence.py',
    PREFIX+'export_evidence.py', CLEANUP, JDK_INVENTORY, 'web/analysis/wav-reader.js', 'web/analysis/models/game/config.json')
DEPENDENCIES = {
    'test-json.jar': dict(bytes=90031, sha256='c243f45f9590c12694a4142ed3f07fc70dfb71e4daebd05ae234bf92a2da92a6'),
    'android.jar': dict(bytes=27092450, sha256='4566663c3876e022b4fa4ced8c8697c4ab1688267f090114fd92d027b32e619b'),
    'onnxruntime-1.25.1.jar': dict(bytes=41804437, sha256='749793ebed63743fec853d093da7987a86ea5cd592d54fba898cd3233100c381')}
JDK_ARCHIVE = dict(bytes=193252603, sha256='3808d1d15e3ec6bd5b84057fb5d84c33d8a1536a258146bcea2e603fc726e08e')


def require(value, message):
    if not value:
        raise ValueError(message)


def pin(path):
    require(path.is_file() and not path.is_symlink(), 'Missing or linked regular file: '+str(path))
    with path.open('rb') as stream:
        return dict(bytes=path.stat().st_size, sha256=hashlib.file_digest(stream, 'sha256').hexdigest())


def read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key: '+key)
            result[key] = value
        return result
    def number(value):
        result = float(value)
        require(math.isfinite(result), 'Nonfinite JSON number')
        return result
    def invalid(value):
        raise ValueError('Nonfinite JSON constant: '+value)
    pin(path)
    return json.loads(path.read_text(), object_pairs_hook=pairs, parse_float=number, parse_constant=invalid)


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def git(commit, relative):
    return subprocess.check_output(['git', 'show', commit+':'+relative], cwd=ROOT, timeout=30)


def tree(commit):
    require(re.fullmatch('[a-f0-9]{40}', commit), 'Exact immutable Git commit required')
    return subprocess.check_output(['git', 'rev-parse', commit+'^{tree}'], cwd=ROOT, text=True, timeout=30).strip()


def exact_source(commit, relative):
    value = git(commit, relative)
    require((ROOT/relative).read_bytes() == value, 'Uncommitted execution source: '+relative)
    return value


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT/relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stage(command, name, output, status, cleanup, timeout):
    log = output/(name+'.log')
    try:
        with log.open('x') as stream:
            process = subprocess.Popen(list(map(str, command)), cwd=ROOT, stdout=stream,
                stderr=subprocess.STDOUT, start_new_session=True)
            started = time.monotonic()
            try:
                while process.poll() is None:
                    require(time.monotonic()-started < timeout, name+' exceeded its bounded execution time')
                    try:
                        process.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        pass
            finally:
                cleanup.retire_stage(process)
        status[name+'ExitCode'] = process.returncode
        require(process.returncode == 0, name+' failed; inspect '+str(log))
    finally:
        if log.is_file():
            status['stageLogs'][name] = pin(log)


def validate_upstream_audit(value, commit, expected_tree, verifier_pin):
    require(value.get('schema') == 'lightforge.deux-source-independent-verification.v1' and
        value.get('status') == 'VERIFIED_CPU_DIAGNOSTIC' and value.get('executionSourceCommit') == commit and
        value.get('executionSourceTree') == expected_tree and value.get('verifierSha256') == verifier_pin['sha256'] and
        value.get('verifierBytes') == verifier_pin['bytes'] and value.get('verifierUnchangedDuringAudit') is True and
        value.get('completeInventoryRechecked') is True and value.get('productionReplayReceiptsExactlyEqual') is True and
        value.get('savedStemFilesReproduced') == 3 and value.get('cudaExecuted') is False,
        'Completed source-bound independent CPU Deux audit required')
    require(all(value.get(k) is False for k in ('qualityApproved', 'target75Proven', 'benchmarkTimingAdmitted',
        'releaseAuthorized', 'fullVocalStageExecuted', 'androidIntegrationApproved')), 'Unexpected upstream approval')


def qualify(args, collector, bindings, output):
    baseline, game, accel = collector.baseline, collector.game, collector.accel
    provenance, plan = baseline.validate_input(output/'voice-full.f32', output/'input-provenance.json')
    require(provenance['sourceKind'] == 'public-separated-vocals' and provenance['separatedVocals'] is True and
            len(plan) == 6 and provenance['sourceSamples'] == 2822400, 'Complete actual separated source required')
    manifest = game.verify_models(args.models)
    java = args.toolchain/'jdk17/bin'
    dependencies = [args.toolchain/'test-json.jar', args.toolchain/'android-sdk/platforms/android-35/android.jar',
                    args.toolchain/'onnx/onnxruntime-1.25.1.jar']
    directory = output/'qualification'
    directory.mkdir()
    receipt = dict(schema='lightforge.game-separated-voice-cpu-experiment.v1', status='INCOMPLETE',
        variants=['cpu_all'], lifecycleArms=['default'], modes=list(collector.MODES), inputProvenance=provenance,
        inputProvenanceSha256=pin(output/'input-provenance.json')['sha256'], passagePlan=plan,
        sourceHashes={n: p['sha256'] for n, p in bindings['sources'].items()},
        modelManifestSha256=pin(args.models/'manifest.json')['sha256'],
        modelHashes={n: p['sha256'] for n, p in manifest['files'].items()},
        dependencyHashes={n: p['sha256'] for n, p in bindings['dependencies'].items()},
        executionIdentity={'cpu_all': baseline.execution_identity('cpu_all')},
        requestedGraphProviders={'cpu_all': game.requested_graph_providers('cpu_all', True)},
        gpuQualificationIncluded=False, cudaExecuted=False, hostOnly=True, appLifecycleEquivalent=False,
        runs=[], observerComparisons=[], providerTraces={}, placement={}, generatedSources={}, **FLAGS)
    # Qualification progress is intentionally mutable until all artifacts close.
    def save():
        (directory/'receipt.json').write_text(json.dumps(receipt, indent=2, allow_nan=False)+'\n')
    save()
    log = output/'qualification.log'
    try:
        accel.verify_runtime(dependencies[-1], read(ROOT/'android/native-runtime.json')['host'])
        accel.verify_java_api(java, dependencies[-1])
        receipt['runtimeProbe'] = accel.probe_runtime(java, dependencies, directory/'cpu_all-runtime-probe', False)
        original = game.SOURCE.read_text()
        snapshots = {}
        for mode in collector.MODES:
            label = 'cpu_all_'+mode
            destination = directory/label
            traces = directory/'cpu_all_profiled_lifetime_traces' if mode == 'profiled' else None
            if traces:
                traces.mkdir()
            generated = collector.source_snapshot(original, 'cpu_all', 'default', mode, 2822400, 0, traces)
            classes, _ = collector.compile_snapshot(destination, generated, java, dependencies)
            patch = ''.join(difflib.unified_diff(original.splitlines(True), generated.splitlines(True),
                fromfile='qualified/NativeGame.java', tofile='research/NativeGame.java'))
            (destination/'generated.patch').write_text(patch)
            receipt['generatedSources'][label] = dict(snapshotSha256=pin(destination/'NativeGame.java')['sha256'],
                diffSha256=pin(destination/'generated.patch')['sha256'])
            snapshots[mode] = (destination, classes, traces)
        receipt['readinessCompiledSnapshotCount'] = 3
        save()
        with log.open('x') as progress:
            for mode in collector.MODES:
                destination, classes, traces = snapshots[mode]
                result = destination/'output'
                progress.write(mode+' started\n'); progress.flush()
                print('cpu_all/default/'+mode+': six separated-voice passages', flush=True)
                baseline.run_process([str(java/'java'), '-Xmx2g', '-XX:MaxDirectMemorySize=2g', '-cp',
                    os.pathsep.join(map(str, [classes, *dependencies])), 'com.cyberbasslord.lightforge.GameSessionReuseRunner',
                    str(args.models), str(output/'voice-full.f32'), str(result), '0', str(mode != 'plain').lower(),
                    '', str(traces) if traces else '', 'default'], destination/'run.log', 7200)
                run = collector.validate_run(result, mode, 'default', provenance, plan, manifest)
                receipt['runs'].append(dict(variant='cpu_all', lifecycleArm='default', mode=mode,
                    receipt=str((result/'receipt.json').relative_to(directory)), receiptSha256=pin(result/'receipt.json')['sha256'],
                    wallNanos=run['wallNanos'], passageCount=6, timingEligible=False))
                if traces:
                    summary = collector.summarize_session_traces(traces, result/'trace-markers.json', 'default', 'cpu_all', provenance, plan)
                    require(summary['sessionCount'] == 30 and summary['modelRuns'] == 72, 'Expected 30 sessions and 72 model calls')
                    receipt['providerTraces']['cpu_all'] = summary
                    receipt['placement']['cpu_all'] = summary['placement']
                progress.write(mode+' complete\n'); progress.flush(); save()
        for row in plan:
            folders = {mode: directory/('cpu_all_'+mode)/'output'/f"passage-{row['index']:03d}" for mode in collector.MODES}
            plain, captured = read(folders['plain']/'receipt.json'), read(folders['captured']/'receipt.json')
            comparison = collector.comparator.compare(folders['captured'], folders['profiled'])
            receipt['observerComparisons'].extend([
                dict(variant='cpu_all', passageIndex=row['index'], kind='plain-vs-capture', rawTensorsByteIdentical=None,
                    unroundedNotesIdentical=plain['notes'] == captured['notes']),
                dict(variant='cpu_all', passageIndex=row['index'], kind='capture-vs-profile',
                    rawTensorsByteIdentical=comparison['exactParity'], unroundedNotesIdentical=comparison['unroundedNotesIdentical'],
                    rawComparison=comparison)])
        game.validate_observers(receipt['observerComparisons'])
        receipt['observerComparisonsPassed'] = True
        receipt['artifactHashes'] = {}
        for p in sorted(directory.rglob('*')):
            require(not p.is_symlink(), 'Linked qualification artifact')
            if p.is_file() and p != directory/'receipt.json':
                receipt['artifactHashes'][p.relative_to(directory).as_posix()] = pin(p)['sha256']
        receipt.update(inputsRecheckedAfterQualification=False, status='CAPTURE_COMPLETE_PENDING_INPUT_RECHECK')
    except BaseException as error:
        receipt.update(status='BLOCKED_OR_REJECTED', failure=type(error).__name__+': '+str(error))
        raise
    finally:
        save()
    return receipt


def main():
    signal.signal(signal.SIGTERM, lambda signum, frame: (_ for _ in ()).throw(KeyboardInterrupt('Separated-voice driver terminated')))
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-commit', 'source-tree', 'upstream-source-commit', 'upstream-verifier-commit'):
        parser.add_argument('--'+name, required=True)
    for name in ('upstream-run', 'upstream-audit', 'toolchain', 'models', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    for name in ('upstream_run', 'upstream_audit', 'toolchain', 'models', 'output'):
        setattr(args, name, getattr(args, name).absolute())
    require(tree(args.source_commit) == args.source_tree, 'Execution tree mismatch')
    require(not any(os.environ.get(n) for n in ('NODE_OPTIONS', 'NODE_PATH', 'JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS')),
        'Unset runtime option injection variables')
    for name in (*PYTHON_IMPORTS, *EXTRA_SOURCES):
        exact_source(args.source_commit, name)
    collector, cleanup, jdk_module = load('voice_collector', COLLECTOR), load('voice_cleanup', CLEANUP), load('voice_jdk', JDK_INVENTORY)
    sources = sorted(set(collector.SOURCE_BINDINGS) | set(EXTRA_SOURCES))
    source_bytes = {name: exact_source(args.source_commit, name) for name in sources}
    require(all(source_bytes[name] == git(APP_BASELINE, name) for name in APP_FILES),
            'Original GAME application/model source differs from the qualified baseline')
    upstream_tree, verifier_tree = tree(args.upstream_source_commit), tree(args.upstream_verifier_commit)
    verifier_bytes = git(args.upstream_verifier_commit, UPSTREAM_VERIFIER)
    verifier_pin = dict(bytes=len(verifier_bytes), sha256=hashlib.sha256(verifier_bytes).hexdigest())
    validate_upstream_audit(read(args.upstream_audit), args.upstream_source_commit, upstream_tree, verifier_pin)
    require(not args.output.exists() and not args.output.is_symlink() and
        not args.output.resolve().is_relative_to(args.upstream_run.resolve()), 'Fresh output outside upstream evidence required')
    args.output.mkdir(parents=True)
    status = dict(schema='lightforge.game-separated-voice-driver.v1', status='INCOMPLETE',
        executionSourceCommit=args.source_commit, executionSourceTree=args.source_tree,
        createdUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(), stageLogs={}, variants=['cpu_all'],
        lifecycleArms=['default'], cudaExecuted=False, submittedUpstreamAudit=pin(args.upstream_audit), **FLAGS)
    try:
        for name, value in source_bytes.items():
            destination = args.output/'execution-source'/name
            destination.parent.mkdir(parents=True, exist_ok=True); destination.write_bytes(value)
        verifier_file = args.output/'upstream-verification-source'/UPSTREAM_VERIFIER
        verifier_file.parent.mkdir(parents=True); verifier_file.write_bytes(verifier_bytes)
        stage([sys.executable, verifier_file, '--repo', ROOT, '--run-directory', args.upstream_run,
            '--source-commit', args.upstream_source_commit, '--output-dir', args.output/'upstream-audit'],
            'upstreamAudit', args.output, status, cleanup, 900)
        fresh_audit = args.output/'upstream-audit/verification.json'
        validate_upstream_audit(read(fresh_audit), args.upstream_source_commit, upstream_tree, verifier_pin)
        require(pin(verifier_file) == verifier_pin, 'Upstream verifier changed')
        artifacts = args.output/'source-artifacts'; artifacts.mkdir()
        upstream_paths = {'driverReceipt': args.upstream_run/'driver-receipt.json',
            'qualificationReceipt': args.upstream_run/'qualification/receipt.json',
            'consumerReceipt': args.upstream_run/'consumer/receipt.json', 'audit': fresh_audit,
            'runtimeBindings': args.upstream_run/'runtime-input-bindings.json'}
        filenames = {'driverReceipt': 'upstream-driver-receipt.json', 'qualificationReceipt': 'upstream-qualification-receipt.json',
            'consumerReceipt': 'upstream-consumer-receipt.json', 'audit': 'upstream-verification.json',
            'runtimeBindings': 'upstream-runtime-input-bindings.json'}
        upstream = dict(executionSourceCommit=args.upstream_source_commit, executionSourceTree=upstream_tree,
            verifierSourceCommit=args.upstream_verifier_commit, verifierSourceTree=verifier_tree,
            verifier=dict(path=UPSTREAM_VERIFIER, **verifier_pin), **{name: pin(p) for name, p in upstream_paths.items()})
        for name, source in upstream_paths.items():
            shutil.copyfile(source, artifacts/filenames[name])
        voice_source = args.upstream_run/'consumer/cpu_all/voice-full.wav'
        shutil.copyfile(voice_source, artifacts/'voice-full.wav')
        upstream['voiceWav'] = pin(voice_source)
        stage(['node', ROOT/(PREFIX+'input_voice.cjs'), artifacts/'voice-full.wav',
            artifacts/'upstream-consumer-receipt.json', args.output], 'input', args.output, status, cleanup, 120)
        manifest = collector.game.verify_models(args.models)
        dependencies = [args.toolchain/'test-json.jar', args.toolchain/'android-sdk/platforms/android-35/android.jar',
            args.toolchain/'onnx/onnxruntime-1.25.1.jar']
        require({p.name: pin(p) for p in dependencies} == DEPENDENCIES, 'Original runtime/compile pins differ')
        require(pin(args.toolchain/'downloads/jdk17.tar.gz') == JDK_ARCHIVE, 'Original JDK archive differs')
        jdk, links = jdk_module.jdk_inventory(args.toolchain/'jdk17')
        upstream_runtime = read(args.upstream_run/'runtime-input-bindings.json')
        require((jdk, links, JDK_ARCHIVE) == (upstream_runtime['jdk'], upstream_runtime['jdkSymlinks'],
            upstream_runtime['jdkArchive']), 'Installed JDK differs from the upstream archive-verified preparation')
        bindings = dict(schema='lightforge.game-separated-voice-bindings.v1', sourceCommit=args.source_commit,
            sourceTree=args.source_tree, sources={n: pin(ROOT/n) for n in sources},
            models={n: pin(args.models/n) for n in ['manifest.json', *manifest['files']]},
            dependencies=DEPENDENCIES, jdkArchive=JDK_ARCHIVE, jdk=jdk, jdkSymlinks=links,
            upstream=upstream, cpuOnly=True, **FLAGS)
        write(args.output/'bindings.json', bindings)
        bound = {ROOT/n: p for n, p in bindings['sources'].items()}
        bound.update({args.models/n: p for n, p in bindings['models'].items()})
        bound.update({p: pin(p) for p in dependencies})
        bound.update({p: pin(p) for p in artifacts.iterdir()})
        bound.update({args.output/n: pin(args.output/n) for n in ('voice-full.f32', 'input-proof.json', 'input-provenance.json')})
        bound.update({p: upstream[name] for name, p in upstream_paths.items()})
        bound[voice_source] = upstream['voiceWav']
        try:
            qualification = qualify(args, collector, bindings, args.output)
            require(all(pin(p) == expected for p, expected in bound.items()), 'Bound input changed during inference')
            require(jdk_module.jdk_inventory(args.toolchain/'jdk17') == (jdk, links), 'JDK changed during inference')
            require(pin(args.toolchain/'downloads/jdk17.tar.gz') == JDK_ARCHIVE, 'JDK archive changed during inference')
            qualification.update(inputsRecheckedAfterQualification=True, status='COMPLETE_CPU_REFERENCE_DIAGNOSTIC')
            (args.output/'qualification/receipt.json').write_text(json.dumps(qualification, indent=2, allow_nan=False)+'\n')
            status['qualificationExitCode'] = 0
        finally:
            if (args.output/'qualification.log').is_file():
                status['stageLogs']['qualification'] = pin(args.output/'qualification.log')
        stage(['node', ROOT/(PREFIX+'replay_voice.cjs'), args.output, args.output/'consumer'],
            'consumer', args.output, status, cleanup, 120)
        require(all(pin(p) == expected for p, expected in bound.items()), 'Bound input changed during production replay')
        require(pin(verifier_file) == verifier_pin, 'Upstream verifier changed during reference')
        status.update(status='COMPLETE_CPU_REFERENCE_DIAGNOSTIC', completedJvmRuns=3, allBoundInputsRechecked=True,
            bindings=pin(args.output/'bindings.json'), qualificationReceipt=pin(args.output/'qualification/receipt.json'),
            consumerReceipt=pin(args.output/'consumer/receipt.json'), inputProof=pin(args.output/'input-proof.json'),
            inputProvenance=pin(args.output/'input-provenance.json'))
    except BaseException as error:
        status.update(status='BLOCKED_OR_REJECTED', failure=type(error).__name__+': '+str(error))
        raise
    finally:
        write(args.output/'driver-receipt.json', status)
    print(json.dumps({k: status[k] for k in ('status', 'completedJvmRuns', 'qualityApproved', 'target75Proven')}))


if __name__ == '__main__':
    main()
