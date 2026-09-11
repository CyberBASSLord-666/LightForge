/* The service performs native CPU inference; audio remains in private app storage. */
(function(root){'use strict';
 const ANALYSIS_CACHE_PROFILE='native-deux-onnxruntime-android-1.25.1-v1';
 const abortError=()=>new DOMException('Analysis cancelled','AbortError');
 function create(bridge,jobId,onCompatibility=()=>{}){
  if(!bridge||typeof bridge.nativeDeuxStart!=='function')return undefined;
  if(typeof bridge.nativeDeuxAvailability==='function'){
   const availability=JSON.parse(bridge.nativeDeuxAvailability(jobId));
   if(availability.error)throw Error(availability.error);
   if(typeof availability.available!=='boolean')throw Error('Invalid native compatibility response.');
   if(!availability.available){
    const message='Compatibility processing enabled after a native crash. The same Studio models are used; analysis may take longer.';
    root.LightForgeDiagnostics?.log('warn','native-compatibility',message);
    onCompatibility(message);return undefined;
   }
  }
  const predict=async function(startSample,signal,onProgress=()=>{}){
   if(signal?.aborted)throw abortError();
   if(!Number.isSafeInteger(startSample)||startSample< -66150||startSample>44100*14400)throw Error('Invalid native passage position.');
   const decode=raw=>{const value=JSON.parse(raw);if(value.error)throw Error(value.error);return value;};
   let value=decode(bridge.nativeDeuxStart(jobId,startSample));const token=value.token;
   if(typeof token!=='string'||!/^[a-f0-9-]{36}$/.test(token))throw Error('Invalid native passage response.');
   const cancel=()=>{try{bridge.nativeDeuxCancel(jobId,token);}catch{}};
   signal?.addEventListener('abort',cancel,{once:true});
   try{
    while(true){
     if(signal?.aborted)throw abortError();
     if(value.token!==token)throw Error('Native passage identity changed.');
     if(value.state==='completed'){
      const expected='https://appassets.androidplatform.net/background/native/'+token+'.bin';
      if(value.url!==expected)throw Error('Invalid native audio response.');
      onProgress({progress:1,message:value.message});return {url:value.url};
     }
     if(value.state!=='running')throw Error(value.message||'Native Studio analysis stopped. Completed passages remain saved.');
     onProgress({progress:Math.max(0,Math.min(1,Number(value.progress)||0)),message:value.message||'Native Studio analysis'});
     await new Promise(resolve=>setTimeout(resolve,500));
     if(signal?.aborted)throw abortError();
     value=decode(bridge.nativeDeuxStatus(jobId,token));
    }
   }catch(error){cancel();throw error;}finally{signal?.removeEventListener('abort',cancel);}
  };
  predict.release=()=>{if(typeof bridge.nativeDeuxRelease==='function'){const result=JSON.parse(bridge.nativeDeuxRelease(jobId));if(result.error)throw Error(result.error);}};
  // The profile is attached only after a real predictor is admitted. A
  // compatibility fallback must remain a wasm cache identity.
  predict.analysisCacheProfile=ANALYSIS_CACHE_PROFILE;
  return predict;
 }
 root.LightForgeNativeDeux={create,analysisCacheProfile:ANALYSIS_CACHE_PROFILE};
})(window);
