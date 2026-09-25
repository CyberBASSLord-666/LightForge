#!/usr/bin/env python3
"""Collect and replay one frozen, CPU-only Deux run on the original public WAV.

No downloads, model conversion, app edits, GPU execution or timing approval.
The whole child workflow shares a 90-minute deadline, followed by bounded cleanup.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).relative_to(ROOT).as_posix()
COLLECTOR = 'tools/benchmark_deux_source_cuda.py'
REPLAY = 'tools/deux_benchmark/replay_source.cjs'
CLEANUP = 'research/performance/2026-09-24/game-full-source/colab_run.py'
HOST_RESTORE = 'research/performance/2026-09-25/session-reuse/restore_host.py'
DEUX_RESTORE = 'research/performance/2026-09-25/deux-full-source/restore_deux_assets.py'
WAV = dict(bytes=11289644, sha256='33f07d502ba19832b62b97d8fb4a11354e81310264bd885d7a06438228773650')
APK = dict(bytes=1205116958, sha256='af83bf403875c55d42fd695d43f6e193114899c1324fbaeaffd6c02d299d882f')
JDK_ARCHIVE = dict(bytes=193252603, sha256='3808d1d15e3ec6bd5b84057fb5d84c33d8a1536a258146bcea2e603fc726e08e')
SHARED = {
    'test-json.jar': dict(bytes=90031, sha256='c243f45f9590c12694a4142ed3f07fc70dfb71e4daebd05ae234bf92a2da92a6'),
    'android-sdk/platforms/android-35/android.jar': dict(bytes=27092450, sha256='4566663c3876e022b4fa4ced8c8697c4ab1688267f090114fd92d027b32e619b'),
}
FLAGS = ('qualityApproved', 'target75Proven', 'benchmarkTimingAdmitted', 'releaseAuthorized')
LIMIT_SECONDS = 90 * 60


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pin(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'Missing or linked input: ' + str(path))
    with path.open('rb') as stream:
        return dict(bytes=path.stat().st_size, sha256=hashlib.file_digest(stream, 'sha256').hexdigest())


def write(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def exact_source(commit, relative):
    path = ROOT / relative
    require(path.is_file() and not path.is_symlink(), 'Missing or linked execution source: ' + relative)
    data = subprocess.check_output(['git', 'show', f'{commit}:{relative}'], cwd=ROOT, timeout=30)
    require(path.read_bytes() == data, 'Uncommitted execution source: ' + relative)
    return data


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def jdk_inventory(root):
    files, links = {}, {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            require(path.resolve().is_relative_to(root.resolve()), 'JDK link escapes its installation.')
            links[relative] = path.readlink().as_posix()
        elif path.is_file():
            files[relative] = pin(path)
    require(all(name in files for name in ('bin/java', 'bin/javac', 'bin/javap', 'lib/modules', 'lib/server/libjvm.so')),
            'Incomplete Java runtime/compiler installation.')
    return files, links


def stage(command, log_path, receipt_path, deadline, cleanup):
    """One owned process group; nested JVM cleanup is delegated to the bound helper."""
    require(time.monotonic() < deadline, 'Overall 90-minute workflow deadline expired.')
    with log_path.open('x') as log:
        process = subprocess.Popen(list(map(str, command)), cwd=ROOT, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        previous = None
        try:
            while process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Overall 90-minute workflow deadline expired.')
                try:
                    process.wait(timeout=min(20, remaining))
                except subprocess.TimeoutExpired:
                    pass
                if receipt_path.is_file():
                    receipt = json.loads(receipt_path.read_text())
                    passages = len(list(receipt_path.parent.glob('cpu_all_*/passage-*/receipt.json')))
                    progress = (receipt.get('status'), len(receipt.get('runs', [])), passages)
                    if progress != previous:
                        print(log_path.stem, *progress, flush=True)
                        previous = progress
        finally:
            cleanup.retire_stage(process)
    return process.returncode


def validate_completion(qualification, replay):
    require(qualification['schema'] == 'lightforge.deux-source-cuda-experiment.v1' and
            qualification['status'] == 'CPU_SOURCE_DIAGNOSTIC_COMPLETE', 'Incomplete CPU model collection.')
    require(qualification['variants'] == ['cpu_all'] and qualification['modes'] == ['plain', 'profiled'] and
            qualification['gpuRuntime'] is None and qualification['rawOutputsByteIdenticalAcrossVariants'] is None and
            qualification['crossVariantComparisons'] == [], 'Unexpected provider scope.')
    require(qualification['audioFrames'] == 64 * 44100 and qualification['audioSha256'] == WAV['sha256'] and
            len(qualification['passagePlan']) == 12, 'Incomplete public source clock.')
    require([row['label'] for row in qualification['runs']] == ['cpu_all_plain', 'cpu_all_profiled'] and
            all(row['passageCount'] == 12 and row['freshProcessExited'] is True for row in qualification['runs']),
            'Expected two completed fresh JVMs and 24 original predictions.')
    for key in ('observerComparisonsPassed', 'inputsRecheckedAfterQualification', 'allInputAndArtifactHashesRechecked'):
        require(qualification[key] is True, 'Incomplete collection check: ' + key)
    observers = qualification['observerComparisons']
    require(len(observers) == 12 and {row['passageIndex'] for row in observers} == set(range(12)) and
            all(row['variant'] == 'cpu_all' and row['byteIdentical'] is True for row in observers),
            'Incomplete exact plain/profiled observer checks.')
    require(replay['schema'] == 'lightforge-deux-source-consumer-replay-1' and
            replay['status'] == 'CPU_SOURCE_CONSUMER_DIAGNOSTIC_COMPLETE' and
            replay['variants'] == ['cpu_all'] and replay['passageCount'] == 12 and
            replay['audioSha256'] == WAV['sha256'] and replay['audioSamples'] == 64 * 44100,
            'Incomplete public source consumer replay.')
    require(replay['gpuCaptureConsumed'] is False and replay['crossProviderComparisonPerformed'] is False and
            replay['comparison'] is None and replay['completeStemBytesIdentical'] is None and
            replay['fullVocalStageExecuted'] is False and replay['observerComparisonsIndependentlyByteChecked'] == 12,
            'Unexpected GPU, cross-provider or vocal-stage claim.')
    for key in ('checkpointResumeIdentical', 'originalProductionArithmetic', 'capturedInputSourceBytesRevalidated',
                'persistedOutputBytesRechecked'):
        require(replay[key] is True, 'Incomplete production consumer check: ' + key)
    for evidence in (qualification, replay):
        require(all(evidence[key] is False for key in FLAGS), 'Unexpected research approval.')
    require(all(qualification[key] is False for key in
            ('measured', 'wholeSongSpeedupProven', 'fullVocalStageSpeedupProven', 'androidSpeedupProven')) and
            all(replay[key] is False for key in ('fullAnalysisQualityApproved', 'androidIntegrationApproved')),
            'Unexpected whole-analysis, timing or Android claim.')


def main():
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Local Deux research driver terminated')
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-commit', 'source-tree'):
        parser.add_argument('--' + name, required=True)
    for name in ('toolchain', 'models', 'public-wav', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    for name in ('toolchain', 'models', 'public_wav', 'output'):
        setattr(args, name, getattr(args, name).absolute())
    require(re.fullmatch('[a-f0-9]{40}', args.source_commit) and re.fullmatch('[a-f0-9]{40}', args.source_tree),
            'Full source commit and tree identities are required.')
    require(subprocess.check_output(['git', 'rev-parse', args.source_commit + '^{tree}'], cwd=ROOT,
            text=True, timeout=30).strip() == args.source_tree, 'Source commit/tree mismatch.')
    # Imported Python dependencies are frozen before module-level helper imports execute.
    initial_sources = (HERE, COLLECTOR, CLEANUP, 'tools/benchmark_deux_accelerator.py',
                       'tools/profile_deux_operators.py', 'tools/benchmark_deux_execution.py')
    for relative in initial_sources:
        exact_source(args.source_commit, relative)
    collector = load('local_deux_collector', COLLECTOR)
    cleanup = load('local_deux_cleanup', CLEANUP)
    sources = set(collector.SOURCE_BINDINGS) | set(initial_sources) | {HOST_RESTORE, DEUX_RESTORE}
    source_bytes = {relative: exact_source(args.source_commit, relative) for relative in sorted(sources)}
    require(pin(args.public_wav) == WAV, 'Only the complete original public glass-castle.wav is admitted.')
    require(not args.output.exists() and not args.output.is_symlink(), 'Use a new evidence directory.')
    args.output.mkdir(parents=True)
    started = time.monotonic()
    deadline = started + LIMIT_SECONDS
    status = dict(schema='lightforge.deux-source-local-driver.v1', status='INCOMPLETE',
        createdUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        executionSourceCommit=args.source_commit, executionSourceTree=args.source_tree,
        variants=['cpu_all'], cudaExecuted=False, maximumWorkflowSeconds=LIMIT_SECONDS,
        fullVocalStageExecuted=False, qualityApproved=False, target75Proven=False,
        benchmarkTimingAdmitted=False, releaseAuthorized=False, stageLogs={})
    try:
        for relative, data in source_bytes.items():
            target = args.output / 'execution-source' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(data)
        audio = args.output / 'glass-castle.wav'
        shutil.copyfile(args.public_wav, audio)
        require(pin(audio) == WAV, 'Copied original public WAV differs.')
        provenance = dict(schema='lightforge.deux-source-input.v1', sourceCommit=args.source_commit,
            sourceTree=args.source_tree, sourceKind='public-mixture', sampleRate=44100,
            sourceSamples=64 * 44100, audioSha256=WAV['sha256'], channels=2, encoding='pcm16-le',
            publicRelease='https://github.com/CyberBASSLord-666/LightForge/releases/tag/v2.3.1',
            apkSha256=APK['sha256'], audioMember='assets/demo/glass-castle.wav',
            derivation='Complete, unmodified 64-second public stereo PCM16 glass-castle.wav from the exact public v2.3.1 APK. '
                       'The original native reader supplies each 13-second context and zero padding; original production '
                       'separator replay independently rechecks every decoded stereo context. No private audio is used.',
            qualityApproved=False, target75Proven=False)
        write(args.output / 'input-provenance.json', provenance)
        manifest = collector.profiler.verify_models(args.models)
        require(len(manifest['files']) == 27, 'Exact original 27-graph model inventory required.')
        runtime = json.loads((ROOT / 'android/native-runtime.json').read_text())
        dependencies = {name: args.toolchain / name for name in SHARED}
        dependencies['onnx/' + runtime['host']['name']] = args.toolchain / 'onnx' / runtime['host']['name']
        for name, expected in SHARED.items():
            require(pin(dependencies[name]) == expected, 'Pinned shared runtime dependency differs: ' + name)
        require(pin(dependencies['onnx/' + runtime['host']['name']]) ==
                {key: runtime['host'][key] for key in ('bytes', 'sha256')}, 'Original host ORT runtime differs.')
        archive = args.toolchain / 'downloads/jdk17.tar.gz'
        require(pin(archive) == JDK_ARCHIVE, 'Pinned original Java archive differs.')
        node_name = shutil.which('node')
        require(node_name is not None, 'Node is required for the original production replay.')
        node = Path(node_name).resolve()
        version = subprocess.check_output([node, '--version'], text=True, timeout=30).strip()
        require(re.fullmatch(r'v(?:2[0-9]|[3-9][0-9])\.\d+\.\d+', version), 'Observed Node 20+ is required.')
        jdk_files, jdk_links = jdk_inventory(args.toolchain / 'jdk17')
        preparation = {name: args.toolchain / name for name in
                       ('host-preparation-receipt.json', 'deux-preparation-receipt.json')}
        host_prep = json.loads(preparation['host-preparation-receipt.json'].read_text())
        require(host_prep['schema'] == 'lightforge.host-game-research-preparation.v1' and
                host_prep['installedJdkMatchesPinnedArchive'] is True and
                host_prep['jdkFiles'] == jdk_files and host_prep['jdkSymlinks'] == jdk_links and
                host_prep['restoreScript'] == pin(ROOT / HOST_RESTORE),
                'Installed Java is not the archive-verified original preparation.')
        jdk_archive_rows = [row for row in host_prep['archives'] if Path(row['path']).name == 'jdk17.tar.gz']
        require(len(jdk_archive_rows) == 1 and
                {key: jdk_archive_rows[0][key] for key in ('bytes', 'sha256')} == JDK_ARCHIVE,
                'Preparation JDK archive identity differs.')
        for name, dependency in dependencies.items():
            rows = [row for row in host_prep['javaInputs'] if Path(row['path']).name == dependency.name]
            require(len(rows) == 1 and {key: rows[0][key] for key in ('bytes', 'sha256')} == pin(dependency),
                    'Preparation runtime dependency differs: ' + name)
        deux_prep = json.loads(preparation['deux-preparation-receipt.json'].read_text())
        require(deux_prep['schema'] == 'lightforge.host-deux-research-preparation.v1' and
                deux_prep['hostPreparationReceipt'] == pin(preparation['host-preparation-receipt.json']) and
                deux_prep['publicApk'] == APK and deux_prep['modelManifest'] == pin(args.models / 'manifest.json') and
                deux_prep['models'] == {name: pin(args.models / name) for name in manifest['files']} and
                deux_prep['restoreScript'] == pin(ROOT / DEUX_RESTORE),
                'Preparation evidence does not bind the original host, APK and model manifest.')
        for name, source in preparation.items():
            shutil.copyfile(source, args.output / name)
        bindings = dict(schema='lightforge.deux-source-local-bindings.v1',
            sourceCommit=args.source_commit, sourceTree=args.source_tree,
            models={name: pin(args.models / name) for name in ['manifest.json', *manifest['files']]},
            dependencies={name: pin(path) for name, path in dependencies.items()},
            jdk=jdk_files, jdkSymlinks=jdk_links, jdkArchive=pin(archive),
            node=dict(version=version, **pin(node)), python=pin(Path(sys.executable).resolve()),
            publicWav=pin(audio), inputProvenance=pin(args.output / 'input-provenance.json'),
            sources={relative: pin(ROOT / relative) for relative in sorted(sources)},
            preparation={name: pin(path) for name, path in preparation.items()},
            variants=['cpu_all'], cudaExecuted=False, qualityApproved=False, target75Proven=False)
        write(args.output / 'runtime-input-bindings.json', bindings)
        base = [sys.executable, ROOT / COLLECTOR, '--toolchain', args.toolchain, '--models', args.models,
                '--audio', audio, '--input-provenance', args.output / 'input-provenance.json', '--cpu-only']
        for name, command in (
            ('readiness', [*base, '--output', args.output / 'readiness', '--check-readiness']),
            ('qualification', [*base, '--output', args.output / 'qualification']),
            ('consumer', [node, ROOT / REPLAY, args.output / 'qualification', audio, args.output / 'consumer'])):
            log = args.output / (name + '.log')
            try:
                code = stage(command, log, args.output / name / 'receipt.json', deadline, cleanup)
                status[name + 'ExitCode'] = code
            finally:
                if log.is_file():
                    status['stageLogs'][name] = pin(log)
            require(code == 0, name + ' failed; retain and inspect original evidence.')
            if name == 'readiness':
                ready = json.loads((args.output / 'readiness/receipt.json').read_text())
                require(ready['status'] == 'PREFLIGHT_READY' and ready['readinessSnapshotCount'] == 2 and
                        ready['inferenceExecuted'] is False and ready['variants'] == ['cpu_all'], 'CPU preflight incomplete.')
        final = json.loads((args.output / 'qualification/receipt.json').read_text())
        replay = json.loads((args.output / 'consumer/receipt.json').read_text())
        validate_completion(final, replay)
        require(replay['experimentReceiptSha256'] == pin(args.output / 'qualification/receipt.json')['sha256'],
                'Replay is not bound to this collection receipt.')
        for relative, data in source_bytes.items():
            require((ROOT / relative).read_bytes() == data and
                    (args.output / 'execution-source' / relative).read_bytes() == data, 'Execution source changed: ' + relative)
        require(bindings['models'] == {name: pin(args.models / name) for name in bindings['models']}, 'Original models changed.')
        require(bindings['dependencies'] == {name: pin(path) for name, path in dependencies.items()}, 'Runtime dependency changed.')
        require((bindings['jdk'], bindings['jdkSymlinks']) == jdk_inventory(args.toolchain / 'jdk17'), 'Java installation changed.')
        require(bindings['jdkArchive'] == pin(archive) and bindings['node'] == dict(version=version, **pin(node)) and
                bindings['python'] == pin(Path(sys.executable).resolve()), 'Bound runtime binary changed.')
        require(bindings['publicWav'] == pin(audio) == pin(args.public_wav) and
                bindings['inputProvenance'] == pin(args.output / 'input-provenance.json'), 'Public input changed.')
        require(bindings['preparation'] == {name: pin(path) for name, path in preparation.items()} ==
                {name: pin(args.output / name) for name in preparation}, 'Preparation evidence changed.')
        expected_outputs = {'cpu_all/' + name for name in ('voice-full.wav', 'vocals.wav', 'accompaniment.wav')}
        require(set(replay['outputFiles']) == expected_outputs, 'Unexpected derived stem inventory.')
        for relative, descriptor in replay['outputFiles'].items():
            require(pin(args.output / 'consumer' / relative) == {key: descriptor[key] for key in ('bytes', 'sha256')},
                    'Saved production stem changed: ' + relative)
        require(time.monotonic() <= deadline, 'Overall workflow deadline expired during final recheck.')
        status.update(status='COMPLETE_DIAGNOSTIC', completedJvmRuns=2, completedPredictions=24,
            allBoundInputsRechecked=True, qualificationStatus=final['status'], consumerStatus=replay['status'],
            qualificationReceipt=pin(args.output / 'qualification/receipt.json'),
            consumerReceipt=pin(args.output / 'consumer/receipt.json'), outputFiles=replay['outputFiles'])
    except BaseException as error:
        status.update(status='BLOCKED_OR_REJECTED', failure=f'{type(error).__name__}: {error}')
        raise
    finally:
        status['elapsedDiagnosticSeconds'] = time.monotonic() - started
        write(args.output / 'driver-receipt.json', status)
        print(json.dumps(status, indent=2), flush=True)


if __name__ == '__main__':
    main()
