'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const Engine=require('../web/engine/show-engine.js');
const Planner=require('../web/engine/light-planner.js');
const Timeline=require('../web/analysis/semantic-timeline.js');
const Salience=require('../web/analysis/salience.js');

function music(){
  const duration=8,beats=Array.from({length:16},(_,index)=>index*.5);
  return {
    duration,bpm:120,beatConfidence:.96,meter:4,beats,downbeats:beats.filter((_,index)=>index%4===0),
    sections:[{start:0,end:4,energy:.96,label:'Verse'},{start:4,end:duration,energy:.96,label:'Drop'}],
    phrases:[{start:4,end:6,energy:.96,kind:'drop',confidence:.95}],activityRanges:[{start:0,end:duration}],
    waveform:Array(80).fill(.72),onsets:[{time:4,strength:1,band:'bass'}],impacts:[{time:4,strength:.78,kind:'drop'}],
    vocals:{available:true,presence:'detected',sourceSeparated:true,confidence:.96,
      phrases:[{start:4,end:4.5,confidence:.96,strength:.95,kind:'singing'}],
      accents:[{time:4,confidence:.96,strength:1,kind:'syllabic-accent'}],notes:[]},
    bassNotes:[{start:4,end:4.4,confidence:.95,strength:.95,midi:40}],
    bassAnalysis:{confidence:.95,phrases:[{start:4,end:4.4,confidence:.95,strength:.95}]},
    energy:[],energyStep:0,groove:{},silent:false
  };
}
function target(id){
  return {semanticEventId:id,time:4,end:4.22,tier:'climax',salience:.95,role:'structure',
    candidateOutputIds:['left-outer'],fallbackOutputGroups:[['left-repeater','right-repeater']]};
}
function direct(settings){
  const show={frameCount:401,frames:new Uint8Array(401*200),
    sections:[{start:0,end:8,energy:.9,index:0,style:'festival',intensity:.9,variant:0,seed:1}]};
  return Planner.compose(show,music(),{stepMs:20,offsetMs:0,outputEnabled:{},outerBeamRamping:false,
    vocalFocus:.85,bassFocus:.9,sensitivity:.5,beatDivision:'quarter',style:'festival',seed:1,...settings},{accents:[]});
}

test('semantic choreography and collision allocation are jointly opt-in, feasible, and deterministic',()=>{
  const input=music(),timeline=Timeline.build(input),salience=Salience.build(timeline);
  const settings={stepMs:20,dance:'expressive',seed:88,semanticChoreography:true,
    collisionAllocation:{enabled:true,targets:[target('integration-impact')]}};
  const first=Engine.generate({...input,semanticTimeline:timeline,musicSalience:salience},settings);
  const second=Engine.generate({...input,semanticTimeline:timeline,musicSalience:salience},settings);
  assert.equal(first.choreography.semanticStrategy.active,true);
  assert.ok(first.choreography.semanticStrategy.linkedTargetCount>0);
  assert.equal(first.choreography.lighting.semanticTargetAllocation.allocated,1);
  assert.deepEqual(first.lightEvents.filter(event=>event.semanticFallbackAllocation).map(event=>event.id).sort(),
    ['left-repeater','right-repeater']);
  assert.deepEqual(first.frames,second.frames);
  assert.deepEqual(Engine.fseq(first,'semantic-allocation.wav'),Engine.fseq(second,'semantic-allocation.wav'));
  assert.equal(Engine.validate(first,input).valid,true);
});

test('equal-time allocation ties use code-point semantic identifiers, not locale collation',()=>{
  const result=direct({collisionAllocation:{enabled:true,targets:[target('a'),target('A')]}});
  const rows=result.diagnostics.semanticTargetAllocation.rows;
  assert.deepEqual(rows.map(row=>row.semanticEventId),['A','a']);
  assert.deepEqual(rows.map(row=>row.outcome),['allocated','suppressed']);
  assert.deepEqual(rows.map(row=>row.targetId),['semantic-A-1','semantic-a-0']);
});
