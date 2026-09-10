'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const Timeline=require('../web/analysis/semantic-timeline.js');
const Salience=require('../web/analysis/salience.js');
function loadDsp(){
 const context=vm.createContext({});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/analysis/dsp.js'),'utf8'),context,{filename:'dsp.js'});
 return context.LightForgeDSP;
}
const DSP=loadDsp();

function featureData(){
 const frames=160,make=()=>new Float32Array(frames).fill(.1),bass=make(),mid=make(),high=make();
 for(const values of [bass,mid,high])for(let index=0;index<frames;index+=10)values[index]=.4;
 bass[53]=1;mid[73]=1;high[103]=1;
 return {duration:3.2,bass,mid,high,activityRanges:[{start:0,end:3.2}]};
}
function evidence(){
 const data=featureData(),onsets=[
  {time:1.06,band:'bass',strength:.95},
  {time:1.46,band:'mid',strength:.96},
  {time:2.06,band:'high',strength:.97}
 ],attacks=onsets.map(item=>({time:item.time,strength:.9}));
 return DSP.estimatePercussionEvidence(data,{enabled:true,onsets,attacks,activityRanges:data.activityRanges});
}
test('estimated percussion is explicit, conservative, deterministic, and needs multi-resolution attack evidence',()=>{
 const first=evidence(),second=evidence();
 assert.deepEqual(first,second);
 assert.equal(first.source,'mix-feature-estimate');
 assert.equal(first.estimated,true);
 assert.equal(first.inputStem,'mixture');
 assert.equal(first.inputStemSeparated,false);
 assert.equal(first.sourceSeparated,false);
 assert.equal(first.salienceCap,.41);
 assert.deepEqual(Array.from(first.events,event=>event.kind),['kick','snare','hat']);
 assert.ok(first.events.every(event=>event.estimated===true&&event.confidence<=.58&&event.salienceCap===.41));
 const data=featureData(),onsets=[{time:1.06,band:'bass',strength:1}];
 const absent=DSP.estimatePercussionEvidence(data,{enabled:true,onsets,attacks:[],activityRanges:data.activityRanges});
 assert.deepEqual(Array.from(absent.events),[]);
 assert.equal(DSP.estimatePercussionEvidence(data,{enabled:false,onsets,attacks:[]}),null);
});
test('summary never adds estimated percussion without the exact opt-in flag',()=>{
 const frames=40,data={duration:.8,beat:new Float32Array(frames),down:new Float32Array(frames),rms:new Float32Array(frames).fill(.1),bass:new Float32Array(frames),mid:new Float32Array(frames),high:new Float32Array(frames),colour:new Float32Array(frames*3),fineRms:new Float32Array(frames*4),chroma:new Float32Array(Math.ceil(frames/10)*12),chromaStep:.2};
 const baseline=DSP.summarize(data,{});
 assert.equal(Object.prototype.hasOwnProperty.call(baseline,'percussionAnalysis'),false);
});
test('low-trust mix estimates remain below primary salience and cannot drive the context profile',()=>{
 const percussion=evidence(),music={duration:3.2,beatConfidence:.9,beats:[],downbeats:[],sections:[{start:0,end:3.2,energy:.9,label:'peak'}],phrases:[],onsets:[],impacts:[],
  bassNotes:[{start:1.0,end:1.3,confidence:.9,strength:.9,midi:38,frequency:73.4,estimated:true}],
  bassAnalysis:{source:'accompaniment-mixture-estimate',inputStem:'accompaniment',inputStemSeparated:true,instrumentSeparated:false,estimated:true},
  percussionAnalysis:percussion};
 const timeline=Timeline.build(music);
 assert.equal(Timeline.validate(timeline).valid,true);
 const estimated=timeline.events.filter(event=>event.analysisSource==='mix-feature-estimate');
 assert.equal(estimated.length,3);
 assert.ok(estimated.every(event=>event.estimated===true&&event.salienceCap===.41&&event.salience<=.41));
 const coincidence=timeline.events.find(event=>event.type==='kick_bass_coincidence');
 assert.ok(coincidence&&coincidence.estimated===true&&coincidence.salienceCap===.41&&coincidence.salience<=.41);
 const salience=Salience.build(timeline);
 assert.equal(Salience.validate(salience,timeline).valid,true);
 assert.ok([...estimated,coincidence].every(event=>{const ranked=salience.events.find(value=>value.id===event.id);return ranked.score<=.41&&ranked.tier!=='primary'&&ranked.tier!=='phrase'&&ranked.tier!=='structural'&&ranked.tier!=='climax';}));
 assert.equal(salience.summary.context.evidence.rhythm,0);
 assert.equal(salience.summary.context.evidence.percussion,0);
 const invalid=structuredClone(timeline);
 invalid.events.find(event=>event.analysisSource==='mix-feature-estimate').salienceCap=0;
 assert.throws(()=>Salience.build(invalid),/salience cap/);
 assert.equal(Salience.validate(salience,invalid).valid,false);
});
