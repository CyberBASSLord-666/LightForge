'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const telemetry=require('../web/analysis/telemetry.js');
const source=fs.readFileSync(path.join(__dirname,'..','web','analysis','telemetry.js'),'utf8');
const clockSource=fs.readFileSync(path.join(__dirname,'..','web','analysis','diagnostic-clock.js'),'utf8');
function virtualProfile(configure){
 const context=vm.createContext({});configure(context);context.self=context;
 vm.runInContext(source,context);return context.LightForgeAnalysisTelemetry.create('hostile-runtime');
}
function virtualClock(configure){
 const context=vm.createContext({});configure(context);context.self=context;
 vm.runInContext(clockSource,context);return context.LightForgeDiagnosticClock.create(context);
}
function runtimeSnapshot(runtime){return {hardwareConcurrency:runtime.hardwareConcurrency,deviceMemoryGiB:runtime.deviceMemoryGiB,crossOriginIsolated:runtime.crossOriginIsolated,jsHeapUsedBytes:runtime.jsHeapUsedBytes,jsHeapLimitBytes:runtime.jsHeapLimitBytes};}

async function main(){
 const profile=telemetry.create('separation');
 const token=profile.begin('model.initialization');
 profile.end(token,{model:'Deux'});
 profile.cache('stems','hit',{bytes:42});
 profile.increment('passages',2);
 profile.io('read',128,'opfs-analysis-store');profile.allocation(64);profile.copy(32);
 await profile.measureAsync('checkpoint.write',async()=>{});
 const out=profile.snapshot({quality:'precision'});
 assert.equal(out.schemaVersion,1);assert.equal(out.stage,'separation');
 assert.equal(out.cache[0].outcome,'hit');assert.equal(out.counters.passages,2);
 assert.ok(out.totalWallClockMs>=0);assert.equal(out.attributes.quality,'precision');
 assert.ok(out.spanSummary['model.initialization'].count===1);
 assert.equal(out.resources.kind,'analysis-stage-resources');assert.equal(out.resources.stage,'separation');
 assert.equal(out.resources.io.readBytes,128);assert.equal(out.resources.allocations.copyBytes,32);
 const normal=virtualProfile(context=>{context.performance={now:()=>17,memory:{usedJSHeapSize:31,jsHeapSizeLimit:47}};context.navigator={hardwareConcurrency:6,deviceMemory:12};context.crossOriginIsolated=true;}).snapshot();
 assert.deepEqual(runtimeSnapshot(normal.runtime),{hardwareConcurrency:6,deviceMemoryGiB:12,crossOriginIsolated:true,jsHeapUsedBytes:31,jsHeapLimitBytes:47});
 assert.deepEqual({...normal.timing},{source:'performance.now',state:'available'});
 const hostile=[
  ['performance.now',context=>{context.performance={};Object.defineProperty(context.performance,'now',{get(){throw Error('blocked clock');}});context.navigator={};}],
  ['performance.memory',context=>{context.performance={now:()=>0};Object.defineProperty(context.performance,'memory',{get(){throw Error('blocked memory');}});context.navigator={};}],
  ['navigator.hardwareConcurrency',context=>{context.performance={now:()=>0};context.navigator={};Object.defineProperty(context.navigator,'hardwareConcurrency',{get(){throw Error('blocked hardware');}});}],
  ['navigator.deviceMemory',context=>{context.performance={now:()=>0};context.navigator={};Object.defineProperty(context.navigator,'deviceMemory',{get(){throw Error('blocked memory class');}});}],
  ['crossOriginIsolated',context=>{context.performance={now:()=>0};context.navigator={};Object.defineProperty(context,'crossOriginIsolated',{get(){throw Error('blocked isolation');}});}]
 ];
 for(const [label,configure] of hostile){
  let snapshot;assert.doesNotThrow(()=>{snapshot=virtualProfile(configure).snapshot();},label+' must not turn a completed stage into an error');
  assert.deepEqual(runtimeSnapshot(snapshot.runtime),{hardwareConcurrency:null,deviceMemoryGiB:null,crossOriginIsolated:false,jsHeapUsedBytes:null,jsHeapLimitBytes:null},label+' must be represented as unavailable telemetry');
 }
 let calls=0;const late=virtualProfile(context=>{context.performance={};Object.defineProperty(context.performance,'now',{get(){calls++;if(calls<=2)return ()=>calls===1?100:120;throw Error('late clock getter failure');}});context.navigator={};});
 const lateToken=late.begin('late-clock');late.end(lateToken);const lateSnapshot=late.snapshot();
 assert.equal(lateSnapshot.totalWallClockMs,0,'a late performance getter failure must not be mixed with Date.now');assert.equal(lateSnapshot.spans[0].durationMs,0);assert.equal(calls,1,'telemetry must retain its selected performance callable');assert.deepEqual({...lateSnapshot.timing},{source:'performance.now',state:'available'});
 let functionCalls=0;const lateFunction=virtualProfile(context=>{context.performance={now(){functionCalls++;if(functionCalls<=2)return functionCalls*100;throw Error('late clock function failure');}};context.navigator={};});
 const functionToken=lateFunction.begin('late-clock-function');lateFunction.end(functionToken);const functionSnapshot=lateFunction.snapshot();
 assert.equal(functionSnapshot.totalWallClockMs,0,'a late performance function failure must not be mixed with Date.now');assert.equal(functionSnapshot.spans[0].durationMs,0);assert.deepEqual({...functionSnapshot.timing},{source:'performance.now',state:'observed-error'});
 let profileSourceReads=0;const switchingProfile=virtualProfile(context=>{context.Date={now:()=>1789000000000};Object.defineProperty(context,'performance',{get(){profileSourceReads++;return profileSourceReads===1?{now:()=>10}:{now:()=>1789000000000};}});context.navigator={};});
 const switchToken=switchingProfile.begin('switching-clock');switchingProfile.end(switchToken);const switchSnapshot=switchingProfile.snapshot();
 assert.equal(switchSnapshot.totalWallClockMs,0,'telemetry must not replace performance time with epoch time');assert.equal(switchSnapshot.spans[0].durationMs,0);assert.equal(profileSourceReads,2,'only the unrelated runtime probe may reread performance');assert.deepEqual({...switchSnapshot.timing},{source:'performance.now',state:'available'});
 let dateSourceReads=0;const switchingDateProfile=virtualProfile(context=>{context.performance={};Object.defineProperty(context,'Date',{get(){dateSourceReads++;return dateSourceReads===1?{now:()=>10}:{now:()=>1789000000000};}});context.navigator={};});
 const dateSwitchToken=switchingDateProfile.begin('switching-date-clock');switchingDateProfile.end(dateSwitchToken);const dateSwitchSnapshot=switchingDateProfile.snapshot();
 assert.equal(dateSwitchSnapshot.totalWallClockMs,0,'telemetry fallback must not switch Date origins');assert.equal(dateSwitchSnapshot.spans[0].durationMs,0);assert.equal(dateSourceReads,1);assert.deepEqual({...dateSwitchSnapshot.timing},{source:'date.now',state:'available'});
 let descendingCalls=0;const descendingProfile=virtualProfile(context=>{context.performance={now:()=>++descendingCalls===1?10:9};context.navigator={};});
 const descendingToken=descendingProfile.begin('nonmonotonic-clock');descendingProfile.end(descendingToken);const descendingSnapshot=descendingProfile.snapshot();
 assert.equal(descendingSnapshot.totalWallClockMs,0);assert.equal(descendingSnapshot.spans[0].durationMs,0);assert.deepEqual({...descendingSnapshot.timing},{source:'performance.now',state:'observed-error'});
 const unavailable=virtualClock(context=>{context.performance={};context.Date={};});
 assert.equal(unavailable.source,'unavailable');assert.equal(unavailable.elapsed(unavailable.start),0);assert.deepEqual({...unavailable.diagnostics()},{source:'unavailable',state:'unavailable',reason:'date-now-unavailable'});
 const fallback=virtualClock(context=>{context.performance={};context.Date={now:()=>50};});
 assert.equal(fallback.source,'date.now');assert.equal(fallback.elapsed(fallback.start),0);assert.deepEqual({...fallback.diagnostics()},{source:'date.now',state:'fallback',reason:'performance-now-unavailable'});
 let clockGetterCalls=0;const clockGetter=virtualClock(context=>{context.Date={now:()=>1789000000000};context.performance={};Object.defineProperty(context.performance,'now',{get(){clockGetterCalls++;if(clockGetterCalls===1)return ()=>100;throw Error('late clock getter');}});});
 assert.equal(clockGetter.elapsed(clockGetter.start),0);assert.equal(clockGetterCalls,1,'the diagnostic clock must retain its selected performance callable');assert.deepEqual({...clockGetter.diagnostics()},{source:'performance.now',state:'available',reason:null});
 let clockFunctionCalls=0;const clockFunction=virtualClock(context=>{context.Date={now:()=>1789000000000};context.performance={now(){clockFunctionCalls++;if(clockFunctionCalls===1)return 100;throw Error('late clock function');}};});
 assert.equal(clockFunction.elapsed(clockFunction.start),0);assert.deepEqual({...clockFunction.diagnostics()},{source:'performance.now',state:'observed-error',reason:'performance-now-observed-error'});
 let clockSourceReads=0;const switchingClock=virtualClock(context=>{context.Date={now:()=>1789000000000};Object.defineProperty(context,'performance',{get(){clockSourceReads++;return clockSourceReads===1?{now:()=>10}:{now:()=>1789000000000};}});});
 assert.equal(switchingClock.elapsed(switchingClock.start),0,'the diagnostic clock must not switch origins after creation');assert.equal(clockSourceReads,1);assert.deepEqual({...switchingClock.diagnostics()},{source:'performance.now',state:'available',reason:null});
 let clockDateReads=0;const switchingDateClock=virtualClock(context=>{context.performance={};Object.defineProperty(context,'Date',{get(){clockDateReads++;return clockDateReads===1?{now:()=>10}:{now:()=>1789000000000};}});});
 assert.equal(switchingDateClock.elapsed(switchingDateClock.start),0,'the diagnostic fallback must not switch Date origins');assert.equal(clockDateReads,1);assert.deepEqual({...switchingDateClock.diagnostics()},{source:'date.now',state:'fallback',reason:'performance-now-unavailable'});
 let descendingClockCalls=0;const descendingClock=virtualClock(context=>{context.performance={now:()=>++descendingClockCalls===1?10:9};context.Date={now:()=>1789000000000};});
 assert.equal(descendingClock.elapsed(descendingClock.start),0);assert.deepEqual({...descendingClock.diagnostics()},{source:'performance.now',state:'unavailable',reason:'performance.now-nonmonotonic'});
 console.log('Analysis telemetry contract passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
