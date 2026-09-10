#!/usr/bin/env python3
"""Qualify 2.2.5 optimizations with current exact-output proofs.

Historical 2.2.4 numerical/quality evidence is retained as historical. It is
never rebound to changed production code or represented as a fresh execution.
Missing or unfinished qualification inputs fail this gate and replace any old
passing output. The existing seven release gates remain required separately.
"""
from pathlib import Path
import datetime
import hashlib
import json
import math
import os
import re
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
NATIVE_SOURCES = {
    'android/src/com/cyberbasslord/lightforge/NativeDeux.java',
    'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java',
    'tests/NativeDeuxTest.java', 'android/native-runtime.json',
    'web/analysis/models/deux/manifest.json', 'web/demo/glass-castle.wav',
    'qa/release-1.6.0/fixtures/falcon-mix.wav',
    'qa/speedup-exact/native-threads/reference/NativeDeux.java',
    'qa/speedup-exact/native-threads/reference/NativeDeuxTest.java',
    'qa/speedup-exact/native-threads/verify.py',
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
    for relative in ['android/native-runtime.json', 'android/src/com/cyberbasslord/lightforge/NativeMdxTask.java',
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


def verify_native(root, relative, historical, hashes):
    result = read_bound(root, relative, hashes)
    passed(result, 'Current native thread comparison')
    require(result.get('policyAndTransformChecksPassed') is True and set(result.get('sourceHashes', {})) == NATIVE_SOURCES,
            'Native policy or source coverage changed')
    for source, expected in result['sourceHashes'].items():
        bind(root, source, expected, hashes)
    require(result['sourceHashes']['qa/speedup-exact/native-threads/reference/NativeDeux.java'] == historical['source_hashes']['android/src/com/cyberbasslord/lightforge/NativeDeux.java'],
            'Native reference is not the released predictor')
    require((result.get('sampleRate'), result.get('contextSamples'), result.get('samplesPerStem'), result.get('outputBytes'), result.get('startSample')) == (44100, 573300, 573300, 4586400, -66150),
            'Native comparison sample geometry changed')
    manifest = json.loads(file(root, 'web/analysis/models/deux/manifest.json').read_text())
    require(result.get('modelHashes') == {name: item['sha256'] for name, item in manifest['files'].items()}, 'Native comparison graph identity changed')
    runtime = json.loads(file(root, 'android/native-runtime.json').read_text())
    require(result.get('host', {}).get('runtimeJarSha256') == runtime['host']['sha256'], 'Native comparison ORT identity changed')
    fixtures = result.get('fixtures', [])
    require([item.get('id') for item in fixtures] == ['demo-start', 'falcon-start'], 'Native real-input coverage changed')
    for item in fixtures:
        require(item.get('byteIdentical') is True and item.get('maxAbsoluteError') == 0 and item.get('rmse') == 0,
                'Native output is not exact')
        runs = item.get('runs', {})
        require(set(runs) == {'baseline', 'candidate'}, 'Incomplete native pair')
        require(runs['baseline'].get('sha256') == runs['candidate'].get('sha256'), 'Native output digests differ')
        for name, threads in [('baseline', 4), ('candidate', 8)]:
            run = runs[name]
            require(run.get('outputBytes') == 4586400 and run.get('samplesPerStem') == 573300
                    and type(run.get('actualAvailableCores')) is int and run['actualAvailableCores'] >= 8 and run.get('selectedIntraOpThreads') == threads,
                    'Native comparison did not exercise the required production thread policies')
            require(isinstance(run.get('sha256'), str) and re.fullmatch(r'[a-f0-9]{64}', run['sha256']), 'Native output hash missing')
            log_path = (Path(relative).parent / (item['id'] + '-' + name + '.log')).as_posix()
            log = bind(root, log_path, run.get('logSha256'), hashes).read_text()
            metrics = [json.loads(line) for line in log.splitlines() if line.startswith('{"seconds":')]
            require(len(metrics) == 1 and metrics[0].get('sha256') == run['sha256']
                    and metrics[0].get('samplesPerStem') == 573300 and metrics[0].get('seconds') == run.get('seconds'),
                    'Native retained execution log disagrees with receipt')
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


def verify_game_pool(root, relative, hashes):
    require(relative is not None, 'Pending: actual Android GAME pool qualification receipt and provenance have not arrived')
    # The Android rig's final on-device receipt schema must be reviewed before
    # this adapter is completed. Standalone Node-process scheduling exploration
    # does not qualify the shipped game-worker.js adapter.
    file(root, relative)
    raise ValueError('Pending: bind and validate the actual Android GAME pool receipt schema before release')


def verify_release(root=ROOT):
    root = Path(root).resolve()
    hashes = {}
    version = read_bound(root, 'version.json', hashes)
    require(version == {'name': '2.2.5', 'code': 20205}, 'This protocol belongs only to 2.2.5 / 20205')
    inputs = read_bound(root, OUT + 'proof-inputs.json', hashes)
    require(inputs.get('release') == '2.2.5' and set(inputs) == {'release', 'mdx_fft', 'role_cache', 'native_threads', 'game_pool_android'},
            'Release proof input coverage changed')
    hashes[OUT + 'verify-analysis.py'] = digest(file(root, OUT + 'verify-analysis.py'))
    historical = verify_historical(root, hashes)
    assets = verify_assets(root, historical, hashes)
    clock = verify_clock(root, hashes)
    fft = verify_fft(root, inputs['mdx_fft'], historical, hashes)
    native = verify_native(root, inputs['native_threads'], historical, hashes)
    cache = verify_cache(root, inputs['role_cache'], historical, hashes)
    game = verify_game_pool(root, inputs['game_pool_android'], hashes)
    for relative, expected in {**hashes, **assets}.items():
        require(digest(file(root, relative)) == expected, 'Input changed during verification: ' + relative)
    return {
        'release': '2.2.5', 'passed': True, 'errors': [], 'source_hashes': hashes, 'analysis_asset_hashes': assets,
        'scope': 'Current exact-output optimization proofs, fresh production source-clock boundaries, complete current asset inventory, and explicitly historical unchanged-model evidence. Current full-browser and Android lifecycle gates remain separate.',
        'checks': [
            'All current analysis assets match their complete inventory; model weights, model configuration and ORT Web bytes match the published 2.2.4 evidence.',
            'Current MDX FFT encoding and decoding match every consumed float32 value on three real inputs and a deterministic edge-value stress input.',
            'Current NativeDeux 4-thread reference and production 8-thread policy return byte-identical complete stereo-role outputs on two real inputs.',
            'Current role-cache composition preserves fresh and edited-rhythm JSON exactly, including warnings and model metadata; complete recovery tests pass.',
            'Current Android GAME pool qualification passed with exact production model outputs, unchanged steps, child execution, cancellation and durable retry protection.',
            'Fresh 2.2.5 source-clock regression preserves all 932143 samples across four overlapping passages.',
        ],
        'fresh_source_clock': clock,
        'exact_optimization_proofs': {key: {'path': inputs[key], 'sha256': hashes[inputs[key]]} for key in ['mdx_fft', 'role_cache', 'native_threads', 'game_pool_android']},
        'historical_model_evidence': {'release': '2.2.4', 'path': HISTORICAL, 'sha256': HISTORICAL_SHA256, 'status': 'Historical; not rerun or rebound to changed source',
            'spectral_diagnostic_passed': False, 'scope': historical['scope']},
        'timing_limits': {'mdx_fft_timing_valid': fft.get('timing_valid'), 'mdx_fft_timing_limitation': fft.get('timing_limitation'),
            'native': native.get('limitations'), 'cache': cache.get('limits'), 'game': game.get('limitations')},
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
