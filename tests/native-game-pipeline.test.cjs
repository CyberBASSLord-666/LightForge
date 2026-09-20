'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{webcrypto}=require('node:crypto');
const source=name=>fs.readFileSync(path.join(__dirname,'..','web/analysis',name),'utf8'),RATE=44100;
const notes=[{start:.123456,end:.423456,midi:63.123456}];
function gameHarness(){
 const records=new Map(),stats={wasm:0},context=vm.createContext({URL,Float32Array,Number,Math,DOMException,fetch:async()=>({json:async()=>({id:'game-test'})})});context.self=context;
 vm.runInContext(source('game.js'),context);
 return {api:context.LightForgeGAME,records,stats,options:{ort:{InferenceSession:{create:async()=>{stats.wasm++;throw Error('Unexpected WASM model creation');}}},baseUrl:'https://app.test/models/game/',checkpoint:{read:async key=>records.get(key),write:async(key,value)=>records.set(key,value)}}};
}
test('native GAME receives complete bounded PCM, language and deterministic seeds; shared stitching keeps original rounding',async()=>{
 const h=gameHarness(),calls=[],progress=[],game=await h.api.create({...h.options,nativeInfer:async(pcm,language,seed,onStep)=>{calls.push({length:pcm.length,language,seed});onStep(.5);return notes;}});
 const result=await game.process(async(_first,count)=>new Float32Array(count).fill(.1),26*RATE,{language:4,onProgress:p=>progress.push(p)});
 assert.deepEqual(calls,[{length:14*RATE,language:4,seed:2025},{length:16*RATE,language:4,seed:106754},{length:4*RATE,language:4,seed:211483}]);
 assert.equal(result.notes[0].start,.123);assert.equal(result.notes[0].end,.423);assert.equal(result.notes[0].midi,63.12);
 assert.deepEqual(JSON.parse(JSON.stringify(h.records.get('game-4-0').notes)),notes);assert.equal(h.records.get('game-4-0').execution,'native-game-v1');
 assert.equal(result.runtime,'onnxruntime-android-cpu');assert.equal(h.stats.wasm,0);assert.ok(progress.includes(1/6));await game.release();
});
test('native GAME rejects unavailable, nonfinite, out-of-clock, overlapping and unfiltered notes before committing or invoking WASM',async()=>{
 const invalid=[undefined,{},[{start:0,end:1,midi:NaN}],[{start:0,end:1,midi:128}],[{start:-.01,end:1,midi:60}],[{start:0,end:1.1,midi:60}],[{start:0,end:.05,midi:60}],[{start:.3,end:.5,midi:60},{start:.1,end:.4,midi:60}]];
 for(const value of invalid){const h=gameHarness(),game=await h.api.create({...h.options,nativeInfer:async()=>value});await assert.rejects(game.process(async()=>new Float32Array(RATE).fill(.1),RATE),error=>error.code==='native-game-fallback');assert.equal(h.records.size,0);assert.equal(h.stats.wasm,0);await game.release();}
});
test('GAME passage checkpoints cannot cross native and WASM execution identities',async()=>{
 const h=gameHarness(),record={first:0,last:RATE,model:'game-test',steps:8,notes};h.records.set('game-0-0',record);let calls=0;
 const game=await h.api.create({...h.options,nativeInfer:async()=>{calls++;return notes;}});await game.process(async()=>new Float32Array(RATE).fill(.1),RATE);assert.equal(calls,1);
 await game.process(async()=>assert.fail('matching native passage must restore'),RATE);assert.equal(calls,1);await game.release();
 const wasm=await h.api.create(h.options);await assert.rejects(wasm.process(async()=>new Float32Array(RATE).fill(.1),RATE),/Unexpected WASM model creation/);assert.equal(h.stats.wasm,1);await wasm.release();
});
test('native GAME preserves cancellation and unretired JNI failures as fatal, not fallback',async()=>{
 for(const error of [new DOMException('cancelled','AbortError'),Object.assign(Error('JNI still running'),{code:'native-game-retirement-pending'}),Object.assign(Error('cache fence failed'),{code:'native-game-fence-failed'})]){
  const h=gameHarness(),game=await h.api.create({...h.options,nativeInfer:async()=>{throw error;}});await assert.rejects(game.infer(new Float32Array(RATE),0,2025),actual=>actual===error);assert.equal(h.stats.wasm,0);await game.release();
 }
});

function workerHarness({duration=1,respond,failFence=false}={}){
 const records=new Map(),messages=[],invalidations=[],requests=[];let wasm=0;
 const store={read:async key=>records.get(key),write:async(key,value)=>records.set(key,value),invalidate:async prefixes=>{invalidations.push([...prefixes]);if(failFence)throw Error('GAME fence refused');for(const key of records.keys())if(prefixes.some(prefix=>key===prefix||key.startsWith(prefix+'-')))records.delete(key);}};
 const reader={mono22050:async(_start,count)=>new Float32Array(count)};
 const context=vm.createContext({console,URL,Float32Array,ArrayBuffer,DataView,Map,Number,Math,DOMException,setTimeout,clearTimeout,performance,crypto:webcrypto,navigator:{hardwareConcurrency:2},ort:{env:{wasm:{}},InferenceSession:{create:async()=>{wasm++;throw Error('Unexpected WASM model creation');}}},
  fetch:async url=>({json:async()=>String(url).endsWith('manifest.json')?{id:'game-test'}:String(url).endsWith('model-manifest.json')?{precision:{},balanced:{}}:{}}),
  LightForgeAnalysisStore:{open:async()=>store},LightForgeStemCache:{readers:async()=>({vocals:reader,accompaniment:reader}),fullVoice:async()=>async(_start,count)=>new Float32Array(count).fill(.1)},
  LightForgeVocals:{analyze:async()=>({classifier:[],model:'test'})},LightForgeVocalDetail:{Extractor:class{push(){}finish(){return {phrases:[],accents:[],pitchContour:{midi:[]},envelope:[],timing:{},diagnostics:{}};}}}
 });context.self=context;context.location={href:'https://app.test/analysis/worker.js'};context.importScripts=()=>{};
 context.postMessage=(message,transfers)=>{messages.push(message);if(message.type==='native-game'){requests.push(message);assert.equal(transfers[0],message.buffer);setImmediate(()=>context.onmessage({data:{type:'native-game-result',requestId:message.requestId,...(respond?respond(requests.length,message):{notes})}}));}};
 vm.runInContext(source('game.js'),context);vm.runInContext(source('worker.js'),context);
 return {records,messages,invalidations,requests,get wasm(){return wasm;},run:()=>context.onmessage({data:{stage:'voice',audioUrl:'/song.wav',value:{stemCache:{fullSamples:duration*RATE,duration,samples:duration*22050}},options:{workId:'a'.repeat(64),cacheKey:'test',supportsNativeGame:true}}})};
}
test('worker transports complete native GAME PCM and commits only validated voice output',async()=>{
 const h=workerHarness();await h.run();assert.equal(h.requests.length,1);assert.equal(h.requests[0].buffer.byteLength,RATE*4);assert.equal(h.requests[0].language,0);assert.equal(h.requests[0].seed,2025);assert.equal(h.messages.at(-1).type,'result');assert.ok(h.records.has('voice'));assert.ok(h.records.has('game-0-0'));assert.equal(h.wasm,0);
});
test('later native GAME passage failure fences all dependent records before reporting a WASM restart',async()=>{
 const h=workerHarness({duration:13,respond:count=>count===1?{notes}:{fallback:true}});await h.run();assert.equal(h.requests.length,2);assert.deepEqual(h.invalidations,[['voice','vocal-semantics','game','bass','recurrence']]);assert.equal(h.records.size,0);assert.equal(h.messages.at(-1).code,'native-game-fallback');assert.equal(h.wasm,0);
});
test('native GAME malformed results are fenced, but failed fences and pending retirement cannot admit a WASM restart',async()=>{
 const invalid=workerHarness({respond:()=>({notes:[{start:0,end:1,midi:Infinity}]})});await invalid.run();assert.equal(invalid.messages.at(-1).code,'native-game-fallback');assert.equal(invalid.invalidations.length,1);
 const fence=workerHarness({failFence:true,respond:()=>({fallback:true})});await fence.run();assert.equal(fence.messages.at(-1).code,'native-game-fence-failed');assert.match(fence.messages.at(-1).message,/GAME fence refused/);assert.equal(fence.wasm,0);
 const retiring=workerHarness({respond:()=>({code:'native-game-retirement-pending',message:'JNI still active'})});await retiring.run();assert.equal(retiring.messages.at(-1).code,'native-game-retirement-pending');assert.deepEqual(retiring.invalidations,[]);assert.equal(retiring.wasm,0);
});

function analyzerHarness(){
 const starts=[],responses=[],events=[],manifest=JSON.stringify({'analyzer.js':{bytes:1,sha256:'a'.repeat(64)},'worker.js':{bytes:1,sha256:'b'.repeat(64)},'models/features.json':{bytes:1,sha256:'c'.repeat(64)},'models/model-manifest.json':{bytes:1,sha256:'d'.repeat(64)}});
 const context=vm.createContext({URL,ArrayBuffer,Float32Array,crypto:webcrypto,TextEncoder,DOMException,AbortController,performance,setInterval,clearInterval,fetch:async()=>({ok:true,text:async()=>manifest}),LightForgeVersion:{name:'test'},document:{currentScript:{src:'https://app.test/analysis/analyzer.js'}},LightForgeAnalysisStore:{hash:async bytes=>Buffer.from(await webcrypto.subtle.digest('SHA-256',bytes)).toString('hex'),discard:async()=>{}},LightForgeStemCache:{discard:async()=>{}}});context.window=context;
 context.Worker=class{
  constructor(){this.closed=false;}terminate(){this.closed=true;}
  postMessage(message){structuredClone(message);setImmediate(()=>{if(this.closed)return;
   if(message.stage){this.request=message;starts.push(message);if(message.stage==='voice'&&message.options.supportsNativeGame)this.onmessage({data:{type:'native-game',requestId:7,buffer:new Float32Array(RATE).fill(.1).buffer,language:4,seed:4294967295}});else this.finish();}
   else if(message.type==='native-game-result'){responses.push(message);if(message.fallback||message.code)this.onmessage({data:{type:'error',message:'native unavailable',code:message.code||'native-game-fallback'}});else this.finish();}
  });}
  finish(){this.onmessage({data:{type:'result',value:{...this.request.value,engine:{name:'test'}},seconds:0,restored:false}});}
 };
 vm.runInContext(source('analyzer.js'),context);return {...context.MusicAnalyzer,starts,responses,events};
}
const identityOptions={analysisIdentity:'a'.repeat(64),analysisQuality:'precision'},gameProfile='native-game-onnxruntime-android-1.25.1-v1',deuxProfile='native-deux-onnxruntime-android-1.25.1-v1',mdxProfile='native-mdx-onnxruntime-android-1.25.1-v1';
test('analyzer native GAME transfer preserves callback parameters, stays outside structured clone and releases before bass',async()=>{
 const h=analyzerHarness(),events=[],nativeGame=async(pcm,language,seed,signal,onProgress)=>{assert.equal(pcm.length,RATE);assert.equal(language,4);assert.equal(seed,4294967295);assert.equal(signal.aborted,false);onProgress({progress:.5,message:'GAME'});events.push('inferred');return notes;};nativeGame.release=async()=>events.push('released');
 const result=await h.analyze('/song.wav',{...identityOptions,nativeGame,nativeRuntimeProfile:gameProfile});assert.deepEqual(events,['inferred','released']);assert.equal(result.engine.cacheIdentity.execution,'native-game-v1');assert.equal(result.engine.cacheIdentity.persistent,true);assert.equal('nativeGame' in h.starts[0].options,false);assert.equal(h.starts[0].options.supportsNativeGame,true);assert.equal(h.starts.at(-1).stage,'bass');
});
test('all native GAME combinations have isolated, query-reproducible cache identities',async()=>{
 const h=analyzerHarness(),nativeGame=async()=>notes,nativePredict=async()=>{},nativeMdx=async()=>{},cases=[
  [identityOptions,'wasm-v1','wasm'],
  [{...identityOptions,nativeGame,nativeRuntimeProfile:gameProfile},'native-game-v1',gameProfile],
  [{...identityOptions,nativeGame,nativePredict,nativeRuntimeProfile:deuxProfile+'+'+gameProfile},'native-deux-v1+native-game-v1',deuxProfile+'+'+gameProfile],
  [{...identityOptions,analysisQuality:'balanced',nativeGame,nativeMdx,nativeRuntimeProfile:mdxProfile+'+'+gameProfile},'native-mdx-v1+native-game-v1',mdxProfile+'+'+gameProfile]
 ],ids=[];
 for(const [options,execution,profile] of cases){const actual=await h.cacheIdentity(options),query=await h.cacheIdentity({...identityOptions,analysisQuality:options.analysisQuality,cacheIdentityQuery:true,cacheIdentityExecution:execution,cacheIdentityNativeRuntimeProfile:profile});assert.equal(actual.persistent,true);assert.equal(actual.execution,execution);assert.equal(actual.workId,query.workId);ids.push(actual.workId);}
 assert.equal(new Set(ids).size,4);
 for(const [execution,profile,quality] of [['native-game-v1',deuxProfile,'precision'],['native-deux-v1+native-game-v1',gameProfile+'+'+deuxProfile,'precision'],['native-deux-v1+native-game-v1',deuxProfile+'+'+gameProfile,'balanced'],['native-mdx-v1+native-game-v1',mdxProfile,'balanced']]){const invalid=await h.cacheIdentity({...identityOptions,analysisQuality:quality,cacheIdentityQuery:true,cacheIdentityExecution:execution,cacheIdentityNativeRuntimeProfile:profile});assert.equal(invalid.persistent,false);assert.equal(invalid.verified,false);}
 assert.equal((await h.cacheIdentity({...identityOptions,nativeGame,nativeRuntimeProfile:deuxProfile})).persistent,false);
});
test('native GAME fallback releases and persists before restarting every stage under all-WASM identity',async()=>{
 const h=analyzerHarness(),events=[],nativePredict=async()=>{},nativeGame=async()=>undefined;nativePredict.release=async()=>events.push('separator released');nativeGame.release=async()=>events.push('game released');
 const result=await h.analyze('/song.wav',{...identityOptions,nativePredict,nativeGame,nativeRuntimeProfile:deuxProfile+'+'+gameProfile,onNativeFallback:async diagnostic=>{assert.deepEqual(events,['separator released','game released']);assert.equal(diagnostic.attemptedExecution,'native-deux-v1+native-game-v1');assert.equal(diagnostic.reason,'native-game-fallback');events.push('persisted');return true;}});
 assert.deepEqual(events,['separator released','game released','persisted']);assert.deepEqual(h.starts.map(x=>x.stage),['rhythm','separation','voice','rhythm','separation','voice','bass']);assert.equal(new Set(h.starts.map(x=>x.options.workId)).size,2);for(const start of h.starts.slice(3)){assert.equal(start.options.supportsNativeGame,false);assert.equal(start.options.supportsNativeDeux,false);assert.equal(start.options.nativeRuntimeProfile,'wasm');}assert.equal(result.engine.cacheIdentity.execution,'wasm-v1');assert.equal(result.engine.nativeFallback.reason,'native-game-fallback');
});
test('analyzer native GAME retirement and release failures prevent any WASM retry',async()=>{
 for(const releaseFails of [false,true]){const h=analyzerHarness(),failure=Object.assign(Error('JNI not retired'),{code:'native-game-retirement-pending'}),nativeGame=async()=>{if(!releaseFails)throw failure;return undefined;};nativeGame.release=async()=>{if(releaseFails)throw failure;};await assert.rejects(h.analyze('/song.wav',{...identityOptions,nativeGame,nativeRuntimeProfile:gameProfile,onNativeFallback:async()=>assert.fail('must not persist fallback')}),error=>error.code==='native-game-retirement-pending');assert.deepEqual(h.starts.map(x=>x.stage),['rhythm','separation','voice']);}
});
test('analyzer cannot open the WASM namespace when native GAME fallback persistence fails',async()=>{
 const h=analyzerHarness(),nativeGame=async()=>undefined;nativeGame.release=async()=>{};
 await assert.rejects(h.analyze('/song.wav',{...identityOptions,nativeGame,nativeRuntimeProfile:gameProfile,onNativeFallback:async()=>false}),/fallback checkpoint/);assert.deepEqual(h.starts.map(x=>x.stage),['rhythm','separation','voice']);assert.equal(new Set(h.starts.map(x=>x.options.workId)).size,1);
});
test('cancellation aborts native GAME and releases it without starting downstream work or fallback',async()=>{
 const h=analyzerHarness(),controller=new AbortController();let callSignal,released=0;const nativeGame=async(_pcm,_language,_seed,signal)=>{callSignal=signal;setImmediate(()=>controller.abort());return new Promise(()=>{});};nativeGame.release=async()=>{released++;};await assert.rejects(h.analyze('/song.wav',{...identityOptions,nativeGame,nativeRuntimeProfile:gameProfile,onNativeFallback:async()=>assert.fail('cancellation is not fallback')},()=>{},controller.signal),error=>error.name==='AbortError');assert.equal(callSignal.aborted,true);assert.equal(released,1);assert.deepEqual(h.starts.map(x=>x.stage),['rhythm','separation','voice']);
});
