#!/usr/bin/env python3
"""Audit completed public CPU Deux evidence and replay its consumer, without model inference.

The caller supplies an immutable expected execution commit. Absent model/runtime
binaries remain explicitly attested identities, not independently re-executed assets.
"""
import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess
import sys
import types
import zipfile

sys.dont_write_bytecode = True
COLLECTOR = 'tools/benchmark_deux_source_cuda.py'
REPLAY = 'tools/deux_benchmark/replay_source.cjs'
DRIVER = 'research/performance/2026-09-25/deux-full-source/run_local.py'
EXPORTER = 'research/performance/2026-09-25/deux-full-source/export_evidence.py'
BASELINE_SOURCE = 'efd95eb04068a7470490e34d729020f81efcab56'
MANIFEST_SHA = '6aebf45e6e7f6fa974f14fe47a252fc01f48da4815f40a1fdf10641a432529a9'
WAV_PIN = dict(bytes=11289644, sha256='33f07d502ba19832b62b97d8fb4a11354e81310264bd885d7a06438228773650')
APP_FILES = (
    'android/src/com/cyberbasslord/lightforge/NativeDeux.java',
    'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java',
    'android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java', 'android/native-runtime.json',
    'web/analysis/models/deux/manifest.json', 'web/analysis/models/features.json',
    'web/analysis/separator-deux.js', 'web/analysis/dsp.js', 'web/analysis/wav-reader.js',
    'web/analysis/stem-cache.js', 'web/analysis/work-store.js')
FLAGS = ('qualityApproved', 'target75Proven', 'benchmarkTimingAdmitted', 'releaseAuthorized')
MAX_MEMBER = 512 * 1024 ** 2
MAX_TOTAL = 8 * 1024 ** 3
MAX_FILES = 4097


def require(value, message):
    if not value:
        raise ValueError(message)


def pin(path):
    require(path.is_file() and not path.is_symlink(), 'Missing or linked regular file: ' + str(path))
    with path.open('rb') as stream:
        return dict(bytes=path.stat().st_size, sha256=hashlib.file_digest(stream, 'sha256').hexdigest())


def validate_pin(value):
    require(isinstance(value, dict) and set(value) == {'bytes', 'sha256'} and
            type(value['bytes']) is int and value['bytes'] >= 0 and
            isinstance(value['sha256'], str) and re.fullmatch('[a-f0-9]{64}', value['sha256']), 'Invalid file identity.')


def check_pin(path, value):
    validate_pin(value)
    require(pin(path) == value, 'File identity differs: ' + str(path))


def safe_relative(name):
    require(isinstance(name, str) and name and '\\' not in name and '\x00' not in name and
            not re.match(r'^[A-Za-z]:', name), 'Invalid relative path.')
    path = PurePosixPath(name)
    require(not path.is_absolute() and all(part not in ('', '.', '..') for part in name.split('/')),
            'Unsafe relative path: ' + name)
    return path


def safe_file(root, name):
    path = root
    for part in safe_relative(name).parts:
        path /= part
        require(not path.is_symlink(), 'Linked evidence path: ' + name)
    require(path.is_file(), 'Missing evidence file: ' + name)
    return path


def strict_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def floating(value):
        number = float(value)
        require(math.isfinite(number), 'Nonfinite JSON number.')
        return number
    def invalid(value):
        raise ValueError('Nonfinite JSON constant: ' + value)
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= MAX_MEMBER,
            'Missing, linked or oversized JSON.')
    return json.loads(path.read_text(), object_pairs_hook=pairs, parse_float=floating, parse_constant=invalid)


def inventory(root):
    require(root.is_dir() and not root.is_symlink(), 'Expected regular evidence directory.')
    result, total = {}, 0
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink() and (path.is_dir() or path.is_file()), 'Linked or special evidence entry.')
        if path.is_file():
            size = path.stat().st_size
            require(size <= MAX_MEMBER, 'Oversized evidence member.')
            total += size
            require(total <= MAX_TOTAL and len(result) < MAX_FILES, 'Evidence inventory exceeds bounds.')
            result[path.relative_to(root).as_posix()] = pin(path)
    return result


def git_blob(repo, commit, name):
    safe_relative(name)
    return subprocess.check_output(['git', '-C', str(repo), 'show', commit + ':' + name], timeout=30)


def extract_zip(path, expected, output):
    check_pin(path, expected)
    output.mkdir()
    with zipfile.ZipFile(path) as archive:
        rows = archive.infolist()
        require(0 < len(rows) <= MAX_FILES, 'Invalid archive member count.')
        seen, total = set(), 0
        for row in rows:
            require(not row.is_dir(), 'Exporter archives contain regular files only.')
            safe_relative(row.filename)
            require(row.filename not in seen, 'Duplicate archive member.')
            seen.add(row.filename)
            kind = stat.S_IFMT((row.external_attr >> 16) & 0xffff)
            require(kind in (0, stat.S_IFREG) and not row.flag_bits & 1 and
                    0 <= row.file_size <= MAX_MEMBER, 'Special, encrypted or oversized archive member.')
            total += row.file_size
        require(total <= MAX_TOTAL, 'Archive exceeds expansion bound.')
        roots = {PurePosixPath(row.filename).parts[0] for row in rows}
        require(len(roots) == 1 and all(len(PurePosixPath(row.filename).parts) > 1 for row in rows),
                'Archive must have one regular evidence root.')
        for row in rows:
            target = output.joinpath(*PurePosixPath(row.filename).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(row) as source, target.open('xb') as sink:
                shutil.copyfileobj(source, sink, 1024 ** 2)
            require(target.stat().st_size == row.file_size, 'Extracted member length differs.')
    check_pin(path, expected)
    return output / next(iter(roots))


def import_frozen(source, relative):
    """Compile only authenticated source bytes; never trust archived pyc caches."""
    python = {path.resolve(): path.read_bytes() for path in source.rglob('*.py')}
    original_spec = importlib.util.spec_from_file_location
    class Loader(importlib.machinery.SourceFileLoader):
        def get_code(self, fullname):
            return compile(python[Path(self.path).resolve()], self.path, 'exec', dont_inherit=True)
    def source_spec(name, location=None, *, loader=None, submodule_search_locations=None):
        path = Path(location).resolve()
        require(path in python and loader is None and submodule_search_locations is None,
                'Unverified dynamic Python import.')
        return original_spec(name, str(path), loader=Loader(name, str(path)))
    importlib.util.spec_from_file_location = source_spec
    try:
        spec = source_spec('verified_deux_' + Path(relative).stem, source / relative)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        importlib.util.spec_from_file_location = original_spec
    return module


def verify_sources(root, repo, commit):
    source = root / 'execution-source'
    files = inventory(source)
    require(COLLECTOR in files and DRIVER in files and REPLAY in files and all(name in files for name in APP_FILES),
            'Missing required execution source.')
    for name in files:
        require(safe_file(source, name).read_bytes() == git_blob(repo, commit, name), 'Source differs from expected Git commit: ' + name)
    for name in APP_FILES:
        require(git_blob(repo, commit, name) == git_blob(repo, BASELINE_SOURCE, name),
                'Application differs from qualified research baseline: ' + name)
    require(files['web/analysis/models/deux/manifest.json']['sha256'] == MANIFEST_SHA, 'Original model manifest changed.')
    return source, files


def verify_bindings(root, source, files, commit, tree):
    value = strict_json(safe_file(root, 'runtime-input-bindings.json'))
    require(value['schema'] == 'lightforge.deux-source-local-bindings.v1' and value['sourceCommit'] == commit and
            value['sourceTree'] == tree and value['variants'] == ['cpu_all'] and value['cudaExecuted'] is False and
            value['qualityApproved'] is False and value['target75Proven'] is False and value['sources'] == files,
            'Source-bound runtime inventory differs.')
    manifest_path = safe_file(source, 'web/analysis/models/deux/manifest.json')
    manifest = strict_json(manifest_path)
    require(len(manifest['files']) == 27 and value['models'] == {'manifest.json': pin(manifest_path), **manifest['files']},
            'Original 27-graph identities differ.')
    runtime = strict_json(safe_file(source, 'android/native-runtime.json'))
    expected_dependencies = {
        'test-json.jar': dict(bytes=90031, sha256='c243f45f9590c12694a4142ed3f07fc70dfb71e4daebd05ae234bf92a2da92a6'),
        'android-sdk/platforms/android-35/android.jar': dict(bytes=27092450, sha256='4566663c3876e022b4fa4ced8c8697c4ab1688267f090114fd92d027b32e619b'),
        'onnx/' + runtime['host']['name']: {key: runtime['host'][key] for key in ('bytes', 'sha256')},
    }
    require(runtime['version'] == '1.25.1' and value['dependencies'] == expected_dependencies, 'Original CPU runtime/SDK identities differ.')
    require(value['publicWav'] == WAV_PIN, 'Original public WAV identity differs.')
    check_pin(safe_file(root, 'glass-castle.wav'), WAV_PIN)
    check_pin(safe_file(root, 'input-provenance.json'), value['inputProvenance'])
    require(set(value['preparation']) == {'host-preparation-receipt.json', 'deux-preparation-receipt.json'}, 'Preparation inventory differs.')
    for name, expected in value['preparation'].items():
        check_pin(safe_file(root, name), expected)
    host = strict_json(safe_file(root, 'host-preparation-receipt.json'))
    deux = strict_json(safe_file(root, 'deux-preparation-receipt.json'))
    require(host['schema'] == 'lightforge.host-game-research-preparation.v1' and host['installedJdkMatchesPinnedArchive'] is True and
            host['jdkFiles'] == value['jdk'] and host['jdkSymlinks'] == value['jdkSymlinks'], 'JDK installation/preparation binding differs.')
    for name, expected in value['jdk'].items():
        safe_relative(name)
        validate_pin(expected)
    require(all(name in value['jdk'] for name in ('bin/java', 'bin/javac', 'bin/javap', 'lib/modules', 'lib/server/libjvm.so')),
            'Essential JDK files are absent.')
    for name, target in value['jdkSymlinks'].items():
        safe_relative(name)
        require(isinstance(target, str) and target and not PurePosixPath(target).is_absolute(), 'Invalid JDK link attestation.')
    require(value['jdkArchive'] == dict(bytes=193252603, sha256='3808d1d15e3ec6bd5b84057fb5d84c33d8a1536a258146bcea2e603fc726e08e'),
            'Original JDK archive pin differs.')
    require(deux['schema'] == 'lightforge.host-deux-research-preparation.v1' and
            deux['hostPreparationReceipt'] == value['preparation']['host-preparation-receipt.json'] and
            deux['modelManifest'] == value['models']['manifest.json'] and deux['models'] == manifest['files'] and
            deux['publicApk'] == dict(bytes=1205116958, sha256='af83bf403875c55d42fd695d43f6e193114899c1324fbaeaffd6c02d299d882f'),
            'Original APK/graph preparation differs.')
    for preparation, name in ((host, 'research/performance/2026-09-25/session-reuse/restore_host.py'),
                              (deux, 'research/performance/2026-09-25/deux-full-source/restore_deux_assets.py')):
        require(preparation['restoreScript'] == files[name], 'Preparation script differs from frozen source.')
        require(preparation['modelInferenceExecuted'] is False and preparation['cudaExecuted'] is False and
                all(preparation[key] is False for key in FLAGS), 'Unexpected preparation inference/approval.')
    validate_pin({key: value['node'][key] for key in ('bytes', 'sha256')})
    validate_pin(value['python'])
    return value, manifest


def verify_snapshots(directory, receipt, source, collector):
    actual = {name: value['sha256'] for name, value in inventory(directory / 'snapshots').items()
              if Path(name).suffix in ('.java', '.class')}
    actual = {'snapshots/' + name: value for name, value in actual.items()}
    require(receipt['compiledSnapshotHashes'] == actual, 'Compiled Java/class inventory differs.')
    original = (source / 'android/src/com/cyberbasslord/lightforge/NativeDeux.java').read_text()
    for mode in ('plain', 'profiled'):
        snapshot = directory / 'snapshots' / ('cpu_all_' + mode)
        observed = safe_file(snapshot, 'NativeDeux.java').read_text()
        traces = None
        if mode == 'profiled':
            matches = re.findall(r'options\.enableProfiling\(new File\(("(?:[^"\\]|\\.)*"),name\)\.getAbsolutePath\(\)\);', observed)
            matches += re.findall(r'options\.enableProfiling\(DeuxSourceTrace\.prefix\(name,("(?:[^"\\]|\\.)*")\)\);', observed)
            require(len(matches) == 1, 'Missing or ambiguous generated trace destination.')
            traces = Path(json.loads(matches[0]))
            require(traces.is_absolute() and traces.name == 'cpu_all_profiled_active_traces' and
                    traces.parent.name == directory.name, 'Unexpected generated trace destination.')
        require(observed == collector.source_snapshot(original, 'cpu_all', mode, traces), 'Generated NativeDeux differs from frozen generator.')
        for filename, relative in (
            ('DeuxSourceRunner.java', 'tools/deux_benchmark/DeuxSourceRunner.java'),
            ('NativeDeuxTransform.java', 'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java'),
            ('NativeInferenceProfile.java', 'android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java')):
            require(safe_file(snapshot, filename).read_bytes() == safe_file(source, relative).read_bytes(), 'Copied Java source differs.')
        if 'tools/deux_benchmark/DeuxSourceTrace.java' in collector.SOURCE_BINDINGS:
            require(safe_file(snapshot, 'DeuxSourceTrace.java').read_bytes() ==
                    safe_file(source, 'tools/deux_benchmark/DeuxSourceTrace.java').read_bytes(), 'Copied trace-ownership helper differs.')
        stub = 'package com.cyberbasslord.lightforge; public final class AppDiagnostics {' \
               'public static void log(android.content.Context c,String l,String s,String m){}' \
               'public static boolean flush(long timeout){return true;}}\n'
        require(safe_file(snapshot, 'AppDiagnostics.java').read_text() == stub, 'Research diagnostics stub differs.')
        classes = [name for name in actual if name.startswith('snapshots/cpu_all_' + mode + '/classes/')]
        require(len(classes) >= 20, 'Incomplete compiled helper class inventory.')
    return len(actual)


def verify_no_active_traces(directory):
    # ZIPs preserve reviewed regular files, not empty directories. Both the
    # original present-and-empty directory and its absence after extraction are valid.
    require(not directory.is_symlink(), 'Linked active trace directory.')
    if directory.exists():
        require(directory.is_dir() and not list(directory.iterdir()), 'Completed run left unmatched active traces.')


def verify_collection(root, source, bindings, manifest, collector):
    provenance, plan = collector.validate_input(safe_file(root, 'glass-castle.wav'), safe_file(root, 'input-provenance.json'))
    require(provenance['sourceCommit'] == bindings['sourceCommit'] and provenance['sourceTree'] == bindings['sourceTree'] and
            provenance['sourceKind'] == 'public-mixture' and len(plan) == 12, 'Complete public input binding differs.')
    receipts = {}
    native_runtime = strict_json(source / 'android/native-runtime.json')
    java_names = ('bin/java', 'bin/javac', 'bin/javap', 'lib/modules', 'lib/server/libjvm.so',
                  'lib/libjava.so', 'lib/libjli.so', 'release', 'conf/security/java.security')
    for stage in ('readiness', 'qualification'):
        directory = root / stage
        receipt = strict_json(safe_file(directory, 'receipt.json'))
        receipts[stage] = receipt
        require(receipt['schema'] == 'lightforge.deux-source-cuda-experiment.v1' and
                receipt['variants'] == ['cpu_all'] and receipt['modes'] == ['plain', 'profiled'] and
                receipt['inputProvenance'] == provenance and receipt['inputProvenanceSha256'] == bindings['inputProvenance']['sha256'] and
                receipt['passagePlan'] == plan and receipt['audioSha256'] == WAV_PIN['sha256'] and receipt['audioFrames'] == 64 * 44100,
                'Collection input or scope differs.')
        expected_sources = {name: bindings['sources'][name]['sha256'] for name in collector.SOURCE_BINDINGS}
        require(receipt['sourceHashes'] == expected_sources and receipt['modelManifestSha256'] == MANIFEST_SHA and
                receipt['modelHashes'] == {name: value['sha256'] for name, value in manifest['files'].items()}, 'Collector source/model identities differ.')
        require(receipt['dependencyHashes'] == {Path(name).name: value['sha256'] for name, value in bindings['dependencies'].items()} and
                receipt['javaIdentity']['files'] == {name: bindings['jdk'][name] for name in java_names} and
                set(receipt['javaIdentity']['executables']) == {'java', 'javac', 'javap'} and
                all(re.search(r'(?:version "|javac |^)17\.', value) for value in receipt['javaIdentity']['executables'].values()),
                'Collector runtime identity differs.')
        require(receipt['runtimeVersion'] == '1.25.1' and receipt['executionIdentity'] == {'cpu_all': collector.execution_identity('cpu_all')} and
                receipt['cpuRuntime'] == native_runtime['host'] and
                receipt['gpuRuntime'] is None and receipt['cudaOptions'] is None and receipt['requestedCudaLogicalDevice'] is None and
                receipt['cublasWorkspaceConfig'] == ':4096:8' and receipt['nvidiaTf32Override'] == '0' and
                receipt['inputsRecheckedAfterQualification'] is True and all(receipt[key] is False for key in FLAGS),
                'Collector runtime/provider scope or approval differs.')
        probes = receipt['runtimeProbes']
        require(len(probes) == 1 and probes[0]['runtimeVersion'] == '1.25.1' and
                probes[0]['cudaRequested'] is False and probes[0]['cudaKernelExecutionProven'] is False and
                probes[0]['output'] == safe_file(directory, 'cpu_all-runtime-probe/probe.log').read_text().strip() and
                probes[0]['output'].splitlines() == ['1.25.1', '[CPU]'], 'Recorded CPU runtime probe differs.')
        require(strict_json(safe_file(directory, 'source-plan.json')) == dict(audioFrames=64 * 44100,
                audioSha256=WAV_PIN['sha256'], passagePlan=plan), 'Persisted source plan differs.')
        verify_snapshots(directory, receipt, source, collector)
    ready, final = receipts['readiness'], receipts['qualification']
    require(ready['status'] == 'PREFLIGHT_READY' and ready['inferenceExecuted'] is False and
            ready['readinessSnapshotCount'] == 2 and ready['runs'] == [], 'Incomplete CPU preflight.')
    outputs = {'cpu_all': {}}
    for mode in ('plain', 'profiled'):
        label = 'cpu_all_' + mode
        directory = root / 'qualification' / label
        actual_run = collector.validate_run(directory, mode, provenance, plan, manifest)
        row = next(item for item in final['runs'] if item['label'] == label)
        require(row['receipt'] == label + '/receipt.json' and row['outputDirectory'] == label and
                row['receiptSha256'] == pin(directory / 'receipt.json')['sha256'] and row['passages'] == actual_run['passages'] and
                row['wallNanos'] == actual_run['wallNanos'] and row['observation'] == mode and row['variant'] == 'cpu_all' and
                row['provider'] == 'CPUExecutionProvider' and row['timingEligible'] is False,
                'Nested run receipt or diagnostic wall binding differs.')
        outputs['cpu_all'][mode] = directory
    observers = collector.compare_observers(outputs, plan, ('cpu_all',))
    collector.validate_observers(observers, plan, ('cpu_all',))
    require(final['observerComparisons'] == observers, 'Recorded observer comparisons differ from raw Float32 evidence.')
    traces, placements = [], []
    for row in plan:
        summary = collector.profiler.summarize_traces(outputs['cpu_all']['profiled'] / f"passage-{row['index']:03d}" / 'traces')
        traces.append(dict(passageIndex=row['index'], **summary))
        placements.append(dict(passageIndex=row['index'], **collector.accel.validate_placement(summary, 'cpu_all')))
    require(final['providerTraces'] == {'cpu_all': traces} and final['placement'] == {'cpu_all': placements},
            'Recorded 27-graph/335-call trace placement differs from raw traces.')
    verify_no_active_traces(root / 'qualification/cpu_all_profiled_active_traces')
    all_files = inventory(root / 'qualification')
    expected_artifacts = {name: value['sha256'] for name, value in all_files.items() if
        name == 'source-plan.json' or name.startswith(('cpu_all_plain/', 'cpu_all_profiled/')) or
        name.startswith('snapshots/') and Path(name).suffix in ('.java', '.class')}
    require(final['artifactHashes'] == expected_artifacts, 'Completed artifact inventory differs from retained files.')
    return final, dict(completedPredictions=24, exactObserverPassages=12, profiledGraphSessions=12 * 27,
                       profiledGraphCalls=sum(row['modelRuns'] for row in traces), cpuPlacementRecomputed=True)


def run_replay(root, source, output):
    require(not os.environ.get('NODE_OPTIONS') and not os.environ.get('NODE_PATH'),
            'Unset injected Node options/module paths before independent replay.')
    node_name = shutil.which('node')
    require(node_name is not None, 'Node is required for independent production consumer replay.')
    node = Path(node_name).resolve()
    observed = dict(version=subprocess.check_output([node, '--version'], text=True, timeout=30).strip(), **pin(node))
    log = output / 'consumer-replay.log'
    with log.open('x') as stream:
        process = subprocess.Popen([str(node), str(source / REPLAY), str(root / 'qualification'),
            str(root / 'glass-castle.wav'), str(output / 'consumer-replayed')], stdout=stream,
            stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = process.wait(timeout=300)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    require(code == 0, 'Independent production replay failed; inspect its audit log.')
    original = strict_json(safe_file(root, 'consumer/receipt.json'))
    replayed = strict_json(safe_file(output, 'consumer-replayed/receipt.json'))
    # The producer uses a fixed research clock and relative evidence paths; no
    # receipt fields need to be discarded or normalized for exact comparison.
    require(replayed == original, 'Independent production consumer receipt differs.')
    for name, expected in original['outputFiles'].items():
        expected_pin = {key: expected[key] for key in ('bytes', 'sha256')}
        check_pin(safe_file(root / 'consumer', name), expected_pin)
        check_pin(safe_file(output / 'consumer-replayed', name), expected_pin)
    require(pin(node) == {key: observed[key] for key in ('bytes', 'sha256')}, 'Replay Node binary changed.')
    return original, observed


def audit(args, output):
    require(re.fullmatch('[a-f0-9]{40}', args.source_commit), 'Full expected execution commit is required.')
    tree = subprocess.check_output(['git', '-C', str(args.repo), 'rev-parse', args.source_commit + '^{tree}'], text=True, timeout=30).strip()
    archive_pin = None
    if args.zip:
        require(args.expected_size is not None and args.expected_sha256 is not None, 'ZIP requires independently expected size and SHA256.')
        archive_pin = dict(bytes=args.expected_size, sha256=args.expected_sha256)
        root = extract_zip(args.zip, archive_pin, output / 'extracted')
    else:
        require(not args.run_directory.is_symlink(), 'Linked run directory is not admitted.')
        root = args.run_directory.resolve()
    require(not output.resolve().is_relative_to(root.resolve()), 'Audit output must be outside evidence input.')
    driver_receipt = strict_json(safe_file(root, 'driver-receipt.json'))
    require(driver_receipt['schema'] == 'lightforge.deux-source-local-driver.v1' and driver_receipt['status'] == 'COMPLETE_DIAGNOSTIC' and
            driver_receipt['executionSourceCommit'] == args.source_commit and driver_receipt['executionSourceTree'] == tree and
            driver_receipt['variants'] == ['cpu_all'] and driver_receipt['cudaExecuted'] is False and
            driver_receipt['fullVocalStageExecuted'] is False and driver_receipt['allBoundInputsRechecked'] is True and
            driver_receipt['completedJvmRuns'] == 2 and driver_receipt['completedPredictions'] == 24 and
            driver_receipt['maximumWorkflowSeconds'] == 5400 and
            type(driver_receipt['elapsedDiagnosticSeconds']) in (int, float) and
            0 < driver_receipt['elapsedDiagnosticSeconds'] <= 5400 and
            all(driver_receipt[key] is False for key in FLAGS), 'Incomplete, source-mismatched or overclaimed driver receipt.')
    actual = inventory(root)
    source, files = verify_sources(root, args.repo, args.source_commit)
    bindings, manifest = verify_bindings(root, source, files, args.source_commit, tree)
    # Import only exact Git-authenticated bytes, after source and input validation.
    collector = import_frozen(source, COLLECTOR)
    driver_module = import_frozen(source, DRIVER)
    exporter = types.ModuleType('verified_deux_export_boundary')
    exporter.__file__ = str(args.repo / EXPORTER)
    exec(compile(git_blob(args.repo, args.source_commit, EXPORTER), exporter.__file__, 'exec'), exporter.__dict__)
    for name in actual:
        require(name == 'archive-manifest.json' or exporter.allowed(Path(name), files), 'Unreviewed evidence member: ' + name)
    archive_manifest = root / 'archive-manifest.json'
    if archive_manifest.exists():
        archived = strict_json(archive_manifest)
        require(archived['schema'] == 'lightforge.deux-source-local-archive.v1' and archived['runDirectory'] == root.name and
                archived['executionSourceCommit'] == args.source_commit and archived['executionSourceTree'] == tree and
                archived['status'] == 'COMPLETE_DIAGNOSTIC' and archived['publicFixtureOnly'] is True and
                archived['cudaExecuted'] is False and archived['fullVocalStageExecuted'] is False and
                all(archived[key] is False for key in FLAGS), 'Archive scope/source claims differ.')
        rows = archived['files']
        require(len({row['path'] for row in rows}) == len(rows), 'Duplicate archive inventory entry.')
        require({row['path']: {key: row[key] for key in ('bytes', 'sha256')} for row in rows} ==
                {name: value for name, value in actual.items() if name != 'archive-manifest.json'}, 'Archive inventory is not exact.')
    else:
        require(args.zip is None, 'ZIP has no complete archive inventory.')
    for stage in ('readiness', 'qualification', 'consumer'):
        require(driver_receipt[stage + 'ExitCode'] == 0, 'Recorded stage failed.')
        check_pin(safe_file(root, stage + '.log'), driver_receipt['stageLogs'][stage])
    check_pin(safe_file(root, 'qualification/receipt.json'), driver_receipt['qualificationReceipt'])
    check_pin(safe_file(root, 'consumer/receipt.json'), driver_receipt['consumerReceipt'])
    final, checks = verify_collection(root, source, bindings, manifest, collector)
    replay, node = run_replay(root, source, output)
    driver_module.validate_completion(final, replay)
    require(replay['experimentReceiptSha256'] == driver_receipt['qualificationReceipt']['sha256'] and
            replay['outputFiles'] == driver_receipt['outputFiles'], 'Driver consumer binding differs.')
    require(actual == inventory(root), 'Input evidence changed during independent verification.')
    return dict(schema='lightforge.deux-source-independent-verification.v1', status='VERIFIED_CPU_DIAGNOSTIC',
        executionSourceCommit=args.source_commit, executionSourceTree=tree, archive=archive_pin,
        evidenceFiles=len(actual), completeInventoryRechecked=True, **checks,
        productionReplayReceiptsExactlyEqual=True, replayReceiptFieldsIgnored=[],
        savedStemFilesReproduced=3, replayNode=node, modelInferenceExecuted=False,
        nativeCompiledClassesExecuted=False, modelAndRuntimeBinariesIncluded=False,
        modelAndRuntimeIdentityScope='Retained source-bound collector and archive-verified preparation attestations; '
            'model/runtime binaries are not included or independently executed by this auditor.',
        applicationBaselineCommit=BASELINE_SOURCE,
        applicationSourceScope='Matches qualified research baseline, including previously enabled CPU arena and memory patterns; '
            'only model graphs and public WAV are claimed original to the v2.3.1 APK.',
        cudaExecuted=False, fullVocalStageExecuted=False, qualityApproved=False, target75Proven=False,
        benchmarkTimingAdmitted=False, androidIntegrationApproved=False, releaseAuthorized=False)


def main():
    def terminated(signum, frame):
        raise KeyboardInterrupt('Independent Deux auditor terminated')
    signal.signal(signal.SIGTERM, terminated)
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--run-directory', type=Path)
    mode.add_argument('--zip', type=Path)
    parser.add_argument('--expected-size', type=int)
    parser.add_argument('--expected-sha256')
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    require(not args.output_dir.exists() and not args.output_dir.is_symlink(), 'Use a fresh independent audit directory.')
    if args.run_directory:
        require(not args.output_dir.absolute().is_relative_to(args.run_directory.absolute()), 'Audit output must be outside run input.')
    args.output_dir.mkdir(parents=True)
    verifier_file = Path(__file__).resolve()
    verifier_pin = pin(verifier_file)
    try:
        result = audit(args, args.output_dir)
        require(pin(verifier_file) == verifier_pin, 'Independent verifier source changed during audit.')
        result.update(verifierSha256=verifier_pin['sha256'], verifierBytes=verifier_pin['bytes'],
                      verifierUnchangedDuringAudit=True)
    except BaseException as error:
        result = dict(schema='lightforge.deux-source-independent-verification.v1', status='REJECTED',
            failure=f'{type(error).__name__}: {error}', modelInferenceExecuted=False,
            verifierSha256=verifier_pin['sha256'], verifierBytes=verifier_pin['bytes'],
            verifierUnchangedDuringAudit=pin(verifier_file) == verifier_pin,
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
