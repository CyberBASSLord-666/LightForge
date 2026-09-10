'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const Timeline=require('../web/analysis/semantic-timeline.js');
const Salience=require('../web/analysis/salience.js');
const Recurrence=require('../web/analysis/recurrence.js');

function section(start,end,energy,group=''){return {start,end,energy,confidence:.92,label:'intentionally-not-exported',recurrenceGroup:group||undefined,similarity:group&&start>0?.992:0,repetitionIndex:group?(start===0?0:1):undefined};}
function baseMusic(){
 return {duration:12,beats:[0,.5,1,1.5,2,2.5,3,3.5,4,4.5,5,5.5,6,6.5,7,7.5,8,8.5,9,9.5,10,10.5,11,11.5],downbeats:[0,2,4,6,8,10],beatDetails:[{time:0,barPosition:1,confidence:.9},{time:2,barPosition:1,confidence:.9},{time:4,barPosition:1,confidence:.9},{time:6,barPosition:1,confidence:.9},{time:8,barPosition:1,confidence:.9}],sections:[section(0,4,.42,'repeat-a'),section(4,8,.28,'single-b'),section(8,12,.64,'repeat-a')],phrases:[],vocals:{phrases:[],notes:[],accents:[]},bassNotes:[],bassAnalysis:{phrases:[]}};
}
function chromaMusic(){
 const music=baseMusic();
 music.sections=music.sections.map((item,index)=>({...item,recurrenceGroup:'section-'+index,similarity:0,repetitionIndex:0}));
 const energy=[],chroma=[];
 for(let frame=0;frame<60;frame++){
  const block=Math.floor(frame/20),value=block===1?.34:.58;
  energy.push(value);
  const pitch=block===1?5:0;
  for(let bin=0;bin<12;bin++)chroma.push(bin===pitch?1:.015);
 }
 music.energy=energy;music.energyStep=.2;music.chroma=chroma;music.chromaStep=.2;
 return music;
}
function build(music){
 const timeline=Timeline.build(music),evidence=Recurrence.captureEvidence(music,timeline),sidecar=Recurrence.build(timeline,evidence);
 return {timeline,evidence,sidecar};
}

test('prevalidated section recurrence becomes a deterministic opt-in motif sidecar without labels or commands',()=>{
 const music=baseMusic(),before=structuredClone(music),first=build(music),second=build(structuredClone(music));
 assert.deepEqual(first.sidecar,second.sidecar);
 assert.deepEqual(music,before);
 assert.equal(Recurrence.validateEvidence(first.evidence,first.timeline).valid,true);
 assert.equal(Recurrence.validate(first.sidecar,first.timeline,first.evidence).valid,true);
 assert.equal(first.sidecar.motifs.length,1);
 const motif=first.sidecar.motifs[0];
 assert.equal(motif.evidence,'prevalidated-section-recurrence');
 assert.deepEqual(motif.instances.map(instance=>instance.evolution.phase),['establish','escalate']);
 assert.equal(motif.instances[1].evolution.requiresChoreographyOptIn,true);
 assert.equal(JSON.stringify(first.sidecar).includes('intentionally-not-exported'),false);
 assert.equal(JSON.stringify(first.sidecar).includes('command'),false);
 assert.equal(Recurrence.timelineFingerprint(first.timeline),Salience.build(first.timeline).timelineFingerprint);
});

test('strict chroma-and-energy evidence can establish a fresh generic motif identity',()=>{
 const {timeline,evidence,sidecar}=build(chromaMusic());
 assert.equal(Recurrence.validate(sidecar,timeline,evidence).valid,true);
 assert.equal(sidecar.motifs.length,1);
 assert.equal(sidecar.motifs[0].evidence,'section-chroma-energy');
 assert.deepEqual(sidecar.motifs[0].instances.map(instance=>instance.sectionIndex),[0,2]);
 assert.equal(sidecar.summary.evidence.hasChroma,true);
 assert.equal(sidecar.motifs[0].instances[1].similarity,1);
});

test('weak or unsupported group metadata cannot create a motif by itself',()=>{
 const music=baseMusic();
 music.sections[2].similarity=.90;
 const {sidecar}=build(music);
 assert.equal(sidecar.motifs.length,0);
 assert.equal(sidecar.assignments.length,0);
});

test('sidecars fail closed when their timeline or evidence binding changes',()=>{
 const {timeline,evidence,sidecar}=build(chromaMusic());
 const changedTimeline=structuredClone(timeline);changedTimeline.events.find(event=>event.type==='section').intensity=.01;
 assert.equal(Recurrence.validate(sidecar,changedTimeline,evidence).valid,false);
 const changedEvidence=structuredClone(evidence);changedEvidence.sections[0].energy=.01;
 assert.equal(Recurrence.validate(sidecar,timeline,changedEvidence).valid,false);
 const changedAssignment=structuredClone(sidecar);changedAssignment.assignments[0].evolution.phase='release';
 assert.equal(Recurrence.validate(changedAssignment,timeline,evidence).valid,false);
});

test('capture rejects incomplete frame evidence instead of silently truncating it',()=>{
 const music=baseMusic();
 music.energy=[.5,.5];music.energyStep=.2;
 const timeline=Timeline.build(music);
 assert.throws(()=>Recurrence.captureEvidence(music,timeline),/does not cover/);
});
