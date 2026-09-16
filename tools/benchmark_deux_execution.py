#!/usr/bin/env python3
"""Paired, alternating full-passage native Deux execution benchmark.

Compiles two exact Java source snapshots against the same pinned runtime and
original graph inventory. Every measurement is a fresh JVM. Warmups, total wall
time and time inside ORT Run are separate. A nonidentical/nonfinite/incomplete
PCM output fails the comparison; timings never substitute for quality evidence.
This is a host experiment, not a whole-song or Android speed claim.
"""
import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'android/src/com/cyberbasslord/lightforge'
SAMPLES = 2 * 573300
GRAPH_NAMES = {'front', 'head-0', 'head-1'} | {
    'block-%02d-%s' % (block, axis) for block in range(12)
    for axis in ('time', 'frequency')
}
STAGE_NAMES = {
    'inference-gate-wait', 'cache-preflight', 'buffer-init', 'runtime-setup',
    'pcm-read', 'feature-encode', 'model-init', 'tensor-bind', 'inference',
    'pack', 'scatter', 'decode', 'output-write', 'output-flush', 'output-commit',
}


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_output(path):
    data = path.read_bytes()
    require(len(data) == SAMPLES * 4, 'A complete two-stem output is required.')
    require(all(math.isfinite(value) for (value,) in struct.iter_unpack('<f', data)),
            'Output contains nonfinite samples.')
    return hashlib.sha256(data).hexdigest()


def profile_fields(path):
    lines = path.read_text().splitlines()
    require(len(lines) == 43, 'Full 27-graph/15-stage profile required.')
    records = [dict(piece.split('=', 1) for piece in line.split()) for line in lines]
    summary = records[0]
    require(summary.get('schema') == 'native-inference-profile-v2' and
            summary.get('outcome') == 'completed' and summary.get('graphRecords') == '27' and
            summary.get('stageRecords') == '15' and summary.get('droppedGraphRecords') == '0' and
            summary.get('droppedStageRecords') == '0', 'Incomplete inference profile.')
    graphs = [r for r in records[1:] if r.get('schema') == 'native-inference-graph-v2']
    stages = [r for r in records[1:] if r.get('schema') == 'native-inference-stage-v1']
    require(len(graphs) == 27 and {r.get('graph') for r in graphs} == GRAPH_NAMES and
            len(stages) == 15 and {r.get('stage') for r in stages} == STAGE_NAMES,
            'Inference topology differs from the unchanged full model.')
    require(all(int(r.get('runCount', '0')) == (1 if r['graph'] == 'front' else
                15 if r['graph'].endswith('-time') else 11) for r in graphs),
            'Original batch counts changed; a complete passage is required.')
    for key in ('inferenceWallMs', 'modelInitWallMs'):
        require(math.isfinite(float(summary[key])) and float(summary[key]) > 0,
                'Invalid model/inference timing.')
    return summary


def compile_variant(name, source, work, java, dependencies):
    directory = work / name
    directory.mkdir()
    classes = directory / 'classes'
    classes.mkdir()
    snapshot = directory / 'NativeDeux.java'
    snapshot.write_bytes(source.read_bytes())
    stub = directory / 'AppDiagnostics.java'
    stub.write_text('package com.cyberbasslord.lightforge; public final class AppDiagnostics {'
                    'public static void log(android.content.Context c,String l,String s,String m){}'
                    'public static boolean flush(long timeout){return true;}}\n')
    sources = [snapshot, SOURCE / 'NativeDeuxTransform.java', SOURCE / 'NativeInferenceProfile.java',
               ROOT / 'tests/NativeDeuxExecutionBenchmark.java', stub]
    command = [str(java / 'javac'), '--release', '8', '-encoding', 'UTF-8', '-cp',
               os.pathsep.join(map(str, dependencies)), '-d', str(classes), *map(str, sources)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    (directory / 'compile.log').write_text(result.stdout + result.stderr)
    require(result.returncode == 0, name + ' compilation failed; see compile.log.')
    return classes, sha(snapshot)


def measure(name, round_number, phase, classes, work, java, dependencies, models, audio, start):
    directory = work / name
    prefix = phase + '-' + str(round_number)
    output, profile = directory / (prefix + '.f32'), directory / (prefix + '.profile.txt')
    command = [str(java / 'java'), '-Xmx1g', '-XX:MaxDirectMemorySize=512m', '-cp',
               os.pathsep.join(map(str, [classes, *dependencies])),
               'com.cyberbasslord.lightforge.NativeDeuxExecutionBenchmark', str(models), str(audio),
               str(output), str(start), str(profile)]
    print(phase + ' ' + str(round_number) + ' ' + name, flush=True)
    result = subprocess.run(command, capture_output=True, text=True, timeout=1200)
    (directory / (prefix + '.log')).write_text(result.stdout + result.stderr)
    require(result.returncode == 0, name + ' inference failed; see ' + prefix + '.log.')
    measurement = json.loads(result.stdout.strip().splitlines()[-1])
    require(set(measurement) == {'wallNanos', 'processCpuNanos', 'peakRssBytes'},
            'Unrecognized native measurement fields.')
    require(type(measurement['wallNanos']) is int and measurement['wallNanos'] > 0,
            'Invalid full-passage elapsed time.')
    for key in ('processCpuNanos', 'peakRssBytes'):
        require(type(measurement[key]) is int and (measurement[key] == -1 or measurement[key] > 0),
                'Invalid resource observation.')
        if measurement[key] == -1:
            measurement[key] = None
    fields = profile_fields(profile)
    measurement.update(variant=name, round=round_number, phase=phase,
                       outputSha256=read_output(output), outputBytes=output.stat().st_size,
                       inferenceMillis=float(fields['inferenceWallMs']),
                       modelInitMillis=float(fields['modelInitWallMs']),
                       profileSha256=sha(profile))
    return measurement


def summarize(runs):
    measured = [r for r in runs if r['phase'] == 'measurement']
    variants = {}
    for name in ('baseline', 'candidate'):
        chosen = [r for r in measured if r['variant'] == name]
        require(len(chosen) >= 3, 'At least three measured runs per variant are required.')
        variants[name] = {key: statistics.median(r[key] for r in chosen)
                          for key in ('wallNanos', 'inferenceMillis', 'modelInitMillis')}
        for key in ('processCpuNanos', 'peakRssBytes'):
            variants[name][key] = (statistics.median(r[key] for r in chosen)
                                   if all(r[key] is not None for r in chosen) else None)
    pairs = []
    for round_number in sorted({r['round'] for r in measured}):
        pair = {r['variant']: r for r in measured if r['round'] == round_number}
        require(len(pair) == 2, 'Incomplete baseline/candidate pair.')
        pairs.append({'round': round_number,
                      'wallReductionPercent': 100 * (1 - pair['candidate']['wallNanos'] / pair['baseline']['wallNanos']),
                      'inferenceReductionPercent': 100 * (1 - pair['candidate']['inferenceMillis'] / pair['baseline']['inferenceMillis']),
                      'byteIdentical': pair['baseline']['outputSha256'] == pair['candidate']['outputSha256']})
    return {'medians': variants, 'pairs': pairs,
            'allOutputsByteIdentical': len({r['outputSha256'] for r in runs}) == 1,
            'speedupProvenOnAndroid': False, 'wholeSongSpeedupProven': False,
            'qualityCriterion': 'Complete finite outputs; exact float32 bytes across every warmup and measured run.'}


def host_metadata():
    result = {'platform': platform.platform(), 'machine': platform.machine(), 'cpuCount': os.cpu_count()}
    try:
        result['cpuAffinity'] = sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        result['cpuAffinity'] = None
    for label, filename in [('cpuQuota', '/sys/fs/cgroup/cpu.max'),
                            ('memoryLimit', '/sys/fs/cgroup/memory.max')]:
        try:
            result[label] = Path(filename).read_text().strip()
        except OSError:
            result[label] = None
    try:
        result['cpuModel'] = next(line.split(':', 1)[1].strip() for line in
                                  Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name'))
    except (OSError, StopIteration):
        result['cpuModel'] = None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-source', type=Path, required=True)
    parser.add_argument('--candidate-source', type=Path, default=SOURCE / 'NativeDeux.java')
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--start-sample', type=int, default=-66150)
    parser.add_argument('--models', type=Path, default=ROOT / 'web/analysis/models/deux')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--warmups', type=int, default=1)
    args = parser.parse_args()
    require(3 <= args.repeats <= 10 and 1 <= args.warmups <= 3, 'Use 3-10 paired runs and 1-3 warmup pairs.')
    require(not args.output.exists(), 'Use a new output directory to prevent stale evidence.')
    toolchain = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain'))
    java = Path(os.environ.get('LIGHTFORGE_JAVA_HOME', toolchain / 'jdk17')) / 'bin'
    runtime = json.loads((ROOT / 'android/native-runtime.json').read_text())
    host = toolchain / 'onnx' / runtime['host']['name']
    require(host.stat().st_size == runtime['host']['bytes'] and sha(host) == runtime['host']['sha256'],
            'Host runtime does not match the checked-in binary pin.')
    dependencies = [toolchain / 'test-json.jar',
                    Path(os.environ.get('ANDROID_SDK_ROOT', toolchain / 'android-sdk')) / 'platforms/android-35/android.jar', host]
    for path in [*dependencies, args.baseline_source, args.candidate_source, args.audio]:
        require(path.is_file(), 'Required input is missing: ' + path.name)
    manifest_path = args.models / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    require(manifest.get('execution') == 'bounded-independent-batches-v1' and
            manifest.get('frames') == 1301 and manifest.get('samples') == 573300 and
            manifest.get('headFrames') == 128, 'Original full-context geometry is required.')
    require(set(manifest['files']) == {name + '.onnx' for name in GRAPH_NAMES}, 'Exact original graph inventory required.')
    for name, entry in manifest['files'].items():
        graph = args.models / name
        require(graph.stat().st_size == entry['bytes'] and sha(graph) == entry['sha256'], 'Graph integrity failed: ' + name)
    args.output.mkdir(parents=True)
    receipt = {'schema': 'lightforge.deux-execution-comparison.v1',
               'createdUtc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'host': host_metadata(),
               'startSample': args.start_sample, 'samplesPerStem': 573300, 'runtimeVersion': runtime['version'],
               'runtimeSha256': sha(host), 'audioSha256': sha(args.audio), 'modelManifestSha256': sha(manifest_path),
               'modelHashes': {name: entry['sha256'] for name, entry in manifest['files'].items()},
               'sharedSourceHashes': {str(p.relative_to(ROOT)): sha(p) for p in [SOURCE / 'NativeDeuxTransform.java',
                    SOURCE / 'NativeInferenceProfile.java', ROOT / 'tests/NativeDeuxExecutionBenchmark.java', Path(__file__)]},
               'dependencyHashes': {p.name: sha(p) for p in dependencies}, 'sourceHashes': {}, 'runs': []}
    classes = {}
    for name, source in [('baseline', args.baseline_source), ('candidate', args.candidate_source)]:
        classes[name], receipt['sourceHashes'][name] = compile_variant(name, source, args.output, java, dependencies)
    receipt_path = args.output / 'receipt.json'
    for phase, count in [('warmup', args.warmups), ('measurement', args.repeats)]:
        for round_number in range(count):
            order = ('baseline', 'candidate') if round_number % 2 == 0 else ('candidate', 'baseline')
            for name in order:
                receipt['runs'].append(measure(name, round_number, phase, classes[name], args.output, java,
                                               dependencies, args.models, args.audio, args.start_sample))
                receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    require(sha(args.audio) == receipt['audioSha256'], 'Audio changed during the comparison.')
    require(sha(manifest_path) == receipt['modelManifestSha256'], 'Model manifest changed during comparison.')
    for name, expected in receipt['modelHashes'].items():
        require(sha(args.models / name) == expected, 'Model changed during comparison: ' + name)
    for name, expected in receipt['sharedSourceHashes'].items():
        require(sha(ROOT / name) == expected, 'Shared benchmark source changed during comparison: ' + name)
    receipt['summary'] = summarize(receipt['runs'])
    receipt['passed'] = receipt['summary']['allOutputsByteIdentical']
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt['summary'], indent=2))
    require(receipt['passed'], 'Quality comparison failed: native outputs differ. Do not adopt the execution change.')


if __name__ == '__main__':
    main()
