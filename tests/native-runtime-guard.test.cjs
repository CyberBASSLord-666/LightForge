'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/background/native-deux.js'),'utf8');
function adapter(){
 const logs=[],window={LightForgeDiagnostics:{log(...args){logs.push(args);}}};
 vm.runInNewContext(source,{window,DOMException,setTimeout});
 return {create:window.LightForgeNativeDeux.create,profile:window.LightForgeNativeDeux.analysisCacheProfile,logs};
}
test('guard identity follows the pinned native runtime version',()=>{
 const runtime=JSON.parse(fs.readFileSync(path.join(__dirname,'../android/native-runtime.json'),'utf8'));
 const engine=fs.readFileSync(path.join(__dirname,'../android/src/com/cyberbasslord/lightforge/NativeDeux.java'),'utf8');
 assert.equal(engine.match(/public static final String RUNTIME_VERSION="([^"]+)";/)?.[1],runtime.version);
});
test('native cache profiles are revision-bound and only attached to admitted predictors',async()=>{
 const runtime=JSON.parse(fs.readFileSync(path.join(__dirname,'../android/native-runtime.json'),'utf8')),mdx=fs.readFileSync(path.join(__dirname,'../web/background/native-mdx.js'),'utf8');
 const {create,profile}=adapter();assert.equal(profile,'native-deux-onnxruntime-android-'+runtime.version+'-v1');
 assert.match(mdx,new RegExp("native-mdx-onnxruntime-android-"+runtime.version.replace(/\./g,'\\.')+"-v1"));
 const unavailable=create({nativeDeuxAvailability(){return JSON.stringify({available:false});}},'job');
 assert.equal(unavailable,undefined,'a fallback predictor was incorrectly admitted');
 const token='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',url='https://appassets.androidplatform.net/background/native/'+token+'.bin';
 const admitted=create({nativeDeuxAvailability(){return JSON.stringify({available:true});},nativeDeuxStart(){return JSON.stringify({token,state:'completed',url});},nativeDeuxRelease(){return '{}';}},'job');
 assert.equal(admitted.analysisCacheProfile,profile);
});
test('confirmed native unavailability selects the existing same-model path before any native work',()=>{
 const {create,logs}=adapter();let availabilityCalls=0,compatibilityMessage;
 const bridge={nativeDeuxAvailability(id){assert.equal(id,'job');availabilityCalls++;return JSON.stringify({available:false,reason:'previous-native-crash'});},
  nativeDeuxStart(){assert.fail('JNI start must not be called');},nativeDeuxStatus(){assert.fail('no native polling');},nativeDeuxRelease(){assert.fail('no native session created');}};
 assert.equal(create(bridge,'job',message=>{compatibilityMessage=message;}),undefined);
 assert.equal(availabilityCalls,1);assert.match(compatibilityMessage,/same Studio models/);assert.match(compatibilityMessage,/longer/);
 assert.equal(logs.length,1);assert.equal(logs[0][1],'native-compatibility');
});
test('native compatibility query failures are surfaced instead of silently changing runtimes',()=>{
 for(const response of ['{',JSON.stringify({error:'Could not save compatibility state.'}),JSON.stringify({available:'false'}),JSON.stringify({})]){
  const {create}=adapter();assert.throws(()=>create({nativeDeuxAvailability(){return response;},nativeDeuxStart(){assert.fail('must not start');}},'job'));
 }
 const {create}=adapter();assert.throws(()=>create({nativeDeuxAvailability(){throw Error('bridge disconnected');},nativeDeuxStart(){}},'job'),/disconnected/);
});
test('available runtimes and older bridges retain native prediction and release',async()=>{
 for(const availability of [undefined,()=>JSON.stringify({available:true,runtime:'1.25.1'})]){
  const {create,logs}=adapter();let started=0,released=0;
  const token='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',url='https://appassets.androidplatform.net/background/native/'+token+'.bin';
  const bridge={nativeDeuxStart(id,sample){assert.equal(id,'job');assert.equal(sample,-66150);started++;return JSON.stringify({token,state:'completed',url,message:'Complete'});},nativeDeuxRelease(){released++;return '{}';}};
  if(availability)bridge.nativeDeuxAvailability=availability;
  const predict=create(bridge,'job',()=>assert.fail('native is available'));
  assert.equal(typeof predict,'function');assert.equal((await predict(-66150)).url,url);predict.release();
  assert.equal(started,1);assert.equal(released,1);assert.equal(logs.length,0);
 }
});
const wasmCacheIdentity=values=>({schemaVersion:1,persistent:true,verified:true,execution:'wasm-v1',refreshEpoch:null,nativeRuntimeProfile:'wasm',...values});
test('service runner rejects a completed v8 result when its exact analysis cache identity changed',async()=>{
 let complete,failed;
 const finished=new Promise((resolve,reject)=>{complete=resolve;failed=reject;});
 const events=[],expected=wasmCacheIdentity({workId:'fresh-work',implementationFingerprint:'fresh-implementation',assetFingerprint:'fresh-assets'});
 const request={projectId:'stale-show',name:'Stale show',duration:12,analysisIdentity:'saved-analysis-identity',needAnalysis:false,settings:{analysisQuality:'precision',sensitivity:70},
  music:{duration:12,analysisVersion:8,engine:{cacheIdentity:wasmCacheIdentity({workId:'old-work',implementationFingerprint:'old-implementation',assetFingerprint:'old-assets'})}}};
 const context={URL,AbortController,DOMException,setTimeout,navigator:{},location:{href:'https://appassets.androidplatform.net/background/runner.html?job=job'},
  fetch:async url=>{assert.equal(url,'/background/request.json');return {ok:true,json:async()=>request};},
  MusicAnalyzer:{async cacheIdentity(options){events.push('identity');assert.equal(options.analysisIdentity,'saved-analysis-identity');assert.equal(options.nativeRuntimeProfile,undefined);return expected;},
   async analyze(url,options,report){events.push('analyze');assert.equal(options.nativeRuntimeProfile,undefined);report({progress:.5,stage:'rhythm',detail:'Fresh evidence'});return {duration:12,analysisVersion:8,engine:{cacheIdentity:expected}};}},
  ShowCompiler:{async generate(music){events.push('compose');assert.equal(music.engine.cacheIdentity.workId,'fresh-work');return {compiled:{sha256:'frames'},show:{version:'planner'}};}},
  LightForgeVersion:{name:'test'},VehicleProfile:{version:'test'},LightForgeDiagnostics:{log(){},progress(){},protectText(){}},
  BackgroundJob:{clearRunObservation(){events.push('clear');return true;},progressInfo(){},checkpoint(id,body){events.push('checkpoint');assert.equal(JSON.parse(body).engine.cacheIdentity.workId,'fresh-work');return true;},
   complete(id,body){events.push('complete');complete(JSON.parse(body));return true;},failed(id,message){failed(Error(message));}}
 };
 context.window=context;vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/background/runner.js'),'utf8'),context);
 const saved=await finished;
 assert.deepEqual(events,['identity','clear','analyze','checkpoint','compose','complete']);
 assert.equal(saved.music.engine.cacheIdentity.workId,'fresh-work');
});
test('service runner retains completed music only for an exact current analysis cache identity',async()=>{
 let complete,failed;
 const finished=new Promise((resolve,reject)=>{complete=resolve;failed=reject;});
 const events=[],identity=wasmCacheIdentity({workId:'same-work',implementationFingerprint:'same-implementation',assetFingerprint:'same-assets'});
 const request={projectId:'reused-show',name:'Reused show',duration:12,analysisIdentity:'saved-analysis-identity',needAnalysis:false,settings:{analysisQuality:'precision',sensitivity:70},
  music:{duration:12,analysisVersion:8,engine:{cacheIdentity:identity}}};
 const context={URL,AbortController,DOMException,setTimeout,navigator:{},location:{href:'https://appassets.androidplatform.net/background/runner.html?job=job'},
  fetch:async()=>({ok:true,json:async()=>request}),
  MusicAnalyzer:{async cacheIdentity(){events.push('identity');return identity;},analyze(){assert.fail('exact completed analysis must be reused for choreography-only work');}},
  ShowCompiler:{async generate(music){events.push('compose');assert.equal(music.engine.cacheIdentity.workId,'same-work');return {compiled:{sha256:'frames'},show:{version:'planner'}};}},
  LightForgeVersion:{name:'test'},VehicleProfile:{version:'test'},
  BackgroundJob:{clearRunObservation(){assert.fail('exact completed analysis must not clear its observation');},progressInfo(){},checkpoint(){events.push('checkpoint');return true;},
   complete(id,body){events.push('complete');complete(JSON.parse(body));return true;},failed(id,message){failed(Error(message));}}
 };
 context.window=context;vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/background/runner.js'),'utf8'),context);
 const saved=await finished;
 assert.deepEqual(events,['identity','checkpoint','compose','complete']);
 assert.equal(saved.needAnalysis,false);
});
test('service runner completes the checkpoint transaction with compatibility routing and unchanged analysis identity',async()=>{
 let complete,failed;
 const finished=new Promise((resolve,reject)=>{complete=resolve;failed=reject;});
 const events=[],progress=[],request={projectId:'preserved-show',name:'Existing show',duration:12,analysisIdentity:'saved-analysis-identity',needAnalysis:true,settings:{analysisQuality:'precision',sensitivity:70}};
 const context={URL,AbortController,DOMException,setTimeout,navigator:{},location:{href:'https://appassets.androidplatform.net/background/runner.html?job=job'},
  fetch:async url=>{assert.equal(url,'/background/request.json');return {ok:true,json:async()=>request};},
  MusicAnalyzer:{async analyze(url,options,report){
   assert.match(url,/\/project\/preserved-show\/audio.wav$/);assert.equal(options.nativePredict,undefined);
   assert.equal(options.analysisQuality,'precision');assert.equal(options.analysisIdentity,'saved-analysis-identity');assert.equal(options.projectId,'preserved-show');
   events.push('analyze');report({progress:.5,stage:'separation',detail:'Studio passage 1',restoredPassages:1,passagesCompleted:1});
   return {duration:12,analysisVersion:6,engine:'deux-original-models'};
  }},
  ShowCompiler:{async generate(music,settings){assert.equal(music.engine,'deux-original-models');assert.equal(settings.analysisQuality,'precision');events.push('compose');return {compiled:{sha256:'frames'},show:{version:'planner'}};}},
  LightForgeVersion:{name:'test'},VehicleProfile:{version:'test'},
  BackgroundJob:{clearRunObservation(id){assert.equal(id,'job');events.push('clear');return true;},nativeDeuxAvailability(){return JSON.stringify({available:false,reason:'previous-native-crash'});},nativeDeuxStart(){assert.fail('fallback must not enter JNI');},
   progressInfo(id,value,detail,info){progress.push({detail,info:JSON.parse(info)});},
   checkpoint(id,body){assert.equal(JSON.parse(body).duration,12);events.push('checkpoint');return true;},
   complete(id,body){events.push('complete');complete(JSON.parse(body));return true;},failed(id,message){failed(Error(message));}}
 };
 context.window=context;vm.runInNewContext(source,context);
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/background/runner.js'),'utf8'),context);
 const saved=await finished;
 assert.deepEqual(events,['clear','analyze','checkpoint','compose','complete']);assert.equal(saved.music.engine,'deux-original-models');assert.equal(saved.needAnalysis,false);
 assert.ok(progress.some(event=>/may take longer/.test(event.detail)));
 assert.ok(progress.some(event=>event.detail==='Compatibility · Studio passage 1'&&event.info.restoredPassages===1));
});
