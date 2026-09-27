#!/usr/bin/env python3
"""Export bounded public GAME session-reuse evidence; never include model/runtime binaries."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile


def pin(path):
    with path.open('rb') as stream:
        return dict(bytes=path.stat().st_size, sha256=hashlib.file_digest(stream, 'sha256').hexdigest())


def allowed(relative):
    name = relative.as_posix()
    if name.startswith('execution-source/'):
        return relative.suffix in ('.py', '.js', '.cjs', '.java', '.json', '.md')
    if len(relative.parts) == 1:
        return name in ('driver-receipt.json', 'runtime-input-bindings.json', 'host-preparation-receipt.json',
            'input-provenance.json', 'input-source-proof.json', 'input-source-proof.log',
            'public-demo-mixture-full64s.f32', 'readiness.log', 'qualification.log')
    if relative.parts[0] not in ('readiness', 'qualification'):
        return False
    if relative.suffix in ('.json', '.java', '.class', '.patch', '.log', '.txt'):
        return True
    return bool(re.fullmatch(r'qualification/cpu_all_(?:default|reuse)_(?:captured|profiled)/output/passage-\d{3}/[A-Za-z0-9_-]+\.bin', name))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not args.run.is_symlink() and args.run.is_dir()
    run, output = args.run.resolve(), args.output.resolve()
    assert not output.exists() and not output.is_relative_to(run), 'Use a new archive outside the run.'
    driver = json.loads((run / 'driver-receipt.json').read_text())
    assert driver['schema'] == 'lightforge.game-session-reuse-driver.v1'
    assert driver['status'] in ('COMPLETE_DIAGNOSTIC', 'BLOCKED_OR_REJECTED')
    assert driver['variants'] == ['cpu_all'] and driver['cudaExecuted'] is False
    for key in ('qualityApproved', 'target75Proven', 'benchmarkTimingAdmitted', 'releaseAuthorized'):
        assert driver[key] is False
    entries = []
    for path in sorted(run.rglob('*')):
        assert not path.is_symlink(), 'Refusing a linked evidence member.'
        if path.is_file():
            relative = path.relative_to(run)
            assert allowed(relative), 'Unreviewed archive member: ' + relative.as_posix()
            entries.append(dict(path=relative.as_posix(), **pin(path)))
    pcm = next(row for row in entries if row['path'] == 'public-demo-mixture-full64s.f32')
    assert pcm['bytes'] == 11289600 and pcm['sha256'] == '298f7a549c4bb8dfc53c47d1078cea842c5e818a3e7c82bf289bffcec0ba30c2'
    manifest = dict(schema='lightforge.game-session-reuse-archive.v1', runDirectory=run.name,
        executionSourceCommit=driver['executionSourceCommit'], executionSourceTree=driver['executionSourceTree'],
        status=driver['status'], files=entries, publicFixtureOnly=True, cudaExecuted=False,
        qualityApproved=False, target75Proven=False, benchmarkTimingAdmitted=False, releaseAuthorized=False)
    with (run / 'archive-manifest.json').open('x') as stream:
        json.dump(manifest, stream, indent=2, allow_nan=False)
        stream.write('\n')
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for row in entries:
            path = run / row['path']
            assert pin(path) == {key: row[key] for key in ('bytes', 'sha256')}, 'Evidence changed during export.'
            archive.write(path, arcname=run.name + '/' + row['path'])
        archive.write(run / 'archive-manifest.json', arcname=run.name + '/archive-manifest.json')
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
    print(json.dumps(dict(archive=output.name, **pin(output), members=len(entries) + 1,
        status=driver['status'], qualityApproved=False, target75Proven=False), indent=2))


if __name__ == '__main__':
    main()
