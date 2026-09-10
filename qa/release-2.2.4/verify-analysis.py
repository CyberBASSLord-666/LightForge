#!/usr/bin/env python3
"""Bind 2.2.4's fresh native runtime comparison and source-clock evidence.

The native predictor source and Balanced execution path changed, so these
comparisons are newly executed. This gate binds the measured host predictions,
the complete current analysis inventory, and a fresh source-clock regression. It
does not claim a new corpus accuracy benchmark or an ARM64 crash reproduction.
"""
from pathlib import Path
import datetime
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OUT = 'qa/release-2.2.4/'
COMPARISON_SHA256 = 'e74c12ca08132182f7cb971a98a6280401fcbfb5220a403e690e276c21c91712'
ASSET_MANIFEST_SHA256 = 'bb35b78f3c44f6660c04d356f07c2c7b37151428513dc06c0ef91b4ebd303575'
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
    require(result.get('release') == '2.2.4' and result.get('passed') is True and not result.get('failure'),
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
    require(result.get('release') == '2.2.4' and result.get('passed') is True and not result.get('errors'),
            'Fresh 2.2.4 source-clock check did not pass')
    require(result.get('samples') == 932143 and result.get('chunks') == 4 and
            result.get('contiguousSourceSamples') is True and result.get('monotonicProgress') is True and
            finite_number(result.get('maxAbsError')) and 0 <= result['maxAbsError'] < 2e-6,
            'Fresh source-clock boundaries failed')
    require(set(result.get('source_hashes', {})) == CLOCK_SOURCES, 'Fresh source-clock source coverage changed')
    for source, expected in result['source_hashes'].items():
        bind(root, source, expected, hashes)
    hashes[relative] = digest(path)
    return result


MDX_COMPARISON_SHA256 = '3e8dc72c4f2659ff6404294c92bb77eb773e7bdf8e7043ca5ca5e916e64fa9ef'
MDX_SOURCES = {
    'version.json', 'android/native-runtime.json',
    'android/src/com/cyberbasslord/lightforge/NativeMdxTask.java',
    'android/src/com/cyberbasslord/lightforge/NativeRuntimeGuard.java',
    'android/src/com/cyberbasslord/lightforge/NativeDeux.java',
    'web/analysis/dsp.js', 'web/analysis/wav-reader.js',
    'web/analysis/separator-mdx.js', 'web/analysis/models/separator-mdx-model.json',
    'web/demo/glass-castle.wav', 'qa/release-1.6.0/fixtures/falcon-mix.wav',
    'qa/release-1.6.0/musdb-fixture-provenance.json', OUT + 'NativeMdxComparisonMain.java',
    OUT + 'compare-mdx-wasm.cjs', OUT + 'compare-native-mdx.py', OUT + 'mdx_numeric.py',
    OUT + 'initial-mdx-absolute-only/compare-native-mdx.py',
    OUT + 'initial-mdx-absolute-only/native-mdx-comparison-verification.json',
    OUT + 'initial-mdx-absolute-only/native-mdx-comparison.log',
    OUT + 'revised-mdx-first-run/compare-native-mdx.py',
    OUT + 'revised-mdx-first-run/mdx_numeric.py',
    OUT + 'revised-mdx-first-run/native-mdx-comparison-verification.json',
    OUT + 'revised-mdx-first-run/native-mdx-comparison.log',
}


def verify_mdx(root, hashes):
    relative = OUT + 'native-mdx-comparison-verification.json'
    path = bind(root, relative, MDX_COMPARISON_SHA256, hashes)
    result = json.loads(path.read_text())
    require(result.get('release') == '2.2.4' and result.get('passed') is True and not result.get('errors'),
            'Fresh production MDX numerical comparison did not pass')
    adapters = {p.relative_to(root).as_posix() for p in (root / 'tests/native-mdx-host').rglob('*.java')}
    require(bool(adapters) and set(result.get('source_hashes', {})) == MDX_SOURCES | adapters,
            'MDX comparison source coverage changed')
    for source, expected in result['source_hashes'].items():
        bind(root, source, expected, hashes)
    assets = {'web/analysis/models/uvr-mdx-voc-ft.onnx'} | {
        p.relative_to(root).as_posix() for p in (root / 'web/analysis/vendor').glob('*') if p.is_file()}
    require(set(result.get('analysis_asset_hashes', {})) == assets, 'MDX comparison asset coverage changed')
    for source, expected in result['analysis_asset_hashes'].items():
        bind(root, source, expected, hashes)
    inputs = [{'id': 'demo-start', 'source': 'web/demo/glass-castle.wav', 'start_sample': -3840},
              {'id': 'demo-20s', 'source': 'web/demo/glass-castle.wav', 'start_sample': 878160},
              {'id': 'falcon-start', 'source': 'qa/release-1.6.0/fixtures/falcon-mix.wav', 'start_sample': -3840}]
    require(result.get('inputs') == inputs and result.get('sample_rate') == 44100 and
            result.get('spectrum_floats') == 3145728 and result.get('waveform_samples') == 261120,
            'MDX comparison used a different source boundary or geometry')
    require(result.get('native_runtime') == '1.25.1' and result.get('native_runtime_sha256') == NEW_RUNTIME_SHA256 and
            result.get('wasm_runtime') == '1.20.1', 'MDX comparison runtime identity changed')
    spectral = {'absolute_tolerance': 1e-4, 'relative_tolerance': 1e-5, 'rmse': 1e-5, 'relative_rmse': 1e-3}
    waveform = {'max_absolute_error': 1e-6, 'rmse': 1e-7, 'relative_rmse': 1e-4}
    require(result.get('thresholds') == {'spectrum': spectral, 'waveform': waveform}, 'MDX comparison thresholds changed')
    passages = result.get('passages', [])
    require(len(passages) == 3, 'MDX comparison passage coverage changed')
    for passage, expected_input in zip(passages, inputs):
        require(all(passage.get(k) == v for k, v in expected_input.items()) and passage.get('source_sha256') == hashes[expected_input['source']], 'MDX comparison input binding changed')
        comparisons = passage.get('comparisons', [])
        require(len(comparisons) == 3 and [c.get('output') for c in comparisons] == ['positive', 'negative', 'waveform'],
                'MDX comparison output coverage changed')
        for item, count in zip(comparisons, [3145728, 3145728, 261120]):
            require(item.get('samples') == count and item.get('finite') is True, 'MDX output incomplete or nonfinite')
            for metric in ['max_absolute_error', 'rmse', 'reference_rms', 'relative_rmse']:
                require(finite_number(item.get(metric)) and item[metric] >= 0, 'MDX numerical metric invalid: ' + metric)
            if item['output'] == 'waveform':
                require(item.get('within_thresholds') is True, 'MDX decoded waveform comparison failed')
                for metric, limit in waveform.items():
                    require(item[metric] <= limit, 'MDX decoded waveform threshold failed: ' + metric)
            else:
                violations = item.get('coefficient_violations')
                scaled = item.get('maximum_scaled_error')
                require(type(violations) is int and 0 <= violations <= count and finite_number(scaled) and scaled >= 0, 'MDX coefficient diagnostic invalid')
                require((violations == 0) == (scaled <= 1), 'MDX coefficient diagnostic conflicts with its count')
                diagnostic_pass = violations == 0 and item['rmse'] <= spectral['rmse'] and item['relative_rmse'] <= spectral['relative_rmse']
                require(item.get('within_thresholds') is diagnostic_pass, 'MDX spectral diagnostic was relabeled')
        runs = passage.get('runs', {})
        require(set(runs) == {'native', 'wasm'}, 'MDX runtime run coverage changed')
        for runtime, version in [('native', '1.25.1'), ('wasm', '1.20.1')]:
            require([r.get('polarity') for r in runs[runtime]] == ['positive', 'negative'], 'MDX polarity coverage changed')
            for run in runs[runtime]:
                require(run.get('runtime') == version and finite_number(run.get('seconds')) and run['seconds'] > 0,
                        'MDX runtime metrics are invalid')
        outputs = passage.get('output_hashes', {})
        expected_outputs = {runtime + '-' + kind + '.float32le': count * 4
            for runtime in ['native', 'wasm'] for kind, count in [('positive', 3145728), ('negative', 3145728), ('waveform', 261120)]}
        require(set(outputs) == set(expected_outputs), 'MDX output digest coverage changed')
        for name, count in expected_outputs.items():
            require(outputs[name].get('bytes') == count and re.fullmatch(r'[0-9a-f]{64}', outputs[name].get('sha256', '')),
                    'MDX output digest metadata invalid')
    require(result.get('decoded_waveform_passed') is True, 'MDX decoded waveform qualification missing')
    spectral_pass = all(c['within_thresholds'] for p in passages for c in p['comparisons'] if c['output'] != 'waveform')
    require(result.get('spectral_diagnostic_passed') is spectral_pass, 'MDX aggregate spectral diagnostic was relabeled')
    revision = result.get('protocol_revision', {})
    require(revision.get('revision') == 3 and revision.get('after_prior_failures') is True, 'MDX protocol revision disclosure missing')
    require(revision.get('prior_revised_failure_path') == OUT + 'revised-mdx-first-run/native-mdx-comparison-verification.json', 'Revised MDX failure provenance missing')
    previous_path = bind(root, revision['prior_revised_failure_path'], revision.get('prior_revised_failure_sha256'), hashes)
    previous = json.loads(previous_path.read_text())
    require(previous.get('passed') is False and previous['thresholds'] == result['thresholds'], 'Earlier MDX diagnostic failure was relabeled or tolerances changed')
    require(digest(file(root, OUT + 'revised-mdx-first-run/compare-native-mdx.py')) == previous['source_hashes'][OUT + 'compare-native-mdx.py'], 'Earlier MDX comparator differs from its measured source')
    review = result.get('criterion_review', {})
    require(review.get('initial_failure_path') == OUT + 'initial-mdx-absolute-only/native-mdx-comparison-verification.json', 'Initial MDX criterion failure provenance missing')
    initial_path = bind(root, review['initial_failure_path'], review.get('initial_failure_sha256'), hashes)
    initial = json.loads(initial_path.read_text())
    require(initial.get('passed') is False and bool(initial.get('errors')), 'Original spectral failure was relabeled')
    require(review.get('initial_comparator_path') == OUT + 'initial-mdx-absolute-only/compare-native-mdx.py', 'Initial MDX comparator provenance missing')
    require(review.get('initial_comparator_sha256') == initial['source_hashes'][OUT + 'compare-native-mdx.py'], 'Initial MDX comparator differs from the failed measurement')
    bind(root, review['initial_comparator_path'], review.get('initial_comparator_sha256'), hashes)
    return result



DOWNSTREAM_SHA256 = '8742d94afae00533041e8bac86ce53bfb05c7df695eb5a864b5f32169a221468'
DOWNSTREAM_SOURCES = {
    'version.json', OUT + 'verify-mdx-downstream.cjs', OUT + 'mdx-downstream-compare.cjs',
    'tests/mdx-downstream-compare.test.cjs', 'web/analysis/vocal.js',
    'web/analysis/vocal-detail.js', 'web/analysis/game.js', 'web/analysis/dsp.js',
    'web/analysis/stem-cache.js', 'web/analysis/wav-reader.js', 'web/analysis/separator-mdx.js',
    'web/analysis/worker.js', 'web/analysis/models/features.json',
    'web/analysis/models/vocal-model.json', 'web/analysis/models/vocal-frontend.json',
    'web/analysis/models/game/manifest.json', 'web/analysis/models/separator-mdx-model.json',
    'web/demo/glass-castle.wav',
}


def verify_downstream(root, hashes, mdx):
    relative = OUT + 'native-mdx-downstream-verification.json'
    path = bind(root, relative, DOWNSTREAM_SHA256, hashes)
    result = json.loads(path.read_text())
    require(result.get('release') == '2.2.4' and result.get('passed') is True and not result.get('errors'),
            'Mandatory paired downstream GAME and vocal-feature verification did not pass')
    require(set(result.get('source_hashes', {})) == DOWNSTREAM_SOURCES,
            'Downstream verification source coverage changed')
    for source, expected in result['source_hashes'].items():
        bind(root, source, expected, hashes)
    game = json.loads(file(root, 'web/analysis/models/game/manifest.json').read_text())
    vocal = json.loads(file(root, 'web/analysis/models/vocal-model.json').read_text())
    assets = {'web/analysis/models/game/' + name for name in game['files']} | {
        'web/analysis/models/' + vocal['file']} | {
        p.relative_to(root).as_posix() for p in (root / 'web/analysis/vendor').glob('*') if p.is_file()}
    require(set(result.get('analysis_asset_hashes', {})) == assets, 'Downstream model/runtime asset coverage changed')
    for source, expected in result['analysis_asset_hashes'].items():
        bind(root, source, expected, hashes)
    fixture = {'id': 'demo-20s', 'source': 'web/demo/glass-castle.wav',
        'sourceSha256': hashes['web/demo/glass-castle.wav'], 'contextReadStart': 878160,
        'contextReadSamples': 261120, 'coreStart': 882000, 'coreSamples': 253440, 'sampleRate': 44100}
    require(result.get('fixture') == fixture, 'Downstream fixture/source-clock coverage changed')
    measured = next(p for p in mdx['passages'] if p['id'] == fixture['id'])
    require(set(result.get('inputs', {})) == {'native', 'wasm'} and set(result.get('runs', {})) == {'native', 'wasm'},
            'Downstream paired-runtime coverage changed')
    outputs = []
    for runtime in ['native', 'wasm']:
        name = runtime + '-waveform.float32le'
        require(result['inputs'][runtime] == {'file': name, **measured['output_hashes'][name]},
                'Downstream input is not the measured production MDX waveform')
        run = result['runs'][runtime]
        require(run.get('runtime') == '1.20.1', 'Downstream runtime identity changed')
        expected_clock = {'fixture': 'demo-20s', 'source': fixture['source'], 'coreStartSample': 882000,
            'coreSamples': 253440, 'sampleRate': 44100, 'contextReadStart': 878160, 'contextReadSamples': 261120}
        require(run.get('sourceClock') == expected_clock, 'Downstream retained output changed source clock')
        expected_executions = {'segmenter': 8, 'encoder': 1, 'dur2bd': 1, 'bd2dur': 1, 'estimator': 1, 'frameMn10': 1}
        require(run.get('executions') == expected_executions, 'Downstream did not execute every required graph step')
        require(bool(run.get('loadedModels')), 'Downstream model execution inventory missing')
        for source, expected in run['loadedModels'].items():
            require(source in assets and result['analysis_asset_hashes'][source] == expected,
                    'Downstream executed an unbound model')
        output = run.get('output', {})
        filename = OUT + 'native-mdx-downstream-' + runtime + '.json'
        measured_output = bind(root, filename, output.get('sha256'), hashes)
        require(type(output.get('bytes')) is int and output['bytes'] > 0 and measured_output.stat().st_size == output['bytes'],
                'Downstream measured output byte count changed')
        details = json.loads(measured_output.read_text())
        require(details.get('waveformSha256') == result['inputs'][runtime]['sha256'] and
                details.get('executions') == run['executions'] and details.get('loadedModels') == run['loadedModels'] and
                details.get('samples44100') == 253440 and details.get('samples22050') == 126720,
                'Downstream output provenance or sample geometry changed')
        outputs.append(measured_output)
    # Recompute the full fixed comparison from exact retained model outputs.
    # This validates all categorical decisions, notes, arrays, tolerances,
    # nonempty singing coverage and eight-step execution without rerunning ORT.
    script = "const fs=require('fs');const {compare,thresholds}=require(process.argv[1]);const read=p=>{const {waveformSha256,...value}=JSON.parse(fs.readFileSync(p));return value;};process.stdout.write(JSON.stringify({comparison:compare(read(process.argv[2]),read(process.argv[3])),thresholds}));"
    verification = json.loads(subprocess.check_output(['node', '-e', script,
        str(file(root, OUT + 'mdx-downstream-compare.cjs')), *map(str, outputs)], cwd=root, text=True))
    require(verification['comparison'].get('passed') is True and not verification['comparison'].get('errors'),
            'Retained downstream outputs fail the full fixed comparison')
    require(result.get('comparison') == verification['comparison'] and result.get('thresholds') == verification['thresholds'],
            'Downstream receipt differs from recomputed output metrics, coverage or fixed thresholds')
    return result


def verify_release(root=ROOT):
    root = Path(root).resolve()
    version_path = file(root, 'version.json')
    require(json.loads(version_path.read_text()) == {'name': '2.2.4', 'code': 20204},
            'This evidence protocol belongs only to 2.2.4 / 20204')
    hashes = {'version.json': digest(version_path)}
    comparison = verify_comparison(root, hashes)
    assets = verify_assets(root, hashes)
    clock = verify_clock(root, hashes)
    mdx = verify_mdx(root, hashes)
    downstream = verify_downstream(root, hashes, mdx)
    hashes[OUT + 'verify-analysis.py'] = digest(file(root, OUT + 'verify-analysis.py'))
    for relative, expected in {**hashes, **assets}.items():
        require(digest(file(root, relative)) == expected, 'Source changed during analysis verification: ' + relative)
    return {
        'release': '2.2.4', 'passed': True, 'errors': [], 'source_hashes': hashes,
        'analysis_asset_hashes': assets,
        'analysis_asset_binding': {'manifest_path': 'web/analysis/ASSET_MANIFEST.json',
            'manifest_sha256': ASSET_MANIFEST_SHA256, 'verified_asset_count': len(assets),
            'scope': 'All 73 installed analysis assets passed complete byte-count and SHA-256 checks. Generated model graphs are bound separately from checkout source files; the release publisher independently verifies their packaged bytes.'},
        'scope': 'Fresh matched Linux/JVM full-passage Deux runtime comparison, fresh production native MDX versus CPU WASM comparison, fresh production source-clock regression, and exact verification of all bundled analysis assets. This is not a new corpus accuracy benchmark, Android/ARM64 crash reproduction, phone performance result, or validation of background compatibility fallback.',
        'checks': [
            'Pinned fresh host evidence compares actually loaded ONNX Runtime 1.23.2 and 1.25.1 using identical production predictor code, original unquantized models, source audio, and startSample=-66150.',
            'Both runtime runs completed two finite 573300-sample stems and satisfy the predeclared absolute and relative numerical thresholds; exact differences are recorded in the bound comparison.',
            'Every source bound by the fresh host comparison remains byte-identical; the current native runtime manifest matches the measured 1.25.1 dependency.',
            'All 73 analysis assets match the current reviewed inventory, including all 27 Deux graphs and every GAME graph.',
            'Fresh 2.2.4 source-clock execution preserves all 932143 samples across four overlapping windows, including the final odd sample.',
            'Fresh production NativeMdxTask and bundled CPU WASM compare three fixed inputs with unchanged graph weights and both polarity passes. Strict decoded waveform equivalence is mandatory; internal spectral diagnostics retain any failed coefficient comparisons, with protocol revision history preserved.',
            'The same measured demo-20s waveforms pass separately executed production resampling, voice classification, vocal features and all eight GAME transcription steps; the complete retained downstream outputs are re-compared, including nonempty singing coverage and categorical decisions.',
            'Current full-browser inference, Android background lifecycle and native-crash fallback tests are separate mandatory release gates.'
        ],
        'fresh_native_runtime_comparison': {'path': OUT + 'native-runtime-comparison-verification.json',
            'sha256': COMPARISON_SHA256, 'runs': comparison['runs'], 'comparison': comparison['comparison'],
            'scope': comparison['scope']},
        'fresh_native_mdx_comparison': {'path': OUT + 'native-mdx-comparison-verification.json', 'sha256': hashes[OUT + 'native-mdx-comparison-verification.json'], 'passages': mdx['passages'], 'scope': mdx['scope'], 'decoded_waveform_passed': mdx['decoded_waveform_passed'], 'spectral_diagnostic_passed': mdx['spectral_diagnostic_passed'], 'protocol_revision': mdx['protocol_revision']},
        'fresh_native_mdx_downstream': {'path': OUT + 'native-mdx-downstream-verification.json', 'sha256': hashes[OUT + 'native-mdx-downstream-verification.json'], 'scope': downstream.get('scope'), 'fixture': downstream['fixture'], 'coverage': downstream['comparison']['coverage'], 'thresholds': downstream['thresholds']},
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
        receipt = {'release': '2.2.4', 'passed': False, 'errors': [str(error)]}
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
