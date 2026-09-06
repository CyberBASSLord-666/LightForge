'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const Engine=require('../web/engine/show-engine.js');
function blank(duration=30,stepMs=20){const frameCount=Math.ceil(duration*1000/stepMs);return {frameCount,stepMs,frames:new Uint8Array(frameCount*200),sections:[{start:0,end:duration,label:'Test'}],settings:{optionalFog:false},duration};}
function paint(show,ch,a,b,value){for(let f=Math.round(a*1000/show.stepMs);f<Math.round(b*1000/show.stepMs);f++)show.frames[f*200+ch-1]=value;}
function near(actual,expected,epsilon=1e-8){assert.ok(Math.abs(actual-expected)<epsilon,`${actual} != ${expected}`);}
function lamp(show,ch,t){return Engine.stateAt(show,t).lights[ch-1];}
function part(show,key,t){return Engine.stateAt(show,t).closureState[key];}

test('all ramp durations begin at zero at the exact frame boundary and advance continuously',()=>{
  for(const stepMs of [15,20])for(const [on,off,seconds] of [[178,26,.5],[204,51,1],[230,77,2]]){
    const show=blank(12,stepMs),start=.6;
    paint(show,3,start,6,on);paint(show,3,6,9,off);
    near(lamp(show,3,start-1e-5),0);near(lamp(show,3,start),0);
    near(lamp(show,3,start+.001),.001/seconds);
    near(lamp(show,3,start+seconds*.5),.5);near(lamp(show,3,start+seconds),1);
    near(lamp(show,3,6),1);near(lamp(show,3,6+seconds/2),.5);near(lamp(show,3,6+seconds),0);
  }
});

test('interrupted and reversed ramps continue from their actual brightness without jumping',()=>{
  const show=blank(8);paint(show,5,1,1.5,230);paint(show,5,1.5,1.6,26);paint(show,5,1.6,3,204);paint(show,5,3,3.2,255);
  near(lamp(show,5,1.5),.25);near(lamp(show,5,1.55),.15);near(lamp(show,5,1.6),.05);
  near(lamp(show,5,1.8),.25);near(lamp(show,5,2.55),1);near(lamp(show,5,3.2),0);
  paint(show,1,.4,1.2,77);Engine.invalidatePreview(show);near(lamp(show,1,.8),0); // projector beam is boolean
});

test('Model 3 merged light outputs obey Channel 4 ramp duration and side/aux OR',()=>{
  const show=blank(9);paint(show,7,1,4,204);paint(show,9,1,4,255);paint(show,11,1,4,255);
  paint(show,7,4,6,51);paint(show,9,4,5,255);paint(show,11,4,5,0);
  for(const ch of [7,9,11]){near(lamp(show,ch,1.5),.5);near(lamp(show,ch,4.5),1);near(lamp(show,ch,5.5),.5);}
  paint(show,20,2,3,255);Engine.invalidatePreview(show);
  for(const ch of [17,18,19,20]){near(lamp(show,ch,2.5),1);near(lamp(show,ch,3),0);}
});

test('physical outputs suppress absent lights and never invent unsupported closures',()=>{
  const show=blank(2);for(const ch of [15,16,29,31,32,33,34,42,43,44,45,47,48])paint(show,ch,0,1,255);
  let state=Engine.stateAt(show,.5);for(const ch of [15,16,29])near(state.lights[ch-1],0);
  assert.deepEqual(state.closures.map(c=>c.channel),[35,36,37,38,39,40,41,46]);
  assert.equal(state.closures.some(c=>/steer|wheel|falcon|frunk|handle/i.test(c.name)),false);
  show.settings.optionalFog=true;Engine.invalidatePreview(show);state=Engine.stateAt(show,.5);near(state.lights[14],0);near(state.lights[15],0);near(state.lights[28],0); // Legacy optionalFog cannot invent absent Highland lamps.
});

test('open/close commands persist through Idle and move from the current partial position',()=>{
  const show=blank(20);paint(show,37,1,1.02,63);paint(show,37,7,7.02,191);
  near(part(show,'windowFL',0).openFraction,0);near(part(show,'windowFL',3).openFraction,.5);
  assert.equal(part(show,'windowFL',3).command,'Idle');assert.equal(part(show,'windowFL',3).motion,'opening');
  near(part(show,'windowFL',5).openFraction,1);near(part(show,'windowFL',9).openFraction,.5);near(part(show,'windowFL',11).openFraction,0);
  paint(show,39,1,1.02,63);paint(show,39,3,3.02,191);Engine.invalidatePreview(show);
  near(part(show,'windowFR',3).openFraction,.5);near(part(show,'windowFR',4).openFraction,.25);near(part(show,'windowFR',5).openFraction,0);
});

test('Stop holds the reached position and later movement resumes without jumping',()=>{
  const show=blank(20);paint(show,41,1,1.02,63);paint(show,41,8,8.02,255);paint(show,41,12,12.02,191);
  near(part(show,'trunk',8).openFraction,.5);near(part(show,'trunk',11).openFraction,.5);
  assert.equal(part(show,'trunk',8).motion,'stopped');assert.equal(part(show,'trunk',11).moving,false);
  near(part(show,'trunk',13).openFraction,.25);near(part(show,'trunk',14).openFraction,0);
});

test('mirrors start unfolded and use real open/close commands, with no invented dance',()=>{
  const show=blank(15);paint(show,35,1,1.02,191);paint(show,35,5,5.02,63);paint(show,36,1,4,127);
  near(part(show,'mirrorL',0).openFraction,1);near(part(show,'mirrorL',2).foldedFraction,.5);near(part(show,'mirrorL',3).foldedFraction,1);
  near(part(show,'mirrorL',6).foldedFraction,.5);near(part(show,'mirrorL',7).foldedFraction,0);
  assert.equal(part(show,'mirrorR',2).dancing,false);near(part(show,'mirrorR',2).openFraction,1);
});

test('estimated Dance moves, stops at Idle, and seeks reproduce identical poses',()=>{
  const show=blank(40);paint(show,37,1,12,127);paint(show,41,0,14,63);paint(show,41,15,25,127);
  const poses=[2,3,4,5,6,7,8,9,10,11].map(t=>part(show,'windowFL',t).openFraction);
  assert.ok(new Set(poses.map(v=>v.toFixed(4))).size>6);assert.ok(poses.every(v=>v>=0&&v<=1));
  assert.equal(part(show,'windowFL',6).motion,'dancing');assert.equal(part(show,'windowFL',6).estimated,true);
  const stopped=part(show,'windowFL',12).openFraction;near(part(show,'windowFL',19).openFraction,stopped);
  assert.equal(part(show,'windowFL',12).dancing,false);assert.equal(part(show,'windowFL',12).moving,false);
  assert.notEqual(part(show,'trunk',16).openFraction,part(show,'trunk',18).openFraction);
  const times=[0,1,2.431,5.124,11.99,12,17.64,25.1,30],forward=times.map(t=>Engine.stateAt(show,t));
  for(let i=times.length-1;i>=0;i--)assert.deepEqual(Engine.stateAt(show,times[i]),forward[i]);
  Engine.invalidatePreview(show);for(let i=0;i<times.length;i++)assert.deepEqual(Engine.stateAt(show,times[i]),forward[i]);
});

test('charge Dance is an LED rainbow, never door oscillation, and auto-close occurs at two minutes',()=>{
  const show=blank(140);paint(show,46,1,1.02,63);paint(show,46,4,130,127);
  const a=part(show,'charge',5),b=part(show,'charge',6);near(a.openFraction,1);near(b.openFraction,1);
  assert.equal(a.rainbow,true);assert.equal(a.moving,false);assert.notDeepEqual(a.rainbowColor,b.rainbowColor);
  near(part(show,'charge',122).openFraction,.5);assert.equal(part(show,'charge',122).rainbow,false);assert.equal(part(show,'charge',122).automatic,true);
  near(part(show,'charge',123).openFraction,0);
  const invalid=blank(10);paint(invalid,46,0,8,127);assert.equal(part(invalid,'charge',4).rainbow,false);near(part(invalid,'charge',4).openFraction,0);
});

test('preview raw commands and all RGB zones exactly match independently decoded exported bytes',()=>{
  const fixture=JSON.parse(fs.readFileSync(require('node:path').join(__dirname,'engine-glass-castle.json'),'utf8'));
  const show=Engine.generate(fixture,{stepMs:15});
  // Deliberately poison preview-unrelated event metadata: exported bytes are authoritative.
  show.movements=[{start:0,end:99999,channels:[41],value:127}];
  const binary=Buffer.from(Engine.fseq(show)),offset=binary.readUInt16LE(4),count=binary.readUInt32LE(14),step=binary[18];
  for(let i=0;i<101;i++){
    const time=(count-1)*step/1000*i/100+.003,frame=Math.min(count-1,Math.floor(time*1000/step));
    const data=binary.subarray(offset+frame*200,offset+(frame+1)*200),state=Engine.stateAt(show,time);
    assert.deepEqual(Buffer.from(state.raw),data);assert.equal(state.frame,frame);
    [176,179,182,185,188,191].forEach((channel,index)=>assert.deepEqual(state.interior[index],Array.from(data.subarray(channel-1,channel+2))));
    for(const closure of state.closures)assert.equal(closure.rawCommand,data[closure.channel-1]);
  }
});
