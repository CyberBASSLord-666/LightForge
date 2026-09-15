'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {supervise} = require('../qa/locked-benchmark/capture-supervisor.cjs');

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
