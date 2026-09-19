/* A fresh worker per model stage releases its entire WASM heap before the next.
 * Completed model work is retained under the source/settings/runtime identity.
 */
(function(scope){'use strict';
const base=new URL('.',document.currentScript.src),BASE_STAGES=Object.freeze(['rhythm','separation','voice','bass']);
const ANALYSIS_PIPELINE_REVISION='bounded-analysis-v3',ASSET_MANIFEST='ASSET_MANIFEST.json',HEX_256=/^[a-f0-9]{64}$/;
const REQUIRED_IMPLEMENTATION_ASSETS=Object.freeze(['analyzer.js','worker.js','models/features.json','models/model-manifest.json']);
let implementationAssets;
const stagesFor=options=>options?.recurrenceAnalysis===true?[...BASE_STAGES,'recurrence']:BASE_STAGES;
const CACHE_QUERY_EXECUTIONS=Object.freeze({
 'wasm-v1':'wasm',
 'native-deux-v1':'native-deux',
 'native-mdx-v1':'native-mdx',
 'native-game-v1':'native-game',
 'native-deux-v1+native-game-v1':'native-deux+native-game',
 'native-mdx-v1+native-game-v1':'native-mdx+native-game'
});
const normalizeRefreshEpoch=value=>typeof value==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(value)?value.toLowerCase():null;
const validRefreshEpoch=value=>normalizeRefreshEpoch(value)!==null;
const suppliedRefreshEpochIsInvalid=value=>value!==undefined&&value!==null&&value!==''&&!validRefreshEpoch(value);
const validNativeProfile=value=>typeof value==='string'&&/^[A-Za-z0-9._:+-]{1,160}$/.test(value);
function nativeCapabilities(options={}){
 if(options.cacheIdentityQuery===true){
  const execution=options.cacheIdentityExecution,profile=options.cacheIdentityNativeRuntimeProfile,kind=CACHE_QUERY_EXECUTIONS[execution],quality=options.analysisQuality==='balanced'?'balanced':'precision';
  const parts=typeof profile==='string'?profile.split('+'):[],kinds=kind?.split('+')||[];
  const valid=kind==='wasm'?profile==='wasm':validNativeProfile(profile)&&parts.length===kinds.length&&kinds.length>0&&kinds.every((component,i)=>parts[i].startsWith(component+'-')&&(component!=='native-deux'||quality==='precision')&&(component!=='native-mdx'||quality==='balanced'));
  if(valid)return {hasNative:kinds.includes('native-deux'),hasMdx:kinds.includes('native-mdx'),hasGame:kinds.includes('native-game'),execution};
  return {hasNative:false,hasMdx:false,hasGame:false,execution:'invalid-cache-query'};
 }
 const hasNative=typeof options.nativePredict==='function'&&options.analysisQuality!=='balanced',hasMdx=typeof options.nativeMdx==='function'&&options.analysisQuality==='balanced',hasGame=typeof options.nativeGame==='function';
 return {hasNative,hasMdx,hasGame,execution:[hasNative?'native-deux-v1':null,hasMdx?'native-mdx-v1':null,hasGame?'native-game-v1':null].filter(Boolean).join('+')||'wasm-v1'};
}
function nativeRuntimeProfile(options,hasNative,hasMdx,hasGame){
 if(options.cacheIdentityQuery===true){
  const profile=options.cacheIdentityNativeRuntimeProfile;
  return validNativeProfile(profile)?profile:null;
 }
 if(!hasNative&&!hasMdx&&!hasGame)return 'wasm';
 const profile=options.nativeRuntimeProfile;
 if(hasGame){const parts=typeof profile==='string'?profile.split('+'):[],kinds=[hasNative?'native-deux':null,hasMdx?'native-mdx':null,'native-game'].filter(Boolean);if(parts.length!==kinds.length||!kinds.every((kind,i)=>parts[i].startsWith(kind+'-')))return null;}
 return validNativeProfile(profile)?profile:null;
}
function validAssetRecord(value){return !!value&&Number.isSafeInteger(value.bytes)&&value.bytes>0&&typeof value.sha256==='string'&&HEX_256.test(value.sha256);}
async function assetsFingerprint(signal){
 if(implementationAssets)return implementationAssets;
 const response=await fetch(new URL(ASSET_MANIFEST,base),{cache:'no-store',signal});
 if(!response||!response.ok)throw Error('Analysis asset manifest is unavailable.');
 const raw=await response.text(),manifest=JSON.parse(raw);
 for(const path of REQUIRED_IMPLEMENTATION_ASSETS)if(!validAssetRecord(manifest?.[path]))throw Error('Analysis asset manifest is incomplete.');
 const fingerprint=await scope.LightForgeAnalysisStore.hash(new TextEncoder().encode(raw));
 if(!HEX_256.test(fingerprint))throw Error('Analysis asset manifest fingerprint is invalid.');
 implementationAssets={fingerprint};return implementationAssets;
}
async function implementationFingerprint(options,hasNative,hasMdx,hasGame,signal){
 const native=nativeRuntimeProfile(options,hasNative,hasMdx,hasGame);
 try{
  const assets=(await assetsFingerprint(signal)).fingerprint;
  if(!native)throw Error('Native analysis cache profile is unavailable.');
  const fingerprint=await scope.LightForgeAnalysisStore.hash(new TextEncoder().encode(JSON.stringify({schemaVersion:1,pipeline:ANALYSIS_PIPELINE_REVISION,assets,native})));
  if(!HEX_256.test(fingerprint))throw Error('Analysis implementation fingerprint is invalid.');
  return {fingerprint,assets,native,verified:true};
 }catch(error){
  if(error?.name==='AbortError')throw error;
  // A manifest/profile that cannot be proven current must never reuse a
  // completed semantic timeline. Keep analysis available with a fresh,
  // nonpersistent identity and leave verified assets as the only memoized data.
  scope.LightForgeDiagnostics?.log('error','analysis-cache-identity',error);
  return {fingerprint:'unverified-'+crypto.randomUUID(),assets:'unverified',native:native||'unverified',verified:false};
 }
}
async function analysisCacheIdentity(options={},signal,refreshEpoch=null){
 const {hasNative,hasMdx,hasGame,execution}=nativeCapabilities(options),sourcePersistent=HEX_256.test(options.analysisIdentity||''),identity=sourcePersistent?options.analysisIdentity:crypto.randomUUID(),isQuery=options.cacheIdentityQuery===true;
 const queryEpoch=isQuery?normalizeRefreshEpoch(options.cacheIdentityRefreshEpoch):null,explicitEpoch=normalizeRefreshEpoch(refreshEpoch),invalidEpoch=(isQuery&&suppliedRefreshEpochIsInvalid(options.cacheIdentityRefreshEpoch))||(!isQuery&&suppliedRefreshEpochIsInvalid(refreshEpoch));
 const invalidQuery=(isQuery&&execution==='invalid-cache-query')||invalidEpoch,epoch=explicitEpoch||queryEpoch;
 const implementation=invalidQuery?{fingerprint:'unverified-'+crypto.randomUUID(),assets:'unverified',native:'unverified',verified:false}:await implementationFingerprint(options,hasNative,hasMdx,hasGame,signal),persistent=sourcePersistent&&implementation.verified===true&&!invalidQuery;
 const binding={pipeline:ANALYSIS_PIPELINE_REVISION,release:scope.LightForgeVersion?.name||'unknown',identity,refreshEpoch:epoch,quality:options.analysisQuality==='balanced'?'balanced':'precision',sensitivity:options.sensitivity??.82,bpmOverride:options.bpmOverride??null,estimatedPercussionEvidence:options.enableEstimatedPercussionEvidence===true,execution,implementationFingerprint:implementation.fingerprint};
 const workId=await scope.LightForgeAnalysisStore.hash(new TextEncoder().encode(JSON.stringify(binding)));
 return {schemaVersion:1,pipeline:ANALYSIS_PIPELINE_REVISION,persistent,verified:implementation.verified===true,workId,execution,refreshEpoch:epoch,implementationFingerprint:implementation.fingerprint,assetFingerprint:implementation.assets,nativeRuntimeProfile:implementation.native};
}
function createDiagnosticClock(){
 let factory;try{factory=scope.LightForgeDiagnosticClock;}catch(_){return {start:0,now:()=>null,elapsed:()=>0};}
 if(factory&&typeof factory.create==='function')try{
  const clock=factory.create(scope);
  if(clock&&typeof clock.now==='function'&&typeof clock.elapsed==='function')return clock;
 }catch(_){ }
 // Timing is optional. A missing or hostile runtime clock must not prevent
 // analysis, cache recovery, or FSEQ compilation from completing.
 return {start:0,now:()=>null,elapsed:()=>0};
}
function resourceDiagnostics(timings,scheduler,totalWallClockMs){
 const api=scope.LightForgeResourceDiagnostics;
 if(!api||typeof api.pipeline!=='function'||typeof api.validate!=='function')return null;
 const stages={};
 for(const [stage,timing] of Object.entries(timings)){
  const resources=timing?.profile?.resources;
  if(!resources)return null;
  try{if(api.validate(resources)!==true)return null;}catch(_){return null;}
  stages[stage]=resources;
 }
 try{return api.pipeline(stages,scheduler,totalWallClockMs);}catch(error){scope.LightForgeDiagnostics?.log('error','analysis-resource-diagnostics',error);return null;}
}
async function analyze(audioUrl,options={},onProgress=()=>{},signal){
 const aborted=()=>new DOMException('Analysis cancelled','AbortError');
 if(signal?.aborted)throw aborted();
 const {nativePredict,nativeMdx,nativeGame,analysisImplementationFingerprint:ignoredImplementationFingerprint,analysisAssetFingerprint:ignoredAssetFingerprint,nativeRuntimeProfile:ignoredNativeRuntimeProfile,cacheIdentityQuery:ignoredCacheIdentityQuery,cacheIdentityNativeRuntimeProfile:ignoredCacheIdentityNativeRuntimeProfile,cacheIdentityExecution:ignoredCacheIdentityExecution,cacheIdentityRefreshEpoch:ignoredCacheIdentityRefreshEpoch,analysisRefreshEpoch:requestedRefreshEpoch,analysisNativeFallback:requestedNativeFallback,onNativeFallback:requestedNativeFallbackPersistence,...serializableOptions}=options;
 const actualOptions={...serializableOptions,nativePredict,nativeMdx,nativeGame,nativeRuntimeProfile:options.nativeRuntimeProfile};
 if(suppliedRefreshEpochIsInvalid(requestedRefreshEpoch))throw Error('Analysis refresh epoch is invalid. Start a fresh analysis again.');
 const refreshEpoch=normalizeRefreshEpoch(requestedRefreshEpoch);
 const {hasNative,hasMdx,hasGame}=nativeCapabilities(actualOptions),cacheIdentity=await analysisCacheIdentity(actualOptions,signal,refreshEpoch),persistent=cacheIdentity.persistent,workId=cacheIdentity.workId;
 const id=workId.slice(0,32),cacheKey='stem-'+[id.slice(0,8),id.slice(8,12),id.slice(12,16),id.slice(16,20),id.slice(20)].join('-');
 const fallbackDiagnostic=requestedNativeFallback&&typeof requestedNativeFallback==='object'&&typeof requestedNativeFallback.attemptedExecution==='string'&&typeof requestedNativeFallback.reason==='string'?{schemaVersion:1,attemptedExecution:requestedNativeFallback.attemptedExecution.slice(0,80),reason:requestedNativeFallback.reason.slice(0,120),resultExecution:'wasm-v1'}:null;
 const clock=createDiagnosticClock(),runOptions={...serializableOptions,cacheKey,workId,supportsNativeDeux:hasNative,supportsNativeMdx:hasMdx,supportsNativeGame:hasGame,analysisImplementationFingerprint:cacheIdentity.implementationFingerprint,analysisAssetFingerprint:cacheIdentity.assetFingerprint,nativeRuntimeProfile:cacheIdentity.nativeRuntimeProfile},stages=stagesFor(actualOptions),timings={},started=clock.start;let value={},progress=0;
 function runStage(stage){return new Promise((resolve,reject)=>{
  if(signal?.aborted){reject(aborted());return;}
  scope.LightForgeDiagnostics?.log('info','analysis-worker','Stage started: '+stage);
  const worker=new Worker(new URL('worker.js',base)),controller=new AbortController();let finished=false,lastActivity=clock.now(),nativeActive=false,nativeMdxActive=false,nativeGameActive=false;
  const watchdog=setInterval(()=>{if(clock.elapsed(lastActivity)>12*60*1000)end(new Error('Analysis stopped making progress during '+stage+'. Completed passages are saved; resume to continue.'));},15000);
  function cleanup(){clearInterval(watchdog);worker.terminate();controller.abort();signal?.removeEventListener('abort',abort);}
  function end(error,result){if(finished)return;finished=true;scope.LightForgeDiagnostics?.log(error&&error.name!=='AbortError'?'error':'info','analysis-worker',error||'Stage completed: '+stage);cleanup();error?reject(error):resolve(result);}
  function abort(){end(aborted());}
  signal?.addEventListener('abort',abort,{once:true});
  worker.onmessage=e=>{
   if(finished)return;const m=e.data;lastActivity=clock.now();
   if(m.type==='progress'){
    progress=Math.max(progress,Math.min(1,Number(m.value.progress)||0));
    scope.LightForgeDiagnostics?.progress('analysis-worker',{...m.value,stage,progress});
    try{onProgress({...m.value,progress,elapsedSeconds:clock.elapsed(started)/1000,completedStages:Object.keys(timings).length,restoredStages:Object.values(timings).filter(t=>t.restored).length});}catch(error){end(error);}return;
   }
   if(m.type==='native-deux'){
    if(stage!=='separation'||!hasNative||nativeActive||!Number.isSafeInteger(m.requestId)||!Number.isSafeInteger(m.startSample)){end(new Error('Invalid native studio request.'));return;}
    nativeActive=true;let nativeProgress=-1,nativeMessage='';
    const reportNative=p=>{
     if(finished||!p||!Number.isFinite(p.progress))return;
     if(p.progress<=nativeProgress&&p.message===nativeMessage)return;
     lastActivity=clock.now();nativeProgress=Math.max(nativeProgress,p.progress);nativeMessage=p.message;
     worker.postMessage({type:'native-deux-progress',requestId:m.requestId,value:{progress:Math.max(0,Math.min(1,p.progress)),message:String(p.message||'Studio analysis')}});
    };
    Promise.resolve().then(()=>nativePredict(m.startSample,controller.signal,reportNative)).then(result=>{
     if(finished)return;if(typeof result?.url!=='string')throw Error('Native studio output is unavailable.');
     nativeActive=false;lastActivity=clock.now();worker.postMessage({type:'native-deux-result',requestId:m.requestId,url:result.url});
    }).catch(error=>{if(!finished){scope.LightForgeDiagnostics?.log(error?.name==='AbortError'?'info':'error','analysis',error);nativeActive=false;if(error?.name==='AbortError')worker.postMessage({type:'native-deux-result',requestId:m.requestId,aborted:true,message:error.message||'Analysis cancelled'});else worker.postMessage({type:'native-deux-result',requestId:m.requestId,fallback:true,message:typeof error?.message==='string'?error.message.slice(0,320):undefined});}});return;
   }
   if(m.type==='native-mdx'){
    if(stage!=='separation'||!hasMdx||nativeMdxActive||!Number.isSafeInteger(m.requestId)||!(m.buffer instanceof ArrayBuffer)){end(new Error('Invalid native balanced request.'));return;}
    nativeMdxActive=true;let nativeProgress=-1,nativeMessage='';const expectedFloats=m.buffer.byteLength/Float32Array.BYTES_PER_ELEMENT;
    const reportNative=p=>{
     if(finished||!p||!Number.isFinite(p.progress))return;
     if(p.progress<=nativeProgress&&p.message===nativeMessage)return;
     lastActivity=clock.now();nativeProgress=Math.max(nativeProgress,p.progress);nativeMessage=p.message;
     worker.postMessage({type:'native-mdx-progress',requestId:m.requestId,value:{progress:Math.max(0,Math.min(1,p.progress)),message:String(p.message||'Balanced MDX analysis')}});
    };
    Promise.resolve().then(()=>nativeMdx(new Float32Array(m.buffer),controller.signal,reportNative)).then(result=>{
     if(finished)return;nativeMdxActive=false;lastActivity=clock.now();
     const valid=result instanceof Float32Array&&result.length===expectedFloats&&Array.prototype.every.call(result,Number.isFinite);
     if(!valid){worker.postMessage({type:'native-mdx-result',requestId:m.requestId,fallback:true});return;}
     // Transfer only a standalone full ArrayBuffer. Shared buffers and subviews
     // are copied so unrelated samples never cross the worker boundary.
     const fullArrayBuffer=result.buffer instanceof ArrayBuffer&&result.byteOffset===0&&result.byteLength===result.buffer.byteLength;
     const buffer=fullArrayBuffer?result.buffer:Float32Array.from(result).buffer;
     worker.postMessage({type:'native-mdx-result',requestId:m.requestId,buffer},[buffer]);
    }).catch(error=>{if(!finished){scope.LightForgeDiagnostics?.log(error?.name==='AbortError'?'info':'error','analysis',error);nativeMdxActive=false;if(error?.name==='AbortError')worker.postMessage({type:'native-mdx-result',requestId:m.requestId,aborted:true,message:error.message||'Analysis cancelled'});else worker.postMessage({type:'native-mdx-result',requestId:m.requestId,fallback:true,message:typeof error?.message==='string'?error.message.slice(0,320):undefined});}});return;
   }
   if(m.type==='native-game'){
    if(stage!=='voice'||!hasGame||nativeGameActive||!Number.isSafeInteger(m.requestId)||!(m.buffer instanceof ArrayBuffer)||m.buffer.byteLength<4||m.buffer.byteLength>44100*16*4||m.buffer.byteLength%4!==0||![0,1,2,3,4].includes(m.language)||!Number.isInteger(m.seed)||m.seed<0||m.seed>0xffffffff){end(new Error('Invalid native singing request.'));return;}
    const pcm=new Float32Array(m.buffer);if(!pcm.every(Number.isFinite)){end(new Error('Invalid native singing audio.'));return;}
    nativeGameActive=true;let nativeProgress=-1,nativeMessage='';
    const reportNative=p=>{
     if(finished||!p||!Number.isFinite(p.progress))return;
     if(p.progress<=nativeProgress&&p.message===nativeMessage)return;
     lastActivity=clock.now();nativeProgress=Math.max(nativeProgress,p.progress);nativeMessage=p.message;
     worker.postMessage({type:'native-game-progress',requestId:m.requestId,value:{progress:Math.max(0,Math.min(1,p.progress)),message:String(p.message||'Singing transcription')}});
    };
    Promise.resolve().then(()=>nativeGame(pcm,m.language,m.seed,controller.signal,reportNative)).then(notes=>{
     if(finished)return;nativeGameActive=false;lastActivity=clock.now();
     // The GAME adapter validates complete unrounded notes before checkpoint
     // writes or shared stitching. Undefined is an explicit fenced restart.
     worker.postMessage({type:'native-game-result',requestId:m.requestId,...(Array.isArray(notes)?{notes}:{fallback:true})});
    }).catch(error=>{if(!finished){scope.LightForgeDiagnostics?.log(error?.name==='AbortError'?'info':'error','analysis',error);nativeGameActive=false;if(error?.name==='AbortError')worker.postMessage({type:'native-game-result',requestId:m.requestId,aborted:true,message:error.message||'Analysis cancelled'});else worker.postMessage({type:'native-game-result',requestId:m.requestId,fallback:error?.code!=='native-game-retirement-pending',code:error?.code==='native-game-retirement-pending'?error.code:undefined,message:typeof error?.message==='string'?error.message.slice(0,320):undefined});}});return;
   }
   if(m.type==='result'){timings[stage]={seconds:Number.isFinite(m.seconds)?m.seconds:0,restored:!!m.restored,profile:m.profile&&m.profile.schemaVersion===1?m.profile:null};end(null,m.value);}
   else{const error=new Error(m.message||'Music analysis failed during '+stage+'.');if(typeof m.code==='string')error.code=m.code;if(typeof m.stack==='string')error.stack=m.stack.slice(0,8192);end(error);}
  };
  worker.onerror=e=>end(new Error(e.message||'The '+stage+' engine stopped. Completed passages are saved; reopen and resume.'));
  worker.onmessageerror=()=>end(new Error('The '+stage+' engine returned an unreadable response.'));
  try{worker.postMessage({audioUrl:String(audioUrl),options:runOptions,stage,value});}catch(error){end(error);}
 });}
 let schedulerLease=null,schedulerDiagnostics=null,restartWithWasm=false,restartProgress=0,restartReason=null;
 try{
  // This admission gate owns no audio/model state. It only prevents two
  // complete model pipelines from contending for bounded heap/checkpoint IO.
  const scheduler=scope.LightForgeAnalysisScheduler;
  if(scheduler&&typeof scheduler.acquire==='function')try{
   schedulerLease=await scheduler.acquire({key:workId,signal});
   if(schedulerLease&&typeof schedulerLease.diagnostics==='function')schedulerDiagnostics=schedulerLease.diagnostics();
  }catch(error){
   if(error?.name==='AbortError')throw error;
   // Coordination is optional. A buggy/unsupported Web Locks implementation
   // must not turn an otherwise valid offline analysis into a failed show.
   scope.LightForgeDiagnostics?.log('error','analysis-scheduler',error);
  }
  for(const stage of stages){
   try{value=await runStage(stage);}
   catch(error){
    // runStage aborts the native request before releasing its model resources.
    // An in-flight native call can still be winding down; the service owns its
    // final cleanup, and a release error must not mask the original failure.
    if(stage==='separation'){
     if(hasNative&&typeof nativePredict.release==='function')try{await nativePredict.release();}catch{}
     if(hasMdx&&typeof nativeMdx.release==='function')try{await nativeMdx.release();}catch{}
     if((hasMdx&&error?.code==='native-mdx-fallback')||(hasNative&&error?.code==='native-deux-fallback')){restartWithWasm=true;restartProgress=progress;restartReason=error.code;break;}
    }
    if(stage==='voice'){
     if(hasGame&&typeof nativeGame.release==='function')try{await nativeGame.release();}catch(releaseError){if(error?.name!=='AbortError')throw releaseError;}
     if(hasGame&&error?.code==='native-game-fallback'){restartWithWasm=true;restartProgress=progress;restartReason=error.code;break;}
    }
    throw error;
   }
   // The worker has fetched and committed every native output by this point.
   // Release native direct buffers before GAME creates its own model heap,
   // including when the separation worker restored a completed checkpoint.
   if(stage==='separation'){
    if(hasNative&&typeof nativePredict.release==='function')await nativePredict.release();
    if(hasMdx&&typeof nativeMdx.release==='function')await nativeMdx.release();
   }
   if(stage==='voice'&&hasGame&&typeof nativeGame.release==='function')await nativeGame.release();
  }
  if(!restartWithWasm){
   if(signal?.aborted)throw aborted();
   if(!value?.engine)throw Error('Music analysis ended without a complete result.');
   value.engine.analysisSeconds=Math.round(clock.elapsed(started)/100)/10;
   value.engine.stages=timings;value.engine.recoverable=persistent;
   value.engine.cacheIdentity={schemaVersion:cacheIdentity.schemaVersion,pipeline:cacheIdentity.pipeline,persistent:cacheIdentity.persistent,verified:cacheIdentity.verified,execution:cacheIdentity.execution,refreshEpoch:cacheIdentity.refreshEpoch,workId:cacheIdentity.workId,implementationFingerprint:cacheIdentity.implementationFingerprint,assetFingerprint:cacheIdentity.assetFingerprint,nativeRuntimeProfile:cacheIdentity.nativeRuntimeProfile};
   if(schedulerDiagnostics)value.engine.scheduler=schedulerDiagnostics;
   if(fallbackDiagnostic)value.engine.nativeFallback=fallbackDiagnostic;
   const resources=resourceDiagnostics(timings,schedulerDiagnostics,clock.elapsed(started));
   if(resources)value.engine.resourceDiagnostics=resources;
   // Browsers lack a durable source fingerprint. Keep their audition stems, but
   // do not retain an unreachable checkpoint namespace after successful work.
   if(!persistent)await Promise.allSettled([scope.LightForgeAnalysisStore.discard(workId)]);
   return value;
  }
 }catch(error){
  if(!persistent)await Promise.allSettled([scope.LightForgeStemCache.discard(cacheKey),scope.LightForgeAnalysisStore.discard(workId)]);
  throw error;
 }finally{
  // release waits for the origin-wide Web Lock before admitting a queued job.
  // Never replace a completed analysis with an optional diagnostics failure.
  if(schedulerLease&&typeof schedulerLease.release==='function')try{await schedulerLease.release();}catch(error){scope.LightForgeDiagnostics?.log('error','analysis-scheduler',error);}
 }
 if(restartWithWasm){
  // The worker fenced/aborted every native write before reporting this
  // sentinel. A nonpersistent native namespace is intentionally disposable;
  // clear it only after its lease is released and before WASM can be admitted.
  if(!persistent)await Promise.allSettled([scope.LightForgeStemCache.discard(cacheKey),scope.LightForgeAnalysisStore.discard(workId)]);
  // Make the effective runtime durable before opening the new WASM namespace.
  // If that trusted checkpoint cannot be written, fail rather than create
  // retry work that a later process could misidentify as native.
  if(typeof requestedNativeFallbackPersistence==='function'){
   const persisted=await requestedNativeFallbackPersistence({attemptedExecution:cacheIdentity.execution,reason:restartReason||'native-fallback'});
   if(persisted!==true)throw Error('The native fallback checkpoint could not be persisted safely.');
  }
  // Retry only under a distinct verified WASM identity while retaining this
  // fresh-run epoch.
  return analyze(audioUrl,{...actualOptions,nativePredict:undefined,nativeMdx:undefined,nativeGame:undefined,nativeRuntimeProfile:undefined,analysisRefreshEpoch:refreshEpoch,analysisNativeFallback:{attemptedExecution:cacheIdentity.execution,reason:restartReason||'native-fallback'}},value=>{
   const next=Math.max(restartProgress,Math.min(1,Number(value?.progress)||0));
   onProgress({...value,progress:next});
  },signal);
 }
}
scope.MusicAnalyzer={analyze,cacheIdentity:analysisCacheIdentity,version:scope.LightForgeVersion.name,engine:'Beat This! transformer · offline'};
})(window);
