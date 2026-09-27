#!/usr/bin/env python3
"""Preserve this one rejected run without changing its files or accepting its outputs."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

COMMIT = '925fc91ecb198141901ef62eb55feb7d7e43c3a0'
TREE = '8d2160d126bf0adb5698a94471c44cd09b8df36b'
RUN = 'deux-full-source-cpu-20260925-02'
EXPORTER = 'research/performance/2026-09-25/deux-full-source/export_evidence.py'
EXPORTER_SHA = 'de5999554d55995ddce68ce8c29ec6e21f27f58eaef08c774f310462af427c6c'
FLAGS = ('qualityApproved', 'target75Proven', 'benchmarkTimingAdmitted',
         'releaseAuthorized', 'cudaExecuted', 'fullVocalStageExecuted')
PARTIAL = re.compile(r'qualification/cpu_all_plain/passage-(00[0-9]|01[01])/\.native-deux-[0-9]{1,20}\.partial')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pin(path):
    require(path.is_file() and not path.is_symlink(), 'Expected regular evidence file')
    with path.open('rb') as stream:
        return dict(bytes=path.stat().st_size, sha256=hashlib.file_digest(stream, 'sha256').hexdigest())


def inventory(run, sources, allowed):
    rows = {}
    total = 0
    for path in sorted(run.rglob('*')):
        require(not path.is_symlink(), 'Linked evidence rejected')
        require(path.is_dir() or path.is_file(), 'Nonregular evidence rejected')
        if not path.is_file():
            continue
        relative = path.relative_to(run)
        name = relative.as_posix()
        require(allowed(relative, sources), 'Unreviewed archive member: ' + name)
        if name.endswith('.partial'):
            require(PARTIAL.fullmatch(name), 'Unexpected partial member: ' + name)
        row = pin(path)
        require(row['bytes'] <= 16 * 1024**2, 'Member bound exceeded')
        total += row['bytes']
        require(total <= 128 * 1024**2 and len(rows) < 256, 'Inventory bound exceeded')
        rows[name] = row
    require(len(rows) == 181, 'This helper only preserves the inspected 181-file failure')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    require(args.run.is_dir() and not args.run.is_symlink() and args.run.name == RUN, 'Unexpected failed run')
    run, repo = args.run.resolve(), args.repo.resolve()
    for path in (args.output, args.report):
        require(not path.exists() and not path.is_symlink() and not path.resolve().is_relative_to(run), 'Use a new destination outside the failed run')
    require(args.output.resolve() != args.report.resolve(), 'Separate archive and report destinations required')
    git = lambda *tail: subprocess.check_output(['git', '-C', str(repo), *tail])
    require(git('rev-parse', COMMIT + '^{tree}').decode().strip() == TREE, 'Wrong execution tree')
    exporter_bytes = git('show', COMMIT + ':' + EXPORTER)
    require(sha(exporter_bytes) == EXPORTER_SHA, 'Wrong frozen exporter')
    driver = json.loads((run / 'driver-receipt.json').read_text())
    require(driver['status'] == 'BLOCKED_OR_REJECTED' and driver['executionSourceCommit'] == COMMIT
            and driver['executionSourceTree'] == TREE and driver['qualificationExitCode'] == 1,
            'Only the exact rejected execution may be preserved')
    require(driver['variants'] == ['cpu_all'] and all(driver[key] is False for key in FLAGS), 'Unexpected execution or approval claims')
    bindings = json.loads((run / 'runtime-input-bindings.json').read_text())
    require(bindings['sourceCommit'] == COMMIT and bindings['sourceTree'] == TREE, 'Runtime source mismatch')
    sources = bindings['sources']
    require(len(sources) == 22, 'Expected 22 exact execution source files')
    for name, expected in sources.items():
        require(not Path(name).is_absolute() and all(part not in ('', '.', '..') for part in name.split('/')), 'Unsafe source path')
        original = git('show', COMMIT + ':' + name)
        require(expected == dict(bytes=len(original), sha256=sha(original)), 'Git source pin mismatch')
        require((run / 'execution-source' / name).read_bytes() == original, 'Copied source differs from Git')
    qualification = json.loads((run / 'qualification/receipt.json').read_text())
    require(qualification['status'] == 'BLOCKED_OR_REJECTED'
            and qualification['failure'] == 'ValueError: Unexpected passage output member.'
            and qualification['runs'] == [] and qualification['observerComparisons'] == [],
            'Unexpected rejected qualification state')
    require(not (run / 'qualification/cpu_all_profiled').exists()
            and not (run / 'qualification/snapshots/cpu_all_profiled').exists()
            and not (run / 'consumer').exists(), 'This failure must precede profiled execution and replay')
    completed = sorted((run / 'qualification/cpu_all_plain').glob('passage-*/receipt.json'))
    require(len(completed) == 12, 'Expected 12 plain passage receipts')
    for index, path in enumerate(completed):
        receipt = json.loads(path.read_text())
        require(path.parent.name == f'passage-{index:03d}' and receipt['index'] == index
                and receipt['predictReturned'] is True and receipt['profiled'] is False,
                'Unexpected plain receipt')
        require(pin(path.parent / 'stems.f32') == dict(bytes=receipt['outputBytes'], sha256=receipt['outputSha256'])
                and receipt['outputBytes'] == 4586400, 'Completed public-derived output pin mismatch')
        require(pin(path.parent / 'profile.txt')['sha256'] == receipt['profileSha256'], 'Stage profile pin mismatch')
    partials = []
    for path in sorted(run.rglob('.native-deux-*.partial')):
        name = path.relative_to(run).as_posix()
        require(PARTIAL.fullmatch(name), 'Unexpected partial path')
        data = path.read_bytes()
        require(len(data) in (0, 2293200) and data == (path.parent / 'stems.f32').read_bytes()[:len(data)],
                'Partial must be empty or the exact first half of the retained public-derived output')
        partials.append(dict(path=name, **pin(path), exactOutputPrefix=True))
    require(len(partials) == 11 and [int(PARTIAL.fullmatch(row['path']).group(1)) for row in partials]
            == [0, *range(2, 12)], 'Unexpected partial inventory')
    require([row['bytes'] for row in partials] == [0] + [2293200] * 10, 'Unexpected partial sizes')

    # The original exporter writes an archive manifest. Give it a byte-identical
    # scratch snapshot so that it cannot write anything into the rejected run.
    with tempfile.TemporaryDirectory(prefix='deux-blocked-preservation-', dir=str(args.output.resolve().parent)) as temporary:
        temporary = Path(temporary)
        exporter_path = temporary / 'frozen_exporter.py'
        exporter_path.write_bytes(exporter_bytes)
        spec = importlib.util.spec_from_file_location('frozen_deux_exporter', exporter_path)
        exporter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(exporter)
        before = inventory(run, sources, exporter.allowed)
        snapshot = temporary / RUN
        snapshot.mkdir()
        for relative, expected in before.items():
            destination = snapshot / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(run / relative, destination)
            require(pin(destination) == expected, 'Snapshot copy changed')
        result = exporter.export(snapshot, args.output)
        with zipfile.ZipFile(args.output) as archive:
            members = archive.infolist()
            require(len(members) == 182 and len({row.filename for row in members}) == 182, 'Unexpected archive inventory')
            require(archive.testzip() is None, 'Archive CRC failure')
            manifest = json.loads(archive.read(RUN + '/archive-manifest.json'))
            archived = {row['path']: {key: row[key] for key in ('bytes', 'sha256')} for row in manifest['files']}
            require(archived == before and len(manifest['files']) == len(before), 'Archive inventory differs from original failure')
            require(manifest['status'] == 'BLOCKED_OR_REJECTED' and all(manifest[key] is False for key in FLAGS), 'Archive cannot grant approval')
            require({row.filename for row in members} == {RUN + '/' + name for name in before} | {RUN + '/archive-manifest.json'}, 'Unexpected archive members')
            for name, expected in before.items():
                data = archive.read(RUN + '/' + name)
                require(dict(bytes=len(data), sha256=sha(data)) == expected, 'Archive bytes differ from failed run')
        require(inventory(run, sources, exporter.allowed) == before, 'Original failed evidence changed during preservation')
    report = dict(schema='lightforge.deux-retry02-blocked-preservation.v1', status='VERIFIED_INTEGRITY_BLOCKED',
                  archive=pin(args.output), memberCount=182, originalFiles=181, allMemberCrcsAndPinsVerified=True,
                  executionSourceCommit=COMMIT, executionSourceTree=TREE, exactGitSourceFiles=22,
                  completedPassageReceipts=dict(cpu_all_plain=12, cpu_all_profiled=0), acceptedCollectorRuns=0,
                  failure=qualification['failure'], retainedPartials=partials,
                  partialCauseAttribution='The actor or mechanism responsible for the remaining or reappeared temporary files is not established.',
                  originalFailedEvidenceChanged=False, completeDiagnosticVerified=False, modelInferenceExecuted=False,
                  cudaExecuted=False, fullVocalStageExecuted=False, qualityApproved=False, target75Proven=False,
                  benchmarkTimingAdmitted=False, releaseAuthorized=False,
                  frozenExporterSha256=EXPORTER_SHA, preservationHelperSha256=sha(Path(__file__).read_bytes()))
    with args.report.open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps(dict(result, report=str(args.report), originalFiles=181, retainedPartials=11), indent=2))


if __name__ == '__main__':
    main()
