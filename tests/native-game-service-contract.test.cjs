'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

// Wiring checks only. Task lifecycle tests and Android instrumentation cover
// runtime cancellation/retirement; these assertions do not execute JNI.
const service=fs.readFileSync(process.env.LIGHTFORGE_SERVICE_SOURCE||path.join(__dirname,'..','android/src/com/cyberbasslord/lightforge/AnalysisService.java'),'utf8');

test('unknown native retirement blocks all new engines including frozen WASM jobs',()=>{
 const start=service.slice(service.indexOf('private void startEngine('),service.indexOf('private boolean ownsEngine('));
 const guard=start.indexOf('if(!NativeGameTask.runtimeRetirementConfirmed())');
 assert.ok(guard>=0);
 assert.match(start.slice(guard,guard+260),/throw new IOException\("Native singing cleanup could not be confirmed/);
 assert.ok(guard<start.indexOf('boolean forceWasm='));
 assert.ok(guard<start.indexOf('new WebView('));
 assert.ok(guard<start.indexOf('new NativeGameTask('));
});

test('GAME task allocation respects the frozen WASM fence in both quality modes',()=>{
 const fence=service.indexOf('boolean forceWasm="wasm-v1"');
 const allocation=service.indexOf('if(!forceWasm)try{game=new NativeGameTask(this,jobId);}');
 assert.ok(fence>=0&&allocation>fence);
 assert.match(service,/persistNativeFallback\(jobId,"native-game-fallback",balanced\?"native-mdx-v1\+native-game-v1":"native-deux-v1\+native-game-v1"\)/);
 assert.match(service,/nativeGame=game;/);
 assert.match(service,/new JobBridge\(ownedJobId,ownedGeneration,ownedPassage,ownedMdx,ownedGame\)/);
 assert.doesNotMatch(service,/new NativeGame\(/,'the service thread must not initialize the model engine');
});

test('every GAME bridge operation checks renderer generation and task ownership',()=>{
 for(const name of ['Availability','Begin','Append','Run','Status','Release']){
  const start=service.indexOf('public String nativeGame'+name+'(');
  assert.ok(start>=0,name+' bridge method exists');
  const end=service.indexOf('@JavascriptInterface',start+1);
  const method=service.slice(start,end<0?undefined:end);
  assert.match(method,/ownerGame==null\|\|!owns\(id\)/,name+' checks current renderer owner');
  const call=name==='Release'?'releaseIdle':name.toLowerCase();
  assert.ok(method.includes('ownerGame.'+call+'(id'),name+' forwards owner to task');
 }
 assert.match(service,/nativeGameBegin\(String id,long bytes,int language,long seed\)/,'unsigned JavaScript seed must fit Java long');
 assert.match(service,/nativeGameCancel\(String id,String token\)\{if\(ownerGame!=null&&owns\(id\)\)ownerGame.cancel\(id,token\);\}/);
 assert.match(service,/private boolean owns\(String id\)\{return ownerJobId.equals\(id\)&&ownsEngine\(ownerJobId,ownerGeneration\);\}/);
 const fallback=service.slice(service.indexOf('public boolean markAnalysisWasmFallbackWithExecution('),service.indexOf('public boolean clearRunObservation('));
 assert.match(fallback,/synchronized\(engineOwnership\)/);
 assert.match(fallback,/if\(!owns\(id\)\)return false;/);
 assert.match(fallback,/AnalysisJobStore.markAnalysisWasmFallback\(getFilesDir\(\),id,reason,attemptedExecution\)/);
});

test('renderer recovery closes GAME and waits for native retirement before restarting',()=>{
 const recovery=service.slice(service.indexOf('private void handleRendererGone('),service.indexOf('private JSONObject persistNativeFallback('));
 assert.match(recovery,/final NativeGameTask retiredGame=nativeGame;nativeGame=null;/);
 assert.match(recovery,/if\(retiredGame!=null\)retiredGame.close\(\);/);
 assert.match(recovery,/retiredGame==null\|\|retiredGame.isRetired\(\)/);
 assert.ok(recovery.indexOf('retiredGame.isRetired()')<recovery.indexOf('AnalysisRendererRecovery.ready('));
 assert.ok(recovery.indexOf('AnalysisRendererRecovery.ready(')<recovery.indexOf('startEngine(resumed)'));
});

test('shutdown closes GAME and no GAME file transport is exposed',()=>{
 const shutdown=service.slice(service.indexOf('private void shutdown('),service.indexOf('private void releaseEngine('));
 assert.match(shutdown,/NativeGameTask previousGame=nativeGame;nativeGame=null;/);
 assert.match(shutdown,/if\(previousGame!=null\)previousGame.close\(\);/);
 assert.doesNotMatch(service,/\/background\/native-game\//,'bounded note JSON uses the owner-checked status bridge only');
});
