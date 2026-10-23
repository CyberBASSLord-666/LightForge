#!/usr/bin/env python3
"""Qualify exact-output parallel inference using unchanged production Java sources.

One compiled class set serves both variants. Only the constructor differs; there
are no generated or patched production implementations. Each run is a fresh JVM.
The warmup pair warms system caches and is excluded from the three measured pairs.
Every Java benchmark child is restricted to the same first seven allowed CPUs,
reserving at least one CPU of the observed cgroup quota for platform work. The
candidate explicitly exercises the unchanged eight-worker production runner on
those seven CPUs; this fixture does not simulate Android scheduler admission.
The Python parent and Android code are not repinned. Child-observed affinity and
processor count are mandatory observations; JVM processor counts are not spoofed.
This is host evidence, not physical Android or complete-song performance evidence.
"""
import argparse
import copy
import datetime
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import statistics
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATHS = {
    'android/src/com/cyberbasslord/lightforge/' + name + '.java'
    for name in ('NativeDeux', 'NativeDeuxTransform', 'NativeInferenceProfile', 'NativeExecutionPolicy', 'NativePassagePolicy')
} | {'android/native-runtime.json', 'tests/NativeDeuxParallelBenchmark.java',
     'tools/benchmark_deux_parallel.py', 'tools/benchmark_deux_execution.py',
     'qa/release-2.4.1/verify-analysis.py'}
GEOMETRY = dict(graphCount=27, stageCount=15, bands=60, frames=1301, samplesPerStem=573300,
                baseline=dict(workers=1, timeBatch=4, frequencyBatch=128, inferenceCalls=335),
                candidate=dict(workers=8, timeBatch=1, frequencyBatch=16, frequencyTail=5, inferenceCalls=1727))
CRITERIA = dict(measuredPairs=3, minMedianWallReductionPercent=15, minEachPairWallReductionPercent=5)
MAX_THROTTLE_TO_WALL_RATIO = .05
LEGACY_PROTOCOL = 'production-v3'
PORTABLE_PROTOCOL = 'portable-four-worker-three-cpu-v1'
PORTABLE_SCHEMA = 'lightforge.experimental-portable-parallel-qualification.v1'
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


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


b = load('deux_execution_benchmark', ROOT / 'tools/benchmark_deux_execution.py')


def source_bindings(paths=SOURCE_PATHS):
    return {name: b.sha(ROOT / name) for name in sorted(paths)}


def child_cpu_control():
    b.require(hasattr(os, 'sched_getaffinity') and hasattr(os, 'sched_setaffinity'),
              'Observed Linux child affinity control is required')
    parent = sorted(os.sched_getaffinity(0))
    b.require(len(parent) >= 8, 'Eight allowed CPUs are required to reserve platform headroom')
    quota_text = Path('/sys/fs/cgroup/cpu.max').read_text().strip()
    fields = quota_text.split()
    b.require(len(fields) == 2 and fields[0].isdigit() and int(fields[0]) > 0
              and fields[1].isdigit() and int(fields[1]) > 0, 'A finite positive cgroup CPU quota is required')
    capacity = int(fields[0]) / int(fields[1])
    b.require(capacity >= 8, 'CPU quota does not permit seven child CPUs and one CPU of headroom')
    return dict(schema='lightforge.child-cpu-affinity.v2', scope='java-benchmark-children-only',
                parentCpuAffinity=parent, childCpuAffinity=parent[:7], cgroupCpuQuota=quota_text,
                quotaCpuCapacity=capacity, expectedAvailableProcessors=7, reservedQuotaCpuCapacity=1)


def parse_cpu_affinity(value):
    b.require(isinstance(value, str) and len(value) <= 4096 and
              re.fullmatch(r'[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*', value), 'Invalid child CPU affinity')
    cpus = []
    for part in value.split(','):
        bounds = [int(number) for number in part.split('-')]
        first, last = bounds[0], bounds[-1]
        b.require(0 <= first <= last <= 65535 and last - first < 256, 'Unbounded child CPU affinity')
        cpus.extend(range(first, last + 1))
    b.require(cpus == sorted(set(cpus)), 'Child CPU affinity is duplicated or unordered')
    return cpus


def coverage(path, variant):
    b.require(variant in {'baseline', 'candidate4', 'candidate'}, 'Unknown reviewed host geometry')
    rows = [dict(piece.split('=', 1) for piece in line.split()) for line in path.read_text().splitlines()]
    b.require(len(rows) == 43, 'Full 27-graph/15-stage profile required')
    summary = rows[0]
    b.require(summary.get('schema') == 'native-inference-profile-v2' and summary.get('outcome') == 'completed'
              and summary.get('graphRecords') == '27' and summary.get('stageRecords') == '15'
              and summary.get('droppedGraphRecords') == '0' and summary.get('droppedStageRecords') == '0',
              'Incomplete production inference profile')
    graphs = [r for r in rows[1:] if r.get('schema') == 'native-inference-graph-v2']
    stages = [r for r in rows[1:] if r.get('schema') == 'native-inference-stage-v1']
    b.require(len(graphs) == 27 and {r.get('graph') for r in graphs} == b.GRAPH_NAMES
              and len(stages) == 15 and {r.get('stage') for r in stages} == b.STAGE_NAMES,
              'Original graph/stage inventory changed')
    temporal_calls = 15 if variant == 'baseline' else 60
    frequency_calls = 11 if variant == 'baseline' else 82
    expected = {name: 1 if name == 'front' else temporal_calls if name.endswith('-time') else frequency_calls if name.endswith('-frequency') else 11
                for name in b.GRAPH_NAMES}
    observed = {r['graph']: int(r['runCount']) for r in graphs}
    b.require(observed == expected and int(summary['inferenceCount']) == sum(expected.values()),
              'Original full-context band/frame work is incomplete')
    profile_verifier = load('current_parallel_profile_geometry', ROOT / 'qa/release-2.4.1/verify-analysis.py')
    profile_verifier.verify_scheduler_profile(path.read_text().splitlines(), sum(expected.values()),
                                              None if variant == 'baseline' else 4 if variant == 'candidate4' else 8)
    for key in ('inferenceWallMs', 'modelInitWallMs'):
        b.require(math.isfinite(float(summary[key])) and float(summary[key]) > 0, 'Invalid production timing')
    return dict(graphCount=27, stageCount=15, inferenceCalls=sum(expected.values()), graphRunCounts=observed)


def compile_production(work, java, dependencies, bindings):
    sources = work / 'source-snapshots'
    sources.mkdir()
    paths = []
    for name in sorted(bindings):
        original = ROOT / name
        destination = sources / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(original.read_bytes())
        b.require(b.sha(destination) == bindings[name], 'Production source changed before compile: ' + name)
        if name.endswith('.java'):
            paths.append(destination)
    stub = sources / 'AppDiagnostics.java'
    stub.write_text('package com.cyberbasslord.lightforge; public final class AppDiagnostics {'
                    'public static void log(android.content.Context c,String l,String s,String m){}'
                    'public static boolean flush(long timeout){return true;}}\n')
    paths.append(stub)
    classes = work / 'classes'
    classes.mkdir()
    command = [str(java / 'javac'), '--release', '8', '-encoding', 'UTF-8', '-cp',
               os.pathsep.join(map(str, dependencies)), '-d', str(classes), *map(str, paths)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    (work / 'compile.log').write_text(result.stdout + result.stderr)
    b.require(result.returncode == 0, 'Production compilation failed; see compile.log')
    b.require(source_bindings(bindings) == bindings, 'Production sources changed during compilation')
    return classes


def class_hashes(classes):
    return {str(path.relative_to(classes)): b.sha(path) for path in sorted(classes.rglob('*.class'))}


def measure(variant, pair, order, phase, classes, work, java, dependencies, models, audio, start_sample,
            cpu_control=None, run_process=None):
    control = child_cpu_control() if cpu_control is None else cpu_control
    b.require(child_cpu_control() == control, 'Parent CPU allowance or quota changed before run')
    directory = work / variant
    directory.mkdir(exist_ok=True)
    prefix = phase + '-' + str(pair)
    output, profile = directory / (prefix + '.f32'), directory / (prefix + '.profile.txt')
    b.require(not output.exists() and not profile.exists(), 'Existing observation must not be overwritten')
    command = [str(java / 'java'), '-Xmx1g', '-XX:MaxDirectMemorySize=512m', '-cp',
               os.pathsep.join(map(str, [classes, *dependencies])),
               'com.cyberbasslord.lightforge.NativeDeuxParallelBenchmark', str(models), str(audio),
               str(output), str(start_sample), str(profile), variant]
    print(phase + ' ' + str(pair) + ' ' + variant, flush=True)
    before = b.host_counters()
    # Runs only in the forked Java child. This single-threaded Python parent,
    # unrelated processes, Android implementation and cgroup quota are unchanged.
    result = (run_process or subprocess.run)(command, capture_output=True, text=True, timeout=1200,
                                             preexec_fn=lambda: os.sched_setaffinity(0, control['childCpuAffinity']))
    after = b.host_counters()
    (directory / (prefix + '.log')).write_text(result.stdout + result.stderr)
    b.require(result.returncode == 0, variant + ' inference failed; see ' + prefix + '.log')
    observation = json.loads(result.stdout.strip().splitlines()[-1])
    b.require(set(observation) == {'wallNanos', 'processCpuNanos', 'peakRssBytes', 'cpuAffinityList', 'availableProcessors'}
              and all(type(observation[key]) is int and observation[key] > 0
                      for key in ('wallNanos', 'processCpuNanos', 'peakRssBytes')), 'Invalid resource observation')
    context = dict(cpuAffinity=parse_cpu_affinity(observation.pop('cpuAffinityList')),
                   availableProcessors=observation.pop('availableProcessors'))
    b.require(context['cpuAffinity'] == control['childCpuAffinity'] and
              type(context['availableProcessors']) is int and
              context['availableProcessors'] == control['expectedAvailableProcessors'], 'Child CPU control was not applied')
    b.require(child_cpu_control() == control, 'Parent CPU allowance or quota changed during run')
    output_hash = b.read_output(output)
    observation.update(phase=phase, pairIndex=pair, orderInPair=order, variant=variant,
                       output=dict(sha256=output_hash, bytes=output.stat().st_size, floats=b.SAMPLES, finite=True),
                       coverage=coverage(profile, variant), profileSha256=b.sha(profile),
                       hostCountersBefore=before, hostCountersAfter=after, executionContext=context)
    return observation


def portable_host():
    return load('portable_inference_host', ROOT / 'tools/portable_inference_host.py')


def portable_class_hashes(classes):
    b.require(classes.is_dir() and not classes.is_symlink()
              and all(not path.is_symlink() for path in classes.rglob('*')),
              'Portable class inventory contains symlinks')
    return class_hashes(classes)


def portable_profile(path, variant):
    """Bind actual slot counts and the reference's observed three-thread geometry."""
    result = coverage(path, variant)
    summary = dict(piece.split('=', 1) for piece in path.read_text().splitlines()[0].split())
    reference = 'cpu-i3-j1-d0-sequential'
    expected = dict(temporalConfig=reference if variant == 'baseline' else 'cpu-i1-j1-d0-sequential-w4-b1',
                    frequencyConfig=reference if variant == 'baseline' else 'cpu-i1-j1-d0-sequential-w4-b16')
    b.require(variant in {'baseline', 'candidate4'} and
              all(summary.get(key) == value for key, value in expected.items()),
              'Portable profile does not execute the declared reference/candidate geometry')
    result['schedulerConfigurations'] = expected
    return result


def measure_portable(variant, pair, order, phase, classes, work, java, dependencies,
                     models, audio, controls, host=None, run_process=None):
    b.require(variant in {'baseline', 'candidate4'}, 'Portable protocol only measures baseline and candidate4')
    host = portable_host() if host is None else host
    host.validate_controls(controls)
    b.require(host.observe_controls() == controls, 'Portable host controls changed before run')
    directory = work / variant
    directory.mkdir(exist_ok=True)
    prefix = phase + '-' + str(pair)
    output, profile = directory / (prefix + '.f32'), directory / (prefix + '.profile.txt')
    b.require(not output.exists() and not profile.exists(), 'Existing observation must not be overwritten')
    command = [str(java / 'java'), '-Xmx1g', '-XX:MaxDirectMemorySize=512m', '-cp',
               os.pathsep.join(map(str, [classes, *dependencies])),
               'com.cyberbasslord.lightforge.NativeDeuxParallelBenchmark', str(models), str(audio),
               str(output), '661500', str(profile), variant, PORTABLE_PROTOCOL]
    child = controls['childCpuAffinity']
    print(PORTABLE_PROTOCOL + ' ' + phase + ' ' + str(pair) + ' ' + variant, flush=True)
    before = host.observe_counters(controls)
    (directory / (prefix + '.resources-before.json')).write_text(json.dumps(before, indent=2) + '\n')
    result = (run_process or subprocess.run)(command, capture_output=True, text=True, timeout=1200,
                                             preexec_fn=lambda: os.sched_setaffinity(0, child))
    (directory / (prefix + '.log')).write_text(result.stdout + result.stderr)
    (directory / (prefix + '.process.json')).write_text(json.dumps(
        dict(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr), indent=2) + '\n')
    after = host.observe_counters(controls)
    (directory / (prefix + '.resources-after.json')).write_text(json.dumps(after, indent=2) + '\n')
    b.require(result.returncode == 0, variant + ' portable inference failed; see ' + prefix + '.log')
    observation = json.loads(result.stdout.strip().splitlines()[-1])
    b.require(set(observation) == {'wallNanos', 'processCpuNanos', 'peakRssBytes', 'cpuAffinityList',
                                  'availableProcessors', 'protocol', 'hostVariant', 'referenceIntraThreads',
                                  'resourceIdentityBefore', 'resourceIdentityAfter'}
              and all(type(observation[key]) is int and observation[key] > 0
                      for key in ('wallNanos', 'processCpuNanos', 'peakRssBytes')),
              'Invalid portable resource observation')
    context = dict(cpuAffinity=parse_cpu_affinity(observation.pop('cpuAffinityList')),
                   availableProcessors=observation.pop('availableProcessors'),
                   referenceIntraThreads=observation.pop('referenceIntraThreads'),
                   protocol=observation.pop('protocol'), hostVariant=observation.pop('hostVariant'),
                   resourceIdentityBefore=observation.pop('resourceIdentityBefore'),
                   resourceIdentityAfter=observation.pop('resourceIdentityAfter'))
    expected_identity = dict(procCgroup=controls['procCgroup'], cgroupNamespace=controls['namespace']['link'])
    b.require(context == dict(cpuAffinity=child, availableProcessors=3, referenceIntraThreads=3,
                             protocol=PORTABLE_PROTOCOL, hostVariant=variant,
                             resourceIdentityBefore=expected_identity, resourceIdentityAfter=expected_identity)
              and type(context['availableProcessors']) is int and type(context['referenceIntraThreads']) is int,
              'Observed portable JVM configuration differs from declaration')
    b.require(host.observe_controls() == controls, 'Portable host controls changed during run')
    output_hash = b.read_output(output)
    observation.update(phase=phase, pairIndex=pair, orderInPair=order, variant=variant,
                       output=dict(sha256=output_hash, bytes=output.stat().st_size, floats=b.SAMPLES, finite=True),
                       coverage=portable_profile(profile, variant), profileSha256=b.sha(profile),
                       hostCountersBefore=before, hostCountersAfter=after, executionContext=context)
    observation['artifacts'] = {key: b.sha(directory / (prefix + suffix)) for key, suffix in (
        ('logSha256', '.log'), ('processSha256', '.process.json'),
        ('countersBeforeSha256', '.resources-before.json'), ('countersAfterSha256', '.resources-after.json'))}
    return observation


def summarize_portable(record, host=None):
    host = portable_host() if host is None else host
    measured = [run for run in record['runs'] if run['phase'] == 'measurement']
    pairs = []
    for index in range(3):
        pair = {run['variant']: run for run in measured if run['pairIndex'] == index}
        baseline, candidate = pair['baseline']['wallNanos'], pair['candidate4']['wallNanos']
        pairs.append(dict(pairIndex=index, baselineWallNanos=baseline, candidateWallNanos=candidate,
                          wallReductionPercent=100 * (1 - candidate / baseline)))
    medians = {variant: {key: statistics.median(run[key] for run in measured if run['variant'] == variant)
                         for key in ('wallNanos', 'processCpuNanos', 'peakRssBytes')}
               for variant in ('baseline', 'candidate4')}
    resources = [host.validate_resource_pair(run['hostCountersBefore'], run['hostCountersAfter'],
                                            run['wallNanos'], record['hostControls']) for run in record['runs']]
    reduction = 100 * (1 - medians['candidate4']['wallNanos'] / medians['baseline']['wallNanos'])
    exact = len({run['output']['sha256'] for run in record['runs']}) == 1
    record.update(pairedReductions=pairs, medians=medians, medianWallReductionPercent=reduction,
                  allOutputsByteIdentical=exact, resourcePairs=resources,
                  passed=exact and reduction >= 15 and all(pair['wallReductionPercent'] >= 5 for pair in pairs))


def run_portable(args):
    """Produce separate experimental evidence, never the current build prerequisite."""
    b.require(args.receipt == ROOT / 'research/inference-current/production-parallel-qualification.json',
              'Portable evidence stays in its fresh output directory; --receipt is legacy-only')
    work = args.output.resolve()
    b.require(not work.exists(), 'A fresh output directory is required')
    host = portable_host()
    controls = host.observe_controls()
    host.validate_controls(controls)
    work.mkdir(parents=True)
    toolchain = ROOT.parent / 'toolchain'
    java = toolchain / 'jdk17/bin'
    dependencies = [toolchain / 'test-json.jar', toolchain / 'android-sdk/platforms/android-35/android.jar',
                    toolchain / 'onnx/onnxruntime-1.25.1.jar']
    runtime = json.loads((ROOT / 'android/native-runtime.json').read_text())
    b.require(runtime['version'] == '1.25.1' and b.sha(dependencies[-1]) == runtime['host']['sha256'],
              'Pinned ONNX Runtime 1.25.1 is required')
    models, audio = ROOT / 'web/analysis/models/deux', ROOT / 'web/demo/glass-castle.wav'
    manifest = json.loads((models / 'manifest.json').read_text())
    b.require(manifest.get('frames') == 1301 and manifest.get('samples') == 573300 and len(manifest['files']) == 27,
              'Original model geometry is required')
    for name, entry in manifest['files'].items():
        b.require((models / name).stat().st_size == entry['bytes'] and b.sha(models / name) == entry['sha256'],
                  'Original model integrity failure: ' + name)
    bindings = source_bindings(PORTABLE_SOURCE_PATHS)
    classes = compile_production(work, java, dependencies, bindings)
    compiled = portable_class_hashes(classes)
    declaration = dict(schema='lightforge.portable-qualification-declaration.v1', protocol=PORTABLE_PROTOCOL,
        declaredAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), scope=PORTABLE_SCOPE,
        releaseAdmissible=False, geometry=copy.deepcopy(PORTABLE_GEOMETRY), criteria=copy.deepcopy(CRITERIA),
        maxAllowedThrottleToWallRatio=MAX_THROTTLE_TO_WALL_RATIO, hostControls=controls,
        sourceBindings=bindings, compiledClassHashes=compiled)
    declaration_path = work / 'protocol.json'
    with declaration_path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(declaration, indent=2) + '\n')
    declaration_hash = b.sha(declaration_path)
    record = dict(schema=PORTABLE_SCHEMA, protocol=PORTABLE_PROTOCOL, scope=PORTABLE_SCOPE,
        createdAt=declaration['declaredAt'], protocolDeclaration=declaration,
        protocolDeclarationSha256=declaration_hash, host=b.host_metadata(), hostControls=controls,
        sourceBindings=bindings, compiledClassHashes=compiled,
        runtime=dict(version='1.25.1', hostJarSha256=runtime['host']['sha256']),
        models=dict(manifestSha256=b.sha(models / 'manifest.json'),
                    graphHashes={name: entry['sha256'] for name, entry in manifest['files'].items()}),
        audio=dict(sha256=b.sha(audio), startSample=661500), geometry=copy.deepcopy(PORTABLE_GEOMETRY),
        criteria=copy.deepcopy(CRITERIA), maxAllowedThrottleToWallRatio=MAX_THROTTLE_TO_WALL_RATIO,
        runs=[], passed=False, releaseAdmissible=False, eightWorkerSpeedupProven=False,
        androidSpeedupProven=False, wholeAnalysisSpeedupProven=False)
    receipt = work / 'receipt.json'
    receipt.write_text(json.dumps(record, indent=2) + '\n')
    for phase, count in [('warmup', 1), ('measurement', 3)]:
        for pair in range(count):
            order = ('candidate4', 'baseline') if pair % 2 else ('baseline', 'candidate4')
            for order_index, variant in enumerate(order):
                b.require(source_bindings(PORTABLE_SOURCE_PATHS) == bindings, 'Portable sources changed before run')
                b.require(portable_class_hashes(classes) == compiled and b.sha(declaration_path) == declaration_hash,
                          'Portable classes or prospective declaration changed before run')
                run = measure_portable(variant, pair, order_index, phase, classes, work, java,
                                       dependencies, models, audio, controls, host)
                record['runs'].append(run)
                record['sourceBindingsAfter'] = source_bindings(PORTABLE_SOURCE_PATHS)
                record['compiledClassHashesAfter'] = portable_class_hashes(classes)
                receipt.write_text(json.dumps(record, indent=2) + '\n')
                b.require(record['sourceBindingsAfter'] == bindings and record['compiledClassHashesAfter'] == compiled
                          and b.sha(declaration_path) == declaration_hash,
                          'Portable measured inputs changed during run')
                b.require(len({run['output']['sha256'] for run in record['runs']}) == 1,
                          'Complete Float32 outputs differ')
    for name, expected in record['models']['graphHashes'].items():
        b.require(b.sha(models / name) == expected, 'Original model changed during qualification')
    b.require(b.sha(audio) == record['audio']['sha256'], 'Qualification audio changed')
    b.require(b.sha(dependencies[-1]) == runtime['host']['sha256'], 'Pinned runtime changed during qualification')
    summarize_portable(record, host)
    record['finishedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    receipt.write_text(json.dumps(record, indent=2) + '\n')
    b.require(record['passed'], 'Experimental performance thresholds were not met; observations retained')
    verifier = load('portable_inference_verifier', ROOT / 'tools/verify_inference_improvement.py')
    verifier.verify_portable(receipt, ROOT)
    print(json.dumps(dict(passed=True, releaseAdmissible=False, protocol=PORTABLE_PROTOCOL,
                          medianWallReductionPercent=record['medianWallReductionPercent'])), flush=True)


def delta(run, group, key):
    before, after = run['hostCountersBefore'][group][key], run['hostCountersAfter'][group][key]
    b.require(type(before) is int and type(after) is int and 0 <= before <= after, 'Invalid host resource counters')
    return after - before


def summarize(record):
    measured = [run for run in record['runs'] if run['phase'] == 'measurement']
    pairs = []
    for index in range(3):
        pair = {run['variant']: run for run in measured if run['pairIndex'] == index}
        baseline, candidate = pair['baseline']['wallNanos'], pair['candidate']['wallNanos']
        pairs.append(dict(pairIndex=index, baselineWallNanos=baseline, candidateWallNanos=candidate,
                          wallReductionPercent=100 * (1 - candidate / baseline)))
    medians = {variant: {key: statistics.median(run[key] for run in measured if run['variant'] == variant)
                         for key in ('wallNanos', 'processCpuNanos', 'peakRssBytes')}
               for variant in ('baseline', 'candidate')}
    resources = dict(
        noOom=all(delta(run, 'cgroupMemoryEvents', key) == 0 for run in record['runs'] for key in ('oom', 'oom_kill')),
        noMemoryLimitEvents=all(delta(run, 'cgroupMemoryEvents', 'max') == 0 for run in record['runs']),
        noDirectReclaim=all(delta(run, 'cgroupMemoryStat', key) == 0 for run in record['runs']
                            for key in ('pgscan_direct', 'pgsteal_direct')),
        maxThrottleToWallRatio=max(delta(run, 'cgroupCpuStat', 'throttled_usec') * 1000 / run['wallNanos']
                                    for run in record['runs']))
    reduction = 100 * (1 - medians['candidate']['wallNanos'] / medians['baseline']['wallNanos'])
    exact = len({run['output']['sha256'] for run in record['runs']}) == 1
    passed = (exact and reduction >= CRITERIA['minMedianWallReductionPercent']
              and all(pair['wallReductionPercent'] >= CRITERIA['minEachPairWallReductionPercent'] for pair in pairs)
              and all(resources[key] for key in ('noOom', 'noMemoryLimitEvents', 'noDirectReclaim'))
              and resources['maxThrottleToWallRatio'] <= MAX_THROTTLE_TO_WALL_RATIO)
    record.update(pairedReductions=pairs, medians=medians, medianWallReductionPercent=reduction,
                  allOutputsByteIdentical=exact, resources=resources, passed=passed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='Fresh directory for immutable run evidence')
    parser.add_argument('--receipt', type=Path, default=ROOT / 'research/inference-current/production-parallel-qualification.json')
    parser.add_argument('--protocol', choices=(LEGACY_PROTOCOL, PORTABLE_PROTOCOL), default=LEGACY_PROTOCOL,
                        help='Prospectively select a protocol. Portable evidence is experimental, never release-admissible.')
    args = parser.parse_args()
    if args.protocol == PORTABLE_PROTOCOL:
        return run_portable(args)
    work = args.output.resolve()
    b.require(not work.exists(), 'A fresh output directory is required')
    work.mkdir(parents=True)
    toolchain = ROOT.parent / 'toolchain'
    java = toolchain / 'jdk17/bin'
    dependencies = [toolchain / 'test-json.jar', toolchain / 'android-sdk/platforms/android-35/android.jar',
                    toolchain / 'onnx/onnxruntime-1.25.1.jar']
    runtime = json.loads((ROOT / 'android/native-runtime.json').read_text())
    b.require(runtime['version'] == '1.25.1' and b.sha(dependencies[-1]) == runtime['host']['sha256'],
              'Pinned ONNX Runtime 1.25.1 is required')
    models, audio = ROOT / 'web/analysis/models/deux', ROOT / 'web/demo/glass-castle.wav'
    manifest = json.loads((models / 'manifest.json').read_text())
    b.require(manifest.get('frames') == 1301 and manifest.get('samples') == 573300 and len(manifest['files']) == 27,
              'Original model geometry is required')
    for name, entry in manifest['files'].items():
        b.require((models / name).stat().st_size == entry['bytes'] and b.sha(models / name) == entry['sha256'],
                  'Original model integrity failure: ' + name)
    bindings = source_bindings()
    cpu_control = child_cpu_control()
    record = dict(schema='lightforge.production-parallel-qualification.v3',
                  createdAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), host=b.host_metadata(),
                  hostControls=cpu_control,
                  sourceBindings=bindings, runtime=dict(version='1.25.1', hostJarSha256=runtime['host']['sha256']),
                  models=dict(manifestSha256=b.sha(models / 'manifest.json'),
                              graphHashes={name: entry['sha256'] for name, entry in manifest['files'].items()}),
                  audio=dict(sha256=b.sha(audio), startSample=661500), geometry=GEOMETRY, criteria=CRITERIA,
                  maxAllowedThrottleToWallRatio=MAX_THROTTLE_TO_WALL_RATIO,
                  runs=[], passed=False, androidSpeedupProven=False, wholeAnalysisSpeedupProven=False)
    classes = compile_production(work, java, dependencies, bindings)
    record['compiledClassHashes'] = class_hashes(classes)
    receipt = work / 'receipt.json'
    receipt.write_text(json.dumps(record, indent=2) + '\n')
    for phase, count in [('warmup', 1), ('measurement', 3)]:
        for pair in range(count):
            order = ('candidate', 'baseline') if pair % 2 else ('baseline', 'candidate')
            for order_index, variant in enumerate(order):
                b.require(source_bindings() == bindings, 'Production sources changed before run')
                b.require(class_hashes(classes) == record['compiledClassHashes'], 'Compiled classes changed before run')
                run = measure(variant, pair, order_index, phase, classes, work, java, dependencies, models, audio, 661500,
                              cpu_control)
                record['runs'].append(run)
                record['sourceBindingsAfter'] = source_bindings()
                b.require(record['sourceBindingsAfter'] == bindings, 'Production sources changed during qualification')
                b.require(class_hashes(classes) == record['compiledClassHashes'], 'Compiled classes changed during qualification')
                receipt.write_text(json.dumps(record, indent=2) + '\n')
                b.require(len({r['output']['sha256'] for r in record['runs']}) == 1, 'Complete Float32 outputs differ')
            current = {r['variant']: r for r in record['runs'] if r['phase'] == phase and r['pairIndex'] == pair}
            print(json.dumps(dict(phase=phase, pairIndex=pair, baselineSeconds=current['baseline']['wallNanos'] / 1e9,
                                  candidateSeconds=current['candidate']['wallNanos'] / 1e9, exact=True)), flush=True)
    for name, expected in record['models']['graphHashes'].items():
        b.require(b.sha(models / name) == expected, 'Original model changed during qualification')
    b.require(b.sha(audio) == record['audio']['sha256'], 'Qualification audio changed')
    record['sourceBindingsAfter'] = source_bindings()
    b.require(record['sourceBindingsAfter'] == bindings, 'Production sources changed before final receipt')
    summarize(record)
    record['finishedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    receipt.write_text(json.dumps(record, indent=2) + '\n')
    b.require(record['passed'], 'Production performance thresholds were not met; retained observations in output directory')
    # The build prerequisite receives only a fully completed, passing receipt.
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(dict(passed=True, medianWallReductionPercent=record['medianWallReductionPercent'],
                          pairedReductions=record['pairedReductions'])), flush=True)


if __name__ == '__main__':
    main()
