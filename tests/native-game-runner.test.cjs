'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'..','web/background/runner.js'),'utf8');
const profiles={deux:'native-deux-onnxruntime-android-1.25.1-v1',mdx:'native-mdx-onnxruntime-android-1.25.1-v1',game:'native-game-onnxruntime-android-1.25.1-v1'};
const identity=(execution='wasm-v1',nativeRuntimeProfile='wasm')=>({schemaVersion:1,persistent:true,verified:true,execution,nativeRuntimeProfile,refreshEpoch:null,workId:'work-'+execution,implementationFingerprint:'implementation-'+nativeRuntimeProfile,assetFingerprint:'assets'});
async function runner({quality='precision',available=['deux','mdx','game'],request:overrides={},expected,analyze,bridge:bridgeOverrides={},factories={}}={}){
 const calls={factories:[],queries:[],analysis:[],persist:[],checkpoint:[],compose:0},request={projectId:'native-game-test',name:'Native GAME test',duration:12,analysisIdentity:'a'.repeat(64),needAnalysis:true,settings:{analysisQuality:quality},...overrides};
 let done;const finished=new Promise(resolve=>{done=resolve;});
 const context={URL,AbortController,DOMException,setTimeout,location:{href:'https://appassets.androidplatform.net/background/runner.html?job=job'},fetch:async()=>({ok:true,json:async()=>request}),LightForgeVersion:{name:'test'},VehicleProfile:{version:'test'},
  MusicAnalyzer:{cacheIdentity:async options=>{calls.queries.push(options);return expected;},analyze:async(url,options)=>{calls.analysis.push(options);if(analyze)return analyze(options,calls);return {duration:12,analysisVersion:8,engine:{cacheIdentity:identity()}};}},
  ShowCompiler:{generate:async()=>{calls.compose++;return {compiled:{sha256:'frames'},show:{version:'planner'}};}},
  BackgroundJob:{clearRunObservation:()=>true,progressInfo(){},checkpoint(_id,body){calls.checkpoint.push(JSON.parse(body));return true;},markAnalysisWasmFallbackWithExecution(id,reason,attemptedExecution){calls.persist.push({id,reason,attemptedExecution});return true;},complete(_id,body){done({saved:JSON.parse(body)});return true;},failed(_id,message,cancelled){done({error:message,cancelled});},...bridgeOverrides}
 };
 for(const [name,key] of [['LightForgeNativeDeux','deux'],['LightForgeNativeMdx','mdx'],['LightForgeNativeGame','game']])context[name]={analysisCacheProfile:profiles[key],create(){calls.factories.push(key);if(factories[key])return factories[key]();if(!available.includes(key))return undefined;return Object.assign(async()=>{}, {analysisCacheProfile:profiles[key]});}};
 context.window=context;vm.runInNewContext(source,context);return {...await finished,calls};
}
test('runner supplies native GAME alone or the correctly ordered separator/GAME profile without exposing callbacks in cache probes',async()=>{
 for(const [quality,available,expectedProfile,hasDeux,hasMdx,hasGame] of [
  ['precision',['game'],profiles.game,false,false,true],
  ['precision',['deux','game'],profiles.deux+'+'+profiles.game,true,false,true],
  ['balanced',['mdx','game'],profiles.mdx+'+'+profiles.game,false,true,true],
  ['precision',['deux'],profiles.deux,true,false,false],
  ['balanced',['mdx'],profiles.mdx,false,true,false],
  ['precision',[],undefined,false,false,false]
 ]){
  const h=await runner({quality,available});assert.equal(h.error,undefined);const options=h.calls.analysis[0];assert.equal(options.nativeRuntimeProfile,expectedProfile);assert.ok(!expectedProfile||expectedProfile.length<=160);assert.equal(typeof options.nativePredict==='function',hasDeux);assert.equal(typeof options.nativeMdx==='function',hasMdx);assert.equal(typeof options.nativeGame==='function',hasGame);assert.equal(typeof options.onNativeFallback==='function',hasDeux||hasMdx||hasGame);
 }
});
test('runner reuses only exact current GAME and combined completed cache identities without probing native availability',async()=>{
 for(const [quality,execution,profile] of [['precision','native-game-v1',profiles.game],['balanced','native-game-v1',profiles.game],['precision','native-deux-v1+native-game-v1',profiles.deux+'+'+profiles.game],['balanced','native-mdx-v1+native-game-v1',profiles.mdx+'+'+profiles.game]]){
  const expected=identity(execution,profile),h=await runner({quality,expected,request:{needAnalysis:false,music:{duration:12,analysisVersion:8,engine:{cacheIdentity:expected}}}});assert.equal(h.error,undefined);assert.equal(h.calls.analysis.length,0);assert.deepEqual(h.calls.factories,[]);assert.equal(h.calls.queries.length,1);assert.equal(h.calls.queries[0].cacheIdentityExecution,execution);assert.equal(h.calls.queries[0].cacheIdentityNativeRuntimeProfile,profile);assert.equal(h.calls.queries[0].nativeGame,undefined);assert.equal(h.calls.queries[0].nativePredict,undefined);
 }
});
test('runner rebuilds GAME caches for wrong quality, profile ordering, revision, and changed implementation identity',async()=>{
 for(const [quality,execution,profile,expected] of [
  ['precision','native-mdx-v1+native-game-v1',profiles.mdx+'+'+profiles.game,null],
  ['balanced','native-deux-v1+native-game-v1',profiles.deux+'+'+profiles.game,null],
  ['precision','native-deux-v1+native-game-v1',profiles.game+'+'+profiles.deux,null],
  ['precision','native-game-v1',profiles.game+'-stale',null],
  ['precision','native-game-v1',profiles.game,{...identity('native-game-v1',profiles.game),implementationFingerprint:'new-implementation'}]
 ]){const h=await runner({quality,expected,request:{needAnalysis:false,music:{duration:12,analysisVersion:8,engine:{cacheIdentity:identity(execution,profile)}}}});assert.equal(h.error,undefined);assert.equal(h.calls.analysis.length,1);}
});
test('runner persists the entire attempted composite execution, not merely the stage that requested fallback',async()=>{
 const attemptedExecution='native-deux-v1+native-game-v1',h=await runner({analyze:async options=>{assert.equal(await options.onNativeFallback({attemptedExecution,reason:'native-game-fallback'}),true);return {duration:12,analysisVersion:8,engine:{cacheIdentity:identity()}};}});
 assert.equal(h.error,undefined);assert.deepEqual(h.calls.persist,[{id:'job',reason:'native-game-fallback',attemptedExecution}]);
});
test('runner restores persisted GAME fallback solely under WASM and rejects prior native completed caches',async()=>{
 const attemptedExecution='native-deux-v1+native-game-v1',nativeIdentity=identity(attemptedExecution,profiles.deux+'+'+profiles.game),lineage={analysisEffectiveExecution:'wasm-v1',analysisNativeFallbackReason:'native-game-fallback',analysisNativeAttemptedExecution:attemptedExecution};
 const h=await runner({expected:nativeIdentity,request:{...lineage,needAnalysis:false,music:{duration:12,analysisVersion:8,engine:{cacheIdentity:nativeIdentity}}}});assert.equal(h.error,undefined);assert.deepEqual(h.calls.factories,[]);assert.deepEqual(h.calls.queries,[]);const options=h.calls.analysis[0];assert.equal(options.nativeGame,undefined);assert.equal(options.nativePredict,undefined);assert.equal(options.nativeMdx,undefined);assert.equal(options.nativeRuntimeProfile,undefined);assert.deepEqual(JSON.parse(JSON.stringify(options.analysisNativeFallback)),{attemptedExecution,reason:'native-game-fallback'});
 const cached=identity(),reuse=await runner({expected:cached,request:{...lineage,needAnalysis:false,music:{duration:12,analysisVersion:8,engine:{cacheIdentity:cached}}}});assert.equal(reuse.error,undefined);assert.equal(reuse.calls.analysis.length,0);assert.equal(reuse.calls.queries[0].cacheIdentityExecution,'wasm-v1');assert.deepEqual(reuse.calls.factories,[]);
});
test('runner refuses invalid persisted GAME lineage before cache reuse or native availability',async()=>{
 for(const lineage of [{analysisNativeFallbackReason:'native-game-fallback'}, {analysisNativeFallbackReason:'native-game-fallback',analysisNativeAttemptedExecution:'native-deux-v1'}, {analysisNativeFallbackReason:'native-mdx-fallback',analysisNativeAttemptedExecution:'native-game-v1'}, {analysisNativeFallbackReason:'native-game-fallback',analysisNativeAttemptedExecution:'native-mdx-v1+native-game-v1'}]){const h=await runner({request:{analysisEffectiveExecution:'wasm-v1',...lineage}});assert.match(h.error,/lineage is invalid/);assert.equal(h.calls.analysis.length,0);assert.deepEqual(h.calls.factories,[]);assert.deepEqual(h.calls.queries,[]);}
});
test('older fallback bridge cannot truncate GAME composite lineage, while legacy separator-only fallback remains usable',async()=>{
 let legacyCalls=0;
 const bridge={markAnalysisWasmFallbackWithExecution:undefined,markAnalysisWasmFallback(){legacyCalls++;return true;}},analyze=attemptedExecution=>async options=>{await options.onNativeFallback({attemptedExecution,reason:attemptedExecution.includes('game')?'native-game-fallback':'native-deux-fallback'});return {duration:12,analysisVersion:8,engine:{cacheIdentity:identity()}};};
 const game=await runner({bridge,analyze:analyze('native-deux-v1+native-game-v1')});assert.match(game.error,/singing fallback execution checkpoint is unavailable/);assert.equal(legacyCalls,0);assert.equal(game.calls.compose,0);
 const legacy=await runner({available:['deux'],bridge,analyze:analyze('native-deux-v1')});assert.equal(legacy.error,undefined);assert.equal(legacyCalls,1);
});
test('native GAME construction failure clears all native callbacks and profile before analysis',async()=>{
 const h=await runner({factories:{game(){throw Error('bridge unavailable');}}});assert.equal(h.error,undefined);const options=h.calls.analysis[0];assert.equal(options.nativePredict,undefined);assert.equal(options.nativeMdx,undefined);assert.equal(options.nativeGame,undefined);assert.equal(options.nativeRuntimeProfile,undefined);assert.equal(options.onNativeFallback,undefined);
});
test('runner never compiles or commits after an unretired native GAME failure',async()=>{
 const h=await runner({analyze:async()=>{throw Object.assign(Error('Native singing cleanup could not be confirmed'),{code:'native-game-retirement-pending'});}});assert.match(h.error,/cleanup could not be confirmed/);assert.equal(h.calls.compose,0);assert.deepEqual(h.calls.checkpoint,[]);assert.deepEqual(h.calls.persist,[]);
});
