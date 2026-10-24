'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const {pcm16000:reference}=require('./fixtures/performance/vocal-resampler-de831259.cjs');
const {pcm16000,VocalResampler,analyze}=require('../web/analysis/vocal.js');
function identical(a,b){assert.equal(a.length,b.length);assert.deepEqual(new Uint32Array(a.buffer,a.byteOffset,a.length),new Uint32Array(b.buffer,b.byteOffset,b.length));}
function signal(n){let seed=173;return Float32Array.from({length:n},(_,i)=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return i%19007===0?1:((seed>>>8)/2**24-.5)*.1;});}
function readerFor(source){return {duration:source.length/22050,reads:0,async mono22050(start,count){this.reads++;const raw=new Float32Array(count);for(let i=0;i<count;i++)if(start+i>=0&&start+i<source.length)raw[i]=source[start+i];return raw;}};}
test('all output bits match frozen resampling across normal, repeated, reversed and irregular padded windows',async()=>{
 const reader=readerFor(signal(427177)),cache=new VocalResampler();let reused=0;
 for(const start of [0,96000,147840,147840,96000,96001,1,-39,320000,0]){
  identical(await pcm16000(reader,start,160000,{},null,cache),await reference(reader,start,160000,{}));
  reused+=cache.reusedSamples;assert.equal(cache.reusedSamples+cache.computedSamples,160000);
  assert.ok(cache.retainedBytes<=1522264);
 }
 assert.ok(reused>300000);assert.equal(reader.reads,20);cache.clear();assert.equal(cache.previous,null);assert.equal(cache.retainedBytes,0);
});
test('every rational phase and varying counts retain exact output',async()=>{
 const reader=readerFor(signal(10000)),cache=new VocalResampler();
 for(let start=0;start<320;start++)identical(await pcm16000(reader,start,600,{},null,cache),await reference(reader,start,600,{}));
 for(const count of [0,1,2,63,65,160001]){identical(await pcm16000(reader,1,count,{},null,cache),await reference(reader,1,count,{}));if(count===0||count>160000)assert.equal(cache.previous,null);}
});
test('source mutation, signed zero, impulse and non-finite input are checked by Float32 bits',async()=>{
 for(const value of [1,-0,NaN,Infinity,-Infinity]){
  const source=new Float32Array(24000),reader=readerFor(source),cache=new VocalResampler();
  await pcm16000(reader,0,16000,{},null,cache);source[10000]=value;
  identical(await pcm16000(reader,100,16000,{},null,cache),await reference(reader,100,16000,{}));
  assert.equal(cache.reusedSamples,0);
 }
});
test('source and returned output mutations cannot alter saved snapshots; subviews are supported',async()=>{
 const source=signal(24000),reader=readerFor(source),cache=new VocalResampler();let raw;
 const original=reader.mono22050.bind(reader);reader.mono22050=async(...args)=>{const samples=await original(...args),buffer=new Float32Array(samples.length+10);buffer.set(samples,5);raw=buffer.subarray(5,5+samples.length);return raw;};
 const out=await pcm16000(reader,0,16000,{},null,cache);out.fill(999);raw.fill(0);
 identical(await pcm16000(reader,100,16000,{},null,cache),await reference(reader,100,16000,{}));assert.equal(cache.reusedSamples,15900);
});
test('non-Float32 and truncated input fall back without unsafe reuse',async()=>{
 for(const kind of ['array','float64','short']){
  const source=signal(24000),reader=readerFor(source),original=reader.mono22050.bind(reader),cache=new VocalResampler();
  reader.mono22050=async(...args)=>{const a=await original(...args);return kind==='array'?Array.from(a):kind==='float64'?Float64Array.from(a):a.subarray(0,100);};
  await pcm16000(reader,0,16000,{},null,cache);
  identical(await pcm16000(reader,100,16000,{},null,cache),await reference(reader,100,16000,{}));assert.equal(cache.reusedSamples,0);
 }
});
test('reader failure and cancellation clear source/output retention',async()=>{
 const reader=readerFor(signal(24000)),cache=new VocalResampler();await pcm16000(reader,0,16000,{},null,cache);
 reader.mono22050=async()=>{throw new Error('cancelled');};
 await assert.rejects(pcm16000(reader,100,16000,{},null,cache),/cancelled/);assert.equal(cache.previous,null);assert.equal(cache.retainedBytes,0);
});
test('analysis clears its own cache on success, model failure and cancellation',async()=>{
 const frontend=JSON.parse(fs.readFileSync(require.resolve('../web/analysis/models/vocal-frontend.json'))),oldLocation=global.location,oldExtract=VocalResampler.prototype.extract;global.location={href:'https://lightforge.invalid/analysis/'};
 let cache;VocalResampler.prototype.extract=function(...args){cache=this;return oldExtract.apply(this,args);};
 try{
  for(const mode of ['success','model failure','cancelled']){
   const reader=readerFor(signal(270000)),counters={};let runs=0;
   const runtime={Tensor:class{constructor(type,data){this.data=data;}dispose(){}},InferenceSession:{async create(){return {async run(){runs++;if(mode==='model failure')throw new Error(mode);return {scores:{data:new Float32Array(500),dispose(){}}};},async release(){}};}}};
   const options={ort:runtime,frontend,model:{file:'test.onnx',singingClassIds:[0],speechClassIds:[1]},telemetry:{increment(name,value){counters[name]=(counters[name]||0)+value;}},report(p){if(mode==='cancelled'&&p>0)throw new Error(mode);}};
   if(mode==='success'){await analyze(reader,{},options);assert.ok(counters['vocal.resampler.reusedSamples']>0);}else await assert.rejects(analyze(reader,{},options),new RegExp(mode));
   assert.ok(runs>0);assert.equal(cache.previous,null);assert.equal(cache.retainedBytes,0);
  }
 }finally{global.location=oldLocation;VocalResampler.prototype.extract=oldExtract;}
});
