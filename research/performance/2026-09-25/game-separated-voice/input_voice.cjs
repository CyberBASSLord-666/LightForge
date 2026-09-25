#!/usr/bin/env node
'use strict';
// Byte-preserving bridge from verified production Deux fullVoice to original GAME.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const ROOT=path.resolve(__dirname,'../../../..');
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const pin=bytes=>({bytes:bytes.length,sha256:hash(bytes)});
const PUBLIC_SHA='33f07d502ba19832b62b97d8fb4a11354e81310264bd885d7a06438228773650';
function check(ok,message){if(!ok)throw Error(message);}
function originalVoice(bytes,consumer){
  check(consumer.schema==='lightforge-deux-source-consumer-replay-1' && consumer.status==='CPU_SOURCE_CONSUMER_DIAGNOSTIC_COMPLETE' &&
    consumer.audioSha256===PUBLIC_SHA && consumer.audioSamples===2822400 && consumer.passageCount===12 &&
    JSON.stringify(consumer.variants)==='["cpu_all"]' && consumer.gpuCaptureConsumed===false &&
    consumer.originalProductionArithmetic===true && consumer.checkpointResumeIdentical===true &&
    consumer.persistedOutputBytesRechecked===true && consumer.capturedInputSourceBytesRevalidated===true,
    'Completed public CPU production stem replay required');
  for(const flag of ['fullVocalStageExecuted','qualityApproved','target75Proven','benchmarkTimingAdmitted','releaseAuthorized'])
    check(consumer[flag]===false,'Upstream approval outside diagnostic scope');
  const descriptor=consumer.outputFiles?.['cpu_all/voice-full.wav'];
  check(descriptor && descriptor.bytes===bytes.length && descriptor.sha256===hash(bytes),'Verified full-voice WAV binding differs');
  check(bytes.length===44+2822400*4 && bytes.toString('ascii',0,4)==='RIFF' && bytes.readUInt32LE(4)===bytes.length-8 &&
    bytes.toString('ascii',8,12)==='WAVE' && bytes.toString('ascii',12,16)==='fmt ' && bytes.readUInt32LE(16)===16 &&
    bytes.readUInt16LE(20)===3 && bytes.readUInt16LE(22)===1 && bytes.readUInt32LE(24)===44100 &&
    bytes.readUInt32LE(28)===176400 && bytes.readUInt16LE(32)===4 && bytes.readUInt16LE(34)===32 &&
    bytes.toString('ascii',36,40)==='data' && bytes.readUInt32LE(40)===2822400*4,'Original complete mono Float32 WAV required');
  const pcm=bytes.subarray(44);
  check(hash(pcm)===consumer.arms?.cpu_all?.completeVoicePcmSha256 && consumer.arms.cpu_all.verifiedStemReaders===true,
    'Production fullVoice reader identity differs');
  for(let i=0;i<pcm.length;i+=4)check(Number.isFinite(pcm.readFloatLE(i)),'Nonfinite full-voice sample');
  return pcm;
}
async function prepare(wavFile,consumerFile,output){
  const bytes=fs.readFileSync(wavFile),consumerBytes=fs.readFileSync(consumerFile),consumer=JSON.parse(consumerBytes);
  const pcm=originalVoice(bytes,consumer),WavReader=require(path.join(ROOT,'web/analysis/wav-reader.js'));
  const engine=require(path.join(ROOT,'tools/game_benchmark/process_capture.cjs'));
  const savedFetch=globalThis.fetch,productionReaderCalls=[];
  try{
    globalThis.fetch=async(url,options)=>{
      check(url==='https://lightforge-verified-voice.invalid/voice-full.wav','Unexpected source fetch');
      const match=/^bytes=(\d+)-(\d+)$/.exec(options.headers.Range);check(match,'Expected bounded production range');
      const first=Number(match[1]),last=Math.min(Number(match[2]),bytes.length-1);
      return new Response(bytes.subarray(first,last+1),{status:206,headers:{'Content-Length':String(last-first+1),
        'Content-Range':`bytes ${first}-${last}/${bytes.length}`}});
    };
    const reader=new WavReader('https://lightforge-verified-voice.invalid/voice-full.wav');await reader.open();
    check(reader.rate===44100&&reader.samples===2822400&&reader.format===3&&reader.channels===1&&reader.bits===32,'Production WAV reader geometry differs');
    for(let first=0;first<reader.samples;first+=32*44100){
      const count=Math.min(32*44100,reader.samples-first),stereo=await reader.stereo44100(first,count);
      productionReaderCalls.push({first,count});
      for(const channel of stereo){
        const decoded=Buffer.alloc(count*4);for(let i=0;i<count;i++)decoded.writeFloatLE(channel[i],i*4);
        check(decoded.equals(pcm.subarray(first*4,(first+count)*4)),'Production reader changed stored Float32 bytes');
      }
    }
  }finally{globalThis.fetch=savedFetch;}
  const plan=engine.planPassages(2822400,0).map(row=>{
    const data=pcm.subarray(row.first*4,row.last*4);let peak=0;
    for(let i=0;i<data.length;i+=4)peak=Math.max(peak,Math.abs(data.readFloatLE(i)));
    check(peak>1e-5,'Silent passage unsupported by complete capture contract: '+row.index);
    return {...row,pcmSha256:hash(data)};
  });
  const proof={schema:'lightforge.game-separated-voice-input-proof.v1',sourceWav:pin(bytes),pcm:pin(pcm),
    sourceSamples:2822400,sampleRate:44100,language:0,productionReaderCalls,plan,
    sourceHashes:Object.fromEntries(['web/analysis/game.js','web/analysis/wav-reader.js'].map(name=>[name,hash(fs.readFileSync(path.join(ROOT,name)))])),
    finitePcm:true,allPassagesNonSilent:true,byteIdenticalToProductionReader:true,modelInferenceExecuted:false,
    qualityApproved:false,target75Proven:false};
  const proofBytes=Buffer.from(JSON.stringify(proof,null,2)+'\n');
  const provenance={schema:'lightforge.game-source-input.v1',sourceKind:'public-separated-vocals',separatedVocals:true,
    sourceSHA256:hash(bytes),pcmSHA256:hash(pcm),sourceSamples:2822400,sampleRate:44100,language:0,
    derivation:'Complete CPU production Deux voice-full.wav from the pinned public glass-castle.wav. Exact stored mono Float32 PCM, verified through unchanged fullVoice and WavReader consumers; no conversion, crop or resampling.',
    inputSourceProofSha256:hash(proofBytes),upstreamPublicAudioSha256:PUBLIC_SHA,upstreamConsumerReceiptSha256:hash(consumerBytes)};
  fs.writeFileSync(path.join(output,'voice-full.f32'),pcm,{flag:'wx'});
  fs.writeFileSync(path.join(output,'input-proof.json'),proofBytes,{flag:'wx'});
  fs.writeFileSync(path.join(output,'input-provenance.json'),JSON.stringify(provenance,null,2)+'\n',{flag:'wx'});
  return proof;
}
module.exports={prepare,originalVoice};
if(require.main===module){check(process.argv.length===5,'Usage: input_voice.cjs verified-voice.wav upstream-consumer.json new-output-directory');
  prepare(...process.argv.slice(2)).then(proof=>console.log(JSON.stringify({sourceSamples:proof.sourceSamples,passages:proof.plan.length,modelInferenceExecuted:false}))).catch(error=>{console.error(error);process.exitCode=1;});}
