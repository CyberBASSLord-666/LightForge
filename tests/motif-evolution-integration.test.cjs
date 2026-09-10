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
    // This real planner target establishes a semantic link. Motif evolution
    // must not activate merely because a valid timeline exists.
    bassNotes:[{start:2,end:2.8,confidence:.96,strength:.94,midi:40}],
    bassAnalysis:{confidence:.96,phrases:[{start:2,end:2.8,confidence:.96,strength:.94}]},
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
function recurrenceAnalysisMarker(sidecar){
  return {schemaVersion:1,enabled:true,cacheDomain:'recurrence',engineVersion:sidecar.engineVersion,sidecarSchemaVersion:sidecar.schemaVersion,
    clock:sidecar.clock,duration:sidecar.duration,timelineFingerprint:sidecar.timelineFingerprint,evidenceFingerprint:sidecar.evidenceFingerprint};
}
function withThrowingSemanticStrategy(run){
  const moduleId=require.resolve('../web/engine/show-engine.js'),cached=require.cache[moduleId],prior=globalThis.SemanticChoreography;
  globalThis.SemanticChoreography={create(){throw Error('simulated semantic strategy module fault');}};
  delete require.cache[moduleId];
  try{return run(require('../web/engine/show-engine.js'));}
  finally{
    delete require.cache[moduleId];
    if(cached)require.cache[moduleId]=cached;
    if(prior===undefined)delete globalThis.SemanticChoreography;else globalThis.SemanticChoreography=prior;
  }
}

test('motif evolution requires a valid cap-aware recurrence binding and keeps default FSEQ bytes identical',()=>{
  const music=musicFixture(),{timeline,salience,evidence,sidecar}=buildBoundRecurrence(music);
  const analysis={...music,semanticTimeline:timeline,musicSalience:salience,recurrenceEvidence:evidence,recurrenceSidecar:sidecar,recurrenceAnalysis:recurrenceAnalysisMarker(sidecar)};
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
  assert.equal(semanticOnly.choreography.semanticStrategy.active,true,
    'the valid fixture must establish a real linkable semantic planning strategy');
  const {recurrenceAnalysis,...withoutMarker}=analysis;
  const missingProvenance=Engine.generate(withoutMarker,{...settings,semanticChoreography:true,motifEvolution:true});
  assert.equal(missingProvenance.choreography.motifEvolution.active,false);
  assert.equal(missingProvenance.choreography.motifEvolution.reason,'recurrence-analysis-disabled');
  assert.deepEqual(Engine.fseq(missingProvenance,'motif.wav'),Engine.fseq(semanticOnly,'motif.wav'),
    'a sidecar without explicit recurrence-analysis provenance must retain the semantic-only output');
  const disabledProvenance=Engine.generate({...analysis,recurrenceAnalysis:{...analysis.recurrenceAnalysis,enabled:false}},
    {...settings,semanticChoreography:true,motifEvolution:true});
  assert.equal(disabledProvenance.choreography.motifEvolution.active,false);
  assert.equal(disabledProvenance.choreography.motifEvolution.reason,'recurrence-analysis-disabled');
  assert.deepEqual(Engine.fseq(disabledProvenance,'motif.wav'),Engine.fseq(semanticOnly,'motif.wav'),
    'an explicitly disabled recurrence marker must retain the semantic-only output');
  const invalidProvenance=Engine.generate({...analysis,recurrenceAnalysis:{...analysis.recurrenceAnalysis,evidenceFingerprint:'00000000'}},
    {...settings,semanticChoreography:true,motifEvolution:true});
  assert.equal(invalidProvenance.choreography.motifEvolution.active,false);
  assert.equal(invalidProvenance.choreography.motifEvolution.reason,'recurrence-analysis-provenance-invalid');
  assert.deepEqual(Engine.fseq(invalidProvenance,'motif.wav'),Engine.fseq(semanticOnly,'motif.wav'));
  const stale=Engine.generate({...analysis,recurrenceSidecar:{...sidecar,timelineFingerprint:'00000000'},recurrenceAnalysis:{...analysis.recurrenceAnalysis,timelineFingerprint:'00000000'}},
    {...settings,semanticChoreography:true,motifEvolution:true});
  assert.equal(stale.choreography.motifEvolution.active,false);
  assert.equal(stale.choreography.motifEvolution.reason,'recurrence-sidecar-binding-invalid');
  assert.deepEqual(Engine.fseq(stale,'motif.wav'),Engine.fseq(semanticOnly,'motif.wav'),
    'a stale sidecar must fall back exactly to the non-motif semantic strategy');

  const first=Engine.generate(analysis,{...settings,semanticChoreography:true,motifEvolution:true});
  const second=Engine.generate(analysis,{...settings,semanticChoreography:true,motifEvolution:true});
  assert.equal(first.choreography.motifEvolution.active,true);
  assert.equal(first.choreography.semanticStrategy.active,true,
    'the final motif scene must retain the active semantic strategy established by the preflight');
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

test('motif evolution requires canonical, active semantic salience before it can alter a scene',()=>{
  const music=musicFixture(),{timeline,salience,evidence,sidecar}=buildBoundRecurrence(music);
  const analysis={...music,semanticTimeline:timeline,musicSalience:salience,recurrenceEvidence:evidence,recurrenceSidecar:sidecar,recurrenceAnalysis:recurrenceAnalysisMarker(sidecar)};
  const settings={stepMs:20,dance:'off',seed:778,semanticChoreography:true,motifEvolution:true};
  const assertSemanticFallback=(name,value)=>{
    const expected=Engine.generate(value,{...settings,motifEvolution:false});
    const actual=Engine.generate(value,settings);
    assert.equal(actual.choreography.motifEvolution.active,false,name+' must keep motif evolution inactive');
    assert.equal(actual.choreography.motifEvolution.reason,'semantic-strategy-inactive',name+' must fail before any scene mutation');
    assert.equal(actual.choreography.semanticStrategy.active,false,name+' must not activate semantic scheduling');
    assert.deepEqual(actual.frames,expected.frames,name+' must retain the exact non-motif frame plan');
    assert.deepEqual(Engine.fseq(actual,'motif-guard.wav'),Engine.fseq(expected,'motif-guard.wav'),name+' must retain exact non-motif FSEQ bytes');
  };

  const missing={...analysis};delete missing.musicSalience;
  assertSemanticFallback('missing salience',missing);

  const malformed={...analysis,musicSalience:{...salience,events:'not-an-array'}};
  assertSemanticFallback('malformed salience',malformed);

  const stale={...analysis,musicSalience:{...salience,timelineFingerprint:'00000000'}};
  assertSemanticFallback('stale salience',stale);

  const invalidCap=structuredClone(analysis),capped=invalidCap.semanticTimeline.events.find(event=>event.salienceCap!==undefined);
  assert.ok(capped);capped.salienceCap=capped.salience-.01;
  assert.equal(Timeline.validate(invalidCap.semanticTimeline).valid,false,'the cap mutation must be rejected by the canonical timeline validator');
  assertSemanticFallback('cap-invalid timeline',invalidCap);

  const wrongClock=structuredClone(analysis);wrongClock.semanticTimeline.clock='resampled-clock';
  assert.equal(Timeline.validate(wrongClock.semanticTimeline).valid,false);
  assertSemanticFallback('wrong-clock timeline',wrongClock);

  const wrongSchema=structuredClone(analysis);wrongSchema.semanticTimeline.schemaVersion=3;
  assert.equal(Timeline.validate(wrongSchema.semanticTimeline).valid,false);
  assertSemanticFallback('wrong-schema timeline',wrongSchema);

  for(const events of ['not-an-array',[null],{}]){
    const malformedTimeline=structuredClone(analysis);malformedTimeline.semanticTimeline.events=events;
    assert.doesNotThrow(()=>Timeline.validate(malformedTimeline.semanticTimeline));
    assert.equal(Timeline.validate(malformedTimeline.semanticTimeline).valid,false);
    assertSemanticFallback('malformed timeline events '+JSON.stringify(events),malformedTimeline);
  }
});

test('a semantic strategy module fault fails closed to the exact legacy sequence',()=>{
  const music=musicFixture(),{timeline,salience,evidence,sidecar}=buildBoundRecurrence(music);
  const analysis={...music,semanticTimeline:timeline,musicSalience:salience,recurrenceEvidence:evidence,recurrenceSidecar:sidecar,recurrenceAnalysis:recurrenceAnalysisMarker(sidecar)};
  const settings={stepMs:20,dance:'off',seed:779,semanticChoreography:true,motifEvolution:true};
  const baseline=Engine.generate(analysis,{stepMs:20,dance:'off',seed:779});
  const faulted=withThrowingSemanticStrategy(FaultedEngine=>FaultedEngine.generate(analysis,settings));
  assert.equal(faulted.choreography.semanticStrategy.active,false);
  assert.equal(faulted.choreography.motifEvolution.active,false);
  assert.equal(faulted.choreography.motifEvolution.reason,'semantic-strategy-inactive');
  assert.deepEqual(faulted.frames,baseline.frames);
  assert.deepEqual(Engine.fseq(faulted,'semantic-fault.wav'),Engine.fseq(baseline,'semantic-fault.wav'));
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
