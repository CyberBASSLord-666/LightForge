'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {webcrypto}=require('node:crypto');

const source=fs.readFileSync(process.env.LIGHTFORGE_ANALYZER_SOURCE||path.join(__dirname,'..','web/analysis/analyzer.js'),'utf8');
const manifest=JSON.stringify({'analyzer.js':{bytes:1,sha256:'a'.repeat(64)},'worker.js':{bytes:1,sha256:'b'.repeat(64)},'models/features.json':{bytes:1,sha256:'c'.repeat(64)},'models/model-manifest.json':{bytes:1,sha256:'d'.repeat(64)}});

function harness(){
 const starts=[],events=[];let separationFailed=false;
 const context=vm.createContext({URL,crypto:webcrypto,TextEncoder,DOMException,AbortController,performance,setInterval,clearInterval,fetch:async()=>({ok:true,text:async()=>manifest}),
  LightForgeVersion:{name:'test'},document:{currentScript:{src:'https://app.test/analysis/analyzer.js'}},
  LightForgeAnalysisStore:{hash:async bytes=>Buffer.from(await webcrypto.subtle.digest('SHA-256',bytes)).toString('hex'),discard:async id=>events.push(['discard-work',id])},
  LightForgeStemCache:{discard:async id=>events.push(['discard-stem',id])}
 });
 context.window=context;
 context.Worker=class{
  constructor(){this.closed=false;}
  terminate(){this.closed=true;}
  postMessage(message){starts.push(message);setImmediate(()=>{
   if(this.closed||!message.stage)return;
   if(message.stage==='separation'&&message.options.supportsNativeDeux&&!separationFailed){separationFailed=true;this.onmessage({data:{type:'error',message:'native separation failed',code:'native-deux-fallback'}});return;}
   this.onmessage({data:{type:'result',value:{...message.value,engine:{name:'test'}},seconds:0,restored:false,profile:{schemaVersion:1,resources:{}}}});
  });}
 };
 vm.runInContext(source,context);
 return {analyze:context.MusicAnalyzer.analyze,starts,events};
}

test('native fallback persists before retrying under a distinct WASM cache identity',async()=>{
 const h=harness(),events=[];const predict=async()=>{throw Error('must be worker-fenced');};predict.release=async()=>events.push('released');
 const result=await h.analyze('/song.wav',{analysisIdentity:'a'.repeat(64),analysisQuality:'precision',nativePredict:predict,nativeRuntimeProfile:'native-deux-test-v1',onNativeFallback:async diagnostic=>{
  assert.deepEqual(events,['released']);assert.equal(diagnostic.attemptedExecution,'native-deux-v1');assert.equal(diagnostic.reason,'native-deux-fallback');events.push('persisted');return true;
 }});
 assert.deepEqual(events,['released','persisted']);
 const workIds=[...new Set(h.starts.filter(start=>start.stage).map(start=>start.options.workId))];assert.equal(workIds.length,2);
 assert.deepEqual(h.starts.filter(start=>start.options.workId===workIds[0]).map(start=>start.stage),['rhythm','separation']);
 assert.deepEqual(h.starts.filter(start=>start.options.workId===workIds[1]).map(start=>start.stage),['rhythm','separation','voice','bass']);
 assert.equal(result.engine.cacheIdentity.execution,'wasm-v1');assert.equal(result.engine.nativeFallback.schemaVersion,1);assert.equal(result.engine.nativeFallback.attemptedExecution,'native-deux-v1');assert.equal(result.engine.nativeFallback.reason,'native-deux-fallback');assert.equal(result.engine.nativeFallback.resultExecution,'wasm-v1');
});

test('a failed persistence fence blocks the WASM retry',async()=>{
 const h=harness(),predict=async()=>{};predict.release=async()=>{};
 await assert.rejects(h.analyze('/song.wav',{analysisIdentity:'a'.repeat(64),nativePredict:predict,nativeRuntimeProfile:'native-deux-test-v1',onNativeFallback:async()=>false}),/fallback checkpoint/);
 assert.deepEqual(h.starts.map(start=>start.stage),['rhythm','separation']);
});
