'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const VocalSemantics=require('../web/analysis/vocal-semantics.js');
const Timeline=require('../web/analysis/semantic-timeline.js');

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

test('links only exact existing vocal timeline events and fails closed on a changed clock',()=>{
 const input=fixture(),sidecar=VocalSemantics.build(input),timeline=Timeline.build(input),link=VocalSemantics.linkTimeline(sidecar,timeline);
 assert.equal(link.phrases.length,sidecar.phrases.length);
 assert.equal(link.notes.length,sidecar.notes.length);
 assert.equal(link.articulations.length,sidecar.articulations.length);
 assert.match(link.timelineFingerprint,/^vt1-[0-9a-f]{16}$/);
 const retuned=structuredClone(timeline);retuned.events.find(value=>value.type==='vocal_note').midi=67;
 assert.notEqual(VocalSemantics.linkTimeline(sidecar,retuned).timelineFingerprint,link.timelineFingerprint,'a semantically changed but time-identical timeline must not retain the old link binding');
 const recapped=structuredClone(timeline);recapped.events.find(value=>value.type==='vocal_accent').salienceCap=.42;
 assert.notEqual(VocalSemantics.linkTimeline(sidecar,recapped).timelineFingerprint,link.timelineFingerprint,'a cap-only timeline mutation must invalidate the vocal link binding');
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
