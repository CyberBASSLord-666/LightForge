'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{webcrypto}=require('node:crypto');
const root=path.resolve(__dirname,'..'),source=name=>fs.readFileSync(path.join(root,'web/analysis',name),'utf8');
const missing=()=>new DOMException('Missing','NotFoundError');
function opfs(){
 const control={failWrite:false};
 class FileHandle{
  constructor(){this.kind='file';this.data=Buffer.alloc(0);this.time=Date.now();this.writers=0;}
  async getFile(){const file=new Blob([this.data]);file.lastModified=this.time;return file;}
  async createWritable(){
   this.writers++;const handle=this,parts=[];let ended=false;
   return {async write(data){if(control.failWrite){control.failWrite=false;throw new DOMException('Full','QuotaExceededError');}parts.push(Buffer.from(typeof data==='string'?data:data instanceof ArrayBuffer?new Uint8Array(data):data));},async close(){assert.equal(ended,false);handle.data=Buffer.concat(parts);handle.time=Date.now();handle.writers--;ended=true;},async abort(){if(!ended){ended=true;handle.writers--;}}};
  }
 }
 class Directory{
  constructor(){this.kind='directory';this.children=new Map();}
  async getDirectoryHandle(name,{create=false}={}){if(!this.children.has(name)){if(!create)throw missing();this.children.set(name,new Directory());}const value=this.children.get(name);if(value.kind!=='directory')throw Error('Wrong type');return value;}
  async getFileHandle(name,{create=false}={}){if(!this.children.has(name)){if(!create)throw missing();this.children.set(name,new FileHandle());}const value=this.children.get(name);if(value.kind!=='file')throw Error('Wrong type');return value;}
  async removeEntry(name){if(!this.children.has(name))throw missing();this.children.delete(name);}
  async *entries(){yield* [...this.children.entries()];}
 }
 const directory=new Directory();
 return {directory,control,async file(...names){let d=directory;for(const name of names.slice(0,-1))d=await d.getDirectoryHandle(name);return d.getFileHandle(names.at(-1));},storage:{getDirectory:async()=>directory,estimate:async()=>({quota:control.quota??8*1024**3,usage:control.usage??0})}};
}
function loadStore(disk=opfs()){
 const context=vm.createContext({crypto:webcrypto,TextEncoder,TextDecoder,ArrayBuffer,DataView,Uint8Array,Float32Array,Blob,DOMException,setTimeout,clearTimeout,navigator:{storage:disk.storage}});context.self=context;
 vm.runInContext(source('work-store.js'),context);vm.runInContext(source('stem-cache.js'),context);return {disk,context,store:context.LightForgeAnalysisStore,stems:context.LightForgeStemCache};
}
const key='a'.repeat(64),other='b'.repeat(64);
test('analysis checkpoints round-trip precise floats and reject changed, swapped and truncated records',async()=>{
 const {disk,store}=loadStore(),work=await store.open(key,{sourceId:'song-one'}),pcm=Float32Array.of(-.25,1e-8,0,Math.fround(Math.PI));
 await work.write('rhythm',{duration:2,values:pcm});await work.writeFloats('deux-0',[pcm,Float32Array.of(.5)]);
 assert.deepEqual((await work.read('rhythm')).values,pcm);assert.deepEqual((await work.readFloats('deux-0'))[0],pcm);
 const json=await disk.file('lightforge-analysis-v1',key,'rhythm.json'),original=Buffer.from(json.data);const altered=JSON.parse(json.data);altered.payload=altered.payload.replace('"duration":2','"duration":9');json.data=Buffer.from(JSON.stringify(altered));assert.equal(await work.read('rhythm'),null);json.data=original;
 const foreign=await store.open(other,{sourceId:'song-two'});await foreign.write('rhythm',{duration:9});(await disk.file('lightforge-analysis-v1',other,'rhythm.json')).data=original;assert.equal(await foreign.read('rhythm'),null,'Valid checksum from another source accepted');
 await work.write('voice',{duration:2});(await disk.file('lightforge-analysis-v1',key,'voice.json')).data=original;assert.equal(await work.read('voice'),null,'Valid checksum from another stage accepted');
 const binary=await disk.file('lightforge-analysis-v1',key,'deux-0.bin'),valid=Buffer.from(binary.data);binary.data[binary.data.length-1]^=1;assert.equal(await work.readFloats('deux-0'),null);binary.data=valid.subarray(0,10);assert.equal(await work.readFloats('deux-0'),null);
 await assert.rejects(work.writeFloats('deux-1',[Float32Array.of(NaN)]),/invalid audio/);await assert.rejects(work.write('voice',{score:Infinity}),/invalid number/);await assert.rejects(work.read('../outside'),/Invalid analysis checkpoint name/);
});
test('failed atomic replacement keeps the last committed passage and a damaged identity invalidates every saved stage',async()=>{
 const {disk,store}=loadStore(),work=await store.open(key,{sourceId:'song'});await work.write('rhythm',{duration:2});await work.writeFloats('deux-0',[Float32Array.of(.125)]);
 disk.control.failWrite=true;await assert.rejects(work.writeFloats('deux-0',[Float32Array.of(.75)]),/storage filled/);assert.deepEqual((await work.readFloats('deux-0'))[0],Float32Array.of(.125));
 await assert.rejects(store.open(key,{sourceId:'wrong-song'}),/different audio/);
 (await disk.file('lightforge-analysis-v1',key,'identity.json')).data=Buffer.from('{damaged');const repaired=await store.open(key,{sourceId:'song'});assert.equal(await repaired.read('rhythm'),null);assert.equal(await repaired.readFloats('deux-0'),null);
});
test('invalidating downstream voice work preserves expensive separation passages and unrelated rhythm',async()=>{
 const {store}=loadStore(),work=await store.open(key);for(const name of ['rhythm','separation','voice','voice-classifier','game-0-0','bass'])await work.write(name,{ok:true});await work.writeFloats('deux-0',[Float32Array.of(.25)]);
 await work.invalidate(['separation','voice','game','bass']);for(const name of ['separation','voice','voice-classifier','game-0-0','bass'])assert.equal(await work.read(name),null);assert.equal((await work.read('rhythm')).ok,true);assert.deepEqual((await work.readFloats('deux-0'))[0],Float32Array.of(.25));
});
test('rebuilding an audition cache removes its commit marker before independent stem writes',async()=>{
 const {stems}=loadStore(),config=require('../web/analysis/models/features.json'),cacheKey='stem-11111111-1111-1111-1111-111111111111',samples=44101;
 const first=await stems.create(cacheKey,samples,config,'song');await first.append({sampleRate:44100,startSample:0,vocals:new Float32Array(samples),accompaniment:new Float32Array(samples)});const meta=await first.finish();await stems.files(meta);
 const interrupted=await stems.create(cacheKey,samples,config,'song');await assert.rejects(stems.files(meta),e=>e.name==='NotFoundError');await interrupted.abort();
});
function analyzerHarness({behavior,native=false}={}){
 const workers=[],discarded=[],stageStarts=[];let active=0,maxActive=0;
 const context=vm.createContext({URL,crypto:webcrypto,TextEncoder,DOMException,AbortController,performance,setInterval,clearInterval,console,LightForgeVersion:{name:'2.2.1'},document:{currentScript:{src:'https://app.test/analysis/analyzer.js'}},LightForgeAnalysisStore:{hash:async bytes=>Buffer.from(await webcrypto.subtle.digest('SHA-256',bytes)).toString('hex'),discard:async id=>discarded.push(['work',id])},LightForgeStemCache:{discard:async id=>discarded.push(['stem',id])}});context.window=context;
 context.Worker=class{
  constructor(){this.closed=false;workers.push(this);active++;maxActive=Math.max(maxActive,active);}
  terminate(){if(!this.closed){this.closed=true;active--;}}
  postMessage(message){const m=structuredClone(message);if(m.stage){this.request=m;stageStarts.push(m.stage);}setImmediate(()=>{if(this.closed)return;if(behavior)return behavior(this,m);if(m.stage)this.finish(m);});}
  emit(data){if(!this.closed)this.onmessage({data});}
  finish(m=this.request){this.emit({type:'progress',value:{progress:{rhythm:.4,separation:.82,voice:.985,bass:1}[m.stage],stage:m.stage}});if(!this.closed)this.emit({type:'result',value:{...m.value,engine:{name:'test'},[m.stage]:true},seconds:1,restored:m.stage==='rhythm'});}
 };
 vm.runInContext(source('analyzer.js'),context);return {analyze:context.MusicAnalyzer.analyze,workers,discarded,stageStarts,context,get maxActive(){return maxActive;}};
}
test('public analyzer destroys each model heap before the next stage and clears only transient work after success',async()=>{
 const h=analyzerHarness(),progress=[],music=await h.analyze('/song.wav',{},p=>progress.push(p));assert.equal(h.maxActive,1);assert.deepEqual(h.stageStarts,['rhythm','separation','voice','bass']);assert.ok(h.workers.every(w=>w.closed));assert.equal(music.engine.stages.rhythm.restored,true);assert.equal(music.engine.recoverable,false);assert.deepEqual(h.discarded.map(x=>x[0]),['work']);assert.equal(progress.at(-1).completedStages,3);assert.equal(progress.at(-1).restoredStages,1);assert.ok(progress.every((p,i)=>i===0||p.progress>=progress[i-1].progress));
});
test('analysis cache identity separates analysis evidence while choreography and vehicle choices reuse heavy work',async()=>{
 const h=analyzerHarness(),options={analysisIdentity:key,analysisQuality:'precision',projectId:'song'};
 await h.analyze('/song.wav',options);await h.analyze('/song.wav',options);await h.analyze('/song.wav',{...options,enableEstimatedPercussionEvidence:false});await h.analyze('/song.wav',{...options,analysisQuality:'balanced'});await h.analyze('/song.wav',{...options,sensitivity:.7});
 await h.analyze('/song.wav',{...options,enableEstimatedPercussionEvidence:true});
 await h.analyze('/song.wav',{...options,semanticChoreography:true,motifEvolution:true,vehicleProfile:{revision:'calibrated-v2'}});
 assert.equal(h.workers[0].request.options.workId,h.workers[4].request.options.workId);assert.equal(h.workers[0].request.options.workId,h.workers[8].request.options.workId,'explicit false must share the default analysis namespace');
 assert.notEqual(h.workers[0].request.options.workId,h.workers[12].request.options.workId);assert.notEqual(h.workers[0].request.options.workId,h.workers[16].request.options.workId);
 assert.notEqual(h.workers[0].request.options.workId,h.workers[20].request.options.workId,'estimated percussion must not reuse a default rhythm cache');
 assert.equal(h.workers[20].request.options.enableEstimatedPercussionEvidence,true);
 assert.equal(h.workers[0].request.options.workId,h.workers[24].request.options.workId,'choreography/vehicle changes must not invalidate completed music analysis');
 assert.deepEqual(h.discarded,[]);
});
test('cancellation and stage failures preserve durable work and never start a downstream model',async()=>{
 const h=analyzerHarness(),controller=new AbortController();await assert.rejects(h.analyze('/song.wav',{analysisIdentity:key},p=>{if(p.stage==='separation')controller.abort();},controller.signal),e=>e.name==='AbortError');assert.deepEqual(h.stageStarts,['rhythm','separation']);assert.deepEqual(h.discarded,[]);assert.ok(h.workers.every(w=>w.closed));
 const transient=analyzerHarness({behavior(w,m){if(m.stage==='rhythm')w.emit({type:'error',message:'model failure'});}});await assert.rejects(transient.analyze('/song.wav'),/model failure/);assert.deepEqual(transient.discarded.map(x=>x[0]).sort(),['stem','work']);
});
test('native acceleration callback stays outside structured clone and its result returns to the requesting worker',async()=>{
 let invocation=0,progressForwarded=0;
 const h=analyzerHarness({behavior(w,m){if(m.stage==='separation')w.emit({type:'native-deux',requestId:7,startSample:-66150});else if(m.type==='native-deux-progress'){progressForwarded++;assert.equal(m.requestId,7);}else if(m.type==='native-deux-result'){assert.equal(m.requestId,7);assert.equal(m.url,'https://app.test/result.bin');w.finish();}else if(m.stage)w.finish(m);}});
 await h.analyze('/song.wav',{analysisIdentity:key,nativePredict:async(start,signal,progress)=>{invocation++;assert.equal(start,-66150);assert.equal(signal.aborted,false);progress({progress:.5,message:'Transformer'});progress({progress:.5,message:'Transformer'});return {url:'https://app.test/result.bin'};}});assert.equal(invocation,1);assert.equal(progressForwarded,1);assert.equal(h.workers[1].request.options.supportsNativeDeux,true);assert.equal('nativePredict' in h.workers[1].request.options,false);
});
test('aborting native acceleration cancels its operation and retains all completed passages',async()=>{
 const controller=new AbortController();let nativeSignal;
 const h=analyzerHarness({behavior(w,m){if(m.stage==='separation')w.emit({type:'native-deux',requestId:1,startSample:0});else if(m.stage)w.finish(m);}});
 await assert.rejects(h.analyze('/song.wav',{analysisIdentity:key,nativePredict:(start,signal)=>{nativeSignal=signal;setImmediate(()=>controller.abort());return new Promise(()=>{});}},()=>{},controller.signal),e=>e.name==='AbortError');assert.equal(nativeSignal.aborted,true);assert.deepEqual(h.discarded,[]);assert.deepEqual(h.stageStarts,['rhythm','separation']);
});
function gameHarness(){
 const records=new Map(),runs={encoder:0,loaded:0},manifest={id:'game-large-test'};
 class Tensor{constructor(type,data,dims){Object.assign(this,{type,data,dims});}dispose(){}}
 const f=(...v)=>new Tensor('float32',Float32Array.from(v),[1,v.length]),mask=()=>new Tensor('bool',Uint8Array.of(1),[1,1]);
 const ort={Tensor,InferenceSession:{create:async url=>{runs.loaded++;const name=path.basename(new URL(url).pathname,'.onnx');return {release:async()=>{},run:async feed=>{
  if(name==='encoder'){runs.encoder++;return {maskT:mask(),x_seg:f(1),x_est:f(1)};}
  if(name==='dur2bd'||name==='segmenter')return {boundaries:f(1)};
  if(name==='bd2dur')return {durations:f(.5),maskN:mask()};
  if(name==='estimator')return {scores:f(60),presence:mask()};throw Error(name);
 }}}}};
 const context=vm.createContext({URL,Float32Array,BigInt64Array,console,fetch:async()=>({json:async()=>manifest})});context.self=context;vm.runInContext(source('game.js'),context);
 const checkpoint={read:async key=>records.get(key)||null,write:async(key,value)=>records.set(key,structuredClone(value))};
 return {records,runs,checkpoint,create:()=>context.LightForgeGAME.create({ort,baseUrl:'https://app.test/',checkpoint})};
}
test('GAME resumes completed passages with identical note boundaries and without rereading or reloading cached inference',async()=>{
 const h=gameHarness(),rate=44100,total=rate*25+1,reads=[];const read=async(first,count)=>{reads.push(first);return new Float32Array(count).fill(.1);};
 let game=await h.create();await assert.rejects(game.process(read,total,{onProgress:(p,info)=>{if(info.checkpointSaved&&info.passagesCompleted===1)throw Error('Interrupted');}}),/Interrupted/);await game.release();assert.equal(h.runs.encoder,1);assert.equal(h.records.size,1);
 game=await h.create();const progress=[],result=await game.process(read,total,{onProgress:(p,info)=>progress.push(info)});await game.release();assert.equal(h.runs.encoder,3);assert.deepEqual(reads,[0,rate*10,rate*22]);assert.equal(progress.at(-1).restoredPassages,1);assert.equal(progress.at(-1).passagesCompleted,3);
 const before=h.runs.loaded;game=await h.create();const restored=await game.process(()=>{throw Error('Cached audio reread');},total);await game.release();assert.equal(h.runs.loaded,before,'Cached work loaded GAME model graphs');assert.deepEqual(restored,result);
 h.records.get('game-0-0').notes[0].midi=999;game=await h.create();await game.process(read,total);await game.release();assert.equal(h.runs.encoder,4,'Invalid checkpoint pitch was accepted');
});
function workerHarness({cached=null,brokenStems=false,nativeBytes=null,quotaFailure=false}={}){
 const messages=[],invalidations=[],writes=[],received=[],progress=[],reservations=[];let created=0,aborted=0,released=0;
 const context=vm.createContext({console,URL,Float32Array,ArrayBuffer,DataView,performance,Map,Number,setTimeout,crypto:webcrypto,navigator:{hardwareConcurrency:2},importScripts(){},ort:{env:{wasm:{}}},LightForgeAnalysisStore:{open:async()=>({read:async()=>cached,write:async(name,value)=>writes.push([name,value]),invalidate:async prefixes=>invalidations.push(Array.from(prefixes)),reserve:async plan=>{reservations.push(plan);if(quotaFailure)throw Error('Free at least 500 MB of device storage, then resume this song.');}})},LightForgeStemCache:{prune:async()=>{},files:async()=>{if(brokenStems)throw Error('Missing stems');},fullVoice:async()=>{},create:async()=>{created++;return {append:async chunk=>received.push(chunk),finish:async()=>({key:'rebuilt'}),abort:async()=>{aborted++;}};}},LightForgeWavReader:class{constructor(){this.samples=44100;this.duration=1;}async open(){}async stereo44100(){throw Error('Unexpected source read');}},fetch:async url=>{
  if(String(url).endsWith('features.json'))return {json:async()=>({})};if(String(url).endsWith('model-manifest.json'))return {json:async()=>({precision:{},balanced:{}})};
  return {ok:true,arrayBuffer:async()=>nativeBytes};
 },LightForgeMdxSeparator:{constants:require('../web/analysis/separator-mdx.js').constants},LightForgeDeux:{create:async options=>({release:async()=>{released++;},process:async(read,total,onChunk,onProgress)=>{
  const result=options.nativePredict?await options.nativePredict(-66150,(p,message)=>progress.push([p,message])):{vocals:new Float32Array(1),accompaniment:new Float32Array(1)};
  await onChunk({sampleRate:44100,startSample:0,...result});onProgress({progress:1,processedSeconds:1,message:'Done',passagesCompleted:1,passageCount:1,checkpointSaved:true});return {modelId:'same-model'};
 }})}});context.self=context;context.location={href:'https://app.test/analysis/worker.js'};
 context.postMessage=m=>{messages.push(m);if(m.type==='native-deux')setImmediate(async()=>{await context.onmessage({data:{type:'native-deux-progress',requestId:m.requestId,value:{progress:.5,message:'Block'}}});await context.onmessage({data:{type:'native-deux-result',requestId:m.requestId,url:'https://app.test/native.bin'}});});};
 vm.runInContext(source('worker.js'),context);
 return {messages,invalidations,writes,received,progress,reservations,storagePlan:context.separationStoragePlan,get created(){return created;},get aborted(){return aborted;},get released(){return released;},run:()=>context.onmessage({data:{stage:'separation',audioUrl:'/song.wav',value:{duration:1},options:{workId:key,cacheKey:'test',supportsNativeDeux:nativeBytes!==null}}})};
}
test('worker restores completed separation without creating a model or replacing audition audio',async()=>{
 const h=workerHarness({cached:{separation:{modelId:'same-model'},stemCache:{key:'saved'}}});await h.run();assert.equal(h.created,0);assert.equal(h.invalidations.length,0);assert.equal(h.messages.at(-1).restored,true);assert.equal(h.messages.at(-1).value.duration,1);assert.equal(h.messages.at(-1).value.stemCache.key,'saved');
});
test('worker invalidates derived stages when committed stems are missing and keeps passage checkpoint storage available',async()=>{
 const h=workerHarness({cached:{separation:{modelId:'same-model'},stemCache:{key:'missing'}},brokenStems:true});await h.run();assert.deepEqual(h.invalidations,[['separation','voice','game','bass']]);assert.equal(h.created,1);assert.equal(h.writes[0][0],'separation');assert.equal(h.messages.at(-1).value.stemCache.key,'rebuilt');assert.equal(h.released,1);assert.ok(h.messages.some(m=>m.type==='progress'&&m.value.checkpointSaved));
});
test('worker native transport preserves raw source floats and rejects truncated and non-finite output transactionally',async()=>{
 const bytes=new ArrayBuffer(573300*8),view=new DataView(bytes);view.setFloat32(0,1e-8,true);view.setFloat32(573300*4,-.25,true);const valid=workerHarness({nativeBytes:bytes});await valid.run();assert.equal(valid.received[0].vocals[0],Math.fround(1e-8));assert.equal(valid.received[0].accompaniment[0],-.25);assert.deepEqual(valid.progress,[[.5,'Block']]);assert.equal(valid.messages.at(-1).type,'result');
 for(const data of [new ArrayBuffer(8),bytes]){if(data===bytes)view.setFloat32(0,NaN,true);const broken=workerHarness({nativeBytes:data});await broken.run();assert.equal(broken.received.length,0);assert.equal(broken.aborted,1);assert.equal(broken.released,1);assert.equal(broken.messages.at(-1).type,'error');assert.match(broken.messages.at(-1).message,/incomplete|invalid samples/);assert.equal(broken.writes.length,0);}
});
test('native resources release after the worker consumes output and before the voice model starts',async()=>{
 const events=[];let fetched=false;
 const nativePredict=async()=>{events.push('native-result');return {url:'https://app.test/result.bin'};};
 nativePredict.release=async()=>{assert.equal(fetched,true,'Released before the worker consumed native output');events.push('release-start');await new Promise(r=>setImmediate(r));events.push('released');};
 const h=analyzerHarness({behavior(w,m){
  if(m.stage==='separation')w.emit({type:'native-deux',requestId:1,startSample:0});
  else if(m.type==='native-deux-result'){assert.deepEqual(events,['native-result']);setImmediate(()=>{fetched=true;events.push('worker-consumed');w.finish();});}
  else if(m.stage){if(m.stage==='voice'){assert.equal(events.at(-1),'released');events.push('voice-start');}w.finish(m);}
 }});
 await h.analyze('/song.wav',{analysisIdentity:key,nativePredict});assert.deepEqual(events,['native-result','worker-consumed','release-start','released','voice-start']);
});
test('restored separation still releases idle native resources before voice analysis',async()=>{
 const events=[],nativePredict=async()=>{throw Error('Cached separation requested inference');};nativePredict.release=async()=>events.push('released');
 const h=analyzerHarness({behavior(w,m){if(m.stage==='separation')w.emit({type:'result',restored:true,value:m.value});else if(m.stage){if(m.stage==='voice'){assert.deepEqual(events,['released']);events.push('voice-start');}w.finish(m);}}});
 await h.analyze('/song.wav',{analysisIdentity:key,nativePredict});assert.deepEqual(events,['released','voice-start']);
});
test('native cancellation precedes best-effort release and retains the original interruption error',async()=>{
 const events=[],controller=new AbortController();
 const nativePredict=(start,signal)=>{signal.addEventListener('abort',()=>events.push('cancelled'));setImmediate(()=>controller.abort());return new Promise(()=>{});};
 nativePredict.release=async()=>{events.push('release-attempt');throw Error('Native model still stopping');};
 const h=analyzerHarness({behavior(w,m){if(m.stage==='separation')w.emit({type:'native-deux',requestId:1,startSample:0});else if(m.stage)w.finish(m);}});
 await assert.rejects(h.analyze('/song.wav',{analysisIdentity:key,nativePredict},()=>{},controller.signal),e=>e.name==='AbortError');assert.deepEqual(events,['cancelled','release-attempt']);assert.deepEqual(h.stageStarts,['rhythm','separation']);assert.deepEqual(h.discarded,[]);
});
test('native release failure blocks the next model heap after successful separation',async()=>{
 const nativePredict=async()=>{throw Error('Unexpected inference');};nativePredict.release=async()=>{throw Error('Native resources could not close');};
 const h=analyzerHarness();await assert.rejects(h.analyze('/song.wav',{analysisIdentity:key,nativePredict}),/Native resources could not close/);assert.deepEqual(h.stageStarts,['rhythm','separation']);assert.deepEqual(h.discarded,[]);
});
test('storage admission includes remaining passages and final stems while crediting valid completed work on retry',async()=>{
 const {store,disk}=loadStore(),work=await store.open(key),counts=[4096,4096],perPassage=4096*8+4100,stemBytes=10000,headroom=64*1024*1024;
 const passages=[0,1,2].map(i=>({name:'deux-'+i,counts}));
 disk.control.quota=stemBytes+headroom+perPassage*2;disk.control.usage=0;
 await assert.rejects(work.reserve({passages,stemBytes}),/Free at least 1 MB.*resume.*Completed passages stay saved/);
 await work.writeFloats('deux-0',[new Float32Array(4096),new Float32Array(4096)]);
 const resumed=await work.reserve({passages,stemBytes});assert.equal(resumed.creditedPassages,1);assert.equal(resumed.requiredBytes,stemBytes+headroom+perPassage*2);
 await work.writeFloats('deux-1',[new Float32Array(4096),new Float32Array(4096)]);
 disk.control.quota=stemBytes+headroom+perPassage;const advanced=await work.reserve({passages,stemBytes});assert.equal(advanced.creditedPassages,2);
 const saved=await disk.file('lightforge-analysis-v1',key,'deux-1.bin');saved.data[saved.data.length-1]^=1;
 await assert.rejects(work.reserve({passages,stemBytes}),/Free at least 1 MB/);assert.notEqual(await work.readFloats('deux-0'),null,'Admission destroyed completed work');
});
test('storage admission skips redundant checkpoint validation when quota already covers worst-case work',async()=>{
 const {store,disk}=loadStore(),work=await store.open(key);let reads=0;
 const parent=await disk.directory.getDirectoryHandle('lightforge-analysis-v1'),directory=await parent.getDirectoryHandle(key),original=directory.getFileHandle.bind(directory);
 directory.getFileHandle=async(...args)=>{if(args[0].endsWith('.bin'))reads++;return original(...args);};
 const result=await work.reserve({passages:[{name:'deux-0',counts:[573300,573300]}],stemBytes:44100*8});assert.equal(result.checked,true);assert.equal(reads,0);
 await assert.rejects(work.reserve({passages:[{name:'deux-0',counts:[2]},{name:'deux-0',counts:[2]}]}),/Invalid analysis storage plan/);
});
test('worker reserves passage storage before opening model output writers and skips reservation for committed separation',async()=>{
 const full=workerHarness({quotaFailure:true});await full.run();assert.equal(full.reservations.length,1);assert.equal(full.created,0);assert.equal(full.received.length,0);assert.equal(full.messages.at(-1).type,'error');assert.match(full.messages.at(-1).message,/Free at least 500 MB/);
 const restored=workerHarness({cached:{separation:{modelId:'same-model'},stemCache:{key:'saved'}},quotaFailure:true});await restored.run();assert.equal(restored.reservations.length,0);assert.equal(restored.messages.at(-1).restored,true);
 for(const quality of ['precision','balanced'])for(const total of [44100,441000,441001,44100*25+1,44100*241+1]){
  const plan=full.storagePlan(total,quality),constants=require('../web/analysis/separator-mdx.js').constants,core=quality==='precision'?441000:constants.CORE,stride=quality==='precision'?220500:constants.STRIDE;
  assert.equal(plan.passages.length,1+Math.ceil(Math.max(0,total-core)/stride));assert.equal(plan.stemBytes,132+Math.ceil(total/2)*8+total*4);
  const count=quality==='precision'?573300:constants.INPUT_LENGTH;assert.ok(plan.passages.every(p=>p.counts.length===(quality==='precision'?2:1)&&p.counts.every(n=>n===count)));
 }
});

test('cached bass provenance migrates accompaniment mixtures without rereading stems',async()=>{
 const cached={duration:8,analysisVersion:7,beats:[0,.5,1,1.5],downbeats:[0],sections:[{start:0,end:8,energy:.5,label:'Groove'}],phrases:[],bassNotes:[{start:1.1,end:2.2,confidence:.8,strength:.7,midi:40}],bassAnalysis:{source:'separated-accompaniment',sourceSeparated:true,phrases:[{start:1.1,end:2.2,confidence:.8,strength:.7}]},vocals:{phrases:[],notes:[],accents:[]},roleAnalysis:{version:4,bassSource:'Low-register harmonics in separated accompaniment',sourceSeparated:true},warnings:[]};
 const messages=[],writes=[],context=vm.createContext({console,URL,Float32Array,ArrayBuffer,DataView,performance,Map,Number,setTimeout,crypto:webcrypto,navigator:{hardwareConcurrency:2},importScripts(){},ort:{env:{wasm:{}}},LightForgeSemanticTimeline:require('../web/analysis/semantic-timeline.js'),LightForgeMusicSalience:require('../web/analysis/salience.js'),LightForgeAnalysisStore:{open:async()=>({read:async()=>structuredClone(cached),write:async(name,value)=>writes.push([name,structuredClone(value)]),invalidate:async()=>{},reserve:async()=>{}})},fetch:async()=>({json:async()=>({precision:{},balanced:{},frontend:{}})}),postMessage:m=>messages.push(m)});
 context.self=context;context.location={href:'https://app.test/analysis/worker.js'};vm.runInContext(source('worker.js'),context);
 await context.onmessage({data:{stage:'bass',audioUrl:'/song.wav',value:{},options:{workId:key,projectId:'song'}}});
 const result=messages.at(-1);assert.equal(result.type,'result');assert.equal(result.restored,true);assert.equal(result.value.analysisVersion,8);assert.equal(result.value.bassAnalysis.source,'accompaniment-mixture-estimate');assert.equal(result.value.bassAnalysis.sourceSeparated,false);assert.equal(result.value.bassAnalysis.instrumentSeparated,false);assert.equal(result.value.bassNotes[0].sourceSeparated,false);assert.equal(result.value.roleAnalysis.version,5);assert.equal(result.value.roleAnalysis.bassInstrumentSeparated,false);assert.equal(result.value.semanticTimeline.schemaVersion,2);assert.equal(result.value.semanticTimeline.summary.hasSeparatedBass,false);assert.equal(result.value.semanticTimeline.summary.hasSeparatedAccompaniment,true);assert.equal(result.value.musicSalience.schemaVersion,1);assert.equal(require('../web/analysis/salience.js').validate(result.value.musicSalience,result.value.semanticTimeline).valid,true);assert.equal(writes[0][1].musicSalience.schemaVersion,1);assert.equal(writes.length,1);
});

test('analyzer acquires one heavy-job lease and releases it after success, failure, or optional-lock fallback',async()=>{
 const calls=[];
 const successful=analyzerHarness();successful.context.LightForgeAnalysisScheduler={acquire:async request=>{calls.push({kind:'acquire',request});return {diagnostics:()=>({schemaVersion:1,resourceClass:'analysis-heavy',capacity:1,crossContextMode:'single-context',waitMs:0,admissionTicket:1}),release:async()=>{calls.push({kind:'release'});return true;}};}};
 const result=await successful.analyze('/song.wav',{analysisIdentity:key});assert.equal(calls[0].request.key.length,64);assert.equal(calls[0].request.signal,undefined);assert.deepEqual({...result.engine.scheduler},{schemaVersion:1,resourceClass:'analysis-heavy',capacity:1,crossContextMode:'single-context',waitMs:0,admissionTicket:1});assert.equal(calls.filter(call=>call.kind==='release').length,1);
 const failing=analyzerHarness({behavior(worker,message){if(message.stage==='rhythm')worker.emit({type:'error',message:'scheduled model failure'});}}),failureCalls=[];failing.context.LightForgeAnalysisScheduler={acquire:async()=>({diagnostics:()=>({schemaVersion:1,resourceClass:'analysis-heavy',capacity:1,crossContextMode:'web-locks',waitMs:3,admissionTicket:2}),release:async()=>{failureCalls.push('released');return true;}})};
 await assert.rejects(failing.analyze('/song.wav',{analysisIdentity:key}),/scheduled model failure/);assert.deepEqual(failureCalls,['released']);
 const fallback=analyzerHarness(),logs=[];fallback.context.LightForgeDiagnostics={log:(...entry)=>logs.push(entry),progress:()=>{}};fallback.context.LightForgeAnalysisScheduler={acquire:async()=>{throw Error('optional lock unavailable');}};
 const recovered=await fallback.analyze('/song.wav',{analysisIdentity:key});assert.equal(recovered.engine.scheduler,undefined);assert.deepEqual(fallback.stageStarts,['rhythm','separation','voice','bass']);assert.ok(logs.some(entry=>entry[1]==='analysis-scheduler'));
});
