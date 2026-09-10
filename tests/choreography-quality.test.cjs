'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const Quality=require('../web/engine/choreography-quality.js');

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
