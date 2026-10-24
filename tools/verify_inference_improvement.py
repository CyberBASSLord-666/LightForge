#!/usr/bin/env python3
"""Hold production builds until final-source, exact-output inference timing qualifies.

This is a host performance prerequisite, independent of fresh production/Android
quality gates. It does not establish physical phone or whole-analysis speedup.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import math
import os
import posixpath
import subprocess
import tempfile
from pathlib import Path
import re
import statistics
import struct

ROOT = Path(__file__).resolve().parents[1]
def current_analysis_verifier(root):
    version = json.loads((root / 'version.json').read_text())['name']
    if not isinstance(version, str) or re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version) is None:
        raise ValueError('Invalid current release identity')
    return 'qa/release-' + version + '/verify-analysis.py'


CURRENT_ANALYSIS_VERIFIER = current_analysis_verifier(ROOT)
# Current qualification must never overwrite the published historical receipt.
RECEIPT = 'research/inference-current/production-parallel-qualification.json'
SOURCE_PATHS = {
    'android/src/com/cyberbasslord/lightforge/' + name + '.java'
    for name in ('NativeDeux', 'NativeDeuxTransform', 'NativeInferenceProfile', 'NativeExecutionPolicy', 'NativePassagePolicy')
} | {'android/native-runtime.json', 'tests/NativeDeuxParallelBenchmark.java',
     'tools/benchmark_deux_parallel.py', 'tools/benchmark_deux_execution.py',
     CURRENT_ANALYSIS_VERIFIER, 'version.json'}
GRAPH_NAMES = {'front', 'head-0', 'head-1'} | {
    f'block-{i:02d}-{axis}' for i in range(12) for axis in ('time', 'frequency')}
GEOMETRY = dict(graphCount=27, stageCount=15, bands=60, frames=1301, samplesPerStem=573300,
                baseline=dict(workers=1, timeBatch=4, frequencyBatch=128, inferenceCalls=335),
                candidate=dict(workers=8, timeBatch=1, frequencyBatch=16, frequencyTail=5, inferenceCalls=1727))
CRITERIA = dict(measuredPairs=3, minMedianWallReductionPercent=15,
                minEachPairWallReductionPercent=5)
PORTABLE_PROTOCOL = 'portable-four-worker-three-cpu-v1'
PORTABLE_SCHEMA = 'lightforge.experimental-portable-parallel-qualification.v1'
BOUNDED_PROTOCOL = 'bounded-four-worker-three-cpu-v1'
BOUNDED_SCHEMA = 'lightforge.bounded-host-parallel-qualification.v1'
BOUNDED_SCOPE = ('Bounded host prerequisite: unchanged forced four-worker production neural execution '
                 'versus unchanged three-thread reference on the same three actual logical CPUs, '
                 'with at least one effective CPU of capacity headroom. Original passage only; '
                 'not ordinary production admission, eight-worker, Android, full-song or release readiness.')
PORTABLE_SOURCE_PATHS = SOURCE_PATHS | {
    'tools/portable_inference_host.py', 'tools/verify_inference_improvement.py'}
PORTABLE_GEOMETRY = dict(graphCount=27, stageCount=15, bands=60, frames=1301, samplesPerStem=573300,
    baseline=dict(workers=1, intraThreads=3, timeBatch=4, frequencyBatch=128, inferenceCalls=335),
    candidate4=dict(workers=4, intraThreads=1, timeBatch=1, frequencyBatch=16,
                    frequencyTail=5, inferenceCalls=1727),
    commonGraphIntraThreads=3)
PORTABLE_SCOPE = ('Experimental forced four-worker production execution versus the unmodified '
                  'production reference on the same three observed child CPUs; one CPU of '
                  'effective capacity reserved. Not device admission, eight-worker, Android, '
                  'whole-song or release qualification.')


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
        # Output heads retain 128-frame chunks (ceil(1301 / 128) == 11);
        # only the twelve frequency blocks use the candidate's 16-frame batch.
        counts = {name: 1 if name == 'front' else temporal_calls if name.endswith('-time')
                  else frequency_calls if name.endswith('-frequency') else 11 for name in GRAPH_NAMES}
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


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def portable_coverage(variant):
    require(variant in {'baseline', 'candidate4'}, 'Unknown portable execution variant')
    baseline = variant == 'baseline'
    counts = {name: 1 if name == 'front' else (15 if baseline else 60) if name.endswith('-time')
              else (11 if baseline or name.startswith('head-') else 82) for name in GRAPH_NAMES}
    return dict(graphCount=27, stageCount=15, inferenceCalls=sum(counts.values()), graphRunCounts=counts,
        schedulerConfigurations=dict(temporalConfig='cpu-i3-j1-d0-sequential' if baseline else 'cpu-i1-j1-d0-sequential-w4-b1',
                                     frequencyConfig='cpu-i3-j1-d0-sequential' if baseline else 'cpu-i1-j1-d0-sequential-w4-b16'))


def validate_portable_measurements(record, host=None, *, _bounded=False, root=ROOT):
    """Replay experimental evidence without admitting it to the production gate."""
    protocol = BOUNDED_PROTOCOL if _bounded else PORTABLE_PROTOCOL
    schema = BOUNDED_SCHEMA if _bounded else PORTABLE_SCHEMA
    scope = BOUNDED_SCOPE if _bounded else PORTABLE_SCOPE
    paths = bounded_source_paths(root) if _bounded else PORTABLE_SOURCE_PATHS
    host = host or load_module('portable_inference_host', ROOT / 'tools/portable_inference_host.py')
    require(isinstance(record, dict), 'Portable receipt must be an object')
    require(record.get('schema') == schema and record.get('protocol') == protocol,
            'Unknown experimental portable protocol')
    require(record.get('scope') == scope and record.get('passed') is True
            and record.get('allOutputsByteIdentical') is True, 'Portable evidence or scope did not pass')
    require(all(record.get(key) is False for key in ('releaseAdmissible', 'eightWorkerSpeedupProven',
                                                    'androidSpeedupProven', 'wholeAnalysisSpeedupProven')),
            'Portable evidence cannot establish release, eight-worker, device or whole-analysis qualification')
    canonical = lambda value: json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':'))
    require(canonical(record.get('geometry')) == canonical(PORTABLE_GEOMETRY)
            and canonical(record.get('criteria')) == canonical(CRITERIA)
            and equal_number(record.get('maxAllowedThrottleToWallRatio'), .05),
            'Portable geometry or thresholds changed')
    controls = record.get('hostControls')
    host.validate_controls(controls)
    child = controls['childCpuAffinity']
    compiled = record.get('compiledClassHashes')
    require(isinstance(compiled, dict) and 0 < len(compiled) <= 512 and all(
        isinstance(name, str) and re.fullmatch(r'(?:[A-Za-z0-9_$]+/)*[A-Za-z0-9_$]+\.class', name)
        and digest(value) for name, value in compiled.items()) and record.get('compiledClassHashesAfter') == compiled,
        'Portable compiled classes are missing, malformed or changed')
    bindings = record.get('sourceBindings')
    require(isinstance(bindings, dict) and set(bindings) == paths
            and all(digest(value) for value in bindings.values()) and record.get('sourceBindingsAfter') == bindings,
            'Portable source fingerprints are incomplete or changed')
    expected_declaration = dict(schema=('lightforge.bounded-host-protocol-declaration.v1' if _bounded
        else 'lightforge.portable-qualification-declaration.v1'),
        protocol=protocol, declaredAt=record.get('createdAt'), scope=scope,
        releaseAdmissible=False, geometry=PORTABLE_GEOMETRY, criteria=CRITERIA,
        maxAllowedThrottleToWallRatio=.05, hostControls=controls,
        sourceBindings=record.get('sourceBindings'), compiledClassHashes=compiled)
    require(canonical(record.get('protocolDeclaration')) == canonical(expected_declaration)
            and digest(record.get('protocolDeclarationSha256')), 'Prospective portable declaration differs')
    start, finish = record.get('createdAt'), record.get('finishedAt')
    require(isinstance(start, str) and isinstance(finish, str), 'Portable observation interval is missing')
    start, finish = datetime.datetime.fromisoformat(start), datetime.datetime.fromisoformat(finish)
    require(start.tzinfo is not None and finish.tzinfo is not None and finish >= start,
            'Invalid portable observation interval')
    runs = record.get('runs')
    require(isinstance(runs, list) and len(runs) == 8, 'One warmup and three complete measured pairs are required')
    expected = [('warmup', 0, 0, 'baseline'), ('warmup', 0, 1, 'candidate4')]
    for pair in range(3):
        order = ('candidate4', 'baseline') if pair % 2 else ('baseline', 'candidate4')
        expected.extend(('measurement', pair, index, variant) for index, variant in enumerate(order))
    output_hash, resources = None, []
    for run, identity in zip(runs, expected):
        require(tuple(run.get(key) for key in ('phase', 'pairIndex', 'orderInPair', 'variant')) == identity
                and type(run.get('pairIndex')) is int and type(run.get('orderInPair')) is int,
                'Portable pairs must alternate with warmup excluded')
        context = run.get('executionContext', {})
        expected_identity = dict(procCgroup=controls['procCgroup'], cgroupNamespace=controls['namespace']['link'])
        require(context == dict(cpuAffinity=child, availableProcessors=3, referenceIntraThreads=3,
                                protocol=protocol, hostVariant=run['variant'],
                                resourceIdentityBefore=expected_identity, resourceIdentityAfter=expected_identity)
                and type(context['availableProcessors']) is int and type(context['referenceIntraThreads']) is int
                and all(type(cpu) is int for cpu in context['cpuAffinity']),
                'Observed portable JVM execution differs from declaration')
        require(all(positive(run.get(key)) for key in ('wallNanos', 'processCpuNanos', 'peakRssBytes')),
                'Complete real time/CPU/RSS observations are required')
        output = run.get('output', {})
        require(set(output) == {'sha256', 'bytes', 'floats', 'finite'} and digest(output['sha256'])
                and output['finite'] is True and type(output['bytes']) is int and output['bytes'] == 4586400
                and type(output['floats']) is int and output['floats'] == 1146600, 'Incomplete or nonfinite Float32 output')
        output_hash = output_hash or output['sha256']
        require(output['sha256'] == output_hash, 'Full portable output bytes differ')
        require(run.get('coverage') == portable_coverage(run['variant']) and digest(run.get('profileSha256')),
                'Portable full-context work or exact scheduler configuration differs')
        artifacts = run.get('artifacts')
        require(isinstance(artifacts, dict) and set(artifacts) == {
            'logSha256', 'processSha256', 'countersBeforeSha256', 'countersAfterSha256'}
            and all(digest(value) for value in artifacts.values()), 'Portable raw-artifact fingerprints are missing')
        resources.append(host.validate_resource_pair(run.get('hostCountersBefore'), run.get('hostCountersAfter'),
                                                     run['wallNanos'], controls))
    require(record.get('resourcePairs') == resources, 'Portable resources do not replay from raw observations')
    paired = []
    measured = runs[2:]
    for index in range(3):
        pair = {run['variant']: run for run in measured if run['pairIndex'] == index}
        baseline, candidate = pair['baseline']['wallNanos'], pair['candidate4']['wallNanos']
        reduction = 100 * (1 - candidate / baseline)
        require(reduction >= 5, 'At least one portable pair lacks a repeatable five-percent gain')
        paired.append(dict(pairIndex=index, baselineWallNanos=baseline, candidateWallNanos=candidate,
                           wallReductionPercent=reduction))
    saved_pairs = record.get('pairedReductions')
    require(isinstance(saved_pairs, list) and len(saved_pairs) == 3, 'Portable paired reductions are missing')
    for saved, actual in zip(saved_pairs, paired):
        require(set(saved) == set(actual) and all(equal_number(saved[key], actual[key]) for key in actual),
                'Stored portable paired reduction is incorrect')
    medians = {variant: {key: statistics.median(run[key] for run in measured if run['variant'] == variant)
                         for key in ('wallNanos', 'processCpuNanos', 'peakRssBytes')}
               for variant in ('baseline', 'candidate4')}
    require(record.get('medians') == medians, 'Stored portable medians differ from observations')
    reduction = 100 * (1 - medians['candidate4']['wallNanos'] / medians['baseline']['wallNanos'])
    require(reduction >= 15 and equal_number(record.get('medianWallReductionPercent'), reduction),
            'Portable source has not demonstrated fifteen-percent lower median passage time')
    return reduction


def verify_portable(receipt, root=ROOT, *, _bounded=False):
    """Require complete local artifacts; a portable PASS is not release admission."""
    receipt = Path(receipt)
    require(receipt.name == 'receipt.json' and receipt.is_file() and not receipt.is_symlink()
            and receipt.stat().st_size <= 16 * 1024 * 1024, 'Complete portable receipt is unavailable')
    work = receipt.parent.resolve()
    parse_json = decode_bounded_json if _bounded else json.loads
    record = read_bounded_json(receipt, 16 * 1024 * 1024) if _bounded else json.loads(receipt.read_text())
    reduction = validate_portable_measurements(record, _bounded=_bounded, root=root)
    paths = bounded_source_paths(root) if _bounded else PORTABLE_SOURCE_PATHS
    bindings = record.get('sourceBindings')
    require(isinstance(bindings, dict) and set(bindings) == paths
            and record.get('sourceBindingsAfter') == bindings, 'Portable source inventory changed')
    for name, expected in bindings.items():
        snapshot = work / 'source-snapshots' / name
        require(digest(expected) and (root / name).is_file() and sha(root / name) == expected
                and snapshot.is_file() and snapshot.resolve().is_relative_to(work)
                and sha(snapshot) == expected, 'Portable measured source changed: ' + name)
    declaration = work / 'protocol.json'
    require(declaration.is_file() and not declaration.is_symlink() and declaration.stat().st_size <= 1024 * 1024
            and sha(declaration) == record['protocolDeclarationSha256']
            and parse_json(declaration.read_text()) == record['protocolDeclaration'],
            'Retained prospective portable declaration changed')
    classes = work / 'classes'
    class_paths = sorted(classes.rglob('*.class'))
    require(classes.is_dir() and not classes.is_symlink()
            and all(not path.is_symlink() for path in classes.rglob('*')) and all(
        path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(classes.resolve())
        for path in class_paths), 'Portable class inventory contains nonregular or escaped entries')
    actual_classes = {str(path.relative_to(classes)): sha(path) for path in class_paths}
    require(actual_classes == record['compiledClassHashes'], 'Retained portable compiled classes changed')
    runtime = parse_json((root / 'android/native-runtime.json').read_text())
    require(runtime.get('version') == '1.25.1'
            and record.get('runtime') == dict(version='1.25.1', hostJarSha256=runtime['host']['sha256']),
            'Portable runtime differs from the original pinned runtime')
    manifest_path = root / 'web/analysis/models/deux/manifest.json'
    manifest = parse_json(manifest_path.read_text())
    require(manifest.get('frames') == 1301 and manifest.get('samples') == 573300
            and set(manifest['files']) == {name + '.onnx' for name in GRAPH_NAMES}
            and record.get('models') == dict(manifestSha256=sha(manifest_path),
                graphHashes={name: entry['sha256'] for name, entry in manifest['files'].items()}),
            'Portable evidence changed original model assets')
    for name, entry in manifest['files'].items():
        model = manifest_path.parent / name
        require(model.is_file() and model.stat().st_size == entry['bytes'] and sha(model) == entry['sha256'],
                'Retained original model bytes changed: ' + name)
    require(record.get('audio') == dict(sha256=sha(root / 'web/demo/glass-castle.wav'), startSample=661500),
            'Portable comparison input changed')
    profile_verifier = load_module('portable_profile_replay', root / current_analysis_verifier(root))
    for run in record['runs']:
        prefix = run['phase'] + '-' + str(run['pairIndex'])
        directory = work / run['variant']
        retained = {}
        for key, suffix in (('logSha256', '.log'), ('processSha256', '.process.json'),
                            ('countersBeforeSha256', '.resources-before.json'),
                            ('countersAfterSha256', '.resources-after.json')):
            artifact = directory / (prefix + suffix)
            require(artifact.is_file() and not artifact.is_symlink() and artifact.resolve().is_relative_to(work)
                    and artifact.stat().st_size <= 8 * 1024 * 1024
                    and sha(artifact) == run['artifacts'][key], 'Retained portable raw observation changed: ' + suffix)
            retained[key] = artifact.read_text()
        process = parse_json(retained['processSha256'])
        require(isinstance(process, dict) and set(process) == {'returncode', 'stdout', 'stderr'}
                and type(process['returncode']) is int and process['returncode'] == 0
                and isinstance(process['stdout'], str) and isinstance(process['stderr'], str)
                and process['stdout'] + process['stderr'] == retained['logSha256'],
                'Retained portable process capture differs from the log')
        lines = process['stdout'].strip().splitlines()
        require(lines, 'Retained portable child observation is missing')
        child = parse_json(lines[-1])
        context = run['executionContext']
        expected_child = dict(wallNanos=run['wallNanos'], processCpuNanos=run['processCpuNanos'],
            peakRssBytes=run['peakRssBytes'], availableProcessors=context['availableProcessors'],
            referenceIntraThreads=context['referenceIntraThreads'], protocol=context['protocol'], hostVariant=run['variant'],
            resourceIdentityBefore=context['resourceIdentityBefore'], resourceIdentityAfter=context['resourceIdentityAfter'])
        require(isinstance(child, dict) and set(child) == set(expected_child) | {'cpuAffinityList'}
                and all(type(child[key]) is type(value) and child[key] == value for key, value in expected_child.items()),
                'Receipt timing/CPU/RSS/context conflicts with the retained child observation')
        # Parse Linux list syntax independently; do not trust a normalized receipt
        # when the raw process observation records a different binding.
        affinity = child['cpuAffinityList']
        require(isinstance(affinity, str) and len(affinity) <= 4096
                and re.fullmatch(r'[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*', affinity),
                'Invalid retained child CPU affinity')
        cpus = []
        for part in affinity.split(','):
            bounds = [int(value) for value in part.split('-')]
            require(0 <= bounds[0] <= bounds[-1] <= 65535 and bounds[-1] - bounds[0] < 256,
                    'Unbounded retained child CPU affinity')
            cpus.extend(range(bounds[0], bounds[-1] + 1))
        require(cpus == sorted(set(cpus)) and cpus == context['cpuAffinity'],
                'Retained child CPU affinity differs from the receipt')
        require(parse_json(retained['countersBeforeSha256']) == run['hostCountersBefore']
                and parse_json(retained['countersAfterSha256']) == run['hostCountersAfter'],
                'Receipt resource counters conflict with retained raw observations')
        output, profile = directory / (prefix + '.f32'), directory / (prefix + '.profile.txt')
        require(output.is_file() and not output.is_symlink() and output.resolve().is_relative_to(work)
                and output.stat().st_size == 4586400 and sha(output) == run['output']['sha256'],
                'Retained portable output bytes changed')
        require(all(math.isfinite(value[0]) for value in struct.iter_unpack('<f', output.read_bytes())),
                'Retained portable Float32 output is nonfinite')
        require(profile.is_file() and not profile.is_symlink() and profile.resolve().is_relative_to(work)
                and profile.stat().st_size <= 131072 and sha(profile) == run['profileSha256'],
                'Retained portable production profile changed')
        summary, counts = profile_verifier.verify_scheduler_profile(profile.read_text().splitlines(),
            run['coverage']['inferenceCalls'], None if run['variant'] == 'baseline' else 4)
        require(counts == run['coverage']['graphRunCounts'] and all(
            summary.get(key) == expected for key, expected in run['coverage']['schedulerConfigurations'].items()),
            'Retained portable scheduler geometry differs')
    require(isinstance(record.get('host'), dict), 'Portable host provenance is missing')
    return reduction


def decode_bounded_json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate bounded JSON field')
            result[key] = value
        return result
    def nonfinite(_):
        raise ValueError('Nonfinite bounded JSON number')
    result = json.loads(text, object_pairs_hook=unique, parse_constant=nonfinite)
    def finite(value, depth=0):
        require(depth <= 64, 'Over-nested bounded JSON')
        if isinstance(value, float):
            require(math.isfinite(value), 'Nonfinite bounded JSON number')
        elif isinstance(value, dict):
            for child in value.values():
                finite(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                finite(child, depth + 1)
    finite(result)
    return result


def read_bounded_json(path, limit=1024 * 1024):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= limit,
            'Bounded JSON is unavailable or oversized')
    return decode_bounded_json(path.read_text())


def campaign_helper(root=ROOT):
    return load_module('host_campaign_for_gate', root / 'tools/host_inference_campaign.py')


def bounded_source_paths(root=ROOT):
    return set(campaign_helper(root).load_policy(root)['sourcePaths'])


def verify_bounded(receipt, root=ROOT, *, rebuild_classes=False):
    """Full retained experiment replay, not by itself trusted campaign admission."""
    receipt, root = Path(receipt), Path(root)
    record = read_bounded_json(receipt, 16 * 1024 * 1024)
    require(record.get('schema') == BOUNDED_SCHEMA and record.get('protocol') == BOUNDED_PROTOCOL
            and record.get('campaignState') == 'terminal-pass', 'Only a complete bounded terminal pass can replay')
    reduction = verify_portable(receipt, root, _bounded=True)
    helper = campaign_helper(root)
    policy = helper.load_policy(root)
    declaration_path = receipt.parent / 'declaration.json'
    declaration = read_bounded_json(declaration_path)
    require(sha(declaration_path) == record.get('campaignDeclarationSha256')
            and record.get('campaignDeclaration') == declaration
            and record.get('campaignId') == policy['campaignId'], 'Bounded campaign declaration differs')
    helper.verify_source_bindings(root, declaration, policy)
    for field in ('sourceBindings', 'compiledClassHashes', 'models', 'runtime', 'runtimeBindings',
                  'audio', 'geometry', 'criteria', 'hostControls', 'host', 'pairOrder', 'childProtocol'):
        require(record.get(field) == declaration.get(field), 'Bounded declared experiment differs: ' + field)
    require(record.get('pairOrder') == [{key: run[key] for key in ('phase', 'pairIndex', 'orderInPair', 'variant')}
                                      for run in record['runs']], 'Declared order differs from actual observations')
    require(record.get('childProtocol') == policy['childProtocol'], 'Bounded child protocol changed')
    runtime_binding = record.get('runtimeBindings', {})
    require(isinstance(runtime_binding, dict) and set(runtime_binding) == {'schema', 'childEnvironment', 'jdkFiles', 'jdkSymlinks', 'dependencyFiles'}
            and runtime_binding.get('schema') == 'lightforge.host-runtime-bindings.v1'
            and runtime_binding.get('childEnvironment') == {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'TZ': 'UTC'},
            'Incomplete or uncontrolled bounded runtime environment')
    jdk = runtime_binding['jdkFiles']
    require(isinstance(jdk, dict) and {'bin/java', 'bin/javac', 'lib/modules', 'lib/server/libjvm.so', 'release'} <= set(jdk)
            and 0 < len(jdk) <= 4096 and all(isinstance(name, str) and not name.startswith('/')
                and '..' not in Path(name).parts and digest(value) for name, value in jdk.items()),
            'Incomplete bounded JDK/compiler fingerprint inventory')
    links = runtime_binding['jdkSymlinks']
    require(isinstance(links, dict) and set(links) <= set(jdk) and all(
        isinstance(target, str) and 0 < len(target) <= 4096 and not target.startswith('/')
        and not posixpath.normpath(posixpath.join(posixpath.dirname(name), target)).startswith('../')
        for name, target in links.items()), 'Bounded JDK links escape their frozen inventory')
    dependencies = runtime_binding['dependencyFiles']
    require(isinstance(dependencies, dict) and set(dependencies) == {'test-json.jar', 'android.jar', 'onnxruntime-1.25.1.jar'}
            and all(digest(value) for value in dependencies.values())
            and dependencies['onnxruntime-1.25.1.jar'] == record['runtime']['hostJarSha256'],
            'Incomplete bounded classpath/native runtime fingerprint inventory')
    check = read_bounded_json(receipt.parent / 'registration-check.json')
    require(check == record.get('registrationCheck') and check.get('measurementAuthorized') is True
            and check.get('purpose') == 'producer', 'Retained prospective registration check missing')
    marker = read_bounded_json(receipt.parent / 'measurement-started.json')
    require(marker == dict(campaignId=record['campaignId'], startedAt=record.get('measurementStartedAt'),
                           declarationSha256=record['campaignDeclarationSha256']), 'Original execution marker changed')
    intervals = [declaration.get('declaredAt'), check.get('checkedAt'),
                 record.get('measurementStartedAt'), record.get('finishedAt')]
    require(all(isinstance(value, str) for value in intervals), 'Bounded timing provenance is incomplete')
    instants = [datetime.datetime.fromisoformat(value.replace('Z', '+00:00')) for value in intervals]
    require(all(value.tzinfo is not None for value in instants) and instants == sorted(instants),
            'Inconsistent prospective registration/measurement order')
    if rebuild_classes:
        benchmark = load_module('bounded_recompile', root / 'tools/benchmark_deux_parallel.py')
        benchmark.ROOT = root
        java, dependencies = benchmark.bounded_toolchain()
        require(benchmark.bounded_runtime_bindings(java, dependencies) == record['runtimeBindings'],
                'Current runtime/compiler does not match the immutable experiment')
        with tempfile.TemporaryDirectory(prefix='lightforge-bounded-recompile-') as directory:
            classes = benchmark.compile_production(Path(directory), java, dependencies, record['sourceBindings'],
                                                    controlled_environment=benchmark.BOUNDED_CHILD_ENV)
            require(benchmark.portable_class_hashes(classes) == record['compiledClassHashes'],
                    'Current compiled production classes differ from the terminal proof')
    return reduction


def verify_bounded_prerequisite(record, root=ROOT):
    """A current build needs trusted history AND exact original experiment replay."""
    require(record.get('schema') == 'lightforge.host-inference-build-prerequisite.v1'
            and set(record) == {'schema', 'sourceBindings', 'sourceBindingsAfter', 'admission'},
            'Unknown bounded prerequisite envelope')
    admission = record.get('admission')
    require(isinstance(admission, dict), 'Trusted bounded host admission missing')
    source_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    source_tree = subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=root, text=True).strip()
    session = os.environ.get('LIGHTFORGE_EVIDENCE_SESSION')
    require(isinstance(session, str) and re.fullmatch('[0-9a-f]{64}', session) is not None,
            'Fresh current candidate evidence session missing')
    require(admission.get('candidate') == dict(sourceCommit=source_commit, sourceTreeSha=source_tree,
                                              evidenceSession=session),
            'Host admission belongs to a different current candidate or evidence session')
    helper = campaign_helper(root)
    declaration, proof, directory, online = helper.fetch_proof(root, admission=admission)
    require(online.get('trustedReplayAuthorized') is True, 'Trusted terminal campaign history not established')
    require(record['sourceBindings'] == record['sourceBindingsAfter'] == proof.get('sourceBindings')
            and admission.get('recompiledClassHashes') == proof.get('compiledClassHashes'),
            'Build envelope differs from exact measured source/class bindings')
    return verify_bounded(Path(directory) / 'receipt.json', root, rebuild_classes=True)


def verify(root=ROOT):
    path = root / RECEIPT
    require(path.is_file() and path.stat().st_size <= 262144, 'final-source inference improvement evidence is missing')
    record = read_bounded_json(path, 262144)
    if record.get('schema') == 'lightforge.host-inference-build-prerequisite.v1':
        return verify_bounded_prerequisite(record, root)
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
    parser.add_argument('--experimental-portable-receipt', type=Path,
                        help='Replay retained portable artifacts only; never satisfies the production release gate')
    parser.add_argument('--bounded-receipt', type=Path, help='Local complete bounded replay only, not trusted admission')
    parser.add_argument('--rebuild-classes', action='store_true', help='Require current runtime and recompiled class equality')
    args = parser.parse_args()
    try:
        if args.bounded_receipt is not None:
            require(args.experimental_portable_receipt is None, 'Choose exactly one explicit replay protocol')
            reduction = verify_bounded(args.bounded_receipt, args.root, rebuild_classes=args.rebuild_classes)
            print(f'BOUNDED LOCAL REPLAY: {reduction:.1f}% lower median passage time; trusted campaign admission still required.')
            return
        if args.experimental_portable_receipt is not None:
            reduction = verify_portable(args.experimental_portable_receipt, args.root)
            print(f'EXPERIMENTAL PASS: {reduction:.1f}% lower median constrained-host passage time; NOT release-admissible.')
        else:
            reduction = verify(args.root)
            print(f'PASS: exact-output host inference prerequisite ({reduction:.1f}% lower median passage time).')
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise SystemExit('Release held: ' + str(error)) from error


if __name__ == '__main__':
    main()
