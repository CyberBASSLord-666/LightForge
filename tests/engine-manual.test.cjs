'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const E=require('../web/engine/show-engine.js'),P=require('../web/engine/vehicle-profile.js');
const music=(duration=40,silent=true)=>({duration,bpm:120,beatConfidence:1,beats:Array.from({length:duration*2},(_,i)=>i/2),downbeats:Array.from({length:Math.floor(duration/2)},(_,i)=>i*2),waveform:[silent?0:.8],sections:[{start:0,end:duration,energy:silent?0:.8,label:'Test'}]});
const cue=(outputId,start,end,value,id)=>({id:id||`${outputId}-${start}`,outputId,start,end,value});
const sample=(show,ch,time)=>E.stateAt(show,time).raw[ch-1];
function render(cues,settings={},duration=40,silent=true){return E.generate(music(duration,silent),Object.assign({manualCues:cues},settings));}
function decoded(show){const bytes=Buffer.from(E.fseq(show));return {bytes,offset:bytes.readUInt16LE(4),step:bytes[18],frames:bytes.readUInt32LE(14)};}

test('canonical profile covers every exported channel and explicitly excludes uninstalled fogs',()=>{
  assert.equal(E.getCapabilities(),P);assert.equal(P.outputs.length,37);assert.equal(P.outputs.filter(x=>x.available).length,34);
  const channels=P.outputs.flatMap(o=>o.channels);assert.equal(new Set(channels).size,channels.length);
  assert.deepEqual(channels.slice().sort((a,b)=>a-b),[...Array.from({length:30},(_,i)=>i+1),35,36,37,38,39,40,41,46,...Array.from({length:18},(_,i)=>i+176)]);
});

test('every available exterior and RGB output can be independently authored and exported',()=>{
  for(const output of P.outputs.filter(o=>o.available&&o.kind!=='closure')){
    const item=output.mode==='rgb'?{id:output.id,outputId:output.id,start:1,end:2,rgb:[13,89,241]}:cue(output.id,1,2,255);
    const show=render([item]),binary=decoded(show),frame=Math.floor(1.5*1000/binary.step),row=binary.bytes.subarray(binary.offset+frame*200,binary.offset+(frame+1)*200);
    for(let ch=1;ch<=200;ch++){
      const index=output.channels.indexOf(ch),expected=index<0?0:output.mode==='rgb'?item.rgb[index%3]:255;
      assert.equal(row[ch-1],expected,`${output.id}, channel ${ch}`);
    }
    assert.ok(binary.bytes.subarray(binary.bytes.length-200).every(x=>x===0));
  }
});

test('all exterior ramp directions and durations reach preview with exact frame boundaries',()=>{
  for(const stepMs of [15,20])for(const [value,seconds] of [[178,.5],[204,1],[230,2]]){
    const show=render([cue('left-inner',.6,5,value),cue('left-inner',5.1,8,value===178?26:value===204?51:77)],{stepMs});
    assert.equal(E.stateAt(show,.6).lights[2],0);assert.ok(Math.abs(E.stateAt(show,.6+seconds/2).lights[2]-.5)<1e-8);
    assert.equal(sample(show,3,1),value);
  }
});

test('outer beam fades require an explicit verified-hardware option and preserve exact bytes',()=>{
  assert.throws(()=>render([cue('left-outer',1,4,204)]),/not supported/);
  const show=render([cue('left-outer',1,4,204)],{outerBeamRamping:true});assert.equal(sample(show,1,2),204);assert.ok(Math.abs(E.stateAt(show,1.5).lights[0]-.5)<1e-8);
  assert.equal(E.stateAt(show,1.5).lights[1],0);assert.ok(E.validate(show).valid);
  const automatic=render([],{outerBeamRamping:true},40,false);assert.ok(automatic.frames.some((v,i)=>i%200<2&&[26,51,77,178,204,230].includes(v)));
  const normal=render([],{},40,false);assert.ok(normal.frames.every((v,i)=>i%200>=2||v===0||v===255));
});

test('linked physical outputs share manual cues; valid unequal aliases retain physical OR semantics',()=>{
  const show=render([cue('left-combined',1,4,204),cue('park-markers',1,2,255)]);
  for(const ch of [7,9,11])assert.equal(sample(show,ch,2),204);
  for(const ch of [17,18,19,20])assert.equal(sample(show,ch,1.5),255);
  const independent=render([]);for(let f=50;f<100;f++)independent.frames[f*200+8]=255;
  E.invalidatePreview(independent);assert.ok(E.validate(independent).valid);
  for(const ch of [7,9,11])assert.equal(E.stateAt(independent,1.5).lights[ch-1],1);
});

test('manual closures replace only their own automatic track and accept all supported commands',()=>{
  for(const output of P.outputs.filter(o=>o.kind==='closure')){
    const id=output.id,ch=output.channels[0],isMirror=ch<37;
    const cues=isMirror?[cue(id,1,1.02,191),cue(id,2,2.02,255),cue(id,4,4.02,63),cue(id,8,8.02,0)]:[
      cue(id,0,.02,63),cue(id,15,17,127),cue(id,17,17.02,255),cue(id,18,18.02,0),cue(id,20,20.02,191)];
    const show=render(cues,{},80,false),events=show.movements.filter(e=>e.channels.includes(ch));
    assert.equal(events.length,cues.length);assert.ok(events.every(e=>e.manual));assert.ok(show.movements.some(e=>!e.channels.includes(ch)&&!e.manual));
    for(const item of cues)assert.equal(sample(show,ch,item.start),item.value);
    assert.ok(show.validation.valid);
  }
});

test('Stop interrupts a partial travel; Idle preserves the reached position and closing resumes there',()=>{
  const show=render([cue('trunk',1,1.02,63),cue('trunk',8,8.02,255),cue('trunk',10,10.02,0),cue('trunk',12,12.02,191)],{},16);
  assert.equal(E.stateAt(show,8).closureState.trunk.openFraction,.5);assert.equal(E.stateAt(show,11).closureState.trunk.openFraction,.5);
  assert.equal(E.stateAt(show,13).closureState.trunk.openFraction,.25);assert.equal(E.stateAt(show,14).closureState.trunk.openFraction,0);
  assert.equal(show.validation.stats.commandCounts[41],2);
});

test('Idle ends Dance but does not cancel an in-flight one-frame Open/Close request',()=>{
  const show=render([cue('windowFL',1,1.02,63),cue('windowFL',6,8,127),cue('windowFL',8,8.02,0),cue('windowFL',12,12.02,191)]);
  assert.equal(E.stateAt(show,3).closureState.windowFL.motion,'opening');assert.equal(E.stateAt(show,9).closureState.windowFL.moving,false);
  assert.equal(E.stateAt(show,16).closureState.windowFL.openFraction,0);assert.equal(show.validation.stats.commandCounts[37],3);
});

test('per-output switch masks automatic and manual cues, with independent RGB zones and closures',()=>{
  const show=render([cue('left-tail',1,2,255),{id:'rgb',outputId:'rgb-left-front',start:1,end:2,rgb:[255,12,8]},cue('mirrorL',1,1.02,191)],{outputEnabled:{'left-tail':false,'rgb-left-front':false,mirrorL:false}},80,false);
  for(let f=0;f<show.frameCount;f++)for(const ch of [26,188,189,190,35])assert.equal(show.frames[f*200+ch-1],0);
  assert.ok(show.frames.some((v,i)=>i%200===26&&v>0));assert.ok(show.movements.some(e=>e.channels.includes(36)));
});

test('invalid commands, timing, overlaps, unsupported outputs and damaged colors fail before export',()=>{
  const invalid=[
    [cue('left-front-fog',1,2,255),/not available/], [cue('mirrorL',1,2,127),/mirrors/], [cue('brakes',1,2,204),/not supported/],
    [cue('unknown',1,2,255),/unknown/],[cue('left-tail',1,1,255),/end time/],[cue('left-tail',-1,2,255),/end time/],
    [cue('left-tail',1,41,255),/after the music/],[cue('left-tail',1,1.001,255),/one frame/],
    [{outputId:'display',start:1,end:2,rgb:[256,0,0]},/RGB color/]];
  for(const [item,pattern] of invalid)assert.throws(()=>render([item]),pattern);
  assert.throws(()=>render([cue('left-tail',1,3,255),cue('left-tail',2,4,0)]),/overlap/);
  assert.throws(()=>render([cue('left-tail',1,2,255,'same'),cue('right-tail',3,4,255,'same')]),/unique/);
  assert.throws(()=>render([],{outputEnabled:{unknown:true}}),/Unknown/);
});

test('movement budgets, preparation, automatic close and final settled position are enforced',()=>{
  assert.throws(()=>render([cue('trunk',0,10,127)]),/time to open/);
  assert.throws(()=>render([cue('charge',0,1,63),cue('charge',1,2,127),cue('charge',3,3.02,191)]),/time to open/);
  assert.throws(()=>render([cue('windowFL',0,31,127),cue('windowFL',32,32.02,191)]),/30-second/);
  assert.throws(()=>render([cue('trunk',1,1.02,63),cue('trunk',8,8.02,255)]),/finish closed/);
  assert.throws(()=>render([cue('mirrorL',1,1.02,191)]),/finish unfolded/);
  const tooMany=Array.from({length:7},(_,i)=>cue('windowFL',i*5,i*5+.02,i%2?63:191));assert.throws(()=>render(tooMany),/6-command/);
  assert.throws(()=>render([cue('charge',0,.02,63),cue('charge',118,123,127)],{},130),/automatic close/);
});

test('project JSON round-trip preserves all manual cues, switches, colors and exact FSEQ',()=>{
  const settings={manualCues:[cue('left-signature',1,2,230),{id:'color',outputId:'display',start:1,end:4,rgb:[22,98,241]}],outputEnabled:{'right-tail':false},outerBeamRamping:true};
  const first=render(settings.manualCues,settings),copy=E.generate(music(),JSON.parse(JSON.stringify(first.settings)));
  assert.deepEqual(copy.settings,first.settings);assert.deepEqual(E.fseq(copy),E.fseq(first));
});

// Host-native audit fixtures use the same actual generated FSEQ bytes and WAV
// duration. They do not pretend to invoke an Android media codec.
if(process.env.LIGHTFORGE_NATIVE_FIXTURES){
  const out=process.env.LIGHTFORGE_NATIVE_FIXTURES;fs.mkdirSync(out,{recursive:true});
  const cases={
    'stop-and-close':render([cue('trunk',1,1.02,63),cue('trunk',8,8.02,255),cue('trunk',12,12.02,191)],{},16),
    'all-closures':render(P.outputs.filter(o=>o.kind==='closure').flatMap(o=>o.channels[0]<37?[cue(o.id,1,1.02,191),cue(o.id,4,4.02,63)]:[cue(o.id,0,.02,63),cue(o.id,15,17,127),cue(o.id,20,20.02,191)])),
    'all-lamps':render(P.outputs.filter(o=>o.available&&o.kind!=='closure').map(o=>o.mode==='rgb'?{id:o.id,outputId:o.id,start:1,end:2,rgb:[22,98,241]}:cue(o.id,1,2,o.mode==='ramp'?204:255))),
    'outer-ramp':render([cue('left-outer',1,4,204)],{outerBeamRamping:true}),
    'precision-15':render([],{stepMs:15})
  };
  for(const [name,show] of Object.entries(cases)){fs.writeFileSync(path.join(out,name+'.fseq'),E.fseq(show));fs.writeFileSync(path.join(out,name+'.json'),JSON.stringify({duration:show.audioDuration,settings:show.settings}));}
}
