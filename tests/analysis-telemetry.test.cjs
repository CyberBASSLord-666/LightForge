'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const telemetry=require('../web/analysis/telemetry.js');
const source=fs.readFileSync(path.join(__dirname,'..','web','analysis','telemetry.js'),'utf8');
function virtualProfile(configure){
 const context=vm.createContext({});configure(context);context.self=context;
 vm.runInContext(source,context);return context.LightForgeAnalysisTelemetry.create('hostile-runtime');
}

async function main(){
 const profile=telemetry.create('separation');
 const token=profile.begin('model.initialization');
 profile.end(token,{model:'Deux'});
 profile.cache('stems','hit',{bytes:42});
 profile.increment('passages',2);
 await profile.measureAsync('checkpoint.write',async()=>{});
 const out=profile.snapshot({quality:'precision'});
 assert.equal(out.schemaVersion,1);assert.equal(out.stage,'separation');
 assert.equal(out.cache[0].outcome,'hit');assert.equal(out.counters.passages,2);
 assert.ok(out.totalWallClockMs>=0);assert.equal(out.attributes.quality,'precision');
 assert.ok(out.spanSummary['model.initialization'].count===1);
 const normal=virtualProfile(context=>{context.performance={now:()=>17,memory:{usedJSHeapSize:31,jsHeapSizeLimit:47}};context.navigator={hardwareConcurrency:6,deviceMemory:12};context.crossOriginIsolated=true;}).snapshot();
 assert.deepEqual({...normal.runtime},{hardwareConcurrency:6,deviceMemoryGiB:12,crossOriginIsolated:true,jsHeapUsedBytes:31,jsHeapLimitBytes:47});
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
  assert.deepEqual({...snapshot.runtime},{hardwareConcurrency:null,deviceMemoryGiB:null,crossOriginIsolated:false,jsHeapUsedBytes:null,jsHeapLimitBytes:null},label+' must be represented as unavailable telemetry');
 }
 let calls=0;const late=virtualProfile(context=>{context.performance={};Object.defineProperty(context.performance,'now',{get(){calls++;if(calls<=2)return ()=>calls===1?100:120;throw Error('late clock getter failure');}});context.navigator={};});
 const token=late.begin('late-clock');late.end(token);const lateSnapshot=late.snapshot();
 assert.equal(lateSnapshot.totalWallClockMs,0,'a late performance getter failure must not be mixed with Date.now');assert.equal(lateSnapshot.spans[0].durationMs,0);assert.deepEqual({...lateSnapshot.timing},{source:'performance.now',state:'observed-error'});
 let functionCalls=0;const lateFunction=virtualProfile(context=>{context.performance={now(){functionCalls++;if(functionCalls<=2)return functionCalls*100;throw Error('late clock function failure');}};context.navigator={};});
 const functionToken=lateFunction.begin('late-clock-function');lateFunction.end(functionToken);const functionSnapshot=lateFunction.snapshot();
 assert.equal(functionSnapshot.totalWallClockMs,0,'a late performance function failure must not be mixed with Date.now');assert.equal(functionSnapshot.spans[0].durationMs,0);assert.deepEqual({...functionSnapshot.timing},{source:'performance.now',state:'observed-error'});
 console.log('Analysis telemetry contract passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
