'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
require('../web/analysis/dsp.js');
const DSP=global.LightForgeDSP;
function fixture({duration=48,change=time=>Math.floor(time/12)%2,amplitude=()=>.5,transpose=0,background=0}={}){
 const frames=Math.ceil(duration*50),count=Math.ceil(duration/.2),chroma=new Float32Array(count*12).fill(background),rms=Float32Array.from({length:frames},(_,i)=>amplitude(i*.02)),colour=new Float32Array(frames*3).fill(1);
 for(let i=0;i<count;i++)for(const pitch of [0,4,7])chroma[i*12+(pitch+change(i*.2)+transpose)%12]+=1;
 const rhythm={bpm:120,meter:4,meterConfidence:.9,beatConfidence:.9,downbeatConfidence:.9,beats:Array.from({length:Math.ceil(duration*2)},(_,i)=>i*.5),downbeats:Array.from({length:Math.ceil(duration/2)},(_,i)=>i*2),activityRanges:[{start:0,end:duration}]};
 return {data:{duration,chroma,chromaStep:.2,rms,colour},rhythm};
}
function analyze(input){const {data,rhythm}=input,tonal=DSP.tonalStructure(data,rhythm),structure=DSP.sectionsFromFeatures(data.rms,data.colour,rhythm,data.duration,tonal),landmarks=DSP.phrasesAndImpacts(rhythm,structure,[],data.duration);return {tonal,structure,...landmarks};}
const times=items=>items.map(item=>item.time);
test('equal-energy harmonic sections missed by the energy-only detector become measured default boundaries',()=>{
 const input=fixture(),before=DSP.sectionsFromFeatures(input.data.rms,input.data.colour,input.rhythm,input.data.duration),after=analyze(input);
 assert.deepEqual(before.sections.map(s=>s.start),[0]);
 assert.deepEqual(after.structure.sections.map(s=>s.start),[0,12,24,36]);
 assert.ok(after.structure.sections.slice(1).every(s=>s.boundarySource==='tonal-novelty'&&s.estimated));
 const original=structuredClone(input.rhythm);analyze(input);assert.deepEqual(input.rhythm,original,'the approved neural beat clock is immutable');
});
test('three-bar transitions lead phrasing and edge-window artifacts do not create boundaries',()=>{
 const result=analyze(fixture({change:t=>Math.floor(t/6)%2}));
 assert.deepEqual(times(result.tonal.sections),[12,18,24,30,36]);
 assert.deepEqual(result.phrases.map(p=>p.start),[0,6,12,18,24,30,36,42]);
 assert.ok(result.phrases.slice(1).every(p=>p.boundarySource==='tonal-novelty'));
});
test('global pitch transposition and common chroma floor preserve transition locations',()=>{
 const reference=analyze(fixture());for(const transpose of [1,5,11]){
  const result=analyze(fixture({transpose,background:.4}));
  assert.deepEqual(times(result.tonal.sections),times(reference.tonal.sections));
  assert.deepEqual(times(result.tonal.phrases),times(reference.tonal.phrases));
 }
});
test('a sustained chord, periodic one-bar chord progression and isolated tonal artifacts do not invent sections',()=>{
 for(const input of [fixture({change:()=>0}),fixture({change:t=>[0,5,7,0][Math.floor(t/2)%4]}),fixture({change:t=>t>=23.8&&t<24?1:0})])assert.deepEqual(analyze(input).tonal.sections,[]);
 const sustained=analyze(fixture({change:()=>0}));assert.deepEqual(sustained.tonal.phrases,[]);assert.ok(sustained.phrases.slice(1).every(p=>p.boundarySource==='meter-scaffold'&&p.confidence<=.5));
});
test('silence and flat pitch-class energy cannot acquire harmonic structure',()=>{
 const silent=fixture({amplitude:()=>0});silent.rhythm.activityRanges=[];
 assert.equal(analyze(silent).tonal.available,false);assert.deepEqual(analyze(silent).structure.sections.map(s=>s.label),['Silence']);
 const flat=fixture();flat.data.chroma.fill(1);assert.equal(analyze(flat).tonal.available,false);
 const tinyNoise=fixture();tinyNoise.data.chroma=Float32Array.from(tinyNoise.data.chroma,(_,i)=>1+(i%7)*.0001);assert.equal(analyze(tinyNoise).tonal.available,false);
});
test('malformed chroma fails closed to energy/spectral structure without fabricated tonal events',()=>{
 const input=fixture();for(const mutate of [d=>delete d.chroma,d=>d.chroma[24]=NaN,d=>d.chroma[24]=-1,d=>d.chromaStep=0,d=>d.chroma=d.chroma.subarray(0,120),d=>d.chroma=new Float32Array(72001*12),d=>d.chroma=Array(d.chroma.length).fill(1e308),d=>d.chroma=Array(d.chroma.length).fill(1.2e153)]){
  const value=structuredClone(input);mutate(value.data);const result=analyze(value);assert.equal(result.tonal.available,false);assert.deepEqual(result.tonal.sections,[]);assert.deepEqual(result.structure.sections.map(s=>s.start),[0]);
 }
 assert.equal(DSP.tonalStructure({...input.data,duration:14401},input.rhythm).reason,'invalid-duration');
});
test('explicit silent gaps survive section spacing and never produce tonal transitions',()=>{
 const input=fixture({amplitude:t=>t>=20&&t<23?0:.5});input.rhythm.activityRanges=[{start:0,end:20},{start:23,end:48}];
 const result=analyze(input),silent=result.structure.sections.find(s=>s.label==='Silence');
 assert.equal(silent.start,20);assert.equal(silent.end,23);assert.ok(result.tonal.sections.every(s=>s.time<20||s.time>=23));
 assert.ok(result.phrases.some(p=>p.start===20&&p.end===23&&p.kind==='silence'));
});
test('off-grid evidence remains on its original clock when downbeats are uncertain',()=>{
 const input=fixture({change:t=>Math.floor((t+1.4)/12)%2});input.rhythm.downbeatConfidence=0;input.rhythm.meterConfidence=0;input.rhythm.beats=[];input.rhythm.downbeats=[];
 const result=analyze(input);assert.deepEqual(times(result.tonal.sections),[10.6,22.6,34.6]);assert.deepEqual(result.structure.sections.map(s=>s.start),[0,10.6,22.6,34.6]);
});
test('the default composer changes scenes using new structure without moving any music events',()=>{
 const engine=require('../web/engine/show-engine.js'),input=fixture(),after=analyze(input),legacy=DSP.sectionsFromFeatures(input.data.rms,input.data.colour,input.rhythm,input.data.duration),legacyPhrases=DSP.phrasesAndImpacts(input.rhythm,legacy,[],input.data.duration);
 const music={duration:48,...input.rhythm,waveform:Array(480).fill(.5),energy:legacy.energy,energyStep:.02,onsets:[],...legacyPhrases,sections:legacy.sections};
 const before=engine.generate(music,{seed:7,dance:'off'}),enhanced=engine.generate({...music,...after,sections:after.structure.sections},{seed:7,dance:'off'});
 assert.notDeepEqual(enhanced.frames,before.frames);assert.equal(enhanced.sections.length,4);assert.ok(enhanced.validation.valid);assert.deepEqual(enhanced.choreography.rhythm.beats,before.choreography.rhythm.beats);
});
module.exports={fixture,analyze};

test('production spectral frontend distinguishes sustained major/minor harmony at nearly equal energy',()=>{
 const input=fixture(),config=require('../web/analysis/models/features.json');
 const chords=[[60,64,67],[60,63,67]].map(notes=>{
  const pcm=Float32Array.from({length:1411},(_,i)=>notes.reduce((sum,midi)=>sum+.1*Math.sin(2*Math.PI*440*Math.pow(2,(midi-69)/12)*i/22050),0));
  return new DSP.FeatureExtractor(config).extract(pcm,0,1);
 });
 for(let i=0;i<input.data.rms.length;i++){const frame=chords[Math.floor(i/600)%2];input.data.rms[i]=frame.rms[0];input.data.colour.set(frame.colour,i*3);if(i%10===0)input.data.chroma.set(frame.chroma,i/10*12);}
 const baseline=DSP.sectionsFromFeatures(input.data.rms,input.data.colour,input.rhythm,input.data.duration),result=analyze(input);
 assert.equal(baseline.sections.length,1);assert.deepEqual(result.structure.sections.map(section=>section.start),[0,12,24,36]);
});
