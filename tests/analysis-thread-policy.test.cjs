'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'..'),source=name=>fs.readFileSync(path.join(root,'web/analysis',name),'utf8');
const stages=['rhythm','separation','voice','bass'],workId='a'.repeat(64),total=13*44100;
const classifierModel={id:'fixture-classifier',sha256:'b'.repeat(64)};
function classifierFixture(){return {model:{...classifierModel},classifier:{model:{...classifierModel},frameStep:.04,singingScores:new Float32Array(325).fill(.9),speechScores:new Float32Array(325).fill(.1)}};}

function workerHarness({cores=8,isolated=true,shared=true,cached=null,classifier=null,completeVoice=null,voice=false,downgrade=false}={}){
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
  LightForgeAnalysisStore:{open:async()=>({read:async name=>structuredClone(name==='voice-classifier'?classifier:name==='voice'?completeVoice:name==='rhythm'?cached:null),write:async(name,value)=>writes.push([name,structuredClone(value)]),invalidate:async()=>{}})},
  LightForgeStemCache:{files:async()=>{},readers:async()=>({vocals:reader,accompaniment:reader}),fullVoice:async()=>async(first,count)=>{reads.push([first,count]);return new Float32Array(count).fill(.1);}},
  LightForgeWavReader:class{constructor(){this.samples=total;this.duration=13;}async open(){if(!voice)throw Error('__POLICY_BOUNDARY__');}},
  LightForgeVocals:{analyze:async(_reader,_config,{ort:runtime,includeClassifierScores})=>{
   assert.equal(includeClassifierScores,true);const session=await runtime.InferenceSession.create('https://app.test/analysis/models/frame-mn10-singing.onnx');
   await session.run({});await session.release();return classifierFixture();
  }},
  LightForgeVocalDetail:{Extractor:class{push(){}finish(){return {accents:[],pitchContour:{midi:new Array(325).fill(0)},phrases:[{start:0,end:13,kind:'singing',confidence:.9}],envelopeStep:.02,envelope:new Array(650).fill(.2),timing:{},diagnostics:{}};}}},
  fetch:async url=>({json:async()=>String(url).endsWith('model-manifest.json')?{precision:{},balanced:{}}:String(url).endsWith('vocal-model.json')?classifierModel:String(url).endsWith('/game/manifest.json')?{id:'fixture-game'}:{}}),
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
 for(const quality of ['precision','balanced'])for(const stage of [...stages,'voice-classifier'])for(const cores of [1,2,4,6,7,8,12]){
  const h=workerHarness({cores});
  const expected=cores>=8&&(stage==='voice'||quality==='precision'&&stage==='separation')?4:1;
  assert.equal(h.context.wasmThreadsForStage({androidApp:true},stage,quality),expected,JSON.stringify({quality,stage,cores}));
 }
});

test('Android shared-memory prerequisites retain serial execution independently',async()=>{
 for(const isolated of [false,true])for(const shared of [false,true])for(const cores of [undefined,0,7,8]){
  const h=workerHarness({cores,isolated,shared});h.context.navigator.hardwareConcurrency=cores;
  assert.equal(h.context.wasmThreadsForStage({androidApp:true},'voice','precision'),isolated&&shared&&cores>=8?4:1,JSON.stringify({isolated,shared,cores}));
 }
});

test('browser runtime selection preserves the published two and three thread routes',async()=>{
 for(const quality of ['precision','balanced'])for(const stage of stages)for(const cores of [1,2,4,6,8,12]){
  const h=workerHarness({cores});
  assert.equal(h.context.wasmThreadsForStage({androidApp:false},stage,quality),Math.min(4,Math.max(1,Math.floor(cores/2))),JSON.stringify({quality,stage,cores}));
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
  const h=workerHarness({cores:4,isolated,voice:true,classifier:classifierFixture()}),result=await h.run('voice',{androidApp});
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
 const h=workerHarness({cores:8,voice:true,downgrade:true,classifier:classifierFixture()}),result=await h.run('voice');
 assert.equal(result.type,'result',result.message);assert.equal(h.context.ort.env.wasm.numThreads,1);
 assert.equal(result.runtime.configuredThreads,4);assert.equal(result.runtime.ortThreadsAfterStage,1);
 assert.equal(result.runtime.crossOriginIsolated,true);assert.equal(result.runtime.sharedArrayBuffer,true);assert.equal(result.runtime.restored,false);
 assert.equal(h.sessions.length,5);assert.ok(h.sessions.every(s=>s.threads===1));
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
  assert.equal(requests.length,expected?5:4);assert.ok(requests.every(request=>request.options.androidApp===expected));
  assert.equal(logs.filter(log=>log[1]==='analysis-runtime').length,expected?5:4);
  assert.deepEqual(Object.keys(music.engine.stages),stages);assert.equal(music.engine.stages.voice.seconds,expected?2:1);
  assert.equal('runtime' in music,false);assert.equal('configuredThreads' in music.engine,false);
  assert.ok(Object.values(music.engine.stages).every(stage=>!('runtime' in stage)&&!('configuredThreads' in stage)));
 }
});

test('private classifier handoff retires one-thread inference before four-thread GAME without changing output',async()=>{
 const first=workerHarness({voice:true}),classified=await first.run('voice-classifier');
 assert.equal(classified.type,'result',classified.message);assert.equal(classified.runtime.configuredThreads,1);
 assert.deepEqual(first.graphs,['frame-mn10-singing']);assert.ok(first.sessions.every(session=>session.threads===1));
 assert.equal('classifier' in classified.value,false);assert.equal('vocals' in classified.value,false);
 assert.deepEqual(first.writes.map(([key])=>key),['voice-classifier']);
 const handoff=first.writes[0][1],second=workerHarness({voice:true,classifier:handoff}),accelerated=await second.run('voice');
 assert.equal(accelerated.type,'result',accelerated.message);assert.equal(accelerated.runtime.configuredThreads,4);assert.equal(accelerated.runtime.classifierFallback,false);
 assert.equal(second.graphs.includes('frame-mn10-singing'),false);assert.ok(second.sessions.every(session=>session.threads===4));
 assert.equal(second.graphs.filter(name=>name==='segmenter').length,16);assert.equal(second.capacityRequests,0);assert.equal(second.children,0);
 const fallback=workerHarness({voice:true}),serial=await fallback.run('voice');
 assert.equal(serial.type,'result',serial.message);assert.equal(serial.runtime.configuredThreads,1);assert.equal(serial.runtime.classifierFallback,true);
 assert.equal(JSON.stringify(accelerated.value),JSON.stringify(serial.value));
 assert.deepEqual(second.writes, fallback.writes,'Handoff changed persisted classification or GAME values');
});

test('complete voice and valid classifier checkpoints bypass private inference and preserve the musical value',async()=>{
 const full=workerHarness({completeVoice:{vocals:{fixture:true}}}),whole=await full.run('voice-classifier');
 assert.equal(whole.type,'result',whole.message);assert.equal(whole.restored,true);assert.equal(whole.runtime.configuredThreads,null);
 assert.equal(full.context.ort.env.wasm.numThreads,undefined);assert.equal(full.sessions.length,0);assert.equal(full.writes.length,0);
 assert.equal('vocals' in whole.value,false,'Private stage merged a cached voice result into its public input');
 const ready=workerHarness({voice:true,classifier:classifierFixture()}),cached=await ready.run('voice-classifier');
 assert.equal(cached.type,'result',cached.message);assert.equal(cached.restored,true);assert.equal(cached.runtime.ortThreadsAfterStage,null);
 assert.equal(ready.context.ort.env.wasm.numThreads,undefined);assert.equal(ready.sessions.length,0);assert.equal(ready.writes.length,0);
});

test('missing, wrong-model, truncated and corrupt classifier handoffs force complete serial voice before ORT initialization',async()=>{
 const wrongModel=classifierFixture();wrongModel.model.sha256='c'.repeat(64);
 const wrongClock=classifierFixture();wrongClock.classifier.frameStep=.02;
 const truncated=classifierFixture();truncated.classifier.singingScores=new Float32Array(324);
 const nonfinite=classifierFixture();nonfinite.classifier.speechScores[0]=NaN;
 const wrongType=classifierFixture();wrongType.classifier.singingScores=Array.from(wrongType.classifier.singingScores);
 for(const classifier of [null,{},wrongModel,wrongClock,truncated,nonfinite,wrongType]){
  const h=workerHarness({voice:true,classifier}),result=await h.run('voice');
  assert.equal(result.type,'result',result.message);assert.equal(result.runtime.classifierFallback,true);assert.equal(result.runtime.configuredThreads,1);
  assert.equal(h.sessions[0].name,'frame-mn10-singing');assert.ok(h.sessions.every(session=>session.threads===1));
  assert.equal(h.graphs.filter(name=>name==='segmenter').length,16);assert.equal(h.capacityRequests,0);assert.equal(h.children,0);
  assert.equal(h.context.validVoiceClassifier(h.writes[0][1],13,classifierModel),true,'Fallback did not repair the handoff');
 }
});

function lifecycleHarness({cancelPrivate=false}={}){
 const {webcrypto}=require('node:crypto'),events=[],requests=[],progress=[],controller=new AbortController();let active=0,maximum=0;
 const context=vm.createContext({URL,TextEncoder,crypto:webcrypto,DOMException,AbortController,performance,setInterval,clearInterval,console,
  Android:{pickAudio(){}},LightForgeVersion:{name:'2.2.5'},document:{currentScript:{src:'https://app.test/analysis/analyzer.js'}},
  LightForgeAnalysisStore:{hash:async bytes=>Buffer.from(await webcrypto.subtle.digest('SHA-256',bytes)).toString('hex')},
 });context.window=context;
 context.Worker=class{
  constructor(){active++;maximum=Math.max(active,maximum);this.closed=false;}
  terminate(){if(!this.closed){this.closed=true;active--;events.push('terminated:'+this.stage);}}
  postMessage(message){
   this.stage=message.stage;requests.push(structuredClone(message));events.push('started:'+this.stage);
   queueMicrotask(()=>{
    if(this.closed)return;
    this.onmessage({data:{type:'progress',value:{progress:{rhythm:.4,separation:.82,'voice-classifier':.90,voice:.98,bass:1}[this.stage],stage:this.stage}}});
    if(this.closed)return;
    this.onmessage({data:{type:'result',value:this.stage==='voice-classifier'?{privateOnly:'never merge'}:{...message.value,engine:{name:'fixture'},[this.stage]:true},seconds:this.stage==='voice-classifier'?7:3,restored:false}});
   });
  }
 };
 vm.runInContext(source('analyzer.js'),context);
 return {events,requests,progress,get maximum(){return maximum;},get active(){return active;},run:()=>context.MusicAnalyzer.analyze('/song.wav',{analysisIdentity:workId,analysisAudioIdentity:'b'.repeat(64)},info=>{progress.push(info);if(cancelPrivate&&info.stage==='voice-classifier')controller.abort();},controller.signal)};
}

test('private worker completes and terminates before GAME while public progress and timing retain four stages',async()=>{
 const h=lifecycleHarness(),music=await h.run();
 assert.equal(h.maximum,1);assert.equal(h.active,0);
 assert.deepEqual(h.requests.map(request=>request.stage),['rhythm','separation','voice-classifier','voice','bass']);
 assert.ok(h.events.indexOf('terminated:voice-classifier')<h.events.indexOf('started:voice'));
 assert.equal(h.requests[2].options.workId,h.requests[3].options.workId);assert.equal(h.requests[3].value.privateOnly,undefined);assert.equal(music.privateOnly,undefined);
 assert.deepEqual(Object.keys(music.engine.stages),stages);assert.equal(music.engine.stages.voice.seconds,10);
 assert.equal(h.progress.find(info=>info.stage==='voice-classifier').completedStages,2);assert.equal(h.progress.find(info=>info.stage==='voice').completedStages,2);assert.equal(h.progress.at(-1).completedStages,3);
 assert.ok(h.progress.every((info,index)=>index===0||info.progress>=h.progress[index-1].progress));
});

test('cancelling the private classifier retires its worker and never starts GAME',async()=>{
 const h=lifecycleHarness({cancelPrivate:true});await assert.rejects(h.run(),error=>error.name==='AbortError');
 assert.equal(h.maximum,1);assert.equal(h.active,0);assert.deepEqual(h.requests.map(request=>request.stage),['rhythm','separation','voice-classifier']);
 assert.equal(h.events.at(-1),'terminated:voice-classifier');
});
