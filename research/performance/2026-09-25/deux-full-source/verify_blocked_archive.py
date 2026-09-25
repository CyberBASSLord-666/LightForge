#!/usr/bin/env python3
"""Verify the retained failed trace collection without promoting it to qualification."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import zipfile

EXPECTED_SIZE = 132558003
EXPECTED_SHA = '41d0ca6a25ddfa80a325ae71d5ad9930cf6d9a78480d6c63461c6abe3a14f624'
COMMIT = '85bca325b65f93790a17bfd9142dad80162384b2'
TREE = 'b703f823fb7da8f36eb4461c4f139ddda0df2038'
ROOT_NAME = 'deux-full-source-cpu-20260925-01'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', type=Path, required=True)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not args.zip.is_symlink() and args.zip.stat().st_size == EXPECTED_SIZE
    with args.zip.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == EXPECTED_SHA
    assert subprocess.check_output(['git', '-C', str(args.repo), 'rev-parse', COMMIT + '^{tree}'], text=True).strip() == TREE
    assert not args.output.exists(), 'Use a new verification report.'
    with zipfile.ZipFile(args.zip) as archive:
        rows = archive.infolist()
        assert len(rows) == 383 and len({row.filename for row in rows}) == len(rows)
        assert sum(row.file_size for row in rows) < 2 * 1024**3
        for row in rows:
            name = PurePosixPath(row.filename)
            assert not name.is_absolute() and '\\' not in row.filename
            assert all(part not in ('', '.', '..') for part in row.filename.split('/'))
            assert name.parts[0] == ROOT_NAME and len(name.parts) > 1
            assert not row.is_dir() and not row.flag_bits & 1
            assert stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG)
        assert archive.testzip() is None
        def read(relative):
            return archive.read(ROOT_NAME + '/' + relative)
        manifest = json.loads(read('archive-manifest.json'))
        assert manifest['executionSourceCommit'] == COMMIT and manifest['executionSourceTree'] == TREE
        assert manifest['status'] == 'BLOCKED_OR_REJECTED' and manifest['publicFixtureOnly'] is True
        inventory = {row['path']: row for row in manifest['files']}
        assert len(inventory) == len(manifest['files']) == 382
        assert set(inventory) == {row.filename[len(ROOT_NAME)+1:] for row in rows} - {'archive-manifest.json'}
        frozen = 0
        for relative, pin in inventory.items():
            data = read(relative)
            assert len(data) == pin['bytes'] and digest(data) == pin['sha256']
            if relative.startswith('execution-source/'):
                original = subprocess.check_output(['git', '-C', str(args.repo), 'show', COMMIT + ':' + relative[len('execution-source/'):]])
                assert data == original
                frozen += 1
        assert frozen == 21
        driver = json.loads(read('driver-receipt.json'))
        assert driver['status'] == 'BLOCKED_OR_REJECTED' and driver['qualificationExitCode'] == 1
        assert driver['executionSourceCommit'] == COMMIT and driver['executionSourceTree'] == TREE
        for key in ('qualityApproved', 'target75Proven', 'benchmarkTimingAdmitted', 'releaseAuthorized', 'cudaExecuted'):
            assert driver[key] is False and manifest[key] is False
        log = read('qualification/snapshots/cpu_all_profiled/run.log').decode()
        assert 'Exactly 27 completed passage traces required' in log
        active = {p.rsplit('/', 1)[1]: p for p in inventory if p.startswith('qualification/cpu_all_profiled_active_traces/')}
        previous = {p.rsplit('/', 1)[1]: p for p in inventory if p.startswith('qualification/cpu_all_profiled/passage-003/traces/')}
        assert len(active) == 54 and len(previous) == 27 and set(previous) <= set(active)
        for name, relative in previous.items():
            assert read(relative) == read(active[name])
        completed = {arm: sum(p.startswith('qualification/' + arm + '/passage-') and p.endswith('/receipt.json') for p in inventory)
                     for arm in ('cpu_all_plain', 'cpu_all_profiled')}
        assert completed == dict(cpu_all_plain=12, cpu_all_profiled=4)
    result = dict(schema='lightforge.deux-blocked-archive-integrity.v1', status='VERIFIED_INTEGRITY_BLOCKED',
        archive=dict(bytes=EXPECTED_SIZE, sha256=EXPECTED_SHA), memberCount=383, allMemberCrcsAndPinsVerified=True,
        executionSourceCommit=COMMIT, executionSourceTree=TREE, exactGitSourceFiles=frozen,
        completedPassageReceipts=completed, activeTraceFiles=54, previousPassageTracesReappearedByteIdentically=27,
        causeAttribution='Reappeared prior-passage bytes confirmed; the actor or mechanism that recreated them is not established.',
        completeDiagnosticVerified=False, modelInferenceExecuted=False, cudaExecuted=False,
        qualityApproved=False, target75Proven=False, benchmarkTimingAdmitted=False, releaseAuthorized=False,
        verifierSha256=digest(Path(__file__).read_bytes()))
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
