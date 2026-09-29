#!/usr/bin/env python3
"""Source-bound real-JNI screening memory checks; synthetic decisions, never speed evidence."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CASES = ('four-only', 'drop-eight-before', 'drop-all-before-four', 'drop-eight-final',
         'cancel-after-four', 'abort-after-four', 'runtime-after-four')


def sha(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', choices=CASES, default=list(CASES))
    parser.add_argument('--compile-only', action='store_true')
    parser.add_argument('--reference-native-deux', type=Path,
                        help='Explicit historical NativeDeux source, solely for a disclosed negative control')
    args = parser.parse_args()
    work = args.output.resolve()
    require(not work.exists(), 'Use fresh evidence paths')
    require(len(args.cases) == len(set(args.cases)), 'Repeated cases are not independent observations')
    work.mkdir(parents=True)
    toolchain = ROOT.parent / 'toolchain'
    java = toolchain / 'jdk17/bin'
    dependencies = [toolchain / 'test-json.jar', toolchain / 'android-sdk/platforms/android-35/android.jar',
                    toolchain / 'onnx/onnxruntime-1.25.1.jar']
    runtime = json.loads((ROOT / 'android/native-runtime.json').read_text())
    frozen = json.loads((ROOT / 'research/inference-2.4.1/separator-scheduler-paired.json').read_text())
    dependency_hashes = {path.name: sha(path) for path in dependencies}
    require(dependency_hashes == frozen['dependencyHashes'], 'Pinned runtime/test dependencies changed')
    require(dependency_hashes[dependencies[-1].name] == runtime['host']['sha256'], 'Runtime changed')
    paths = {'android/src/com/cyberbasslord/lightforge/' + name + '.java': ROOT / 'android/src/com/cyberbasslord/lightforge' / (name + '.java')
             for name in ('NativeDeux', 'NativeDeuxTransform', 'NativeInferenceProfile', 'NativeExecutionPolicy', 'NativePassagePolicy')}
    paths.update({name: ROOT / name for name in ('tests/NativeDeuxNominationMemoryTest.java', 'tools/verify_deux_nomination.py', 'android/native-runtime.json')})
    if args.reference_native_deux:
        paths['android/src/com/cyberbasslord/lightforge/NativeDeux.java'] = args.reference_native_deux.resolve()
    bindings = {name: sha(path) for name, path in paths.items()}
    snapshots = work / 'source-snapshots'; classes = work / 'classes'; classes.mkdir()
    sources = []
    for name, original in paths.items():
        target = snapshots / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(original.read_bytes())
        require(sha(target) == bindings[name], 'Source changed while copied: ' + name)
        if name.endswith('.java'):
            sources.append(target)
    stub = snapshots / 'AppDiagnostics.java'
    stub.write_text('package com.cyberbasslord.lightforge; public final class AppDiagnostics {'
                    'public static void log(android.content.Context c,String l,String s,String m){}'
                    'public static boolean flush(long t){return true;}}\n')
    sources.append(stub)
    compiled = subprocess.run([str(java / 'javac'), '--release', '8', '-encoding', 'UTF-8', '-cp',
                               os.pathsep.join(map(str, dependencies)), '-d', str(classes), *map(str, sources)],
                              capture_output=True, text=True, timeout=90)
    (work / 'compile.log').write_text(compiled.stdout + compiled.stderr)
    require(compiled.returncode == 0, 'Compilation failed; inspect compile.log')
    class_hashes = {str(path.relative_to(classes)): sha(path) for path in sorted(classes.rglob('*.class'))}
    receipt = dict(schema='lightforge.nomination-memory-host-check.v1', passed=False, compiled=True,
                   inferencePerformed=False, compileOnly=args.compile_only,
                   scope='Actual original graph JNI; synthetic headroom and disclosed per-case delays. No performance, phone, full-passage, or release qualification.',
                   sourceBindings=bindings, compiledClassHashes=class_hashes, dependencyHashes=dependency_hashes,
                   historicalNativeDeuxOverride=str(args.reference_native_deux.resolve()) if args.reference_native_deux else None,
                   createdAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), cases=[])
    def save():
        (work / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    def unchanged():
        require({name: sha(path) for name, path in paths.items()} == bindings, 'Source changed during validation')
        require({str(path.relative_to(classes)): sha(path) for path in sorted(classes.rglob('*.class'))} == class_hashes,
                'Compiled classes changed during validation')
        require({path.name: sha(path) for path in dependencies} == dependency_hashes, 'Pinned dependencies changed')
    unchanged(); save()
    if args.compile_only:
        print(json.dumps(dict(compiled=True, inferencePerformed=False, receipt=str(work / 'receipt.json')))); return
    models = ROOT / 'web/analysis/models/deux'; manifest_path = models / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    require(sha(manifest_path) == frozen['modelManifestSha256'] and len(manifest['files']) == 27,
            'Original full-context model manifest changed')
    def verify_models():
        require(sha(manifest_path) == frozen['modelManifestSha256'], 'Model manifest changed during validation')
        for name, pin in manifest['files'].items():
            require((models / name).stat().st_size == pin['bytes'] and sha(models / name) == pin['sha256'] == frozen['modelHashes'][name],
                    'Original model graph changed: ' + name)
    verify_models()
    audio = ROOT / 'web/demo/glass-castle.wav'
    original = json.loads((ROOT / 'research/inference-2.4.1/production-parallel-qualification.json').read_text())
    require(original.get('audio') == {'sha256': sha(audio), 'startSample': 661500}, 'Original demo input changed')
    receipt.update(modelManifestSha256=sha(manifest_path), graphHashes=frozen['modelHashes'], audioSha256=sha(audio))
    affinity = sorted(os.sched_getaffinity(0))[:8]
    require(len(affinity) == 8, 'Eight real allowed CPUs required')
    receipt['childCpuAffinity'] = affinity
    for case in args.cases:
        unchanged()
        observation = dict(scenario=case, state='launch-attempted', passed=False)
        receipt['cases'].append(observation)
        if receipt['inferencePerformed'] is not True:
            receipt['inferencePerformed'] = None
        save()
        command = [str(java / 'java'), '-Xmx1g', '-XX:MaxDirectMemorySize=512m', '-cp',
                   os.pathsep.join(map(str, [classes, *dependencies])),
                   'com.cyberbasslord.lightforge.NativeDeuxNominationMemoryTest', str(models), str(audio), case, str(work / case)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=180,
                                    preexec_fn=lambda: os.sched_setaffinity(0, affinity))
        except subprocess.TimeoutExpired as error:
            def decoded(value):
                return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value or ''
            (work / (case + '.log')).write_text(decoded(error.stdout) + decoded(error.stderr))
            observation.update(state='timed-out', timeoutSeconds=180, errorClass=type(error).__name__)
            save()
            if args.reference_native_deux:
                continue
            raise
        except OSError as error:
            (work / (case + '.log')).write_text(str(error) + '\n')
            observation.update(state='launch-failed', errorClass=type(error).__name__, error=str(error))
            save()
            if args.reference_native_deux:
                continue
            raise
        (work / (case + '.log')).write_text(result.stdout + result.stderr)
        observation.update(state='exited', exitCode=result.returncode)
        try:
            actual = json.loads(result.stdout.strip().splitlines()[-1]); observation['observation'] = actual
            require(actual.get('schema') == 'lightforge.nomination-memory-orchestration.v1', 'Unexpected case evidence')
            receipt['inferencePerformed'] = True
        except (ValueError, IndexError):
            save(); raise
        observation['passed'] = result.returncode == 0 and actual.get('passed') is True
        save(); unchanged()
        # Preserve the actual failing negative-control receipt and continue other
        # requested cases; an historical override never turns a failure into PASS.
        if not observation['passed'] and not args.reference_native_deux:
            raise ValueError('Current nomination validation failed; inspect ' + case + '.log')
    receipt['passed'] = all(item['passed'] for item in receipt['cases'])
    verify_models(); require(sha(audio) == receipt['audioSha256'], 'Input audio changed during validation'); unchanged()
    receipt['sourceBindingsAfter'] = {name: sha(path) for name, path in paths.items()}
    receipt['finishedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat(); save()
    print(json.dumps(dict(passed=receipt['passed'], receipt=str(work / 'receipt.json'))))
    if not receipt['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
