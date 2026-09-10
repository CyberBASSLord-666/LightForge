/* Bounded, privacy-safe timing evidence for offline music analysis. */
(function(root){'use strict';
 const number=x=>typeof x==='number'&&Number.isFinite(x)?x:null;
 // Browser privacy/runtime probes may be accessor-backed and throw. Diagnostics
 // are observational only, so an unavailable probe must never fail analysis.
 const read=(object,key)=>{try{return object==null?undefined:object[key];}catch(_){return undefined;}};
 function now(){
  const performanceRef=read(root,'performance'),clock=read(performanceRef,'now');
  if(typeof clock==='function')try{const value=clock.call(performanceRef);if(number(value)!==null)return value;}catch(_){}
  try{return Date.now();}catch(_){return 0;}
 }
 const clampText=x=>String(x||'').replace(/[^a-zA-Z0-9_.:-]/g,'_').slice(0,96);
 function runtime(){
  const nav=read(root,'navigator'),performanceRef=read(root,'performance'),memory=read(performanceRef,'memory');
  return {hardwareConcurrency:number(read(nav,'hardwareConcurrency')),deviceMemoryGiB:number(read(nav,'deviceMemory')),crossOriginIsolated:read(root,'crossOriginIsolated')===true,
   jsHeapUsedBytes:number(read(memory,'usedJSHeapSize')),jsHeapLimitBytes:number(read(memory,'jsHeapSizeLimit'))};
 }
 function create(stage,extra={}){
  const begun=now(),open=new Map(),spans=[],caches=[],counters={};
  function begin(name){const token=clampText(name);if(!open.has(token)&&open.size<32)open.set(token,now());return token;}
  function end(token,attributes){const started=open.get(token);if(started===undefined)return null;open.delete(token);
   const duration=Math.max(0,now()-started),entry={name:token,durationMs:duration};
   if(attributes&&typeof attributes==='object')for(const [key,value] of Object.entries(attributes))if(typeof value==='string'||typeof value==='boolean'||number(value)!==null)entry[clampText(key)]=typeof value==='string'?value.slice(0,160):value;
   if(spans.length<96)spans.push(entry);return entry;
  }
  function measure(name,fn,attributes){const token=begin(name);try{return fn();}finally{end(token,attributes);}}
  async function measureAsync(name,fn,attributes){const token=begin(name);try{return await fn();}finally{end(token,attributes);}}
  function cache(domain,outcome,attributes){if(caches.length>=64)return;const entry={domain:clampText(domain),outcome:['hit','miss','restore','invalidate','write','corrupt'].includes(outcome)?outcome:'unknown'};
   if(attributes&&typeof attributes==='object')for(const [key,value] of Object.entries(attributes))if(typeof value==='boolean'||number(value)!==null)entry[clampText(key)]=value;caches.push(entry);}
  function increment(name,count=1){const key=clampText(name);counters[key]=Math.max(0,(counters[key]||0)+(number(count)??0));}
  function snapshot(attributes={}){for(const token of [...open.keys()])end(token,{unfinished:true});
   const total=Math.max(0,now()-begun),summary={};for(const span of spans){const row=summary[span.name]||{count:0,totalMs:0,maxMs:0};row.count++;row.totalMs+=span.durationMs;row.maxMs=Math.max(row.maxMs,span.durationMs);summary[span.name]=row;}
   return {schemaVersion:1,kind:'analysis-stage-profile',stage:clampText(stage),totalWallClockMs:total,runtime:runtime(),spans,spanSummary:summary,cache:caches,counters,attributes};}
  return {begin,end,measure,measureAsync,cache,increment,snapshot};
 }
 const api={create};root.LightForgeAnalysisTelemetry=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof self!=='undefined'?self:globalThis);
