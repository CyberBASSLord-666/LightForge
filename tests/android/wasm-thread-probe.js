/* Separate instrumentation asset; all imported engine/runtime/model bytes are production. */
'use strict';
const wtSend = self.postMessage.bind(self), wtChildren = [], wtRecords = [], wtSessions = [];
const wtRealWorker = self.Worker;
if (wtRealWorker) self.Worker = class extends wtRealWorker {
 constructor(url, options) {
  super(url, options);
  const entry = {url: String(url), options: options || null, messages: [], terminated: false};
  wtChildren.push(entry); this.wtEntry = entry;
  this.addEventListener('message', event => entry.messages.push(String(event.data?.cmd || event.data?.type || typeof event.data)));
 }
 terminate() { this.wtEntry.terminated = true; return super.terminate(); }
};
importScripts('worker.js');
const wtCheck = (condition, message) => { if (!condition) throw Error(message); };
// WebCrypto does not accept a SharedArrayBuffer view. The detached copy is only
// for hashing; the unchanged output tensor continues to the actual GAME code.
const wtDigest = async bytes => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new Uint8Array(bytes.buffer || bytes, bytes.byteOffset || 0, bytes.byteLength).slice())), n => n.toString(16).padStart(2, '0')).join('');
self.onmessage = async event => {
 const request = event.data, started = performance.now();
 const result = {mode: request.mode, passed: false, crossOriginIsolated: self.crossOriginIsolated === true,
  sharedArrayBuffer: typeof SharedArrayBuffer === 'function', hardwareConcurrency: navigator.hardwareConcurrency,
  secureContext: self.isSecureContext === true, workerLocation: self.location.href,
  configuredThreads: null, effectiveThreads: null, pthreadWorkers: wtChildren, records: wtRecords, sessions: wtSessions};
 let graph, input, outputs, game, store, key;
 try {
  wtCheck(['tiny', 'reference', 'candidate', 'cancel', 'restart'].includes(request.mode), 'Unknown mode.');
  result.policyChecks = [];
  const originalCoreProperty = Object.getOwnPropertyDescriptor(navigator, 'hardwareConcurrency');
  try {
   // Unit inputs to the actual packaged selector only. Restore the real device
   // capability before calling the worker or initializing its WASM runtime.
   for (const cores of [4, 8]) {
    Object.defineProperty(navigator, 'hardwareConcurrency', {configurable: true, value: cores});
    for (const [stage, quality] of [['rhythm', 'balanced'], ['bass', 'balanced'], ['separation', 'balanced'], ['separation', 'precision'], ['voice-classifier', 'balanced'], ['voice', 'balanced']]) {
     const selected = wasmThreadsForStage({androidApp: true}, stage, quality);
     const qualified = stage === 'voice' || stage === 'separation' && quality === 'precision';
     const expected = result.crossOriginIsolated && result.sharedArrayBuffer && cores >= 8 && qualified ? 4 : 1;
     wtCheck(selected === expected, 'Packaged Android stage policy differs.');
     result.policyChecks.push({simulatedCores: cores, stage, quality, selected});
    }
   }
  } finally {
   if (originalCoreProperty) Object.defineProperty(navigator, 'hardwareConcurrency', originalCoreProperty);
   else delete navigator.hardwareConcurrency;
  }
  wtCheck(navigator.hardwareConcurrency === result.hardwareConcurrency, 'Device capability was not restored before runtime initialization.');
  key = await wtDigest(new TextEncoder().encode('wasm-thread-probe-' + request.nonce + '-' + request.mode));
  await LightForgeAnalysisStore.discard(key);
  result.productionRequest = {stage: 'voice', androidApp: true, analysisQuality: 'balanced'};
  result.threadSelectionScope = 'actual-packaged-selector-direct-game';
  result.productionDispatchExercised = false;
  // This deliberately qualifies GAME independently of classifier handoff.
  // Calling the packaged selector is not a full production voice-stage run;
  // the separate full-pipeline proof covers classifier-one/GAME-four routing.
  result.configuredThreads = wasmThreadsForStage({androidApp: true}, 'voice', 'balanced');
  ort.env.wasm.wasmPaths = new URL('vendor/', self.location.href).href;
  result.wasmPaths = ort.env.wasm.wasmPaths;
  ort.env.wasm.numThreads = result.configuredThreads;
  ort.env.wasm.proxy = false;
  // Only the serial reference changes this setting. The candidate retains the
  // exact assignment made by the packaged production analysis worker.
  if (request.mode === 'reference') ort.env.wasm.numThreads = 1;
  const hex = '08083a5a0a190a05696e70757412066f757470757422084964656e7469747912124c69676874466f72676543707550726f62655a130a05696e707574120a0a08080112040a02080462140a066f7574707574120a0a08080112040a0208044202100d';
  graph = await ort.InferenceSession.create(Uint8Array.from(hex.match(/../g), x => parseInt(x, 16)), {executionProviders: ['wasm'], graphOptimizationLevel: 'all', enableCpuMemArena: false, enableMemPattern: false});
  input = new ort.Tensor('float32', new Float32Array([1, -2, .25, -0]), [4]);
  outputs = await graph.run({input});
  result.effectiveThreads = ort.env.wasm.numThreads;
  result.outputBits = Array.from(new Uint32Array(outputs.output.data.buffer, outputs.output.data.byteOffset, 4));
  result.identityExact = JSON.stringify(result.outputBits) === JSON.stringify([1065353216, 3221225472, 1048576000, 2147483648]);
  wtCheck(result.identityExact, 'Identity did not preserve all float32 bits.');
  const expected = request.mode === 'reference' ? 1 : request.expectedThreads;
  wtCheck(result.effectiveThreads === expected, 'Effective threads differ from the required runtime: ' + result.effectiveThreads);
  wtCheck(wtChildren.length === Math.max(0, expected - 1) && wtChildren.every(c => c.messages.includes('loaded')), 'Expected real loaded pthread workers are missing.');
  for (const output of Object.values(outputs)) output.dispose(); outputs = null; input.dispose(); input = null; await graph.release(); graph = null;
  if (!['tiny', 'restart'].includes(request.mode)) {
   const pcmBytes = await (await fetch('__wasm_thread_pcm__.f32')).arrayBuffer();
   result.fixtureSha256 = await wtDigest(pcmBytes);
   wtCheck(result.fixtureSha256 === request.fixtureSha256 && pcmBytes.byteLength === 3 * 44100 * 4, 'Separated source PCM identity/clock differs.');
   const pcm = new Float32Array(pcmBytes); wtCheck(pcm.every(Number.isFinite), 'Source PCM contains invalid samples.');
   result.samples = pcm.length; result.sampleRate = 44100; result.seed = 2025; result.language = 0;
   const create = ort.InferenceSession.create.bind(ort.InferenceSession), counts = {};
   ort.InferenceSession.create = async (url, options) => {
    const name = new URL(String(url), self.location.href).pathname.split('/').pop().replace('.onnx', '');
    const session = await create(url, options); wtSessions.push(name); const run = session.run.bind(session);
    session.run = async (feeds, ...rest) => {
     const ordinal = counts[name] || 0; counts[name] = ordinal + 1;
     if (name === 'encoder') {
      wtCheck(await wtDigest(feeds.waveform.data) === result.fixtureSha256, 'GAME encoder did not receive exact fixture bytes.');
      if (request.mode === 'cancel') wtSend({type: 'wasm-thread-active', result: {mode: request.mode, effectiveThreads: ort.env.wasm.numThreads, pthreadWorkers: wtChildren, graph: name, samples: pcm.length, checkpointKey: key}});
     }
     const began = performance.now(), values = await run(feeds, ...rest), seconds = (performance.now() - began) / 1000, tensors = {};
     for (const key of Object.keys(values).sort()) {
      const tensor = values[key]; wtCheck(ArrayBuffer.isView(tensor.data), 'Nonnumeric graph output.');
      tensors[key] = {type: tensor.type, dims: Array.from(tensor.dims), bytes: tensor.data.byteLength, sha256: await wtDigest(tensor.data)};
     }
     wtRecords.push({graph: name, ordinal, tensors});
     wtSend({type: 'wasm-thread-progress', graph: name, ordinal, seconds});
     return values;
    };
    return session;
   };
   store = await LightForgeAnalysisStore.open(key, {sourceId: 'wasm-thread-probe'});
   result.freshCheckpointMiss = (await store.read('game-0-0')) === null;
   wtCheck(result.freshCheckpointMiss, 'Fresh neural comparison restored earlier work.');
   let writes = 0;
   const checkpoint = {read: name => store.read(name), write: async (name, value) => {
    wtCheck(name === 'game-0-0' && ++writes === 1, 'Unexpected or duplicate passage write.');
    await store.write(name, value); result.checkpointJson = JSON.stringify(value);
    wtCheck(JSON.stringify(await store.read(name)) === result.checkpointJson, 'OPFS changed the unrounded checkpoint.');
   }};
   game = await LightForgeGAME.create({ort, baseUrl: new URL('models/game/', self.location.href).href, checkpoint, parallelism: 1,
    onProgress: detail => wtSend({type: 'wasm-thread-progress', detail})});
   const read = async (first, count) => { wtCheck(first === 0 && count === pcm.length, 'Production passage changed its source clock.'); return pcm; };
   const notes = await game.process(read, pcm.length, {language: 0});
   wtCheck(request.mode !== 'cancel', 'Cancellation did not interrupt inference.');
   result.transcriptionJson = JSON.stringify(notes); result.checkpointSha256 = await wtDigest(new TextEncoder().encode(result.checkpointJson));
   wtCheck(JSON.stringify(counts) === JSON.stringify({encoder: 1, dur2bd: 1, segmenter: 8, bd2dur: 1, estimator: 1}), 'Incomplete graph coverage: ' + JSON.stringify(counts));
   wtCheck(wtRecords.length === 12 && writes === 1, 'Graph/checkpoint counts differ.');
   const resumed = await game.process(async () => { throw Error('Resume unexpectedly read source PCM.'); }, pcm.length, {language: 0});
   result.resumeWithoutInference = wtRecords.length === 12 && JSON.stringify(resumed) === result.transcriptionJson && writes === 1;
   wtCheck(result.resumeWithoutInference, 'Durable restore changed notes or repeated inference.');
   result.rawOutputsSha256 = await wtDigest(new TextEncoder().encode(JSON.stringify(wtRecords)));
   wtCheck(ort.env.wasm.numThreads === expected, 'Runtime thread count changed during GAME inference.');
   await game.release(); game = null; result.modelSessionsReleased = true;
  }
  result.passed = true;
 } catch (error) { result.error = String(error.stack || error); }
 finally {
  try {
   if (outputs) for (const value of Object.values(outputs)) value.dispose();
   if (input) input.dispose(); if (graph) await graph.release(); if (game) await game.release();
   if (key) { await LightForgeAnalysisStore.discard(key); result.checkpointNamespaceRemoved = true; }
  } catch (error) { result.passed = false; result.cleanupError = String(error.stack || error); }
  result.seconds = (performance.now() - started) / 1000;
  wtSend({type: 'wasm-thread-result', result});
 }
};
