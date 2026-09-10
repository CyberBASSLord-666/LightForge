'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const VocalChoreography=require('../web/engine/vocal-choreography.js');
const Engine=require('../web/engine/show-engine.js');
let ActualTimeline=null,ActualVocalSemantics=null;
try{ActualTimeline=require('../web/analysis/semantic-timeline.js');ActualVocalSemantics=require('../web/analysis/vocal-semantics.js');}catch(_){}

function sidecar(){return {
  schemaVersion:1,engineVersion:'1.0.1',clock:'original-decoded-audio',duration:12,source:'separated-vocals',sourceSeparated:true,linguisticAlignment:false,sourceFingerprint:'vs1-1234567890abcdef',
  phrases:[{id:'vp0000',start:1,end:3,duration:2,onset:1,release:2.6,kind:'singing',confidence:.94,intensity:.90,source:'separated-vocals',linguistic:false,pitchTrajectory:{source:'existing-note-output',observations:2,startMidi:60,endMidi:67,medianMidi:63.5,movement:'rising',confidence:.91}}],
  articulations:[{id:'va0000',phraseId:'vp0000',time:1.2,role:'acoustic-articulation',syllableLike:true,stress:'primary',stressConfidence:.92,confidence:.95,intensity:.97,source:'separated-vocals',linguistic:false}],
  notes:[{id:'vn0000',phraseId:'vp0000',start:1.5,end:2.5,midi:64,confidence:.92,intensity:.88,kind:'held-note',source:'separated-vocals',linguistic:false}],
  regions:[],summary:{linguisticContent:false}
};}
function timeline(changed=false){return {schemaVersion:2,clock:'original-decoded-audio',duration:12,events:[
  {id:'event-phrase',type:'vocal_phrase',source:'vocals',time:1,duration:2,kind:'singing',confidence:.94,intensity:.90,salience:.70},
  {id:'event-articulation',type:'vocal_accent',source:'vocals',time:changed?1.21:1.2,duration:0,kind:'syllabic-accent',confidence:.95,intensity:.97,salience:.82},
  {id:'event-note',type:'vocal_note',source:'vocals',time:1.5,duration:1,kind:'held-note',confidence:.92,intensity:.88,salience:.68}
]};}
function linked(t){return {schemaVersion:1,clock:'original-decoded-audio',duration:12,sidecarFingerprint:'vs1-1234567890abcdef',timelineFingerprint:'vt1-'+t.events.map(event=>event.id+':'+event.time).join('|'),phrases:[{semanticId:'vp0000',eventId:'event-phrase'}],articulations:[{semanticId:'va0000',eventId:'event-articulation'}],notes:[{semanticId:'vn0000',eventId:'event-note'}]};}
function semanticsApi(){return {
  validate(value,input){return {valid:!!value&&input?.duration===12&&input?.vocals?.sourceSeparated===true&&input?.vocals?.source==='separated-vocals'};},
  linkTimeline(value,current){if(!value||!current||current.clock!=='original-decoded-audio')throw Error('bad link');return linked(current);}
};}
function music(includeSidecar=true){
  const beats=Array.from({length:24},(_,index)=>index*.5),value={
    duration:12,bpm:120,beatConfidence:.96,beats,downbeats:beats.filter((_,index)=>index%4===0),waveform:Array(600).fill(.70),energy:Array(600).fill(.65),energyStep:.02,
    sections:[{start:0,end:6,energy:.55,label:'Verse'},{start:6,end:12,energy:.84,label:'Chorus'}],onsets:[{time:1.2,strength:.8,band:'mid'}],impacts:[],phrases:[],activityRanges:[{start:0,end:12}],
    vocals:{available:true,presence:'detected',source:'separated-vocals',sourceSeparated:true,confidence:.94,phrases:[{start:1,end:3,releaseTime:2.6,confidence:.94,strength:.90,kind:'singing'}],notes:[{start:1.5,end:2.5,midi:64,confidence:.92,strength:.88}],accents:[{time:1.2,kind:'syllabic-accent',confidence:.95,strength:.97,source:'separated-vocals'}],pitchContour:{step:.04,midi:[],confidence:[]},envelope:[],envelopeStep:.02},
    bassNotes:[],bassAnalysis:{confidence:0,phrases:[],envelope:[],envelopeStep:.02}
  };
  if(includeSidecar){const semantic=timeline();value.semanticTimeline=semantic;value.vocalSemantics=sidecar();value.vocalSemanticLinks=linked(semantic);}
  return value;
}

test('bridge consumes only a freshly recomputed non-linguistic acoustic link and applies bounded hints',()=>{
  const input=music(),before=structuredClone(input),strategy=VocalChoreography.create({music:input,normalizedMusic:{...input,musicCues:[]},settings:{vocalOffsetMs:0}},{enabled:true,api:semanticsApi()});
  assert.equal(strategy.active,true);
  const direction=strategy.directionFor({sourceStart:1,sourceEventTime:1.2,kind:'articulation'});
  assert.deepEqual(direction,{direction:'right',side:true,phraseId:'vp0000',eventId:'event-phrase',movement:'rising',confidence:.91});
  const original={role:'vocals',sourceStart:1,sourceEnd:3,sourceEventTime:1.2,articulation:true,musicTime:1.2,start:1.2,end:3,priority:70,strength:.42,release:0};
  const articulated=strategy.classifyCandidate(original);
  assert.deepEqual(original,{role:'vocals',sourceStart:1,sourceEnd:3,sourceEventTime:1.2,articulation:true,musicTime:1.2,start:1.2,end:3,priority:70,strength:.42,release:0},'bridge must not mutate an incoming cue');
  assert.equal(articulated.vocalStress,'primary');assert.ok(articulated.priority>original.priority);assert.ok(articulated.priority<=78,'automatic vocal detail must not outrank a structural/climax cue');assert.ok(articulated.strength>=.42);
  assert.equal(articulated.end,2.6,'the measured release may shorten only an existing cue that covers it');
  assert.equal(articulated.vocalPitchMovement,'rising');
  const held=strategy.classifyCandidate({role:'vocals',sourceStart:1,sourceEnd:3,sourceEventTime:1.5,vocalNote:true,musicTime:1.5,start:1.5,end:3,priority:71,strength:.5,release:0});
  assert.equal(held.vocalHeldNote,true);assert.ok(held.release>0);assert.equal(held.vocalNoteKind,'held-note');
  const diagnostics=strategy.diagnostics();
  assert.equal(diagnostics.active,true);assert.equal(diagnostics.applied.primaryArticulationCount,1);assert.equal(diagnostics.applied.heldNoteCount,1);assert.equal(diagnostics.applied.pitchDirectionPhraseCount,1);assert.equal(diagnostics.applied.phraseReleaseCount,1);
  assert.deepEqual(input,before,'planning must not rewrite analysis, cache sidecars, or semantic links');
});

test('stale links, missing evidence, forbidden language fields, and manual vocal edits fail closed',()=>{
  const api=semanticsApi(),input=music(),stale=structuredClone(input);stale.semanticTimeline=timeline(true);
  assert.equal(VocalChoreography.create({music:stale,normalizedMusic:{...stale,musicCues:[]},settings:{}},{enabled:true,api}).diagnostics().reason,'vocal-semantic-links-mismatch');
  const forbidden=music();forbidden.vocalSemantics.phrases[0].word='not allowed';
  assert.equal(VocalChoreography.create({music:forbidden,normalizedMusic:{...forbidden,musicCues:[]},settings:{}},{enabled:true,api}).diagnostics().reason,'invalid-vocal-semantics');
  const invalidCap=music();invalidCap.semanticTimeline.events[1].salienceCap=.50;
  assert.equal(VocalChoreography.create({music:invalidCap,normalizedMusic:{...invalidCap,musicCues:[]},settings:{}},{enabled:true,api}).diagnostics().reason,'invalid-semantic-timeline');
  const edited=music();
  assert.equal(VocalChoreography.create({music:edited,normalizedMusic:{...edited,musicCues:[]},settings:{vocalRegions:[{start:1,end:2,kind:'voice'}]}},{enabled:true,api}).diagnostics().reason,'vocal-evidence-edited');
  assert.equal(VocalChoreography.create({music:music(false),normalizedMusic:{...music(false),musicCues:[]},settings:{}},{enabled:true,api}).active,false);
});

test('default, missing-sidecar, and invalid-sidecar runs retain exact legacy FSEQ output',()=>{
  const input=music(false),settings={stepMs:20,dance:'balanced',seed:110,vocalFocus:1};
  const baseline=Engine.generate(input,settings),missing=Engine.generate(input,{...settings,vocalChoreography:true});
  assert.deepEqual(missing.frames,baseline.frames);assert.deepEqual(Engine.fseq(missing,'vocal.wav'),Engine.fseq(baseline,'vocal.wav'));
  assert.equal(missing.choreography.vocalChoreography.active,false);
  const invalid=music();invalid.vocalSemantics.phrases[0].word='not allowed';
  const prior=globalThis.LightForgeVocalSemantics;globalThis.LightForgeVocalSemantics=semanticsApi();
  try{
    const invalidShow=Engine.generate(invalid,{...settings,vocalChoreography:true});
    assert.deepEqual(invalidShow.frames,baseline.frames);assert.deepEqual(Engine.fseq(invalidShow,'vocal.wav'),Engine.fseq(baseline,'vocal.wav'));
    assert.equal(invalidShow.choreography.vocalChoreography.reason,'invalid-vocal-semantics');
  }finally{if(prior===undefined)delete globalThis.LightForgeVocalSemantics;else globalThis.LightForgeVocalSemantics=prior;}
});

test('active bridge is deterministic and remains vehicle/FSEQ feasible',()=>{
  const input=music(),before=structuredClone(input),prior=globalThis.LightForgeVocalSemantics;globalThis.LightForgeVocalSemantics=semanticsApi();
  try{
    const settings={stepMs:20,dance:'balanced',seed:111,vocalFocus:1,vocalChoreography:true};
    const first=Engine.generate(input,settings),second=Engine.generate(structuredClone(input),settings);
    assert.equal(first.choreography.vocalChoreography.active,true);
    assert.ok(first.choreography.lighting.vocalChoreography.applied.matchedEventCount>0);
    assert.deepEqual(first.frames,second.frames);assert.deepEqual(Engine.fseq(first,'vocal.wav'),Engine.fseq(second,'vocal.wav'));
    assert.equal(first.validation.valid,true);assert.equal(Engine.validate(first,input).valid,true);
    assert.deepEqual(input,before);
  }finally{if(prior===undefined)delete globalThis.LightForgeVocalSemantics;else globalThis.LightForgeVocalSemantics=prior;}
});

test('actual cap-aware vocal semantics proof activates only on the current valid timeline', {skip:!ActualTimeline||!ActualVocalSemantics?'requires vocal semantic enrichment prerequisite':false},()=>{
  const raw=music(false),sidecar=ActualVocalSemantics.build(raw),semanticTimeline=ActualTimeline.build(raw),links=ActualVocalSemantics.linkTimeline(sidecar,semanticTimeline);
  const enriched={...raw,semanticTimeline,vocalSemantics:sidecar,vocalSemanticLinks:links},settings={stepMs:20,dance:'balanced',seed:112,vocalFocus:1};
  const baseline=Engine.generate(raw,settings),sidecarOff=Engine.generate(enriched,{...settings,vocalChoreography:false});
  assert.deepEqual(sidecarOff.frames,baseline.frames,'valid enrichment must be inert until the explicit choreography opt-in');
  assert.deepEqual(Engine.fseq(sidecarOff,'vocal.wav'),Engine.fseq(baseline,'vocal.wav'));
  const active=Engine.generate(enriched,{...settings,vocalChoreography:true});
  assert.equal(active.choreography.vocalChoreography.active,true);
  assert.ok(active.choreography.lighting.vocalChoreography.applied.matchedEventCount>0,'real acoustic evidence must reach existing planner candidates');
  const capStale=structuredClone(enriched),capEvent=capStale.semanticTimeline.events.find(event=>!Object.prototype.hasOwnProperty.call(event,'salienceCap'));
  assert.ok(capEvent,'fixture needs an uncapped event');capEvent.salienceCap=1;
  assert.equal(ActualTimeline.validate(capStale.semanticTimeline).valid,true,'a cap at one is valid yet must change the canonical timeline receipt');
  const stale=Engine.generate(capStale,{...settings,vocalChoreography:true});
  assert.equal(stale.choreography.vocalChoreography.active,false);assert.equal(stale.choreography.vocalChoreography.reason,'vocal-semantic-links-mismatch');
  assert.deepEqual(stale.frames,baseline.frames);assert.deepEqual(Engine.fseq(stale,'vocal.wav'),Engine.fseq(baseline,'vocal.wav'));
  const invalidCap=structuredClone(enriched);invalidCap.semanticTimeline.events[0].salienceCap=-.01;
  assert.equal(ActualTimeline.validate(invalidCap.semanticTimeline).valid,false);assert.throws(()=>ActualVocalSemantics.linkTimeline(sidecar,invalidCap.semanticTimeline),/invalid timeline/);
  const rejected=Engine.generate(invalidCap,{...settings,vocalChoreography:true});
  assert.equal(rejected.choreography.vocalChoreography.active,false);assert.equal(rejected.choreography.vocalChoreography.reason,'invalid-semantic-timeline');
  assert.deepEqual(rejected.frames,baseline.frames);assert.deepEqual(rejected,structuredClone(rejected),'diagnostics must remain serializable');
  const wrongSidecarClock=structuredClone(enriched);wrongSidecarClock.vocalSemantics.clock='resampled-vocals';
  const wrongSidecar=Engine.generate(wrongSidecarClock,{...settings,vocalChoreography:true});
  assert.equal(wrongSidecar.choreography.vocalChoreography.active,false);assert.equal(wrongSidecar.choreography.vocalChoreography.reason,'invalid-vocal-semantics');
  assert.deepEqual(wrongSidecar.frames,baseline.frames);
  const wrongTimelineClock=structuredClone(enriched);wrongTimelineClock.semanticTimeline.clock='resampled-analysis';
  assert.equal(ActualTimeline.validate(wrongTimelineClock.semanticTimeline).valid,false,'canonical timeline validation must reject a non-original clock');
  assert.throws(()=>ActualVocalSemantics.linkTimeline(sidecar,wrongTimelineClock.semanticTimeline),/matching semantic timeline/);
  const wrongTimeline=Engine.generate(wrongTimelineClock,{...settings,vocalChoreography:true});
  assert.equal(wrongTimeline.choreography.vocalChoreography.active,false);assert.equal(wrongTimeline.choreography.vocalChoreography.reason,'invalid-semantic-timeline');
  assert.deepEqual(wrongTimeline.frames,baseline.frames);assert.deepEqual(Engine.fseq(wrongTimeline,'vocal.wav'),Engine.fseq(baseline,'vocal.wav'));
});

test('browser and worker load acoustic semantics and bridge before ShowEngine',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../web/index.html'),'utf8');
  const timeline=html.indexOf('analysis/semantic-timeline.js'),semantics=html.indexOf('analysis/vocal-semantics.js'),bridge=html.indexOf('engine/vocal-choreography.js'),engine=html.indexOf('engine/show-engine.js');
  assert.ok(timeline>=0&&semantics>timeline&&bridge>semantics&&engine>bridge);
  const worker=fs.readFileSync(path.join(__dirname,'../web/engine/worker.js'),'utf8');
  const workerTimeline=worker.indexOf("'../analysis/semantic-timeline.js'"),workerSemantics=worker.indexOf("'../analysis/vocal-semantics.js'"),workerBridge=worker.indexOf("'vocal-choreography.js'"),workerEngine=worker.indexOf("'show-engine.js'");
  assert.ok(workerTimeline>=0&&workerSemantics>workerTimeline&&workerBridge>workerSemantics&&workerEngine>workerBridge);
});
