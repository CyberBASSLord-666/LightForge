'use strict';
// Probe-only bootstrap. The production worker and all imported scripts stay unchanged.
const probeRun=Number(new URL(self.location.href).searchParams.get('run'));
if(![1,4].includes(probeRun))throw Error('Invalid probe thread count');
Object.defineProperty(navigator,'hardwareConcurrency',{value:probeRun===1?2:8,configurable:true});
let probeStage=null,sessionSequence=0,wrapped=false;
self.addEventListener('message',event=>{if(event.data?.stage)probeStage=event.data.stage;});
const realImport=importScripts.bind(self);
async function sendRecord(value){
 const response=await fetch('/__thread-probe/record',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run:probeRun,...value})});
 const reply=await response.json();if(!response.ok||!reply.accepted)throw Error(reply.error||'Exact thread qualification stopped');
}
async function hashTensors(tensors){
 const result={};
 for(const name of Object.keys(tensors).sort()){
  const t=tensors[name],raw=new Uint8Array(t.data.buffer,t.data.byteOffset,t.data.byteLength).slice();
  const digest=await crypto.subtle.digest('SHA-256',raw);
  result[name]={type:t.type,dims:Array.from(t.dims),bytes:raw.byteLength,sha256:Array.from(new Uint8Array(digest),x=>x.toString(16).padStart(2,'0')).join('')};
 }
 return result;
}
self.importScripts=(...urls)=>{
 realImport(...urls);
 if(!wrapped&&self.ort){
  wrapped=true;const originalCreate=ort.InferenceSession.create.bind(ort.InferenceSession);
  ort.InferenceSession.create=async function(source,options){
   if(ort.env.wasm.numThreads!==probeRun||!crossOriginIsolated||typeof SharedArrayBuffer!=='function')throw Error('Requested original thread policy was not active');
   const sessionId=++sessionSequence,modelPath=new URL(String(source),self.location.href).pathname;
   await sendRecord({type:'session',stage:probeStage,sessionId,modelPath,threads:ort.env.wasm.numThreads,hardwareConcurrency:navigator.hardwareConcurrency,crossOriginIsolated,sharedArrayBuffer:typeof SharedArrayBuffer==='function',options:JSON.parse(JSON.stringify(options))});
   const session=await originalCreate(source,options),originalRun=session.run.bind(session);let call=0;
   session.run=async function(feeds,...rest){
    const inputs=await hashTensors(feeds),started=performance.now(),outputs=await originalRun(feeds,...rest),seconds=(performance.now()-started)/1000;
    await sendRecord({type:'graph',stage:probeStage,sessionId,call:++call,modelPath,threads:ort.env.wasm.numThreads,inputs,outputs:await hashTensors(outputs),seconds});
    return outputs;
   };
   return session;
  };
 }
};
importScripts('worker.js');
