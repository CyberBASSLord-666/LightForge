/* Bounded, privacy-safe timing evidence for offline music analysis. */
(function(root){'use strict';
 const number=x=>typeof x==='number'&&Number.isFinite(x)?x:null;
 // Browser privacy/runtime probes may be accessor-backed and throw. Diagnostics
 // are observational only, so an unavailable probe must never fail analysis.
 const read=(object,key)=>{try{return object==null?undefined:object[key];}catch(_){return undefined;}};
 function selectClock(key){
  const receiver=read(root,key),callable=read(receiver,'now');
  if(typeof callable!=='function')return null;
  try{const value=number(callable.call(receiver));return value===null?null:{receiver,callable,value};}catch(_){return null;}
 }
 function sampleClock(clock){try{const value=number(clock.callable.call(clock.receiver));return value===null?null:value;}catch(_){return null;}}
 function createClock(){
  const performanceClock=selectClock('performance');
  if(performanceClock){
   let unavailable=false,last=performanceClock.value;return {source:'performance.now',start:last,now(){if(unavailable)return null;const value=sampleClock(performanceClock);if(value===null||value<last){unavailable=true;return null;}last=value;return value;},elapsed(start){const end=this.now();return end===null||number(start)===null?0:Math.max(0,end-start);},diagnostics(){return {source:'performance.now',state:unavailable?'observed-error':'available'};}};
  }
  const dateClock=selectClock('Date');let unavailable=!dateClock,last=dateClock?.value??0;return {source:dateClock?'date.now':'unavailable',start:last,now(){if(unavailable)return null;const value=sampleClock(dateClock);if(value===null||value<last){unavailable=true;return null;}last=value;return value;},elapsed(start){const end=this.now();return end===null||number(start)===null?0:Math.max(0,end-start);},diagnostics(){return {source:dateClock?'date.now':'unavailable',state:unavailable?'observed-error':'available'};}};
 }
 const clampText=x=>String(x||'').replace(/[^a-zA-Z0-9_.:-]/g,'_').slice(0,96);
 function runtime(){
  const nav=read(root,'navigator'),performanceRef=read(root,'performance'),memory=read(performanceRef,'memory');
  return {hardwareConcurrency:number(read(nav,'hardwareConcurrency')),deviceMemoryGiB:number(read(nav,'deviceMemory')),crossOriginIsolated:read(root,'crossOriginIsolated')===true,
   jsHeapUsedBytes:number(read(memory,'usedJSHeapSize')),jsHeapLimitBytes:number(read(memory,'jsHeapSizeLimit'))};
 }
 function create(stage,extra={}){
  const clock=createClock(),begun=clock.start,open=new Map(),spans=[],caches=[],counters={};
  function begin(name){const token=clampText(name);if(!open.has(token)&&open.size<32)open.set(token,clock.now());return token;}
  function end(token,attributes){const started=open.get(token);if(started===undefined)return null;open.delete(token);
   const duration=clock.elapsed(started),entry={name:token,durationMs:duration};
   if(attributes&&typeof attributes==='object')for(const [key,value] of Object.entries(attributes))if(typeof value==='string'||typeof value==='boolean'||number(value)!==null)entry[clampText(key)]=typeof value==='string'?value.slice(0,160):value;
   if(spans.length<96)spans.push(entry);return entry;
  }
  function measure(name,fn,attributes){const token=begin(name);try{return fn();}finally{end(token,attributes);}}
  async function measureAsync(name,fn,attributes){const token=begin(name);try{return await fn();}finally{end(token,attributes);}}
  function cache(domain,outcome,attributes){if(caches.length>=64)return;const entry={domain:clampText(domain),outcome:['hit','miss','restore','invalidate','write','corrupt'].includes(outcome)?outcome:'unknown'};
   if(attributes&&typeof attributes==='object')for(const [key,value] of Object.entries(attributes))if(typeof value==='boolean'||number(value)!==null)entry[clampText(key)]=value;caches.push(entry);}
  function increment(name,count=1){const key=clampText(name);counters[key]=Math.max(0,(counters[key]||0)+(number(count)??0));}
  function snapshot(attributes={}){for(const token of [...open.keys()])end(token,{unfinished:true});
   const total=clock.elapsed(begun),summary={};for(const span of spans){const row=summary[span.name]||{count:0,totalMs:0,maxMs:0};row.count++;row.totalMs+=span.durationMs;row.maxMs=Math.max(row.maxMs,span.durationMs);summary[span.name]=row;}
   return {schemaVersion:1,kind:'analysis-stage-profile',stage:clampText(stage),totalWallClockMs:total,timing:clock.diagnostics(),runtime:runtime(),spans,spanSummary:summary,cache:caches,counters,attributes};}
  return {begin,end,measure,measureAsync,cache,increment,snapshot};
 }
 const api={create};root.LightForgeAnalysisTelemetry=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof self!=='undefined'?self:globalThis);
