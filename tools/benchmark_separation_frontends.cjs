#!/usr/bin/env node
'use strict';
// Usage: node tools/benchmark_separation_frontends.cjs /path/to/released-separator-mdx.cjs [canonical.wav] [--verify-model]
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
require(path.join(root,'web/analysis/dsp.js'));
const releasedFile=process.argv[2];
if(!releasedFile)throw Error('Supply a copy of the released separator-mdx.js for the exact-output comparison.');
const released=require(path.resolve(releasedFile)),current=require(path.join(root,'web/analysis/separator-mdx.js'));
const Reader=require(path.join(root,'web/analysis/wav-reader.js'));
const median=values=>values.slice().sort((a,b)=>a-b)[Math.floor(values.length/2)];
const hash=data=>crypto.createHash('sha256').update(data).digest('hex');
const asBytes=array=>Buffer.from(array.buffer,array.byteOffset,array.byteLength);

async function verifyModel(reader){
 const base=path.join(root,'web/analysis'),ort=require(path.join(base,'vendor/ort.wasm.min.js'));
 const manifest=require(path.join(base,'models/separator-mdx-model.json'));
 const asset='models/'+manifest.file,model=fs.readFileSync(path.join(base,asset));
 assert.equal(hash(model),require(path.join(base,'ASSET_MANIFEST.json'))[asset].sha256);
 ort.env.wasm.numThreads=2;
 ort.env.wasm.wasmPaths=base+'/vendor/';
 const outputs=[],frames=current.constants.CORE;
 // Use the original first passage context. Measure neither inference time nor
 // stitching of multiple passages in this optional host model parity check.
 for(const implementation of [released,current]){
  let calls=0;
  const runtime={Tensor:ort.Tensor,InferenceSession:{create:async(_,options)=>{
   const session=await ort.InferenceSession.create(model,options);
   return {inputNames:session.inputNames,outputNames:session.outputNames,
    run:feeds=>{calls++;return session.run(feeds);},release:()=>session.release()};
  }}};
  const separator=await implementation.create({manifest,ort:runtime,denoise:true}),digests={};
  try{
   const result=await separator.process((offset,count)=>reader.stereo44100(offset,count),frames,chunk=>{
    assert.equal(chunk.startSample,0);
    for(const role of ['vocals','accompaniment']){
     assert.equal(chunk[role].length,frames);
     assert.ok(chunk[role].every(Number.isFinite));
     digests[role]=hash(asBytes(chunk[role]));
    }
   });
   assert.equal(calls,2);assert.equal(result.modelPasses,2);
   outputs.push(digests);
  }finally{await separator.release();}
 }
 assert.deepEqual(outputs[0],outputs[1]);
 return {modelSha256:hash(model),polarityPassesPerVariant:2,comparedFramesPerStem:frames,stemSha256:outputs[0]};
}

async function main(){
 const args=process.argv.slice(3),wav=args.find(argument=>argument!=='--verify-model');
 const input=fs.readFileSync(wav||path.join(root,'web/demo/glass-castle.wav'));
 const reader=new Reader('');
 let bytesRead=0;
 reader.totalBytes=input.length;
 reader.bytes=async(start,end)=>{
  const part=input.subarray(start,end+1);
  bytesRead+=part.length;
  return part.buffer.slice(part.byteOffset,part.byteOffset+part.byteLength);
 };
 await reader.open();
 assert.ok(reader.rate===44100&&reader.format===1&&reader.bits===16&&[1,2].includes(reader.channels),'Select an imported 44.1 kHz PCM16 WAV.');
 const starts=[];
 for(let start=0;start<reader.samples;start+=220500){
  starts.push(start-66150);
  if(start+441000>=reader.samples)break;
 }
 const stereo=await reader.stereo44100(0,current.constants.INPUT_LENGTH);
 const measurements={released:[],current:[]},probeResults={released:[],current:[]};
 let referenceActivity,referenceHashes;
 for(let round=0;round<=5;round++){
  for(const name of round%2?['current','released']:['released','current']){
   bytesRead=0;
   const active=[],preflightStart=performance.now();
   for(const offset of starts){
    if(name==='current')active.push(await reader.hasPcm16Signal44100(offset,573300,1e-7));
    else{
     const channels=await reader.stereo44100(offset,573300);
     let peak=0;
     for(const channel of channels)for(const value of channel)peak=Math.max(peak,Math.abs(value));
     active.push(peak>=1e-7);
    }
   }
   const preflightMs=performance.now()-preflightStart;
   if(referenceActivity)assert.deepEqual(active,referenceActivity);
   else referenceActivity=active;
   if(round)probeResults[name].push({preflightMs,bytesRead});

   const implementation=name==='current'?current:released;
   const frontend=new implementation.Frontend(),start=performance.now();
   const spectrum=frontend.encode(stereo),encoded=performance.now();
   const pcm=frontend.decode(spectrum),decoded=performance.now();
   const hashes=[hash(asBytes(spectrum)),hash(asBytes(pcm))];
   if(referenceHashes)assert.deepEqual(hashes,referenceHashes);
   else referenceHashes=hashes;
   if(round)measurements[name].push({encodeMs:encoded-start,decodeMs:decoded-encoded,combinedMs:decoded-start});
  }
 }
 const medians=trials=>Object.fromEntries(Object.entries(trials).map(([name,rows])=>[
  name,Object.fromEntries(Object.keys(rows[0]).map(key=>[key,median(rows.map(row=>row[key]))]))
 ]));
 console.log(JSON.stringify({
  scope:'Memory-backed Studio activity preflight and one Balanced frontend round-trip without model inference.',
  node:process.version,fixtureSha256:hash(input),sourceFrames:reader.samples,studioWindows:starts.length,
  activeWindows:referenceActivity.filter(Boolean).length,mdxFrames:stereo[0].length,
  releasedMdxSha256:hash(fs.readFileSync(releasedFile)),spectrumSha256:referenceHashes[0],pcmSha256:referenceHashes[1],
  warmupPairs:1,measuredPairs:5,order:'Alternating',studioPreflight:{medians:medians(probeResults),trials:probeResults},
  balancedFrontend:{medians:medians(measurements),trials:measurements},
  modelParity:args.includes('--verify-model')?await verifyModel(reader):null
 },null,2));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
