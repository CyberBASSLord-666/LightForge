'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {wave,open,same,config,Baseline,Candidate}=require('../tools/benchmark_wav_decode.cjs');

test('PCM fast paths and unchanged generic paths match frozen reader bits across formats, channels and padding',async()=>{
 for(const rate of [22050,44100])for(const channels of [1,2,3,8])for(const [bits,format] of [[16,1],[24,1],[32,1],[32,3]]){
  const data=wave({rate,channels,bits,format}),before=await open(Baseline,data),after=await open(Candidate,data);
  for(const [start,count] of [[-17,127],[0,4099],[127,2047],[22050*2-17,127],[22050*2+127,31],[0,0]])same(await after.mono22050(start,count,config),await before.mono22050(start,count,config));
  if(rate===44100)for(const [start,count] of [[-17,127],[0,4099],[127,2047],[rate*2-17,127],[rate*2+127,31],[0,0]])same(await after.stereo44100(start,count),await before.stereo44100(start,count));
 }
});

test('repeated reads observe changed source bytes without retaining decoded PCM',async()=>{
 const data=wave({rate:44100,channels:2}),before=await open(Baseline,data),after=await open(Candidate,data);
 let reads=0;const read=after.bytes;after.bytes=async(...args)=>{reads++;return read(...args);};
 same(await after.stereo44100(127,1024),await before.stereo44100(127,1024));
 data.writeInt16LE(-32768,44+127*4);
 same(await after.stereo44100(127,1024),await before.stereo44100(127,1024));
 assert.equal(reads,2,'No PCM or transport cache may hide a changed source');
});

test('Studio activity probe matches PCM16 decoding at edges and only skips proven active bytes',async()=>{
 for(const channels of [1,2]){
  const data=wave({rate:44100,channels}),reader=await open(Candidate,data);
  const originalRead=reader.bytes,ranges=[];
  reader.bytes=async(first,last)=>{ranges.push([first,last]);return originalRead(first,last);};
  for(const [start,count,signalFrame,amplitude] of [
   [-23,10000,0,1], [0,10000,4096,-1], [0,10000,9999,256],
   [0,10000,null,0], [reader.samples-4,1000,reader.samples-1,-32768],
   [-100,10,null,0], [reader.samples+10,20,null,0], [0,0,null,0]
  ]){
   data.fill(0,44);
   if(signalFrame!==null)data.writeInt16LE(amplitude,44+(signalFrame*channels+channels-1)*2);
   const decoded=await reader.stereo44100(start,count);
   const expected=decoded.some(channel=>channel.some(value=>Math.abs(value)>=1e-7));
   ranges.length=0;
   assert.equal(await reader.hasPcm16Signal44100(start,count,1e-7),expected);
   if(signalFrame===0)assert.deepEqual(ranges,[[44,44+2048*channels*2-1]]);
   if(start===0&&count===10000&&signalFrame!==0)assert.equal(ranges.at(-1)[1],44+10000*channels*2-1);
   if(!count||start>=reader.samples||start+count<=0)assert.equal(ranges.length,0);
  }
  for(const threshold of [0,NaN,.01])assert.equal(await reader.hasPcm16Signal44100(0,1,threshold),null);
  await assert.rejects(reader.hasPcm16Signal44100(0,-1,1e-7),/bounds/);
  reader.bytes=async()=>new ArrayBuffer(1);
  await assert.rejects(reader.hasPcm16Signal44100(0,100,1e-7),/incomplete/);
 }
 for(const options of [{rate:22050},{channels:3},{bits:24},{bits:32,format:3}]){
  const reader=await open(Candidate,wave(options));
  reader.bytes=()=>assert.fail('Unsupported layout was read');
  assert.equal(await reader.hasPcm16Signal44100(0,64,1e-7),null);
 }
});
