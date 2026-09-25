#!/usr/bin/env python3
"""Export only explicitly reviewed public Deux diagnostic evidence, never models or runtimes."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

WAV = dict(bytes=11289644, sha256='33f07d502ba19832b62b97d8fb4a11354e81310264bd885d7a06438228773650')
GRAPH = r'(?:front|head-[01]|block-(?:0[0-9]|1[01])-(?:time|frequency))'
FLAGS = ('qualityApproved', 'target75Proven', 'benchmarkTimingAdmitted', 'releaseAuthorized')
MAX_MEMBER_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 ** 3
MAX_MEMBERS = 4096


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pin(path):
    require(path.is_file() and not path.is_symlink(), 'Missing or linked evidence file.')
    with path.open('rb') as stream:
        return dict(bytes=path.stat().st_size, sha256=hashlib.file_digest(stream, 'sha256').hexdigest())


def allowed(relative, sources):
    name = relative.as_posix()
    if name.startswith('execution-source/'):
        return name.removeprefix('execution-source/') in sources and relative.suffix in ('.py', '.js', '.cjs', '.java', '.json', '.md')
    if len(relative.parts) == 1:
        return name in ('driver-receipt.json', 'runtime-input-bindings.json', 'host-preparation-receipt.json',
            'deux-preparation-receipt.json', 'input-provenance.json', 'glass-castle.wav',
            'readiness.log', 'qualification.log', 'consumer.log')
    if name == 'consumer/receipt.json' or re.fullmatch(r'consumer/cpu_all/(?:voice-full|vocals|accompaniment)\.wav', name):
        return True
    stage = r'(?:readiness|qualification)'
    if re.fullmatch(stage + r'/(?:receipt|source-plan)\.(?:json|partial)', name):
        return True
    if re.fullmatch(stage + r'/cpu_all-runtime-probe/(?:RuntimeProbe\.(?:java|class)|compile\.log|probe\.log)', name):
        return True
    if re.fullmatch(stage + r'/snapshots/cpu_all_(?:plain|profiled)/(?:NativeDeux|AppDiagnostics|DeuxSourceRunner|NativeDeuxTransform|NativeInferenceProfile)\.java', name):
        return True
    if re.fullmatch(stage + r'/snapshots/cpu_all_(?:plain|profiled)/(?:compile|run)\.log', name):
        return True
    if re.fullmatch(stage + r'/snapshots/cpu_all_(?:plain|profiled)/classes/com/cyberbasslord/lightforge/[A-Za-z0-9_$]+\.class', name):
        return True
    passage = r'qualification/cpu_all_(?:plain|profiled)/passage-(?:00[0-9]|01[01])/'
    if re.fullmatch(r'qualification/cpu_all_(?:plain|profiled)/receipt\.json(?:\.partial)?', name):
        return True
    if re.fullmatch(passage + r'(?:receipt\.json(?:\.partial)?|profile\.txt|stems\.f32|\.native-deux-[A-Za-z0-9_-]+\.partial)', name):
        return True
    return bool(re.fullmatch(
        r'(?:qualification/cpu_all_profiled/passage-(?:00[0-9]|01[01])/traces/|'
        + stage + r'/cpu_all_profiled_active_traces/)' + GRAPH + r'_[A-Za-z0-9_.-]+\.json', name))


def export(run_arg, output_arg):
    require(not run_arg.is_symlink() and run_arg.is_dir(), 'Expected a regular run directory.')
    require(not output_arg.exists() and not output_arg.is_symlink(), 'Use a new archive.')
    run, output = run_arg.resolve(), output_arg.resolve()
    require(not output.is_relative_to(run), 'Archive must be outside the run directory.')
    driver = json.loads((run / 'driver-receipt.json').read_text())
    require(driver['schema'] == 'lightforge.deux-source-local-driver.v1' and
            driver['status'] in ('COMPLETE_DIAGNOSTIC', 'BLOCKED_OR_REJECTED'), 'No final driver receipt.')
    require(driver['variants'] == ['cpu_all'] and driver['cudaExecuted'] is False and
            driver['fullVocalStageExecuted'] is False and all(driver[key] is False for key in FLAGS),
            'Unexpected provider, full-vocal-stage or approval claim.')
    bindings = json.loads((run / 'runtime-input-bindings.json').read_text())
    require(bindings['schema'] == 'lightforge.deux-source-local-bindings.v1' and
            bindings['sourceCommit'] == driver['executionSourceCommit'] and
            bindings['sourceTree'] == driver['executionSourceTree'] and
            bindings['publicWav'] == WAV, 'Source/input binding mismatch.')
    require(pin(run / 'glass-castle.wav') == WAV, 'Only the exact original public WAV may be exported.')
    sources = bindings['sources']
    require(isinstance(sources, dict) and sources, 'Missing explicit execution source inventory.')
    for name, expected in sources.items():
        require(not Path(name).is_absolute() and all(part not in ('', '.', '..') for part in name.split('/')),
                'Unsafe source identity.')
        require(pin(run / 'execution-source' / name) == expected, 'Execution source copy differs: ' + name)
    entries, total = [], 0
    for path in sorted(run.rglob('*')):
        require(not path.is_symlink(), 'Refusing a linked evidence member.')
        if path.is_file():
            relative = path.relative_to(run)
            require(allowed(relative, sources), 'Unreviewed archive member: ' + relative.as_posix())
            size = path.stat().st_size
            require(size <= MAX_MEMBER_BYTES, 'Evidence member exceeds the archive bound.')
            total += size
            require(total <= MAX_TOTAL_BYTES and len(entries) < MAX_MEMBERS, 'Evidence inventory exceeds archive bounds.')
            entries.append(dict(path=relative.as_posix(), **pin(path)))
    manifest = dict(schema='lightforge.deux-source-local-archive.v1', runDirectory=run.name,
        executionSourceCommit=driver['executionSourceCommit'], executionSourceTree=driver['executionSourceTree'],
        status=driver['status'], files=entries, publicFixtureOnly=True, cudaExecuted=False,
        fullVocalStageExecuted=False, qualityApproved=False, target75Proven=False,
        benchmarkTimingAdmitted=False, releaseAuthorized=False)
    manifest_file = run / 'archive-manifest.json'
    with manifest_file.open('x') as stream:
        json.dump(manifest, stream, indent=2, allow_nan=False)
        stream.write('\n')
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for row in entries:
            path = run / row['path']
            require(pin(path) == {key: row[key] for key in ('bytes', 'sha256')}, 'Evidence changed during export.')
            archive.write(path, arcname=run.name + '/' + row['path'])
        archive.write(manifest_file, arcname=run.name + '/archive-manifest.json')
    with zipfile.ZipFile(output) as archive:
        require(archive.testzip() is None, 'Archive CRC verification failed.')
    return dict(archive=output.name, **pin(output), members=len(entries) + 1,
                status=driver['status'], qualityApproved=False, target75Proven=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.run, args.output), indent=2))


if __name__ == '__main__':
    main()
