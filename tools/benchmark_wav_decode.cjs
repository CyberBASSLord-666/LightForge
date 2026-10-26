#!/usr/bin/env node
'use strict';
// Synthetic PCM reader timing. Measures decoding/read work, not model inference.
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto');
const {performance}=require('node:perf_hooks');
const Baseline=require('../tests/fixtures/performance/wav-reader-e434d38.cjs');
const Candidate=require('../web/analysis/wav-reader.js');
const config=require('../web/analysis/models/features.json');
const bytes=a=>Buffer.from(a.buffer,a.byteOffset,a.byteLength);
const median=values=>values.slice().sort((a,b)=>a-b)[Math.floor(values.length/2)];

function wave({rate=44100,channels=2,bits=16,format=1,seconds=2}={}){
 const frames=rate*seconds,stride=channels*bits/8,b=Buffer.alloc(44+frames*stride);
 b.write('RIFF');b.writeUInt32LE(b.length-8,4);b.write('WAVEfmt ',8);b.writeUInt32LE(16,16);
 b.writeUInt16LE(format,20);b.writeUInt16LE(channels,22);b.writeUInt32LE(rate,24);
 b.writeUInt32LE(rate*stride,28);b.writeUInt16LE(stride,32);b.writeUInt16LE(bits,34);
 b.write('data',36);b.writeUInt32LE(frames*stride,40);
 let random=0x6a09e667;
 for(let i=0;i<frames;i++)for(let channel=0;channel<channels;channel++){
  random^=random<<13;random^=random>>>17;random^=random<<5;
  const at=44+i*stride+channel*bits/8;
  if(format===3){const value=[NaN,Infinity,-Infinity,-0,0,1,-1][i%7];b.writeFloatLE(i<7?value:random/2147483648,at);}
  else if(bits===16)b.writeInt16LE(i<4?[-32768,32767,0,-1][(i+channel)%4]:random>>16,at);
  else if(bits===24)b.writeIntLE(random>>8,at,3);
  else b.writeInt32LE(random,at);
 }
 return b;
}

async function open(Reader,data,telemetry){
 const reader=new Reader('/synthetic.wav',telemetry);reader.totalBytes=data.length;
 reader.bytes=async(first,last)=>data.buffer.slice(data.byteOffset+first,data.byteOffset+Math.min(data.length,last+1));
 await reader.open();return reader;
}

function same(actual,expected){
 const left=Array.isArray(actual)?actual:[actual],right=Array.isArray(expected)?expected:[expected];
 assert.equal(left.length,right.length);
 for(let i=0;i<left.length;i++)assert.ok(bytes(left[i]).equals(bytes(right[i])),'Decoded Float32 bits changed');
}

async function benchmark(){
 const results=[];
 for(const [rate,channels,method] of [[22050,1,'mono22050'],[22050,2,'mono22050'],[44100,1,'stereo44100'],[44100,2,'stereo44100'],[44100,2,'mono22050']]){
  const data=wave({rate,channels,seconds:24}),count=(method==='mono22050'?22050:44100)*10;
  const starts=[-17,127,method==='mono22050'?22050*6:44100*6,method==='mono22050'?22050*18:44100*18];
  const expected=[],reference=await open(Baseline,data);
  for(const start of starts)expected.push(await reference[method](start,count,config));
  const samples=[[],[]],decoding=[[],[]],cpuSamples=[[],[]];
  for(let round=-2;round<7;round++)for(const variant of round%2?[1,0]:[0,1]){
   let decode=0;
   const reader=await open(variant?Candidate:Baseline,data,{measure(name,fn){const at=performance.now();try{return fn();}finally{if(name==='performance.audio_decode')decode+=performance.now()-at;}}});
   const outputs=[],cpu=process.cpuUsage(),at=performance.now();
   for(const start of starts)outputs.push(await reader[method](start,count,config));
   const elapsed=performance.now()-at,used=process.cpuUsage(cpu);
   outputs.forEach((value,i)=>same(value,expected[i]));
   if(round>=0){samples[variant].push(elapsed);decoding[variant].push(decode);cpuSamples[variant].push((used.user+used.system)/1000);}
  }
  const baselineMs=median(samples[0]),candidateMs=median(samples[1]);
  results.push({rate,channels,method,baselineMedianMs:baselineMs,candidateMedianMs:candidateMs,
   readWallReductionPercent:100*(1-candidateMs/baselineMs),baselineDecodeMedianMs:median(decoding[0]),
   candidateDecodeMedianMs:median(decoding[1]),baselineCpuMedianMs:median(cpuSamples[0]),candidateCpuMedianMs:median(cpuSamples[1]),
   samplesMs:{baseline:samples[0],candidate:samples[1]},cpuSamplesMs:{baseline:cpuSamples[0],candidate:cpuSamples[1]},allOutputBytesIdentical:true});
 }
 const sources={};
 for(const source of ['web/analysis/wav-reader.js','tests/fixtures/performance/wav-reader-e434d38.cjs','tools/benchmark_wav_decode.cjs'])sources[source]=crypto.createHash('sha256').update(fs.readFileSync(require('node:path').join(__dirname,'..',source))).digest('hex');
 return {scope:'Host synthetic PCM reads with memory-backed byte transport, original FIR and padding. Excludes filesystem/network latency, models and complete analysis; not a phone or whole-song speedup.',node:process.version,warmups:2,rounds:7,results,sources};
}
module.exports={wave,open,same,config,Baseline,Candidate,benchmark};
if(require.main===module)benchmark().then(result=>{
 const output=process.argv.indexOf('--output');
 if(output>=0)fs.writeFileSync(process.argv[output+1],JSON.stringify(result,null,2)+'\n',{flag:'wx'});
 console.log(JSON.stringify(result,null,2));
}).catch(error=>{console.error(error);process.exitCode=1;});
