'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.join(__dirname,'..');
const Observation=require(path.join(root,'web/analysis/run-observation.js'));

const measured=milliseconds=>({milliseconds,measured:true,status:'available',reason:null,source:'performance.now'});
const worker=(seconds,restored=false)=>({seconds,restored,profile:{attributes:{workerClockMeasured:true,workerClockStatus:'available',workerClockSource:'performance.now',workerClockReason:'private-worker-reason'}}});
function engine(overrides={}){
 return {quality:'precision',runtime:'Private backend /device/secret',modelId:'private-model-id',separationModel:{modelId:'private-separator-id',runtime:'onnxruntime-android-cpu',nativeModelPasses:1,restoredPassages:2},stages:{rhythm:worker(1.25),separation:worker(5),voice:worker(0,true),bass:worker(.5),recurrence:worker(.75)},resourceDiagnostics:{schemaVersion:1,kind:'analysis-pipeline-resources',stages:{rhythm:{},separation:{},voice:{},bass:{},recurrence:{}},scheduler:{status:'available',waitMilliseconds:125}},...overrides};
}
function input(overrides={}){return {analysisPerformed:true,engine:engine(),analysisTiming:measured(7000),choreographyTiming:measured(1000),totalTiming:measured(8500),...overrides};}

test('builds a bounded fresh-run observation from actual aggregate timings',()=>{
 const value=Observation.build(input());
 assert.equal(Observation.validate(value),true);
 assert.equal(value.runKind,'fresh-completed');
 assert.equal(value.timing.analysis.seconds,7);
 assert.equal(value.timing.choreography.seconds,1);
 assert.equal(value.timing.total.seconds,8.5);
 assert.deepEqual(value.analysis.implementation,{rhythmModelFamily:'beat-this-full',separationModelFamily:'deux',runtimeKind:'android-cpu-plus-web'});
 assert.deepEqual(value.analysis.cache,{restoredStageCount:1,restoredStageNames:['voice'],separationRestoredPassages:2});
 assert.deepEqual(value.analysis.stages.find(stage=>stage.stageId==='voice').timing,{source:'unavailable',status:'unavailable',seconds:null,reason:'restored-stage-zero-cost'});
 assert.deepEqual(value.resources,{status:'available',schedulerWaitSeconds:.125,observedStageCount:5});
 const withoutPassageCounter=Observation.build(input({engine:engine({separationModel:{runtime:'onnxruntime-web-wasm'}})}));
 assert.equal(withoutPassageCounter.analysis.cache.separationRestoredPassages,null);
});

test('uses a fixed primitive allowlist and excludes private engine/user data',()=>{
 const source=input({engine:engine({projectId:'private-project',name:'Private song',audioPath:'/secret/private.wav',lyrics:'private words',runtime:'backend /private/device',modelId:'private-model',separationModel:{modelId:'private-separator',runtime:'private-runtime',restoredPassages:2},diagnostics:{exception:'private exception'}})});
 const value=Observation.build(source),encoded=JSON.stringify(value);
 for(const privateValue of ['private-project','Private song','/secret/private.wav','private words','backend /private/device','private-model','private-separator','private-runtime','private exception'])assert.equal(encoded.includes(privateValue),false);
 assert.equal(encoded.includes('modelId'),false);
 assert.equal(Observation.completed(input({analysisPerformed:false})),null);
 assert.equal(Observation.completed(input({analysisTiming:measured(21600001)})),null);
 assert.equal(Observation.completed(input({engine:engine({stages:{...engine().stages,untrusted:worker(1)}})})),null);
});

test('records unavailable clocks as unavailable rather than zero-duration measurements',()=>{
 const value=Observation.build(input({analysisTiming:{milliseconds:0,measured:false,status:'unavailable',reason:'private reason',source:'unavailable'},choreographyTiming:{milliseconds:0,measured:false,status:'observed-error',reason:'private exception',source:'performance.now'},totalTiming:{milliseconds:0,measured:false,status:'unavailable',reason:'private reason',source:'unavailable'}}));
 assert.deepEqual(value.timing.analysis,{source:'unavailable',status:'unavailable',seconds:null,reason:'clock-unavailable'});
 assert.deepEqual(value.timing.choreography,{source:'performance.now',status:'observed-error',seconds:null,reason:'clock-observed-error'});
 assert.equal(value.timing.total.seconds,null);
 assert.equal(Observation.validate(value),true);
});

test('rejects modified output shapes, unknown values, and false restored-stage timing',()=>{
 const value=Observation.build(input());
 assert.throws(()=>Observation.validate({...value,projectId:'leak'}),/shape/);
 const invalid=JSON.parse(JSON.stringify(value));
 invalid.analysis.implementation.runtimeKind='private-runtime';
 assert.throws(()=>Observation.validate(invalid),/implementation/);
 const restored=JSON.parse(JSON.stringify(value));
 restored.analysis.stages.find(stage=>stage.restored).timing={source:'performance.now',status:'available',seconds:0,reason:null};
 assert.throws(()=>Observation.validate(restored),/Restored analysis stage timing/);
});

async function tick(){for(let index=0;index<4;index++)await new Promise(resolve=>setImmediate(resolve));}
async function runProduction(overrides={}){
 const runner=fs.readFileSync(path.join(root,'web/background/runner.js'),'utf8');
 const events=[],failures=[];let completed=null,tickCount=0;
 const freshMusic={analysisVersion:8,duration:2,engine:engine()};
 const request={projectId:'safe-project',name:'Private Song',duration:2,needAnalysis:true,settings:{analysisQuality:'precision'},...overrides.request};
 const fakeClock={mark:()=>({milliseconds:tickCount++*1000,source:'performance.now'}),measure:mark=>({milliseconds:Math.max(0,tickCount++*1000-mark.milliseconds),measured:true,status:'available',reason:null,source:'performance.now'})};
 const musicAnalyzer={analyze:async()=>{events.push('analyze');if(overrides.analyzeError)throw overrides.analyzeError;return overrides.music||freshMusic;}};
 // Cache reuse is permitted only when the saved result exposes the current
 // immutable analysis identity; fresh paths do not need this preflight stub.
 if(request.needAnalysis===false)musicAnalyzer.cacheIdentity=async()=>{events.push('identity');return request.music?.engine?.cacheIdentity||null;};
 const context={AbortController,DOMException,URL,location:{href:'https://appassets.androidplatform.net/background/runner.html?job=job'},navigator:{},console,setTimeout,clearTimeout,
  fetch:async()=>({ok:true,json:async()=>request}),
  MusicAnalyzer:musicAnalyzer,
  ShowCompiler:{generate:async()=>{events.push('compile');if(overrides.compileError)throw overrides.compileError;return overrides.result||{show:{version:'show-v1'},compiled:{sha256:'compiled-sha',frames:[1,2]}};}},
  BackgroundJob:{progress:()=>{},clearRunObservation:()=>{events.push('clear');return overrides.clearResult!==undefined?overrides.clearResult:true;},checkpoint:()=>{events.push('checkpoint');return true;},complete:(_id,encoded)=>{events.push('complete');completed=JSON.parse(encoded);return true;},failed:(_id,message,cancelled)=>{events.push('failed');failures.push({message,cancelled});}},
  LightForgeDiagnostics:{log:()=>{},progress:()=>{},protectText:()=>{}},LightForgeVersion:{name:'test'},VehicleProfile:{version:'test'},LightForgeDiagnosticClock:{create:()=>fakeClock},LightForgeAnalysisRunObservation:{completed:value=>Observation.completed(JSON.parse(JSON.stringify(value))),validate:value=>Observation.validate(JSON.parse(JSON.stringify(value)))}
 };
 context.window=context;
 vm.runInNewContext(runner,context,{filename:'runner.js'});
 await tick();return {completed,events,failures,freshMusic};
}

test('the production fresh path clears stale evidence then persists one observation only after compile succeeds',async()=>{
 const page=fs.readFileSync(path.join(root,'web/background/runner.html'),'utf8');
 assert.ok(page.indexOf('analysis/diagnostic-clock.js')<page.indexOf('analysis/analyzer.js'));
 assert.ok(page.indexOf('analysis/run-observation.js')<page.indexOf('runner.js'));
 const expectedCompiled={sha256:'compiled-sha',frames:[1,2]};
 const run=await runProduction({result:{show:{version:'show-v1'},compiled:expectedCompiled}});
 assert.deepEqual(run.events,['clear','analyze','checkpoint','compile','complete']);
 assert.ok(run.completed?.analysisRunObservation);
 assert.equal(Observation.validate(run.completed.analysisRunObservation),true);
 assert.deepEqual(run.completed.compiled,expectedCompiled);
 assert.deepEqual(run.completed.music,run.freshMusic);
 const encoded=JSON.stringify(run.completed.analysisRunObservation);
 for(const privateValue of ['Private Song','safe-project','Private backend','private-model-id','private-separator-id'])assert.equal(encoded.includes(privateValue),false);
});

test('fresh failed, cancelled, and compile-failed runs clear stale evidence but persist no observation',async()=>{
 const compileFailed=await runProduction({compileError:Error('compile failed')});
 assert.deepEqual(compileFailed.events,['clear','analyze','checkpoint','compile','failed']);
 assert.equal(compileFailed.completed,null);
 assert.equal(compileFailed.failures.length,1);
 const cancelled=await runProduction({analyzeError:new DOMException('cancelled','AbortError')});
 assert.deepEqual(cancelled.events,['clear','analyze','failed']);
 assert.equal(cancelled.completed,null);
 assert.equal(cancelled.failures[0].cancelled,true);
});

test('cached/reused music produces no fresh observation and does not invoke the fresh-clear bridge',async()=>{
 const cacheIdentity={schemaVersion:1,persistent:true,workId:'same-work',implementationFingerprint:'same-implementation',assetFingerprint:'same-assets',nativeRuntimeProfile:'wasm'};
 const cachedMusic={analysisVersion:8,duration:2,engine:engine({cacheIdentity})};
 const run=await runProduction({request:{needAnalysis:false,music:cachedMusic}});
 assert.deepEqual(run.events,['identity','checkpoint','compile','complete']);
 assert.equal(run.completed.analysisRunObservation,undefined);
 assert.deepEqual(run.completed.music,cachedMusic);
});
