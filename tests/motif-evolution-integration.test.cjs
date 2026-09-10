'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const Engine=require('../web/engine/show-engine.js');
const Timeline=require('../web/analysis/semantic-timeline.js');
const Salience=require('../web/analysis/salience.js');
const Recurrence=require('../web/analysis/recurrence.js');

function section(start,end,energy,group=''){
  return {start,end,energy,confidence:.92,label:'generic-structure',recurrenceGroup:group||undefined,
    similarity:group&&start>0?.992:0,repetitionIndex:group?(start===0?0:1):undefined};
}
function musicFixture(){
  const duration=24,beats=Array.from({length:48},(_,index)=>index*.5);
  return {
    duration,bpm:120,beatConfidence:.94,beats,downbeats:beats.filter((_,index)=>index%4===0),
    beatDetails:beats.map((time,index)=>({time,confidence:.94,barPosition:index%4+1,localBpm:120})),
    sections:[section(0,8,.42,'repeat-a'),section(8,16,.28),section(16,24,.64,'repeat-a')],
    phrases:[],waveform:Array(240).fill(.65),onsets:[{time:2,strength:.8,band:'bass'}],
    impacts:[{time:16,strength:.9,kind:'transition'}],
    vocals:{available:false,presence:'not_detected',phrases:[],notes:[],accents:[]},
    bassNotes:[],bassAnalysis:{phrases:[]},
    percussionAnalysis:{
      source:'mix-feature-estimate',method:'bounded test evidence',inputStem:'mixture',
      inputStemSeparated:false,sourceSeparated:false,estimated:true,salienceCap:.41,
      events:[{time:2.04,kind:'kick',confidence:.52,strength:.55,estimated:true,salienceCap:.41}]
    }
  };
}
function buildBoundRecurrence(music){
  const timeline=Timeline.build(music),salience=Salience.build(timeline);
  const capped=timeline.events.find(event=>event.salienceCap===.41);
  assert.ok(capped,'capped percussion evidence must survive into the semantic timeline');
  assert.equal(Recurrence.timelineFingerprint(timeline),salience.timelineFingerprint,
    'recurrence and salience must bind the same cap-aware semantic timeline');
  const evidence=Recurrence.captureEvidence(music,timeline),sidecar=Recurrence.build(timeline,evidence);
  assert.equal(Recurrence.validate(sidecar,timeline,evidence).valid,true);
  return {timeline,salience,evidence,sidecar};
}

test('motif evolution requires a valid cap-aware recurrence binding and keeps default FSEQ bytes identical',()=>{
  const music=musicFixture(),{timeline,salience,evidence,sidecar}=buildBoundRecurrence(music);
  const analysis={...music,semanticTimeline:timeline,musicSalience:salience,recurrenceEvidence:evidence,recurrenceSidecar:sidecar};
  const originalAnalysis=structuredClone(analysis);
  const settings={stepMs:20,dance:'off',seed:777};

  const baseline=Engine.generate(music,settings);
  const suppliedButDefault=Engine.generate(analysis,settings);
  assert.deepEqual(suppliedButDefault.frames,baseline.frames,'sidecar data alone must preserve legacy frame bytes');
  assert.deepEqual(Engine.fseq(suppliedButDefault,'motif.wav'),Engine.fseq(baseline,'motif.wav'),
    'sidecar data alone must preserve legacy FSEQ bytes');
  const requestedWithoutSemantic=Engine.generate(analysis,{...settings,motifEvolution:true});
  assert.equal(requestedWithoutSemantic.choreography.motifEvolution.reason,'semantic-choreography-disabled');
  assert.deepEqual(Engine.fseq(requestedWithoutSemantic,'motif.wav'),Engine.fseq(baseline,'motif.wav'),
    'motif evolution cannot affect FSEQ output without the semantic opt-in');

  const semanticOnly=Engine.generate(analysis,{...settings,semanticChoreography:true});
  const stale=Engine.generate({...analysis,recurrenceSidecar:{...sidecar,timelineFingerprint:'00000000'}},
    {...settings,semanticChoreography:true,motifEvolution:true});
  assert.equal(stale.choreography.motifEvolution.active,false);
  assert.equal(stale.choreography.motifEvolution.reason,'recurrence-sidecar-binding-invalid');
  assert.deepEqual(Engine.fseq(stale,'motif.wav'),Engine.fseq(semanticOnly,'motif.wav'),
    'a stale sidecar must fall back exactly to the non-motif semantic strategy');

  const first=Engine.generate(analysis,{...settings,semanticChoreography:true,motifEvolution:true});
  const second=Engine.generate(analysis,{...settings,semanticChoreography:true,motifEvolution:true});
  assert.equal(first.choreography.motifEvolution.active,true);
  assert.deepEqual(first.frames,second.frames,'opt-in motif variation must be deterministic');
  assert.deepEqual(Engine.fseq(first,'motif.wav'),Engine.fseq(second,'motif.wav'));
  assert.notDeepEqual(first.frames,semanticOnly.frames,
    'a validated motif assignment must create controlled visual variation beyond the semantic-only plan');
  assert.equal(first.validation.valid,true);
  assert.equal(Engine.validate(first,music).valid,true);
  assert.equal(first.sections[0].motifGroup,first.sections[2].motifGroup);
  assert.equal(first.sections[0].motifEvolution.phase,'establish');
  assert.equal(first.sections[2].motifEvolution.phase,'escalate');
  assert.notEqual(first.sections[0].seed,first.sections[2].seed,
    'repeat instances retain a shared motif identity but not copied scene seeds');
  assert.deepEqual(analysis,originalAnalysis,'motif planning must not mutate supplied analysis or recurrence evidence');

  const protectedSettings={...settings,semanticChoreography:true,motifEvolution:true,sectionOverrides:{2:{seed:12345}}};
  const protectedShow=Engine.generate(analysis,protectedSettings);
  const protectedLegacy=Engine.generate(analysis,{...protectedSettings,motifEvolution:false});
  assert.equal(protectedShow.choreography.motifEvolution.lockedSectionCount,1);
  assert.equal(protectedShow.sections[2].seed,protectedLegacy.sections[2].seed,
    'an explicit section seed remains authoritative over motif evolution');
});

test('cap-aware recurrence fingerprints invalidate stale evidence and sidecars',()=>{
  const music=musicFixture(),{timeline,evidence,sidecar}=buildBoundRecurrence(music);
  const changedTimeline=structuredClone(timeline);
  const capped=changedTimeline.events.find(event=>event.salienceCap===.41);
  assert.ok(capped);
  capped.salienceCap=.42;
  const changedRecurrenceFingerprint=Recurrence.timelineFingerprint(changedTimeline);
  const changedSalience=Salience.build(changedTimeline);
  assert.equal(changedRecurrenceFingerprint,changedSalience.timelineFingerprint);
  assert.notEqual(changedRecurrenceFingerprint,Recurrence.timelineFingerprint(timeline));
  assert.equal(Recurrence.validate(sidecar,changedTimeline,evidence).valid,false,
    'a cap-only semantic mutation must invalidate the old recurrence sidecar');
  const changedEvidence=Recurrence.captureEvidence(music,changedTimeline);
  const changedSidecar=Recurrence.build(changedTimeline,changedEvidence);
  assert.equal(Recurrence.validate(changedSidecar,changedTimeline,changedEvidence).valid,true);
  assert.equal(Recurrence.validate(sidecar,timeline,changedEvidence).valid,false,
    'a cap-only mutation must invalidate old recurrence evidence as well');
});

test('browser and composition worker load recurrence validation before the motif bridge and show engine',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../web/index.html'),'utf8');
  const recurrence=html.indexOf('analysis/recurrence.js'),motif=html.indexOf('engine/motif-evolution.js'),engine=html.indexOf('engine/show-engine.js');
  assert.ok(recurrence>=0&&motif>recurrence&&engine>motif);
  const worker=fs.readFileSync(path.join(__dirname,'../web/engine/worker.js'),'utf8');
  const workerRecurrence=worker.indexOf("'../analysis/recurrence.js'"),workerMotif=worker.indexOf("'motif-evolution.js'"),workerEngine=worker.indexOf("'show-engine.js'");
  assert.ok(workerRecurrence>=0&&workerMotif>workerRecurrence&&workerEngine>workerMotif);
});
