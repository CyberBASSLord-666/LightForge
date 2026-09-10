/* Diagnostic APK asset only. Imports the current, unmodified GAME engine. */
'use strict';
const childLane = self.location.pathname.endsWith('/__game_pool_child__.js');
const send = self.postMessage.bind(self), records = [], children = [], sessionEvents = [], executions = [];
let laneContext = null, probeGame = null, requestMode = '', cancellation = null;
const digest = async view => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', view)), n => n.toString(16).padStart(2, '0')).join('');
const canonical = value => JSON.stringify(value, (_, item) => item && typeof item === 'object' && !Array.isArray(item) ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item);
function check(condition, message) { if (!condition) throw Error(message); }
function emitRecord(record, execution) {
 if (childLane) send({type: 'pool-probe-trace', record, execution});
 else { records.push(record); executions.push(execution); }
}
function instrumentOrt() {
 const create = ort.InferenceSession.create.bind(ort.InferenceSession);
 ort.InferenceSession.create = async function(url, options) {
  const name = new URL(String(url), self.location.href).pathname.split('/').pop().replace('.onnx', '');
  sessionEvents.push({name, event: 'create'});
  const session = await create(url, options), run = session.run.bind(session);
  session.run = async function(feeds, ...rest) {
   if (name === 'encoder') laneContext = {pcm: await digest(new Uint8Array(feeds.waveform.data.buffer, feeds.waveform.data.byteOffset, feeds.waveform.data.byteLength)), counts: {}};
   check(laneContext, 'A graph ran without its encoder PCM identity.');
   const ordinal = laneContext.counts[name] || 0; laneContext.counts[name] = ordinal + 1;
   const startEpochMs = performance.timeOrigin + performance.now();
   const outputs = await run(feeds, ...rest), endEpochMs = performance.timeOrigin + performance.now(), tensors = {};
   for (const key of Object.keys(outputs).sort()) {
    const tensor = outputs[key], data = tensor.data;
    check(ArrayBuffer.isView(data), 'A graph returned nonnumeric data.');
    tensors[key] = {type: tensor.type, dims: Array.from(tensor.dims), bytes: data.byteLength, sha256: await digest(new Uint8Array(data.buffer, data.byteOffset, data.byteLength))};
   }
   emitRecord({pcm: laneContext.pcm, graph: name, ordinal, tensors}, {pcm: laneContext.pcm, graph: name, ordinal, lane: childLane ? 'child' : 'parent', startEpochMs, endEpochMs});
   return outputs;
  };
  return session;
 };
}
if (childLane) {
 // The child's location has the same /analysis/ directory. The original child
 // and every model/runtime byte still come from the candidate app itself.
 importScripts('game-worker.js');
 instrumentOrt();
} else {
 const RealWorker = self.Worker;
 self.Worker = class extends RealWorker {
  constructor(url, options) {
   const original = new URL(String(url), self.location.href);
   check(original.pathname.endsWith('/game-worker.js'), 'Unexpected descendant worker: ' + original.href);
   super(new URL('__game_pool_child__.js', self.location.href).href, options);
   const entry = {productionUrl: original.href, createdAt: performance.now(), inferRequests: 0, results: 0, terminated: false};
   children.push(entry); this.probeEntry = entry;
   this.addEventListener('message', event => {
    if (event.data?.type === 'pool-probe-trace') { records.push(event.data.record); executions.push(event.data.execution); }
    if (event.data?.type === 'result') entry.results++;
   });
  }
  postMessage(value, transfer) {
   if (value?.type === 'infer') {
    this.probeEntry.inferRequests++;
    if (requestMode === 'cancel' && !cancellation) {
     cancellation = {requested: true, requestWasPending: true, released: false};
     // Run at the next event-loop turn while model/session initialization is
     // active. This retires the pending child, then waits for the local lane.
     setTimeout(async () => {
      try { await probeGame.release(); cancellation.released = true; }
      catch (error) { cancellation.error = String(error); }
     }, 0);
    }
   }
   return super.postMessage(value, transfer);
  }
  terminate() { this.probeEntry.terminated = true; this.probeEntry.terminatedAt = performance.now(); return super.terminate(); }
 };
 importScripts('wav-reader.js', 'work-store.js', 'game.js', 'vendor/ort.wasm.min.js');
 ort.env.wasm.wasmPaths = new URL('vendor/', self.location.href).href;
 ort.env.wasm.numThreads = 1;
 ort.env.wasm.proxy = false;
 instrumentOrt();
 self.onmessage = async event => {
  const request = event.data; requestMode = request.mode;
  const started = performance.now(), writes = [], checkpoints = {}, reads = [];
  let store, storeKey;
  const result = {mode: requestMode, passed: false, parallelism: request.parallelism, numThreads: ort.env.wasm.numThreads,
   sampleRate: 44100, samples: 24 * 44100, records, children, checkpoints, writes, reads, sessionEvents, executions};
  try {
   check(['serial', 'parallel', 'cancel', 'restart'].includes(requestMode), 'Unknown probe mode.');
   check(request.parallelism === (requestMode === 'serial' || requestMode === 'restart' ? 1 : 2), 'Probe mode and admission differ.');
   storeKey = await digest(new TextEncoder().encode('game-pool-diagnostic-' + requestMode + '-' + request.nonce));
   await LightForgeAnalysisStore.discard(storeKey);
   store = await LightForgeAnalysisStore.open(storeKey, {sourceId: 'game-pool-diagnostic'});
   const reader = new LightForgeWavReader(new URL('../demo/glass-castle.wav', self.location.href).href);
   await reader.open(); check(reader.rate === 44100 && reader.samples >= result.samples, 'Real demo source clock is incomplete.');
   const read = async (first, count) => {
    const stereo = await reader.stereo44100(first, count), mono = new Float32Array(count);
    for (let i = 0; i < count; i++) mono[i] = (stereo[0][i] + stereo[1][i]) * .5;
    reads.push({first, count, sha256: await digest(new Uint8Array(mono.buffer))});
    return mono;
   };
   const checkpoint = {read: async key => store.read(key), write: async (key, value) => {
    check(!Object.prototype.hasOwnProperty.call(checkpoints, key), 'A passage checkpoint was written twice.');
    await store.write(key, value);
    check(canonical(await store.read(key)) === canonical(value), 'The durable checkpoint did not preserve its payload.');
    const bytes = new TextEncoder().encode(JSON.stringify(value));
    checkpoints[key] = {value, json: new TextDecoder().decode(bytes), sha256: await digest(bytes)};
    writes.push(key);
   }};
   probeGame = await LightForgeGAME.create({ort, baseUrl: new URL('models/game/', self.location.href).href, checkpoint, parallelism: request.parallelism,
    onProgress: detail => send({type: 'pool-probe-progress', mode: requestMode, detail})});
   if (requestMode === 'restart') {
    const pcm = await read(0, 14 * 44100);
    result.restartedNotes = await probeGame.infer(pcm, 0, 2025, progress => send({type: 'pool-probe-progress', mode: requestMode, progress}));
   } else {
    try {
     result.transcription = await probeGame.process(read, result.samples, {language: 0, onProgress: (progress, info) => send({type: 'pool-probe-progress', mode: requestMode, progress, info})});
     check(requestMode !== 'cancel', 'Cancelled analysis unexpectedly completed.');
    } catch (error) {
     if (requestMode !== 'cancel') throw error;
     check(error.name === 'AbortError', 'Cancellation did not reject with AbortError: ' + error);
     result.aborted = true;
    }
   }
   await probeGame.release();
   if (cancellation) {
    const until = performance.now() + 10000;
    while (!cancellation.released && !cancellation.error && performance.now() < until) await new Promise(resolve => setTimeout(resolve, 25));
    result.cancellation = cancellation;
    check(cancellation.released && !cancellation.error && result.aborted, 'Cancellation did not fully release the engine.');
    check(writes.length === 0, 'Cancelled initialization committed passage work.');
   }
   if (request.parallelism === 2) check(children.length === 1 && children[0].inferRequests === 1 && children[0].terminated, 'Expected child was not created, used, and terminated exactly once.');
   else check(children.length === 0, 'Serial execution created a descendant worker.');
   if (requestMode === 'parallel') check(children[0].results === 1, 'The child did not supply a completed real-model result.');
   result.concurrentGraphCalls = executions.some(a => a.lane === 'child' && executions.some(b => b.lane === 'parent' && a.startEpochMs < b.endEpochMs && b.startEpochMs < a.endEpochMs));
   if (requestMode === 'parallel') check(result.concurrentGraphCalls, 'No parent and child model calls overlapped.');
   const ordered = records.slice().sort((a,b) => canonical([a.pcm,a.graph,a.ordinal]).localeCompare(canonical([b.pcm,b.graph,b.ordinal])));
   result.rawOutputsSha256 = await digest(new TextEncoder().encode(canonical(ordered)));
   if (result.transcription) result.transcriptionJson = JSON.stringify(result.transcription);
   if (result.restartedNotes) result.restartedNotesJson = JSON.stringify(result.restartedNotes);
   result.passed = true;
  } catch (error) { result.error = String(error.stack || error); }
  finally {
   if (probeGame) try { await probeGame.release(); } catch (error) { result.passed = false; result.releaseError = String(error); }
   if (storeKey) try { await LightForgeAnalysisStore.discard(storeKey); result.checkpointNamespaceRemoved = true; } catch (error) { result.passed = false; result.checkpointCleanupError = String(error); }
   result.seconds = (performance.now() - started) / 1000;
   result.effectiveThreads = ort.env.wasm.numThreads;
   send({type: 'game-pool-result', result});
  }
 };
}
