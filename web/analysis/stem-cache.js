/* Private, replaceable analysis audio. Projects never depend on this cache to export.
 * A v2 completion marker binds each finished WAV to a streamed SHA-256 digest so
 * an interrupted or silently damaged stem is never promoted into musical events.
 */
(function(root){'use strict';
const RATE=22050,NS='lightforge-stems-v1',HASH_CHUNK=1024*1024;
const validKey=k=>typeof k==='string'&&/^stem-[a-f0-9-]{36}$/.test(k);
const validDigest=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
const verified=new Set();
// Cache timestamps are retention/diagnostic metadata, never integrity input.
// A hostile or unavailable Date bridge must not turn a completed stem write
// into a partial cache or make a resumable analysis fail.
const metadataNow=()=>{try{const value=Date.now();return Number.isFinite(value)&&value>=0?value:0;}catch{return 0;}};
async function directory(){if(!navigator.storage?.getDirectory)throw Error('Update Android System WebView to analyze separated musical parts.');return(await navigator.storage.getDirectory()).getDirectoryHandle(NS,{create:true});}
function header(samples,rate=RATE){const b=new ArrayBuffer(44),v=new DataView(b);const text=(at,s)=>{for(let i=0;i<s.length;i++)v.setUint8(at+i,s.charCodeAt(i));};text(0,'RIFF');v.setUint32(4,36+samples*4,true);text(8,'WAVEfmt ');v.setUint32(16,16,true);v.setUint16(20,3,true);v.setUint16(22,1,true);v.setUint32(24,rate,true);v.setUint32(28,rate*4,true);v.setUint16(32,4,true);v.setUint16(34,32,true);text(36,'data');v.setUint32(40,samples*4,true);return new Uint8Array(b);}
// Incremental SHA-256 keeps verification bounded to a small buffer. WebCrypto's
// digest API accepts only a complete ArrayBuffer, which would make a long cached
// song require a second full-size allocation merely to validate recovery data.
const SHA_K=new Uint32Array([0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2]);
const rotr=(value,bits)=>(value>>>bits)|(value<<(32-bits));
class Sha256{
 constructor(){this.state=new Uint32Array([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]);this.buffer=new Uint8Array(64);this.used=0;this.total=0;this.done=false;this.words=new Uint32Array(64);}
 block(bytes,offset){
  const w=this.words;for(let i=0;i<16;i++){const at=offset+i*4;w[i]=((bytes[at]<<24)|(bytes[at+1]<<16)|(bytes[at+2]<<8)|bytes[at+3])>>>0;}
  for(let i=16;i<64;i++){const s0=rotr(w[i-15],7)^rotr(w[i-15],18)^(w[i-15]>>>3),s1=rotr(w[i-2],17)^rotr(w[i-2],19)^(w[i-2]>>>10);w[i]=(w[i-16]+s0+w[i-7]+s1)>>>0;}
  let [a,b,c,d,e,f,g,h]=this.state;
  for(let i=0;i<64;i++){const s1=rotr(e,6)^rotr(e,11)^rotr(e,25),choice=(e&f)^((~e)&g),temp1=(h+s1+choice+SHA_K[i]+w[i])>>>0,s0=rotr(a,2)^rotr(a,13)^rotr(a,22),majority=(a&b)^(a&c)^(b&c),temp2=(s0+majority)>>>0;h=g;g=f;f=e;e=(d+temp1)>>>0;d=c;c=b;b=a;a=(temp1+temp2)>>>0;}
  this.state[0]=(this.state[0]+a)>>>0;this.state[1]=(this.state[1]+b)>>>0;this.state[2]=(this.state[2]+c)>>>0;this.state[3]=(this.state[3]+d)>>>0;this.state[4]=(this.state[4]+e)>>>0;this.state[5]=(this.state[5]+f)>>>0;this.state[6]=(this.state[6]+g)>>>0;this.state[7]=(this.state[7]+h)>>>0;
 }
 update(input){
  if(this.done)throw Error('Digest is complete.');const bytes=input instanceof Uint8Array?input:new Uint8Array(input);this.total+=bytes.length;let at=0;
  if(this.used){const copied=Math.min(64-this.used,bytes.length);this.buffer.set(bytes.subarray(0,copied),this.used);this.used+=copied;at+=copied;if(this.used===64){this.block(this.buffer,0);this.used=0;}}
  while(at+64<=bytes.length){this.block(bytes,at);at+=64;}
  if(at<bytes.length){this.buffer.set(bytes.subarray(at),0);this.used=bytes.length-at;}
  return this;
 }
 hex(){
  if(!this.done){const bits=this.total*8,tail=new Uint8Array(this.used<56?64:128);tail.set(this.buffer.subarray(0,this.used));tail[this.used]=0x80;const high=Math.floor(bits/0x100000000)>>>0,low=bits>>>0,at=tail.length-8;tail[at]=(high>>>24)&255;tail[at+1]=(high>>>16)&255;tail[at+2]=(high>>>8)&255;tail[at+3]=high&255;tail[at+4]=(low>>>24)&255;tail[at+5]=(low>>>16)&255;tail[at+6]=(low>>>8)&255;tail[at+7]=low&255;for(let offset=0;offset<tail.length;offset+=64)this.block(tail,offset);this.done=true;}
  return Array.from(this.state,value=>value.toString(16).padStart(8,'0')).join('');
 }
}
async function digestFile(file){const digest=new Sha256();for(let at=0;at<file.size;at+=HASH_CHUNK)digest.update(new Uint8Array(await file.slice(at,Math.min(file.size,at+HASH_CHUNK)).arrayBuffer()));return digest.hex();}
function descriptor(meta,name){const value=meta?.files?.[name];if(!value||!Number.isSafeInteger(value.bytes)||value.bytes<44||!validDigest(value.sha256))throw Error('The separated audio integrity record is invalid. Analyze this song again.');return value;}
function verificationKey(meta,name,file,entry){return [meta.key,meta.createdAt,name,entry.sha256,file.size,Number(file.lastModified)||0].join('|');}
async function verify(file,meta,name){if(meta.version!==2)return;const entry=descriptor(meta,name),tag=verificationKey(meta,name,file,entry);if(verified.has(tag))return;if(file.size!==entry.bytes)throw Error('The separated audio is incomplete. Analyze this song again.');if(await digestFile(file)!==entry.sha256)throw Error('The separated audio integrity check failed. Analyze this song again.');verified.add(tag);}
async function discard(key){
 if(!validKey(key))return false;
 for(const tag of [...verified])if(tag.startsWith(key+'|'))verified.delete(tag);
 // Terminating a worker releases its OPFS writable locks asynchronously.
 // Retry the same private directory while those handles are being closed.
 for(const delay of [0,40,100,250,500,1000,1500,2000]){
  if(delay)await new Promise(resolve=>setTimeout(resolve,delay));
  try{await(await directory()).removeEntry(key,{recursive:true});return true;}
  catch(error){if(error?.name==='NotFoundError')return true;}
 }
 // If the WebView still owns a lock, make the incomplete job eligible for
 // cleanup on the next analysis instead of retaining it for the usual day.
 try{const dir=await(await directory()).getDirectoryHandle(key),stream=await(await dir.getFileHandle('aborted.json',{create:true})).createWritable();await stream.write('{}');await stream.close();}catch{}
 return false;
}
async function prune(protect,needed=0){
 const dir=await directory(),entries=[];let total=0;
 for await(const [key,handle]of dir.entries()){
  if(handle.kind!=='directory'||!validKey(key)||key===protect)continue;
  try{const file=await(await handle.getFileHandle('complete.json')).getFile(),meta=JSON.parse(await file.text());let size=0;for(const name of ['vocals.wav','accompaniment.wav'])size+=(await(await handle.getFileHandle(name)).getFile()).size;try{size+=(await(await handle.getFileHandle('voice-full.wav')).getFile()).size;}catch{}total+=size;entries.push({key,size,time:meta.createdAt||file.lastModified});}
  catch{try{let abandoned=false;try{await handle.getFileHandle('aborted.json');abandoned=true;}catch{}const f=await(await handle.getFileHandle('started.json')).getFile();if(abandoned||metadataNow()-f.lastModified>24*3600*1000)await dir.removeEntry(key,{recursive:true});}catch{}}
 }
 entries.sort((a,b)=>a.time-b.time);const budget=Math.max(512*1024*1024,needed*1.15);
 for(const item of entries)if(total+needed>budget){await dir.removeEntry(item.key,{recursive:true});for(const tag of [...verified])if(tag.startsWith(item.key+'|'))verified.delete(tag);total-=item.size;}
}
class DownsampleWriter{
 constructor(stream,filter,total,digest=new Sha256()){this.stream=stream;this.filter=filter;this.total=total;this.digest=digest;this.received=0;this.next=0;this.base=0;this.buffer=new Float32Array(0);}
 async push(pcm,start,final=false){
  if(!(pcm instanceof Float32Array)||start!==this.received||start+pcm.length>this.total)throw Error('Separated audio arrived out of sequence.');
  const joined=new Float32Array(this.buffer.length+pcm.length);joined.set(this.buffer);joined.set(pcm,this.buffer.length);this.buffer=joined;this.received+=pcm.length;
  const end=final?Math.ceil(this.total/2):Math.max(0,Math.floor((this.received-32)/2)+1),values=new Float32Array(Math.max(0,end-this.next));
  for(let i=0;i<values.length;i++){const center=(this.next+i)*2;let value=0;for(let j=0;j<this.filter.length;j++)value+=(this.buffer[center+j-31-this.base]||0)*this.filter[j];values[i]=Number.isFinite(value)?value:0;}
  if(values.length){const bytes=new ArrayBuffer(values.length*4),view=new DataView(bytes);for(let i=0;i<values.length;i++)view.setFloat32(i*4,values[i],true);const encoded=new Uint8Array(bytes);await this.stream.write(encoded);this.digest.update(encoded);}
  this.next=end;const keep=Math.max(this.base,this.next*2-31),offset=Math.min(this.buffer.length,Math.max(0,keep-this.base));this.buffer=this.buffer.slice(offset);this.base+=offset;
 }
 async finish(){if(this.received!==this.total)throw Error('Separated audio ended before the music did.');await this.push(new Float32Array(0),this.received,true);await this.stream.close();return this.digest.hex();}
}
// Bounded reusable encoding storage; writes complete before the next refill.
class FloatWriter{
 constructor(stream,digest=new Sha256()){this.stream=stream;this.digest=digest;this.bytes=new Uint8Array(65536);this.view=new DataView(this.bytes.buffer);}
 async push(pcm){
  for(let start=0;start<pcm.length;start+=this.bytes.length/4){
   const count=Math.min(this.bytes.length/4,pcm.length-start);
   for(let i=0;i<count;i++){const value=pcm[start+i];if(!Number.isFinite(value))throw Error('Invalid full-resolution vocal sample.');this.view.setFloat32(i*4,value,true);}
   const encoded=this.bytes.subarray(0,count*4);await this.stream.write(encoded);this.digest.update(encoded);
  }
 }
}
async function create(key,sampleCount,config,sourceId=''){
 if(!validKey(key)||!Number.isSafeInteger(sampleCount)||sampleCount<44100||sampleCount>44100*14400+3)throw Error('Invalid separated-audio cache request.');
 const expected=Math.ceil(sampleCount/2),needed=132+expected*8+sampleCount*4;
 await prune(key,needed);const space=await navigator.storage.estimate().catch(()=>({}));if(space.quota&&space.quota-(space.usage||0)<needed+16*1024*1024)throw Error('Free some device storage before analyzing this song. Its separated audio needs temporary space.');
 const dir=await(await directory()).getDirectoryHandle(key,{create:true}),marker=await(await dir.getFileHandle('started.json',{create:true})).createWritable();await marker.write(JSON.stringify({createdAt:metadataNow(),sourceId}));await marker.close();
 // Remove the commit marker before replacing any stem file. A worker killed
 // between independent stream closes must never expose a mixed old/new set.
 try{await dir.removeEntry('complete.json');}catch(e){if(e.name!=='NotFoundError')throw e;}
 const writers={},digests={};let full,fullDigest;
 try{
  for(const name of ['vocals','accompaniment']){const stream=await(await dir.getFileHandle(name+'.wav',{create:true})).createWritable(),digest=new Sha256(),initial=header(expected);await stream.write(initial);digest.update(initial);digests[name]=digest;writers[name]=new DownsampleWriter(stream,config.resampleHalfFIR,sampleCount,digest);}
  full=await(await dir.getFileHandle('voice-full.wav',{create:true})).createWritable();fullDigest=new Sha256();const fullHeader=header(sampleCount,44100);await full.write(fullHeader);fullDigest.update(fullHeader);
 }catch(e){for(const writer of Object.values(writers))await writer.stream.abort().catch(()=>{});if(full)await full.abort().catch(()=>{});await discard(key);throw e;}
 const fullWriter=new FloatWriter(full,fullDigest);let finished=false;
 return {key,async append(chunk){if(finished)throw Error('Analysis audio is already complete.');if(chunk.sampleRate!==44100)throw Error('Separated audio has an unsupported sample rate.');if(!(chunk.vocals instanceof Float32Array)||!(chunk.accompaniment instanceof Float32Array)||chunk.vocals.length!==chunk.accompaniment.length)throw Error('Separated audio layers must have matching sample counts.');await writers.vocals.push(chunk.vocals,chunk.startSample);await writers.accompaniment.push(chunk.accompaniment,chunk.startSample);await fullWriter.push(chunk.vocals);},async finish(){const files={};for(const name of ['vocals','accompaniment'])files[name+'.wav']={bytes:44+expected*4,sha256:await writers[name].finish()};await full.close();files['voice-full.wav']={bytes:44+sampleCount*4,sha256:fullDigest.hex()};const meta={version:2,key,createdAt:metadataNow(),sampleRate:RATE,samples:expected,duration:sampleCount/44100,sourceId,fullSamples:sampleCount,files};const stream=await(await dir.getFileHandle('complete.json',{create:true})).createWritable();await stream.write(JSON.stringify(meta));await stream.close();finished=true;return meta;},async abort(){if(full)await full.abort().catch(()=>{});for(const writer of Object.values(writers))await writer.stream.abort().catch(()=>{});await discard(key);}};
}
function validMeta(meta){return !!meta&&(meta.version===1||meta.version===2)&&validKey(meta.key)&&meta.sampleRate===RATE&&Number.isSafeInteger(meta.samples)&&Number.isFinite(meta.duration)&&Math.abs(meta.samples/RATE-meta.duration)<=1/RATE;}
async function storedMeta(meta){
 if(!validMeta(meta))throw Error('Analyze this song again to listen to its separated parts.');
 const dir=await(await directory()).getDirectoryHandle(meta.key),stored=JSON.parse(await(await(await dir.getFileHandle('complete.json')).getFile()).text());
 if(!validMeta(stored)||stored.version!==meta.version||stored.key!==meta.key||stored.sourceId!==meta.sourceId||stored.samples!==meta.samples||Math.abs(stored.duration-meta.duration)>1/RATE||stored.fullSamples!==meta.fullSamples)throw Error('The separated audio does not match this project. Analyze the song again.');
 if(!Number.isSafeInteger(stored.samples)||stored.samples<1||stored.samples>RATE*14400+2||!Number.isFinite(stored.duration)||stored.duration<1||stored.duration>14401)throw Error('The separated audio metadata is invalid. Analyze this song again.');
 if(stored.version===2)for(const name of ['vocals.wav','accompaniment.wav','voice-full.wav']){const left=descriptor(stored,name),right=descriptor(meta,name);if(left.bytes!==right.bytes||left.sha256!==right.sha256)throw Error('The separated audio integrity record does not match this project. Analyze this song again.');}
 return {dir,stored};
}
async function files(meta){
 const {dir,stored}=await storedMeta(meta),result={};
 for(const name of ['vocals','accompaniment']){const file=await(await dir.getFileHandle(name+'.wav')).getFile();if(file.size!==44+stored.samples*4)throw Error('The separated audio is incomplete. Analyze this song again.');const actual=new Uint8Array(await file.slice(0,44).arrayBuffer()),expected=header(stored.samples);if(actual.length!==44||actual.some((v,i)=>v!==expected[i]))throw Error('The separated audio header is damaged. Analyze this song again.');await verify(file,stored,name+'.wav');result[name]=file;}
 return result;
}
async function readers(meta){const source=await files(meta),out={};for(const [name,file]of Object.entries(source)){const reader=new root.LightForgeWavReader('');reader.bytes=async(start,end)=>{if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start<0||end<start)throw Error('Invalid cached-audio bounds.');reader.totalBytes=file.size;return file.slice(start,Math.min(file.size,end+1)).arrayBuffer();};await reader.open();out[name]=reader;}return out;}
async function fullVoice(meta){
 await files(meta);if(!Number.isSafeInteger(meta.fullSamples)||Math.abs(meta.fullSamples/44100-meta.duration)>1/44100)throw Error('Re-analyze to recover full-resolution voice audio.');
 const {dir,stored}=await storedMeta(meta),file=await(await dir.getFileHandle('voice-full.wav')).getFile();
 if(file.size!==44+meta.fullSamples*4)throw Error('Full-resolution voice audio is incomplete.');
 const actual=new Uint8Array(await file.slice(0,44).arrayBuffer()),expected=header(meta.fullSamples,44100);if(actual.length!==44||actual.some((v,i)=>v!==expected[i]))throw Error('Full-resolution voice header is invalid.');await verify(file,stored,'voice-full.wav');
 return async(start,count)=>{if(!Number.isSafeInteger(start)||!Number.isSafeInteger(count)||start<0||count<0||start+count>meta.fullSamples)throw Error('Invalid full-resolution voice bounds.');const buffer=await file.slice(44+start*4,44+(start+count)*4).arrayBuffer(),view=new DataView(buffer),out=new Float32Array(count);for(let i=0;i<count;i++)out[i]=view.getFloat32(i*4,true);return out;};
}
root.LightForgeStemCache={create,files,readers,fullVoice,discard,prune,validKey,header,DownsampleWriter,FloatWriter,Sha256,digestFile};
})(typeof self!=='undefined'?self:globalThis);
