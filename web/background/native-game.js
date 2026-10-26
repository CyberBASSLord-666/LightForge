/* Optional Android execution of the unchanged GAME graphs and diffusion steps. */
(function(root){'use strict';
 const ANALYSIS_CACHE_PROFILE='native-game-onnxruntime-android-1.25.1-v1';
 const RATE=44100,MAX_SAMPLES=16*RATE,RAW_CHUNK=48*1024,MODEL='game-large-1.0.3-lightforge-1',PAIR_PROTOCOL='native-game-pair-v1';
 const abortError=()=>new DOMException('Analysis cancelled','AbortError');
 const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
 const parse=raw=>{const value=JSON.parse(raw);if(!value||typeof value!=='object'||value.error)throw Error(value?.error||'Invalid native singing response.');return value;};
 function retirementError(){const error=Error('Native singing cleanup could not be confirmed. Restart LightForge before resuming analysis.');error.code='native-game-retirement-pending';return error;}
 function pack(pcm){const bytes=new Uint8Array(pcm.length*4),view=new DataView(bytes.buffer);for(let i=0;i<pcm.length;i++){if(!Number.isFinite(pcm[i]))throw Error('Singing input contains invalid samples.');view.setFloat32(i*4,pcm[i],true);}return bytes;}
 function encode(bytes){let text='';for(let i=0;i<bytes.length;i+=8192)text+=String.fromCharCode(...bytes.subarray(i,i+8192));return btoa(text);}
 function result(state,samples,language,seed){
  if(state.sampleRate!==RATE||state.samples!==samples||state.language!==language||state.seed!==seed||state.steps!==8||state.model!==MODEL||!Array.isArray(state.notes)||state.notes.length>1601)throw Error('Native singing result identity is invalid.');
  let end=0;const duration=samples/RATE;
  return state.notes.map(note=>{
   if(!note||!Number.isFinite(note.start)||!Number.isFinite(note.end)||!Number.isFinite(note.midi)||note.start<0||note.start<end-1e-6||note.end-note.start<.06-1e-6||note.end>duration+.001||note.midi<0||note.midi>127)throw Error('Native singing notes are invalid.');
   end=note.end;return {start:note.start,end:note.end,midi:note.midi};
  });
 }
 function create(bridge,jobId,onCompatibility=()=>{}){
  if(!bridge||['Availability','Begin','Append','Run','Status','Cancel','Release'].some(name=>typeof bridge['nativeGame'+name]!=='function'))return undefined;
  let batchAvailable=false;
  try{
   const availability=parse(bridge.nativeGameAvailability(jobId));
   if(availability.available!==true){onCompatibility('Native singing acceleration is unavailable; using verified WebAssembly.');return undefined;}
   batchAvailable=availability.batchProtocol===PAIR_PROTOCOL&&availability.maxBatchPassages===2&&availability.maxBatchInputBytes===2*MAX_SAMPLES*4&&typeof bridge.nativeGameBeginBatch==='function';
  }catch(error){root.LightForgeDiagnostics?.log('warn','native-game-compatibility',error);onCompatibility('Native singing acceleration is unavailable; using verified WebAssembly.');return undefined;}
  let released=false,disabled=false,busy=false,token=null,activeCall=null,cleanupUnknown=false;
  const cancel=()=>{if(token)try{bridge.nativeGameCancel(jobId,token);}catch{}};
  async function retire(){
   if(cleanupUnknown)throw retirementError();
   if(token){
    let terminal=false;
    for(let attempt=0;attempt<200;attempt++){
     let state;try{state=parse(bridge.nativeGameStatus(jobId,token));}catch{throw retirementError();}
     if(state.token!==token)throw retirementError();
     if(['completed','failed','cancelled'].includes(state.state)){terminal=true;break;}
     if(!['running','uploading'].includes(state.state))throw retirementError();
     cancel();await delay(100);
    }
    if(!terminal)throw retirementError();
   }
   try{parse(bridge.nativeGameRelease(jobId));}catch{throw retirementError();}
   token=null;
  }
  function pairIdentity(state,requests){
   if(state.batchProtocol!==PAIR_PROTOCOL||!Array.isArray(state.passages)||state.passages.length!==2)throw Error('Native singing pair identity is invalid.');
   for(let i=0;i<2;i++){const descriptor=state.passages[i],request=requests[i];if(!descriptor||Object.keys(descriptor).length!==3||descriptor.samples!==request.pcm.length||descriptor.language!==request.language||descriptor.seed!==request.seed)throw Error('Native singing pair passage identity is invalid.');}
  }
  const invoke=async(requests,batch,signal,onProgress=()=>{})=>{
   if(released)throw Error('Native singing transcription is closed.');
   if(disabled)return undefined;
   if(busy)throw Error('A native singing passage is already active.');
   if(signal?.aborted)throw abortError();
   if(!Array.isArray(requests)||requests.length!==(batch?2:1))throw Error('Invalid native singing input.');
   if(!requests[0]||(batch&&!requests[1]))throw Error('Invalid native singing input.');
   const payloads=requests.map(request=>{if(!request||!(request.pcm instanceof Float32Array)||request.pcm.length<1||request.pcm.length>MAX_SAMPLES||![0,1,2,3,4].includes(request.language)||!Number.isInteger(request.seed)||request.seed<0||request.seed>0xffffffff)throw Error('Invalid native singing input.');return pack(request.pcm);});
   const descriptors=requests.map(({pcm,language,seed})=>({samples:pcm.length,language,seed}));busy=true;
   const call=(async()=>{
    try{
     const request=requests[0],started=parse(batch?bridge.nativeGameBeginBatch(jobId,JSON.stringify(descriptors)):bridge.nativeGameBegin(jobId,payloads[0].length,request.language,request.seed));
     token=started.token;
     if(typeof token!=='string'||!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(token)){cleanupUnknown=true;throw retirementError();}
     if(batch)pairIdentity(started,requests);
     signal?.addEventListener('abort',cancel,{once:true});
     for(const bytes of payloads)for(let first=0;first<bytes.length;first+=RAW_CHUNK){
      if(signal?.aborted||released)throw abortError();
      const state=parse(bridge.nativeGameAppend(jobId,token,encode(bytes.subarray(first,first+RAW_CHUNK))));
      if(state.token!==token||state.state!=='uploading')throw Error('Native singing input upload stopped.');
      if(batch)pairIdentity(state,requests);
      onProgress({progress:Math.max(0,Math.min(.2,Number(state.progress)||0)),message:'Sending singing passage to Android'});
     }
     if(signal?.aborted||released)throw abortError();
     let state=parse(bridge.nativeGameRun(jobId,token));
     while(true){
      if(signal?.aborted||released)throw abortError();
      if(state.token!==token)throw Error('Native singing passage identity changed.');
      if(batch)pairIdentity(state,requests);
      if(state.state==='completed'){
       if(batch&&(!Array.isArray(state.notes)||state.notes.length!==2))throw Error('Native singing pair notes are incomplete.');
       const notes=batch?requests.map((request,index)=>result({...state,...descriptors[index],notes:state.notes[index]},request.pcm.length,request.language,request.seed)):result(state,request.pcm.length,request.language,request.seed);await retire();
       onProgress({progress:1,message:'Native singing transcription complete'});
       if(signal?.aborted||released)throw abortError();return notes;
      }
      if(state.state!=='running')throw Error('Native singing transcription stopped.');
      onProgress({progress:Math.max(.2,Math.min(.99,Number(state.progress)||0)),message:'Running singing transcription on Android'});
      await delay(250);state=parse(bridge.nativeGameStatus(jobId,token));
     }
    }catch(error){
     cancel();await retire();
     if(signal?.aborted||released)throw abortError();
     if(error?.name==='AbortError')throw error;
     disabled=true;root.LightForgeDiagnostics?.log('warn','native-game-fallback',error);
     onCompatibility('Native singing acceleration stopped; restarting with verified WebAssembly.');return undefined;
    }finally{signal?.removeEventListener('abort',cancel);}
   })();
   activeCall=call;try{return await call;}finally{busy=false;if(activeCall===call)activeCall=null;}
  };
  const predict=(pcm,language,seed,signal,onProgress)=>invoke([{pcm,language,seed}],false,signal,onProgress);
  if(batchAvailable)predict.batch=(requests,signal,onProgress)=>invoke(requests,true,signal,onProgress);
  predict.release=async()=>{
   if(released&&!activeCall&&!token&&!cleanupUnknown)return;
   released=true;cancel();if(activeCall)await activeCall.catch(()=>{});await retire();
  };
  predict.analysisCacheProfile=ANALYSIS_CACHE_PROFILE;
  return predict;
 }
 root.LightForgeNativeGame={create,analysisCacheProfile:ANALYSIS_CACHE_PROFILE,constants:{RATE,MAX_SAMPLES,MODEL}};
})(window);
