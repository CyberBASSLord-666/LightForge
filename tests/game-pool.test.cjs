'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const GAME=fs.readFileSync(path.join(__dirname,'../web/analysis/game.js'),'utf8');
const CHILD=fs.readFileSync(path.join(__dirname,'../web/analysis/game-worker.js'),'utf8');
const RATE=44100,MODEL='game-large-test';
const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};};
const plain=value=>JSON.parse(JSON.stringify(value));

function harness({threads=1,childMode='normal',localGate,records=new Map(),failWrite,onWrite,checkRead}={}){
 const stats={loads:[],releases:[],inferences:[],workers:[],reads:[],writes:[],options:[],events:[]};
 let gated=false;
 class Tensor{
  constructor(type,data,dims){Object.assign(this,{type,data,dims});}
  dispose(){this.disposed=true;}
 }
 function runtime(lane){
  const state={marker:0};
  return {env:{wasm:{numThreads:threads}},Tensor,InferenceSession:{async create(url,options){
   const name=path.basename(new URL(url).pathname,'.onnx');stats.loads.push({lane,name});stats.options.push(plain(options));
   return {async release(){stats.releases.push({lane,name});},async run(feeds){
    if(name==='encoder'){
     state.marker=feeds.waveform.data[0];stats.inferences.push({lane,name,marker:state.marker,samples:feeds.waveform.data.length});
     if(lane==='local'&&localGate&&!gated){gated=true;await localGate.promise;}
     const mask=new Tensor('bool',Uint8Array.of(1,1,1),[1,3]);mask.seconds=feeds.duration.data[0];mask.marker=state.marker;
     return {x_seg:new Tensor('float32',Float32Array.of(state.marker),[1,1,1]),x_est:new Tensor('float32',Float32Array.of(state.marker),[1,1,1]),maskT:mask};
    }
    if(name==='dur2bd')return {boundaries:feeds.maskT};
    if(name==='segmenter'){
     stats.inferences.push({lane,name,marker:feeds.x_seg.data[0],language:Number(feeds.language.data[0]),time:feeds.t.data[0],noise:Array.from(feeds.random_uniform.data)});
     return {boundaries:feeds.maskT};
    }
    if(name==='bd2dur'){
     const duration=feeds.maskT.seconds;
     return {durations:new Tensor('float32',Float32Array.of(.5,Math.max(.1,duration-1),.5),[1,3]),maskN:new Tensor('bool',Uint8Array.of(1,1,1),[1,3])};
    }
    if(name==='estimator')return {scores:new Tensor('float32',Float32Array.of(60,64+Math.floor(feeds.x_est.data[0]/(RATE*12))%2,60),[1,3]),presence:new Tensor('bool',Uint8Array.of(1,1,1),[1,3])};
    throw Error('Unknown model');
   }};
  }}};
 }
 function context(lane){
  const value=vm.createContext({URL,ArrayBuffer,Float32Array,BigInt64Array,Uint8Array,console,setTimeout,clearTimeout,ort:runtime(lane),fetch:async()=>({json:async()=>({id:MODEL})})});
  value.self=value;value.location={href:'https://app.test/analysis/game-worker.js'};return value;
 }
 class Worker{
  constructor(url){
   this.url=url;this.requests=[];this.terminated=false;this.context=context('child-'+stats.workers.length);stats.workers.push(this);
   const child=this.context;
   child.postMessage=value=>queueMicrotask(()=>{if(!this.terminated)this.onmessage?.({data:structuredClone(value)});});
   child.close=()=>this.terminate();
   child.importScripts=(...urls)=>{for(const url of urls)if(url==='game.js')vm.runInContext(GAME,child);else assert.equal(url,'vendor/ort.wasm.min.js');};
   vm.runInContext(CHILD,child);
  }
  postMessage(value,transfer=[]){
   const request=structuredClone(value,{transfer});this.requests.push(request);
   queueMicrotask(()=>{
    if(this.terminated)return;
    if(childMode==='hang')return;
    if(childMode==='fail'){this.onerror?.({preventDefault(){}});return;}
    if(childMode==='invalid'){this.onmessage?.({data:{type:'result',requestId:request.requestId,model:MODEL,steps:7,notes:[]}});return;}
    this.context.onmessage({data:request});
   });
  }
  terminate(){this.terminated=true;stats.events.push('terminate');}
 }
 const parent=context('local');parent.Worker=Worker;vm.runInContext(GAME,parent);
 const checkpoint={async read(key){return records.get(key)||null;},async write(key,value){
  if(failWrite===key)throw Error('Disk full');
  records.set(key,plain(value));stats.writes.push(key);onWrite?.(key,value);
 }};
 return {stats,records,checkpoint,async create(parallelism=2){return parent.LightForgeGAME.create({ort:parent.ort,baseUrl:'https://app.test/analysis/models/game/',checkpoint,parallelism});},
  async read(first,count){checkRead?.(first,count,records);stats.reads.push([first,count]);return new Float32Array(count).fill(first+1);}};
}
function traces(h){return h.stats.inferences.filter(x=>x.name==='segmenter').map(({lane,...rest})=>rest).sort((a,b)=>a.marker-b.marker||a.time-b.time);}
function entries(h){return Array.from(h.records).sort(([a],[b])=>a.localeCompare(b));}
async function baseline(total,language=0){const h=harness(),game=await h.create(1);try{return {h,result:plain(await game.process(h.read,total,{language}))};}finally{await game.release();}}

test('two lanes preserve source windows, global seeds, cache bytes and stitching when the child finishes first',async()=>{
 const total=RATE*37,reference=await baseline(total,3),gate=deferred(),childSaved=deferred();
 const h=harness({localGate:gate,onWrite:key=>{if(key==='game-3-1')childSaved.resolve();},checkRead:(first,count,records)=>{
  if(first>=RATE*22)assert.ok(records.has('game-3-0')&&records.has('game-3-1'),'Prefetched beyond the two-passage bound');
 }}),game=await h.create();
 const progress=[],pending=game.process(h.read,total,{language:3,onProgress:(p,info)=>progress.push([p,plain(info)])});
 await childSaved.promise;
 await new Promise(resolve=>setImmediate(resolve));
 assert.deepEqual(h.stats.writes,['game-3-1']);assert.equal(h.stats.reads.length,2);assert.equal(h.stats.workers.length,1);
 assert.equal(progress.at(-1)[1].passagesCompleted,1);assert.equal(progress.at(-1)[1].checkpointSaved,true);
 gate.resolve();const result=plain(await pending);await game.release();
 assert.deepEqual(result,reference.result);assert.deepEqual(entries(h),entries(reference.h));assert.deepEqual(h.stats.reads,reference.h.stats.reads);assert.deepEqual(traces(h),traces(reference.h));
 assert.ok(h.stats.workers.every(w=>w.terminated));assert.equal(progress.at(-1)[1].passagesCompleted,4);
 assert.ok(h.stats.options.every(o=>o.executionProviders[0]==='wasm'&&o.graphOptimizationLevel==='all'&&o.enableCpuMemArena===false&&o.enableMemPattern===false));
});

test('fully restored passages create neither a model session nor a child worker',async()=>{
 const total=RATE*37,reference=await baseline(total),h=harness({records:new Map(entries(reference.h))}),game=await h.create();
 const result=plain(await game.process(()=>{throw Error('Restored PCM was reread');},total));await game.release();
 assert.deepEqual(result,reference.result);assert.equal(h.stats.loads.length,0);assert.equal(h.stats.workers.length,0);assert.equal(h.stats.writes.length,0);
});

for(const mode of ['fail','invalid'])test('child '+mode+' terminates it and retries identical retained PCM serially',async()=>{
 const total=RATE*37,reference=await baseline(total),h=harness({childMode:mode}),game=await h.create(),progress=[];
 const result=plain(await game.process(h.read,total,{onProgress:(p,info)=>progress.push(plain(info))}));await game.release();
 assert.deepEqual(result,reference.result);assert.deepEqual(entries(h),entries(reference.h));assert.deepEqual(traces(h),traces(reference.h));
 assert.equal(h.stats.workers.length,1);assert.equal(h.stats.workers[0].terminated,true);assert.ok(progress.some(p=>p.workerFallback&&p.parallelism===1));
 assert.equal(h.stats.inferences.filter(x=>x.name==='encoder'&&x.lane==='local').length,4);
});

test('checkpoint failure propagates, retains other completed work, and does not recompute a successful child result',async()=>{
 const h=harness({failWrite:'game-0-1'}),game=await h.create();
 await assert.rejects(game.process(h.read,RATE*24),/Disk full/);await game.release();
 assert.equal(h.records.has('game-0-0'),true);assert.equal(h.records.has('game-0-1'),false);assert.ok(h.stats.workers.every(w=>w.terminated));
 assert.equal(h.stats.inferences.filter(x=>x.name==='encoder'&&x.lane==='local').length,1);
});

test('a progress callback interruption propagates instead of becoming a serial fallback',async()=>{
 const gate=deferred(),h=harness({localGate:gate}),game=await h.create();let interrupted=false,fallback=false;
 await assert.rejects(game.process(h.read,RATE*24,{onProgress:(progress,info)=>{
  fallback||=!!info.workerFallback;
  if(progress>0&&!interrupted){interrupted=true;gate.resolve();throw Error('Progress consumer stopped');}
 }}),/Progress consumer stopped/);
 await game.release();assert.equal(interrupted,true);assert.equal(fallback,false);assert.ok(h.stats.workers.every(w=>w.terminated));
 assert.equal(h.stats.inferences.filter(x=>x.name==='encoder'&&x.lane==='local').length,1);
});

test('release terminates a hanging child promptly and retires parent sessions after active inference stops',async()=>{
 const gate=deferred(),h=harness({childMode:'hang',localGate:gate}),game=await h.create(),pending=game.process(h.read,RATE*24);
 const rejection=assert.rejects(pending,e=>e.name==='AbortError');
 while(!h.stats.inferences.some(x=>x.name==='encoder'))await new Promise(resolve=>setImmediate(resolve));
 const released=game.release();assert.equal(game.release(),released,'Concurrent release calls did not share retirement');assert.equal(h.stats.workers[0].terminated,true);assert.equal(h.stats.releases.length,0,'Closed an executing model session');
 gate.resolve();await released;await rejection;
 assert.equal(h.stats.releases.length,5);assert.equal(h.stats.writes.length,0);await game.release();assert.equal(h.stats.releases.length,5);
});

test('each lane retires its model set after four inferences and retains every diffusion step',async()=>{
 const h=harness(),game=await h.create();await game.process(h.read,RATE*120);await game.release();
 assert.equal(h.stats.workers.length,2);assert.ok(h.stats.workers.every(w=>w.terminated));
 assert.equal(h.stats.loads.filter(x=>x.lane==='local').length,10);assert.equal(h.stats.releases.filter(x=>x.lane==='local').length,10);
 assert.deepEqual(h.stats.workers.map(w=>w.requests.length),[4,1]);assert.equal(h.stats.inferences.filter(x=>x.name==='segmenter').length,80);assert.equal(h.records.size,10);
});

test('parallelism is opt-in and stays serial when the parent already uses multiple WASM threads',async()=>{
 for(const [threads,parallelism] of [[1,1],[2,2],[4,2]]){
  const h=harness({threads}),game=await h.create(parallelism);await game.process(h.read,RATE*24);await game.release();assert.equal(h.stats.workers.length,0);
 }
});
