'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const Strategy=require('../web/engine/semantic-choreography.js');
const Engine=require('../web/engine/show-engine.js');
const Timeline=require('../web/analysis/semantic-timeline.js');
const Salience=require('../web/analysis/salience.js');

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

test('browser and composition-worker contexts load the opt-in semantic strategy before ShowEngine',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../web/index.html'),'utf8');
  const quality=html.indexOf('engine/choreography-quality.js'),semantic=html.indexOf('engine/semantic-choreography.js'),engine=html.indexOf('engine/show-engine.js');
  assert.ok(quality>=0&&semantic>quality&&engine>semantic);
  const worker=fs.readFileSync(path.join(__dirname,'../web/engine/worker.js'),'utf8');
  const workerSemantic=worker.indexOf("'semantic-choreography.js'"),workerEngine=worker.indexOf("'show-engine.js'");
  assert.ok(workerSemantic>=0&&workerEngine>workerSemantic);
});
