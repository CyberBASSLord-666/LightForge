'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const Routing=require('../web/analysis/stem-routing.js');
const workerSource=fs.readFileSync(path.join(__dirname,'../web/analysis/worker.js'),'utf8');
const key='stem-12345678-1234-1234-1234-123456789abc';

async function restoreCachedBass(stemRouting){
 const messages=[],writes=[],imports=[];
 const cached={duration:2,stemCache:{key},separation:{modelId:'deux-test-model'},semanticTimeline:{valid:true,events:[]},musicSalience:{valid:true,events:[],summary:{context:{profile:'balanced'}}}};
 if(stemRouting)cached.stemRouting=stemRouting;
 const context={
  importScripts:(...names)=>imports.push(...names),
  postMessage:value=>messages.push(value),
  fetch:async()=>({json:async()=>({precision:{},balanced:{},frontend:{}})}),
  performance:{now:()=>0},
  LightForgeStemRouting:Routing,
  LightForgeSemanticTimeline:{validate:value=>({valid:value?.valid===true}),build:()=>({valid:true,events:[]})},
  LightForgeMusicSalience:{validate:value=>({valid:value?.valid===true}),build:()=>({valid:true,events:[],summary:{context:{profile:'balanced'}}})},
  LightForgeAnalysisStore:{open:async()=>({read:async()=>cached,write:async(stage,value)=>writes.push({stage,value})})}
 };
 context.self=context;vm.runInNewContext(workerSource,context,{filename:'worker.js'});
 await context.self.onmessage({data:{audioUrl:'memory://fixture',options:{},stage:'bass',value:{}}});
 return {imports,messages,writes};
}

test('worker restores missing routing metadata without rerunning models and preserves a valid contract',async()=>{
 const missing=await restoreCachedBass();
 assert.ok(missing.imports.includes('stem-routing.js'));
 assert.match(workerSource,/const stemRoutingPhase=telemetry\.begin\('stem\.routing'\);\s*\n const stemRouting=ensureStemRouting\(result\);/);
 assert.equal(missing.writes.length,1);
 const restored=missing.messages.find(message=>message.type==='result')?.value;
 assert.ok(restored?.stemRouting);
 assert.equal(Routing.validate(restored.stemRouting).valid,true);
 assert.deepEqual(restored.stemRouting.stems.map(stem=>stem.role),['accompaniment','combined-vocals']);
 const valid=Routing.fromAnalysis({stemCache:{key},separation:{modelId:'deux-test-model'}});
 const current=await restoreCachedBass(valid);
 assert.equal(current.writes.length,0);
 assert.equal(current.messages.find(message=>message.type==='result')?.value.stemRouting,valid);
});
