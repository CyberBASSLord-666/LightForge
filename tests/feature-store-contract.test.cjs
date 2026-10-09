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
function workerContext(){const context=vm.createContext({Float32Array,ArrayBuffer,DataView,Math,Promise,URL,importScripts:()=>{},postMessage:()=>{},self:null});context.self=context;vm.runInContext(source('worker.js'),context);return context;}
const bytes=value=>Buffer.from(value.buffer,value.byteOffset,value.byteLength);
function deterministicFloats(length,seed){const values=new Float32Array(length);for(let i=0;i<length;i++)values[i]=Math.fround(Math.sin((i+1)*seed)*.73+Math.cos((i+3)*seed)*.19);return values;}
function freshRhythmFeatures(n,duration){return {duration,beat:new Float32Array(n),down:new Float32Array(n),rms:deterministicFloats(n,.13),bass:deterministicFloats(n,.17),mid:deterministicFloats(n,.23),high:deterministicFloats(n,.29),colour:deterministicFloats(n*3,.31),fineRms:deterministicFloats(n*4,.37),chroma:deterministicFloats(Math.ceil(n/10)*12,.41),chromaStep:.2};}
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
test('cached rhythm payload restores byte-identical downstream feature buffers',async()=>{
 const worker=workerContext(),n=23,duration=.46,fresh=freshRhythmFeatures(n,duration);fresh.rms[0]=-0;fresh.colour[1]=-0;const bundle=worker.rhythmFeatureBundle(fresh,n);
 assert.equal(worker.validRhythmFeature(bundle,n,duration),true);
 const h=load(),store=await h.features.open(identity);await store.writeFloat32('rhythm-dsp-v2',bundle.arrays,{...bundle.metadata,producer:'dsp-feature-extractor-v2'});
 const hit=await (await load(h.disk).features.open(identity)).readFloat32('rhythm-dsp-v2');assert.ok(hit);assert.equal(worker.validRhythmFeature(hit,n,duration),true);
 const restored=worker.rhythmDataFromFeature(hit,n);
 assert.deepEqual(Object.keys(restored).sort(),Object.keys(fresh).sort());assert.equal(restored.duration,fresh.duration);assert.equal(restored.chromaStep,fresh.chromaStep);
 for(const field of ['beat','down','rms','bass','mid','high','colour','fineRms','chroma'])assert.deepEqual(bytes(restored[field]),bytes(fresh[field]),field+' cache hit differs from fresh downstream input');
 assert.equal(Object.is(restored.rms[0],-0),true);assert.equal(Object.is(restored.colour[1],-0),true);
});
test('rhythm worker reuses only shape-validated source features and keeps anonymous analysis fresh',async()=>{
 const context=workerContext();
 const n=2,feature={duration:1.5,chromaStep:.2,rms:Float32Array.of(.1,.2),bass:Float32Array.of(.3,.4),mid:Float32Array.of(.5,.6),high:Float32Array.of(.7,.8),colour:Float32Array.of(1,2,3,4,5,6),fineRms:Float32Array.of(1,2,3,4,5,6,7,8),chroma:new Float32Array(12)},bundle=context.rhythmFeatureBundle(feature,n);
 assert.equal(context.validRhythmFeature(bundle,n,1.5),true);assert.equal(context.validRhythmFeature({...bundle,arrays:[bundle.arrays[0].subarray(0,-1)]},n,1.5),false);assert.equal(context.validRhythmFeature({...bundle,metadata:{...bundle.metadata,fieldOrder:['bass',...bundle.metadata.fieldOrder.slice(1)]}},n,1.5),false);
 const data=context.rhythmDataFromFeature(bundle,n);assert.deepEqual(Array.from(data.rms),Array.from(feature.rms));assert.deepEqual(Array.from(data.beat),[0,0]);assert.deepEqual(Array.from(data.down),[0,0]);
 assert.equal(await context.reusableRhythmFeatures({analysisIdentity:'not-a-sha'},{}),null);
 assert.match(source('worker.js'),/work-store\.js','feature-store\.js/);
});
const config=JSON.parse(fs.readFileSync(path.join(root,'web/analysis/models/features.json'),'utf8'));
function typedIdentity(worker,n=23){return {...identity,transform:worker.rhythmTransform(audio,'c'.repeat(64),config,n/50)};}
async function changeRecord(h,store,edit){
 const file=await h.disk.file('lightforge-analysis-v1',store.identityKey,'feature-rhythm-dsp-v2-float-meta.json'),envelope=JSON.parse(file.data),payload=JSON.parse(envelope.payload);edit(payload);envelope.payload=JSON.stringify(payload);envelope.sha256=Buffer.from(await webcrypto.subtle.digest('SHA-256',Buffer.from(envelope.payload))).toString('hex');file.data=Buffer.from(JSON.stringify(envelope));
}
test('typed transforms distinguish source, global clock, geometry, dtype and frontend without legacy fallback',async()=>{
 const worker=workerContext(),h=load(),base=typedIdentity(worker),typed=await h.features.open(base),legacy=await h.features.open(identity);
 assert.notEqual(typed.identityKey,legacy.identityKey);
 const mutate=[t=>t.source.role='vocals',t=>t.clock.sampleRate=44100,t=>t.clock.originSeconds=.2,t=>t.frontend.configSha256='d'.repeat(64),t=>t.frontend.id='other-v1',t=>t.components[0].frameOriginSamples=1,t=>t.components[0].hopSamples=220,t=>t.components[0].window.samples=1410,t=>t.components[0].window.offsetSamples=-704,t=>t.components[0].window.kind='hann',t=>t.components[0].padding='reflect'];
 for(const edit of mutate){const changed=JSON.parse(JSON.stringify(base));edit(changed.transform);assert.notEqual((await h.features.open(changed)).identityKey,typed.identityKey);}
 for(const edit of [t=>t.dtype='float16',t=>t.shape[0]++,t=>t.source.sha256='d'.repeat(64),t=>t.components[0].extra=true,t=>t.components[0].shape=[Number.MAX_SAFE_INTEGER,2]]){const changed=JSON.parse(JSON.stringify(base));edit(changed.transform);assert.throws(()=>h.features.normalizeIdentity(changed));}
 const bundle=worker.rhythmFeatureBundle(freshRhythmFeatures(23,.46),23);await legacy.writeFloat32('rhythm-dsp-v2',bundle.arrays,bundle.metadata);assert.equal(await typed.readFloat32('rhythm-dsp-v2'),null);
 await typed.writeFloat32('rhythm-dsp-v2',bundle.arrays,bundle.metadata);
 await assert.rejects(typed.writeFloat32('rhythm-dsp-v2',[Float32Array.of(1)]),/shape/);
 await assert.rejects(typed.readFloat32('mel'),/name/);
 await assert.rejects(typed.write('rhythm-dsp-v2',{}),/Float32/);
 assert.ok(await typed.readFloat32('rhythm-dsp-v2'),'invalid write must preserve previous committed payload');
});
test('typed descriptors reject rechecksummed transform corruption and missing legacy metadata',async()=>{
 for(const edit of [r=>delete r.transform,r=>r.transform.clock.sampleRate=44100,r=>r.transform.components[0].padding='reflect',r=>r.lengths=[Number.MAX_SAFE_INTEGER]]){
  const worker=workerContext(),h=load(),store=await h.features.open(typedIdentity(worker)),bundle=worker.rhythmFeatureBundle(freshRhythmFeatures(23,.46),23);
  await store.writeFloat32('rhythm-dsp-v2',bundle.arrays,bundle.metadata);await changeRecord(h,store,edit);assert.equal(await store.readFloat32('rhythm-dsp-v2'),null);
 }
});
test('actual rhythm consumer uses typed identity and restores exact DSP values and summarized output',async()=>{
 const worker=workerContext(),h=load(),duration=.46,n=23;
 vm.runInContext(source('dsp.js'),worker);worker.LightForgeFeatureStore=h.features;worker.LightForgeAnalysisStore=h.context.LightForgeAnalysisStore;
 const options={analysisIdentity:audio,analysisAssetFingerprint:'e'.repeat(64)},store=await worker.reusableRhythmFeatures(options,config,null,duration);
 assert.equal(store.diagnostics().typedTransform,true);
 const extracted=new worker.LightForgeDSP.FeatureExtractor(config).extract(deterministicFloats((n-1)*441+1411,.013),0,n),fresh={duration,beat:new Float32Array(n),down:new Float32Array(n),chroma:new Float32Array(Math.ceil(n/10)*12),chromaStep:.2};
 for(const field of ['rms','bass','mid','high','colour','fineRms'])fresh[field]=extracted[field];
 for(let i=0;i<n;i++)for(let b=0;b<12;b++)fresh.chroma[Math.floor(i/10)*12+b]+=extracted.chroma[i*12+b]/10;
 const bundle=worker.rhythmFeatureBundle(fresh,n);await store.writeFloat32('rhythm-dsp-v2',bundle.arrays,bundle.metadata);
 const hit=await (await worker.reusableRhythmFeatures(options,config,null,duration)).readFloat32('rhythm-dsp-v2'),restored=worker.rhythmDataFromFeature(hit,n);
 for(const field of ['beat','down',...['rms','bass','mid','high','colour','fineRms','chroma']])assert.deepEqual(bytes(restored[field]),bytes(fresh[field]),field);
 assert.deepEqual(worker.LightForgeDSP.summarize(restored,{}),worker.LightForgeDSP.summarize(fresh,{}));
 const input=await worker.recurrenceEvidenceInput({duration},options,config,{resource:null,begin(){},end(){},cache(){}});assert.deepEqual(bytes(input.chroma),bytes(fresh.chroma));
 assert.equal(await worker.reusableRhythmFeatures(options,config,null,1000000),null,'oversize cache bypasses before packing');
});
test('feature payload budget and measured Float32 transfers stay bounded and observational',async()=>{
 const h=load(),events=[],resource={allocation:(bytes,count)=>events.push(['allocation',bytes,count]),copy:(bytes,count)=>events.push(['copy',bytes,count])},store=await h.features.open(identity,{resourceDiagnostics:resource});
 await store.writeFloat32('mel',[Float32Array.of(1,2,3)]);assert.deepEqual(events,[['allocation',12,1],['copy',12,1]]);events.length=0;
 await store.readFloat32('mel');assert.deepEqual(events,[['allocation',12,1],['allocation',12,1],['copy',12,1]]);
 await assert.rejects(store.writeFloat32('mel',[new Float32Array(Math.floor(h.features.maxFloatBytes/4)+1)]),/budget/);
 assert.deepEqual(Array.from((await store.readFloat32('mel')).arrays[0]),[1,2,3]);
 const broken=await h.features.open(identity,{resourceDiagnostics:{allocation(){throw Error('observer');},copy(){throw Error('observer');}}});assert.ok(await broken.readFloat32('mel'));
});
test('interrupted typed publication cannot revive stale metadata and can resume safely',async()=>{
 const worker=workerContext(),h=load(),store=await h.features.open(typedIdentity(worker)),bundle=worker.rhythmFeatureBundle(freshRhythmFeatures(23,.46),23);
 await store.writeFloat32('rhythm-dsp-v2',bundle.arrays,bundle.metadata);
 const directory=await (await h.disk.directory.getDirectoryHandle('lightforge-analysis-v1')).getDirectoryHandle(store.identityKey),original=directory.getFileHandle;
 directory.getFileHandle=async function(name,options){if(name==='feature-rhythm-dsp-v2-float-meta.json'&&options?.create)throw new DOMException('Interrupted','AbortError');return original.call(this,name,options);};
 await assert.rejects(store.writeFloat32('rhythm-dsp-v2',bundle.arrays,bundle.metadata),{name:'AbortError'});
 directory.getFileHandle=original;
 const resumed=await load(h.disk).features.open(typedIdentity(worker));assert.equal(await resumed.readFloat32('rhythm-dsp-v2'),null);
 await resumed.writeFloat32('rhythm-dsp-v2',bundle.arrays,bundle.metadata);assert.deepEqual(bytes((await resumed.readFloat32('rhythm-dsp-v2')).arrays[0]),bytes(bundle.arrays[0]));
});
