#!/usr/bin/env python3
"""Bind 2.2.3's fresh native runtime comparison and source-clock evidence.

The old 2.2.2 retention protocol is intentionally not reused: native ORT has
changed. This gate proves the newly measured host prediction comparison,
unchanged bundled analysis assets, and a fresh source-clock regression. It
does not claim a new corpus accuracy benchmark or an ARM64 crash reproduction.
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
OUT = 'qa/release-2.2.3/'
COMPARISON_SHA256 = 'e4bb8b11f1abaf1e541967f07695290a097f634eee20a38a813b3f0b1a88a63f'
ASSET_MANIFEST_SHA256 = '3757b3406d2e78f5c787a76d76320dc86d7124484468f891e7477eb16e883431'
OLD_RUNTIME_SHA256 = 'e0ab4a1af57d2da09097202f2dfd691e390c82e81183314788ccde4cf7c3cc38'
NEW_RUNTIME_SHA256 = '749793ebed63743fec853d093da7987a86ea5cd592d54fba898cd3233100c381'
SAMPLES = 573300
THRESHOLDS = {'max_absolute_error': 1e-4, 'rmse': 1e-5, 'relative_rmse': 1e-3}
COMPARISON_SOURCES = {
    'android/src/com/cyberbasslord/lightforge/NativeDeux.java',
    'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java',
    'tests/NativeDeuxTest.java', 'android/native-runtime.json',
    'web/analysis/models/deux/manifest.json', 'web/demo/glass-castle.wav',
    OUT + 'compare-native-runtime.py',
}
CLOCK_SOURCES = {
    'web/analysis/separator-deux.js', 'web/analysis/dsp.js',
    'web/analysis/models/deux/manifest.json', OUT + 'test-source-clock.cjs',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def file(root, relative):
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute(), 'Invalid source path')
    path = (root / relative).resolve()
    require(path.is_relative_to(root) and path.is_file() and path.relative_to(root).as_posix() == relative,
            'Missing, noncanonical or external source: ' + relative)
    return path


def bind(root, relative, expected, hashes):
    require(isinstance(expected, str) and re.fullmatch(r'[0-9a-f]{64}', expected), 'Invalid source hash: ' + relative)
    path = file(root, relative)
    actual = digest(path)
    require(actual == expected, 'Source differs from measured evidence: ' + relative)
    hashes[relative] = actual
    return path


def finite_number(value):
    return type(value) in {int, float} and math.isfinite(value)


def verify_comparison(root, hashes):
    path = bind(root, OUT + 'native-runtime-comparison-verification.json', COMPARISON_SHA256, hashes)
    result = json.loads(path.read_text())
    require(result.get('release') == '2.2.3' and result.get('passed') is True and not result.get('failure'),
            'Current native runtime comparison did not pass')
    require(set(result.get('source_hashes', {})) == COMPARISON_SOURCES, 'Native comparison source coverage changed')
    for relative, expected in result['source_hashes'].items():
        bind(root, relative, expected, hashes)
    require(result.get('start_sample') == -66150 and result.get('sample_rate') == 44100 and
            result.get('samples_per_stem') == SAMPLES, 'Native comparison does not cover the reported passage boundary')
    require(result.get('thresholds') == THRESHOLDS, 'Native comparison thresholds changed')
    runtime = json.loads(file(root, 'android/native-runtime.json').read_text())
    require(runtime.get('version') == '1.25.1' and runtime['host']['sha256'] == NEW_RUNTIME_SHA256 and
            runtime['host']['bytes'] == 41804437, 'Current native runtime pins changed')
    runs = result.get('runs', [])
    require(len(runs) == 2 and [run.get('version') for run in runs] == ['1.23.2', '1.25.1'],
            'Native comparison versions changed')
    for run, expected, size in zip(runs, [OLD_RUNTIME_SHA256, NEW_RUNTIME_SHA256], [75255976, 41804437]):
        require(run.get('runtime_jar_sha256') == expected and run.get('runtime_jar_bytes') == size,
                'Native comparison runtime identity changed')
        require(run.get('samplesPerStem') == SAMPLES and run.get('output_bytes') == 2 * SAMPLES * 4,
                'Native comparison output is incomplete')
        require(finite_number(run.get('seconds')) and run['seconds'] > 0 and
                type(run.get('peakRssBytes')) is int and run['peakRssBytes'] > 0 and
                isinstance(run.get('sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', run['sha256']),
                'Native comparison output metadata is invalid')
    stems = result.get('comparison', [])
    require(len(stems) == 2 and [stem.get('stem') for stem in stems] == ['vocals', 'accompaniment'],
            'Native comparison stem coverage changed')
    for stem in stems:
        require(stem.get('finite') is True and stem.get('samples') == SAMPLES, 'Native comparison contains invalid samples')
        for key, limit in THRESHOLDS.items():
            value = stem.get(key)
            require(finite_number(value) and 0 <= value <= limit, 'Native comparison numerical threshold failed: ' + key)
        require(not stem.get('identical') or stem['max_absolute_error'] == 0, 'Native comparison identity assertion conflicts with metrics')
    if all(stem.get('identical') for stem in stems):
        require(runs[0]['sha256'] == runs[1]['sha256'], 'Identical native predictions have different digests')
    model_files = json.loads(file(root, 'web/analysis/models/deux/manifest.json').read_text())['files']
    expected_models = {'web/analysis/models/deux/' + name: item['sha256'] for name, item in model_files.items()}
    require(len(expected_models) == 27 and result.get('model_asset_hashes') == expected_models,
            'Native comparison model inventory differs from current Deux models')
    return result


def verify_asset(root, relative, metadata, hashes):
    require(isinstance(metadata, dict) and set(metadata) == {'bytes', 'sha256'} and
            type(metadata['bytes']) is int and metadata['bytes'] > 0, 'Invalid asset metadata: ' + relative)
    path = bind(root, 'web/analysis/' + relative, metadata['sha256'], hashes)
    require(path.stat().st_size == metadata['bytes'], 'Analysis asset byte count changed: ' + relative)


def verify_assets(root, hashes):
    manifest_path = bind(root, 'web/analysis/ASSET_MANIFEST.json', ASSET_MANIFEST_SHA256, hashes)
    manifest = json.loads(manifest_path.read_text())
    require(len(manifest) == 73, 'Analysis asset inventory changed')
    base = root / 'web/analysis'
    actual = {path.relative_to(base).as_posix() for path in base.rglob('*') if path.is_file()
              and path.name != 'ASSET_MANIFEST.json' and
              not any(part.startswith('.') or part == '__pycache__' for part in path.relative_to(base).parts)}
    require(actual == set(manifest), 'Installed analysis inventory differs from the reviewed manifest')
    assets = {}
    for relative, metadata in manifest.items():
        verify_asset(root, relative, metadata, assets)
    for model in ['deux', 'game']:
        directory = base / 'models' / model
        expected = set(json.loads((directory / 'manifest.json').read_text())['files'])
        actual_graphs = {path.relative_to(directory).as_posix() for path in directory.rglob('*.onnx')}
        require({name for name in expected if name.endswith('.onnx')} == actual_graphs,
                'Model graph inventory changed: ' + model)
        # These manifests are tracked source; generated ONNX files remain asset bindings.
        relative = 'web/analysis/models/' + model + '/manifest.json'
        hashes[relative] = assets[relative]
    return assets


def verify_clock(root, hashes):
    relative = OUT + 'source-clock-verification.json'
    path = file(root, relative)
    result = json.loads(path.read_text())
    require(result.get('release') == '2.2.3' and result.get('passed') is True and not result.get('errors'),
            'Fresh 2.2.3 source-clock check did not pass')
    require(result.get('samples') == 932143 and result.get('chunks') == 4 and
            result.get('contiguousSourceSamples') is True and result.get('monotonicProgress') is True and
            finite_number(result.get('maxAbsError')) and 0 <= result['maxAbsError'] < 2e-6,
            'Fresh source-clock boundaries failed')
    require(set(result.get('source_hashes', {})) == CLOCK_SOURCES, 'Fresh source-clock source coverage changed')
    for source, expected in result['source_hashes'].items():
        bind(root, source, expected, hashes)
    hashes[relative] = digest(path)
    return result


def verify_release(root=ROOT):
    root = Path(root).resolve()
    version_path = file(root, 'version.json')
    require(json.loads(version_path.read_text()) == {'name': '2.2.3', 'code': 20203},
            'This evidence protocol belongs only to 2.2.3 / 20203')
    hashes = {'version.json': digest(version_path)}
    comparison = verify_comparison(root, hashes)
    assets = verify_assets(root, hashes)
    clock = verify_clock(root, hashes)
    hashes[OUT + 'verify-analysis.py'] = digest(file(root, OUT + 'verify-analysis.py'))
    for relative, expected in {**hashes, **assets}.items():
        require(digest(file(root, relative)) == expected, 'Source changed during analysis verification: ' + relative)
    return {
        'release': '2.2.3', 'passed': True, 'errors': [], 'source_hashes': hashes,
        'analysis_asset_hashes': assets,
        'analysis_asset_binding': {'manifest_path': 'web/analysis/ASSET_MANIFEST.json',
            'manifest_sha256': ASSET_MANIFEST_SHA256, 'verified_asset_count': len(assets),
            'scope': 'All 73 installed analysis assets passed complete byte-count and SHA-256 checks. Generated model graphs are bound separately from checkout source files; the release publisher independently verifies their packaged bytes.'},
        'scope': 'Fresh matched Linux/JVM full-passage native runtime comparison, fresh production source-clock regression, and exact verification of all bundled analysis assets. This is not a new corpus accuracy benchmark, Android/ARM64 crash reproduction, phone performance result, or validation of background compatibility fallback.',
        'checks': [
            'Pinned fresh host evidence compares actually loaded ONNX Runtime 1.23.2 and 1.25.1 using identical production predictor code, original unquantized models, source audio, and startSample=-66150.',
            'Both runtime runs completed two finite 573300-sample stems and satisfy the predeclared absolute and relative numerical thresholds; exact differences are recorded in the bound comparison.',
            'Every source bound by the fresh host comparison remains byte-identical; the current native runtime manifest matches the measured 1.25.1 dependency.',
            'All 73 analysis assets match the unchanged reviewed inventory, including all 27 Deux graphs and every GAME graph.',
            'Fresh 2.2.3 source-clock execution preserves all 932143 samples across four overlapping windows, including the final odd sample.',
            'Current full-browser inference, Android background lifecycle and native-crash fallback tests are separate mandatory release gates.'
        ],
        'fresh_native_runtime_comparison': {'path': OUT + 'native-runtime-comparison-verification.json',
            'sha256': COMPARISON_SHA256, 'runs': comparison['runs'], 'comparison': comparison['comparison'],
            'scope': comparison['scope']},
        'fresh_source_clock': {'path': OUT + 'source-clock-verification.json',
            'sha256': hashes[OUT + 'source-clock-verification.json'], 'samples': clock['samples'],
            'chunks': clock['chunks'], 'maxAbsError': clock['maxAbsError'], 'scope': clock.get('scope')},
        'limitations': ['No previous release execution is relabeled as current; the old runtime is only the newly executed comparison baseline.',
                       'The native prediction comparison ran on Linux x86_64 and does not exercise ARM instruction dispatch.',
                       'No claim of physical phone crash resolution, full-song performance or Tesla timing is implied.'],
        'completedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def main():
    output = ROOT / OUT / 'analysis-verification.json'
    try:
        receipt = verify_release()
    except Exception as error:
        # Never leave a stale passing receipt after a failed refresh.
        receipt = {'release': '2.2.3', 'passed': False, 'errors': [str(error)]}
        output.write_text(json.dumps(receipt, indent=2) + '\n')
        raise
    with tempfile.NamedTemporaryFile(mode='w', dir=output.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(receipt, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
    print(json.dumps({'passed': True, 'release': receipt['release'], 'checks': receipt['checks']}, indent=2))


if __name__ == '__main__':
    main()
