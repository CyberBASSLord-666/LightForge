'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const planner=require('../web/engine/light-planner.js');

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
function settings(outputEnabled={}){
  return {stepMs:20,offsetMs:0,outputEnabled,outerBeamRamping:false,vocalFocus:.85,bassFocus:.9,
    sensitivity:.5,beatDivision:'quarter',style:'festival',seed:1};
}
function compose(accents,outputEnabled={}){
  const show={frameCount:401,frames:new Uint8Array(401*200),
    sections:[{start:0,end:8,energy:.9,index:0,style:'festival',intensity:.9,variant:0,seed:1}]};
  return {show,result:planner.compose(show,music(),settings(outputEnabled),{accents})};
}

test('rescues a fully collided high-salience movement arrival without replacing its winning command',()=>{
  const first=compose([{channels:[37],time:4,strength:.95}]);
  const {show,result}=first,d=result.diagnostics;
  assert.equal(d.rescuedCollisions,1);
  assert.equal(d.unresolvedHighSalienceCollisions,0);
  assert.equal(d.collisionResolutionTruncated,0);
  assert.deepEqual(d.collisionResolutions,[{
    groupId:'arrangement-movement-arrival-movement-4000-37-0-0',
    eventType:'movement arrival',preferredOutput:'left-outer',chosenOutput:'left-repeater',
    chosenOutputs:['left-repeater','right-repeater'],time:4,salience:.9725,tier:'climax',
    outcome:'rescued',reason:'safe-symmetric-secondary-group'
  }]);
  const rescue=result.events.filter(event=>event.collisionRescue);
  assert.deepEqual(rescue.map(event=>event.id).sort(),['left-repeater','right-repeater']);
  assert.ok(rescue.every(event=>event.actualStart===4&&event.actualEnd===4.22));
  assert.ok(result.events.some(event=>event.id==='left-outer'&&event.kind==='musical impact'&&event.actualStart===4),
    'the original higher-salience impact remains in place');
  for(const channel of [21,22])assert.equal(show.frames[200*200+channel-1],255);
  const second=compose([{channels:[37],time:4,strength:.95}]);
  assert.deepEqual(Array.from(second.show.frames),Array.from(show.frames));
  assert.deepEqual(second.result.diagnostics.collisionResolutions,d.collisionResolutions);
});

test('does not force a fallback when the preferred high-salience route survives',()=>{
  const {result}=compose([{channels:[35],time:4,strength:.95}]);
  assert.equal(result.diagnostics.rescuedCollisions,0);
  assert.equal(result.diagnostics.unresolvedHighSalienceCollisions,0);
  assert.deepEqual(result.diagnostics.collisionResolutions,[]);
  assert.ok(result.events.some(event=>event.kind==='movement arrival'&&!event.collisionRescue));
});

test('reports a fully lost high-salience event when no safe secondary pair is enabled',()=>{
  const disabled={'left-repeater':false,'right-repeater':false,'left-rear-turn':false,'right-rear-turn':false};
  const {result}=compose([{channels:[37],time:4,strength:.95}],disabled);
  const d=result.diagnostics;
  assert.equal(d.rescuedCollisions,0);
  assert.equal(d.unresolvedHighSalienceCollisions,1);
  assert.deepEqual(d.collisionResolutions,[{
    groupId:'arrangement-movement-arrival-movement-4000-37-0-0',
    eventType:'movement arrival',preferredOutput:'left-outer',chosenOutput:null,chosenOutputs:[],
    time:4,salience:.9725,tier:'climax',outcome:'suppressed',
    reason:'all-preferred-outputs-collided:secondary-output-unavailable'
  }]);
  assert.equal(result.events.some(event=>event.collisionRescue),false);
});
