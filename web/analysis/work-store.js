/* Durable, checksummed model work. Each OPFS write becomes visible only on close.
 * Records are bound to the analysis identity, stage name, payload, and immutable
 * invalidation-fence snapshots. A failed physical delete or a stale WebView can
 * therefore never revive a dependent checkpoint after it has been invalidated.
 */
(function(root){'use strict';
const NS='lightforge-analysis-v1',MAX_JSON=24*1024*1024,MAX_FLOATS=16*1024*1024;
const IDENTITY='identity',CONTROL='cache-control',RECORD_VERSION=3,CONTROL_VERSION=1,FENCE_VERSION=1,FENCE_PREFIX='cache-fence-';
const validKey=k=>typeof k==='string'&&/^[a-f0-9]{64}$/.test(k);
const validName=n=>typeof n==='string'&&/^[a-z][a-z0-9-]{0,79}$/.test(n);
const internalName=n=>n===IDENTITY||n===CONTROL;
const validFenceToken=value=>typeof value==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(value);
const fenceFile=token=>FENCE_PREFIX+token+'.json';
const fenceFileToken=name=>{const match=typeof name==='string'&&new RegExp('^'+FENCE_PREFIX+'([a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12})\\.json$').exec(name);return match?match[1]:null;};
function newFenceToken(){if(typeof crypto.randomUUID==='function'){const token=crypto.randomUUID().toLowerCase();if(validFenceToken(token))return token;}if(typeof crypto.getRandomValues!=='function')throw Error('Secure storage invalidation identifiers are unavailable.');const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;const hex=Array.from(bytes,value=>value.toString(16).padStart(2,'0')).join('');return hex.slice(0,8)+'-'+hex.slice(8,12)+'-'+hex.slice(12,16)+'-'+hex.slice(16,20)+'-'+hex.slice(20);}
function staleWorkError(message){const error=new Error(message);error.code='analysis-cache-stale';return error;}
// Wall-clock metadata must never decide whether a checkpoint is valid. Some
// embedders expose Date.now through a guarded bridge, so retain a harmless
// sentinel when that bridge is unavailable rather than interrupting a durable
// identity write or invalidation fence.
const metadataNow=()=>{try{const value=Date.now();return Number.isFinite(value)&&value>=0?value:0;}catch{return 0;}};
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
function canonical(value){
 if(value===null)return 'null';
 if(typeof value==='string')return JSON.stringify(value);
 if(typeof value==='boolean')return value?'true':'false';
 if(typeof value==='number'){if(!Number.isFinite(value))throw Error('Cache identity contains an invalid number.');return JSON.stringify(value);}
 if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
 if(value&&Object.prototype.toString.call(value)==='[object Object]'){const keys=Object.keys(value).sort();return '{'+keys.map(key=>JSON.stringify(key)+':'+canonical(value[key])).join(',')+'}';}
 throw Error('Cache identity must contain only JSON values.');
}
async function contentAddress(domain,identity){
 if(!validName(domain))throw Error('Invalid cache domain.');
 return hash(new TextEncoder().encode(canonical({schemaVersion:1,domain,identity})));
}
async function namespace(){if(!navigator.storage?.getDirectory)throw Error('Update Android System WebView to use recoverable analysis.');return(await navigator.storage.getDirectory()).getDirectoryHandle(NS,{create:true});}
async function discard(key){if(!validKey(key))return;try{await(await namespace()).removeEntry(key,{recursive:true});}catch(e){if(e.name!=='NotFoundError')throw e;}}
function matchesPrefix(name,prefix){return name===prefix||name.startsWith(prefix+'-');}
async function open(key,{sourceId='',requiredBytes=0,resourceDiagnostics=null}={}){
 if(!validKey(key))throw Error('Invalid analysis checkpoint identity.');
 if(typeof sourceId!=='string'||sourceId.length>80||!Number.isSafeInteger(requiredBytes)||requiredBytes<0)throw Error('Invalid analysis checkpoint request.');
 const resource=(direction,bytes)=>{
  // Diagnostics are strictly observational: a bad/incompatible observer must
  // never make a durable checkpoint unreadable or alter its write order.
  try{if(resourceDiagnostics&&typeof resourceDiagnostics.io==='function'&&Number.isSafeInteger(bytes)&&bytes>=0)resourceDiagnostics.io(direction,bytes,'opfs-analysis-store');}catch(_){ }
 };
 const bytesOf=value=>value instanceof ArrayBuffer||ArrayBuffer.isView(value)?value.byteLength:typeof value==='string'?new TextEncoder().encode(value).byteLength:0;
 const parent=await namespace();
 // Cleanup is best effort: another job's abandoned lock must not prevent work.
 for await(const [name,entry]of parent.entries())if(name!==key&&entry.kind==='directory'&&validKey(name)){
  try{const marker=await(await entry.getFileHandle('identity.json')).getFile();if(metadataNow()-marker.lastModified>7*86400000)await parent.removeEntry(name,{recursive:true});}catch{}
 }
 const dir=await parent.getDirectoryHandle(key,{create:true});
 const nameOf=(name,suffix)=>{if(!validName(name))throw Error('Invalid analysis checkpoint name.');return name+suffix;};
 const recovery={schemaVersion:1,kind:'analysis-cache-recovery',legacyControlMigrated:false,corruptControlDiscarded:false,invalidationFences:0,pendingPhysicalDeletes:0,corruptRecords:0};
 let control,authorizedControl;const authorizedFences=new Set();
 async function atomic(name,parts){
  let stream;
  try{stream=await(await dir.getFileHandle(name,{create:true})).createWritable();let bytes=0;for(const part of parts){await stream.write(part);bytes+=bytesOf(part);}await stream.close();resource('write',bytes);}
  catch(e){if(stream)await stream.abort().catch(()=>{});if(e.name==='QuotaExceededError')throw Error('Device storage filled while saving analysis progress. Free storage, then resume this song.');throw e;}
 }
 async function file(name,max){try{const f=await(await dir.getFileHandle(name)).getFile();return f.size>0&&f.size<=max?f:null;}catch(e){if(e.name==='NotFoundError')return null;throw e;}}
 async function record(name,max=MAX_JSON){
  const f=await file(nameOf(name,'.json'),max);if(!f)return {state:'missing'};
  try{
   const text=await f.text();resource('read',f.size);const envelope=JSON.parse(text);
   if((envelope.version!==1&&envelope.version!==2&&envelope.version!==RECORD_VERSION)||envelope.key!==key||envelope.name!==name||typeof envelope.payload!=='string'||typeof envelope.sha256!=='string'||await hash(new TextEncoder().encode(envelope.payload))!==envelope.sha256)return {state:'corrupt'};
   const generation=envelope.version===1?0:envelope.generation;
   const fences=envelope.version===RECORD_VERSION&&!internalName(name)?envelope.fences:[];
   if(!internalName(name)&&(!Number.isSafeInteger(generation)||generation<0||!Array.isArray(fences)||fences.some(token=>!validFenceToken(token))||new Set(fences).size!==fences.length||fences.some((token,index)=>index&&fences[index-1]>=token)))return {state:'corrupt'};
   return {state:'ok',recordVersion:envelope.version,payload:decode(envelope.payload),generation:internalName(name)?0:generation,fences};
  }catch(e){if(e instanceof SyntaxError||e instanceof TypeError)return {state:'corrupt'};throw e;}
 }
 function generation(name,value=control){let current=0;for(const [prefix,revision]of Object.entries(value.generations))if(matchesPrefix(name,prefix))current=Math.max(current,revision);return current;}
 const sameFences=(left,right)=>left.length===right.length&&left.every((token,index)=>token===right[index]);
 async function writeRecord(name,value,{generationValue=0,fences=[]}={}){
  nameOf(name,'.json');const payload=encode(value);if(typeof payload!=='string')throw Error('Invalid analysis checkpoint payload.');
  const encoded=new TextEncoder().encode(payload);if(encoded.length>MAX_JSON)throw Error('Analysis checkpoint is too large.');
  const envelope={version:RECORD_VERSION,key,name,payload,sha256:await hash(encoded)};
  if(!internalName(name)){if(!Array.isArray(fences)||fences.some(token=>!validFenceToken(token))||new Set(fences).size!==fences.length||fences.some((token,index)=>index&&fences[index-1]>=token))throw Error('Invalid analysis invalidation fence snapshot.');envelope.generation=generationValue;envelope.fences=fences;}
  const bytes=new TextEncoder().encode(JSON.stringify(envelope));if(bytes.length>MAX_JSON)throw Error('Analysis checkpoint is too large.');
  await atomic(name+'.json',[bytes]);
 }
 async function readFence(fileName){
  const token=fenceFileToken(fileName),f=token?await file(fileName,MAX_JSON):null;if(!token||!f)return {state:'corrupt'};
  try{const text=await f.text();resource('read',f.size);const envelope=JSON.parse(text);if(envelope.version!==FENCE_VERSION||typeof envelope.payload!=='string'||typeof envelope.sha256!=='string'||await hash(new TextEncoder().encode(envelope.payload))!==envelope.sha256)return {state:'corrupt'};const payload=JSON.parse(envelope.payload);if(!payload||payload.version!==FENCE_VERSION||payload.key!==key||payload.sourceId!==sourceId||payload.token!==token||!Array.isArray(payload.prefixes)||!payload.prefixes.length||payload.prefixes.some(prefix=>!validName(prefix)||internalName(prefix))||new Set(payload.prefixes).size!==payload.prefixes.length||payload.prefixes.some((prefix,index)=>index&&payload.prefixes[index-1]>=prefix))return {state:'corrupt'};return {state:'ok',token,payload};}
  catch(error){if(error instanceof SyntaxError||error instanceof TypeError)return {state:'corrupt'};throw error;}
 }
 async function fences(){
  const values=[];for await(const [fileName,entry]of dir.entries()){
   if(entry.kind!=='file'||!fenceFileToken(fileName))continue;
   const item=await readFence(fileName);if(item.state!=='ok')throw Error('Analysis invalidation fence is corrupt. Start a fresh analysis again.');values.push(item);
  }
  return values.sort((left,right)=>left.token.localeCompare(right.token));
 }
 async function matchingFences(name){return (await fences()).filter(item=>item.payload.prefixes.some(prefix=>matchesPrefix(name,prefix))).map(item=>item.token);}
async function writeFence(prefixes){const token=newFenceToken(),name=fenceFile(token),payload=JSON.stringify({version:FENCE_VERSION,key,sourceId,token,prefixes}),envelope=JSON.stringify({version:FENCE_VERSION,payload,sha256:await hash(new TextEncoder().encode(payload))});try{await atomic(name,[new TextEncoder().encode(envelope)]);}catch(error){try{await dir.removeEntry(name);}catch(_){}throw error;}return token;}
 async function clearAll(){for await(const [name]of dir.entries())try{await dir.removeEntry(name,{recursive:true});}catch(e){if(e.name!=='NotFoundError')throw e;}}
 async function clearExceptIdentity(){for await(const [name]of dir.entries())if(name!=='identity.json')try{await dir.removeEntry(name,{recursive:true});}catch(e){if(e.name!=='NotFoundError')throw e;}}
 let identityRecord=await record(IDENTITY);
 if(identityRecord.state==='ok'&&(identityRecord.payload?.version!==1||identityRecord.payload?.key!==key||identityRecord.payload?.sourceId!==sourceId))throw Error('Analysis progress belongs to different audio.');
 if(identityRecord.state!=='ok'){
  // A missing or corrupt identity makes every other record untrusted.
  await clearAll();
  if(requiredBytes){const space=await navigator.storage.estimate().catch(()=>({}));if(space.quota&&space.quota-(space.usage||0)<requiredBytes+64*1024*1024)throw Error('Free device storage before analyzing this song. Recoverable analysis needs temporary space for completed passages.');}
  await writeRecord(IDENTITY,{key,sourceId,version:1,updatedAt:metadataNow()});
 }else await writeRecord(IDENTITY,{key,sourceId,version:1,updatedAt:metadataNow()});
 const controlRecord=await record(CONTROL);
 const validControl=value=>value&&value.version===CONTROL_VERSION&&value.key===key&&value.sourceId===sourceId&&value.generations&&Object.getPrototypeOf(value.generations)===Object.prototype&&Object.entries(value.generations).every(([prefix,value])=>validName(prefix)&&Number.isSafeInteger(value)&&value>=0);
 async function discardUntrustedCheckpoints(reason){
  try{await clearExceptIdentity();}
  catch(error){throw Error('Analysis checkpoint '+reason+' while old work is still busy. Wait for the previous analysis to stop, then resume this song.');}
 }
 if(controlRecord.state==='missing'){
  const legacyIdentity=identityRecord.state==='ok'&&identityRecord.recordVersion===1;
  if(identityRecord.state==='ok'&&!legacyIdentity){
   // A version-two-or-newer identity proves this namespace already used
   // durable invalidation state. Missing control can therefore be a lost
   // fence, not a legacy namespace: discard dependent records rather than
   // letting a physically locked pre-fence checkpoint become a cache hit.
   await discardUntrustedCheckpoints('control is missing');
   recovery.corruptControlDiscarded=true;
  }
  control={version:CONTROL_VERSION,key,sourceId,generations:{},updatedAt:metadataNow()};
  recovery.legacyControlMigrated=legacyIdentity;
  await writeRecord(CONTROL,control);
 }else if(controlRecord.state!=='ok'||!validControl(controlRecord.payload)){
  // Do not retain checkpoints when the fence itself cannot be verified. This
  // is stricter than a best-effort delete and prevents an old dependent stage
  // from becoming a cache hit after interrupted invalidation.
  await discardUntrustedCheckpoints('control is corrupt');
  control={version:CONTROL_VERSION,key,sourceId,generations:{},updatedAt:metadataNow()};
  recovery.corruptControlDiscarded=true;
  await writeRecord(CONTROL,control);
 }else control=controlRecord.payload;
 authorizedControl={...control,generations:{...control.generations}};
 for(const item of await fences())authorizedFences.add(item.token);
 async function currentControl(){const item=await record(CONTROL);if(item.state!=='ok'||!validControl(item.payload))throw Error('Analysis invalidation control is corrupt. Start a fresh analysis again.');control=item.payload;return control;}
 async function writableFences(name){
  const current=await matchingFences(name);
  if(current.some(token=>!authorizedFences.has(token)))throw staleWorkError('Analysis work was invalidated by another session. Reopen and resume this song.');
  return current;
 }
 async function read(name){
  if(internalName(name)){const item=await record(name);return item.state==='ok'?item.payload:null;}
  const before=await matchingFences(name),item=await record(name),current=await currentControl(),after=await matchingFences(name);
  if(item.state!=='ok'){if(item.state==='corrupt')recovery.corruptRecords++;return null;}
  if(!sameFences(before,after)||item.generation!==generation(name,current)||!sameFences(item.fences,after))return null;
  return item.payload;
 }
 async function write(name,value){
  if(internalName(name)){await writeRecord(name,value);return;}
  const current=await currentControl();if(generation(name,current)!==generation(name,authorizedControl))throw staleWorkError('Analysis work was invalidated by another session. Reopen and resume this song.');
  const fenceIds=await writableFences(name);await writeRecord(name,value,{generationValue:generation(name,current),fences:fenceIds});
  if(!sameFences(fenceIds,await matchingFences(name)))throw staleWorkError('Analysis work was invalidated while saving. Reopen and resume this song.');
 }
 async function readFloats(name){
  const before=await matchingFences(name);
  const f=await file(nameOf(name,'.bin'),MAX_FLOATS);if(!f||f.size<8)return null;
  const prefix=await f.slice(0,4).arrayBuffer();resource('read',prefix.byteLength);if(prefix.byteLength!==4)return null;
  const headerSize=new DataView(prefix).getUint32(0,true);if(headerSize<1||headerSize>4096||4+headerSize>=f.size)return null;
  try{
   const headerText=await f.slice(4,4+headerSize).text();resource('read',headerSize);const meta=JSON.parse(headerText),bytes=await f.slice(4+headerSize).arrayBuffer();resource('read',bytes.byteLength);
   const metaGeneration=meta.version===1?0:meta.generation,metaFences=meta.version===RECORD_VERSION?meta.fences:[];
   const current=await currentControl(),after=await matchingFences(name);
   if((meta.version!==1&&meta.version!==2&&meta.version!==RECORD_VERSION)||meta.key!==key||meta.name!==name||!Array.isArray(meta.counts)||meta.counts.length<1||meta.counts.length>4||meta.counts.some(n=>!Number.isSafeInteger(n)||n<1)||!Number.isSafeInteger(metaGeneration)||metaGeneration<0||!Array.isArray(metaFences)||metaFences.some(token=>!validFenceToken(token))||new Set(metaFences).size!==metaFences.length||metaFences.some((token,index)=>index&&metaFences[index-1]>=token)||meta.counts.reduce((a,b)=>a+b,0)*4!==bytes.byteLength||await hash(bytes)!==meta.sha256||!sameFences(before,after)||metaGeneration!==generation(name,current)||!sameFences(metaFences,after))return null;
   const data=new DataView(bytes),arrays=[];let at=0;
   for(const count of meta.counts){const pcm=new Float32Array(count);for(let i=0;i<count;i++,at+=4){pcm[i]=data.getFloat32(at,true);if(!Number.isFinite(pcm[i]))return null;}arrays.push(pcm);}return arrays;
  }catch(e){if(e instanceof SyntaxError||e instanceof RangeError||e instanceof TypeError)return null;throw e;}
 }
 async function writeFloats(name,arrays){
  nameOf(name,'.bin');
  if(!Array.isArray(arrays)||!arrays.length||arrays.length>4||arrays.some(a=>!(a instanceof Float32Array)||!a.length))throw Error('Invalid passage checkpoint.');
  const size=arrays.reduce((n,a)=>n+a.byteLength,0);if(size>MAX_FLOATS-4100)throw Error('Passage checkpoint is too large.');
  const current=await currentControl();if(generation(name,current)!==generation(name,authorizedControl))throw staleWorkError('Analysis work was invalidated by another session. Reopen and resume this song.');
  const fenceIds=await writableFences(name),bytes=new Uint8Array(size),view=new DataView(bytes.buffer);let at=0;
  for(const pcm of arrays)for(const value of pcm){if(!Number.isFinite(value))throw Error('A passage contains invalid audio.');view.setFloat32(at,value,true);at+=4;}
  const header=new TextEncoder().encode(JSON.stringify({version:RECORD_VERSION,key,name,generation:generation(name,current),fences:fenceIds,counts:arrays.map(a=>a.length),sha256:await hash(bytes)})),prefix=new Uint8Array(4);
  new DataView(prefix.buffer).setUint32(0,header.length,true);await atomic(name+'.bin',[prefix,header,bytes]);
  if(!sameFences(fenceIds,await matchingFences(name)))throw staleWorkError('Analysis work was invalidated while saving. Reopen and resume this song.');
 }
 async function remove(name){if(internalName(name))throw Error('Internal analysis checkpoints cannot be removed.');for(const suffix of ['.json','.bin'])try{await dir.removeEntry(nameOf(name,suffix));}catch(e){if(e.name!=='NotFoundError')throw e;}}
 async function invalidate(prefixes){
  if(!Array.isArray(prefixes)||prefixes.some(p=>!validName(p)||internalName(p)))throw Error('Invalid checkpoint invalidation.');
 const unique=[...new Set(prefixes)].sort();
  if(!unique.length)return {invalidated:[],removed:0,pending:0};
  // Fences are immutable, so concurrent WebViews cannot overwrite another
  // invalidation. Physical removal is merely reclamation: a locked OPFS file
  // cannot make a stale record visible after cancellation.
  const token=await writeFence(unique);authorizedFences.add(token);
  recovery.invalidationFences+=unique.length;
  let removed=0,pending=0;
  for await(const [fileName,entry]of dir.entries()){
   if(entry.kind!=='file'||fileName==='identity.json'||fileName==='cache-control.json'||fenceFileToken(fileName))continue;
   const candidate=fileName.endsWith('.json')?fileName.slice(0,-5):fileName.endsWith('.bin')?fileName.slice(0,-4):'';
   if(!candidate||!unique.some(prefix=>matchesPrefix(candidate,prefix)))continue;
   try{await dir.removeEntry(fileName);removed++;}catch(e){if(e.name!=='NotFoundError'){pending++;}}
  }
  recovery.pendingPhysicalDeletes+=pending;
  return {invalidated:unique,removed,pending};
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
 const diagnostics=()=>({...recovery,invalidationGenerations:Object.keys(control.generations).length});
 return {key,read,write,readFloats,writeFloats,remove,invalidate,reserve,diagnostics};
}
root.LightForgeAnalysisStore={open,discard,validKey,hash,contentAddress,canonical};
})(typeof self!=='undefined'?self:globalThis);
