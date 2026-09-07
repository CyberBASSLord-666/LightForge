'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..');require(root+'/web/analysis/dsp.js');
const Deux=require(root+'/web/analysis/separator-deux.js');
const manifest=JSON.parse(fs.readFileSync(root+'/web/analysis/models/deux/manifest.json'));
const RATE=44100,SAMPLES=573300,HALO=66150,STRIDE=220500,CORE=441000;
global.fetch=async()=>({json:async()=>manifest});
const ort={InferenceSession:{create(){throw Error('Native analysis must never load a WASM model.');}}};
function source(total){return async(start,count)=>[0,1].map(channel=>{
 const out=new Float32Array(count);for(let i=Math.max(0,-start);i<Math.min(count,total-start);i++)out[i]=Math.sin((start+i)*.003)*(channel?.25:.5);return out;
});}
function fakeNative(total,calls){const read=source(total);return async start=>{calls.push(start);const channels=await read(start,SAMPLES);return{vocals:channels[0],accompaniment:channels[1]};};}

test('native passages retain source clock, reuse completed work and report durable progress',async()=>{
 const total=CORE+STRIDE+17,calls=[],records=new Map(),progress=[],output=[];
 const checkpoint={readFloats:async key=>records.get(key),writeFloats:async(key,arrays)=>records.set(key,arrays.map(a=>a.slice()))};
 let separator=await Deux.create({ort,baseUrl:'https://models.invalid/',checkpoint,nativePredict:fakeNative(total,calls)});
 const result=await separator.process(source(total),total,c=>output.push(c),p=>progress.push(p));await separator.release();
 assert.deepEqual(calls,[-HALO,STRIDE-HALO,2*STRIDE-HALO]);assert.equal(result.chunks,3);assert.equal(result.restoredPassages,0);assert.equal(result.runtime,'onnxruntime-android-cpu');
 assert.equal(output.reduce((n,c)=>n+c.vocals.length,0),total);let emitted=0;
 for(const chunk of output){assert.equal(chunk.startSample,emitted);emitted+=chunk.vocals.length;}
 assert.equal(progress.at(-1).passagesCompleted,3);assert.equal(progress.at(-1).passageCount,3);assert.equal(progress.at(-1).checkpointSaved,true);
 for(let i=1;i<progress.length;i++)assert.ok(progress[i].progress>=progress[i-1].progress,'progress must be monotonic');
 separator=await Deux.create({ort,baseUrl:'https://models.invalid/',checkpoint,nativePredict:()=>{throw Error('A restored passage ran twice.');}});
 let at=0;const restored=await separator.process(source(total),total,chunk=>{assert.deepEqual(chunk.vocals,output[at].vocals);assert.deepEqual(chunk.accompaniment,output[at++].accompaniment);});await separator.release();
 assert.equal(restored.restoredPassages,3);assert.equal(at,3);
});

test('a failed passage leaves prior checkpoints reusable without committing partial output',async()=>{
 const total=CORE+10,calls=[],records=new Map(),checkpoint={readFloats:async key=>records.get(key),writeFloats:async(key,arrays)=>records.set(key,arrays)};
 let emitted=0;
 const good=fakeNative(total,calls);let separator=await Deux.create({ort,baseUrl:'https://models.invalid/',checkpoint,nativePredict:async start=>{if(start>=0)throw Error('Android interrupted the passage');return good(start);}});
 await assert.rejects(separator.process(source(total),total,c=>emitted+=c.vocals.length),/interrupted/);await separator.release();
 assert.equal(emitted,STRIDE);assert.equal(records.size,1);
 const resumed=[];separator=await Deux.create({ort,baseUrl:'https://models.invalid/',checkpoint,nativePredict:fakeNative(total,resumed)});
 const result=await separator.process(source(total),total,()=>{});await separator.release();
 assert.deepEqual(resumed,[STRIDE-HALO]);assert.equal(result.restoredPassages,1);
});

test('malformed native or cached audio is never exported or accepted as completed',async()=>{
 const read=source(RATE),invalid=new Float32Array(SAMPLES);invalid[HALO]=NaN;let emitted=0;
 let separator=await Deux.create({ort,baseUrl:'https://models.invalid/',nativePredict:async()=>({vocals:invalid,accompaniment:new Float32Array(SAMPLES)})});
 await assert.rejects(separator.process(read,RATE,()=>emitted++),/invalid passage audio/);await separator.release();assert.equal(emitted,0);
 const calls=[];separator=await Deux.create({ort,baseUrl:'https://models.invalid/',checkpoint:{readFloats:async()=>[invalid,new Float32Array(SAMPLES)],writeFloats:async()=>{}},nativePredict:fakeNative(RATE,calls)});
 const result=await separator.process(read,RATE,()=>{});await separator.release();assert.deepEqual(calls,[-HALO]);assert.equal(result.restoredPassages,0);
});

test('checkpoint commit failure preserves retry semantics and does not emit its passage',async()=>{
 const calls=[];let emitted=0;const separator=await Deux.create({ort,baseUrl:'https://models.invalid/',checkpoint:{readFloats:async()=>null,writeFloats:async()=>{throw Error('Storage is full');}},nativePredict:fakeNative(RATE,calls)});
 await assert.rejects(separator.process(source(RATE),RATE,()=>emitted++),/Storage is full/);await separator.release();assert.equal(emitted,0);
});

test('silence and released separators never start expensive model inference',async()=>{
 const separator=await Deux.create({ort,baseUrl:'https://models.invalid/',nativePredict:()=>{throw Error('Silence started inference');}});
 const result=await separator.process(async()=>[new Float32Array(SAMPLES),new Float32Array(SAMPLES)],RATE,chunk=>assert.ok(chunk.vocals.every(x=>x===0)));
 assert.equal(result.chunks,1);await separator.release();await separator.release();
 await assert.rejects(separator.process(source(RATE),RATE,()=>{}),/closed/);
});
