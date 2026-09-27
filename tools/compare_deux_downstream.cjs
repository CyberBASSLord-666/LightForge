#!/usr/bin/env node
'use strict';

/* Research-only consumer sensitivity check for an already captured Deux pair.
 * The actual separator emits its first five-second chunk from the full source;
 * the missing second passage stops replay. The downstream pipeline then treats
 * that emitted chunk as a bounded excerpt, not as a completed song. No app code,
 * GPU benchmark admission rule or publication gate is changed by this tool. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const {fileURLToPath, pathToFileURL} = require('node:url');

const ROOT = path.resolve(__dirname, '..');
const SAMPLES = 573300, HALO = 66150, CORE = 441000, STRIDE = 220500, RATE = 44100;
const VARIANTS = ['cpu_all', 'cuda_basic'];
const PUBLIC_AUDIO_SHA256 = '33f07d502ba19832b62b97d8fb4a11354e81310264bd885d7a06438228773650';
const COMPARATOR = 'qa/release-2.3.2/mdx-downstream-compare.cjs';
const SOURCE_NAMES = [
  'tools/compare_deux_downstream.cjs', COMPARATOR, 'web/analysis/ASSET_MANIFEST.json',
  'web/analysis/separator-deux.js', 'web/analysis/dsp.js', 'web/analysis/stem-cache.js',
  'web/analysis/wav-reader.js', 'web/analysis/vocal.js', 'web/analysis/vocal-detail.js',
  'web/analysis/game.js', 'web/analysis/worker.js',
  'web/analysis/models/features.json', 'web/analysis/models/vocal-model.json',
  'web/analysis/models/vocal-frontend.json', 'web/analysis/models/game/manifest.json',
  'web/analysis/models/deux/manifest.json',
];
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const fileSha = file => sha(fs.readFileSync(file));
const buffer = bytes => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
const json = value => JSON.stringify(value, (_, v) => ArrayBuffer.isView(v) ? Array.from(v) : v, 2) + '\n';
const load = file => JSON.parse(fs.readFileSync(file, 'utf8'));
function writeJson(file, value) { fs.writeFileSync(file, json(value), {flag: 'wx'}); }

function readCaptured(bytes) {
  assert.equal(bytes.length, 2 * SAMPLES * 4, 'Complete two-stem passage required');
  // Explicit little-endian decoding also works on big-endian hosts.
  const values = new Float32Array(2 * SAMPLES);
  for (let i = 0; i < values.length; i++) {
    values[i] = bytes.readFloatLE(i * 4);
    assert.ok(Number.isFinite(values[i]), 'Nonfinite captured PCM');
  }
  return {vocals: values.slice(0, SAMPLES), accompaniment: values.slice(SAMPLES)};
}

function validateRun(receipt, variant, bytes) {
  assert.ok(VARIANTS.includes(variant), 'Unsupported comparison arm');
  const rows = receipt.runs?.filter(r => r.variant === variant && r.phase === 'qualification' && r.round === 0);
  assert.equal(rows?.length, 1, 'Exactly one captured qualification run required');
  assert.equal(rows[0].outputBytes, 2 * SAMPLES * 4, 'Captured output size differs');
  assert.equal(bytes.length, rows[0].outputBytes, 'Captured output is incomplete');
  assert.equal(sha(bytes), rows[0].outputSha256, 'Captured output digest differs');
  const observer = receipt.comparisons?.filter(c => c.reference === variant && c.candidate === variant + '_profiled');
  assert.equal(observer?.length, 1, 'Exact observer comparison is required');
  assert.equal(observer[0].byteIdentical, true, 'Observer comparison did not preserve bytes');
  assert.equal(observer[0].referenceSha256, rows[0].outputSha256, 'Observer identity differs');
  assert.equal(observer[0].candidateSha256, rows[0].outputSha256, 'Profiled observer identity differs');
  readCaptured(bytes);
  return rows[0];
}

function sourceFile(relative) {
  assert.ok(typeof relative === 'string' && relative && !path.isAbsolute(relative), 'Nonrelative source identity');
  const full = path.resolve(ROOT, relative);
  assert.equal(path.relative(ROOT, full).split(path.sep).join('/'), relative, 'Noncanonical source identity');
  assert.ok(!relative.startsWith('../'), 'Source escapes repository');
  return full;
}

function bindInputs(evidence, audio) {
  const receiptPath = path.join(evidence, 'receipt.json'), receipt = load(receiptPath);
  assert.equal(receipt.schema, 'lightforge.deux-accelerator-experiment.v1', 'Unknown capture schema');
  assert.equal(receipt.status, 'NUMERICAL_EQUIVALENCE_UNPROVEN', 'Expected unresolved numerical capture');
  assert.equal(receipt.inputsRecheckedAfterQualification, true, 'Capture inputs were not rechecked');
  assert.equal(receipt.startSample, -HALO, 'Only the captured first passage is supported');
  assert.equal(receipt.samplesPerStem, SAMPLES, 'Passage context changed');
  assert.equal(receipt.audioFrames, 64 * RATE, 'Expected the complete public demo');
  assert.equal(receipt.audioSha256, PUBLIC_AUDIO_SHA256, 'Only the public demo is accepted');
  assert.equal(fileSha(audio), receipt.audioSha256, 'Source audio digest differs');
  assert.ok(receipt.sourceHashes && Object.keys(receipt.sourceHashes).length >= 9, 'Missing capture source inventory');
  for (const required of ['android/src/com/cyberbasslord/lightforge/NativeDeux.java',
    'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java', 'tools/benchmark_deux_accelerator.py']) {
    assert.ok(receipt.sourceHashes[required], 'Missing capture source: ' + required);
  }
  for (const [name, expected] of Object.entries(receipt.sourceHashes)) {
    assert.equal(fileSha(sourceFile(name)), expected, 'Capture source differs: ' + name);
  }
  const bindings = Object.fromEntries(SOURCE_NAMES.map(name => [name, fileSha(sourceFile(name))]));
  assert.equal(bindings['web/analysis/models/deux/manifest.json'], receipt.modelManifestSha256, 'Deux manifest differs');
  const deux = load(sourceFile('web/analysis/models/deux/manifest.json'));
  assert.deepEqual(receipt.modelHashes, Object.fromEntries(Object.entries(deux.files).map(([name, info]) => [name, info.sha256])), 'Captured model inventory differs');
  const game = load(sourceFile('web/analysis/models/game/manifest.json'));
  assert.equal(game.id, 'game-large-1.0.3-lightforge-1');
  assert.equal(game.steps, 8); assert.equal(game.sampleRate, RATE);
  const vocal = load(sourceFile('web/analysis/models/vocal-model.json'));
  const assetNames = [...Object.keys(game.files).map(name => 'models/game/' + name),
    'models/' + vocal.file, 'vendor/ort.wasm.min.js', 'vendor/ort-wasm-simd-threaded.wasm',
    'vendor/ort-wasm-simd-threaded.mjs'];
  const inventory = load(sourceFile('web/analysis/ASSET_MANIFEST.json'));
  const assets = {};
  // Bind every consumed application module/config to its reviewed inventory too.
  for (const name of [...assetNames, ...SOURCE_NAMES.filter(n => n.startsWith('web/analysis/') && !n.endsWith('ASSET_MANIFEST.json')).map(n => n.slice(13))]) {
    const item = inventory[name], full = sourceFile('web/analysis/' + name);
    assert.ok(item && Number.isSafeInteger(item.bytes), 'Missing asset pin: ' + name);
    assert.equal(fs.statSync(full).size, item.bytes, 'Asset size differs: ' + name);
    assert.equal(fileSha(full), item.sha256, 'Asset digest differs: ' + name);
    assets['web/analysis/' + name] = item.sha256;
  }
  const outputs = {};
  for (const variant of VARIANTS) {
    const full = path.join(evidence, variant, 'qualification-0.f32'), bytes = fs.readFileSync(full);
    validateRun(receipt, variant, bytes);
    outputs[variant] = {file: variant + '/qualification-0.f32', bytes: bytes.length, sha256: sha(bytes)};
  }
  return {receiptSha256: fileSha(receiptPath), receiptStatus: receipt.status,
    sourceHashes: bindings, captureSourceHashes: receipt.sourceHashes, assetHashes: assets,
    audioSha256: receipt.audioSha256, audioFrames: receipt.audioFrames, outputs};
}

async function replayFirstChunk(reader, captured, manifest) {
  assert.ok(reader.samples > CORE, 'A shortened source changes first-passage end behavior');
  assert.equal(reader.rate, RATE);
  for (const role of ['vocals', 'accompaniment']) {
    assert.ok(captured[role] instanceof Float32Array && captured[role].length === SAMPLES);
    assert.ok(captured[role].every(Number.isFinite), 'Nonfinite captured PCM');
  }
  require(ROOT + '/web/analysis/dsp.js');
  const Deux = require(ROOT + '/web/analysis/separator-deux.js');
  const previousFetch = global.fetch;
  const sentinel = new Error('No captured second passage');
  let separator, chunk, nativeCalls = 0, stoppedAtMissingPassage = false;
  const reads = [];
  try {
    global.fetch = async url => {
      assert.equal(String(url), 'https://captured.invalid/manifest.json');
      return {json: async () => manifest};
    };
    separator = await Deux.create({
      baseUrl: 'https://captured.invalid/',
      ort: {InferenceSession: {create() { throw new Error('Replay must never infer a new Deux passage'); }}},
      nativePredict: async start => {
        if (start === STRIDE - HALO && nativeCalls === 1) throw sentinel;
        assert.equal(start, -HALO, 'Captured source offset differs');
        assert.equal(nativeCalls++, 0, 'Captured passage was reused');
        return captured;
      },
    });
    await separator.process(async (start, count) => {
      reads.push({start, count}); return reader.stereo44100(start, count);
    }, reader.samples, async value => {
      assert.ok(chunk === undefined, 'More than the captured committed chunk was emitted');
      chunk = value;
    });
    throw new Error('Partial capture unexpectedly completed a source');
  } catch (error) {
    if (error !== sentinel) throw error;
    stoppedAtMissingPassage = true;
  } finally {
    await separator?.release(); global.fetch = previousFetch;
  }
  assert.equal(nativeCalls, 1, 'Source bypassed the captured native passage');
  assert.ok(chunk, 'No committed source chunk');
  assert.equal(chunk.startSample, 0); assert.equal(chunk.sampleRate, RATE);
  assert.equal(chunk.vocals.length, STRIDE); assert.equal(chunk.accompaniment.length, STRIDE);
  assert.deepEqual(reads, [{start: -HALO, count: SAMPLES}, {start: STRIDE - HALO, count: SAMPLES}]);
  return {chunk, replay: {nativeCalls, sourceSamples: reader.samples, reads, stoppedAtMissingPassage,
    sourceComplete: false, firstCommittedSamples: STRIDE, haloSamples: HALO, coreSamples: CORE, strideSamples: STRIDE,
    overlapBetweenTwoMeasuredPassagesExercised: false}};
}

class MemoryStream {
  constructor() { this.parts = []; this.closed = false; }
  async write(bytes) { assert.equal(this.closed, false); this.parts.push(Buffer.from(bytes)); }
  async close() { this.closed = true; }
  bytes() { assert.equal(this.closed, true); return Buffer.concat(this.parts); }
}

async function runChildInference(options, variant, bindings) {
  const directory = path.join(options.output, variant); fs.mkdirSync(directory);
  require(ROOT + '/web/analysis/dsp.js'); require(ROOT + '/web/analysis/stem-cache.js');
  const Wav = require(ROOT + '/web/analysis/wav-reader.js');
  const Vocal = require(ROOT + '/web/analysis/vocal.js');
  const Detail = require(ROOT + '/web/analysis/vocal-detail.js');
  const Game = require(ROOT + '/web/analysis/game.js');
  const bytes = fs.readFileSync(options.audio), reader = new Wav('host://public-demo');
  reader.cached = buffer(bytes); reader.totalBytes = bytes.length; await reader.open();
  assert.equal(reader.samples, bindings.audioFrames);
  assert.equal(reader.channels, 2); assert.equal(reader.bits, 16); assert.equal(reader.format, 1);
  const captured = readCaptured(fs.readFileSync(path.join(options.evidence, bindings.outputs[variant].file)));
  const {chunk, replay} = await replayFirstChunk(reader, captured, load(ROOT + '/web/analysis/models/deux/manifest.json'));
  const config = load(ROOT + '/web/analysis/models/features.json');
  global.location = {href: pathToFileURL(ROOT + '/web/analysis/worker.js').href};
  global.fetch = async input => {
    const full = fileURLToPath(new URL(String(input), global.location.href));
    const relative = path.relative(ROOT, full).split(path.sep).join('/');
    assert.ok(bindings.assetHashes[relative], 'Unbound asset fetch: ' + relative);
    return new Response(fs.readFileSync(full));
  };
  const raw = require(ROOT + '/web/analysis/vendor/ort.wasm.min.js');
  raw.env.wasm.numThreads = 4; raw.env.wasm.proxy = false; raw.env.wasm.wasmPaths = ROOT + '/web/analysis/vendor/';
  const executions = {}, loadedModels = {};
  const ort = {Tensor: raw.Tensor, env: raw.env, InferenceSession: {async create(source, settings) {
    const full = fileURLToPath(source), relative = path.relative(ROOT, full).split(path.sep).join('/');
    assert.equal(fileSha(full), bindings.assetHashes[relative], 'Unbound model: ' + relative);
    loadedModels[relative] = fileSha(full);
    const role = path.basename(full) === 'frame-mn10-singing.onnx' ? 'frameMn10' : path.basename(full, '.onnx');
    const session = await raw.InferenceSession.create(fs.readFileSync(full), settings);
    return {async run(feeds) { executions[role] = (executions[role] || 0) + 1; return session.run(feeds); },
      async release() { return session.release(); }};
  }}};
  async function downsample(pcm, role) {
    const stream = new MemoryStream(), writer = new LightForgeStemCache.DownsampleWriter(stream, config.resampleHalfFIR, pcm.length);
    await writer.push(pcm.subarray(0, 65537), 0); await writer.push(pcm.subarray(65537), 65537); await writer.finish();
    const payload = stream.bytes(), wav = Buffer.concat([Buffer.from(LightForgeStemCache.header(Math.ceil(pcm.length / 2))), payload]);
    fs.writeFileSync(path.join(directory, role + '-22050.wav'), wav, {flag: 'wx'});
    const result = new Wav('host://excerpt'); result.cached = buffer(wav); result.totalBytes = wav.length; await result.open();
    return {reader: result, pcm: new Float32Array(buffer(payload)), sha256: sha(payload)};
  }
  const vocals = await downsample(chunk.vocals, 'vocals'), accompaniment = await downsample(chunk.accompaniment, 'accompaniment');
  const count = chunk.vocals.length, duration = count / RATE;
  console.log(variant + ': Frame-MN10 on exact first committed five-second chunk');
  const classified = await Vocal.analyze(vocals.reader, config, {ort, includeClassifierScores: true});
  const extractor = new Detail.Extractor({sampleRate: 22050, duration}); extractor.push(vocals.pcm, 0, accompaniment.pcm);
  console.log(variant + ': GAME Large, eight diffusion steps');
  const rawGameCheckpoints = [];
  const game = await Game.create({ort, baseUrl: pathToFileURL(ROOT + '/web/analysis/models/game/').href,
    checkpoint: {read: async () => null, write: async (key, value) => { rawGameCheckpoints.push({key, ...value}); }}});
  let transcription;
  try {
    transcription = await game.process(async (start, length) => {
      assert.ok(Number.isSafeInteger(start) && Number.isSafeInteger(length) && start >= 0 && start + length <= count);
      return chunk.vocals.slice(start, start + length);
    }, count, {language: 0});
  } finally { await game.release(); }
  const detail = extractor.finish({classifier: classified.classifier, model: classified.model, transcription});
  const comparable = {samples44100: count, samples22050: vocals.pcm.length, transcription, classified,
    features: {fineEnergy: extractor.fineEnergy, residualEnergy: extractor.residualEnergy,
      frequency: extractor.frequency, periodicity: extractor.periodicity},
    vocals: Game.fuse(detail, transcription), executions, loadedModels, runtime: raw.env.versions.web,
    sourceClock: {sampleRate: RATE, coreStartSample: 0, emittedSamples: count, contextReadStart: -HALO,
      contextReadSamples: SAMPLES, fullSourceSamples: reader.samples}};
  assert.equal(comparable.runtime, '1.20.1');
  const result = {bindings, replay, comparable, rawGameCheckpoints,
    resampledSha256: {vocals: vocals.sha256, accompaniment: accompaniment.sha256},
    downstreamInputIsBoundedExcerpt: true, downstreamWholeSourceContextPreserved: false};
  assert.deepEqual(bindInputs(options.evidence, options.audio), bindings, 'An input changed during downstream inference');
  writeJson(path.join(directory, 'downstream.json'), result);
  console.log(JSON.stringify({variant, notes: transcription.notes.length, fusedNotes: comparable.vocals.notes.length,
    phrases: comparable.vocals.phrases.length, executions}));
}

async function runChild(options, variant) {
  const bindings = bindInputs(options.evidence, options.audio);
  const check = {variant, inputsRechecked: false, unchanged: false, errors: []};
  try { await runChildInference(options, variant, bindings); }
  catch (error) { check.errors.push(error.message || String(error)); throw error; }
  finally {
    try {
      assert.deepEqual(bindInputs(options.evidence, options.audio), bindings, 'Inputs changed during child inference');
      check.inputsRechecked = true; check.unchanged = true;
    } catch (error) { check.errors.push(error.message || String(error)); }
    writeJson(path.join(options.output, variant + '-input-recheck.json'), check);
    assert.equal(check.unchanged, true, 'Child input recheck failed; see retained recheck receipt');
  }
}

function parseArgs(args) {
  const result = {};
  for (let i = 0; i < args.length; i += 2) {
    const key = args[i]?.replace(/^--/, '');
    assert.ok(['evidence', 'audio', 'output', 'child'].includes(key) && args[i].startsWith('--') && args[i + 1], 'Expected --evidence DIR --audio WAV --output NEW_DIR');
    assert.equal(result[key], undefined, 'Duplicate option'); result[key] = args[i + 1];
  }
  for (const key of ['evidence', 'audio', 'output']) { assert.ok(result[key], 'Missing --' + key); result[key] = path.resolve(result[key]); }
  if (result.child) assert.ok(VARIANTS.includes(result.child), 'Unsupported child');
  return result;
}

async function main(options) {
  if (options.child) return runChild(options, options.child);
  fs.mkdirSync(options.output, {recursive: false});
  const report = {schema: 'lightforge.deux-downstream-sensitivity.v1', status: 'INCOMPLETE',
    createdUtc: new Date().toISOString(), sensitivityPassed: false, qualityApproved: false,
    releaseAuthorized: false, target75Proven: false, benchmarkTimingAdmitted: false,
    scope: 'Two captured first-passage Deux outputs replayed through the original full-source consumer to its first committed five-second chunk; paired actual-model vocal downstream sensitivity on that bounded excerpt.',
    limitations: ['One public opening excerpt; not a representative corpus or perceptual evaluation.',
      'The second captured passage is absent: full-song overlap-add and completion are untested.',
      'Downstream runs treat the committed chunk as a bounded excerpt; full-song classifier/GAME context is not claimed.',
      'A passing sensitivity comparison neither resolves the upstream numerical gate nor admits benchmark ratios.',
      'No CUDA inference, complete app analysis, transfer timing, Android or physical-device test is performed here.'],
    errors: []};
  let exitCode = 2;
  try {
    const bindings = bindInputs(options.evidence, options.audio); report.bindings = bindings;
    const comparator = require(ROOT + '/' + COMPARATOR);
    report.comparisonContract = {source: COMPARATOR, sha256: fileSha(ROOT + '/' + COMPARATOR), thresholds: comparator.thresholds,
      scope: 'Existing physical-unit downstream sensitivity rules reused unchanged; not a new Deux waveform tolerance or publication policy.'};
    writeJson(path.join(options.output, 'declared-contract.json'), report);
    for (const variant of VARIANTS) {
      const log = fs.openSync(path.join(options.output, variant + '.log'), 'wx');
      let result;
      try { result = spawnSync(process.execPath, [__filename, '--evidence', options.evidence, '--audio', options.audio,
        '--output', options.output, '--child', variant], {cwd: ROOT, stdio: ['ignore', log, log], timeout: 1200000}); }
      finally { fs.closeSync(log); }
      console.log(fs.readFileSync(path.join(options.output, variant + '.log'), 'utf8'));
      if (result.error) throw result.error;
      assert.equal(result.status, 0, 'Downstream inference failed: ' + variant);
    }
    const results = Object.fromEntries(VARIANTS.map(variant => [variant, load(path.join(options.output, variant, 'downstream.json'))]));
    for (const result of Object.values(results)) assert.deepEqual(result.bindings, bindings, 'Child input bindings differ');
    assert.deepEqual(results.cpu_all.replay, results.cuda_basic.replay, 'Consumer replay coverage differs');
    report.replay = results.cpu_all.replay;
    report.comparison = comparator.compare(results.cuda_basic.comparable, results.cpu_all.comparable);
    report.rawGameCheckpointsByteIdentical = json(results.cpu_all.rawGameCheckpoints) === json(results.cuda_basic.rawGameCheckpoints);
    report.outputs = Object.fromEntries(VARIANTS.map(variant => [variant, {file: variant + '/downstream.json',
      sha256: fileSha(path.join(options.output, variant, 'downstream.json'))}]));
    assert.deepEqual(bindInputs(options.evidence, options.audio), bindings, 'Inputs changed during paired capture');
    report.inputsRecheckedAfterComparison = true;
    report.sensitivityPassed = report.comparison.passed;
    report.status = report.sensitivityPassed ? 'EXCERPT_SENSITIVITY_PASS' : 'EXCERPT_SENSITIVITY_FAILED';
    exitCode = report.sensitivityPassed ? 0 : 2;
  } catch (error) { report.errors.push(error.message || String(error)); }
  finally {
    if (report.bindings) {
      try {
        assert.deepEqual(bindInputs(options.evidence, options.audio), report.bindings, 'Inputs changed during paired capture');
        report.inputsRecheckedAfterComparison = true;
      } catch (error) {
        report.inputsRecheckedAfterComparison = false; report.sensitivityPassed = false;
        report.status = 'INPUT_BINDING_INVALIDATED'; exitCode = 2;
        report.errors.push(error.message || String(error));
      }
    }
    report.completedUtc = new Date().toISOString(); writeJson(path.join(options.output, 'receipt.json'), report);
  }
  console.log(json({status: report.status, sensitivityPassed: report.sensitivityPassed, qualityApproved: false,
    target75Proven: false, errors: report.errors}));
  process.exitCode = exitCode;
}

module.exports = {readCaptured, validateRun, replayFirstChunk, parseArgs, bindInputs, SAMPLES, HALO, CORE, STRIDE};
if (require.main === module) main(parseArgs(process.argv.slice(2))).catch(error => { console.error(error.stack); process.exitCode = 2; });
