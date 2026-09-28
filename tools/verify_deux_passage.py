#!/usr/bin/env python3
"""Run current original-graph host quality checks without an APK or historical receipt writes.

--compile-only snapshots and compiles current production/test sources without
performing inference. The variants mode checks forced baseline/four/eight-worker
complete outputs against committed original outputs for licensed MUSDB inputs.
The integration mode also exercises unfunded-work admission, rejected legacy
graph caches, actual concurrent JNI cancellation, interruption and recovery.
Single host observations do not qualify a speedup or Android release.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess

import benchmark_deux_parallel as benchmark

ROOT = Path(__file__).resolve().parents[1]
b = benchmark.b


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='Fresh scratch evidence directory')
    parser.add_argument('--compile-only', action='store_true')
    parser.add_argument('--mode', choices=('variants', 'integration', 'all'), default='variants')
    parser.add_argument('--fixture', choices=('falcon', 'stella'), default='falcon')
    parser.add_argument('--variants', nargs='+', choices=('baseline', 'candidate4', 'candidate'),
                        default=['baseline', 'candidate4', 'candidate'])
    args = parser.parse_args()
    work = args.output.resolve()
    b.require(not work.exists(), 'Use a fresh evidence directory; never overwrite prior observations')
    b.require(len(args.variants) == len(set(args.variants)), 'Repeated variants are not independent paired evidence')
    work.mkdir(parents=True)
    toolchain = ROOT.parent / 'toolchain'
    java = toolchain / 'jdk17/bin'
    dependencies = [toolchain / 'test-json.jar', toolchain / 'android-sdk/platforms/android-35/android.jar',
                    toolchain / 'onnx/onnxruntime-1.25.1.jar']
    frozen = json.loads((ROOT / 'research/inference-2.4.1/separator-scheduler-paired.json').read_text())
    dependency_hashes = {path.name: b.sha(path) for path in dependencies}
    b.require(dependency_hashes == frozen['dependencyHashes'], 'Pinned Java test/runtime dependencies differ')
    # compile_production snapshots all listed bytes and rechecks them after javac.
    benchmark.SOURCE_PATHS = benchmark.SOURCE_PATHS | {
        'tests/NativeDeuxCalibrationTest.java', 'tools/verify_deux_passage.py',
        'qa/release-2.4.1/verify-analysis.py', 'tests/test_native_scheduler_evidence.py',
    }
    bindings = benchmark.source_bindings()
    classes = benchmark.compile_production(work, java, dependencies, bindings)
    class_hashes = benchmark.class_hashes(classes)
    record = dict(schema='lightforge.current-passage-host-check.v1',
                  createdAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  scope='Current-source host quality/integration checks only; no phone, whole-job, speedup or release qualification.',
                  sourceBindings=bindings, compiledClassHashes=class_hashes, dependencyHashes=dependency_hashes,
                  mode=args.mode, compileOnly=args.compile_only, compiled=True, inferencePerformed=False, passed=False)
    receipt = work / 'receipt.json'

    def save():
        receipt.write_text(json.dumps(record, indent=2) + '\n')

    def unchanged():
        b.require(benchmark.source_bindings() == bindings, 'Source changed after compilation')
        b.require(benchmark.class_hashes(classes) == class_hashes, 'Compiled class set changed')

    save()
    if args.compile_only:
        print(json.dumps(dict(compiled=True, inferencePerformed=False, receipt=str(receipt))))
        return
    models = ROOT / 'web/analysis/models/deux'
    manifest_path = models / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    b.require(b.sha(manifest_path) == frozen['modelManifestSha256'] and
              len(manifest['files']) == 27 and manifest['frames'] == 1301 and manifest['samples'] == 573300,
              'Original full-context model manifest differs')

    def verify_models():
        b.require(b.sha(manifest_path) == frozen['modelManifestSha256'], 'Model manifest changed')
        for name, expected in manifest['files'].items():
            b.require((models / name).stat().st_size == expected['bytes'] and
                      b.sha(models / name) == expected['sha256'] == frozen['modelHashes'][name],
                      'Original graph bytes differ: ' + name)

    verify_models()
    record['modelManifestSha256'] = frozen['modelManifestSha256']
    record['graphHashes'] = frozen['modelHashes']
    control = benchmark.child_cpu_control()
    record['hostControls'] = control
    if args.mode in ('variants', 'all'):
        inputs = benchmark.load('passage_original_inputs', ROOT / 'tools/verify_deux_parallel_inputs.py')
        canonical_path = ROOT / 'research/inference-2.4.1/separator-divergent-inputs.json'
        canonical = json.loads(canonical_path.read_text())
        b.require(canonical['passed'] is True and canonical['modelManifestSha256'] == frozen['modelManifestSha256']
                  and canonical['runtimeSha256'] == dependency_hashes[dependencies[-1].name],
                  'Original output reference does not bind the original graphs/runtime')
        case = next(case for case in canonical['cases'] if case['id'] == args.fixture)
        reference = next(run for run in case['runs'] if run['variant'] == 'baseline')
        b.require(case['byteIdentical'] is True and case['samplesPerStem'] == 573300
                  and reference['outputBytes'] == 4586400, 'Original complete output reference is invalid')
        audio = work / 'fixtures' / (args.fixture + '-mix-pcm16.wav')
        preparation = inputs.prepare_fixture(case, ROOT / 'qa/release-1.6.0/fixtures', audio)
        record['input'] = dict(case=args.fixture, preparation=preparation, startSample=case['startSample'],
                               canonicalReceiptSha256=b.sha(canonical_path), originalOutputSha256=reference['outputSha256'])
        record['runs'] = []
        for order, variant in enumerate(args.variants):
            unchanged()
            run = benchmark.measure(variant, 0, order, 'quality', classes, work, java, dependencies,
                                    models, audio, case['startSample'], control)
            record['inferencePerformed'] = True
            record['runs'].append(run)
            save()
            b.require(run['output']['sha256'] == reference['outputSha256'],
                      'Current complete Float32 output differs from the original reference: ' + variant)
            b.require(b.sha(audio) == case['audioSha256'], 'Prepared input changed during inference')
            unchanged()
    if args.mode in ('integration', 'all'):
        unchanged()
        audio = ROOT / 'web/demo/glass-castle.wav'
        audio_hash = b.sha(audio)
        command = [str(java / 'java'), '-Xmx1g', '-XX:MaxDirectMemorySize=512m', '-cp',
                   os.pathsep.join(map(str, [classes, *dependencies])),
                   'com.cyberbasslord.lightforge.NativeDeuxCalibrationTest', str(models), str(audio), str(work / 'integration')]
        # Quality-only integration uses eight actual CPUs so automatic nomination
        # can consider both geometries; no performance claim uses this busy host.
        integration_affinity = control['parentCpuAffinity'][:8]
        record['integrationCpuAffinity'] = integration_affinity
        result = subprocess.run(command, capture_output=True, text=True, timeout=1800,
                                preexec_fn=lambda: os.sched_setaffinity(0, integration_affinity))
        (work / 'integration.log').write_text(result.stdout + result.stderr)
        b.require(result.returncode == 0, 'Native integration failed; see integration.log')
        verifier = benchmark.load('current_scheduler_evidence', ROOT / 'qa/release-2.4.1/verify-analysis.py')
        integration = verifier.verify_scheduler_calibration(json.loads(result.stdout.strip().splitlines()[-1]))
        original_path = ROOT / 'research/inference-2.4.1/production-parallel-qualification.json'
        original = json.loads(original_path.read_text())
        original_hashes = {run['output']['sha256'] for run in original['runs']}
        b.require(original['audio']['sha256'] == audio_hash and original['audio']['startSample'] == integration['startSample']
                  and len(original_hashes) == 1 and integration['runs']['reference']['outputSha256'] in original_hashes,
                  'Integration baseline changed the committed original complete demo output')
        record['integration'] = integration
        record['integrationReferenceReceiptSha256'] = b.sha(original_path)
        record['inferencePerformed'] = True
        b.require(b.sha(audio) == audio_hash, 'Integration input changed')
        unchanged()
    verify_models()
    record.update(passed=True, sourceBindingsAfter=benchmark.source_bindings(),
                  finishedAt=datetime.datetime.now(datetime.timezone.utc).isoformat())
    save()
    print(json.dumps(dict(passed=True, mode=args.mode, receipt=str(receipt))))


if __name__ == '__main__':
    main()
