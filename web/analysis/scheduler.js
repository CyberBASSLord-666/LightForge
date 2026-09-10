/*
 * Deterministic admission control for the offline analysis pipeline.
 *
 * A single analysis owns several large WASM and, on supported Android builds,
 * native inference heaps.  Running two complete pipelines at once does not
 * improve one show's result and can cause allocator contention, process death,
 * or two writers racing the same recoverable checkpoint.  This scheduler only
 * controls admission: it never changes an analyser, model, input, output, or
 * stage order.  The Web Locks path additionally serializes heavy work across
 * tabs belonging to the same origin.  Browsers without Web Locks retain the
 * same safe single-context behaviour as before.
 */
(function(root){'use strict';
 const LOCK_NAME='lightforge-analysis-heavy-v1',KEY=/^[a-f0-9]{64}$/;
 const read=(object,key)=>{try{return object==null?undefined:object[key];}catch(_){return undefined;}};
 const number=value=>typeof value==='number'&&Number.isFinite(value)?value:null;
 const invokeNow=(object,key)=>{
  const clock=read(object,key);if(typeof clock!=='function')return null;
  try{return number(clock.call(object));}catch(_){return null;}
 };
 const performanceNow=()=>invokeNow(read(root,'performance'),'now'),dateNow=()=>invokeNow(read(root,'Date'),'now');
 // Select a clock once. Falling from a monotonic performance clock to epoch
 // time after a late hostile getter/call failure would fabricate wait times.
 const createClock=()=>{
  const first=performanceNow();
  if(first!==null){let unavailable=false;return {now(){if(unavailable)return null;const value=performanceNow();if(value===null)unavailable=true;return value;}};}
  const firstDate=dateNow();let unavailable=firstDate===null;
  return {now(){if(unavailable)return null;const value=dateNow();if(value===null)unavailable=true;return value;}};
 };
 const clock=createClock(),now=()=>clock.now(),elapsed=(start,end)=>{
  const first=number(start),last=number(end);return first===null||last===null?0:Math.max(0,last-first);
 };
 const abortError=()=>typeof DOMException==='function'?new DOMException('Analysis cancelled','AbortError'):Object.assign(new Error('Analysis cancelled'),{name:'AbortError'});
 const supportedLocks=()=>{
  const navigatorRef=read(root,'navigator'),locks=read(navigatorRef,'locks'),request=read(locks,'request');
  return typeof request==='function'?{locks,request}:null;
 };
 const state={active:null,queue:[],sequence:0};
 const mode=()=>supportedLocks()?'web-locks':'single-context';
 function snapshot(){return {schemaVersion:1,resourceClass:'analysis-heavy',capacity:1,active:state.active?1:0,queued:state.queue.length,crossContextMode:mode()};}
 function remove(entry){const index=state.queue.indexOf(entry);if(index>=0)state.queue.splice(index,1);}
 async function originLease(entry){
  const lockApi=supportedLocks();
  if(!lockApi)return {mode:'single-context',release:async()=>{}};
  let releaseHeld,resolveAcquired,rejectAcquired,acquired=false;
  const held=new Promise(resolve=>{releaseHeld=resolve;});
  const acquiredPromise=new Promise((resolve,reject)=>{resolveAcquired=resolve;rejectAcquired=reject;});
  let request;
  try{
   request=lockApi.request.call(lockApi.locks,LOCK_NAME,{mode:'exclusive',signal:entry.controller.signal},async()=>{
    if(entry.cancelled)throw abortError();
    acquired=true;
    resolveAcquired();
    await held;
   });
   if(!request||typeof request.then!=='function')throw Error('Web Locks returned an invalid request.');
   request.catch(error=>{if(!acquired)rejectAcquired(error);});
  }catch(error){
   if(entry.cancelled||error?.name==='AbortError')throw abortError();
   return {mode:'single-context-fallback',release:async()=>{}};
  }
  try{await acquiredPromise;}
  catch(error){
   // Web Locks is an optional coordination enhancement.  If an otherwise
   // usable browser exposes a broken implementation, fall back to the local
   // gate instead of making resumable analysis unavailable.  Cancellation is
   // never converted to a fallback.
   if(entry.cancelled||error?.name==='AbortError')throw abortError();
   return {mode:'single-context-fallback',release:async()=>{}};
  }
  return {mode:'web-locks',release:async()=>{releaseHeld();try{await request;}catch(error){if(error?.name!=='AbortError')throw error;}}};
 }
 function pump(){
  if(state.active||!state.queue.length)return;
  const entry=state.queue.shift();
  if(entry.cancelled){entry.reject(abortError());pump();return;}
  state.active=entry;entry.status='admitting';
  originLease(entry).then(origin=>{
   if(entry.cancelled){return origin.release().then(()=>{throw abortError();});}
   entry.origin=origin;entry.status='active';entry.started=now();
   if(entry.abortListener)entry.signal?.removeEventListener?.('abort',entry.abortListener);
   let released=false;
   entry.resolve({
    diagnostics:()=>({schemaVersion:1,resourceClass:'analysis-heavy',capacity:1,crossContextMode:origin.mode,waitMs:elapsed(entry.submitted,entry.started),admissionTicket:entry.position}),
    async release(){
     if(released)return false;
     released=true;entry.status='released';
     try{await origin.release();}
     finally{if(state.active===entry)state.active=null;pump();}
     return true;
    }
   });
  }).catch(error=>{
   if(state.active===entry)state.active=null;
   if(entry.abortListener)entry.signal?.removeEventListener?.('abort',entry.abortListener);
   entry.reject(error?.name==='AbortError'?abortError():error);
   pump();
  });
 }
 function acquire({key,signal}={}){
  if(typeof key!=='string'||!KEY.test(key))return Promise.reject(new Error('Invalid analysis scheduler identity.'));
  if(signal?.aborted)return Promise.reject(abortError());
  return new Promise((resolve,reject)=>{
   const controller=typeof AbortController==='function'?new AbortController():{abort(){},signal:undefined};
   const entry={key,signal,controller,resolve,reject,status:'queued',submitted:now(),position:++state.sequence,cancelled:false,abortListener:null};
   entry.abortListener=()=>{
    if(entry.status==='queued'){
     entry.cancelled=true;controller.abort();remove(entry);signal?.removeEventListener?.('abort',entry.abortListener);reject(abortError());pump();return;
    }
    // The local queue has admitted this job, but another tab currently owns
    // the origin-wide Web Lock. Abort that pending lock request immediately;
    // originLease's rejection path releases the local slot and advances FIFO.
    if(entry.status==='admitting'){entry.cancelled=true;controller.abort();}
   };
   signal?.addEventListener?.('abort',entry.abortListener,{once:true});
   state.queue.push(entry);pump();
  });
 }
 root.LightForgeAnalysisScheduler={acquire,snapshot};
 if(typeof module!=='undefined'&&module.exports)module.exports={acquire,snapshot};
})(typeof self!=='undefined'?self:globalThis);
