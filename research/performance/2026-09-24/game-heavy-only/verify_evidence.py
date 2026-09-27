#!/usr/bin/env python3
"""Read-only GAME evidence verification; never executes a benchmark or grants approval.

This verifier is exclusively for the explicitly requested heavy-only CUDA policy.
The input ZIP is left unchanged. A new output directory holds safely extracted
evidence and a separate verification report. Imported comparison modules are
first matched against the immutable research commit. The original all-graphs verifier remains a separate, unchanged file.
"""
import argparse
import ast
import hashlib
import importlib.machinery
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import zipfile

sys.dont_write_bytecode = True
SOURCE = '8590ac4a67de4340857a96ffe38bae53d7d902b8'
SOURCE_TREE = 'c841bf18f91d3d04dd6daf7e886e2aa473ab8c70'
INPUT_SOURCE = 'd9b42bb79145cfe81367fd70e2ca0ff7f4d52c12'
PARENT_SETUP_SHA = 'a92e864c73f5da16c9103291bc6057d73fd80dd1c70773c21220cf82f14b3926'
PARENT_PROVENANCE_SHA = '3bd1db1265dfd30a31bdc0fe4b92e5fe428404ccd45b2453a8221a1031760ffb'
PARENT_PROOF_SHA = '075a6cf2ae0c884ac14c8b9a5e6e67fb3f248091c043bb45468e0e34192ea8a9'
HARNESS_SHA = '0305734ab3102b375ae80b5d090cadaf68068541b84ced58cbf5466cd89403d9'
NOTEBOOK_COMMIT = '3d525cd16ae7688777a2ca677db7fecbf76c4e9e'
NOTEBOOK = 'notebooks/LightForge_Colab_Kaggle_GAME_GPU_Qualification.ipynb'
NOTEBOOK_SHA = 'eb274157af3ea1e6d78c5803ffe3bccbbd2765683abed6d5618746c3e6555445'
PCM_SHA = 'a75b3b8d59c87d428e38e45db5f54ad8d2b1613fe79ee07c2595fecbf9215274'
AUDIO_SHA = '33f07d502ba19832b62b97d8fb4a11354e81310264bd885d7a06438228773650'
APK_SHA = 'af83bf403875c55d42fd695d43f6e193114899c1324fbaeaffd6c02d299d882f'
SOURCE_FILES = {
    'android/src/com/cyberbasslord/lightforge/NativeGame.java',
    'tools/game_benchmark/GameAcceleratorCapture.java',
    'tools/game_benchmark/GameAcceleratorRunner.java',
    'tools/benchmark_game_accelerator.py', 'tools/game_benchmark/compare.py',
    'tools/benchmark_deux_accelerator.py', 'tools/profile_deux_operators.py',
    'tools/benchmark_deux_execution.py', 'android/native-runtime.json',
    'web/analysis/models/game/manifest.json',
}
FLAGS = ('measured', 'qualityApproved', 'target75Proven', 'wholeSongSpeedupProven',
         'fullVocalStageSpeedupProven', 'androidSpeedupProven', 'releaseAuthorized')
EXPECTED_CLASSES = {'com/cyberbasslord/lightforge/' + name for name in (
    'NativeGame.class', 'NativeGame$Owned.class', 'NativeGame$Cancellation.class',
    'NativeGame$Listener.class', 'GameAcceleratorCapture.class',
    'GameAcceleratorCapture$1.class', 'GameAcceleratorRunner.class')}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def blob(repo, name, commit=SOURCE):
    return subprocess.check_output(['git', '-C', str(repo), 'show', commit + ':' + name])


def strict_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result

    def floating(value):
        result = float(value)
        require(math.isfinite(result), 'Nonfinite JSON value')
        return result

    def constant(value):
        raise ValueError('Invalid JSON constant: ' + value)

    require(path.is_file() and not path.is_symlink(), 'Missing regular JSON file: ' + str(path))
    return json.loads(path.read_text(), object_pairs_hook=pairs,
                      parse_float=floating, parse_constant=constant)


def safe_relative(value):
    require(isinstance(value, str) and value and '\\' not in value and '\x00' not in value,
            'Invalid relative path')
    path = PurePosixPath(value)
    require(not path.is_absolute() and all(part not in ('', '.', '..') for part in value.split('/'))
            and not re.match(r'^[A-Za-z]:', value), 'Unsafe relative path: ' + value)
    return path


def safe_file(root, relative):
    path = root.joinpath(*safe_relative(relative).parts)
    require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root.resolve()),
            'Missing/unsafe evidence file: ' + str(relative))
    return path


def extract_verified(args):
    archive = args.zip.resolve()
    require(archive.is_file() and not archive.is_symlink(), 'ZIP must be a regular file')
    require(archive.stat().st_size == args.expected_size, 'ZIP size does not match displayed size')
    actual = sha(archive)
    require(actual == args.expected_sha256, 'ZIP SHA256 does not match displayed digest')
    destination = args.output_dir / 'evidence'
    destination.mkdir()
    with zipfile.ZipFile(archive) as source:
        infos = source.infolist()
        require(0 < len(infos) <= 10000, 'Unexpected ZIP member count')
        seen = set()
        total = 0
        for info in infos:
            name = info.filename[:-1] if info.is_dir() else info.filename
            safe_relative(name)
            require(name not in seen, 'Duplicate ZIP member: ' + name)
            seen.add(name)
            mode = (info.external_attr >> 16) & 0xffff
            kind = stat.S_IFMT(mode)
            require(kind in (0, stat.S_IFDIR if info.is_dir() else stat.S_IFREG),
                    'Non-regular ZIP member: ' + name)
            require(not (info.flag_bits & 1), 'Encrypted ZIP member: ' + name)
            require(info.file_size >= 0 and info.file_size <= args.max_uncompressed_bytes,
                    'Oversized ZIP member: ' + name)
            total += info.file_size
        require(total <= args.max_uncompressed_bytes, 'ZIP exceeds uncompressed-byte safety limit')
        for info in infos:
            path = destination.joinpath(*PurePosixPath(info.filename).parts)
            if info.is_dir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with source.open(info) as incoming, path.open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
            require(path.stat().st_size == info.file_size, 'Extracted member length differs')
        # Reading each complete ZipExtFile above also checks its CRC.
    require(archive.stat().st_size == args.expected_size and sha(archive) == actual,
            'Input ZIP changed during verification')
    return destination, dict(bytes=args.expected_size, sha256=actual,
                             members=len(infos), uncompressedBytes=total, crcChecked=True)


def pinned_module(repo, receipt):
    require(set(receipt['sourceHashes']) == SOURCE_FILES, 'Bound source inventory differs')
    python_sources = {}
    for name, digest in receipt['sourceHashes'].items():
        data = blob(repo, name)
        expected = hashlib.sha256(data).hexdigest()
        require(expected == digest, 'Receipt source differs from pinned commit: ' + name)
        require(sha(safe_file(repo, name)) == expected, 'Local comparison source differs: ' + name)
        if name.endswith('.py'):
            python_sources[(repo / name).resolve()] = data

    class PinnedSourceLoader(importlib.machinery.SourceFileLoader):
        def get_code(self, fullname):
            # Compile verified Git blob bytes; never load a local __pycache__.
            data = python_sources[Path(self.path).resolve()]
            return compile(data, self.path, 'exec', dont_inherit=True)

    original_spec = importlib.util.spec_from_file_location

    def source_only_spec(name, location=None, *, loader=None, submodule_search_locations=None):
        path = Path(location).resolve()
        require(path in python_sources and loader is None and submodule_search_locations is None,
                'Unexpected dynamic verification-module import')
        return original_spec(name, str(path), loader=PinnedSourceLoader(name, str(path)))

    importlib.util.spec_from_file_location = source_only_spec
    try:
        spec = source_only_spec('verified_game_harness', repo / 'tools/benchmark_game_accelerator.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        importlib.util.spec_from_file_location = original_spec
    return module


def verify_snapshots(evidence, receipt, harness, kind):
    expected = receipt['compiledSnapshotHashes']
    require(isinstance(expected, dict) and expected, 'Missing artifact hash inventory')
    for name, digest in expected.items():
        require(sha(safe_file(evidence, name)) == digest, 'Artifact SHA256 mismatch: ' + name)
    source = harness.SOURCE.read_text()
    trace_roots = set()
    for variant in receipt['variants']:
        for mode in receipt['modes']:
            directory = evidence / (variant + '_' + mode)
            native = directory / 'NativeGame.java'
            text = native.read_text()
            changed = harness.variant_source(source, variant, cuda_heavy_only=True)
            if mode == 'profiled':
                matches = re.findall(r'options\.enableProfiling\(new File\(("(?:[^"\\]|\\.)*")', text)
                require(len(matches) == 1, 'Missing/duplicate snapshot profile path')
                trace = Path(json.loads(matches[0]))
                require(trace.is_absolute() and trace.name == variant + '_traces'
                        and '..' not in trace.parts, 'Unexpected bound profile path')
                require(kind != 'gpu' or trace.parent.name == 'qualification', 'Unexpected notebook qualification path')
                trace_roots.add(str(trace.parent))
                changed = harness.observed_source(changed, trace)
            elif mode == 'captured':
                changed = harness.observed_source(changed)
            require(text == changed, 'Snapshot differs from pinned generator: ' + str(directory.name))
            require(str(native.relative_to(evidence)) in expected, 'Unbound Java snapshot')
            for helper in harness.HELPERS:
                copied = directory / helper.name
                require(sha(copied) == sha(helper) and str(copied.relative_to(evidence)) in expected,
                        'Helper snapshot differs or is unbound')
            classes = directory / 'classes'
            require(classes.is_dir() and not classes.is_symlink(), 'Missing compiled class directory')
            actual_classes = {str(file.relative_to(classes)) for file in classes.rglob('*') if file.is_file()}
            require(actual_classes == EXPECTED_CLASSES, 'Incomplete/unexpected compiled class inventory')
            for file in classes.rglob('*'):
                if file.is_file():
                    require(str(file.relative_to(evidence)) in expected, 'Unbound compiled class')
            for file in (directory / 'output').iterdir():
                require(str(file.relative_to(evidence)) in expected, 'Unbound run output')
        for file in (evidence / (variant + '_traces')).iterdir():
            require(str(file.relative_to(evidence)) in expected, 'Unbound provider trace')
    require(len(trace_roots) == 1, 'Snapshots came from inconsistent evidence roots')
    return len(expected)


def verify_inputs(root, receipt, harness, repo, kind):
    if kind == 'gpu':
        provenance_path = root / 'input-provenance.json'
        pcm = root / 'public-demo-mixture-first14s.f32'
    else:
        provenance_path = root / 'input/provenance.json'
        pcm = root / 'input/passage.f32'
    provenance = harness.validate_input(pcm, provenance_path)
    require(provenance == receipt['inputProvenance'] and sha(provenance_path) == receipt['inputProvenanceSha256'],
            'Input provenance binding mismatch')
    require(provenance['pcmSHA256'] == PCM_SHA and provenance['sourceSHA256'] == AUDIO_SHA
            and provenance['sourceSamples'] == 2822400 and provenance['firstSample'] == 0
            and provenance['lastSample'] == 617400 and provenance['seed'] == 2025
            and provenance['language'] == 0, 'Unexpected public diagnostic passage')
    manifest = json.loads(blob(repo, 'web/analysis/models/game/manifest.json'))
    require(receipt['modelManifestSha256'] == receipt['sourceHashes']['web/analysis/models/game/manifest.json']
            and receipt['modelHashes'] == {key: value['sha256'] for key, value in manifest['files'].items()},
            'Model manifest binding mismatch')
    if kind == 'gpu':
        require(provenance['sourceCommit'] == INPUT_SOURCE and provenance['inputKind'] == 'public-demo-mixture'
                and provenance['separatedVocals'] is False and provenance['apkSha256'] == APK_SHA,
                'Unexpected notebook input origin')
        proof_path = root / 'input-source-proof.json'
        proof = strict_json(proof_path)
        require(sha(proof_path) == provenance['inputSourceProofSha256'], 'Input proof hash mismatch')
        plan = []
        for index in range(6):
            first = max(0, index * 12 - 2) * 44100
            last = min(2822400, ((index + 1) * 12 + 2) * 44100)
            plan.append(dict(index=index, first=first, last=last, samples=last-first,
                             language=0, seed=(2025+index*104729) & 0xffffffff))
        require(proof['schema'] == 'lightforge.game-notebook-input-proof.v1'
                and proof['pcmSha256'] == PCM_SHA and proof['publicAudioSha256'] == AUDIO_SHA
                and proof['byteIdenticalToProductionReaderMix'] is True and proof['plan'] == plan
                and proof['totalSamples'] == 2822400 and proof['sampleRate'] == 44100
                and proof['selectedPassage'] == 0 and proof['planOnly'] is True
                and proof['modelInferenceExecuted'] is False and proof['qualityApproved'] is False,
                'Incomplete/mismatched notebook source proof')
        require(set(proof['sourceHashes']) == {'web/analysis/wav-reader.js', 'web/analysis/game.js'},
                'Unexpected input-proof source inventory')
        for name, digest in proof['sourceHashes'].items():
            require(hashlib.sha256(blob(repo, name)).hexdigest() == digest, 'Input-proof source differs: ' + name)
    return manifest


def verify_libraries(root, receipt, harness, repo):
    setup = strict_json(root / 'setup-receipt.json')
    require(setup['schema'] == 'lightforge.game-notebook-setup.v1' and setup['sourceCommit'] == SOURCE
            and setup['publicApkSha256'] == APK_SHA and setup['publicAudioSha256'] == AUDIO_SHA
            and setup['inputPcmSha256'] == PCM_SHA
            and setup['inputProvenanceSha256'] == receipt['inputProvenanceSha256']
            and setup['modelManifestSha256'] == receipt['modelManifestSha256'], 'Setup receipt binding differs')
    require(all(setup.get(key) is False for key in ('qualityApproved', 'target75Proven', 'releaseAuthorized')),
            'Unexpected setup approval flag')
    notebook = blob(repo, NOTEBOOK, NOTEBOOK_COMMIT)
    require(hashlib.sha256(notebook).hexdigest() == NOTEBOOK_SHA, 'Pinned notebook digest differs')
    cell = ''.join(json.loads(notebook)['cells'][18]['source'])
    tree = ast.parse(cell)
    wheel_nodes = [node.value for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == 'CUDA_WHEELS' for target in node.targets)]
    require(len(wheel_nodes) == 1, 'Missing pinned wheel definition')
    wheels = ast.literal_eval(wheel_nodes[0])
    pins = [dict(package=p, version=v, filename=f, bytes=s, sha256=h,
                 source='https://pypi.org/project/' + p + '/' + v + '/') for p,v,f,s,h,_ in wheels]
    require(setup['cudaWheelPins'] == pins, 'CUDA wheel pins differ from immutable notebook')
    libs = receipt['gpuNativeLibraries']
    maps = safe_file(root / 'qualification', 'cuda_basic_profiled/cuda-jvm-loaded-library-maps.txt')
    require(str(maps.relative_to(root / 'qualification')) in receipt['compiledSnapshotHashes'], 'Unbound CUDA library map')
    mapped = set()
    prefixes = ('libcuda', 'libcudnn', 'libcublas', 'libnvrtc', 'libnvJitLink')
    for line in maps.read_text().splitlines():
        parts = line.split(None, 5)
        if len(parts) == 6 and parts[5].startswith('/') and Path(parts[5]).name.startswith(prefixes):
            mapped.add(parts[5])
    require(mapped, 'No mapped GPU native libraries retained')
    recorded_by_name = {}
    for name, info in libs.items():
        require(Path(name).is_absolute() and isinstance(info['bytes'], int) and info['bytes'] > 0
                and re.fullmatch('[0-9a-f]{64}', info['sha256']), 'Invalid native library binding')
        require(Path(name).name not in recorded_by_name, 'Duplicate native library basename')
        recorded_by_name[Path(name).name] = info
        require(name in mapped, 'Recorded library path missing from JVM maps; basename equality is insufficient')
        marker = '/cuda-wheels/'
        if marker in name:
            relative = name.split(marker, 1)[1]
            require(setup['extractedNativeLibraries'].get(relative) == info, 'Mapped wheel library differs from extraction receipt')
        else:
            require(Path(name).name.startswith('libcuda.so'), 'Unexpected unpinned non-driver library: ' + name)
    require(mapped == set(libs), 'Full JVM mapped paths differ from resolved library receipt paths; any alias requires separate live-runtime proof')
    for prefix in ('libcudart.so', 'libcudnn.so', 'libcublas.so'):
        require(sum(name.startswith(prefix) for name in recorded_by_name) == 1, 'Missing or duplicate ' + prefix)
    require(receipt['gpuNativeLibraryVersions'] == dict(cudaRuntimeVersion=12090, cudnnVersion=91002,
                                                       cublasVersion=[12,9,1]), 'Loaded library versions differ from pinned stack')
    return dict(mappedLibraryCount=len(libs), versions=receipt['gpuNativeLibraryVersions'],
                wheelBindingsMatch=True, actualLibraryBytesIncluded=False,
                limitation='Archive retains library hashes, mapped paths and queried versions; actual library bytes remain in Colab. Final runtime rehash is recorded by the harness.')


def verify_handoff(root, receipt, repo):
    parent_path = root / 'parent-setup-receipt.json'
    parent = strict_json(parent_path)
    require(sha(parent_path) == PARENT_SETUP_SHA, 'Original setup bytes differ from retained blocked run')
    require(parent['sourceCommit'] == INPUT_SOURCE, 'Original setup source differs')
    setup_path = root / 'setup-receipt.json'
    setup = strict_json(setup_path)
    expected_setup = dict(parent, sourceCommit=SOURCE, parentSetupSha256=PARENT_SETUP_SHA)
    require(setup == expected_setup, 'New setup must retain original verified settings with only execution-source and parent-hash additions')
    require(sha(root / 'input-provenance.json') == PARENT_PROVENANCE_SHA
            and receipt['inputProvenanceSha256'] == PARENT_PROVENANCE_SHA,
            'Reused input provenance bytes differ from original derivation')
    require(sha(root / 'input-source-proof.json') == PARENT_PROOF_SHA,
            'Reused input proof bytes differ from original derivation')
    handoff_path = root / 'source-handoff.json'
    handoff = strict_json(handoff_path)
    expected = dict(schema='lightforge.game-heavy-only-handoff.v1', executionSourceCommit=SOURCE,
                    executionSourceTree=SOURCE_TREE, inputDerivationSourceCommit=INPUT_SOURCE,
                    parentSetupSha256=PARENT_SETUP_SHA, setupReceiptSha256=sha(setup_path),
                    inputProvenanceSha256=PARENT_PROVENANCE_SHA, inputSourceProofSha256=PARENT_PROOF_SHA,
                    harnessSha256=HARNESS_SHA, cudaHeavyOnly=True)
    for key, value in expected.items():
        require(handoff.get(key) == value, 'Execution/derivation handoff mismatch: ' + key)
    require(handoff.get('cudaHeavyOnly') is True, 'Heavy-only handoff flag must be boolean true')
    require(receipt['sourceHashes']['tools/benchmark_game_accelerator.py'] == HARNESS_SHA,
            'Qualification harness differs from handoff')
    tree = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', SOURCE + '^{tree}'], text=True).strip()
    require(tree == SOURCE_TREE, 'Execution source tree differs from handoff')
    # The retained derivation is old evidence. Independently establish that its
    # decoder, window planner and original model manifest are unchanged here.
    for name in ('web/analysis/wav-reader.js', 'web/analysis/game.js', 'web/analysis/models/game/manifest.json'):
        require(blob(repo, name, INPUT_SOURCE) == blob(repo, name, SOURCE),
                'Reused derivation source/model binding changed: ' + name)
    for flag in ('qualityApproved', 'target75Proven', 'releaseAuthorized'):
        require(flag not in handoff or handoff[flag] is False, 'Unexpected handoff approval')
    return dict(schema=handoff['schema'], sha256=sha(handoff_path), executionSourceCommit=SOURCE,
                executionSourceTree=SOURCE_TREE, inputDerivationSourceCommit=INPUT_SOURCE,
                parentSetupSha256=PARENT_SETUP_SHA, setupReceiptSha256=sha(setup_path),
                retainedDerivationUnchanged=True)


def verify(args, extracted):
    candidates = []
    for path in extracted.rglob('receipt.json'):
        if path.parent.name == 'qualification':
            record = strict_json(path)
            if record.get('schema') == 'lightforge.game-accelerator-experiment.v1':
                candidates.append((path, record))
    require(len(candidates) == 1, 'Expected exactly one qualification receipt')
    receipt_path, receipt = candidates[0]
    evidence, root = receipt_path.parent, receipt_path.parent.parent
    harness = pinned_module(args.repo, receipt)
    variants = list(harness.VARIANTS if args.kind == 'gpu' else harness.VARIANTS[:2])
    modes = ['plain', 'captured', 'profiled']
    require(receipt['variants'] == variants and receipt['modes'] == modes, 'Run variants/modes differ')
    require(receipt.get('cudaHeavyOnly') is True, 'Explicit heavy-only CUDA request is required')
    require(receipt.get('requestedGraphProviders') == {
        name: harness.requested_graph_providers(name, cuda_heavy_only=True) for name in variants},
        'Per-graph requested providers differ from the pinned heavy-only policy')
    handoff_report = verify_handoff(root, receipt, args.repo)
    require(all(receipt.get(flag) is False for flag in FLAGS), 'Unexpected quality/performance/release approval')
    require(receipt.get('inputsRecheckedAfterQualification') is True
            and receipt.get('observerComparisonsPassed') is True, 'Incomplete integrity/observer checks')
    manifest = verify_inputs(root, receipt, harness, args.repo, args.kind)
    artifacts = verify_snapshots(evidence, receipt, harness, args.kind)
    dependencies = {'test-json.jar': 'c243f45f9590c12694a4142ed3f07fc70dfb71e4daebd05ae234bf92a2da92a6',
                    'android.jar': '4566663c3876e022b4fa4ced8c8697c4ab1688267f090114fd92d027b32e619b'}
    native_runtime = json.loads(blob(args.repo, 'android/native-runtime.json'))
    dependencies[native_runtime['host']['name']] = native_runtime['host']['sha256']
    if args.kind == 'gpu':
        dependencies[harness.accel.GPU_RUNTIME['name']] = harness.accel.GPU_RUNTIME['sha256']
    require(receipt['dependencyHashes'] == dependencies, 'Runtime/compile dependency pins differ')
    require(receipt['cudaOptions'] == harness.accel.CUDA_OPTIONS
            and receipt['cublasWorkspaceConfig'] == ':4096:8'
            and receipt['nvidiaTf32Override'] == '0', 'Provider configuration differs')
    require(len(receipt['runtimeProbes']) == (2 if args.kind == 'gpu' else 1), 'Runtime probe count differs')
    for index, probe in enumerate(receipt['runtimeProbes']):
        require(probe['runtimeVersion'] == '1.25.1' and probe['cudaRequested'] is (index == 1)
                and probe['cudaKernelExecutionProven'] is False, 'Runtime probe binding differs')
    expected_pairs = [(variant, mode) for variant in variants for mode in modes]
    require([(row['variant'], row['mode']) for row in receipt['runs']] == expected_pairs,
            'Missing/duplicate/reordered execution')
    run_records = {}
    for row in receipt['runs']:
        variant, mode = row['variant'], row['mode']
        relative = variant + '_' + mode + '/output/receipt.json'
        require(row['receipt'] == relative, 'Run receipt path differs')
        file = safe_file(evidence, relative)
        require(sha(file) == row['receiptSha256'], 'Run receipt SHA256 mismatch')
        run = strict_json(file)
        for key, value in dict(schema='lightforge-game-benchmark-1', steps=8, pcmSHA256=PCM_SHA,
                               modelFiles=manifest['files'], samples=617400, sampleRate=44100,
                               seed=2025, language=0, runtime='onnxruntime-java-1.25.1').items():
            require(run.get(key) == value, 'Run binding mismatch: ' + relative + ':' + key)
        require(run['capture'] is (mode != 'plain') and run['retirementConfirmed'] is True
                and type(run['wallNanos']) is int and run['wallNanos'] > 0
                and row['wallNanos'] == run['wallNanos'] and row['notes'] == run['notes']
                and row['capturedGraphInferenceSeconds'] == run['inferenceSeconds']
                and row['timingEligible'] is False, 'Invalid execution/timing row')
        if mode != 'plain':
            _, tensors = harness.comparator.load(file.parent)
            require(len(tensors) == 16, 'Expected sixteen raw captured tensors')
        run_records[(variant, mode)] = run
    observers = []
    placements = {}
    for variant in variants:
        captured = evidence / (variant + '_captured/output')
        profiled = evidence / (variant + '_profiled/output')
        comparison = harness.comparator.compare(captured, profiled)
        observers += [dict(variant=variant, kind='plain-vs-capture', rawTensorsByteIdentical=None,
                           unroundedNotesIdentical=run_records[(variant,'plain')]['notes'] == run_records[(variant,'captured')]['notes']),
                      dict(variant=variant, kind='capture-vs-profile', rawTensorsByteIdentical=comparison['exactParity'],
                           unroundedNotesIdentical=comparison['unroundedNotesIdentical'], rawComparison=comparison)]
        traces = harness.summarize_traces(evidence / (variant + '_traces'))
        require(traces == receipt['providerTraces'][variant], 'Recomputed provider trace summary differs')
        placement = harness.validate_placement(traces, variant, cuda_heavy_only=True)
        require(placement == receipt['placement'][variant], 'Recomputed placement differs')
        placements[variant] = placement
    harness.validate_observers(observers)
    require(observers == receipt['observerComparisons'], 'Recomputed observers differ')
    cross = []
    pairs = list(zip(variants, variants[1:])) + ([('cpu_all','cuda_basic')] if args.kind == 'gpu' else [])
    for left, right in pairs:
        comparison = harness.comparator.compare(evidence / (left+'_captured/output'), evidence / (right+'_captured/output'))
        comparison.update(reference=left, candidate=right, qualityApproved=False, tolerance=None)
        cross.append(comparison)
    require(cross == receipt['crossVariantComparisons'], 'Recomputed cross-variant comparisons differ')
    exact = all(row['exactParity'] for row in cross)
    status = ('CUDA_DIAGNOSTIC_COMPLETE' if args.kind == 'gpu' else 'CPU_CONTROL_DIAGNOSTIC_COMPLETE') if exact else 'NUMERICAL_EQUIVALENCE_UNPROVEN'
    require(receipt['rawOutputsByteIdenticalAcrossVariants'] is exact and receipt['status'] == status,
            'Diagnostic completion status inconsistent with raw comparisons')
    library_report = verify_libraries(root, receipt, harness, args.repo) if args.kind == 'gpu' else None
    return dict(schema='lightforge.game-evidence-verification.v1', verificationPassed=True,
                sourceCommit=SOURCE, kind=args.kind, receiptPath=str(receipt_path),
                receiptSha256=sha(receipt_path), receiptBytes=receipt_path.stat().st_size,
                diagnosticStatus=status, runCount=len(receipt['runs']), boundArtifactCount=artifacts,
                sourceHashCount=len(receipt['sourceHashes']), dependencyHashCount=len(dependencies),
                observerComparisonsPassed=True, observerComparisonCount=len(observers),
                crossVariantComparisons=cross, placement=placements, nativeLibraries=library_report,
                sourceHandoff=handoff_report, cudaHeavyOnly=True,
                requestedGraphProviders=receipt['requestedGraphProviders'],
                coldPassageDiagnosticTimes=[dict(variant=row['variant'], mode=row['mode'],
                                                 wallNanos=row['wallNanos']) for row in receipt['runs']],
                qualityApproved=False, target75Proven=False, measuredSpeedupApproved=False,
                releaseAuthorized=False, noBenchmarksExecuted=True,
                limitation='One public mixture passage only. Unrounded numerical differences remain diagnostic; no fitted tolerance, quality approval, whole-song speed claim or release approval.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', type=Path, required=True)
    parser.add_argument('--expected-size', type=int, required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--repo', type=Path, required=True)
    parser.set_defaults(kind='gpu')
    parser.add_argument('--max-uncompressed-bytes', type=int, default=8*1024**3)
    args = parser.parse_args()
    require(re.fullmatch('[0-9a-f]{64}', args.expected_sha256), 'Expected SHA256 must be lowercase hex')
    require(args.expected_size > 0 and args.max_uncompressed_bytes > 0, 'Invalid size limit')
    args.repo = args.repo.resolve()
    args.output_dir = args.output_dir.absolute()
    require(not args.output_dir.exists(), 'Output directory must be new')
    require(not args.output_dir.resolve().is_relative_to(args.repo), 'Verification output must be outside repository')
    args.output_dir.mkdir(parents=True)
    try:
        extracted, archive = extract_verified(args)
        report = verify(args, extracted)
        report['archive'] = archive
        report_path = args.output_dir / 'verification.json'
        report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        print(json.dumps({key:report[key] for key in ('verificationPassed','kind','diagnosticStatus','runCount',
              'boundArtifactCount','receiptSha256','qualityApproved','target75Proven')}, indent=2))
        print('Verification report:', report_path)
        return 0
    except Exception as error:
        report = dict(verificationPassed=False, errorType=type(error).__name__, error=str(error),
                      qualityApproved=False, target75Proven=False, releaseAuthorized=False)
        (args.output_dir / 'verification-failure.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
