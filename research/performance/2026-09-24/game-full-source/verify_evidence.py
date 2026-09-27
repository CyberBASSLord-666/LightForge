#!/usr/bin/env python3
"""Verify a frozen complete-source GAME diagnostic archive without inference.

The ZIP and repository are read only. Extracted files and reports go into a new
directory outside the repository. Partial/blocked evidence is retained and
reported as partial, never promoted to a completed diagnostic or quality gate.
Only source bytes checked against the fixed Git commit may be imported/executed.
"""
import argparse
import ast
import hashlib
import io
import importlib.machinery
import importlib.util
import json
import math
import os
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
SOURCE = '3797783e703738d28af1df9b722f5f4e886b99f2'
TREE = '47fa69218b35ff8e1644e123ee8170983a884f8b'
HARNESS_SHA = 'a75b75aecca793622f2eb8874fd1aef1ac133146b90387b3c36c276adc927959'
ORIGINAL = 'd9b42bb79145cfe81367fd70e2ca0ff7f4d52c12'
APK_SHA = 'af83bf403875c55d42fd695d43f6e193114899c1324fbaeaffd6c02d299d882f'
AUDIO_SHA = '33f07d502ba19832b62b97d8fb4a11354e81310264bd885d7a06438228773650'
MANIFEST_SHA = '51e172cfaa967d9e2518f01f508a64d49cd283d23ae8e8456af9c6e76eeb4f97'
FIRST14_SHA = 'a75b3b8d59c87d428e38e45db5f54ad8d2b1613fe79ee07c2595fecbf9215274'
FULL_PCM_SHA = '298f7a549c4bb8dfc53c47d1078cea842c5e818a3e7c82bf289bffcec0ba30c2'
WRAPPER_SOURCE = 'fb292cc9cf899a22e267bb149bfbfb87a8eee391'
WRAPPER_PATH = 'research/performance/2026-09-24/game-full-source/colab_run.py'
WRAPPER_SHA = 'a39b14d34833bbbde69ea96f076a0d6981f15f1f5682fdd84551011e49cfa36a'
NOTEBOOK_SOURCE = '3d525cd16ae7688777a2ca677db7fecbf76c4e9e'
NOTEBOOK_PATH = 'notebooks/LightForge_Colab_Kaggle_GAME_GPU_Qualification.ipynb'
NOTEBOOK_SHA = 'eb274157af3ea1e6d78c5803ffe3bccbbd2765683abed6d5618746c3e6555445'
FLAGS = ('measured', 'qualityApproved', 'benchmarkTimingAdmitted', 'target75Proven',
         'wholeSongSpeedupProven', 'fullVocalStageSpeedupProven', 'androidSpeedupProven', 'releaseAuthorized')
APP_FILES = ('android/src/com/cyberbasslord/lightforge/NativeGame.java', 'android/native-runtime.json',
             'web/analysis/game.js', 'web/analysis/wav-reader.js', 'web/analysis/models/game/manifest.json')
MATRIX = [(v, m) for v in ('cpu_all', 'cuda_basic') for m in ('plain', 'captured', 'profiled')]
SUCCESS = ('COMPLETE_DIAGNOSTIC', 'NUMERICAL_EQUIVALENCE_UNPROVEN')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def strict_json(path):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result

    def floating(value):
        result = float(value)
        require(math.isfinite(result), 'Nonfinite JSON number')
        return result

    def constant(value):
        raise ValueError('Nonfinite JSON constant: ' + value)

    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 512 * 1024**2,
            'Missing, linked or oversized JSON file: ' + str(path))
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs,
                      parse_float=floating, parse_constant=constant)


def safe_relative(value):
    require(isinstance(value, str) and value and '\\' not in value and '\x00' not in value,
            'Invalid relative path')
    item = PurePosixPath(value)
    require(not item.is_absolute() and not re.match(r'^[A-Za-z]:', value)
            and all(v not in ('', '.', '..') for v in value.split('/')), 'Unsafe relative path: ' + value)
    return item


def safe_file(root, relative):
    path = root.joinpath(*safe_relative(relative).parts)
    require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root.resolve()),
            'Missing or unsafe evidence file: ' + relative)
    return path


def checked(root, relative, pin):
    require(isinstance(pin, dict) and type(pin.get('bytes')) is int and pin['bytes'] >= 0
            and re.fullmatch('[a-f0-9]{64}', str(pin.get('sha256', ''))), 'Invalid file pin: ' + relative)
    path = safe_file(root, relative)
    require(path.stat().st_size == pin['bytes'] and sha(path) == pin['sha256'], 'File binding differs: ' + relative)
    return path


def blob(repo, name, commit=SOURCE):
    safe_relative(name)
    return subprocess.check_output(['git', '-C', str(repo), 'show', commit + ':' + name])


def extract_verified(args):
    require(args.zip.is_file() and not args.zip.is_symlink(), 'ZIP must be a regular file')
    require(args.zip.stat().st_size == args.expected_size and sha(args.zip) == args.expected_sha256,
            'ZIP size or SHA256 differs from required expected values')
    destination = args.output_dir / 'extracted'
    destination.mkdir()
    with zipfile.ZipFile(args.zip) as archive:
        members = archive.infolist()
        require(0 < len(members) <= 30000, 'Unexpected archive member count')
        seen, total = set(), 0
        for info in members:
            name = info.filename[:-1] if info.is_dir() else info.filename
            safe_relative(name)
            require(name not in seen, 'Duplicate ZIP member: ' + name)
            seen.add(name)
            kind = stat.S_IFMT((info.external_attr >> 16) & 0xffff)
            require(kind in (0, stat.S_IFDIR if info.is_dir() else stat.S_IFREG), 'Nonregular ZIP member: ' + name)
            require(not info.flag_bits & 1 and 0 <= info.file_size <= args.max_uncompressed_bytes,
                    'Encrypted or oversized ZIP member: ' + name)
            total += info.file_size
        require(total <= args.max_uncompressed_bytes, 'Archive exceeds uncompressed size limit')
        for info in members:
            target = destination.joinpath(*PurePosixPath(info.filename).parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as incoming, target.open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing, 1024**2)
            require(target.stat().st_size == info.file_size, 'Extracted member size mismatch')
            # Reading each entire ZipExtFile verifies its CRC, including zero-byte members.
    require(args.zip.stat().st_size == args.expected_size and sha(args.zip) == args.expected_sha256,
            'ZIP changed during extraction')
    roots = list(destination.iterdir())
    require(len(roots) == 1 and roots[0].is_dir(), 'Expected one evidence root in archive')
    return roots[0], dict(bytes=args.expected_size, sha256=args.expected_sha256, members=len(members),
                         uncompressedBytes=total, allMemberCrcsVerified=True)


def verify_inventory(root):
    manifest = strict_json(root / 'archive-manifest.json')
    # Exporter owns the exact schema. Inventory entries are paths relative to this evidence root.
    require(manifest.get('schema') == 'lightforge.game-full-source-archive.v1', 'Unexpected archive manifest schema')
    entries = manifest.get('files')
    require(isinstance(entries, list) and entries, 'Missing archive file inventory')
    files = {}
    for entry in entries:
        require(isinstance(entry, dict) and entry.get('path') not in files, 'Invalid or duplicate archive inventory entry')
        files[entry['path']] = {key: entry[key] for key in ('bytes', 'sha256')}
    require(manifest.get('executionSourceCommit') == SOURCE and manifest.get('executionSourceTree') == TREE
            and manifest.get('runDirectory') == root.name
            and all(manifest.get(flag) is False for flag in ('qualityApproved', 'target75Proven', 'releaseAuthorized')),
            'Archive source identity or approval flags differ')
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and str(p.relative_to(root)) != 'archive-manifest.json'}
    require(set(files) == actual, 'Archive inventory has missing or extra files')
    for name, pin in files.items():
        checked(root, name, pin)
    return dict(fileCount=len(files), archiveManifestSha256=sha(root / 'archive-manifest.json'))


def verify_sources(root, handoff, repo):
    require(handoff.get('schema') == 'lightforge.game-full-source-handoff.v1'
            and handoff.get('executionSourceCommit') == SOURCE and handoff.get('executionSourceTree') == TREE
            and handoff.get('harnessSha256') == HARNESS_SHA and handoff.get('originalSetupSourceCommit') == ORIGINAL
            and handoff.get('originalApplicationSourceUnchanged') is True, 'Frozen source handoff differs')
    actual_tree = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', SOURCE + '^{tree}'], text=True).strip()
    require(actual_tree == TREE, 'Local fixed commit tree differs')
    source = root / 'execution-source'
    pins = handoff['sourceFiles']
    require(isinstance(pins, dict) and pins, 'Missing source snapshot inventory')
    actual = {str(p.relative_to(source)) for p in source.rglob('*') if p.is_file()}
    require(actual == set(pins), 'Source snapshot inventory differs')
    for name, pin in pins.items():
        file = checked(source, name, pin)
        require(file.read_bytes() == blob(repo, name), 'Archived source differs from fixed Git blob: ' + name)
    require(sha(source / 'tools/benchmark_game_source_cuda.py') == HARNESS_SHA, 'Frozen harness digest differs')
    for name in APP_FILES:
        expected = hashlib.sha256(blob(repo, name, ORIGINAL)).hexdigest()
        require(handoff['applicationSourceHashes'].get(name) == expected and sha(source / name) == expected,
                'Original application source changed: ' + name)
    return source


def pinned_module(source):
    python = {p.resolve(): p.read_bytes() for p in source.rglob('*.py')}
    original_spec = importlib.util.spec_from_file_location

    class SourceLoader(importlib.machinery.SourceFileLoader):
        def get_code(self, fullname):
            return compile(python[Path(self.path).resolve()], self.path, 'exec', dont_inherit=True)

    def source_spec(name, location=None, *, loader=None, submodule_search_locations=None):
        path = Path(location).resolve()
        require(path in python and loader is None and submodule_search_locations is None,
                'Unexpected unverified dynamic module import')
        return original_spec(name, str(path), loader=SourceLoader(name, str(path)))

    importlib.util.spec_from_file_location = source_spec
    try:
        spec = source_spec('verified_full_source_game', source / 'tools/benchmark_game_source_cuda.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        importlib.util.spec_from_file_location = original_spec
    return module


def verify_input(root, handoff, harness, repo):
    parent_path = checked(root, 'parent-setup/setup-receipt.json', handoff['parentSetupReceipt'])
    parent = strict_json(parent_path)
    require(parent['schema'] == 'lightforge.game-notebook-setup.v1' and parent['sourceCommit'] == ORIGINAL
            and parent['publicApkSha256'] == APK_SHA and parent['publicAudioSha256'] == AUDIO_SHA
            and parent['modelManifestSha256'] == MANIFEST_SHA and parent['inputPcmSha256'] == FIRST14_SHA,
            'Original setup identity differs')
    for item in (parent, handoff):
        require(all(item.get(flag) is False for flag in ('qualityApproved', 'target75Proven', 'releaseAuthorized')),
                'Unexpected setup approval')
    require(handoff['extractedNativeLibraries'] == parent['extractedNativeLibraries'], 'Handoff native-library pins differ from setup')
    old_provenance = safe_file(root, 'parent-setup/input-provenance.json')
    require(sha(old_provenance) == parent['inputProvenanceSha256'], 'Parent input provenance digest differs')
    require(sha(safe_file(root, 'parent-setup/input-source-proof.json')) == strict_json(old_provenance)['inputSourceProofSha256'],
            'Parent input proof digest differs')
    pcm = checked(root, 'public-demo-mixture-full64s.f32', handoff['fullPcm'])
    provenance_file = checked(root, 'input-provenance.json', handoff['inputProvenance'])
    proof_file = checked(root, 'input-source-proof.json', handoff['inputSourceProof'])
    provenance, plan = harness.validate_input(pcm, provenance_file)
    require(provenance['sourceCommit'] == SOURCE and provenance['sourceTree'] == TREE
            and provenance['sourceKind'] == 'public-mixture' and provenance['separatedVocals'] is False
            and provenance['sourceSamples'] == 2822400 and provenance['sourceSHA256'] == AUDIO_SHA
            and provenance['apkSha256'] == APK_SHA and provenance['language'] == 0
            and provenance['inputSourceProofSha256'] == sha(proof_file), 'Complete public input provenance differs')
    require(hashlib.sha256(pcm.read_bytes()[:617400*4]).hexdigest() == FIRST14_SHA,
            'Full PCM does not begin with the previously qualified exact passage')
    public_audio = blob(repo, 'web/demo/glass-castle.wav')
    require(hashlib.sha256(public_audio).hexdigest() == AUDIO_SHA, 'Public WAV Git blob differs from original source pin')
    with wave.open(io.BytesIO(public_audio), 'rb') as audio:
        require(audio.getnchannels() == 2 and audio.getsampwidth() == 2 and audio.getframerate() == 44100
                and audio.getcomptype() == 'NONE' and audio.getnframes() == 2822400, 'Original public WAV clock/format differs')
        stereo = audio.readframes(2822400)
    require(len(stereo) == 2822400*4, 'Truncated original public WAV')
    derived = bytearray(2822400*4)
    for index, (left, right) in enumerate(struct.iter_unpack('<hh', stereo)):
        struct.pack_into('<f', derived, index*4, (left/32768.0 + right/32768.0)*.5)
    require(bytes(derived) == pcm.read_bytes() and hashlib.sha256(derived).hexdigest() == FULL_PCM_SHA,
            'Complete archived PCM differs from independent full public WAV derivation')
    proof = strict_json(proof_file)
    expected_plan = [dict(index=p['index'], first=p['first'], last=p['last'], samples=p['last']-p['first'],
                          language=0, seed=p['seed']) for p in plan]
    require(proof['schema'] == 'lightforge.game-source-input-proof.v1' and proof['publicAudioSha256'] == AUDIO_SHA
            and proof['pcmSha256'] == sha(pcm) and proof['totalSamples'] == 2822400 and proof['sampleRate'] == 44100
            and proof['byteIdenticalToProductionReaderMix'] is True and proof['plan'] == expected_plan
            and proof['scheduleProbeUsesSyntheticNonSilentPCM'] is True and proof['planOnly'] is True
            and proof.get('productionReaderCalls') == [dict(first=0, count=1411200), dict(first=1411200, count=1411200)]
            and proof['modelInferenceExecuted'] is False and proof['qualityApproved'] is False, 'Recorded production input proof differs')
    require(proof['sourceHashes'] == {name: sha(harness.ROOT / name) for name in ('web/analysis/wav-reader.js', 'web/analysis/game.js')},
            'Input proof source identities differ')
    manifest_file = harness.ROOT / 'web/analysis/models/game/manifest.json'
    require(sha(manifest_file) == MANIFEST_SHA, 'Original model manifest differs')
    return pcm, provenance, plan, strict_json(manifest_file), parent


def verify_exit(root, stage):
    file = root / (stage + '-exit.json')
    if not file.is_file():
        return None
    record = strict_json(file)
    require(type(record.get('exitCode')) is int and record.get('logSha256') == sha(safe_file(root, stage + '.log'))
            and record.get('qualityApproved') is False and record.get('target75Proven') is False,
            'Closed stage log or exit receipt differs: ' + stage)
    return record['exitCode']


def verify_artifacts(directory, pins):
    require(isinstance(pins, dict), 'Invalid artifact inventory')
    for name, digest in pins.items():
        require(re.fullmatch('[a-f0-9]{64}', str(digest)) and sha(safe_file(directory, name)) == digest,
                'Bound artifact digest mismatch: ' + name)
    return len(pins)


def verify_snapshot(directory, variant, mode, harness, pins, readiness=False):
    prefix = 'readiness_' if readiness else ''
    folder = directory / (prefix + variant + '_' + mode)
    native = safe_file(folder, 'NativeGame.java')
    text = native.read_text()
    traces = None
    if mode == 'profiled':
        matches = re.findall(r'options\.enableProfiling\(new File\(("(?:[^"\\]|\\.)*")', text)
        require(len(matches) == 1, 'Missing or duplicated profile path in generated source')
        traces = Path(json.loads(matches[0]))
        require(traces.is_absolute() and '..' not in traces.parts and
                traces.name == prefix + variant + '_active_traces', 'Unexpected original profile output path')
    expected = harness.source_snapshot(harness.game.SOURCE.read_text(), variant, mode, traces)
    require(text == expected, 'Generated source differs from frozen transformation: ' + folder.name)
    for file in (native, folder / 'GameSourceRunner.java', folder / 'GameAcceleratorCapture.java'):
        name = str(file.relative_to(directory))
        require(name in pins and sha(file) == pins[name], 'Unbound generated Java source: ' + name)
    require((folder / 'GameSourceRunner.java').read_bytes() == harness.RUNNER.read_bytes()
            and (folder / 'GameAcceleratorCapture.java').read_bytes() == harness.CAPTURE.read_bytes(),
            'Copied Java helpers differ from frozen source')
    classes = {str(p.relative_to(folder / 'classes')) for p in (folder / 'classes').rglob('*.class')}
    expected_classes = {'com/cyberbasslord/lightforge/' + name for name in
                        ('NativeGame.class', 'NativeGame$Owned.class', 'NativeGame$Cancellation.class', 'NativeGame$Listener.class',
                         'GameAcceleratorCapture.class', 'GameAcceleratorCapture$1.class', 'GameSourceRunner.class')}
    require(classes == expected_classes, 'Compiled class inventory differs: ' + folder.name)
    for name in classes:
        require(str((folder / 'classes' / name).relative_to(directory)) in pins, 'Unbound compiled class')


def verify_configuration(receipt, harness, provenance, plan, manifest):
    require(receipt['schema'] == 'lightforge.game-source-cuda-experiment.v1'
            and all(receipt.get(flag) is False for flag in FLAGS), 'Unexpected experiment schema or approval')
    require(receipt['sourceHashes'] == {name: sha(harness.ROOT / name) for name in harness.SOURCE_BINDINGS},
            'Collector source bindings differ')
    require(receipt['inputProvenance'] == provenance and receipt['passagePlan'] == plan
            and receipt['modelManifestSha256'] == MANIFEST_SHA
            and receipt['modelHashes'] == {name: pin['sha256'] for name, pin in manifest['files'].items()},
            'Collector input/model/plan differs')
    require(receipt['variants'] == ['cpu_all', 'cuda_basic'] and receipt['modes'] == ['plain', 'captured', 'profiled']
            and receipt['executionIdentity'] == {v: harness.execution_identity(v) for v in harness.VARIANTS}
            and receipt['cudaOptions'] == harness.accel.CUDA_OPTIONS and receipt['cudaHeavyOnly'] is True
            and receipt['cudaDeterministicCompute'] is True and receipt['cublasWorkspaceConfig'] == ':4096:8'
            and receipt['nvidiaTf32Override'] == '0'
            and receipt['requestedGraphProviders'] == {v: harness.game.requested_graph_providers(v, True) for v in harness.VARIANTS},
            'Collector provider configuration differs')
    runtime = strict_json(harness.ROOT / 'android/native-runtime.json')
    dependencies = {'test-json.jar': 'c243f45f9590c12694a4142ed3f07fc70dfb71e4daebd05ae234bf92a2da92a6',
                    'android.jar': '4566663c3876e022b4fa4ced8c8697c4ab1688267f090114fd92d027b32e619b',
                    runtime['host']['name']: runtime['host']['sha256'],
                    harness.accel.GPU_RUNTIME['name']: harness.accel.GPU_RUNTIME['sha256']}
    require(receipt['dependencyHashes'] == dependencies, 'Original runtime dependency pins differ')
    return dependencies


def verify_libraries(receipt, directory, parent, repo):
    notebook = blob(repo, NOTEBOOK_PATH, NOTEBOOK_SOURCE)
    require(hashlib.sha256(notebook).hexdigest() == NOTEBOOK_SHA, 'Original setup notebook differs')
    tree = ast.parse(''.join(json.loads(notebook)['cells'][18]['source']))
    matches = [n.value for n in tree.body if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == 'CUDA_WHEELS' for t in n.targets)]
    require(len(matches) == 1, 'Original wheel pin definition missing')
    wheels = ast.literal_eval(matches[0])
    expected = [dict(package=p, version=v, filename=f, bytes=s, sha256=h,
                     source='https://pypi.org/project/' + p + '/' + v + '/') for p, v, f, s, h, _ in wheels]
    require(parent['cudaWheelPins'] == expected, 'CUDA wheel pins differ from original setup')
    maps = safe_file(directory, 'cuda_basic_profiled/cuda-jvm-loaded-library-maps.txt')
    require(str(maps.relative_to(directory)) in receipt['artifactHashes'], 'Unbound CUDA library map')
    mapped = set()
    for line in maps.read_text().splitlines():
        fields = line.split(None, 5)
        if len(fields) == 6 and fields[5].startswith('/') and Path(fields[5]).name.startswith(
                ('libcuda', 'libcudnn', 'libcublas', 'libnvrtc', 'libnvJitLink')):
            mapped.add(fields[5])
    libraries = receipt['gpuNativeLibraries']
    require(mapped and mapped == set(libraries), 'Full native-library map paths differ from recorded resolved paths')
    basenames = set()
    for name, pin in libraries.items():
        basename = Path(name).name
        require(basename not in basenames and type(pin['bytes']) is int and pin['bytes'] > 0
                and re.fullmatch('[a-f0-9]{64}', pin['sha256']), 'Invalid or duplicate loaded library')
        basenames.add(basename)
        if '/cuda-wheels/' in name:
            require(parent['extractedNativeLibraries'].get(name.split('/cuda-wheels/', 1)[1]) == pin,
                    'Loaded wheel library differs from original extraction')
        else:
            require(basename.startswith('libcuda.so'), 'Unpinned non-driver native library')
    require(receipt['gpuNativeLibraryVersions'] == dict(cudaRuntimeVersion=12090, cudnnVersion=91002, cublasVersion=[12, 9, 1]),
            'Loaded CUDA/cuDNN/cuBLAS versions differ')
    return dict(mappedLibraryCount=len(libraries), recordedVersions=receipt['gpuNativeLibraryVersions'],
                originalWheelPinsVerified=True, actualLibraryBytesIncluded=False)


def verify_collector(root, harness, pcm, provenance, plan, manifest, parent, args):
    path = root / 'qualification/receipt.json'
    if not path.is_file():
        return dict(present=False, completeDiagnosticVerified=False)
    receipt, directory = strict_json(path), path.parent
    require(receipt.get('status') in (*SUCCESS, 'OBSERVER_COMPARISON_INVALID', 'BLOCKED_OR_REJECTED', 'INCOMPLETE'),
            'Unknown collector status')
    if 'sourceHashes' not in receipt:
        require(receipt.get('status') in ('BLOCKED_OR_REJECTED', 'INCOMPLETE'), 'Successful collector lacks source bindings')
        return dict(present=True, status=receipt['status'], completedRunCount=0, completeDiagnosticVerified=False,
                    recordedFailure=receipt.get('failure'))
    verify_configuration(receipt, harness, provenance, plan, manifest)
    require(receipt['inputProvenanceSha256'] == sha(root / 'input-provenance.json'), 'Collector provenance byte binding differs')
    rows = receipt.get('runs', [])
    require([(r['variant'], r['mode']) for r in rows] == MATRIX[:len(rows)], 'Missing, reordered or duplicated completed run')
    require(len(rows) <= 6, 'Extra collector run')
    artifacts = verify_artifacts(directory, receipt.get('artifactHashes', {}))
    outputs, runs = {v: {} for v in harness.VARIANTS}, {}
    for row in rows:
        variant, mode = row['variant'], row['mode']
        relative = variant + '_' + mode + '/output/receipt.json'
        require(row['receipt'] == relative and sha(safe_file(directory, relative)) == row['receiptSha256']
                and row['timingEligible'] is False and row['passageCount'] == len(plan), 'Completed run binding differs')
        output = directory / (variant + '_' + mode) / 'output'
        run = harness.validate_run(output, mode, provenance, plan, manifest)
        require(row['wallNanos'] == run['wallNanos'], 'Run duration receipt differs')
        outputs[variant][mode], runs[(variant, mode)] = output, run
        if receipt.get('artifactHashes'):
            verify_snapshot(directory, variant, mode, harness, receipt['artifactHashes'])
    traces, placements = {}, {}
    for variant in harness.VARIANTS:
        if 'profiled' not in outputs[variant]:
            continue
        summaries, observed = [], []
        for row in plan:
            summary = harness.game.summarize_traces(outputs[variant]['profiled'] / f"passage-{row['index']:03d}" / 'traces')
            placement = harness.game.validate_placement(summary, variant, True)
            summaries.append(dict(passageIndex=row['index'], **summary))
            observed.append(dict(passageIndex=row['index'], **placement))
        require(summaries == receipt['providerTraces'][variant] and observed == receipt['placement'][variant],
                'Independently recomputed provider traces or placement differ')
        traces[variant], placements[variant] = summaries, observed
    observers, observer_valid = [], False
    if len(rows) == 6:
        observers = harness.compare_observers(outputs, plan)
        require(observers == receipt['observerComparisons'], 'Independently recomputed observer comparisons differ')
        try:
            harness.game.validate_observers(observers)
            observer_valid = True
        except harness.accel.InvalidObserver:
            require(receipt['status'] == 'OBSERVER_COMPARISON_INVALID', 'Observer failure was not declared')
    cross = []
    if all('captured' in outputs[v] for v in harness.VARIANTS):
        for row in plan:
            comparison = harness.comparator.compare(*(outputs[v]['captured'] / f"passage-{row['index']:03d}" for v in harness.VARIANTS))
            cross.append(dict(passageIndex=row['index'], reference='cpu_all', candidate='cuda_basic',
                              qualityApproved=False, tolerance=None, **comparison))
        if receipt.get('crossVariantComparisons'):
            require(cross == receipt['crossVariantComparisons'], 'Independently recomputed cross-provider comparisons differ')
    complete = receipt['status'] in SUCCESS
    libraries = None
    if complete:
        require(len(rows) == 6 and observer_valid and receipt['observerComparisonsPassed'] is True
                and receipt['inputsRecheckedAfterQualification'] is True and artifacts > 0,
                'Collector claimed completion without all verification gates')
        exact = all(row['exactParity'] for row in cross)
        require(receipt['rawOutputsByteIdenticalAcrossVariants'] is exact and
                receipt['status'] == ('COMPLETE_DIAGNOSTIC' if exact else 'NUMERICAL_EQUIVALENCE_UNPROVEN'),
                'Collector completion status differs from raw evidence')
        libraries = verify_libraries(receipt, directory, parent, args.repo)
    return dict(present=True, status=receipt['status'], receiptSha256=sha(path), completedRunCount=len(rows),
                completeDiagnosticVerified=complete, boundArtifactCount=artifacts,
                observerComparisonsIndependentlyRecomputed=len(observers), observerComparisonsPassed=observer_valid,
                crossVariantComparisons=cross, providerPlacementIndependentlyRecomputed=placements,
                nativeLibraryEvidence=libraries, recordedFailure=receipt.get('failure'))


def replay_and_compare(root, source, pcm, args):
    archived = strict_json(root / 'replay.json')
    output = args.output_dir / 'recomputed-replay.json'
    log = args.output_dir / 'recomputed-replay.log'
    node_version = subprocess.check_output([args.node, '--version'], text=True).strip()
    require(re.fullmatch(r'v(?:2[2-9]|[3-9][0-9])\.\d+\.\d+', node_version), 'Node 22 or newer required for independent replay')
    with log.open('x') as stream:
        result = subprocess.run([args.node, str(source / 'tools/game_benchmark/replay_cuda_source.cjs'),
            str(root / 'qualification/replay-manifest.json'), str(pcm), str(output)], cwd=source,
            stdout=stream, stderr=subprocess.STDOUT, timeout=180)
    require(result.returncode in (0, 2), 'Independent actual production replay failed; inspect recomputed-replay.log')
    actual = strict_json(output)
    require(actual == archived, 'Independent actual production replay differs from archived comparison')
    require(result.returncode == (0 if actual['productionTranscriptionIdentical'] else 2), 'Replay exit code contradicts comparison')
    return dict(actualProductionReplayReexecuted=True, archivedComparisonExactlyReproduced=True,
                originalComparisonSha256=sha(root / 'replay.json'), recomputedComparisonSha256=sha(output),
                nodeVersion=node_version, passageCount=actual['passageCount'],
                productionTranscriptionIdentical=actual['productionTranscriptionIdentical'],
                nativeCheckpointResumeIdentical=actual['nativeCheckpointResumeIdentical'],
                exactRuntimeObjectsPreserved=True, replayDoesNotExecuteModelInference=True,
                rawNoteDiagnostics=actual['rawNoteDiagnostics'], finalTranscriptionDiagnostics=actual['finalTranscriptionDiagnostics'])


def verify(args, root):
    inventory = verify_inventory(root)
    driver = strict_json(root / 'driver-receipt.json')
    require(driver['schema'] == 'lightforge.game-full-source-driver.v1'
            and driver['executionSourceCommit'] == SOURCE and driver['executionSourceTree'] == TREE
            and driver['harnessSha256'] == HARNESS_SHA and driver['status'] in ('COMPLETE_DIAGNOSTIC', 'BLOCKED_OR_REJECTED', 'INCOMPLETE'),
            'Unexpected driver identity or status')
    require(strict_json(root / 'archive-manifest.json')['driverStatus'] == driver['status'], 'Archive/driver status differs')
    for key in ('qualityApproved', 'target75Proven', 'benchmarkTimingAdmitted', 'releaseAuthorized', 'completeVocalStageMeasured'):
        require(driver.get(key) is False, 'Unexpected driver approval: ' + key)
    checked(root, 'executed-colab-run.py', driver['driverScript'])
    report = dict(schema='lightforge.game-full-source-verification.v1', archiveIntegrityVerified=True,
                  evidenceVerificationPassed=True, completeDiagnosticVerified=False, evidenceStatus='VERIFIED_PARTIAL',
                  sourceCommit=SOURCE, sourceTree=TREE, archiveInventory=inventory, driverStatus=driver['status'],
                  recordedFailure=driver.get('failure'), qualityApproved=False, target75Proven=False,
                  measuredSpeedupApproved=False, releaseAuthorized=False, modelInferenceExecuted=False)
    if driver['status'] == 'COMPLETE_DIAGNOSTIC':
        wrapper = blob(args.repo, WRAPPER_PATH, WRAPPER_SOURCE)
        require(hashlib.sha256(wrapper).hexdigest() == WRAPPER_SHA
                and safe_file(root, 'executed-colab-run.py').read_bytes() == wrapper,
                'Successful run did not use the reviewed corrected wrapper')
        report['driverScriptVerifiedAgainstReviewedGitBlob'] = True
    handoff_path = root / 'source-handoff.json'
    if not handoff_path.is_file():
        require(driver['status'] != 'COMPLETE_DIAGNOSTIC', 'Completed driver lacks source handoff')
        report['limitation'] = 'Driver stopped before a complete frozen source/input handoff; only archived file integrity verified.'
        return report
    handoff = strict_json(handoff_path)
    source = verify_sources(root, handoff, args.repo)
    harness = pinned_module(source)
    pcm, provenance, plan, manifest, parent = verify_input(root, handoff, harness, args.repo)
    report.update(sourceSnapshotFilesVerified=len(handoff['sourceFiles']), fullPcmSha256=sha(pcm), totalSamples=2822400,
                  canonicalPassageCount=len(plan), inputProofRecordedAndBound=True,
                  fullPcmIndependentlyDerivedFromPinnedPublicWav=True,
                  sourceAudioAndModelWeightsIncluded=False)
    exits = {stage: verify_exit(root, stage) for stage in ('readiness', 'qualification', 'replay')}
    report['stageExitCodes'] = exits
    readiness_path = root / 'readiness/receipt.json'
    if readiness_path.is_file():
        readiness = strict_json(readiness_path)
        if 'sourceHashes' in readiness:
            verify_configuration(readiness, harness, provenance, plan, manifest)
        if readiness['status'] == 'PREFLIGHT_READY':
            require(exits['readiness'] == 0 and readiness['readinessSnapshotCount'] == 6 and readiness['inferenceExecuted'] is False,
                    'Readiness success declaration differs')
            pins = readiness['readinessCompiledSnapshotHashes']
            report['readinessArtifactsVerified'] = verify_artifacts(readiness_path.parent, pins)
            for variant, mode in MATRIX:
                verify_snapshot(readiness_path.parent, variant, mode, harness, pins, True)
    collector = verify_collector(root, harness, pcm, provenance, plan, manifest, parent, args)
    report['collector'] = collector
    if driver['status'] == 'COMPLETE_DIAGNOSTIC':
        require(collector['completeDiagnosticVerified'] and exits['qualification'] == 0 and exits['replay'] in (0, 2)
                and driver['inputsAndSourcesRecheckedAfterReplay'] is True and driver['completedJvmRuns'] == 6,
                'Driver completion does not match independent collector verification')
        checked(root, 'qualification/receipt.json', driver['qualificationReceipt'])
        checked(root, 'replay.json', driver['replayReceipt'])
        report['replay'] = replay_and_compare(root, source, pcm, args)
        require(driver['replayExitCode'] == exits['replay'], 'Driver replay exit binding differs')
        report.update(completeDiagnosticVerified=True, evidenceStatus='VERIFIED_COMPLETE_DIAGNOSTIC')
    report['limitations'] = [
        'Complete 64-second public mixture GAME diagnostic; not complete separated-vocal or full-analysis quality evidence.',
        'Exact source snapshots, complete public PCM, raw tensors and raw traces are rechecked locally; full PCM is independently rederived from the pinned public WAV Git blob. Model weights and runtime binaries are absent; their pinned identity and runtime rehash are recorded by the bound collector/setup.',
        'Production runtime labels are preserved as adapter labels; CPU/CUDA research identities are reported separately.',
        'No GPU/model execution, timing ratio, fitted tolerance, 75% target approval, Android approval or publication authorization is produced.']
    verify_inventory(root)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', type=Path, required=True)
    parser.add_argument('--expected-size', type=int, required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--repo', type=Path, required=True, help='Read-only local Git object store containing the fixed commits')
    parser.add_argument('--node', default='node')
    parser.add_argument('--max-uncompressed-bytes', type=int, default=8*1024**3)
    args = parser.parse_args()
    require(re.fullmatch('[a-f0-9]{64}', args.expected_sha256) and args.expected_size > 0 and args.max_uncompressed_bytes > 0,
            'Expected positive archive size and lowercase SHA256 are mandatory')
    args.zip, args.repo, args.output_dir = args.zip.absolute(), args.repo.resolve(), args.output_dir.absolute()
    require(not args.output_dir.exists() and not args.output_dir.resolve().is_relative_to(args.repo),
            'Verification output must be a new directory outside the repository')
    args.output_dir.mkdir(parents=True)
    root, archive = None, None
    try:
        root, archive = extract_verified(args)
        report = verify(args, root)
        report['archive'] = archive
        target = args.output_dir / 'verification.json'
        target.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
        print(json.dumps({key: report[key] for key in ('evidenceStatus', 'archiveIntegrityVerified', 'evidenceVerificationPassed',
              'completeDiagnosticVerified', 'qualityApproved', 'target75Proven')}))
        print('Verification report:', target)
        return 0
    except Exception as error:
        failure = dict(schema='lightforge.game-full-source-verification.v1', evidenceVerificationPassed=False,
                       completeDiagnosticVerified=False, errorType=type(error).__name__, error=str(error),
                       archiveIntegrityVerified=archive is not None,
                       qualityApproved=False, target75Proven=False, releaseAuthorized=False)
        if archive is not None:
            failure['archive'] = archive
            failure['extractedEvidenceRetained'] = str(root)
            for key, name in (('recordedDriverStatus', 'driver-receipt.json'), ('recordedCollectorStatus', 'qualification/receipt.json')):
                try:
                    failure[key] = strict_json(root / name).get('status')
                except (OSError, ValueError, TypeError):
                    pass
        (args.output_dir / 'verification-failure.json').write_text(json.dumps(failure, indent=2)+'\n')
        print(json.dumps(failure), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
