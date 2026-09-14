'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const Validation=require('../web/engine/perceptual-validation.js');

function quality(){
 return {validInput:true,
  conflictingCommands:{assessed:true,count:2},
  minimumDurations:{assessed:true,violationCount:3,repeatIntervalViolationCount:1},
  actuatorOveruse:{assessed:true,overusedOutputCount:1},
  outputOveruse:{assessed:false,violationCount:null}
 };
}
function sync(){return {collision:{targetLoss:{count:4,rate:.25,highSalienceCount:2,highSalienceRate:.5},mechanicalLoss:{count:1,rate:.1,highSalienceCount:0,highSalienceRate:0}}};}

test('reports per-class command/perceptual percentiles only from explicit realization evidence',()=>{
 const events=[
  {eventClass:'vocal',targetTime:1,commandTime:1.02,predictedPerceptualTime:1.05,status:'matched',salience:.92,collisionLoss:false},
  {eventClass:'vocal_phrase',targetTime:2,commandTime:1.97,predictedPerceptualTime:2.01,status:'matched',tier:'primary',collisionLoss:false},
  {eventClass:'bass',targetTime:3,status:'suppressed',salience:.9,collisionLoss:true},
  {eventClass:'kick',targetTime:4,commandTime:3.93,measuredPerceptualTime:4.01,status:'matched',tier:'structural',collisionLoss:false}
 ];
 const show={frames:Uint8Array.from([0,255,0]),choreography:{quality:quality()},synchronization:sync()},before=Uint8Array.from(show.frames);
 const report=Validation.evaluate(show,{events});
 assert.deepEqual(show.frames,before,'validation must never mutate final frame bytes');
 const vocals=report.perEventClass.vocals;
 assert.equal(vocals.timing.command.state,'available');
 assert.equal(vocals.timing.command.count,2);
 assert.equal(vocals.timing.command.medianMs,25);
 assert.equal(vocals.timing.command.p90Ms,29);
 assert.equal(vocals.timing.command.p95Ms,29.5);
 assert.equal(vocals.timing.command.p99Ms,29.9);
 assert.equal(vocals.timing.command.maxMs,30);
 assert.equal(vocals.timing.perceptual.state,'unavailable','predictions are not relabelled as measurements');
 assert.equal(vocals.timing.predictedPerceptual.state,'estimated');
 assert.equal(vocals.coverage.coverage,1);
 assert.equal(vocals.highSalienceCoverage.coverage,1);
 assert.equal(report.perEventClass.bass.coverage.coverage,0);
 assert.equal(report.perEventClass.bass.collisionLoss.count,1);
 assert.equal(report.perEventClass.bass.collisionLoss.highSalienceCount,1);
 assert.equal(report.perEventClass.kick.timing.perceptual.medianMs,10);
 assert.equal(report.collision.syncReview.lighting.count,4);
 assert.equal(report.feasibility.state,'partial');
 assert.equal(report.feasibility.knownViolationCount,7);
});

test('keeps missing event, timing, salience, collision, and feasibility evidence explicitly unavailable',()=>{
 const report=Validation.evaluate({choreography:{}},{});
 assert.equal(report.eventEvidence.state,'unavailable');
 assert.equal(report.perEventClass.vocals.eventEvidence.state,'unavailable');
 assert.equal(report.perEventClass.vocals.timing.command.state,'unavailable');
 assert.equal(report.perEventClass.vocals.coverage.state,'unavailable');
 assert.equal(report.perEventClass.vocals.highSalienceCoverage.state,'unavailable');
 assert.equal(report.perEventClass.vocals.collisionLoss.state,'unavailable');
 assert.equal(report.collision.syncReview.lighting.state,'unavailable');
 assert.equal(report.feasibility.state,'unavailable');
 assert.match(report.scope,/does not establish detector accuracy/);
});

test('accepts an explicit measured response but rejects an unmarked perceptual timestamp as ground truth',()=>{
 const report=Validation.evaluate(null,{eventEvidence:[
  {eventClass:'snare',targetTime:1,commandTime:1.01,perceptualTime:1.02,status:'matched'},
  {eventClass:'snare',targetTime:2,commandTime:2.01,perceptualTime:2.03,perceptualEvidence:'measured',status:'matched'}
 ]});
 const snare=report.perEventClass.snare;
 assert.equal(snare.timing.command.count,2);
 assert.equal(snare.timing.perceptual.count,1);
 assert.equal(snare.timing.perceptual.medianMs,30);
});

test('normalizes semantic timeline event types into canonical coverage classes and rejects negative timestamps',()=>{
 const report=Validation.evaluate(null,{events:[
  {type:'vocal_note',targetTime:1,commandTime:1,status:'matched'},
  {type:'bass_note',targetTime:2,commandTime:2,status:'matched'},
  {type:'percussion_kick',targetTime:3,commandTime:3,status:'matched'},
  {type:'percussion_snare',targetTime:4,commandTime:4,status:'matched'},
  {type:'percussion_clap',targetTime:5,commandTime:5,status:'matched'},
  {eventClass:'kick',targetTime:-1,commandTime:-1,status:'matched'},
  {eventClass:'snare',targetTime:6,commandTime:-1,status:'matched'}
 ]});
 assert.equal(report.eventEvidence.acceptedCount,6);
 assert.equal(report.eventEvidence.invalidCount,1);
 assert.equal(report.perEventClass.vocals.eventEvidence.count,1);
 assert.equal(report.perEventClass.bass.eventEvidence.count,1);
 assert.equal(report.perEventClass.kick.eventEvidence.count,1);
 assert.equal(report.perEventClass.snare.eventEvidence.count,2);
 assert.equal(report.perEventClass.percussion.eventEvidence.count,1);
 assert.equal(report.perEventClass.snare.timing.command.count,1,'negative commands are not timing evidence');
 assert.equal(report.perEventClass.lighting.eventEvidence.state,'unavailable','lighting remains an explicit canonical unavailable state');
 assert.equal(report.perEventClass['percussion-kick'],undefined);
});

test('bounds exported event evidence and leaves caller-owned data untouched',()=>{
 const events=Array.from({length:10005},(_,index)=>({eventClass:'beat',targetTime:index,commandTime:index,status:'matched',salience:.2}));
 const before=structuredClone(events),first=Validation.evaluate(null,{events}),second=Validation.analyze(null,{events});
 assert.deepEqual(events,before);
 assert.deepEqual(first,second);
 assert.equal(first.eventEvidence.acceptedCount,10000);
 assert.equal(first.eventEvidence.omittedCount,5);
 assert.equal(first.perEventClass.beat.coverage.selected,10000);
});

test('browser and composition worker load the validation sidecar before ShowEngine',()=>{
 const fs=require('node:fs'),path=require('node:path');
 const index=fs.readFileSync(path.join(__dirname,'../web/index.html'),'utf8');
 const worker=fs.readFileSync(path.join(__dirname,'../web/engine/worker.js'),'utf8');
 assert.ok(index.indexOf('engine/perceptual-validation.js')>index.indexOf('engine/choreography-quality.js'));
 assert.ok(index.indexOf('engine/perceptual-validation.js')<index.indexOf('engine/show-engine.js'));
 assert.ok(worker.indexOf("'perceptual-validation.js'")>worker.indexOf("'choreography-quality.js'"));
 assert.ok(worker.indexOf("'perceptual-validation.js'")<worker.indexOf("'show-engine.js'"));
});
