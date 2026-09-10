#!/usr/bin/env python3
"""Qualify 2.2.5 optimizations with current exact-output proofs.

Historical 2.2.4 numerical/quality evidence is retained as historical. It is
never rebound to changed production code or represented as a fresh execution.
Missing or unfinished qualification inputs fail this gate and replace any old
passing output. The existing seven release gates remain required separately.
"""
from pathlib import Path
import ast
import collections
import datetime
import difflib
import hashlib
import importlib.util
import json
import math
import os
import re
import struct
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OUT = 'qa/release-2.2.5/'
HISTORICAL = 'qa/release-2.2.4/analysis-verification.json'
HISTORICAL_SHA256 = '8f1c599220f2f53b18b786c4eb2d5480c0d893575a7450fe63edbe9ce9255301'
CLOCK_SOURCES = {
    'version.json', 'web/analysis/separator-deux.js', 'web/analysis/dsp.js',
    'web/analysis/models/deux/manifest.json', OUT + 'test-source-clock.cjs',
}
REQUIRED_CACHE_SOURCES = {
    'web/analysis/worker.js', 'web/analysis/analyzer.js', 'web/background/runner.js',
    'web/analysis/work-store.js', 'web/analysis/stem-cache.js',
    'android/src/com/cyberbasslord/lightforge/AnalysisJobStore.java',
    'tests/analysis-recovery-2.2.1.test.cjs', 'version.json',
}



def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def file(root, relative):
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute(), 'Missing qualification path')
    path = (root / relative).resolve()
    require(path.is_relative_to(root) and path.is_file() and path.relative_to(root).as_posix() == relative,
            'Missing, external, or noncanonical qualification file: ' + relative)
    return path


def bind(root, relative, expected, hashes):
    require(isinstance(expected, str) and re.fullmatch(r'[a-f0-9]{64}', expected), 'Invalid SHA-256: ' + relative)
    path = file(root, relative)
    require(digest(path) == expected, 'Source differs from measured evidence: ' + relative)
    hashes[relative] = expected
    return path


def read_bound(root, relative, hashes):
    path = file(root, relative)
    hashes[relative] = digest(path)
    return json.loads(path.read_text())


def passed(result, label):
    require(result.get('passed') is True and not result.get('errors') and not result.get('error') and not result.get('failure'),
            label + ' is pending or failed')


def finite(value):
    return type(value) in {int, float} and math.isfinite(value)


def verify_historical(root, hashes):
    old = json.loads(bind(root, HISTORICAL, HISTORICAL_SHA256, hashes).read_text())
    require(old.get('release') == '2.2.4' and old.get('passed') is True, 'Historical release identity changed')
    require(old['fresh_native_mdx_comparison']['spectral_diagnostic_passed'] is False,
            'Historical failed spectral comparisons must remain visible')
    # Retain the measured comparisons and earlier failed protocols by their
    # original immutable hashes. Their old production-source bindings stay old.
    for key in ['fresh_native_runtime_comparison', 'fresh_native_mdx_comparison', 'fresh_native_mdx_downstream']:
        entry = old[key]
        bind(root, entry['path'], entry['sha256'], hashes)
    for relative, expected in old['source_hashes'].items():
        if relative.startswith('qa/release-2.2.4/initial-mdx-absolute-only/') or relative.startswith('qa/release-2.2.4/revised-mdx-first-run/'):
            bind(root, relative, expected, hashes)
    # The unchanged MDX bridge/runtime requires no new cross-runtime claim.
    for relative in ['android/native-runtime.json', 'android/src/com/cyberbasslord/lightforge/NativeDeux.java',
                     'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java', 'tests/NativeDeuxTest.java',
                     'android/src/com/cyberbasslord/lightforge/NativeMdxTask.java',
                     'android/src/com/cyberbasslord/lightforge/NativeRuntimeGuard.java', 'web/analysis/wav-reader.js']:
        bind(root, relative, old['source_hashes'][relative], hashes)
    return old


def verify_assets(root, historical, hashes):
    relative = 'web/analysis/ASSET_MANIFEST.json'
    manifest = read_bound(root, relative, hashes)
    require(isinstance(manifest, dict) and manifest, 'Current analysis inventory missing')
    base = root / 'web/analysis'
    actual = {p.relative_to(base).as_posix() for p in base.rglob('*') if p.is_file()
              and p.name != 'ASSET_MANIFEST.json' and not any(part.startswith('.') or part == '__pycache__' for part in p.relative_to(base).parts)}
    require(actual == set(manifest), 'Current analysis inventory does not match installed files')
    assets = {}
    for name, metadata in manifest.items():
        require(isinstance(metadata, dict) and set(metadata) == {'bytes', 'sha256'} and type(metadata['bytes']) is int and metadata['bytes'] > 0,
                'Invalid analysis asset metadata: ' + name)
        path = bind(root, 'web/analysis/' + name, metadata['sha256'], assets)
        require(path.stat().st_size == metadata['bytes'], 'Analysis asset length changed: ' + name)
    protected = {p: h for p, h in historical['analysis_asset_hashes'].items()
                 if p.startswith('web/analysis/models/') or p.startswith('web/analysis/vendor/')}
    require(set(protected) == {p for p in assets if p.startswith('web/analysis/models/') or p.startswith('web/analysis/vendor/')},
            'Model/runtime inventory changed; this exact optimization protocol is insufficient')
    for path, expected in protected.items():
        require(assets[path] == expected, 'Model weights, configuration, or runtime changed: ' + path)
    for name in ['deux', 'game']:
        manifest_path = 'web/analysis/models/' + name + '/manifest.json'
        hashes[manifest_path] = assets[manifest_path]
        models = json.loads(file(root, manifest_path).read_text())['files']
        require({p.relative_to(root / 'web/analysis/models' / name).as_posix() for p in (root / 'web/analysis/models' / name).rglob('*.onnx')} == {p for p in models if p.endswith('.onnx')},
                'Model graph inventory mismatch: ' + name)
    return assets


def verify_clock(root, hashes):
    result = read_bound(root, OUT + 'source-clock-verification.json', hashes)
    passed(result, 'Fresh source-clock check')
    require(result.get('release') == '2.2.5' and set(result.get('source_hashes', {})) == CLOCK_SOURCES, 'Source-clock release/source coverage changed')
    for source, expected in result['source_hashes'].items():
        bind(root, source, expected, hashes)
    require(result.get('samples') == 932143 and result.get('chunks') == 4 and result.get('contiguousSourceSamples') is True
            and result.get('monotonicProgress') is True and finite(result.get('maxAbsError')) and 0 <= result['maxAbsError'] < 2e-6,
            'Source-clock seams, overlap, or final sample failed')
    return result


def verify_fft(root, relative, historical, hashes):
    result = read_bound(root, relative, hashes)
    passed(result, 'Current MDX FFT exact comparison')
    sources = result.get('sources', {})
    require(set(sources) == {'baseline', 'candidate', 'dsp', 'probe'}, 'FFT proof source coverage changed')
    mapping = {'baseline': 'qa/speedup-exact/separator-mdx-2.2.4.js', 'candidate': 'web/analysis/separator-mdx.js',
               'dsp': 'web/analysis/dsp.js', 'probe': 'qa/speedup-exact/verify-mdx-fft.cjs'}
    for key, source in mapping.items():
        bind(root, source, sources[key], hashes)
    require(sources['baseline'] == historical['analysis_asset_hashes']['web/analysis/separator-mdx.js'], 'FFT reference is not the released 2.2.4 implementation')
    cases = result.get('cases', [])
    expected = [('web/demo/glass-castle.wav', -3840), ('web/demo/glass-castle.wav', 878160),
                ('qa/release-1.6.0/fixtures/falcon-mix.wav', -3840), ('seeded full-band stereo and edge floats', None)]
    require([(case.get('fixture'), case.get('start')) for case in cases] == expected, 'FFT fixture coverage changed')
    for case in cases:
        require(case.get('exact') is True and case.get('spectrumValues') == 3145728 and case.get('pcmSamples') == 261120,
                'FFT consumed spectrum or decoded PCM differs')
        for name in ['spectrumSHA256', 'pcmSHA256']:
            require(isinstance(case.get(name), str) and re.fullmatch(r'[a-f0-9]{64}', case[name]), 'FFT output fingerprint missing')
        if case['fixture'] != expected[-1][0]:
            bind(root, case['fixture'], case.get('sourceSHA256'), hashes)
    return result


def verify_unqualified_native_experiment(root, historical, hashes):
    relative = 'qa/speedup-exact/native-threads/release-decision.json'
    decision = read_bound(root, relative, hashes)
    require(decision.get('shipping') is False and decision.get('targetQualification') == 'unqualified',
            'The unqualified native eight-thread experiment must not ship')
    prior = decision.get('historicalReceipt', {})
    measured = json.loads(bind(root, prior.get('path'), prior.get('sha256'), hashes).read_text())
    require(measured.get('host', {}).get('machine') == 'x86_64', 'Native experiment architecture evidence changed')
    # Preserve candidate source snapshots under their recorded original hashes;
    # never compare these experimental bindings to restored production source.
    snapshots = decision.get('candidateSourceSnapshots', {})
    require(isinstance(snapshots, dict) and snapshots, 'Rejected native candidate snapshots missing')
    for source, metadata in snapshots.items():
        bind(root, metadata.get('preservedPath'), metadata.get('sha256'), hashes)
        if source in measured.get('sourceHashes', {}):
            require(metadata['sha256'] == measured['sourceHashes'][source], 'Native experiment snapshot differs from measured source')
    for source, expected in decision.get('restoredProductionHashes', {}).items():
        # The original rollback was exact. A later, separately reviewed build
        # integration adds AndroidX classpaths/resources to the verifier only.
        # Keep its old bytes in the immutable snapshot and qualify that later
        # integration separately; native arithmetic and tests remain unchanged.
        if source == 'tests/verify_native_release.py':
            verify_androidx_build_integration(root, expected, hashes)
        else:
            bind(root, source, expected, hashes)
        if source in historical['source_hashes']:
            require(expected == historical['source_hashes'][source], 'Native rollback differs from the published implementation')
    for source, expected in decision.get('architectureReviewHashes', {}).items():
        bind(root, source, expected, hashes)
    runtime = decision.get('supplementalRuntimeProvenance', {})
    bind(root, runtime.get('path'), runtime.get('sha256'), hashes)
    return {'shipping': False, 'target_qualification': 'unqualified', 'decision_path': relative,
            'decision_sha256': hashes[relative], 'historical_receipt': prior,
            'scope': 'Retained Linux/x86_64 experiment only; target ARM dispatch, prepacking and front/head kernel equivalence were not qualified. Production native source remains the published implementation.'}


def verify_androidx_build_integration(root, original_verifier_hash, hashes):
    relative = 'qa/speedup-exact/webview-isolation/build-integration.json'
    result = read_bound(root, relative, hashes)
    passed(result, 'Current AndroidX Java/resource/DEX build integration')
    require(result.get('factoryVerified') is True and result.get('officialBoundaryAndPublicApiDexClasses') is True
            and result.get('javaResourcesVerified') is True, 'AndroidX runtime closure was not verified')
    sources = result.get('sourceHashes', {})
    required = {'tests/verify_native_release.py', 'android/androidx-runtime.json', 'tools/bootstrap_androidx_runtime.py',
                'build.sh', 'tools/apk_archive.py', 'tools/build_android_tests.py', 'tools/build_diagnostics_tests.py',
                'android/src/com/cyberbasslord/lightforge/WebViewIsolation.java',
                'android/src/com/cyberbasslord/lightforge/NativeDeux.java',
                'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java'}
    require(isinstance(sources, dict) and required <= set(sources), 'AndroidX integration omits required current build sources')
    for source, expected in sources.items():
        bind(root, source, expected, hashes)
    integration = result.get('verifierIntegration', {})
    require(integration.get('baselineSha256') == original_verifier_hash
            and integration.get('currentPath') == 'tests/verify_native_release.py'
            and integration.get('currentSha256') == sources['tests/verify_native_release.py'],
            'Later native-verifier integration does not bind its original and current bytes')
    baseline = bind(root, integration.get('baselinePath'), original_verifier_hash, hashes).read_text()
    current = file(root, integration['currentPath']).read_text()
    difference = ''.join(difflib.unified_diff(baseline.splitlines(keepends=True), current.splitlines(keepends=True),
                                           fromfile=integration['baselinePath'], tofile=integration['currentPath']))
    require(difference == integration.get('unifiedDiff'), 'Native-verifier changes differ from the reviewed AndroidX integration')
    old_tree, new_tree = ast.parse(baseline), ast.parse(current)
    old_asserts = collections.Counter(ast.dump(node) for node in ast.walk(old_tree) if isinstance(node, ast.Assert))
    new_asserts = collections.Counter(ast.dump(node) for node in ast.walk(new_tree) if isinstance(node, ast.Assert))
    require(not old_asserts - new_asserts, 'An original native numerical/lifecycle assertion was removed or changed')
    def native_test_names(tree):
        return [ast.literal_eval(node.value) for node in ast.walk(tree) if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == 'names' for target in node.targets)]
    require(native_test_names(old_tree) == native_test_names(new_tree), 'The original native test coverage changed')
    measured = result.get('nativeHostGate', {})
    native = json.loads(bind(root, measured.get('path'), measured.get('sha256'), hashes).read_text())
    passed(native, 'Native host checks at the AndroidX integration checkpoint')
    require(native.get('release') == '2.2.5' and native.get('source_hashes', {}).get('tests/verify_native_release.py') == sources['tests/verify_native_release.py'],
            'Native host verification did not execute the current AndroidX-integrated verifier')
    for name in ['android/src/com/cyberbasslord/lightforge/NativeDeux.java',
                 'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java',
                 'tests/NativeDeuxTest.java', 'android/native-runtime.json']:
        bind(root, name, native.get('source_hashes', {}).get(name), hashes)
    return result


def verify_cache(root, relative, historical, hashes):
    result = read_bound(root, relative, hashes)
    passed(result, 'Current role-cache exact composition')
    require(result.get('sourceUnchangedDuringVerification') is True, 'Cache source stability was not verified')
    require(result.get('baseline', {}).get('worker', {}).get('sha256') == historical['analysis_asset_hashes']['web/analysis/worker.js'],
            'Cache reference is not the released 2.2.4 worker')
    candidate = result.get('candidate', {}).get('sources', [])
    bound = {}
    for item in candidate:
        require(isinstance(item, dict) and item.get('path') not in bound, 'Cache source binding is duplicate or invalid')
        path = bind(root, item.get('path'), item.get('sha256'), hashes)
        require(path.stat().st_size == item.get('bytes'), 'Cache source byte count changed')
        bound[item['path']] = item['sha256']
    require(REQUIRED_CACHE_SOURCES <= set(bound), 'Cache proof omits required current sources')
    folder = Path(relative).parent
    for metadata in [result.get('harness', {}), result.get('recoveryTests', {}).get('log', {})]:
        name = metadata.get('file')
        require(isinstance(name, str) and Path(name).name == name, 'Invalid cache evidence artifact name')
        path = bind(root, (folder / name).as_posix(), metadata.get('sha256'), hashes)
        require(path.stat().st_size == metadata.get('bytes'), 'Cache evidence artifact byte count changed')
    for label in ['baseline', 'candidate']:
        metadata = result.get(label, {})
        name = metadata.get('snapshot')
        require(isinstance(name, str) and Path(name).name == name, 'Cache worker snapshot missing')
        expected = metadata['worker']['sha256'] if label == 'baseline' else bound['web/analysis/worker.js']
        bind(root, (folder / name).as_posix(), expected, hashes)
    comparisons = result.get('comparisons', [])
    pairs = [('oldFresh', 'newFresh'), ('oldEdited', 'newEdited'), ('oldEdited', 'restored'), ('oldEdited', 'restoredLegacy')]
    require([(item.get('left'), item.get('right')) for item in comparisons] == pairs, 'Cache comparison coverage changed')
    for item in comparisons:
        require(item.get('passed') is True and item.get('byteIdentical') is True, 'Cache output differs from fresh baseline')
        left = bind(root, (folder / (item['left'] + '.json')).as_posix(), item.get('sha256'), hashes)
        right = bind(root, (folder / (item['right'] + '.json')).as_posix(), item.get('sha256'), hashes)
        require(left.stat().st_size == right.stat().st_size == item.get('bytes') and left.read_bytes() == right.read_bytes(),
                'Retained cache output comparison failed')
    require(result.get('newBassCheckpointKeys') == ['bassAnalysis', 'bassNotes'], 'Bass checkpoint contains stale rhythm')
    test = result.get('recoveryTests', {})
    require(test.get('exitCode') == 0 and type(test.get('tests')) is int and test['tests'] >= 22
            and test.get('pass') == test['tests'] and all(test.get(key) == 0 for key in ['fail', 'cancelled', 'skipped', 'todo']),
            'Cache recovery regression suite did not pass completely')
    return result


def verify_game_pool(root, relative, assets, hashes):
    require(relative is not None, 'Pending: actual Android GAME pool qualification receipt and provenance have not arrived')
    result = read_bound(root, relative, hashes)
    passed(result, 'Actual Android GAME pool qualification')
    require(result.get('diagnostic_only') is True, 'GAME qualification provenance is not the reviewed diagnostic')
    folder = Path(relative).parent
    provenance_path = (folder / 'provenance.json').as_posix()
    provenance = json.loads(bind(root, provenance_path, result.get('provenance_sha256'), hashes).read_text())
    require(provenance.get('prepared') is True and provenance.get('diagnostic_only') is True
            and provenance.get('release_eligible') is False and provenance.get('signing_key_destroyed') is True
            and provenance.get('diagnostic_version') == {'name': '2.2.5', 'code': 20205},
            'GAME diagnostic build/source identity incomplete')
    require(provenance.get('input_head_sha') == '57e6ee996bd8f9d135e89334585efe90d8667b68'
            and provenance.get('input_run_id') == 34424617050 and provenance.get('input_run_conclusion') == 'success'
            and provenance.get('input_apk_sha256') == '5620e784909b8fd14a4fb0e86c097f4acfe146f1b0a32681b1611015ef2c03d7',
            'GAME models did not originate from the reviewed complete 2.2.4 CI build')
    sources = provenance.get('source_hashes', {})
    required = {
        'version.json', 'android/native-runtime.json', 'android/AndroidManifest.xml',
        'android/src/com/cyberbasslord/lightforge/AnalysisService.java',
        'android/src/com/cyberbasslord/lightforge/AnalysisJobStore.java',
        'android/src/com/cyberbasslord/lightforge/AnalysisResourcePolicy.java',
        'web/analysis/game.js', 'web/analysis/game-worker.js', 'web/analysis/worker.js',
        'web/analysis/analyzer.js', 'web/analysis/work-store.js', 'web/background/runner.js',
        'web/analysis/ASSET_MANIFEST.json', 'web/analysis/models/game/manifest.json',
        'tools/prepare_game_pool_probe.py', 'tests/android/GamePoolProbe.java',
        'tests/android/game-pool-probe.js', '.github/workflows/probe-game-pool.yml',
    }
    require(isinstance(sources, dict) and required <= set(sources), 'Android GAME proof omits required production/rig sources')
    for source, expected in sources.items():
        bind(root, source, expected, hashes)
    # Import only the recorded collector's pure validation functions. This does
    # not prepare APKs, invoke adb, or run inference. Reuse its final raw schema
    # rather than translating the diagnostic into a looser receipt format.
    old_path = list(sys.path)
    try:
        sys.path.insert(0, str(root / 'tools'))
        spec = importlib.util.spec_from_file_location('lightforge_game_pool_receipt', file(root, 'tools/prepare_game_pool_probe.py'))
        collector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(collector)
        require(collector.source_hashes() == sources, 'Android GAME source coverage or bytes changed after qualification')
        device = result.get('device', {})
        collector.validate_report(device, provenance)
    finally:
        sys.path[:] = old_path
    require(device.get('androidSdk') == 35 and device.get('diagnosticOnly') is True,
            'Android GAME runtime differs from the reviewed device protocol')
    require(str(device.get('document', {}).get('location', '')).startswith('https://appassets.androidplatform.net/'),
            'GAME inference did not run in the actual app WebView')
    widths = {'float32': 4, 'float64': 8, 'float16': 2, 'bfloat16': 2, 'int64': 8, 'uint64': 8,
              'int32': 4, 'uint32': 4, 'int16': 2, 'uint16': 2, 'int8': 1, 'uint8': 1, 'bool': 1}
    for mode in ['serial', 'parallel', 'restart']:
        run = device[mode]
        require(run.get('sampleRate') == 44100 and run.get('samples') == 1058400 and run.get('numThreads') == 1,
                'GAME source clock or per-worker thread count changed')
        for record in run['records']:
            require(isinstance(record.get('tensors'), dict) and record['tensors'], 'Missing raw graph tensor evidence')
            for tensor in record['tensors'].values():
                dims = tensor.get('dims')
                require(isinstance(dims, list) and all(type(n) is int and n >= 0 for n in dims)
                        and tensor.get('type') in widths and type(tensor.get('bytes')) is int
                        and tensor['bytes'] == math.prod(dims) * widths[tensor['type']]
                        and isinstance(tensor.get('sha256'), str) and re.fullmatch(r'[a-f0-9]{64}', tensor['sha256']),
                        'Invalid raw graph tensor type/shape/byte fingerprint')
        if mode != 'restart':
            require(json.loads(run['transcriptionJson']) == run.get('transcription'), 'GAME transcription object differs from compared JSON')
        for checkpoint in run.get('checkpoints', {}).values():
            require(json.loads(checkpoint['json']) == checkpoint['value'], 'Checkpoint object differs from exact persisted JSON')
    # Preserve the actual runner output and require exactly the same full device
    # report, rather than trusting only summary success flags.
    log = read_bound_text(root, (folder / 'instrumentation.log').as_posix(), hashes)
    reports = [json.loads(line.split('GAME_POOL_RESULT ', 1)[1]) for line in log.splitlines() if 'GAME_POOL_RESULT ' in line]
    require(len(reports) == 1 and reports[0] == device and sum(line.strip() == 'GAME_POOL_PASS' for line in log.splitlines()) == 1,
            'Retained Android instrumentation output does not match the result')
    before = read_bound(root, (folder / 'input-payloads.json').as_posix(), hashes)
    after = read_bound(root, (folder / 'diagnostic-payloads.json').as_posix(), hashes)
    require(set(after) == set(before) | {'assets/analysis/game-worker.js'}, 'Android qualification APK payload inventory changed')
    replacements = provenance.get('replacement_entries', {})
    require(isinstance(replacements, dict) and replacements, 'Current Java/JS replacement provenance missing')
    for entry, metadata in after.items():
        if entry in replacements:
            require(all(metadata.get(key) == expected for key, expected in replacements[entry].items()),
                    'Android replacement payload differs from recorded source: ' + entry)
        else:
            require(metadata == before.get(entry), 'Unreviewed Android payload changed: ' + entry)
    for source, expected in assets.items():
        if source.startswith('web/analysis/models/') or source.startswith('web/analysis/vendor/'):
            entry = 'assets/' + source.removeprefix('web/')
            require(entry in before and after.get(entry) == before[entry] and after[entry].get('sha256') == expected,
                    'Android loaded an altered model/configuration/runtime payload: ' + source)
    for source in sources:
        if source.startswith('web/'):
            entry = 'assets/' + source.removeprefix('web/')
            require(after.get(entry, {}).get('sha256') == sources[source], 'Android packaged stale web source: ' + source)
    memory = result.get('memory', {})
    require(type(memory.get('samples')) is int and memory['samples'] >= 2
            and type(memory.get('renderer_samples')) is int and memory['renderer_samples'] >= 1,
            'Continuous system/renderer PSS observations missing')
    capacity = read_bound(root, (folder / 'host-capacity.json').as_posix(), hashes)
    require(capacity == result.get('hostCapacity') and capacity.get('passed') is True
            and capacity.get('configuredGuestMemoryMiB', 0) >= 8192 and capacity.get('configuredGuestCores', 0) >= 4,
            'Observed host/guest capacity qualification differs')
    safety = result.get('hostSafety', {})
    require(type(safety.get('samples')) is int and safety['samples'] >= 2 and safety.get('errors') == []
            and safety.get('reserveBytes') == 1610612736 and safety.get('minimumAvailableBytes', 0) >= safety['reserveBytes']
            and not safety.get('emulatorStopped'), 'Host capacity/swap guard did not remain healthy')
    return {'scope': result.get('scope'), 'limitations': [
        'Same-renderer API 35 emulator qualification with actual production GAME code and original model/runtime payloads.',
        'Timings include raw-output tracing and are not a physical-phone performance claim.',
        'An interrupted active lease is simulated; cancellation executes the real engine release path.',
        'Large platform memory/logcat streams remain in the original CI artifact; the retained receipt includes all compared model-output fingerprints.'
    ]}


def verify_pipeline_threads(root, relative, hashes):
    result = read_bound(root, relative, hashes)
    passed(result, 'Final isolated-classifier pipeline thread qualification')
    require(result.get('schema') == 'lightforge-full-pipeline-android-classifier-handoff-1'
            and result.get('firstMismatch') is None, 'Final pipeline qualification schema or exactness differs')
    expected_threads = {'rhythm': 1, 'separation': 4, 'voice-classifier': 1, 'voice': 4, 'bass': 1}
    controls = result.get('controls', {})
    require(controls.get('quality') == 'precision' and controls.get('nativePrediction') is False
            and controls.get('gamePool') is False and controls.get('expectedEffectiveThreads') == expected_threads,
            'The exact pipeline proof does not exercise the reviewed final Android routing')
    normalization = result.get('traceMetadataNormalization', {})
    require(normalization.get('stageMap') == {'voice-classifier': 'voice'}
            and normalization.get('ignoredComparisonFields') == ['sessionId'], 'Raw trace comparison exclusions changed')
    folder = Path(relative).parent
    archive = read_bound(root, (folder / 'archive-binding.json').as_posix(), hashes)
    copies = {}
    for item in archive.get('copies', []):
        require(item.get('exactCopy') is True and item.get('originalPath') not in copies, 'Pipeline archive mapping is duplicate or non-exact')
        path = bind(root, item.get('path'), item.get('sha256'), hashes)
        require(path.stat().st_size == item.get('bytes'), 'Pipeline archive byte count differs')
        copies[item['originalPath']] = item

    def archived(original, expected):
        item = copies.get(original)
        require(item is not None and item['sha256'] == expected, 'Missing exact portable copy of measured pipeline artifact: ' + str(original))
        return file(root, item['path'])

    baseline_binding = result.get('baselineBinding', {})
    baseline_path = archived(baseline_binding.get('path'), baseline_binding.get('sha256'))
    baseline = json.loads(baseline_path.read_text())
    require(baseline.get('passed') is False and baseline.get('firstMismatch', {}).get('index') == 0,
            'Rejected all-four route was relabeled or lost')
    rejected = read_bound(root, archive.get('classifierFourFailureReceipt'), hashes)
    require(rejected.get('passed') is False and rejected.get('firstMismatch', {}).get('index') == 337
            and rejected['firstMismatch']['candidate']['modelPath'] == '/analysis/models/frame-mn10-singing.onnx',
            'Rejected four-thread classifier evidence was relabeled or lost')
    require(baseline.get('sourceHashes') == baseline_binding.get('originalSourceHashes'), 'Original executed source binding differs')
    baseline_folder = baseline_path.parent
    for source, expected in baseline['sourceHashes'].items():
        snapshot = baseline_folder / 'executed-source' / source
        if snapshot.is_file():
            bind(root, snapshot.relative_to(root).as_posix(), expected, hashes)
        else:
            require(source.startswith(('web/analysis/models/', 'web/analysis/vendor/')), 'Original executable source snapshot missing: ' + source)
            bind(root, source, expected, hashes)
    sources = result.get('sourceHashes', {})
    required = {'web/analysis/worker.js', 'web/analysis/analyzer.js', 'web/analysis/game.js', 'web/analysis/vocal.js',
                'web/analysis/separator-deux.js', 'web/analysis/work-store.js', 'web/analysis/stem-cache.js',
                'web/analysis/ASSET_MANIFEST.json', 'web/analysis/vendor/ort.wasm.min.js',
                'web/analysis/vendor/ort-wasm-simd-threaded.mjs', 'web/analysis/vendor/ort-wasm-simd-threaded.wasm'}
    require(isinstance(sources, dict) and required <= set(sources), 'Final pipeline proof omits executed current source/runtime bytes')
    for source, expected in sources.items():
        bind(root, source, expected, hashes)
    harness = result.get('harness', {})
    archived(harness.get('path'), harness.get('sha256'))
    archived(harness.get('bootstrapPath'), harness.get('bootstrapSha256'))
    input = result.get('input', {})
    require(input == baseline.get('input') and input.get('sampleBytesUnchanged') is True
            and input.get('sampleRate') == 44100 and input.get('channels') == 2 and input.get('frames') == 132300
            and input.get('firstFrame') == 0 and input.get('seconds') == 3 and input.get('dataBytes') == 1058400,
            'Pipeline input source clock or byte-preserving construction differs')
    original = bind(root, 'qa/release-1.6.0/fixtures/falcon-mix.wav', input.get('sourceSha256'), hashes).read_bytes()
    offset, count = input.get('sourceDataOffset'), input['dataBytes']
    require(type(offset) is int and offset >= 12 and original[:4] == b'RIFF' and original[8:12] == b'WAVE'
            and original[offset - 8:offset - 4] == b'data' and offset + count <= len(original), 'Original WAV prefix geometry differs')
    prefix = original[offset:offset + count]
    require(hashlib.sha256(prefix).hexdigest() == input.get('dataSha256') == input.get('sourcePrefixDataSha256'), 'Pipeline source PCM bytes differ')
    fixture = bytearray(original[:offset] + prefix)
    struct.pack_into('<I', fixture, 4, len(fixture) - 8)
    struct.pack_into('<I', fixture, offset - 4, count)
    require(hashlib.sha256(fixture).hexdigest() == input.get('fixtureSha256'), 'Pipeline fixture SHA cannot be reproduced from unchanged source bytes')
    one, final = result.get('runs', {}).get('1', {}), result.get('runs', {}).get('4', {})
    require(one == baseline.get('runs', {}).get('1'), 'Original one-thread execution was changed when reused as the reference')
    expected_models = {'/analysis/models/beat-this-mel.onnx': 1, '/analysis/models/beat-this-large.onnx': 1,
                       '/analysis/models/deux/front.onnx': 1, '/analysis/models/deux/head-0.onnx': 11,
                       '/analysis/models/deux/head-1.onnx': 11, '/analysis/models/frame-mn10-singing.onnx': 1}
    for layer in range(12):
        for kind, calls in [('time', 15), ('frequency', 11)]:
            expected_models[f'/analysis/models/deux/block-{layer:02d}-{kind}.onnx'] = calls
    expected_models.update({'/analysis/models/game/' + name + '.onnx': 8 if name == 'segmenter' else 1
                            for name in ['encoder', 'dur2bd', 'segmenter', 'bd2dur', 'estimator']})
    widths = {'float32': 4, 'float64': 8, 'float16': 2, 'bfloat16': 2, 'int64': 8, 'uint64': 8,
              'int32': 4, 'uint32': 4, 'int16': 2, 'uint16': 2, 'int8': 1, 'uint8': 1, 'bool': 1}
    for run, is_final in [(one, False), (final, True)]:
        graphs = run.get('graphs', [])
        require(len(graphs) == 350 and dict(collections.Counter(row.get('modelPath') for row in graphs)) == expected_models,
                'Full 350-call model/step coverage is missing')
        sessions = run.get('sessions', [])
        require(len(sessions) == 35 and {row.get('modelPath') for row in sessions} == set(expected_models), 'Full model-session coverage differs')
        for row in [*sessions, *graphs]:
            expected = expected_threads.get(row.get('stage')) if is_final else 1
            require(expected is not None and row.get('threads') == expected, 'An executed model used unqualified thread selection')
            if row in sessions:
                require(row.get('crossOriginIsolated') is True and row.get('sharedArrayBuffer') is True, 'Model session lacks actual shared-memory context evidence')
            else:
                require(row.get('inputs') and row.get('outputs'), 'Raw model inputs or outputs are missing')
                for tensor in [*row['inputs'].values(), *row['outputs'].values()]:
                    dims = tensor.get('dims')
                    require(isinstance(dims, list) and all(type(n) is int and n >= 0 for n in dims)
                            and tensor.get('type') in widths and tensor.get('bytes') == math.prod(dims) * widths[tensor['type']]
                            and isinstance(tensor.get('sha256'), str) and re.fullmatch('[a-f0-9]{64}', tensor['sha256']),
                            'Malformed raw pipeline tensor fingerprint')
        music = run.get('analysis', {}).get('music', {})
        require(set(music.get('engine', {}).get('stages', {})) == {'rhythm', 'separation', 'voice', 'bass'}
                and all(value.get('restored') is False for value in music['engine']['stages'].values())
                and music.get('separation', {}).get('restoredPassages') == 0 and music.get('vocals', {}).get('transcription', {}).get('steps') == 8,
                'Pipeline qualification restored prior work or changed transcription settings')
    require(any(row.get('stage') == 'voice-classifier' and row.get('modelPath') == '/analysis/models/frame-mn10-singing.onnx' for row in final['graphs']),
            'Final private classifier did not actually run')
    for before, after in zip(one['graphs'], final['graphs']):
        require(all(before[key] == after[key] for key in ['modelPath', 'call', 'inputs', 'outputs'])
                and before['stage'] == ('voice' if after['stage'] == 'voice-classifier' else after['stage']),
                'A final pipeline graph input/output or invocation differs')
    excluded = ['separation.analysisSeconds', 'engine.analysisSeconds', 'engine.separationModel.analysisSeconds',
                'engine.stages.rhythm.seconds', 'engine.stages.separation.seconds', 'engine.stages.voice.seconds',
                'engine.stages.bass.seconds', 'stemCache.createdAt']
    comparison = result.get('finalComparison', {})
    require(comparison.get('excludedPaths') == excluded and comparison.get('graphCalls') == 350
            and comparison.get('allGraphInputsOutputsExact') is True and comparison.get('musicalFieldsExact') is True,
            'Final music comparison coverage differs')
    def musical(value):
        copied = json.loads(json.dumps(value))
        for dotted in excluded:
            parts = dotted.split('.')
            at = copied
            for key in parts[:-1]:
                at = at[key]
            del at[parts[-1]]
        return json.dumps(copied, separators=(',', ':'), sort_keys=True, ensure_ascii=False)
    require(musical(one['analysis']['music']) == musical(final['analysis']['music'])
            and one['analysis']['stemHashes'] == final['analysis']['stemHashes']
            and one['analysis']['fullVoiceSamples'] == final['analysis']['fullVoiceSamples'] == 132300,
            'Final musical output or source stem bytes differ')
    return {'scope': result['scope'], 'graph_calls': 350, 'timing_valid': False,
            'limitations': ['Host Chromium raw-output qualification on a three-second source prefix; actual Android bootstrap/GAME and full-browser gates remain separate.',
                           'Original failed four-thread beat/classifier routes remain historical and excluded.',
                           'Recorded model durations are instrumented and not controlled performance or physical-phone claims.']}


def verify_android_threads(root, relative, assets, hashes):
    result = read_bound(root, relative, hashes)
    passed(result, 'Actual Android one-heap WASM thread qualification')
    require(result.get('diagnostic_only') is True, 'Actual Android proof must retain its diagnostic scope')
    folder = Path(relative).parent
    provenance = json.loads(bind(root, (folder / 'provenance.json').as_posix(), result.get('provenance_sha256'), hashes).read_text())
    require(provenance.get('prepared') is True and provenance.get('diagnostic_only') is True
            and provenance.get('release_eligible') is False and provenance.get('signing_key_destroyed') is True
            and provenance.get('diagnostic_version') == {'name': '2.2.5', 'code': 20205}, 'Android diagnostic build identity incomplete')
    require(provenance.get('input_head_sha') == '57e6ee996bd8f9d135e89334585efe90d8667b68'
            and provenance.get('input_run_id') == 34424617050 and provenance.get('input_run_conclusion') == 'success'
            and provenance.get('input_apk_sha256') == '5620e784909b8fd14a4fb0e86c097f4acfe146f1b0a32681b1611015ef2c03d7',
            'Android models did not originate from the reviewed complete 2.2.4 CI build')
    sources = provenance.get('source_hashes', {})
    required = {'version.json', 'android/androidx-runtime.json', 'android/native-runtime.json',
                'android/src/com/cyberbasslord/lightforge/WebViewIsolation.java',
                'android/src/com/cyberbasslord/lightforge/WebViewFileTransport.java',
                'android/src/com/cyberbasslord/lightforge/MainActivity.java',
                'android/src/com/cyberbasslord/lightforge/AnalysisService.java',
                'web/analysis/worker.js', 'web/analysis/analyzer.js', 'web/analysis/game.js',
                'tools/prepare_wasm_thread_probe.py', 'tools/verify_wasm_thread_report.py',
                'tests/android/WasmThreadProbe.java', 'tests/android/wasm-thread-probe.js'}
    require(isinstance(sources, dict) and required <= set(sources), 'Android thread proof omits final app/rig source bindings')
    for source, expected in sources.items():
        bind(root, source, expected, hashes)
    old_path = list(sys.path)
    try:
        sys.path.insert(0, str(root / 'tools'))
        spec = importlib.util.spec_from_file_location('lightforge_wasm_thread_receipt', file(root, 'tools/prepare_wasm_thread_probe.py'))
        collector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(collector)
        require(collector.source_hashes() == sources, 'Android thread source coverage or bytes changed after execution')
        phases = result.get('phases', {})
        require(set(phases) == {'stock', 'modern'}, 'Both actual provider phases are required')
        for mode in ['stock', 'modern']:
            require(collector.validate_report(phases[mode], mode, provenance) == result.get('assertions', {}).get(mode),
                    'Android phase raw validation differs: ' + mode)
            log = read_bound_text(root, (folder / ('instrumentation-' + mode + '.log')).as_posix(), hashes)
            reports = [json.loads(line.split('WASM_THREAD_RESULT ', 1)[1]) for line in log.splitlines() if 'WASM_THREAD_RESULT ' in line]
            require(reports == [phases[mode]] and sum(line.strip() == 'WASM_THREAD_PASS' for line in log.splitlines()) == 1,
                    'Actual Android log does not retain exactly the validated phase: ' + mode)
        from verify_wasm_thread_report import validate_pair
        require(validate_pair(phases['stock'], phases['modern']) == result.get('pair_assertions'), 'Android provider-pair validation differs')
        provider = provenance.get('provider', {})
        require(provider.get('apk_sha256') == collector.PROVIDER_SHA256 and provider.get('apk_bytes') == collector.PROVIDER_BYTES
                and provider.get('version') == collector.PROVIDER_VERSION and provider.get('certificate_sha256') == collector.PROVIDER_CERTIFICATE
                and provider.get('official_chromium_snapshot') is True and provider.get('google_play_release_signed') is False,
                'Android provider provenance differs from the pinned official diagnostic image')
    finally:
        sys.path[:] = old_path
    before = read_bound(root, (folder / 'input-payloads.json').as_posix(), hashes)
    after = read_bound(root, (folder / 'diagnostic-payloads.json').as_posix(), hashes)
    replacements = provenance.get('replacement_entries', {})
    require(isinstance(replacements, dict) and replacements and set(before) <= set(after)
            and set(after) == set(before) | set(replacements), 'Android payload inventory has unreviewed additions/removals')
    for entry, metadata in after.items():
        if entry in replacements:
            require(all(metadata.get(key) == value for key, value in replacements[entry].items()), 'Android rebuilt payload differs: ' + entry)
        else:
            require(metadata == before[entry], 'Android unchanged payload differs: ' + entry)
    for source, expected in assets.items():
        if source.startswith(('web/analysis/models/', 'web/analysis/vendor/')):
            entry = 'assets/' + source.removeprefix('web/')
            require(after.get(entry) == before.get(entry) and after.get(entry, {}).get('sha256') == expected,
                    'Android loaded altered model/configuration/runtime bytes: ' + source)
    for source, expected in sources.items():
        if source.startswith('web/'):
            require(after.get('assets/' + source.removeprefix('web/'), {}).get('sha256') == expected, 'Android packaged stale web source: ' + source)
    require(result.get('same_app_and_instrumentation') is True and result.get('app_reinstalled_between_phases') is False
            and result.get('app_data_cleared') is False, 'Provider qualification did not preserve the same app/default-profile data')
    capacity = read_bound(root, (folder / 'host-capacity.json').as_posix(), hashes)
    require(capacity == result.get('hostCapacity') and capacity.get('passed') is True
            and capacity.get('configuredGuestMemoryMiB') == 4096 and capacity.get('configuredGuestCores') == 8
            and capacity.get('swapTotalBytes') == 0, 'Observed Android diagnostic host/guest capacity differs')
    safety, memory = result.get('hostSafety', {}), result.get('memory', {})
    require(type(safety.get('samples')) is int and safety['samples'] >= 2 and safety.get('errors') == []
            and safety.get('reserveBytes') == 1610612736 and safety.get('minimumAvailableBytes', 0) >= 1610612736
            and not safety.get('emulatorStopped'), 'Android host memory/swap guard failed')
    require(type(memory.get('samples')) is int and memory['samples'] >= 2
            and type(memory.get('renderer_samples')) is int and memory['renderer_samples'] >= 1,
            'Actual Android system/renderer observations incomplete')
    return {'scope': result['scope'], 'limitations': ['Actual API35 emulator with stock124 and pinned official155 provider; not the user\'s physical phone.',
            'The Android rig exercises the packaged selector and direct fresh GAME graph sequence; complete production classifier handoff is covered separately.',
            'Instrumented timings and guest CPU configuration are not physical-phone performance evidence.']}


def verify_thread_policy(root, relative, hashes):
    result = read_bound(root, relative, hashes)
    passed(result, 'Current Android thread/pool policy behavior')
    require(result.get('schema') == 'lightforge-wasm-thread-policy-1' and result.get('release') == '2.2.5'
            and result.get('poolShipping') is False, 'Thread policy proof identity changed')
    required = {'version.json', 'web/analysis/worker.js', 'web/analysis/analyzer.js',
                'web/analysis/game.js', 'web/analysis/game-worker.js', 'web/background/runner.js',
                'tests/analysis-thread-policy.test.cjs', 'qa/speedup-exact/wasm-policy/verify.py'}
    sources = result.get('source_hashes', {})
    require(isinstance(sources, dict) and required <= set(sources), 'Thread policy proof omits current production/test sources')
    for source, expected in sources.items():
        bind(root, source, expected, hashes)
    test = result.get('tests', {})
    require(test.get('command') == ['node', '--test', '--test-reporter=tap', 'tests/analysis-thread-policy.test.cjs']
            and test.get('exitCode') == 0 and type(test.get('tests')) is int and test['tests'] >= 12
            and test.get('pass') == test['tests'] and all(test.get(name) == 0 for name in ['fail', 'cancelled', 'skipped', 'todo']),
            'Current thread policy and dormant-pool behavior suite did not pass completely')
    metadata = test.get('log', {})
    log = bind(root, metadata.get('path'), metadata.get('sha256'), hashes)
    require(log.stat().st_size == metadata.get('bytes'), 'Thread policy test log byte count changed')
    for name in ['tests', 'pass', 'fail', 'cancelled', 'skipped', 'todo']:
        require(re.findall(r'^# ' + name + r' (\d+)$', log.read_text(), re.M) == [str(test[name])],
                'Thread policy test log and summary differ: ' + name)
    decision_path = 'qa/speedup-exact/game-pool/release-decision.json'
    decision = read_bound(root, decision_path, hashes)
    require(decision.get('schema') == 'lightforge-game-pool-release-decision-1'
            and decision.get('release') == '2.2.5' and decision.get('shipping') is False
            and decision.get('targetQualification') == 'unqualified', 'Experimental GAME pool shipping decision changed')
    activation = decision.get('activation', {})
    require(activation == {'source': 'web/analysis/worker.js', 'sha256': sources['web/analysis/worker.js'],
                           'constant': 'GAME_PASSAGE_POOL_ENABLED', 'value': False}, 'Dormant GAME activation binding changed')
    require('const GAME_PASSAGE_POOL_ENABLED=false;' in file(root, 'web/analysis/worker.js').read_text(),
            'Production GAME pool is no longer explicitly disabled')
    require(decision.get('currentBehaviorProof') == {'path': relative, 'sha256': hashes[relative]},
            'Pool nonshipping decision is not bound to the current behavior proof')
    history = decision.get('historicalEvidence', [])
    require(isinstance(history, list) and len(history) >= 3, 'Original pool/resource experiment history missing')
    for item in history:
        old = json.loads(bind(root, item.get('path'), item.get('sha256'), hashes).read_text())
        require(old.get('passed') == item.get('passed') and 'Historical' in item.get('bindingScope', ''),
                'Original experimental pool evidence was relabeled')
    return {'shipping': False, 'target_qualification': 'unqualified', 'decision_path': decision_path,
            'decision_sha256': hashes[decision_path], 'behavior_proof': relative,
            'scope': result['scope'], 'limitations': ['Mocked graph outputs prove routing only; exact model and Android runtime qualification are separate.']}


def read_bound_text(root, relative, hashes):
    path = file(root, relative)
    hashes[relative] = digest(path)
    return path.read_text()


def verify_release(root=ROOT):
    root = Path(root).resolve()
    hashes = {}
    version = read_bound(root, 'version.json', hashes)
    require(version == {'name': '2.2.5', 'code': 20205}, 'This protocol belongs only to 2.2.5 / 20205')
    inputs = read_bound(root, OUT + 'proof-inputs.json', hashes)
    require(inputs.get('release') == '2.2.5' and set(inputs) == {'release', 'mdx_fft', 'role_cache', 'game_pool_android'},
            'Release proof input coverage changed')
    hashes[OUT + 'verify-analysis.py'] = digest(file(root, OUT + 'verify-analysis.py'))
    historical = verify_historical(root, hashes)
    assets = verify_assets(root, historical, hashes)
    clock = verify_clock(root, hashes)
    fft = verify_fft(root, inputs['mdx_fft'], historical, hashes)
    native_experiment = verify_unqualified_native_experiment(root, historical, hashes)
    cache = verify_cache(root, inputs['role_cache'], historical, hashes)
    game = verify_game_pool(root, inputs['game_pool_android'], assets, hashes)
    for relative, expected in {**hashes, **assets}.items():
        require(digest(file(root, relative)) == expected, 'Input changed during verification: ' + relative)
    return {
        'release': '2.2.5', 'passed': True, 'errors': [], 'source_hashes': hashes, 'analysis_asset_hashes': assets,
        'scope': 'Current exact-output optimization proofs, fresh production source-clock boundaries, complete current asset inventory, and explicitly historical unchanged-model evidence. Current full-browser and Android lifecycle gates remain separate.',
        'checks': [
            'All current analysis assets match their complete inventory; model weights, model configuration and ORT Web bytes match the published 2.2.4 evidence.',
            'Current MDX FFT encoding and decoding match every consumed float32 value on three real inputs and a deterministic edge-value stress input.',
            'NativeDeux, its transform, runtime, and source test retain the published 2.2.4 bindings; the unqualified eight-thread experiment is excluded from shipping.',
            'Current role-cache composition preserves fresh and edited-rhythm JSON exactly, including warnings and model metadata; complete recovery tests pass.',
            'Current Android GAME pool qualification passed with exact production model outputs, unchanged steps, child execution, cancellation and durable retry protection.',
            'Fresh 2.2.5 source-clock regression preserves all 932143 samples across four overlapping passages.',
        ],
        'fresh_source_clock': clock,
        'exact_optimization_proofs': {key: {'path': inputs[key], 'sha256': hashes[inputs[key]]} for key in ['mdx_fft', 'role_cache', 'game_pool_android']},
        'historical_model_evidence': {'release': '2.2.4', 'path': HISTORICAL, 'sha256': HISTORICAL_SHA256, 'status': 'Historical; not rerun or rebound to changed source',
            'spectral_diagnostic_passed': False, 'scope': historical['scope']},
        'unqualified_experiments': {'native_eight_threads': native_experiment},
        'timing_limits': {'mdx_fft_timing_valid': fft.get('timing_valid'), 'mdx_fft_timing_limitation': fft.get('timing_limitation'),
            'cache': cache.get('limits'), 'game': game.get('limitations')},
        'limitations': ['No historical measurement is represented as current execution.', 'No new corpus accuracy benchmark or physical-phone speed claim is made.',
                       'The new transformations and scheduling changes require exact output identity; historical MDX cross-runtime spectral differences and failed protocols remain preserved.'],
        'completedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def main():
    output = ROOT / OUT / 'analysis-verification.json'
    try:
        receipt = verify_release()
    except Exception as error:
        atomic_json(output, {'release': '2.2.5', 'passed': False, 'errors': [str(error)],
                            'status': 'Pending or failed current qualification; release is blocked',
                            'completedAt': datetime.datetime.now(datetime.timezone.utc).isoformat()})
        raise
    atomic_json(output, receipt)
    print(json.dumps({'release': receipt['release'], 'passed': True, 'checks': receipt['checks']}, indent=2))


if __name__ == '__main__':
    main()
