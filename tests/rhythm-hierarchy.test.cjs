'use strict';
const assert=require('assert');
const fs=require('fs');
const path=require('path');
const vm=require('vm');
const {test:nodeTest}=require('node:test');
const context={console};context.self=context;vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/analysis/rhythm-hierarchy.js'),'utf8'),context,{filename:'rhythm-hierarchy.js'});
const api=context.LightForgeRhythmHierarchy;
const close=(actual,expected,message)=>assert.ok(Math.abs(actual-expected)<1e-3,message||`${actual} !== ${expected}`);

function rhythm(overrides={}){
 const beats=[0,.5,1,1.5,2,2.5,3,3.5,4,4.666667,5.333333,6,6.666667,7.333333,8,8.666667];
 return {
  duration:9,
  beats,
  downbeats:[0,2,4,6.666667],
  beatDetails:beats.map((time,index)=>({time,confidence:.9,localBpm:index<8?120:90,barPosition:index<8?(index%4)+1:((index-8)%4)+1})),
  bpm:100,
  meter:4,
  beatConfidence:.9,
  downbeatConfidence:.85,
  meterConfidence:.88,
  onsets:[{time:.125,strength:.8,band:'high'},{time:.25,strength:.8,band:'high'},{time:1.5,strength:.7,band:'bass'},{time:4.333333,strength:.9,band:'mid'}],
  phrases:[{start:0,end:4,kind:'groove',confidence:.8}],
  sections:[{start:0,end:9,label:'Opening',confidence:.8,recurrenceGroup:'section-0',repetitionIndex:0}],
  ...overrides
 };
}

{
 const input=rhythm(),original=JSON.stringify(input),result=api.build(input);
 assert.equal(result.schemaVersion,1);
 assert.equal(result.kind,'evidence-aware-rhythm-hierarchy');
 assert.equal(result.beats.length,input.beats.length);
 assert.equal(result.downbeats.length,input.downbeats.length);
 assert.equal(result.bars.length,4);
 assert.equal(result.bars[0].complete,true);
 assert.equal(result.bars[0].verified,true);
 assert.equal(result.tempo.variable,true);
 assert.equal(result.tempo.segments.length,2);
 close(result.tempo.segments[0].bpm,120);
 close(result.tempo.segments[1].bpm,90);
 assert.ok(result.subdivisions.some(value=>value.kind==='quarter-subdivision'));
 assert.equal(JSON.stringify(input),original,'building the sidecar must not rewrite legacy data');
 assert.deepEqual(api.validate(result,input),{valid:true});
}

{
 const input=rhythm({beats:[0,.5,1,2,2.5,3,3.5],downbeats:[0,2],beatDetails:[0,.5,1,2,2.5,3,3.5].map((time,index)=>({time,confidence:.8,localBpm:120,barPosition:(index%4)+1}))});
 const result=api.build(input);
 assert.equal(result.tempo.halfDouble.ambiguous,true);
 assert.ok(result.tempo.halfDouble.evidence.some(value=>value.kind==='missing-or-half-time-interval'));
 assert.deepEqual(result.beats.map(value=>value.time),input.beats,'ambiguity must not substitute an alternate beat grid');
 assert.equal(result.tempo.halfDouble.safeguard,'No alternate grid is substituted for the approved beat map.');
}

{
 const input=rhythm({beats:[],downbeats:[],beatDetails:[],bpm:0,meter:4});
 const result=api.build(input);
 assert.equal(result.status,'no-pulse');
 assert.equal(result.bars.length,0);
 assert.ok(result.limitations.some(value=>value.includes('No approved beat evidence')));
 assert.deepEqual(api.validate(result,input),{valid:true});
}

{
 const beats=[0,.5,1,1.5,2,2.5,3,3.5,4,4.5];
 const input=rhythm({beats,downbeats:[0,1.5,3,4.5],meter:4,beatDetails:beats.map((time,index)=>({time,confidence:.9,localBpm:120,barPosition:(index%3)+1}))});
 const result=api.build(input);
 assert.equal(result.meter.value,4,'the hierarchy must retain legacy meter authority');
 assert.equal(result.meter.candidates[0].value,3,'measured downbeat spacing should expose an alternate meter hypothesis');
 assert.ok(result.meter.safeguard.includes('without changing the beat grid'));
}

{
 const input=rhythm();
 const result=api.build(input);
 input.beats=input.beats.map(value=>value+.01);
 input.downbeats=input.downbeats.map(value=>value+.01);
 input.beatDetails=input.beatDetails.map(value=>({...value,time:value.time+.01}));
 assert.deepEqual(api.validate(result,input),{valid:false,reason:'stale'},'a changed grid must not reuse a stale hierarchy checkpoint');
}

{
 const input=rhythm();
 const result=api.build(input);
 input.onsets=[...input.onsets,{time:2.25,strength:.7,band:'bass'}];
 assert.deepEqual(api.validate(result,input),{valid:false,reason:'stale'},'a changed micro-onset map must not reuse a stale hierarchy checkpoint');
}

{
 const input=rhythm({beats:[0,.5,.5,1],downbeats:[0],beatDetails:[]});
 assert.equal(api.build(input),null,'non-monotonic model output is rejected rather than interpreted');
 const invalidDownbeat=rhythm({downbeats:[.2],beatDetails:rhythm().beatDetails});
 assert.equal(api.build(invalidDownbeat),null,'off-grid downbeats are rejected rather than snapped');
}

{
 const input=rhythm();
 const first=api.attach(input);
 assert.equal(first.attached,true);
 const second=api.attach(input);
 assert.equal(second.attached,false);
 assert.equal(second.reused,true);
}

nodeTest('cached rhythm sidecar is opt-in and never leaks into the legacy restore',async()=>{
 const workerSource=fs.readFileSync(path.join(__dirname,'../web/analysis/worker.js'),'utf8');
 const moduleSource=fs.readFileSync(path.join(__dirname,'../web/analysis/rhythm-hierarchy.js'),'utf8');
 async function run(options,cached){
  const messages=[],writes=[],workerContext={console,performance:{now:()=>10},postMessage:value=>messages.push(value),fetch:async()=>({json:async()=>({})})};
  workerContext.self=workerContext;
  workerContext.importScripts=(...names)=>{for(const name of names)if(name==='rhythm-hierarchy.js')vm.runInContext(moduleSource,workerContext,{filename:name});};
  workerContext.LightForgeAnalysisStore={open:async()=>({read:async()=>cached,write:async(...args)=>writes.push(args)})};
  vm.createContext(workerContext);
  vm.runInContext(workerSource,workerContext,{filename:'worker.js'});
  await workerContext.onmessage({data:{stage:'rhythm',audioUrl:'memory://audio',options,value:{}}});
  return {messages,writes};
 }
 const enabled=await run({rhythmHierarchy:true},rhythm());
 const enabledResult=enabled.messages.find(value=>value.type==='result');
 assert.ok(enabledResult?.value?.rhythmHierarchy);
 assert.equal(enabled.writes.length,1,'a validated opt-in hierarchy is checkpointed for reuse');
 const legacy=await run({},({...rhythm(),rhythmHierarchy:enabledResult.value.rhythmHierarchy}));
 const legacyResult=legacy.messages.find(value=>value.type==='result');
 assert.equal(legacyResult?.value?.rhythmHierarchy,undefined,'a default restore remains byte-compatible at the public legacy boundary');
 assert.equal(legacy.writes.length,0,'default restore must not churn the rhythm checkpoint');
});

console.log('rhythm hierarchy tests passed');
