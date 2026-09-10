/* Durable, checksummed model work. Each OPFS write becomes visible only on close.
 * The identity and record names are bound to their payloads so a
 * missing marker, interrupted write or misplaced file cannot become a hit.
 */
(function(root){'use strict';
const NS='lightforge-analysis-v1',MAX_JSON=24*1024*1024,MAX_FLOATS=16*1024*1024;
const validKey=k=>typeof k==='string'&&/^[a-f0-9]{64}$/.test(k);
const validName=n=>typeof n==='string'&&/^[a-z][a-z0-9-]{0,79}$/.test(n);
const hash=async bytes=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('');
const encode=value=>JSON.stringify(value,(_,v)=>{
 if(typeof v==='number'&&!Number.isFinite(v))throw Error('Analysis progress contains an invalid number.');
 return v instanceof Float32Array?{float32:Array.from(v)}:v;
});
const decode=text=>JSON.parse(text,(_,v)=>{
 if(v&&Object.keys(v).length===1&&Array.isArray(v.float32)){
  if(v.float32.some(n=>typeof n!=='number'||!Number.isFinite(n)))throw new TypeError('Invalid saved samples.');
  const values=Float32Array.from(v.float32);if(values.some(n=>!Number.isFinite(n)))throw new TypeError('Invalid saved samples.');return values;
 }return v;
});
async function namespace(){if(!navigator.storage?.getDirectory)throw Error('Update Android System WebView to use recoverable analysis.');return(await navigator.storage.getDirectory()).getDirectoryHandle(NS,{create:true});}
async function discard(key){if(!validKey(key))return;try{await(await namespace()).removeEntry(key,{recursive:true});}catch(e){if(e.name!=='NotFoundError')throw e;}}
async function open(key,{sourceId='',requiredBytes=0}={}){
 if(!validKey(key))throw Error('Invalid analysis checkpoint identity.');
 if(typeof sourceId!=='string'||sourceId.length>80||!Number.isSafeInteger(requiredBytes)||requiredBytes<0)throw Error('Invalid analysis checkpoint request.');
 const parent=await namespace();
 // Cleanup is best effort: another job's abandoned lock must not prevent work.
 for await(const [name,entry]of parent.entries())if(name!==key&&entry.kind==='directory'&&validKey(name)){
  try{const marker=await(await entry.getFileHandle('identity.json')).getFile();if(Date.now()-marker.lastModified>7*86400000)await parent.removeEntry(name,{recursive:true});}catch{}
 }
 const dir=await parent.getDirectoryHandle(key,{create:true});
 const nameOf=(name,suffix)=>{if(!validName(name))throw Error('Invalid analysis checkpoint name.');return name+suffix;};
 async function atomic(name,parts){
  let stream;
  try{stream=await(await dir.getFileHandle(name,{create:true})).createWritable();for(const part of parts)await stream.write(part);await stream.close();}
  catch(e){if(stream)await stream.abort().catch(()=>{});if(e.name==='QuotaExceededError')throw Error('Device storage filled while saving analysis progress. Free storage, then resume this song.');throw e;}
 }
 async function file(name,max){try{const f=await(await dir.getFileHandle(name)).getFile();return f.size>0&&f.size<=max?f:null;}catch(e){if(e.name==='NotFoundError')return null;throw e;}}
 async function read(name){
  const f=await file(nameOf(name,'.json'),MAX_JSON);if(!f)return null;
  try{
   const envelope=JSON.parse(await f.text());
   if(envelope.version!==1||envelope.key!==key||envelope.name!==name||typeof envelope.payload!=='string'||await hash(new TextEncoder().encode(envelope.payload))!==envelope.sha256)return null;
   return decode(envelope.payload);
  }catch(e){if(e instanceof SyntaxError||e instanceof TypeError)return null;throw e;}
 }
 async function write(name,value){
  nameOf(name,'.json');const payload=encode(value);if(typeof payload!=='string')throw Error('Invalid analysis checkpoint payload.');
  const encoded=new TextEncoder().encode(payload);if(encoded.length>MAX_JSON)throw Error('Analysis checkpoint is too large.');
  const bytes=new TextEncoder().encode(JSON.stringify({version:1,key,name,payload,sha256:await hash(encoded)}));if(bytes.length>MAX_JSON)throw Error('Analysis checkpoint is too large.');
  await atomic(name+'.json',[bytes]);
 }
 async function readFloats(name){
  const f=await file(nameOf(name,'.bin'),MAX_FLOATS);if(!f||f.size<8)return null;
  const prefix=await f.slice(0,4).arrayBuffer();if(prefix.byteLength!==4)return null;
  const headerSize=new DataView(prefix).getUint32(0,true);if(headerSize<1||headerSize>4096||4+headerSize>=f.size)return null;
  try{
   const meta=JSON.parse(await f.slice(4,4+headerSize).text()),bytes=await f.slice(4+headerSize).arrayBuffer();
   if(meta.version!==1||meta.key!==key||meta.name!==name||!Array.isArray(meta.counts)||meta.counts.length<1||meta.counts.length>4||meta.counts.some(n=>!Number.isSafeInteger(n)||n<1)||meta.counts.reduce((a,b)=>a+b,0)*4!==bytes.byteLength||await hash(bytes)!==meta.sha256)return null;
   const data=new DataView(bytes),arrays=[];let at=0;
   for(const count of meta.counts){const pcm=new Float32Array(count);for(let i=0;i<count;i++,at+=4){pcm[i]=data.getFloat32(at,true);if(!Number.isFinite(pcm[i]))return null;}arrays.push(pcm);}return arrays;
  }catch(e){if(e instanceof SyntaxError||e instanceof RangeError||e instanceof TypeError)return null;throw e;}
 }
 async function writeFloats(name,arrays){
  nameOf(name,'.bin');
  if(!Array.isArray(arrays)||!arrays.length||arrays.length>4||arrays.some(a=>!(a instanceof Float32Array)||!a.length))throw Error('Invalid passage checkpoint.');
  const size=arrays.reduce((n,a)=>n+a.byteLength,0);if(size>MAX_FLOATS-4100)throw Error('Passage checkpoint is too large.');
  const bytes=new Uint8Array(size),view=new DataView(bytes.buffer);let at=0;
  for(const pcm of arrays)for(const value of pcm){if(!Number.isFinite(value))throw Error('A passage contains invalid audio.');view.setFloat32(at,value,true);at+=4;}
  const header=new TextEncoder().encode(JSON.stringify({version:1,key,name,counts:arrays.map(a=>a.length),sha256:await hash(bytes)})),prefix=new Uint8Array(4);
  new DataView(prefix.buffer).setUint32(0,header.length,true);await atomic(name+'.bin',[prefix,header,bytes]);
 }
 async function remove(name){for(const suffix of ['.json','.bin'])try{await dir.removeEntry(nameOf(name,suffix));}catch(e){if(e.name!=='NotFoundError')throw e;}}
 async function invalidate(prefixes){
  if(!Array.isArray(prefixes)||prefixes.some(p=>!validName(p)))throw Error('Invalid checkpoint invalidation.');
  for await(const [name,entry]of dir.entries())if(entry.kind==='file'&&name!=='identity.json'&&prefixes.some(p=>name===p+'.json'||name===p+'.bin'||name.startsWith(p+'-')))await dir.removeEntry(name);
 }
 async function reserve({passages,stemBytes=0,onProgress=()=>{}}){
  if(!Array.isArray(passages)||passages.length>10000||!Number.isSafeInteger(stemBytes)||stemBytes<0)throw Error('Invalid analysis storage plan.');
  const names=new Set();let required=stemBytes+64*1024*1024;
  for(const passage of passages){
   if(!passage||!validName(passage.name)||names.has(passage.name)||!Array.isArray(passage.counts)||!passage.counts.length||passage.counts.length>4||passage.counts.some(n=>!Number.isSafeInteger(n)||n<1))throw Error('Invalid analysis storage plan.');
   names.add(passage.name);const bytes=passage.counts.reduce((sum,n)=>sum+n*4,0)+4100;
   if(bytes>MAX_FLOATS)throw Error('Invalid analysis passage size.');required+=bytes;
  }
  const estimate=await navigator.storage.estimate().catch(()=>({}));
  if(!Number.isFinite(estimate.quota)||estimate.quota<=0||!Number.isFinite(estimate.usage))return {checked:false};
  const available=Math.max(0,estimate.quota-estimate.usage);let credited=0;
  // With ample space no second checkpoint read is needed. Under pressure,
  // verify existing passages individually and credit their exact planned size.
  // Each verification is bounded to one passage; source audio is never rehashed.
  if(available<required)for(let i=0;i<passages.length;i++){
   const passage=passages[i],arrays=await readFloats(passage.name);
   if(arrays&&arrays.length===passage.counts.length&&arrays.every((a,j)=>a.length===passage.counts[j])){required-=passage.counts.reduce((sum,n)=>sum+n*4,0)+4100;credited++;}
   onProgress(i+1,passages.length);
  }
  if(available<required)throw Error('Free at least '+Math.ceil((required-available)/1000000)+' MB of device storage, then resume this song. Completed passages stay saved.');
  return {checked:true,requiredBytes:required,availableBytes:available,creditedPassages:credited};
 }
 const identity=await read('identity');
 if(identity&&(identity.version!==1||identity.key!==key||identity.sourceId!==sourceId))throw Error('Analysis progress belongs to different audio.');
 if(!identity){
  // An identity record is committed before any model work. Without it, every
  // existing record is untrusted even if its individual checksum is valid.
  for await(const [name]of dir.entries())await dir.removeEntry(name,{recursive:true});
  if(requiredBytes){const space=await navigator.storage.estimate().catch(()=>({}));if(space.quota&&space.quota-(space.usage||0)<requiredBytes+64*1024*1024)throw Error('Free device storage before analyzing this song. Recoverable analysis needs temporary space for completed passages.');}
 }
 await write('identity',{key,sourceId,version:1,updatedAt:Date.now()});
 return {key,read,write,readFloats,writeFloats,remove,invalidate,reserve};
}
root.LightForgeAnalysisStore={open,discard,validKey,hash};
})(typeof self!=='undefined'?self:globalThis);
