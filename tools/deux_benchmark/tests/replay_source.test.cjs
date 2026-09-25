'use strict';
// These fixtures are synthetic consumer tests, never measured inference evidence.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const R = require('../replay_source.cjs');
const ROOT = path.resolve(__dirname, '../../..');
const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, 'web/analysis/models/deux/manifest.json')));
const config = JSON.parse(fs.readFileSync(path.join(ROOT, 'web/analysis/models/features.json')));

function fixture(seconds = 16) {
  const total = seconds * R.RATE, audioBytes = Buffer.alloc(44 + total * 4);
  audioBytes.write('RIFF'); audioBytes.writeUInt32LE(audioBytes.length - 8, 4); audioBytes.write('WAVEfmt ', 8);
  audioBytes.writeUInt32LE(16, 16); audioBytes.writeUInt16LE(1, 20); audioBytes.writeUInt16LE(2, 22);
  audioBytes.writeUInt32LE(R.RATE, 24); audioBytes.writeUInt32LE(R.RATE * 4, 28);
  audioBytes.writeUInt16LE(4, 32); audioBytes.writeUInt16LE(16, 34); audioBytes.write('data', 36);
  audioBytes.writeUInt32LE(total * 4, 40);
  for (let i = 0; i < total; i++) { audioBytes.writeInt16LE((i % 201) - 100, 44 + i * 4); audioBytes.writeInt16LE(200 - i % 399, 46 + i * 4); }
  const captures = R.planPassages(total).map(passage => {
    const bytes = Buffer.alloc(R.SAMPLES * 8);
    for (let i = 0; i < R.SAMPLES; i++) {
      // Adjacent passages deliberately disagree; copying/concatenating their
      // cores cannot pass the unchanged production overlap checkpoint replay.
      bytes.writeFloatLE((passage.index + 1) * .001 + (i % 701 - 350) * .00001, i * 4);
      bytes.writeFloatLE((passage.index + 1) * -.002 + (i % 109 - 54) * .0001, (R.SAMPLES + i) * 4);
    }
    return bytes;
  });
  return {audioBytes, captures, manifest, config,
    identity: {schema: 'synthetic-consumer-test-only', sourceSha256: R.hash(audioBytes), provider: 'synthetic', noInferenceEvidence: true}};
}

test('complete 64-second original consumer produces verified stems and genuine partial-checkpoint resume', async () => {
  const input = fixture(64), result = await R.replayArm({...input, stopBefore: 6}), report = result.report;
  assert.equal(report.productionResult.chunks, 12); assert.equal(report.productionResult.restoredPassages, 0);
  assert.deepEqual(report.chunks.map(c => c.samples), [...Array(11).fill(R.STRIDE), 9 * R.RATE]);
  assert.deepEqual(report.sourceReads.map(c => c.startSample), Array.from({length: 12}, (_, i) => -R.HALO + i * R.STRIDE));
  assert.deepEqual(report.resumedCallbackIndices, [6, 7, 8, 9, 10, 11]);
  assert.equal(report.restoredPassages, 6); assert.equal(report.checkpointOnlyRestoredPassages, 12);
  assert.equal(report.metadata.fullSamples, 64 * R.RATE); assert.equal(report.metadata.samples, 64 * 22050);
  assert.equal(result.stems['voice-full.wav'].length, 44 + 64 * R.RATE * 4);
  assert.equal(report.completeVoicePcmSha256, R.hash(result.stems['voice-full.wav'].subarray(44)));
  assert.equal(report.checkpointFiles.length, 12); assert.equal(report.verifiedStemReaders, true);
  assert.equal(report.interruption.completeStemCacheCommitted, false);
  assert.equal(report.interruptedResumeStemBytesIdentical, true); assert.equal(report.checkpointOnlyStemBytesIdentical, true);
});

test('missing complete passage rejects instead of using another passage or inferring', async () => {
  const input = fixture(11); input.captures.pop();
  await assert.rejects(R.executeConsumer(input), /All canonical passages/);
});

test('silent source cannot admit unused non-silent captures', async () => {
  const input = fixture(1); input.audioBytes.fill(0, 44);
  await assert.rejects(R.executeConsumer(input), /Silent passage/);
});

test('short or nonfinite capture cannot become a committed source', async () => {
  assert.throws(() => R.decodeCaptured(Buffer.alloc(10)), /Complete two-stem/);
  const input = fixture(1); input.captures[0].writeFloatLE(NaN, R.HALO * 4);
  await assert.rejects(R.executeConsumer(input), /Nonfinite captured/);
});

test('real checksum-corrupted work-store passage is re-consumed on resume', async () => {
  const input = fixture(11), first = await R.executeConsumer(input);
  const corrupt = first.snapshot.map(item => ({path: item.path, bytes: Buffer.from(item.bytes)}));
  corrupt.find(item => item.path.endsWith('/deux-0.bin')).bytes[1000] ^= 1;
  const resumed = await R.executeConsumer({...input, snapshot: corrupt});
  assert.deepEqual(resumed.calls, [0]); assert.equal(resumed.result.restoredPassages, 1);
  for (const name of Object.keys(first.stems)) assert.deepEqual(resumed.stems[name], first.stems[name]);
});

test('fresh production cache verifier rejects corrupted completed full-resolution voice', async () => {
  const input = fixture(1), first = await R.executeConsumer(input);
  const corrupt = first.snapshot.map(item => ({path: item.path, bytes: Buffer.from(item.bytes)}));
  corrupt.find(item => item.path.endsWith('/voice-full.wav')).bytes[1000] ^= 1;
  const context = R.productionContext(R.memoryDisk(corrupt), manifest);
  await assert.rejects(context.LightForgeStemCache.fullVoice(first.metadata), /integrity check failed/);
});

test('descriptor deltas never promote a numerical tolerance', () => {
  const left = R.encodeFloats(Float32Array.of(0, .25, -0)), right = R.encodeFloats(Float32Array.of(0, .25 + 2 ** -24, 0));
  const report = R.comparePcm(left, right);
  assert.equal(report.byteIdentical, false); assert.equal(report.changedSamples, 1);
  assert.equal(report.maxAbsoluteDifference, 2 ** -24); assert.match(report.rule, /no equivalence tolerance/);
});

test('CPU-only complete scope admits exactly CPU observers and no inferred cross-provider result', () => {
  const receipt = {schema: 'lightforge.deux-source-cuda-experiment.v1', status: 'CPU_SOURCE_DIAGNOSTIC_COMPLETE',
    variants: ['cpu_all'], modes: ['plain', 'profiled'], executionIdentity: {cpu_all: {}},
    gpuRuntime: null, rawOutputsByteIdenticalAcrossVariants: null, crossVariantComparisons: []};
  assert.deepEqual(R.captureScope(receipt), {cpuOnly: true, variants: ['cpu_all']});
  for (const status of ['PREFLIGHT_READY', 'BLOCKED_OR_REJECTED', 'OBSERVER_COMPARISON_INVALID', 'INCOMPLETE'])
    assert.throws(() => R.captureScope({...receipt, status}), /Incomplete or rejected/);
  assert.throws(() => R.captureScope({...receipt, rawOutputsByteIdenticalAcrossVariants: true}), /cross-provider result/);
  assert.throws(() => R.captureScope({...receipt, executionIdentity: {cpu_all: {}, cuda_basic: {}}}), /identity arms/);
  assert.throws(() => R.captureScope({...receipt, status: 'COMPLETE_DIAGNOSTIC'}), /execution variants/);
});

test('paired scope requires the explicit complete CPU and CUDA matrix', () => {
  const receipt = {schema: 'lightforge.deux-source-cuda-experiment.v1', status: 'NUMERICAL_EQUIVALENCE_UNPROVEN',
    variants: ['cpu_all', 'cuda_basic'], modes: ['plain', 'profiled'], executionIdentity: {cpu_all: {}, cuda_basic: {}}};
  assert.deepEqual(R.captureScope(receipt), {cpuOnly: false, variants: ['cpu_all', 'cuda_basic']});
  assert.throws(() => R.captureScope({...receipt, variants: ['cuda_basic']}), /execution variants/);
  assert.throws(() => R.captureScope({...receipt, modes: ['plain']}), /observer modes/);
});
