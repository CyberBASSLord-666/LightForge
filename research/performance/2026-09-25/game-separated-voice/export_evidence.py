#!/usr/bin/env python3
"""Export a bounded completed separated-voice diagnostic; no model/runtime binaries."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

MAX_FILES, MAX_MEMBER, MAX_TOTAL = 4097, 512 * 1024**2, 8 * 1024**3
CLASS_NAMES = {'NativeGame.class', 'NativeGame$Owned.class', 'NativeGame$Cancellation.class',
    'NativeGame$Listener.class', 'GameAcceleratorCapture.class', 'GameAcceleratorCapture$1.class',
    'GameSessionReuseRunner.class', 'GameSessionReuseTrace.class'}
TENSOR_NAMES = {'bd2dur-durations.bin', 'bd2dur-maskN.bin', 'dur2bd-boundaries.bin',
    'encoder-maskT.bin', 'encoder-x_est.bin', 'encoder-x_seg.bin',
    'estimator-presence.bin', 'estimator-scores.bin'}


def require(value, message):
    if not value:
        raise ValueError(message)


def pin(path):
    require(path.is_file() and not path.is_symlink(), 'Regular unlinked artifact required')
    with path.open('rb') as stream:
        return dict(bytes=path.stat().st_size, sha256=hashlib.file_digest(stream, 'sha256').hexdigest())


def allowed(relative, sources):
    name = relative.as_posix()
    if relative.is_absolute() or any(part in ('.', '..') for part in relative.parts) or '\\' in name:
        return False
    if name in {'driver-receipt.json', 'bindings.json', 'input-proof.json', 'input-provenance.json',
                'voice-full.f32', 'upstreamAudit.log', 'input.log', 'qualification.log', 'consumer.log'}:
        return True
    if name.startswith('execution-source/'):
        return name.removeprefix('execution-source/') in sources and relative.suffix in {'.py', '.cjs', '.js', '.java', '.json'}
    if name == 'upstream-verification-source/research/performance/2026-09-25/deux-full-source/verify_evidence.py':
        return True
    if name.startswith('source-artifacts/'):
        return relative.name in {'voice-full.wav', 'upstream-driver-receipt.json', 'upstream-qualification-receipt.json',
            'upstream-consumer-receipt.json', 'upstream-verification.json', 'upstream-runtime-input-bindings.json'} and len(relative.parts) == 2
    if name in {'upstream-audit/verification.json', 'upstream-audit/consumer-replay.log',
                'upstream-audit/consumer-replayed/receipt.json', 'consumer/receipt.json'}:
        return True
    if name.startswith('upstream-audit/consumer-replayed/cpu_all/'):
        return relative.name in {'voice-full.wav', 'vocals.wav', 'accompaniment.wav'} and len(relative.parts) == 4
    if name == 'qualification/receipt.json':
        return True
    if name.startswith('qualification/cpu_all-runtime-probe/'):
        return len(relative.parts) == 3 and relative.name in {'RuntimeProbe.java', 'RuntimeProbe.class', 'compile.log', 'probe.log'}
    if re.fullmatch(r'qualification/cpu_all_profiled_lifetime_traces/(encoder|dur2bd|segmenter|bd2dur|estimator)_s00[0-5]_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_\d{3}\.json', name):
        return True
    match = re.fullmatch(r'qualification/cpu_all_(plain|captured|profiled)/(.+)', name)
    if match:
        mode, tail = match.groups()
        if tail in {'NativeGame.java', 'GameSessionReuseRunner.java', 'GameSessionReuseTrace.java',
                    'GameAcceleratorCapture.java', 'compile.log', 'run.log', 'generated.patch', 'output/receipt.json'}:
            return True
        if tail.startswith('classes/com/cyberbasslord/lightforge/'):
            return tail.removeprefix('classes/com/cyberbasslord/lightforge/') in CLASS_NAMES
        if tail == 'output/trace-markers.json':
            return mode == 'profiled'
        passage = re.fullmatch(r'output/passage-00([0-5])/([^/]+)', tail)
        if passage:
            ordinal, filename = int(passage[1]), passage[2]
            if filename == 'receipt.json':
                return True
            if mode == 'plain':
                return False
            if filename in TENSOR_NAMES:
                return True
            segmenter = re.fullmatch(r'segmenter-(0|[1-9][0-9]*)-boundaries\.bin', filename)
            return bool(segmenter and 8*ordinal <= int(segmenter[1]) < 8*(ordinal+1))
    return False


def export(run, destination):
    require(run.is_dir() and not run.is_symlink(), 'Original evidence directory required')
    require(not destination.exists() and not destination.is_symlink() and not destination.resolve().is_relative_to(run.resolve()),
            'Use a new ZIP outside the input evidence')
    driver = json.loads((run/'driver-receipt.json').read_text())
    bindings = json.loads((run/'bindings.json').read_text())
    require(driver['schema'] == 'lightforge.game-separated-voice-driver.v1' and
            driver['status'] == 'COMPLETE_CPU_REFERENCE_DIAGNOSTIC' and driver['allBoundInputsRechecked'] is True and
            driver['completedJvmRuns'] == 3 and all(driver[k] is False for k in
            ('qualityApproved', 'target75Proven', 'benchmarkTimingAdmitted', 'releaseAuthorized')), 'Completed diagnostic required')
    manifest_path = run/'archive-manifest.json'
    require(not manifest_path.exists(), 'Evidence was already exported; preserve its original manifest')
    rows = []
    for artifact in sorted(run.rglob('*')):
        require(not artifact.is_symlink() and (artifact.is_dir() or artifact.is_file()), 'Special evidence artifact')
        if artifact.is_file():
            relative = artifact.relative_to(run)
            require(allowed(relative, bindings['sources']), 'Artifact is outside bounded export: '+str(relative))
            identity = pin(artifact)
            require(identity['bytes'] <= MAX_MEMBER, 'Oversized evidence member')
            rows.append(dict(path=relative.as_posix(), **identity))
            require(len(rows) < MAX_FILES and sum(row['bytes'] for row in rows) <= MAX_TOTAL, 'Evidence export bound exceeded')
    manifest = dict(schema='lightforge.game-separated-voice-archive.v1', runDirectory=run.name,
        executionSourceCommit=driver['executionSourceCommit'], executionSourceTree=driver['executionSourceTree'],
        upstreamEvidenceMustBeSuppliedSeparately=True, files=rows, modelRuntimeBytesIncluded=False,
        qualityApproved=False, benchmarkTimingAdmitted=False, target75Proven=False, releaseAuthorized=False)
    with manifest_path.open('x') as stream:
        json.dump(manifest, stream, indent=2, allow_nan=False); stream.write('\n')
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for row in rows:
            artifact = run/row['path']
            require(pin(artifact) == {k: row[k] for k in ('bytes', 'sha256')}, 'Artifact changed during export')
            archive.write(artifact, run.name+'/'+row['path'])
        archive.write(manifest_path, run.name+'/archive-manifest.json')
    with zipfile.ZipFile(destination) as archive:
        require(archive.testzip() is None, 'ZIP CRC verification failed')
    return dict(archive=str(destination), **pin(destination), files=len(rows)+1, allMemberCrcsVerified=True,
                upstreamEvidenceMustBeSuppliedSeparately=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.run, args.output)))


if __name__ == '__main__':
    main()
