'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Engine = require('../web/engine/show-engine.js');

function music(duration=238.0399773243,bpm=120,energy=.8){
  const beats=[];for(let t=.12;t<duration;t+=60/bpm)beats.push(t);
  return {duration,bpm,beatConfidence:.92,beats,downbeats:beats.filter((_,i)=>i%4===0),
    onsets:beats.map((time,i)=>({time:time+(i%3-1)*.018,strength:.7+(i%3)*.1,band:i%2?'mid':'bass'})),
    sections:[{start:0,end:duration*.12,energy:.2,label:'Opening'},{start:duration*.12,end:duration*.42,energy:energy*.75,label:'Verse'},
      {start:duration*.42,end:duration*.63,energy,label:'Peak'},{start:duration*.63,end:duration*.76,energy:.25,label:'Break'},
      {start:duration*.76,end:duration,energy:Math.min(1,energy*1.1),label:'Finale'}],waveform:Array.from({length:300},(_,i)=>.35+.4*Math.sin(i*.19)**2)};
}

// This decoder deliberately ignores the engine's validation, event metadata and
// generated statistics. It reads the binary export as a separate consumer.
function decode(bytes){
  const b=Buffer.from(bytes);assert.equal(b.subarray(0,4).toString(),'PSEQ');assert.equal(b[7],2);assert.equal(b[6],0);
  const offset=b.readUInt16LE(4),fixed=b.readUInt16LE(8),channels=b.readUInt32LE(10),count=b.readUInt32LE(14),step=b[18];
  assert.equal(fixed,32);assert.equal(channels,200);assert.equal(b[20],0);assert.ok([15,20].includes(step));
  assert.equal(b.length,offset+channels*count);assert.ok(offset%4===0);
  const fields={};let p=fixed;while(p+4<=offset){const length=b.readUInt16LE(p);if(length===0)break;assert.ok(length>=4&&p+length<=offset);fields[b.subarray(p+2,p+4).toString()]=b.subarray(p+4,p+length).toString().replace(/\0$/,'');p+=length;}
  return {channels,count,step,offset,fields,data:b.subarray(offset)};
}
function closureRuns(decoded,channel){
  const events=[];let i=0;
  while(i<decoded.count){let j=i+1;const value=decoded.data[i*200+channel-1];while(j<decoded.count&&decoded.data[j*200+channel-1]===value)j++;if(value)events.push({value,start:i*decoded.step/1000,end:j*decoded.step/1000});i=j;}
  return events;
}

test('FSEQ binary header, variable metadata, payload and duration agree with audio',()=>{
  for(const stepMs of [15,20]){
    const m=music(),show=Engine.generate(m,{stepMs}),decoded=decode(Engine.fseq(show));
    assert.equal(decoded.fields.mf,'lightshow.wav');assert.equal(decoded.count,Math.ceil(m.duration*1000/stepMs));
    assert.deepEqual(new Uint8Array(decoded.data),show.frames);assert.ok(decoded.count*stepMs/1000>=m.duration);
    assert.ok(decoded.count*stepMs/1000-m.duration<stepMs/1000+1e-9);
    assert.ok(decoded.data.subarray(decoded.data.length-200).every(v=>v===0));
  }
});

test('FSEQ frame-step contract is shared by validation and serialization',()=>{
  for(const stepMs of [15,20]){
    const show=Engine.generate(music(2),{stepMs,dance:'off'});
    assert.equal(Engine.validate(show,music(2)).valid,true,'valid '+stepMs+' ms show');
    assert.equal(Engine.fseqHeader(show)[18],stepMs,'valid '+stepMs+' ms header');
    assert.equal(Engine.fseq(show)[18],stepMs,'valid '+stepMs+' ms sequence');
  }
  const valid=Engine.generate(music(2),{stepMs:20,dance:'off'});
  for(const stepMs of [14,16,19,21,25,100]){
    assert.throws(()=>Engine.generate(music(2),{stepMs}),/20 ms recommended frame interval or 15 ms precision mode/);
    const corrupt={...valid,stepMs},report=Engine.validate(corrupt);
    assert.equal(report.valid,false,'reject '+stepMs+' ms during validation');
    assert.ok(report.errors.includes('Frame interval must be 20 ms recommended or 15 ms precision.'),report.errors.join('; '));
    assert.throws(()=>Engine.fseqHeader(corrupt),/Frame interval must be 20 ms recommended or 15 ms precision/);
    assert.throws(()=>Engine.fseq(corrupt),/Frame interval must be 20 ms recommended or 15 ms precision/);
  }
});

test('broad tempo and duration matrix retains physical closure timing and budgets',()=>{
  for(const duration of [1,14,15,20,39,43,60,90,238.03998,600])for(const bpm of [40,75,93,120,180,240])for(const stepMs of [15,20]){
    const show=Engine.generate(music(duration,bpm),{stepMs,offsetMs:duration===90?1850:-90});
    const decoded=decode(Engine.fseq(show));
    for(const channel of [35,36,37,38,39,40,41,46]){
      const events=closureRuns(decoded,channel),limit=channel<37?20:channel===46?3:6;
      assert.ok(events.filter(e=>[63,127,191].includes(e.value)).length<=limit,`${duration}s ${bpm}bpm ch${channel} count`);
      assert.ok(events.filter(e=>e.value===127).reduce((sum,e)=>sum+e.end-e.start,0)<=30.001);
      let open=null,available=-Infinity;
      for(const e of events){
        assert.ok(e.start>=available-.001,`${duration}s ${bpm}bpm ch${channel}: physical overlap`);
        if(e.value===63){open=e.start;available=e.start+(channel===41?14:channel>=37&&channel<=40?4:2);}
        else if(e.value===191){open=null;available=e.start+(channel>=37&&channel<=41?4:2);}
        else if(e.value===127){
          assert.ok(channel>=37);if(channel===41||channel===46)assert.ok(open!==null&&e.start-open>=(channel===41?14:2)-.001);
          if(channel===46)assert.ok(e.end-open<=120);
          available=e.end;
        }
      }
      if(events.length){assert.equal(events.at(-1).value,channel<37?63:191);assert.ok(available<decoded.count*decoded.step/1000);}
    }
  }
});

test('expressive choreography places visible gestures at musical beats within per-closure budgets',()=>{
  const m=music(238,120),show=Engine.generate(m,{dance:'expressive'}),decoded=decode(Engine.fseq(show));
  const musicalTargets=m.beats.concat(m.sections.map(s=>s.start));const nearestTarget=t=>Math.min(...musicalTargets.map(b=>Math.abs(b-t)));
  for(const c of [37,38,39,40,41]){
    const events=closureRuns(decoded,c),dances=events.filter(e=>e.value===127);
    assert.ok(dances.length>=1,`Supported closure ${c} has a visible musical gesture`);
    assert.ok(events.filter(e=>[63,127,191].includes(e.value)).length<=6);
    assert.ok(dances.reduce((total,e)=>total+e.end-e.start,0)<=30.001);
    for(const e of dances){assert.ok(e.end-e.start>=4,`ch${c} leaves visible movement time`);assert.ok(nearestTarget(e.start)<=decoded.step/2000+.000001,`ch${c} starts at a supplied beat or structural arrival`);}
  }
  for(const c of [35,36]){
    const events=closureRuns(decoded,c);
    assert.ok(events.some(e=>e.value===191)&&events.some(e=>e.value===63));
    assert.ok(events.length<=20);assert.ok(events.every(e=>e.value!==127));
    assert.equal(events.at(-1).value,63);
  }
  const highSections=m.sections.filter(s=>s.energy>=.75);
  assert.ok(show.movements.filter(e=>e.value===127).some(e=>highSections.some(s=>e.start>=s.start&&e.start<s.end)),'At least one ensemble uses a high-energy passage');
  assert.ok(show.stats.activeExteriorPercent>20&&show.stats.activeExteriorPercent<95);
});

test('shared physical outputs and unsupported channels are correct in every binary frame',()=>{
  const show=Engine.generate(music(125,111),{}),allowed=new Set([...Array.from({length:30},(_,i)=>i+1),35,36,37,38,39,40,41,46,...Array.from({length:18},(_,i)=>176+i)]);
  for(let f=0;f<show.frameCount;f++){
    for(const group of [[7,9,11],[8,10,12],[17,18,19,20]])assert.ok(group.every(c=>show.frames[f*200+c-1]===show.frames[f*200+group[0]-1]));
    for(let c=1;c<=200;c++)if(!allowed.has(c)||[15,16,29].includes(c))assert.equal(show.frames[f*200+c-1],0);
  }
});

test('all supported fade durations are real Tesla commands, and preview evaluates their brightness',()=>{
  const seen=new Set();
  for(const bpm of [40,90,150]){
    const m=music(30,bpm);m.sections=[{start:0,end:30,energy:.1,label:'Quiet'}];m.waveform=[.1];
    const show=Engine.generate(m,{dance:'off',style:'cinematic'});
    for(let f=0;f<show.frameCount;f++)seen.add(show.frames[f*200+4]);
    const first=m.beats[0],before=Engine.stateAt(show,first-.05),during=Engine.stateAt(show,first+.2);
    assert.ok(during.lights[4]>before.lights[4]&&during.lights[4]<1);
    assert.ok(Engine.stateAt(show,show.duration).lights.every(x=>x===0));
  }
  for(const code of [26,51,77,178,204,230])assert.ok(seen.has(code),`Ramp code ${code} must occur`);
});

test('RGB segments and display are independently addressable and optional',()=>{
  const show=Engine.generate(music(30),{});const seen=new Set();
  for(let f=0;f<show.frameCount;f++)seen.add(Array.from(show.frames.subarray(f*200+175,f*200+193)).join(','));
  assert.ok(seen.size>200);const off=Engine.generate(music(30),{enabled:{interior:false}});
  for(let f=0;f<off.frameCount;f++)assert.ok(off.frames.subarray(f*200+175,f*200+193).every(v=>v===0));
});

test('disabled closures are absent, including in an expressive show',()=>{
  const show=Engine.generate(music(120),{enabled:{windows:false,mirrors:false,trunk:false,charge:false}});
  assert.equal(show.movements.length,0);
  const off=Engine.generate(music(120),{dance:'off'});assert.equal(off.movements.length,0);
});

test('timing offset moves musical light and closure entrances while preserving preparation',()=>{
  const m=music(238,93),a=Engine.generate(m,{offsetMs:0}),b=Engine.generate(m,{offsetMs:100});
  const af=a.movements.find(e=>e.value===127),bf=b.movements.find(e=>e.value===127);
  assert.ok(Math.abs((bf.start-af.start)-.1)<.021);
  assert.ok(b.validation.valid);
});

test('quiet input is intentionally dark; malformed and overlong tracks are rejected',()=>{
  const m=music(30);m.waveform=[0,0,0];const show=Engine.generate(m,{});
  assert.ok(show.frames.every(v=>v===0));assert.equal(show.movements.length,0);assert.ok(show.validation.warnings.some(w=>w.includes('silent')));
  for(const duration of [0,-1,NaN,Infinity,14400.001])assert.throws(()=>Engine.generate({duration},{}));
  assert.throws(()=>Engine.generate(music(1),{stepMs:10}));assert.throws(()=>Engine.fseq(Engine.generate(music(1)),'../music.wav'));
});

test('degraded analysis data is normalized with explicit warnings',()=>{
  const m={duration:21,bpm:NaN,beats:[NaN,-3,30],downbeats:[],onsets:[null,{time:4,strength:1,band:'bass'},{time:2,strength:Infinity}],sections:[{start:0,energy:.8}],waveform:[.6]};
  const show=Engine.generate(m,{});assert.ok(show.validation.valid);assert.ok(show.validation.warnings.length>=2);assert.equal(show.stats.bpm,120);
});

test('seed reproducibility, pattern variation and section overrides are functional',()=>{
  const m=music(80),a=Engine.generate(m,{seed:1}),b=Engine.generate(m,{seed:1}),c=Engine.generate(m,{seed:2}),d=Engine.generate(m,{seed:1,sectionOverrides:{2:{style:'cinematic',intensity:.2}}});
  assert.deepEqual(a.frames,b.frames);assert.notDeepEqual(a.frames,c.frames);assert.notDeepEqual(a.frames,d.frames);
  assert.equal(d.sections[2].style,'cinematic');assert.equal(d.sections[2].intensity,.2);
});

test('validator catches corrupted payload, unsupported dimming, absent lamps and illegal movement',()=>{
  const show=Engine.generate(music(30),{dance:'off'});
  const corrupt=(index,value,term)=>{const clone=Object.assign({},show,{frames:show.frames.slice()});clone.frames[index]=value;const v=Engine.validate(clone);assert.equal(v.valid,false);assert.ok(v.errors.some(x=>x.includes(term)),v.errors.join('; '));};
  corrupt(31,63,'unsupported Model 3');corrupt(24,99,'boolean lamp');corrupt(14,255,'not fitted');corrupt(34,127,'Mirrors');corrupt(show.frames.length-1,1,'last frame');
  assert.equal(Engine.validate(Object.assign({},show,{frameCount:2})).valid,false);
});

test('the exact four-hour limit is accepted without timing overflow',()=>{
  const show=Engine.generate({duration:14400,bpm:120,beats:[],sections:[{start:0,energy:0}],waveform:[0]},{stepMs:20});
  assert.equal(show.frameCount,720000);assert.equal(show.duration,14400);assert.equal(show.frames.length,144000000);assert.ok(show.validation.valid);
});

const fixture=path.join(__dirname,'engine-glass-castle.json');
if(fs.existsSync(fixture))test('the actual Glass Castle music analysis exports a complete validated show',()=>{
  const m=JSON.parse(fs.readFileSync(fixture,'utf8')),show=Engine.generate(m,{seed:666});
  assert.equal(show.frameCount,11902);assert.ok(show.validation.valid);assert.equal(show.sections.length,m.sections.length);
  const trunk=closureRuns(decode(Engine.fseq(show)),41);assert.ok(trunk.some(e=>e.value===127));assert.ok(trunk.length<=6);assert.ok(trunk.filter(e=>e.value===127).reduce((sum,e)=>sum+e.end-e.start,0)<=30.001);
});
