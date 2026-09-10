'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path');
const fs=require('node:fs');
const root=path.resolve(__dirname,'..');
require(root+'/web/analysis/dsp.js');
const Deux=require(root+'/web/analysis/separator-deux.js');
const {SAMPLES,HALO,STRIDE,FRAMES,REUSE_SOURCE_FIRST,REUSE_SOURCE_LAST,REUSE_TARGET_FIRST,REUSE_FRAMES}=Deux.constants;

function sample(at,channel){
 // Deliberately non-periodic enough to expose an incorrect hop, channel or
 // complex-frame copy while remaining a stable Float32 source.
 return Math.fround(Math.sin(at*.001731+channel*.371)+.37*Math.cos(at*.000217-channel*.113)+(at%97)*.0001);
}
function windowAt(start){
 return [0,1].map(channel=>{const values=new Float32Array(SAMPLES);for(let i=0;i<SAMPLES;i++)values[i]=sample(start+i,channel);return values;});
}
function bytes(values){return Buffer.from(values.buffer,values.byteOffset,values.byteLength);}

test('adjacent overlap preprocessing reuses only identical interior STFT frames bit-for-bit',()=>{
 const firstWindow=windowAt(-HALO),secondWindow=windowAt(STRIDE-HALO);
 const cachedTransform=new Deux.Transform(),prior=cachedTransform.encode(firstWindow);
 const cached=cachedTransform.encodeWithReuse(secondWindow,prior);
 const full=new Deux.Transform().encode(secondWindow);
 assert.strictEqual(cached.spectrum,prior,'reuse must retain one spectrum buffer rather than allocating a second full spectrum');
 assert.equal(cached.reusedFrames,REUSE_FRAMES);
 assert.equal(cached.encodedFrames,FRAMES-REUSE_FRAMES);
 assert.equal(REUSE_SOURCE_FIRST,503);
 assert.equal(REUSE_SOURCE_LAST,1297);
 assert.equal(REUSE_TARGET_FIRST,3);
 assert.equal(REUSE_FRAMES,795);
 assert.equal(Buffer.compare(bytes(cached.spectrum),bytes(full)),0,'the full complex spectrum must be byte-identical to a fresh encode');
});

test('Deux profiler aggregates cold-path spans and explicitly marks unavailable worker telemetry',()=>{
 const profile=Deux.createPerformanceProfile(),token=profile.begin('session.create','front');
 profile.increment('session.created');profile.cache('spectrum','disabled');profile.end(token);
 const snapshot=profile.snapshot({candidate:'disabled'});
 assert.equal(snapshot.schema,1);
 assert.equal(snapshot.counters['session.created'],1);
 assert.equal(snapshot.counters['cache.spectrum.disabled'],1);
 assert.equal(snapshot.resources.wallClockMs.available,true);
 assert.equal(snapshot.resources.cpuTimeMs.available,false);
 assert.equal(snapshot.resources.acceleratorUtilization.available,false);
 assert.ok(snapshot.segments.some(segment=>segment.name==='session.create'&&segment.scopes[0].name==='front'));
});

test('experimental spectrum reuse remains off by default and native/recovery paths do not create WASM sessions',async()=>{
 const manifest=JSON.parse(fs.readFileSync(root+'/web/analysis/models/deux/manifest.json')),previousFetch=global.fetch;
 global.fetch=async()=>({json:async()=>manifest});
 try{
  const profile=Deux.createPerformanceProfile(),silentOrt={InferenceSession:{create(){throw Error('Native passage unexpectedly opened a WASM session.');}}};
  const source=[new Float32Array(SAMPLES).fill(.125),new Float32Array(SAMPLES).fill(-.25)];
  const vocals=new Float32Array(SAMPLES).fill(.1),accompaniment=new Float32Array(SAMPLES).fill(-.2);
  const separator=await Deux.create({ort:silentOrt,baseUrl:'https://models.invalid/',profile,nativePredict:async()=>({vocals,accompaniment})});
  const result=await separator.process(async()=>source,Deux.constants.CORE+1,async()=>{});
  await separator.release();
  assert.equal(result.chunks,2);
  assert.deepEqual(result.preprocessing.spectrumReuse,{experimental:true,enabled:false,sourceFrames:{first:503,last:1297},targetFrames:{first:3,last:797},reusedFramesPerPassage:795,recomputedFramesPerPassage:506,hits:0,misses:0});
  assert.equal(result.performanceProfile.spectrumReuse.enabled,false);
  assert.equal(result.performanceProfile.counters['cache.passage.native'],2);
  assert.equal(result.performanceProfile.counters['session.created'],undefined);
 }finally{global.fetch=previousFetch;}
});
