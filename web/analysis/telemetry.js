/* Bounded, privacy-safe timing evidence for offline music analysis. */
(function(root){'use strict';
 const number=x=>typeof x==='number'&&Number.isFinite(x)?x:null;
 const read=(object,key)=>{try{return {error:false,value:object==null?undefined:object[key]};}catch(_){return {error:true,value:undefined};}};
 const observation=(probe,present)=>({status:probe.error?'observed-error':present(probe.value)?'available':'unavailable'});
 // Latch both receiver and callable before the first measurement. A hostile
 // getter or later clock swap must make timing unavailable rather than mixing
 // clock origins or changing analysis behavior.
 function selectClock(key){
  const receiverRef=read(root,key);if(receiverRef.error)return null;
  const receiver=receiverRef.value,callableRef=read(receiver,'now');
  if(callableRef.error||typeof callableRef.value!=='function')return null;
  try{const value=number(callableRef.value.call(receiver));return value===null?null:{receiver,callable:callableRef.value,value};}catch(_){return null;}
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
  const clock=createClock(),begun=clock.start,open=new Map(),spans=[],summaries=new Map(),caches=[],counters={};let resources=null,totalSpanCount=0,omittedSpanCount=0;
  try{const api=resourceApi();resources=api?api.create(stage):null;}catch(_){resources=null;}
  function begin(name){const token=clampText(name);if(!open.has(token)&&open.size<32)open.set(token,clock.now());return token;}
  function end(token,attributes){const started=open.get(token);if(started===undefined)return null;open.delete(token);
   const finished=clock.now(),duration=finished===null||number(started)===null?null:number(Math.max(0,finished-started)),entry={name:token,durationMs:duration};
   // Keep complete totals independently of the bounded raw-span prefix. Bound
   // distinct names too, and expose omissions rather than inventing a stage.
   totalSpanCount++;let row=summaries.get(token);
   if(!row&&summaries.size<96){row={count:0,totalMs:0,maxMs:0};summaries.set(token,row);}
   if(row){row.count++;
    if(duration===null){row.unavailableCount=(row.unavailableCount||0)+1;row.totalMs=null;row.maxMs=null;}
    else if(row.totalMs!==null){const total=number(row.totalMs+duration);if(total===null){row.overflowed=true;row.totalMs=null;row.maxMs=null;}else{row.totalMs=total;row.maxMs=Math.max(row.maxMs,duration);}}
   }else omittedSpanCount++;
   if(attributes&&typeof attributes==='object')for(const [key,value] of Object.entries(attributes)){const name=clampText(key);if(name!=='name'&&name!=='durationMs'&&(typeof value==='string'||typeof value==='boolean'||number(value)!==null))entry[name]=typeof value==='string'?value.slice(0,160):value;}
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
   const total=clock.elapsed(begun),summary=Object.fromEntries([...summaries].map(([name,row])=>[name,{...row}]));
  let resourceSnapshot=null;try{resourceSnapshot=resources?resources.snapshot():null;}catch(_){}
  let observedRuntime;try{observedRuntime=runtime();}catch(_){observedRuntime={hardwareConcurrency:null,deviceMemoryGiB:null,crossOriginIsolated:false,jsHeapUsedBytes:null,jsHeapLimitBytes:null,observations:{hardwareConcurrency:{status:'observed-error'},deviceMemoryGiB:{status:'observed-error'},crossOriginIsolated:{status:'observed-error'},jsHeap:{status:'observed-error'},jsHeapUsedBytes:{status:'observed-error'},jsHeapLimitBytes:{status:'observed-error'}}};}
  return {schemaVersion:1,kind:'analysis-stage-profile',stage:clampText(stage),totalWallClockMs:total,timing:clock.diagnostics(),runtime:observedRuntime,spans,spanSummary:summary,spanSummaryCoverage:{namesComplete:omittedSpanCount===0,summaryNameLimit:96,omittedSpanCount,totalSpanCount,retainedSpanCount:spans.length},cache:caches,counters,attributes,resources:resourceSnapshot};}
  return {begin,end,measure,measureAsync,cache,increment,io,allocation,copy,scheduler,resource:resources,snapshot};
 }
 const api={create};root.LightForgeAnalysisTelemetry=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof self!=='undefined'?self:globalThis);
