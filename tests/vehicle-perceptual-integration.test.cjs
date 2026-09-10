'use strict';

const test=require('node:test');
const assert=require('node:assert/strict');
const Engine=require('../web/engine/show-engine.js');
const Profile=require('../web/engine/vehicle-profile.js');

function fixture(duration=80){
 const beats=Array.from({length:duration*2},(_,index)=>index*.5);
 return {duration,bpm:120,meter:4,beatConfidence:1,beats,downbeats:beats.filter((_,index)=>index%4===0),onsets:[],sections:[{start:0,end:duration,energy:.9,label:'Active'}],waveform:Array(duration*50).fill(.9),energy:Array(duration*50).fill(.9),energyStep:.02,activityRanges:[{start:0,end:duration}],analysisVersion:2};
}

test('automatic perceptual report observes final realization without changing default FSEQ bytes',()=>{
 const music=fixture(),base=Engine.generate(music,{dance:'expressive',seed:9}),disabled=Engine.generate(music,{dance:'expressive',seed:9,vehicleTimingCalibration:{version:1,enabled:false}});
 assert.deepEqual(Engine.fseq(base),Engine.fseq(disabled),'an explicit disabled calibration must be byte-identical to legacy/default export');
 assert.equal(base.validation.perceptualValidation.state,'available');
 assert.equal(base.perceptualValidation.state,'available');
 assert.equal(base.perceptualValidation.eventEvidence.source,'options.eventEvidence');
 assert.equal(base.perceptualValidation.eventEvidence.acceptedCount,base.synchronization.eventEvidence.length);
 assert.ok(base.synchronization.eventEvidence.some(row=>row.eventClass==='mechanical'&&row.realizationStatus==='matched'));
 assert.equal(base.perceptualValidation.perEventClass.mechanical.timing.command.state,'available');
 assert.equal(base.perceptualValidation.perEventClass.mechanical.timing.perceptual.state,'unavailable','estimated arrivals must not be labelled as measured response');
 assert.equal(base.perceptualValidation.perEventClass.mechanical.timing.predictedPerceptual.state,'unavailable','uncalibrated commands must not be relabelled as perceptual predictions');
});

test('only a calibrated planner intent may expose an estimated mechanical perceptual timestamp',()=>{
 const show=Engine.generate(fixture(),{dance:'expressive',seed:9,vehicleTimingCalibration:{version:1,enabled:true,calibrationId:'mirror-latency',outputs:{mirrorL:{commandLatencyMs:80,activationLatencyMs:40}}}});
 const mechanical=show.synchronization.eventEvidence.filter(row=>row.eventClass==='mechanical'&&row.realizationStatus==='matched');
 assert.ok(mechanical.length>0);
 assert.ok(mechanical.some(row=>Number.isFinite(row.predictedPerceptualTime)),'a calibrated arrival may be reported as an estimate');
 assert.equal(show.perceptualValidation.perEventClass.mechanical.timing.predictedPerceptual.state,'estimated');
});

test('explicit vehicle timing limits remove infeasible automatic closure gestures before FSEQ realization',()=>{
 const calibration={version:1,enabled:true,calibrationId:'strict-trunk-limits',outputs:{trunk:{commandLatencyMs:1,minimumUsefulDurationMs:60000,minimumRepeatIntervalMs:60000}}};
 const show=Engine.generate(fixture(),{dance:'expressive',seed:9,vehicleTimingCalibration:calibration});
 const trunkQuality=show.choreography.quality.minimumDurations.outputs.find(row=>row.id==='trunk');
 assert.equal(show.validation.valid,true);
 assert.equal(show.movements.some(event=>event.outputId==='trunk'),false);
 assert.equal(show.choreography.targets.some(target=>target.outputId==='trunk'),false);
 assert.ok(show.choreography.movement.skipped.some(reason=>reason.startsWith('trunk: automatic movement omitted because minimum useful duration 60000 ms')));
 assert.equal(trunkQuality.minimumUsefulDurationMs,60000);
 assert.equal(trunkQuality.minimumRepeatIntervalMs,60000);
 assert.equal(trunkQuality.minimumDurationViolationCount,0);
 assert.equal(trunkQuality.repeatIntervalViolationCount,0);
 for(let frame=0;frame<show.frameCount;frame++)assert.equal(show.frames[frame*200+40],0,'trunk channel must remain idle when no complete safe gesture can be planned');
});

test('explicit timing limits reject infeasible manual commands instead of exporting them',()=>{
 const calibration={version:1,enabled:true,calibrationId:'manual-trunk-limit',outputs:{trunk:{commandLatencyMs:1,minimumUsefulDurationMs:5000}}};
 assert.throws(()=>Engine.generate(fixture(),{dance:'off',vehicleTimingCalibration:calibration,manualCues:[{id:'short-open',outputId:'trunk',start:2,end:3,value:63}]}),/Vehicle timing calibration rejects 1 minimum-duration or repeat-interval command violation/);
});

test('repeat-only timing calibration is independently assessed and rejects rapid manual commands',()=>{
 const calibration={version:1,enabled:true,calibrationId:'manual-trunk-repeat',outputs:{trunk:{commandLatencyMs:1,minimumRepeatIntervalMs:5000}}};
 assert.throws(()=>Engine.generate(fixture(),{dance:'off',vehicleTimingCalibration:calibration,manualCues:[
  {id:'open',outputId:'trunk',start:2,end:3,value:63},
  {id:'close',outputId:'trunk',start:3,end:4,value:191}
 ]}),/Vehicle timing calibration rejects 1 minimum-duration or repeat-interval command violation/);
});

test('vehicle timing calibration rejects malformed input and preserves explicit zero feasibility limits',()=>{
 const resolved=Profile.resolvePerceptualTiming({version:1,enabled:true,calibrationId:'zero-limits',outputs:{trunk:{commandLatencyMs:1,minimumUsefulDurationMs:0,minimumRepeatIntervalMs:0}}});
 assert.equal(resolved.outputs.trunk.minimumUsefulDurationMs,0);
 assert.equal(resolved.outputs.trunk.minimumRepeatIntervalMs,0);
 for(const input of [
  [],
  {version:2,enabled:false},
  {version:1,enabled:false,outputs:{trunk:{commandLatencyMs:1}}},
  {version:1,enabled:true,calibrationId:'x',outputs:{unknown:{commandLatencyMs:1}}},
  {version:1,enabled:true,calibrationId:'x',outputs:{trunk:{commandLatencyMs:-1}}},
  {version:1,enabled:true,calibrationId:'x',outputs:{trunk:{commandLatencyMs:Infinity}}}
 ])assert.throws(()=>Profile.normalizePerceptualCalibration(input),/calibration/i);
});
