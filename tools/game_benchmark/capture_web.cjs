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

async function main() {
  if (require('node:os').endianness() !== 'LE') throw Error('Capture requires little-endian host');
  const [modelsArg, inputArg, outputArg, seedArg, languageArg, threadsArg, captureArg] = process.argv.slice(2);
  if (process.argv.length !== 9) throw Error('models-directory pcm-f32le output-directory seed language threads capture(true|false)');
  const models = path.resolve(modelsArg), input = path.resolve(inputArg), output = path.resolve(outputArg);
  const seed = Number(seedArg), language = Number(languageArg), threads = Number(threadsArg), capture = captureArg === 'true';
  if (!Number.isInteger(seed) || seed < 0 || seed > 0xffffffff || ![0,1,2,3,4].includes(language) || !Number.isInteger(threads) || threads < 1 || threads > 64 || !['true','false'].includes(captureArg)) throw Error('Invalid settings');
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
      const bytes = fs.readFileSync(filename), start = performance.now();
      const session = await ort.InferenceSession.create(bytes, options);
      initialization.push({graph, seconds:(performance.now() - start) / 1000});
      return {
        async run(feeds) {
          const start = performance.now(), result = await session.run(feeds), seconds = (performance.now() - start) / 1000;
          const index = counts[graph] || 0; counts[graph] = index + 1;
          const label = graph === 'segmenter' ? graph + '-' + index : graph;
          const outputs = [];
          if (capture) for (const [name,tensor] of Object.entries(result)) {
            const data = tensor.data;
            if (!ArrayBuffer.isView(data)) throw Error('Unsupported tensor output');
            const bytes = Buffer.from(data.buffer, data.byteOffset, data.byteLength), file = label + '-' + name + '.bin';
            fs.writeFileSync(path.join(output,file),bytes,{flag:'wx'});
            outputs.push({name,type:tensor.type,dims:tensor.dims,file,bytes:bytes.length,sha256:hash(bytes)});
          }
          stages.push({graph,label,seconds,outputs});
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
  const start = performance.now(); let adapter;
  try {
    adapter = await GAME.create({ort:wrapped,baseUrl:pathToFileURL(models + path.sep).href});
    const notes = await adapter.infer(pcm,language,seed);
    const wallSeconds = (performance.now() - start) / 1000;
    const receipt = {
      schema:'lightforge-game-benchmark-1',runtime:'onnxruntime-web-' + ort.env.versions.web,
      sampleRate:44100,samples:pcm.length,pcmSHA256:hash(bytes),modelFiles,seed,language,steps:8,requestedThreads:threads,
      effectiveThreads:null,runtimeReportedWasmThreads:ort.env.wasm.numThreads,
      threadObservation:'WASM configuration only; effective workers and runtime fallback were not independently observed',capture,
      initialization,stages,notes,inferenceSeconds:stages.reduce((n,s)=>n+s.seconds,0),wallSeconds,wallIncludesCapture:capture,
      scope:'Shipped GAME adapter under Node WASM; not an Android WebView or physical-device performance result'
    };
    fs.writeFileSync(path.join(output,'receipt.json'),JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});
    console.log(JSON.stringify({receipt:path.join(output,'receipt.json'),inferenceSeconds:receipt.inferenceSeconds,notes:notes.length}));
  } finally { await adapter?.release(); globalThis.fetch = savedFetch; }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
