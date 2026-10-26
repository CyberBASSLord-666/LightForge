"""The next release cannot use partial, noisy or stale inference evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('inference_gate', ROOT / 'tools/verify_inference_improvement.py')
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def production_coverage(variant):
    """Independent original-graph geometry, not the gate's branch expression.

    Twelve blocks each cover 60 bands and all 1301 frames. The two output
    heads always use 128-frame chunks, independent of frequency-block batching.
    """
    bands, frames, head_batch = 60, 1301, 128
    time_batch, frequency_batch = (4, 128) if variant == 'baseline' else (1, 16)
    head_calls = (frames + head_batch - 1) // head_batch
    counts = {'front': 1, 'head-0': head_calls, 'head-1': head_calls}
    for block in range(12):
        counts[f'block-{block:02d}-time'] = (bands + time_batch - 1) // time_batch
        counts[f'block-{block:02d}-frequency'] = (frames + frequency_batch - 1) // frequency_batch
    return dict(graphCount=len(counts), stageCount=15,
                inferenceCalls=sum(counts.values()), graphRunCounts=counts)


def valid():
    record = dict(schema='lightforge.production-parallel-qualification.v3', passed=True,
                  allOutputsByteIdentical=True, androidSpeedupProven=False,
                  wholeAnalysisSpeedupProven=False, geometry=copy.deepcopy(GATE.GEOMETRY),
                  criteria=copy.deepcopy(GATE.CRITERIA), runs=[], pairedReductions=[],
                  hostControls=dict(schema='lightforge.child-cpu-affinity.v2',
                    scope='java-benchmark-children-only', parentCpuAffinity=list(range(9)),
                    childCpuAffinity=list(range(7)), cgroupCpuQuota='800000 100000',
                    quotaCpuCapacity=8, expectedAvailableProcessors=7, reservedQuotaCpuCapacity=1))
    for phase, pairs in [('warmup', 1), ('measurement', 3)]:
        for index in range(pairs):
            for order, variant in enumerate(('candidate', 'baseline') if index % 2 else ('baseline', 'candidate')):
                counters = dict(cgroupMemoryEvents=dict(oom=0, oom_kill=0, max=0),
                                cgroupMemoryStat=dict(pgscan_direct=0, pgsteal_direct=0),
                                cgroupCpuStat=dict(throttled_usec=0))
                record['runs'].append(dict(phase=phase, pairIndex=index, orderInPair=order, variant=variant,
                    wallNanos=100000000 if variant == 'baseline' else 75000000, processCpuNanos=250000000,
                    peakRssBytes=1000000000, output=dict(sha256='a'*64, bytes=4586400, floats=1146600, finite=True),
                    coverage=production_coverage(variant),
                    executionContext=dict(cpuAffinity=list(range(7)), availableProcessors=7),
                    hostCountersBefore=copy.deepcopy(counters), hostCountersAfter=copy.deepcopy(counters)))
    record['pairedReductions'] = [dict(pairIndex=i, baselineWallNanos=100000000, candidateWallNanos=75000000,
                                     wallReductionPercent=25.) for i in range(3)]
    record['medians'] = {variant: dict(wallNanos=100000000 if variant == 'baseline' else 75000000,
                                      processCpuNanos=250000000, peakRssBytes=1000000000)
                         for variant in ('baseline', 'candidate')}
    record['medianWallReductionPercent'] = 25.
    record['resources'] = dict(noOom=True, noMemoryLimitEvents=True, noDirectReclaim=True, maxThrottleToWallRatio=0.)
    return record


class InferenceImprovementTest(unittest.TestCase):
    def test_benchmark_and_verifier_contracts_match(self):
        spec = importlib.util.spec_from_file_location('production_benchmark', ROOT / 'tools/benchmark_deux_parallel.py')
        benchmark = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(benchmark)
        self.assertEqual(GATE.SOURCE_PATHS, benchmark.SOURCE_PATHS)
        self.assertEqual(GATE.GEOMETRY, benchmark.GEOMETRY)
        self.assertEqual(GATE.CRITERIA, benchmark.CRITERIA)
        benchmark_source = (ROOT / 'tools/benchmark_deux_parallel.py').read_text()
        self.assertIn("default=ROOT / '" + GATE.RECEIPT + "'", benchmark_source)
        self.assertNotIn('inference-2.4.1/', GATE.RECEIPT)
        self.assertIn('android/src/com/cyberbasslord/lightforge/NativePassagePolicy.java', GATE.SOURCE_PATHS)

    def test_version_change_cannot_bypass_missing_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('2.4.1', '2.4.2', '3.0.0', ''):
                with self.subTest(version=name):
                    (root / 'version.json').write_text(json.dumps({'name': name}))
                    result = subprocess.run([sys.executable, str(ROOT / 'tools/verify_inference_improvement.py'),
                                             '--root', str(root)], capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('Release held:', result.stderr)
                    self.assertIn('evidence is missing', result.stderr)
        source = (ROOT / 'build.sh').read_text()
        self.assertNotIn("if version['name']=='2.4.1'", source)
        self.assertEqual(source.count('gate.verify(root)'), 2)

    def test_complete_measurement(self):
        self.assertEqual(GATE.validate_measurements(valid()), 25.)
        value = valid()
        value['hostControls'].update(cgroupCpuQuota='850000 100000', quotaCpuCapacity=8.5)
        self.assertEqual(GATE.validate_measurements(value), 25.)

    def test_original_graph_geometry_keeps_heads_separate_from_frequency_blocks(self):
        for variant, temporal, frequency, total in (
                ('baseline', 15, 11, 335), ('candidate', 60, 82, 1727)):
            with self.subTest(variant=variant):
                coverage = production_coverage(variant)
                self.assertEqual(coverage['graphCount'], 27)
                self.assertEqual(coverage['graphRunCounts']['front'], 1)
                self.assertEqual(coverage['graphRunCounts']['head-0'], 11)
                self.assertEqual(coverage['graphRunCounts']['head-1'], 11)
                self.assertEqual(coverage['inferenceCalls'], 1 + 12 * temporal + 12 * frequency + 2 * 11)
                self.assertEqual(coverage['inferenceCalls'], total)
                self.assertEqual(GATE.GEOMETRY[variant]['inferenceCalls'], total)
        self.assertEqual(GATE.validate_measurements(valid()), 25.)

    def test_wrong_head_counts_rejected_even_with_consistent_or_unchanged_total(self):
        for first, second in ((0, 11), (10, 11), (12, 11), (82, 82), (10, 12)):
            with self.subTest(head_calls=(first, second)):
                record = valid()
                coverage = record['runs'][3]['coverage']
                coverage['graphRunCounts'].update({'head-0': first, 'head-1': second})
                coverage['inferenceCalls'] = sum(coverage['graphRunCounts'].values())
                with self.assertRaisesRegex(ValueError, 'Incomplete original graph/band/frame work'):
                    GATE.validate_measurements(record)

    def test_previous_1869_call_head_overcount_is_not_admissible(self):
        record = valid()
        for run in record['runs']:
            if run['variant'] == 'candidate':
                coverage = run['coverage']
                coverage['graphRunCounts'].update({'head-0': 82, 'head-1': 82})
                coverage['inferenceCalls'] = sum(coverage['graphRunCounts'].values())
                self.assertEqual(coverage['inferenceCalls'], 1869)
        with self.assertRaisesRegex(ValueError, 'Incomplete original graph/band/frame work'):
            GATE.validate_measurements(record)

    def test_missing_repeat_changed_output_geometry_or_clock_rejected(self):
        transforms = [lambda r: r['runs'].pop(),
                      lambda r: r['runs'][3]['output'].update(sha256='b'*64),
                      lambda r: r['runs'][3]['output'].update(finite=False),
                      lambda r: r['runs'][3]['output'].update(bytes=4),
                      lambda r: r['runs'][3]['coverage']['graphRunCounts'].update({'block-11-time': 59}),
                      lambda r: r['runs'][3].update(wallNanos=0),
                      lambda r: r['runs'][3].update(processCpuNanos=-1),
                      lambda r: r['runs'][3].update(peakRssBytes=-1),
                      lambda r: r['runs'][4].update(orderInPair=1),
                      lambda r: r['criteria'].update(measuredPairs=2),
                      lambda r: r.update(androidSpeedupProven=True),
                      lambda r: r.update(passed=1)]
        for transform in transforms:
            with self.subTest(transform=transform):
                value = valid(); transform(value)
                with self.assertRaises(ValueError): GATE.validate_measurements(value)

    def test_noisy_pair_cannot_hide_behind_good_median(self):
        value = valid(); value['runs'][3]['wallNanos'] = 97000000
        with self.assertRaises(ValueError): GATE.validate_measurements(value)

    def test_unequal_or_oversubscribed_cpu_controls_rejected(self):
        transforms = [lambda r: r.pop('hostControls'),
                      lambda r: r['hostControls'].update(cgroupCpuQuota='700000 100000', quotaCpuCapacity=7),
                      lambda r: r['hostControls'].update(childCpuAffinity=list(range(1, 9))),
                      lambda r: r['hostControls'].update(quotaCpuCapacity=9),
                      lambda r: r['hostControls'].update(reservedQuotaCpuCapacity=0),
                      lambda r: r['runs'][3]['executionContext'].update(cpuAffinity=list(range(9))),
                      lambda r: r['runs'][3]['executionContext'].update(availableProcessors=9)]
        for transform in transforms:
            with self.subTest(transform=transform):
                value = valid(); transform(value)
                with self.assertRaises(ValueError): GATE.validate_measurements(value)

    def test_summary_is_recomputed(self):
        value = valid(); value['medianWallReductionPercent'] = 75
        with self.assertRaises(ValueError): GATE.validate_measurements(value)
        value = valid(); value['medians']['baseline']['wallNanos'] = 300000000
        with self.assertRaises(ValueError): GATE.validate_measurements(value)

    def test_resource_pressure_cannot_hide_behind_summary(self):
        for group, key, amount in [('cgroupMemoryEvents', 'oom_kill', 1),
                                    ('cgroupMemoryEvents', 'max', 1),
                                    ('cgroupMemoryStat', 'pgscan_direct', 1),
                                    ('cgroupCpuStat', 'throttled_usec', 10000)]:
            with self.subTest(key=key):
                value = valid(); value['runs'][3]['hostCountersAfter'][group][key] = amount
                with self.assertRaises(ValueError): GATE.validate_measurements(value)

    def test_build_checks_prerequisite_before_assets_or_packaging(self):
        source = (ROOT / 'build.sh').read_text()
        gate = source.index('tools/replay_inference_proof.py')
        self.assertLess(gate, source.index('tools/verify_analysis_assets.py'))
        self.assertLess(gate, source.index('mkdir -p'))
        # The current prerequisite has a cross-release envelope. Every build
        # checkpoint must use its admission verifier, including the later
        # compilation/signing checks; the frozen numerical CLI rejects it.
        self.assertNotIn('tools/verify_inference_improvement.py', source)
        checkpoint = 'python3 "$ROOT/tools/replay_inference_proof.py" verify --root "$ROOT"'
        for output_step in ('"$JAVA_HOME/bin/javac" -encoding',
                            '"$BUILD_TOOLS/zipalign" -P 16 -f 4'):
            with self.subTest(output_step=output_step):
                before = source[:source.index(output_step)].rstrip().splitlines()
                self.assertEqual(before[-1], checkpoint)
        self.assertIn('"$BUILD/java-src" "$BUILD/generated" "$BUILD/java-sources.txt"', source)
        self.assertIn('before!=copied or copied!=after', source)
        self.assertIn("copied.get(name[len(prefix):])!=digest", source)

    def test_changed_source_cannot_reuse_successful_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in GATE.SOURCE_PATHS:
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('test source ' + name)
            (root / 'android/native-runtime.json').write_text(json.dumps({'host': {'sha256': '1' * 64}}))
            manifest = root / 'web/analysis/models/deux/manifest.json'
            manifest.parent.mkdir(parents=True); manifest.write_text(json.dumps({'files': {
                name + '.onnx': {'sha256': '2' * 64} for name in GATE.GRAPH_NAMES}}))
            audio = root / 'web/demo/glass-castle.wav'; audio.parent.mkdir(parents=True); audio.write_bytes(b'fixture')
            value = valid()
            value.update(sourceBindings={name: GATE.sha(root / name) for name in GATE.SOURCE_PATHS},
                runtime=dict(version='1.25.1', hostJarSha256='1'*64),
                models=dict(manifestSha256=GATE.sha(manifest), graphHashes={name+'.onnx': '2'*64 for name in GATE.GRAPH_NAMES}),
                audio=dict(sha256=GATE.sha(audio), startSample=661500), host={'scope': 'unit fixture'},
                createdAt='2026-09-28T00:00:00+00:00')
            value['sourceBindingsAfter'] = dict(value['sourceBindings'])
            receipt = root / GATE.RECEIPT; receipt.parent.mkdir(parents=True); receipt.write_text(json.dumps(value))
            self.assertEqual(GATE.verify(root), 25.)
            for name in sorted(GATE.SOURCE_PATHS):
                with self.subTest(source=name):
                    path = root / name
                    original = path.read_bytes()
                    try:
                        path.write_text('changed measured input')
                        with self.assertRaisesRegex(ValueError, 'source changed'):
                            GATE.verify(root)
                    finally:
                        path.write_bytes(original)


if __name__ == '__main__':
    unittest.main()
