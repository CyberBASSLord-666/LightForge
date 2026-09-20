#!/usr/bin/env node
'use strict';
// Replay real captured notes through the unchanged production checkpoint/stitch path.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {isDeepStrictEqual} = require('node:util');
const root = path.resolve(__dirname, '../..');
const GAME = require(path.join(root, 'web/analysis/game.js'));
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

function planPassages(total, language = 0) {
  if (!Number.isSafeInteger(total) || total < 1 || total > 44100 * 14401 || ![0,1,2,3,4].includes(language)) throw Error('Invalid source clock or language');
  const duration = total / 44100, passages = [];
  for (let index = 0; index < Math.ceil(duration / 12); index++) {
    const first = Math.round(Math.max(0, index * 12 - 2) * 44100);
    const last = Math.min(total, Math.round(Math.min(duration, (index + 1) * 12 + 2) * 44100));
    passages.push({index, key:'game-' + language + '-' + index, first, last, seed:(2025 + index * 104729) >>> 0});
  }
  return passages;
}

async function processRecords(manifest, total, language, records, nativeMode=false) {
  if (manifest.id !== 'game-large-1.0.3-lightforge-1' || manifest.steps !== 8 || manifest.sampleRate !== 44100) throw Error('Unexpected GAME model contract');
  const plan = planPassages(total, language);
  if (records.length !== plan.length) throw Error('Incomplete passage records');
  for (let i = 0; i < plan.length; i++) {
    for (const field of ['index','first','last','seed']) if (records[i][field] !== plan[i][field]) throw Error('Passage contract mismatch: ' + field);
    if (!Array.isArray(records[i].notes)) throw Error('Missing raw notes');
  }
  const consumed = [], savedFetch = globalThis.fetch;
  const baseUrl = pathToFileURL(path.join(root, 'web/analysis/models/game') + path.sep).href;
  globalThis.fetch = async url => {
    if (String(url) !== new URL('manifest.json', baseUrl).href) throw Error('Unexpected replay fetch');
    return {json:async()=>manifest};
  };
  let adapter;
  try {
    adapter = await GAME.create({
      baseUrl,
      ...(nativeMode?{nativeInfer:async()=>{throw Error('Unexpected inference during native checkpoint replay');}}:{}),
      ort:{InferenceSession:{create:async()=>{throw Error('Production rejected a captured checkpoint');}}},
      checkpoint:{read:async key=>{
        const index = plan.findIndex(p=>p.key === key);
        if (index < 0 || consumed.includes(index)) throw Error('Unexpected or duplicate checkpoint');
        consumed.push(index);
        return {model:manifest.id, steps:8, first:records[index].first, last:records[index].last,
                notes:structuredClone(records[index].notes),...(nativeMode?{execution:'native-game-v1'}:{})};
      }}
    });
    const result = await adapter.process(async()=>{throw Error('Production rejected a captured checkpoint');}, total, {language});
    assert.deepEqual(consumed, plan.map(p=>p.index), 'Production did not consume the exact passage plan');
    return result;
  } finally {
    await adapter?.release();
    globalThis.fetch = savedFetch;
  }
}

function checkedReceipt(directory, relative, expectedHash) {
  const resolved = path.resolve(directory, relative);
  if (!resolved.startsWith(path.resolve(directory) + path.sep)) throw Error('Receipt escapes experiment directory');
  const bytes = fs.readFileSync(resolved);
  if (hash(bytes) !== expectedHash) throw Error('Captured receipt digest mismatch');
  return JSON.parse(bytes);
}

async function compareCapturedProcess(inputFile) {
  const directory = path.dirname(path.resolve(inputFile)), bytes = fs.readFileSync(inputFile), input = JSON.parse(bytes);
  if (input.schema !== 'lightforge-game-native-process-input-1') throw Error('Unknown process capture schema');
  const manifest = input.modelManifest, plan = planPassages(input.totalSamples, input.language), sides = {};
  if (input.passages.length !== plan.length) throw Error('Incomplete captured passages');
  for (const side of ['wasm','native']) {
    const records = input.passages.map((passage, index)=>{
      for (const field of ['index','first','last','seed']) if (passage[field] !== plan[index][field]) throw Error('Capture plan mismatch');
      const receipt = checkedReceipt(directory, passage[side + 'Receipt'], passage[side + 'ReceiptSha256']);
      if (receipt.schema !== 'lightforge-game-benchmark-1' || receipt.steps !== 8 || receipt.sampleRate !== 44100 ||
          receipt.samples !== passage.last - passage.first || receipt.seed !== passage.seed || receipt.language !== input.language ||
          receipt.pcmSHA256 !== passage.pcmSha256 || receipt.capture !== true) throw Error('Capture input binding mismatch');
      const expectedModels = Object.fromEntries(['encoder','dur2bd','segmenter','bd2dur','estimator'].map(name=>[name+'.onnx',manifest.files[name+'.onnx']]));
      assert.deepEqual(receipt.modelFiles, expectedModels, 'Capture model binding mismatch');
      return {...plan[index], notes:receipt.notes};
    });
    sides[side] = await processRecords(manifest, input.totalSamples, input.language, records);
  }
  const identical = JSON.stringify(sides.wasm) === JSON.stringify(sides.native);
  return {
    schema:'lightforge-game-native-process-comparison-1', captureInputSha256:hash(bytes),
    productionAdapterSha256:hash(fs.readFileSync(path.join(root,'web/analysis/game.js'))),
    totalSamples:input.totalSamples, language:input.language, passageCount:plan.length,
    productionTranscriptionIdentical:identical,
    wasm:sides.wasm, native:sides.native,
    scope:'Actual production process() checkpoint validation, clipping, continuation, stitching, sorting and rounding over captured real-model passage notes. Model inference was captured separately.',
    rawTensorParityRequiredElsewhere:true, fullAnalysisQualityApproved:false, androidIntegrationApproved:false,
    limitations:['Raw tensor and unrounded pitch differences remain in stage comparison receipts.',
                'This replay does not run source separation, vocal fusion, show generation, native task ownership or Android lifecycle behavior.']
  };
}

async function processNativeRecords(manifest, pcmBytes, language, records) {
  const total=pcmBytes.length/4, plan=planPassages(total,language), checkpoints=new Map();
  if(records.length!==plan.length)throw Error('Incomplete production native records');
  for(let i=0;i<plan.length;i++)for(const field of ['index','first','last','seed'])
    if(records[i][field]!==plan[i][field])throw Error('Production native passage mismatch');
  let calls=0,reads=0,adapter;
  const savedFetch=globalThis.fetch,baseUrl='file:///lightforge-production-game/';
  globalThis.fetch=async url=>{
    if(String(url)!==baseUrl+'manifest.json')throw Error('Unexpected native replay fetch');
    return {json:async()=>manifest};
  };
  try{
    adapter=await GAME.create({baseUrl,
      ort:{InferenceSession:{create:async()=>{throw Error('Unexpected WASM inference during native replay');}}},
      checkpoint:{read:async key=>structuredClone(checkpoints.get(key)),write:async(key,value)=>checkpoints.set(key,structuredClone(value))},
      nativeInfer:async(pcm,actualLanguage,seed)=>{
        const record=records[calls++];
        if(!record||actualLanguage!==language||seed!==record.seed||pcm.length!==record.last-record.first||
           hash(Buffer.from(pcm.buffer,pcm.byteOffset,pcm.byteLength))!==record.pcmSha256)throw Error('Native callback input contract mismatch');
        return structuredClone(record.notes);
      }});
    const read=async(first,count)=>{
      const p=plan[reads++];
      if(!p||first!==p.first||count!==p.last-p.first)throw Error('Native PCM window mismatch');
      const values=new Float32Array(count);
      for(let i=0;i<count;i++)values[i]=pcmBytes.readFloatLE((first+i)*4);
      return values;
    };
    const transcription=await adapter.process(read,total,{language});
    if(calls!==plan.length||reads!==plan.length)throw Error('Native replay did not consume every captured passage');
    for(const value of checkpoints.values())if(value.execution!=='native-game-v1')throw Error('Native checkpoint execution identity missing');
    const resumed=await adapter.process(async()=>{throw Error('Native resume unexpectedly read PCM');},total,{language});
    assert.deepEqual(resumed,transcription,'Native checkpoint resume changed the transcription');
    if(calls!==plan.length)throw Error('Native resume unexpectedly repeated inference');
    return {transcription,nativeCalls:calls,nativeCheckpointResumeIdentical:true};
  }finally{await adapter?.release();globalThis.fetch=savedFetch;}
}

async function compareProductionCaptures(inputFile,pcmFile=null){
  const directory=path.dirname(path.resolve(inputFile)),bytes=fs.readFileSync(inputFile),input=JSON.parse(bytes);
  if(input.schema!=='lightforge-game-production-process-input-1')throw Error('Unknown production capture schema');
  if(!Number.isSafeInteger(input.totalSamples)||input.totalSamples<1||input.totalSamples>600*44100)throw Error('Invalid complete source sample count');
  let pcm=null;
  if(pcmFile!==null){
    const size=fs.statSync(pcmFile).size;
    if(!size||size%4||size>600*44100*4)throw Error('Invalid complete PCM size');
    pcm=fs.readFileSync(pcmFile);
    if(pcm.length/4!==input.totalSamples||hash(pcm)!==input.inputPcmSha256)throw Error('Complete PCM binding mismatch');
  }
  const plan=planPassages(input.totalSamples,input.language),manifest=input.modelManifest;
  if(input.passages.length!==plan.length)throw Error('Incomplete production captures');
  if(manifest.id!=='game-large-1.0.3-lightforge-1'||manifest.steps!==8||manifest.sampleRate!==44100)throw Error('Unexpected GAME contract');
  const wasmRecords=[],nativeRecords=[],diagnostics=[];
  for(let i=0;i<plan.length;i++){
    const passage=input.passages[i];
    for(const field of ['index','first','last','seed'])if(passage[field]!==plan[i][field])throw Error('Production capture plan mismatch');
    if(pcm&&hash(pcm.subarray(passage.first*4,passage.last*4))!==passage.pcmSha256)throw Error('Passage PCM digest mismatch');
    const wasm=checkedReceipt(directory,passage.wasmReceipt,passage.wasmReceiptSha256);
    const native=checkedReceipt(directory,passage.nativeReceipt,passage.nativeReceiptSha256);
    for(const r of [wasm,native])if(r.samples!==passage.last-passage.first||r.seed!==passage.seed||r.language!==input.language||r.steps!==8)throw Error('Executed source clock/settings differ');
    if(wasm.schema!=='lightforge-game-benchmark-1'||wasm.sampleRate!==44100||wasm.pcmSHA256!==passage.pcmSha256||wasm.capture!==true)throw Error('WASM source binding mismatch');
    const expectedModels=Object.fromEntries(['encoder','dur2bd','segmenter','bd2dur','estimator'].map(name=>[name+'.onnx',manifest.files[name+'.onnx']]));
    assert.deepEqual(wasm.modelFiles,expectedModels,'WASM graph identity differs');
    wasmRecords.push({...plan[i],notes:wasm.notes});
    nativeRecords.push({...plan[i],pcmSha256:passage.pcmSha256,notes:native.notes});
    const sameCount=wasm.notes.length===native.notes.length;
    diagnostics.push({index:i,noteCounts:[wasm.notes.length,native.notes.length],
      unroundedNotesExactlyIdentical:isDeepStrictEqual(wasm.notes,native.notes),
      boundariesExactlyIdentical:sameCount&&wasm.notes.every((n,j)=>n.start===native.notes[j].start&&n.end===native.notes[j].end),
      maxAcceptedPitchDifferenceMidi:sameCount?Math.max(0,...wasm.notes.map((n,j)=>Math.abs(n.midi-native.notes[j].midi))):null,
      wasmUnroundedNotes:wasm.notes,nativeUnroundedNotes:native.notes});
  }
  const wasm=await processRecords(manifest,input.totalSamples,input.language,wasmRecords);
  let replay;
  if(pcm)replay=await processNativeRecords(manifest,pcm,input.language,nativeRecords);
  else{
    const transcription=await processRecords(manifest,input.totalSamples,input.language,nativeRecords,true);
    const resumed=await processRecords(manifest,input.totalSamples,input.language,nativeRecords,true);
    assert.deepEqual(resumed,transcription,'Native checkpoint restore changed the transcription');
    replay={transcription,nativeCalls:0,nativeCheckpointResumeIdentical:true};
  }
  const native=replay.transcription;
  if(native.runtime!=='onnxruntime-android-cpu')throw Error('Production native runtime identity missing');
  const {runtime,...payload}=native;
  return {schema:'lightforge-game-production-process-comparison-1',
    captureInputSha256:hash(bytes),productionAdapterSha256:hash(fs.readFileSync(path.join(root,'web/analysis/game.js'))),
    totalSamples:input.totalSamples,passageCount:plan.length,
    verificationMode:pcm?'fresh-pcm-native-callback-replay':'receipt-only-checkpoint-replay',
    freshNativeCallbackInputsRevalidated:!!pcm,
    productionTranscriptionIdentical:JSON.stringify(payload)===JSON.stringify(wasm),
    nativeCheckpointResumeIdentical:replay.nativeCheckpointResumeIdentical,
    nativeCalls:replay.nativeCalls,wasm,native,rawNoteDiagnostics:diagnostics,
    declaredRuntimeDifference:{wasm:'absent',native:runtime},
    rawNativeTensorCaptureAvailable:false,rawTensorParityAsserted:false,
    fullAnalysisQualityApproved:false,androidIntegrationApproved:false,
    scope:'Fresh production NativeGame notes versus fresh WASM captures; actual game.js nativeInfer/process/checkpoint resume. Excludes Android transport/service and downstream vocal fusion/show generation.'};
}

async function main() {
  if (process.argv[2] === '--plan' && process.argv.length === 5) {
    const total = Number(process.argv[3]), language = Number(process.argv[4]), passages = planPassages(total, language);
    // The real production adapter must accept every derived boundary; drift fails before inference.
    await processRecords({id:'game-large-1.0.3-lightforge-1',steps:8,sampleRate:44100}, total, language,
                         passages.map(p=>({...p,notes:[]})));
    console.log(JSON.stringify(passages));
    return;
  }
  if(process.argv[2]==='--production'&&process.argv.length===6){
    const result=await compareProductionCaptures(process.argv[3],process.argv[4]);
    fs.writeFileSync(process.argv[5],JSON.stringify(result,null,2)+'\n',{flag:'wx'});
    console.log(JSON.stringify({productionTranscriptionIdentical:result.productionTranscriptionIdentical,
                               nativeCheckpointResumeIdentical:result.nativeCheckpointResumeIdentical,
                               passageCount:result.passageCount,notes:[result.wasm.notes.length,result.native.notes.length]}));
    if(!result.productionTranscriptionIdentical)process.exitCode=2;
    return;
  }
  if(process.argv[2]==='--production-receipts'&&process.argv.length===5){
    const result=await compareProductionCaptures(process.argv[3]);
    fs.writeFileSync(process.argv[4],JSON.stringify(result,null,2)+'\n',{flag:'wx'});
    console.log(JSON.stringify({productionTranscriptionIdentical:result.productionTranscriptionIdentical,
                               nativeCheckpointResumeIdentical:result.nativeCheckpointResumeIdentical,
                               verificationMode:result.verificationMode}));
    if(!result.productionTranscriptionIdentical)process.exitCode=2;
    return;
  }
  if (process.argv.length !== 4) throw Error('capture-input.json output-comparison.json OR --plan total-samples language');
  const result = await compareCapturedProcess(process.argv[2]);
  fs.writeFileSync(process.argv[3], JSON.stringify(result,null,2)+'\n', {flag:'wx'});
  console.log(JSON.stringify({productionTranscriptionIdentical:result.productionTranscriptionIdentical,
                             passageCount:result.passageCount, notes:[result.wasm.notes.length,result.native.notes.length]}));
  if (!result.productionTranscriptionIdentical) process.exitCode = 2;
}

module.exports = {planPassages,processRecords,compareCapturedProcess,processNativeRecords,compareProductionCaptures};
if (require.main === module) main().catch(error=>{console.error(error);process.exitCode=1;});
