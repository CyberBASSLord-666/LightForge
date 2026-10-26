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
