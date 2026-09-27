'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const {logMel:reference}=require('./fixtures/performance/vocal-frontend-2.3.2.cjs');
const {logMel,MelFrontend,analyze,pcm16000,chunkStarts}=require('../web/analysis/vocal.js');
const frontend=JSON.parse(fs.readFileSync(require.resolve('../web/analysis/models/vocal-frontend.json')));
function signal(length){const pcm=new Float32Array(length);let seed=77321;for(let i=0;i<length;i++){seed=(Math.imul(seed,1664525)+1013904223)>>>0;pcm[i]=((seed>>>8)/2**24-.5)*.08+Math.sin(i*.043)*.23;}return pcm;}
function identical(actual,expected){assert.equal(actual.length,expected.length);assert.ok(Buffer.from(actual.buffer,actual.byteOffset,actual.byteLength).equals(Buffer.from(expected.buffer,expected.byteOffset,expected.byteLength)),'Float32 model inputs must be byte-identical');}
test('cached twiddles preserve every Float32 value of the released frontend',()=>{
 for(const length of [1,2,159,160,319,16000,160000]){const pcm=signal(length);identical(logMel(pcm,frontend),reference(pcm,frontend));}
 for(const pcm of [new Float32Array(1600),Float32Array.from({length:1600},(_,i)=>i%2?-0:0)])identical(logMel(pcm,frontend),reference(pcm,frontend));
});
test('overlap reuse excludes reflected edges and preserves irregular final-window inputs',()=>{
 const pcm=signal(350000),mel=new MelFrontend(frontend),starts=[0,96000,147840];let reused=0;
 for(const start of starts){const input=pcm.slice(start,start+160000);identical(mel.extract(input,start),reference(input,frontend));reused+=mel.reusedFrames;assert.equal(mel.computedFrames+mel.reusedFrames,1000);}
 assert.ok(reused>1000);assert.ok(mel.reusedFrames<1000);assert.equal(mel.previous.pcm.length,160000);
});
test('changed overlapping PCM and nonaligned coordinates invalidate reuse',()=>{
 const pcm=signal(270000),mel=new MelFrontend(frontend);mel.extract(pcm.slice(0,160000),0);
 const changed=pcm.slice(96000,256000);changed[1000]+=.0001;identical(mel.extract(changed,96000),reference(changed,frontend));assert.equal(mel.reusedFrames,0);
 const shifted=pcm.slice(96001,256001);identical(mel.extract(shifted,96001),reference(shifted,frontend));assert.equal(mel.reusedFrames,0);
 mel.clear();identical(mel.extract(shifted,96001),reference(shifted,frontend));assert.equal(mel.reusedFrames,0);
});
test('cache owns snapshots and remains bounded to one ten-second passage',()=>{
 const pcm=signal(260000),mel=new MelFrontend(frontend),input=pcm.slice(0,160000),features=mel.extract(input,0);
 input.fill(0);features.fill(999);const next=pcm.slice(96000,256000);identical(mel.extract(next,96000),reference(next,frontend));assert.equal(mel.reusedFrames,397);
 const large=pcm.slice(0,160160);identical(mel.extract(large,0),reference(large,frontend));assert.equal(mel.previous,null);
});
test('other PCM representations use the original frontend without partial buffer keys',()=>{
 const mel=new MelFrontend(frontend),first=Float64Array.from(signal(1600));mel.extract(first,0);
 const changed=first.slice();changed[1100]+=.5;identical(mel.extract(changed,0),reference(changed,frontend));assert.equal(mel.reusedFrames,0);assert.equal(mel.previous,null);
 const array=Array.from(changed);identical(mel.extract(array,0),reference(array,frontend));assert.equal(mel.reusedFrames,0);
});
test('production analysis delivers unchanged model inputs for every original window',async()=>{
 const priorLocation=global.location;global.location={href:'https://lightforge.invalid/analysis/'};
 const duration=19.373,source=signal(Math.ceil(duration*22050)),reader={duration,async mono22050(start,count){return Float32Array.from({length:count},(_,i)=>source[start+i]||0);}},starts=chunkStarts(duration),inputs=[],counters={};let releases=0;
 const runtime={Tensor:class{constructor(type,data,dims){this.data=data;this.dims=dims;}dispose(){}},InferenceSession:{async create(){return {async run({log_mel}){inputs.push(log_mel.data.slice());return {scores:{data:new Float32Array(500).fill(.3),dispose(){}}};},async release(){releases++;}};}}};
 try{await analyze(reader,{}, {ort:runtime,frontend,model:{file:'test.onnx',id:'test',name:'test',singingClassIds:[0],speechClassIds:[1]},telemetry:{increment(name,value){counters[name]=(counters[name]||0)+value;}}});
  assert.equal(inputs.length,starts.length);assert.equal(releases,1);
  for(let i=0;i<starts.length;i++){const pcm=await pcm16000(reader,starts[i]*640,160000,{});identical(inputs[i],reference(pcm,frontend));}
  assert.ok(counters['vocal.frontend.reusedFrames']>0);assert.equal(counters['vocal.frontend.reusedFrames']+counters['vocal.frontend.computedFrames'],starts.length*1000);
 }finally{global.location=priorLocation;}
});
