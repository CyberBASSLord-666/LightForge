'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const planner=require('../web/engine/light-planner.js');
const engine=require('../web/engine/show-engine.js');

function music(){
  return {
    duration:8,bpm:120,beatConfidence:.95,meter:4,
    beats:Array.from({length:16},(_,i)=>i*.5),downbeats:[0,2,4,6],
    waveform:Array(80).fill(.7),sections:[{start:0,end:8,energy:.9,index:0}],
    onsets:[],phrases:[],impacts:[{time:4,strength:.78}],
    vocals:{available:false,presence:'not_detected',phrases:[],accents:[],notes:[],confidence:0},
    bassNotes:[],bassAnalysis:{confidence:0,phrases:[]},energy:[],energyStep:0,groove:{},silent:false
  };
}
function settings(extra={}){
  return {stepMs:20,offsetMs:0,outputEnabled:{},outerBeamRamping:false,vocalFocus:.85,bassFocus:.9,
    sensitivity:.5,beatDivision:'quarter',style:'festival',seed:1,...extra};
}
function compose(extra={}){
  const show={frameCount:401,frames:new Uint8Array(401*200),
    sections:[{start:0,end:8,energy:.9,index:0,style:'festival',intensity:.9,variant:0,seed:1}]};
  return {show,result:planner.compose(show,music(),settings(extra),{accents:[]})};
}
function target(overrides={}){
  return {semanticEventId:'m000042',time:4,end:4.22,tier:'climax',salience:.95,role:'structure',
    candidateOutputIds:['left-outer'],fallbackOutputGroups:[['left-repeater','right-repeater']],...overrides};
}

test('keeps legacy planner frames and events byte-equivalent unless allocation is explicitly enabled',()=>{
  const baseline=compose();
  const disabled=compose({collisionAllocation:{enabled:false}});
  assert.deepEqual(Array.from(disabled.show.frames),Array.from(baseline.show.frames));
  assert.deepEqual(disabled.result.events,baseline.result.events);
  assert.deepEqual(disabled.result.diagnostics,baseline.result.diagnostics);
  assert.equal(baseline.result.diagnostics.semanticTargetAllocation,undefined);
  assert.equal(disabled.result.diagnostics.semanticTargetAllocation,undefined);
});

test('keeps ShowEngine FSEQ bytes unchanged for absent or explicitly disabled allocation',()=>{
  const legacy=engine.generate(music(),{dance:'off'});
  const disabled=engine.generate(music(),{dance:'off',collisionAllocation:{enabled:false}});
  assert.deepEqual(disabled.frames,legacy.frames);
  assert.deepEqual(engine.fseq(disabled),engine.fseq(legacy));
  assert.equal(disabled.choreography.lighting.semanticTargetAllocation,undefined);
});

test('atomically reroutes an explicitly lost high-salience semantic target through its configured fallback pair',()=>{
  const allocation={enabled:true,targets:[target()]};
  const first=compose({collisionAllocation:allocation}),{show,result}=first,d=result.diagnostics;
  assert.deepEqual(d.semanticTargetAllocation,{
    enabled:true,maxAllocations:128,minimumSalience:.78,tiers:['climax','structural'],
    requested:1,eligible:1,allocated:1,suppressed:0,skipped:0,omittedTargets:0,
    rows:[{
      targetId:'semantic-m000042-0',semanticEventId:'m000042',time:4,end:4.22,tier:'climax',salience:.95,
      preferredOutputIds:['left-outer'],chosenOutput:'left-repeater',chosenOutputs:['left-repeater','right-repeater'],
      outcome:'allocated',reason:'configured-fallback-after-preferred-loss'
    }]
  });
  const rerouted=result.events.filter(event=>event.semanticFallbackAllocation);
  assert.deepEqual(rerouted.map(event=>event.id).sort(),['left-repeater','right-repeater']);
  assert.ok(rerouted.every(event=>event.actualStart===4&&event.actualEnd===4.22&&event.semanticEventId==='m000042'));
  assert.ok(result.events.some(event=>event.id==='left-outer'&&event.kind==='musical impact'&&event.actualStart===4),
    'the original winning preferred cue stays in place');
  for(const channel of [21,22])assert.equal(show.frames[200*200+channel-1],255);
  const second=compose({collisionAllocation:allocation});
  assert.deepEqual(Array.from(second.show.frames),Array.from(show.frames));
  assert.deepEqual(second.result.diagnostics.semanticTargetAllocation,d.semanticTargetAllocation);
});

test('passes a checked allocation contract through ShowEngine into actual FSEQ frames',()=>{
  const show=engine.generate(music(),{dance:'off',collisionAllocation:{enabled:true,targets:[target()]}});
  assert.equal(show.choreography.lighting.semanticTargetAllocation.allocated,1);
  assert.deepEqual(show.lightEvents.filter(event=>event.semanticFallbackAllocation).map(event=>event.id).sort(),['left-repeater','right-repeater']);
  assert.equal(show.frames[200*200+20],255);
  assert.equal(show.frames[200*200+21],255);
});

test('requires every preferred route to be unavailable before adding a fallback, avoiding duplicate accents',()=>{
  const {result}=compose({collisionAllocation:{enabled:true,targets:[target({semanticEventId:'m000043',time:6.25,end:6.45})]}});
  assert.equal(result.events.some(event=>event.semanticFallbackAllocation),false);
  assert.deepEqual(result.diagnostics.semanticTargetAllocation.rows.map(row=>row.outcome),['skipped']);
  assert.deepEqual(result.diagnostics.semanticTargetAllocation.rows.map(row=>row.reason),['preferred-output-still-available']);
});

test('keeps configured fallback groups atomic and suppresses safely when a member cannot run',()=>{
  const {result}=compose({outputEnabled:{'right-repeater':false},collisionAllocation:{enabled:true,targets:[target()]}});
  assert.equal(result.events.some(event=>event.semanticFallbackAllocation),false);
  assert.deepEqual(result.diagnostics.semanticTargetAllocation.rows,[{
    targetId:'semantic-m000042-0',semanticEventId:'m000042',time:4,end:4.22,tier:'climax',salience:.95,
    preferredOutputIds:['left-outer'],chosenOutput:null,chosenOutputs:[],
    outcome:'suppressed',reason:'configured-fallback-unavailable'
  }]);
});

test('does not infer a fallback when an opt-in semantic target omits configured fallback outputs',()=>{
  const {result}=compose({collisionAllocation:{enabled:true,targets:[target({fallbackOutputGroups:undefined})]}});
  assert.equal(result.events.some(event=>event.semanticFallbackAllocation),false);
  assert.deepEqual(result.diagnostics.semanticTargetAllocation.rows.map(row=>row.reason),['no-configured-fallback']);
});

test('fails closed for malformed direct planner routes instead of treating an unknown output as lost',()=>{
  const {result}=compose({collisionAllocation:{enabled:true,targets:[target({candidateOutputIds:['not-a-vehicle-output']})]}});
  assert.equal(result.events.some(event=>event.semanticFallbackAllocation),false);
  assert.deepEqual(result.diagnostics.semanticTargetAllocation.rows.map(row=>row.reason),['invalid-preferred-output']);
});

test('normalizes only explicit safe allocation contracts and preserves absent settings',()=>{
  assert.equal(engine.normalizeSettings({}).collisionAllocation,undefined);
  const normalized=engine.normalizeSettings({collisionAllocation:{
    enabled:true,minimumSalience:.9,maxAllocations:2,tiers:['climax'],
    fallbacks:{climax:[['left-repeater','right-repeater']]},
    targets:[{semanticEventId:'m000042',time:4,end:4.22,tier:'climax',salience:.95,candidateOutputIds:['left-outer']}]
  }}).collisionAllocation;
  assert.deepEqual(normalized,{
    version:1,enabled:true,minimumSalience:.9,maxAllocations:2,tiers:['climax'],
    fallbacks:{climax:[['left-repeater','right-repeater']]},
    targets:[{semanticEventId:'m000042',time:4,end:4.22,tier:'climax',salience:.95,role:null,candidateOutputIds:['left-outer']}]
  });
  assert.throws(()=>engine.normalizeSettings({collisionAllocation:{enabled:true,targets:[{
    semanticEventId:'m000042',time:4,end:4.22,tier:'climax',salience:.95,candidateOutputIds:['left-outer']
  }]}}),/needs configured fallback outputs/);
  assert.throws(()=>engine.normalizeSettings({collisionAllocation:{enabled:true,fallbacks:{
    climax:[['left-outer','left-outer']]
  },targets:[{semanticEventId:'m000042',time:4,end:4.22,tier:'climax',salience:.95,candidateOutputIds:['left-outer']}]
  }}),/cannot repeat an output/);
});
