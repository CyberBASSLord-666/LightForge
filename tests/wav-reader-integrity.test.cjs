'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const Reader=require('../web/analysis/wav-reader.js');

function wav({rate=22050,extensible=false}={}){
 const offset=extensible?68:44,bytes=Buffer.alloc(offset+rate*2);
 bytes.write('RIFF');bytes.writeUInt32LE(bytes.length-8,4);bytes.write('WAVEfmt ',8);
 bytes.writeUInt32LE(extensible?40:16,16);bytes.writeUInt16LE(extensible?65534:1,20);
 bytes.writeUInt16LE(1,22);bytes.writeUInt32LE(rate,24);bytes.writeUInt32LE(rate*2,28);
 bytes.writeUInt16LE(2,32);bytes.writeUInt16LE(16,34);
 if(extensible){bytes.writeUInt16LE(22,36);bytes.writeUInt16LE(16,38);Buffer.from('0100000000001000800000aa00389b71','hex').copy(bytes,44);}
 bytes.write('data',offset-8);bytes.writeUInt32LE(rate*2,offset-4);
 for(let i=0;i<rate;i++)bytes.writeInt16LE((i%200)-100,offset+i*2);
 return bytes;
}
async function opened(bytes){
 const reader=new Reader('/fixture.wav');reader.totalBytes=bytes.length;
 reader.bytes=async(start,end)=>{const view=bytes.subarray(start,Math.min(bytes.length,end+1));return view.buffer.slice(view.byteOffset,view.byteOffset+view.byteLength);};
 await reader.open();return reader;
}

test('mono reads reject malformed and excessive sample bounds before any IO',async()=>{
 for(const rate of [22050,44100]){
  const reader=await opened(wav({rate}));let reads=0;reader.bytes=async()=>{reads++;throw Error('Unexpected IO');};
  for(const [start,count] of [[0,NaN],[NaN,4],[0,1.5],[.5,4],[0,-1],[0,Infinity],[Infinity,4],[0,22050*40+1],[Number.MAX_SAFE_INTEGER,4]]){
   await assert.rejects(reader.mono22050(start,count,{resampleHalfFIR:new Float64Array(63)}),/Invalid mono audio read bounds/);
  }
  assert.equal(reads,0);
 }
});

test('zero-length mono requests allocate no source window and perform no IO',async()=>{
 const reader=await opened(wav({rate:44100}));reader.bytes=async()=>{throw Error('Zero-length read performed IO');};
 assert.equal((await reader.mono22050(0,0,{})).length,0);
});

test('whole-file fallback cannot silently replace an established source length',async()=>{
 const original=global.fetch,bytes=wav(),reader=new Reader('/changing.wav');let calls=0;
 global.fetch=async(_url,{headers})=>{
  const [,first,last]=/bytes=(\d+)-(\d+)/.exec(headers.Range),start=Number(first),end=Math.min(Number(last),bytes.length-1);
  if(calls++===0)return new Response(bytes.subarray(start,end+1),{status:206,headers:{'Content-Range':`bytes ${start}-${end}/${bytes.length}`}});
  const changed=Buffer.concat([bytes,Buffer.from([0,0])]);
  return new Response(changed,{status:200,headers:{'Content-Length':String(changed.length)}});
 };
 try{await reader.open();await assert.rejects(reader.mono22050(0,16,{}),/audio.*(changed|match)|source.*changed/i);assert.equal(reader.cached,null);assert.equal(reader.totalBytes,bytes.length);}
 finally{global.fetch=original;}
});

test('RIFF and extensible format boundaries reject corrupt audio before decoding',async()=>{
 for(const mutate of [
  bytes=>bytes.writeUInt32LE(bytes.length+8,4),
  bytes=>bytes.writeUInt32LE(36,4),
  bytes=>bytes.writeUInt32LE(1,28)
 ]){const bytes=wav();mutate(bytes);await assert.rejects(opened(bytes),/incomplete|unsupported|supported PCM/);}
 assert.equal((await opened(wav({extensible:true}))).format,1);
 for(const mutate of [bytes=>bytes[46]=1,bytes=>bytes[59]=0,bytes=>bytes.writeUInt16LE(0,36)]){
  const bytes=wav({extensible:true});mutate(bytes);await assert.rejects(opened(bytes),/unsupported|supported PCM/);
 }
});

test('bounded source reads retain byte-exact integer PCM and edge padding',async()=>{
 const bytes=wav(),reader=await opened(bytes);
 for(const [start,count] of [[0,64],[-16,64],[reader.samples-16,64]]){
  const result=await reader.mono22050(start,count,{});
  for(let i=0;i<count;i++)assert.equal(result[i],start+i<0||start+i>=reader.samples?0:bytes.readInt16LE(44+(start+i)*2)/32768);
 }
});

test('44.1 kHz FIR reads retain the original-clock sample values across chunk edges',async()=>{
 const bytes=wav({rate:44100}),reader=await opened(bytes),config=require('../web/analysis/models/features.json');
 for(const [start,count] of [[-17,64],[17,64],[22040,64],[30000,64]]){
  const actual=await reader.mono22050(start,count,config),expected=new Float32Array(count);
  for(let i=0;i<count;i++){
   let sum=0;
   for(let tap=0;tap<config.resampleHalfFIR.length;tap++){
    const source=(start+i)*2+tap-31;
    sum+=(source<0||source>=reader.samples?0:bytes.readInt16LE(44+source*2)/32768)*config.resampleHalfFIR[tap];
   }
   expected[i]=sum;
  }
  assert.deepEqual(Buffer.from(actual.buffer),Buffer.from(expected.buffer));
 }
});

test('stereo rejects overflowed end coordinates before allocation or IO',async()=>{
 const reader=await opened(wav({rate:44100}));reader.bytes=async()=>{throw Error('Unexpected IO');};
 await assert.rejects(reader.stereo44100(Number.MAX_SAFE_INTEGER,4),/Invalid stereo audio read bounds/);
});
