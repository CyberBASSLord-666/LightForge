'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const VocalSemantics=require('../web/analysis/vocal-semantics.js');
const Timeline=require('../web/analysis/semantic-timeline.js');
const Salience=require('../web/analysis/salience.js');

function fixture(){return {duration:8,vocals:{source:'separated-vocals',sourceSeparated:true,phrases:[
 {start:1,end:2.4,releaseTime:2.4,confidence:.92,strength:.8,peakTime:1.7,kind:'singing',word:'never-copy-this',estimated:true},
 {start:2.55,end:3.4,releaseTime:3.25,confidence:.76,strength:.55,peakTime:2.8,kind:'singing',text:'never-copy-this',estimated:true},
 {start:5,end:5.8,releaseTime:5.8,confidence:.81,strength:.7,peakTime:5.3,kind:'speech',estimated:true}
 ],notes:[
 {start:1.05,end:1.65,midi:60,frequency:261.63,confidence:.86,strength:.74,type:'held-note',estimated:true},
 {start:1.72,end:2.25,midi:64,frequency:329.63,confidence:.84,strength:.7,type:'held-note',estimated:true},
 {start:5.1,end:5.5,midi:55,frequency:196,confidence:.9,strength:.8,type:'note',estimated:true}
 ],accents:[
 {time:1,kind:'entrance',confidence:.9,strength:.42,estimated:true},
 {time:1.28,kind:'syllabic-accent',confidence:.87,strength:.9,estimated:true},
 {time:1.9,kind:'syllabic-accent',confidence:.78,strength:.44,estimated:true},
 {time:5,kind:'entrance',confidence:.81,strength:.7,estimated:true},
 {time:5.25,kind:'syllabic-accent',confidence:.8,strength:.6,estimated:true},
 {time:7.1,kind:'syllabic-accent',confidence:.99,strength:1,estimated:true}
 ],pitchContour:{step:.04,midi:[0,0,60,61,62,63,64,0,0],confidence:[0,0,.7,.7,.8,.8,.8,0,0]}}};}

test('builds deterministic non-linguistic region, phrase, pitch and articulation sidecar',()=>{
 const input=fixture(),first=VocalSemantics.build(input),second=VocalSemantics.build(structuredClone(input));
 assert.deepEqual(first,second);
 assert.equal(VocalSemantics.validate(first,input).valid,true);
 assert.equal(first.sourceSeparated,true);
 assert.equal(first.linguisticAlignment,false);
 assert.equal(first.regions.length,2);
 assert.equal(first.phrases.length,3);
 assert.equal(first.notes.length,2,'speech notes are not promoted into a sung phrase semantic');
 assert.equal(first.articulations.length,5,'only supplied accents inside valid phrases are represented');
 assert.equal(first.summary.syllableLikeCount,3);
 const phrase=first.phrases[0];
 assert.equal(phrase.onset,1);assert.equal(phrase.release,2.4);
 assert.equal(first.phrases[1].release,3.25,'the accepted acoustic release is preserved independently of the analysis span');
 assert.deepEqual({...phrase.pitchTrajectory,confidence:undefined},{source:'existing-note-output',observations:2,startMidi:60,endMidi:64,medianMidi:62,movement:'rising',confidence:undefined});
 assert.ok(phrase.pitchTrajectory.confidence>.85&&phrase.pitchTrajectory.confidence<.851);
 const strong=first.articulations.find(value=>value.time===1.28);
 assert.equal(strong.role,'acoustic-articulation');assert.equal(strong.syllableLike,true);assert.equal(strong.stress,'primary');assert.equal(strong.linguistic,false);
 assert.equal(JSON.stringify(first).includes('never-copy-this'),false);
 assert.equal(/"(?:word|text|lyric|phoneme)/i.test(JSON.stringify(first)),false);
});

test('rejects stale, invalid, unseparated and linguistic sidecars',()=>{
 const input=fixture(),sidecar=VocalSemantics.build(input),changed=structuredClone(input);changed.vocals.phrases[0].end=2.2;
 assert.equal(VocalSemantics.validate(sidecar,changed).valid,false);
 const unseparated=fixture();unseparated.vocals.sourceSeparated=false;
 assert.throws(()=>VocalSemantics.build(unseparated),/separated-vocal/);
 const invalid=structuredClone(sidecar);invalid.phrases[0].word='fabricated';
 assert.equal(VocalSemantics.validate(invalid,input).valid,false);
 const invalidArticulation=structuredClone(sidecar);invalidArticulation.articulations[0].syllableLike=true;
 assert.equal(VocalSemantics.validate(invalidArticulation,input).valid,false);
 const invalidRelease=structuredClone(sidecar);invalidRelease.phrases[0].release=3;
 assert.equal(VocalSemantics.validate(invalidRelease,input).valid,false);
});

test('rejects malformed cached semantic lists without throwing',()=>{
 const input=fixture(),sidecar=VocalSemantics.build(input);
 for(const [field,value] of [
  ['regions',null],
  ['phrases','not-an-array'],
  ['phrases',[null]],
  ['articulations',{corrupt:true}],
  ['notes',[null]]
 ]){
  const corrupt=structuredClone(sidecar);corrupt[field]=value;
  let check;
  assert.doesNotThrow(()=>{check=VocalSemantics.validate(corrupt,input);},`${field} cache corruption must not escape validation`);
 assert.equal(check.valid,false,`${field} cache corruption must fail closed`);
 }
 const nested=structuredClone(sidecar);nested.regions[0].phraseIds={corrupt:true};
 let nestedCheck;
 assert.doesNotThrow(()=>{nestedCheck=VocalSemantics.validate(nested,input);},'a malformed nested region list must not escape validation');
 assert.equal(nestedCheck.valid,false,'a malformed nested region list must fail closed');
});

test('links only exact existing vocal timeline events and fails closed on a changed clock',()=>{
 const input=fixture(),sidecar=VocalSemantics.build(input),timeline=Timeline.build(input),link=VocalSemantics.linkTimeline(sidecar,timeline);
 assert.equal(link.phrases.length,sidecar.phrases.length);
 assert.equal(link.notes.length,sidecar.notes.length);
 assert.equal(link.articulations.length,sidecar.articulations.length);
 assert.match(link.timelineFingerprint,/^vt1-[0-9a-f]{16}$/);
 const retuned=structuredClone(timeline);retuned.events.find(value=>value.type==='vocal_note').midi=67;
 assert.notEqual(VocalSemantics.linkTimeline(sidecar,retuned).timelineFingerprint,link.timelineFingerprint,'a semantically changed but time-identical timeline must not retain the old link binding');
 const recapped=structuredClone(timeline);recapped.events.find(value=>value.type==='vocal_accent').salienceCap=.75;
 assert.equal(Timeline.validate(recapped).valid,true,'the cap-only binding fixture must remain a valid semantic timeline');
 assert.notEqual(VocalSemantics.linkTimeline(sidecar,recapped).timelineFingerprint,link.timelineFingerprint,'a cap-only timeline mutation must invalidate the vocal link binding');
 const finelyRecapped=structuredClone(recapped);finelyRecapped.events.find(value=>value.type==='vocal_accent').salienceCap=.7500004;
 assert.equal(Timeline.validate(finelyRecapped).valid,true);
 assert.notEqual(VocalSemantics.linkTimeline(sidecar,finelyRecapped).timelineFingerprint,VocalSemantics.linkTimeline(sidecar,recapped).timelineFingerprint,'valid sub-micro semantic changes must not reuse a timeline receipt');
 const invalid=structuredClone(timeline);invalid.events[0].salience=1.01;
 assert.throws(()=>VocalSemantics.linkTimeline(sidecar,invalid),/invalid timeline/,'links must reject a timeline that the canonical validator rejects');
 const malformed=structuredClone(timeline);malformed.events=[null];
 assert.throws(()=>VocalSemantics.linkTimeline(sidecar,malformed),/invalid timeline/,'a malformed timeline cache must fail closed with a controlled link error');
 const invalidCap=structuredClone(timeline),capEvent=invalidCap.events.find(value=>value.type==='vocal_accent');
 capEvent.salienceCap=Math.max(0,capEvent.salience-.01);
 assert.equal(Timeline.validate(invalidCap).valid,false,'the integrated canonical timeline validator must reject caps below realized salience');
 assert.throws(()=>VocalSemantics.linkTimeline(sidecar,invalidCap),/Invalid event salience cap/,'cap-aware canonical validation must block an invalid timeline before linking');
 const wrongClock=structuredClone(timeline);wrongClock.clock='resampled-clock';
 assert.equal(Timeline.validate(wrongClock).valid,false,'the canonical semantic timeline validator must reject a non-original audio clock');
 assert.throws(()=>VocalSemantics.linkTimeline(sidecar,wrongClock),/matching semantic timeline/,'a vocal link must never relabel a resampled timeline as original-audio time');
 const shifted=structuredClone(timeline);shifted.events.find(value=>value.type==='vocal_accent'&&value.kind==='syllabic-accent').time+=.01;
 assert.throws(()=>VocalSemantics.linkTimeline(sidecar,shifted),/cannot be linked/);
});

test('does not create pitch trajectory or articulation when the accepted input has none',()=>{
 const input=fixture();input.vocals.notes=[];input.vocals.pitchContour={step:.04,midi:[],confidence:[]};input.vocals.accents=[];
 const sidecar=VocalSemantics.build(input);
 assert.equal(sidecar.notes.length,0);assert.equal(sidecar.articulations.length,0);
 assert.equal(sidecar.phrases.some(value=>value.pitchTrajectory),false);
 assert.equal(VocalSemantics.validate(sidecar,input).valid,true);
});

test('worker keeps opt-in sidecars out of the base cache and removes them for default callers',async()=>{
 const workerSelf={LightForgeVocalSemantics:VocalSemantics};
 const context={self:workerSelf,importScripts(){},postMessage(){},performance:{now:()=>0},URL,fetch:async()=>{throw Error('Unexpected worker fetch.');},navigator:{hardwareConcurrency:1},SharedArrayBuffer};
 vm.createContext(context);
 vm.runInContext(fs.readFileSync(require.resolve('../web/analysis/worker.js'),'utf8')+'\nself.__vocalSemanticTest={persistableAnalysis,ensureVocalSemantics,linkVocalSemantics};',context);
 const {persistableAnalysis,ensureVocalSemantics,linkVocalSemantics}=workerSelf.__vocalSemanticTest,input=fixture();
 input.semanticTimeline=Timeline.build(input);
 const values=new Map(),store={read:async key=>values.get(key)||null,write:async(key,value)=>values.set(key,value),invalidate:async keys=>keys.forEach(key=>values.delete(key))},telemetry={begin:()=>({}),end:()=>{},cache:()=>{}};
 await ensureVocalSemantics(input,{vocalSemanticEnrichment:true},store,telemetry);
 assert.ok(input.vocalSemantics);assert.ok(values.has('vocal-semantics'));
 linkVocalSemantics(input);assert.equal(input.vocalSemanticLinks.articulations.length,input.vocalSemantics.articulations.length);
 await ensureVocalSemantics(input,{vocalSemanticEnrichment:true},store,telemetry);
 assert.equal('vocalSemanticLinks' in input,false,'a restored sidecar cannot retain a link from another timeline');
 linkVocalSemantics(input);
 const persisted=persistableAnalysis(input);
 assert.equal('vocalSemantics' in persisted,false);assert.equal('vocalSemanticLinks' in persisted,false);
 await ensureVocalSemantics(input,{},store,telemetry);
 assert.equal('vocalSemantics' in input,false);assert.equal('vocalSemanticLinks' in input,false);
});

test('worker invalidates and rebuilds a malformed cached vocal sidecar without fabricating language',async()=>{
 const throwingApi={...VocalSemantics,validate(sidecar,input){if(sidecar?.__throwOnValidate===true)throw Error('simulated corrupt-cache validator fault');return VocalSemantics.validate(sidecar,input);}};
 const workerSelf={LightForgeVocalSemantics:throwingApi};
 const context={self:workerSelf,importScripts(){},postMessage(){},performance:{now:()=>0},URL,fetch:async()=>{throw Error('Unexpected worker fetch.');},navigator:{hardwareConcurrency:1},SharedArrayBuffer};
 vm.createContext(context);
 vm.runInContext(fs.readFileSync(require.resolve('../web/analysis/worker.js'),'utf8')+'\nself.__vocalSemanticRecoveryTest={persistableAnalysis,ensureVocalSemantics};',context);
 const {persistableAnalysis,ensureVocalSemantics}=workerSelf.__vocalSemanticRecoveryTest,input=fixture(),events=[];
 const corrupt=VocalSemantics.build(input);corrupt.phrases=[null];corrupt.__throwOnValidate=true;
 const values=new Map([['vocal-semantics',corrupt]]),store={read:async key=>values.get(key)||null,write:async(key,value)=>values.set(key,value),invalidate:async keys=>{events.push(...keys);keys.forEach(key=>values.delete(key));}},telemetry={begin:()=>({}),end:()=>{},cache:(stage,state)=>events.push(`${stage}:${state}`)};
 await assert.doesNotReject(async()=>ensureVocalSemantics(input,{vocalSemanticEnrichment:true},store,telemetry));
 const rebuilt=values.get('vocal-semantics');
 assert.notEqual(rebuilt,corrupt,'the malformed checkpoint must not be restored');
 assert.equal(VocalSemantics.validate(rebuilt,input).valid,true,'the replacement checkpoint must be valid');
 assert.ok(events.includes('vocal-semantics'),'the malformed checkpoint must be invalidated before rebuild');
 assert.ok(events.includes('vocal-semantics:corrupt'),'a validator fault must be treated as corrupt cache evidence rather than a worker crash');
 assert.equal(rebuilt.summary.linguisticContent,false);
 assert.equal(JSON.stringify(rebuilt).includes('never-copy-this'),false,'recovery must not copy rejected word/text fields into acoustic metadata');
 const persisted=persistableAnalysis(input);
 assert.equal('vocalSemantics' in persisted,false,'recovered opt-in cache data must remain absent from the default persisted result');
});

test('worker rebuilds corrupt cached semantic timeline and salience after validator faults',()=>{
 const throwingTimeline={...Timeline,validate(value){if(value?.__throwOnValidate===true)throw Error('simulated timeline validator fault');return Timeline.validate(value);}};
 const throwingSalience={...Salience,validate(value,timeline){if(value?.__throwOnValidate===true)throw Error('simulated salience validator fault');return Salience.validate(value,timeline);}};
 const workerSelf={LightForgeSemanticTimeline:throwingTimeline,LightForgeMusicSalience:throwingSalience};
 const context={self:workerSelf,importScripts(){},postMessage(){},performance:{now:()=>0},URL,fetch:async()=>{throw Error('Unexpected worker fetch.');},navigator:{hardwareConcurrency:1},SharedArrayBuffer};
 vm.createContext(context);
 vm.runInContext(fs.readFileSync(require.resolve('../web/analysis/worker.js'),'utf8')+'\nself.__semanticCacheRecoveryTest={ensureSemanticTimeline,ensureMusicSalience};',context);
 const {ensureSemanticTimeline,ensureMusicSalience}=workerSelf.__semanticCacheRecoveryTest,input=fixture();
 const corruptTimeline=Timeline.build(input);corruptTimeline.__throwOnValidate=true;input.semanticTimeline=corruptTimeline;
 let rebuiltTimeline;assert.doesNotThrow(()=>{rebuiltTimeline=ensureSemanticTimeline(input);});
 assert.notEqual(rebuiltTimeline,corruptTimeline);assert.equal(Timeline.validate(rebuiltTimeline).valid,true);
 const corruptSalience=Salience.build(rebuiltTimeline);corruptSalience.__throwOnValidate=true;input.musicSalience=corruptSalience;
 let rebuiltSalience;assert.doesNotThrow(()=>{rebuiltSalience=ensureMusicSalience(input,rebuiltTimeline);});
 assert.notEqual(rebuiltSalience,corruptSalience);assert.equal(Salience.validate(rebuiltSalience,rebuiltTimeline).valid,true);
});
