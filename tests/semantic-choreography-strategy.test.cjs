'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {createRequire}=require('node:module');
const Strategy=require('../web/engine/semantic-choreography.js');
const Engine=require('../web/engine/show-engine.js');
const Timeline=require('../web/analysis/semantic-timeline.js');
const Salience=require('../web/analysis/salience.js');
const Recurrence=require('../web/analysis/recurrence.js');

function engineTimelineFingerprint(timeline){
  const file=path.join(__dirname,'../web/engine/show-engine.js');
  const marker='  const api={version:VERSION,';
  const source=fs.readFileSync(file,'utf8').replace(marker,'  root.__semanticTimelineFingerprintForTest=semanticTimelineFingerprint;\n'+marker);
  assert.notEqual(source,fs.readFileSync(file,'utf8'),'test instrumentation must bind the production ShowEngine fingerprint function');
  const context={require:createRequire(file)};
  vm.createContext(context);
  vm.runInContext(source,context,{filename:file});
  return context.__semanticTimelineFingerprintForTest(timeline);
}

test('semantic strategy is deterministic and makes bounded hierarchy, density, and negative-space decisions',()=>{
  const semantic={events:[
    {id:'structural',time:1,source:'vocals',score:.96,tier:'structural'},
    {id:'nearby-detail',time:1.08,source:'vocals',score:.20,tier:'secondary'},
    {id:'detail-a',time:3,source:'vocals',score:.30,tier:'secondary'},
    {id:'detail-b',time:3.1,source:'vocals',score:.40,tier:'secondary'},
    {id:'detail-c',time:3.2,source:'vocals',score:.50,tier:'secondary'}
  ]};
  const strategy=Strategy.create(semantic,{stepMs:20});
  const targets=[1,1.08,3,3.1,3.2].map(time=>({role:'vocals',time,end:time+.12}));
  const firstState=strategy.prepareTargets(targets),secondState=strategy.prepareTargets(targets);
  const raw=[
    {serial:0,role:'vocals',sourceEventTime:1,priority:30,kind:'vocal entrance'},
    {serial:1,role:'vocals',sourceEventTime:1.08,priority:22,kind:'vocal articulation'},
    {serial:2,role:'vocals',sourceEventTime:3,priority:21,kind:'vocal articulation'},
    {serial:3,role:'vocals',sourceEventTime:3.1,priority:22,kind:'vocal articulation'},
    {serial:4,role:'vocals',sourceEventTime:3.2,priority:23,kind:'vocal articulation'}
  ];
  const before=structuredClone(raw),firstClassified=raw.map(candidate=>strategy.classifyCandidate(candidate,firstState)),secondClassified=raw.map(candidate=>strategy.classifyCandidate(candidate,secondState));
  const first=strategy.filterCandidates(firstClassified,firstState),second=strategy.filterCandidates(secondClassified,secondState);
  assert.deepEqual(raw,before,'the strategy must not mutate incoming candidates');
  assert.deepEqual(first,second,'identical targets and candidates must produce identical scheduling decisions');
  assert.ok(firstClassified[0].priority>raw[0].priority,'structural target receives a deterministic hierarchy boost');
  assert.equal(first.diagnostics.active,true);
  assert.ok(first.diagnostics.hierarchy.boostedCandidateCount>0);
  assert.ok(first.diagnostics.negativeSpace.suppressedCandidateCount>0,'low-authority detail yields to structural negative space');
  assert.ok(first.diagnostics.density.suppressedCandidateCount>0,'dense low-authority targets are bounded');
  assert.ok(first.candidates.some(candidate=>candidate.serial===0),'the structural target remains schedulable');
});

test('semantic strategy falls back to the supported FSEQ clock for unsupported precision',()=>{
  const semantic={events:[{id:'accent',time:0,source:'vocals',score:.9,tier:'primary'}]},target=[{role:'vocals',time:.09,end:.2}];
  const supported=Strategy.create(semantic,{stepMs:20}).prepareTargets(target);
  const fallback=Strategy.create(semantic,{stepMs:25}).prepareTargets(target);
  assert.deepEqual(fallback,supported);
  assert.equal(fallback.links.length,0,'25 ms must not widen semantic target matching');
});

function musicFixture(){
  const duration=80,beats=Array.from({length:duration*2},(_,index)=>index*.5);
  return {
    duration,bpm:120,beatConfidence:.96,beats,downbeats:beats.filter((_,index)=>index%4===0),
    sections:[{start:0,end:20,energy:.2,label:'Intro'},{start:20,end:48,energy:.96,label:'Drop'},{start:48,end:duration,energy:.45,label:'Outro'}],
    phrases:[{start:20,end:42,energy:.96,kind:'drop',confidence:.95}],activityRanges:[{start:0,end:duration}],
    waveform:Array(400).fill(.72),onsets:[{time:20,strength:1,band:'bass'}],impacts:[{time:20,strength:1,kind:'drop'}],
    vocals:{available:true,presence:'detected',sourceSeparated:true,confidence:.96,phrases:[{start:20,end:24,confidence:.96,strength:.95,kind:'singing'}],accents:[{time:20,confidence:.96,strength:1,kind:'syllabic-accent'}],notes:[]},
    bassNotes:[{start:20,end:22,confidence:.95,strength:.95,midi:40}],bassAnalysis:{confidence:.95,phrases:[{start:20,end:22,confidence:.95,strength:.95}]}
  };
}

test('semantic choreography is opt-in, mismatch-safe, deterministic, and FSEQ-feasible',()=>{
  const music=musicFixture(),settings={stepMs:20,dance:'expressive',seed:88};
  const timeline=Timeline.build(music),salience=Salience.build(timeline);
  const baseline=Engine.generate(music,settings);
  const validMusic={...music,semanticTimeline:timeline,musicSalience:salience};
  const legacyWithValidTargets=Engine.generate(validMusic,settings);
  assert.deepEqual(legacyWithValidTargets.frames,baseline.frames,'semantic data alone must retain the legacy planner');
  assert.deepEqual(Engine.fseq(legacyWithValidTargets,'semantic.wav'),Engine.fseq(baseline,'semantic.wav'));
  const mismatch=Engine.generate({...validMusic,musicSalience:{...salience,duration:music.duration-1}},{...settings,semanticChoreography:true});
  assert.deepEqual(mismatch.frames,baseline.frames,'a timeline/salience mismatch must fall back exactly');
  assert.deepEqual(Engine.fseq(mismatch,'semantic.wav'),Engine.fseq(baseline,'semantic.wav'));
  assert.equal(mismatch.choreography.semanticStrategy.active,false);
  const first=Engine.generate(validMusic,{...settings,semanticChoreography:true}),second=Engine.generate(validMusic,{...settings,semanticChoreography:true});
  assert.equal(first.choreography.semanticStrategy.active,true);
  assert.ok(first.choreography.semanticStrategy.linkedTargetCount>0);
  assert.ok(first.choreography.lighting.semanticStrategy.hierarchy.matchedCandidateCount>0);
  assert.deepEqual(first.frames,second.frames,'the opt-in strategy must be deterministic');
  assert.deepEqual(Engine.fseq(first,'semantic.wav'),Engine.fseq(second,'semantic.wav'));
  assert.equal(first.validation.valid,true);
  assert.equal(Engine.validate(first,music).valid,true,'strategy output must retain vehicle/FSEQ feasibility');
});

test('semantic choreography accepts the cap-bound salience sidecar for a conservative percussion estimate',()=>{
  const music=musicFixture();
  music.percussionAnalysis={source:'mix-feature-estimate',estimated:true,events:[
    {time:20,kind:'kick',confidence:.55,strength:.58,estimated:true}
  ]};
  const timeline=Timeline.build(music),salience=Salience.build(timeline);
  const capped=timeline.events.find(event=>event.type==='percussion_kick');
  assert.equal(capped.salienceCap,.41);
  assert.equal(Salience.validate(salience,timeline).valid,true);
  assert.equal(Recurrence.timelineFingerprint(timeline),salience.timelineFingerprint,'recurrence and salience must bind the same capped timeline');
  assert.equal(engineTimelineFingerprint(timeline),salience.timelineFingerprint,'ShowEngine must bind the same cap-aware ordering and marker as analysis sidecars');
  const recapped=structuredClone(timeline);
  recapped.events.find(event=>event.type==='percussion_kick').salienceCap=.42;
  const recappedSalience=Salience.build(recapped);
  assert.equal(Recurrence.timelineFingerprint(recapped),recappedSalience.timelineFingerprint);
  assert.equal(engineTimelineFingerprint(recapped),recappedSalience.timelineFingerprint);
  assert.notEqual(recappedSalience.timelineFingerprint,salience.timelineFingerprint,'a cap-only mutation must invalidate every semantic consumer');
  const legacySettings={stepMs:20,dance:'expressive',seed:88};
  const baseline=Engine.generate(music,legacySettings);
  const legacyWithCappedSidecar=Engine.generate({...music,semanticTimeline:timeline,musicSalience:salience},legacySettings);
  assert.deepEqual(legacyWithCappedSidecar.frames,baseline.frames,'a valid capped sidecar must not alter the default planner');
  assert.deepEqual(Engine.fseq(legacyWithCappedSidecar,'capped.wav'),Engine.fseq(baseline,'capped.wav'));
  const show=Engine.generate({...music,semanticTimeline:timeline,musicSalience:salience},{
    stepMs:20,dance:'expressive',seed:88,semanticChoreography:true
  });
  assert.equal(show.choreography.semanticStrategy.active,true,'the engine must use the same cap-aware timeline binding as music salience');
  assert.equal(show.validation.valid,true);
});

test('semantic consumers reject invalid canonical timelines even with a forged matching salience sidecar',()=>{
  const music=musicFixture(),settings={stepMs:20,dance:'expressive',seed:88};
  const timeline=Timeline.build(music),salience=Salience.build(timeline);
  const evidence=Recurrence.captureEvidence(music,timeline),sidecar=Recurrence.build(timeline,evidence);
  const baseline=Engine.generate(music,settings);
  const assertRejected=invalid=>{
    assert.equal(Timeline.validate(invalid).valid,false);
    assert.equal(Salience.validate(salience,invalid).valid,false);
    assert.throws(()=>Salience.build(invalid),/valid semantic timeline/);
    assert.throws(()=>Recurrence.captureEvidence(music,invalid),/valid semantic timeline/);
    assert.equal(Recurrence.validateEvidence(evidence,invalid).valid,false);
    assert.equal(Recurrence.validate(sidecar,invalid,evidence).valid,false);
    const forged={...salience,timelineSchemaVersion:invalid.schemaVersion,clock:invalid.clock,timelineFingerprint:engineTimelineFingerprint(invalid)};
    const show=Engine.generate({...music,semanticTimeline:invalid,musicSalience:forged},{...settings,semanticChoreography:true});
    assert.equal(show.choreography.semanticStrategy.active,false);
    assert.deepEqual(show.frames,baseline.frames,'invalid semantic timing metadata must fall back exactly to the legacy planner');
    assert.deepEqual(Engine.fseq(show,'invalid-semantic.wav'),Engine.fseq(baseline,'invalid-semantic.wav'));
  };
  const wrongClock=structuredClone(timeline);wrongClock.clock='resampled-clock';
  assertRejected(wrongClock);
  const wrongSchema=structuredClone(timeline);wrongSchema.schemaVersion=99;
  assertRejected(wrongSchema);
  const invalidCap=structuredClone(timeline);
  const cappedEvent=invalidCap.events.find(event=>event.salience>.01);
  cappedEvent.salienceCap=cappedEvent.salience-.001;
  assertRejected(invalidCap);
  const invalidSalience=structuredClone(timeline);
  const invalidSalienceEvent=invalidSalience.events.find(event=>event.salience>.01);
  delete invalidSalienceEvent.salienceCap;
  invalidSalienceEvent.salience=1.01;
  assertRejected(invalidSalience);
  const emptyId=structuredClone(timeline);emptyId.events[0].id='';
  assertRejected(emptyId);
  const invalidDuration=structuredClone(timeline);invalidDuration.events[0].duration=invalidDuration.duration+1;
  assertRejected(invalidDuration);
});

test('semantic choreography rejects a forged but fingerprint-matching salience ranking',()=>{
  const music=musicFixture(),settings={stepMs:20,dance:'expressive',seed:88};
  const timeline=Timeline.build(music),salience=Salience.build(timeline);
  const forged=structuredClone(salience);
  const ranked=forged.events.find(event=>event.tier!=='climax')||forged.events[0];
  ranked.tier=ranked.tier==='climax'?'micro':'climax';
  assert.equal(forged.timelineFingerprint,engineTimelineFingerprint(timeline),'the attack must retain a matching timeline fingerprint');
  assert.equal(Salience.validate(forged,timeline).valid,false,'canonical salience validation must reject a malformed rank/tier record');
  const baseline=Engine.generate(music,settings);
  const show=Engine.generate({...music,semanticTimeline:timeline,musicSalience:forged},{...settings,semanticChoreography:true});
  assert.equal(show.choreography.semanticStrategy.active,false);
  assert.deepEqual(show.frames,baseline.frames,'a malformed semantic ranking must fall back exactly to the legacy planner');
  assert.deepEqual(Engine.fseq(show,'invalid-salience.wav'),Engine.fseq(baseline,'invalid-salience.wav'));
});

test('semantic consumers reject malformed timeline event containers without throwing or activating choreography',()=>{
  const music=musicFixture(),settings={stepMs:20,dance:'expressive',seed:88};
  const timeline=Timeline.build(music),salience=Salience.build(timeline);
  const evidence=Recurrence.captureEvidence(music,timeline),sidecar=Recurrence.build(timeline,evidence);
  const baseline=Engine.generate(music,settings);
  for(const [label,events] of [['null-event',[null]],['object-events',{}],['null-events',null],['string-events','x']]){
    const malformed={...timeline,events};
    assert.doesNotThrow(()=>Timeline.validate(malformed),label);
    assert.equal(Timeline.validate(malformed).valid,false,label);
    assert.doesNotThrow(()=>Salience.validate(salience,malformed),label);
    assert.equal(Salience.validate(salience,malformed).valid,false,label);
    assert.throws(()=>Salience.build(malformed),/valid semantic timeline/,label);
    assert.throws(()=>Recurrence.captureEvidence(music,malformed),/valid semantic timeline/,label);
    assert.equal(Recurrence.validateEvidence(evidence,malformed).valid,false,label);
    assert.equal(Recurrence.validate(sidecar,malformed,evidence).valid,false,label);
    const show=Engine.generate({...music,semanticTimeline:malformed,musicSalience:salience},{...settings,semanticChoreography:true});
    assert.equal(show.choreography.semanticStrategy.active,false,label);
    assert.deepEqual(show.frames,baseline.frames,label+' malformed semantic events must fall back exactly to the legacy planner');
    assert.deepEqual(Engine.fseq(show,label+'-semantic.wav'),Engine.fseq(baseline,label+'-semantic.wav'),label);
  }
});

test('semantic choreography rejects malformed salience events without throwing',()=>{
  const music=musicFixture(),settings={stepMs:20,dance:'expressive',seed:88};
  const timeline=Timeline.build(music),salience=Salience.build(timeline);
  const malformed=structuredClone(salience);
  malformed.events[0]=null;
  assert.doesNotThrow(()=>Salience.validate(malformed,timeline));
  assert.equal(Salience.validate(malformed,timeline).valid,false);
  const baseline=Engine.generate(music,settings);
  const show=Engine.generate({...music,semanticTimeline:timeline,musicSalience:malformed},{...settings,semanticChoreography:true});
  assert.equal(show.choreography.semanticStrategy.active,false);
  assert.deepEqual(show.frames,baseline.frames,'malformed salience events must fall back exactly to the legacy planner');
  assert.deepEqual(Engine.fseq(show,'malformed-salience.wav'),Engine.fseq(baseline,'malformed-salience.wav'));
});

test('semantic choreography rejects a non-array salience event field without throwing',()=>{
  const music=musicFixture(),settings={stepMs:20,dance:'expressive',seed:88};
  const timeline=Timeline.build(music),salience=Salience.build(timeline);
  const malformed={...salience,events:'x'};
  assert.doesNotThrow(()=>Salience.validate(malformed,timeline));
  assert.equal(Salience.validate(malformed,timeline).valid,false);
  const baseline=Engine.generate(music,settings);
  const show=Engine.generate({...music,semanticTimeline:timeline,musicSalience:malformed},{...settings,semanticChoreography:true});
  assert.equal(show.choreography.semanticStrategy.active,false);
  assert.deepEqual(show.frames,baseline.frames,'a non-array semantic ranking must fall back exactly to the legacy planner');
  assert.deepEqual(Engine.fseq(show,'non-array-salience.wav'),Engine.fseq(baseline,'non-array-salience.wav'));
});

test('semantic choreography falls back when a future validator throws',()=>{
  const music=musicFixture(),settings={stepMs:20,dance:'expressive',seed:88};
  const timeline=Timeline.build(music),salience=Salience.build(timeline),baseline=Engine.generate(music,settings);
  const original=Timeline.validate;Timeline.validate=()=>{throw Error('injected validator failure');};
  try{
    const show=Engine.generate({...music,semanticTimeline:timeline,musicSalience:salience},{...settings,semanticChoreography:true});
    assert.equal(show.choreography.semanticStrategy.active,false);
    assert.deepEqual(show.frames,baseline.frames,'validator exceptions must retain the legacy planner');
    assert.deepEqual(Engine.fseq(show,'validator-failure.wav'),Engine.fseq(baseline,'validator-failure.wav'));
  }finally{Timeline.validate=original;}
});

test('browser and composition-worker contexts load the canonical timeline before semantic strategy and ShowEngine',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../web/index.html'),'utf8');
  const timeline=html.indexOf('analysis/semantic-timeline.js'),salience=html.indexOf('analysis/salience.js'),quality=html.indexOf('engine/choreography-quality.js'),semantic=html.indexOf('engine/semantic-choreography.js'),engine=html.indexOf('engine/show-engine.js');
  assert.ok(timeline>=0&&salience>timeline&&quality>salience&&semantic>quality&&engine>semantic);
  const worker=fs.readFileSync(path.join(__dirname,'../web/engine/worker.js'),'utf8');
  const workerTimeline=worker.indexOf("'../analysis/semantic-timeline.js'"),workerSalience=worker.indexOf("'../analysis/salience.js'"),workerSemantic=worker.indexOf("'semantic-choreography.js'"),workerEngine=worker.indexOf("'show-engine.js'");
  assert.ok(workerTimeline>=0&&workerSalience>workerTimeline&&workerSemantic>workerSalience&&workerEngine>workerSemantic);
});

test('density and breathing space preserve exact selected source attacks while pruning nearby decoration',()=>{
 const semantic={events:[{id:'anchor',time:1,source:'vocals',score:.96,tier:'structural'},...Array.from({length:4},(_,i)=>({id:'voice-'+i,time:1.08+i*.1,source:'vocals',score:.2,tier:'secondary'}))]},strategy=Strategy.create(semantic,{stepMs:15});
 const targets=semantic.events.map(event=>({role:'vocals',time:event.time,end:event.time+.12})),state=strategy.prepareTargets(targets);
 const attacks=targets.slice(1).map((target,i)=>({serial:i,role:'vocals',sourceSeparated:true,sourceConfidence:.399,sourceEventTime:target.time,priority:70,kind:'vocal articulation'}));
 const decoration=attacks.map((attack,i)=>({...attack,serial:10+i,role:undefined,sourceEventTime:attack.sourceEventTime+.015}));
 const classified=[...attacks,...decoration].map(candidate=>strategy.classifyCandidate(candidate,state)),result=strategy.filterCandidates(classified,state);
 for(const attack of attacks)assert.ok(result.candidates.some(candidate=>candidate.serial===attack.serial),'an already selected source attack remains available for collision allocation');
 assert.equal(result.diagnostics.density.protectedTargetCandidateCount,4);assert.ok(result.candidates.length<classified.length,'decorative copies still yield to higher musical authority');
 assert.equal(classified.find(candidate=>candidate.serial===10).semanticTargetAttack,false,'a nearby decorative event is not an exact source attack');
});
