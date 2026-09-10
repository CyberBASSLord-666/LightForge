/* Stable, failure-tolerant clocks for optional progress and resource timing.
 * A selected performance clock never falls through to epoch time after a late
 * failure; callers receive zero elapsed time instead of fabricated telemetry.
 */
(function(root){'use strict';
 const number=value=>typeof value==='number'&&Number.isFinite(value)?value:null;
 const read=(object,key)=>{try{return {ok:true,value:object==null?undefined:object[key]};}catch(_){return {ok:false,reason:String(key)+'-observed-error'};}};
 const invoke=(object,key,label)=>{
  const ref=read(object,key);if(!ref.ok)return {ok:false,reason:label+'-observed-error'};
  if(typeof ref.value!=='function')return {ok:false,reason:label+'-unavailable'};
  try{const value=number(ref.value.call(object));return value===null?{ok:false,reason:label+'-invalid'}:{ok:true,value};}catch(_){return {ok:false,reason:label+'-observed-error'};}
 };
 function create(target=root){
  const samplePerformance=()=>{
   const ref=read(target,'performance');return ref.ok&&ref.value!=null?invoke(ref.value,'now','performance-now'):{ok:false,reason:'performance-clock-'+(ref.ok?'unavailable':'observed-error')};
  };
  const sampleDate=()=>{
   const ref=read(target,'Date');return ref.ok&&ref.value!=null?invoke(ref.value,'now','date-now'):{ok:false,reason:'date-clock-'+(ref.ok?'unavailable':'observed-error')};
  };
  const firstPerformance=samplePerformance();
  const initial=firstPerformance.ok?firstPerformance:sampleDate();
  const source=firstPerformance.ok?'performance.now':initial.ok?'date.now':'unavailable';
  const sample=source==='performance.now'?samplePerformance:source==='date.now'?sampleDate:()=>({ok:false,reason:'clock-unavailable'});
  const fallbackReason=firstPerformance.ok?null:firstPerformance.reason;
  let unavailable=!initial.ok,failureReason=initial.ok?null:initial.reason,last=initial.ok?initial.value:0;
  const now=()=>{
   if(unavailable)return null;
   const next=sample();
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
