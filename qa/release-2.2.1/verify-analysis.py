#!/usr/bin/env python3
"""Bind fresh runtime equivalence and role checks to the current release.

This gate preserves the declared original-reference lineage. It does not turn
the archived six-song separation benchmark into a new full-dataset benchmark.
"""
from pathlib import Path
import datetime
import hashlib
import json
import math
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
VERSION = json.loads((ROOT / 'version.json').read_text())['name']
sys.path.insert(0, str(ROOT / 'tools'))
from verify_analysis_assets import verify as verify_assets


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


receipt = {
    'release': VERSION, 'passed': False, 'errors': [], 'checks': [], 'source_hashes': {},
    'scope': 'Fresh bounded WASM equivalence to the declared original full-context output; '
             'actual native Java CPU equivalence on the identical PCM16 fixture; '
             'source-clock seams and fresh role inference on 18 fixed original-model estimates. '
             'Public browser and Android lifecycle checks are separate mandatory release gates. '
             'This is not a fresh full-dataset separation benchmark, human note-accuracy evaluation or physical-device test.'
}


def bind(relative, expected=None):
    path = (ROOT / relative).resolve()
    require(path.is_relative_to(ROOT) and path.is_file(), 'Missing bound source: ' + relative)
    actual = digest(path)
    require(expected is None or actual == expected, 'Evidence is stale: ' + relative)
    receipt['source_hashes'][relative] = actual


def evidence(name):
    path = OUT / name
    value = json.loads(path.read_text())
    require(value.get('passed') is True and not value.get('errors'), 'Failed evidence: ' + name)
    if 'release' in value:
        require(value['release'] == VERSION, 'Wrong evidence release: ' + name)
    require(bool(value.get('source_hashes')), 'Missing source binding: ' + name)
    for relative, expected in value['source_hashes'].items():
        bind(relative, expected)
    bind(path.relative_to(ROOT).as_posix())
    return value


def validate_model(value, manifest):
    model = value['model']
    require(model['id'] == manifest['id'], 'Runtime used another model ID')
    require(model['checkpointSHA256'] == manifest['checkpointSHA256'], 'Runtime used another model checkpoint')
    require(model['manifestSHA256'] == digest(ROOT / 'web/analysis/models/deux/manifest.json'),
            'Runtime used another graph manifest')


def validate_pcm(value, samples, comparison=False, max_tolerance=.00003, rms_tolerance=.000003):
    for role in ['vocals', 'accompaniment']:
        result = value['pcm'][role]
        require(result['samples'] == samples, role + ' sample count changed')
        require(result.get('nonFiniteSamples', 0) == 0, role + ' contains invalid audio')
        require(len(result['sha256']) == 64, role + ' PCM hash missing')
        if comparison:
            maximum, rms = result['maxAbsError'], result['rmsError']
            require(math.isfinite(maximum) and 0 <= maximum <= max_tolerance, role + ' sample error exceeds the runtime tolerance')
            require(math.isfinite(rms) and 0 <= rms <= rms_tolerance, role + ' RMS error exceeds the runtime tolerance')


try:
    require(VERSION == '2.2.1', 'This numeric protocol belongs to release 2.2.1')
    verify_assets()
    for relative in ['version.json', 'web/analysis/ASSET_MANIFEST.json',
                     'web/analysis/models/deux/manifest.json', 'android/native-runtime.json',
                     'qa/release-2.2.1/verify-analysis.py', 'tools/verify_analysis_assets.py']:
        bind(relative)
    manifest = json.loads((ROOT / 'web/analysis/models/deux/manifest.json').read_text())
    for relative, expected in manifest['files'].items():
        model_file=ROOT/'web/analysis/models/deux'/relative
        require(model_file.stat().st_size==expected['bytes'] and digest(model_file)==expected['sha256'], 'Bundled separator graph changed: '+relative)
    require(manifest['execution'] == 'bounded-independent-batches-v1' and manifest['headFrames'] == 128,
            'Unexpected bounded inference configuration')
    clock = evidence('source-clock-verification.json')
    require(clock['contiguousSourceSamples'] and clock['monotonicProgress'] and clock['chunks'] >= 4,
            'Source-clock seams or progress failed')
    require(clock['samples'] == 932143 and clock['maxAbsError'] < .000002, 'Source-clock reconstruction changed')

    wasm = evidence('deux-bounded-wasm.json')
    reference = evidence('deux-bounded-pcm16-wasm.json')
    native = evidence('deux-native-java.json')
    for value in [wasm, reference, native]:
        validate_model(value, manifest)
    validate_pcm(wasm, 300032, comparison=True)
    validate_pcm(reference, 300032)
    validate_pcm(native, 300032, comparison=True, max_tolerance=.00002, rms_tolerance=.000001)
    require(native['fullPassageSamplesPerStem'] == 573300 and native['sourceStartSample'] == -66150 and native['cropOffsetSamples'] == 66150, 'Native full-context/source-clock relationship changed')
    require(native['referenceReceiptSHA256'] == digest(OUT/'deux-bounded-pcm16-wasm.json'), 'Native reference receipt changed')

    historical_path = ROOT / 'qa/release-2.1.0/analysis-verification.json'
    historical = json.loads(historical_path.read_text())
    require(historical['passed'] and not historical['errors'], 'Original reference lineage did not pass')
    bind(historical_path.relative_to(ROOT).as_posix())
    require(wasm['pcm']['vocals']['referenceSHA256'] == historical['wasm']['vocalPcmSHA256'],
            'WASM comparator is not the declared archived vocal reference')
    require(native['fixtureSHA256'] == reference['fixtureSHA256'], 'Native and WASM used different PCM16 inputs')
    for role in ['vocals', 'accompaniment']:
        require(native['pcm'][role]['referenceSHA256'] == reference['pcm'][role]['sha256'],
                'Native comparator is not the current same-input WASM ' + role)
    runtime_pin = json.loads((ROOT / 'android/native-runtime.json').read_text())
    require(native['runtimeVersion'] == runtime_pin['version'], 'Native runtime version changed')
    require(native['nativeManifestSHA256'] == digest(ROOT / 'android/native-runtime.json'), 'Native dependency pin changed')

    roles = evidence('role-verification.json')
    require(bool(roles.get('model_hashes')), 'Role model hashes are missing')
    for relative, expected in roles['model_hashes'].items():
        model_file=(ROOT/relative).resolve()
        require(model_file.is_relative_to(ROOT/'web/analysis/models/game') and digest(model_file)==expected, 'Role model changed: '+relative)
    positives = [r for r in roles['results'] if not r['track'].endswith('-instrumental')]
    negatives = [r for r in roles['results'] if r['track'].endswith('-instrumental')]
    require(len(positives) == 12 and len(negatives) == 6 and len({r['track'] for r in roles['results']}) == 18,
            'Role coverage is incomplete')
    require(all(r['phraseCount'] > 0 and r['noteCount'] > 0 for r in positives), 'Singing disappeared')
    require(all(r['phraseCount'] == r['noteCount'] == r['accentCount'] == 0 for r in negatives),
            'Instrument-only reference created vocal events')
    require(all(r['transcriptionReused'] is False for r in roles['results']), 'Role inference was reused')

    receipt.update(
        checks=[
            'Four overlapping passages preserve every source sample, including seam impulses and an odd final count.',
            'Fresh bounded WASM output matches the declared original full-context runtime reference within the unchanged numeric tolerance.',
            'Actual native Java CPU output matches current WASM on identical PCM16 input with pinned native binaries and model graphs.',
            'All 12 positive fixed-estimate cases retain singing; all six instrumental cases create zero vocal events, using freshly recomputed neural predictions.'
        ],
        wasm={'runtime': wasm['runtime'], 'pcm': wasm['pcm']},
        native={'runtime': native.get('runtime', {}), 'pcm': native['pcm']},
        roles={'positiveCases': 12, 'instrumentalCasesWithZeroVoiceEvents': 6, 'freshNeuralInference': True},
        historicalQuality={'path': historical_path.relative_to(ROOT).as_posix(),
                           'status': 'Historical separation scores remain historical; current gates measure runtime equivalence and role regressions.'},
        limitations=['Short development excerpts are not a representative held-out evaluation.',
                     'Role estimates are fixed original-PyTorch outputs, not 18 newly separated current-runtime mixtures.',
                     'Desktop CPU and WASM timing/memory do not establish sustained phone performance or physical Tesla timing.'])
    for relative, expected in receipt['source_hashes'].items():
        require(digest(ROOT / relative) == expected, 'Source changed during evidence aggregation: ' + relative)
    receipt['passed'] = True
except Exception as error:
    receipt['errors'].append(str(error))

receipt['completedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
(OUT / 'analysis-verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({key: value for key, value in receipt.items() if key != 'source_hashes'}, indent=2))
raise SystemExit(0 if receipt['passed'] else 1)
