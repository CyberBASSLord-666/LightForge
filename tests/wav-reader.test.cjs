const assert=require('assert');
const fs=require('fs');
const Reader=require('../web/analysis/wav-reader.js');
const originalFetch=global.fetch;
const results=[];
function wav({rate=22050,channels=1,bits=16,format=1,frames=rate*2,junk=0}={}){
 const stride=channels*bits/8,offset=44+(junk?8+junk+(junk%2):0),b=Buffer.alloc(offset+frames*stride);
 b.write('RIFF');b.writeUInt32LE(b.length-8,4);b.write('WAVEfmt ',8);b.writeUInt32LE(16,16);b.writeUInt16LE(format,20);b.writeUInt16LE(channels,22);b.writeUInt32LE(rate,24);b.writeUInt32LE(rate*stride,28);b.writeUInt16LE(stride,32);b.writeUInt16LE(bits,34);
 if(junk){b.write('JUNK',36);b.writeUInt32LE(junk,40);}b.write('data',offset-8);b.writeUInt32LE(frames*stride,offset-4);
 for(let f=0;f<frames;f++)for(let c=0;c<channels;c++){const p=offset+f*stride+c*bits/8,v=Math.sin(f/41)*.6;if(format===3)b.writeFloatLE(v,p);else if(bits===16)b.writeInt16LE(Math.round(v*32767),p);else if(bits===24)b.writeIntLE(Math.round(v*8388607),p,3);else b.writeInt32LE(Math.round(v*2147483647),p);}
 return b;
}
function serve(data,{mode='range'}={}){
 let reads=0;
 global.fetch=async(url,options={})=>{
  reads++;assert.equal(options.cache,'no-store');
  const m=/bytes=(\d+)-(\d+)/.exec(options.headers.Range),start=+m[1],end=Math.min(+m[2],data.length-1);
  if(mode==='whole')return new Response(data,{status:200,headers:{'Content-Length':String(data.length)}});
  const first=mode==='wrong-offset'&&start?start-1:start;
  const body=mode==='double-seek'&&start?data.subarray(start*2,end+1):mode==='overread'&&start?data.subarray(start):data.subarray(start,end+1);
  return new Response(body,{status:206,headers:{'Content-Range':`bytes ${first}-${end}/${data.length}`,'Content-Length':String(end-start+1)}});
 };
 return()=>reads;
}
async function test(name,fn){await fn();results.push({name,status:'PASS'});}
(async()=>{try{
 await test('Exact ranges, first PCM offset44 and final clipped sample',async()=>{const b=wav();const count=serve(b);const r=new Reader('/music.wav');await r.open();const f=await r.mono22050(0,32,{});for(let i=0;i<32;i++)assert(Math.abs(f[i]-b.readInt16LE(44+i*2)/32768)<1e-7);const end=await r.mono22050(r.samples-2,8,{});assert(end.slice(2).every(v=>v===0));assert(count()>=3);assert.equal(r.cached,null);});
 await test('Chromium double seek reproduction rejected as transport error',async()=>{serve(wav(),{mode:'double-seek'});const r=new Reader('/music.wav');await r.open();await assert.rejects(()=>r.mono22050(0,500,{}),/incomplete audio chunk/);});
 await test('Range overread rejected without blaming source music',async()=>{serve(wav(),{mode:'overread'});const r=new Reader('/music.wav');await r.open();await assert.rejects(()=>r.mono22050(0,500,{}),/transfer exceeded/);});
 await test('Wrong range start rejected',async()=>{serve(wav(),{mode:'wrong-offset'});const r=new Reader('/music.wav');await r.open();await assert.rejects(()=>r.mono22050(0,500,{}),/requested position/);});
 await test('Server without Range uses complete bounded cache',async()=>{const count=serve(wav(),{mode:'whole'});const r=new Reader('/music.wav');await r.open();await r.mono22050(0,400,{});await r.mono22050(400,400,{});assert.equal(count(),1);});
 await test('WAV metadata larger than64KiB and odd padding',async()=>{const b=wav({junk:70001});serve(b);const r=new Reader('/large-header.wav');await r.open();assert.equal(r.offset,70054);assert.equal((await r.mono22050(0,100,{})).length,100);});
 await test('Actual truncated WAV detected before model inference',async()=>{const b=wav();serve(b.subarray(0,b.length-8));const r=new Reader('/truncated.wav');await assert.rejects(()=>r.open(),/saved WAV file is incomplete/);});
 await test('PCM16/24/32 and IEEEfloat32 decoding with edge padding',async()=>{for(const [bits,format] of [[16,1],[24,1],[32,1],[32,3]]){serve(wav({bits,format}));const r=new Reader('/music.wav');await r.open();const f=await r.mono22050(-20,120,{});assert(f.slice(0,20).every(v=>v===0));assert(Math.abs(f[60]-Math.sin(40/41)*.6)<.0001);}});
 await test('Malformed PCM alignment and float encoding rejected',async()=>{for(const mutate of [b=>b.writeUInt16LE(3,32),b=>b.writeUInt16LE(3,20)]){const b=wav();mutate(b);serve(b);await assert.rejects(()=>new Reader('/bad.wav').open(),/supported PCM/);}});
 await test('Actual bundled music reads byte-exact at nonzero offsets',async()=>{const b=fs.readFileSync(require('path').join(__dirname,'../web/demo/glass-castle.wav'));serve(b);const r=new Reader('/demo.wav');await r.open();assert.equal(r.duration,64);for(const start of [44,40000,b.length-250])assert.deepEqual(Buffer.from(await r.bytes(start,Math.min(b.length-1,start+249))),b.subarray(start,Math.min(b.length,start+250)));});
 console.log(JSON.stringify({result:'PASS',tests:results},null,2));
 }finally{global.fetch=originalFetch;}})().catch(e=>{console.error(e);process.exitCode=1;});
