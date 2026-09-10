/* Diagnostic only: imported by a separate instrumentation APK, never shipped. */
'use strict';
const probeSend = self.postMessage.bind(self), messages = [], children = [];
const NativeWorker = self.Worker;
if (NativeWorker) self.Worker = class extends NativeWorker {
 constructor(url, options) {
  super(url, options);
  const entry = {url: String(url), options: options || null, messages: []};
  children.push(entry);
  this.addEventListener('message', event => {
   const value = event.data;
   entry.messages.push(value && typeof value === 'object' ? String(value.cmd || value.type || 'object') : typeof value);
  });
 }
};
// This URL is served only by the test APK at /analysis/__cpu_probe__.js.
// Relative imports and the shipped wasmPaths calculation therefore retain
// the production /analysis/ base. Every imported byte comes from the CI APK.
importScripts('worker.js');
const shippedHandler = self.onmessage;
self.postMessage = value => messages.push(value);
self.onmessage = async () => {
 const result = {
  diagnosticOnly: true, workerLocation: self.location.href,
  crossOriginIsolated: self.crossOriginIsolated === true,
  sharedArrayBuffer: typeof SharedArrayBuffer === 'function',
  hardwareConcurrency: navigator.hardwareConcurrency,
  userAgent: navigator.userAgent,
  secureContext: self.isSecureContext === true,
  workerSourceSha256: null, ortSourceSha256: null,
  configuredThreads: null, effectiveThreads: null,
  pthreadWorkers: children, wasmProxy: null,
 };
 const key = 'fc'.repeat(32), sentinel = '__LIGHTFORGE_CPU_PROBE_STOP_AFTER_SHIPPED_CONFIG__';
 let session, input, outputs;
 try {
  const sha = async name => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await (await fetch(name)).arrayBuffer())), value => value.toString(16).padStart(2, '0')).join('');
  result.workerSourceSha256 = await sha('worker.js');
  result.ortSourceSha256 = await sha('vendor/ort.wasm.min.js');
  // Observe the actual shipped assignment. Stop immediately afterward, before
  // any model is loaded, rather than copying the thread selection expression.
  let proxyValue;
  Object.defineProperty(ort.env.wasm, 'proxy', {
   configurable: true, get: () => proxyValue,
   set(value) {
    proxyValue = value;
    result.wasmProxy = value;
    result.configuredThreads = ort.env.wasm.numThreads;
    result.wasmPaths = ort.env.wasm.wasmPaths;
    throw Error(sentinel);
   }
  });
  await shippedHandler({data: {stage: 'rhythm', options: {workId: key, projectId: 'analysis-cpu-probe', analysisQuality: 'balanced'}}});
  Object.defineProperty(ort.env.wasm, 'proxy', {configurable: true, enumerable: true, writable: true, value: proxyValue});
  if (!Number.isInteger(result.configuredThreads) || !messages.some(value => value.type === 'error' && value.message === sentinel)) {
   throw Error('Shipped runtime configuration was not reached: ' + JSON.stringify(messages));
  }
  // An ONNX Identity graph, IR 8 / opset 13 / float32[4]. This exercises the
  // shipped backend initialization and its thread fallback, without loading
  // a musical model or presenting this as a throughput benchmark.
  const hex = '08083a5a0a190a05696e70757412066f757470757422084964656e7469747912124c69676874466f72676543707550726f62655a130a05696e707574120a0a08080112040a02080462140a066f7574707574120a0a08080112040a0208044202100d';
  const graph = Uint8Array.from(hex.match(/../g), value => parseInt(value, 16));
  session = await ort.InferenceSession.create(graph, {executionProviders: ['wasm'], graphOptimizationLevel: 'all', enableCpuMemArena: false, enableMemPattern: false});
  result.effectiveThreads = ort.env.wasm.numThreads;
  input = new ort.Tensor('float32', new Float32Array([1, -2, .25, -0]), [4]);
  outputs = await session.run({input});
  const actual = new Uint32Array(outputs.output.data.buffer, outputs.output.data.byteOffset, 4);
  const expected = new Uint32Array(input.data.buffer, input.data.byteOffset, 4);
  result.outputBits = Array.from(actual);
  result.identityExact = actual.every((value, index) => value === expected[index]);
  if (!result.identityExact) throw Error('Tiny graph changed float32 bits.');
  if (result.effectiveThreads > 1 && !children.some(child => child.messages.includes('loaded'))) throw Error('Multithread configuration lacked a loaded pthread worker.');
  result.passed = true;
 } catch (error) {
  result.passed = false;
  result.error = String(error.stack || error);
 } finally {
  if (outputs) for (const value of Object.values(outputs)) value.dispose();
  if (input) input.dispose();
  if (session) await session.release();
  try { await LightForgeAnalysisStore.discard(key); result.checkpointRemoved = true; }
  catch (error) { result.passed = false; result.cleanupError = String(error); }
  probeSend({type: 'analysis-cpu-probe', result});
 }
};
