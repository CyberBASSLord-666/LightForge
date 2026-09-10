'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const Resource=require('../web/analysis/resource-diagnostics.js');

const analysisRoot=path.resolve(__dirname,'../web/analysis');
function diagnosticVm({hostile=false}={}){
 const sandbox={};
 if(hostile){
  const navigator={};Object.defineProperty(navigator,'hardwareConcurrency',{get(){throw Error('privacy-wrapper-hardware-concurrency');}});
  const performance={now:()=>100};Object.defineProperty(performance,'memory',{get(){throw Error('privacy-wrapper-performance-memory');}});
  Object.defineProperty(sandbox,'navigator',{configurable:true,get(){return navigator;}});
  Object.defineProperty(sandbox,'performance',{configurable:true,get(){return performance;}});
 }
 sandbox.self=sandbox;
 const context=vm.createContext(sandbox);
 for(const file of ['resource-diagnostics.js','telemetry.js'])vm.runInContext(fs.readFileSync(path.join(analysisRoot,file),'utf8'),context,{filename:file});
 return context;
}
function hostileWorkerThreadCount(){
 const sandbox={importScripts:()=>{},postMessage:()=>{},SharedArrayBuffer:function SharedArrayBuffer(){}};
 const navigator={};Object.defineProperty(navigator,'hardwareConcurrency',{get(){throw Error('privacy-wrapper-worker-hardware-concurrency');}});
 Object.defineProperty(sandbox,'navigator',{configurable:true,get(){return navigator;}});
 sandbox.crossOriginIsolated=true;sandbox.self=sandbox;
 const context=vm.createContext(sandbox);
 vm.runInContext(fs.readFileSync(path.join(analysisRoot,'worker.js'),'utf8'),context,{filename:'worker.js'});
 return vm.runInContext('wasmThreadCount()',context);
}

test('resource diagnostics distinguish unavailable browser metrics from zero observations',()=>{
 const snapshot=Resource.create('rhythm').snapshot();
 assert.equal(Resource.validate(snapshot),true);
 assert.equal(snapshot.wallClock.status,'available');
 assert.equal(snapshot.io.status,'unavailable');
 assert.equal(snapshot.io.readBytes,null);
 assert.equal(snapshot.allocations.status,'unavailable');
 assert.equal(snapshot.cpu.utilization.status,'unavailable');
 assert.equal(snapshot.cpu.utilization.percent,null);
 assert.equal(snapshot.accelerator.utilization.status,'unavailable');
 assert.equal(snapshot.accelerator.utilization.percent,null);
});

test('instrumented cache, IO and buffer counters are bounded and pipeline scheduler wait stays separate',()=>{
 const recorder=Resource.create('separation');
 recorder.cache('hit');recorder.cache('miss');recorder.cache('not-a-known-outcome');
 assert.equal(recorder.io('read',4096,'opfs-analysis-store'),true);
 assert.equal(recorder.io('write',2048,'opfs-analysis-store'),true);
 assert.equal(recorder.allocation(8192,2),true);
 assert.equal(recorder.copy(4096,1),true);
 assert.equal(recorder.io('read',-1,'bad'),false);
 assert.equal(recorder.allocation(-1),false);
 const stage=recorder.snapshot();
 assert.equal(stage.cache.outcomes.hit,1);assert.equal(stage.cache.outcomes.miss,1);assert.equal(stage.cache.outcomes.unknown,1);
 assert.deepEqual(stage.io,{status:'partial',readBytes:4096,writeBytes:2048,readOperations:1,writeOperations:1,coverage:['opfs-analysis-store'],reason:'decoder-model-and-stem-cache-io-not-fully-instrumented'});
 assert.deepEqual(stage.allocations,{status:'partial',allocationBytes:8192,allocationCount:2,copyBytes:4096,copyCount:1,reason:'only-instrumented-buffer-operations-are-counted'});
 const pipeline=Resource.pipeline({separation:stage},{waitMs:17.25,crossContextMode:'web-locks'},41.5);
 assert.equal(Resource.validatePipeline(pipeline),true);
 assert.deepEqual(pipeline.scheduler,{status:'available',waitMilliseconds:17.25,admissionMode:'web-locks',reason:null});
});

test('malformed resource evidence fails closed instead of being converted to an optimistic measurement',()=>{
 const stage=Resource.create('bass').snapshot();
 const malformed=structuredClone(stage);malformed.io={...malformed.io,status:'partial',readBytes:0,writeBytes:0,readOperations:0,writeOperations:0,coverage:[],reason:null};
 assert.throws(()=>Resource.validate(malformed),/Invalid resource io|Instrumented resource io|Partial resource io/);
 const pipeline=Resource.pipeline({bass:stage},null,1);
 pipeline.scheduler={status:'available',waitMilliseconds:null,admissionMode:'web-locks',reason:null};
 assert.throws(()=>Resource.validatePipeline(pipeline),/scheduler/);
 assert.throws(()=>Resource.create('not a valid stage'),/Invalid resource diagnostics stage/);
});

test('hostile privacy getters become explicit observed-error evidence without aborting resource or legacy telemetry snapshots',()=>{
 const context=diagnosticVm({hostile:true}),remoteResource=context.LightForgeResourceDiagnostics,remoteTelemetry=context.LightForgeAnalysisTelemetry;
 let stage;assert.doesNotThrow(()=>{stage=remoteResource.create('voice').snapshot();});
 assert.equal(stage.jsHeap.status,'unavailable');
 assert.equal(stage.jsHeap.reason,'performance-memory-api-observed-error');
 assert.equal(stage.cpu.status,'unavailable');
 assert.equal(stage.cpu.reason,'navigator-hardware-concurrency-observed-error');
 assert.equal(remoteResource.validate(stage),true);
 let profile;assert.doesNotThrow(()=>{profile=remoteTelemetry.create('voice').snapshot();});
 assert.equal(profile.runtime.hardwareConcurrency,null);
 assert.equal(profile.runtime.jsHeapUsedBytes,null);
 assert.equal(profile.runtime.observations.hardwareConcurrency.status,'observed-error');
 assert.equal(profile.runtime.observations.jsHeap.status,'observed-error');
 assert.equal(profile.resources.jsHeap.reason,'performance-memory-api-observed-error');
 assert.equal(profile.resources.cpu.reason,'navigator-hardware-concurrency-observed-error');
 let threads;assert.doesNotThrow(()=>{threads=hostileWorkerThreadCount();});
 assert.equal(threads,1);
});

test('unavailable browser APIs remain explicitly unavailable and cross-realm diagnostics validate safely',()=>{
 const context=diagnosticVm(),remoteResource=context.LightForgeResourceDiagnostics,remoteTelemetry=context.LightForgeAnalysisTelemetry;
 const foreignStage=remoteResource.create('bass').snapshot();
 assert.equal(foreignStage.jsHeap.reason,'performance-memory-api-unavailable');
 assert.equal(foreignStage.cpu.reason,'navigator-hardware-concurrency-unavailable');
 assert.equal(Resource.validate(foreignStage),true);
 const pipeline=Resource.pipeline({bass:foreignStage},null,1);
 assert.equal(Resource.validatePipeline(pipeline),true);
 const profile=remoteTelemetry.create('bass').snapshot();
 assert.equal(profile.runtime.observations.hardwareConcurrency.status,'unavailable');
 assert.equal(profile.runtime.observations.jsHeap.status,'unavailable');
});

test('pipeline integrity rejects a stage-map key that disagrees with the embedded stage',()=>{
 const bass=Resource.create('bass').snapshot();
 assert.throws(()=>Resource.pipeline({rhythm:bass},null,1),/stage mapping/);
 const pipeline=Resource.pipeline({bass},null,1);
 pipeline.stages.bass={...bass,stage:'rhythm'};
 assert.throws(()=>Resource.validatePipeline(pipeline),/stage mapping/);
});
