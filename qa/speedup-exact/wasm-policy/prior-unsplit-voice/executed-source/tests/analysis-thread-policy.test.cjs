'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'..'),source=name=>fs.readFileSync(path.join(root,'web/analysis',name),'utf8');
const stages=['rhythm','separation','voice','bass'],workId='a'.repeat(64),total=13*44100;

function workerHarness({cores=8,isolated=true,shared=true,cached=null,voice=false,downgrade=false}={}){
 const messages=[],writes=[],reads=[],sessions=[],graphs=[];let children=0,capacityRequests=0,pcmDuration=0;
 class Tensor{constructor(type,data,dims){Object.assign(this,{type,data,dims});}dispose(){}}
 const f=(...values)=>new Tensor('float32',Float32Array.from(values),[1,values.length]);
 const mask=()=>new Tensor('bool',Uint8Array.of(1),[1,1]);
 const ort={env:{wasm:{}},Tensor,InferenceSession:{create:async url=>{
  if(downgrade)ort.env.wasm.numThreads=1;
  const name=path.basename(new URL(url).pathname,'.onnx');sessions.push({name,threads:ort.env.wasm.numThreads});
  return {release:async()=>{},run:async feed=>{
   graphs.push(name);
   if(name==='encoder'){pcmDuration=feed.waveform.data.length/44100;return {maskT:mask(),x_seg:f(1),x_est:f(1)};}
   if(name==='dur2bd'||name==='segmenter')return {boundaries:f(1)};
   if(name==='bd2dur')return {durations:f(Math.min(5,pcmDuration)),maskN:mask()};
   if(name==='estimator')return {scores:f(60),presence:mask()};
   if(name==='frame-mn10-singing')return {scores:f(.9)};
   throw Error('Unexpected graph '+name);
  }};
 }}};
 const reader={mono22050:async(first,count)=>new Float32Array(count).fill(.1)};
 const context=vm.createContext({console,URL,Float32Array,Uint8Array,BigInt64Array,ArrayBuffer,DataView,performance,Map,Number,setTimeout,clearTimeout,
  navigator:{hardwareConcurrency:cores},crossOriginIsolated:isolated,SharedArrayBuffer:shared?SharedArrayBuffer:undefined,importScripts(){},ort,
  LightForgeAnalysisStore:{open:async()=>({read:async name=>name==='voice-classifier'?null:cached,write:async(name,value)=>writes.push([name,structuredClone(value)]),invalidate:async()=>{}})},
  LightForgeStemCache:{files:async()=>{},readers:async()=>({vocals:reader,accompaniment:reader}),fullVoice:async()=>async(first,count)=>{reads.push([first,count]);return new Float32Array(count).fill(.1);}},
  LightForgeWavReader:class{constructor(){this.samples=total;this.duration=13;}async open(){if(!voice)throw Error('__POLICY_BOUNDARY__');}},
  LightForgeVocals:{analyze:async(_reader,_config,{ort:runtime,includeClassifierScores})=>{
   assert.equal(includeClassifierScores,true);const session=await runtime.InferenceSession.create('https://app.test/analysis/models/frame-mn10-singing.onnx');
   await session.run({});await session.release();return {classifier:{fixture:true},model:'fixture-classifier'};
  }},
  LightForgeVocalDetail:{Extractor:class{push(){}finish(){return {accents:[],pitchContour:{midi:new Array(325).fill(0)},phrases:[{start:0,end:13,kind:'singing',confidence:.9}],envelopeStep:.02,envelope:new Array(650).fill(.2),timing:{},diagnostics:{}};}}},
  fetch:async url=>({json:async()=>String(url).endsWith('model-manifest.json')?{precision:{},balanced:{}}:String(url).endsWith('/game/manifest.json')?{id:'fixture-game'}:{}}),
  Worker:class{constructor(){children++;throw Error('Unqualified pool child started');}},
 });
 context.self=context;context.location={href:'https://app.test/analysis/worker.js'};
 context.postMessage=m=>{
  messages.push(m);
  if(m.type==='game-capacity'){
   capacityRequests++;
   queueMicrotask(()=>context.onmessage({data:{type:'game-capacity-result',requestId:m.requestId,parallelism:2}}));
  }
 };
 vm.runInContext(source('game.js'),context);vm.runInContext(source('worker.js'),context);
 return {context,messages,writes,reads,sessions,graphs,get children(){return children;},get capacityRequests(){return capacityRequests;},
  run:async(stage='voice',options={})=>{
   await context.onmessage({data:{stage,audioUrl:'/song.wav',options:{workId,cacheKey:'fixture',androidApp:true,analysisQuality:'precision',supportsGameCapacity:true,...options},value:{duration:13,stemCache:{key:'fixture',samples:Math.ceil(total/2)}}}});
   return messages.at(-1);
  }};
}

test('Android runtime selection enables only qualified stage/thread combinations',async()=>{
 for(const quality of ['precision','balanced'])for(const stage of stages)for(const cores of [1,2,4,6,7,8,12]){
  const h=workerHarness({cores}),result=await h.run(stage,{analysisQuality:quality});
  assert.equal(result.type,'error');assert.match(result.message,/__POLICY_BOUNDARY__/);
  const expected=cores>=8&&(stage==='voice'||quality==='precision'&&stage==='separation')?4:1;
  assert.equal(h.context.ort.env.wasm.numThreads,expected,JSON.stringify({quality,stage,cores}));
 }
});

test('Android shared-memory prerequisites retain serial execution independently',async()=>{
 for(const isolated of [false,true])for(const shared of [false,true])for(const cores of [undefined,0,7,8]){
  const h=workerHarness({cores,isolated,shared});h.context.navigator.hardwareConcurrency=cores;await h.run('voice');
  assert.equal(h.context.ort.env.wasm.numThreads,isolated&&shared&&cores>=8?4:1,JSON.stringify({isolated,shared,cores}));
 }
});

test('browser runtime selection preserves the published two and three thread routes',async()=>{
 for(const quality of ['precision','balanced'])for(const stage of stages)for(const cores of [1,2,4,6,8,12]){
  const h=workerHarness({cores});await h.run(stage,{analysisQuality:quality,androidApp:false});
  assert.equal(h.context.ort.env.wasm.numThreads,Math.min(4,Math.max(1,Math.floor(cores/2))),JSON.stringify({quality,stage,cores}));
 }
});

test('a completed stage restores before initializing or claiming a new model runtime',async()=>{
 const h=workerHarness({cached:{rhythmFixture:true}}),result=await h.run('rhythm');
 assert.equal(result.type,'result');assert.equal(result.restored,true);assert.equal(result.value.rhythmFixture,true);
 assert.equal(h.context.ort.env.wasm.numThreads,undefined);assert.equal(h.sessions.length,0);assert.equal(h.graphs.length,0);assert.equal(h.writes.length,0);
 assert.equal(result.runtime.configuredThreads,null);assert.equal(result.runtime.ortThreadsAfterStage,null);assert.equal(result.runtime.restored,true);
});

test('production GAME pool stays disabled despite eligible capacity and nonzero multi-passage audio',async()=>{
 for(const androidApp of [false,true])for(const isolated of [false,true]){
  const h=workerHarness({cores:4,isolated,voice:true}),result=await h.run('voice',{androidApp});
  assert.equal(result.type,'result',result.message);assert.equal(result.restored,false);
  assert.equal(h.capacityRequests,0,'Worker queried an eligible pool capacity callback');
  assert.equal(h.children,0,'Production transcription started an experimental child');
  assert.deepEqual(h.reads,[[0,total],[441000,total-441000]],'Serial transcription changed original passage PCM geometry');
  assert.equal(h.graphs.filter(n=>n==='encoder').length,2);assert.equal(h.graphs.filter(n=>n==='segmenter').length,16);
  assert.equal(h.graphs.filter(n=>n==='estimator').length,2);
  const passages=h.writes.filter(([key])=>key.startsWith('game-'));
  assert.deepEqual(passages.map(([key])=>key),['game-0-0','game-0-1']);
  assert.ok(passages.every(([,value])=>value.steps===8&&value.model==='fixture-game'));
  assert.equal(result.value.vocals.transcription.steps,8);
 }
});

test('runtime fallback after four-thread selection keeps serial GAME and complete inference',async()=>{
 const h=workerHarness({cores:8,voice:true,downgrade:true}),result=await h.run('voice');
 assert.equal(result.type,'result',result.message);assert.equal(h.context.ort.env.wasm.numThreads,1);
 assert.equal(result.runtime.configuredThreads,4);assert.equal(result.runtime.ortThreadsAfterStage,1);
 assert.equal(result.runtime.crossOriginIsolated,true);assert.equal(result.runtime.sharedArrayBuffer,true);assert.equal(result.runtime.restored,false);
 assert.ok(h.sessions.length>=6);assert.ok(h.sessions.every(s=>s.threads===1));
 assert.equal(h.capacityRequests,0);assert.equal(h.children,0);assert.equal(h.graphs.filter(n=>n==='segmenter').length,16);
});

test('analyzer derives Android routing from callable app bridges and keeps runtime detail in diagnostics',async()=>{
 const {webcrypto}=require('node:crypto');
 for(const [bridge,expected] of [[{},false],[{Android:{pickAudio(){}}},true],[{BackgroundJob:{checkpoint(){}}},true],[{Android:{pickAudio:true},BackgroundJob:{checkpoint:true}},false]]){
  const requests=[],logs=[],context=vm.createContext({URL,TextEncoder,crypto:webcrypto,DOMException,AbortController,performance,setInterval,clearInterval,console,...bridge,
   LightForgeVersion:{name:'2.2.5'},document:{currentScript:{src:'https://app.test/analysis/analyzer.js'}},
   LightForgeAnalysisStore:{hash:async bytes=>Buffer.from(await webcrypto.subtle.digest('SHA-256',bytes)).toString('hex')},
   LightForgeDiagnostics:{log:(...args)=>logs.push(args)},
  });context.window=context;
  context.Worker=class{terminate(){}postMessage(message){
   requests.push(structuredClone(message));queueMicrotask(()=>this.onmessage({data:{type:'result',value:{engine:{name:'fixture'},evidence:[1,2,3]},seconds:1,restored:false,runtime:{androidApp:expected,configuredThreads:4,ortThreadsAfterStage:4,restored:false}}}));
  }};
  vm.runInContext(source('analyzer.js'),context);
  const music=await context.MusicAnalyzer.analyze('/song.wav',{analysisIdentity:workId,androidApp:!expected});
  assert.equal(requests.length,4);assert.ok(requests.every(request=>request.options.androidApp===expected));
  assert.equal(logs.filter(log=>log[1]==='analysis-runtime').length,4);
  assert.equal('runtime' in music,false);assert.equal('configuredThreads' in music.engine,false);
  assert.ok(Object.values(music.engine.stages).every(stage=>!('runtime' in stage)&&!('configuredThreads' in stage)));
 }
});
