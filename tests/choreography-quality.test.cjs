'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const Quality=require('../web/engine/choreography-quality.js');
const Engine=require('../web/engine/show-engine.js');
const Timeline=require('../web/analysis/semantic-timeline.js');
const Salience=require('../web/analysis/salience.js');

function fixture(){
  const frames=new Uint8Array(12*4),set=(frame,channel,value)=>{frames[frame*4+channel-1]=value;};
  // Two lighting gestures, then deliberate visual darkness. The motor remains
  // active during part of the darkness to ensure closure commands do not mask
  // a lighting negative-space result.
  set(0,1,255);set(1,1,255);
  set(3,2,255);set(4,2,255);
  set(0,3,63);set(1,3,63);set(3,3,191);set(5,3,63);
  return {
    channels:4,frameCount:12,stepMs:100,frames,settings:{},
    choreography:{negativeSpace:[{start:.6,end:.8}]},
    lightEvents:[
      {id:'left',channels:[1],actualStart:.1,actualEnd:.4,value:255},
      {id:'left',channels:[1],actualStart:.2,actualEnd:.5,value:0}
    ],
    movements:[]
  };
}
function profile(){
  return {id:'quality-fixture',outputs:[
    {id:'left',kind:'light',channels:[1]},
    {id:'right',kind:'light',channels:[2]},
    {id:'motor',kind:'closure',channels:[3],commandLimit:2}
  ]};
}
function options(){
  return {
    profile:profile(),windowMs:400,hopMs:200,visualSampleMs:100,
    minimumNegativeSpaceMs:200,minimumDurationMs:{motor:300},maximumTransitionsPerMinute:{left:20},includeWindows:true,
    tierTargets:[
      {time:0,tier:'structural',candidateOutputIds:['left']},
      {time:.6,tier:'climax',candidateOutputIds:['right']}
    ]
  };
}

test('quality sidecar is deterministic and never mutates exported frame bytes',()=>{
  const show=fixture(),before=Uint8Array.from(show.frames),first=Quality.evaluate(show,options()),second=Quality.analyze(show,options());
  assert.deepEqual(show.frames,before);
  assert.deepEqual(first,second);
  assert.equal(first.validInput,true);
  assert.equal(first.density.sampledTransitionCount,4);
  assert.equal(first.windows.windowCount,5);
  assert.equal(first.windows.rows.length,5);
  assert.equal(first.negativeSpace.declared.provided,true);
  assert.equal(first.negativeSpace.declared.fullyDarkCount,1);
  assert.ok(first.negativeSpace.longestObservedDurationMs>=600);
  assert.equal(first.repetition.adjacentRepeatCount,1);
  assert.ok(first.repetition.normalizedEntropy>=0&&first.repetition.normalizedEntropy<=1);
});

test('quality sidecar identifies configured feasibility violations and metadata conflicts',()=>{
  const result=Quality.evaluate(fixture(),options());
  assert.equal(result.actuatorOveruse.assessed,true);
  assert.equal(result.actuatorOveruse.overusedOutputCount,1);
  assert.equal(result.actuatorOveruse.outputs[0].observedCommandCount,3);
  assert.equal(result.outputOveruse.thresholdedOutputCount,1);
  assert.equal(result.outputOveruse.violationCount,1);
  assert.equal(result.minimumDurations.assessed,true);
  assert.equal(result.minimumDurations.violationCount,3);
  assert.equal(result.conflictingCommands.assessed,true);
  assert.equal(result.conflictingCommands.count,1);
  assert.deepEqual(result.conflictingCommands.rows[0].channel,1);
  assert.equal(result.hierarchy.assessed,true);
  assert.equal(result.hierarchy.tiers.structural.attackCoverage,1);
  assert.equal(result.hierarchy.tiers.climax.activeCoverage,0);
});

test('quality sidecar does not invent duration, actuator, target, or conflict limits',()=>{
  const show={channels:1,frameCount:4,stepMs:20,frames:Uint8Array.from([255,255,0,0]),settings:{}};
  const result=Quality.evaluate(show,{outputs:[{id:'raw-light',kind:'light',channels:[1]}]});
  assert.equal(result.minimumDurations.assessed,false);
  assert.equal(result.minimumDurations.violationCount,null);
  assert.equal(result.outputOveruse.violationCount,null);
  assert.equal(result.actuatorOveruse.assessed,false);
  assert.equal(result.hierarchy.assessed,false);
  assert.equal(result.conflictingCommands.assessed,false);
  assert.match(result.scope,/do not establish music-detection accuracy/);
});

test('quality sidecar rejects malformed frames without attempting a repair',()=>{
  const bad={channels:2,frameCount:2,stepMs:20,frames:new Uint8Array(3)};
  const result=Quality.evaluate(bad);
  assert.equal(result.validInput,false);
  assert.match(result.errors[0],/do not agree/);
});

test('ShowEngine attaches a read-only quality report without changing default FSEQ bytes',()=>{
  const music={
    duration:8,bpm:120,beatConfidence:.95,
    beats:Array.from({length:16},(_,index)=>index*.5),downbeats:[0,2,4,6],
    onsets:[{time:1,strength:.9,band:'bass'},{time:2,strength:.7,band:'mid'}],
    sections:[{start:0,end:4,energy:.45,label:'Verse'},{start:4,end:8,energy:.8,label:'Peak'}],
    waveform:Array(80).fill(.65)
  };
  const show=Engine.generate(music,{stepMs:20,dance:'off',seed:731});
  assert.equal(show.choreography.quality.validInput,true);
  assert.equal(show.choreography.quality.hierarchy.assessed,false,'no unlabelled target is promoted to a salience tier');
  const frames=Uint8Array.from(show.frames),before=Engine.fseq(show,'quality-fixture.wav');
  show.choreography.quality=Quality.evaluate(show);
  assert.deepEqual(show.frames,frames);
  assert.deepEqual(Engine.fseq(show,'quality-fixture.wav'),before,'diagnostic refresh must leave exported FSEQ bytes identical');
});

test('interactive and composition-worker engine contexts load quality diagnostics before ShowEngine',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../web/index.html'),'utf8');
  const sync=html.indexOf('engine/sync-review.js'),quality=html.indexOf('engine/choreography-quality.js'),engine=html.indexOf('engine/show-engine.js');
  assert.ok(sync>=0&&quality>sync&&engine>quality);
  const worker=fs.readFileSync(path.join(__dirname,'../web/engine/worker.js'),'utf8');
  const workerQuality=worker.indexOf("'choreography-quality.js'"),workerEngine=worker.indexOf("'show-engine.js'");
  assert.ok(workerQuality>=0&&workerEngine>workerQuality);
});

test('matching semantic salience annotates existing targets without changing planner output',()=>{
  const duration=80,beats=Array.from({length:duration*2},(_,index)=>index*.5);
  const music={
    duration,bpm:120,beatConfidence:.96,beats,downbeats:beats.filter((_,index)=>index%4===0),
    sections:[{start:0,end:20,energy:.2,label:'Intro'},{start:20,end:48,energy:.96,label:'Drop'},{start:48,end:duration,energy:.45,label:'Outro'}],
    phrases:[{start:20,end:42,energy:.96,kind:'drop',confidence:.95}],activityRanges:[{start:0,end:duration}],
    waveform:Array(400).fill(.72),onsets:[{time:20,strength:1,band:'bass'}],impacts:[{time:20,strength:1,kind:'drop'}],
    vocals:{available:true,presence:'detected',sourceSeparated:true,confidence:.96,phrases:[{start:20,end:24,confidence:.96,strength:.95,kind:'singing'}],accents:[{time:20,confidence:.96,strength:1,kind:'syllabic-accent'}],notes:[]},
    bassNotes:[{start:20,end:22,confidence:.95,strength:.95,midi:40}],bassAnalysis:{confidence:.95,phrases:[{start:20,end:22,confidence:.95,strength:.95}]}
  };
  const timeline=Timeline.build(music),salience=Salience.build(timeline),settings={stepMs:20,dance:'expressive',seed:88};
  const baseline=Engine.generate(music,settings);
  const annotated=Engine.generate({...music,semanticTimeline:timeline,musicSalience:salience},settings);
  assert.deepEqual(annotated.frames,baseline.frames);
  assert.deepEqual(Engine.fseq(annotated,'salience.wav'),Engine.fseq(baseline,'salience.wav'));
  assert.equal(annotated.choreography.salienceTargets.schemaVersion,1);
  assert.ok(annotated.choreography.salienceTargets.light.length>0);
  assert.ok(annotated.choreography.salienceTargets.movement.length>0);
  assert.equal(annotated.choreography.quality.hierarchy.assessed,true);
  const stale=Engine.generate({...music,semanticTimeline:timeline,musicSalience:{...salience,duration:duration-1}},settings);
  assert.equal(Object.hasOwn(stale.choreography,'salienceTargets'),false);
  assert.deepEqual(stale.frames,baseline.frames);
  assert.deepEqual(stale.synchronization,baseline.synchronization,'invalid salience leaves legacy synchronization inputs untouched');
});
