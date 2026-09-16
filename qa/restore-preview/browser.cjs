'use strict';
// Real browser workers and WebGL; the Android bridge and visual-commit callback
// are simulated. This is not Android lifecycle, audio quality, or release proof.
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const crypto = require('node:crypto'), assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
let RELEASE = null, inventoryPath = null;
const output = path.resolve(process.env.LIGHTFORGE_RESTORE_QA_OUTPUT || __dirname);
const EVIDENCE_SESSION_SCHEMA = 'lightforge.evidence-session.v1';
const EVIDENCE_SESSION_PATTERN = /^[0-9a-f]{32,128}$/;
function sourceNames() {
  const inventory = JSON.parse(fs.readFileSync(path.join(root, inventoryPath), 'utf8'));
  assert.equal(inventory?.schema, 'lightforge.browser-source-inventory.v1', 'Restore-preview source inventory schema is invalid');
  assert.ok(Array.isArray(inventory?.common) && Array.isArray(inventory?.restore_preview), 'Restore-preview source inventory is invalid');
  const names = [...inventory.common, ...inventory.restore_preview];
  assert.ok(names.length && names.every(name => typeof name === 'string' && name && !path.isAbsolute(name) && !name.split('/').includes('..')), 'Restore-preview source inventory contains an invalid path');
  assert.equal(new Set(names).size, names.length, 'Restore-preview source inventory contains duplicates');
  assert.ok(names.includes('version.json') && names.includes(inventoryPath), 'Restore-preview source inventory must bind its release metadata and inventory');
  return names;
}
function writeJsonAtomic(file, value) {
  const temporary = `${file}.${process.pid}.${crypto.randomBytes(8).toString('hex')}.tmp`;
  try { fs.writeFileSync(temporary, JSON.stringify(value, null, 2) + '\n'); fs.renameSync(temporary, file); }
  finally { if (fs.existsSync(temporary)) fs.unlinkSync(temporary); }
}
function errorText(error) { return error && error.stack ? error.stack : String(error); }
fs.mkdirSync(output, {recursive: true});
const evidenceSession = process.env.LIGHTFORGE_EVIDENCE_SESSION;
const sessionError = evidenceSession !== undefined && !EVIDENCE_SESSION_PATTERN.test(evidenceSession) ?
  new Error('Invalid LIGHTFORGE_EVIDENCE_SESSION') : null;
const receipt = {release: RELEASE, passed: false, scope: 'Desktop Chromium with actual workers, compiled frames, GLB, and WebGL. Synthetic music analysis and simulated native bridge; not Android, musical-quality, speedup, or release certification.', checks: [], errors: [], source_hashes: {}};
if (!sessionError && evidenceSession !== undefined) {
  receipt.evidenceSessionSchema = EVIDENCE_SESSION_SCHEMA;
  receipt.evidenceSession = evidenceSession;
}
const receiptPath = path.join(output, 'restore-preview-verification.json');
const write = () => writeJsonAtomic(receiptPath, receipt);
// Publish an atomic failed receipt before version/source reads, Playwright import, or browser work.
write();
(async () => {
  let browser, server, releaseRead, saved, chromium;
  const readGate = new Promise(resolve => { releaseRead = resolve; });
  const errors = [];
  try {
    if (sessionError) throw sessionError;
    const version = JSON.parse(fs.readFileSync(path.join(root, 'version.json'), 'utf8'));
    assert.match(version?.name, /^[0-9]+\.[0-9]+\.[0-9]+$/, 'Restore-preview release version is invalid');
    RELEASE = version.name;
    inventoryPath = `qa/release-${RELEASE}/browser-source-inventory.json`;
    receipt.release = RELEASE;
    receipt.source_hashes = Object.fromEntries(sourceNames().map(name => [name, crypto.createHash('sha256').update(fs.readFileSync(path.join(root, name))).digest('hex')]));
    ({chromium} = require('playwright'));
    server = http.createServer((req, res) => {
      const pathname = decodeURIComponent(new URL(req.url, 'http://local').pathname);
      if (pathname === '/completed-project.json') {
        readGate.then(() => { if (!res.destroyed) { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(saved)); } });
        return;
      }
      const file = path.resolve(root, 'web', '.' + (pathname === '/' ? '/index.html' : pathname));
      if (!file.startsWith(path.join(root, 'web') + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) { res.writeHead(404).end(); return; }
      res.setHeader('Content-Type', ({'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.wav':'audio/wav','.glb':'model/gltf-binary','.wasm':'application/wasm'})[path.extname(file)] || 'application/octet-stream');
      res.setHeader('Cross-Origin-Opener-Policy', 'same-origin'); res.setHeader('Cross-Origin-Embedder-Policy', 'require-corp');
      res.setHeader('Content-Length', fs.statSync(file).size);
      fs.createReadStream(file).pipe(res);
    });
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
    const origin = 'http://127.0.0.1:' + server.address().port;
    browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_EXECUTABLE_PATH ? {executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH} : {}), args: ['--no-sandbox', '--enable-unsafe-swiftshader']});
    const setup = await browser.newPage({viewport: {width: 393, height: 852}});
    setup.on('pageerror', error => errors.push(error.message));
    await setup.addInitScript(release => { window.Android = {pickAudio() {}, getBootstrap: () => JSON.stringify({projects: [], version: release})}; }, RELEASE);
    await setup.goto(origin);
    await setup.waitForFunction(() => !!window.LightForgeApp && !!window.ShowCompiler);
    saved = await setup.evaluate(async () => {
      const music = {duration: 2, bpm: 120, beats: [0, .5, 1, 1.5], waveform: [.4], beatConfidence: .9, sections: [{start: 0, end: 2, energy: .7}], analysisVersion: 6};
      const settings = structuredClone(LightForgeApp.state.settings);
      const result = await ShowCompiler.generate(music, settings);
      return {version: 1, projectId: 'restore-preview-fixture', settings, music, compiled: result.compiled, needAnalysis: false};
    });
    await setup.close();
    const page = await browser.newPage({viewport: {width: 393, height: 852}});
    page.on('pageerror', error => errors.push(error.message));
    let modelRequests = 0;
    page.on('request', request => { if (request.url().endsWith('/preview/models/highland.glb')) modelRequests++; });
    const nativeBridge = ({deferCompletion = false, release} = {}) => {
      const project = {id: 'restore-preview-fixture', name: 'Restore preview fixture', duration: 2, projectUrl: '/completed-project.json', audioUrl: '/demo/glass-castle.wav'};
      const job = {id: 'completed-preview-fixture', projectId: project.id, state: 'completed', progress: 1};
      const calls = []; let lease, sequence = 0, terminal = false;
      const matches = (id, nonce) => lease?.id === id && lease?.nonce === nonce;
      window.restoreQA = {calls, job, contexts: 0, armed: !deferCompletion};
      const getContext = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (type, ...args) { if (/^webgl/.test(type)) restoreQA.contexts++; return getContext.call(this, type, ...args); };
      window.Android = {
        pickAudio() {}, getBootstrap: () => JSON.stringify(restoreQA.armed ? {projects: [project], lastProjectId: project.id, backgroundJob: job, version: release} : {projects: [], version: release}),
        getAnalysisStatus: () => JSON.stringify(restoreQA.armed ? job : null), saveProject: () => true,
        startAnalysis() { throw Error('A completed restore must not restart analysis'); },
        beginCompletedRestore(id, nonce) { if (lease) return false; lease = {id, nonce}; calls.push('begin'); return id === job.id; },
        completedRestorePulse(id, nonce, phase, next) { if (!matches(id, nonce) || next <= sequence) return false; sequence = next; calls.push(phase); return true; },
        requestCompletedRestoreVisualCommit: matches,
        completedRestoreVisualCommitted(id, nonce) { return matches(id, nonce) && LightForgeApp.vehiclePreview.renderCount > 0; },
        completedRestoreTerminal(id, nonce, next) {
          const phases = ['worker-started', 'worker-verified', 'show-adopted', 'preview-starting', 'preview-first-render', 'preview-visual-commit'];
          const positions = phases.map(phase => calls.indexOf(phase));
          if (!matches(id, nonce) || next <= sequence || positions.some((value, index) => value < 0 || index > 0 && value <= positions[index - 1]) || localStorage.getItem('lightforge-background-ack')) return false;
          terminal = true; calls.push('terminal'); return true;
        },
        completedRestoreAckCommitted(id, nonce) { if (!terminal || !matches(id, nonce) || localStorage.getItem('lightforge-background-ack') !== id) return false; calls.push('ack'); return true; },
        completedRestoreFailed(_id, _nonce, reason) { calls.push('failed:' + reason); return true; },
      };
    };
    await page.addInitScript(nativeBridge, {release: RELEASE});
    await page.goto(origin, {waitUntil: 'domcontentloaded'});
    await page.waitForFunction(() => window.LightForgeApp?.state.completedRestore?.phase === 'project-read-fallback');
    const deferred = await page.evaluate(() => ({contexts: restoreQA.contexts, graphics: !!LightForgeApp.vehiclePreview.renderer, started: LightForgeApp.vehiclePreview._loadStarted, deferred: LightForgeApp.vehiclePreview._loadDeferred, frames: LightForgeApp.vehiclePreview.renderCount}));
    assert.deepEqual(deferred, {contexts: 0, graphics: false, started: false, deferred: true, frames: 0});
    assert.equal(modelRequests, 0);
    receipt.checks.push('Cold completed restore performs no WebGL context allocation or GLB request while waiting for its saved payload.');
    releaseRead();
    await page.waitForFunction(() => localStorage.getItem('lightforge-background-ack') === restoreQA.job.id && !LightForgeApp.state.backgroundApplying && LightForgeApp.vehiclePreview.renderCount > 0, {}, {timeout: 45000});
    const complete = await page.evaluate(() => ({calls: restoreQA.calls, contexts: restoreQA.contexts, sha256: LightForgeApp.state.compiled.sha256, loaded: LightForgeApp.vehiclePreview.loaded, frames: LightForgeApp.vehiclePreview.renderCount, pending: LightForgeApp.state.backgroundSyncPending, quality: LightForgeApp.vehiclePreview.getPerformance()}));
    assert.equal(complete.sha256, saved.compiled.sha256);
    assert.equal(complete.loaded, true); assert.equal(complete.pending, false);
    assert.equal(complete.contexts, 1); assert.equal(modelRequests, 1);
    assert.equal(complete.calls.filter(call => call === 'begin').length, 1);
    assert.equal(complete.calls.at(-1), 'ack');
    assert.ok(complete.frames > 0);
    assert.equal(errors.length, 0, JSON.stringify(errors));
    receipt.checks.push('Verified worker result, show adoption, actual WebGL rendering, simulated visual commit, terminal proof, and browser ACK complete in order with one model load.');
    receipt.checks.push('Restoration preserves the exact compiled frame SHA-256; the test does not rerun audio analysis or substitute a cheaper show.');
    receipt.observation = complete;
    await page.screenshot({path: path.join(output, 'restore-preview.png'), fullPage: true, animations: 'disabled'});
    await page.close();
    const foreground = await browser.newPage({viewport: {width: 393, height: 852}});
    foreground.on('pageerror', error => errors.push(error.message));
    let foregroundReads = 0;
    foreground.on('request', request => { if (request.url().endsWith('/completed-project.json')) foregroundReads++; });
    await foreground.addInitScript(nativeBridge, {deferCompletion: true, release: RELEASE});
    await foreground.goto(origin, {waitUntil: 'domcontentloaded'});
    await foreground.waitForFunction(() => window.LightForgeApp?.vehiclePreview.loaded);
    await foreground.evaluate(() => {
      pausePreview(); restoreQA.armed = true;
      for (let n = 0; n < 3; n++) onNativeEvent('analysisJob', JSON.stringify(restoreQA.job));
    });
    const paused = await foreground.evaluate(() => ({calls: restoreQA.calls, pending: LightForgeApp.state.backgroundSyncPending, applying: !!LightForgeApp.state.backgroundApplying, busy: LightForgeApp.state.busy, paused: LightForgeApp.vehiclePreview._paused, ack: localStorage.getItem('lightforge-background-ack')}));
    assert.deepEqual(paused, {calls: [], pending: true, applying: false, busy: false, paused: true, ack: null});
    assert.equal(foregroundReads, 0, 'Paused completion delivery must not read a project or open a visual-proof lease');
    await foreground.evaluate(() => resumePreview());
    await foreground.waitForFunction(() => localStorage.getItem('lightforge-background-ack') === restoreQA.job.id && !LightForgeApp.state.backgroundApplying && LightForgeApp.vehiclePreview.renderCount > 0, {}, {timeout: 45000});
    const resumed = await foreground.evaluate(() => ({calls: restoreQA.calls, sha256: LightForgeApp.state.compiled.sha256, loaded: LightForgeApp.vehiclePreview.loaded, frames: LightForgeApp.vehiclePreview.renderCount, pending: LightForgeApp.state.backgroundSyncPending, paused: LightForgeApp.vehiclePreview._paused}));
    assert.equal(resumed.sha256, saved.compiled.sha256); assert.equal(foregroundReads, 1);
    assert.equal(resumed.calls.filter(call => call === 'begin').length, 1);
    assert.equal(resumed.calls.filter(call => call === 'ack').length, 1);
    assert.equal(resumed.pending, false); assert.equal(resumed.paused, false);
    assert.equal(resumed.loaded, true); assert.ok(resumed.frames > 0);
    assert.equal(errors.length, 0, JSON.stringify(errors));
    receipt.checks.push('Native pause followed by repeated completed-job deliveries performs no project read, worker restore, or native lease/ACK until resume; foreground restoration then renders the exact saved frames and acknowledges once.');
    receipt.foregroundObservation = resumed;
    await foreground.screenshot({path: path.join(output, 'foreground-resume.png'), fullPage: true, animations: 'disabled'});
    for (const [name, expected] of Object.entries(receipt.source_hashes)) assert.equal(crypto.createHash('sha256').update(fs.readFileSync(path.join(root, name))).digest('hex'), expected, 'Source changed during restore verification: ' + name);
    receipt.passed = true;
  } catch (error) {
    receipt.errors.push(errorText(error)); console.error(errorText(error)); process.exitCode = 1;
  } finally {
    releaseRead?.(); await browser?.close();
    if (server?.listening) await new Promise(resolve => server.close(resolve));
    receipt.completedAt = new Date().toISOString(); write(); console.log(JSON.stringify(receipt));
  }
})();
