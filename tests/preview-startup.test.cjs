'use strict';
// Constructor/ownership tests exercise the real class without claiming GPU or
// Android coverage. Full browser and Android gates still require visible frames.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function harness({initError, loadError, rejection, saved = {}} = {}) {
  const events = [], warnings = [], storage = new Map(Object.entries(saved));
  const controls = ['studio', 'night'].map(stage => ({
    dataset: {stage}, attributes: {}, selected: false,
    classList: {toggle(_name, value) { controls.find(c => c.dataset.stage === stage).selected = value; }},
    setAttribute(name, value) { this.attributes[name] = value; },
  }));
  const canvas = {dataset: {}, dispatchEvent() {}, removeEventListener() {}};
  const status = {dataset: {}};
  let resolveLoad;
  const loading = new Promise(resolve => { resolveLoad = resolve; });
  const context = {
    window: {}, navigator: {deviceMemory: 8}, THREE: {Vector3: class {}},
    matchMedia: () => ({matches: false}), performance: {now: () => 100},
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options?.detail; } },
    localStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value)},
    document: {hidden: false, getElementById: () => status, querySelectorAll: () => controls, removeEventListener() {}},
    requestAnimationFrame: () => { throw Error('Uninitialized preview must not schedule a GPU frame'); },
    cancelAnimationFrame() {}, console: {warn: (...message) => warnings.push(message)},
  };
  const source = fs.readFileSync(path.join(__dirname, '../web/preview/src/vehicle-preview.js'), 'utf8')
    .replace(/^import .*;\s*$/gm, '');
  vm.runInNewContext(source, context, {filename: 'vehicle-preview.js'});
  const Preview = context.window.VehiclePreview;
  Preview.prototype.init = function () {
    events.push({type: 'init', stage: this.stage, view: this.view, quality: this.quality,
      effectiveQuality: this.effectiveQuality, paused: this._paused,
      frame: this.last[0]?.frame, time: this.last[1]});
    if (initError) throw initError;
  };
  Preview.prototype.load = function () {
    events.push({type: 'load'});
    if (loadError) throw loadError;
    return rejection ? Promise.reject(rejection) : loading;
  };
  return {Preview, canvas, status, events, warnings, storage, controls,
    resolve: value => resolveLoad(value)};
}

test('deferred construction allocates neither GPU resources nor a model request', async () => {
  const h = harness(), p = new h.Preview(h.canvas, null, {deferLoad: true});
  const ready = p.ready;
  assert.deepEqual(h.events, []);
  assert.equal(p.renderer, undefined);
  assert.equal(p.loaded, false);
  assert.equal(p.renderCount, 0);
  p.setLoadDeferred(true);
  assert.equal(p.ready, ready);
  assert.deepEqual(h.events, []);
  p.dispose();
  assert.equal(await ready, false);
});

test('release initializes once and retains the latest frame, pause, view, and full quality', async () => {
  const h = harness({saved: {'lightforge-stage': 'night'}});
  const p = new h.Preview(h.canvas, null, {deferLoad: true}), ready = p.ready;
  p.setView('rear');
  p.setQuality('high');
  p.setPaused(true);
  p.render({frame: 6}, 0.12);
  p.render({frame: 27}, 0.54);
  assert.deepEqual(h.events, []);
  p.setLoadDeferred(false);
  p.setLoadDeferred(false);
  assert.equal(p.startLoad(), ready);
  assert.deepEqual(h.events, [
    {type: 'init', stage: 'night', view: 'rear', quality: 'high', effectiveQuality: 'high', paused: true, frame: 27, time: 0.54},
    {type: 'load'},
  ]);
  let settled = false;
  ready.then(() => { settled = true; });
  await Promise.resolve();
  assert.equal(settled, false, 'Construction is not evidence of model readiness');
  h.resolve(true);
  assert.equal(await ready, true);
  p.setLoadDeferred(false);
  assert.equal(h.events.length, 2);
});

test('ordinary startup remains immediate and preserves the saved stage', async () => {
  const h = harness({saved: {'lightforge-stage': 'night'}}), p = new h.Preview(h.canvas);
  assert.deepEqual(h.events.map(e => e.type), ['init', 'load']);
  assert.equal(h.events[0].stage, 'night');
  h.resolve(true);
  assert.equal(await p.ready, true);
});

for (const [name, options] of [
  ['graphics initialization throws', {initError: Error('context initialization failed')}],
  ['model load throws synchronously', {loadError: Error('model request failed')}],
  ['model load rejects asynchronously', {rejection: Error('model decode failed')}],
]) {
  test(`${name}: readiness fails without creating an automatic retry loop`, async () => {
    const h = harness(options), p = new h.Preview(h.canvas, null, {deferLoad: true});
    const ready = p.ready;
    p.setLoadDeferred(false);
    assert.equal(await ready, false);
    assert.equal(h.canvas.dataset.rendererState, 'error');
    assert.equal(h.warnings.length, 1);
    const count = h.events.length;
    p.setLoadDeferred(false);
    assert.equal(p.ready, ready);
    assert.equal(h.events.length, count);
    if (options.initError) assert.equal(count, 1, 'A failed context cannot start model loading');
  });
}

test('disposing a deferred preview permanently prevents resource initialization', async () => {
  const h = harness(), p = new h.Preview(h.canvas, null, {deferLoad: true});
  const ready = p.ready;
  p.dispose();
  p.dispose();
  p.setLoadDeferred(false);
  p.startLoad();
  assert.equal(await ready, false);
  assert.deepEqual(h.events, []);
});

test('a late model completion cannot change the disposed preview readiness result', async () => {
  const h = harness(), p = new h.Preview(h.canvas, null, {deferLoad: true});
  const ready = p.ready;
  p.setLoadDeferred(false);
  p.dispose();
  assert.equal(await ready, false);
  h.resolve(true);
  await Promise.resolve();
  p.setLoadDeferred(false);
  assert.equal(await p.ready, false);
  assert.equal(p._readyResolve, null);
  assert.equal(h.events.length, 2);
});

test('stage selection is persisted and reflected in controls before graphics start', async () => {
  const h = harness(), p = new h.Preview(h.canvas, null, {deferLoad: true});
  p.setStage('night');
  assert.equal(h.storage.get('lightforge-stage'), 'night');
  assert.equal(h.controls[1].selected, true);
  assert.equal(h.controls[1].attributes['aria-pressed'], 'true');
  assert.deepEqual(h.events, []);
  p.setLoadDeferred(false);
  assert.equal(h.events[0].stage, 'night');
  h.resolve(true);
  assert.equal(await p.ready, true);
});
