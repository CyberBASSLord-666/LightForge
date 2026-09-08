/* Each job owns its worker; aborting never leaves old results able to commit. */
(function(root){'use strict';
 const url=new URL('worker.js',document.currentScript.src);
 function run(payload,onProgress=()=>{},signal){return new Promise((resolve,reject)=>{
  if(signal?.aborted){reject(new DOMException('Composition canceled','AbortError'));return;}
  root.LightForgeDiagnostics?.log('info','composition-worker',payload.action==='restore'?'Verifying saved arrangement':'Composition started');
  const worker=new Worker(url);let finished=false;
  const finish=(error,value)=>{if(finished)return;finished=true;root.LightForgeDiagnostics?.log(error&&error.name!=='AbortError'?'error':'info','composition-worker',error||'Composition completed');worker.terminate();signal?.removeEventListener('abort',abort);error?reject(error):resolve(value);};
  const abort=()=>finish(new DOMException('Composition canceled','AbortError'));
  signal?.addEventListener('abort',abort,{once:true});
  worker.onmessage=({data})=>{if(data.type==='progress'){if(!finished){root.LightForgeDiagnostics?.progress('composition-worker',{...data.value,stage:'generate'});onProgress(data.value);}return;}let error=null;if(data.type==='error'){error=new Error(data.message);if(typeof data.stack==='string')error.stack=data.stack.slice(0,8192);}finish(error,data.value);};
  worker.onerror=e=>finish(new Error(e.message||'The composition worker could not start.'));
  worker.onmessageerror=()=>finish(new Error('The composition worker returned an unreadable response.'));
  try{worker.postMessage(payload);}catch(error){finish(error);}
 });}
 root.ShowCompiler={generate:(music,settings,onProgress,signal)=>run({action:'generate',music,settings},onProgress,signal),restore:(compiled,music,settings,onProgress,signal)=>run({action:'restore',compiled,music,settings},onProgress,signal),version:root.LightForgeVersion.name};
})(window);
