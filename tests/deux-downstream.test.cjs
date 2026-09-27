'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const tool = require('../tools/compare_deux_downstream.cjs');
const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, '../web/analysis/models/deux/manifest.json')));
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

function captureBytes() {
  const bytes = Buffer.alloc(2 * tool.SAMPLES * 4);
  for (let i = 0; i < tool.SAMPLES; i++) {
    bytes.writeFloatLE(i / tool.SAMPLES, i * 4);
    bytes.writeFloatLE(-i / tool.SAMPLES, (tool.SAMPLES + i) * 4);
  }
  return bytes;
}
function receipt(bytes) {
  return {runs: [{variant: 'cpu_all', phase: 'qualification', round: 0, outputBytes: bytes.length, outputSha256: hash(bytes)}],
    comparisons: [{reference: 'cpu_all', candidate: 'cpu_all_profiled', byteIdentical: true,
      referenceSha256: hash(bytes), candidateSha256: hash(bytes)}]};
}
function source(overrides = {}) {
  return {rate: 44100, samples: 64 * 44100,
    stereo44100: async (_start, count) => [new Float32Array(count).fill(.2), new Float32Array(count).fill(.3)],
    ...overrides};
}

test('captured PCM preserves both planar stems and rejects truncation or nonfinite values', () => {
  const bytes = captureBytes(), result = tool.readCaptured(bytes);
  assert.equal(result.vocals.length, tool.SAMPLES);
  assert.equal(result.accompaniment.length, tool.SAMPLES);
  assert.equal(result.vocals[120000], bytes.readFloatLE(120000 * 4));
  assert.equal(result.accompaniment[120000], -result.vocals[120000]);
  assert.throws(() => tool.readCaptured(bytes.subarray(4)), /Complete two-stem/);
  bytes.writeFloatLE(NaN, (tool.SAMPLES + 100) * 4);
  assert.throws(() => tool.readCaptured(bytes), /Nonfinite/);
});

test('capture binding rejects altered bytes, duplicate runs, missing observers and false observer identities', () => {
  const bytes = captureBytes(), good = receipt(bytes);
  assert.equal(tool.validateRun(good, 'cpu_all', bytes), good.runs[0]);
  const changed = Buffer.from(bytes); changed[400] ^= 1;
  assert.throws(() => tool.validateRun(good, 'cpu_all', changed), /digest differs/);
  const duplicate = structuredClone(good); duplicate.runs.push({...duplicate.runs[0]});
  assert.throws(() => tool.validateRun(duplicate, 'cpu_all', bytes), /Exactly one/);
  const absent = structuredClone(good); absent.comparisons = [];
  assert.throws(() => tool.validateRun(absent, 'cpu_all', bytes), /observer comparison/);
  for (const field of ['referenceSha256', 'candidateSha256']) {
    const bad = structuredClone(good); bad.comparisons[0][field] = '0'.repeat(64);
    assert.throws(() => tool.validateRun(bad, 'cpu_all', bytes), /identity differs/);
  }
  const invalid = structuredClone(good); invalid.comparisons[0].byteIdentical = false;
  assert.throws(() => tool.validateRun(invalid, 'cpu_all', bytes), /preserve bytes/);
});

test('unmodified separator emits only the correct first five seconds and requests the next overlap', async () => {
  const bytes = captureBytes(), original = hash(bytes), captured = tool.readCaptured(bytes);
  const before = global.fetch;
  const result = await tool.replayFirstChunk(source(), captured, manifest);
  assert.equal(global.fetch, before, 'Global transport is restored');
  assert.equal(result.chunk.startSample, 0);
  assert.equal(result.chunk.vocals.length, 220500);
  assert.equal(result.chunk.accompaniment.length, 220500);
  assert.deepEqual(result.chunk.vocals, captured.vocals.slice(66150, 286650));
  assert.deepEqual(result.chunk.accompaniment, captured.accompaniment.slice(66150, 286650));
  assert.equal(result.replay.sourceComplete, false);
  assert.equal(result.replay.stoppedAtMissingPassage, true);
  assert.equal(result.replay.overlapBetweenTwoMeasuredPassagesExercised, false);
  assert.deepEqual(result.replay.reads, [{start: -66150, count: 573300}, {start: 154350, count: 573300}]);
  assert.equal(hash(bytes), original, 'Original captured bytes remain unchanged');
});

test('replay rejects a shortened source and cannot promote silence bypass as captured inference', async () => {
  const captured = tool.readCaptured(captureBytes());
  await assert.rejects(tool.replayFirstChunk(source({samples: tool.CORE}), captured, manifest), /shortened source/);
  // The real consumer bypasses inference for silence. The research replay must
  // reject that, rather than implying the measured CUDA capture was consumed.
  await assert.rejects(tool.replayFirstChunk(source({stereo44100: async (_s, n) => [new Float32Array(n), new Float32Array(n)]}), captured, manifest));
});

test('unexpected reader failure remains a failure rather than a planned partial completion', async () => {
  const captured = tool.readCaptured(captureBytes()), original = global.fetch;
  await assert.rejects(tool.replayFirstChunk(source({stereo44100: async () => { throw new Error('damaged source'); }}), captured, manifest), /damaged source/);
  assert.equal(global.fetch, original);
});

test('CLI rejects duplicate flags, unknown arms and missing exact evidence inputs', () => {
  const good = ['--evidence', '/tmp/evidence', '--audio', '/tmp/demo.wav', '--output', '/tmp/output'];
  assert.equal(tool.parseArgs(good).evidence, '/tmp/evidence');
  assert.throws(() => tool.parseArgs([...good, '--output', '/tmp/other']), /Duplicate/);
  assert.throws(() => tool.parseArgs([...good, '--child', 'cpu_basic']), /Unsupported child/);
  assert.throws(() => tool.parseArgs(['--output', '/tmp/output']), /Missing/);
});
