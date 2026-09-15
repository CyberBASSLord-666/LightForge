'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const capture = require('../qa/locked-benchmark/capture-app.cjs');

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
  fs.writeFileSync(path.join(web, 'worker.js'), 'worker'); const file = path.join(dir, 'input.wav'), bytes = wav(10); fs.writeFileSync(file, bytes);
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
