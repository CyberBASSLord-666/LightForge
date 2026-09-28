#!/usr/bin/env python3
"""Verify final production parallel classes on independent full-context inputs.

Original baseline bytes were captured previously with the same pinned models and
runtime. They are revalidated here; their historical times are not compared with
these quality-only runs. Both four- and eight-worker production paths are tested.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qualification-output', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, default=ROOT / 'research/inference-2.4.1/production-parallel-independent-inputs.json')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('parallel_benchmark', ROOT / 'tools/benchmark_deux_parallel.py')
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    b = benchmark.b
    work, qualification = args.output.resolve(), args.qualification_output.resolve()
    b.require(not work.exists(), 'Use a fresh quality evidence directory')
    work.mkdir(parents=True)
    performance_path = qualification / 'receipt.json'
    performance = json.loads(performance_path.read_text())
    b.require(performance.get('passed') is True and performance.get('schema') == 'lightforge.production-parallel-qualification.v3',
              'A completed production qualification class set is required')
    bindings = performance['sourceBindings']
    cpu_control = benchmark.child_cpu_control()
    b.require(cpu_control == performance['hostControls'], 'Quality child CPU control differs from qualified execution')
    b.require(benchmark.source_bindings() == bindings == performance['sourceBindingsAfter'],
              'Production sources differ from the qualified classes')
    classes = qualification / 'classes'
    b.require(benchmark.class_hashes(classes) == performance['compiledClassHashes'], 'Qualified classes changed')
    canonical_path = ROOT / 'build/inference-screen/formal-six/divergent-inputs.json'
    canonical = json.loads(canonical_path.read_text())
    b.require(canonical.get('passed') is True and canonical['runtimeVersion'] == '1.25.1', 'Canonical reference failed')
    frozen_path = ROOT / 'research/inference-2.4.1/separator-scheduler-paired.json'
    frozen = json.loads(frozen_path.read_text())['frozenSourceSnapshots']
    text_sha = lambda text: hashlib.sha256(text.encode('utf-8')).hexdigest()
    b.require(text_sha(frozen['baseline/NativeDeux.java']) == canonical['sourceHashes']['baseline'],
              'Canonical original implementation provenance differs')
    for name, expected in canonical['sharedSourceHashes'].items():
        b.require(name in frozen and text_sha(frozen[name]) == expected, 'Canonical common source provenance differs: ' + name)
    toolchain = ROOT.parent / 'toolchain'
    java = toolchain / 'jdk17/bin'
    dependencies = [toolchain / 'test-json.jar', toolchain / 'android-sdk/platforms/android-35/android.jar',
                    toolchain / 'onnx/onnxruntime-1.25.1.jar']
    models = ROOT / 'web/analysis/models/deux'
    b.require(b.sha(dependencies[-1]) == canonical['runtimeSha256'] == performance['runtime']['hostJarSha256'],
              'Pinned runtime differs from reference')
    b.require(b.sha(models / 'manifest.json') == canonical['modelManifestSha256'] == performance['models']['manifestSha256'],
              'Original model manifest differs from reference')
    for name, expected in performance['models']['graphHashes'].items():
        b.require(b.sha(models / name) == expected, 'Original model graph changed: ' + name)
    helper_hash = b.sha(Path(__file__))
    report = dict(schema='lightforge.production-parallel-independent-inputs.v1',
                  createdAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  scope='Quality-only complete finite Float32 comparisons; no timing or device speedup claim.',
                  sourceBindings=bindings, compiledClassHashes=performance['compiledClassHashes'],
                  qualificationReceiptSha256=b.sha(performance_path), executionHelperSha256=helper_hash,
                  canonicalReferenceReceiptSha256=b.sha(canonical_path), canonicalReference=canonical,
                  canonicalFrozenSourcesReceiptSha256=b.sha(frozen_path), runtime=performance['runtime'],
                  models=performance['models'], host=b.host_metadata(), hostControls=cpu_control, cases=[], passed=False)
    receipt = work / 'receipt.json'
    fixtures = [('falcon', ROOT / 'qa/release-2.2.1/fixtures/falcon-mix-pcm16.wav', -66150),
                ('stella', ROOT / 'build/inference-screen/fixtures/stella-mix-pcm16.wav', 0)]
    for label, audio, start in fixtures:
        reference_case = next(case for case in canonical['cases'] if case['id'] == label)
        reference = next(run for run in reference_case['runs'] if run['variant'] == 'baseline')
        reference_output = ROOT / 'build/inference-screen/formal-six/baseline' / ('quality-' + label + '-0.f32')
        b.require(b.read_output(reference_output) == reference['outputSha256'], 'Canonical full output bytes changed')
        b.require(b.sha(audio) == reference_case['audioSha256'] and start == reference_case['startSample'],
                  'Canonical test input changed')
        case = dict(id=label, audioSha256=b.sha(audio), startSample=start,
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
    report.update(sourceBindingsAfter=benchmark.source_bindings(), finishedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  passed=True)
    b.require(report['sourceBindingsAfter'] == bindings, 'Production source changed before quality receipt')
    receipt.write_text(json.dumps(report, indent=2) + '\n')
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
