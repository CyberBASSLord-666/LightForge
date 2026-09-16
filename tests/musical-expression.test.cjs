'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{JSDOM}=require('jsdom');
const root=path.resolve(__dirname,'..'),runWorker=require('./worker-harness.cjs');
const Engine=require('../web/engine/show-engine.js'),Timeline=require('../web/analysis/semantic-timeline.js'),Salience=require('../web/analysis/salience.js'),Vocal=require('../web/analysis/vocal-semantics.js'),Recurrence=require('../web/analysis/recurrence.js');
const expressionKeys=['vocalSemanticEnrichment','recurrenceAnalysis','semanticChoreography','vocalChoreography','motifEvolution'];
function fixture(){
 const duration=24,beats=Array.from({length:48},(_,i)=>i*.5);
 return {analysisVersion:8,duration,bpm:120,beatConfidence:.94,beats,downbeats:beats.filter((_,i)=>i%4===0),beatDetails:beats.map((time,i)=>({time,confidence:.94,barPosition:i%4+1,localBpm:120})),waveform:Array(240).fill(.65),energy:Array(240).fill(.65),energyStep:.1,activityRanges:[{start:0,end:24}],
  sections:[{start:0,end:8,energy:.42,confidence:.92,recurrenceGroup:'repeat-a',repetitionIndex:0},{start:8,end:16,energy:.28,confidence:.92},{start:16,end:24,energy:.64,confidence:.92,recurrenceGroup:'repeat-a',similarity:.992,repetitionIndex:1}],phrases:[],onsets:[{time:1.2,strength:.8,band:'mid'}],impacts:[{time:16,strength:.9,kind:'transition'}],
  vocals:{available:true,presence:'detected',source:'separated-vocals',sourceSeparated:true,confidence:.94,phrases:[{start:1,end:4,releaseTime:3.8,confidence:.94,strength:.9,kind:'singing'}],notes:[{start:1.5,end:2.8,midi:60,confidence:.92,strength:.88},{start:3,end:3.7,midi:67,confidence:.92,strength:.88}],accents:[{time:1.2,kind:'syllabic-accent',confidence:.95,strength:.97,source:'separated-vocals'}],pitchContour:{step:.04,midi:[],confidence:[]},envelope:[],envelopeStep:.02},
  bassNotes:[{start:2,end:2.8,confidence:.96,strength:.94,midi:40}],bassAnalysis:{confidence:.96,phrases:[{start:2,end:2.8,confidence:.96,strength:.94}]}};
}
function harness(saved){
 const dom=new JSDOM(fs.readFileSync(path.join(root,'web/index.html'),'utf8'),{url:'https://lightforge.test/',runScripts:'outside-only'}),w=dom.window,d=w.document,calls=[];
 w.scrollTo=()=>{};w.requestAnimationFrame=()=>0;w.cancelAnimationFrame=()=>{};w.matchMedia=()=>({matches:true,addEventListener(){}});w.HTMLMediaElement.prototype.pause=function(){};w.HTMLMediaElement.prototype.load=function(){};Object.defineProperty(w.HTMLMediaElement.prototype,'readyState',{get:()=>4});
 w.VehiclePreview=class{render(){}setCamera(){}setStage(){}setQuality(){}resize(){}};
 Object.assign(w,{LightForgeVersion:require('../web/version.js'),ShowEngine:Engine,VehicleProfile:require('../web/engine/vehicle-profile.js'),MusicCues:require('../web/engine/music-cues.js'),LightForgeSemanticTimeline:Timeline,LightForgeMusicSalience:Salience,LightForgeVocalSemantics:Vocal,LightForgeRecurrence:Recurrence});
 w.ShowCompiler={generate:(music,settings)=>runWorker(path.join(root,'web/engine'),{action:'generate',music,settings}),restore:(compiled,music,settings)=>runWorker(path.join(root,'web/engine'),{action:'restore',compiled,music,settings})};
 w.MusicAnalyzer={analyze:async(_url,options)=>{calls.push(options);return fixture();}};
 w.Android={pickAudio(){},getBootstrap:()=>JSON.stringify({projects:[]}),saveProject:()=>true};w.fetch=async()=>({ok:true,json:async()=>structuredClone(saved)});
 w.eval(fs.readFileSync(path.join(root,'web/app.js'),'utf8'));
 return {dom,w,d,calls,app:w.LightForgeApp};
}
test('new shows enable expression while saved projects keep original frames and explicit off choices',async()=>{
 const raw=fixture(),h=harness({settings:{dance:'off',seed:17},music:raw});
 try{
  for(const key of expressionKeys)assert.equal(h.app.state.settings[key],true,'new Studio default '+key);
  await h.app.selectProject({id:'saved',duration:24,audioUrl:'song.wav',projectUrl:'project.json'});
  for(const key of expressionKeys)assert.equal(h.app.state.settings[key],false,'historical absence stays off '+key);
  const old=h.app.state.show.frames.slice(),originalMusic=JSON.stringify(h.app.state.music),baseline=Engine.generate(raw,h.app.state.settings);
  assert.deepEqual(Array.from(old),Array.from(baseline.frames));
  h.d.getElementById('musicalExpression').checked=true;await h.d.getElementById('musicalExpression').onchange();
  assert.equal(h.calls.length,0,'expression enrichment must never invoke model analysis');assert.equal(h.app.state.needAnalysis,false);assert.equal(h.app.state.analysisExecutionMode,'resume');
  const active=h.app.state.show,activeFrames=active.frames.slice();
  assert.equal(active.validation.valid,true);assert.equal(active.choreography.vocalChoreography.active,true);assert.equal(active.choreography.semanticStrategy.active,true);assert.equal(active.choreography.motifEvolution.active,true);
  assert.ok(active.choreography.vocalChoreography.applied.matchedEventCount>0);assert.ok(active.choreography.motifEvolution.appliedSectionCount>0);assert.notDeepEqual(Array.from(activeFrames),Array.from(old));
  assert.equal(Vocal.validate(h.app.state.music.vocalSemantics,h.app.state.music).valid,true);assert.equal(Recurrence.validate(h.app.state.music.recurrenceSidecar,h.app.state.music.semanticTimeline,h.app.state.music.recurrenceEvidence).valid,true);
  await h.app.undo();assert.deepEqual(Array.from(h.app.state.show.frames),Array.from(old));assert.equal(JSON.stringify(h.app.state.music),originalMusic);
  await h.app.redo();assert.deepEqual(Array.from(h.app.state.show.frames),Array.from(activeFrames));
  h.d.getElementById('musicalExpression').checked=false;await h.d.getElementById('musicalExpression').onchange();assert.deepEqual(Array.from(h.app.state.show.frames),Array.from(old));assert.equal(h.calls.length,0);
  await h.app.selectProject({id:'new',duration:24,audioUrl:'new.wav'},true);for(const key of expressionKeys)assert.equal(h.app.state.settings[key],true,'new project selects recommendations');
  await h.app.generate();assert.equal(h.calls.length,1);assert.equal(h.calls[0].vocalSemanticEnrichment,true);assert.equal(h.calls[0].recurrenceAnalysis,true);
 }finally{h.w.close();}
});
test('incomplete saved evidence requests resumable enrichment and keeps explicit opt-outs on restore',async()=>{
 const h=harness({settings:{dance:'off',vocalSemanticEnrichment:false,recurrenceAnalysis:false,vocalChoreography:false,semanticChoreography:false,motifEvolution:false},music:{...fixture(),analysisVersion:5}});
 try{
  await h.app.selectProject({id:'old',duration:24,audioUrl:'old.wav',projectUrl:'project.json'});
  assert.equal(h.d.getElementById('musicalExpression').checked,false);
  h.d.getElementById('musicalExpression').checked=true;await h.d.getElementById('musicalExpression').onchange();
  assert.equal(h.app.state.needAnalysis,true);assert.equal(h.app.state.analysisExecutionMode,'resume');assert.equal(h.calls.length,0);
 }finally{h.w.close();}
});
test('toggling a chroma-backed saved arrangement off and on preserves its exact recurrence and frames',async()=>{
 const music=fixture();music.sections=music.sections.map((section,index)=>({...section,energy:index===1?.34:.58,recurrenceGroup:undefined,similarity:0,repetitionIndex:0}));
 const chroma=[];for(let frame=0;frame<240;frame++)for(let bin=0;bin<12;bin++)chroma.push(bin===(frame>=80&&frame<160?5:0)?1:.015);
 music.semanticTimeline=Timeline.build(music);music.musicSalience=Salience.build(music.semanticTimeline);music.vocalSemantics=Vocal.build(music);music.vocalSemanticLinks=Vocal.linkTimeline(music.vocalSemantics,music.semanticTimeline);
 music.recurrenceEvidence=Recurrence.captureEvidence({...music,chroma,chromaStep:.1},music.semanticTimeline);music.recurrenceSidecar=Recurrence.build(music.semanticTimeline,music.recurrenceEvidence);
 const sidecar=music.recurrenceSidecar;music.recurrenceAnalysis={schemaVersion:1,enabled:true,cacheDomain:'recurrence',engineVersion:Recurrence.version,sidecarSchemaVersion:sidecar.schemaVersion,clock:sidecar.clock,duration:sidecar.duration,timelineFingerprint:sidecar.timelineFingerprint,evidenceFingerprint:sidecar.evidenceFingerprint};
 assert.equal(sidecar.summary.evidence.chromaEnergyMotifCount,1);assert.equal(music.chroma,undefined,'real worker stores chroma in the evidence receipt only');
 const h=harness({settings:{dance:'off',...Object.fromEntries(expressionKeys.map(key=>[key,true]))},music});
 try{
  await h.app.selectProject({id:'chroma',duration:24,audioUrl:'chroma.wav',projectUrl:'project.json'});const frames=h.app.state.show.frames.slice(),evidence=JSON.stringify(h.app.state.music.recurrenceEvidence);
  const toggle=h.d.getElementById('musicalExpression');toggle.checked=false;await toggle.onchange();toggle.checked=true;await toggle.onchange();
  assert.equal(JSON.stringify(h.app.state.music.recurrenceEvidence),evidence);assert.deepEqual(Array.from(h.app.state.show.frames),Array.from(frames));assert.equal(h.calls.length,0);
 }finally{h.w.close();}
});
test('optional recurrence limits leave completed vocal evidence usable without a neural rerun',async()=>{
 const h=harness({settings:{dance:'off'},music:fixture()});
 try{
  await h.app.selectProject({id:'bounded',duration:24,audioUrl:'bounded.wav',projectUrl:'project.json'});
  h.w.LightForgeRecurrence={...Recurrence,captureEvidence(){throw Error('Invalid energy evidence length');}};
  const toggle=h.d.getElementById('musicalExpression');toggle.checked=true;await toggle.onchange();
  assert.equal(h.calls.length,0);assert.equal(h.app.state.needAnalysis,false);assert.equal(h.app.state.show.validation.valid,true);assert.equal(h.app.state.show.choreography.vocalChoreography.active,true);
  assert.equal(h.app.state.music.recurrenceAnalysis.enabled,false);assert.equal(h.app.state.show.choreography.motifEvolution.active,false);assert.equal(h.app.state.music.recurrenceSidecar,undefined);
 }finally{h.w.close();}
});
