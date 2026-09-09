/* Optional Android bridge for the unchanged balanced UVR MDX graph. */
(function(root){'use strict';
 const BINS=3072,FRAMES=256,INPUT_FLOATS=4*BINS*FRAMES,INPUT_BYTES=INPUT_FLOATS*4,RAW_CHUNK=48*1024;
 const abortError=()=>new DOMException('Analysis cancelled','AbortError');
 const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
 function parse(raw){const value=JSON.parse(raw);if(value?.error)throw Error(value.error);return value;}
 function base64(bytes){
  let encoded='';
  for(let first=0;first<bytes.length;first+=RAW_CHUNK){
   const last=Math.min(bytes.length,first+RAW_CHUNK),part=bytes.subarray(first,last);let text='';
   // Keep the argument list small on WebView versions with a shallow JS stack.
   for(let i=0;i<part.length;i+=8192)text+=String.fromCharCode(...part.subarray(i,Math.min(part.length,i+8192)));
   encoded+=btoa(text);
  }
  return encoded;
 }
 function decodeAudio(buffer){
  if(buffer.byteLength!==INPUT_BYTES)throw Error('Native balanced audio is incomplete.');
  const view=new DataView(buffer),output=new Float32Array(INPUT_FLOATS);
  for(let i=0,at=0;i<output.length;i++,at+=4){const value=view.getFloat32(at,true);if(!Number.isFinite(value))throw Error('Native balanced audio contains invalid samples.');output[i]=value;}
  return output;
 }
 function create(bridge,jobId,onCompatibility=()=>{}){
  if(!bridge||typeof bridge.nativeMdxBegin!=='function'||typeof bridge.nativeMdxAppend!=='function'||typeof bridge.nativeMdxRun!=='function')return undefined;
  try{
   const availability=parse(bridge.nativeMdxAvailability?.(jobId)||'{"available":false}');
   if(typeof availability.available!=='boolean')throw Error('Invalid native balanced compatibility response.');
   if(!availability.available){onCompatibility('Balanced native acceleration is unavailable; using the verified WebAssembly separator.');return undefined;}
  }catch(error){
   // The bridge is deliberately optional. A model/runtime mismatch must not
   // prevent the quality-checked WebAssembly path from completing the show.
   root.LightForgeDiagnostics?.log('warn','native-mdx-compatibility',error);
   onCompatibility('Balanced native acceleration is unavailable; using the verified WebAssembly separator.');
   return undefined;
  }
  let released=false,disabled=false,token=null,activeCall=null;
  const predict=async function(encoded,signal,onProgress=()=>{}){
   if(released)throw Error('The native balanced separator is closed.');
   if(disabled)return undefined;
   if(signal?.aborted)throw abortError();
   if(!(encoded instanceof Float32Array)||encoded.length!==INPUT_FLOATS)throw Error('The native balanced separator received an invalid spectrum.');
   const call=(async()=>{
    let current=null;
    const cancel=()=>{if(current)try{bridge.nativeMdxCancel(jobId,current);}catch{}};
    try{
     const started=parse(bridge.nativeMdxBegin(jobId,encoded.byteLength));current=started.token;token=current;
     if(typeof current!=='string'||!/^[a-f0-9-]{36}$/.test(current))throw Error('Invalid native balanced passage response.');
     signal?.addEventListener('abort',cancel,{once:true});
     const bytes=new Uint8Array(encoded.buffer,encoded.byteOffset,encoded.byteLength);
     for(let first=0;first<bytes.length;first+=RAW_CHUNK){
      if(signal?.aborted)throw abortError();
      const state=parse(bridge.nativeMdxAppend(jobId,current,base64(bytes.subarray(first,Math.min(bytes.length,first+RAW_CHUNK)))));
      if(state.token!==current||state.state!=='uploading')throw Error(state.message||'Native balanced input upload stopped.');
      onProgress({progress:Math.max(0,Math.min(.25,Number(state.progress)||0)),message:state.message||'Sending balanced spectrum'});
     }
     let state=parse(bridge.nativeMdxRun(jobId,current));
     if(state.token!==current)throw Error('Native balanced passage identity changed.');
     while(true){
      if(signal?.aborted)throw abortError();
      if(state.state==='completed'){
       const expected='https://appassets.androidplatform.net/background/native-mdx/'+current+'.bin';
       if(state.url!==expected)throw Error('Invalid native balanced audio response.');
       onProgress({progress:1,message:state.message||'Balanced MDX complete'});
       const response=await fetch(state.url,{cache:'no-store'});if(!response.ok)throw Error('Native balanced audio could not be read.');
       return decodeAudio(await response.arrayBuffer());
      }
      if(state.state!=='running')throw Error(state.message||'Native balanced analysis stopped.');
      onProgress({progress:Math.max(.25,Math.min(.99,Number(state.progress)||0)),message:state.message||'Running balanced MDX'});
      await delay(250);if(signal?.aborted)throw abortError();state=parse(bridge.nativeMdxStatus(jobId,current));
     }
    }catch(error){
     cancel();
     if(error?.name==='AbortError')throw error;
     disabled=true;
     root.LightForgeDiagnostics?.log('warn','native-mdx-fallback',error);
     onCompatibility('Balanced native acceleration stopped; continuing with the verified WebAssembly separator.');
     return undefined;
    }finally{signal?.removeEventListener('abort',cancel);}
   })();
   activeCall=call;
   try{return await call;}finally{if(activeCall===call)activeCall=null;}
  };
  predict.release=async()=>{
   if(released)return;released=true;
   if(activeCall)await activeCall.catch(()=>{});
   if(token&&typeof bridge.nativeMdxStatus==='function'){
    for(let i=0;i<80;i++){
     let state;try{state=parse(bridge.nativeMdxStatus(jobId,token));}catch{break;}
     if(state.state!=='running'&&state.state!=='uploading')break;
     try{bridge.nativeMdxCancel(jobId,token);}catch{}await delay(100);
    }
   }
   if(typeof bridge.nativeMdxRelease==='function')try{const value=parse(bridge.nativeMdxRelease(jobId));if(value.error)throw Error(value.error);}catch(error){root.LightForgeDiagnostics?.log('warn','native-mdx-release',error);}
  };
  return predict;
 }
 root.LightForgeNativeMdx={create,constants:{BINS,FRAMES,INPUT_FLOATS,INPUT_BYTES}};
})(window);
