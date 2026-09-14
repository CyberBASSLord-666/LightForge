'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const source=fs.readFileSync(process.env.LIGHTFORGE_RUNNER_SOURCE||path.join(__dirname,'..','web/background/runner.js'),'utf8');
const E1='11111111-1111-4111-8111-111111111111',E2='22222222-2222-4222-8222-222222222222';
const wasmIdentity={schemaVersion:1,persistent:true,verified:true,execution:'wasm-v1',workId:'wasm-work',implementationFingerprint:'wasm-implementation',assetFingerprint:'wasm-assets',nativeRuntimeProfile:'wasm',refreshEpoch:null};
const nativeIdentity={schemaVersion:1,persistent:true,verified:true,execution:'native-deux-v1',workId:'native-work',implementationFingerprint:'native-implementation',assetFingerprint:'native-assets',nativeRuntimeProfile:'native-deux-test-v1',refreshEpoch:null};

function run(request,{cacheIdentity=wasmIdentity,onAnalyze=()=>({duration:12,analysisVersion:8,engine:{cacheIdentity:wasmIdentity}}),nativeDeux}={}){
 let complete,fail;const done=new Promise((resolve,reject)=>{complete=resolve;fail=reject;}),events=[];
 const context={URL,AbortController,DOMException,setTimeout,clearTimeout,navigator:{},location:{href:'https://appassets.androidplatform.net/background/runner.html?job=job'},
  fetch:async()=>({ok:true,json:async()=>request}),
  MusicAnalyzer:{async cacheIdentity(options){events.push({type:'identity',options});return cacheIdentity;},async analyze(url,options){events.push({type:'analyze',options});return onAnalyze(url,options);}},
  ShowCompiler:{async generate(){events.push({type:'compose'});return {compiled:{sha256:'frames'},show:{version:'planner'}};}},
  LightForgeVersion:{name:'test'},VehicleProfile:{version:'test'},LightForgeDiagnostics:{log(){},progress(){},protectText(){}},
  BackgroundJob:{clearRunObservation(){events.push({type:'clear'});return true;},progressInfo(){},checkpoint(){events.push({type:'checkpoint'});return true;},complete(id,body){events.push({type:'complete'});complete(JSON.parse(body));return true;},failed(id,message){fail(Error(message));}},
  LightForgeNativeDeux:nativeDeux
 };
 context.window=context;vm.runInNewContext(source,context);return done.then(saved=>({saved,events}));
}

function request(extra={}){return {projectId:'show',name:'Show',duration:12,analysisIdentity:'a'.repeat(64),needAnalysis:false,settings:{analysisQuality:'precision',sensitivity:.82},...extra};}

test('fresh lineage E1 cannot reuse a completed E2 cache identity',async()=>{
 const savedIdentity={...wasmIdentity,refreshEpoch:E2};
 const {events}=await run(request({analysisExecutionMode:'fresh',analysisRefreshEpoch:E1,music:{duration:12,analysisVersion:8,engine:{cacheIdentity:savedIdentity}}}),{cacheIdentity:savedIdentity,onAnalyze:(url,options)=>{
  assert.equal(options.analysisRefreshEpoch,E1);return {duration:12,analysisVersion:8,engine:{cacheIdentity:{...wasmIdentity,refreshEpoch:E1}}};
 }});
 assert.deepEqual(events.map(event=>event.type),['clear','analyze','checkpoint','compose','complete']);
});

test('persisted WASM retry rejects native cache evidence and carries fallback diagnostics',async()=>{
 let nativeCreated=0;
 const {events}=await run(request({analysisExecutionMode:'resume',analysisEffectiveExecution:'wasm-v1',analysisNativeFallbackReason:'native-deux-fallback',music:{duration:12,analysisVersion:8,engine:{cacheIdentity:nativeIdentity}}}),{
  cacheIdentity:nativeIdentity,
  nativeDeux:{analysisCacheProfile:'native-deux-test-v1',create(){nativeCreated++;throw Error('native must be fenced');}},
  onAnalyze:(url,options)=>{assert.equal(options.nativePredict,undefined);assert.equal(options.analysisNativeFallback.attemptedExecution,'native-deux-v1');assert.equal(options.analysisNativeFallback.reason,'native-deux-fallback');return {duration:12,analysisVersion:8,engine:{cacheIdentity:wasmIdentity,nativeFallback:options.analysisNativeFallback}};}
 });
 assert.equal(nativeCreated,0);assert.deepEqual(events.map(event=>event.type),['clear','analyze','checkpoint','compose','complete']);
});

test('only a literal boolean false may skip new analysis',async()=>{
 const {events}=await run(request({needAnalysis:'false',music:{duration:12,analysisVersion:8,engine:{cacheIdentity:wasmIdentity}}}));
 assert.deepEqual(events.map(event=>event.type),['clear','analyze','checkpoint','compose','complete']);
});

test('service reads the durable runtime fence before allocating optional native tasks',()=>{
 const service=fs.readFileSync(process.env.LIGHTFORGE_SERVICE_SOURCE||path.join(__dirname,'..','android/src/com/cyberbasslord/lightforge/AnalysisService.java'),'utf8');
 const request=service.indexOf('JSONObject request=AnalysisJobStore.request'),fence=service.indexOf('boolean forceWasm="wasm-v1"'),passage=service.indexOf('if(!forceWasm&&!balanced)try{passage=new NativePassageTask'),mdx=service.indexOf('if(balanced&&!forceWasm)try{mdx=new NativeMdxTask');
 assert.ok(request>=0&&fence>request&&passage>fence&&mdx>passage,'native allocation must be fenced by the bound frozen request');
 assert.match(service,/persistNativeFallback\(jobId,"native-deux-fallback"\)/,'precision constructor failures must persist a WASM fence before the WebView starts');
 assert.match(service,/persistNativeFallback\(jobId,"native-mdx-fallback"\)/,'balanced constructor failures must persist a WASM fence before the WebView starts');
 assert.match(service,/if\(!forceWasm&&!balanced\)/,'balanced work must not allocate the unused precision native task');
 assert.match(service,/ownerTask==null\|\|!owns\(id\)/,'forced-WASM bridge calls must fail safely without a native task');
});
