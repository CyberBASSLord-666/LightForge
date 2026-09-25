#!/usr/bin/env python3
"""Run one frozen CPU-only session-reuse qualification on the public fixture.

Models and runtimes must already be prepared. Evidence is never overwritten.
This driver performs no download, GPU execution, timing approval or publication.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
PCM_SHA = '298f7a549c4bb8dfc53c47d1078cea842c5e818a3e7c82bf289bffcec0ba30c2'
WAV_SHA = '33f07d502ba19832b62b97d8fb4a11354e81310264bd885d7a06438228773650'
COLLECTOR = 'tools/benchmark_game_session_reuse.py'
OLD_DRIVER = 'research/performance/2026-09-24/game-full-source/colab_run.py'


def pin(path):
    path = Path(path)
    assert path.is_file() and not path.is_symlink(), f'Missing or linked input: {path}'
    with path.open('rb') as stream:
        return dict(bytes=path.stat().st_size, sha256=hashlib.file_digest(stream, 'sha256').hexdigest())


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def git_blob(commit, relative):
    return subprocess.check_output(['git', 'show', f'{commit}:{relative}'], cwd=ROOT)


def exact_source(commit, relative):
    data = git_blob(commit, relative)
    assert (ROOT / relative).read_bytes() == data, f'Uncommitted execution source: {relative}'
    return data


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def jdk_inventory(root):
    files, links = {}, {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            assert path.resolve().is_relative_to(root.resolve()), 'JDK link leaves its pinned installation.'
            links[relative] = path.readlink().as_posix()
        elif path.is_file():
            files[relative] = pin(path)
    assert all(name in files for name in ('bin/java', 'bin/javac', 'lib/modules', 'lib/server/libjvm.so'))
    return files, links


def stage(command, log_path, receipt_path, cleanup):
    with log_path.open('x') as log:
        process = subprocess.Popen(list(map(str, command)), cwd=ROOT, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        previous = None
        try:
            while process.poll() is None:
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    pass
                if receipt_path.is_file():
                    receipt = json.loads(receipt_path.read_text())
                    progress = (receipt.get('status'), len(receipt.get('runs', [])))
                    if progress != previous:
                        print(log_path.stem, *progress, flush=True)
                        previous = progress
        finally:
            cleanup.retire_stage(process)
    return process.returncode


def main():
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Host research driver terminated')
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-commit', 'source-tree'):
        parser.add_argument('--' + name, required=True)
    for name in ('toolchain', 'models', 'input-bundle', 'public-wav', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    assert subprocess.check_output(['git', 'rev-parse', args.source_commit + '^{tree}'], cwd=ROOT,
                                   text=True).strip() == args.source_tree
    for relative in (COLLECTOR, OLD_DRIVER, str(Path(__file__).relative_to(ROOT))):
        exact_source(args.source_commit, relative)
    # Imported helpers are checked against the same frozen Git tree below before execution.
    collector = load('local_reuse_collector', COLLECTOR)
    cleanup = load('local_reuse_cleanup', OLD_DRIVER)
    sources = set(collector.SOURCE_BINDINGS) | {OLD_DRIVER, str(Path(__file__).relative_to(ROOT)),
        'web/analysis/wav-reader.js', 'web/analysis/game.js', 'web/analysis/models/game/config.json',
        'tools/game_benchmark/verify_session_reuse_evidence.py'}
    source_bytes = {relative: exact_source(args.source_commit, relative) for relative in sorted(sources)}
    assert pin(args.public_wav)['sha256'] == WAV_SHA
    expected_pcm = args.input_bundle / 'public-demo-mixture-full64s.f32'
    assert pin(expected_pcm) == dict(bytes=11289600, sha256=PCM_SHA)
    assert not args.output.exists(), 'Use a new evidence directory.'
    args.output.mkdir(parents=True)
    status = dict(schema='lightforge.game-session-reuse-driver.v1', status='INCOMPLETE',
        createdUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        executionSourceCommit=args.source_commit, executionSourceTree=args.source_tree,
        variants=['cpu_all'], cudaExecuted=False, qualityApproved=False,
        target75Proven=False, benchmarkTimingAdmitted=False, releaseAuthorized=False)
    try:
        for relative, data in source_bytes.items():
            target = args.output / 'execution-source' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(data)
        for name in ('public-demo-mixture-full64s.f32', 'input-provenance.json'):
            shutil.copyfile(args.input_bundle / name, args.output / name)
        # Re-run the unchanged production WAV reader proof on actual public WAV bytes.
        proof = args.output / 'input-source-proof.json'
        with (args.output / 'input-source-proof.log').open('x') as log:
            subprocess.run(['node', '-e', cleanup.NODE_PROOF, str(ROOT), str(args.public_wav),
                str(args.output / 'public-demo-mixture-full64s.f32'), str(proof)],
                stdout=log, stderr=subprocess.STDOUT, check=True, timeout=90)
        provenance = json.loads((args.output / 'input-provenance.json').read_text())
        assert provenance['inputSourceProofSha256'] == pin(proof)['sha256'], 'Actual source proof changed.'
        manifest = collector.game.verify_models(args.models)
        runtime = json.loads((ROOT / 'android/native-runtime.json').read_text())
        dependencies = [args.toolchain / 'test-json.jar',
            args.toolchain / 'android-sdk/platforms/android-35/android.jar',
            args.toolchain / 'onnx' / runtime['host']['name']]
        jdk_files, jdk_links = jdk_inventory(args.toolchain / 'jdk17')
        jdk_archive = pin(args.toolchain / 'downloads/jdk17.tar.gz')
        assert jdk_archive == dict(bytes=193252603,
            sha256='3808d1d15e3ec6bd5b84057fb5d84c33d8a1536a258146bcea2e603fc726e08e')
        bindings = dict(schema='lightforge.game-session-reuse-runtime-bindings.v1',
            sourceCommit=args.source_commit, sourceTree=args.source_tree,
            models={name: pin(args.models / name) for name in ['manifest.json', *manifest['files']]},
            dependencies={path.name: pin(path) for path in dependencies},
            jdk=jdk_files, jdkSymlinks=jdk_links, jdkArchive=jdk_archive,
            publicWav=pin(args.public_wav), fullPcm=pin(args.output / 'public-demo-mixture-full64s.f32'),
            sources={relative: pin(ROOT / relative) for relative in sorted(sources)},
            variants=['cpu_all'], cudaExecuted=False, qualityApproved=False, target75Proven=False)
        write(args.output / 'runtime-input-bindings.json', bindings)
        prep = args.toolchain / 'host-preparation-receipt.json'
        shutil.copyfile(prep, args.output / 'host-preparation-receipt.json')
        status['hostPreparationReceipt'] = pin(prep)
        base = [sys.executable, ROOT / COLLECTOR, '--toolchain', args.toolchain, '--models', args.models,
            '--input', args.output / 'public-demo-mixture-full64s.f32',
            '--input-provenance', args.output / 'input-provenance.json', '--variants', 'cpu_all']
        status['stageLogs'] = {}
        for name, extra in (('readiness', ['--check-readiness']), ('qualification', [])):
            destination = args.output / name
            code = stage([*base, '--output', destination, *extra], args.output / (name + '.log'),
                         destination / 'receipt.json', cleanup)
            status[name + 'ExitCode'] = code
            status['stageLogs'][name] = pin(args.output / (name + '.log'))
            assert code == 0, f'{name} failed; inspect retained evidence.'
        final = json.loads((args.output / 'qualification/receipt.json').read_text())
        for relative, data in source_bytes.items():
            assert (ROOT / relative).read_bytes() == data, f'Execution source changed: {relative}'
        assert bindings['models'] == {name: pin(args.models / name) for name in bindings['models']}
        assert bindings['dependencies'] == {path.name: pin(path) for path in dependencies}
        assert (bindings['jdk'], bindings['jdkSymlinks']) == jdk_inventory(args.toolchain / 'jdk17')
        assert bindings['fullPcm'] == pin(args.output / 'public-demo-mixture-full64s.f32')
        status.update(status='COMPLETE_DIAGNOSTIC', qualificationStatus=final['status'],
            completedJvmRuns=len(final['runs']), allBoundInputsRechecked=True,
            qualificationReceipt=pin(args.output / 'qualification/receipt.json'))
    except BaseException as error:
        status.update(status='BLOCKED_OR_REJECTED', failure=f'{type(error).__name__}: {error}')
        raise
    finally:
        write(args.output / 'driver-receipt.json', status)
        print(json.dumps(status, indent=2), flush=True)


if __name__ == '__main__':
    main()
