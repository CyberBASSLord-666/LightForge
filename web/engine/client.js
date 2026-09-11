/* Each job owns its worker; aborting never leaves old results able to commit. */
(function(root){'use strict';
 const url=new URL('worker.js',document.currentScript.src);
 function run(payload,onProgress=()=>{},signal,{restoreLease=null,onRestoreEvent=null}={}){return new Promise((resolve,reject)=>{
  if(signal?.aborted){reject(new DOMException('Composition canceled','AbortError'));return;}
  root.LightForgeDiagnostics?.log('info','composition-worker',payload.action==='restore'?'Verifying saved arrangement':'Composition started');
  let worker,finished=false,attempt=0,restoreStage=0;
  const restoreEvent=data=>{
   if(!restoreLease||typeof onRestoreEvent!=='function')return;
   // The browser lease is an ordered proof, not a generic worker-status
   // channel.  Ready is intentionally outside this protocol; a later/stale
   // message may not synthesize liveness or a terminal proof.
   if(data.type==='restore-started'){if(restoreStage!==0)return;restoreStage=1;}
   else if(data.type==='restore-pulse'){if(restoreStage!==1)return;}
   else if(data.type==='restore-verified'){if(restoreStage!==1)return;restoreStage=2;}
   else if(data.type==='restore-error'){if(restoreStage===3)return;restoreStage=3;}
   else return;
   try{onRestoreEvent({...data,lease:restoreLease});}catch(error){root.LightForgeDiagnostics?.log('error','composition-worker',error);}
  };
  const finish=(error,value)=>{if(finished)return;finished=true;root.LightForgeDiagnostics?.log(error&&error.name!=='AbortError'?'error':'info','composition-worker',error||'Composition completed');worker?.terminate();signal?.removeEventListener('abort',abort);error?reject(error):resolve(value);};
  const abort=()=>finish(new DOMException('Composition canceled','AbortError'));
  const start=()=>{
   let activeWorker,activeAttempt;
   try{activeWorker=new Worker(url);activeAttempt=++attempt;worker=activeWorker;}catch(error){finish(error);return;}
   activeWorker.onmessage=({data})=>{
    if(finished||activeAttempt!==attempt)return;
    // Ready proves only the import graph; a completed restore advances only
    // through its explicit request-scoped events below.
    if(data.type==='ready')return;
    if(data.type==='restore-started'||data.type==='restore-pulse'||data.type==='restore-verified'||data.type==='restore-error'){
     if(data.lease?.jobId!==restoreLease?.jobId||data.lease?.nonce!==restoreLease?.nonce)return;
     restoreEvent({...data,attempt:activeAttempt});return;
    }
    if(data.type==='progress'){root.LightForgeDiagnostics?.progress('composition-worker',{...data.value,stage:'generate'});onProgress(data.value);return;}
    if(data.type==='result'&&restoreLease&&restoreStage!==2){
     const error=new Error('Completed restore ended without verified worker proof.');restoreEvent({type:'restore-error',message:error.message,attempt:activeAttempt});finish(error);return;
    }
    let error=null;if(data.type==='error'){error=new Error(data.message);if(typeof data.stack==='string')error.stack=data.stack.slice(0,8192);restoreEvent({type:'restore-error',message:data.message,attempt:activeAttempt});}finish(error,data.value);
   };
   activeWorker.onerror=e=>{if(activeAttempt===attempt){restoreEvent({type:'restore-error',message:e.message||'The composition worker could not start.',attempt:activeAttempt});finish(new Error(e.message||'The composition worker could not start.'));}};
   activeWorker.onmessageerror=()=>{if(activeAttempt===attempt){restoreEvent({type:'restore-error',message:'The composition worker returned an unreadable response.',attempt:activeAttempt});finish(new Error('The composition worker returned an unreadable response.'));}};
   try{activeWorker.postMessage(restoreLease?{...payload,restoreLease:{jobId:restoreLease.jobId,nonce:restoreLease.nonce}}:payload);}catch(error){restoreEvent({type:'restore-error',message:error.message||String(error),attempt:activeAttempt});finish(error);}
  };
  signal?.addEventListener('abort',abort,{once:true});start();
 });}
 root.ShowCompiler={generate:(music,settings,onProgress,signal)=>run({action:'generate',music,settings},onProgress,signal),restore:(compiled,music,settings,onProgress,signal,options)=>run({action:'restore',compiled,music,settings},onProgress,signal,options),version:root.LightForgeVersion.name};
})(window);
