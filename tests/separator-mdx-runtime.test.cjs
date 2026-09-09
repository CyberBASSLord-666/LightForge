'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
require('../web/analysis/dsp.js');
const M=require('../web/analysis/separator-mdx.js');
const {INPUT_LENGTH,CORE}=M.constants;
const manifest={id:'mdx-test',sampleRate:44100,nFFT:7680,file:'uvr-mdx-voc-ft.onnx',sha256:'a'.repeat(64),compensate:1};
const source=(total)=>async(start,count)=>[0,1].map(channel=>{const value=new Float32Array(count);for(let i=Math.max(0,-start);i<Math.min(count,total-start);i++)value[i]=channel?.2:.1;return value;});
test('balanced separator can use native MDX without creating a WASM session',async()=>{
 const previousFetch=global.fetch;global.fetch=async()=>({json:async()=>manifest});let nativeCalls=0,wasmSessions=0;
 const ort={InferenceSession:{create:async()=>{wasmSessions++;throw Error('WASM should not be used when native output is valid.');}}};
 const native=async(encoded,onProgress)=>{assert.equal(encoded.length,4*3072*256);nativeCalls++;onProgress({progress:.75,message:'Native MDX'});return new Float32Array(encoded.length);};
 try{const separator=await M.create({ort,baseUrl:'https://models.invalid/',nativePredict:native}),total=44100*7,output=[];const result=await separator.process(source(total),total,chunk=>output.push(chunk));await separator.release();assert.equal(wasmSessions,0);assert.equal(result.runtime,'onnxruntime-android-cpu');assert.equal(result.nativeModelPasses,nativeCalls);assert.equal(result.wasmModelPasses,0);assert.equal(nativeCalls,result.modelPasses);assert.equal(result.modelPasses,2*(1+Math.ceil(Math.max(0,total-CORE)/M.constants.STRIDE)));assert.equal(output.reduce((sum,chunk)=>sum+chunk.vocals.length,0),total);assert.ok(output.every(chunk=>chunk.vocals.every(Number.isFinite)));}finally{global.fetch=previousFetch;}
});
test('balanced separator falls back to WASM as a complete polarity pair',async()=>{
 const previousFetch=global.fetch;global.fetch=async()=>({json:async()=>manifest});let nativeCalls=0,wasmRuns=0,sessionReleases=0;
 class Tensor{constructor(type,data,dims){this.type=type;this.data=data;this.dims=dims;}dispose(){}}
 const ort={Tensor,InferenceSession:{create:async()=>{wasmSessions++;return{inputNames:['input'],outputNames:['output'],run:async()=>{wasmRuns++;return{output:{data:new Float32Array(4*3072*256),dispose(){}}};},release:async()=>{sessionReleases++;}}}}};let wasmSessions=0;
 const native=async()=>{nativeCalls++;return undefined;};
 try{const separator=await M.create({ort,baseUrl:'https://models.invalid/',nativePredict:native}),total=44100*7,result=await separator.process(source(total),total,()=>{});await separator.release();const chunks=1+Math.ceil(Math.max(0,total-CORE)/M.constants.STRIDE);assert.equal(nativeCalls,chunks);assert.equal(result.runtime,'onnxruntime-web-wasm');assert.equal(result.nativeModelPasses,0);assert.equal(result.wasmModelPasses,wasmRuns);assert.equal(wasmRuns,result.modelPasses);assert.equal(result.modelPasses,2*chunks);assert.equal(wasmSessions,chunks);assert.equal(sessionReleases,wasmSessions);}finally{global.fetch=previousFetch;}
});
