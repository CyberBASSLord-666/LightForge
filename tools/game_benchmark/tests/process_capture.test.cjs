'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const crypto=require('node:crypto'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {planPassages,processRecords,processNativeRecords,compareProductionCaptures} = require('../process_capture.cjs');
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const model = {id:'game-large-1.0.3-lightforge-1',steps:8,sampleRate:44100};

test('full 64-second plan retains 14/16-second windows and final tail', async()=>{
  const total = 64 * 44100, plan = planPassages(total);
  assert.deepEqual(plan.map(p=>[p.first/44100,p.last/44100]), [[0,14],[10,26],[22,38],[34,50],[46,62],[58,64]]);
  assert.deepEqual(plan.map(p=>p.seed), [2025,106754,211483,316212,420941,525670]);
  const result = await processRecords(model,total,0,plan.map(p=>({...p,notes:[]})));
  assert.deepEqual(result.notes,[]);
});

test('actual production stitching merges carried sustain but keeps within-core attacks', async()=>{
  const total=24*44100, plan=planPassages(total);
  const records=plan.map(p=>({...p,notes:[]}));
  records[0].notes=[{start:11,end:13,midi:60.001}];
  records[1].notes=[{start:1,end:3,midi:60.002},{start:3,end:4,midi:60.002}];
  const result=await processRecords(model,total,0,records);
  assert.deepEqual(result.notes.map(n=>[n.start,n.end,n.midi,n.continuation]), [[11,13,60,false],[13,14,60,false]]);
});

test('single full vocal excerpt uses production note precision without changing raw inputs', async()=>{
  const plan=planPassages(300032), notes=[{start:0.1004,end:0.5998,midi:60.123456}];
  const result=await processRecords(model,300032,0,[{...plan[0],notes}]);
  assert.deepEqual(result.notes.map(n=>[n.start,n.end,n.midi]), [[0.1,0.6,60.12]]);
  assert.equal(notes[0].midi,60.123456);
});

test('missing passage, altered boundaries and wrong seed fail before replay', async()=>{
  const total=24*44100, records=planPassages(total).map(p=>({...p,notes:[]}));
  await assert.rejects(processRecords(model,total,0,records.slice(0,1)),/Incomplete/);
  for(const field of ['first','last','seed']){
    const changed=structuredClone(records);changed[1][field]++;
    await assert.rejects(processRecords(model,total,0,changed),/contract mismatch/);
  }
});

test('production rejects invalid raw notes rather than silently rewriting them', async()=>{
  const plan=planPassages(300032), record={...plan[0],notes:[{start:0,end:99,midi:60}]};
  await assert.rejects(processRecords(model,300032,0,[record]),/rejected/);
});

test('actual optional-native path validates PCM/seed and resumes without reinference', async()=>{
  const total=2*44100,pcm=Buffer.alloc(total*4);
  for(let i=0;i<total;i++)pcm.writeFloatLE(.125,i*4);
  const record={...planPassages(total)[0],pcmSha256:hash(pcm),notes:[{start:.1,end:.8,midi:60.123456}]};
  const replay=await processNativeRecords(model,pcm,0,[record]);
  assert.equal(replay.nativeCalls,1);assert.equal(replay.nativeCheckpointResumeIdentical,true);
  assert.equal(replay.transcription.runtime,'onnxruntime-android-cpu');
  assert.deepEqual(replay.transcription.notes.map(n=>[n.start,n.end,n.midi]),[[.1,.8,60.12]]);
  await assert.rejects(processNativeRecords(model,pcm,0,[{...record,pcmSha256:'a'.repeat(64)}]));
});

test('receipt-only replay derives payload but explicitly does not reobserve PCM', async()=>{
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'game-production-receipts-'));
  try{
    const total=2*44100,plan=planPassages(total),pcm=Buffer.alloc(total*4);
    for(let i=0;i<total;i++)pcm.writeFloatLE(.125,i*4);
    const files=Object.fromEntries(['encoder','dur2bd','segmenter','bd2dur','estimator'].map(n=>[n+'.onnx',{bytes:1,sha256:'b'.repeat(64)}]));
    const settings={samples:total,seed:2025,language:0,steps:8,notes:[{start:.1,end:.8,midi:60.123456}]};
    const native=JSON.stringify(settings),wasm=JSON.stringify({...settings,notes:[{start:.1,end:.8,midi:60.123455}],
      schema:'lightforge-game-benchmark-1',sampleRate:44100,pcmSHA256:hash(pcm),capture:true,modelFiles:files});
    fs.writeFileSync(path.join(directory,'native.json'),native);fs.writeFileSync(path.join(directory,'wasm.json'),wasm);
    const input={schema:'lightforge-game-production-process-input-1',modelManifest:{...model,files},
      totalSamples:total,language:0,inputPcmSha256:hash(pcm),passages:[{...plan[0],pcmSha256:hash(pcm),
        wasmReceipt:'wasm.json',wasmReceiptSha256:hash(wasm),nativeReceipt:'native.json',nativeReceiptSha256:hash(native)}]};
    const inputPath=path.join(directory,'input.json');fs.writeFileSync(inputPath,JSON.stringify(input));
    const result=await compareProductionCaptures(inputPath);
    assert.equal(result.productionTranscriptionIdentical,true);assert.equal(result.nativeCheckpointResumeIdentical,true);
    assert.equal(result.verificationMode,'receipt-only-checkpoint-replay');
    assert.equal(result.freshNativeCallbackInputsRevalidated,false);assert.equal(result.nativeCalls,0);
    assert.equal(result.rawNativeTensorCaptureAvailable,false);assert.equal(result.rawTensorParityAsserted,false);
    assert.equal(result.rawNoteDiagnostics[0].unroundedNotesExactlyIdentical,false);
    const reordered=JSON.stringify({...settings,notes:[{end:.8,midi:60.123455,start:.1}]});
    fs.writeFileSync(path.join(directory,'native.json'),reordered);
    input.passages[0].nativeReceiptSha256=hash(reordered);fs.writeFileSync(inputPath,JSON.stringify(input));
    assert.equal((await compareProductionCaptures(inputPath)).rawNoteDiagnostics[0].unroundedNotesExactlyIdentical,true,
                 'raw numeric note identity does not depend on JSON object key order');
    fs.writeFileSync(path.join(directory,'native.json'),native+' ');
    await assert.rejects(compareProductionCaptures(inputPath),/digest mismatch/);
  }finally{fs.rmSync(directory,{recursive:true,force:true});}
});
