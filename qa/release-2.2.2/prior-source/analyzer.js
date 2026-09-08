/* A fresh worker per model stage releases its entire WASM heap before the next.
 * Completed model work is retained under the source/settings/runtime identity.
 */
(function(scope){'use strict';
const base=new URL('.',document.currentScript.src),STAGES=['rhythm','separation','voice','bass'];
async function analyze(audioUrl,options={},onProgress=()=>{},signal){
 const aborted=()=>new DOMException('Analysis cancelled','AbortError');
 if(signal?.aborted)throw aborted();
 const persistent=/^[a-f0-9]{64}$/.test(options.analysisIdentity||''),identity=persistent?options.analysisIdentity:crypto.randomUUID();
 const {nativePredict,...serializableOptions}=options,hasNative=typeof nativePredict==='function'&&options.analysisQuality!=='balanced';
 const binding={pipeline:'bounded-analysis-v2',release:scope.LightForgeVersion.name,identity,quality:options.analysisQuality==='balanced'?'balanced':'precision',sensitivity:options.sensitivity??.82,bpmOverride:options.bpmOverride??null,execution:hasNative?'native-deux-v1':'wasm-v1'};
 const workId=await scope.LightForgeAnalysisStore.hash(new TextEncoder().encode(JSON.stringify(binding)));
 const id=workId.slice(0,32),cacheKey='stem-'+[id.slice(0,8),id.slice(8,12),id.slice(12,16),id.slice(16,20),id.slice(20)].join('-');
 const runOptions={...serializableOptions,cacheKey,workId,supportsNativeDeux:hasNative},timings={},started=performance.now();let value={},progress=0;
 function runStage(stage){return new Promise((resolve,reject)=>{
  if(signal?.aborted){reject(aborted());return;}
  const worker=new Worker(new URL('worker.js',base)),controller=new AbortController();let finished=false,lastActivity=performance.now(),nativeActive=false;
  const watchdog=setInterval(()=>{if(performance.now()-lastActivity>12*60*1000)end(new Error('Analysis stopped making progress during '+stage+'. Completed passages are saved; resume to continue.'));},15000);
  function cleanup(){clearInterval(watchdog);worker.terminate();controller.abort();signal?.removeEventListener('abort',abort);}
  function end(error,result){if(finished)return;finished=true;cleanup();error?reject(error):resolve(result);}
  function abort(){end(aborted());}
  signal?.addEventListener('abort',abort,{once:true});
  worker.onmessage=e=>{
   if(finished)return;const m=e.data;lastActivity=performance.now();
   if(m.type==='progress'){
    progress=Math.max(progress,Math.min(1,Number(m.value.progress)||0));
    try{onProgress({...m.value,progress,elapsedSeconds:(performance.now()-started)/1000,completedStages:Object.keys(timings).length,restoredStages:Object.values(timings).filter(t=>t.restored).length});}catch(error){end(error);}return;
   }
   if(m.type==='native-deux'){
    if(stage!=='separation'||!hasNative||nativeActive||!Number.isSafeInteger(m.requestId)||!Number.isSafeInteger(m.startSample)){end(new Error('Invalid native studio request.'));return;}
    nativeActive=true;let nativeProgress=-1,nativeMessage='';
    const reportNative=p=>{
     if(finished||!p||!Number.isFinite(p.progress))return;
     if(p.progress<=nativeProgress&&p.message===nativeMessage)return;
     lastActivity=performance.now();nativeProgress=Math.max(nativeProgress,p.progress);nativeMessage=p.message;
     worker.postMessage({type:'native-deux-progress',requestId:m.requestId,value:{progress:Math.max(0,Math.min(1,p.progress)),message:String(p.message||'Studio analysis')}});
    };
    Promise.resolve().then(()=>nativePredict(m.startSample,controller.signal,reportNative)).then(result=>{
     if(finished)return;if(typeof result?.url!=='string')throw Error('Native studio output is unavailable.');
     nativeActive=false;lastActivity=performance.now();worker.postMessage({type:'native-deux-result',requestId:m.requestId,url:result.url});
    }).catch(error=>{if(!finished){nativeActive=false;worker.postMessage({type:'native-deux-result',requestId:m.requestId,error:error.message||String(error)});}});return;
   }
   if(m.type==='result'){timings[stage]={seconds:Number.isFinite(m.seconds)?m.seconds:0,restored:!!m.restored};end(null,m.value);}
   else end(new Error(m.message||'Music analysis failed during '+stage+'.'));
  };
  worker.onerror=e=>end(new Error(e.message||'The '+stage+' engine stopped. Completed passages are saved; reopen and resume.'));
  try{worker.postMessage({audioUrl:String(audioUrl),options:runOptions,stage,value});}catch(error){end(error);}
 });}
 try{
  for(const stage of STAGES){
   try{value=await runStage(stage);}
   catch(error){
    // runStage aborts the native request before releasing its model resources.
    // An in-flight native call can still be winding down; the service owns its
    // final cleanup, and a release error must not mask the original failure.
    if(stage==='separation'&&hasNative&&typeof nativePredict.release==='function')try{await nativePredict.release();}catch{}
    throw error;
   }
   // The worker has fetched and committed every native output by this point.
   // Release native direct buffers before GAME creates its own model heap,
   // including when the separation worker restored a completed checkpoint.
   if(stage==='separation'&&hasNative&&typeof nativePredict.release==='function')await nativePredict.release();
  }
  if(signal?.aborted)throw aborted();
  if(!value?.engine)throw Error('Music analysis ended without a complete result.');
  value.engine.analysisSeconds=Math.round((performance.now()-started)/100)/10;
  value.engine.stages=timings;value.engine.recoverable=persistent;
  // Browsers lack a durable source fingerprint. Keep their audition stems, but
  // do not retain an unreachable checkpoint namespace after successful work.
  if(!persistent)await scope.LightForgeAnalysisStore.discard(workId);
  return value;
 }catch(error){
  if(!persistent)await Promise.allSettled([scope.LightForgeStemCache.discard(cacheKey),scope.LightForgeAnalysisStore.discard(workId)]);
  throw error;
 }
}
scope.MusicAnalyzer={analyze,version:scope.LightForgeVersion.name,engine:'Beat This! transformer · offline'};
})(window);
