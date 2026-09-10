/* One bounded GAME passage lane. Models and numerical integration are shared
 * with the parent worker; independent single-thread WASM keeps its kernels. */
'use strict';
importScripts('game.js','vendor/ort.wasm.min.js');
ort.env.wasm.wasmPaths=new URL('vendor/',self.location.href).href;
ort.env.wasm.numThreads=1;
ort.env.wasm.proxy=false;
let game=null,busy=false,closed=false;
self.onmessage=async event=>{
 const message=event.data;
 if(message?.type==='close'){
  closed=true;
  if(game)await game.release();
  self.close();return;
 }
 if(message?.type!=='infer')return;
 const requestId=message.requestId;
 if(busy){self.postMessage({type:'error',requestId,message:'A singing passage is already running.'});return;}
 busy=true;
 try{
  if(closed||!Number.isSafeInteger(requestId)||requestId<1||!(message.buffer instanceof ArrayBuffer)||message.buffer.byteLength<4||message.buffer.byteLength>44100*16*4||message.buffer.byteLength%4||![0,1,2,3,4].includes(message.language)||!Number.isSafeInteger(message.seed)||message.seed<0||message.seed>0xffffffff)throw Error('Invalid parallel singing passage.');
  const pcm=new Float32Array(message.buffer);
  for(const value of pcm)if(!Number.isFinite(value))throw Error('Singing audio contains invalid samples.');
  if(!game)game=await LightForgeGAME.create({ort,baseUrl:new URL('models/game/',self.location.href).href});
  if(closed)throw Error('Singing transcription is closed.');
  if(message.model!==game.manifest.id)throw Error('The singing model does not match its passage.');
  const notes=await game.infer(pcm,message.language,message.seed,progress=>{
   if(!closed)self.postMessage({type:'progress',requestId,progress});
  });
  if(!closed)self.postMessage({type:'result',requestId,model:game.manifest.id,steps:8,samples:pcm.length,language:message.language,seed:message.seed,notes});
 }catch(error){
  if(!closed)self.postMessage({type:'error',requestId,message:String(error.message||error).slice(0,2048)});
 }finally{busy=false;}
};
