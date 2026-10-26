'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const Engine=require('../web/engine/show-engine.js');
const Timeline=require('../web/analysis/semantic-timeline.js');
const Salience=require('../web/analysis/salience.js');
function fixture(){
 const duration=24,beats=Array.from({length:48},(_,i)=>.013+i*.5);
 return {duration,bpm:120,beatConfidence:.95,beats,downbeats:beats.filter((_,i)=>i%4===0),
  waveform:Array(1200).fill(.7),activityRanges:[{start:0,end:duration}],
  sections:[{start:0,end:8,energy:.25},{start:8,end:24,energy:.95}],
  onsets:[{time:8.013,strength:.98,band:'bass'},{time:8.2,strength:.6,band:'high'}],
  impacts:[{time:8.013,strength:.98,kind:'impact'}]};
}
function enrich(music){const semanticTimeline=Timeline.build(music);return {...music,semanticTimeline,musicSalience:Salience.build(semanticTimeline)};}
test('instrumental arrangements receive linked hierarchy without inventing vocal/bass targets',()=>{
 const music=enrich(fixture()),settings={dance:'off',semanticChoreography:true};
 const show=Engine.generate(music,settings);
 assert.equal(show.choreography.semanticStrategy.active,true);
 assert.ok(show.choreography.semanticStrategy.hierarchy.boostedCandidateCount>0);
 assert.ok(show.choreography.semanticStrategy.negativeSpace.windowCount>0);
 assert.ok(show.lightEvents.some(e=>e.kind==='musical impact'&&e.semanticEventId));
 assert.ok(show.lightEvents.filter(e=>e.semanticRole==='rhythm'&&e.semanticEventId).length>0);
 assert.equal(show.stats.vocalCues,0);assert.equal(show.stats.bassNoteCues,0);
 assert.equal(show.validation.valid,true);
 assert.deepEqual(Engine.generate(music,settings).frames,show.frames);
});
test('invalid/disabled hierarchy retains legacy arrangement and frame bytes',()=>{
 const music=fixture(),valid=enrich(music),base=Engine.generate(music,{dance:'off'});
 assert.deepEqual(Engine.generate(valid,{dance:'off'}).frames,base.frames);
 assert.deepEqual(Engine.generate({...valid,musicSalience:{...valid.musicSalience,duration:1}},{dance:'off',semanticChoreography:true}).frames,base.frames);
});
for(const stepMs of [15,20])test('automatic ramps allow at least 50 ms at both endpoints at '+stepMs+' ms',()=>{
 const music=fixture();music.sections=[{start:0,end:24,energy:.15}];music.waveform.fill(.15);music.impacts=[];
 const show=Engine.generate(music,{stepMs,dance:'off',style:'cinematic',seed:17}),step=stepMs/1000;
 const ramps=show.lightEvents.filter(e=>e.fade>0);assert.ok(ramps.length>0);
 for(const cue of ramps){
  const channel=Engine.getCapabilities().outputs.find(o=>o.id===cue.id).channels[0]-1;
  const up=show.frames[cue.a*200+channel];let pivot=cue.a;
  while(pivot<cue.b&&show.frames[pivot*200+channel]===up)pivot++;
  assert.ok((pivot-cue.a)*step>=cue.fade+.05-1e-8,JSON.stringify(cue));
  assert.ok((cue.b-pivot)*step>=cue.fade+.05-1e-8,JSON.stringify(cue));
 }
});

test('recorded pulse passages retain beat attacks instead of turning accents into density gaps',()=>{
 const fs=require('node:fs'),path=require('node:path');
 const cases=[
  ['qa/music-1.3.0/current-demo-music.json',[[30.445,['left-inner','right-inner','left-signature','right-tail']]]],
  ['qa/music-1.3.0/current-sample-music.json',[[64.445,['left-inner','right-inner','brakes','right-outer','right-combined','right-tail']],[192.115,['left-outer','right-outer','left-tail','right-tail','right-signature']]]],
  ['qa/release-1.6.0/actual-music-user-glass-prefix64-analysis.json',[[30.305,['left-tail','right-tail']]]]
 ];
 for(const [file,anchors]of cases)for(const stepMs of [15,20]){
  const music=enrich(JSON.parse(fs.readFileSync(path.join(__dirname,'..',file))));
  const show=Engine.generate(music,{style:'pulse',stepMs,seed:2025,dance:'expressive',semanticChoreography:true,vocalChoreography:true});
  assert.equal(show.validation.valid,true);
  for(const [time,ids]of anchors)for(const id of ids){
   const cue=show.lightEvents.find(e=>e.id===id&&e.kind==='beat pulse'&&Math.abs(e.musicTime-time)<1e-6);
   assert.ok(cue,`${file} ${stepMs}ms ${time}s ${id} beat must survive`);
   assert.equal(cue.semanticRhythmAttack,true);
   assert.ok(Math.abs(cue.actualStart-time)*1000<=stepMs/2+1e-6,'retain nearest-frame source anchor');
  }
 }
});
