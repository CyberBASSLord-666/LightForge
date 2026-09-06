/* Public entry point. Every model and runtime asset is packaged with the APK. */
(function(scope){'use strict';
const base=new URL('.',document.currentScript.src);
function analyze(audioUrl,options={},onProgress=()=>{},signal){return new Promise((resolve,reject)=>{
 if(signal&&signal.aborted){reject(new DOMException('Analysis cancelled','AbortError'));return;}
 const cacheKey='stem-'+crypto.randomUUID(),worker=new Worker(new URL('worker.js',base));let finished=false;
 const discard=()=>scope.LightForgeStemCache?.discard(cacheKey);
 function cleanup(){worker.terminate();if(signal)signal.removeEventListener('abort',abort);}
 function abort(){if(finished)return;finished=true;cleanup();discard();reject(new DOMException('Analysis cancelled','AbortError'));}
 if(signal)signal.addEventListener('abort',abort,{once:true});
 worker.onmessage=e=>{const m=e.data;if(m.type==='progress'){onProgress(m.value);return;}if(finished)return;finished=true;cleanup();if(m.type==='result')resolve(m.value);else{discard();reject(new Error(m.message||'Music analysis failed'));}};
 worker.onerror=e=>{if(finished)return;finished=true;cleanup();discard();reject(new Error(e.message||'The music worker could not start. Restart the app and try again.'));};
 worker.postMessage({audioUrl:String(audioUrl),options:{...options,cacheKey}});
 });}
scope.MusicAnalyzer={analyze,version:'1.6.0',engine:'Beat This! transformer · offline'};
})(window);
