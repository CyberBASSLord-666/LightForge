#!/usr/bin/env node
'use strict';
/* Execute the unmodified browser analyzer/compiler against a hash-locked WAV.
 * This is a raw observation collector, never a complete release qualification. */
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');
const os = require('node:os');

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
function plain(value) { return value !== null && Object.getPrototypeOf(value) === Object.prototype; }
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
  const value = JSON.parse(fs.readFileSync(file, 'utf8'));
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
    requireValue(data.bytes / format.byte_rate >= 1 && data.bytes / format.byte_rate <= 14400.05, 'The production pipeline requires 1 second to 4 hours of audio');
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
async function capture(options) {
  const webRoot = path.resolve(options['app-root'], 'web'), wav = path.resolve(options.wav), out = path.resolve(options['output-dir']);
  requireValue(!fs.existsSync(out), 'Output directory already exists; use a new attempt directory');
  fs.mkdirSync(out, { recursive: false, mode: 0o700 });
  const report = { schema: SCHEMA, status: 'failed', production_ready: false, qualification_status: 'not_evaluated', physical_validation: 'unverified', limitations: ['Raw application observations only; no complete metric contract, annotation scoring, paired comparison or authenticated human review.', 'Browser/WASM execution without Android native model bridges.', 'Fresh browser origin/cache only; host page-cache, energy and thermal conditions are not controlled or measured by this runner.'] };
  let server, browser, timeout, success = false;
  const errors = [], blocked = [];
  try {
    const lock = readJson(options['web-manifest']), lockDigest = validateLock(lock), identity = readJson(options.identity), config = readJson(options.configuration);
    validateIdentity(identity, lockDigest); validateConfiguration(config);
    requireValue(HEX.test(options['audio-sha256']), 'Invalid locked audio SHA-256');
    const audio = wavInfo(wav), audioHash = await hashFile(wav);
    requireValue(audioHash === options['audio-sha256'], 'Audio content differs from the supplied lock');
    requireValue(canonical(await inventory(webRoot)) === canonical(lock), 'Current web bytes differ from the supplied source lock');
    const scripts = bootstrapScripts(lock);
    const manifest = readJson(path.join(webRoot, 'analysis/ASSET_MANIFEST.json'));
    for (const [name, record] of Object.entries(manifest)) requireValue(safeRelative(name) && canonical(lock.files['analysis/' + name]) === canonical(record), 'Analysis asset differs from its production manifest: ' + name);
    Object.assign(report, { identity, source_identity_binding: { git_commit_and_tree: 'caller-declared', web_inventory: 'verified-against-supplied-lock', git_to_inventory_binding: 'requires-independent-release-orchestration' }, configuration: config, configuration_sha256: hashBytes(canonical(config)), audio: { ...audio, content_sha256: audioHash }, source_lock_sha256: lockDigest, collector_sha256: await hashFile(__filename), cache_condition: { browser_origin: 'fresh', browser_http_cache: 'disabled', persisted_app_state: 'empty', host_page_cache: 'uncontrolled', release_controlled: false } });
    report.bootstrap = { loaded_scripts: scripts, absent_optional_scripts: BOOTSTRAP_ORDER.filter(name => !scripts.includes(name)), source: 'locked-distribution-only' };
    const served = new Set();
    server = createServer(webRoot, wav, lock, served);
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
    const origin = 'http://127.0.0.1:' + server.address().port;
    const { chromium } = require('playwright');
    const launch = { headless: true, args: ['--no-sandbox', '--enable-unsafe-swiftshader', '--disable-background-networking', '--disable-component-update'] };
    if (process.env.PLAYWRIGHT_EXECUTABLE_PATH) launch.executablePath = process.env.PLAYWRIGHT_EXECUTABLE_PATH;
    browser = await chromium.launch(launch);
    const context = await browser.newContext({ serviceWorkers: 'block' });
    await context.route('**/*', route => { const url = new URL(route.request().url()); if (url.origin === origin) return route.continue(); blocked.push(url.protocol + '//external'); return route.abort(); });
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message.slice(0,400)));
    const seconds = options['timeout-seconds'] === undefined ? 3600 : Number(options['timeout-seconds']);
    requireValue(Number.isSafeInteger(seconds) && seconds >= 1 && seconds <= 14400, 'Capture deadline must be 1..14400 seconds');
    page.setDefaultTimeout(seconds * 1000);
    timeout = setTimeout(() => { report.timeout = true; browser.close().catch(() => {}); }, seconds * 1000);
    await page.goto(origin); await page.waitForFunction(() => !!window.MusicAnalyzer && !!window.ShowCompiler);
    requireValue(await page.evaluate(() => crossOriginIsolated), 'Capture is not cross-origin isolated');
    report.runtime = { browser: browser.version(), node: process.version, platform: process.platform, arch: process.arch, logical_cpus: os.availableParallelism(), model_asset_manifest_sha256: await hashFile(path.join(webRoot, 'analysis/ASSET_MANIFEST.json')), harness: 'production analyzer/compiler scripts without app UI', external_network_requests_blocked: 0 };
    // Chromium bindings emit transitions while work runs, so an external process
    // monitor can align its observations; collection/startup time remains separate.
    await page.exposeFunction('__capturePhase', (phase, extra) => emit(phase, { ...extra, track_id: identity.track_id, run_id: identity.run_id, report_side: identity.report_side }));
    const result = await page.evaluate(async ({ config, identity, audioHash }) => {
      function base64(array) { let s = ''; for (let i = 0; i < array.length; i += 24576) s += String.fromCharCode(...array.subarray(i, i + 24576)); return btoa(s); }
      const progress = []; let lastProgress = -1;
      const options = { ...config.analysis_options, analysisIdentity: audioHash, projectId: 'capture-' + identity.track_id + '-' + identity.run_id };
      await window.__capturePhase('analysis_start', {}); const analysisStart = performance.now();
      const music = await MusicAnalyzer.analyze('/__capture__/input.wav', options, value => {
        if (progress.length < 20000) progress.push({ progress: value.progress, stage: value.stage, elapsedSeconds: value.elapsedSeconds ?? null });
        if (value.progress < lastProgress) throw Error('Analysis progress moved backwards');
        lastProgress = value.progress;
      });
      const analysisEnd = performance.now(); await window.__capturePhase('analysis_end', { duration_ms: analysisEnd - analysisStart });
      await window.__capturePhase('compilation_start', {}); const compilationStart = performance.now();
      const generated = await ShowCompiler.generate(music, config.show_settings);
      const compilationEnd = performance.now(); await window.__capturePhase('compilation_end', { duration_ms: compilationEnd - compilationStart });
      const { frames, ...show } = generated.show;
      if (!(frames instanceof Uint8Array) || !(generated.header instanceof Uint8Array)) throw Error('Compiler did not return actual frame/header bytes');
      if (frames.byteLength > 192000000) throw Error('Compiler frame result exceeds its production bound');
      return JSON.parse(JSON.stringify({ music, show, compiled: generated.compiled, frames: base64(frames), header: base64(generated.header), progress,
        timing: { clock: 'performance.now', analysis_ms: analysisEnd - analysisStart, compilation_ms: compilationEnd - compilationStart, analysis_start_ms: analysisStart, analysis_end_ms: analysisEnd, compilation_start_ms: compilationStart, compilation_end_ms: compilationEnd }, effective_analysis_options: options }));
    }, { config, identity, audioHash });
    clearTimeout(timeout);
    requireValue(report.timeout !== true, 'Browser execution exceeded the capture deadline');
    requireValue(errors.length === 0 && blocked.length === 0, 'Browser errors or external requests occurred during capture');
    requireValue(result.show?.validation?.valid === true, 'Actual generated show did not pass application validation');
    const frames = Buffer.from(result.frames, 'base64'), header = Buffer.from(result.header, 'base64');
    requireValue(header.length >= 32 && header.toString('ascii', 0, 4) === 'PSEQ' && header.readUInt16LE(4) === header.length, 'Compiler emitted invalid FSEQ header');
    requireValue(frames.length === result.show.frameCount * result.show.channelCount && header.readUInt32LE(10) === result.show.channelCount && header.readUInt32LE(14) === result.show.frameCount && header[18] === result.show.stepMs, 'FSEQ payload dimensions differ from application metadata');
    requireValue(hashBytes(frames) === result.compiled.sha256, 'Actual frame bytes differ from compiled payload digest');
    requireValue(await hashFile(wav) === audioHash && canonical(await inventory(webRoot)) === canonical(lock), 'Locked audio or application source changed during capture');
    const fseq = Buffer.concat([header, frames]);
    const fseqProperties = { version_major: header[7], version_minor: header[6], data_offset: header.length, channel_count: result.show.channelCount, frame_count: result.show.frameCount, step_ms: result.show.stepMs, sequence_bytes: fseq.length, frame_bytes: frames.length, frames_sha256: hashBytes(frames), fseq_sha256: hashBytes(fseq) };
    const projection = outputCategories(result.music, result.show, fseqProperties), artifacts = {}, goldens = {};
    function save(name, bytes) { fs.writeFileSync(path.join(out, name), bytes, { flag: 'wx', mode: 0o600 }); artifacts[name] = { bytes: bytes.length, sha256: hashBytes(bytes) }; }
    for (const [name, value] of Object.entries({ 'analysis.json': result.music, 'show.json': result.show, 'compiled.json': result.compiled, 'progress.json': result.progress })) save(name, Buffer.from(canonical(value) + '\n'));
    if (Object.hasOwn(result.show, 'perceptualValidation')) save('perceptual-validation.json', Buffer.from(canonical(result.show.perceptualValidation) + '\n'));
    else report.missing_optional_artifacts = { 'perceptual-validation.json': 'not emitted by the actual configured application' };
    save('show.frames.bin', frames); save('show.header.bin', header); save('lightshow.fseq', fseq);
    for (const [name, value] of Object.entries(projection.categories)) { const file = name + '.json'; save(file, Buffer.from(canonical(value) + '\n')); goldens[name + '_sha256'] = artifacts[file].sha256; }
    Object.assign(report, { status: 'captured', timing: result.timing, effective_analysis_options: result.effective_analysis_options, effective_show_settings: result.show.settings, engine: result.music.engine, resource_observations: result.music.engine?.resourceDiagnostics || { status: 'unavailable', reason: 'application-did-not-emit-resource-diagnostics' }, artifacts, observed_output_hashes: goldens, missing_output_categories: projection.missing, served_source_hashes: Object.fromEntries([...served].sort().map(name => [name, lock.files[name]])), progress_records: result.progress.length });
    success = true;
  } catch (error) { report.error = String(error.message || error).slice(0, 1000); }
  finally {
    clearTimeout(timeout);
    report.browser_errors = errors;
    report.external_network_requests_blocked = blocked.length;
    if (report.runtime) report.runtime.external_network_requests_blocked = blocked.length;
    try { await browser?.close(); } catch { report.cleanup_error = 'browser-close-failed'; success = false; }
    if (server?.listening) { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
  }
  if (!success) report.status = 'failed';
  report.completed_at = new Date().toISOString();
  writeJson(path.join(out, 'capture.json'), report);
  emit(report.status, { output_directory: out, production_ready: false, error: report.error || null });
  return success ? 0 : 1;
}
async function main(argv = process.argv.slice(2)) {
  const options = parseArgs(argv);
  if (options.command === 'inventory') {
    const lock = await inventory(path.resolve(options['app-root'], 'web'));
    writeJson(options.output, lock);
    process.stdout.write(JSON.stringify({ web_manifest_sha256: validateLock(lock), files: Object.keys(lock.files).length }) + '\n');
    return 0;
  }
  return capture(options);
}
module.exports = { canonical, hashBytes, inventory, validateLock, bootstrapScripts, validateIdentity, validateConfiguration, wavInfo, parseRange, createServer, outputCategories, parseArgs, capture, main };
if (require.main === module) main().then(code => { process.exitCode = code; }).catch(error => { process.stderr.write(String(error.message || error) + '\n'); process.exitCode = 1; });
