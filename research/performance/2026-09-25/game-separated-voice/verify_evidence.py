#!/usr/bin/env python3
"""Independently audit CPU GAME on verified public separated voice, without inference.

The original completed upstream Deux run is mandatory. Its explicitly bound,
Git-authenticated auditor is re-executed before any downstream evidence is used.
Original models/runtime binaries remain source-bound producer attestations.
"""
import argparse
import difflib
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = 'research/performance/2026-09-25/game-separated-voice/'
UPSTREAM_VERIFIER = 'research/performance/2026-09-25/deux-full-source/verify_evidence.py'
BASELINE = 'tools/benchmark_game_source_cuda.py'
COLLECTOR = 'tools/benchmark_game_session_reuse.py'
APP_BASELINE = 'ae7ed37ad7539b71ea84f783470c174f1297346e'
APP_FILES = ('android/src/com/cyberbasslord/lightforge/NativeGame.java', 'android/native-runtime.json',
    'web/analysis/game.js', 'web/analysis/wav-reader.js', 'web/analysis/models/game/manifest.json',
    'web/analysis/models/game/config.json')
FLAGS = ('qualityApproved', 'target75Proven', 'benchmarkTimingAdmitted', 'releaseAuthorized')
REFERENCE_FLAGS = (*FLAGS, 'measured', 'fullVocalStageExecuted', 'androidIntegrationApproved',
                   'wholeSongSpeedupProven', 'fullVocalStageSpeedupProven', 'androidSpeedupProven')
PCM_SAMPLES = 2822400
PUBLIC_MIXTURE_SHA = '33f07d502ba19832b62b97d8fb4a11354e81310264bd885d7a06438228773650'
MANIFEST_SHA = '51e172cfaa967d9e2518f01f508a64d49cd283d23ae8e8456af9c6e76eeb4f97'
JDK_ARCHIVE = dict(bytes=193252603, sha256='3808d1d15e3ec6bd5b84057fb5d84c33d8a1536a258146bcea2e603fc726e08e')


def require(value, message):
    if not value:
        raise ValueError(message)


def pin(path):
    require(path.is_file() and not path.is_symlink(), 'Expected a regular file: ' + str(path))
    with path.open('rb') as stream:
        return dict(bytes=path.stat().st_size, sha256=hashlib.file_digest(stream, 'sha256').hexdigest())


def strict_json(path):
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= 512 * 1024**2, 'Invalid JSON file.')
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, 'Duplicate JSON key.')
            result[key] = value
        return result
    def finite(value):
        result = float(value)
        require(math.isfinite(result), 'Nonfinite JSON number.')
        return result
    def invalid(value):
        raise ValueError('Nonfinite JSON constant.')
    return json.loads(path.read_text(), object_pairs_hook=pairs, parse_float=finite, parse_constant=invalid)


def safe_file(root, name):
    require(isinstance(name, str) and name and '\\' not in name and '\x00' not in name and
            not re.match(r'^[A-Za-z]:', name) and not PurePosixPath(name).is_absolute() and
            all(part not in ('', '.', '..') for part in name.split('/')), 'Unsafe relative file identity.')
    target = root
    for part in name.split('/'):
        target /= part
        require(not target.is_symlink(), 'Linked path component.')
    require(target.is_file(), 'Missing evidence file: ' + name)
    return target


def git_blob(repo, commit, name):
    require(re.fullmatch('[a-f0-9]{40}', commit), 'Expected immutable Git commit.')
    require(not PurePosixPath(name).is_absolute() and '..' not in PurePosixPath(name).parts, 'Invalid Git path.')
    return subprocess.check_output(['git', '-C', str(repo), 'show', commit + ':' + name], timeout=30)


def run_child(command, log, timeout=600):
    with log.open('x') as stream:
        process = subprocess.Popen(list(map(str, command)), stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        finally:
            # The authenticated upstream auditor owns a separately sessioned
            # Node replay. Give its SIGTERM handler time to retire that child.
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    require(code == 0, 'Independent child verification failed: ' + str(log))


def audit_scope(value):
    require(value.get('schema') == 'lightforge.deux-source-independent-verification.v1' and
            value.get('status') == 'VERIFIED_CPU_DIAGNOSTIC' and value.get('completedPredictions') == 24 and
            value.get('exactObserverPassages') == 12 and value.get('profiledGraphCalls') == 12 * 335 and
            value.get('productionReplayReceiptsExactlyEqual') is True and value.get('savedStemFilesReproduced') == 3 and
            value.get('cudaExecuted') is False and value.get('modelInferenceExecuted') is False and
            all(value.get(key) is False for key in FLAGS), 'Upstream completed independent CPU audit is required.')


def independent_trace_owners(directory):
    """Recheck serial ORT ownership independently; never align Java/ORT clocks."""
    pids, tids, calls = set(), set(), 0
    paths = list(directory.iterdir())
    require(len(paths) == 30, 'Expected 30 original default-arm session traces.')
    for path in paths:
        events = strict_json(path)
        require(isinstance(events, list), 'Expected ORT trace event list.')
        for event in events:
            require(isinstance(event, dict), 'Invalid ORT trace event.')
            if event.get('cat') == 'Session' and event.get('name') == 'model_run' and event.get('ph') == 'X':
                require(type(event.get('pid')) is int and event['pid'] > 0 and
                        type(event.get('tid')) is int and event['tid'] > 0, 'ORT call lacks integer process/thread ownership.')
                pids.add(event['pid'])
                tids.add(event['tid'])
                calls += 1
    require(calls == 72 and len(pids) == len(tids) == 1, 'Mixed or incomplete original ORT run owner identity.')
    return dict(processId=next(iter(pids)), runThreadId=next(iter(tids)), modelRuns=calls)


def verify_upstream(args, root, bindings, output):
    """Authenticate the mandatory upstream auditor before importing its utilities."""
    upstream = bindings['upstream']
    verifier = upstream['verifier']
    require(verifier['path'] == UPSTREAM_VERIFIER, 'Unexpected upstream verifier path.')
    verifier_bytes = git_blob(args.repo, upstream['verifierSourceCommit'], UPSTREAM_VERIFIER)
    expected = dict(bytes=len(verifier_bytes), sha256=hashlib.sha256(verifier_bytes).hexdigest())
    require(expected == {key: verifier[key] for key in ('bytes', 'sha256')}, 'Upstream verifier differs from immutable Git source.')
    require(safe_file(root, 'upstream-verification-source/' + UPSTREAM_VERIFIER).read_bytes() == verifier_bytes,
            'Saved upstream verification source differs.')
    for prefix in ('execution', 'verifier'):
        actual_tree = subprocess.check_output(['git', '-C', str(args.repo), 'rev-parse', upstream[prefix + 'SourceCommit'] + '^{tree}'],
                                             text=True, timeout=30).strip()
        require(actual_tree == upstream[prefix + 'SourceTree'], 'Upstream Git tree identity differs.')
    selected = output / 'upstream-verifier.py'
    with selected.open('xb') as stream:
        stream.write(verifier_bytes)
    spec = importlib.util.spec_from_file_location('verified_upstream_evidence_tools', selected)
    utility = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utility)
    require(not args.upstream_run.is_symlink() and args.upstream_run.is_dir(), 'Mandatory original upstream run is absent or linked.')
    upstream_before = utility.inventory(args.upstream_run)
    for key, local_name, original_name in (
        ('driverReceipt', 'upstream-driver-receipt.json', 'driver-receipt.json'),
        ('qualificationReceipt', 'upstream-qualification-receipt.json', 'qualification/receipt.json'),
        ('consumerReceipt', 'upstream-consumer-receipt.json', 'consumer/receipt.json'),
        ('runtimeBindings', 'upstream-runtime-input-bindings.json', 'runtime-input-bindings.json')):
        require(pin(safe_file(root, 'source-artifacts/' + local_name)) == upstream[key] ==
                pin(safe_file(args.upstream_run, original_name)), 'Upstream recorded/source artifact differs: ' + key)
    prior = strict_json(safe_file(root, 'source-artifacts/upstream-verification.json'))
    require(pin(root / 'source-artifacts/upstream-verification.json') == upstream['audit'], 'Submitted upstream audit differs.')
    audit_scope(prior)
    require(prior['verifierSha256'] == expected['sha256'] and prior['verifierBytes'] == expected['bytes'] and
            prior['executionSourceCommit'] == upstream['executionSourceCommit'] and
            prior['executionSourceTree'] == upstream['executionSourceTree'], 'Submitted upstream audit source differs.')
    run_child([sys.executable, '-I', selected, '--repo', args.repo, '--run-directory', args.upstream_run,
        '--source-commit', upstream['executionSourceCommit'], '--output-dir', output / 'upstream-audit'],
        output / 'upstream-audit.log')
    fresh_path = output / 'upstream-audit/verification.json'
    fresh = strict_json(fresh_path)
    audit_scope(fresh)
    require(fresh['verifierSha256'] == expected['sha256'] and fresh['verifierBytes'] == expected['bytes'] and
            fresh['executionSourceCommit'] == upstream['executionSourceCommit'] and fresh['executionSourceTree'] == upstream['executionSourceTree'],
            'Fresh upstream verification source differs.')
    consumer = strict_json(root / 'source-artifacts/upstream-consumer-receipt.json')
    voice_pin = {key: consumer['outputFiles']['cpu_all/voice-full.wav'][key] for key in ('bytes', 'sha256')}
    require(pin(safe_file(root, 'source-artifacts/voice-full.wav')) == voice_pin ==
            pin(safe_file(args.upstream_run, 'consumer/cpu_all/voice-full.wav')) == upstream['voiceWav'],
            'Separated voice differs from verified upstream consumer.')
    upstream_bindings = strict_json(safe_file(args.upstream_run, 'runtime-input-bindings.json'))
    require(all(bindings[key] == upstream_bindings[key] for key in ('jdk', 'jdkSymlinks', 'jdkArchive')),
            'GAME Java runtime differs from re-audited original archive-verified preparation.')
    require(upstream_before == utility.inventory(args.upstream_run), 'Original upstream evidence changed during audit.')
    return utility, consumer, dict(verifier=expected, priorAudit=upstream['audit'], freshAudit=pin(fresh_path),
        originalUpstreamInventoryUnchanged=True, upstreamModelInferenceExecuted=False)


def verify_bindings(root, source, files, bindings, commit, tree, utility):
    require(bindings['schema'] == 'lightforge.game-separated-voice-bindings.v1' and bindings['sourceCommit'] == commit and
            bindings['sourceTree'] == tree and bindings['sources'] == files and bindings['cpuOnly'] is True and
            all(bindings[key] is False for key in REFERENCE_FLAGS), 'Downstream source/runtime scope differs.')
    manifest_path = safe_file(source, 'web/analysis/models/game/manifest.json')
    manifest = strict_json(manifest_path)
    require(pin(manifest_path)['sha256'] == MANIFEST_SHA and
            bindings['models'] == {'manifest.json': pin(manifest_path), **manifest['files']}, 'Original float32 GAME model identities differ.')
    runtime = strict_json(source / 'android/native-runtime.json')
    expected = {'android.jar': dict(bytes=27092450, sha256='4566663c3876e022b4fa4ced8c8697c4ab1688267f090114fd92d027b32e619b'),
        'test-json.jar': dict(bytes=90031, sha256='c243f45f9590c12694a4142ed3f07fc70dfb71e4daebd05ae234bf92a2da92a6'),
        'onnxruntime-1.25.1.jar': {key: runtime['host'][key] for key in ('bytes', 'sha256')}}
    require(runtime['version'] == '1.25.1' and bindings['dependencies'] == expected and bindings['jdkArchive'] == JDK_ARCHIVE,
            'Original CPU runtime identity differs.')
    essential = ('bin/java', 'bin/javac', 'bin/javap', 'lib/modules', 'lib/libjli.so', 'lib/server/libjvm.so')
    require(all(name in bindings['jdk'] for name in essential), 'Essential JDK runtime libraries unbound.')
    for name, value in bindings['jdk'].items():
        utility.safe_relative(name)
        utility.validate_pin(value)
    require(not set(bindings['jdk']).intersection(bindings['jdkSymlinks']), 'Overlapping JDK files and links.')
    for name, target in bindings['jdkSymlinks'].items():
        utility.safe_relative(name)
        require(isinstance(target, str) and target and not PurePosixPath(target).is_absolute(), 'Invalid JDK link attestation.')
    return manifest


def verify_qualification(root, source, bindings, manifest, collector, utility):
    baseline = collector.baseline
    provenance, plan = baseline.validate_input(safe_file(root, 'voice-full.f32'), safe_file(root, 'input-provenance.json'))
    require(provenance['sourceKind'] == 'public-separated-vocals' and provenance['separatedVocals'] is True and
            provenance['sourceSamples'] == PCM_SAMPLES and provenance['sampleRate'] == 44100 and provenance['language'] == 0 and
            provenance['upstreamPublicAudioSha256'] == PUBLIC_MIXTURE_SHA and
            provenance['upstreamConsumerReceiptSha256'] == bindings['upstream']['consumerReceipt']['sha256'] and
            provenance['sourceSHA256'] == pin(root / 'source-artifacts/voice-full.wav')['sha256'] and
            provenance['inputSourceProofSha256'] == pin(root / 'input-proof.json')['sha256'], 'Separated-voice provenance differs.')
    proof = strict_json(root / 'input-proof.json')
    require(proof['schema'] == 'lightforge.game-separated-voice-input-proof.v1' and
            proof['sourceWav'] == pin(root / 'source-artifacts/voice-full.wav') and proof['pcm'] == pin(root / 'voice-full.f32') and
            proof['sourceSamples'] == PCM_SAMPLES and proof['sampleRate'] == 44100 and proof['language'] == 0 and
            proof['productionReaderCalls'] == [dict(first=0, count=1411200), dict(first=1411200, count=1411200)] and
            proof['sourceHashes'] == {name: bindings['sources'][name]['sha256'] for name in ('web/analysis/game.js', 'web/analysis/wav-reader.js')} and
            proof['plan'] == plan and proof['finitePcm'] is True and proof['allPassagesNonSilent'] is True and
            proof['byteIdenticalToProductionReader'] is True and proof['modelInferenceExecuted'] is False and
            proof['qualityApproved'] is False and proof['target75Proven'] is False,
            'Original production input proof differs.')
    directory = root / 'qualification'
    receipt = strict_json(safe_file(directory, 'receipt.json'))
    modes = ['plain', 'captured', 'profiled']
    require(receipt['schema'] == 'lightforge.game-separated-voice-cpu-experiment.v1' and
            receipt['status'] == 'COMPLETE_CPU_REFERENCE_DIAGNOSTIC' and receipt['variants'] == ['cpu_all'] and
            receipt['lifecycleArms'] == ['default'] and receipt['modes'] == modes and receipt['passagePlan'] == plan and
            receipt['inputProvenance'] == provenance and receipt['inputProvenanceSha256'] == pin(root / 'input-provenance.json')['sha256'] and
            receipt['sourceHashes'] == {name: value['sha256'] for name, value in bindings['sources'].items()} and
            receipt['modelManifestSha256'] == MANIFEST_SHA and
            receipt['modelHashes'] == {name: value['sha256'] for name, value in manifest['files'].items()} and
            receipt['dependencyHashes'] == {name: value['sha256'] for name, value in bindings['dependencies'].items()} and
            receipt['executionIdentity'] == {'cpu_all': baseline.execution_identity('cpu_all')} and
            receipt['requestedGraphProviders'] == {'cpu_all': baseline.game.requested_graph_providers('cpu_all', True)} and
            receipt['inputsRecheckedAfterQualification'] is True and receipt['observerComparisonsPassed'] is True and
            receipt['readinessCompiledSnapshotCount'] == 3 and receipt['gpuQualificationIncluded'] is False and
            receipt['cudaExecuted'] is False and receipt['hostOnly'] is True and receipt['appLifecycleEquivalent'] is False and
            all(receipt[key] is False for key in REFERENCE_FLAGS), 'Completed three-mode CPU reference collection differs.')
    probe = receipt['runtimeProbe']
    probe_log = safe_file(directory, 'cpu_all-runtime-probe/probe.log').read_text().strip()
    require(probe['runtimeVersion'] == '1.25.1' and probe['cudaRequested'] is False and probe['cudaKernelExecutionProven'] is False and
            probe['output'] == probe_log and probe_log.splitlines() == ['1.25.1', '[CPU]'], 'Observed CPU runtime probe differs.')
    require(set(receipt['generatedSources']) == {'cpu_all_' + mode for mode in modes}, 'Snapshot matrix differs.')
    require(len(receipt['runs']) == 3 and [row['mode'] for row in receipt['runs']] == modes, 'Incomplete selected CPU run matrix.')
    outputs, actual_observers = {}, []
    for mode, row in zip(modes, receipt['runs']):
        label = 'cpu_all_' + mode
        folder = directory / label
        observed = safe_file(folder, 'NativeGame.java').read_text()
        traces = Path('/verified/lifetime-trace-placeholder') if mode == 'profiled' else None
        original = baseline.game.SOURCE.read_text()
        expected_source = collector.source_snapshot(original, 'cpu_all', 'default', mode, PCM_SAMPLES, 0, traces)
        require(observed == expected_source, 'Generated source differs from frozen original transformation.')
        qualified = baseline.game.variant_source(original, 'cpu_all', True, True)
        patch = ''.join(difflib.unified_diff(qualified.splitlines(True), expected_source.splitlines(True),
            fromfile='qualified/NativeGame.java', tofile='research/NativeGame.java'))
        require(safe_file(folder, 'generated.patch').read_text() == patch, 'Generated patch differs from frozen transformation.')
        require(receipt['generatedSources'][label]['snapshotSha256'] == pin(folder / 'NativeGame.java')['sha256'], 'Generated source pin differs.')
        require(receipt['generatedSources'][label]['diffSha256'] == pin(folder / 'generated.patch')['sha256'], 'Generated patch pin differs.')
        for filename in ('GameSessionReuseRunner.java', 'GameSessionReuseTrace.java', 'GameAcceleratorCapture.java'):
            require(safe_file(folder, filename).read_bytes() == safe_file(source, 'tools/game_benchmark/' + filename).read_bytes(), 'Copied source helper differs.')
        classes = {path.relative_to(folder / 'classes').as_posix() for path in (folder / 'classes').rglob('*.class')}
        require(classes == {'com/cyberbasslord/lightforge/' + name for name in
            ('NativeGame.class', 'NativeGame$Owned.class', 'NativeGame$Cancellation.class', 'NativeGame$Listener.class',
             'GameAcceleratorCapture.class', 'GameAcceleratorCapture$1.class', 'GameSessionReuseRunner.class', 'GameSessionReuseTrace.class')},
            'Compiled source/helper class inventory differs.')
        output = folder / 'output'
        actual_run = collector.validate_run(output, mode, 'default', provenance, plan, manifest)
        require(row['variant'] == 'cpu_all' and row['lifecycleArm'] == 'default' and row['receipt'] == label + '/output/receipt.json' and
                row['receiptSha256'] == pin(output / 'receipt.json')['sha256'] and row['wallNanos'] == actual_run['wallNanos'] and
                row['passageCount'] == 6 and row['timingEligible'] is False and all(actual_run[key] is False for key in FLAGS),
                'Nested GAME aggregate binding differs.')
        outputs[mode] = output
    for passage in plan:
        paths = {mode: outputs[mode] / f"passage-{passage['index']:03d}" for mode in modes}
        plain, captured = [strict_json(paths[mode] / 'receipt.json') for mode in ('plain', 'captured')]
        compared = baseline.comparator.compare(paths['captured'], paths['profiled'])
        actual_observers.extend([
            dict(variant='cpu_all', passageIndex=passage['index'], kind='plain-vs-capture', rawTensorsByteIdentical=None,
                 unroundedNotesIdentical=plain['notes'] == captured['notes']),
            dict(variant='cpu_all', passageIndex=passage['index'], kind='capture-vs-profile', rawTensorsByteIdentical=compared['exactParity'],
                 unroundedNotesIdentical=compared['unroundedNotesIdentical'], rawComparison=compared)])
    require(receipt['observerComparisons'] == actual_observers and all(row['unroundedNotesIdentical'] and
            row['rawTensorsByteIdentical'] is not False for row in actual_observers), 'Actual raw observer parity differs.')
    summary = collector.summarize_session_traces(directory / 'cpu_all_profiled_lifetime_traces',
        outputs['profiled'] / 'trace-markers.json', 'default', 'cpu_all', provenance, plan)
    independent_owner = independent_trace_owners(directory / 'cpu_all_profiled_lifetime_traces')
    require(summary['sessionCount'] == 30 and summary['modelRuns'] == 72 and
            all(summary[key] == value for key, value in independent_owner.items()) and
            receipt['providerTraces'] == {'cpu_all': summary} and receipt['placement'] == {'cpu_all': summary['placement']},
            'Original default-arm CPU lifetime trace binding differs.')
    require(receipt['artifactHashes'] == {name: value['sha256'] for name, value in utility.inventory(directory).items()
            if name != 'receipt.json'}, 'Complete qualification artifact inventory differs.')
    return receipt, proof, provenance


def audit(args, output):
    root = args.run_directory.absolute()
    require(root.is_dir() and not root.is_symlink() and not output.resolve().is_relative_to(root.resolve()), 'Invalid evidence/output paths.')
    bindings = strict_json(safe_file(root, 'bindings.json'))
    initial_bindings_pin = pin(root / 'bindings.json')
    tree = subprocess.check_output(['git', '-C', str(args.repo), 'rev-parse', args.source_commit + '^{tree}'], text=True, timeout=30).strip()
    require(bindings['sourceCommit'] == args.source_commit and bindings['sourceTree'] == tree, 'Execution commit/tree differs.')
    utility, upstream_consumer, upstream_report = verify_upstream(args, root, bindings, output)
    require(pin(root / 'bindings.json') == initial_bindings_pin, 'Bindings changed during upstream re-audit.')
    before = utility.inventory(root)
    source = root / 'execution-source'
    files = utility.inventory(source)
    for required in (*APP_FILES, BASELINE, COLLECTOR, HERE + 'run_local.py', HERE + 'input_voice.cjs', HERE + 'replay_voice.cjs', HERE + 'verify_evidence.py'):
        require(required in files, 'Missing frozen source: ' + required)
    for name in files:
        require(safe_file(source, name).read_bytes() == git_blob(args.repo, args.source_commit, name), 'Source differs from immutable execution Git: ' + name)
    for name in APP_FILES:
        require(git_blob(args.repo, args.source_commit, name) == git_blob(args.repo, APP_BASELINE, name), 'Original GAME application changed: ' + name)
    exporter_bytes = git_blob(args.repo, args.source_commit, HERE + 'export_evidence.py')
    export_namespace = {'__name__': 'verified_voice_export_boundary', '__file__': str(source / (HERE + 'export_evidence.py'))}
    exec(compile(exporter_bytes, export_namespace['__file__'], 'exec'), export_namespace)
    for name in before:
        require(name == 'archive-manifest.json' or export_namespace['allowed'](Path(name), files), 'Unreviewed evidence member: ' + name)
    archive_path = root / 'archive-manifest.json'
    if archive_path.exists():
        archive = strict_json(archive_path)
        require(archive['schema'] == 'lightforge.game-separated-voice-archive.v1' and archive['runDirectory'] == root.name and
                archive['executionSourceCommit'] == args.source_commit and archive['executionSourceTree'] == tree and
                archive['upstreamEvidenceMustBeSuppliedSeparately'] is True and all(archive[key] is False for key in FLAGS),
                'Archive source/scope differs.')
        rows = archive['files']
        require(len({row['path'] for row in rows}) == len(rows) and
                {row['path']: {key: row[key] for key in ('bytes', 'sha256')} for row in rows} ==
                {name: value for name, value in before.items() if name != 'archive-manifest.json'}, 'Archive inventory differs from complete actual evidence.')
    manifest = verify_bindings(root, source, files, bindings, args.source_commit, tree, utility)
    collector = utility.import_frozen(source, COLLECTOR)
    producer = utility.import_frozen(source, HERE + 'run_local.py')
    require(set(files) == set(collector.SOURCE_BINDINGS) | set(producer.EXTRA_SOURCES),
            'Unexpected or missing transitive original GAME/producer source.')
    qualification, proof, provenance = verify_qualification(root, source, bindings, manifest, collector, utility)
    require(provenance['pcmSHA256'] == upstream_consumer['arms']['cpu_all']['completeVoicePcmSha256'], 'PCM differs from complete verified upstream voice.')
    driver = strict_json(safe_file(root, 'driver-receipt.json'))
    require(driver['schema'] == 'lightforge.game-separated-voice-driver.v1' and driver['status'] == 'COMPLETE_CPU_REFERENCE_DIAGNOSTIC' and
            driver['executionSourceCommit'] == args.source_commit and driver['executionSourceTree'] == tree and
            driver['allBoundInputsRechecked'] is True and driver['completedJvmRuns'] == 3 and driver['variants'] == ['cpu_all'] and
            driver['lifecycleArms'] == ['default'] and driver['cudaExecuted'] is False and
            all(driver[key] is False for key in REFERENCE_FLAGS), 'Completed reference driver differs.')
    for key, name in (('bindings', 'bindings.json'), ('qualificationReceipt', 'qualification/receipt.json'),
                      ('consumerReceipt', 'consumer/receipt.json'), ('inputProof', 'input-proof.json'), ('inputProvenance', 'input-provenance.json')):
        require(driver[key] == pin(safe_file(root, name)), 'Driver evidence binding differs: ' + key)
    for name in ('upstreamAudit', 'input', 'qualification', 'consumer'):
        require(driver[name + 'ExitCode'] == 0 and driver['stageLogs'][name] == pin(safe_file(root, name + '.log')), 'Driver stage binding differs: ' + name)
    require(not os.environ.get('NODE_OPTIONS') and not os.environ.get('NODE_PATH'), 'Unset injected Node options before independent replay.')
    node_name = shutil.which('node')
    require(node_name, 'Node required for actual production revalidation.')
    node = Path(node_name).resolve()
    node_pin = pin(node)
    # Exact Node command contracts are shared with the source-bound producer.
    (output / 'input-replayed').mkdir()
    run_child([node, source / (HERE + 'input_voice.cjs'), root / 'source-artifacts/voice-full.wav',
        root / 'source-artifacts/upstream-consumer-receipt.json', output / 'input-replayed'], output / 'input-replay.log', 120)
    require(pin(output / 'input-replayed/voice-full.f32') == pin(root / 'voice-full.f32') and
            strict_json(output / 'input-replayed/input-proof.json') == proof and
            strict_json(output / 'input-replayed/input-provenance.json') == provenance, 'Independent original input reader proof differs.')
    run_child([node, source / (HERE + 'replay_voice.cjs'), root,
        output / 'consumer-replayed'], output / 'consumer-replay.log', 300)
    consumer = strict_json(safe_file(root, 'consumer/receipt.json'))
    require(strict_json(output / 'consumer-replayed/receipt.json') == consumer, 'Independent complete production replay receipt differs.')
    require(consumer['schema'] == 'lightforge.game-separated-voice-production-replay.v1' and
            consumer['qualificationReceipt'] == pin(root / 'qualification/receipt.json') and consumer['inputPcm'] == pin(root / 'voice-full.f32') and
            consumer['nativeCalls'] == 6 and consumer['nativeCheckpointResumeIdentical'] is True and
            consumer['independentCheckpointRestoreIdentical'] is True and consumer['cudaExecuted'] is False and
            consumer['modelInferenceExecuted'] is False and consumer['fullVocalStageExecuted'] is False and
            consumer['androidIntegrationApproved'] is False and all(consumer[key] is False for key in FLAGS), 'Actual production GAME consumer scope differs.')
    require(pin(node) == node_pin, 'Audit Node changed during input/consumer replay.')
    require(before == utility.inventory(root), 'Original separated-voice evidence changed during audit.')
    return dict(schema='lightforge.game-separated-voice-independent-verification.v1', status='VERIFIED_CPU_REFERENCE_DIAGNOSTIC',
        executionSourceCommit=args.source_commit, executionSourceTree=tree, upstream=upstream_report,
        completedJvmRuns=3, completedPredictions=18, exactObserverChecks=12, inputReaderReproduced=True,
        productionConsumerReceiptExactlyEqual=True, ignoredReplayReceiptFields=[], originalEvidenceUnchanged=True,
        replayNode=node_pin,
        modelInferenceExecuted=False, cpuEvidenceOnly=True, cudaExecuted=False, fullVocalStageExecuted=False,
        modelRuntimeBytesIncluded=False, modelRuntimeIdentityScope='Source-bound producer attestations; no model/runtime execution by this auditor.',
        qualityApproved=False, target75Proven=False, benchmarkTimingAdmitted=False, releaseAuthorized=False)


def main():
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Independent separated-voice auditor terminated')
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('repo', 'run-directory', 'upstream-run', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    args = parser.parse_args()
    require(re.fullmatch('[a-f0-9]{40}', args.source_commit), 'Full execution commit required.')
    require(not args.output_dir.exists() and not args.output_dir.is_symlink(), 'Use a fresh audit output directory.')
    for original in (args.run_directory, args.upstream_run):
        require(not args.output_dir.resolve().is_relative_to(original.resolve()), 'Output cannot be inside original evidence.')
    args.output_dir.mkdir(parents=True)
    own = pin(Path(__file__).resolve())
    try:
        result = audit(args, args.output_dir)
        require(pin(Path(__file__).resolve()) == own, 'Auditor source changed during verification.')
        result.update(verifier=own)
    except BaseException as error:
        result = dict(schema='lightforge.game-separated-voice-independent-verification.v1', status='REJECTED',
            failure=f'{type(error).__name__}: {error}', verifier=own, modelInferenceExecuted=False,
            qualityApproved=False, target75Proven=False, benchmarkTimingAdmitted=False, releaseAuthorized=False)
        with (args.output_dir / 'verification.json').open('x') as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write('\n')
        raise
    with (args.output_dir / 'verification.json').open('x') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
