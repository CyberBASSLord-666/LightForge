"""Falsification tests for the experimental host-observation contract.

The fixture is deliberately separate from the live host. It creates no cgroups,
changes no host settings, and cannot qualify the machine running these tests.
Integration tests may use valid_observations() for real validator inputs.
"""
import copy
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('portable_inference_host_test_subject',
                                            ROOT / 'tools/portable_inference_host.py')
HOST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOST)

MOUNT = '/sys/fs/cgroup'
MOUNTINFO = ('1 0 8:1 / / rw - ext4 /dev/root rw\n'
             '2 1 0:5 / /proc rw,nosuid,nodev,noexec - proc proc rw\n'
             '3 1 0:27 / /sys/fs/cgroup ro,nosuid,nodev,noexec - cgroup2 cgroup rw\n')
PRESSURE = 'some avg10=0.00 avg60=0.00 avg300=0.00 total=100\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=50\n'


class FixtureReader:
    """An injected, mutable fixture, NOT a fake successful live-host probe."""

    def __init__(self, *, leaf='/batch/worker', quota='400000 100000\n', affinity=None):
        self.machine = dict(system='Linux', machine='x86_64')
        self.cpus = list(range(8)) if affinity is None else affinity
        self.links = {'/proc/self/ns/cgroup': 'cgroup:[4026531835]'}
        self.files = {'/proc/self/cgroup': '0::' + leaf + '\n',
                      '/proc/self/mountinfo': MOUNTINFO}
        self.identities = {}
        self.reads = []
        paths = [MOUNT]
        if leaf != '/':
            parts = leaf.strip('/').split('/')
            paths += [MOUNT + '/' + '/'.join(parts[:i]) for i in range(1, len(parts) + 1)]
        for index, path in enumerate(paths):
            self.identities[path] = dict(device='0:27', inode=100 + index, type='directory')
            raw = {'cpuset.cpus.effective': '0-7\n', 'cpuset.mems.effective': '0-1\n',
                   'cgroup.controllers': 'cpu cpuset io memory pids\n',
                   'cgroup.subtree_control': 'cpu cpuset memory\n' if index < len(paths) - 1 else '\n',
                   'cpu.pressure': PRESSURE, 'memory.pressure': PRESSURE}
            if index:
                raw.update({'cpuset.cpus': '\n', 'cpuset.mems': '\n',
                            'cpuset.cpus.partition': 'member\n', 'cgroup.type': 'domain\n',
                            'cpu.max': quota if index == len(paths) - 1 else 'max 100000\n',
                            'memory.max': '8589934592\n', 'memory.high': 'max\n',
                            'cpu.stat': 'usage_usec 1000\nuser_usec 700\nsystem_usec 300\nnr_periods 10\nnr_throttled 2\nthrottled_usec 100\n',
                            'memory.events': 'low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\noom_group_kill 0\n',
                            'memory.stat': 'anon 100\nfile 100\npgscan_direct 0\npgsteal_direct 0\n'})
            self.files.update({path + '/' + key: value for key, value in raw.items()})

    def platform(self):
        return copy.deepcopy(self.machine)

    def affinity(self):
        return self.cpus.copy()

    def read_text(self, path):
        self.reads.append(path)
        if path not in self.files:
            raise FileNotFoundError('Required fixture observation is unavailable: ' + path)
        return self.files[path]

    def readlink(self, path):
        return self.links[path]

    def identity(self, path):
        return copy.deepcopy(self.identities[path])


def valid_observations(**kwargs):
    """Return (controls, before, after) accepted by the real validators.

    Keyword arguments are forwarded to FixtureReader (leaf, quota, affinity).
    All counter totals are nonzero where useful, proving that resource checks
    concern observed deltas, not synthetic default-zero measurements.
    """
    reader = FixtureReader(**kwargs)
    controls = HOST.observe_controls(reader=reader)
    before = HOST.observe_counters(controls, reader=reader)
    after = HOST.observe_counters(controls, reader=reader)
    return controls, before, after


def change_counter(snapshot, ancestor, filename, key, value):
    """Replace one raw counter in-place for integration falsification tests."""
    raw = snapshot['ancestors'][ancestor]['raw'][filename]
    lines = raw.splitlines()
    replaced = False
    for index, line in enumerate(lines):
        if line.split()[0] == key:
            if filename.endswith('.pressure'):
                fields = line.split()
                fields[-1] = 'total=' + str(value)
                lines[index] = ' '.join(fields)
            else:
                lines[index] = key + ' ' + str(value)
            replaced = True
    if not replaced:
        raise KeyError(key)
    snapshot['ancestors'][ancestor]['raw'][filename] = '\n'.join(lines) + '\n'


class PortableControlsTest(unittest.TestCase):
    def test_valid_explicit_unlimited_leaf_and_fractional_capacity(self):
        for quota, expected in [('max 100000\n', 8.0), ('450000 100000\n', 4.5), ('400000 100000\n', 4.0)]:
            with self.subTest(quota=quota):
                controls, _, _ = valid_observations(quota=quota)
                summary = HOST.validate_controls(controls)
                self.assertEqual(summary['effectiveCpuCapacity'], expected)
                self.assertEqual(summary['reservedCpuCapacity'], expected - 3)
                self.assertEqual(summary['childCpuAffinity'], [0, 1, 2])
                self.assertEqual(summary['candidateWorkers'], 4)
                self.assertEqual(controls['ancestors'][-1]['raw']['cpu.max'], quota)
                self.assertEqual(HOST.validate_controls(json.loads(json.dumps(controls))), summary)

    def test_tightest_ancestor_quota_and_affinity_limit_capacity(self):
        reader = FixtureReader(quota='max 100000\n', affinity=[2, 3, 4, 5, 6])
        reader.files[MOUNT + '/batch/cpu.max'] = '425000 100000\n'
        controls = HOST.observe_controls(reader=reader)
        self.assertEqual(controls['effectiveCpuCapacity'], 4.25)
        self.assertEqual(controls['childCpuAffinity'], [2, 3, 4])
        reader.files[MOUNT + '/batch/cpu.max'] = '800000 100000\n'
        self.assertEqual(HOST.observe_controls(reader=reader)['effectiveCpuCapacity'], 5)
        reader.files[MOUNT + '/batch/cpu.max'] = '399999 100000\n'
        with self.assertRaisesRegex(ValueError, 'four effective CPUs'):
            HOST.observe_controls(reader=reader)

    def test_root_exemption_is_explicit_and_process_must_not_live_at_root(self):
        reader = FixtureReader()
        controls = HOST.observe_controls(reader=reader)
        before = HOST.observe_counters(controls, reader=reader)
        summary = HOST.validate_resource_pair(before, copy.deepcopy(before), 1_000_000_000, controls)
        self.assertEqual(controls['globalRootProof']['namespaceInode'], 4026531835)
        self.assertEqual(controls['ancestors'][0]['limitObservation'], 'notApplicableGlobalRoot')
        self.assertEqual(before['ancestors'][0]['resourceCounterObservation'], 'notApplicableGlobalRoot')
        self.assertIsNone(summary['ancestors'][0]['throttleToWallRatio'])
        self.assertEqual(summary['resourceCounterScope'], 'observed-non-root-ancestry')
        self.assertNotIn(MOUNT + '/cpu.max', reader.reads)
        self.assertNotIn(MOUNT + '/memory.max', reader.reads)
        self.assertIn(MOUNT + '/memory.pressure', reader.reads)
        self.assertNotIn(MOUNT + '/cpu.stat', reader.reads)
        with self.assertRaisesRegex(ValueError, 'must be in a non-root cgroup'):
            HOST.observe_controls(reader=FixtureReader(leaf='/'))

    def test_every_missing_nonroot_control_rejects(self):
        for name in HOST._NONROOT_CONTROLS:
            for parent in ('/batch', '/batch/worker'):
                with self.subTest(name=name, parent=parent):
                    reader = FixtureReader()
                    del reader.files[MOUNT + parent + '/' + name]
                    with self.assertRaises((ValueError, OSError)):
                        HOST.observe_controls(reader=reader)

    def test_namespace_hidden_mount_and_ambiguous_overlay_rejected(self):
        transforms = [
            lambda r: r.links.update({'/proc/self/ns/cgroup': 'cgroup:[4026532500]'}),
            lambda r: r.links.update({'/proc/self/ns/cgroup': 'cgroup:[04026531835]'}),
            lambda r: r.files.update({'/proc/self/mountinfo': MOUNTINFO.replace('0:27 / /sys', '0:27 /hidden /sys')}),
            lambda r: r.files.update({'/proc/self/mountinfo': MOUNTINFO + '4 1 0:27 / /other rw - cgroup2 cgroup rw\n'}),
            lambda r: r.files.update({'/proc/self/mountinfo': MOUNTINFO + '4 3 0:55 / /sys/fs/cgroup/batch rw - tmpfs tmpfs rw\n'}),
            lambda r: r.files.update({'/proc/self/mountinfo': MOUNTINFO + '4 3 0:27 /batch /sys/fs/cgroup/batch rw - cgroup2 cgroup rw\n'}),
            lambda r: r.files.update({'/proc/self/mountinfo': MOUNTINFO + '4 1 0:55 / /proc/self rw - tmpfs tmpfs rw\n'}),
            lambda r: r.files.update({'/proc/self/mountinfo': MOUNTINFO + '4 1 0:28 / /legacy rw - cgroup cgroup rw\n'}),
            lambda r: r.files.update({'/proc/self/mountinfo': MOUNTINFO.replace('cgroup rw', 'cgroup rw,memory_localevents')}),
            lambda r: r.files.update({'/proc/self/cgroup': '0::/batch/../escape\n'}),
            lambda r: r.files.update({'/proc/self/cgroup': '0:://batch/worker\n'}),
            lambda r: r.files.update({'/proc/self/cgroup': '0::/batch/worker (deleted)\n'}),
            lambda r: r.files.update({'/proc/self/cgroup': '0::/batch/worker\n1:cpu:/old\n'}),
        ]
        for transform in transforms:
            with self.subTest(transform=transform):
                reader = FixtureReader(); transform(reader)
                with self.assertRaises(ValueError):
                    HOST.observe_controls(reader=reader)

    def test_malformed_raw_quota_or_limits_never_infer_unlimited(self):
        for quota in ('', '\n', 'max', 'max 0', 'MAX 100000', '0 100000', '-1 100000',
                      '400000 0', '400000 999', '400000 1000001', '400000 100000 extra',
                      '4.0 1', 'NaN 100000', '400000 0100000', '1e9 100000'):
            with self.subTest(quota=quota):
                with self.assertRaises(ValueError):
                    HOST.observe_controls(reader=FixtureReader(quota=quota))
        for name in ('memory.max', 'memory.high'):
            for value in ('', 'NaN', '-1', 'infinity', '1 2', 'max 0'):
                with self.subTest(name=name, value=value):
                    reader = FixtureReader(); reader.files[MOUNT + '/batch/' + name] = value
                    with self.assertRaises(ValueError): HOST.observe_controls(reader=reader)

    def test_invalid_cpuset_affinity_platform_or_identity_rejected(self):
        transforms = [
            lambda r: setattr(r, 'cpus', [0, 1, 2]),
            lambda r: setattr(r, 'cpus', [0, 1, 2, True]),
            lambda r: setattr(r, 'cpus', [0, 1, 1, 2, 3]),
            lambda r: setattr(r, 'cpus', [0, 1, 2, 8]),
            lambda r: r.machine.update(system='Darwin'),
            lambda r: r.machine.update(machine='aarch64'),
            lambda r: r.identities[MOUNT + '/batch'].update(device='0:55'),
            lambda r: r.identities[MOUNT + '/batch'].update(type='symlink'),
            lambda r: r.identities[MOUNT + '/batch'].update(inode=100),
            lambda r: r.files.update({MOUNT + '/batch/cpuset.cpus.effective': '0-3,3-7\n'}),
            lambda r: r.files.update({MOUNT + '/batch/cpuset.cpus.effective': '7-0\n'}),
            lambda r: r.files.update({MOUNT + '/batch/cpuset.cpus.effective': '\n'}),
            lambda r: r.files.update({MOUNT + '/batch/cpuset.mems.effective': '\n'}),
            lambda r: r.files.update({MOUNT + '/batch/cpuset.cpus.partition': 'root\n'}),
            lambda r: r.files.update({MOUNT + '/batch/cgroup.type': 'threaded\n'}),
            lambda r: r.files.update({MOUNT + '/batch/cgroup.subtree_control': 'cpu cpuset\n'}),
        ]
        for transform in transforms:
            with self.subTest(transform=transform):
                reader = FixtureReader(); transform(reader)
                with self.assertRaises(ValueError): HOST.observe_controls(reader=reader)

    def test_missing_or_fabricated_derived_fields_cannot_bypass_replay(self):
        controls, _, _ = valid_observations()
        transforms = [
            lambda c: c.update(effectiveCpuCapacity=8),
            lambda c: c.update(reservedCpuCapacity=2),
            lambda c: c.update(candidateWorkers=True),
            lambda c: c.update(expectedAvailableProcessors=4),
            lambda c: c.update(childCpuAffinity=[1, 2, 3]),
            lambda c: c.update(effectiveCpuCapacity=float('nan')),
            lambda c: c.update(effectiveCpuCapacity=10**1000),
            lambda c: c['ancestors'][0]['identity'].update(inode=10**1000),
            lambda c: c['ancestors'][1]['raw'].update({'cgroup.type': None}),
            lambda c: c['ancestors'][1]['raw'].update({'cpuset.cpus.partition': False}),
            lambda c: c.pop('namespace'),
            lambda c: c.update(globalRootProof={}),
            lambda c: c['ancestors'].pop(1),
            lambda c: c['ancestors'].reverse(),
            lambda c: c['ancestors'][1].update(isGlobalRoot=True),
            lambda c: c['ancestors'][1]['raw'].pop('cpu.max'),
            lambda c: c['ancestors'][1].update(path=MOUNT + '/../batch'),
        ]
        for transform in transforms:
            with self.subTest(transform=transform):
                value = copy.deepcopy(controls); transform(value)
                with self.assertRaises(ValueError): HOST.validate_controls(value)

    def test_control_observation_is_stable_and_read_only(self):
        reader = FixtureReader()
        original = copy.deepcopy(reader.files)
        controls = HOST.observe_controls(reader=reader)
        HOST.observe_counters(controls, reader=reader)
        self.assertEqual(original, reader.files)
        class ChangingReader(FixtureReader):
            count = 0
            def affinity(self):
                self.count += 1
                return list(range(8 if self.count == 1 else 7))
        with self.assertRaisesRegex(ValueError, 'changed'):
            HOST.observe_controls(reader=ChangingReader())
        class ChangingIdentity(FixtureReader):
            count = 0
            def identity(self, path):
                result = super().identity(path)
                self.count += 1
                result['inode'] += self.count
                return result
        with self.assertRaisesRegex(ValueError, 'directory changed'):
            HOST.observe_controls(reader=ChangingIdentity())


class PortableResourcesTest(unittest.TestCase):
    def setUp(self):
        self.controls, self.before, self.after = valid_observations()

    def validate(self):
        return HOST.validate_resource_pair(self.before, self.after, 1_000_000_000, self.controls)

    def test_nonzero_history_and_cpu_psi_are_valid_monotonic_observations(self):
        change_counter(self.after, 2, 'cpu.pressure', 'some', 20000)
        change_counter(self.after, 2, 'cpu.pressure', 'full', 10000)
        change_counter(self.after, 2, 'cpu.stat', 'nr_throttled', 3)
        change_counter(self.after, 2, 'cpu.stat', 'throttled_usec', 50100)
        summary = self.validate()
        self.assertEqual(summary['maxThrottleToWallRatio'], 0.05)
        self.assertEqual(summary['ancestors'][2]['deltas']['cpu.pressure']['some'], 19900)
        self.assertTrue(summary['noMemoryPressure'])
        self.assertEqual(summary, self.validate())
        json.dumps(summary, allow_nan=False)

    def test_throttle_threshold_is_per_ancestor_and_exact(self):
        for index in (1, 2):
            with self.subTest(index=index):
                self.setUp()
                change_counter(self.after, index, 'cpu.stat', 'throttled_usec', 50101)
                with self.assertRaisesRegex(ValueError, 'throttling exceeds'):
                    self.validate()

    def test_cumulative_ancestor_throttle_cannot_hide_below_individual_thresholds(self):
        change_counter(self.after, 1, 'cpu.stat', 'throttled_usec', 25100)
        change_counter(self.after, 2, 'cpu.stat', 'throttled_usec', 25100)
        summary = self.validate()
        self.assertEqual(summary['maxThrottleToWallRatio'], 0.025)
        self.assertEqual(summary['cumulativeThrottleToWallRatio'], 0.05)
        change_counter(self.after, 2, 'cpu.stat', 'throttled_usec', 25101)
        with self.assertRaisesRegex(ValueError, 'Cumulative ancestor'):
            self.validate()

    def test_each_memory_event_and_direct_reclaim_is_rejected_everywhere(self):
        for index in (1, 2):
            for group, keys in [('memory.events', ('oom', 'oom_kill', 'max', 'high')),
                                ('memory.stat', ('pgscan_direct', 'pgsteal_direct'))]:
                for key in keys:
                    with self.subTest(index=index, group=group, key=key):
                        self.setUp(); change_counter(self.after, index, group, key, 1)
                        with self.assertRaises(ValueError): self.validate()

    def test_root_and_nonroot_memory_pressure_rejected(self):
        for index in (0, 1, 2):
            for key, value in [('some', 101), ('full', 51)]:
                with self.subTest(index=index, key=key):
                    self.setUp(); change_counter(self.after, index, 'memory.pressure', key, value)
                    with self.assertRaisesRegex(ValueError, 'Memory PSI increased'): self.validate()

    def test_nonmonotonic_cumulative_counters_rejected_but_memory_gauges_may_fall(self):
        for index in (0, 1, 2):
            for key in ('some', 'full'):
                with self.subTest(index=index, key=key):
                    self.setUp(); change_counter(self.after, index, 'cpu.pressure', key, 49)
                    with self.assertRaises(ValueError): self.validate()
        for key in ('throttled_usec', 'nr_throttled'):
            self.setUp(); change_counter(self.after, 1, 'cpu.stat', key, 0)
            with self.assertRaisesRegex(ValueError, 'Nonmonotonic'): self.validate()
        self.setUp(); change_counter(self.after, 2, 'memory.stat', 'anon', 99)
        self.assertTrue(self.validate()['noDirectReclaim'])

    def test_all_counter_files_and_required_fields_must_be_observed(self):
        for index in (0, 1, 2):
            for name in tuple(self.before['ancestors'][index]['raw']):
                with self.subTest(index=index, name=name):
                    self.setUp(); del self.after['ancestors'][index]['raw'][name]
                    with self.assertRaises(ValueError): self.validate()
        for name, keys in [('cpu.stat', ('throttled_usec', 'nr_throttled')),
                           ('memory.events', ('oom', 'oom_kill', 'max', 'high')),
                           ('memory.stat', ('pgscan_direct', 'pgsteal_direct'))]:
            for key in keys:
                with self.subTest(name=name, key=key):
                    self.setUp()
                    raw = self.after['ancestors'][2]['raw'][name]
                    self.after['ancestors'][2]['raw'][name] = '\n'.join(l for l in raw.splitlines() if not l.startswith(key + ' '))
                    with self.assertRaises(ValueError): self.validate()

    def test_missing_root_pressure_is_unsupported_not_zero(self):
        reader = FixtureReader(); controls = HOST.observe_controls(reader=reader)
        del reader.files[MOUNT + '/cpu.pressure']
        with self.assertRaises(FileNotFoundError): HOST.observe_counters(controls, reader=reader)

    def test_malformed_duplicate_or_nan_counters_rejected(self):
        replacements = [('cpu.stat', 'throttled_usec -1\nnr_throttled 0\n'),
                        ('cpu.stat', 'throttled_usec 0\nnr_throttled 0\nthrottled_usec 0\n'),
                        ('cpu.stat', 'throttled_usec 1.0\nnr_throttled 0\n'),
                        ('memory.stat', 'pgscan_direct 0\npgsteal_direct NaN\n'),
                        ('cpu.pressure', PRESSURE.replace('0.00', 'nan', 1)),
                        ('cpu.pressure', PRESSURE.replace('total=100', 'total=-1')),
                        ('cpu.pressure', PRESSURE.replace('total=100', 'total=100.0')),
                        ('cpu.pressure', PRESSURE.splitlines()[0]),
                        ('cpu.pressure', PRESSURE + PRESSURE),
                        ('cpu.pressure', PRESSURE.replace('avg60=0.00', 'avg10=0.00'))]
        for name, raw in replacements:
            with self.subTest(name=name, raw=raw):
                self.setUp(); self.after['ancestors'][2]['raw'][name] = raw
                with self.assertRaises(ValueError): self.validate()

    def test_snapshots_bind_full_controls_and_every_ancestor(self):
        transforms = [lambda c: c.update(controlsSha256='0' * 64),
                      lambda c: c.pop('observedControls'),
                      lambda c: c['observedControls'].update(parentCpuAffinity=list(range(7))),
                      lambda c: c['observedControls']['ancestors'][1]['raw'].update({'memory.high': '1\n'}),
                      lambda c: c['observedControls']['ancestors'][1]['raw'].update({'cpu.max': '500000 100000\n'}),
                      lambda c: c['ancestors'].pop(1),
                      lambda c: c['ancestors'].reverse(),
                      lambda c: c['ancestors'][1]['identity'].update(inode=999),
                      lambda c: c['ancestors'][1]['identity'].update(inode=101.0)]
        for transform in transforms:
            with self.subTest(transform=transform):
                self.setUp(); transform(self.after)
                with self.assertRaises(ValueError): self.validate()

    def test_live_counter_capture_rejects_changed_settings(self):
        for path, value in [(MOUNT + '/batch/cpu.max', '500000 100000\n'),
                            (MOUNT + '/batch/memory.high', '100\n'),
                            (MOUNT + '/batch/cpuset.cpus', '0-7\n')]:
            with self.subTest(path=path):
                reader = FixtureReader(); controls = HOST.observe_controls(reader=reader)
                reader.files[path] = value
                with self.assertRaisesRegex(ValueError, 'changed'):
                    HOST.observe_counters(controls, reader=reader)
        class ChangingCounterReader(FixtureReader):
            def read_text(self, path):
                value = super().read_text(path)
                if path.endswith('/cpu.pressure'):
                    self.files[MOUNT + '/batch/memory.high'] = '100\n'
                return value
        reader = ChangingCounterReader(); controls = HOST.observe_controls(reader=reader)
        with self.assertRaisesRegex(ValueError, 'changed while counters'):
            HOST.observe_counters(controls, reader=reader)

    def test_bad_wall_time_rejected(self):
        for value in (0, -1, True, '1000', 1.0, float('nan')):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    HOST.validate_resource_pair(self.before, self.after, value, self.controls)


class LinuxReaderTest(unittest.TestCase):
    def test_descriptor_reader_rejects_symlink_files_and_parent_components(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'real').mkdir(); (root / 'real' / 'counter').write_text('42\n')
            (root / 'link').symlink_to(root / 'real', target_is_directory=True)
            (root / 'counter').symlink_to(root / 'real' / 'counter')
            reader = HOST.LinuxReader()
            self.assertEqual(reader.read_text(str(root / 'real' / 'counter')), '42\n')
            for path in (root / 'link' / 'counter', root / 'counter'):
                with self.subTest(path=path):
                    with self.assertRaises(OSError): reader.read_text(str(path))
            with self.assertRaises(ValueError): reader.read_text(str(root) + '/../escape')
            self.assertEqual(reader.identity(str(root))['type'], 'directory')

    def test_proc_self_is_verified_by_descriptor_relative_readlink_before_substitution(self):
        reader = HOST.LinuxReader()
        original_open = os.open
        flags_seen = []
        links_seen = []
        def tracked_open(path, flags, *args, **kwargs):
            flags_seen.append(flags)
            return original_open(path, flags, *args, **kwargs)
        def matching_readlink(path, *, dir_fd):
            links_seen.append((path, dir_fd))
            self.assertGreaterEqual(dir_fd, 0)
            os.fstat(dir_fd)  # The directory descriptor is live for the read.
            return str(os.getpid())
        with mock.patch.object(HOST.os, 'open', tracked_open), \
                mock.patch.object(HOST.os, 'readlink', matching_readlink):
            self.assertEqual(reader._physical_path('/proc/self/cgroup'),
                             '/proc/' + str(os.getpid()) + '/cgroup')
        self.assertEqual(len(links_seen), 1)
        self.assertEqual(links_seen[0][0], 'self')
        self.assertTrue(flags_seen)
        self.assertTrue(all((flags & os.O_ACCMODE) == os.O_RDONLY for flags in flags_seen))
        self.assertTrue(all(flags & os.O_NOFOLLOW and flags & os.O_DIRECTORY for flags in flags_seen))
        with self.assertRaises(OSError): os.fstat(links_seen[0][1])

    def test_proc_self_namespace_mismatch_rejects_before_opening_process_files(self):
        for method, path in (('read_text', '/proc/self/cgroup'),
                             ('read_text', '/proc/self/mountinfo'),
                             ('readlink', '/proc/self/ns/cgroup')):
            with self.subTest(method=method, path=path):
                reader = HOST.LinuxReader()
                with mock.patch.object(HOST.os, 'readlink', return_value=str(os.getpid() + 1)), \
                        mock.patch.object(reader, '_open', wraps=reader._open) as opened:
                    with self.assertRaisesRegex(ValueError, 'PID namespace does not match'):
                        getattr(reader, method)(path)
                self.assertFalse(any('/proc/' + str(os.getpid()) + '/' in str(call)
                                     for call in opened.call_args_list))

    def test_proc_self_malformed_targets_fail_with_safe_diagnostic_category(self):
        for target in ('', '0', '-1', '+1', '01', '1/../private', '/private/123',
                       '123\n', ' 123', '123 ', '１２３', None):
            with self.subTest(target=target):
                with mock.patch.object(HOST.os, 'readlink', return_value=target):
                    with self.assertRaisesRegex(ValueError, 'self PID identity is malformed') as error:
                        HOST.LinuxReader()._physical_path('/proc/self/cgroup')
                self.assertEqual(HOST._diagnostic_reason(error.exception),
                                 'Procfs self PID identity is malformed')
        with mock.patch.object(HOST.os, 'readlink', side_effect=OSError('SECRET_PRIVATE_PATH')):
            with self.assertRaisesRegex(ValueError, 'self PID identity is unavailable') as error:
                HOST.LinuxReader()._physical_path('/proc/self/cgroup')
        self.assertEqual(HOST._diagnostic_reason(error.exception), 'Procfs self PID identity is unavailable')
        self.assertNotIn('SECRET', HOST._diagnostic_reason(error.exception))

    def test_proc_self_mismatch_is_an_ineligible_safe_diagnostic(self):
        with mock.patch.object(HOST.os, 'readlink', return_value=str(os.getpid() + 1)):
            record = HOST.diagnose()
        self.assertFalse(record['eligible'])
        self.assertEqual(record['reason'], 'Procfs PID namespace does not match the current process')
        self.assertNotIn('verifiedHostControls', record)
        self.assertNotIn('observedCounters', record)

    def test_only_read_only_descriptors_are_used(self):
        original_open = os.open
        flags_seen = []
        def tracked_open(path, flags, *args, **kwargs):
            flags_seen.append(flags)
            return original_open(path, flags, *args, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test'; path.write_text('value')
            with mock.patch.object(HOST.os, 'open', tracked_open):
                HOST.LinuxReader().read_text(str(path))
            self.assertTrue(flags_seen)
            self.assertTrue(all((flags & os.O_ACCMODE) == os.O_RDONLY for flags in flags_seen))
            self.assertTrue(all(flags & os.O_NOFOLLOW for flags in flags_seen))


class DiagnosticCliTest(unittest.TestCase):
    def test_diagnostic_is_eligible_only_and_omits_full_mountinfo(self):
        reader = FixtureReader()
        # A relevant proof sees this unrelated mount, but output must not dump
        # its potentially sensitive options or unrelated filesystem details.
        reader.files['/proc/self/mountinfo'] += '4 1 0:28 / /unrelated rw - tmpfs tmpfs rw,secret=DO_NOT_DUMP\n'
        record = HOST.diagnose(reader=reader)
        self.assertTrue(record['eligible'])
        self.assertFalse(record['qualificationEstablished'])
        self.assertFalse(record['releaseAdmissible'])
        self.assertFalse(record['fullQualificationEvidence'])
        self.assertEqual(record['observations']['parentCpuAffinity'], list(range(8)))
        self.assertIn('observedCounters', record)
        text = json.dumps(record)
        self.assertNotIn('DO_NOT_DUMP', text)
        self.assertNotIn('/unrelated', text)
        self.assertNotIn('procMountinfo"', text)
        self.assertLess(len(text.encode()), 1024 * 1024)

    def test_hidden_namespace_and_missing_counters_are_explicitly_ineligible(self):
        reader = FixtureReader()
        reader.links['/proc/self/ns/cgroup'] = 'cgroup:[999999]'
        record = HOST.diagnose(reader=reader)
        self.assertFalse(record['eligible'])
        self.assertIn('hidden ancestors', record['reason'])
        self.assertEqual(record['observations']['parentCpuAffinity'], list(range(8)))
        self.assertNotIn('verifiedHostControls', record)
        reader = FixtureReader()
        del reader.files[MOUNT + '/batch/worker/cpu.stat']
        record = HOST.diagnose(reader=reader)
        self.assertFalse(record['eligible'])
        self.assertIn('cpu.stat', record['reason'])
        self.assertNotIn('observedCounters', record)

    def test_malformed_unrelated_mount_errors_do_not_disclose_its_path(self):
        reader = FixtureReader()
        reader.files['/proc/self/mountinfo'] += '4 1 0:28 / /private\\134SENSITIVE_PATH rw - tmpfs tmpfs rw\n'
        record = HOST.diagnose(reader=reader)
        self.assertFalse(record['eligible'])
        self.assertTrue(record['observationErrors'])
        self.assertNotIn('SENSITIVE_PATH', json.dumps(record))
        self.assertIn('unsafe or noncanonical', record['reason'])

    def assert_failure(self, record, code, stage, field=None):
        self.assertFalse(record['eligible'])
        self.assertFalse(record['qualificationEstablished'])
        self.assertFalse(record['releaseAdmissible'])
        self.assertFalse(record['fullQualificationEvidence'])
        self.assertEqual(record['reasonCode'], code)
        self.assertEqual(record['stage'], stage)
        self.assertNotIn('verifiedHostControls', record)
        self.assertNotIn('observedCounters', record)
        self.assertLess(len(json.dumps(record).encode()), 1024 * 1024)
        if field is not None:
            self.assertEqual(record['field'], field)

    def test_missing_interfaces_are_distinguished_by_stage_and_allowed_field(self):
        for name, stage in [('cpu.max', 'controlObservation'),
                            ('cpuset.cpus.effective', 'controlObservation'),
                            ('memory.high', 'controlObservation'),
                            ('cpu.stat', 'counterObservation'),
                            ('memory.events', 'counterObservation'),
                            ('memory.pressure', 'counterObservation')]:
            with self.subTest(name=name):
                reader = FixtureReader()
                del reader.files[MOUNT + '/batch/worker/' + name]
                record = HOST.diagnose(reader=reader)
                self.assert_failure(record, 'missing_interface', stage, name)
                self.assertNotIn('errno', record)  # The fixture has no OS errno.
                self.assertNotIn('/batch/worker/', record['reason'])

    def test_unreadable_interface_errno_is_safe_and_not_a_missing_zero(self):
        class UnreadableFixture(FixtureReader):
            def read_text(self, path):
                if path.endswith('/memory.high'):
                    raise PermissionError(13, 'SECRET_OS_TEXT', '/SECRET_DIR/memory.high')
                return super().read_text(path)
        record = HOST.diagnose(reader=UnreadableFixture())
        self.assert_failure(record, 'unreadable_interface', 'controlObservation', 'memory.high')
        self.assertEqual(record['errno'], 13)
        self.assertNotIn('SECRET', json.dumps(record))
        # An arbitrary failed directory is not echoed as though it were a field.
        failure = HOST._diagnostic_failure(OSError(5, 'SECRET_IO', '/SECRET_DIR/unknown'), 'counterObservation')
        self.assertEqual(failure['reasonCode'], 'unreadable_interface')
        self.assertEqual(failure['errno'], 5)
        self.assertNotIn('field', failure)
        self.assertNotIn('SECRET', json.dumps(failure))

    def test_malformed_constraints_have_precise_safe_fields(self):
        for name, raw in [('cpu.max', 'max'), ('cpu.max', '400000 0'),
                          ('memory.max', 'not-a-limit'), ('memory.high', '-1'),
                          ('cpuset.cpus.effective', ''), ('cpuset.mems.effective', '1-0'),
                          ('cgroup.controllers', 'cpu cpu'), ('cgroup.type', '')]:
            with self.subTest(name=name, raw=raw):
                reader = FixtureReader(); reader.files[MOUNT + '/batch/worker/' + name] = raw
                self.assert_failure(HOST.diagnose(reader=reader), 'malformed_constraint',
                                    'controlObservation', name)

    def test_disabled_and_unavailable_controllers_are_not_inferred_from_missing_files(self):
        reader = FixtureReader()
        reader.files[MOUNT + '/batch/cgroup.subtree_control'] = 'cpu cpuset\n'
        self.assert_failure(HOST.diagnose(reader=reader), 'disabled_controller', 'controlObservation')
        reader = FixtureReader()
        reader.files[MOUNT + '/batch/cgroup.controllers'] = 'cpuset memory\n'
        self.assert_failure(HOST.diagnose(reader=reader), 'unavailable_controller', 'controlObservation')
        reader = FixtureReader()
        del reader.files[MOUNT + '/batch/memory.max']
        self.assert_failure(HOST.diagnose(reader=reader), 'missing_interface', 'controlObservation', 'memory.max')

    def test_capacity_failure_does_not_claim_which_capacity_limit_was_responsible(self):
        for reader in (FixtureReader(affinity=[0, 1, 2]), FixtureReader(quota='399999 100000\n')):
            with self.subTest(affinity=reader.cpus):
                record = HOST.diagnose(reader=reader)
                self.assert_failure(record, 'insufficient_cpu_capacity', 'controlObservation')
                self.assertNotIn('field', record)
                self.assertNotIn('cpu.max', record['reason'])

    def test_missing_required_counters_and_malformed_counters_are_distinct(self):
        for name, required in [('cpu.stat', 'nr_throttled'), ('memory.events', 'high'),
                               ('memory.stat', 'pgscan_direct')]:
            with self.subTest(name=name):
                reader = FixtureReader(); path = MOUNT + '/batch/worker/' + name
                reader.files[path] = '\n'.join(line for line in reader.files[path].splitlines()
                                                if not line.startswith(required + ' ')) + '\n'
                record = HOST.diagnose(reader=reader)
                self.assert_failure(record, 'missing_required_counter', 'counterObservation', name)
                self.assertIn('missing values are not zero', record['reason'])
        reader = FixtureReader()
        reader.files[MOUNT + '/batch/worker/cpu.stat'] = 'nr_throttled 0\nthrottled_usec NaN\n'
        self.assert_failure(HOST.diagnose(reader=reader), 'malformed_counter',
                            'counterObservation', 'cpu.stat.throttled_usec')

    def test_invalid_psi_is_explicit_and_no_pressure_is_synthesized(self):
        for name, raw in [('cpu.pressure', PRESSURE.splitlines()[0]),
                          ('memory.pressure', PRESSURE.replace('total=100', 'total=NaN')),
                          ('memory.pressure', '')]:
            with self.subTest(name=name, raw=raw):
                reader = FixtureReader(); reader.files[MOUNT + '/batch/worker/' + name] = raw
                record = HOST.diagnose(reader=reader)
                self.assert_failure(record, 'invalid_psi', 'counterObservation')
                self.assertTrue(record['field'].startswith(name))

    def test_changed_identity_control_and_final_binding_stages_are_preserved(self):
        class ChangingDirectory(FixtureReader):
            identity_calls = 0
            def identity(self, path):
                identity = super().identity(path)
                self.identity_calls += 1
                identity['inode'] += self.identity_calls
                return identity
        self.assert_failure(HOST.diagnose(reader=ChangingDirectory()),
                            'changed_identity', 'controlObservation')
        class ChangingCounterIdentity(FixtureReader):
            def read_text(self, path):
                raw = super().read_text(path)
                if path.endswith('/cpu.pressure'):
                    self.identities[path.rsplit('/', 1)[0]]['inode'] += 10
                return raw
        self.assert_failure(HOST.diagnose(reader=ChangingCounterIdentity()),
                            'changed_identity', 'counterObservation')
        class ChangingControls(FixtureReader):
            affinity_calls = 0
            def affinity(self):
                self.affinity_calls += 1
                return list(range(8 if self.affinity_calls < 3 else 7))
        self.assert_failure(HOST.diagnose(reader=ChangingControls()),
                            'changed_controls', 'controlObservation')
        class ChangingInitialBinding(FixtureReader):
            affinity_calls = 0
            def affinity(self):
                self.affinity_calls += 1
                return list(range(8 if self.affinity_calls == 1 else 7))
        self.assert_failure(HOST.diagnose(reader=ChangingInitialBinding()),
                            'changed_identity', 'finalBinding')

    def test_basic_observation_errors_get_codes_without_leaking_bad_mount_text(self):
        reader = FixtureReader()
        reader.files['/proc/self/mountinfo'] += 'malformed SECRET_MOUNT_OPTIONS /SECRET_PATH\n'
        record = HOST.diagnose(reader=reader)
        self.assert_failure(record, 'malformed_mount_topology', 'controlObservation')
        self.assertEqual(len(record['observationErrors']), 1)
        failure = record['observationErrors'][0]
        self.assertEqual(failure['observation'], 'cgroup2Mounts')
        self.assertEqual(failure['reasonCode'], 'malformed_mount_topology')
        self.assertEqual(failure['stage'], 'basicObservations')
        self.assertNotIn('SECRET', json.dumps(record))

    def test_same_basic_host_observations_do_not_prove_the_unreported_cause(self):
        # Deliberately share the visible four-CPU/global-namespace topology.
        # These synthetic cases have different failures; none diagnose a real run.
        records = []
        for name, raw in [('cpu.max', 'max'), ('memory.high', 'invalid')]:
            reader = FixtureReader(leaf='/system.slice/hosted-compute-agent.service', affinity=[0, 1, 2, 3])
            reader.files[MOUNT + '/system.slice/hosted-compute-agent.service/' + name] = raw
            records.append(HOST.diagnose(reader=reader))
        self.assertEqual(records[0]['observations'], records[1]['observations'])
        self.assertEqual(records[0]['field'], 'cpu.max')
        self.assertEqual(records[1]['field'], 'memory.high')
        self.assertTrue(all(not record['eligible'] for record in records))

    def test_unknown_failures_remain_generic_and_exception_contents_are_not_echoed(self):
        for error in (ValueError('SECRET_UNKNOWN'), ValueError('SECRET_UNKNOWN cpu.stat'),
                      OSError(123456789, 'SECRET_OS', '/SECRET_DIR/unknown')):
            failure = HOST._diagnostic_failure(error, 'controlObservation')
            self.assertNotIn('SECRET', json.dumps(failure))
            self.assertNotIn('123456789', json.dumps(failure))
            if not isinstance(error, OSError):
                self.assertEqual(failure['reasonCode'], 'unclassified_validation_failure')
        reader = FixtureReader()
        with mock.patch.object(HOST, 'observe_controls', side_effect=ValueError('SECRET_UNKNOWN')):
            record = HOST.diagnose(reader=reader)
        self.assert_failure(record, 'unclassified_validation_failure', 'controlObservation')
        self.assertNotIn('SECRET', json.dumps(record))

    def test_output_limit_keeps_failure_code_and_never_admits_truncated_evidence(self):
        reader = FixtureReader()
        # A large but supported raw counter file makes the resulting diagnostic
        # projection exceed one MiB without modifying any validation behavior.
        reader.files[MOUNT + '/batch/worker/memory.stat'] += ''.join(
            'fixture_gauge_' + str(index) + ' 0\n' for index in range(50000))
        record = HOST.diagnose(reader=reader)
        self.assert_failure(record, 'diagnostic_output_too_large', 'outputBounding')
        self.assertLess(len(json.dumps(record).encode()), 2048)

    def test_cli_emits_only_json_and_sets_eligibility_exit_status(self):
        for eligible in (False, True):
            record = dict(eligible=eligible, qualificationEstablished=False, releaseAdmissible=False)
            stream = io.StringIO()
            with mock.patch.object(HOST, 'diagnose', return_value=record), \
                    mock.patch('sys.argv', ['portable_inference_host.py']), contextlib.redirect_stdout(stream):
                self.assertEqual(HOST.main(), 0 if eligible else 2)
            self.assertEqual(json.loads(stream.getvalue()), record)


if __name__ == '__main__':
    unittest.main()
