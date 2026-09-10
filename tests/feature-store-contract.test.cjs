'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{webcrypto}=require('node:crypto');
const root=path.resolve(__dirname,'..'),source=name=>fs.readFileSync(path.join(root,'web/analysis',name),'utf8'),missing=()=>new DOMException('Missing','NotFoundError');
function opfs(){
 const control={blocked:new Set()};
 class FileHandle{
  constructor(){this.kind='file';this.data=Buffer.alloc(0);this.time=Date.now();}
  async getFile(){const file=new Blob([this.data]);file.lastModified=this.time;return file;}
  async createWritable(){const handle=this,parts=[];let ended=false;return {async write(value){parts.push(Buffer.from(typeof value==='string'?value:value instanceof ArrayBuffer?new Uint8Array(value):value));},async close(){if(ended)throw Error('closed');handle.data=Buffer.concat(parts);handle.time=Date.now();ended=true;},async abort(){ended=true;}};}
 }
 class Directory{
  constructor(){this.kind='directory';this.children=new Map();}
  async getDirectoryHandle(name,{create=false}={}){if(!this.children.has(name)){if(!create)throw missing();this.children.set(name,new Directory());}const value=this.children.get(name);if(value.kind!=='directory')throw Error('Wrong type');return value;}
  async getFileHandle(name,{create=false}={}){if(!this.children.has(name)){if(!create)throw missing();this.children.set(name,new FileHandle());}const value=this.children.get(name);if(value.kind!=='file')throw Error('Wrong type');return value;}
  async removeEntry(name){if(control.blocked.has(name))throw new DOMException('Locked','InvalidStateError');if(!this.children.has(name))throw missing();this.children.delete(name);}
  async *entries(){yield* [...this.children.entries()];}
 }
 const directory=new Directory();return {directory,control,async file(...names){let entry=directory;for(const name of names.slice(0,-1))entry=await entry.getDirectoryHandle(name);return entry.getFileHandle(names.at(-1));},storage:{getDirectory:async()=>directory,estimate:async()=>({quota:8*1024**3,usage:0})}};
}
function load(disk=opfs()){
 const context=vm.createContext({crypto:webcrypto,TextEncoder,TextDecoder,ArrayBuffer,DataView,Uint8Array,Uint32Array,Float32Array,Blob,DOMException,navigator:{storage:disk.storage}});context.self=context;
 vm.runInContext(source('work-store.js'),context);vm.runInContext(source('feature-store.js'),context);return {disk,context,features:context.LightForgeFeatureStore};
}
const audio='a'.repeat(64),identity={audioIdentity:audio,preprocessingVersion:'pcm-44100-v2',modelVersions:{beat:'1.0.0',frontend:'1.0.0'},analysisConfiguration:{sampleRate:44100,mono:true}};
test('feature identity is content-addressed and independent of property insertion order',async()=>{
 const {features}=load(),left=await features.open(identity),right=await features.open({analysisConfiguration:{mono:true,sampleRate:44100},modelVersions:{frontend:'1.0.0',beat:'1.0.0'},preprocessingVersion:'pcm-44100-v2',audioIdentity:audio});
 const changed=await features.open({...identity,analysisConfiguration:{sampleRate:22050,mono:true}});
 assert.equal(left.identityKey,right.identityKey);assert.notEqual(left.identityKey,changed.identityKey);assert.match(left.identityKey,/^[a-f0-9]{64}$/);assert.throws(()=>features.normalizeIdentity({...identity,modelVersions:{}}),/model versions/);
});
test('valid JSON features restore exactly while a changed identity is a deterministic miss',async()=>{
 const h=load(),store=await h.features.open(identity,{sourceId:'track'});assert.equal(await store.read('rms'),null);
 await store.write('rms',{values:Float32Array.of(.25,-.5),stepSeconds:.02},{units:'linear'});
 const resumed=await load(h.disk).features.open(identity,{sourceId:'another-project'}),hit=await resumed.read('rms');
 assert.deepEqual(Array.from(hit.value.values),[.25,-.5]);assert.equal(hit.value.stepSeconds,.02);assert.equal(hit.metadata.units,'linear');
 const miss=await (await load(h.disk).features.open({...identity,preprocessingVersion:'pcm-44100-v3'},{sourceId:'track'})).read('rms');assert.equal(miss,null);
});
test('invalidating a locked physical feature record fences it from every later read',async()=>{
 const h=load(),store=await h.features.open(identity,{sourceId:'track'});await store.write('onset',{value:1});
 const directory=await (await h.disk.directory.getDirectoryHandle('lightforge-analysis-v1')).getDirectoryHandle(store.identityKey);h.disk.control.blocked.add('feature-onset-json.json');
 await store.invalidate(['onset']);assert.equal((await directory.getFileHandle('feature-onset-json.json')).kind,'file');assert.equal(await store.read('onset'),null);
 const resumed=await load(h.disk).features.open(identity,{sourceId:'track'});assert.equal(await resumed.read('onset'),null);assert.ok(resumed.diagnostics().cache.invalidationFences>=0);
});
test('Float32 descriptors reject corrupt or mismatched binary payloads instead of reusing it',async()=>{
 const h=load(),store=await h.features.open(identity,{sourceId:'track'});await store.writeFloat32('mel',[Float32Array.of(.1,.2),Float32Array.of(.3)],{hop:441});
 const hit=await store.readFloat32('mel');assert.equal(hit.arrays[0][0],Math.fround(.1));assert.equal(hit.arrays[0][1],Math.fround(.2));assert.equal(hit.metadata.hop,441);
 const binary=await h.disk.file('lightforge-analysis-v1',store.identityKey,'feature-mel-float.bin');binary.data[binary.data.length-1]^=1;
 const resumed=await load(h.disk).features.open(identity,{sourceId:'track'});assert.equal(await resumed.readFloat32('mel'),null);
});
test('malformed feature descriptors are invalidated rather than accepted as compatible',async()=>{
 const h=load(),store=await h.features.open(identity,{sourceId:'track'});await store.write('chroma',{value:[1,0,0]});
 const file=await h.disk.file('lightforge-analysis-v1',store.identityKey,'feature-chroma-json.json'),envelope=JSON.parse(file.data);const payload=JSON.parse(envelope.payload);payload.identityKey='b'.repeat(64);envelope.payload=JSON.stringify(payload);envelope.sha256=Buffer.from(await webcrypto.subtle.digest('SHA-256',Buffer.from(envelope.payload))).toString('hex');file.data=Buffer.from(JSON.stringify(envelope));
 assert.equal(await store.read('chroma'),null);
});
test('rhythm worker reuses only shape-validated source features and keeps anonymous analysis fresh',async()=>{
 const context=vm.createContext({Float32Array,ArrayBuffer,DataView,Math,Promise,URL,importScripts:()=>{},postMessage:()=>{},self:null});context.self=context;
 vm.runInContext(source('worker.js'),context);
 const n=2,feature={version:1,frameCount:n,duration:1.5,chromaStep:.2,rms:Float32Array.of(.1,.2),bass:Float32Array.of(.3,.4),mid:Float32Array.of(.5,.6),high:Float32Array.of(.7,.8),colour:Float32Array.of(1,2,3,4,5,6),fineRms:Float32Array.of(1,2,3,4,5,6,7,8),chroma:new Float32Array(12)};
 assert.equal(context.validRhythmFeature(feature,n,1.5),true);assert.equal(context.validRhythmFeature({...feature,high:Float32Array.of(.7)},n,1.5),false);
 const data=context.rhythmDataFromFeature(feature,n);assert.deepEqual(Array.from(data.rms),Array.from(feature.rms));assert.deepEqual(Array.from(data.beat),[0,0]);assert.deepEqual(Array.from(data.down),[0,0]);
 assert.equal(await context.reusableRhythmFeatures({analysisIdentity:'not-a-sha'},{}),null);
 assert.match(source('worker.js'),/work-store\.js','feature-store\.js/);
});
