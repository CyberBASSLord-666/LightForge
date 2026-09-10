/* Bounded, privacy-safe timing evidence for offline music analysis. */
(function(root){'use strict';
 const number=x=>typeof x==='number'&&Number.isFinite(x)?x:null;
 const read=(object,key)=>{try{return {error:false,value:object==null?undefined:object[key]};}catch(_){return {error:true,value:undefined};}};
 const observation=(probe,present)=>({status:probe.error?'observed-error':present(probe.value)?'available':'unavailable'});
 function now(){
  const performanceRef=read(root,'performance'),clock=performanceRef.error?{error:true,value:undefined}:read(performanceRef.value,'now');
  if(!clock.error&&typeof clock.value==='function')try{const value=clock.value.call(performanceRef.value);if(number(value)!==null)return value;}catch(_){}
  try{return Date.now();}catch(_){return 0;}
 }
 const clampText=x=>String(x||'').replace(/[^a-zA-Z0-9_.:-]/g,'_').slice(0,96);
 const resourceApi=()=>{
  const direct=root.LightForgeResourceDiagnostics;
  if(direct&&typeof direct.create==='function')return direct;
  // Node contract tests load telemetry directly; this keeps the browser build
  // dependency-free while making the resource contract testable in isolation.
  if(typeof module!=='undefined'&&module.exports&&typeof require==='function')try{
   const loaded=require('./resource-diagnostics.js');return loaded&&typeof loaded.create==='function'?loaded:null;
  }catch(_){}
 return null;
 };
 function runtime(){
  const navigatorRef=read(root,'navigator'),hardware=navigatorRef.error?{error:true,value:undefined}:read(navigatorRef.value,'hardwareConcurrency'),deviceMemory=navigatorRef.error?{error:true,value:undefined}:read(navigatorRef.value,'deviceMemory');
  const performanceRef=read(root,'performance'),memory=performanceRef.error?{error:true,value:undefined}:read(performanceRef.value,'memory');
  const heapUsed=memory.error?{error:true,value:undefined}:read(memory.value,'usedJSHeapSize'),heapLimit=memory.error?{error:true,value:undefined}:read(memory.value,'jsHeapSizeLimit');
  const isolated=read(root,'crossOriginIsolated');
  return {hardwareConcurrency:number(hardware.value),deviceMemoryGiB:number(deviceMemory.value),crossOriginIsolated:isolated.value===true,
   jsHeapUsedBytes:number(heapUsed.value),jsHeapLimitBytes:number(heapLimit.value),
   observations:{hardwareConcurrency:observation(hardware,value=>number(value)!==null),deviceMemoryGiB:observation(deviceMemory,value=>number(value)!==null),crossOriginIsolated:observation(isolated,value=>typeof value==='boolean'),jsHeap:observation(memory,value=>value!==null&&value!==undefined),jsHeapUsedBytes:observation(heapUsed,value=>number(value)!==null),jsHeapLimitBytes:observation(heapLimit,value=>number(value)!==null)}};
 }
 function create(stage,extra={}){
  const begun=now(),open=new Map(),spans=[],caches=[],counters={};let resources=null;
  try{const api=resourceApi();resources=api?api.create(stage):null;}catch(_){resources=null;}
  function begin(name){const token=clampText(name);if(!open.has(token)&&open.size<32)open.set(token,now());return token;}
  function end(token,attributes){const started=open.get(token);if(started===undefined)return null;open.delete(token);
   const duration=Math.max(0,now()-started),entry={name:token,durationMs:duration};
   if(attributes&&typeof attributes==='object')for(const [key,value] of Object.entries(attributes))if(typeof value==='string'||typeof value==='boolean'||number(value)!==null)entry[clampText(key)]=typeof value==='string'?value.slice(0,160):value;
   if(spans.length<96)spans.push(entry);return entry;
  }
  function measure(name,fn,attributes){const token=begin(name);try{return fn();}finally{end(token,attributes);}}
  async function measureAsync(name,fn,attributes){const token=begin(name);try{return await fn();}finally{end(token,attributes);}}
  function cache(domain,outcome,attributes){const normalized=['hit','miss','restore','invalidate','write','corrupt'].includes(outcome)?outcome:'unknown';try{resources?.cache(normalized);}catch(_){}if(caches.length>=64)return;const entry={domain:clampText(domain),outcome:normalized};
   if(attributes&&typeof attributes==='object')for(const [key,value] of Object.entries(attributes))if(typeof value==='boolean'||number(value)!==null)entry[clampText(key)]=value;caches.push(entry);}
  function increment(name,count=1){const key=clampText(name);counters[key]=Math.max(0,(counters[key]||0)+(number(count)??0));}
  function io(direction,bytes,source){try{return resources?.io(direction,bytes,source)===true;}catch(_){return false;}}
  function allocation(bytes,count=1){try{return resources?.allocation(bytes,count)===true;}catch(_){return false;}}
  function copy(bytes,count=1){try{return resources?.copy(bytes,count)===true;}catch(_){return false;}}
  function scheduler(value){try{return resources?.observeScheduler(value)===true;}catch(_){return false;}}
  function snapshot(attributes={}){for(const token of [...open.keys()])end(token,{unfinished:true});
   const total=Math.max(0,now()-begun),summary={};for(const span of spans){const row=summary[span.name]||{count:0,totalMs:0,maxMs:0};row.count++;row.totalMs+=span.durationMs;row.maxMs=Math.max(row.maxMs,span.durationMs);summary[span.name]=row;}
  let resourceSnapshot=null;try{resourceSnapshot=resources?resources.snapshot():null;}catch(_){}
  let observedRuntime;try{observedRuntime=runtime();}catch(_){observedRuntime={hardwareConcurrency:null,deviceMemoryGiB:null,crossOriginIsolated:false,jsHeapUsedBytes:null,jsHeapLimitBytes:null,observations:{hardwareConcurrency:{status:'observed-error'},deviceMemoryGiB:{status:'observed-error'},crossOriginIsolated:{status:'observed-error'},jsHeap:{status:'observed-error'},jsHeapUsedBytes:{status:'observed-error'},jsHeapLimitBytes:{status:'observed-error'}}};}
  return {schemaVersion:1,kind:'analysis-stage-profile',stage:clampText(stage),totalWallClockMs:total,runtime:observedRuntime,spans,spanSummary:summary,cache:caches,counters,attributes,resources:resourceSnapshot};}
  return {begin,end,measure,measureAsync,cache,increment,io,allocation,copy,scheduler,resource:resources,snapshot};
 }
 const api={create};root.LightForgeAnalysisTelemetry=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof self!=='undefined'?self:globalThis);
