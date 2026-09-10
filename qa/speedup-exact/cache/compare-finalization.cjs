#!/usr/bin/env node
'use strict';

// Reproduce the role-cache finalization comparison without running model inference.
// Usage: node compare-finalization.cjs [repo] [baseline-root] [output-directory]
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { spawnSync } = require('node:child_process');
const repo = path.resolve(process.argv[2] || path.join(__dirname, '../../..'));
const baseline = path.resolve(process.argv[3] || path.join(__dirname, 'reference'));
const out = path.resolve(process.argv[4] || __dirname);
const fixturePath = 'qa/release-2.2.4/actual-analysis-falcon.json';
const workerPath = 'web/analysis/worker.js';
const recoveryTestPath = 'tests/analysis-recovery-2.2.1.test.cjs';
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const read = file => fs.readFileSync(file);
const sourcePaths = [
  'android/src/com/cyberbasslord/lightforge/AnalysisJobStore.java',
  'tests/AnalysisJobStoreTest.java',
  'web/background/runner.js',
  'web/analysis/analyzer.js', workerPath, recoveryTestPath,
  'web/analysis/work-store.js', 'web/analysis/stem-cache.js',
  'web/analysis/separator-mdx.js', 'web/analysis/separator-deux.js',
  'web/analysis/game.js', 'web/analysis/wav-reader.js',
  'web/analysis/dsp.js', 'web/analysis/vocal.js',
  'web/analysis/vocal-detail.js', 'web/analysis/bass-notes.js',
  'web/analysis/models/features.json', 'web/analysis/models/model-manifest.json',
  'version.json', fixturePath
];
function binding(root, relative) {
  const bytes = read(path.join(root, relative));
  return { path: relative, bytes: bytes.length, sha256: sha256(bytes) };
}
function beforeBass(input) {
  const value = structuredClone(input);
  for (const name of ['bassNotes', 'bassAnalysis', 'engine', 'analysisVersion', 'roleAnalysis', 'recommendedAudio']) delete value[name];
  return value;
}
async function runWorker(source, input, bassEvidence, cached, models, actual) {
  const messages = [], writes = [];
  const context = vm.createContext({
    console, URL, Float32Array, ArrayBuffer, DataView, Map, Number, setTimeout,
    // Timing is fixed before either implementation runs. No output field is removed.
    performance: { now: () => 1000 }, navigator: { hardwareConcurrency: 2 },
    importScripts() {}, postMessage: m => messages.push(m), ort: { env: { wasm: {} } },
    LightForgeAnalysisStore: { open: async () => ({
      read: async name => {
        assert.equal(name, 'bass');
        return cached === null ? null : structuredClone(cached);
      },
      write: async (name, value) => writes.push([name, structuredClone(value)])
    }) },
    LightForgeStemCache: { readers: async () => ({ accompaniment: {} }) },
    LightForgeBass: { analyze: async () => structuredClone(bassEvidence) },
    LightForgeWavReader: class {
      constructor() { this.duration = actual.duration; this.samples = actual.stemCache.fullSamples; }
      async open() {}
    },
    fetch: async url => ({ json: async () => String(url).endsWith('features.json') ? {} : models })
  });
  context.self = context;
  context.location = { href: 'https://app.test/analysis/worker.js' };
  vm.runInContext(source, context);
  await context.onmessage({ data: {
    stage: 'bass', audioUrl: '/song.wav', value: structuredClone(input),
    options: { workId: 'a'.repeat(64), analysisQuality: 'precision' }
  } });
  const final = messages.at(-1);
  assert.equal(final.type, 'result', JSON.stringify(final));
  return { value: JSON.parse(JSON.stringify(final.value)), writes, restored: final.restored };
}
async function main() {
  fs.mkdirSync(out, { recursive: true });
  const before = sourcePaths.map(p => binding(repo, p));
  const oldBinding = binding(baseline, workerPath);
  const oldSource = read(path.join(baseline, workerPath)).toString('utf8');
  const newSource = read(path.join(repo, workerPath)).toString('utf8');
  const actual = JSON.parse(read(path.join(repo, fixturePath)));
  const models = JSON.parse(read(path.join(repo, 'web/analysis/models/model-manifest.json')));
  assert.ok(actual.vocals && Array.isArray(actual.bassNotes) && actual.bassAnalysis && actual.duration > 0);
  // Retain the model's measured evidence. Remove only worker-added annotations
  // from the archived completed bass result to reconstruct its analyzer return.
  const bassEvidence = { ...structuredClone(actual.bassAnalysis), notes: structuredClone(actual.bassNotes) };
  delete bassEvidence.source;
  delete bassEvidence.sourceSeparated;
  bassEvidence.limitations = (bassEvidence.limitations || []).filter(s => s !== 'Bass notes are estimated from combined accompaniment, not an isolated bass instrument.');
  const initial = beforeBass(actual);
  const oldFresh = await runWorker(oldSource, initial, bassEvidence, null, models, actual);
  const newFresh = await runWorker(newSource, initial, bassEvidence, null, models, actual);
  assert.deepEqual(newFresh.value, oldFresh.value);
  assert.deepEqual(newFresh.writes.map(([name, value]) => [name, Object.keys(value).sort()]), [['bass', ['bassAnalysis', 'bassNotes']]]);
  const edited = beforeBass(actual);
  edited.bpm = 123;
  edited.beats = [.125, .613, 1.101];
  edited.sections = [{ start: 0, end: actual.duration, label: 'new rhythm', energy: .4 }];
  edited.warnings = ['current rhythm warning'];
  const oldEdited = await runWorker(oldSource, edited, bassEvidence, null, models, actual);
  const newEdited = await runWorker(newSource, edited, bassEvidence, null, models, actual);
  const restored = await runWorker(newSource, edited, bassEvidence, newFresh.writes[0][1], models, actual);
  const staleFull = { ...structuredClone(oldFresh.value), bpm: 77, beats: [0], warnings: ['stale rhythm warning'] };
  const restoredLegacy = await runWorker(newSource, edited, bassEvidence, staleFull, models, actual);
  const outputs = { oldFresh, newFresh, oldEdited, newEdited, restored, restoredLegacy };
  const comparisons = [];
  for (const [left, right, purpose] of [
    ['oldFresh', 'newFresh', 'Fresh finalization preserves every output field'],
    ['oldEdited', 'newEdited', 'Fresh finalization preserves edited rhythm'],
    ['oldEdited', 'restored', 'Bass-only cache preserves current rhythm and exact final metadata'],
    ['oldEdited', 'restoredLegacy', 'Legacy full-result cache cannot replace current rhythm or warnings']
  ]) {
    assert.deepEqual(outputs[left].value, outputs[right].value);
    const leftBytes = Buffer.from(JSON.stringify(outputs[left].value));
    const rightBytes = Buffer.from(JSON.stringify(outputs[right].value));
    assert.equal(Buffer.compare(leftBytes, rightBytes), 0);
    comparisons.push({ left, right, purpose, passed: true, byteIdentical: true, bytes: leftBytes.length, sha256: sha256(leftBytes) });
  }
  assert.equal(restored.restored, true);
  assert.equal(restoredLegacy.restored, true);
  assert.equal(restored.writes.length, 0);
  assert.equal(restoredLegacy.writes.length, 0);
  assert.ok(restored.value.warnings.includes('current rhythm warning'));
  assert.ok(!restored.value.warnings.includes('stale rhythm warning'));
  const test = spawnSync(process.execPath, ['--test', recoveryTestPath], { cwd: repo, encoding: 'utf8' });
  const testLog = (test.stdout || '') + (test.stderr || '');
  fs.writeFileSync(path.join(out, 'recovery-tests.log'), testLog);
  assert.equal(test.status, 0, testLog);
  const count = name => {
    const match = testLog.match(new RegExp('(?:# |ℹ )' + name + '\\s+(\\d+)'));
    assert.ok(match, 'Missing test count: ' + name);
    return Number(match[1]);
  };
  const testCounts = Object.fromEntries(['tests', 'pass', 'fail', 'cancelled', 'skipped', 'todo'].map(name => [name, count(name)]));
  assert.ok(testCounts.tests >= 22, 'Original recovery cases must remain included');
  assert.equal(testCounts.pass, testCounts.tests);
  for (const name of ['fail', 'cancelled', 'skipped', 'todo']) assert.equal(testCounts[name], 0);
  const after = sourcePaths.map(p => binding(repo, p));
  assert.deepEqual(after, before, 'Production source changed during verification');
  assert.deepEqual(binding(baseline, workerPath), oldBinding, 'Baseline changed during verification');
  fs.writeFileSync(path.join(out, 'baseline-worker.js'), oldSource);
  fs.writeFileSync(path.join(out, 'candidate-worker.js'), newSource);
  for (const [name, result] of Object.entries(outputs)) fs.writeFileSync(path.join(out, name + '.json'), JSON.stringify(result.value));
  const scriptBytes = read(__filename);
  const receipt = {
    schemaVersion: 1, generatedAt: new Date().toISOString(), passed: true,
    claim: 'Worker finalization and restored role-cache composition preserve exact music JSON for the archived Falcon evidence and an explicit rhythm edit.',
    limits: [
      'Model inference and PCM decoding are stubbed; this validates composition and persistence behavior, not model numerical parity.',
      'Clock fixed at 1000 ms for both implementations; no output field is omitted from comparisons.',
      'No physical-device timing or first-analysis performance claim is made.',
      'Execution identity remains the advertised native/WASM route, as in the baseline; actual fallback and WebView/thread fingerprints are not added by this patch.'
    ],
    runtime: { node: process.version, platform: process.platform, arch: process.arch },
    command: ['node', 'compare-finalization.cjs', repo, baseline, out],
    harness: { file: path.basename(__filename), bytes: scriptBytes.length, sha256: sha256(scriptBytes) },
    baseline: { root: baseline, worker: oldBinding, snapshot: 'baseline-worker.js' },
    candidate: { root: repo, sources: before, snapshot: 'candidate-worker.js' },
    sourceUnchangedDuringVerification: true,
    comparisons,
    newBassCheckpointKeys: Object.keys(newFresh.writes[0][1]).sort(),
    recoveryTests: { command: [process.execPath, '--test', recoveryTestPath], exitCode: test.status, ...testCounts, log: { file: 'recovery-tests.log', bytes: Buffer.byteLength(testLog), sha256: sha256(Buffer.from(testLog)) } }
  };
  fs.writeFileSync(path.join(out, 'verification.json'), JSON.stringify(receipt, null, 2) + '\n');
  console.log(JSON.stringify({ passed: true, comparisons: comparisons.length, recoveryTests: testCounts, receipt: path.join(out, 'verification.json') }));
}
main().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
