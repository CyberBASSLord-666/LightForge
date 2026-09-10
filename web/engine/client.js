/* Each job owns its worker; aborting never leaves old results able to commit. */
(function(root){'use strict';
 const url=new URL('worker.js',document.currentScript.src),RESTORE_STARTUP_TIMEOUT_MS=7500;
 function run(payload,onProgress=()=>{},signal,{retryStartup=false}={}){return new Promise((resolve,reject)=>{
  if(signal?.aborted){reject(new DOMException('Composition canceled','AbortError'));return;}
  root.LightForgeDiagnostics?.log('info','composition-worker',payload.action==='restore'?'Verifying saved arrangement':'Composition started');
  let worker,finished=false,attempt=0,startupTimer=null;
  const clearStartupTimer=()=>{if(startupTimer!==null){clearTimeout(startupTimer);startupTimer=null;}};
  const finish=(error,value)=>{if(finished)return;finished=true;clearStartupTimer();root.LightForgeDiagnostics?.log(error&&error.name!=='AbortError'?'error':'info','composition-worker',error||'Composition completed');worker?.terminate();signal?.removeEventListener('abort',abort);error?reject(error):resolve(value);};
  const abort=()=>finish(new DOMException('Composition canceled','AbortError'));
  const start=()=>{
   let activeWorker,activeAttempt;
   try{activeWorker=new Worker(url);activeAttempt=++attempt;worker=activeWorker;}catch(error){finish(error);return;}
   activeWorker.onmessage=({data})=>{
    if(finished||activeAttempt!==attempt)return;
    // Ready is sent after imports. Any response is also proof of startup so a
    // cached older worker cannot be retried while it is already composing.
    clearStartupTimer();if(data.type==='ready')return;
    if(data.type==='progress'){root.LightForgeDiagnostics?.progress('composition-worker',{...data.value,stage:'generate'});onProgress(data.value);return;}
    let error=null;if(data.type==='error'){error=new Error(data.message);if(typeof data.stack==='string')error.stack=data.stack.slice(0,8192);}finish(error,data.value);
   };
   activeWorker.onerror=e=>{if(activeAttempt===attempt)finish(new Error(e.message||'The composition worker could not start.'));};
   activeWorker.onmessageerror=()=>{if(activeAttempt===attempt)finish(new Error('The composition worker returned an unreadable response.'));};
   if(retryStartup){
    startupTimer=setTimeout(()=>{
     if(finished||activeAttempt!==attempt)return;
     if(activeAttempt===1){root.LightForgeDiagnostics?.log('info','composition-worker','Restore worker did not become ready; recreating it once.');activeWorker.terminate();start();}
     else finish(new Error('The saved arrangement verification worker did not become ready. Please reopen the project and try again.'));
    },RESTORE_STARTUP_TIMEOUT_MS);
   }
   try{activeWorker.postMessage(payload);}catch(error){finish(error);}
  };
  signal?.addEventListener('abort',abort,{once:true});start();
 });}
 root.ShowCompiler={generate:(music,settings,onProgress,signal)=>run({action:'generate',music,settings},onProgress,signal),restore:(compiled,music,settings,onProgress,signal,options)=>run({action:'restore',compiled,music,settings},onProgress,signal,options),version:root.LightForgeVersion.name};
})(window);
