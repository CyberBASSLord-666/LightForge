'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const ROOT=path.resolve(__dirname,'..');
function context(file,extra={}){const c=vm.createContext({performance:{now:()=>1},Date,Float32Array,Float64Array,Uint8Array,Uint32Array,ArrayBuffer,DataView,Map,Set,Promise,Error,Number,Object,Math,importScripts(){},...extra});c.self=c;vm.runInContext(fs.readFileSync(path.join(ROOT,'web/analysis',file),'utf8'),c);return c;}
function timer(){const active=[],events=[];return {active,events,measure(name,fn){assert.equal(active.length,0);active.push(name);try{return fn();}finally{assert.equal(active.pop(),name);events.push(name);}},outside(){assert.equal(active.length,0);}};}
test('partial telemetry modules use non-disruptive wrappers for all new worker calls',async()=>{
 const c=context('worker.js',{LightForgeAnalysisTelemetry:{create:()=>({begin(){},end(){},cache(){},snapshot(){return {old:true};}})}});
 const recorder=c.createTelemetry('rhythm',{});let calls=0;
 assert.equal(recorder.measure('test',()=>++calls),1);assert.equal(await recorder.measureAsync('test',async()=>++calls),2);assert.equal(recorder.snapshot(),null);
});
test('stem resampling and serialization preserve sample bytes and exclude writes',async()=>{
 const c=context('stem-cache.js'),telemetry=timer(),writes=[];
 const stream={async write(value){telemetry.outside();writes.push(Uint8Array.from(value));},async close(){telemetry.outside();}};
 const filter=new Float64Array(63);filter[31]=1;const pcm=Float32Array.from({length:100},(_,i)=>i/100);
 const writer=new c.LightForgeStemCache.DownsampleWriter(stream,filter,pcm.length,undefined,telemetry);
 await writer.push(pcm.subarray(0,40),0);await writer.push(pcm.subarray(40),40);await writer.finish();
 const bytes=Buffer.concat(writes.map(value=>Buffer.from(value))),view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
 assert.equal(bytes.length,50*4);for(let i=0;i<50;i++)assert.equal(view.getFloat32(i*4,true),pcm[i*2]);
 assert.equal(telemetry.events.filter(x=>x==='performance.resample_normalize').length,3);
 assert.equal(telemetry.events.filter(x=>x==='performance.postprocessing').length,3);
});
test('empty stem writes do not manufacture executed resampling intervals',async()=>{
 const c=context('stem-cache.js'),telemetry=timer();const stream={write:async()=>{},close:async()=>{}};
 const down=new c.LightForgeStemCache.DownsampleWriter(stream,new Float64Array(63),0,undefined,telemetry);
 await down.finish();const full=new c.LightForgeStemCache.FloatWriter(stream,undefined,telemetry);await full.push(new Float32Array(0));
 assert.deepEqual(telemetry.events,[]);
});
test('full-rate PCM serialization retains exact values across the reusable buffer boundary',async()=>{
 const c=context('stem-cache.js'),telemetry=timer(),writes=[];
 const stream={async write(value){telemetry.outside();writes.push(Uint8Array.from(value));}};
 const pcm=Float32Array.from({length:17000},(_,i)=>Math.sin(i*.1));const writer=new c.LightForgeStemCache.FloatWriter(stream,undefined,telemetry);await writer.push(pcm);
 const bytes=Buffer.concat(writes.map(value=>Buffer.from(value)));for(let i=0;i<pcm.length;i++)assert.equal(bytes.readFloatLE(i*4),pcm[i]);
 assert.equal(telemetry.events.length,2);
});
test('rhythm frontend observes inference separately from input reflection and output trim',async()=>{
 let disposed=0;class Tensor{constructor(type,data,dims){Object.assign(this,{type,data,dims});}dispose(){disposed++;}}
 const c=context('worker.js',{ort:{Tensor}}),events=[],active=[];
 const telemetry={measure(name,fn){active.push(name);try{return fn();}finally{active.pop();events.push(name);}},async measureAsync(name,fn){active.push(name);try{return await fn();}finally{active.pop();events.push(name);}}};
 const reader={duration:1,async mono22050(_start,count){assert.equal(active.length,0);return new Float32Array(count).fill(.25);}};
 const session={async run({audio_pcm}){assert.deepEqual(active,['performance.feature_generation','performance.model_inference']);assert.equal(audio_pcm.dims[1],1765);return {mel_spectrogram:{data:Float32Array.from({length:640},(_,i)=>i),dispose(){disposed++;}}};}};
 const result=await c.melForFrames(reader,session,0,1,{},telemetry);
 assert.deepEqual(Array.from(result),Array.from({length:128},(_,i)=>i+256));assert.equal(disposed,2);
 assert.deepEqual(events,['performance.preprocessing','performance.model_inference','performance.feature_generation','performance.postprocessing']);
});
