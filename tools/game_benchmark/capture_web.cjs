#!/usr/bin/env node
'use strict';
// Executes the shipped GAME adapter; wrapping run() captures every raw output.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {pathToFileURL, fileURLToPath} = require('node:url');
const root = path.resolve(__dirname, '../..');
const GAME = require(path.join(root, 'web/analysis/game.js'));
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const cpuSeconds = usage => (usage.user + usage.system) / 1e6;

function checkFeeds(graph, feeds, contract) {
  if (!contract) return;
  const expected = contract.graphs[graph].inputs;
  if (Object.keys(feeds).sort().join(',') !== expected.map(t => t.name).sort().join(',')) throw Error('Graph input inventory mismatch: ' + graph);
  for (const tensor of expected) {
    const actual = feeds[tensor.name];
    if (actual.dims.length !== tensor.dims.length || tensor.dims.some((dim, i) =>
      (dim === 'B' && actual.dims[i] !== 1) || (Number.isInteger(dim) && actual.dims[i] !== dim))) {
      throw Error('Graph input shape mismatch: ' + graph + '/' + tensor.name);
    }
  }
}

async function main() {
  if (require('node:os').endianness() !== 'LE') throw Error('Capture requires little-endian host');
  const [modelsArg, inputArg, outputArg, seedArg, languageArg, threadsArg, captureArg, mode = 'baseline', contractArg] = process.argv.slice(2);
  if (process.argv.length < 9 || process.argv.length > 11) throw Error('models-directory pcm-f32le output-directory seed language threads capture(true|false) [baseline|batch-one] [shape-contract.json]');
  const models = path.resolve(modelsArg), input = path.resolve(inputArg), output = path.resolve(outputArg);
  const seed = Number(seedArg), language = Number(languageArg), threads = Number(threadsArg), capture = captureArg === 'true';
  if (!Number.isInteger(seed) || seed < 0 || seed > 0xffffffff || ![0,1,2,3,4].includes(language) || !Number.isInteger(threads) || threads < 1 || threads > 64 || !['true','false'].includes(captureArg)) throw Error('Invalid settings');
  if (!['baseline','batch-one'].includes(mode) || (mode === 'batch-one' && !contractArg)) throw Error('Batch-one experiment requires the original-graph shape contract');
  if (fs.existsSync(output)) throw Error('Output directory must not exist');
  const inputBytes = fs.statSync(input).size;
  if (inputBytes < 4 || inputBytes % 4 || inputBytes > 16 * 44100 * 4) throw Error('Expected one nonempty <=16-second mono Float32 passage');
  const manifest = JSON.parse(fs.readFileSync(path.join(models, 'manifest.json'), 'utf8'));
  if (manifest.id !== 'game-large-1.0.3-lightforge-1' || manifest.steps !== 8 || manifest.sampleRate !== 44100) throw Error('Unexpected GAME manifest');
  const modelFiles = {};
  for (const name of ['encoder','dur2bd','segmenter','bd2dur','estimator']) {
    const file = name + '.onnx', bytes = fs.readFileSync(path.join(models, file)), expected = manifest.files[file];
    if (bytes.length !== expected.bytes || hash(bytes) !== expected.sha256) throw Error('Model checksum mismatch: ' + name);
    modelFiles[file] = expected;
  }
  const contract = contractArg ? JSON.parse(fs.readFileSync(contractArg, 'utf8')) : null;
  if (contract) {
    if (contract.schema !== 'lightforge-game-batch-contract-1') throw Error('Invalid shape contract');
    for (const [file, expected] of Object.entries(modelFiles)) {
      const graph = contract.graphs?.[path.basename(file, '.onnx')], bound = contract.modelFiles?.[file];
      if (bound?.sha256 !== expected.sha256 || bound?.bytes !== expected.bytes || !graph?.inputs?.some(t => t.dims[0] === 'B')) throw Error('Shape contract does not bind the original batch dimension: ' + file);
    }
  }
  const bytes = fs.readFileSync(input), pcm = new Float32Array(bytes.length / 4);
  for (let i = 0; i < pcm.length; i++) { pcm[i] = bytes.readFloatLE(i * 4); if (!Number.isFinite(pcm[i])) throw Error('Invalid PCM'); }
  fs.mkdirSync(output, {recursive:true});
  const ort = require(path.join(root, 'web/analysis/vendor/ort.wasm.min.js'));
  ort.env.wasm.numThreads = threads;
  ort.env.wasm.wasmPaths = path.join(root, 'web/analysis/vendor/');
  const initialization = [], stages = [], counts = {};
  const wrapped = {
    Tensor: ort.Tensor,
    InferenceSession: {async create(url, options) {
      const filename = fileURLToPath(url), graph = path.basename(filename, '.onnx');
      // This wrapper is benchmark-only. The shipped adapter and graph bytes are
      // identical in both modes; only the proven batch dimension is specialized.
      const sessionOptions = mode === 'batch-one' ? {...options, freeDimensionOverrides:{B:1}} : options;
      const bytes = fs.readFileSync(filename), cpu = process.cpuUsage(), start = performance.now();
      const session = await ort.InferenceSession.create(bytes, sessionOptions);
      initialization.push({graph, seconds:(performance.now() - start) / 1000, processCpuSeconds:cpuSeconds(process.cpuUsage(cpu)), options:sessionOptions});
      return {
        async run(feeds) {
          checkFeeds(graph, feeds, contract);
          const cpu = process.cpuUsage(), start = performance.now(), result = await session.run(feeds), seconds = (performance.now() - start) / 1000;
          const processCpuSeconds = cpuSeconds(process.cpuUsage(cpu));
          const index = counts[graph] || 0; counts[graph] = index + 1;
          const label = graph === 'segmenter' ? graph + '-' + index : graph;
          const outputs = [];
          for (const [name,tensor] of Object.entries(result)) {
            const data = tensor.data;
            if (!ArrayBuffer.isView(data)) throw Error('Unsupported tensor output');
            if ((tensor.type === 'float32' || tensor.type === 'float64') && data.some(value => !Number.isFinite(value))) throw Error('Nonfinite tensor output: ' + label + '/' + name);
            const bytes = Buffer.from(data.buffer, data.byteOffset, data.byteLength), file = label + '-' + name + '.bin';
            if (capture) fs.writeFileSync(path.join(output,file),bytes,{flag:'wx'});
            outputs.push({name,type:tensor.type,dims:tensor.dims,...(capture ? {file} : {}),bytes:bytes.length,sha256:hash(bytes),finite:true});
          }
          stages.push({graph,label,seconds,processCpuSeconds,outputs});
          console.error(label + ' ' + seconds + ' seconds');
          return result;
        },
        release: () => session.release()
      };
    }}
  };
  const savedFetch = globalThis.fetch;
  globalThis.fetch = async url => {
    const filename = fileURLToPath(url);
    if (filename === path.join(models,'manifest.json')) return {json:async()=>manifest};
    if (filename === path.join(root,'web/analysis/vendor/ort-wasm-simd-threaded.wasm'))
      return new Response(fs.readFileSync(filename), {headers:{'Content-Type':'application/wasm'}});
    throw Error('Unexpected benchmark fetch: ' + filename);
  };
  const cpu = process.cpuUsage(), start = performance.now(); let adapter;
  try {
    adapter = await GAME.create({ort:wrapped,baseUrl:pathToFileURL(models + path.sep).href});
    const notes = await adapter.infer(pcm,language,seed);
    const wallSeconds = (performance.now() - start) / 1000;
    const receipt = {
      schema:'lightforge-game-benchmark-1',runtime:'onnxruntime-web-' + ort.env.versions.web,
      sampleRate:44100,samples:pcm.length,pcmSHA256:hash(bytes),modelFiles,seed,language,steps:8,requestedThreads:threads,
      effectiveThreads:null,runtimeReportedWasmThreads:ort.env.wasm.numThreads,
      threadObservation:'WASM configuration only; effective workers and runtime fallback were not independently observed',capture,
      experiment:mode,freeDimensionOverrides:mode === 'batch-one' ? {B:1} : {},
      shapeContractSHA256:contractArg ? hash(fs.readFileSync(contractArg)) : null,
      initialization,stages,notes,inferenceSeconds:stages.reduce((n,s)=>n+s.seconds,0),wallSeconds,wallIncludesCapture:capture,
      inferenceProcessCpuSeconds:stages.reduce((n,s)=>n+s.processCpuSeconds,0),passageProcessCpuSeconds:cpuSeconds(process.cpuUsage(cpu)),
      processPeakRssKiB:process.resourceUsage().maxRSS,
      timingScope:'Sum of awaited session.run calls, excluding session initialization, PCM/model reads, input checks, output validation/hash/capture and note postprocessing; fresh process and sessions per passage',
      memoryScope:'OS process lifetime peak RSS in KiB, including graph loading, JavaScript, WASM linear memory and output evidence; not isolated model working memory',
      cpuScope:'Process user plus system CPU across threads during awaited session.run calls; wall time also includes scheduling waits',
      scope:'Shipped GAME adapter under Node WASM; not an Android WebView or physical-device performance result'
    };
    fs.writeFileSync(path.join(output,'receipt.json'),JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});
    console.log(JSON.stringify({receipt:path.join(output,'receipt.json'),inferenceSeconds:receipt.inferenceSeconds,notes:notes.length}));
  } finally { await adapter?.release(); globalThis.fetch = savedFetch; }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
