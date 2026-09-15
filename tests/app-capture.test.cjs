'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const capture = require('../qa/locked-benchmark/capture-app.cjs');
const publishedBootstrap = require('./fixtures/capture-bootstrap-2.2.4.json');
const coreFiles = [...publishedBootstrap.expected_capture_scripts, 'analysis/worker.js', 'engine/worker.js', 'analysis/ASSET_MANIFEST.json'];
function fixtureLock(names) { return { schema: 'lightforge.web-capture-lock.v1', files: Object.fromEntries(names.map(name => [name, { bytes: 1, sha256: '0'.repeat(64) }])) }; }

function temporary(t) { const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lightforge-capture-test-')); t.after(() => fs.rmSync(dir, { recursive: true, force: true })); return dir; }
function wav(samples = 44100) {
  const bytes = Buffer.alloc(44 + samples * 4);
  bytes.write('RIFF'); bytes.writeUInt32LE(bytes.length - 8, 4); bytes.write('WAVEfmt ', 8);
  bytes.writeUInt32LE(16, 16); bytes.writeUInt16LE(1, 20); bytes.writeUInt16LE(2, 22);
  bytes.writeUInt32LE(44100, 24); bytes.writeUInt32LE(176400, 28);
  bytes.writeUInt16LE(4, 32); bytes.writeUInt16LE(16, 34); bytes.write('data', 36); bytes.writeUInt32LE(samples * 4, 40);
  return bytes;
}
const configuration = () => ({ analysis_options: { analysisQuality: 'balanced' }, show_settings: { seed: 100, stepMs: 20 } });
const identity = digest => ({ source_commit: 'a'.repeat(40), source_tree_sha: 'b'.repeat(40), web_manifest_sha256: digest, pipeline_version: 'pipeline-v1', preprocessing_version: 'preprocessing-v1', track_id: 'real-track', run_id: 'pair-01', report_side: 'candidate' });

test('raw JSON digests are independent of object insertion order and reject non-finite numbers', () => {
  assert.equal(capture.canonical({ z: 1, a: { q: 2, c: 3 } }), capture.canonical({ a: { c: 3, q: 2 }, z: 1 }));
  for (const value of [Infinity, NaN, undefined]) assert.throws(() => capture.canonical({ measured: value }));
});
test('WAV header measurement reports actual sample count without decoding invented audio', t => {
  const file = path.join(temporary(t), 'fixture.wav'); fs.writeFileSync(file, wav(44123));
  const info = capture.wavInfo(file); assert.equal(info.sample_frames, 44123); assert.equal(info.channels, 2); assert.equal(info.sample_rate, 44100);
});
test('truncated WAV, lying RIFF length and inconsistent sample size fail closed', t => {
  const file = path.join(temporary(t), 'fixture.wav');
  for (const mutation of [bytes => bytes.subarray(0, bytes.length - 1), bytes => { bytes.writeUInt32LE(6, 40); return bytes; }, bytes => { bytes.writeUInt16LE(7, 32); return bytes; }]) {
    fs.writeFileSync(file, mutation(wav())); assert.throws(() => capture.wavInfo(file));
  }
});
test('WAV and inventory symlinks are rejected', async t => {
  const dir = temporary(t), target = path.join(dir, 'audio.wav'); fs.writeFileSync(target, wav());
  const link = path.join(dir, 'alias.wav'); fs.symlinkSync(target, link); assert.throws(() => capture.wavInfo(link));
  await assert.rejects(capture.inventory(dir), /symlink/);
});
test('full pipeline rejects non-44.1 kHz and sub-second inputs before browser startup', t => {
  const file = path.join(temporary(t), 'fixture.wav');
  for (const rate of [22050, 48000, 96000]) {
    const bytes = wav(); bytes.writeUInt32LE(rate, 24); bytes.writeUInt32LE(rate * 4, 28);
    fs.writeFileSync(file, bytes); assert.throws(() => capture.wavInfo(file), /44.1/);
  }
  fs.writeFileSync(file, wav(4)); assert.throws(() => capture.wavInfo(file), /1 second/);
});
test('WAV fmt must precede data', t => {
  const file = path.join(temporary(t), 'fixture.wav'), bytes = wav();
  fs.writeFileSync(file, Buffer.concat([bytes.subarray(0, 12), bytes.subarray(36), bytes.subarray(12, 36)]));
  assert.throws(() => capture.wavInfo(file), /fmt must precede/);
});
test('extensible WAV validates complete subtype GUID, extension size and valid bits', t => {
  const file = path.join(temporary(t), 'fixture.wav');
  function extensible() {
    const pcm = wav(), bytes = Buffer.concat([pcm.subarray(0, 36), Buffer.alloc(24), pcm.subarray(36)]);
    bytes.writeUInt32LE(bytes.length - 8, 4); bytes.writeUInt32LE(40, 16); bytes.writeUInt16LE(0xfffe, 20);
    bytes.writeUInt16LE(22, 36); bytes.writeUInt16LE(16, 38); bytes.writeUInt32LE(3, 40);
    Buffer.from('0100000000001000800000aa00389b71', 'hex').copy(bytes, 44); return bytes;
  }
  fs.writeFileSync(file, extensible()); const info = capture.wavInfo(file);
  assert.equal(info.subformat_tag, 1); assert.equal(info.valid_bits_per_sample, 16); assert.equal(info.channel_mask, 3);
  for (const mutate of [b => b.writeUInt16LE(0, 36), b => b.fill(0xff, 46, 60), b => b.writeUInt16LE(33, 38)]) {
    const bytes = extensible(); mutate(bytes); fs.writeFileSync(file, bytes); assert.throws(() => capture.wavInfo(file));
  }
});
test('a changed source byte changes the complete inventory lock', async t => {
  const dir = temporary(t), file = path.join(dir, 'worker.js'); fs.writeFileSync(file, 'first');
  const first = await capture.inventory(dir); fs.writeFileSync(file, 'other'); const second = await capture.inventory(dir);
  assert.notEqual(capture.validateLock(first), capture.validateLock(second));
  assert.throws(() => capture.validateIdentity(identity(capture.validateLock(first)), capture.validateLock(second)), /differs/);
});
test('inventory rejects paths that could escape its web root', () => {
  for (const name of ['../secret', '/secret', 'a/../secret', 'a\\secret']) {
    assert.throws(() => capture.validateLock({ schema: 'lightforge.web-capture-lock.v1', files: { [name]: { bytes: 1, sha256: 'a'.repeat(64) } } }));
  }
});
test('published 2.2.4 bootstrap uses its observed module order without candidate enhancements', () => {
  const lock = fixtureLock(publishedBootstrap.web_blob_paths), loaded = capture.bootstrapScripts(lock);
  assert.equal(publishedBootstrap.source.commit_sha, 'a8c6fd8abf76c413913c3aed85cba2ad6bae17bd');
  assert.equal(publishedBootstrap.source.tree_sha, '6c24fb9a14a25f1fdfc90addcf6dac9ef327a63f');
  assert.deepEqual(loaded, publishedBootstrap.expected_capture_scripts);
  assert.deepEqual(publishedBootstrap.index_script_order.filter(name => loaded.includes(name)), loaded);
  for (const missing of publishedBootstrap.absent_enhancement_scripts) {
    assert.equal(Object.hasOwn(lock.files, missing), false); assert.equal(loaded.includes(missing), false);
  }
});
test('enhancement scripts load only when present in the locked distribution and keep candidate dependency order', () => {
  const lock = fixtureLock([...coreFiles, ...publishedBootstrap.absent_enhancement_scripts]);
  assert.deepEqual(capture.bootstrapScripts(lock), ['version.js', 'analysis/semantic-timeline.js', 'analysis/vocal-semantics.js', 'analysis/salience.js', 'analysis/recurrence.js', 'analysis/stem-cache.js', 'analysis/work-store.js', 'analysis/diagnostic-clock.js', 'analysis/scheduler.js', 'analysis/resource-diagnostics.js', 'analysis/analyzer.js', 'engine/client.js']);
  delete lock.files['analysis/scheduler.js']; assert.equal(capture.bootstrapScripts(lock).includes('analysis/scheduler.js'), false);
});
test('baseline compatibility does not make real analyzer/compiler core files optional', () => {
  for (const missing of coreFiles) {
    const lock = fixtureLock(coreFiles); delete lock.files[missing];
    assert.throws(() => capture.bootstrapScripts(lock), /Required production capture file absent/);
  }
});
test('paired identity needs explicit side and stable opaque run ID', () => {
  const item = identity('c'.repeat(64)); assert.doesNotThrow(() => capture.validateIdentity(item, item.web_manifest_sha256));
  for (const mutation of [{ run_id: '../pair' }, { run_id: 123 }, { source_commit: ['a'.repeat(40)] }, { report_side: 'release' }, { source_commit: 'short' }, { extra: true }]) assert.throws(() => capture.validateIdentity({ ...item, ...mutation }, item.web_manifest_sha256));
});
test('configuration cannot override measured source/cache identities or claim native execution', () => {
  for (const key of ['analysisIdentity', 'nativePredict', 'supportsNativeDeux', 'analysisRefreshEpoch', 'projectId']) {
    const config = configuration(); config.analysis_options[key] = 'fake'; assert.throws(() => capture.validateConfiguration(config), /Reserved/);
  }
});
test('configuration requires quality choice and explicit deterministic frame interval/seed', () => {
  assert.doesNotThrow(() => capture.validateConfiguration(configuration()));
  for (const replacement of [{}, { seed: 1 }, { seed: -1, stepMs: 20 }, { seed: 1, stepMs: 16 }]) assert.throws(() => capture.validateConfiguration({ ...configuration(), show_settings: replacement }));
  assert.throws(() => capture.validateConfiguration({ ...configuration(), analysis_options: {} }));
});
test('range parser accepts bounded open-ended reads and rejects invalid or multi-range input', () => {
  assert.deepEqual(capture.parseRange('bytes=2-', 10), { start: 2, end: 9, partial: true });
  assert.deepEqual(capture.parseRange('bytes=2-90', 10), { start: 2, end: 9, partial: true });
  for (const range of ['bytes=-1', 'bytes=20-21', 'bytes=8-2', 'bytes=0-2,4-5', 'bytes=999999999999999999999-']) assert.throws(() => capture.parseRange(range, 10));
});
test('server serves exact locked WAV ranges and cannot expose another local file', async t => {
  const dir = temporary(t), web = path.join(dir, 'web'); fs.mkdirSync(web);
  fs.writeFileSync(path.join(web, 'worker.js'), 'worker');
  for (const relative of coreFiles) { const file = path.join(web, relative); fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, 'unit protocol fixture'); }
  const file = path.join(dir, 'input.wav'), bytes = wav(10); fs.writeFileSync(file, bytes);
  fs.writeFileSync(path.join(dir, 'secret.txt'), 'must not be served');
  const server = capture.createServer(web, file, await capture.inventory(web), new Set());
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const origin = 'http://127.0.0.1:' + server.address().port;
  const result = await fetch(origin + '/__capture__/input.wav', { headers: { Range: 'bytes=3-14' } });
  assert.equal(result.status, 206); assert.deepEqual(Buffer.from(await result.arrayBuffer()), bytes.subarray(3, 15));
  assert.equal(result.headers.get('cross-origin-embedder-policy'), 'require-corp');
  assert.equal((await fetch(origin + '/%2e%2e%2fsecret.txt')).status, 404);
  assert.equal((await fetch(origin + '/worker.js', { method: 'POST' })).status, 405);
  assert.equal((await fetch(origin + '/__capture__/input.wav', { headers: { Range: 'bytes=1000000-' } })).status, 416);
});
test('absent percussion is missing evidence, never generated from onsets', () => {
  const result = capture.outputCategories({ onsets: [{ time: 1 }], beats: [] }, {}, { frame_count: 10 });
  assert.equal(Object.hasOwn(result.categories, 'drum_map'), false); assert.match(result.missing.drum_map, /not emitted/);
  assert.equal(Object.hasOwn(result.categories, 'validation_report'), false);
});
test('baseline-shaped output leaves unavailable semantic, salience, drum and perceptual sidecars absent', () => {
  const music = { beats: [], downbeats: [], bpm: 120, meter: 4, vocals: { notes: [] }, bassNotes: [], bassAnalysis: { method: 'baseline' }, sections: [], engine: { analysisSeconds: 1, stages: {} } };
  const show = { choreography: { version: '2.2.4' }, settings: { seed: 1 }, validation: { valid: true, errors: [] } };
  const result = capture.outputCategories(music, show, { frame_count: 50 });
  assert.deepEqual(Object.keys(result.missing).sort(), ['drum_map', 'salience_map', 'semantic_timeline']);
  assert.equal(Object.hasOwn(show, 'perceptualValidation'), false); assert.equal(Object.hasOwn(music.engine, 'resourceDiagnostics'), false);
  assert.equal(Object.keys(result.categories).length, 7);
});
test('actual percussion provenance and optional perceptual sidecars are preserved without invented scores', () => {
  const percussion = { estimated: true, events: [{ kind: 'kick', time: 1, confidence: 0.4 }] };
  const result = capture.outputCategories({ percussionAnalysis: percussion, semanticTimeline: { events: [] } }, { choreography: { quality: { kind: 'actual' } }, settings: { seed: 10 }, validation: { valid: true, errors: [] } }, { frame_count: 10 });
  assert.deepEqual(result.categories.drum_map, percussion); assert.equal(Object.hasOwn(result.categories, 'salience_map'), false);
  assert.deepEqual(result.categories.validation_report, { valid: true, errors: [] });
});
test('section and vocal projections preserve actual emitted recurrence and vocal semantic links', () => {
  const music = { sections: [], recurrenceAnalysis: { observed: true }, recurrenceEvidence: { frames: 3 }, recurrenceSidecar: { schemaVersion: 1 }, vocals: { notes: [] }, vocalSemanticLinks: { events: [] } };
  const result = capture.outputCategories(music, {}, {});
  assert.deepEqual(result.categories.section_map, { sections: [], recurrenceAnalysis: music.recurrenceAnalysis, recurrenceEvidence: music.recurrenceEvidence, recurrenceSidecar: music.recurrenceSidecar });
  assert.deepEqual(result.categories.vocal_map.vocalSemanticLinks, music.vocalSemanticLinks);
});
test('raw musical projections exclude engine performance timings', () => {
  const before = { beats: [1], bpm: 120, vocals: { notes: [] }, engine: { analysisSeconds: 100 } };
  const after = { ...before, engine: { analysisSeconds: 1 } };
  assert.equal(capture.canonical(capture.outputCategories(before, {}, {})), capture.canonical(capture.outputCategories(after, {}, {})));
});
test('a wrong audio hash writes a failed receipt without starting Chromium or creating success artifacts', async t => {
  const dir = temporary(t), web = path.join(dir, 'web'); fs.mkdirSync(web); fs.writeFileSync(path.join(web, 'worker.js'), 'worker');
  const audio = path.join(dir, 'audio.wav'); fs.writeFileSync(audio, wav()); const lock = await capture.inventory(web);
  for (const [name, value] of Object.entries({ lock, identity: identity(capture.validateLock(lock)), configuration: configuration() })) fs.writeFileSync(path.join(dir, name + '.json'), JSON.stringify(value));
  const out = path.join(dir, 'attempt');
  const code = await capture.capture({ 'app-root': dir, wav: audio, 'audio-sha256': '0'.repeat(64), identity: path.join(dir, 'identity.json'), configuration: path.join(dir, 'configuration.json'), 'web-manifest': path.join(dir, 'lock.json'), 'output-dir': out });
  assert.equal(code, 1); const report = JSON.parse(fs.readFileSync(path.join(out, 'capture.json')));
  assert.equal(report.status, 'failed'); assert.equal(report.production_ready, false); assert.match(report.error, /Audio content differs/);
  assert.deepEqual(fs.readdirSync(out), ['capture.json']);
  await assert.rejects(capture.capture({ 'app-root': dir, wav: audio, 'output-dir': out }), /already exists/);
});


test('external JSON files reject nested and escaped duplicate keys before evidence can be rebound', t => {
  const file = path.join(temporary(t), 'input.json');
  for (const content of ['{"source_commit":"first","source_commit":"last"}', '{"outer":{"sha256":"first","sha\\u003256":"last"}}', '{"rows":[{"x":1,"x":2}]}']) {
    fs.writeFileSync(file, content); assert.throws(() => capture.readJson(file), /Duplicate/);
  }
});
test('producer numeric validation precedes lossy JSON conversion, including typed arrays', () => {
  for (const value of [{ semantic: { time: NaN } }, { preview: new Float64Array([0, Infinity]) }, { offset: -Infinity }]) {
    assert.throws(() => capture.producerJson(value), /Non-finite producer number/);
  }
  const actual = { previewIndex: { lights: [{ times: new Float64Array([0, 1.25]), values: new Uint8Array([0, 255]) }] } };
  assert.deepEqual(JSON.parse(capture.producerJson(actual)), JSON.parse(JSON.stringify(actual)));
  assert.throws(() => capture.producerJson({ values: [undefined] }), /Unsupported/);
  assert.throws(() => capture.producerJson({ custom: { toJSON() { return null; } } }), /serialization/);
  let reads = 0; assert.throws(() => capture.producerJson({ get time() { return reads++ ? NaN : 1; } }), /accessor/);
  assert.equal(reads, 0);
  assert.throws(() => capture.producerJson({ text: 'larger than bound' }, 5), /byte bound/);
});
test('maximum legal identity fields produce a stable project ID within work-store 80 characters', () => {
  const item = { track_id: 't'.repeat(128), run_id: 'r'.repeat(128) };
  const first = capture.captureProjectId(item);
  assert.equal(first.length, 72); assert.match(first, /^capture-[0-9a-f]{64}$/);
  assert.equal(first, capture.captureProjectId({ ...item, report_side: 'baseline' }));
  assert.notEqual(first, capture.captureProjectId({ ...item, run_id: 'r'.repeat(127) + 's' }));
});
test('four-hour compiler duration bound rejects even one extra sample before startup', t => {
  const file = path.join(temporary(t), 'long-sparse.wav');
  function sparse(samples) {
    const header = wav().subarray(0, 44), size = 44 + samples * 2;
    header.writeUInt32LE(size - 8, 4); header.writeUInt16LE(1, 22); header.writeUInt32LE(88200, 28); header.writeUInt16LE(2, 32); header.writeUInt32LE(samples * 2, 40);
    fs.writeFileSync(file, header); fs.truncateSync(file, size);
  }
  sparse(14400 * 44100); assert.equal(capture.wavInfo(file).duration_seconds, 14400);
  sparse(14400 * 44100 + 1); assert.throws(() => capture.wavInfo(file), /4 hours/);
});
test('failed show retains bounded original fields and byte evidence without success goldens', t => {
  const dir = temporary(t), report = {}, sidecar = { eventEvidence: { accepted: 0, invalid: 3, omitted: 1 }, timing: { command: { p95: 0.12 } }, label: 'original' };
  const result = { music: { beats: [1] }, show: { validation: { valid: false, errors: ['invalid movement'] }, perceptualValidation: sidecar }, compiled: { schema: 1 }, progress: [], frames: Buffer.from([1,2]).toString('base64'), header: Buffer.from([3,4]).toString('base64') };
  capture.retainRawArtifacts(dir, result, report);
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(dir, 'perceptual-validation.json'))), sidecar);
  assert.equal(JSON.parse(fs.readFileSync(path.join(dir, 'show.json'))).validation.valid, false);
  assert.deepEqual(fs.readFileSync(path.join(dir, 'show.frames.bin')), Buffer.from([1,2]));
  assert.match(report.raw_evidence_status, /not-qualified/);
  assert.equal(Object.hasOwn(report, 'observed_output_hashes'), false);
  for (const [name, record] of Object.entries(report.artifacts)) { const bytes = fs.readFileSync(path.join(dir, name)); assert.equal(capture.hashBytes(bytes), record.sha256); assert.equal(bytes.length, record.bytes); }
});
test('unserializable artifact retains the other raw outputs and explicit failure reason', t => {
  const dir = temporary(t), report = {};
  capture.retainRawArtifacts(dir, { music: { time: NaN }, show: { validation: { valid: false } }, serialization_errors: [{ field: 'progress', error: 'non-finite' }] }, report);
  assert.equal(fs.existsSync(path.join(dir, 'analysis.json')), false);
  assert.equal(fs.existsSync(path.join(dir, 'show.json')), true);
  assert.equal(report.artifact_errors.length, 1);
  assert.equal(fs.existsSync(path.join(dir, 'producer-failure.json')), true);
  assert.match(report.missing_optional_artifacts['perceptual-validation.json'], /not emitted/);
});
test('undefined optional values are plain-false and cannot erase a failure checkpoint', t => {
  assert.equal(capture.plain(undefined), false);
  const dir = temporary(t);
  assert.throws(() => capture.checkpoint(dir, { schema: 'bad', engine: undefined }), /plain JSON/);
  const report = JSON.parse(fs.readFileSync(path.join(dir, '.capture-checkpoint.json')));
  assert.equal(report.status, 'failed'); assert.equal(report.production_ready, false); assert.match(report.error, /receipt serialization failed/);
});

async function protocolAttempt(t, result, extra = {}, closeBody = '') {
  const dir = temporary(t), web = path.join(dir, 'web'); fs.mkdirSync(web);
  for (const relative of coreFiles) { const file = path.join(web, relative); fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, relative.endsWith('.json') ? '{}' : 'unit protocol fixture'); }
  const audio = path.join(dir, 'audio.wav'); fs.writeFileSync(audio, wav()); const lock = await capture.inventory(web);
  for (const [name, value] of Object.entries({ lock, identity: identity(capture.validateLock(lock)), configuration: configuration() })) fs.writeFileSync(path.join(dir, name + '.json'), JSON.stringify(value));
  const stub = path.join(dir, 'node_modules', 'playwright'); fs.mkdirSync(stub, { recursive: true });
  fs.writeFileSync(path.join(stub, 'index.js'), `module.exports={chromium:{launch:async()=>({version:()=>"protocol-test",close:async()=>{${closeBody}},newContext:async()=>({route:async()=>{},newPage:async()=>({on(){},setDefaultTimeout(){},goto:async()=>{},waitForFunction:async()=>{},addScriptTag:async()=>{},exposeFunction:async()=>{},evaluate:async(fn,arg)=>arg?${JSON.stringify(result)}:true})})})}};`);
  // Keep the real collector bytes but resolve its protocol stub locally.
  // NODE_PATH cannot override a checkout's installed node_modules/playwright.
  const harness = path.join(dir, 'harness'); fs.mkdirSync(harness);
  for (const name of ['capture-app.cjs', 'strict-json.cjs', 'capture-supervisor.cjs', 'capture-supervisor.py']) {
    fs.copyFileSync(path.join(__dirname, '..', 'qa', 'locked-benchmark', name), path.join(harness, name));
  }
  const isolatedCapture = require(path.join(harness, 'capture-app.cjs'));
  const out = path.join(dir, 'attempt');
  const code = await isolatedCapture.capture({ 'app-root': dir, wav: audio, 'audio-sha256': await capture.hashBytes(fs.readFileSync(audio)), identity: path.join(dir, 'identity.json'), configuration: path.join(dir, 'configuration.json'), 'web-manifest': path.join(dir, 'lock.json'), 'output-dir': out, ...extra });
  return { code, out, report: JSON.parse(fs.readFileSync(path.join(out, 'capture.json'))) };
}
test('supervised pipeline keeps failed validation artifacts and authoritative failure receipt', async t => {
  const { code, out, report } = await protocolAttempt(t, { music: { beats: [1] }, show: { validation: { valid: false, errors: ['unit fixture failure'] } }, compiled: {}, progress: [], serialization_errors: [] });
  assert.equal(code, 1); assert.equal(report.status, 'failed'); assert.match(report.error, /application validation/);
  assert.equal(report.effective_show_settings.status, 'unavailable'); assert.equal(report.engine.status, 'unavailable');
  assert.equal(fs.existsSync(path.join(out, 'analysis.json')), true); assert.equal(fs.existsSync(path.join(out, 'show.json')), true);
  assert.equal(report.supervision.termination.verified, true); assert.equal(report.production_ready, false);
});


test('large valid frame transport is retained without regex stack overflow', t => {
  const dir = temporary(t), report = {};
  const encoded = 'A'.repeat(8 * 1024 ** 2);
  const retained = capture.retainRawArtifacts(dir, { frames: encoded }, report);
  assert.equal(retained.frames.length, 6 * 1024 ** 2);
  assert.equal(report.artifact_errors.length, 0);
  assert.equal(report.artifacts['show.frames.bin'].bytes, 6 * 1024 ** 2);
});

function validProtocolResult() {
  const frames = Buffer.from([17]), header = Buffer.alloc(32);
  header.write('PSEQ', 0); header.writeUInt16LE(32, 4);
  header.writeUInt32LE(1, 10); header.writeUInt32LE(1, 14); header[18] = 20;
  return { music: { beats: [0.5] }, show: { validation: { valid: true }, settings: {}, frameCount: 1, channelCount: 1, stepMs: 20 },
    compiled: { sha256: capture.hashBytes(frames) }, frames: frames.toString('base64'), header: header.toString('base64'), progress: [], serialization_errors: [] };
}
for (const scenario of [
  { name: 'browser close failure', closeBody: "throw Error('fixture close failure')", timedOut: false },
  { name: 'browser close timeout', closeBody: 'await new Promise(() => {})', timedOut: true },
]) test(scenario.name + ' retains raw artifacts but removes validated category hashes', async t => {
  const { code, out, report } = await protocolAttempt(t, validProtocolResult(), { 'timeout-seconds': '1' }, scenario.closeBody);
  assert.equal(code, 1); assert.equal(report.status, 'failed');
  assert.equal(report.runtime.browser, 'protocol-test', 'the fixture uses its local protocol stub even when real Playwright is installed');
  assert.equal(report.supervision.timed_out, scenario.timedOut);
  assert.equal(Object.hasOwn(report, 'observed_output_hashes'), false);
  assert.equal(fs.existsSync(path.join(out, 'lightshow.fseq')), true, 'capture passed validation before cleanup failed');
  assert.equal(fs.existsSync(path.join(out, 'analysis.json')), true);
  assert.equal(report.production_ready, false);
});

test('internal dispatch also rejects invalid deadlines before any file or browser work', async () => {
  const saved = process.env.LIGHTFORGE_CAPTURE_SUPERVISED;
  process.env.LIGHTFORGE_CAPTURE_SUPERVISED = '1';
  try {
    for (const seconds of ['0', '-1', '1.5', '14401', 'NaN', 'Infinity']) {
      const args = ['__capture-worker', 'capture', '--app-root', '/missing-capture-fixture'];
      for (const name of ['wav', 'audio-sha256', 'configuration', 'identity', 'web-manifest', 'output-dir']) args.push('--' + name, '/missing-capture-fixture');
      args.push('--timeout-seconds', seconds);
      await assert.rejects(capture.main(args), /Capture deadline must be 1\.\.14400 seconds/);
    }
  } finally {
    if (saved === undefined) delete process.env.LIGHTFORGE_CAPTURE_SUPERVISED;
    else process.env.LIGHTFORGE_CAPTURE_SUPERVISED = saved;
  }
});
