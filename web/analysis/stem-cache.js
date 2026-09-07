/* Private, replaceable analysis audio. Projects never depend on this cache to export. */
(function(root){'use strict';
const RATE=22050,NS='lightforge-stems-v1',validKey=k=>typeof k==='string'&&/^stem-[a-f0-9-]{36}$/.test(k);
async function directory(){if(!navigator.storage?.getDirectory)throw Error('Update Android System WebView to analyze separated musical parts.');return(await navigator.storage.getDirectory()).getDirectoryHandle(NS,{create:true});}
function header(samples,rate=RATE){const b=new ArrayBuffer(44),v=new DataView(b);const text=(at,s)=>{for(let i=0;i<s.length;i++)v.setUint8(at+i,s.charCodeAt(i));};text(0,'RIFF');v.setUint32(4,36+samples*4,true);text(8,'WAVEfmt ');v.setUint32(16,16,true);v.setUint16(20,3,true);v.setUint16(22,1,true);v.setUint32(24,rate,true);v.setUint32(28,rate*4,true);v.setUint16(32,4,true);v.setUint16(34,32,true);text(36,'data');v.setUint32(40,samples*4,true);return new Uint8Array(b);}
async function discard(key){
 if(!validKey(key))return false;
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
  catch{try{let abandoned=false;try{await handle.getFileHandle('aborted.json');abandoned=true;}catch{}const f=await(await handle.getFileHandle('started.json')).getFile();if(abandoned||Date.now()-f.lastModified>24*3600*1000)await dir.removeEntry(key,{recursive:true});}catch{}}
 }
 entries.sort((a,b)=>a.time-b.time);const budget=Math.max(512*1024*1024,needed*1.15);
 for(const item of entries)if(total+needed>budget){await dir.removeEntry(item.key,{recursive:true});total-=item.size;}
}
class DownsampleWriter{
 constructor(stream,filter,total){this.stream=stream;this.filter=filter;this.total=total;this.received=0;this.next=0;this.base=0;this.buffer=new Float32Array(0);}
 async push(pcm,start,final=false){
  if(!(pcm instanceof Float32Array)||start!==this.received||start+pcm.length>this.total)throw Error('Separated audio arrived out of sequence.');
  const joined=new Float32Array(this.buffer.length+pcm.length);joined.set(this.buffer);joined.set(pcm,this.buffer.length);this.buffer=joined;this.received+=pcm.length;
  const end=final?Math.ceil(this.total/2):Math.max(0,Math.floor((this.received-32)/2)+1),values=new Float32Array(Math.max(0,end-this.next));
  for(let i=0;i<values.length;i++){const center=(this.next+i)*2;let value=0;for(let j=0;j<this.filter.length;j++)value+=(this.buffer[center+j-31-this.base]||0)*this.filter[j];values[i]=Number.isFinite(value)?value:0;}
  if(values.length){const bytes=new ArrayBuffer(values.length*4),view=new DataView(bytes);for(let i=0;i<values.length;i++)view.setFloat32(i*4,values[i],true);await this.stream.write(bytes);}
  this.next=end;const keep=Math.max(this.base,this.next*2-31),offset=Math.min(this.buffer.length,Math.max(0,keep-this.base));this.buffer=this.buffer.slice(offset);this.base+=offset;
 }
 async finish(){if(this.received!==this.total)throw Error('Separated audio ended before the music did.');await this.push(new Float32Array(0),this.received,true);await this.stream.close();}
}
// Bounded reusable encoding storage; writes complete before the next refill.
class FloatWriter{
 constructor(stream){this.stream=stream;this.bytes=new Uint8Array(65536);this.view=new DataView(this.bytes.buffer);}
 async push(pcm){
  for(let start=0;start<pcm.length;start+=this.bytes.length/4){
   const count=Math.min(this.bytes.length/4,pcm.length-start);
   for(let i=0;i<count;i++){const value=pcm[start+i];if(!Number.isFinite(value))throw Error('Invalid full-resolution vocal sample.');this.view.setFloat32(i*4,value,true);}
   await this.stream.write(this.bytes.subarray(0,count*4));
  }
 }
}
async function create(key,sampleCount,config,sourceId=''){
 if(!validKey(key)||!Number.isSafeInteger(sampleCount)||sampleCount<44100||sampleCount>44100*14400+3)throw Error('Invalid separated-audio cache request.');
 const expected=Math.ceil(sampleCount/2),needed=132+expected*8+sampleCount*4;
 await prune(key,needed);const space=await navigator.storage.estimate().catch(()=>({}));if(space.quota&&space.quota-(space.usage||0)<needed+16*1024*1024)throw Error('Free some device storage before analyzing this song. Its separated audio needs temporary space.');
 const dir=await(await directory()).getDirectoryHandle(key,{create:true}),marker=await(await dir.getFileHandle('started.json',{create:true})).createWritable();await marker.write(JSON.stringify({createdAt:Date.now(),sourceId}));await marker.close();
 const writers={};let full;
 try{for(const name of ['vocals','accompaniment']){const stream=await(await dir.getFileHandle(name+'.wav',{create:true})).createWritable();await stream.write(header(expected));writers[name]=new DownsampleWriter(stream,config.resampleHalfFIR,sampleCount);}full=await(await dir.getFileHandle('voice-full.wav',{create:true})).createWritable();await full.write(header(sampleCount,44100));}
 catch(e){for(const writer of Object.values(writers))await writer.stream.abort().catch(()=>{});if(full)await full.abort().catch(()=>{});await discard(key);throw e;}
 const fullWriter=new FloatWriter(full);let finished=false;
 return{key,async append(chunk){if(finished)throw Error('Analysis audio is already complete.');if(chunk.sampleRate!==44100)throw Error('Separated audio has an unsupported sample rate.');if(!(chunk.vocals instanceof Float32Array)||!(chunk.accompaniment instanceof Float32Array)||chunk.vocals.length!==chunk.accompaniment.length)throw Error('Separated audio layers must have matching sample counts.');await writers.vocals.push(chunk.vocals,chunk.startSample);await writers.accompaniment.push(chunk.accompaniment,chunk.startSample);await fullWriter.push(chunk.vocals);},async finish(){for(const writer of Object.values(writers))await writer.finish();await full.close();const meta={version:1,key,createdAt:Date.now(),sampleRate:RATE,samples:expected,duration:sampleCount/44100,sourceId,fullSamples:sampleCount};const stream=await(await dir.getFileHandle('complete.json',{create:true})).createWritable();await stream.write(JSON.stringify(meta));await stream.close();finished=true;return meta;},async abort(){if(full)await full.abort().catch(()=>{});for(const writer of Object.values(writers))await writer.stream.abort().catch(()=>{});await discard(key);}};
}
async function files(meta){
 if(!meta||meta.version!==1||!validKey(meta.key)||meta.sampleRate!==RATE||!Number.isSafeInteger(meta.samples)||!Number.isFinite(meta.duration)||Math.abs(meta.samples/RATE-meta.duration)>1/RATE)throw Error('Analyze this song again to listen to its separated parts.');
 const dir=await(await directory()).getDirectoryHandle(meta.key),stored=JSON.parse(await(await(await dir.getFileHandle('complete.json')).getFile()).text());
 if(stored.version!==1||stored.key!==meta.key||stored.sourceId!==meta.sourceId||stored.samples!==meta.samples||stored.sampleRate!==RATE||Math.abs(stored.duration-meta.duration)>1/RATE)throw Error('The separated audio does not match this project. Analyze the song again.');
 if(!Number.isSafeInteger(stored.samples)||stored.samples<1||stored.samples>RATE*14400+2||!Number.isFinite(stored.duration)||stored.duration<1||stored.duration>14401)throw Error('The separated audio metadata is invalid. Analyze this song again.');
 const result={};for(const name of ['vocals','accompaniment']){const file=await(await dir.getFileHandle(name+'.wav')).getFile();if(file.size!==44+stored.samples*4)throw Error('The separated audio is incomplete. Analyze this song again.');const actual=new Uint8Array(await file.slice(0,44).arrayBuffer()),expected=header(stored.samples);if(actual.length!==44||actual.some((v,i)=>v!==expected[i]))throw Error('The separated audio header is damaged. Analyze this song again.');result[name]=file;}return result;
}
async function readers(meta){const source=await files(meta),out={};for(const [name,file]of Object.entries(source)){const reader=new root.LightForgeWavReader('');reader.bytes=async(start,end)=>{if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start<0||end<start)throw Error('Invalid cached-audio bounds.');reader.totalBytes=file.size;return file.slice(start,Math.min(file.size,end+1)).arrayBuffer();};await reader.open();out[name]=reader;}return out;}
async function fullVoice(meta){
 await files(meta);if(!Number.isSafeInteger(meta.fullSamples)||Math.abs(meta.fullSamples/44100-meta.duration)>1/44100)throw Error('Re-analyze to recover full-resolution voice audio.');
 const dir=await(await directory()).getDirectoryHandle(meta.key),file=await(await dir.getFileHandle('voice-full.wav')).getFile();
 if(file.size!==44+meta.fullSamples*4)throw Error('Full-resolution voice audio is incomplete.');
 const actual=new Uint8Array(await file.slice(0,44).arrayBuffer()),expected=header(meta.fullSamples,44100);if(actual.some((v,i)=>v!==expected[i]))throw Error('Full-resolution voice header is invalid.');
 return async(start,count)=>{if(!Number.isSafeInteger(start)||!Number.isSafeInteger(count)||start<0||count<0||start+count>meta.fullSamples)throw Error('Invalid full-resolution voice bounds.');const buffer=await file.slice(44+start*4,44+(start+count)*4).arrayBuffer(),view=new DataView(buffer),out=new Float32Array(count);for(let i=0;i<count;i++)out[i]=view.getFloat32(i*4,true);return out;};
}
root.LightForgeStemCache={create,files,readers,fullVoice,discard,prune,validKey,header,DownsampleWriter,FloatWriter};
})(typeof self!=='undefined'?self:globalThis);
