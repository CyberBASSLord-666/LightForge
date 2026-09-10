/*
 * Measurement-only resource evidence for offline music analysis.
 *
 * This module deliberately distinguishes a zero observation from an
 * unavailable observation. Browsers do not expose CPU/GPU utilisation or
 * allocator counters portably, so those fields are never inferred. Callers
 * may instrument known byte transfers, allocations and copies through the
 * recorder; uninstrumented domains remain explicitly unavailable.
 */
(function(root){'use strict';
 const VERSION=1,MAX_STAGE=64,MAX_SOURCE=48,MAX_MODE=64;
 const cacheOutcomes=['hit','miss','restore','invalidate','write','corrupt','unknown'];
 const finite=value=>typeof value==='number'&&Number.isFinite(value);
 const whole=value=>Number.isSafeInteger(value)&&value>=0;
 // `Object.getPrototypeOf(value)===Object.prototype` rejects records created
 // in a Web Worker, iframe, or Node VM. Accept a genuine plain object from
 // another realm, but keep class instances and proxy failures out of the
 // evidence contract.
 const nativeObject=Function.prototype.toString.call(Object);
 const plain=value=>{
  if(!value||typeof value!=='object')return false;
  try{
   const prototype=Object.getPrototypeOf(value);
   if(!prototype||Object.getPrototypeOf(prototype)!==null)return false;
   const constructor=Object.getOwnPropertyDescriptor(prototype,'constructor')?.value;
   return typeof constructor==='function'&&Function.prototype.toString.call(constructor)===nativeObject;
  }catch(_){return false;}
 };
 // Privacy shims are allowed to expose browser APIs through throwing getters.
 // Observation must not turn those shims into an analysis failure.
 const read=(object,key)=>{try{return {error:false,value:object==null?undefined:object[key]};}catch(_){return {error:true,value:undefined};}};
 function now(){
  const performanceRef=read(root,'performance'),clock=performanceRef.error?{error:true,value:undefined}:read(performanceRef.value,'now');
  if(!clock.error&&typeof clock.value==='function')try{const value=clock.value.call(performanceRef.value);if(finite(value))return value;}catch(_){}
  try{return Date.now();}catch(_){return 0;}
 }
 const clean=(value,max=MAX_SOURCE)=>String(value||'').replace(/[^a-zA-Z0-9_.:-]/g,'_').slice(0,max);
 const stageName=value=>typeof value==='string'&&/^[a-z][a-z0-9-]{0,63}$/.test(value)?value:null;
 const round=value=>Math.round(value*1000)/1000;
 const exact=(value,keys,label)=>{
  if(!plain(value)||Object.keys(value).sort().join(',')!==keys.slice().sort().join(','))throw Error('Invalid '+label+' shape.');
  return value;
 };
 const state=value=>['available','partial','unavailable'].includes(value);
 const nullableWhole=value=>value===null||whole(value);
 const nullableFinite=value=>value===null||finite(value)&&value>=0;
 function heap(){
  const performanceRef=read(root,'performance');
  if(performanceRef.error)return {used:null,limit:null,reason:'performance-memory-api-observed-error'};
  const memoryRef=read(performanceRef.value,'memory');
  if(memoryRef.error)return {used:null,limit:null,reason:'performance-memory-api-observed-error'};
  if(memoryRef.value===null||memoryRef.value===undefined)return {used:null,limit:null,reason:'performance-memory-api-unavailable'};
  const usedRef=read(memoryRef.value,'usedJSHeapSize'),limitRef=read(memoryRef.value,'jsHeapSizeLimit');
  if(usedRef.error||limitRef.error)return {used:null,limit:null,reason:'performance-memory-api-observed-error'};
  const used=whole(usedRef.value)?usedRef.value:null;
  const limit=whole(limitRef.value)?limitRef.value:null;
  return {used,limit,reason:used===null?'performance-memory-api-unavailable':null};
 }
 function platform(){
  const navigatorRef=read(root,'navigator');
  if(navigatorRef.error)return {cores:null,memory:null,webgpu:false,coresReason:'navigator-hardware-concurrency-observed-error',memoryReason:'navigator-device-memory-observed-error',webgpuReason:'navigator-gpu-observed-error'};
  const coresRef=read(navigatorRef.value,'hardwareConcurrency'),memoryRef=read(navigatorRef.value,'deviceMemory'),gpuRef=read(navigatorRef.value,'gpu');
  const cores=whole(coresRef.value)&&coresRef.value>0?coresRef.value:null;
  const memory=finite(memoryRef.value)&&memoryRef.value>0?memoryRef.value:null;
  // `navigator.gpu` only says that the WebGPU API is exposed. It does not
  // prove an adapter exists, which one will run inference, or its utilisation.
  const webgpu=!gpuRef.error&&!!gpuRef.value;
  return {cores,memory,webgpu,
   coresReason:coresRef.error?'navigator-hardware-concurrency-observed-error':'navigator-hardware-concurrency-unavailable',
   memoryReason:memoryRef.error?'navigator-device-memory-observed-error':'navigator-device-memory-unavailable',
   webgpuReason:gpuRef.error?'navigator-gpu-observed-error':'webgpu-api-unavailable'};
 }
 function unavailable(reason){return {status:'unavailable',reason};}
 function validateWall(value){
  exact(value,['milliseconds','status'],'resource wall-clock');
  if(value.status!=='available'||!finite(value.milliseconds)||value.milliseconds<0)throw Error('Invalid resource wall-clock.');
 }
 function validateScheduler(value){
  exact(value,['admissionMode','reason','status','waitMilliseconds'],'resource scheduler');
  if(!state(value.status)||!nullableFinite(value.waitMilliseconds)||!(value.admissionMode===null||typeof value.admissionMode==='string'&&value.admissionMode.length<=MAX_MODE)||!(value.reason===null||typeof value.reason==='string'&&value.reason.length<=MAX_MODE))throw Error('Invalid resource scheduler.');
  if(value.status==='available'&&value.waitMilliseconds===null)throw Error('Available resource scheduler has no wait time.');
  if(value.status==='unavailable'&&(value.waitMilliseconds!==null||value.reason===null))throw Error('Unavailable resource scheduler is ambiguous.');
 }
 function validateCache(value){
  exact(value,['outcomes','recordedEvents','status'],'resource cache');
  if(value.status!=='instrumented'||!whole(value.recordedEvents)||!plain(value.outcomes))throw Error('Invalid resource cache.');
  const keys=Object.keys(value.outcomes).sort();
  if(keys.join(',')!==cacheOutcomes.slice().sort().join(','))throw Error('Invalid resource cache outcomes.');
  let total=0;for(const key of keys){if(!whole(value.outcomes[key]))throw Error('Invalid resource cache count.');total+=value.outcomes[key];}
  if(total!==value.recordedEvents)throw Error('Resource cache count mismatch.');
 }
 function validateIo(value){
  exact(value,['coverage','readBytes','readOperations','reason','status','writeBytes','writeOperations'],'resource io');
  if(!state(value.status)||!Array.isArray(value.coverage)||value.coverage.length>16||value.coverage.some(item=>typeof item!=='string'||!item||item.length>MAX_SOURCE)||new Set(value.coverage).size!==value.coverage.length||!nullableWhole(value.readBytes)||!nullableWhole(value.writeBytes)||!nullableWhole(value.readOperations)||!nullableWhole(value.writeOperations)||!(value.reason===null||typeof value.reason==='string'&&value.reason.length<=MAX_MODE))throw Error('Invalid resource io.');
  if(value.status==='unavailable'&&(value.readBytes!==null||value.writeBytes!==null||value.readOperations!==null||value.writeOperations!==null||value.reason===null))throw Error('Unavailable resource io is ambiguous.');
  if(value.status!=='unavailable'&&(value.readBytes===null||value.writeBytes===null||value.readOperations===null||value.writeOperations===null))throw Error('Instrumented resource io is incomplete.');
  if(value.status==='partial'&&(value.coverage.length===0||value.reason===null))throw Error('Partial resource io lacks coverage.');
 }
 function validateHeap(value){
  exact(value,['afterBytes','beforeBytes','limitBytes','peakBytes','reason','status'],'resource heap');
  if(!state(value.status)||!nullableWhole(value.beforeBytes)||!nullableWhole(value.afterBytes)||!nullableWhole(value.peakBytes)||!nullableWhole(value.limitBytes)||!(value.reason===null||typeof value.reason==='string'&&value.reason.length<=MAX_MODE))throw Error('Invalid resource heap.');
  if(value.status==='unavailable'&&(value.beforeBytes!==null||value.afterBytes!==null||value.peakBytes!==null||value.limitBytes!==null||value.reason===null))throw Error('Unavailable resource heap is ambiguous.');
  if(value.status!=='unavailable'&&(value.beforeBytes===null||value.afterBytes===null||value.peakBytes===null))throw Error('Available resource heap is incomplete.');
 }
 function validateCounters(value){
  exact(value,['allocationBytes','allocationCount','copyBytes','copyCount','reason','status'],'resource allocation counters');
  if(!state(value.status)||!nullableWhole(value.allocationBytes)||!nullableWhole(value.allocationCount)||!nullableWhole(value.copyBytes)||!nullableWhole(value.copyCount)||!(value.reason===null||typeof value.reason==='string'&&value.reason.length<=MAX_MODE))throw Error('Invalid resource allocation counters.');
  if(value.status==='unavailable'&&(value.allocationBytes!==null||value.allocationCount!==null||value.copyBytes!==null||value.copyCount!==null||value.reason===null))throw Error('Unavailable resource allocation counters are ambiguous.');
  if(value.status!=='unavailable'&&(value.allocationBytes===null||value.allocationCount===null||value.copyBytes===null||value.copyCount===null))throw Error('Instrumented resource allocation counters are incomplete.');
 }
 function validateCpu(value){
  exact(value,['deviceMemoryGiB','logicalCores','reason','status','utilization'],'resource cpu');
  if(!state(value.status)||!nullableWhole(value.logicalCores)||!(value.deviceMemoryGiB===null||finite(value.deviceMemoryGiB)&&value.deviceMemoryGiB>=0)||!(value.reason===null||typeof value.reason==='string'&&value.reason.length<=MAX_MODE))throw Error('Invalid resource cpu.');
  exact(value.utilization,['percent','reason','status'],'resource cpu utilisation');
  if(value.utilization.status!=='unavailable'||value.utilization.percent!==null||typeof value.utilization.reason!=='string'||!value.utilization.reason)throw Error('CPU utilisation must be explicitly unavailable.');
  if(value.status==='unavailable'&&(value.logicalCores!==null||value.reason===null))throw Error('Unavailable resource cpu is ambiguous.');
 }
 function validateAccelerator(value){
  exact(value,['api','reason','status','utilization'],'resource accelerator');
  if(!['api-exposed','unavailable'].includes(value.status)||!['webgpu','none'].includes(value.api)||!(value.reason===null||typeof value.reason==='string'&&value.reason.length<=MAX_MODE))throw Error('Invalid resource accelerator.');
  exact(value.utilization,['percent','reason','status'],'resource accelerator utilisation');
  if(value.utilization.status!=='unavailable'||value.utilization.percent!==null||typeof value.utilization.reason!=='string'||!value.utilization.reason)throw Error('Accelerator utilisation must be explicitly unavailable.');
  if(value.status==='unavailable'&&(value.api!=='none'||value.reason===null))throw Error('Unavailable resource accelerator is ambiguous.');
  if(value.status==='api-exposed'&&(value.api!=='webgpu'||value.reason===null))throw Error('Unprobed resource accelerator is ambiguous.');
 }
 function validate(value){
  exact(value,['accelerator','allocations','cache','cpu','io','jsHeap','kind','schemaVersion','stage','scheduler','wallClock'],'resource diagnostics');
  if(value.schemaVersion!==VERSION||value.kind!=='analysis-stage-resources'||!stageName(value.stage))throw Error('Unsupported resource diagnostics.');
  validateWall(value.wallClock);validateScheduler(value.scheduler);validateCache(value.cache);validateIo(value.io);validateHeap(value.jsHeap);validateCounters(value.allocations);validateCpu(value.cpu);validateAccelerator(value.accelerator);
  return true;
 }
 function create(stage){
  const normalized=stageName(stage);if(!normalized)throw Error('Invalid resource diagnostics stage.');
  const started=now(),initialHeap=heap();let peak=initialHeap.used,heapObserved=initialHeap.used!==null,heapLimit=initialHeap.limit,heapReason=initialHeap.reason;
  const outcomes=Object.fromEntries(cacheOutcomes.map(key=>[key,0]));
  let ioRead=0,ioWrite=0,ioReads=0,ioWrites=0,ioObserved=false,allocBytes=0,allocCount=0,copyBytes=0,copyCount=0,countersObserved=false;const ioCoverage=new Set();
  let scheduler=null;
  function sample(){const current=heap();if(current.reason)heapReason=current.reason;if(current.used!==null){heapObserved=true;peak=peak===null?current.used:Math.max(peak,current.used);}if(current.limit!==null)heapLimit=current.limit;return current;}
  function cache(outcome){sample();const key=cacheOutcomes.includes(outcome)?outcome:'unknown';outcomes[key]++;return true;}
  function io(direction,bytes,source='instrumented'){
   sample();if((direction!=='read'&&direction!=='write')||!whole(bytes)||typeof source!=='string'||!source)return false;
   ioObserved=true;ioCoverage.add(clean(source));if(direction==='read'){ioRead+=bytes;ioReads++;}else{ioWrite+=bytes;ioWrites++;}return true;
  }
  function allocation(bytes,count=1){sample();if(!whole(bytes)||!whole(count)||count<1)return false;countersObserved=true;allocBytes+=bytes;allocCount+=count;return true;}
  function copy(bytes,count=1){sample();if(!whole(bytes)||!whole(count)||count<1)return false;countersObserved=true;copyBytes+=bytes;copyCount+=count;return true;}
  function observeScheduler(value){
   sample();if(!plain(value)||!finite(value.waitMs)||value.waitMs<0)return false;
   const mode=typeof value.crossContextMode==='string'&&value.crossContextMode.length<=MAX_MODE?value.crossContextMode:'unknown';scheduler={waitMilliseconds:round(value.waitMs),admissionMode:mode};return true;
  }
  function snapshot(){
   const finalHeap=sample(),duration=Math.max(0,round(now()-started),0),platformInfo=platform();
   // A valid before/after pair is mandatory before heap values become
   // evidence. A single sample is less useful than an explicit unavailable
   // state and must never be represented as a measured delta.
   const heapStatus=heapObserved&&initialHeap.used!==null&&finalHeap.used!==null?'available':'unavailable';
   const report={schemaVersion:VERSION,kind:'analysis-stage-resources',stage:normalized,
    wallClock:{status:'available',milliseconds:duration},
    scheduler:scheduler?{status:'available',waitMilliseconds:scheduler.waitMilliseconds,admissionMode:scheduler.admissionMode,reason:null}:{status:'unavailable',waitMilliseconds:null,admissionMode:null,reason:'scheduler-not-instrumented'},
    cache:{status:'instrumented',recordedEvents:cacheOutcomes.reduce((sum,key)=>sum+outcomes[key],0),outcomes:{...outcomes}},
    io:ioObserved?{status:'partial',readBytes:ioRead,writeBytes:ioWrite,readOperations:ioReads,writeOperations:ioWrites,coverage:[...ioCoverage].sort(),reason:'decoder-model-and-stem-cache-io-not-fully-instrumented'}:{status:'unavailable',readBytes:null,writeBytes:null,readOperations:null,writeOperations:null,coverage:[],reason:'no-instrumented-io'},
    jsHeap:heapStatus==='unavailable'?{status:'unavailable',beforeBytes:null,afterBytes:null,peakBytes:null,limitBytes:null,reason:heapReason||'performance-memory-api-unavailable'}:{status:'available',beforeBytes:initialHeap.used,afterBytes:finalHeap.used,peakBytes:peak,limitBytes:heapLimit,reason:null},
    allocations:countersObserved?{status:'partial',allocationBytes:allocBytes,allocationCount:allocCount,copyBytes:copyBytes,copyCount:copyCount,reason:'only-instrumented-buffer-operations-are-counted'}:{status:'unavailable',allocationBytes:null,allocationCount:null,copyBytes:null,copyCount:null,reason:'no-instrumented-allocation-or-copy-operations'},
    cpu:platformInfo.cores===null?{status:'unavailable',logicalCores:null,deviceMemoryGiB:null,reason:platformInfo.coresReason,utilization:{status:'unavailable',percent:null,reason:'browser-api-not-exposed'}}:{status:platformInfo.memory===null?'partial':'available',logicalCores:platformInfo.cores,deviceMemoryGiB:platformInfo.memory,reason:platformInfo.memory===null?platformInfo.memoryReason:null,utilization:{status:'unavailable',percent:null,reason:'browser-api-not-exposed'}},
    accelerator:platformInfo.webgpu?{status:'api-exposed',api:'webgpu',reason:'webgpu-api-exposed-but-adapter-and-utilisation-not-probed',utilization:{status:'unavailable',percent:null,reason:'browser-api-not-exposed'}}:{status:'unavailable',api:'none',reason:platformInfo.webgpuReason,utilization:{status:'unavailable',percent:null,reason:'browser-api-not-exposed'}}};
   validate(report);return report;
  }
  return {cache,io,allocation,copy,observeScheduler,sample,snapshot};
 }
 function validatePipeline(value){
  exact(value,['kind','scheduler','schemaVersion','stages','totalWallClockMs'],'pipeline resource diagnostics');
  if(value.kind!=='analysis-pipeline-resources'||value.schemaVersion!==VERSION||!finite(value.totalWallClockMs)||value.totalWallClockMs<0||!plain(value.stages)||!Object.keys(value.stages).length)throw Error('Invalid pipeline resource diagnostics.');
  validateScheduler(value.scheduler);
  for(const [name,stage]of Object.entries(value.stages)){if(!stageName(name)||!validate(stage)||read(stage,'stage').error||read(stage,'stage').value!==name)throw Error('Invalid pipeline resource stage mapping.');}
  return true;
 }
 function pipeline(stages,scheduler,totalWallClockMs){
  if(!plain(stages))throw Error('Invalid pipeline resource stage map.');
  const rows={};for(const name of Object.keys(stages).sort()){
   if(!stageName(name)||!validate(stages[name])||read(stages[name],'stage').error||read(stages[name],'stage').value!==name)throw Error('Invalid pipeline resource stage mapping.');rows[name]=stages[name];
  }
  if(!Object.keys(rows).length)throw Error('Pipeline resource diagnostics require stage evidence.');
  const wait=scheduler&&finite(scheduler.waitMs)&&scheduler.waitMs>=0?{status:'available',waitMilliseconds:round(scheduler.waitMs),admissionMode:typeof scheduler.crossContextMode==='string'&&scheduler.crossContextMode.length<=MAX_MODE?scheduler.crossContextMode:'unknown',reason:null}:{status:'unavailable',waitMilliseconds:null,admissionMode:null,reason:'scheduler-not-observed'};
  validateScheduler(wait);
  if(!finite(totalWallClockMs)||totalWallClockMs<0)throw Error('Invalid pipeline resource wall-clock.');
  const result={schemaVersion:VERSION,kind:'analysis-pipeline-resources',totalWallClockMs:round(totalWallClockMs),scheduler:wait,stages:rows};
  validatePipeline(result);
  return result;
 }
 const api={schemaVersion:VERSION,create,validate,validatePipeline,pipeline};
 root.LightForgeResourceDiagnostics=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof self!=='undefined'?self:globalThis);
