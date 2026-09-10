#!/usr/bin/env node
'use strict';
// Runs the shipped separator and WASM runtime, with optional PCM parity checks.
// Each invocation is one isolated process so maxRSS measures that configuration.
// Process isolation does not clear the host kernel's file cache or control
// thermal state, so neither may be represented as a strict cold-I/O result.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'..'),args=process.argv.slice(2),options={};
for(let i=0;i<args.length;i+=2){if(!args[i].startsWith('--')||!args[i+1])throw Error('Expected --option value');options[args[i].slice(2)]=args[i+1];}
const resolve=(value,fallback)=>path.resolve(value||fallback),sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const implementation=resolve(options.implementation,root+'/web/analysis/separator-deux.js');
const models=resolve(options.models,root+'/web/analysis/models/deux');
const fixture=resolve(options.fixture,root+'/qa/release-1.6.0/fixtures/falcon-mix.wav');
const fixtureProvenance=options['fixture-provenance']?resolve(options['fixture-provenance']):null;
const output=resolve(options.output,root+'/build/deux-runtime.json');
const implementationSHA256=sha(fs.readFileSync(implementation));
const benchmarkSHA256=sha(fs.readFileSync(__filename));
const threads=Number(options.threads||4);
if(!Number.isInteger(threads)||threads<1||threads>8)throw Error('Invalid thread count');
const spectrumReuse=options['spectrum-reuse']||'off';
if(!['off','on'].includes(spectrumReuse))throw Error('--spectrum-reuse must be off or on');
const ort=require(root+'/web/analysis/vendor/ort.wasm.min.js');
ort.env.wasm.numThreads=threads;ort.env.wasm.wasmPaths=root+'/web/analysis/vendor/';
require(root+'/web/analysis/dsp.js');
const Deux=require(implementation),Reader=require(root+'/web/analysis/wav-reader.js');
global.fetch=async url=>({json:async()=>JSON.parse(fs.readFileSync(path.join(models,new URL(url).pathname.split('/').pop())))});
const create=ort.InferenceSession.create.bind(ort.InferenceSession);
let loads=0,runs=0;
const runtime={Tensor:ort.Tensor,InferenceSession:{create:async(url,opts)=>{
  loads++;const session=await create(fs.readFileSync(path.join(models,new URL(url).pathname.split('/').pop())),opts);
  return{run:async feeds=>{runs++;return session.run(feeds);},release:()=>session.release()};
}}};
(async()=>{
  const bytes=fs.readFileSync(fixture),reader=new Reader('');
  reader.bytes=async(a,b)=>{reader.totalBytes=bytes.length;return Uint8Array.from(bytes.subarray(a,b+1)).buffer;};await reader.open();
  const manifestBytes=fs.readFileSync(path.join(models,'manifest.json')),manifest=JSON.parse(manifestBytes);
  for(const [name,entry]of Object.entries(manifest.files||{})){
    const target=path.join(models,name),digest=crypto.createHash('sha256');
    for await(const part of fs.createReadStream(target))digest.update(part);
    if(fs.statSync(target).size!==entry.bytes||digest.digest('hex')!==entry.sha256)throw Error('Model manifest mismatch: '+name);
  }
  const total=options['total-samples']===undefined?reader.samples:Number(options['total-samples']);
  if(!Number.isSafeInteger(total)||total<1||total>reader.samples)throw Error('--total-samples must be a positive integer no greater than the fixture length');
  let provenanceReceipt=null;
  if(fixtureProvenance){
   const provenanceBytes=fs.readFileSync(fixtureProvenance),provenance=JSON.parse(provenanceBytes);
   const outputInfo=provenance?.output||{};
   if(provenance?.schema!=='lightforge.deux-benchmark-fixture.v1'||outputInfo.file!==path.basename(fixture)||outputInfo.sha256!==sha(bytes)||outputInfo.samples!==reader.samples||outputInfo.sample_rate!==reader.rate||outputInfo.channels!==reader.channels||outputInfo.dtype!=='float32')throw Error('Fixture provenance does not bind the exact benchmark WAV.');
   provenanceReceipt={path:path.relative(root,fixtureProvenance),sha256:sha(provenanceBytes),schema:provenance.schema};
  }
  const recoveryAfter=options['recover-after-chunks']===undefined?0:Number(options['recover-after-chunks']);
  if(!Number.isSafeInteger(recoveryAfter)||recoveryAfter<0)throw Error('--recover-after-chunks must be a non-negative integer');
  const profile=Deux.createPerformanceProfile();let chunks=[],recovery;
  let lastLog=0;const start=performance.now();
  const run=async(checkpoint,onChunk)=>{
   const separator=await Deux.create({ort:runtime,baseUrl:'https://models.invalid/',profile,reuseSpectrum:spectrumReuse==='on',checkpoint});
   try{return await separator.process((offset,count)=>reader.stereo44100(offset,count),total,onChunk,progress=>{
    if(performance.now()-lastLog>15000||progress.progress===1){lastLog=performance.now();process.stderr.write(JSON.stringify({progress:progress.progress,elapsedSeconds:(performance.now()-start)/1000,rssMiB:process.memoryUsage().rss/1048576})+'\n');}
   });}finally{await separator.release();}
  };
  let result;
  if(!recoveryAfter)result=await run(undefined,chunk=>chunks.push(chunk));
  else{
   const saved=new Map(),checkpoint={readFloats:async key=>saved.get(key)?.map(values=>values.slice()),writeFloats:async(key,arrays)=>saved.set(key,arrays.map(values=>values.slice()))};
   let interrupted=false,interruptedChunks=0;
   try{await run(checkpoint,async chunk=>{interruptedChunks++;if(interruptedChunks>=recoveryAfter)throw Error('__lightforge_controlled_recovery__');});}
   catch(error){if(error?.message!=='__lightforge_controlled_recovery__')throw error;interrupted=true;}
   if(!interrupted||!saved.size)throw Error('Controlled recovery did not retain a completed passage checkpoint.');
   chunks=[];result=await run(checkpoint,chunk=>chunks.push(chunk));
   recovery={controlledInterruption:true,afterChunks:recoveryAfter,checkpointPassages:saved.size,restoredPassages:result.restoredPassages,resumedSamples:chunks.reduce((count,chunk)=>count+chunk.vocals.length,0)};
   if(result.restoredPassages<1)throw Error('Controlled recovery did not restore its completed passage.');
  }
  const sessionConfiguration={executionProviders:['wasm'],graphOptimizationLevel:'all',enableCpuMemArena:false,enableMemPattern:false};
  const report={schema:2,passed:true,errors:[],fixture:path.relative(root,fixture),fixtureSHA256:sha(bytes),fixtureProvenance:provenanceReceipt,sourceSHA256:implementationSHA256,manifestSHA256:sha(manifestBytes),modelId:manifest.id,model:{id:manifest.id,checkpointSHA256:manifest.checkpointSHA256,manifestSHA256:sha(manifestBytes)},source_hashes:{[path.relative(root,implementation)]:implementationSHA256,'tools/benchmark_deux_runtime.cjs':benchmarkSHA256},threads,mode:{spectrumReuse:{requested:spectrumReuse,enabled:spectrumReuse==='on',experimental:true,defaultEnabled:false},coldProcess:true,filesystemCache:{state:'uncontrolled',strictColdIo:false},thermalState:{available:false}},seconds:(performance.now()-start)/1000,peakRssMiB:process.resourceUsage().maxRSS/1024,sessionLoads:loads,inferenceRuns:runs,samples:total,fixtureSamples:reader.samples,result,recovery,pcm:{}};
  report.runtime={elapsedMs:report.seconds*1000,peakRssBytes:report.peakRssMiB*1048576,threads,ortWebVersion:ort.env?.versions?.web||null,sessionConfiguration};
  if(options.reference)report.referenceProvenance=options.provenance||'Float32 PCM oracle at '+path.resolve(options.reference)+'-{vocals,accompaniment}.f32; exact hashes below.';
  for(const role of ['vocals','accompaniment']){
    const data=Buffer.concat(chunks.map(c=>Buffer.from(c[role].buffer,c[role].byteOffset,c[role].byteLength)));
    const pcm=new Float32Array(data.buffer.slice(data.byteOffset,data.byteOffset+data.byteLength));
    if(pcm.length!==total||pcm.some(x=>!Number.isFinite(x)))throw Error('Invalid output PCM');
    const info={samples:pcm.length,sha256:sha(data),nonFiniteSamples:0};
    if(options.reference){
      const refBytes=fs.readFileSync(path.resolve(options.reference+'-'+role+'.f32'));
      const reference=new Float32Array(refBytes.buffer.slice(refBytes.byteOffset,refBytes.byteOffset+refBytes.byteLength));
      if(reference.length!==pcm.length)throw Error('Reference length mismatch');
      let maxAbsError=0,squaredError=0,signal=0;
      for(let i=0;i<pcm.length;i++){const error=pcm[i]-reference[i];maxAbsError=Math.max(maxAbsError,Math.abs(error));squaredError+=error*error;signal+=reference[i]*reference[i];}
      Object.assign(info,{referenceSHA256:sha(refBytes),maxAbsError,rmsError:Math.sqrt(squaredError/pcm.length),snrDb:10*Math.log10(Math.max(1e-30,signal)/Math.max(1e-30,squaredError))});
      if(info.maxAbsError>0.00003||info.rmsError>0.000003){report.passed=false;report.errors.push(role+' differs from the Float32 runtime reference.');}
    }
    report.pcm[role]=info;
    if(options.pcm){const target=path.resolve(options.pcm+'-'+role+'.f32');fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,data);}
  }
  report.performanceProfile=profile.snapshot({benchmark:{coldProcess:true,filesystemCacheState:'uncontrolled',strictColdIo:false,spectrumReuse:spectrumReuse==='on'}});
  fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');process.stdout.write(JSON.stringify(report,null,2)+'\n');
  if(!report.passed)process.exitCode=1;
})().catch(error=>{process.stderr.write(error.stack+'\n');process.exitCode=1;});
