'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const source=fs.readFileSync(process.env.LIGHTFORGE_MDX_SOURCE||path.join(__dirname,'..','web/analysis/separator-mdx.js'),'utf8');
const manifest={id:'mdx',sha256:'a'.repeat(64),sampleRate:44100,nFFT:7680,file:'mdx.onnx',compensate:1};

async function separator(nativePredict){
 const stats={wasm:0,writes:0,chunks:0};
 const context=vm.createContext({URL,Float32Array,Float64Array,Number,Math,Promise,setTimeout,clearTimeout,console,LightForgeDSP:{FFT:class{run(){}}},ort:{InferenceSession:{create:async()=>{stats.wasm++;throw Error('WASM fallback must be an outer retry');}},Tensor:class{}},fetch:async()=>({json:async()=>manifest})});context.self=context;
 vm.runInContext(source,context);
 const api=await context.LightForgeMdxSeparator.create({ort:context.ort,manifest,nativePredict,checkpoint:{readFloats:async()=>null,writeFloats:async()=>{stats.writes++;}}});
 const C=context.LightForgeMdxSeparator.constants,pcm=new Float32Array(C.INPUT_LENGTH).fill(.1);
 return {stats,async run(){try{return await api.process(async()=>[pcm,pcm],C.CORE,async()=>{stats.chunks++;},()=>{});}finally{await api.release();}}};
}

test('native MDX first-pass failure fences the whole passage before a WASM call or checkpoint',async()=>{
 const h=await separator(async()=>{throw Error('native gone');});await assert.rejects(h.run(),error=>error.code==='native-mdx-fallback');assert.deepEqual(h.stats,{wasm:0,writes:0,chunks:0});
});

test('native MDX reverse-pass failure also fences the whole passage before a WASM call or checkpoint',async()=>{
 let calls=0;const first=new Float32Array(4*3072*256),h=await separator(async()=>{calls++;if(calls===1)return first;throw Error('native gone during reverse pass');});
 await assert.rejects(h.run(),error=>error.code==='native-mdx-fallback');assert.equal(calls,2);assert.deepEqual(h.stats,{wasm:0,writes:0,chunks:0});
});
