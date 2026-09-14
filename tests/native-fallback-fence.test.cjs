'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {webcrypto}=require('node:crypto');

const source=fs.readFileSync(process.env.LIGHTFORGE_WORKER_SOURCE||path.join(__dirname,'..','web/analysis/worker.js'),'utf8');

test('a failed native cache fence blocks the WASM retry instead of admitting mixed evidence',async()=>{
 const invalidations=[],messages=[];let aborted=0;
 const store={
  async read(){return null;},async write(){assert.fail('no separation checkpoint may be committed after fence failure');},
  async reserve(){},async invalidate(prefixes){invalidations.push([...prefixes]);if(invalidations.length===2)throw Error('native cache fence refused');}
 };
 const context=vm.createContext({console,URL,Float32Array,ArrayBuffer,DataView,Map,Number,Math,setTimeout,clearTimeout,performance,crypto:webcrypto,navigator:{hardwareConcurrency:2},ort:{env:{wasm:{}}},
  fetch:async url=>String(url).endsWith('features.json')?{json:async()=>({})}:{json:async()=>({precision:{},balanced:{}})},
  LightForgeAnalysisStore:{open:async()=>store},
  LightForgeAnalysisTelemetry:{create:()=>({begin:()=>null,end:()=>{},cache:()=>{},snapshot:attributes=>attributes})},
  LightForgeStemCache:{prune:async()=>{},create:async()=>({append:async()=>assert.fail('a fenced native chunk must not be appended'),finish:async()=>({}),abort:async()=>{aborted++;}})},
  LightForgeWavReader:class{constructor(){this.samples=44100;this.duration=1;}async open(){}async stereo44100(){throw Error('WASM must not read after native fence failure');}},
  LightForgeDeux:{create:async options=>({process:async()=>options.nativePredict(0,()=>{}),release:async()=>{}})}
 });
 context.self=context;context.location={href:'https://app.test/analysis/worker.js'};context.importScripts=()=>{};
 context.postMessage=message=>{messages.push(message);if(message.type==='native-deux')setImmediate(()=>context.onmessage({data:{type:'native-deux-result',requestId:message.requestId,fallback:true}}));};
 vm.runInContext(source,context);
 await context.onmessage({data:{stage:'separation',audioUrl:'/song.wav',value:{duration:1},options:{workId:'a'.repeat(64),cacheKey:'test',supportsNativeDeux:true}}});
 assert.equal(aborted,1);
 assert.deepEqual(invalidations.map(x=>x.join(',')),['separation,voice,vocal-semantics,game,bass,recurrence','separation,deux,voice,vocal-semantics,game,bass,recurrence']);
 const error=messages.at(-1);assert.equal(error.type,'error');assert.equal(error.code,undefined);assert.match(error.message,/native cache fence refused/);
});
