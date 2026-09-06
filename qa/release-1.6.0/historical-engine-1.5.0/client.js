/* Each job owns its worker; aborting never leaves old results able to commit. */
(function(root){'use strict';
 const url=new URL('worker.js',document.currentScript.src);
 function run(payload,onProgress=()=>{},signal){return new Promise((resolve,reject)=>{
  if(signal?.aborted){reject(new DOMException('Composition canceled','AbortError'));return;}
  const worker=new Worker(url);let finished=false;
  const finish=(error,value)=>{if(finished)return;finished=true;worker.terminate();signal?.removeEventListener('abort',abort);error?reject(error):resolve(value);};
  const abort=()=>finish(new DOMException('Composition canceled','AbortError'));
  signal?.addEventListener('abort',abort,{once:true});
  worker.onmessage=({data})=>{if(data.type==='progress'){if(!finished)onProgress(data.value);return;}finish(data.type==='error'?new Error(data.message):null,data.value);};
  worker.onerror=e=>finish(new Error(e.message||'The composition worker could not start.'));
  worker.postMessage(payload);
 });}
 root.ShowCompiler={generate:(music,settings,onProgress,signal)=>run({action:'generate',music,settings},onProgress,signal),restore:(compiled,music,settings,onProgress,signal)=>run({action:'restore',compiled,music,settings},onProgress,signal),version:'1.5.0'};
})(window);
