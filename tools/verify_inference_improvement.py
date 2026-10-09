#!/usr/bin/env python3
"""Hold production builds until final-source, exact-output inference timing qualifies.

This is a host performance prerequisite, independent of fresh production/Android
quality gates. It does not establish physical phone or whole-analysis speedup.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

ROOT = Path(__file__).resolve().parents[1]
# Current qualification must never overwrite the published historical receipt.
RECEIPT = 'research/inference-current/production-parallel-qualification.json'
SOURCE_PATHS = {
    'android/src/com/cyberbasslord/lightforge/' + name + '.java'
    for name in ('NativeDeux', 'NativeDeuxTransform', 'NativeInferenceProfile', 'NativeExecutionPolicy', 'NativePassagePolicy')
} | {'android/native-runtime.json', 'tests/NativeDeuxParallelBenchmark.java',
     'tools/benchmark_deux_parallel.py', 'tools/benchmark_deux_execution.py',
     'qa/release-2.4.1/verify-analysis.py'}
GRAPH_NAMES = {'front', 'head-0', 'head-1'} | {
    f'block-{i:02d}-{axis}' for i in range(12) for axis in ('time', 'frequency')}
GEOMETRY = dict(graphCount=27, stageCount=15, bands=60, frames=1301, samplesPerStem=573300,
                baseline=dict(workers=1, timeBatch=4, frequencyBatch=128, inferenceCalls=335),
                candidate=dict(workers=8, timeBatch=1, frequencyBatch=16, frequencyTail=5, inferenceCalls=1727))
CRITERIA = dict(measuredPairs=3, minMedianWallReductionPercent=15,
                minEachPairWallReductionPercent=5)


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def positive(value):
    return type(value) is int and value > 0


def equal_number(actual, expected):
    return type(actual) in (int, float) and math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-9)


def counter_delta(run, group, key):
    before = run['hostCountersBefore'][group][key]
    after = run['hostCountersAfter'][group][key]
    require(type(before) is int and type(after) is int and 0 <= before <= after,
            'Missing or invalid host resource counters')
    return after - before


def validate_measurements(record):
    """Replay numerical admission rather than trusting a stored PASS or median."""
    require(record.get('schema') == 'lightforge.production-parallel-qualification.v3', 'Unknown inference evidence schema')
    require(record.get('passed') is True and record.get('allOutputsByteIdentical') is True, 'Inference evidence did not pass')
    require(record.get('androidSpeedupProven') is False and record.get('wholeAnalysisSpeedupProven') is False,
            'Host evidence must not claim device or whole-analysis performance')
    require(record.get('geometry') == GEOMETRY and record.get('criteria') == CRITERIA,
            'Original model coverage or performance thresholds changed')
    controls = record.get('hostControls', {})
    require(set(controls) == {'schema', 'scope', 'parentCpuAffinity', 'childCpuAffinity',
                             'cgroupCpuQuota', 'quotaCpuCapacity', 'expectedAvailableProcessors',
                             'reservedQuotaCpuCapacity'} and
            controls.get('schema') == 'lightforge.child-cpu-affinity.v2' and
            controls.get('scope') == 'java-benchmark-children-only', 'Controlled CPU provenance missing')
    parent, child = controls['parentCpuAffinity'], controls['childCpuAffinity']
    require(isinstance(parent, list) and len(parent) >= 8 and
            all(type(cpu) is int and cpu >= 0 for cpu in parent) and parent == sorted(set(parent)) and
            isinstance(child, list) and all(type(cpu) is int for cpu in child) and
            child == parent[:7] and type(controls['expectedAvailableProcessors']) is int and
            controls['expectedAvailableProcessors'] == 7 and
            type(controls['reservedQuotaCpuCapacity']) is int and controls['reservedQuotaCpuCapacity'] == 1,
            'All variants must use seven allowed CPUs with one CPU of quota reserved')
    quota = controls['cgroupCpuQuota']
    require(isinstance(quota, str) and re.fullmatch(r'[1-9][0-9]* [1-9][0-9]*', quota),
            'Finite host CPU quota missing')
    amount, period = map(int, quota.split())
    require(amount >= (len(child) + controls['reservedQuotaCpuCapacity']) * period and
            equal_number(controls['quotaCpuCapacity'], amount / period), 'Host CPU quota lacks the reserved margin')
    runs = record.get('runs')
    require(isinstance(runs, list) and len(runs) == 8, 'One warmup and three complete measured pairs are required')
    expected = [('warmup', 0, 0, 'baseline'), ('warmup', 0, 1, 'candidate')]
    for pair in range(3):
        order = ('candidate', 'baseline') if pair % 2 else ('baseline', 'candidate')
        expected.extend(('measurement', pair, order_index, variant) for order_index, variant in enumerate(order))
    output_hash = None
    throttle_ratios = []
    for run, identity in zip(runs, expected):
        require(tuple(run.get(k) for k in ('phase', 'pairIndex', 'orderInPair', 'variant')) == identity,
                'Pairs must alternate, with warmup excluded from measurements')
        context = run.get('executionContext', {})
        require(context == {'cpuAffinity': child, 'availableProcessors': 7} and
                type(context['availableProcessors']) is int and
                all(type(cpu) is int for cpu in context['cpuAffinity']),
                'Observed JVM CPU affinity differs between variants')
        require(all(positive(run.get(k)) for k in ('wallNanos', 'processCpuNanos', 'peakRssBytes')),
                'Complete real time/CPU/RSS observations are required')
        output = run.get('output', {})
        require(set(output) == {'sha256', 'bytes', 'floats', 'finite'} and digest(output['sha256']) and
                output['finite'] is True and type(output['bytes']) is int and output['bytes'] == 4586400 and
                type(output['floats']) is int and output['floats'] == 1146600, 'Incomplete or nonfinite Float32 output')
        output_hash = output_hash or output['sha256']
        require(output['sha256'] == output_hash, 'Full output bytes differ')
        temporal_calls = 15 if run['variant'] == 'baseline' else 60
        frequency_calls = 11 if run['variant'] == 'baseline' else 82
        counts = {name: 1 if name == 'front' else temporal_calls if name.endswith('-time') else frequency_calls for name in GRAPH_NAMES}
        coverage = dict(graphCount=27, stageCount=15, inferenceCalls=sum(counts.values()), graphRunCounts=counts)
        require(run.get('coverage') == coverage, 'Incomplete original graph/band/frame work')
        for name in ('oom', 'oom_kill', 'max'):
            require(counter_delta(run, 'cgroupMemoryEvents', name) == 0, 'Memory pressure confounds timing')
        for name in ('pgscan_direct', 'pgsteal_direct'):
            require(counter_delta(run, 'cgroupMemoryStat', name) == 0, 'Direct reclaim confounds timing')
        throttle = counter_delta(run, 'cgroupCpuStat', 'throttled_usec') * 1000 / run['wallNanos']
        require(throttle <= .05, 'CPU quota throttling confounds timing')
        throttle_ratios.append(throttle)
    measured = runs[2:]
    paired = []
    for index in range(3):
        by_variant = {run['variant']: run for run in measured if run['pairIndex'] == index}
        base, candidate = by_variant['baseline']['wallNanos'], by_variant['candidate']['wallNanos']
        reduction = 100 * (1 - candidate / base)
        require(reduction >= 5, 'At least one measured pair lacks a noticeable repeatable gain')
        paired.append(dict(pairIndex=index, baselineWallNanos=base, candidateWallNanos=candidate, wallReductionPercent=reduction))
    saved_pairs = record.get('pairedReductions')
    require(isinstance(saved_pairs, list) and len(saved_pairs) == 3, 'Paired reductions absent')
    for saved, actual in zip(saved_pairs, paired):
        require(set(saved) == set(actual) and all(equal_number(saved[k], actual[k]) for k in actual), 'Stored paired reduction is incorrect')
    medians = {variant: {key: statistics.median(run[key] for run in measured if run['variant'] == variant)
                         for key in ('wallNanos', 'processCpuNanos', 'peakRssBytes')}
               for variant in ('baseline', 'candidate')}
    require(record.get('medians') == medians, 'Stored medians differ from observed runs')
    reduction = 100 * (1 - medians['candidate']['wallNanos'] / medians['baseline']['wallNanos'])
    require(reduction >= 15 and equal_number(record.get('medianWallReductionPercent'), reduction),
            'Final production source has not demonstrated at least 15% lower median passage time')
    resources = record.get('resources', {})
    require(set(resources) == {'noOom', 'noMemoryLimitEvents', 'noDirectReclaim', 'maxThrottleToWallRatio'} and
            all(resources[k] is True for k in ('noOom', 'noMemoryLimitEvents', 'noDirectReclaim')) and
            equal_number(resources['maxThrottleToWallRatio'], max(throttle_ratios)), 'Resource summary differs from observations')
    return reduction


def verify(root=ROOT):
    path = root / RECEIPT
    require(path.is_file() and path.stat().st_size <= 262144, 'final-source inference improvement evidence is missing')
    record = json.loads(path.read_text())
    reduction = validate_measurements(record)
    bindings = record.get('sourceBindings')
    require(isinstance(bindings, dict) and set(bindings) == SOURCE_PATHS and record.get('sourceBindingsAfter') == bindings,
            'Inference source inventory is incomplete or changed during qualification')
    for name, expected in bindings.items():
        require(digest(expected) and (root / name).is_file() and sha(root / name) == expected,
                'measured inference source changed: ' + name)
    runtime = json.loads((root / 'android/native-runtime.json').read_text())
    require(record.get('runtime') == {'version': '1.25.1', 'hostJarSha256': runtime['host']['sha256']},
            'Inference evidence is not bound to the pinned runtime')
    manifest_path = root / 'web/analysis/models/deux/manifest.json'
    manifest = json.loads(manifest_path.read_text())
    require(record.get('models') == {'manifestSha256': sha(manifest_path),
            'graphHashes': {name: entry['sha256'] for name, entry in manifest['files'].items()}},
            'Inference evidence changed original model assets')
    require(record.get('audio') == {'sha256': sha(root / 'web/demo/glass-castle.wav'), 'startSample': 661500},
            'Inference comparison input changed')
    require(isinstance(record.get('host'), dict) and isinstance(record.get('createdAt'), str), 'Host provenance missing')
    return reduction


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        reduction = verify(args.root)
        print(f'PASS: exact-output host inference prerequisite ({reduction:.1f}% lower median passage time).')
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise SystemExit('Release held: ' + str(error)) from error


if __name__ == '__main__':
    main()
