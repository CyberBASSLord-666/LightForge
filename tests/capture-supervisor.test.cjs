'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {supervise} = require('../qa/locked-benchmark/capture-supervisor.cjs');
const helperPath = path.join(__dirname, '../qa/locked-benchmark/capture-supervisor.py');

function pythonCheck(source) {
  execFileSync('python3', ['-I', '-c', `import importlib.util, sys\nspec = importlib.util.spec_from_file_location('capture_supervisor', sys.argv[1])\nsupervisor = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(supervisor)\n${source}`, helperPath],
    {timeout: 5000, stdio: 'pipe'});
}

function temp(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lightforge-supervisor-'));
  t.after(() => fs.rmSync(dir, {recursive: true, force: true}));
  return dir;
}

function exists(pid) {
  try { process.kill(pid, 0); return true; }
  catch (error) { if (error.code === 'ESRCH') return false; throw error; }
}

async function run(source, timeoutMs = 1500, extra = {}) {
  return supervise({executable: process.execPath, args: ['-e', source], timeoutMs, stdio: 'ignore', ...extra});
}

test('normal exit has verified kernel reaping and preserves status', async () => {
  for (const status of [0, 7]) {
    const result = await run(`process.exit(${status})`);
    assert.equal(result.exit_code, status);
    assert.equal(result.timed_out, false);
    assert.equal(result.termination.verified, true);
    assert.equal(result.termination.attempted, false);
    assert.equal(result.termination.cleanup_discovery_scans, 0);
    assert.deepEqual(result.termination.remaining_pids, []);
  }
});

test('deadline includes a target that never completes startup', async t => {
  const file = path.join(temp(t), 'startup.pid');
  const started = performance.now();
  const result = await run(`require('node:fs').writeFileSync(${JSON.stringify(file)},String(process.pid)); setInterval(()=>{},1000);`, 700);
  assert.equal(result.exit_code, 124);
  assert.equal(result.timed_out, true);
  assert.equal(result.termination.verified, true);
  assert.equal(exists(Number(fs.readFileSync(file, 'utf8'))), false);
  assert.ok(performance.now() - started < 4200);
});

test('a target hanging in cleanup is killed and reaped within the cleanup allowance', async t => {
  const dir = temp(t);
  const pidFile = path.join(dir, 'cleanup.pid');
  const marker = path.join(dir, 'cleanup.started');
  const result = await run(`const fs=require('node:fs'); fs.writeFileSync(${JSON.stringify(pidFile)},String(process.pid)); process.on('SIGTERM',()=>{fs.writeFileSync(${JSON.stringify(marker)},'entered cleanup');}); setInterval(()=>{},1000);`, 700);
  assert.equal(result.exit_code, 124);
  assert.equal(result.signal, 'SIGKILL');
  assert.equal(result.termination.verified, true);
  assert.equal(fs.readFileSync(marker, 'utf8'), 'entered cleanup');
  assert.equal(exists(Number(fs.readFileSync(pidFile, 'utf8'))), false);
});

test('deadline kills a detached child in its own process group and reaps both processes', async t => {
  const dir = temp(t);
  const parentFile = path.join(dir, 'parent.pid');
  const childFile = path.join(dir, 'detached.pid');
  const detached = `process.on('SIGTERM',()=>{}); setInterval(()=>{},1000);`;
  const source = `const fs=require('node:fs'); const cp=require('node:child_process'); fs.writeFileSync(${JSON.stringify(parentFile)},String(process.pid)); const child=cp.spawn(process.execPath,['-e',${JSON.stringify(detached)}],{detached:true,stdio:'ignore'}); fs.writeFileSync(${JSON.stringify(childFile)},String(child.pid)); child.unref(); setInterval(()=>{},1000);`;
  const result = await run(source, 800);
  assert.equal(result.exit_code, 124);
  assert.equal(result.termination.verified, true);
  assert.ok(result.termination.reaped_processes >= 2);
  for (const file of [parentFile, childFile]) assert.equal(exists(Number(fs.readFileSync(file, 'utf8'))), false);
});

test('successful parent exit cannot hide an immediately detached and reparented child', async t => {
  const file = path.join(temp(t), 'orphan.pid');
  const detached = `process.on('SIGTERM',()=>{}); setInterval(()=>{},1000);`;
  const source = `const child=require('node:child_process').spawn(process.execPath,['-e',${JSON.stringify(detached)}],{detached:true,stdio:'ignore'}); require('node:fs').writeFileSync(${JSON.stringify(file)},String(child.pid)); child.unref();`;
  const result = await run(source);
  assert.equal(result.exit_code, 1);
  assert.equal(result.timed_out, false);
  assert.equal(result.termination.cleanup_required, true);
  assert.equal(result.termination.verified, true);
  assert.ok(result.termination.reaped_processes >= 2);
  assert.equal(exists(Number(fs.readFileSync(file, 'utf8'))), false);
});

test('a deadline already elapsed during helper startup never starts the target', async t => {
  const file = path.join(temp(t), 'must-not-exist');
  const result = await run(`require('node:fs').writeFileSync(${JSON.stringify(file)},'started');`, 1);
  assert.equal(result.exit_code, 124);
  assert.equal(result.termination.verified, true);
  assert.equal(fs.existsSync(file), false);
});

test('missing target produces a failed result without inventing a successful capture', async () => {
  const result = await supervise({executable: '/missing/lightforge-capture', timeoutMs: 1000, stdio: 'ignore'});
  assert.equal(result.exit_code, 1);
  assert.equal(result.termination.verified, true);
  assert.ok(result.errors.some(error => error.includes('FileNotFoundError')));
});

test('missing lifecycle helper cannot claim that descendant termination was verified', async () => {
  const result = await run('process.exit(0)', 1000, {env: {...process.env, PATH: '/missing/lightforge-python'}});
  assert.equal(result.exit_code, 1);
  assert.equal(result.termination.verified, false);
});

test('invalid deadlines and executable arguments are rejected before spawning', () => {
  assert.throws(() => supervise({executable: process.execPath, timeoutMs: 0}), /timeoutMs/);
  assert.throws(() => supervise({executable: process.execPath, args: [null], timeoutMs: 1}), /string arguments/);
});

test('normal monitoring never enumerates procfs while the target runs', () => {
  pythonCheck(`import os, time
from unittest import mock
with mock.patch.object(os, 'listdir', side_effect=AssertionError('normal monitoring enumerated procfs')):
    with mock.patch.object(os, 'scandir', side_effect=AssertionError('normal monitoring enumerated procfs')):
        result = supervisor.supervise(time.monotonic_ns() + 1_000_000_000, [sys.executable, '-I', '-c', 'import time; time.sleep(0.1)'])
assert result['exit_code'] == 0, result
assert result['termination']['cleanup_discovery_scans'] == 0, result
`);
});

test('stale and foreign discovery hints fail kernel ownership before any pidfd is opened', () => {
  pythonCheck(`import os, subprocess, time
from unittest import mock
owned = supervisor.OwnedProcesses()
# A stale PPid hint can name a live foreign process. The actual parent cannot
# be our child, so waitid must return ECHILD without pinning or signaling it.
foreign_pid = os.getppid()
owned.candidate_pids = lambda _deadline: [foreign_pid]
with mock.patch.object(os, 'pidfd_open', side_effect=AssertionError('foreign PID was pinned')):
    owned.discover_direct_children(time.monotonic_ns() + 1_000_000_000)
assert owned.handles == {}
# Model an ownership change between discovery and pinning: the discovered
# direct child exits and is reaped before the hint is consumed.
child = subprocess.Popen([sys.executable, '-I', '-c', 'pass'])
discovered_pid = child.pid
child.wait()
owned.candidate_pids = lambda _deadline: [discovered_pid]
with mock.patch.object(os, 'pidfd_open', side_effect=AssertionError('reaped PID was pinned')):
    owned.discover_direct_children(time.monotonic_ns() + 1_000_000_000)
assert owned.handles == {}
owned.close()
`);
});

test('running direct-child ownership is checked without consuming its exit status', () => {
  pythonCheck(`import os, signal, subprocess, time
owned = supervisor.OwnedProcesses()
child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(10)'])
owned.main_pid = child.pid
try:
    assert owned.pin_direct(child.pid)
    assert owned.main_status is None
    assert child.pid in owned.handles
    owned.signal_all(signal.SIGTERM)
    deadline = time.monotonic() + 2
    while not owned.reap() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert owned.main_status == -signal.SIGTERM, owned.main_status
    assert owned.reap()
    child.returncode = owned.main_status
finally:
    if owned.main_status is None:
        child.kill()
        child.wait()
    owned.close()
`);
});

test('cleanup stops a huge lazy procfs iterator at the injected deadline', () => {
  pythonCheck(`import itertools, os, types
from unittest import mock
owned = supervisor.OwnedProcesses()
owned.children_path = None
class HugeEntries:
    consumed = 0
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def __iter__(self): return self
    def __next__(self):
        self.consumed += 1
        assert self.consumed < 10, 'eagerly consumed a huge process table'
        return types.SimpleNamespace(name=str(1000000 + self.consumed))
entries = HugeEntries()
with mock.patch.object(os, 'scandir', return_value=entries), mock.patch.object(supervisor, 'stat_record', return_value={'pid': 1, 'ppid': -1}), mock.patch.object(supervisor.time, 'monotonic_ns', side_effect=itertools.count()):
    assert list(owned.candidate_pids(5)) == []
assert 0 < entries.consumed <= 5, entries.consumed
assert owned.discovery_deadline_exhausted
assert owned.handles == {}
owned.close()
`);
});

test('cleanup reads a large children file in bounded chunks and stops parsing on expiry', () => {
  pythonCheck(`import itertools
from unittest import mock
owned = supervisor.OwnedProcesses()
owned.children_path = '/synthetic/children'
class HugeChildren:
    sizes = []
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def read(self, size):
        assert 0 < size <= 4096, 'unbounded children-file read'
        self.sizes.append(size)
        assert len(self.sizes) < 3, 'read beyond the cleanup deadline'
        return '12345 ' * (size // 6)
stream = HugeChildren()
with mock.patch('builtins.open', return_value=stream), mock.patch.object(supervisor.time, 'monotonic_ns', side_effect=itertools.count()):
    hints = list(owned.proc_pid_hints(5))
assert 0 < len(hints) < 10, hints
assert stream.sizes == [4096], stream.sizes
assert owned.discovery_deadline_exhausted
owned.close()
`);
});

test('exhausted discovery kills pinned children while leaving termination explicitly unverified', () => {
  pythonCheck(`import os, signal, time
from unittest import mock
def expire(owned, _deadline):
    owned.discovery_deadline_exhausted = True
    return False
result = None
try:
    with mock.patch.object(supervisor.OwnedProcesses, 'discover_direct_children', expire):
        result = supervisor.supervise(time.monotonic_ns() + 500_000_000, [sys.executable, '-I', '-c', 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(10)'])
    assert result['exit_code'] == 124, result
    assert result['termination']['verified'] is False, result
    assert result['termination']['discovery_deadline_exhausted'] is True, result
    assert result['termination']['remaining_pids'], result
    # The supervisor cannot finish discovery, but its existing pidfds still
    # prove safe signal targets. Confirm KILL delivery without rescuing it.
    for pid in result['termination']['remaining_pids']:
        deadline = time.monotonic() + 1
        while True:
            exited, status = os.waitpid(pid, os.WNOHANG)
            if exited:
                assert os.waitstatus_to_exitcode(status) == -signal.SIGKILL, status
                break
            assert time.monotonic() < deadline, 'pinned child survived exhausted discovery'
            time.sleep(0.01)
finally:
    # These are still unreaped direct children of this test, not host hints.
    if result is not None:
        for pid in result['termination']['remaining_pids']:
            try:
                os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
`);
});
