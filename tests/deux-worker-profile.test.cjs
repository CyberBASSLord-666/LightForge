'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'..'),worker=fs.readFileSync(root+'/web/analysis/worker.js','utf8');

async function run(options={}){
 const messages=[],spans=[],profile={begin:name=>({name}),end:()=>{},increment:()=>{},cache:()=>{},snapshot:extra=>({schema:1,...extra})};
 let receivedOptions,released=0;
 const context=vm.createContext({console,URL,Float32Array,ArrayBuffer,DataView,Map,Number,setTimeout,performance,navigator:{hardwareConcurrency:2},importScripts(){},ort:{env:{wasm:{}}},LightForgeAnalysisTelemetry:{create:()=>({begin:name=>({name}),end:(token,attributes)=>spans.push({name:token?.name,attributes}),cache:()=>{},snapshot:extra=>({schema:1,...extra})})},LightForgeAnalysisStore:{open:async()=>({read:async()=>null,write:async()=>{},invalidate:async()=>{},reserve:async()=>{}})},LightForgeStemCache:{prune:async()=>{},create:async()=>({append:async()=>{},finish:async()=>({key:'stems'}),abort:async()=>{}})},LightForgeWavReader:class{constructor(){this.samples=44100;this.duration=1;}async open(){}async stereo44100(){return [new Float32Array(573300),new Float32Array(573300)];}},LightForgeMdxSeparator:{constants:{INPUT_LENGTH:1,CORE:1,STRIDE:1}},LightForgeDeux:{createPerformanceProfile:()=>profile,create:async value=>{receivedOptions=value;return {process:async(read,total,onChunk,onProgress)=>{await onChunk({sampleRate:44100,startSample:0,vocals:new Float32Array(total),accompaniment:new Float32Array(total)});onProgress({progress:1,processedSeconds:1,message:'Done',passagesCompleted:1,passageCount:1,checkpointSaved:true});return {chunks:1,restoredPassages:0,preprocessing:{spectrumReuse:{enabled:value.reuseSpectrum===true}}};},release:async()=>{released++;}};}},fetch:async url=>String(url).endsWith('features.json')?{json:async()=>({})}:{json:async()=>({precision:{},balanced:{},frontend:{}})},postMessage:message=>messages.push(message)});
 context.self=context;context.location={href:'https://app.test/analysis/worker.js'};vm.runInContext(worker,context);
 await context.onmessage({data:{stage:'separation',audioUrl:'/song.wav',value:{duration:1},options:{workId:'work',cacheKey:'cache',analysisQuality:'precision',...options}}});
 return {messages,spans,profile,receivedOptions,released};
}

test('worker records Deux subprofile and keeps experimental overlap reuse disabled by default',async()=>{
 const result=await run();
 assert.equal(result.receivedOptions.profile,result.profile);
 assert.equal(result.receivedOptions.reuseSpectrum,false);
 assert.equal(result.released,1);
 assert.ok(result.spans.some(span=>span.name==='separation.deux'&&span.attributes.outcome==='success'&&span.attributes.spectrumReuse===false));
 assert.equal(result.messages.at(-1).type,'result');
});

test('worker forwards the explicit experimental flag without changing model/runtime selection',async()=>{
 const result=await run({experimentalDeuxSpectrumReuse:true});
 assert.equal(result.receivedOptions.reuseSpectrum,true);
 assert.equal(result.receivedOptions.nativePredict,undefined);
 assert.equal(result.messages.at(-1).value.separation.preprocessing.spectrumReuse.enabled,true);
});
