#!/usr/bin/env python3
"""Independently verify bounded GAME session-reuse evidence without inference.

The explicit immutable Git commit is authoritative, not a branch name or the
archive's own source claims. Only matching source bytes may be imported. CPU-only
evidence remains CPU-only. Diagnostic parity never admits timing or quality.
"""
import argparse
import difflib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import subprocess
import sys
import wave
import zipfile

sys.dont_write_bytecode = True
COLLECTOR = 'tools/benchmark_game_session_reuse.py'
ORIGINAL = 'd9b42bb79145cfe81367fd70e2ca0ff7f4d52c12'
MANIFEST_SHA = '51e172cfaa967d9e2518f01f508a64d49cd283d23ae8e8456af9c6e76eeb4f97'
AUDIO_SHA = '33f07d502ba19832b62b97d8fb4a11354e81310264bd885d7a06438228773650'
PCM_SHA = '298f7a549c4bb8dfc53c47d1078cea842c5e818a3e7c82bf289bffcec0ba30c2'
APP_FILES = ('android/src/com/cyberbasslord/lightforge/NativeGame.java', 'android/native-runtime.json',
             'web/analysis/game.js', 'web/analysis/wav-reader.js', 'web/analysis/models/game/manifest.json')
FLAGS = ('qualityApproved', 'target75Proven', 'benchmarkTimingAdmitted', 'releaseAuthorized')
DEPENDENCIES = {
    'test-json.jar': dict(bytes=90031, sha256='c243f45f9590c12694a4142ed3f07fc70dfb71e4daebd05ae234bf92a2da92a6'),
    'android.jar': dict(bytes=27092450, sha256='4566663c3876e022b4fa4ced8c8697c4ab1688267f090114fd92d027b32e619b'),
    'onnxruntime-1.25.1.jar': dict(bytes=41804437, sha256='749793ebed63743fec853d093da7987a86ea5cd592d54fba898cd3233100c381'),
    'onnxruntime_gpu-1.25.1.jar': dict(bytes=397558371, sha256='0a22d140ee2a064944b7ee45b7f7a8deb113f58e9be514da85c6dfbe85262649'),
}


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def strict_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result

    def finite(value):
        result = float(value)
        require(math.isfinite(result), 'Nonfinite JSON value')
        return result

    def invalid(value):
        raise ValueError('Nonfinite JSON constant: ' + value)

    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 512 * 1024**2,
            'Missing, linked, or oversized JSON: ' + str(path))
    return json.loads(path.read_text(), object_pairs_hook=pairs, parse_float=finite, parse_constant=invalid)


def safe_relative(name):
    require(isinstance(name, str) and name and '\\' not in name and '\x00' not in name,
            'Invalid relative path')
    path = PurePosixPath(name)
    require(not path.is_absolute() and not re.match(r'^[A-Za-z]:', name)
            and all(p not in ('', '.', '..') for p in name.split('/')), 'Unsafe relative path: ' + name)
    return path


def safe_file(root, name):
    relative = safe_relative(name)
    path = root
    for part in relative.parts:
        path /= part
        require(not path.is_symlink(), 'Symlink in evidence path: ' + name)
    require(path.is_file(), 'Missing regular evidence file: ' + name)
    return path


def check_pin(path, pin):
    require(isinstance(pin, dict) and type(pin.get('bytes')) is int and pin['bytes'] >= 0
            and re.fullmatch('[a-f0-9]{64}', str(pin.get('sha256', ''))), 'Invalid file pin')
    require(path.is_file() and not path.is_symlink() and path.stat().st_size == pin['bytes']
            and sha(path) == pin['sha256'], 'File pin mismatch: ' + str(path))


def git_blob(repo, commit, name):
    safe_relative(name)
    return subprocess.check_output(['git', '-C', str(repo), 'show', commit + ':' + name])


def extract_zip(args):
    require(args.expected_size is not None and args.expected_sha256 is not None,
            'ZIP requires its independently expected size and SHA256')
    check_pin(args.zip, dict(bytes=args.expected_size, sha256=args.expected_sha256))
    destination = args.output_dir / 'extracted'
    destination.mkdir()
    with zipfile.ZipFile(args.zip) as archive:
        members = archive.infolist()
        require(0 < len(members) <= 30000, 'Invalid ZIP member count')
        seen, total = set(), 0
        for entry in members:
            name = entry.filename[:-1] if entry.is_dir() else entry.filename
            safe_relative(name)
            require(name not in seen, 'Duplicate ZIP member')
            seen.add(name)
            kind = stat.S_IFMT((entry.external_attr >> 16) & 0xffff)
            require(kind in (0, stat.S_IFDIR if entry.is_dir() else stat.S_IFREG), 'Special ZIP member')
            require(not entry.flag_bits & 1 and 0 <= entry.file_size <= args.max_uncompressed_bytes,
                    'Encrypted or oversized ZIP member')
            total += entry.file_size
        require(total <= args.max_uncompressed_bytes, 'ZIP exceeds expansion limit')
        for entry in members:
            target = destination.joinpath(*PurePosixPath(entry.filename).parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output, 1024**2)
                require(target.stat().st_size == entry.file_size, 'ZIP extracted size mismatch')
    check_pin(args.zip, dict(bytes=args.expected_size, sha256=args.expected_sha256))
    roots = list(destination.iterdir())
    require(len(roots) == 1 and roots[0].is_dir(), 'Expected one ZIP evidence root')
    return roots[0], dict(bytes=args.expected_size, sha256=args.expected_sha256,
                         memberCount=len(members), allMemberCrcsVerified=True)


def tree_inventory(root):
    result = {}
    require(root.is_dir() and not root.is_symlink(), 'Evidence root must be a real directory')
    for path in root.rglob('*'):
        require(not path.is_symlink(), 'Symlink in evidence tree')
        require(path.is_dir() or path.is_file(), 'Special file in evidence tree')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = dict(bytes=path.stat().st_size, sha256=sha(path))
    return result


def verify_archive_inventory(root, actual, commit, tree, required):
    path = root / 'archive-manifest.json'
    if not path.exists():
        require(not required, 'ZIP lacks archive inventory')
        return None
    manifest = strict_json(path)
    require(manifest.get('schema') == 'lightforge.game-session-reuse-archive.v1'
            and manifest.get('executionSourceCommit') == commit and manifest.get('executionSourceTree') == tree
            and manifest.get('runDirectory') == root.name
            and all(manifest.get(f) is False for f in ('qualityApproved', 'target75Proven', 'releaseAuthorized')),
            'Archive source/schema/approval mismatch')
    rows = manifest.get('files')
    require(isinstance(rows, list) and rows, 'Missing archive inventory')
    pins = {}
    for row in rows:
        name = row.get('path')
        safe_relative(name)
        require(name not in pins and name != 'archive-manifest.json', 'Duplicate or self-inventory entry')
        pins[name] = {k: row[k] for k in ('bytes', 'sha256')}
    require(pins == {n: p for n, p in actual.items() if n != 'archive-manifest.json'},
            'Archive inventory differs from actual complete tree')
    return dict(fileCount=len(pins), sha256=sha(path))


def verify_sources(root, repo, commit):
    source = root / 'execution-source'
    inventory = tree_inventory(source)
    require(COLLECTOR in inventory and all(p in inventory for p in APP_FILES), 'Missing required frozen source')
    for name in inventory:
        require(safe_file(source, name).read_bytes() == git_blob(repo, commit, name),
                'Snapshot differs from expected Git commit: ' + name)
    for name in APP_FILES:
        require(git_blob(repo, commit, name) == git_blob(repo, ORIGINAL, name),
                'Original application source changed: ' + name)
    require(inventory['web/analysis/models/game/manifest.json']['sha256'] == MANIFEST_SHA,
            'Original GAME manifest changed')
    return source, inventory


def pinned_module(source):
    python = {p.resolve(): p.read_bytes() for p in source.rglob('*.py')}
    original_spec = importlib.util.spec_from_file_location

    class Loader(importlib.machinery.SourceFileLoader):
        def get_code(self, fullname):
            return compile(python[Path(self.path).resolve()], self.path, 'exec', dont_inherit=True)

    def source_spec(name, location=None, *, loader=None, submodule_search_locations=None):
        path = Path(location).resolve()
        require(path in python and loader is None and submodule_search_locations is None,
                'Unverified dynamic import attempted')
        return original_spec(name, str(path), loader=Loader(name, str(path)))

    importlib.util.spec_from_file_location = source_spec
    try:
        spec = source_spec('verified_game_session_reuse', source / COLLECTOR)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        importlib.util.spec_from_file_location = original_spec
    return module


def verify_inputs_before_import(root, source, repo, commit, tree):
    """Resolve trust-critical pins before importing any archived validator code."""
    bindings = strict_json(safe_file(root, 'runtime-input-bindings.json'))
    require(bindings.get('schema') == 'lightforge.game-session-reuse-runtime-bindings.v1'
            and bindings.get('sourceCommit') == commit and bindings.get('sourceTree') == tree
            and bindings.get('variants') == ['cpu_all'] and bindings.get('cudaExecuted') is False
            and bindings.get('qualityApproved') is False and bindings.get('target75Proven') is False,
            'Runtime/input source binding or CPU-only scope differs')
    manifest_path = source / 'web/analysis/models/game/manifest.json'
    manifest = strict_json(manifest_path)
    expected_models = {'manifest.json': dict(bytes=manifest_path.stat().st_size, sha256=MANIFEST_SHA), **manifest['files']}
    require(bindings.get('models') == expected_models, 'Runtime model pins differ from immutable original manifest')
    expected_dependencies = {k: v for k, v in DEPENDENCIES.items() if k != 'onnxruntime_gpu-1.25.1.jar'}
    require(bindings.get('dependencies') == expected_dependencies, 'Runtime/compile dependency pins differ')
    frozen_files = tree_inventory(source)
    require(bindings.get('sources') == frozen_files, 'Runtime source inventory differs from verified Git snapshot')
    pcm = safe_file(root, 'public-demo-mixture-full64s.f32')
    check_pin(pcm, dict(bytes=11289600, sha256=PCM_SHA))
    require(bindings.get('fullPcm') == dict(bytes=11289600, sha256=PCM_SHA), 'Runtime PCM binding differs')
    audio = git_blob(repo, commit, 'web/demo/glass-castle.wav')
    require(hashlib.sha256(audio).hexdigest() == AUDIO_SHA, 'Public WAV Git blob differs')
    require(bindings.get('publicWav') == dict(bytes=len(audio), sha256=AUDIO_SHA), 'Runtime public WAV binding differs')
    with wave.open(io.BytesIO(audio), 'rb') as wav:
        require((wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes(), wav.getcomptype())
                == (2, 2, 44100, 2822400, 'NONE'), 'Public WAV geometry differs')
        frames = wav.readframes(2822400)
    derived = bytearray(11289600)
    for index, (left, right) in enumerate(struct.iter_unpack('<hh', frames)):
        struct.pack_into('<f', derived, index * 4, (left / 32768.0 + right / 32768.0) * .5)
    require(bytes(derived) == pcm.read_bytes(), 'Archived PCM differs from independent public WAV mix')
    provenance_path, proof_path = safe_file(root, 'input-provenance.json'), safe_file(root, 'input-source-proof.json')
    provenance, proof = strict_json(provenance_path), strict_json(proof_path)
    require(provenance.get('schema') == 'lightforge.game-source-input.v1'
            and provenance.get('sourceKind') == 'public-mixture' and provenance.get('separatedVocals') is False
            and provenance.get('sourceSamples') == 2822400 and provenance.get('sampleRate') == 44100
            and provenance.get('sourceSHA256') == AUDIO_SHA and provenance.get('pcmSHA256') == PCM_SHA
            and provenance.get('language') == 0 and provenance.get('inputSourceProofSha256') == sha(proof_path),
            'Public input provenance differs')
    plan = [dict(index=i, key=f'game-0-{i}', first=max(0, i * 529200 - 88200),
                 last=min(2822400, (i + 1) * 529200 + 88200), seed=(2025 + i * 104729) & 0xffffffff)
            for i in range(6)]
    for row in plan:
        row['pcmSha256'] = hashlib.sha256(derived[row['first']*4:row['last']*4]).hexdigest()
    proof_plan = [dict(index=p['index'], first=p['first'], last=p['last'], samples=p['last']-p['first'], language=0, seed=p['seed']) for p in plan]
    require(proof.get('schema') == 'lightforge.game-source-input-proof.v1'
            and proof.get('publicAudioSha256') == AUDIO_SHA and proof.get('pcmSha256') == PCM_SHA
            and proof.get('totalSamples') == 2822400 and proof.get('sampleRate') == 44100
            and proof.get('plan') == proof_plan and proof.get('byteIdenticalToProductionReaderMix') is True
            and proof.get('planOnly') is True and proof.get('scheduleProbeUsesSyntheticNonSilentPCM') is True
            and proof.get('modelInferenceExecuted') is False and proof.get('qualityApproved') is False
            and proof.get('productionReaderCalls') == [dict(first=0, count=1411200), dict(first=1411200, count=1411200)]
            and proof.get('sourceHashes') == {n: sha(source/n) for n in ('web/analysis/wav-reader.js', 'web/analysis/game.js')},
            'Production reader/schedule proof differs')
    preparation = strict_json(safe_file(root, 'host-preparation-receipt.json'))
    require(preparation.get('schema') == 'lightforge.host-game-research-preparation.v1', 'Unknown host preparation schema')
    java_inputs = {Path(r['path']).name: {k: r[k] for k in ('bytes', 'sha256')} for r in preparation['javaInputs']}
    require(all(java_inputs.get(name) == pin for name, pin in expected_dependencies.items()), 'Host preparation dependencies differ')
    jdk = bindings.get('jdk', {})
    essential = {'bin/java', 'bin/javac', 'lib/modules', 'lib/server/libjvm.so', 'lib/jli/libjli.so'}
    require(isinstance(jdk, dict) and essential <= set(jdk), 'Essential JDK runtime libraries unbound')
    for name, pin in jdk.items():
        safe_relative(name)
        require(type(pin.get('bytes')) is int and pin['bytes'] > 0 and re.fullmatch('[a-f0-9]{64}', str(pin.get('sha256'))),
                'Invalid full JDK file pin')
    require(all(java_inputs.get(Path(n).name) == jdk[n] for n in ('bin/java', 'bin/javac', 'lib/modules')),
            'JDK preparation/run binding differs')
    links = bindings.get('jdkSymlinks')
    require(isinstance(links, dict) and not set(links).intersection(jdk), 'Invalid or overlapping JDK symlink map')
    for name, target in links.items():
        safe_relative(name)
        require(isinstance(target, str) and target and '\x00' not in target, 'Invalid JDK symlink target')
    archive_pin = dict(bytes=193252603, sha256='3808d1d15e3ec6bd5b84057fb5d84c33d8a1536a258146bcea2e603fc726e08e')
    require(bindings.get('jdkArchive') == archive_pin, 'Original prepared JDK archive pin differs')
    require(any({k: p[k] for k in ('bytes', 'sha256')} == archive_pin for p in preparation['archives']),
            'Preparation lacks the pinned JDK archive')
    return bindings, pcm, provenance, plan, manifest


def verify_snapshot(directory, key, collector, plan, provenance, recorded, readiness):
    variant, arm, mode = key
    label = '_'.join(key)
    folder = directory / (('readiness_' if readiness else '') + label)
    native = safe_file(folder, 'NativeGame.java')
    traces = Path('/verified/lifetime-trace-placeholder') if mode == 'profiled' else None
    original = collector.game.SOURCE.read_text()
    expected = collector.source_snapshot(original, variant, arm, mode, provenance['sourceSamples'], provenance['language'], traces)
    require(native.read_text() == expected, 'Generated candidate differs from frozen transformation: ' + label)
    qualified = collector.game.variant_source(original, variant, True, True)
    patch = ''.join(difflib.unified_diff(qualified.splitlines(True), expected.splitlines(True),
                                       fromfile='qualified/NativeGame.java', tofile='research/NativeGame.java'))
    require(safe_file(folder, 'generated.patch').read_text() == patch, 'Generated source diff differs')
    pins = dict(originalSha256=sha(collector.game.SOURCE), qualifiedSha256=hashlib.sha256(qualified.encode()).hexdigest(),
                snapshotSha256=sha(native), diffSha256=sha(folder/'generated.patch'))
    require(recorded == pins, 'Generated-source recorded binding differs')
    for helper in collector.HELPERS:
        require(safe_file(folder, helper.name).read_bytes() == helper.read_bytes(), 'Copied helper differs from frozen source')
    classes = {p.relative_to(folder/'classes').as_posix() for p in (folder/'classes').rglob('*.class')}
    expected_classes = {'com/cyberbasslord/lightforge/' + name for name in
        ('NativeGame.class', 'NativeGame$Owned.class', 'NativeGame$Cancellation.class', 'NativeGame$Listener.class',
         'GameAcceleratorCapture.class', 'GameAcceleratorCapture$1.class', 'GameSessionReuseRunner.class', 'GameSessionReuseTrace.class')}
    require(classes == expected_classes, 'Unexpected compiled class inventory: ' + label)
    return pins


def validate_trace_process_identity(traces):
    """Only same-ORT-process identity is compared; independent clocks are not."""
    pids, tids = set(), set()
    for path in traces.iterdir():
        for event in strict_json(path):
            if event.get('cat') == 'Session' and event.get('name') == 'model_run' and event.get('ph') == 'X':
                require(type(event.get('pid')) is int and type(event.get('tid')) is int, 'ORT run lacks process/thread identity')
                pids.add(event['pid']); tids.add(event['tid'])
                require(math.isfinite(event['ts'] + event['dur']), 'Nonfinite ORT interval end')
    require(len(pids) == len(tids) == 1, 'Mixed process or caller-thread identity in serial lifetime traces')
    return dict(processId=next(iter(pids)), callerThreadId=next(iter(tids)))


def verify_collector(root, name, collector, source, bindings, provenance, plan, manifest):
    directory = root/name
    receipt = strict_json(safe_file(directory, 'receipt.json'))
    readiness = name == 'readiness'
    require(receipt.get('schema') == 'lightforge.game-session-reuse-experiment.v1'
            and all(receipt.get(f) is False for f in (*FLAGS, 'measured', 'wholeSongSpeedupProven', 'fullVocalStageSpeedupProven', 'androidSpeedupProven'))
            and receipt.get('hostOnly') is True and receipt.get('appLifecycleEquivalent') is False,
            'Collector schema/scope/approval differs')
    require(receipt.get('variants') == ['cpu_all'] and receipt.get('lifecycleArms') == ['default', 'reuse']
            and receipt.get('modes') == ['plain', 'captured', 'profiled']
            and receipt.get('gpuQualificationIncluded') is False and receipt.get('gpuInventory') is None
            and receipt.get('cudaOptions') is None and 'gpuNativeLibraries' not in receipt,
            'CPU-only experiment claimed or included unexpected GPU scope')
    source_hashes = {n: sha(source/n) for n in collector.SOURCE_BINDINGS}
    require(receipt.get('sourceHashes') == source_hashes
            and receipt.get('dependencyHashes') == {n: p['sha256'] for n, p in bindings['dependencies'].items()}
            and receipt.get('modelManifestSha256') == MANIFEST_SHA
            and receipt.get('modelHashes') == {n: p['sha256'] for n, p in manifest['files'].items()}, 'Collector immutable pins differ')
    require(receipt.get('inputProvenance') == provenance and receipt.get('inputProvenanceSha256') == sha(root/'input-provenance.json')
            and receipt.get('passagePlan') == plan and receipt.get('inputsRecheckedAfterQualification') is True,
            'Collector source plan or final input recheck differs')
    require(receipt.get('executionIdentity') == {'cpu_all': collector.baseline.execution_identity('cpu_all')}
            and receipt.get('requestedGraphProviders') == {'cpu_all': collector.game.requested_graph_providers('cpu_all', True)}
            and receipt.get('cublasWorkspaceConfig') == ':4096:8' and receipt.get('nvidiaTf32Override') == '0',
            'Provider configuration differs')
    artifacts = receipt.get('artifactHashes')
    require(isinstance(artifacts, dict) and artifacts, 'Missing artifact freeze')
    actual = tree_inventory(directory)
    require(set(artifacts) == set(actual)-{'receipt.json'}, 'Unbound or missing collector artifact')
    require(all(artifacts[n] == actual[n]['sha256'] for n in artifacts), 'Collector artifact changed')
    matrix = [('cpu_all', arm, mode) for arm in ('default', 'reuse') for mode in ('plain', 'captured', 'profiled')]
    require(set(receipt.get('generatedSources', {})) == {'_'.join(k) for k in matrix}, 'Generated snapshot matrix differs')
    for key in matrix:
        verify_snapshot(directory, key, collector, plan, provenance, receipt['generatedSources']['_'.join(key)], readiness)
    probes = receipt.get('runtimeProbes')
    require(isinstance(probes, list) and len(probes) == 1 and probes[0].get('runtimeVersion') == '1.25.1'
            and probes[0].get('cudaRequested') is False and probes[0].get('cudaKernelExecutionProven') is False,
            'CPU runtime probe differs')
    probe_log = safe_file(directory, 'cpu_all-runtime-probe/probe.log').read_text()
    require(probe_log.strip() == probes[0]['output'] and probe_log.splitlines()[0] == '1.25.1'
            and 'CPU' in probe_log and 'CUDA' not in probe_log, 'CPU runtime probe output differs')
    if readiness:
        require(receipt.get('status') == 'PREFLIGHT_READY' and receipt.get('inferenceExecuted') is False
                and receipt.get('readinessSnapshotCount') == 6 and receipt.get('runs') == [], 'Readiness claimed unexpected execution')
        return dict(status=receipt['status'], artifactCount=len(artifacts), compiledSnapshots=6, inferenceExecuted=False)
    require([(r.get('variant'), r.get('lifecycleArm'), r.get('mode')) for r in receipt.get('runs', [])] == matrix,
            'Missing/reordered/duplicate within-provider run')
    outputs, traces_report = {}, {}
    for key, row in zip(matrix, receipt['runs']):
        variant, arm, mode = key; label = '_'.join(key)
        output = directory/label/'output'
        run = collector.validate_run(output, mode, arm, provenance, plan, manifest)
        require(row.get('receipt') == label+'/output/receipt.json' and row.get('receiptSha256') == sha(output/'receipt.json')
                and row.get('timingEligible') is False and row.get('wallNanos') == run['wallNanos']
                and row.get('passageCount') == 6 and type(row.get('processWallIncludingStartupAndInspectionNanos')) is int
                and row['processWallIncludingStartupAndInspectionNanos'] >= run['wallNanos'], 'Run receipt binding differs')
        outputs[(arm, mode)] = output
        if mode == 'profiled':
            trace_dir = directory/(label+'_lifetime_traces')
            summary = collector.summarize_session_traces(trace_dir, output/'trace-markers.json', arm, variant, provenance, plan)
            require(summary == receipt['providerTraces'].get(variant+'_'+arm)
                    and summary['modelRuns'] == 72 and summary['sessionCount'] == (30 if arm == 'default' else 5),
                    'Recomputed persistent/default trace binding differs')
            identity = validate_trace_process_identity(trace_dir)
            traces_report[arm] = dict(sessionCount=summary['sessionCount'], modelRuns=72,
                markersSha256=summary['markersSha256'], placement=summary['placement'], **identity)
    require(set(receipt['providerTraces']) == {'cpu_all_default', 'cpu_all_reuse'}, 'Extra trace summary')
    observers, comparisons = [], []
    for arm in ('default', 'reuse'):
        for row in plan:
            paths = {m: outputs[(arm, m)]/f"passage-{row['index']:03d}" for m in ('plain', 'captured', 'profiled')}
            plain, capture = strict_json(paths['plain']/'receipt.json'), strict_json(paths['captured']/'receipt.json')
            comparison = collector.comparator.compare(paths['captured'], paths['profiled'])
            observers.extend([
                dict(variant='cpu_all', lifecycleArm=arm, passageIndex=row['index'], kind='plain-vs-capture',
                     rawTensorsByteIdentical=None, unroundedNotesIdentical=plain['notes'] == capture['notes']),
                dict(variant='cpu_all', lifecycleArm=arm, passageIndex=row['index'], kind='capture-vs-profile',
                     rawTensorsByteIdentical=comparison['exactParity'], unroundedNotesIdentical=comparison['unroundedNotesIdentical'], rawComparison=comparison)])
    for row in plan:
        comparison = collector.comparator.compare(*(outputs[(a, 'captured')]/f"passage-{row['index']:03d}" for a in ('default', 'reuse')))
        comparisons.append(dict(variant='cpu_all', passageIndex=row['index'], reference='default', candidate='reuse',
                                qualityApproved=False, tolerance=None, **comparison))
    require(observers == receipt.get('observerComparisons') and comparisons == receipt.get('withinProviderComparisons'),
            'Independently recomputed observer/default-reuse comparisons differ')
    observer_ok = all(r['unroundedNotesIdentical'] and r['rawTensorsByteIdentical'] is not False for r in observers)
    parity = all(r['exactParity'] and r['unroundedNotesIdentical'] for r in comparisons)
    expected_status = 'OBSERVER_COMPARISON_INVALID' if not observer_ok else ('COMPLETE_DIAGNOSTIC' if parity else 'WITHIN_PROVIDER_EQUIVALENCE_UNPROVEN')
    require(receipt.get('status') == expected_status, 'Recorded diagnostic gate differs from raw outputs')
    if observer_ok:
        require(receipt.get('observerComparisonsPassed') is True and receipt.get('withinProviderRawAndUnroundedParityProven') is parity,
                'Parity flags differ from independently recomputed evidence')
    return dict(status=expected_status, artifactCount=len(artifacts), completedRuns=6, sourcePassagesPerRun=6,
                observerComparisons=24, observerComparisonsPassed=observer_ok,
                withinProviderComparisons=comparisons, withinProviderParityProven=parity, traces=traces_report)


def verify(args, root):
    require(re.fullmatch('[a-f0-9]{40}', args.source_commit), 'Use an exact 40-character source commit')
    require(args.variants == ['cpu_all'], 'This verifier currently qualifies CPU-only evidence; CUDA library verification is not implemented')
    tree = subprocess.check_output(['git', '-C', str(args.repo), 'rev-parse', args.source_commit+'^{tree}'], text=True).strip()
    if args.source_tree:
        require(tree == args.source_tree, 'Explicit expected source tree differs')
    before = tree_inventory(root)
    inventory = verify_archive_inventory(root, before, args.source_commit, tree, args.zip is not None)
    source, source_inventory = verify_sources(root, args.repo, args.source_commit)
    bindings, pcm, provenance, plan, manifest = verify_inputs_before_import(root, source, args.repo, args.source_commit, tree)
    collector = pinned_module(source)
    require(set(collector.SOURCE_BINDINGS) <= set(source_inventory), 'Missing transitive collector source binding')
    actual_provenance, actual_plan = collector.baseline.validate_input(pcm, root/'input-provenance.json')
    require((actual_provenance, actual_plan) == (provenance, plan), 'Pinned collector and independent passage plans differ')
    driver = strict_json(safe_file(root, 'driver-receipt.json'))
    require(driver.get('schema') == 'lightforge.game-session-reuse-driver.v1'
            and driver.get('executionSourceCommit') == args.source_commit and driver.get('executionSourceTree') == tree
            and driver.get('variants') == ['cpu_all'] and driver.get('cudaExecuted') is False
            and all(driver.get(f) is False for f in FLAGS), 'Driver source/scope binding differs')
    check_pin(root/'host-preparation-receipt.json', driver['hostPreparationReceipt'])
    stages = {name: verify_collector(root, name, collector, source, bindings, provenance, plan, manifest)
              for name in ('readiness', 'qualification')}
    for name in stages:
        require(driver.get(name+'ExitCode') == 0, 'Driver stage exit differs')
        check_pin(safe_file(root, name+'.log'), driver['stageLogs'][name])
    require(driver.get('status') == 'COMPLETE_DIAGNOSTIC' and driver.get('allBoundInputsRechecked') is True
            and driver.get('completedJvmRuns') == 6 and driver.get('qualificationStatus') == stages['qualification']['status'],
            'Driver completion differs from qualified evidence')
    check_pin(root/'qualification/receipt.json', driver['qualificationReceipt'])
    require(before == tree_inventory(root), 'Evidence changed during independent verification')
    return dict(schema='lightforge.game-session-reuse-independent-audit.v1', verificationPassed=True,
                verificationMeaning='Integrity and diagnostic within-provider gates recomputed; no timing, general quality, GPU, or Android approval.',
                sourceCommit=args.source_commit, sourceTree=tree, archiveInventory=inventory,
                completeFileCount=len(before), immutableSourceFiles=len(source_inventory), cpuExecuted=True, cudaExecuted=False,
                modelBytesIncluded=False, runtimeBytesIncluded=False, externalModelRuntimeFinalRehashAttestedByFrozenDriver=True,
                stages=stages, measured=False, benchmarkTimingAdmitted=False, qualityApproved=False,
                target75Proven=False, androidLifecycleQualified=False, releaseAuthorized=False,
                limitations=['The external model, JDK, and runtime binaries are not in this evidence archive; their pinned bindings and frozen-driver final rehash attestations are checked.',
                             'The complete installed JDK file map is a frozen-driver pre/post attestation matched to the pinned preparation archive and original three preparation file pins; the JDK archive is not reconstructed by this verifier.',
                             'Java/class/log/trace artifacts are byte-bound; this verification does not rerun compilation, Java, native destructors, inference, or any timing experiment.',
                             'CPU default/reuse parity does not qualify CUDA or establish the 75% end-to-end target.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--run-directory', type=Path)
    inputs.add_argument('--zip', type=Path)
    parser.add_argument('--expected-size', type=int)
    parser.add_argument('--expected-sha256')
    parser.add_argument('--max-uncompressed-bytes', type=int, default=2*1024**3)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--source-tree')
    parser.add_argument('--variants', nargs='+', choices=['cpu_all', 'cuda_basic'], required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.repo = args.repo.resolve(); args.output_dir = args.output_dir.resolve()
    require(not args.output_dir.exists(), 'Use a new verification output directory')
    if args.run_directory:
        args.run_directory = args.run_directory.absolute()
        require(not args.output_dir.is_relative_to(args.run_directory.resolve()), 'Verification output cannot be inside evidence')
    args.output_dir.mkdir(parents=True)
    try:
        root, archive = extract_zip(args) if args.zip else (args.run_directory, None)
        report = verify(args, root)
        report.update(archive=archive, verifierSha256=sha(Path(__file__)))
        (args.output_dir/'verification.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
        print(json.dumps({k: report[k] for k in ('verificationPassed', 'cpuExecuted', 'cudaExecuted', 'qualityApproved', 'target75Proven')}))
    except Exception as error:
        (args.output_dir/'verification-failure.json').write_text(json.dumps(dict(verificationPassed=False, error=str(error)), indent=2)+'\n')
        raise


if __name__ == '__main__':
    main()
