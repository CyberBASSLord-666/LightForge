'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const engine=require('../web/engine/show-engine.js');
const settings={dance:'off',style:'pulse',vocalFocus:0,bassFocus:0,seed:2025,palette:'aurora'};
function fixture(beats=[.113,.613,1.124,1.724,2.254,2.854,3.414,4.014]){
  return {duration:5,bpm:120,beatConfidence:.99,analysisVersion:5,beats,downbeats:[beats[0],beats[4]],onsets:[],waveform:Array(100).fill(.8),energy:Array(250).fill(.8),energyStep:.02,sections:[{start:0,end:5,energy:.8}]};
}
const rgb=(show,frame,zone=0)=>Array.from(show.frames.subarray(frame*200+175+zone*3,frame*200+178+zone*3));
const brightness=(show,frame)=>rgb(show,frame).reduce((a,b)=>a+b,0);
test('RGB beat peaks use nearest frames for irregular timing and apply the offset once',()=>{
  for(const stepMs of [15,20])for(const offsetMs of [-83,0,117])for(const fraction of [.2,.49,.5,.51,.8]){
    const step=stepMs/1000,shift=offsetMs/1000,target=(70+fraction)*step;
    const music=fixture([.2-shift,target-shift,target+.47-shift,target+1.06-shift,target+1.69-shift]);
    const before=JSON.stringify(music),show=engine.generate(music,{...settings,stepMs,offsetMs});
    const expected=Math.round((music.beats[1]+shift)/step);
    const values=[expected-1,expected,expected+1].map(frame=>brightness(show,frame));
    assert.ok(values[1]>values[0]&&values[1]>values[2],JSON.stringify({stepMs,offsetMs,fraction,expected,values}));
    const attack=show.lightEvents.find(e=>e.kind==='beat pulse'&&Math.abs(e.actualStart-expected*step)<1e-8);
    assert.ok(attack,'exterior and interior use the same selected frame when no onset snap is requested');
    assert.ok(Math.abs(expected*step-target)<=step/2+1e-9);
    assert.equal(JSON.stringify(music),before,'original musical timing is immutable');
    assert.ok(show.validation.valid);
  }
});
test('pickup before the first measured beat has no invented maximum beat pulse',()=>{
  for(const stepMs of [15,20]){
    const show=engine.generate(fixture([.413,1.113,1.613,2.213,2.713,3.313,3.813]),{...settings,stepMs});
    const first=Math.round(.413/(stepMs/1000));
    for(let f=0;f<first;f++)assert.ok(brightness(show,f)<brightness(show,first)/3);
  }
});
test('silent gaps reset vocal, bass and pitch envelopes before the next passage',()=>{
  for(const stepMs of [15,20])for(const offsetMs of [-83,0,117]){
    const base=fixture(),envelope=Array.from({length:250},(_,i)=>i<100?.95:.13);
    base.activityRanges=[{start:0,end:1.4},{start:3,end:5}];
    base.vocals={available:true,presence:'detected',sourceSeparated:true,source:'separated-vocals',confidence:.95,envelope,envelopeStep:.02,phrases:[{start:0,end:1.4,confidence:.95,strength:.95},{start:3,end:4.8,confidence:.95,strength:.13}],notes:[{start:0,end:1.4,confidence:.95,strength:.95,midi:80},{start:3,end:4.8,confidence:.95,strength:.13,midi:48}]};
    base.bassNotes=[{start:0,end:1.4,confidence:.95,strength:.95,midi:36},{start:3,end:4.8,confidence:.95,strength:.13,midi:36}];
    base.bassAnalysis={confidence:.95,envelope,envelopeStep:.02};
    const fresh=JSON.parse(JSON.stringify(base));fresh.vocals.phrases.shift();fresh.vocals.notes.shift();fresh.bassNotes.shift();
    const options={...settings,stepMs,offsetMs,vocalFocus:.85,bassFocus:.9};
    const a=engine.generate(base,options),b=engine.generate(fresh,options),step=stepMs/1000;
    for(let f=0;f<a.frameCount-1;f++){
      const musicTime=f*step-offsetMs/1000;
      if(musicTime>=1.4&&musicTime<3)for(let z=0;z<6;z++)assert.ok(rgb(a,f,z).every(v=>v===0));
      if(musicTime>=3&&musicTime<4.5)for(let z=0;z<6;z++)assert.deepEqual(rgb(a,f,z),rgb(b,f,z),`stale state at ${musicTime}, zone ${z}`);
    }
  }
});
test('interior refinements preserve exterior bytes, disabled outputs and final off frame',()=>{
  for(const stepMs of [15,20]){
    const m=fixture(),on=engine.generate(m,{...settings,stepMs}),off=engine.generate(m,{...settings,stepMs,enabled:{interior:false}});
    for(let f=0;f<on.frameCount;f++){
      assert.deepEqual(on.frames.subarray(f*200,f*200+175),off.frames.subarray(f*200,f*200+175));
      assert.ok(off.frames.subarray(f*200+175,f*200+193).every(v=>v===0));
    }
    assert.ok(on.frames.subarray((on.frameCount-1)*200).every(v=>v===0));
    const muted=engine.generate(m,{...settings,stepMs,outputEnabled:{'display':false}});
    const output=engine.getCapabilities().outputs.find(o=>o.id==='display');
    assert.ok(output,'expected profile display output');
    for(let f=0;f<muted.frameCount;f++)for(const ch of output.channels)assert.equal(muted.frames[f*200+ch-1],0);
  }
});
