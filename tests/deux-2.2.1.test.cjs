'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{createHash}=require('node:crypto');
const root=path.resolve(__dirname,'..');require(root+'/web/analysis/dsp.js');
const Deux=require(root+'/web/analysis/separator-deux.js');
const manifest=JSON.parse(fs.readFileSync(root+'/web/analysis/models/deux/manifest.json'));
const RATE=44100,SAMPLES=573300,HALO=66150,STRIDE=220500,CORE=441000;
global.fetch=async()=>({json:async()=>manifest});
const ort={InferenceSession:{create(){throw Error('Native analysis must never load a WASM model.');}}};
function source(total){const read=async(start,count)=>[0,1].map(channel=>{
 const out=new Float32Array(count);for(let i=Math.max(0,-start);i<Math.min(count,total-start);i++)out[i]=Math.sin((start+i)*.003)*(channel?.25:.5);return out;
});read.immutableSource=true;return read;}
function fakeNative(total,calls,budgets=[]){const read=source(total);return async(start,progress,remainingUseful)=>{calls.push(start);budgets.push(remainingUseful);const channels=await read(start,SAMPLES);return{vocals:channels[0],accompaniment:channels[1]};};}

test('native passages retain source clock, reuse completed work and report durable progress',async()=>{
 const total=CORE+STRIDE+17,calls=[],budgets=[],records=new Map(),progress=[],output=[];
 const checkpoint={readFloats:async key=>records.get(key),writeFloats:async(key,arrays)=>records.set(key,arrays.map(a=>a.slice()))};
 let separator=await Deux.create({ort,baseUrl:'https://models.invalid/',checkpoint,nativePredict:fakeNative(total,calls,budgets)});
 const result=await separator.process(source(total),total,c=>output.push(c),p=>progress.push(p));await separator.release();
 assert.deepEqual(calls,[-HALO,STRIDE-HALO,2*STRIDE-HALO]);assert.equal(result.chunks,3);assert.equal(result.restoredPassages,0);assert.equal(result.runtime,'onnxruntime-android-cpu');
 assert.deepEqual(budgets,[3,2,1]);
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
 const resumed=[],budgets=[];separator=await Deux.create({ort,baseUrl:'https://models.invalid/',checkpoint,nativePredict:fakeNative(total,resumed,budgets)});
 const result=await separator.process(source(total),total,()=>{});await separator.release();
 assert.deepEqual(resumed,[STRIDE-HALO]);assert.equal(result.restoredPassages,1);
 assert.deepEqual(budgets,[1],'Restored work cannot amortize calibration');
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

test('native budget excludes restored and silent future passages before the first inference',async()=>{
 const total=CORE+STRIDE*3+17,calls=[],budgets=[],records=new Map(),read=source(total),reads=[];
 records.set('deux-'+STRIDE*3,[new Float32Array(SAMPLES),new Float32Array(SAMPLES)]);
 const separator=await Deux.create({ort,baseUrl:'https://models.invalid/',checkpoint:{readFloats:async key=>records.get(key),writeFloats:async(key,value)=>records.set(key,value)},nativePredict:fakeNative(total,calls,budgets)});
 const readPassage=async(start,count)=>{reads.push(start);return start===STRIDE-HALO?[new Float32Array(count),new Float32Array(count)]:read(start,count);};readPassage.immutableSource=true;
 const result=await separator.process(readPassage,total,()=>{});
 await separator.release();
 assert.deepEqual(calls,[-HALO,STRIDE*2-HALO,STRIDE*4-HALO]);assert.deepEqual(budgets,[3,2,1]);assert.equal(result.restoredPassages,1);
 assert.equal(reads.filter(start=>start===STRIDE*3-HALO).length,0,'Verified restored audio needs no source read');
 for(const index of [0,1,2,4])assert.equal(reads.filter(start=>start===STRIDE*index-HALO).length,1,'Uncached audio is decoded and scanned once');
});

test('a checkpoint lost after calibration falls back to a fresh source read',async()=>{
 const total=CORE+1,read=source(total),reads=[],budgets=[],calls=[];
 const cached=[new Float32Array(SAMPLES),new Float32Array(SAMPLES)];let firstRead=true;
 const checkpoint={readFloats:async key=>{
  if(key==='deux-0'&&firstRead){firstRead=false;return cached;}
  return null;
 },writeFloats:async()=>{}};
 const separator=await Deux.create({ort,baseUrl:'https://models.invalid/',checkpoint,nativePredict:fakeNative(total,calls,budgets)});
 const readPassage=async(start,count)=>{reads.push(start);return read(start,count);};readPassage.immutableSource=true;
 const result=await separator.process(readPassage,total,()=>{});
 await separator.release();
 assert.equal(result.restoredPassages,0);
 assert.deepEqual(reads,[STRIDE-HALO,-HALO]);
 assert.deepEqual(calls,[-HALO,STRIDE-HALO]);
 assert.deepEqual(budgets,[2,1]);
});

test('a checkpoint completed after calibration takes precedence over planned inference',async()=>{
 const read=source(RATE),reads=[],cached=[new Float32Array(SAMPLES).fill(.25),new Float32Array(SAMPLES).fill(-.25)];let count=0;
 const checkpoint={readFloats:async()=>++count===1?null:cached,writeFloats:async()=>assert.fail('Restored passage was rewritten')};
 const separator=await Deux.create({ort,baseUrl:'https://models.invalid/',checkpoint,nativePredict:()=>assert.fail('Completed passage ran inference')});
 const readPassage=async(start,n)=>{reads.push(start);return read(start,n);};readPassage.immutableSource=true;
 const output=[];const result=await separator.process(readPassage,RATE,c=>output.push(c));
 await separator.release();
 assert.equal(result.restoredPassages,1);assert.deepEqual(reads,[-HALO]);
 assert.ok(output[0].vocals.every(x=>x===.25));assert.ok(output[0].accompaniment.every(x=>x===-.25));
});

test('restored WASM passage does not decode source or initialize model',async()=>{
 const cached=[new Float32Array(SAMPLES).fill(.125),new Float32Array(SAMPLES).fill(-.125)];
 const separator=await Deux.create({ort,baseUrl:'https://models.invalid/',checkpoint:{readFloats:async()=>cached}});
 const read=()=>assert.fail('Restored PCM was decoded');read.immutableSource=true;
 const output=[];const result=await separator.process(read,RATE,c=>output.push(c));
 await separator.release();
 assert.equal(result.restoredPassages,1);assert.equal(output[0].vocals[0],.125);
});

test('unmarked changing source is reread before treating a pre-scan silence as silent',async()=>{
 const silence=[new Float32Array(SAMPLES),new Float32Array(SAMPLES)],active=[new Float32Array(SAMPLES),new Float32Array(SAMPLES)];
 active[0][HALO]=.25;let reads=0,nativeCalls=0;
 const separator=await Deux.create({ort,baseUrl:'https://models.invalid/',nativePredict:async()=>{
  nativeCalls++;return {vocals:new Float32Array(SAMPLES).fill(.375),accompaniment:new Float32Array(SAMPLES).fill(-.125)};
 }});
 const output=[];await separator.process(async()=>++reads===1?silence:active,RATE,c=>output.push(c));
 await separator.release();
 assert.equal(reads,2);assert.equal(nativeCalls,1);assert.equal(output[0].vocals[0],.375);
});

test('unmarked restored work still checks that the source can be read',async()=>{
 const cached=[new Float32Array(SAMPLES),new Float32Array(SAMPLES)];
 const separator=await Deux.create({ort,baseUrl:'https://models.invalid/',checkpoint:{readFloats:async()=>cached}});
 await assert.rejects(separator.process(()=>{throw Error('Audio disappeared');},RATE,()=>{}),/Audio disappeared/);
 await separator.release();
});

test('mixed native, silent, and restored passages preserve exact emitted PCM',async()=>{
 const total=CORE+STRIDE*3+11,reads=[],calls=[],budgets=[],records=new Map();
 records.set('deux-'+STRIDE*3,[new Float32Array(SAMPLES).fill(.625),new Float32Array(SAMPLES).fill(-.375)]);
 const active=[new Float32Array(SAMPLES),new Float32Array(SAMPLES)],silence=[new Float32Array(SAMPLES),new Float32Array(SAMPLES)];
 active[0][HALO]=.25;
 const reader=async(start,count)=>{assert.equal(count,SAMPLES);reads.push(start);return start===STRIDE-HALO?silence:active;};
 reader.immutableSource=true;
 const native=async(start,progress,remainingUseful)=>{
  calls.push(start);budgets.push(remainingUseful);
  const index=(start+HALO)/STRIDE;
  return {vocals:new Float32Array(SAMPLES).fill(.125+index*.125),accompaniment:new Float32Array(SAMPLES).fill(-.25-index*.0625)};
 };
 const checkpoint={readFloats:async key=>records.get(key),writeFloats:async(key,arrays)=>records.set(key,arrays)};
 const separator=await Deux.create({ort,baseUrl:'https://models.invalid/',checkpoint,nativePredict:native});
 const hash=createHash('sha256');let samples=0;
 const result=await separator.process(reader,total,chunk=>{
  assert.equal(chunk.startSample,samples);samples+=chunk.vocals.length;
  for(const role of ['vocals','accompaniment'])hash.update(Buffer.from(chunk[role].buffer,chunk[role].byteOffset,chunk[role].byteLength));
 });
 await separator.release();
 assert.equal(samples,total);assert.equal(result.restoredPassages,1);
 assert.deepEqual(calls,[-HALO,STRIDE*2-HALO,STRIDE*4-HALO]);assert.deepEqual(budgets,[3,2,1]);
 assert.equal(reads.filter(start=>start===STRIDE*3-HALO).length,0);
 for(const index of [0,1,2,4])assert.equal(reads.filter(start=>start===STRIDE*index-HALO).length,1);
 assert.equal(hash.digest('hex'),'6d7552889938d2bc4537db54d0038ea84eab5cc46048b06159e2da18e2815bc2');
});

test('unavailable future budget remains unknown and does not discard successful passage work',async()=>{
 const calls=[],budgets=[],total=CORE+1,read=source(total);let failed=false;
 const separator=await Deux.create({ort,baseUrl:'https://models.invalid/',nativePredict:fakeNative(total,calls,budgets)});
 const result=await separator.process(async(start,count)=>{if(start>=0&&!failed){failed=true;throw Error('Temporary look-ahead read failure');}return read(start,count);},total,()=>{});
 await separator.release();assert.equal(result.chunks,2);assert.deepEqual(budgets,[-1,-1]);
});

test('budget scan preserves cancellation and stops before any native work',async()=>{
 for(const mode of ['abort','release']){
  let reads=0;const separator=await Deux.create({ort,baseUrl:'https://models.invalid/',nativePredict:()=>assert.fail('Cancelled scan entered inference')});
  await assert.rejects(separator.process(async()=>{reads++;if(mode==='release'){await separator.release();return [new Float32Array(SAMPLES),new Float32Array(SAMPLES)];}throw new DOMException('Cancelled','AbortError');},CORE+1,()=>assert.fail('Cancelled scan emitted audio')),mode==='abort'?{name:'AbortError'}:/closed/);
  assert.equal(reads,1);await separator.release();
 }
});
