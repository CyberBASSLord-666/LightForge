'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const Planner=require('../web/engine/movement-planner.js'),Engine=require('../web/engine/show-engine.js'),Profile=require('../web/engine/vehicle-profile.js');
const root=path.resolve(__dirname,'..'),checks=[],errors=[],fixtures=[];
function test(name,fn){try{fn();checks.push({name,passed:true});process.stdout.write('PASS '+name+'\n');}catch(error){checks.push({name,passed:false,error:error.message});errors.push(name+': '+error.message);process.stderr.write('FAIL '+name+' '+error.stack+'\n');}}
function song(duration=180){
  const beats=[];for(let t=0;t<duration;t+=.5)beats.push(t);
  const sections=[{start:0,end:32,energy:.15},{start:32,end:56,energy:.95},{start:56,end:96,energy:.18},{start:96,end:124,energy:.87},{start:124,end:160,energy:.2},{start:160,end:duration,energy:.76}].filter(s=>s.start<duration).map((s,i)=>({...s,end:Math.min(duration,s.end),index:i}));
  return {duration,bpm:120,meter:4,beatConfidence:.97,beats,downbeats:beats.filter((_,i)=>i%4===0),sections,phrases:sections.filter(s=>s.energy>.5).map((s,i)=>({...s,kind:i?'chorus':'drop',confidence:.97})),activityRanges:[{start:0,end:duration}]};
}
function render(music,settings={}){
  const s={stepMs:20,dance:'expressive',...settings},plan=Planner.plan(music,s,Profile),frameCount=Math.ceil(music.duration*1000/s.stepMs-1e-9),frames=new Uint8Array(frameCount*200);
  for(const e of plan.events)for(let f=Math.round(e.start*1000/s.stepMs);f<Math.round(e.end*1000/s.stepMs);f++)for(const ch of e.channels)frames[f*200+ch-1]=e.value;
  frames.fill(0,(frameCount-1)*200);
  const show={frames,channels:200,channelCount:200,frameCount,stepMs:s.stepMs,duration:frameCount*s.stepMs/1000,audioDuration:music.duration,settings:s,sections:music.sections||[],movements:plan.events};
  return {plan,show,validation:Engine.validate(show,music)};
}
function valid(music,settings={}){
  const built=render(music,settings);assert.equal(built.validation.valid,true,built.validation.errors.join('; '));
  for(const [id,count]of Object.entries(built.plan.diagnostics.commandCounts)){assert.ok(count<=Planner.specifications[id].limit,id+' command budget');assert.ok(built.plan.diagnostics.danceSeconds[id]<=30,id+' Dance budget');}
  for(const e of built.plan.events){assert.ok(e.start>=0&&e.end>e.start&&e.end<music.duration);assert.ok(Math.abs(e.start*1000/built.show.stepMs-Math.round(e.start*1000/built.show.stepMs))<1e-6,'quantized onset');}
  return built;
}
test('strongest musical arrivals replace percent-of-duration selection',()=>{
  const {plan}=valid(song());
  assert.deepEqual(plan.targets.filter(t=>t.outputId==='trunk').map(t=>t.musicTime),[32,96]);
  assert.deepEqual(plan.targets.filter(t=>t.outputId==='windowFL').map(t=>t.musicTime),[32,96,160]);
  fixtures.push({name:'known-drops',targets:plan.targets,diagnostics:plan.diagnostics});
});
test('14-second trunk and four-second windows prepare before exact Dance onset',()=>{
  const {plan,show}=valid(song());
  for(const dance of plan.events.filter(e=>e.command==='Dance'&&[41,46].includes(e.channels[0]))){
    const opening=plan.events.filter(e=>e.outputId===dance.outputId&&e.command==='Open'&&e.start<dance.start).pop();
    assert.ok(dance.start-opening.start>=Planner.specifications[dance.outputId].travel+.29);
    const state=Engine.stateAt(show,dance.start).closureState[dance.outputId];assert.equal(state.dancing,true);assert.equal(state.estimatedPosition,1);
  }
  for(const id of ['windowFL','windowFR','windowRL','windowRR']){const track=plan.events.filter(e=>e.outputId===id),first=track.find(e=>e.command==='Dance');assert.ok(first.start-track[0].start>=4.29);}
});
test('final windows close and mirrors unfold with completed home travel',()=>{
  const {show}=valid(song());for(const state of Engine.stateAt(show,show.duration-.04).closures){assert.equal(state.moving,false,state.key);assert.equal(state.estimatedPosition,state.channel<37?1:0,state.key);}
});
test('mirror cycles reserve physical travel, begin folded, and never request Dance',()=>{
  const {plan}=valid(song());for(const id of ['mirrorL','mirrorR']){const track=plan.events.filter(e=>e.outputId===id);assert.equal(track[0].command,'Close');for(let i=0;i<track.length;i++){assert.equal(track[i].command,i%2?'Open':'Close');assert.ok(track[i].end-track[i].start>=2.29);if(i)assert.ok(track[i].start-track[i-1].start>=2.79);}}
});
test('expressive choreography is denser and spatially staggered; balanced remains restrained',()=>{
  const music=song(),a=valid(music).plan,b=valid(music,{dance:'balanced'}).plan;
  assert.ok(a.events.length>b.events.length);assert.ok(a.diagnostics.danceSeconds.windowFL>b.diagnostics.danceSeconds.windowFL);
  const ensemble=a.targets.filter(t=>t.outputId.startsWith('window')&&t.source==='drop');assert.equal(new Set(ensemble.map(t=>t.time)).size,1);
  const response=a.targets.filter(t=>t.outputId.startsWith('window')&&t.musicTime>=96&&t.musicTime<100);assert.equal(new Set(response.map(t=>t.time)).size,4);
});
test('positive and negative audio offsets apply once at musical arrivals',()=>{
  for(const offsetMs of [-1400,780]){const {plan}=valid(song(),{offsetMs});for(const t of plan.targets)assert.ok(Math.abs(t.time-t.musicTime-offsetMs/1000)<=.0100001);const first=plan.targets.find(t=>t.outputId==='trunk');assert.ok(Math.abs(first.time-(32+offsetMs/1000))<1e-8);}
});
test('manual tracks, disabled outputs and global movement switches are respected',()=>{
  const muted=valid(song(),{manualCues:[{id:'custom',outputId:'windowFL',start:1,end:2,value:63}],outputEnabled:{trunk:false},enabled:{mirrors:false}}).plan;
  assert.ok(!muted.events.some(e=>['windowFL','trunk','mirrorL','mirrorR'].includes(e.outputId)));assert.ok(muted.events.some(e=>e.outputId==='windowFR'));
  assert.equal(Planner.plan(song(),{dance:'off'},Profile).events.length,0);assert.equal(Planner.plan({...song(),silent:true},{},Profile).events.length,0);
});
test('actual tempo changes determine stagger and all offsets retain frame precision',()=>{
  const m=song(160);m.beats=[];for(let t=0;t<80;t+=.6)m.beats.push(Number(t.toFixed(8)));for(let t=80;t<160;t+=.4)m.beats.push(Number(t.toFixed(8)));m.downbeats=m.beats.filter((_,i)=>i%4===0);m.phrases=[{start:30,end:48,energy:.95,kind:'drop',confidence:.97},{start:100,end:122,energy:.85,kind:'chorus',confidence:.97}];m.sections=[{start:0,end:30,energy:.2},{start:30,end:48,energy:.95},{start:48,end:100,energy:.2},{start:100,end:122,energy:.85},{start:122,end:160,energy:.2}];
  for(const stepMs of [15,20]){const {plan}=valid(m,{stepMs,offsetMs:315});const response=plan.targets.filter(t=>t.outputId.startsWith('window')&&t.musicTime>=100&&t.musicTime<103);assert.equal(response.length,4);for(const target of response)assert.ok(Math.min(...m.beats.map(b=>Math.abs(b-target.musicTime)))<1e-6);assert.ok(Math.abs(response[1].musicTime-response[0].musicTime-.4)<1e-6);}
});
test('Dance ends before actual musical stops; unsupported short phrases do not consume budgets',()=>{
  const m=song(150);m.activityRanges=[{start:12,end:22},{start:40,end:48},{start:72,end:75},{start:96,end:119}];m.phrases=m.activityRanges.map((r,i)=>({...r,energy:.8,confidence:.9,kind:'drop'}));m.sections=[{start:0,end:150,energy:.8}];
  const {plan}=valid(m);for(const event of plan.events.filter(e=>e.command==='Dance')){const range=m.activityRanges.find(r=>event.start>=r.start&&event.start<r.end);assert.ok(range,'Dance starts in active music');assert.ok(event.end<=range.end,'Dance ends before silence');assert.ok(event.start<72||event.start>=75,'three-second phrase cannot fit meaningful dance');}
});
test('long-track budgets focus on strongest remote peaks rather than evenly distributed gestures',()=>{
  const duration=7200,m=song(duration);m.sections=[{start:0,end:1832,energy:.12},{start:1832,end:1856,energy:.97},{start:1856,end:5300,energy:.12},{start:5300,end:5324,energy:.99},{start:5324,end:duration,energy:.12}];m.phrases=m.sections.filter(s=>s.energy>.5).map(s=>({...s,kind:'drop',confidence:.98}));
  // Planner only: allocating a two-hour frame array is not needed to verify
  // target selection, bounded command budgets and event scheduling.
  const plan=Planner.plan(m,{stepMs:20,dance:'expressive'},Profile);assert.deepEqual(plan.targets.filter(t=>t.outputId==='trunk').map(t=>t.musicTime),[1832,5300]);for(const [id,count]of Object.entries(plan.diagnostics.commandCounts)){assert.ok(count<=Planner.specifications[id].limit);assert.ok(plan.diagnostics.danceSeconds[id]<=30);}
  fixtures.push({name:'two-hour-track',targets:plan.targets.filter(t=>t.outputId==='trunk'),diagnostics:plan.diagnostics});
});
test('short tracks, sparse beats and phase-shifted boundaries retain legal complete choreography',()=>{
  for(const duration of [2,6,10,14.8,19.7,22.3,31.1,39.07,61.125,83.713,121.3])for(const stepMs of [15,20])for(const dance of ['balanced','expressive']){
    const m=song(duration);m.sections=[{start:0,end:duration,energy:.8}];m.phrases=[{start:duration*.40,end:duration*.8,energy:.8,kind:'peak',confidence:.7}];valid(m,{stepMs,dance,offsetMs:stepMs===15?-915:635});
  }
});
test('seeded adversarial phrase timing remains validated by the real exported-byte simulator',()=>{
  let seed=43179;const rnd=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};
  for(let i=0;i<35;i++){
    const d=20+rnd()*240,m=song(d);m.bpm=60+rnd()*160;const beat=60/m.bpm;m.beats=[];for(let t=rnd()*beat;t<d;t+=beat)m.beats.push(t);m.downbeats=m.beats.filter((_,j)=>j%4===0);m.sections=[{start:0,end:d,energy:.7}];m.phrases=[];for(let t=10;t<d;t+=8+rnd()*24)m.phrases.push({start:t,end:Math.min(d,t+4+rnd()*20),kind:rnd()>.5?'drop':'phrase',confidence:rnd(),energy:.3+rnd()*.7});valid(m,{dance:i%2?'balanced':'expressive',stepMs:i%3?20:15,offsetMs:Math.round((rnd()-.5)*4000)});
  }
});
test('integrated show generation preserves analysis targets, offset and exact exported movement bytes',()=>{
  const music=song(),settings={stepMs:15,dance:'expressive',offsetMs:315},show=Engine.generate(music,settings),direct=Planner.plan(music,settings,Profile);
  assert.equal(Engine.validate(show,music).valid,true);assert.deepEqual(show.choreography.targets,direct.targets);
  const fseq=Buffer.from(Engine.fseq(show)),offset=fseq.readUInt16LE(4);
  for(const e of direct.events){const frame=Math.round(e.start*1000/settings.stepMs);for(const ch of e.channels)assert.equal(fseq[offset+frame*200+ch-1],e.value,e.outputId+' exported onset');}
  for(const t of show.choreography.targets.filter(t=>t.kind==='dance'))assert.ok(Math.abs(t.time-t.musicTime-.315)<=.0075001);
});
test('explicit vehicle timing calibration preserves the default FSEQ and only adds conservative command lead',()=>{
  const base={stepMs:20,dance:'expressive',offsetMs:0},music=song();
  const normal=Engine.generate(music,base);
  const disabled=Engine.generate(music,{...base,vehicleTimingCalibration:{enabled:false}});
  assert.deepEqual(disabled.frames,normal.frames,'disabled calibration must not alter FSEQ bytes');
  assert.deepEqual(Engine.fseq(disabled),Engine.fseq(normal),'header and payload stay deterministic without a nonzero calibration');
  assert.equal(Profile.perceptualTiming.status,'unconfigured-until-explicit-calibration');
  assert.equal(Profile.resolvePerceptualTiming().outputs.mirrorL.calibrationConfigured,false);
  assert.throws(()=>Engine.generate(music,{...base,vehicleTimingCalibration:{enabled:true,calibrationId:'rig',outputs:{mirrorL:{commandLatencyMs:0}}}}),/explicit non-zero/);
  assert.throws(()=>Engine.generate(music,{...base,vehicleTimingCalibration:{enabled:true,calibrationId:'rig',outputs:{mirrorL:{openTravelMs:100}}}}),/between 2000 and 60000/);
  assert.throws(()=>Engine.generate(music,{...base,vehicleTimingCalibration:{enabled:true,calibrationId:'rig',outputs:{unknown:{commandLatencyMs:1}}}}),/unknown output/);
  const calibration={version:1,enabled:true,calibrationId:'local-rig-01',outputs:{
    mirrorL:{commandLatencyMs:150},
    windowFL:{activationLatencyMs:100,openTravelMs:4200,closeTravelMs:4100}
  }};
  const calibrated=Engine.generate(music,{...base,vehicleTimingCalibration:calibration});
  assert.equal(calibrated.validation.valid,true,calibrated.validation.errors.join('; '));
  const normalMirror=normal.movements.find(e=>e.outputId==='mirrorL'&&e.command==='Open');
  const calibratedMirror=calibrated.movements.find(e=>e.outputId==='mirrorL'&&e.command==='Open');
  assert.ok(calibratedMirror.start<normalMirror.start,'explicit positive calibration may only lead the command');
  assert.equal(calibratedMirror.intent.targetTime,normalMirror.intent.targetTime,'desired perceptual target remains on the music clock');
  assert.equal(calibratedMirror.intent.perceptualTiming.calibrationId,'local-rig-01');
  const normalWindow=normal.movements.find(e=>e.outputId==='windowFL'&&e.command==='Open');
  const calibratedWindow=calibrated.movements.find(e=>e.outputId==='windowFL'&&e.command==='Open');
  assert.ok(calibratedWindow.start<normalWindow.start,'longer explicit travel is scheduled earlier');
  assert.ok(calibrated.choreography.movement.perceptualTiming.outputs.windowFL.leadAdjusted);
  assert.equal(calibrated.choreography.targets.find(t=>t.outputId==='mirrorL').time,normal.choreography.targets.find(t=>t.outputId==='mirrorL').time);
});
const files=['web/engine/movement-planner.js','web/engine/show-engine.js','web/engine/vehicle-profile.js'];
const receipt={release:Engine.version,passed:errors.length===0,errors,checkedAt:new Date().toISOString(),checks,fixtures,source_hashes:Object.fromEntries(files.map(f=>[f,crypto.createHash('sha256').update(fs.readFileSync(path.join(root,f))).digest('hex')])),limitations:['Motor travel is estimated from Tesla documented approximate durations. No physical car or Android device was used.','Dance oscillation cadence and endpoints are controlled by the car; only command start/end and prepared arrivals are scheduled.'],source:'https://github.com/teslamotors/light-show#closures-channels'};
fs.mkdirSync(path.join(root,'qa/release-'+Engine.version),{recursive:true});fs.writeFileSync(path.join(root,'qa/release-'+Engine.version,'movement-verification.json'),JSON.stringify(receipt,null,2)+'\n');if(errors.length)process.exitCode=1;
