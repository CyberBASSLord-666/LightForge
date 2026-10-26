'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const E=require('../web/engine/show-engine.js');
function blank(outputs,stepMs=20,duration=40){const frameCount=Math.ceil(duration*1000/stepMs);return {channels:200,channelCount:200,frameCount,stepMs,frames:new Uint8Array(frameCount*200),duration:frameCount*stepMs/1000,settings:outputs?{vehicleTimingCalibration:{version:1,enabled:true,calibrationId:'synthetic-response-fixture',outputs}}:{}};}
function paint(s,ch,a,b,v){for(let f=Math.round(a*1000/s.stepMs);f<Math.round(b*1000/s.stepMs);f++)s.frames[f*200+ch-1]=v;}
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-8,`${a} != ${b}`);
const part=(s,id,t)=>E.stateAt(s,t).closureState[id];

test('synthetic calibrated travel and response delay affect preview, never exported command clock',()=>{
 for(const step of [15,20]){
  const s=blank({trunk:{openTravelMs:20000,closeTravelMs:8000,commandLatencyMs:200,activationLatencyMs:100}},step);
  paint(s,41,0,.3,63);paint(s,41,24,24.3,191);
  const original=s.frames.slice();
  near(part(s,'trunk',.2).openFraction,0);near(part(s,'trunk',.3).openFraction,0);
  near(part(s,'trunk',10.3).openFraction,.5);near(part(s,'trunk',20.3).openFraction,1);
  near(part(s,'trunk',28.2).openFraction,.5);near(part(s,'trunk',32.2).openFraction,0);
  assert.equal(E.frameAt(s,0)[40],63);assert.deepEqual(s.frames,original);
  assert.equal(E.validate(s).valid,true);
 }
});

test('validator rejects Dance before configured trunk opening completes',()=>{
 const s=blank({trunk:{openTravelMs:20000,closeTravelMs:8000,commandLatencyMs:200}});
 paint(s,41,0,1,63);paint(s,41,15,16,127);paint(s,41,25,26,191);
 assert.ok(part(s,'trunk',14).openFraction<1);
 assert.equal(part(s,'trunk',15).dancing,false);
 assert.ok(E.validate(s).errors.includes('Trunk dance starts before the trunk has time to open.'));
});

test('validator rejects a return that satisfies default travel but not configured travel',()=>{
 const s=blank({trunk:{closeTravelMs:8000}},20,30);
 paint(s,41,0,1,63);paint(s,41,25,26,191);
 assert.ok(E.validate(s).errors.some(e=>e.includes('must finish closed')));
 near(part(s,'trunk',29).openFraction,.5);
});

test('calibrated Stop and reversal retain actual position during response delay',()=>{
 const s=blank({windowFL:{openTravelMs:8000,closeTravelMs:6000,commandLatencyMs:200,activationLatencyMs:100,deactivationLatencyMs:300}});
 paint(s,37,0,.1,63);paint(s,37,4,4.1,255);paint(s,37,6,6.1,191);
 near(part(s,'windowFL',4.1).openFraction,3.8/8);
 near(part(s,'windowFL',5).openFraction,3.9/8);
 near(part(s,'windowFL',6.4).openFraction,3.9/8);
 near(part(s,'windowFL',7.5).openFraction,3.9/8-1/6);
});

test('calibrated charge-port auto-close follows estimated opening response and slow return',()=>{
 const s=blank({charge:{openTravelMs:4000,closeTravelMs:4000,commandLatencyMs:200,activationLatencyMs:100}},20,140);
 paint(s,46,0,.1,63);
 near(part(s,'charge',120.3).openFraction,1);near(part(s,'charge',122.3).openFraction,.5);near(part(s,'charge',124.3).openFraction,0);
 assert.equal(part(s,'charge',122.3).automatic,true);
});

test('calibrated trajectory is stable under reverse seeks and persisted preview restoration',()=>{
 const s=blank({mirrorL:{openTravelMs:4000,closeTravelMs:4000,commandLatencyMs:100}});
 paint(s,35,1,1.1,191);paint(s,35,8,8.1,63);
 const times=[0,1,1.05,2,4,8,10,15],states=times.map(t=>E.stateAt(s,t));
 for(let i=times.length-1;i>=0;i--)assert.deepEqual(E.stateAt(s,times[i]),states[i]);
 const restored=structuredClone(s);
 for(let i=0;i<times.length;i++)assert.deepEqual(E.stateAt(restored,times[i]),states[i]);
});

test('old trajectory cache is rebuilt for the calibrated model',()=>{
 const s=blank({trunk:{openTravelMs:20000}});paint(s,41,0,1,63);
 s.previewIndex={version:E.version,frameCount:s.frameCount,stepMs:s.stepMs,lights:[],closures:[]};
 near(part(s,'trunk',10).openFraction,.5);assert.equal(s.previewIndex.trajectorySchema,2);
});

test('calibrated Dance/Idle response does not prematurely switch movement or charge colors',()=>{
 for(const [id,ch]of[['windowFL',37],['charge',46]]){
  const s=blank({[id]:{commandLatencyMs:200}});
  paint(s,ch,0,.1,63);paint(s,ch,10,12,127);
  assert.equal(part(s,id,10.1).dancing,false);
  assert.equal(part(s,id,10.3).dancing,true);
  assert.equal(part(s,id,12.1).dancing,true);
  assert.equal(part(s,id,12.3).dancing,false);
  if(ch===46){assert.equal(part(s,id,10.1).rainbow,false);assert.equal(part(s,id,12.1).rainbow,true);}
 }
});

test('ignored premature Dance cannot cancel an Open whose response is pending',()=>{
 const s=blank({trunk:{activationLatencyMs:1000,openTravelMs:20000}});
 paint(s,41,0,.1,63);paint(s,41,.2,.3,127);
 assert.equal(part(s,'trunk',.2).dancing,false);
 near(part(s,'trunk',11).openFraction,.5);
});

test('default response flags share command seek floating-point tolerance',()=>{
 const s=blank(null,20,65);paint(s,41,0,1,63);paint(s,41,57.78,58,127);
 assert.equal(part(s,'trunk',57.78-1e-13).command,'Dance');
 assert.equal(part(s,'trunk',57.78-1e-13).dancing,true);
});
