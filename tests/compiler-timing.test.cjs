'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {webcrypto}=require('node:crypto');
const Engine=require('../web/engine/show-engine.js');
const Telemetry=require('../web/analysis/telemetry.js');
const ROOT=path.join(__dirname,'..');
const metric=name=>'performance.'+name;
const names=['choreography_planning','collision_resolution','vehicle_realization','validation','fseq_generation'].map(metric);
function music(duration=24){
 const beats=Array.from({length:Math.floor(duration*2)},(_,i)=>i*.5);
 return {duration,bpm:120,beatConfidence:.95,beats,downbeats:beats.filter((_,i)=>i%4===0),
  sections:[{start:0,end:duration/2,energy:.7},{start:duration/2,end:duration,energy:.9}],
  waveform:Array(120).fill(.6),onsets:beats.map(time=>({time,strength:.8,band:'bass'})),
  impacts:[{time:duration/2,strength:.95,kind:'transition'}],
  bassNotes:[{start:2,end:3,confidence:.95,strength:.9,midi:40}],bassAnalysis:{confidence:.95,phrases:[]}};
}
function tracked(profile){
 let active=null;const spans=[];
 return {spans,begin(name){assert.equal(active,null,'compiler phases must not overlap');active=name;return profile.begin(name);},
  end(token,attributes){assert.equal(token,active);const result=profile.end(token,attributes);spans.push({name:token,...attributes});active=null;return result;},
  measure(name,fn,attributes){const token=this.begin(name);try{return fn();}finally{this.end(token,attributes);}},
  snapshot(){assert.equal(active,null,'every executed phase must close');return profile.snapshot();}};
}
function clockProfile(now){
 const context=vm.createContext({performance:{now},Date:{now:()=>{throw Error('No fallback clock');}}});context.self=context;
 vm.runInContext(fs.readFileSync(path.join(ROOT,'web/analysis/telemetry.js'),'utf8'),context);
 return context.LightForgeAnalysisTelemetry.create('compiler');
}
test('real compilation probes preserve deterministic show and complete FSEQ bytes',()=>{
 const input=music(),settings={stepMs:20,seed:719,dance:'balanced'};
 const expected=Engine.generate(input,settings),timing=tracked(Telemetry.create('compiler'));
 const show=Engine.generate(input,settings,timing);
 assert.deepEqual(show,expected,'timings never enter deterministic show metadata');
 assert.deepEqual(Engine.fseq(show,'timing.wav',timing),Engine.fseq(expected,'timing.wav'));
 const profile=timing.snapshot();
 for(const name of names){const row=profile.spanSummary[name];assert.ok(row&&row.count>0,name);assert.ok(Number.isFinite(row.totalMs)&&row.totalMs>=0,name);}
 assert.equal(profile.spans.some(span=>span.unfinished),false);
 const fseq=timing.spans.filter(span=>span.name===metric('fseq_generation'));
 assert.deepEqual(fseq.map(span=>span.scope),['header-serialization','contiguous-header-and-frame-payload']);
 assert.ok(timing.spans.some(span=>span.scope==='movement-targets-and-feasibility-planning'));
 assert.ok(timing.spans.some(span=>span.scope==='accepted-light-frame-commands'));
 for(const scope of ['synchronization-review','choreography-quality','perceptual-event-evidence','show-frame-format'])assert.ok(timing.spans.some(span=>span.scope===scope),scope);
});
test('header-only execution records one FSEQ interval and separate repeated validation',()=>{
 let tick=0;const timing=tracked(clockProfile(()=>tick++)),input=music(8);
 const show=Engine.generate(input,{dance:'off'},timing),before=timing.snapshot();
 assert.equal(before.spanSummary[metric('fseq_generation')],undefined,'unexecuted export is not zero time');
 const validationCount=before.spanSummary[metric('validation')].count;
 Engine.fseqHeader(show,'header.wav',timing);
 const after=timing.snapshot();
 assert.equal(after.spanSummary[metric('fseq_generation')].count,1);
 assert.equal(after.spanSummary[metric('fseq_generation')].totalMs,1);
 assert.equal(after.spanSummary[metric('validation')].count,validationCount+1);
 assert.deepEqual(timing.spans.slice(-2).map(span=>span.name),[metric('validation'),metric('fseq_generation')]);
});
test('clock failure remains unavailable while show and export output stay unchanged',()=>{
 let tick=0;const timing=tracked(clockProfile(()=>++tick<4?tick:NaN));
 const input=music(8),expected=Engine.generate(input,{dance:'off'}),show=Engine.generate(input,{dance:'off'},timing);
 assert.deepEqual(show,expected);
 assert.deepEqual(Engine.fseq(show,'clock.wav',timing),Engine.fseq(expected,'clock.wav'));
 const profile=timing.snapshot();assert.equal(profile.timing.state,'observed-error');
 for(const name of names){assert.equal(profile.spanSummary[name].totalMs,null,name);assert.ok(profile.spanSummary[name].unavailableCount>0,name);}
});
test('failed validation never reports unexecuted FSEQ assembly and closes its interval',()=>{
 const timing=tracked(Telemetry.create('compiler'));
 assert.throws(()=>Engine.fseq({frames:new Uint8Array(1)},'invalid.wav',timing));
 const profile=timing.snapshot();
 assert.equal(profile.spanSummary[metric('validation')].count,1);
 assert.equal(profile.spanSummary[metric('fseq_generation')],undefined);
});
test('failed semantic composition attempts close both partial and complete phases before retry',()=>{
 const Timeline=require('../web/analysis/semantic-timeline.js'),Salience=require('../web/analysis/salience.js');
 const Lights=require('../web/engine/light-planner.js'),input=music();
 input.semanticTimeline=Timeline.build(input);input.musicSalience=Salience.build(input.semanticTimeline);
 const key=require.resolve('../web/engine/show-engine.js'),cached=require.cache[key],prior=globalThis.LightPlanner;
 let attempts=0,failDuringPlanning=false;
 globalThis.LightPlanner={...Lights,compose(...args){
  const first=++attempts===1;
  if(first&&failDuringPlanning)args[4]={prepareTargets(){throw Error('Injected in-progress planning failure');}};
  const result=Lights.compose(...args);if(first)throw Error('Injected completed optional attempt failure');return result;
 }};
 delete require.cache[key];
 try{
  const isolated=require('../web/engine/show-engine.js'),settings={semanticChoreography:true,dance:'off'};
  for(const partial of [false,true]){
   failDuringPlanning=partial;attempts=0;
   const expected=isolated.generate(input,settings);assert.equal(attempts,2);
   attempts=0;const timing=tracked(Telemetry.create('compiler')),show=isolated.generate(input,settings,timing);
   assert.equal(attempts,2);assert.deepEqual(show,expected);
   const profile=timing.snapshot();assert.equal(profile.spanSummary[metric('collision_resolution')].count,partial?1:2);
   assert.equal(timing.spans.filter(span=>span.scope==='accepted-light-frame-commands').length,partial?1:2);
   assert.equal(timing.spans.filter(span=>span.scope==='light-candidate-planning').length,2);
  }
 }finally{delete require.cache[key];require.cache[key]=cached;if(prior===undefined)delete globalThis.LightPlanner;else globalThis.LightPlanner=prior;}
});
async function worker(data){
 const messages=[],context=vm.createContext({crypto:webcrypto,TextEncoder,TextDecoder,Uint8Array,ArrayBuffer,DataView,
  Blob,Response,ReadableStream,CompressionStream,DecompressionStream,btoa,atob,setTimeout,performance,
  postMessage:message=>messages.push(message)});context.self=context;
 context.importScripts=(...files)=>{for(const file of files)vm.runInContext(fs.readFileSync(path.resolve(ROOT,'web/engine',file),'utf8'),context,{filename:file});};
 vm.runInContext(fs.readFileSync(path.join(ROOT,'web/engine/worker.js'),'utf8'),context,{filename:'engine/worker.js'});
 await context.onmessage({data});const terminal=messages.find(message=>['result','error'].includes(message.type));
 assert.ok(terminal,'worker must emit a terminal result');return terminal;
}
test('production worker keeps compiler profile separate from saved show and reports restore scope',async()=>{
 const input=music(8),settings={dance:'off'},generated=await worker({action:'generate',music:input,settings});
 assert.equal(generated.type,'result',generated.message);const {show,compiled,header,profile}=generated.value;
 assert.equal(profile.stage,'compiler');assert.equal(profile.attributes.outcome,'completed');
 assert.equal(profile.attributes.fseqGenerationScope,'header-only');assert.equal(profile.attributes.fseqPayloadAssembly,'not-executed');
 assert.equal(profile.spanSummary[metric('fseq_generation')].count,1);
 assert.equal(Object.hasOwn(show,'profile'),false);assert.equal(Object.hasOwn(compiled.meta,'profile'),false);
 const saved=JSON.stringify(compiled),restored=await worker({action:'restore',music:input,settings,compiled});
 assert.equal(restored.type,'result',restored.message);assert.equal(JSON.stringify(restored.value.compiled),saved);
 assert.deepEqual(restored.value.show.frames,show.frames);assert.deepEqual(restored.value.header,header);
 assert.equal(restored.value.profile.attributes.action,'restore');
 for(const name of ['choreography_planning','collision_resolution','vehicle_realization'])assert.equal(restored.value.profile.spanSummary[metric(name)],undefined,'restore must not fabricate '+name);
 assert.equal(restored.value.profile.spanSummary[metric('validation')].count,2);
 const failed=await worker({action:'restore',music:input,settings,compiled:{...compiled,sha256:'0'.repeat(64)}});
 assert.equal(failed.type,'error');assert.equal(failed.profile.attributes.outcome,'failed');
 assert.equal(failed.profile.spanSummary[metric('fseq_generation')],undefined);
});
