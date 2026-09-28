#!/usr/bin/env python3
"""Verify production parallel classes against committed original full-output hashes.

Restore the licensed MUSDB Float32 fixtures as documented in DEUX_PARALLEL_B1.md.
This helper verifies their original hashes and converts them to exact PCM16
inputs. No old build tree, baseline tensors or generated PCM16 files are needed.
Without --qualification-output, unchanged qualified sources are recompiled and
every class hash must match the committed passing host qualification.
The four complete-output comparisons are quality checks, not timing evidence.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import warnings
import wave

ROOT = Path(__file__).resolve().parents[1]
CASE_STARTS = {'falcon': -66150, 'stella': 0}


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_canonical(root, performance):
    """Bind committed output hashes to original source, graphs and inputs."""
    research = root / 'research/inference-2.4.1'
    canonical_path = research / 'separator-divergent-inputs.json'
    frozen_path = research / 'separator-scheduler-paired.json'
    fixture_path = root / 'qa/release-1.6.0/musdb-fixture-provenance.json'
    canonical = json.loads(canonical_path.read_text())
    frozen = json.loads(frozen_path.read_text())
    fixtures = json.loads(fixture_path.read_text())
    require(canonical.get('schema') == 'lightforge.deux-divergent-input-parity.v1'
            and canonical.get('passed') is True and canonical.get('runtimeVersion') == '1.25.1',
            'Committed original output reference did not pass')
    snapshots = frozen['frozenSourceSnapshots']
    text_sha = lambda text: hashlib.sha256(text.encode('utf-8')).hexdigest()
    require(text_sha(snapshots['baseline/NativeDeux.java']) == canonical['sourceHashes']['baseline']
            == frozen['sourceHashes']['baseline'], 'Canonical original implementation provenance differs')
    for name, expected in canonical['sharedSourceHashes'].items():
        require(name in snapshots and text_sha(snapshots[name]) == expected
                == frozen['sharedSourceHashes'][name], 'Canonical common source provenance differs: ' + name)
    require(canonical['modelManifestSha256'] == frozen['modelManifestSha256'] == performance['models']['manifestSha256']
            and frozen['modelHashes'] == performance['models']['graphHashes'], 'Canonical original graph provenance differs')
    require(canonical['runtimeSha256'] == frozen['runtimeSha256'] == performance['runtime']['hostJarSha256'],
            'Canonical pinned runtime provenance differs')
    cases = canonical['cases']
    require(len(cases) == 2 and {case['id'] for case in cases} == set(CASE_STARTS), 'Canonical input inventory differs')
    for case in cases:
        references = [run for run in case['runs'] if run['variant'] == 'baseline']
        require(len(references) == 1 and case.get('byteIdentical') is True
                and case['samplesPerStem'] == 573300 and case['startSample'] == CASE_STARTS[case['id']],
                'Canonical original full-context reference is incomplete')
        reference = references[0]
        require(reference.get('outputBytes') == 4586400
                and re.fullmatch('[0-9a-f]{64}', reference.get('outputSha256', '')) is not None,
                'Canonical complete output hash or size is invalid')
        track = next(track for track in fixtures['tracks'] if track['id'] == case['id'])
        require(case['fixtureProvenance'] == track, 'Canonical fixture provenance differs')
    return canonical, frozen, fixtures, {
        'canonicalReferenceReceiptSha256': sha(canonical_path),
        'canonicalFrozenSourcesReceiptSha256': sha(frozen_path),
        'fixtureProvenanceReceiptSha256': sha(fixture_path),
    }


def prepare_fixture(case, directory, destination):
    """Produce exact historical PCM16 bytes from verified original Float32."""
    label = case['id']
    name = label + '-mix.wav'
    source = directory / name
    require(source.is_file(), 'Missing licensed fixture ' + name
            + '; restore MUSDB fixtures using the clean-checkout instructions in DEUX_PARALLEL_B1.md')
    expected = case['fixtureProvenance']['pcmSHA256'][name]
    require(sha(source) == expected, 'Original Float32 fixture hash differs: ' + name)
    import numpy as np
    from scipy.io import wavfile
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', wavfile.WavFileWarning)
        rate, audio = wavfile.read(source)
    require(rate == 44100 and audio.shape == (300032, 2) and audio.dtype == np.float32
            and np.isfinite(audio).all(), 'Original fixture format or finite sample coverage differs: ' + name)
    pcm = np.clip(np.rint(audio.astype(np.float64) * 32768), -32768, 32767).astype('<i2')
    require(not destination.exists(), 'Existing PCM16 input must not be overwritten')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), 'wb') as stream:
        stream.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
        stream.writeframes(pcm.tobytes())
    require(sha(destination) == case['audioSha256'], 'Deterministic PCM16 fixture hash differs: ' + label)
    require(sha(source) == expected, 'Original Float32 fixture changed during conversion: ' + name)
    return dict(sourceFixture=name, sourceFloat32Sha256=expected, pcm16Sha256=case['audioSha256'],
                frames=300032, channels=2, sampleRate=44100,
                conversion='Float32 to Float64, scale by32768, round nearest ties-to-even, clip[-32768,32767], little-endian PCM16 stereo WAV.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qualification-output', type=Path, help='Optional retained passing class set; default recompiles qualified sources')
    parser.add_argument('--float-fixture-directory', type=Path, default=ROOT / 'qa/release-1.6.0/fixtures')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, default=ROOT / 'research/inference-2.4.1/production-parallel-independent-inputs.json')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('parallel_benchmark', ROOT / 'tools/benchmark_deux_parallel.py')
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    b = benchmark.b
    work = args.output.resolve()
    b.require(not work.exists(), 'Use a fresh quality evidence directory')
    performance_path = ROOT / 'research/inference-2.4.1/production-parallel-qualification.json'
    performance_bytes = performance_path.read_bytes()
    performance_hash = hashlib.sha256(performance_bytes).hexdigest()
    performance = json.loads(performance_bytes)
    b.require(performance.get('passed') is True and performance.get('schema') == 'lightforge.production-parallel-qualification.v3',
              'The committed production qualification must pass')
    bindings = performance['sourceBindings']
    cpu_control = benchmark.child_cpu_control()
    b.require(cpu_control == performance['hostControls'], 'Quality child CPU control differs from qualified execution')
    b.require(benchmark.source_bindings() == bindings == performance['sourceBindingsAfter'],
              'Production sources differ from the qualified classes')
    canonical, frozen, fixture_provenance, canonical_bindings = load_canonical(ROOT, performance)
    work.mkdir(parents=True)
    prepared = {}
    for case in canonical['cases']:
        audio = work / 'fixtures' / (case['id'] + '-mix-pcm16.wav')
        prepared[case['id']] = (audio, prepare_fixture(case, args.float_fixture_directory, audio))
    toolchain = ROOT.parent / 'toolchain'
    java = toolchain / 'jdk17/bin'
    dependencies = [toolchain / 'test-json.jar', toolchain / 'android-sdk/platforms/android-35/android.jar',
                    toolchain / 'onnx/onnxruntime-1.25.1.jar']
    dependency_hashes = {path.name: b.sha(path) for path in dependencies}
    b.require(dependency_hashes == frozen['dependencyHashes'], 'Pinned compilation/runtime dependency differs')
    models = ROOT / 'web/analysis/models/deux'
    b.require(b.sha(dependencies[-1]) == canonical['runtimeSha256'] == performance['runtime']['hostJarSha256'],
              'Pinned runtime differs from reference')
    b.require(b.sha(models / 'manifest.json') == canonical['modelManifestSha256'] == performance['models']['manifestSha256'],
              'Original model manifest differs from reference')
    for name, expected in performance['models']['graphHashes'].items():
        b.require(b.sha(models / name) == expected, 'Original model graph changed: ' + name)
    if args.qualification_output is not None:
        qualification = args.qualification_output.resolve()
        b.require(b.sha(qualification / 'receipt.json') == performance_hash, 'Retained qualification receipt differs')
        classes = qualification / 'classes'
        compilation = 'retained-qualified-class-set'
    else:
        classes = benchmark.compile_production(work, java, dependencies, bindings)
        compilation = 'fresh-exact-class-hash-reproduction'
    b.require(benchmark.class_hashes(classes) == performance['compiledClassHashes'],
              'Recompiled or retained classes differ from the qualified class set; use the documented JDK17 toolchain')
    helper_hash = b.sha(Path(__file__))
    report = dict(schema='lightforge.production-parallel-independent-inputs.v2',
                  createdAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  scope='Quality-only complete finite Float32 comparisons against committed original full-output SHA256; no timing or device speedup claim.',
                  sourceBindings=bindings, compiledClassHashes=performance['compiledClassHashes'], compilation=compilation,
                  qualificationReceiptSha256=performance_hash, executionHelperSha256=helper_hash,
                  canonicalReference=canonical, fixtureArchive=fixture_provenance['archive'], dependencyHashes=dependency_hashes,
                  **canonical_bindings, runtime=performance['runtime'],
                  models=performance['models'], host=b.host_metadata(), hostControls=cpu_control, cases=[], passed=False)
    receipt = work / 'receipt.json'
    for label in CASE_STARTS:
        reference_case = next(case for case in canonical['cases'] if case['id'] == label)
        reference = next(run for run in reference_case['runs'] if run['variant'] == 'baseline')
        audio, preparation = prepared[label]
        start = reference_case['startSample']
        case = dict(id=label, audioSha256=b.sha(audio), startSample=start, inputPreparation=preparation,
                    referenceOutputSha256=reference['outputSha256'], runs=[])
        report['cases'].append(case)
        for index, variant in enumerate(('candidate4', 'candidate')):
            b.require(benchmark.source_bindings() == bindings and benchmark.class_hashes(classes) == performance['compiledClassHashes'],
                      'Qualified production implementation changed before run')
            run = benchmark.measure(variant, 0, index, 'quality-' + label, classes, work, java, dependencies, models, audio, start,
                                    cpu_control)
            case['runs'].append(run)
            receipt.write_text(json.dumps(report, indent=2) + '\n')
            b.require(run['output']['sha256'] == reference['outputSha256'], 'Complete independent production output differs')
            b.require(benchmark.source_bindings() == bindings and benchmark.class_hashes(classes) == performance['compiledClassHashes'],
                      'Qualified production implementation changed during run')
            print(json.dumps(dict(case=label, workers=4 if variant == 'candidate4' else 8,
                                  byteIdentical=True, outputSha256=run['output']['sha256'])), flush=True)
        case['byteIdentical'] = True
        b.require(b.sha(audio) == reference_case['audioSha256'], 'Test input changed during inference')
    b.require(b.sha(Path(__file__)) == helper_hash, 'Quality helper changed during qualification')
    for name, expected in performance['models']['graphHashes'].items():
        b.require(b.sha(models / name) == expected, 'Original model changed during quality proof')
    b.require(b.sha(models / 'manifest.json') == canonical['modelManifestSha256'], 'Original model manifest changed during proof')
    b.require(b.sha(performance_path) == performance_hash, 'Committed qualification receipt changed during proof')
    b.require({path.name: b.sha(path) for path in dependencies} == dependency_hashes, 'Pinned dependencies changed during proof')
    b.require(load_canonical(ROOT, performance)[3] == canonical_bindings, 'Committed original reference changed during proof')
    report.update(sourceBindingsAfter=benchmark.source_bindings(), finishedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  passed=True)
    b.require(report['sourceBindingsAfter'] == bindings, 'Production source changed before quality receipt')
    receipt.write_text(json.dumps(report, indent=2) + '\n')
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
