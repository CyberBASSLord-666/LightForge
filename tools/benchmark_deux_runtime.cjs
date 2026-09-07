#!/usr/bin/env node
'use strict';
// Runs the shipped separator and WASM runtime, with optional PCM parity checks.
// Each invocation is one isolated process so maxRSS measures that configuration.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'..'),args=process.argv.slice(2),options={};
for(let i=0;i<args.length;i+=2){if(!args[i].startsWith('--')||!args[i+1])throw Error('Expected --option value');options[args[i].slice(2)]=args[i+1];}
const resolve=(value,fallback)=>path.resolve(value||fallback),sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const implementation=resolve(options.implementation,root+'/web/analysis/separator-deux.js');
const models=resolve(options.models,root+'/web/analysis/models/deux');
const fixture=resolve(options.fixture,root+'/qa/release-1.6.0/fixtures/falcon-mix.wav');
const output=resolve(options.output,root+'/build/deux-runtime.json');
const implementationSHA256=sha(fs.readFileSync(implementation));
const threads=Number(options.threads||4);
if(!Number.isInteger(threads)||threads<1||threads>8)throw Error('Invalid thread count');
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
  const separator=await Deux.create({ort:runtime,baseUrl:'https://models.invalid/'}),chunks=[];
  let lastLog=0;const start=performance.now();
  let result;
  try{result=await separator.process((offset,count)=>reader.stereo44100(offset,count),reader.samples,chunk=>chunks.push(chunk),progress=>{
    if(performance.now()-lastLog>15000||progress.progress===1){lastLog=performance.now();process.stderr.write(JSON.stringify({progress:progress.progress,elapsedSeconds:(performance.now()-start)/1000,rssMiB:process.memoryUsage().rss/1048576})+'\n');}
  });}finally{await separator.release();}
  const report={schema:1,passed:true,errors:[],fixture:path.relative(root,fixture),fixtureSHA256:sha(bytes),sourceSHA256:implementationSHA256,manifestSHA256:sha(manifestBytes),modelId:manifest.id,model:{id:manifest.id,checkpointSHA256:manifest.checkpointSHA256,manifestSHA256:sha(manifestBytes)},source_hashes:{[path.relative(root,implementation)]:implementationSHA256,'tools/benchmark_deux_runtime.cjs':sha(fs.readFileSync(__filename))},threads,seconds:(performance.now()-start)/1000,peakRssMiB:process.resourceUsage().maxRSS/1024,sessionLoads:loads,inferenceRuns:runs,samples:reader.samples,result,pcm:{}};
  report.runtime={elapsedMs:report.seconds*1000,peakRssBytes:report.peakRssMiB*1048576,threads};
  if(options.reference)report.referenceProvenance=options.provenance||'Float32 PCM oracle at '+path.resolve(options.reference)+'-{vocals,accompaniment}.f32; exact hashes below.';
  for(const role of ['vocals','accompaniment']){
    const data=Buffer.concat(chunks.map(c=>Buffer.from(c[role].buffer,c[role].byteOffset,c[role].byteLength)));
    const pcm=new Float32Array(data.buffer.slice(data.byteOffset,data.byteOffset+data.byteLength));
    if(pcm.length!==reader.samples||pcm.some(x=>!Number.isFinite(x)))throw Error('Invalid output PCM');
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
  fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');process.stdout.write(JSON.stringify(report,null,2)+'\n');
  if(!report.passed)process.exitCode=1;
})().catch(error=>{process.stderr.write(error.stack+'\n');process.exitCode=1;});
