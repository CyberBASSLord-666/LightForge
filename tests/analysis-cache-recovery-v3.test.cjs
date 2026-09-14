'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{webcrypto}=require('node:crypto');
const root=path.resolve(__dirname,'..'),source=name=>fs.readFileSync(path.join(root,'web/analysis',name),'utf8');
const missing=()=>new DOMException('Missing','NotFoundError');
function opfs(){
 const control={failWrite:false,blocked:new Set()};
 class FileHandle{
  constructor(){this.kind='file';this.data=Buffer.alloc(0);this.time=Date.now();}
  async getFile(){const file=new Blob([this.data]);file.lastModified=this.time;return file;}
  async createWritable(){
   const handle=this,parts=[];let ended=false;
   return {async write(data){if(control.failWrite){control.failWrite=false;throw new DOMException('Full','QuotaExceededError');}parts.push(Buffer.from(typeof data==='string'?data:data instanceof ArrayBuffer?new Uint8Array(data):data));},async close(){if(ended)throw Error('already closed');handle.data=Buffer.concat(parts);handle.time=Date.now();ended=true;},async abort(){ended=true;}};
  }
 }
 class Directory{
  constructor(){this.kind='directory';this.children=new Map();}
  async getDirectoryHandle(name,{create=false}={}){if(!this.children.has(name)){if(!create)throw missing();this.children.set(name,new Directory());}const value=this.children.get(name);if(value.kind!=='directory')throw Error('Wrong type');return value;}
  async getFileHandle(name,{create=false}={}){if(!this.children.has(name)){if(!create)throw missing();this.children.set(name,new FileHandle());}const value=this.children.get(name);if(value.kind!=='file')throw Error('Wrong type');return value;}
  async removeEntry(name){if(control.blocked.has(name))throw new DOMException('Locked','InvalidStateError');if(!this.children.has(name))throw missing();this.children.delete(name);}
  async *entries(){yield* [...this.children.entries()];}
 }
 const directory=new Directory();
 return {directory,control,async file(...names){let entry=directory;for(const name of names.slice(0,-1))entry=await entry.getDirectoryHandle(name);return entry.getFileHandle(names.at(-1));},storage:{getDirectory:async()=>directory,estimate:async()=>({quota:8*1024**3,usage:0})}};
}
function load(disk=opfs(),wallClock=Date){
 const context=vm.createContext({crypto:webcrypto,TextEncoder,TextDecoder,ArrayBuffer,DataView,Uint8Array,Uint32Array,Float32Array,Blob,DOMException,setTimeout,clearTimeout,Date:wallClock,navigator:{storage:disk.storage}});context.self=context;
 vm.runInContext(source('work-store.js'),context);vm.runInContext(source('stem-cache.js'),context);
 return {disk,context,store:context.LightForgeAnalysisStore,stems:context.LightForgeStemCache};
}
const key='c'.repeat(64),stemKey='stem-11111111-1111-1111-1111-111111111111';
function hostileDate(mode){
 const wallClock={};
 Object.defineProperty(wallClock,'now',{get(){if(mode==='getter')throw Error('hostile Date.now getter');return ()=>{if(mode==='call')throw Error('hostile Date.now call');return 1700000000000;};}});
 return wallClock;
}
test('content addresses canonicalize cache domains without carrying source paths',async()=>{
 const {store}=load();
 const left=await store.contentAddress('stems',{audio:'a'.repeat(64),model:{b:2,a:1},settings:{quality:'precision'}});
 const reordered=await store.contentAddress('stems',{settings:{quality:'precision'},model:{a:1,b:2},audio:'a'.repeat(64)});
 const otherDomain=await store.contentAddress('vocal',{audio:'a'.repeat(64),model:{a:1,b:2},settings:{quality:'precision'}});
 assert.equal(left,reordered);assert.notEqual(left,otherDomain);assert.match(left,/^[a-f0-9]{64}$/);assert.throws(()=>store.canonical({path:undefined}),/JSON values/);
});
test('streamed stem SHA-256 agrees with published vectors across chunk boundaries',()=>{
 const {stems}=load(),digest=new stems.Sha256(),bytes=Buffer.from('The quick brown fox jumps over the lazy dog');
 for(let at=0;at<bytes.length;at+=5)digest.update(new Uint8Array(bytes.buffer,bytes.byteOffset+at,Math.min(5,bytes.length-at)));
 assert.equal(digest.hex(),'d7a8fbb307d7809469ca9abcb0082e4f8d5651e46d3cdb762d02d0bf37c9e592');
});
test('atomic invalidation fence prevents a locked dependent checkpoint from reviving on resume',async()=>{
 const {disk,store}=load(),work=await store.open(key,{sourceId:'track'});
 await work.write('voice',{revision:1});
 const directory=await (await disk.directory.getDirectoryHandle('lightforge-analysis-v1')).getDirectoryHandle(key);
 disk.control.blocked.add('voice.json');
 const receipt=await work.invalidate(['voice']);
 assert.equal(receipt.pending,1);assert.equal((await directory.getFileHandle('voice.json')).kind,'file');
 assert.equal(await work.read('voice'),null,'fenced record must not be a cache hit');
 const resumed=await store.open(key,{sourceId:'track'});
 assert.equal(await resumed.read('voice'),null,'fence survives process restart');
 await resumed.write('voice',{revision:2});
 assert.equal((await resumed.read('voice')).revision,2);
 assert.deepEqual(Object.keys(resumed.diagnostics()).sort(),['corruptControlDiscarded','corruptRecords','invalidationFences','invalidationGenerations','kind','legacyControlMigrated','pendingPhysicalDeletes','schemaVersion'].sort());
});
test('independent immutable fences keep stale handles from reviving locked JSON or Float32 work',async()=>{
 const firstContext=load(),disk=firstContext.disk,secondContext=load(disk),first=await firstContext.store.open(key,{sourceId:'track'}),second=await secondContext.store.open(key,{sourceId:'track'});
 await first.write('voice',{revision:1});await first.write('bass',{revision:1});await first.writeFloats('deux-0',[Float32Array.of(.25,-0)]);
 disk.control.blocked.add('voice.json');disk.control.blocked.add('bass.json');disk.control.blocked.add('deux-0.bin');
 await first.invalidate(['voice','deux']);
 assert.equal(await second.read('voice'),null,'an already-open handle must observe another handle’s voice fence');
 assert.equal(await second.readFloats('deux-0'),null,'an already-open handle must observe another handle’s binary fence');
 await assert.rejects(second.write('voice',{revision:2}),error=>error?.code==='analysis-cache-stale');
 await assert.rejects(second.writeFloats('deux-0',[Float32Array.of(.5)]),error=>error?.code==='analysis-cache-stale');
 await second.invalidate(['bass']);
 const resumed=await load(disk).store.open(key,{sourceId:'track'});
 assert.equal(await resumed.read('voice'),null);assert.equal(await resumed.read('bass'),null);assert.equal(await resumed.readFloats('deux-0'),null);
 await resumed.write('voice',{revision:3});await resumed.writeFloats('deux-0',[Float32Array.of(-0,.75)]);
 assert.equal((await resumed.read('voice')).revision,3);assert.equal(Object.is((await resumed.readFloats('deux-0'))[0][0],-0),true);
});
test('an empty invalidation is a safe no-op and does not create a corrupt fence',async()=>{
 const {store}=load(),work=await store.open(key,{sourceId:'track'});await work.write('voice',{revision:1});
 const receipt=await work.invalidate([]);assert.deepEqual([...receipt.invalidated],[]);assert.equal(receipt.removed,0);assert.equal(receipt.pending,0);
 assert.equal((await work.read('voice')).revision,1);
});
test('failed fence write preserves the old committed checkpoint until a valid retry commits',async()=>{
 const {disk,store}=load(),work=await store.open(key,{sourceId:'track'});await work.write('bass',{revision:1});
 disk.control.failWrite=true;
 await assert.rejects(work.invalidate(['bass']),/storage filled/);
 assert.equal((await work.read('bass')).revision,1);
 await work.invalidate(['bass']);
 assert.equal(await work.read('bass'),null);
});
test('a corrupt invalidation control record discards all stages before resume',async()=>{
 const {disk,store}=load(),work=await store.open(key,{sourceId:'track'});await work.write('rhythm',{ok:true});await work.writeFloats('deux-0',[Float32Array.of(.25)]);
 (await disk.file('lightforge-analysis-v1',key,'cache-control.json')).data=Buffer.from('{corrupt');
 const resumed=await store.open(key,{sourceId:'track'});
 assert.equal(await resumed.read('rhythm'),null);assert.equal(await resumed.readFloats('deux-0'),null);assert.equal(resumed.diagnostics().corruptControlDiscarded,true);
});
test('a missing post-invalidation control record cannot revive a locked stale checkpoint',async()=>{
 const {disk,store}=load(),work=await store.open(key,{sourceId:'track'});
 await work.write('voice',{revision:1});
 const directory=await (await disk.directory.getDirectoryHandle('lightforge-analysis-v1')).getDirectoryHandle(key);
 disk.control.blocked.add('voice.json');
 await work.invalidate(['voice']);
 await directory.removeEntry('cache-control.json');
 await assert.rejects(store.open(key,{sourceId:'track'}),/control is missing while old work is still busy/,'a missing v2 control fence must not make the pre-fence record visible');
 disk.control.blocked.delete('voice.json');
 const resumed=await store.open(key,{sourceId:'track'});
 assert.equal(await resumed.read('voice'),null,'the retry must clear the stale pre-fence record instead of restoring it');
});
test('a control-less version-one namespace remains eligible for its one-time safe migration',async()=>{
 const {disk,store}=load(),work=await store.open(key,{sourceId:'track'});
 const directory=await (await disk.directory.getDirectoryHandle('lightforge-analysis-v1')).getDirectoryHandle(key);
 async function legacy(name,value){
  const payload=JSON.stringify(value),envelope={version:1,key,name,payload,sha256:await store.hash(new TextEncoder().encode(payload))};
  (await directory.getFileHandle(name+'.json',{create:true})).data=Buffer.from(JSON.stringify(envelope));
 }
 await legacy('identity',{key,sourceId:'track',version:1,updatedAt:0});
 await legacy('rhythm',{revision:1});
 await directory.removeEntry('cache-control.json');
 const resumed=await store.open(key,{sourceId:'track'});
 assert.equal((await resumed.read('rhythm')).revision,1);
 assert.equal(resumed.diagnostics().legacyControlMigrated,true);
 assert.equal(resumed.diagnostics().corruptControlDiscarded,false);
});
test('hostile Date.now cannot block checkpoint open, recovery, or invalidation fences',async()=>{
 for(const mode of ['getter','call']){
  const disk=opfs(),{store}=load(disk,hostileDate(mode)),work=await store.open(key,{sourceId:'track'});
  await work.write('voice',{revision:1});await work.invalidate(['voice']);assert.equal(await work.read('voice'),null);
  const resumed=await load(disk,hostileDate(mode)).store.open(key,{sourceId:'track'});assert.equal(await resumed.read('voice'),null,'fence remains durable after '+mode+' failure');
  const identity=JSON.parse((await disk.file('lightforge-analysis-v1',key,'identity.json')).data);const control=JSON.parse((await disk.file('lightforge-analysis-v1',key,'cache-control.json')).data);
  assert.equal(identity.payload.includes('"updatedAt":0'),true);assert.equal(control.payload.includes('"updatedAt":0'),true);
 }
});
test('hostile Date.now cannot prevent atomic stem-cache completion or later recovery',async()=>{
 for(const mode of ['getter','call']){
  const disk=opfs(),{stems}=load(disk,hostileDate(mode)),samples=44100,config={resampleHalfFIR:Float32Array.of(1)},values=new Float32Array(samples);
  const writer=await stems.create(stemKey,samples,config,'track');await writer.append({sampleRate:44100,startSample:0,vocals:values,accompaniment:values});const meta=await writer.finish();
  assert.equal(meta.createdAt,0);await load(disk,hostileDate(mode)).stems.files(meta);await load(disk,hostileDate(mode)).stems.fullVoice(meta);
 }
});
test('new completed stem caches reject interior PCM corruption while legacy completion markers remain structurally compatible',async()=>{
 const {disk,stems}=load(),samples=44100,config={resampleHalfFIR:Float32Array.of(1)},values=new Float32Array(samples);
 values[100]=.75;
 const writer=await stems.create(stemKey,samples,config,'track');await writer.append({sampleRate:44100,startSample:0,vocals:values,accompaniment:new Float32Array(samples)});const meta=await writer.finish();
 assert.equal(meta.version,2);assert.match(meta.files['vocals.wav'].sha256,/^[a-f0-9]{64}$/);await stems.files(meta);await stems.fullVoice(meta);
 const vocal=await disk.file('lightforge-stems-v1',stemKey,'vocals.wav'),original=Buffer.from(vocal.data);vocal.data[64]^=1;
 const fresh=load(disk);await assert.rejects(fresh.stems.files(meta),/integrity check failed/);
 vocal.data=original;
 const legacy={...meta,version:1};delete legacy.files;(await disk.file('lightforge-stems-v1',stemKey,'complete.json')).data=Buffer.from(JSON.stringify(legacy));
 const legacyContext=load(disk);await legacyContext.stems.files(legacy);await legacyContext.stems.fullVoice(legacy);
});
