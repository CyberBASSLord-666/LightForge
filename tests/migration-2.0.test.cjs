'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs'),crypto=require('node:crypto');
const run=require('./worker-harness.cjs'),current=path.resolve(__dirname,'../web/engine'),legacy=path.resolve(__dirname,'../qa/release-2.0.0/legacy-1.6');
const defaults={musicCues:[],vocalOffsetMs:0,bassOffsetMs:0};
const music={duration:12,bpm:120,beatConfidence:.9,analysisVersion:5,beats:Array.from({length:24},(_,i)=>i*.5),waveform:[.8],sections:[{start:0,end:12,energy:.8}]};
const settings={dance:'off',seed:2025,vocalFocus:.85,bassFocus:.9,vocalRegions:[]};
test('actual 1.6 worker snapshot migrates to 2.0 with exact frames and stable repeated reopen',async()=>{
 const old=await run(legacy,{action:'generate',music,settings});
 const restored=await run(current,{action:'restore',music,settings:{...settings,...defaults},compiled:old.compiled});
 assert.deepEqual(restored.show.frames,old.show.frames);assert.equal(restored.compiled.frameData,old.compiled.frameData);assert.equal(restored.compiled.metaSHA256,old.compiled.metaSHA256);assert.equal(restored.compiled.settingsMigration.to,require('../web/version.js').name);
 const again=await run(current,{action:'restore',music,settings:{...settings,...defaults},compiled:restored.compiled});assert.equal(JSON.stringify(again.compiled),JSON.stringify(restored.compiled));
 for(const patch of [{vocalOffsetMs:1},{bassOffsetMs:-1},{musicCues:[{id:'x',role:'vocals',action:'hold',start:1,end:2}]},{intensity:.3}])await assert.rejects(run(current,{action:'restore',music,settings:{...settings,...defaults,...patch},compiled:old.compiled}),/does not match/);
 for(const mutate of [c=>c.sha256='0'.repeat(64),c=>c.meta.vehicle='changed',c=>c.frameData='invalid',c=>c.frameCount++]){const compiled=structuredClone(old.compiled);mutate(compiled);await assert.rejects(run(current,{action:'restore',music,settings:{...settings,...defaults},compiled}));}
});
test('1.4 direct and 1.5 rebound snapshots still migrate without replacing their frames',async()=>{
 const f=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../qa/release-1.5.0/legacy-1.4-project.json')));
 const next={...f.settings,vocalFocus:.85,bassFocus:.9,vocalRegions:[],...defaults};
 for(const intermediate of [null,path.resolve(__dirname,'../qa/release-1.6.0/historical-engine-1.5.0')]){
  const compiled=intermediate?(await run(intermediate,{action:'restore',music:f.music,settings:{...f.settings,vocalFocus:.85,bassFocus:.9},compiled:f.compiled})).compiled:f.compiled;
  const result=await run(current,{action:'restore',music:f.music,settings:next,compiled});assert.equal(crypto.createHash('sha256').update(result.show.frames).digest('hex'),f.compiled.sha256);
 }
});
test('2.0 cue metadata and final synchronization report survive an exact backup round trip',async()=>{
 const next={...settings,...defaults,musicCues:[{id:'manual',role:'vocals',action:'hold',start:3.137,end:4.719,strength:.8}]};
 const a=await run(current,{action:'generate',music,settings:next}),b=await run(current,{action:'restore',music,settings:next,compiled:JSON.parse(JSON.stringify(a.compiled))});
 assert.deepEqual(a.show.frames,b.show.frames);assert.equal(JSON.stringify(a.show.synchronization),JSON.stringify(b.show.synchronization));assert.equal(a.show.synchronization.manual[0].status,'matched');assert.equal(JSON.stringify(b.show.validation.synchronization),JSON.stringify(a.show.validation.synchronization));
});
