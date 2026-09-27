#!/usr/bin/env node
'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const ROOT=path.resolve(__dirname,'../../../..'),engine=require(path.join(ROOT,'tools/game_benchmark/process_capture.cjs'));
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const pin=bytes=>({bytes:bytes.length,sha256:hash(bytes)});
function check(ok,message){if(!ok)throw Error(message);}
async function replay(run,output){
  check(!fs.existsSync(output),'New consumer output required');
  const qbytes=fs.readFileSync(path.join(run,'qualification/receipt.json')),q=JSON.parse(qbytes);
  check(q.schema==='lightforge.game-separated-voice-cpu-experiment.v1'&&q.status==='COMPLETE_CPU_REFERENCE_DIAGNOSTIC'&&
    q.observerComparisonsPassed===true&&q.inputsRecheckedAfterQualification===true&&JSON.stringify(q.variants)==='["cpu_all"]',
    'Completed CPU separated-voice capture required');
  const pcm=fs.readFileSync(path.join(run,'voice-full.f32')),provenance=JSON.parse(fs.readFileSync(path.join(run,'input-provenance.json')));
  check(pcm.length===2822400*4&&hash(pcm)===provenance.pcmSHA256&&provenance.sourceKind==='public-separated-vocals','Complete separated PCM required');
  const manifest=JSON.parse(fs.readFileSync(path.join(ROOT,'web/analysis/models/game/manifest.json')));
  const sources=['tools/game_benchmark/process_capture.cjs','web/analysis/game.js','web/analysis/models/game/manifest.json'];
  for(const name of sources)check(hash(fs.readFileSync(path.join(ROOT,name)))===q.sourceHashes[name],'Production source differs from capture');
  const records=engine.planPassages(2822400,0).map(row=>{
    const relative='cpu_all_captured/output/passage-'+String(row.index).padStart(3,'0')+'/receipt.json';
    const bytes=fs.readFileSync(path.join(run,'qualification',relative)),receipt=JSON.parse(bytes);
    check(hash(bytes)===q.artifactHashes[relative],'Captured passage receipt changed');
    check(receipt.passageIndex===row.index&&receipt.firstSample===row.first&&receipt.lastSample===row.last&&receipt.seed===row.seed&&
      receipt.language===0&&receipt.steps===8,'Captured passage schedule differs');
    const pcmSha256=hash(pcm.subarray(row.first*4,row.last*4));check(receipt.pcmSHA256===pcmSha256,'Captured PCM differs');
    return {...row,pcmSha256,notes:receipt.notes};
  });
  const fresh=await engine.processNativeRecords(manifest,pcm,0,records);
  const restored=await engine.processRecords(manifest,2822400,0,records,true);
  assert.deepEqual(restored,fresh.transcription,'Independent native checkpoint restore differs');
  check(fresh.nativeCalls===6&&fresh.nativeCheckpointResumeIdentical===true,'Six source callbacks and identical resume required');
  const result={schema:'lightforge.game-separated-voice-production-replay.v1',status:'COMPLETE_CPU_REFERENCE_DIAGNOSTIC',
    qualificationReceipt:pin(qbytes),inputPcm:pin(pcm),passageCount:6,...fresh,independentCheckpointRestoreIdentical:true,
    sourceHashes:Object.fromEntries(sources.map(name=>[name,hash(fs.readFileSync(path.join(ROOT,name)))])),
    modelInferenceExecuted:false,cudaExecuted:false,fullVocalStageExecuted:false,qualityApproved:false,benchmarkTimingAdmitted:false,
    target75Proven:false,androidIntegrationApproved:false,releaseAuthorized:false,
    scope:'Actual separated-voice CPU captures replayed through unchanged production GAME clipping, stitching, sorting, rounding and native checkpoint restore. No fresh model execution or downstream vocal fusion.'};
  fs.mkdirSync(output);fs.writeFileSync(path.join(output,'receipt.json'),JSON.stringify(result,null,2)+'\n',{flag:'wx'});
  return result;
}
module.exports={replay};
if(require.main===module){check(process.argv.length===4,'Usage: replay_voice.cjs completed-run new-consumer-directory');
  replay(...process.argv.slice(2)).then(result=>console.log(JSON.stringify({status:result.status,nativeCalls:result.nativeCalls,notes:result.transcription.notes.length,target75Proven:false}))).catch(error=>{console.error(error);process.exitCode=1;});}
