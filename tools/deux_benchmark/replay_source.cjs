#!/usr/bin/env node
'use strict';
// Research only. Model inference is forbidden here. All audio arithmetic, binary
// checkpoints and stem-cache verification execute the unchanged production files.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const ROOT = path.resolve(__dirname, '../..');
const RATE = 44100, SAMPLES = 573300, HALO = 66150, CORE = 441000, STRIDE = 220500;
const PUBLIC_AUDIO_SHA256 = '33f07d502ba19832b62b97d8fb4a11354e81310264bd885d7a06438228773650';
const SHA = /^[a-f0-9]{64}$/;
const MODULES = ['dsp.js', 'wav-reader.js', 'work-store.js', 'stem-cache.js', 'separator-deux.js'];
const REQUIRED_SOURCES = [...MODULES.map(n => 'web/analysis/' + n),
  'web/analysis/models/features.json', 'web/analysis/models/deux/manifest.json',
  'android/src/com/cyberbasslord/lightforge/NativeDeux.java',
  'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java',
  'android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java', 'android/native-runtime.json',
  'tools/benchmark_deux_source_cuda.py', 'tools/deux_benchmark/DeuxSourceRunner.java',
  'tools/benchmark_deux_accelerator.py', 'tools/benchmark_deux_execution.py',
  'tools/profile_deux_operators.py', 'tools/deux_benchmark/replay_source.cjs'];
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const plain = value => JSON.parse(JSON.stringify(value));
const asArrayBuffer = bytes => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
const check = (value, message) => { if (!value) throw Error(message); };

function encodeFloats(values) {
  const bytes = Buffer.alloc(values.length * 4);
  for (let i = 0; i < values.length; i++) {
    check(Number.isFinite(values[i]), 'Nonfinite captured PCM'); bytes.writeFloatLE(values[i], i * 4);
  }
  return bytes;
}
function decodeCaptured(bytes) {
  check(Buffer.isBuffer(bytes) && bytes.length === SAMPLES * 8, 'Complete two-stem passage required');
  const values = new Float32Array(SAMPLES * 2);
  for (let i = 0; i < values.length; i++) {
    values[i] = bytes.readFloatLE(i * 4); check(Number.isFinite(values[i]), 'Nonfinite captured PCM');
  }
  return {vocals: values.slice(0, SAMPLES), accompaniment: values.slice(SAMPLES)};
}
function planPassages(total) {
  check(Number.isSafeInteger(total) && total >= RATE && total <= RATE * 64, 'Invalid complete source length');
  const plan = [];
  for (let start = 0; start < total; start += STRIDE) {
    const last = start + CORE >= total;
    plan.push({index: plan.length, startSample: start - HALO, outputOffset: start,
      emitSamples: last ? total - start : STRIDE});
    if (last) break;
  }
  return plan;
}
function checkedFile(base, relative, expected) {
  check(typeof relative === 'string' && relative && !path.isAbsolute(relative) &&
    !relative.split(/[\\/]/).some(x => !x || x === '.' || x === '..') && SHA.test(expected), 'Invalid bound file identity');
  base = fs.realpathSync(base);
  const full = fs.realpathSync(path.join(base, relative));
  check(full.startsWith(base + path.sep) && fs.statSync(full).isFile(), 'Bound file escapes evidence directory');
  const bytes = fs.readFileSync(full); check(hash(bytes) === expected, 'Bound file digest mismatch: ' + relative);
  return bytes;
}
function validateSources(hashes) {
  check(hashes && typeof hashes === 'object' && !Array.isArray(hashes), 'Missing source hashes');
  for (const required of REQUIRED_SOURCES) check(SHA.test(hashes[required]), 'Missing required source: ' + required);
  for (const [name, digest] of Object.entries(hashes)) checkedFile(ROOT, name, digest);
}

// This adapter implements only the File System Access operations used by the
// original store. A write is invisible until close. Restart copies committed file
// bytes into new handles and a fresh JS realm, never checkpoint objects.
function memoryDisk(snapshot = []) {
  const missing = () => new DOMException('Missing', 'NotFoundError');
  const validName = name => check(typeof name === 'string' && name && !/[\\/]/.test(name) && name !== '.' && name !== '..', 'Invalid storage name');
  class FileHandle {
    constructor(bytes = Buffer.alloc(0)) { this.kind = 'file'; this.data = Buffer.from(bytes); }
    async getFile() { const blob = new Blob([this.data]); blob.lastModified = 0; return blob; }
    async createWritable() {
      const file = this, parts = []; let closed = false;
      return {
        async write(value) { check(!closed, 'Write after close'); parts.push(Buffer.from(typeof value === 'string' ? value : value instanceof ArrayBuffer ? new Uint8Array(value) : value)); },
        async close() { check(!closed, 'Double close'); file.data = Buffer.concat(parts); closed = true; },
        async abort() { closed = true; },
      };
    }
  }
  class Directory {
    constructor() { this.kind = 'directory'; this.children = new Map(); }
    get(name, kind, create) {
      validName(name);
      if (!this.children.has(name)) { if (!create) throw missing(); this.children.set(name, kind === 'file' ? new FileHandle() : new Directory()); }
      const value = this.children.get(name); check(value.kind === kind, 'Wrong storage entry type'); return value;
    }
    async getDirectoryHandle(name, {create = false} = {}) { return this.get(name, 'directory', create); }
    async getFileHandle(name, {create = false} = {}) { return this.get(name, 'file', create); }
    async removeEntry(name) { validName(name); if (!this.children.delete(name)) throw missing(); }
    async *entries() { yield* [...this.children.entries()]; }
  }
  const directory = new Directory();
  for (const item of snapshot) {
    const names = item.path.split('/'); let parent = directory;
    for (const name of names.slice(0, -1)) parent = parent.get(name, 'directory', true);
    check(!parent.children.has(names.at(-1)), 'Duplicate storage snapshot path');
    validName(names.at(-1)); parent.children.set(names.at(-1), new FileHandle(item.bytes));
  }
  function takeSnapshot(dir = directory, prefix = '') {
    return [...dir.children.entries()].sort(([a], [b]) => a.localeCompare(b)).flatMap(([name, value]) =>
      value.kind === 'file' ? [{path: prefix + name, bytes: Buffer.from(value.data)}] : takeSnapshot(value, prefix + name + '/'));
  }
  return {directory, snapshot: takeSnapshot,
    storage: {getDirectory: async () => directory, estimate: async () => ({quota: 8 * 1024 ** 3, usage: 0})}};
}

function productionContext(disk, manifest) {
  const context = vm.createContext({crypto: crypto.webcrypto, TextEncoder, TextDecoder, ArrayBuffer, DataView,
    Uint8Array, Uint32Array, Float32Array, Float64Array, Blob, DOMException, URL, setTimeout, clearTimeout,
    navigator: {storage: disk.storage}, Date: {now: () => 0}, performance: {now: () => 0},
    fetch: async url => { check(String(url) === 'https://captured.invalid/manifest.json', 'Unexpected replay fetch'); return {json: async () => plain(manifest)}; }});
  context.self = context;
  for (const name of MODULES) vm.runInContext(fs.readFileSync(path.join(ROOT, 'web/analysis', name), 'utf8'), context, {filename: name});
  return context;
}
async function openReader(context, audioBytes) {
  const reader = new context.LightForgeWavReader('public-fixture://source');
  reader.cached = asArrayBuffer(audioBytes); reader.totalBytes = audioBytes.length; await reader.open();
  check(reader.rate === RATE && reader.channels === 2 && reader.format === 1 && reader.bits === 16, 'Expected original stereo PCM16 WAV');
  return reader;
}
function snapshotInventory(snapshot) {
  return snapshot.map(item => ({path: item.path, bytes: item.bytes.length, sha256: hash(item.bytes)}));
}
function stemKeyFor(key) { return 'stem-' + [key.slice(0, 8), key.slice(8, 12), key.slice(12, 16), key.slice(16, 20), key.slice(20, 32)].join('-'); }

async function executeConsumer({audioBytes, captures, manifest, config, identity, snapshot = [], stopBefore = null}) {
  const disk = memoryDisk(snapshot), context = productionContext(disk, manifest), reader = await openReader(context, audioBytes);
  const plan = planPassages(reader.samples);
  check(captures.length === plan.length, 'All canonical passages are required');
  const key = await context.LightForgeAnalysisStore.contentAddress('deux-research-source', identity);
  const stemKey = stemKeyFor(key), sourceId = hash(audioBytes);
  const store = await context.LightForgeAnalysisStore.open(key, {sourceId});
  const writer = await context.LightForgeStemCache.create(stemKey, reader.samples, config, sourceId);
  const calls = [], reads = [], chunks = [], progress = [], stop = new Error('Controlled passage interruption');
  let separator, result, metadata, interrupted = false;
  try {
    separator = await context.LightForgeDeux.create({baseUrl: 'https://captured.invalid/', checkpoint: store,
      ort: {InferenceSession: {create() { throw Error('Replay cannot execute model inference'); }}},
      nativePredict: async start => {
        const index = plan.findIndex(p => p.startSample === start);
        check(index >= 0 && !calls.includes(index), 'Unexpected or duplicate native callback');
        if (index === stopBefore) throw stop;
        calls.push(index); return decodeCaptured(captures[index]);
      }});
    result = await separator.process(async (start, count) => {
      const expected = plan[reads.length]; check(expected && start === expected.startSample && count === SAMPLES, 'Unexpected production source read');
      const stereo = await reader.stereo44100(start, count);
      let peak = 0; for (const channel of stereo) for (const value of channel) peak = Math.max(peak, Math.abs(value));
      check(peak >= 1e-7, 'Silent passage outside the all-capture replay contract');
      reads.push({startSample: start, samples: count, stereoPcmSha256: hash(Buffer.concat(stereo.map(encodeFloats)))});
      return stereo;
    }, reader.samples, async chunk => {
      const expected = plan[chunks.length];
      check(expected && chunk.startSample === expected.outputOffset && chunk.vocals.length === expected.emitSamples &&
        chunk.accompaniment.length === expected.emitSamples && chunk.sampleRate === RATE, 'Production chunk clock mismatch');
      chunks.push({index: chunks.length, startSample: chunk.startSample, samples: chunk.vocals.length,
        vocalsSha256: hash(encodeFloats(chunk.vocals)), accompanimentSha256: hash(encodeFloats(chunk.accompaniment))});
      await writer.append(chunk);
    }, value => progress.push(plain(value)));
    metadata = plain(await writer.finish());
  } catch (error) {
    if (error !== stop) { await writer.abort(); throw error; }
    interrupted = true; await writer.abort();
  } finally { await separator?.release(); }
  if (interrupted) {
    check(stopBefore > 0 && calls.length === stopBefore && chunks.length === stopBefore, 'Interruption did not retain the expected prefix');
    const saved = disk.snapshot();
    check(!saved.some(item => item.path.endsWith('/complete.json')), 'Interrupted stem cache was committed');
    const checkpoints = saved.filter(item => /\/deux-\d+\.bin$/.test(item.path));
    check(checkpoints.length === stopBefore, 'Interrupted checkpoint prefix is incomplete');
    return {interrupted: true, calls, reads, chunks, checkpointKey: key, snapshot: saved,
      checkpointFiles: snapshotInventory(checkpoints)};
  }
  check(result.chunks === plan.length && chunks.length === plan.length && reads.length === plan.length, 'Incomplete production replay');
  check(result.runtime === 'onnxruntime-android-cpu', 'Production adapter label changed');
  const saved = disk.snapshot();
  // A fresh realm must read byte-persisted metadata and verify all three files.
  const reopenedDisk = memoryDisk(saved), reopened = productionContext(reopenedDisk, manifest);
  const files = await reopened.LightForgeStemCache.files(metadata);
  const readers = await reopened.LightForgeStemCache.readers(metadata);
  const fullVoice = await reopened.LightForgeStemCache.fullVoice(metadata);
  const fullParts = [];
  for (let start = 0; start < reader.samples; start += RATE * 8) fullParts.push(encodeFloats(await fullVoice(start, Math.min(RATE * 8, reader.samples - start))));
  const stems = {};
  for (const role of ['vocals', 'accompaniment']) {
    const bytes = Buffer.from(await files[role].arrayBuffer());
    const decoded = [];
    for (let start = 0; start < metadata.samples; start += 22050 * 8) decoded.push(encodeFloats(await readers[role].mono22050(start, Math.min(22050 * 8, metadata.samples - start), config)));
    check(bytes.subarray(44).equals(Buffer.concat(decoded)), 'Verified stem reader altered stored Float32 samples');
    stems[role + '.wav'] = bytes;
  }
  const fullFile = saved.find(item => item.path === 'lightforge-stems-v1/' + stemKey + '/voice-full.wav');
  check(fullFile && fullFile.bytes.subarray(44).equals(Buffer.concat(fullParts)), 'Verified full-voice reader altered original Float32 samples');
  stems['voice-full.wav'] = fullFile.bytes;
  for (const [name, bytes] of Object.entries(stems)) check(metadata.files[name].bytes === bytes.length && metadata.files[name].sha256 === hash(bytes), 'Stem completion integrity mismatch');
  const checkpoints = saved.filter(item => /\/deux-\d+\.bin$/.test(item.path));
  check(checkpoints.length === plan.length, 'Incomplete checkpoint set');
  return {interrupted: false, calls, reads, chunks, result: plain(result), metadata, stems,
    checkpointKey: key, checkpointFiles: snapshotInventory(checkpoints), snapshot: saved,
    completeVoicePcmSha256: hash(fullFile.bytes.subarray(44)), verifiedStemReaders: true};
}

async function replayArm({audioBytes, captures, manifest, config, identity, stopBefore = 6}) {
  // The interrupted run stops before its next measured native callback. Resume
  // restarts the production consumer, reconstructs pending overlap from saved
  // checkpoints, and consumes only the remaining measured captures.
  const fresh = await executeConsumer({audioBytes, captures, manifest, config, identity});
  const interrupted = await executeConsumer({audioBytes, captures, manifest, config, identity, stopBefore});
  const resumed = await executeConsumer({audioBytes, captures, manifest, config, identity, snapshot: interrupted.snapshot});
  const allRestored = await executeConsumer({audioBytes, captures, manifest, config, identity, snapshot: fresh.snapshot});
  assert.deepEqual(fresh.calls, Array.from({length: captures.length}, (_, i) => i));
  assert.deepEqual(resumed.calls, fresh.calls.slice(stopBefore)); assert.deepEqual(allRestored.calls, []);
  check(resumed.result.restoredPassages === stopBefore && allRestored.result.restoredPassages === captures.length, 'Production checkpoint restore count mismatch');
  assert.deepEqual(resumed.chunks, fresh.chunks, 'Interrupted-resumed overlap differs');
  assert.deepEqual(allRestored.chunks, fresh.chunks, 'Checkpoint-only overlap differs');
  assert.deepEqual(resumed.checkpointFiles, fresh.checkpointFiles, 'Resumed checkpoint bytes differ');
  for (const name of Object.keys(fresh.stems)) {
    check(fresh.stems[name].equals(resumed.stems[name]), 'Interrupted-resumed stem differs: ' + name);
    check(fresh.stems[name].equals(allRestored.stems[name]), 'Checkpoint-only stem differs: ' + name);
  }
  return {stems: fresh.stems, report: {
    researchExecutionIdentity: plain(identity), checkpointKey: fresh.checkpointKey,
    productionResult: fresh.result, metadata: fresh.metadata, chunks: fresh.chunks, sourceReads: fresh.reads,
    checkpointFiles: fresh.checkpointFiles, completeVoicePcmSha256: fresh.completeVoicePcmSha256,
    freshCallbackIndices: fresh.calls, interruption: {beforePassage: stopBefore, committedPassages: interrupted.calls.length,
      committedCheckpointFiles: interrupted.checkpointFiles, completeStemCacheCommitted: false},
    resumedCallbackIndices: resumed.calls, restoredPassages: resumed.result.restoredPassages,
    checkpointOnlyCallbackIndices: allRestored.calls, checkpointOnlyRestoredPassages: allRestored.result.restoredPassages,
    interruptedResumeStemBytesIdentical: true, checkpointOnlyStemBytesIdentical: true,
    verifiedStemReaders: true,
    runtimeLabel: {value: fresh.result.runtime, meaning: 'Unchanged production native adapter label; actual captured execution identity is recorded separately.'},
    storageAdapter: 'Atomic-close in-memory File System Access adapter; restart reopens copied committed bytes in a fresh realm. This does not test physical OPFS durability or device lifecycle.',
    replayClock: 'Fixed zero research clock for reproducible metadata; production analysisSeconds is not a measured duration.'}};
}

function comparePcm(left, right) {
  check(left.length === right.length && left.length % 4 === 0, 'PCM comparison length mismatch');
  let changedSamples = 0, maxAbsoluteDifference = 0, squared = 0;
  for (let i = 0; i < left.length; i += 4) {
    const a = left.readFloatLE(i), b = right.readFloatLE(i); check(Number.isFinite(a) && Number.isFinite(b), 'Nonfinite compared PCM');
    const difference = Math.abs(a - b); if (difference !== 0) changedSamples++;
    maxAbsoluteDifference = Math.max(maxAbsoluteDifference, difference); squared += difference * difference;
  }
  return {samples: left.length / 4, byteIdentical: left.equals(right), changedSamples,
    maxAbsoluteDifference, rmsDifference: Math.sqrt(squared / (left.length / 4)),
    signedZeroDifferencesIncludedByByteIdentity: true, rule: 'Exact equality and descriptive deltas only; no equivalence tolerance.'};
}

function captureScope(receipt) {
  const cpuOnly = receipt.status === 'CPU_SOURCE_DIAGNOSTIC_COMPLETE';
  const variants = cpuOnly ? ['cpu_all'] : ['cpu_all', 'cuda_basic'];
  check(receipt.schema === 'lightforge.deux-source-cuda-experiment.v1' &&
    ['CPU_SOURCE_DIAGNOSTIC_COMPLETE', 'COMPLETE_DIAGNOSTIC', 'NUMERICAL_EQUIVALENCE_UNPROVEN'].includes(receipt.status), 'Incomplete or rejected complete-source experiment');
  assert.deepEqual(receipt.variants, variants, 'Unexpected execution variants');
  assert.deepEqual(receipt.modes, ['plain', 'profiled'], 'Unexpected observer modes');
  assert.deepEqual(Object.keys(receipt.executionIdentity || {}).sort(), variants.slice().sort(), 'Unexpected execution identity arms');
  if (cpuOnly) check(receipt.gpuRuntime === null && receipt.rawOutputsByteIdenticalAcrossVariants === null &&
    Array.isArray(receipt.crossVariantComparisons) && receipt.crossVariantComparisons.length === 0,
  'CPU-only scope contains a cross-provider result');
  return {cpuOnly, variants};
}
function bindExperiment(evidenceDirectory, audioFile) {
  const receiptFile = path.join(evidenceDirectory, 'receipt.json');
  const receiptBytes = fs.readFileSync(receiptFile), receipt = JSON.parse(receiptBytes);
  const {cpuOnly, variants} = captureScope(receipt);
  check(receipt.observerComparisonsPassed === true && receipt.inputsRecheckedAfterQualification === true &&
    receipt.allInputAndArtifactHashesRechecked === true, 'Unverified experiment bindings or observers');
  for (const key of ['qualityApproved', 'benchmarkTimingAdmitted', 'target75Proven', 'releaseAuthorized',
    'wholeSongSpeedupProven', 'fullVocalStageSpeedupProven', 'androidSpeedupProven'])
    check(receipt[key] === false, 'Unexpected approval in research experiment: ' + key);
  validateSources(receipt.sourceHashes);
  const audioBytes = fs.readFileSync(audioFile);
  check(receipt.audioSha256 === PUBLIC_AUDIO_SHA256 && hash(audioBytes) === PUBLIC_AUDIO_SHA256 &&
    receipt.audioFrames === 64 * RATE, 'Only the complete pinned public WAV is accepted');
  const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, 'web/analysis/models/deux/manifest.json')));
  const config = JSON.parse(fs.readFileSync(path.join(ROOT, 'web/analysis/models/features.json')));
  check(receipt.modelManifestSha256 === receipt.sourceHashes['web/analysis/models/deux/manifest.json'], 'Model manifest source binding differs');
  assert.deepEqual(receipt.modelHashes, Object.fromEntries(Object.entries(manifest.files).map(([name, info]) => [name, info.sha256])), 'Original graph identities differ');
  check(receipt.runtimeVersion === '1.25.1' && receipt.cublasWorkspaceConfig === ':4096:8' && receipt.nvidiaTf32Override === '0', 'Qualified runtime environment differs');
  assert.deepEqual(receipt.cudaOptions, cpuOnly ? null : {use_tf32: '0', do_copy_in_default_stream: '1', enable_cuda_graph: '0', enable_skip_layer_norm_strict_mode: '1'}, 'Qualified CUDA options differ');
  for (const variant of variants) {
    const gpu = variant === 'cuda_basic';
    assert.deepEqual(receipt.executionIdentity?.[variant], {runtime: 'onnxruntime-java-1.25.1', package: gpu ? 'gpu' : 'cpu',
      provider: gpu ? 'CUDAExecutionProvider' : 'CPUExecutionProvider', optimization: gpu ? 'BASIC_OPT' : 'ALL_OPT',
      deterministicComputeOverride: null,
      deterministicComputeNote: 'Unchanged runtime default, matching the qualified Deux snapshot; no universal kernel determinism guarantee.'},
    'Qualified execution identity differs');
    const placements = receipt.placement?.[variant];
    check(Array.isArray(placements) && placements.length === 12, 'Incomplete source-bound placement evidence');
    for (let i = 0; i < placements.length; i++) {
      const placement = placements[i];
      check(placement.passageIndex === i && placement.allGraphsExecuteCudaArithmetic === gpu &&
        Array.isArray(placement.observedProviders) && placement.observedProviders.length > 0 &&
        placement.observedProviders.every(p => p === 'CPUExecutionProvider' || gpu && p === 'CUDAExecutionProvider') &&
        (!gpu || placement.observedProviders.includes('CUDAExecutionProvider')), 'Recorded provider placement differs');
    }
  }
  const plan = planPassages(receipt.audioFrames);
  check(Array.isArray(receipt.passagePlan) && receipt.passagePlan.length === plan.length, 'Incomplete passage plan');
  for (const [i, expected] of plan.entries()) {
    for (const [key, value] of Object.entries(expected)) check(receipt.passagePlan[i][key] === value, 'Passage plan differs: ' + key);
    check(SHA.test(receipt.passagePlan[i].inputStereoSha256), 'Missing original stereo input proof');
  }
  const labels = variants.flatMap(variant => [variant + '_plain', variant + '_profiled']);
  check(Array.isArray(receipt.runs) && receipt.runs.length === labels.length, 'Incomplete selected run matrix');
  const captures = {}, bindings = {};
  for (const [runIndex, label] of labels.entries()) {
    const row = receipt.runs[runIndex], variant = label.startsWith('cpu') ? 'cpu_all' : 'cuda_basic';
    const observation = label.endsWith('_profiled') ? 'profiled' : 'plain';
    check(row.label === label && row.variant === variant && row.observation === observation &&
      row.provider === (variant === 'cpu_all' ? 'CPUExecutionProvider' : 'CUDAExecutionProvider') && row.outputDirectory === label,
    'Run execution identity differs');
    const runFile = label + '/receipt.json', runBytes = checkedFile(evidenceDirectory, runFile, receipt.artifactHashes?.[runFile]);
    const run = JSON.parse(runBytes);
    check(run.schema === 'lightforge-deux-source-run-1' && run.runtime === 'onnxruntime-java-1.25.1' &&
      run.sampleRate === RATE && run.audioFrames === receipt.audioFrames && run.audioSha256 === receipt.audioSha256 &&
      run.passageCount === plan.length && run.profiled === (observation === 'profiled') && run.engineObjects === 1 &&
      run.engineCloseReturned === true && run.allPredictionsReturned === true &&
      Number.isSafeInteger(run.wallNanos) && run.wallNanos > 0, 'Invalid complete-source Java run receipt');
    for (const key of ['qualityApproved', 'benchmarkTimingAdmitted', 'target75Proven', 'releaseAuthorized'])
      check(run[key] === false, 'Unexpected Java run approval');
    assert.deepEqual(run.modelFiles, manifest.files, 'Original model inventory differs');
    check(Array.isArray(run.passages) && run.passages.length === plan.length && Array.isArray(row.passages) && row.passages.length === plan.length,
      'Incomplete passage receipt matrix');
    captures[label] = []; bindings[label] = [];
    for (const [i, expected] of plan.entries()) {
      const passage = run.passages[i];
      for (const [key, value] of Object.entries(expected)) check(passage[key] === value && row.passages[i][key] === value, 'Captured passage schedule differs');
      const directory = label + '/passage-' + String(i).padStart(3, '0');
      const passageFile = directory + '/receipt.json';
      const passageBytes = checkedFile(evidenceDirectory, passageFile, receipt.artifactHashes?.[passageFile]);
      assert.deepEqual(JSON.parse(passageBytes), passage, 'Nested passage receipt differs');
      check(passage.schema === 'lightforge-deux-source-passage-1' && passage.sampleRate === RATE && passage.samplesPerStem === SAMPLES &&
        passage.sourceSamples === receipt.audioFrames && passage.sourceSha256 === receipt.audioSha256 &&
        passage.inputStereoSha256 === receipt.passagePlan[i].inputStereoSha256 &&
        passage.outputFile === 'passage-' + String(i).padStart(3, '0') + '/stems.f32' && passage.outputBytes === SAMPLES * 8 &&
        passage.profiled === (observation === 'profiled') && passage.predictReturned === true && passage.benchmarkTimingAdmitted === false,
      'Invalid captured passage binding');
      for (const key of ['outputFile', 'outputBytes', 'outputSha256', 'inputStereoSha256'])
        check(row.passages[i][key] === passage[key], 'Top-level passage binding differs: ' + key);
      const outputFile = label + '/' + passage.outputFile;
      check(receipt.artifactHashes?.[outputFile] === passage.outputSha256, 'Capture absent from completed artifact inventory');
      const bytes = checkedFile(evidenceDirectory, outputFile, passage.outputSha256); decodeCaptured(bytes);
      check(bytes.length === passage.outputBytes, 'Truncated capture');
      captures[label].push(bytes); bindings[label].push({file: outputFile, bytes: bytes.length, sha256: hash(bytes),
        receiptFile: passageFile, receiptSha256: hash(passageBytes)});
    }
  }
  check(Array.isArray(receipt.observerComparisons) && receipt.observerComparisons.length === plan.length * variants.length, 'Incomplete observer comparisons');
  for (const variant of variants) for (let i = 0; i < plan.length; i++) {
    const rows = receipt.observerComparisons.filter(row => row.variant === variant && row.passageIndex === i);
    check(rows.length === 1 && rows[0].reference === variant + '_plain' && rows[0].candidate === variant + '_profiled' &&
      rows[0].byteIdentical === true, 'Unqualified passage observer');
    check(captures[variant + '_plain'][i].equals(captures[variant + '_profiled'][i]), 'Independently checked observer bytes differ');
  }
  return {receiptFile, receiptBytes, receipt, cpuOnly, variants, audioBytes, manifest, config, captures, bindings};
}

async function replaySource(evidenceDirectory, audioFile, outputDirectory) {
  const input = bindExperiment(evidenceDirectory, audioFile);
  check(!fs.existsSync(outputDirectory), 'Output directory already exists');
  fs.mkdirSync(outputDirectory, {recursive: false});
  const arms = {}, stems = {}, outputFiles = {};
  for (const variant of input.variants) {
    // Distinct source-bound cache namespaces prevent a CUDA capture from
    // masquerading as an Android CPU cache hit.
    const identity = {schema: 'lightforge-deux-capture-consumer-identity-1',
      sourceSha256: input.receipt.audioSha256, modelManifestSha256: input.receipt.modelManifestSha256,
      execution: {...input.receipt.executionIdentity[variant], variant,
        sourceCaptureReceiptSha256: hash(input.receiptBytes)},
      sourceHashes: input.receipt.sourceHashes, outputCaptures: input.bindings[variant + '_plain']};
    const replay = await replayArm({audioBytes: input.audioBytes, captures: input.captures[variant + '_plain'],
      manifest: input.manifest, config: input.config, identity, stopBefore: 6});
    for (let i = 0; i < replay.report.sourceReads.length; i++) check(replay.report.sourceReads[i].stereoPcmSha256 === input.receipt.passagePlan[i].inputStereoSha256,
      'Original production WavReader disagrees with captured native source bytes');
    arms[variant] = replay.report; stems[variant] = replay.stems;
    fs.mkdirSync(path.join(outputDirectory, variant));
    for (const [name, bytes] of Object.entries(replay.stems)) {
      const relative = variant + '/' + name;
      fs.writeFileSync(path.join(outputDirectory, relative), bytes, {flag: 'wx'});
      outputFiles[relative] = {...replay.report.metadata.files[name]};
    }
  }
  const comparison = input.cpuOnly ? null : Object.fromEntries(Object.keys(stems.cpu_all).map(name => [name,
    comparePcm(stems.cpu_all[name].subarray(44), stems.cuda_basic[name].subarray(44))]));
  validateSources(input.receipt.sourceHashes);
  check(hash(fs.readFileSync(input.receiptFile)) === hash(input.receiptBytes) && hash(fs.readFileSync(audioFile)) === input.receipt.audioSha256,
    'Input changed during production replay');
  check(input.receipt.artifactHashes && Object.keys(input.receipt.artifactHashes).length > 0, 'Missing artifact inventory');
  for (const [relative, digest] of Object.entries(input.receipt.artifactHashes)) checkedFile(evidenceDirectory, relative, digest);
  // Attest the persisted artifact, not just the pre-write in-memory buffer.
  for (const [relative, descriptor] of Object.entries(outputFiles)) {
    const stat = fs.lstatSync(path.join(outputDirectory, relative));
    check(stat.isFile() && !stat.isSymbolicLink() && stat.size === descriptor.bytes, 'Written stem type or size differs');
    check(checkedFile(outputDirectory, relative, descriptor.sha256).length === descriptor.bytes, 'Written stem bytes differ');
  }
  const output = {schema: 'lightforge-deux-source-consumer-replay-1', status: input.cpuOnly ? 'CPU_SOURCE_CONSUMER_DIAGNOSTIC_COMPLETE' : 'COMPLETE_DIAGNOSTIC',
    experimentReceiptSha256: hash(input.receiptBytes), sourceHashes: input.receipt.sourceHashes,
    audioSha256: input.receipt.audioSha256, audioSamples: input.receipt.audioFrames, passageCount: 12,
    variants: input.variants, gpuCaptureConsumed: !input.cpuOnly, crossProviderComparisonPerformed: !input.cpuOnly,
    outputFiles, persistedOutputBytesRechecked: true,
    observerComparisonsIndependentlyByteChecked: 12 * input.variants.length, arms, comparison,
    completeStemBytesIdentical: comparison === null ? null : Object.values(comparison).every(value => value.byteIdentical),
    checkpointResumeIdentical: true, originalProductionArithmetic: true, capturedInputSourceBytesRevalidated: true,
    fullVocalStageExecuted: false, qualityApproved: false, benchmarkTimingAdmitted: false,
    fullAnalysisQualityApproved: false, androidIntegrationApproved: false, target75Proven: false, releaseAuthorized: false,
    scope: 'Complete measured passage captures consumed by unchanged production Deux overlap, work-store binary checkpoints and stem-cache writers/readers. No new model inference.',
    limitations: ['Research CPU/CUDA execution identity remains separate from the original Android-CPU native adapter label.',
      'Synthetic interruption uses an atomic in-memory storage adapter; no physical Android storage or lifecycle claim.',
      'Provider placement is owned by the source-bound collector; replay verifies its retained files, not operator classification.',
      'Exact consumer comparisons are descriptive and do not approve numerical equivalence, musical quality, performance or release.',
      'No classifier, GAME-on-separated-voice, vocal fusion, bass, show generation, network transport or complete-analysis measurement is included.']};
  fs.writeFileSync(path.join(outputDirectory, 'receipt.json'), JSON.stringify(output, null, 2) + '\n', {flag: 'wx'});
  return output;
}

async function main() {
  check(process.argv.length === 5, 'Usage: replay_source.cjs completed-evidence-directory complete-public.wav new-output-directory');
  const result = await replaySource(...process.argv.slice(2));
  console.log(JSON.stringify({status: result.status, passageCount: result.passageCount, variants: result.variants,
    completeStemBytesIdentical: result.completeStemBytesIdentical, checkpointResumeIdentical: true,
    qualityApproved: false, benchmarkTimingAdmitted: false, target75Proven: false}));
  if (result.completeStemBytesIdentical === false) process.exitCode = 2;
}

module.exports = {RATE, SAMPLES, HALO, CORE, STRIDE, PUBLIC_AUDIO_SHA256, REQUIRED_SOURCES,
  hash, encodeFloats, decodeCaptured, planPassages, checkedFile, validateSources,
  memoryDisk, productionContext, executeConsumer, replayArm, comparePcm, captureScope, bindExperiment, replaySource};
if (require.main === module) main().catch(error => { console.error(error); process.exitCode = 1; });
