'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),crypto=require('node:crypto');
const {originalVoice,prepare}=require('./input_voice.cjs');
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
function syntheticFixture(value=.125){
  const bytes=Buffer.alloc(44+2822400*4);
  bytes.write('RIFF');bytes.writeUInt32LE(bytes.length-8,4);bytes.write('WAVE',8);bytes.write('fmt ',12);
  bytes.writeUInt32LE(16,16);bytes.writeUInt16LE(3,20);bytes.writeUInt16LE(1,22);bytes.writeUInt32LE(44100,24);
  bytes.writeUInt32LE(176400,28);bytes.writeUInt16LE(4,32);bytes.writeUInt16LE(32,34);bytes.write('data',36);bytes.writeUInt32LE(bytes.length-44,40);
  for(let offset=44;offset<bytes.length;offset+=4)bytes.writeFloatLE(value,offset);
  const consumer={schema:'lightforge-deux-source-consumer-replay-1',status:'CPU_SOURCE_CONSUMER_DIAGNOSTIC_COMPLETE',
    audioSha256:'33f07d502ba19832b62b97d8fb4a11354e81310264bd885d7a06438228773650',audioSamples:2822400,passageCount:12,
    variants:['cpu_all'],gpuCaptureConsumed:false,originalProductionArithmetic:true,checkpointResumeIdentical:true,
    persistedOutputBytesRechecked:true,capturedInputSourceBytesRevalidated:true,fullVocalStageExecuted:false,
    qualityApproved:false,target75Proven:false,benchmarkTimingAdmitted:false,releaseAuthorized:false,
    outputFiles:{},arms:{cpu_all:{verifiedStemReaders:true}}};
  const rebind=()=>{consumer.outputFiles['cpu_all/voice-full.wav']={bytes:bytes.length,sha256:hash(bytes)};
    consumer.arms.cpu_all.completeVoicePcmSha256=hash(bytes.subarray(44));};
  rebind();return {bytes,consumer,rebind};
}
test('full Float32 input proof preserves actual production reader bytes and source clock',async()=>{
  // This fixture is synthetic and does not constitute upstream inference evidence.
  const fixture=syntheticFixture();fixture.bytes.writeFloatLE(-0,44);fixture.rebind();
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'game-voice-proof-'));
  try{
    fs.writeFileSync(path.join(directory,'voice.wav'),fixture.bytes);fs.writeFileSync(path.join(directory,'consumer.json'),JSON.stringify(fixture.consumer));
    const result=await prepare(path.join(directory,'voice.wav'),path.join(directory,'consumer.json'),directory);
    assert.equal(result.plan.length,6);assert.equal(result.sourceSamples,2822400);
    assert.deepEqual(result.productionReaderCalls,[{first:0,count:1411200},{first:1411200,count:1411200}]);
    assert(fs.readFileSync(path.join(directory,'voice-full.f32')).equals(fixture.bytes.subarray(44)));
    assert.equal(result.plan[5].last,2822400);assert.equal(result.modelInferenceExecuted,false);
  }finally{fs.rmSync(directory,{recursive:true,force:true});}
});
test('source contract rejects changed bytes, nonfinite values, bad geometry and unsupported approval',()=>{
  const fixture=syntheticFixture();assert.equal(originalVoice(fixture.bytes,fixture.consumer).length,2822400*4);
  fixture.bytes[48]^=1;assert.throws(()=>originalVoice(fixture.bytes,fixture.consumer),/binding differs/);fixture.bytes[48]^=1;
  fixture.bytes.writeFloatLE(NaN,48);fixture.rebind();assert.throws(()=>originalVoice(fixture.bytes,fixture.consumer),/Nonfinite/);
  fixture.bytes.writeFloatLE(.125,48);fixture.bytes.writeUInt32LE(22050,24);fixture.rebind();assert.throws(()=>originalVoice(fixture.bytes,fixture.consumer),/Float32 WAV/);
  fixture.bytes.writeUInt32LE(44100,24);fixture.rebind();fixture.consumer.target75Proven=true;
  assert.throws(()=>originalVoice(fixture.bytes,fixture.consumer),/approval/);
});
test('silent passages fail before any GAME input artifacts are emitted',async()=>{
  const fixture=syntheticFixture(0),directory=fs.mkdtempSync(path.join(os.tmpdir(),'game-voice-silence-'));
  try{
    fs.writeFileSync(path.join(directory,'voice.wav'),fixture.bytes);fs.writeFileSync(path.join(directory,'consumer.json'),JSON.stringify(fixture.consumer));
    await assert.rejects(()=>prepare(path.join(directory,'voice.wav'),path.join(directory,'consumer.json'),directory),/Silent passage/);
    for(const name of ['voice-full.f32','input-proof.json','input-provenance.json'])assert.equal(fs.existsSync(path.join(directory,name)),false);
  }finally{fs.rmSync(directory,{recursive:true,force:true});}
});
