'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const Timeline=require('../web/analysis/semantic-timeline.js');
const Recurrence=require('../web/analysis/recurrence.js');

const workerSource=fs.readFileSync(path.join(__dirname,'../web/analysis/worker.js'),'utf8');
const key='b'.repeat(64);

function fixture(cap){
 const music={duration:12,beats:[0,.5,1,1.5,2,2.5,3,3.5,4,4.5,5,5.5,6,6.5,7,7.5,8,8.5,9,9.5,10,10.5,11,11.5],
  downbeats:[0,2,4,6,8,10],beatDetails:[{time:0,barPosition:1,confidence:.9},{time:2,barPosition:1,confidence:.9},{time:4,barPosition:1,confidence:.9},{time:6,barPosition:1,confidence:.9},{time:8,barPosition:1,confidence:.9}],
  sections:[{start:0,end:4,energy:.42,confidence:.92,recurrenceGroup:'repeat-a',similarity:0,repetitionIndex:0},{start:4,end:8,energy:.28,confidence:.92,recurrenceGroup:'single-b',similarity:0,repetitionIndex:0},{start:8,end:12,energy:.64,confidence:.92,recurrenceGroup:'repeat-a',similarity:.992,repetitionIndex:1}],
  energy:new Array(60).fill(.5),energyStep:.2,phrases:[],vocals:{phrases:[],notes:[],accents:[]},bassNotes:[],bassAnalysis:{phrases:[]}};
 if(cap!==undefined)music.percussionAnalysis={source:'mix-feature-estimate',method:'bounded test evidence',inputStem:'mixture',inputStemSeparated:false,sourceSeparated:false,estimated:true,salienceCap:cap,
  events:[{time:2.04,kind:'kick',confidence:.52,strength:.55,estimated:true,salienceCap:cap}]};
 music.semanticTimeline=Timeline.build(music);
 return music;
}
function withTimelineCap(music,cap){
 const event=music.semanticTimeline.events.find(value=>value.type==='beat');
 assert.ok(event&&event.salience<=cap,'fixture cap must remain valid');
 event.salienceCap=cap;
 assert.equal(Timeline.validate(music.semanticTimeline).valid,true);
 return music;
}

function memoryStore(){
 const values=new Map(),invalidations=[];
 return {values,invalidations,read:async key=>values.get(key)||null,write:async(key,value)=>values.set(key,structuredClone(value)),invalidate:async keys=>{
  invalidations.push(keys.slice());for(const key of keys)values.delete(key);
 }};
}

async function run(options,value,store){
 const messages=[],imports=[];
 const context={console,performance:{now:()=>100},postMessage:value=>messages.push(value),
  LightForgeSemanticTimeline:Timeline,
  LightForgeAnalysisStore:{open:async()=>store}};
 context.importScripts=(...names)=>{imports.push(...names);if(names.includes('recurrence.js'))context.LightForgeRecurrence=Recurrence;};
 context.self=context;vm.createContext(context);
 vm.runInContext(workerSource,context,{filename:'worker.js'});
 await context.onmessage({data:{audioUrl:'memory://fixture',options:{...options,workId:key},stage:'recurrence',value}});
 const result=messages.find(message=>message.type==='result');
 const error=messages.find(message=>message.type==='error');
 if(error)throw Error(error.message);
 return {imports,messages,result:result?.value,restored:result?.restored};
}

test('recurrence worker stage is explicit, separately cached, and never leaks into the base checkpoint',async()=>{
 const handlerOffset=workerSource.indexOf('self.onmessage=');
 assert.ok(handlerOffset>0,'worker message handler must be present');
 assert.doesNotMatch(workerSource.slice(0,handlerOffset),/importScripts\([^)]*recurrence\.js/,
  'the normal worker bootstrap must not load recurrence analysis');
 assert.match(workerSource,/if\(!self\.LightForgeRecurrence\)importScripts\('recurrence\.js'\);/,
  'only the explicit recurrence stage may load the sidecar engine');
 const store=memoryStore(),firstInput=fixture(),first=await run({recurrenceAnalysis:true},firstInput,store);
 assert.ok(first.imports.includes('recurrence.js'));
 assert.equal(first.restored,false);
 assert.ok(first.result?.recurrenceEvidence);
 assert.ok(first.result?.recurrenceSidecar);
 assert.deepEqual(JSON.parse(JSON.stringify(first.result?.recurrenceAnalysis)),{schemaVersion:1,enabled:true,cacheDomain:'recurrence',engineVersion:Recurrence.version,sidecarSchemaVersion:1,
  clock:first.result.recurrenceSidecar.clock,duration:12,timelineFingerprint:first.result.recurrenceSidecar.timelineFingerprint,evidenceFingerprint:first.result.recurrenceSidecar.evidenceFingerprint});
 const record=store.values.get('recurrence');
 assert.equal(record.kind,'recurrence-analysis-cache');
 assert.equal(record.timelineFingerprint,first.result.recurrenceSidecar.timelineFingerprint);
 assert.equal(Recurrence.validate(record.sidecar,first.result.semanticTimeline,record.evidence).valid,true);

 const second=await run({recurrenceAnalysis:true},fixture(),store);
 assert.equal(second.restored,true,'a matching recurrence record must restore without recomputing the sidecar');
 assert.deepEqual(second.result.recurrenceSidecar,first.result.recurrenceSidecar);

 const defaultResult=await run({},structuredClone(first.result),store);
 assert.equal(defaultResult.result.recurrenceAnalysis,undefined);
 assert.equal(defaultResult.result.recurrenceEvidence,undefined);
 assert.equal(defaultResult.result.recurrenceSidecar,undefined);

 const persisted=vm.runInNewContext(workerSource+'\n;persistableAnalysis(value);',{value:first.result,self:{},importScripts(){}});
 assert.equal(persisted.recurrenceAnalysis,undefined);
 assert.equal(persisted.recurrenceEvidence,undefined);
 assert.equal(persisted.recurrenceSidecar,undefined);
});

test('recurrence cache rejects cap-only and wrong-clock changes, then rebuilds only from canonical evidence',async()=>{
 const store=memoryStore(),original=await run({recurrenceAnalysis:true},withTimelineCap(fixture(),.50),store);
 const originalFingerprint=original.result.recurrenceAnalysis.timelineFingerprint;
 const recapped=await run({recurrenceAnalysis:true},withTimelineCap(fixture(),.51),store);
 assert.equal(recapped.restored,false,'a cap-only canonical timeline mutation cannot reuse the prior recurrence cache');
 assert.notEqual(recapped.result.recurrenceAnalysis.timelineFingerprint,originalFingerprint);
 assert.ok(store.invalidations.some(keys=>keys.includes('recurrence')));
 assert.equal(Recurrence.validate(recapped.result.recurrenceSidecar,recapped.result.semanticTimeline,recapped.result.recurrenceEvidence).valid,true);

 const reweighted=withTimelineCap(fixture(),.51);
 reweighted.energy[0]=.49;
 const reweightedResult=await run({recurrenceAnalysis:true},reweighted,store);
 assert.equal(reweightedResult.restored,false,'a feature-only evidence mutation cannot reuse the prior recurrence cache');
 assert.equal(reweightedResult.result.recurrenceAnalysis.timelineFingerprint,recapped.result.recurrenceAnalysis.timelineFingerprint);
 assert.notEqual(reweightedResult.result.recurrenceAnalysis.evidenceFingerprint,recapped.result.recurrenceAnalysis.evidenceFingerprint);

 const wrongClock=withTimelineCap(fixture(),.51),canonicalClock=wrongClock.semanticTimeline.clock;
 wrongClock.semanticTimeline.clock='resampled-clock';
 assert.equal(Timeline.validate(wrongClock.semanticTimeline).valid,false,'the test must begin with a rejected clock');
 const repaired=await run({recurrenceAnalysis:true},wrongClock,store);
 assert.equal(repaired.result.semanticTimeline.clock,canonicalClock,'worker must rebuild canonical evidence rather than accept a wrong-clock timeline');
 assert.equal(repaired.result.recurrenceAnalysis.clock,canonicalClock);
 assert.equal(Recurrence.validate(repaired.result.recurrenceSidecar,repaired.result.semanticTimeline,repaired.result.recurrenceEvidence).valid,true);
});

test('analyzer adds the recurrence stage only for an explicit analysis option',()=>{
 const analyzer=fs.readFileSync(path.join(__dirname,'../web/analysis/analyzer.js'),'utf8');
 assert.match(analyzer,/const stagesFor=options=>options\?\.recurrenceAnalysis===true\?\[\.\.\.BASE_STAGES,'recurrence'\]:BASE_STAGES;/);
 assert.match(analyzer,/for\(const stage of stages\)/);
});
