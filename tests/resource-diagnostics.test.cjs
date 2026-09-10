'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const Resource=require('../web/analysis/resource-diagnostics.js');

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
