'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const engine=require('../web/engine/show-engine.js'),cues=require('../web/engine/music-cues.js'),sync=require('../web/engine/sync-review.js');
function fixture(){return {duration:12,bpm:120,beatConfidence:.95,analysisVersion:5,beats:Array.from({length:24},(_,i)=>i*.5),downbeats:[0,2,4,6,8,10],waveform:Array(120).fill(.7),sections:[{start:0,end:6,energy:.7},{start:6,end:12,energy:.8}],onsets:[],vocals:{available:true,presence:'detected',confidence:.9,sourceSeparated:true,source:'separated-vocals',phrases:[{start:1.113,end:5.7,confidence:.9,strength:.8}],accents:[{time:2.137,confidence:.9,strength:.9,source:'separated-vocals'},{time:3.271,confidence:.9,strength:.8,source:'separated-vocals'}],notes:[]},bassNotes:[1.221,1.771,2.321,2.871,3.421].map(start=>({start,end:start+1.9,confidence:.95,strength:.8,midi:36})),bassAnalysis:{confidence:.95}};}
const settings={dance:'off',vocalFocus:.85,bassFocus:.9,seed:2025};
test('legato bass entrances survive held-note competition and preserve the off-grid clock',()=>{
 const m=fixture();for(const stepMs of [15,20]){const show=engine.generate(m,{...settings,stepMs});const r=show.synchronization.roles.bass;assert.equal(r.matched,m.bassNotes.length);assert.equal(r.suppressed,0);assert.ok(show.synchronization.maxErrorMs<=stepMs/2+1e-6);}
});
test('enabled alternative lamps carry voice and bass when preferred outputs are muted',()=>{
 const show=engine.generate(fixture(),{...settings,outputEnabled:{'left-signature':false,'right-signature':false,'left-outer':false,'right-outer':false}});
 assert.ok(show.lightEvents.some(e=>e.role==='vocals'&&['left-inner','right-inner'].includes(e.id)));
 assert.ok(show.lightEvents.some(e=>e.role==='bass'&&['left-tail','right-tail'].includes(e.id)));
 for(let f=0;f<show.frameCount;f++)for(const ch of [1,2,5,6])assert.equal(show.frames[f*200+ch-1],0);
 assert.equal(show.synchronization.roles.bass.matched,5);
});
test('part timing corrects automatic events while user cues keep their own soundtrack times',()=>{
 const m=fixture(),before=JSON.stringify(m),cue={id:'voice-hold',role:'vocals',action:'hold',start:6.137,end:8.271,strength:.9,midi:57};
 for(const stepMs of [15,20])for(const offsetMs of [-117,83]){
  const show=engine.generate(m,{...settings,stepMs,offsetMs,vocalOffsetMs:-150,bassOffsetMs:230,musicCues:[cue]});
  assert.ok(Math.abs(show.choreography.vocalDetail.phrases[0].start-(1.113-.15))<1e-9);
  assert.ok(Math.abs(show.choreography.roles.bassNotes[0].start-(1.221+.23))<1e-9);
  assert.equal(show.choreography.musicCues[0].start,cue.start);
  const report=show.synchronization.manual[0];assert.equal(report.status,'matched');assert.ok(Math.abs(report.errorMs)<=stepMs/2+1e-6);
 }
 assert.equal(JSON.stringify(m),before,'model evidence must remain unchanged');
});
test('explicit holds cross section boundaries, mutes remove role gestures, and accompaniment survives',()=>{
 const musicCues=[{id:'v',role:'vocals',action:'hold',start:5.137,end:7.271,strength:.8},{id:'b',role:'bass',action:'mute',start:1,end:4,strength:.8}];
 const show=engine.generate(fixture(),{...settings,musicCues});
 const v=show.lightEvents.filter(e=>e.cueId==='v');assert.ok(v.length);assert.ok(v.every(e=>e.actualEnd>7.2));
 assert.equal(show.lightEvents.filter(e=>e.role==='bass'&&e.actualStart<4&&e.actualEnd>1).length,0);
 assert.ok(show.lightEvents.some(e=>e.role==='bass'&&e.actualStart>=4),'held notes may resume outside the ignored region');
 assert.ok(show.lightEvents.some(e=>!e.role));assert.ok(show.validation.valid);
});
test('final byte review detects output overrides, missing attacks, and disabled routes',()=>{
 const cue={id:'test',role:'vocals',action:'accent',start:1.137,end:1.437,strength:.8};
 const show=engine.generate(fixture(),{...settings,musicCues:[cue],manualCues:[{id:'mute-left',outputId:'left-signature',start:1,end:2,value:0},{id:'mute-right',outputId:'right-signature',start:1,end:2,value:0}]});
 assert.equal(show.synchronization.manual[0].status,'suppressed');
 const allOff=Object.fromEntries(engine.getCapabilities().outputs.filter(o=>o.kind==='light').map(o=>[o.id,false]));
 const disabled=engine.generate(fixture(),{...settings,outputEnabled:allOff,musicCues:[cue]});assert.equal(disabled.synchronization.matched,0);assert.ok(disabled.synchronization.selected>0);
 const normal=engine.generate(fixture(),settings),e=normal.lightEvents.find(e=>e.role==='bass');
 const target={role:'bass',time:e.sourceStart,end:e.sourceEnd},frame=Math.round(e.actualStart/.02),out=engine.getCapabilities().outputs.find(o=>o.id===e.id);
 for(const ch of out.channels)normal.frames[(frame-1)*200+ch-1]=normal.frames[frame*200+ch-1];
 // Remove other routes so the report cannot count a simultaneous valid attack.
 normal.lightEvents=[e];assert.equal(sync.review(normal,[target]).roles.bass.heldWithoutAttack,1);
});
test('musical edits validate limits and remain deterministic through serialization',()=>{
 const cue={id:'a',role:'bass',action:'hold',start:6,end:7,strength:.9};
 assert.throws(()=>cues.normalize([cue,{...cue,id:'b',start:6.5}]),/overlap/);
 assert.throws(()=>cues.normalize([cue,{...cue}]),/unique/);
 assert.throws(()=>cues.normalize([{...cue,start:NaN}]),/0.10/);
 assert.throws(()=>engine.generate(fixture(),{...settings,musicCues:[{...cue,end:13}]}),/beyond/);
 const s={...settings,musicCues:[cue]},a=engine.generate(fixture(),s),b=engine.generate(fixture(),JSON.parse(JSON.stringify(s)));assert.deepEqual(a.frames,b.frames);
 const silent=fixture();silent.waveform.fill(0);silent.activityRanges=[];const result=engine.generate(silent,s);assert.equal(result.synchronization.matched,0);assert.ok(result.frames.every(v=>v===0));
});
module.exports={fixture};
