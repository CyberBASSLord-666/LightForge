#!/usr/bin/env python3
"""Fail-closed, read-only host observations for an EXPERIMENTAL portable lane.

This is not production qualification and does not change affinity, cgroups,
mounts, or any host setting. Only benchmark children may subsequently be pinned
by the caller. Four candidate workers must share exactly three allowed CPUs,
with at least one additional CPU-equivalent of observed capacity in reserve.

A receipt is evidence, not an attestation against a malicious kernel. All raw
observations are retained and replayed; missing observations never mean zero.
The root exemption follows the cgroup-v2 kernel interface, not file absence:
https://docs.kernel.org/admin-guide/cgroup-v2.html
The initial cgroup namespace inode is PROC_CGROUP_INIT_INO:
https://github.com/torvalds/linux/blob/v6.6/include/linux/proc_ns.h
"""

import argparse
import hashlib
import json
import math
import os
import platform
import posixpath
import re
import stat
from fractions import Fraction


CONTROLS_SCHEMA = 'lightforge.experimental-portable-host-controls.v1'
COUNTERS_SCHEMA = 'lightforge.experimental-portable-host-counters.v1'
SCOPE = 'experimental-read-only-host-observations-not-production-admitted'
INITIAL_CGROUP_NAMESPACE_INODE = 4026531835
CHILD_CPU_COUNT = 3
CANDIDATE_WORKERS = 4
MAX_THROTTLE_TO_WALL_RATIO = 0.05
_MAX_TEXT = 4 * 1024 * 1024
_MAX_CPU = 1048575
_ROOT_CONTROLS = ('cpuset.cpus.effective', 'cpuset.mems.effective',
                  'cgroup.controllers', 'cgroup.subtree_control')
_NONROOT_CONTROLS = _ROOT_CONTROLS + (
    'cpuset.cpus', 'cpuset.mems', 'cpuset.cpus.partition', 'cgroup.type',
    'cpu.max', 'memory.max', 'memory.high')
_ROOT_COUNTERS = ('cpu.pressure', 'memory.pressure')
_NONROOT_COUNTERS = _ROOT_COUNTERS + ('cpu.stat', 'memory.events', 'memory.stat')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _keys(value, expected, name):
    _require(type(value) is dict and set(value) == set(expected),
             'Malformed or missing fields in ' + name)


def _text(value, name):
    _require(type(value) is str and 0 < len(value) <= _MAX_TEXT and '\x00' not in value,
             'Malformed or missing ' + name)
    return value


def _integer(value, name, minimum=0):
    _require(type(value) is int and minimum <= value <= 2**64 - 1, 'Invalid integer ' + name)
    return value


def _uint(text, name):
    _require(type(text) is str and re.fullmatch(r'0|[1-9][0-9]*', text) is not None,
             'Malformed unsigned integer ' + name)
    # Bound hostile receipt numbers while allowing all kernel u64 counters.
    _require(len(text) <= 20 and int(text) <= 2**64 - 1, 'Out-of-range ' + name)
    return int(text)


def _path(value):
    _text(value, 'absolute path')
    _require(value.startswith('/') and not value.startswith('//')
             and posixpath.normpath(value) == value
             and '\\' not in value and all(ord(c) >= 32 and ord(c) != 127 for c in value)
             and not value.endswith(' (deleted)'), 'Unsafe or noncanonical path: ' + value)
    return value


def _under(path, parent):
    return path == parent or path.startswith(parent.rstrip('/') + '/')


def _unescape_mount(value):
    # mountinfo escapes exactly these four characters. Reject unknown escapes.
    _require(re.search(r'\\(?!040|011|012|134)', value) is None,
             'Unknown mountinfo path escape')
    return re.sub(r'\\(040|011|012|134)', lambda m: chr(int(m.group(1), 8)), value)


def _mounts(raw):
    _text(raw, 'procMountinfo')
    result = []
    ids = set()
    for line in raw.splitlines():
        fields = line.split(' ')
        _require('' not in fields and fields.count('-') == 1, 'Malformed mountinfo record')
        separator = fields.index('-')
        _require(separator >= 6 and len(fields) == separator + 4, 'Malformed mountinfo fields')
        mount_id = _uint(fields[0], 'mount ID')
        _uint(fields[1], 'parent mount ID')
        _require(mount_id > 0 and mount_id not in ids, 'Duplicate or zero mount ID')
        ids.add(mount_id)
        _require(re.fullmatch(r'(0|[1-9][0-9]*):(0|[1-9][0-9]*)', fields[2]) is not None,
                 'Malformed mount device')
        root = _path(_unescape_mount(fields[3]))
        point = _path(_unescape_mount(fields[4]))
        result.append(dict(mountId=mount_id, device=fields[2], root=root, mountPoint=point,
                           filesystem=fields[separator + 1],
                           options=fields[5].split(',') + fields[separator + 3].split(',')))
    _require(result, 'Missing mounts')
    return result


def _topology(namespace, proc_cgroup, proc_mountinfo):
    _keys(namespace, ('path', 'link'), 'namespace')
    _require(namespace['path'] == '/proc/self/ns/cgroup', 'Wrong namespace observation path')
    _require(namespace['link'] == 'cgroup:[' + str(INITIAL_CGROUP_NAMESPACE_INODE) + ']',
             'Initial/global cgroup namespace is required; hidden ancestors cannot be qualified')
    lines = _text(proc_cgroup, 'procCgroup').splitlines()
    _require(len(lines) == 1 and lines[0].startswith('0::'),
             'Exactly one unified cgroup-v2 membership is required')
    cgroup_path = _path(lines[0][3:])
    _require(cgroup_path != '/',
             'The measured process must be in a non-root cgroup with real resource counters')
    mounts = _mounts(proc_mountinfo)
    candidates = [m for m in mounts if m['filesystem'] == 'cgroup2']
    _require(len(candidates) == 1 and not any(m['filesystem'] == 'cgroup' for m in mounts),
             'Ambiguous or mixed cgroup mounts')
    mount = candidates[0]
    _require(mount['root'] == '/' and mount['mountPoint'] != '/',
             'Cgroup mount must expose the complete global hierarchy, not a hidden mount root')
    _require('memory_localevents' not in mount['options'],
             'memory_localevents hides hierarchical memory events')
    for other in mounts:
        _require(other is mount or not _under(other['mountPoint'], mount['mountPoint']),
                 'Unexpected cgroup subtree overlay or duplicate mount')
    proc = [m for m in mounts if m['mountPoint'] == '/proc']
    _require(len(proc) == 1 and proc[0]['filesystem'] == 'proc' and proc[0]['root'] == '/',
             'A complete, unambiguous proc filesystem is required')
    # Reject overlays that could replace process evidence. Unrelated standard
    # submounts such as /proc/sys/fs/binfmt_misc do not hide these observations.
    _require(not any(re.match(r'/proc/(?:self|thread-self|[0-9]+)(?:/|$)', m['mountPoint'])
                     for m in mounts), 'Unexpected process proc subtree overlay')
    paths = [('/', mount['mountPoint'])]
    if cgroup_path != '/':
        parts = cgroup_path.strip('/').split('/')
        for end in range(1, len(parts) + 1):
            relative = '/' + '/'.join(parts[:end])
            paths.append((relative, mount['mountPoint'] + relative))
    proof = dict(namespaceInode=INITIAL_CGROUP_NAMESPACE_INODE,
                 mountId=mount['mountId'], mountRoot='/', mountPoint=mount['mountPoint'])
    return mount, paths, proof


def _cpulist(raw, name, allow_empty=False):
    _require(type(raw) is str and len(raw) <= _MAX_TEXT, 'Malformed ' + name)
    value = raw.strip()
    if not value:
        _require(allow_empty, 'Empty ' + name)
        return []
    result = []
    for segment in value.split(','):
        match = re.fullmatch(r'(0|[1-9][0-9]*)(?:-(0|[1-9][0-9]*))?', segment)
        _require(match is not None, 'Malformed ' + name)
        start = int(match[1])
        end = int(match[2]) if match[2] is not None else start
        _require(start <= end <= _MAX_CPU and (not result or start > result[-1]),
                 'Unordered, duplicate or invalid ' + name)
        result.extend(range(start, end + 1))
    return result


def _affinity(value):
    _require(type(value) is list and value, 'Missing parent CPU affinity')
    _require(all(type(v) is int and 0 <= v <= _MAX_CPU for v in value)
             and value == sorted(set(value)), 'Invalid parent CPU affinity')
    return value


def _quota(raw):
    parts = _text(raw, 'cpu.max').split()
    _require(len(parts) == 2, 'Malformed cpu.max quota')
    period = _uint(parts[1], 'cpu.max period')
    _require(1000 <= period <= 1000000, 'Invalid cpu.max period')
    if parts[0] == 'max':
        return None
    quota = _uint(parts[0], 'cpu.max quota')
    _require(quota >= 1000, 'Invalid cpu.max quota')
    return Fraction(quota, period)


def _memory_limit(raw, name):
    value = _text(raw, name).strip()
    return None if value == 'max' else _uint(value, name)


def _controllers(raw, name):
    _require(type(raw) is str and len(raw) <= _MAX_TEXT, 'Malformed ' + name)
    fields = raw.split()
    _require(len(fields) == len(set(fields)) and
             all(re.fullmatch(r'[a-z][a-z0-9_]*', f) for f in fields), 'Malformed ' + name)
    return set(fields)


def _identity(value, device):
    _keys(value, ('device', 'inode', 'type'), 'cgroup directory identity')
    _require(value['device'] == device and value['type'] == 'directory',
             'Cgroup path is not a directory on the observed cgroup2 filesystem')
    _integer(value['inode'], 'cgroup inode', 1)


def _derive_controls(value):
    _keys(value, ('schema', 'scope', 'platform', 'namespace', 'procCgroup', 'procMountinfo',
                  'parentCpuAffinity', 'childCpuAffinity', 'candidateWorkers',
                  'expectedAvailableProcessors', 'effectiveCpuCapacity', 'reservedCpuCapacity',
                  'globalRootProof', 'ancestors'), 'host controls')
    _require(value['schema'] == CONTROLS_SCHEMA and value['scope'] == SCOPE,
             'Wrong experimental host controls schema/scope')
    _keys(value['platform'], ('system', 'machine'), 'platform')
    _require(value['platform'] == dict(system='Linux', machine='x86_64'),
             'The portable lane requires Linux x86_64')
    mount, paths, proof = _topology(value['namespace'], value['procCgroup'], value['procMountinfo'])
    _keys(value['globalRootProof'], ('namespaceInode', 'mountId', 'mountRoot', 'mountPoint'),
          'global-root proof')
    _integer(value['globalRootProof']['namespaceInode'], 'namespace inode', 1)
    _integer(value['globalRootProof']['mountId'], 'global-root mount ID', 1)
    _require(value['globalRootProof'] == proof, 'Missing or inconsistent global-root proof')
    parent = _affinity(value['parentCpuAffinity'])
    ancestors = value['ancestors']
    _require(type(ancestors) is list and len(ancestors) == len(paths),
             'Incomplete cgroup ancestry')
    capacities = [Fraction(len(parent), 1)]
    previous_cpus = previous_mems = None
    inodes = set()
    for index, (ancestor, (relative, path)) in enumerate(zip(ancestors, paths)):
        _keys(ancestor, ('path', 'cgroupPath', 'isGlobalRoot', 'limitObservation', 'identity', 'raw'), 'ancestor')
        root = index == 0
        _require(ancestor['path'] == path and ancestor['cgroupPath'] == relative
                 and type(ancestor['isGlobalRoot']) is bool and ancestor['isGlobalRoot'] == root,
                 'Missing, reordered, duplicated or falsely exempted ancestor')
        _require(ancestor['limitObservation'] == (
            'notApplicableGlobalRoot' if root else 'requiredNonRoot'),
            'Missing explicit quota/memory-limit applicability')
        _identity(ancestor['identity'], mount['device'])
        inode = ancestor['identity']['inode']
        _require(inode not in inodes, 'Aliased ancestor directory identity')
        inodes.add(inode)
        raw = ancestor['raw']
        _keys(raw, _ROOT_CONTROLS if root else _NONROOT_CONTROLS, path + ' controls')
        cpus = set(_cpulist(raw['cpuset.cpus.effective'], path + '/cpuset.cpus.effective'))
        mems = set(_cpulist(raw['cpuset.mems.effective'], path + '/cpuset.mems.effective'))
        _require(set(parent) <= cpus, 'Parent affinity is outside an ancestor CPU allowance')
        _require(previous_cpus is None or cpus <= previous_cpus, 'Inconsistent ancestor CPU allowances')
        _require(previous_mems is None or mems <= previous_mems, 'Inconsistent ancestor memory-node allowances')
        previous_cpus, previous_mems = cpus, mems
        available = _controllers(raw['cgroup.controllers'], 'cgroup.controllers')
        enabled = _controllers(raw['cgroup.subtree_control'], 'cgroup.subtree_control')
        _require(enabled <= available, 'Enabled cgroup controller is unavailable')
        if index + 1 < len(ancestors):
            _require({'cpu', 'cpuset', 'memory'} <= enabled,
                     'An ancestor does not enable all required child controllers')
        if not root:
            _require(_text(raw['cgroup.type'], 'cgroup.type').strip() == 'domain', 'Threaded/invalid cgroups are unsupported')
            _require(_text(raw['cpuset.cpus.partition'], 'cpuset.cpus.partition').strip() == 'member',
                     'Partitioned cpusets are unsupported by this qualification lane')
            _cpulist(raw['cpuset.cpus'], 'cpuset.cpus', allow_empty=True)
            _cpulist(raw['cpuset.mems'], 'cpuset.mems', allow_empty=True)
            quota = _quota(raw['cpu.max'])
            if quota is not None:
                capacities.append(quota)
            _memory_limit(raw['memory.max'], 'memory.max')
            _memory_limit(raw['memory.high'], 'memory.high')
    capacity = min(capacities)
    _require(capacity >= 4, 'At least four effective CPUs and one full reserved CPU are required')
    return dict(parentCpuAffinity=parent, childCpuAffinity=parent[:CHILD_CPU_COUNT],
                expectedAvailableProcessors=CHILD_CPU_COUNT, candidateWorkers=CANDIDATE_WORKERS,
                effectiveCpuCapacity=float(capacity), reservedCpuCapacity=float(capacity - CHILD_CPU_COUNT),
                ancestorPaths=[path for _, path in paths])


def validate_controls(controls):
    """Replay topology, raw limits and capacity; raise ValueError if invalid.

    Return derived camelCase capacity/affinity fields and ancestorPaths. This
    validates recorded observations, not the current host. Real observation is
    exclusively the job of observe_controls/observe_counters.
    """
    summary = _derive_controls(controls)
    for key in ('childCpuAffinity', 'candidateWorkers', 'expectedAvailableProcessors',
                'effectiveCpuCapacity', 'reservedCpuCapacity'):
        actual = controls[key]
        if key == 'childCpuAffinity':
            _affinity(actual)
        elif key in ('candidateWorkers', 'expectedAvailableProcessors'):
            _integer(actual, key, 1)
        else:
            _require(type(actual) in (int, float) and 0 <= actual <= _MAX_CPU + 1 and math.isfinite(actual), 'Invalid ' + key)
        _require(actual == summary[key], 'Host control summary does not replay: ' + key)
    return summary


class LinuxReader:
    """Read-only, descriptor-relative reader; injectable with fixtures in tests.

    Every ordinary path component is opened O_NOFOLLOW. /proc/self is checked
    by descriptor-relative readlink before substituting this reader's PID: a
    procfs mounted for another PID namespace is unsupported. The namespace link
    is also read with readlink, never followed. Directory identity binds cgroup reads
    to the mountinfo device. No write-capable descriptor is ever opened.
    """

    def platform(self):
        return dict(system=platform.system(), machine=platform.machine())

    def affinity(self):
        return sorted(os.sched_getaffinity(0))

    def _physical_path(self, path):
        _path(path)
        if not path.startswith('/proc/self/'):
            return path
        # getpid() is relative to this process's PID namespace, whereas procfs
        # may expose another namespace. Never silently inspect an unrelated PID.
        # Opening /proc does not recurse into this branch or follow any symlink.
        descriptor = self._open('/proc', directory=True)
        try:
            try:
                target = os.readlink('self', dir_fd=descriptor)
            except OSError as error:
                raise ValueError('Procfs self PID identity is unavailable') from error
        finally:
            os.close(descriptor)
        _require(type(target) is str and re.fullmatch(r'[1-9][0-9]*', target) is not None,
                 'Procfs self PID identity is malformed')
        _require(target == str(os.getpid()),
                 'Procfs PID namespace does not match the current process')
        return path.replace('/proc/self/', '/proc/' + target + '/', 1)

    def _open(self, path, directory=False):
        parts = self._physical_path(path).strip('/').split('/')
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
        descriptor = os.open('/', flags | os.O_DIRECTORY)
        try:
            for index, part in enumerate(parts):
                if not part:
                    continue
                next_fd = os.open(part, flags | (os.O_DIRECTORY if index < len(parts) - 1 or directory else 0),
                                  dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_fd
            result = descriptor
            descriptor = None
            return result
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def read_text(self, path):
        descriptor = self._open(path)
        with os.fdopen(descriptor, 'r', encoding='ascii', errors='strict') as stream:
            _require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), 'Not a regular observation file: ' + path)
            text = stream.read(_MAX_TEXT + 1)
        _require(len(text) <= _MAX_TEXT, 'Observation file too large: ' + path)
        return text

    def readlink(self, path):
        path = self._physical_path(path)
        descriptor = self._open(posixpath.dirname(path), directory=True)
        try:
            return os.readlink(posixpath.basename(path), dir_fd=descriptor)
        finally:
            os.close(descriptor)

    def identity(self, path):
        descriptor = self._open(path, directory=True)
        try:
            value = os.fstat(descriptor)
            return dict(device=str(os.major(value.st_dev)) + ':' + str(os.minor(value.st_dev)),
                        inode=value.st_ino, type='directory')
        finally:
            os.close(descriptor)


def _capture_controls(reader):
    value = dict(schema=CONTROLS_SCHEMA, scope=SCOPE, platform=reader.platform(),
                 namespace=dict(path='/proc/self/ns/cgroup', link=reader.readlink('/proc/self/ns/cgroup')),
                 procCgroup=reader.read_text('/proc/self/cgroup'),
                 procMountinfo=reader.read_text('/proc/self/mountinfo'),
                 parentCpuAffinity=reader.affinity())
    _, paths, proof = _topology(value['namespace'], value['procCgroup'], value['procMountinfo'])
    value['globalRootProof'] = proof
    value['ancestors'] = []
    for index, (relative, path) in enumerate(paths):
        identity_before = reader.identity(path)
        raw = {name: reader.read_text(path + '/' + name)
               for name in (_ROOT_CONTROLS if index == 0 else _NONROOT_CONTROLS)}
        _require(reader.identity(path) == identity_before, 'Cgroup directory changed during observation')
        value['ancestors'].append(dict(path=path, cgroupPath=relative, isGlobalRoot=index == 0,
                                       limitObservation='notApplicableGlobalRoot' if index == 0 else 'requiredNonRoot',
                                       identity=identity_before, raw=raw))
    # Placeholders are overwritten only by independently derived values.
    for key in ('childCpuAffinity', 'candidateWorkers', 'expectedAvailableProcessors',
                'effectiveCpuCapacity', 'reservedCpuCapacity'):
        value[key] = None
    summary = _derive_controls(value)
    value.update({key: summary[key] for key in value if key in summary})
    validate_controls(value)
    return value


def observe_controls(*, reader=None):
    """Capture two matching read-only observations or reject an unstable host."""
    reader = LinuxReader() if reader is None else reader
    first = _capture_controls(reader)
    _require(_capture_controls(reader) == first, 'Host controls changed during observation')
    return first


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode('utf-8')).hexdigest()


def _flat_counters(raw, required, name):
    result = {}
    for line in _text(raw, name).splitlines():
        fields = line.split()
        _require(len(fields) == 2 and re.fullmatch(r'[a-z][a-z0-9_]*', fields[0]) is not None,
                 'Malformed counter in ' + name)
        _require(fields[0] not in result, 'Duplicate counter in ' + name)
        result[fields[0]] = _uint(fields[1], name + '.' + fields[0])
    _require(set(required) <= set(result), 'Missing required counter in ' + name)
    return result


def _pressure(raw, name):
    result = {}
    for line in _text(raw, name).splitlines():
        fields = line.split()
        _require(len(fields) == 5 and fields[0] in ('some', 'full') and fields[0] not in result,
                 'Malformed/duplicate PSI observation in ' + name)
        values = {}
        for field in fields[1:]:
            pair = field.split('=')
            _require(len(pair) == 2 and pair[0] not in values, 'Malformed/duplicate PSI field in ' + name)
            values[pair[0]] = pair[1]
        _require(set(values) == {'avg10', 'avg60', 'avg300', 'total'}, 'Missing PSI fields in ' + name)
        for field in ('avg10', 'avg60', 'avg300'):
            _require(re.fullmatch(r'(0|[1-9][0-9]*)\.[0-9]{2}', values[field]) is not None
                     and 0 <= float(values[field]) <= 100, 'Invalid PSI average in ' + name)
        result[fields[0]] = _uint(values['total'], name + '.' + fields[0] + '.total')
    _require(set(result) == {'some', 'full'}, 'Missing some/full PSI observations in ' + name)
    _require(result['full'] <= result['some'], 'PSI full exceeds some in ' + name)
    return result


def _snapshot(snapshot, controls):
    _keys(snapshot, ('schema', 'controlsSha256', 'observedControls', 'ancestors'), 'counter snapshot')
    _require(snapshot['schema'] == COUNTERS_SCHEMA, 'Wrong counter snapshot schema')
    validate_controls(snapshot['observedControls'])
    _require(snapshot['observedControls'] == controls and snapshot['controlsSha256'] == _digest(controls),
             'Counter snapshot controls changed or do not match the recorded host')
    observations = snapshot['ancestors']
    _require(type(observations) is list and len(observations) == len(controls['ancestors']),
             'Incomplete counter ancestry')
    parsed = []
    for observation, ancestor in zip(observations, controls['ancestors']):
        _keys(observation, ('path', 'resourceCounterObservation', 'identity', 'raw'), 'ancestor counters')
        _identity(observation['identity'], ancestor['identity']['device'])
        _require(observation['path'] == ancestor['path'] and observation['identity'] == ancestor['identity'],
                 'Missing, reordered or changed counter ancestor')
        root = ancestor['isGlobalRoot']
        _require(observation['resourceCounterObservation'] == (
            'notApplicableGlobalRoot' if root else 'requiredNonRoot'),
            'Missing explicit resource-counter applicability')
        raw = observation['raw']
        _keys(raw, _ROOT_COUNTERS if root else _NONROOT_COUNTERS, 'raw ancestor counters')
        counters = {name: _pressure(raw[name], name) for name in _ROOT_COUNTERS}
        if not root:
            for name, required in (
                    ('cpu.stat', ('throttled_usec', 'nr_throttled')),
                    ('memory.events', ('oom', 'oom_kill', 'max', 'high')),
                    ('memory.stat', ('pgscan_direct', 'pgsteal_direct'))):
                counters[name] = _flat_counters(raw[name], required, name)
        parsed.append(counters)
    return parsed


def observe_counters(controls, *, reader=None):
    """Observe every ancestor, with matching raw controls bracketing the read."""
    validate_controls(controls)
    reader = LinuxReader() if reader is None else reader
    observed = _capture_controls(reader)
    _require(observed == controls, 'Host controls changed before counters were observed')
    snapshot = dict(schema=COUNTERS_SCHEMA, controlsSha256=_digest(controls),
                    observedControls=observed, ancestors=[])
    for ancestor in observed['ancestors']:
        path = ancestor['path']
        _require(reader.identity(path) == ancestor['identity'], 'Counter ancestor identity changed')
        raw = {name: reader.read_text(path + '/' + name)
               for name in (_ROOT_COUNTERS if ancestor['isGlobalRoot'] else _NONROOT_COUNTERS)}
        _require(reader.identity(path) == ancestor['identity'], 'Counter ancestor identity changed')
        snapshot['ancestors'].append(dict(path=path,
            resourceCounterObservation='notApplicableGlobalRoot' if ancestor['isGlobalRoot'] else 'requiredNonRoot',
            identity=ancestor['identity'].copy(), raw=raw))
    _require(_capture_controls(reader) == controls, 'Host controls changed while counters were observed')
    _snapshot(snapshot, controls)
    return snapshot


def validate_resource_pair(before, after, wall_nanos, controls):
    """Replay a run's resources; return the summary or raise ValueError.

    The elapsed benchmark wall time must be positive integer nanoseconds. Memory
    events, direct reclaim and memory PSI deltas must all be zero, including
    root memory PSI. CPU PSI is required and monotonic, but not required zero:
    four workers intentionally share three CPUs. Throttling is checked at every
    non-root ancestor separately AND conservatively summed across ancestors.
    Overlapping throttling may be counted twice; this intentionally over-rejects.
    Global-root structural counters are not applicable, never synthetic zeros.
    """
    _integer(wall_nanos, 'wall_nanos', 1)
    validate_controls(controls)
    first, last = _snapshot(before, controls), _snapshot(after, controls)
    summary = dict(noOom=True, noMemoryLimitEvents=True, noDirectReclaim=True,
                   noMemoryPressure=True, cpuPressureObserved=True,
                   resourceCounterScope='observed-non-root-ancestry',
                   memoryPressureScope='observed-full-ancestry-including-global-root',
                   maxThrottleToWallRatio=0.0, cumulativeThrottleToWallRatio=0.0, ancestors=[])
    cumulative_throttle = 0
    for ancestor, initial, final in zip(controls['ancestors'], first, last):
        deltas = {}
        for group in initial:
            _require(set(initial[group]) == set(final[group]), 'Counter fields changed during run')
            # memory.stat contains gauges that legitimately decrease. Only its
            # required cumulative direct-reclaim counters are compared.
            keys = ('pgscan_direct', 'pgsteal_direct') if group == 'memory.stat' else initial[group]
            deltas[group] = {}
            for key in keys:
                delta = final[group][key] - initial[group][key]
                _require(delta >= 0, 'Nonmonotonic ' + group + '.' + key + ' at ' + ancestor['path'])
                deltas[group][key] = delta
        _require(all(delta == 0 for delta in deltas['memory.pressure'].values()),
                 'Memory PSI increased at ' + ancestor['path'])
        ratio = None
        if not ancestor['isGlobalRoot']:
            _require(all(deltas['memory.events'][key] == 0 for key in ('oom', 'oom_kill', 'max', 'high')),
                     'OOM or memory limit/high event at ' + ancestor['path'])
            _require(all(delta == 0 for delta in deltas['memory.stat'].values()),
                     'Direct reclaim at ' + ancestor['path'])
            throttle = deltas['cpu.stat']['throttled_usec']
            cumulative_throttle += throttle
            # Integer comparison preserves the exact inclusive 5% boundary.
            _require(throttle * 1000 * 20 <= wall_nanos,
                     'CPU throttling exceeds 5% of wall time at ' + ancestor['path'])
            ratio = throttle * 1000 / wall_nanos
            summary['maxThrottleToWallRatio'] = max(summary['maxThrottleToWallRatio'], ratio)
        summary['ancestors'].append(dict(path=ancestor['path'], isGlobalRoot=ancestor['isGlobalRoot'],
            resourceCounterObservation='notApplicableGlobalRoot' if ancestor['isGlobalRoot'] else 'requiredNonRoot',
            throttleToWallRatio=ratio, deltas=deltas))
    _require(cumulative_throttle * 1000 * 20 <= wall_nanos,
             'Cumulative ancestor CPU throttling exceeds 5% of wall time')
    summary['cumulativeThrottleToWallRatio'] = cumulative_throttle * 1000 / wall_nanos
    return summary


def _diagnostic_reason(error):
    """Expose an actionable category, never raw exception paths or contents."""
    message = str(error)
    safe = (
        'Procfs self PID identity is unavailable',
        'Procfs self PID identity is malformed',
        'Procfs PID namespace does not match the current process',
        'Initial/global cgroup namespace is required; hidden ancestors cannot be qualified',
        'The measured process must be in a non-root cgroup with real resource counters',
        'At least four effective CPUs and one full reserved CPU are required',
        'Exactly one unified cgroup-v2 membership is required',
        'Ambiguous or mixed cgroup mounts',
        'Cgroup mount must expose the complete global hierarchy, not a hidden mount root',
        'memory_localevents hides hierarchical memory events',
        'Unexpected cgroup subtree overlay or duplicate mount',
        'A complete, unambiguous proc filesystem is required',
        'Unexpected process proc subtree overlay',
        'An ancestor does not enable all required child controllers',
        'Threaded/invalid cgroups are unsupported',
        'Partitioned cpusets are unsupported by this qualification lane',
        'Host controls changed during observation',
        'Host controls changed before counters were observed',
        'Host controls changed while counters were observed',
        'Host identity changed during diagnostic observation',
        'Some required diagnostic observations are unavailable',
    )
    if message in safe:
        return message
    if message.startswith('Unsafe or noncanonical path:'):
        return 'A host topology path is unsafe or noncanonical; path details omitted.'
    if 'mountinfo' in message.lower() or 'mount ID' in message or 'mount device' in message:
        return 'The observed mount topology is malformed or ambiguous; unrelated mount details omitted.'
    if isinstance(error, OSError):
        files = sorted(set(_ROOT_CONTROLS + _NONROOT_CONTROLS + _NONROOT_COUNTERS), key=len, reverse=True)
        target = next((name for name in files if re.search(r'(?:^|[/\s\x27\x22])' + re.escape(name)
                                                          + r'(?:$|[\s\x27\x22])', message)), None)
        return 'A required read-only host observation is unavailable' + (': ' + target if target else '.')
    return 'Host topology, limits or counters failed strict validation; no eligibility established.'


def diagnose(*, reader=None):
    """Bounded read-only eligibility diagnostic, never a qualification receipt.

    Only relevant cgroup mount summaries are exposed. Full mountinfo, process
    environments, credentials and unrelated mount options are never dumped.
    Raw applicable ancestor limits/counters are retained after verification,
    but this projection deliberately cannot be replayed as benchmark evidence.
    """
    reader = LinuxReader() if reader is None else reader
    record = dict(schema='lightforge.experimental-portable-runner-diagnostic.v1',
        scope='Read-only runner eligibility only; no inference, performance or release qualification.',
        eligible=False, qualificationEstablished=False, releaseAdmissible=False,
        fullQualificationEvidence=False, observations={}, observationErrors=[])
    observations = (
        ('platform', reader.platform),
        ('parentCpuAffinity', lambda: _affinity(reader.affinity())),
        ('cgroupNamespace', lambda: reader.readlink('/proc/self/ns/cgroup')),
        ('cgroupMembership', lambda: reader.read_text('/proc/self/cgroup')),
        ('cgroup2Mounts', lambda: [{key: mount[key] for key in
                                  ('mountId', 'device', 'root', 'mountPoint', 'filesystem')}
                                 for mount in _mounts(reader.read_text('/proc/self/mountinfo'))
                                 if mount['filesystem'] == 'cgroup2']),
    )
    for name, observe in observations:
        try:
            record['observations'][name] = observe()
        except (OSError, ValueError, UnicodeError) as error:
            record['observationErrors'].append(dict(observation=name, reason=_diagnostic_reason(error)))
    try:
        controls = observe_controls(reader=reader)
        counters = observe_counters(controls, reader=reader)
        _require(not record['observationErrors'], 'Some required diagnostic observations are unavailable')
        _require(record['observations']['parentCpuAffinity'] == controls['parentCpuAffinity']
                 and record['observations']['cgroupNamespace'] == controls['namespace']['link']
                 and record['observations']['cgroupMembership'] == controls['procCgroup'],
                 'Host identity changed during diagnostic observation')
        # Avoid exposing unrelated system mounts or mount-option credentials.
        record['verifiedHostControls'] = {key: value for key, value in controls.items()
                                          if key != 'procMountinfo'}
        record['procMountinfoSha256'] = hashlib.sha256(controls['procMountinfo'].encode()).hexdigest()
        record['observedCounters'] = {key: value for key, value in counters.items()
                                      if key != 'observedControls'}
        record['eligible'] = True
    except (OSError, ValueError, UnicodeError) as error:
        record['reason'] = _diagnostic_reason(error)
    # The CLI must not become an unbounded system-information dump. Oversize
    # reports explicitly fail eligibility instead of silently truncating proof.
    if len(json.dumps(record, allow_nan=False).encode()) > 1024 * 1024:
        record = dict(schema=record['schema'], scope=record['scope'], eligible=False,
                      qualificationEstablished=False, releaseAdmissible=False, fullQualificationEvidence=False,
                      reason='Complete diagnostic exceeds the one-MiB output limit; no eligibility established.')
    return record


def main():
    parser = argparse.ArgumentParser(description='Read-only experimental runner diagnostic; no host writes or benchmark.')
    parser.parse_args()
    record = diagnose()
    print(json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False))
    return 0 if record['eligible'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
