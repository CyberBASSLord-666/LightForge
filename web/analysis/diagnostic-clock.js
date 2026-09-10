/* Stable, failure-tolerant clocks for optional progress and resource timing.
 * A selected performance clock never falls through to epoch time after a late
 * failure; callers receive zero elapsed time instead of fabricated telemetry.
 */
(function(root){'use strict';
 const number=value=>typeof value==='number'&&Number.isFinite(value)?value:null;
 const read=(object,key)=>{try{return {ok:true,value:object==null?undefined:object[key]};}catch(_){return {ok:false,reason:String(key)+'-observed-error'};}};
 const select=(target,key,label)=>{
  const object=read(target,key);
  if(!object.ok)return {ok:false,reason:label+'-clock-observed-error'};
  if(object.value==null)return {ok:false,reason:label+'-clock-unavailable'};
  const now=read(object.value,'now');
  if(!now.ok)return {ok:false,reason:label+'-now-observed-error'};
  if(typeof now.value!=='function')return {ok:false,reason:label+'-now-unavailable'};
  try{const value=number(now.value.call(object.value));return value===null?{ok:false,reason:label+'-now-invalid'}:{ok:true,value,object:object.value,now:now.value,label:label+'-now'};}catch(_){return {ok:false,reason:label+'-now-observed-error'};}
 };
 const sample=clock=>{try{const value=number(clock.now.call(clock.object));return value===null?{ok:false,reason:clock.label+'-invalid'}:{ok:true,value};}catch(_){return {ok:false,reason:clock.label+'-observed-error'};}};
 function create(target=root){
  const firstPerformance=select(target,'performance','performance');
  const initial=firstPerformance.ok?firstPerformance:select(target,'Date','date');
  const source=firstPerformance.ok?'performance.now':initial.ok?'date.now':'unavailable';
  // The source label alone is insufficient: a host getter can replace its
  // object later with an epoch-backed clock. Retain both original receiver and
  // callable so timing either remains on one origin or fails closed.
  const selected=initial.ok?initial:null;
  const fallbackReason=firstPerformance.ok?null:firstPerformance.reason;
  let unavailable=!initial.ok,failureReason=initial.ok?null:initial.reason,last=initial.ok?initial.value:0;
  const now=()=>{
   if(unavailable)return null;
   const next=selected?sample(selected):{ok:false,reason:'clock-unavailable'};
   if(!next.ok){unavailable=true;failureReason=next.reason;return null;}
   if(next.value<last){unavailable=true;failureReason=source+'-nonmonotonic';return null;}
   last=next.value;return next.value;
  };
  const elapsed=(start,end=now())=>{
   const a=number(start),b=number(end);return a===null||b===null?0:Math.max(0,b-a);
  };
  const state=()=>({source,state:unavailable?(String(failureReason||fallbackReason||'').includes('observed-error')?'observed-error':'unavailable'):(source==='date.now'?'fallback':'available'),reason:unavailable?(failureReason||fallbackReason||'clock-unavailable'):(source==='date.now'?fallbackReason:null)});
  const mark=()=>({milliseconds:now()??0,source});
  const measure=marked=>{
   const end=now(),sameSource=!!marked&&marked.source===source&&source!=='unavailable',measured=end!==null&&sameSource;
   const diagnostic=state();
   return {milliseconds:measured?elapsed(marked.milliseconds,end):0,measured,status:diagnostic.state,reason:diagnostic.reason,source};
  };
  return {source,start:initial.ok?initial.value:0,now,elapsed,mark,measure,diagnostics:state};
 }
 root.LightForgeDiagnosticClock={create};
 if(typeof module!=='undefined'&&module.exports)module.exports={create};
})(typeof self!=='undefined'?self:globalThis);
