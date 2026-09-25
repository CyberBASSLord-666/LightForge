#!/usr/bin/env python3
"""Compile real candidate API, then execute Java ownership tests at mock ORT boundaries.

This does not execute native inference, qualify JNI/CUDA ownership or admit timing.
Model preparation alone is substituted in the executed fixture; candidate lifecycle,
numerical/control-flow methods and JNI-result ownership source stay unchanged.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('game_reuse_lifecycle_generator', HERE.parent / 'session_reuse_candidate.py')
reuse = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reuse)
JSON_SHA = 'c243f45f9590c12694a4142ed3f07fc70dfb71e4daebd05ae234bf92a2da92a6'
SOURCE_SAMPLES = 24 * 44100


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fixture_source(candidate):
    begin = '    private void prepareModels(Cancellation cancellation) throws Exception {'
    end = '    private String digest(File file,Cancellation cancellation) throws Exception {'
    reuse.game.require(candidate.count(begin) == 1 and candidate.count(end) == 1,
                       'Model preparation fixture anchors changed.')
    prefix, body = candidate.split(begin)
    _, suffix = body.split(end)
    fixture = (prefix + begin + '\n        // MOCK LIFECYCLE FIXTURE ONLY: no model integrity/inference claim.\n'
               '        ai.onnxruntime.Control.prepare();\n    }\n' + end + suffix)
    reuse.game.require(fixture[:fixture.index(begin)] == candidate[:candidate.index(begin)] and
                       fixture[fixture.index(end):] == candidate[candidate.index(end):],
                       'Fixture changed methods beyond model preparation.')
    return fixture


def command(args, cwd, log, timeout=90):
    result = subprocess.run(list(map(str, args)), cwd=cwd, text=True, capture_output=True, timeout=timeout)
    log.write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f'Exit {result.returncode}; inspect {log}:\n{result.stdout[-1200:]}{result.stderr[-3000:]}')
    return result.stdout


def execute(output, java_home, dependencies):
    if output.exists():
        raise ValueError('Use a fresh output directory for lifecycle evidence.')
    if any(os.environ.get(key) for key in ('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS')):
        raise ValueError('Unset Java injection environment options.')
    java = java_home / 'bin/java'
    javac = java_home / 'bin/javac'
    compiler = [javac] if javac.is_file() else [java, '-m', 'jdk.compiler/com.sun.tools.javac.Main']
    json_jar = dependencies / 'test-json.jar'
    native = json.loads((ROOT / 'android/native-runtime.json').read_text())['host']
    ort_jar = dependencies / native['name']
    if sha(json_jar) != JSON_SHA or json_jar.stat().st_size != 90031:
        raise ValueError('Pinned JSON test dependency mismatch.')
    if sha(ort_jar) != native['sha256'] or ort_jar.stat().st_size != native['bytes']:
        raise ValueError('Pinned actual ORT API dependency mismatch.')
    output.mkdir(parents=True)
    receipt = dict(schema='lightforge.game-session-reuse-lifecycle-suite.v1', status='INCOMPLETE',
        runtime=dict(java=str(java), javaSha256=sha(java), modulesSha256=sha(java_home / 'lib/modules'),
                     compilerCommand=list(map(str, compiler))),
        originalSourceSha256=reuse.ORIGINAL_SHA256, sourceSamples=SOURCE_SAMPLES,
        dependencies={p.name: dict(bytes=p.stat().st_size, sha256=sha(p)) for p in (json_jar, ort_jar)},
        casesPerVariant={}, variants={}, actualNativeExecution=False, nativeJniLifecycleQualified=False,
        realOrtApiCompiled=False, cudaExecuted=False, modelPreparationSubstituted=True,
        withinProviderParityProven=False, benchmarkTimingAdmitted=False, qualityApproved=False,
        target75Proven=False, appLifecycleEquivalent=False, releaseAuthorized=False,
        limitations=['ORT handles, kernels, tensor values and destructor behavior are Java controls, not JNI.',
                     'Fixture substitutes model preparation; no real graph files are loaded or model hashes tested.',
                     'Exact generated candidates compile against pinned real ORT API; execution uses a separate mock classpath.',
                     'No Android lifecycle, native fault semantics, GPU execution, numerical equivalence or timing qualification.'])
    try:
        command([java, '-version'], output, output / 'java-version.log')
        command(compiler + ['-version'], output, output / 'compiler-version.log')
        original = reuse.game.SOURCE.read_text()
        android_stubs = sorted((HERE / 'android').rglob('*.java'))
        mock_sources = sorted(HERE.rglob('*.java'))
        source_copy = output / 'fixture-sources'
        for path in mock_sources:
            target = source_copy / path.relative_to(HERE)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        for variant in reuse.VARIANTS:
            directory = output / variant
            exact = directory / 'exact-api'
            fixture = directory / 'mock-execution'
            for base in (exact, fixture):
                (base / 'classes').mkdir(parents=True)
            candidate = reuse.generate(original, variant, source_samples=SOURCE_SAMPLES)
            candidate_file = exact / 'NativeGame.java'
            candidate_file.write_text(candidate)
            command(compiler + ['--release', '8', '-encoding', 'UTF-8', '-cp', os.pathsep.join(map(str, (json_jar, ort_jar))),
                '-d', exact / 'classes', candidate_file, *android_stubs], output, exact / 'compile.log')
            fixture_file = fixture / 'NativeGame.java'
            fixture_file.write_text(fixture_source(candidate))
            command(compiler + ['--release', '8', '-encoding', 'UTF-8', '-cp', json_jar, '-d', fixture / 'classes',
                fixture_file, *mock_sources], output, fixture / 'compile.log')
            models = fixture / 'models'
            models.mkdir()
            shutil.copyfile(ROOT / 'web/analysis/models/game/manifest.json', models / 'manifest.json')
            stdout = command([java, '-Xmx512m', '-cp', os.pathsep.join(map(str, (fixture / 'classes', json_jar))),
                'com.cyberbasslord.lightforge.GameReuseLifecycleTest', models], output, fixture / 'run.log')
            result = json.loads(stdout)
            if result.get('status') != 'MOCK_BOUNDARIES_PASSED' or result.get('caseCount', 0) < 40:
                raise ValueError('Missing complete controlled lifecycle result.')
            (fixture / 'result.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
            receipt['casesPerVariant'][variant] = result['caseCount']
            receipt['variants'][variant] = dict(candidateSha256=sha(candidate_file), fixtureSha256=sha(fixture_file),
                                                resultSha256=sha(fixture / 'result.json'))
        receipt['realOrtApiCompiled'] = True
        receipt['status'] = 'PASSED_MOCK_LIFECYCLE_AND_REAL_API_COMPILATION'
    finally:
        bindings = [Path(__file__), HERE.parent / 'session_reuse_candidate.py', reuse.game.SOURCE,
                    ROOT / 'tools/benchmark_game_accelerator.py', *sorted(HERE.rglob('*.java'))]
        receipt['sourceBindings'] = {str(p.relative_to(ROOT)): sha(p) for p in bindings}
        receipt['outputBindings'] = {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob('*')) if p.is_file()}
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--java-home', type=Path, default=Path(os.environ.get('LIGHTFORGE_JAVA_HOME', '/usr/lib/jvm/java-17-openjdk-amd64')))
    parser.add_argument('--dependencies', type=Path, default=ROOT.parent / 'reuse-lifecycle-deps')
    args = parser.parse_args()
    print(json.dumps(execute(args.output.resolve(), args.java_home.resolve(), args.dependencies.resolve()), indent=2))
