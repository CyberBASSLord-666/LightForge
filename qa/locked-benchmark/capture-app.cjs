#!/usr/bin/env node
'use strict';
/* Execute the unmodified browser analyzer/compiler against a hash-locked WAV.
 * This is a raw observation collector, never a complete release qualification. */
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');
const os = require('node:os');
const { parse: parseStrictJson } = require('./strict-json.cjs');
const { supervise } = require('./capture-supervisor.cjs');

const SCHEMA = 'lightforge.app-capture.v1';
const HEX = /^[0-9a-f]{64}$/;
const OPAQUE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const MAX_WAV_BYTES = 2 * 1024 ** 3;
const BOOTSTRAP_ORDER = [
  'version.js', 'analysis/semantic-timeline.js', 'analysis/vocal-semantics.js',
  'analysis/salience.js', 'analysis/recurrence.js', 'analysis/stem-cache.js',
  'analysis/work-store.js', 'analysis/diagnostic-clock.js', 'analysis/scheduler.js',
  'analysis/resource-diagnostics.js', 'analysis/analyzer.js', 'engine/client.js',
];
const CORE_SCRIPTS = ['version.js', 'analysis/stem-cache.js', 'analysis/work-store.js', 'analysis/analyzer.js', 'engine/client.js'];
const CORE_FILES = [...CORE_SCRIPTS, 'analysis/worker.js', 'engine/worker.js', 'analysis/ASSET_MANIFEST.json'];
function requireValue(condition, message) { if (!condition) throw Error(message); }
function plain(value) { return value !== null && typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype; }
function canonical(value) {
  function sorted(v) {
    if (v === null || typeof v === 'string' || typeof v === 'boolean') return v;
    if (typeof v === 'number') { requireValue(Number.isFinite(v), 'Non-finite captured number'); return v; }
    if (Array.isArray(v)) return v.map(sorted);
    requireValue(plain(v), 'Captured value is not plain JSON');
    return Object.fromEntries(Object.keys(v).sort().map(k => [k, sorted(v[k])]));
  }
  return JSON.stringify(sorted(value));
}
const hashBytes = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
async function hashFile(file) {
  const hash = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(file)) hash.update(chunk);
  return hash.digest('hex');
}
function regular(file) {
  const stat = fs.lstatSync(file);
  requireValue(stat.isFile() && !stat.isSymbolicLink(), 'Input must be a regular file');
  return stat;
}
function readJson(file) {
  requireValue(regular(file).size <= 8 * 1024 ** 2, 'JSON input exceeds 8 MiB');
  const value = parseStrictJson(fs.readFileSync(file, 'utf8'));
  requireValue(plain(value), 'JSON input must be an object');
  canonical(value);
  return value;
}
function writeJson(file, value) { fs.writeFileSync(file, canonical(value) + '\n', { flag: 'wx', mode: 0o600 }); }
function safeRelative(name) {
  return typeof name === 'string' && name.length > 0 && !name.includes('\\') &&
    !name.startsWith('/') && name.split('/').every(p => p && p !== '.' && p !== '..');
}
async function inventory(webRoot) {
  requireValue(fs.lstatSync(webRoot).isDirectory() && !fs.lstatSync(webRoot).isSymbolicLink(), 'Web root must be a real directory');
  const files = {};
  async function walk(directory, prefix = '') {
    for (const name of fs.readdirSync(directory).sort()) {
      if (name.startsWith('.') || ['node_modules', '__pycache__'].includes(name)) continue;
      const full = path.join(directory, name), relative = prefix + name, stat = fs.lstatSync(full);
      requireValue(!stat.isSymbolicLink(), 'Web inventory contains a symlink');
      if (stat.isDirectory()) await walk(full, relative + '/');
      else {
        requireValue(stat.isFile() && safeRelative(relative), 'Web inventory contains an invalid entry');
        files[relative] = { bytes: stat.size, sha256: await hashFile(full) };
      }
    }
  }
  await walk(webRoot);
  requireValue(Object.keys(files).length > 0, 'Web inventory is empty');
  return { schema: 'lightforge.web-capture-lock.v1', files };
}
function validateLock(lock) {
  requireValue(lock.schema === 'lightforge.web-capture-lock.v1' && plain(lock.files), 'Invalid web inventory lock');
  requireValue(Object.keys(lock).sort().join(',') === 'files,schema', 'Unexpected web lock fields');
  for (const [name, record] of Object.entries(lock.files)) {
    requireValue(safeRelative(name) && plain(record) && Object.keys(record).sort().join(',') === 'bytes,sha256' &&
      Number.isSafeInteger(record.bytes) && record.bytes >= 0 && HEX.test(record.sha256), 'Invalid locked web entry');
  }
  return hashBytes(canonical(lock));
}
function bootstrapScripts(lock) {
  validateLock(lock);
  for (const name of CORE_FILES) requireValue(Object.hasOwn(lock.files, name) && lock.files[name].bytes > 0, 'Required production capture file absent: ' + name);
  // Older published baselines lack later enhancement modules. Load only bytes
  // present in this distribution's independently locked inventory; never
  // import candidate modules or fabricate absent baseline outputs.
  return BOOTSTRAP_ORDER.filter(name => Object.hasOwn(lock.files, name));
}
function validateIdentity(identity, lockDigest) {
  const names = ['source_commit', 'source_tree_sha', 'web_manifest_sha256', 'pipeline_version', 'preprocessing_version', 'track_id', 'run_id', 'report_side'];
  requireValue(Object.keys(identity).sort().join(',') === names.sort().join(','), 'Identity must contain exactly the declared identity fields');
  requireValue(names.every(name => typeof identity[name] === 'string'), 'All identity fields must be strings');
  requireValue(/^[0-9a-f]{40}$/.test(identity.source_commit) && /^[0-9a-f]{40}$/.test(identity.source_tree_sha), 'Invalid source commit/tree identity');
  requireValue(identity.web_manifest_sha256 === lockDigest, 'Declared source inventory hash differs from the web lock');
  for (const key of ['pipeline_version', 'preprocessing_version', 'track_id', 'run_id']) requireValue(OPAQUE.test(identity[key]), 'Invalid opaque identity field: ' + key);
  requireValue(['baseline', 'candidate'].includes(identity.report_side), 'Invalid report side');
}
function validateConfiguration(config) {
  requireValue(Object.keys(config).sort().join(',') === 'analysis_options,show_settings' && plain(config.analysis_options) && plain(config.show_settings), 'Configuration must explicitly provide analysis_options and show_settings');
  requireValue(['precision', 'balanced'].includes(config.analysis_options.analysisQuality), 'Choose explicit precision or balanced analysisQuality');
  // The harness owns source/cache identity and cannot claim a native bridge.
  for (const key of Object.keys(config.analysis_options)) {
    requireValue(!/native|identity|fingerprint|refresh|projectId|cacheKey|workId|supportsNative/i.test(key), 'Reserved analysis option: ' + key);
  }
  requireValue(Number.isSafeInteger(config.show_settings.seed) && config.show_settings.seed >= 0 && config.show_settings.seed <= 0xffffffff, 'An explicit uint32 show seed is required');
  requireValue([15, 20].includes(config.show_settings.stepMs), 'An explicit 15 or 20 ms show frame interval is required');
  canonical(config);
}
function wavInfo(file) {
  const stat = regular(file);
  requireValue(stat.size >= 44 && stat.size <= MAX_WAV_BYTES, 'WAV size is outside capture bounds');
  const descriptor = fs.openSync(file, 'r');
  try {
    const read = (position, length) => { const buffer = Buffer.alloc(length); requireValue(fs.readSync(descriptor, buffer, 0, length, position) === length, 'Truncated WAV'); return buffer; };
    const header = read(0, 12);
    requireValue(header.toString('ascii', 0, 4) === 'RIFF' && header.toString('ascii', 8, 12) === 'WAVE', 'Only RIFF/WAVE input is supported');
    requireValue(header.readUInt32LE(4) + 8 === stat.size, 'WAV RIFF size differs from the file');
    let offset = 12, format = null, data = null, count = 0;
    while (offset + 8 <= stat.size) {
      requireValue(++count <= 4096, 'Too many WAV chunks for the production reader');
      const chunk = read(offset, 8), name = chunk.toString('ascii', 0, 4), length = chunk.readUInt32LE(4);
      requireValue(offset + 8 + length <= stat.size, 'WAV chunk exceeds file bounds');
      if (name === 'fmt ') {
        requireValue(!format && length >= 16 && length <= 65536, 'Invalid or duplicate WAV fmt chunk');
        const bytes = read(offset + 8, length), formatTag = bytes.readUInt16LE(0);
        format = { format_tag: formatTag, channels: bytes.readUInt16LE(2), sample_rate: bytes.readUInt32LE(4), byte_rate: bytes.readUInt32LE(8), block_align: bytes.readUInt16LE(12), bits_per_sample: bytes.readUInt16LE(14) };
        if (formatTag === 0xfffe) {
          requireValue(length >= 40 && bytes.readUInt16LE(16) >= 22 && bytes.readUInt16LE(16) + 18 === length, 'Invalid extensible WAV extension size');
          const guid = bytes.subarray(24, 40).toString('hex');
          requireValue(['0100000000001000800000aa00389b71', '0300000000001000800000aa00389b71'].includes(guid), 'Unsupported extensible WAV subtype GUID');
          format.subformat_tag = bytes.readUInt16LE(24);
          format.valid_bits_per_sample = bytes.readUInt16LE(18);
          format.channel_mask = bytes.readUInt32LE(20);
          requireValue(format.valid_bits_per_sample > 0 && format.valid_bits_per_sample <= format.bits_per_sample, 'Invalid extensible WAV valid bits');
        }
      } else if (name === 'data') { requireValue(format !== null, 'WAV fmt must precede data for the production reader'); requireValue(data === null, 'Duplicate WAV data chunk'); data = { offset: offset + 8, bytes: length }; }
      offset += 8 + length + (length % 2);
    }
    requireValue(offset === stat.size && format && data && data.bytes > 0, 'Incomplete WAV chunk inventory');
    const tag = format.subformat_tag || format.format_tag;
    requireValue([1, 3].includes(tag) && [1, 2].includes(format.channels) && [16, 24, 32].includes(format.bits_per_sample) && (tag !== 3 || format.bits_per_sample === 32), 'Unsupported PCM/float WAV encoding');
    requireValue(format.sample_rate === 44100, 'The complete production pipeline requires decoded 44.1 kHz WAV');
    requireValue(format.block_align === format.channels * format.bits_per_sample / 8 && format.byte_rate === format.sample_rate * format.block_align && data.bytes % format.block_align === 0, 'Inconsistent WAV audio properties');
    requireValue(data.bytes / format.byte_rate >= 1 && data.bytes / format.byte_rate <= 14400, 'The production pipeline requires 1 second to 4 hours of audio');
    return { ...format, sample_frames: data.bytes / format.block_align, duration_seconds: data.bytes / format.byte_rate, data_bytes: data.bytes, file_bytes: stat.size };
  } finally { fs.closeSync(descriptor); }
}
function parseRange(value, size) {
  if (value === undefined) return { start: 0, end: size - 1, partial: false };
  const match = /^bytes=(\d+)-(\d*)$/.exec(value);
  requireValue(match && size > 0, 'Invalid byte range');
  const start = Number(match[1]), end = match[2] ? Math.min(Number(match[2]), size - 1) : size - 1;
  requireValue(Number.isSafeInteger(start) && Number.isSafeInteger(end) && start >= 0 && start <= end && start < size, 'Invalid byte range');
  return { start, end, partial: true };
}
function createServer(webRoot, wav, lock, served) {
  const scripts = bootstrapScripts(lock);
  const html = '<!doctype html><meta charset="utf-8"><title>LightForge capture</title>' + scripts.map(name => '<script src="/' + name + '"></script>').join('');
  return http.createServer((request, response) => {
    try {
    response.setHeader('Cross-Origin-Opener-Policy', 'same-origin');
    response.setHeader('Cross-Origin-Embedder-Policy', 'require-corp');
    response.setHeader('Cache-Control', 'no-store');
    if (!['GET', 'HEAD'].includes(request.method)) { response.writeHead(405).end(); return; }
    let pathname;
    try { pathname = decodeURIComponent(new URL(request.url, 'http://local').pathname); } catch { response.writeHead(400).end(); return; }
    if (pathname === '/') { response.setHeader('Content-Type', 'text/html'); response.end(request.method === 'HEAD' ? undefined : html); return; }
    const relative = pathname.slice(1), isAudio = relative === '__capture__/input.wav';
    if (!isAudio && (!safeRelative(relative) || !Object.hasOwn(lock.files, relative))) { response.writeHead(404).end(); return; }
    const file = isAudio ? wav : path.join(webRoot, relative), stat = regular(file);
    if (!isAudio) served.add(relative);
    let range;
    try { range = parseRange(request.headers.range, stat.size); } catch { response.setHeader('Content-Range', 'bytes */' + stat.size); response.writeHead(416).end(); return; }
    response.setHeader('Content-Type', ({ '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.wasm': 'application/wasm', '.wav': 'audio/wav' })[path.extname(file)] || 'application/octet-stream');
    response.setHeader('Content-Length', stat.size === 0 ? 0 : range.end - range.start + 1);
    if (range.partial) { response.statusCode = 206; response.setHeader('Content-Range', `bytes ${range.start}-${range.end}/${stat.size}`); }
    if (request.method === 'HEAD' || stat.size === 0) response.end();
    else fs.createReadStream(file, { start: range.start, end: range.end }).on('error', () => response.destroy()).pipe(response);
    } catch { if (!response.headersSent) response.writeHead(500); response.end(); }
  });
}
function select(source, names) { return Object.fromEntries(names.filter(name => Object.hasOwn(source, name)).map(name => [name, source[name]])); }
function outputCategories(music, show, fseq) {
  const categories = {}, missing = {};
  function add(name, value) { if (value === undefined || value === null) missing[name] = 'not emitted by the actual configured application'; else categories[name] = value; }
  add('semantic_timeline', music.semanticTimeline);
  const rhythm = select(music, ['bpm', 'beats', 'downbeats', 'beatDetails', 'beatConfidence', 'meter', 'meterConfidence', 'groove', 'phrases', 'rhythmHierarchy']);
  add('rhythm_map', Object.keys(rhythm).length ? rhythm : undefined);
  add('vocal_map', Object.hasOwn(music, 'vocals') ? select(music, ['vocals', 'vocalSemantics', 'vocalSemanticLinks']) : undefined);
  add('bass_map', Object.hasOwn(music, 'bassNotes') ? select(music, ['bassNotes', 'bassAnalysis']) : undefined);
  add('drum_map', music.percussionAnalysis);
  add('section_map', Object.hasOwn(music, 'sections') ? select(music, ['sections', 'recurrenceAnalysis', 'recurrenceEvidence', 'recurrenceSidecar']) : undefined);
  add('salience_map', music.musicSalience);
  add('choreography_plan', Object.hasOwn(show, 'choreography') ? select(show, ['choreography', 'movements', 'sections', 'settings']) : undefined);
  add('fseq_characteristics', fseq);
  add('validation_report', show.validation);
  return { categories, missing };
}
function emit(phase, extra = {}) { process.stdout.write(JSON.stringify({ schema: SCHEMA, phase, monotonic_ns: process.hrtime.bigint().toString(), wall_clock: new Date().toISOString(), ...extra }) + '\n'); }
function parseArgs(argv) {
  const options = {};
  requireValue(argv.length && ['capture', 'inventory'].includes(argv[0]), 'Usage: capture-app.cjs inventory|capture --app-root PATH ...');
  options.command = argv[0];
  const allowed = new Set(['app-root', 'wav', 'audio-sha256', 'configuration', 'identity', 'web-manifest', 'output-dir', 'output', 'timeout-seconds']);
  for (let i = 1; i < argv.length; i += 2) {
    const key = argv[i]?.replace(/^--/, '');
    requireValue(argv[i]?.startsWith('--') && allowed.has(key) && argv[i + 1] !== undefined && !Object.hasOwn(options, key), 'Invalid or duplicate command argument');
    options[key] = argv[i + 1];
  }
  requireValue(options['app-root'], '--app-root is required');
  if (options.command === 'inventory') requireValue(options.output && Object.keys(options).length === 3, 'inventory requires only --app-root and --output');
  else for (const key of ['wav', 'audio-sha256', 'configuration', 'identity', 'web-manifest', 'output-dir']) requireValue(options[key], 'Missing --' + key);
  return options;
}
// Runs in both Node tests and the browser realm. Validate before JSON.stringify
// can turn NaN/Infinity into null. Preserve the historical JSON representation
// of numeric typed arrays used by ShowEngine's derived preview index.
function producerJson(value, maxBytes = 128 * 1024 ** 2) {
  const active = new Set();
  function visit(item, where, depth, inArray = false) {
    if (depth > 512) throw Error('Producer JSON nesting exceeds 512 at ' + where);
    if (item === null || typeof item === 'string' || typeof item === 'boolean') return;
    if (typeof item === 'number') { if (!Number.isFinite(item)) throw Error('Non-finite producer number at ' + where); return; }
    if (item === undefined && !inArray) return; // JSON object fields omitted by the producer are recorded as missing.
    if (typeof item !== 'object' || item === null) throw Error('Unsupported producer JSON value at ' + where);
    if (active.has(item)) throw Error('Circular producer JSON at ' + where);
    if (Object.hasOwn(item, 'toJSON') || typeof item.toJSON === 'function') throw Error('Producer JSON custom serialization at ' + where);
    const array = Array.isArray(item), typed = ArrayBuffer.isView(item) && !(item instanceof DataView);
    if (!array && !typed && Object.getPrototypeOf(item) !== Object.prototype) throw Error('Unsupported producer JSON object at ' + where);
    active.add(item);
    for (const key of Object.keys(item)) {
      const descriptor = Object.getOwnPropertyDescriptor(item, key);
      if (descriptor.get || descriptor.set) throw Error('Producer JSON accessor at ' + where + '.' + key);
      visit(descriptor.value, where + '.' + key, depth + 1, array || typed);
    }
    if (array) for (let i = 0; i < item.length; ++i) if (!Object.hasOwn(item, i)) throw Error('Sparse producer JSON array at ' + where);
    active.delete(item);
  }
  visit(value, '$', 0);
  const json = JSON.stringify(value);
  if (typeof json !== 'string') throw Error('Producer omitted the entire JSON value');
  if (new TextEncoder().encode(json).byteLength > maxBytes) throw Error('Producer JSON exceeds the artifact byte bound');
  return json;
}
function captureProjectId(identity) {
  return 'capture-' + hashBytes(canonical({ track_id: identity.track_id, run_id: identity.run_id }));
}
function initialReport() {
  return { schema: SCHEMA, status: 'failed', production_ready: false, qualification_status: 'not_evaluated', physical_validation: 'unverified', limitations: ['Raw application observations only; no complete metric contract, annotation scoring, paired comparison or authenticated human review.', 'Browser/WASM execution without Android native model bridges.', 'Fresh browser origin/cache only; host page-cache, energy and thermal conditions are not controlled or measured by this runner.'] };
}
function checkpoint(out, report) {
  const next = path.join(out, '.capture-next.json');
  try { writeJson(next, report); fs.renameSync(next, path.join(out, '.capture-checkpoint.json')); }
  catch (error) {
    try { fs.unlinkSync(next); } catch {}
    const fallback = initialReport();
    fallback.error = 'Capture receipt serialization failed: ' + String(error.message || error).slice(0, 500);
    // Never turn malformed producer data into a success or silently replace it.
    writeJson(next, fallback); fs.renameSync(next, path.join(out, '.capture-checkpoint.json'));
    throw error;
  }
}
function retainRawArtifacts(out, result, report) {
  const artifacts = report.artifacts = {}, missing = report.missing_optional_artifacts = {};
  const failures = report.artifact_errors = [];
  function save(name, bytes) {
    fs.writeFileSync(path.join(out, name), bytes, { flag: 'wx', mode: 0o600 });
    artifacts[name] = { bytes: bytes.length, sha256: hashBytes(bytes) };
  }
  function json(name, value) {
    if (value === undefined) { missing[name] = 'not emitted or not serializable by the actual configured application'; return; }
    try { const bytes = Buffer.from(canonical(value) + '\n'); requireValue(bytes.length <= 128 * 1024 ** 2, 'JSON artifact exceeds 128 MiB'); save(name, bytes); }
    catch (error) { failures.push({ artifact: name, error: String(error.message || error).slice(0, 500) }); }
  }
  for (const [name, value] of Object.entries({ 'analysis.json': result.music, 'show.json': result.show, 'compiled.json': result.compiled, 'progress.json': result.progress, 'compiler-profile.json': result.compiler_profile })) json(name, value);
  json('perceptual-validation.json', plain(result.show) ? result.show.perceptualValidation : undefined);
  let frames, header;
  for (const [key, name, bound] of [['frames', 'show.frames.bin', 192000000], ['header', 'show.header.bin', 65535]]) {
    if (typeof result[key] !== 'string') { missing[name] = 'actual compiler bytes were not emitted'; continue; }
    try {
      requireValue(result[key].length <= 4 * Math.ceil(bound / 3), 'Invalid or oversized compiler byte transport');
      const bytes = Buffer.from(result[key], 'base64'); requireValue(bytes.length <= bound && bytes.toString('base64') === result[key], 'Invalid compiler byte transport');
      save(name, bytes); if (key === 'frames') frames = bytes; else header = bytes;
    } catch (error) { failures.push({ artifact: name, error: String(error.message || error).slice(0, 500) }); }
  }
  if (result.producer_error || result.serialization_errors?.length) json('producer-failure.json', { producer_error: result.producer_error || null, serialization_errors: result.serialization_errors || [] });
  report.raw_evidence_status = 'retained-before-validation; not-qualified';
  return { save, frames, header };
}
function captureDeadlineSeconds(options) {
  const seconds = options['timeout-seconds'] === undefined ? 3600 : Number(options['timeout-seconds']);
  requireValue(Number.isSafeInteger(seconds) && seconds >= 1 && seconds <= 14400, 'Capture deadline must be 1..14400 seconds');
  return seconds;
}
async function captureWorker(options) {
  const seconds = captureDeadlineSeconds(options);
  const webRoot = path.resolve(options['app-root'], 'web'), wav = path.resolve(options.wav), out = path.resolve(options['output-dir']);
  const report = initialReport();
  let server, browser, success = false;
  const errors = [], blocked = [];
  let blockedCount = 0, browserErrorCount = 0;
  const persist = () => checkpoint(out, report);
  try {
    persist();
    const lock = readJson(options['web-manifest']), lockDigest = validateLock(lock), identity = readJson(options.identity), config = readJson(options.configuration);
    validateIdentity(identity, lockDigest); validateConfiguration(config);
    requireValue(HEX.test(options['audio-sha256']), 'Invalid locked audio SHA-256');
    const audio = wavInfo(wav), audioHash = await hashFile(wav);
    requireValue(audioHash === options['audio-sha256'], 'Audio content differs from the supplied lock');
    requireValue(canonical(await inventory(webRoot)) === canonical(lock), 'Current web bytes differ from the supplied source lock');
    const scripts = bootstrapScripts(lock);
    const manifest = readJson(path.join(webRoot, 'analysis/ASSET_MANIFEST.json'));
    for (const [name, record] of Object.entries(manifest)) requireValue(safeRelative(name) && canonical(lock.files['analysis/' + name]) === canonical(record), 'Analysis asset differs from its production manifest: ' + name);
    const projectId = captureProjectId(identity);
    Object.assign(report, { identity, source_identity_binding: { git_commit_and_tree: 'caller-declared', web_inventory: 'verified-against-supplied-lock', git_to_inventory_binding: 'requires-independent-release-orchestration' }, configuration: config, configuration_sha256: hashBytes(canonical(config)), audio: { ...audio, content_sha256: audioHash }, source_lock_sha256: lockDigest, collector_sha256: await hashFile(__filename), collector_support_sha256: Object.fromEntries(await Promise.all(['strict-json.cjs', 'capture-supervisor.cjs', 'capture-supervisor.py'].map(async name => [name, await hashFile(path.join(__dirname, name))]))), cache_condition: { browser_origin: 'fresh', browser_http_cache: 'disabled', persisted_app_state: 'empty', host_page_cache: 'uncontrolled', release_controlled: false }, submitted_analysis_options: { ...config.analysis_options, analysisIdentity: audioHash, projectId } });
    report.bootstrap = { loaded_scripts: scripts, absent_optional_scripts: BOOTSTRAP_ORDER.filter(name => !scripts.includes(name)), source: 'locked-distribution-only' };
    persist();
    const served = new Set();
    server = createServer(webRoot, wav, lock, served);
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
    const origin = 'http://127.0.0.1:' + server.address().port;
    const { chromium } = require('playwright');
    const launch = { headless: true, timeout: seconds * 1000, args: ['--no-sandbox', '--enable-unsafe-swiftshader', '--disable-background-networking', '--disable-component-update'] };
    if (process.env.PLAYWRIGHT_EXECUTABLE_PATH) launch.executablePath = process.env.PLAYWRIGHT_EXECUTABLE_PATH;
    browser = await chromium.launch(launch);
    const context = await browser.newContext({ serviceWorkers: 'block' });
    await context.route('**/*', route => { const url = new URL(route.request().url()); if (url.origin === origin) return route.continue(); blockedCount++; if (blocked.length < 1000) blocked.push(url.protocol + '//external'); return route.abort(); });
    const page = await context.newPage();
    page.on('pageerror', error => { browserErrorCount++; if (errors.length < 1000) errors.push(error.message.slice(0,400)); });
    page.setDefaultTimeout(seconds * 1000);
    await page.goto(origin); await page.waitForFunction(() => !!window.MusicAnalyzer && !!window.ShowCompiler);
    requireValue(await page.evaluate(() => crossOriginIsolated), 'Capture is not cross-origin isolated');
    await page.addScriptTag({ content: 'globalThis.__captureProducerJson = ' + producerJson.toString() + ';' });
    report.runtime = { browser: browser.version(), node: process.version, platform: process.platform, arch: process.arch, logical_cpus: os.availableParallelism(), model_asset_manifest_sha256: await hashFile(path.join(webRoot, 'analysis/ASSET_MANIFEST.json')), harness: 'production analyzer/compiler scripts without app UI', external_network_requests_blocked: 0 };
    persist();
    await page.exposeFunction('__capturePhase', (phase, extra) => emit(phase, { ...extra, track_id: identity.track_id, run_id: identity.run_id, report_side: identity.report_side }));
    const result = await page.evaluate(async ({ config, options }) => {
      function base64(array) { let s = ''; for (let i = 0; i < array.length; i += 24576) s += String.fromCharCode(...array.subarray(i, i + 24576)); return btoa(s); }
      const raw = { progress: [] }, result = { serialization_errors: [] };
      let lastProgress = -1;
      try {
        await window.__capturePhase('analysis_start', {}); const analysisStart = performance.now();
        raw.music = await MusicAnalyzer.analyze('/__capture__/input.wav', options, value => {
          if (raw.progress.length < 20000) raw.progress.push({ progress: value.progress, stage: value.stage, elapsedSeconds: value.elapsedSeconds ?? null });
          if (value.progress < lastProgress) throw Error('Analysis progress moved backwards');
          lastProgress = value.progress;
        });
        const analysisEnd = performance.now(); await window.__capturePhase('analysis_end', { duration_ms: analysisEnd - analysisStart });
        raw.timing = { clock: 'performance.now', analysis_ms: analysisEnd - analysisStart, analysis_start_ms: analysisStart, analysis_end_ms: analysisEnd };
        await window.__capturePhase('compilation_start', {}); const compilationStart = performance.now();
        const generated = await ShowCompiler.generate(raw.music, config.show_settings);
        const compilationEnd = performance.now(); await window.__capturePhase('compilation_end', { duration_ms: compilationEnd - compilationStart });
        Object.assign(raw.timing, { compilation_ms: compilationEnd - compilationStart, compilation_start_ms: compilationStart, compilation_end_ms: compilationEnd });
        const { frames, ...show } = generated.show;
        raw.show = show; raw.compiled = generated.compiled; raw.compiler_profile = generated.profile;
        if (!(frames instanceof Uint8Array) || !(generated.header instanceof Uint8Array)) throw Error('Compiler did not return actual frame/header bytes');
        if (frames.byteLength > 192000000 || generated.header.byteLength > 65535) throw Error('Compiler bytes exceed the artifact bound');
        result.frames = base64(frames); result.header = base64(generated.header);
      } catch (error) { result.producer_error = String(error.message || error).slice(0, 1000); }
      for (const [name, value] of Object.entries(raw)) {
        try { result[name] = JSON.parse(window.__captureProducerJson(value)); }
        catch (error) { result.serialization_errors.push({ field: name, error: String(error.message || error).slice(0, 500) }); }
      }
      return result;
    }, { config, options: report.submitted_analysis_options });
    // Preserve all bounded, safely serializable observations before deciding
    // whether the producer result, validation or package dimensions are valid.
    const retained = retainRawArtifacts(out, result, report);
    report.timing = result.timing || { status: 'unavailable', reason: 'application-timings-not-emitted' };
    report.effective_show_settings = result.show?.settings === undefined ? { status: 'unavailable', reason: 'compiler-did-not-emit-settings' } : result.show.settings;
    report.engine = result.music?.engine === undefined ? { status: 'unavailable', reason: 'analyzer-did-not-emit-engine-report' } : result.music.engine;
    report.resource_observations = result.music?.engine?.resourceDiagnostics || { status: 'unavailable', reason: 'application-did-not-emit-resource-diagnostics' };
    report.compiler_profile = result.compiler_profile || { status: 'unavailable', reason: 'compiler-did-not-emit-timing-profile' };
    report.served_source_hashes = Object.fromEntries([...served].sort().map(name => [name, lock.files[name]]));
    report.progress_records = Array.isArray(result.progress) ? result.progress.length : 0;
    persist();
    requireValue(!result.producer_error && result.serialization_errors?.length === 0 && report.artifact_errors.length === 0, 'Producer or artifact serialization failed; see retained failure evidence');
    requireValue(errors.length === 0 && blocked.length === 0, 'Browser errors or external requests occurred during capture');
    requireValue(plain(result.music) && plain(result.show) && plain(result.compiled), 'Application did not emit its required result objects');
    requireValue(result.show.validation?.valid === true, 'Actual generated show did not pass application validation');
    const { frames, header, save } = retained;
    requireValue(Buffer.isBuffer(frames) && Buffer.isBuffer(header), 'Compiler frame/header bytes are missing');
    requireValue(header.length >= 32 && header.toString('ascii', 0, 4) === 'PSEQ' && header.readUInt16LE(4) === header.length, 'Compiler emitted invalid FSEQ header');
    requireValue(frames.length === result.show.frameCount * result.show.channelCount && header.readUInt32LE(10) === result.show.channelCount && header.readUInt32LE(14) === result.show.frameCount && header[18] === result.show.stepMs, 'FSEQ payload dimensions differ from application metadata');
    requireValue(hashBytes(frames) === result.compiled.sha256, 'Actual frame bytes differ from compiled payload digest');
    requireValue(await hashFile(wav) === audioHash && canonical(await inventory(webRoot)) === canonical(lock), 'Locked audio or application source changed during capture');
    const fseq = Buffer.concat([header, frames]);
    const fseqProperties = { version_major: header[7], version_minor: header[6], data_offset: header.length, channel_count: result.show.channelCount, frame_count: result.show.frameCount, step_ms: result.show.stepMs, sequence_bytes: fseq.length, frame_bytes: frames.length, frames_sha256: hashBytes(frames), fseq_sha256: hashBytes(fseq) };
    const projection = outputCategories(result.music, result.show, fseqProperties), goldens = {};
    save('lightshow.fseq', fseq);
    for (const [name, value] of Object.entries(projection.categories)) { const file = name + '.json'; save(file, Buffer.from(canonical(value) + '\n')); goldens[name + '_sha256'] = report.artifacts[file].sha256; }
    Object.assign(report, { status: 'captured', observed_output_hashes: goldens, missing_output_categories: projection.missing });
    success = true;
  } catch (error) { report.error = String(error.message || error).slice(0, 1000); }
  finally {
    report.browser_errors = errors;
    report.external_network_requests_blocked = blockedCount;
    report.browser_error_count = browserErrorCount;
    report.browser_errors_omitted = browserErrorCount - errors.length;
    if (report.runtime) report.runtime.external_network_requests_blocked = blockedCount;
    persist(); // The supervisor can retain this even when browser.close hangs.
    try { await browser?.close(); } catch { report.cleanup_error = 'browser-close-failed'; success = false; }
    if (server?.listening) { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
  }
  if (!success) { report.status = 'failed'; delete report.observed_output_hashes; }
  report.completed_at = new Date().toISOString();
  persist();
  return success ? 0 : 1;
}
async function capture(options) {
  const out = path.resolve(options['output-dir']);
  requireValue(!fs.existsSync(out), 'Output directory already exists; use a new attempt directory');
  const seconds = captureDeadlineSeconds(options);
  fs.mkdirSync(out, { recursive: false, mode: 0o700 });
  let report = initialReport(), outcome;
  try {
    checkpoint(out, report);
    const args = [__filename, '__capture-worker', 'capture'];
    for (const [name, value] of Object.entries(options)) if (name !== 'command') args.push('--' + name, String(value));
    outcome = await supervise({ executable: process.execPath, args, timeoutMs: seconds * 1000, env: { ...process.env, LIGHTFORGE_CAPTURE_SUPERVISED: '1' } });
    report = readJson(path.join(out, '.capture-checkpoint.json'));
    report.supervision = outcome;
    if (outcome.exit_code !== 0 || report.status !== 'captured') {
      report.status = 'failed';
      if (outcome.timed_out) { report.timeout = true; report.error = 'Capture exceeded its whole-worker deadline, including startup or cleanup'; }
      else if (!report.error) report.error = 'Capture worker or supervised cleanup failed';
    }
  } catch (error) { report.status = 'failed'; report.error = String(error.message || error).slice(0, 1000); if (outcome) report.supervision = outcome; }
  if (report.status !== 'captured') delete report.observed_output_hashes;
  report.completed_at = new Date().toISOString();
  try { writeJson(path.join(out, 'capture.json'), report); }
  catch (error) {
    report = { ...initialReport(), error: 'Final receipt serialization failed: ' + String(error.message || error).slice(0, 500), completed_at: new Date().toISOString() };
    writeJson(path.join(out, 'capture.json'), report);
  }
  for (const name of ['.capture-checkpoint.json', '.capture-next.json']) try { fs.unlinkSync(path.join(out, name)); } catch {}
  emit(report.status, { output_directory: out, production_ready: false, error: report.error || null });
  return report.status === 'captured' ? 0 : 1;
}
async function main(argv = process.argv.slice(2)) {
  if (argv[0] === '__capture-worker') {
    requireValue(process.env.LIGHTFORGE_CAPTURE_SUPERVISED === '1', 'Internal capture worker requires its supervisor');
    return captureWorker(parseArgs(argv.slice(1)));
  }
  const options = parseArgs(argv);
  if (options.command === 'inventory') {
    const lock = await inventory(path.resolve(options['app-root'], 'web'));
    writeJson(options.output, lock);
    process.stdout.write(JSON.stringify({ web_manifest_sha256: validateLock(lock), files: Object.keys(lock.files).length }) + '\n');
    return 0;
  }
  return capture(options);
}
module.exports = { plain, readJson, producerJson, captureProjectId, retainRawArtifacts, checkpoint, canonical, hashBytes, inventory, validateLock, bootstrapScripts, validateIdentity, validateConfiguration, wavInfo, parseRange, createServer, outputCategories, parseArgs, capture, main };
if (require.main === module) main().then(code => { process.exitCode = code; }).catch(error => { process.stderr.write(String(error.message || error) + '\n'); process.exitCode = 1; });
