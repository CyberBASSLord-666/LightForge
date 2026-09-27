'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {JSDOM} = require('jsdom');
const root = path.resolve(__dirname, '..');

function scheduler() {
  let serial = 0;
  const pending = new Map();
  return {
    pending,
    request(callback) { const id = ++serial; pending.set(id, callback); return id; },
    cancel(id) { pending.delete(id); },
    flush(time = 100) {
      for (const [id, callback] of [...pending]) {
        if (!pending.delete(id)) continue;
        callback(time);
      }
    },
  };
}

function studio() {
  const dom = new JSDOM(fs.readFileSync(path.join(root, 'web/index.html'), 'utf8'), {
    url: 'https://appassets.androidplatform.net/', runScripts: 'outside-only',
  });
  const w = dom.window, d = w.document, raf = scheduler();
  let hidden = false;
  Object.defineProperty(d, 'hidden', {get: () => hidden, configurable: true});
  Object.defineProperty(d, 'visibilityState', {get: () => hidden ? 'hidden' : 'visible', configurable: true});
  w.requestAnimationFrame = callback => raf.request(callback);
  w.cancelAnimationFrame = id => raf.cancel(id);
  w.scrollTo = () => {};
  w.matchMedia = () => ({matches: true, addEventListener() {}});
  w.HTMLCanvasElement.prototype.getContext = () => new Proxy({}, {get: () => () => {}});
  w.HTMLMediaElement.prototype.pause = function () {};
  w.HTMLMediaElement.prototype.load = function () {};
  w.VehiclePreview = class {
    constructor() { this.paused = false; this.draws = 0; this.pauseChanges = []; }
    setPaused(value) { this.paused = !!value; this.pauseChanges.push(this.paused); }
    render() { if (!this.paused) this.draws++; }
    setStateSource(source) { this.stateSource=source; }
    setCamera() {} setStage() {} setQuality() {} resize() {}
  };
  w.LightForgeVersion = require('../web/version.js');
  w.ShowEngine = require('../web/engine/show-engine.js');
  w.VehicleProfile = require('../web/engine/vehicle-profile.js');
  w.MusicCues = require('../web/engine/music-cues.js');
  w.Android = {
    pickAudio() {}, getBootstrap: () => JSON.stringify({projects: [], version: '2.2.4'}),
    saveProject: () => true,
  };
  w.eval(fs.readFileSync(path.join(root, 'web/app.js'), 'utf8'));
  const app = w.LightForgeApp;
  app.state.project = {id: 'lifecycle-fixture', name: 'Lifecycle', duration: 2};
  return {w, d, raf, app, preview: app.vehiclePreview,
    visibility(value) { hidden = value; d.dispatchEvent(new w.Event('visibilitychange')); },
    close() { w.close(); },
  };
}

test('hiding before the first studio frame cancels it and resumes exactly one RAF chain', () => {
  const t = studio();
  try {
    assert.equal(t.raf.pending.size, 1);
    const staleFirstFrame = [...t.raf.pending.values()][0];
    t.visibility(true);
    assert.equal(t.raf.pending.size, 0, 'The initial frame handle must be owned and cancellable');
    const draws = t.preview.draws;
    staleFirstFrame(100);
    assert.equal(t.raf.pending.size, 0, 'An already-dispatched hidden callback must not restart the loop');
    assert.equal(t.preview.draws, draws);
    t.visibility(false);
    t.visibility(false);
    assert.equal(t.raf.pending.size, 1, 'Repeated visible events must share one studio loop');
    t.raf.flush(200);
    assert.equal(t.raf.pending.size, 1);
    t.visibility(true);
    assert.equal(t.raf.pending.size, 0, 'A second hide must leave no orphaned RAF chain');
  } finally { t.close(); }
});

test('native preview pause stays effective while the document is visible until explicit resume', () => {
  const t = studio();
  try {
    assert.equal(typeof t.w.resumePreview, 'function');
    t.raf.flush(100);
    const staleFrame = [...t.raf.pending.values()][0];
    t.app.state.soloPreview = {duration: 2, name: 'Inspection'};
    t.w.pausePreview();
    t.w.pausePreview();
    assert.equal(t.d.hidden, false, 'This exercises the Android pause before browser visibility changes');
    assert.equal(t.app.state.soloPreview, null);
    assert.equal(t.preview.paused, true);
    assert.equal(t.raf.pending.size, 0);
    const draws = t.preview.draws;
    t.d.getElementById('audio').onpause();
    t.w.dispatchEvent(new t.w.Event('resize'));
    t.visibility(false);
    staleFrame(200);
    assert.equal(t.preview.draws, draws, 'Media, resize and visibility events must not render during native pause');
    assert.equal(t.raf.pending.size, 0);
    assert.equal(t.preview.paused, true);
    t.w.resumePreview();
    t.w.resumePreview();
    assert.equal(t.preview.paused, false);
    assert.equal(t.raf.pending.size, 1);
    t.raf.flush(300);
    assert.equal(t.raf.pending.size, 1);
    assert.ok(t.preview.draws > draws, 'Visible explicit resume must restore rendering');
  } finally { t.close(); }
});

test('page lifecycle suspension is independent of native and document visibility state', () => {
  const t = studio();
  try {
    t.w.dispatchEvent(new t.w.Event('pagehide'));
    t.w.dispatchEvent(new t.w.Event('pagehide'));
    assert.equal(t.raf.pending.size, 0);
    assert.equal(t.preview.paused, true);
    t.visibility(false);
    t.w.resumePreview();
    assert.equal(t.raf.pending.size, 0, 'Native resume cannot clear a pagehide suspension');
    t.w.dispatchEvent(new t.w.Event('pageshow'));
    t.w.dispatchEvent(new t.w.Event('pageshow'));
    assert.equal(t.raf.pending.size, 1);
    t.w.pausePreview();
    t.w.dispatchEvent(new t.w.Event('pagehide'));
    t.w.dispatchEvent(new t.w.Event('pageshow'));
    assert.equal(t.raf.pending.size, 0, 'pageshow cannot clear an explicit native pause');
    t.visibility(true);
    t.w.resumePreview();
    assert.equal(t.raf.pending.size, 0, 'Native resume cannot render a hidden document');
    t.visibility(false);
    assert.equal(t.raf.pending.size, 1);
    assert.equal(t.preview.paused, false);
  } finally { t.close(); }
});

// Evaluate the actual renderer class and its lifecycle methods. GPU construction
// is excluded; the renderer/composer submission boundaries remain observable.
function renderer() {
  const raf = scheduler();
  let hidden = false, gpuDraws = 0, gpuResizes = 0;
  const document = {get hidden() { return hidden; }};
  const context = {window: {}, document, performance: {now: () => 100},
    requestAnimationFrame: callback => raf.request(callback), cancelAnimationFrame: id => raf.cancel(id)};
  const source = fs.readFileSync(path.join(root, 'web/preview/src/vehicle-preview.js'), 'utf8')
    .replace(/^import .*;\s*$/gm, '');
  vm.runInNewContext(source, context, {filename: 'vehicle-preview.js'});
  const preview = Object.create(context.window.VehiclePreview.prototype);
  Object.assign(preview, {
    _raf: 0, _paused: false, _disposed: false, _intersecting: true, _hasSize: true,
    loaded: true, environment: {}, lost: false, _lastRenderAt: 0, _warmupFrames: 5, renderCount: 0,
    width: 320, height: 200, view: 'custom', last: [null, 0],
    canvas: {dataset: {}, getBoundingClientRect: () => ({width: 640, height: 400})},
    renderer: {shadowMap: {}, info: {reset() {}}, setSize() { gpuResizes++; }},
    composer: {render() { gpuDraws++; }, setSize() { gpuResizes++; }},
    camera: {aspect: 1.6, updateProjectionMatrix() {}},
    controls: {enabled: true, update: () => false},
    reportPerformance() {}, recordPerformance() {},
  });
  return {preview, raf, document, setHidden(value) { hidden = value; },
    get gpuDraws() { return gpuDraws; }, get gpuResizes() { return gpuResizes; }};
}

test('renderer explicit pause cancels pending submission and blocks draws and resize allocations', () => {
  const t = renderer(), p = t.preview;
  assert.equal(typeof p.setPaused, 'function');
  p.requestDraw();
  assert.equal(t.raf.pending.size, 1);
  const staleDraw = [...t.raf.pending.values()][0];
  p.setPaused(true);
  p.setPaused(true);
  assert.equal(t.document.hidden, false);
  assert.equal(p.isVisible(), false);
  assert.equal(p.controls.enabled, false, 'Native pause also blocks orbit input');
  assert.equal(t.raf.pending.size, 0);
  p.render({frame: 10, time: 0.2}, 0.2);
  p.resize();
  p.requestDraw();
  staleDraw(200);
  assert.equal(t.gpuDraws, 0);
  assert.equal(t.gpuResizes, 0);
  assert.equal(t.raf.pending.size, 0);
  p.setPaused(false);
  p.setPaused(false);
  assert.equal(p.isVisible(), true);
  assert.equal(p.controls.enabled, true, 'Resume restores orbit input after deferred initialization');
  assert.equal(t.raf.pending.size, 1);
  assert.ok(t.gpuResizes > 0, 'Resume must apply the size deferred while paused');
  t.raf.flush(300);
  assert.equal(t.gpuDraws, 1);
  assert.equal(p.renderCount, 1);
  assert.equal(t.raf.pending.size, 0, 'A stationary renderer must not create a continuous loop');
});

test('renderer resume never submits or reallocates while the document remains hidden', () => {
  const t = renderer(), p = t.preview;
  p.setPaused(true);
  t.setHidden(true);
  p.setPaused(false);
  p.resize();
  p.requestDraw();
  p.draw(100);
  assert.equal(t.raf.pending.size, 0);
  assert.equal(t.gpuDraws, 0);
  assert.equal(t.gpuResizes, 0);
  t.setHidden(false);
  p.resize();
  p.requestDraw();
  t.raf.flush(200);
  assert.equal(t.gpuDraws, 1);
});

test('renderer defers lighting generation and frame submission until the model is loaded and visible', () => {
  const t = renderer(), p = t.preview, events = [];
  p.loaded = false;
  p.environment = null;
  p.createEnvironment = () => { events.push('lighting'); p.environment = {}; };
  const render = p.composer.render;
  p.composer.render = () => { events.push('frame'); render(); };
  p.render({frame: 24, time: 0.48}, 0.48);
  p.requestDraw();
  p.draw(100);
  assert.equal(t.raf.pending.size, 0, 'An unloaded model must not schedule empty GPU frames');
  assert.deepEqual(events, []);
  p.loaded = true;
  t.setHidden(true);
  p.requestDraw();
  p.draw(200);
  assert.deepEqual(events, [], 'A completed model load must not generate lighting while hidden');
  t.setHidden(false);
  p.setPaused(true);
  p.draw(250);
  assert.deepEqual(events, [], 'Native pause must also defer lighting generation');
  p.setPaused(false);
  t.raf.flush(300);
  assert.deepEqual(events, ['lighting', 'frame']);
  assert.equal(p.last[0].frame, 24, 'The delayed first draw must retain the latest show frame');
  assert.equal(p.last[1], 0.48);
  p.redraw();
  t.raf.flush(400);
  assert.deepEqual(events, ['lighting', 'frame', 'frame'], 'Lighting is generated once per graphics context');
});

test('renderer defers GLTF work until completed restore adopts a verified show',async()=>{
 const t=renderer(),p=t.preview;let resolveReady,loads=0;
 p.loaded=false;p._loadDeferred=true;p._loadStarted=false;p.ready=new Promise(resolve=>{resolveReady=resolve;});p._readyResolve=resolveReady;
 p.init=()=>{};p.load=async()=>{loads++;return true;};
 assert.equal(typeof p.setLoadDeferred,'function');
 p.setLoadDeferred(true);assert.equal(loads,0,'A pending completed restore must not begin GLTF loading');
 p.setLoadDeferred(false);assert.equal(loads,1,'Verified show adoption releases exactly one GLTF load');
 await p.ready;
 p.setLoadDeferred(false);assert.equal(loads,1,'Release remains idempotent after the deferred model load starts');
});
test('offline preview bundle preserves the deferred-load contract used by the Studio',()=>{
 const source=fs.readFileSync(path.join(root,'web/preview/src/vehicle-preview.js'),'utf8');
 const bundle=fs.readFileSync(path.join(root,'web/preview/vehicle-preview.js'),'utf8');
 assert.match(source,/constructor\(canvas,onViewChange,\{deferLoad=false\}=\{\}\)/);
 assert.match(source,/setLoadDeferred\(deferred\)/);
 assert.match(bundle,/setLoadDeferred\(e\)/,'The Android-loaded offline bundle must not drop the source deferred-load contract');
});

test('GPU submission samples exported commands at current media time after delayed RAF, seeks and recovery', () => {
  const t=renderer(),p=t.preview,Engine=require('../web/engine/show-engine.js');
  const show={frames:new Uint8Array(100*200),frameCount:100,channels:200,stepMs:20,duration:2,sections:[]};
  show.frames[2*200+4]=255;show.frames[2*200+175]=96;
  const exported=Buffer.from(Engine.fseq(show)),offset=exported.readUInt16LE(4);
  let mediaTime=0,reads=0;
  const submissions=[],rigFrames=[];p.rig={update(data){rigFrames.push(data.frame);return false;}};
  p.setStateSource(()=>{reads++;return {data:Engine.stateAt(show,mediaTime),time:mediaTime,clock:'media-current-time'};});
  p.composer.render=()=>submissions.push({frame:p.last[0].frame,time:p.last[1],raw:Buffer.from(p.last[0].raw),lights:Array.from(p.last[0].lights),interior:p.last[0].interior});
  p.render(Engine.stateAt(show,0),0);
  p.render(Engine.stateAt(show,.02),.02);
  assert.deepEqual(rigFrames,[],'Queued updates must coalesce before geometry and material work');
  mediaTime=.052;t.raf.flush(100);
  assert.deepEqual(rigFrames,[2],'Only the latest authoritative frame updates the physical rig');
  assert.equal(submissions[0].frame,2,'Queued frame zero must not be presented after audio advances');
  assert.deepEqual(submissions[0].raw,exported.subarray(offset+400,offset+600));
  assert.equal(submissions[0].lights[4],1);assert.equal(submissions[0].interior[0][0],96);
  assert.equal(t.raf.pending.size,0,'Clock refresh must not create an extra continuous RAF chain');
  p.requestDraw();mediaTime=.012;t.raf.flush(90000);
  assert.equal(submissions[1].frame,0,'A seek immediately before GPU submission must replace queued data');
  assert.equal(submissions[1].lights[4],0);
  p.requestDraw();t.raf.flush(180000);
  assert.equal(submissions[2].time,.012,'Paused media time must not extrapolate from elapsed wall time');
  p.setPaused(true);mediaTime=.052;p.requestDraw();t.raf.flush(190000);
  assert.equal(reads,3,'Native pause must not sample or render');
  p.setPaused(false);t.raf.flush(200000);
  assert.equal(submissions[3].frame,2,'Resume must read the current media frame');
  p._restorePending=true;p.createEnvironment=()=>{mediaTime=.032;p.environment={};};
  p.composer.reset=()=>{};p.applyQuality=()=>{};p.setStatus=()=>{};
  p.requestDraw();t.raf.flush(210000);
  assert.equal(submissions[4].frame,1,'Clock is sampled after context recovery work');
  assert.equal(p._presented.time,.032);assert.equal(p._presented.frame,1);
  assert.equal(p._presented.clock,'media-current-time');
  p.setStateSource(null);p.render(Engine.stateAt(show,.012),.012);t.raf.flush(220000);
  assert.equal(p._presented.clock,'explicit-show-time');assert.equal(p._presented.time,.012);
});

test('environment light spill follows all physical main beams and reverse without activating absent fog', () => {
  const t=renderer(),p=t.preview,lights=new Float64Array(30);
  p.headlights=[{intensity:0},{intensity:0}];p.tailSpill=[{intensity:0},{intensity:0}];p.reverseSpill=[{intensity:0},{intensity:0}];
  lights[6]=.5;lights[9]=.25;lights[27]=1;
  p.render({lights},0);t.raf.flush();
  assert.deepEqual(p.headlights.map(x=>x.intensity),[4,2]);
  assert.deepEqual(p.reverseSpill.map(x=>x.intensity),[1.5,1.5]);
  assert.deepEqual(p.tailSpill.map(x=>x.intensity),[0,0],'Reverse light must not generate red tail spill');
  lights[25]=1;p.render({lights},0);t.raf.flush();
  assert.deepEqual(p.tailSpill.map(x=>x.intensity),[.35,0],'Left tail must not illuminate the right tail');
  lights[24]=1;p.render({lights},0);t.raf.flush();
  assert.deepEqual(p.tailSpill.map(x=>x.intensity),[.35,.35],'Brake command must illuminate both tails');
  lights.fill(0);lights[14]=lights[15]=1;
  p.render({lights},0);t.raf.flush();
  assert.deepEqual(p.headlights.map(x=>x.intensity),[0,0]);
  assert.deepEqual(p.reverseSpill.map(x=>x.intensity),[0,0]);
});


test('Studio preview state source follows the selected show and media seek without an independent timer', () => {
  const t=studio();
  try {
    const audio=t.d.getElementById('audio');
    const show={frames:new t.w.Uint8Array(100*200),frameCount:100,channels:200,stepMs:20,duration:2,sections:[]};
    show.frames[4*200+4]=255;t.app.state.show=show;
    audio.currentTime=.092;const current=t.preview.stateSource();
    assert.equal(current.clock,'media-current-time');assert.equal(current.time,.092);
    assert.equal(current.data.frame,4);assert.equal(current.data.raw[4],255);
    audio.currentTime=.012;const rewound=t.preview.stateSource();
    assert.equal(rewound.data.frame,0);assert.equal(rewound.data.raw[4],0);
    t.app.state.show=null;const cleared=t.preview.stateSource();
    assert.equal(cleared.data,null,'Removing the show must clear renderer outputs');
    assert.equal(cleared.time,.012);
  } finally { t.close(); }
});
