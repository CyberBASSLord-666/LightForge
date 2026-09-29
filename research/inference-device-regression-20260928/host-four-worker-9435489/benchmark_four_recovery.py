#!/usr/bin/env python3
"""Exploratory original-model four-worker versus baseline complete-passage host check."""
import argparse
import datetime
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.repo.resolve()
    work = args.output.resolve()
    script = Path(__file__).resolve()
    spec = importlib.util.spec_from_file_location('lightforge_parallel', root / 'tools/benchmark_deux_parallel.py')
    p = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(p)
    b = p.b
    b.require(root == p.ROOT, 'Repository path mismatch')
    b.require(not work.exists(), 'Fresh output directory required')
    work.mkdir(parents=True)
    harness_sha = b.sha(script)
    shutil.copyfile(script, work / 'benchmark_four_recovery.py')
    def commit():
        return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
    source_commit = commit()
    toolchain = root.parent / 'toolchain'
    java = toolchain / 'jdk17/bin'
    deps = [toolchain / 'test-json.jar', toolchain / 'android-sdk/platforms/android-35/android.jar',
            toolchain / 'onnx/onnxruntime-1.25.1.jar']
    runtime = json.loads((root / 'android/native-runtime.json').read_text())
    b.require(runtime['version'] == '1.25.1' and b.sha(deps[-1]) == runtime['host']['sha256'], 'Pinned ORT required')
    models, audio = root / 'web/analysis/models/deux', root / 'web/demo/glass-castle.wav'
    manifest = json.loads((models / 'manifest.json').read_text())
    b.require(manifest.get('frames') == 1301 and manifest.get('samples') == 573300 and len(manifest['files']) == 27,
              'Original model geometry required')
    for name, entry in manifest['files'].items():
        path = models / name
        b.require(path.stat().st_size == entry['bytes'] and b.sha(path) == entry['sha256'], 'Model integrity ' + name)
    bindings = p.source_bindings()
    cpu_control = p.child_cpu_control()
    record = dict(schema='lightforge.exploratory-four-worker-host.v1',
                  createdAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  host=b.host_metadata(), hostControls=cpu_control,
                  sourceCommit=source_commit, sourceBindings=bindings, harnessSha256=harness_sha,
                  runtime=dict(version='1.25.1', hostJarSha256=runtime['host']['sha256']),
                  models=dict(manifestSha256=b.sha(models / 'manifest.json'),
                              graphHashes={n: e['sha256'] for n, e in manifest['files'].items()}),
                  audio=dict(sha256=b.sha(audio), startSample=661500),
                  geometry=dict(graphCount=27, stageCount=15, bands=60, frames=1301, samplesPerStem=573300,
                                baseline=dict(workers=1, timeBatch=4, frequencyBatch=128, inferenceCalls=335),
                                candidate4=dict(workers=4, timeBatch=1, frequencyBatch=16,
                                                frequencyTail=5, inferenceCalls=1727)),
                  criteria=dict(measuredPairs=3, minMedianWallReductionPercent=15,
                                minEachPairWallReductionPercent=5, maxThrottleToWallRatio=.05),
                  runs=[], androidSpeedupProven=False, wholeAnalysisSpeedupProven=False)
    classes = p.compile_production(work, java, deps, bindings)
    record['compiledClassHashes'] = p.class_hashes(classes)
    receipt = work / 'receipt.json'
    def save():
        receipt.write_text(json.dumps(record, indent=2) + '\n')
    save()
    for phase, count in [('warmup', 1), ('measurement', 3)]:
        for pair in range(count):
            order = ('candidate4', 'baseline') if pair % 2 else ('baseline', 'candidate4')
            for order_index, variant in enumerate(order):
                b.require(p.source_bindings() == bindings and b.sha(script) == harness_sha and commit() == source_commit,
                          'Source changed before run')
                b.require(p.class_hashes(classes) == record['compiledClassHashes'], 'Class changed before run')
                run = p.measure(variant, pair, order_index, phase, classes, work, java, deps,
                                models, audio, 661500, cpu_control)
                record['runs'].append(run)
                record['sourceBindingsAfter'] = p.source_bindings()
                b.require(record['sourceBindingsAfter'] == bindings and b.sha(script) == harness_sha
                          and commit() == source_commit, 'Source changed during run')
                b.require(p.class_hashes(classes) == record['compiledClassHashes'], 'Class changed during run')
                save()
                b.require(len({r['output']['sha256'] for r in record['runs']}) == 1, 'Output differs')
            current = {r['variant']: r for r in record['runs'] if r['phase'] == phase and r['pairIndex'] == pair}
            print(json.dumps(dict(phase=phase, pairIndex=pair,
                                  baselineSeconds=current['baseline']['wallNanos'] / 1e9,
                                  candidate4Seconds=current['candidate4']['wallNanos'] / 1e9, exact=True)), flush=True)
    for name, expected in record['models']['graphHashes'].items():
        b.require(b.sha(models / name) == expected, 'Model changed')
    b.require(b.sha(audio) == record['audio']['sha256'] and p.source_bindings() == bindings
              and b.sha(script) == harness_sha and commit() == source_commit, 'Input/source changed')
    measured = [r for r in record['runs'] if r['phase'] == 'measurement']
    pairs = []
    for index in range(3):
        pair = {r['variant']: r for r in measured if r['pairIndex'] == index}
        b.require(set(pair) == {'baseline', 'candidate4'}, 'Incomplete pair')
        base, four = pair['baseline']['wallNanos'], pair['candidate4']['wallNanos']
        pairs.append(dict(pairIndex=index, baselineWallNanos=base, candidateWallNanos=four,
                          wallReductionPercent=100 * (1 - four / base)))
    medians = {variant: {key: statistics.median(r[key] for r in measured if r['variant'] == variant)
                         for key in ('wallNanos', 'processCpuNanos', 'peakRssBytes')}
               for variant in ('baseline', 'candidate4')}
    resources = dict(noOom=all(p.delta(r, 'cgroupMemoryEvents', key) == 0 for r in record['runs']
                               for key in ('oom', 'oom_kill')),
                     noMemoryLimitEvents=all(p.delta(r, 'cgroupMemoryEvents', 'max') == 0 for r in record['runs']),
                     noDirectReclaim=all(p.delta(r, 'cgroupMemoryStat', key) == 0 for r in record['runs']
                                         for key in ('pgscan_direct', 'pgsteal_direct')),
                     maxThrottleToWallRatio=max(p.delta(r, 'cgroupCpuStat', 'throttled_usec') * 1000 / r['wallNanos']
                                                for r in record['runs']))
    reduction = 100 * (1 - medians['candidate4']['wallNanos'] / medians['baseline']['wallNanos'])
    exact = len({r['output']['sha256'] for r in record['runs']}) == 1
    record.update(pairedReductions=pairs, medians=medians, medianWallReductionPercent=reduction,
                  allOutputsByteIdentical=exact, resources=resources,
                  meetsHostThresholds=(exact and reduction >= 15
                                       and all(pair['wallReductionPercent'] >= 5 for pair in pairs)
                                       and resources['noOom'] and resources['noMemoryLimitEvents']
                                       and resources['noDirectReclaim']
                                       and resources['maxThrottleToWallRatio'] <= .05))
    record['finishedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save()
    print(json.dumps(dict(meetsHostThresholds=record['meetsHostThresholds'],
                          medianWallReductionPercent=reduction, pairedReductions=pairs,
                          receipt=str(receipt))), flush=True)

if __name__ == '__main__':
    main()
