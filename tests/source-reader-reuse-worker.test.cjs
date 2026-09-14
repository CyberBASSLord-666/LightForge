'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const workerSource=fs.readFileSync(path.join(__dirname,'..','web','analysis','worker.js'),'utf8');

const sourceClock={samples:132300,duration:3};
function stemCache(){return {version:2,key:'stem-12345678-1234-1234-1234-123456789abc',samples:66150,fullSamples:sourceClock.samples,duration:sourceClock.duration};}
function baseValue(){return {duration:2.99,bpm:120,sections:[],warnings:[],stemCache:stemCache(),separation:{limitations:[],nativeModelPasses:0,runtime:'onnxruntime-web-wasm'},vocals:{warnings:[],model:{id:'classifier'},transcription:{model:'game-large'}}};}

async function run(stage,value){
 const state={readerConstructions:0,detailDurations:[],gameSamples:[],writes:[],order:[]},messages=[];
 class ForbiddenOriginalReader{
  constructor(){state.readerConstructions++;throw Error('unexpected original WAV reader in '+stage);}
 }
 const stems={
  vocals:{mono22050:async(start,count)=>new Float32Array(count)},
  accompaniment:{mono22050:async(start,count)=>new Float32Array(count)}
 };
 class DetailExtractor{
  constructor(options){state.detailDurations.push(options.duration);state.order.push('detail');}
  push(){}
  finish(){return {detail:true};}
 }
 const context={
  URL,
  performance:{now:()=>0},
  navigator:{hardwareConcurrency:1},
  location:{href:'https://worker.invalid/worker.js'},
  importScripts:()=>{},
  postMessage:message=>messages.push(message),
  fetch:async url=>({json:async()=>String(url).endsWith('features.json')?{resampleHalfFIR:new Float32Array(63)}:{precision:{file:'beat.onnx',model:'Beat',id:'beat',sha256:'a'},balanced:{file:'beat-small.onnx',model:'Beat small',id:'beat-small',sha256:'b'},frontend:{file:'frontend.onnx',sha256:'c'}}}),
  ort:{env:{wasm:{}},InferenceSession:{create:async()=>{throw Error('unexpected rhythm inference');}}},
  LightForgeWavReader:ForbiddenOriginalReader,
  LightForgeAnalysisStore:{open:async()=>({read:async()=>null,write:async(name,record)=>{state.writes.push({name,record});},invalidate:async()=>{}})},
  LightForgeStemCache:{
   readers:async()=>stems,
   fullVoice:async meta=>{state.order.push('fullVoice');if(!Number.isSafeInteger(meta.fullSamples)||!Number.isFinite(meta.duration)||Math.abs(meta.fullSamples/44100-meta.duration)>1/44100)throw Error('Re-analyze to recover full-resolution voice audio.');return async(start,count)=>new Float32Array(count);}
  },
  LightForgeVocals:{analyze:async()=>{state.order.push('classifier');return {classifier:{},model:{id:'classifier'}};}},
  LightForgeVocalDetail:{Extractor:DetailExtractor},
  LightForgeGAME:{
   create:async()=>({process:async(reader,samples)=>{state.gameSamples.push(samples);state.order.push('game');return {notes:[]};},release:async()=>{}}),
   fuse:()=>({warnings:[],model:{id:'classifier'},transcription:{model:'game-large'},notes:[]})
  },
  LightForgeBass:{analyze:async()=>({notes:[],method:'test-bass'})},
  LightForgeStemRouting:{ensureAnalysis:()=>({routing:{stems:[]},rebuilt:false}),validate:()=>({valid:true})},
  LightForgeSemanticTimeline:{build:()=>({events:[],summary:{countByTier:{}}}),validate:()=>({valid:true})},
  LightForgeMusicSalience:{build:()=>({events:[],summary:{context:{profile:'balanced'},countByTier:{}}}),validate:()=>({valid:true})}
 };
 context.self=context;
 vm.runInNewContext(workerSource,context,{filename:'worker.js'});
 await context.self.onmessage({data:{audioUrl:'memory://original.wav',options:{analysisQuality:'precision',workId:'reader-reuse-test',cacheKey:'stem-12345678-1234-1234-1234-123456789abc'},stage,value}});
 const error=messages.find(message=>message.type==='error');
 if(error){const failure=Error(error.message);failure.state=state;throw failure;}
 const result=messages.find(message=>message.type==='result');
 if(!result)throw Error('Worker returned no result.');
 return {state,result:result.value};
}

test('voice reuses the verified full-resolution stem sample clock without reopening the original WAV',async()=>{
 const {state}=await run('voice',baseValue());
 assert.equal(state.readerConstructions,0);
 assert.deepEqual(state.detailDurations,[sourceClock.duration]);
 assert.deepEqual(state.gameSamples,[sourceClock.samples]);
 assert.ok(state.order.indexOf('fullVoice')<state.order.indexOf('classifier'),'full-resolution cache integrity must be checked before vocal inference');
});

test('bass does not reopen the original WAV after stem separation',async()=>{
 const {state,result}=await run('bass',baseValue());
 assert.equal(state.readerConstructions,0);
 assert.equal(result.bassAnalysis.inputStem,'accompaniment');
});

async function rejectsInvalidClock(invalid){
 let failure;
 try{await run('voice',invalid);}catch(error){failure=error;}
 assert.match(failure?.message||'',/Re-analyze to recover full-resolution voice audio/);
 assert.equal(failure.state.readerConstructions,0);
 assert.deepEqual(failure.state.writes,[],'corrupt cache clock must fail before classifier or voice checkpoints');
}

test('voice preserves an odd original sample clock without reopening the source WAV',async()=>{
 const odd=baseValue();odd.stemCache.fullSamples=132301;odd.stemCache.samples=66151;odd.stemCache.duration=132301/44100;
 const {state}=await run('voice',odd);
 assert.deepEqual(state.detailDurations,[132301/44100]);
 assert.deepEqual(state.gameSamples,[132301]);
});

test('voice rejects an invalid full-resolution stem clock instead of falling back to an original WAV read',async()=>{
 const missing=baseValue();missing.stemCache.fullSamples=null;
 await rejectsInvalidClock(missing);
 const durationMismatch=baseValue();durationMismatch.stemCache.duration=sourceClock.duration+.1;
 await rejectsInvalidClock(durationMismatch);
});
