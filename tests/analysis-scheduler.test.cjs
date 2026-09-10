'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'..','web','analysis','scheduler.js'),'utf8'),key=n=>n.toString(16).padStart(64,'0');
function load({locks}={}){
 const context=vm.createContext({AbortController,DOMException,performance,navigator:locks?{locks}:{},setTimeout,clearTimeout});context.self=context;
 vm.runInContext(source,context);return context.LightForgeAnalysisScheduler;
}
test('single-context admission is FIFO and reports bounded, privacy-safe diagnostics',async()=>{
 const scheduler=load(),first=await scheduler.acquire({key:key(1)}),secondPromise=scheduler.acquire({key:key(2)});
 assert.deepEqual({...scheduler.snapshot()},{schemaVersion:1,resourceClass:'analysis-heavy',capacity:1,active:1,queued:1,crossContextMode:'single-context'});
 let admitted=false;secondPromise.then(()=>{admitted=true;});await new Promise(resolve=>setTimeout(resolve,0));assert.equal(admitted,false);
 const firstInfo=first.diagnostics();assert.equal(firstInfo.crossContextMode,'single-context');assert.equal(firstInfo.resourceClass,'analysis-heavy');assert.ok(Number.isFinite(firstInfo.waitMs)&&firstInfo.waitMs>=0);assert.equal('key' in firstInfo,false);
 assert.equal(await first.release(),true);assert.equal(await first.release(),false);const second=await secondPromise;assert.equal(await second.release(),true);assert.equal(scheduler.snapshot().active,0);
});
test('a queued cancellation is removed without disturbing the active resumable job',async()=>{
 const scheduler=load(),first=await scheduler.acquire({key:key(3)}),controller=new AbortController(),waiting=scheduler.acquire({key:key(4),signal:controller.signal});
 controller.abort();await assert.rejects(waiting,error=>error?.name==='AbortError');assert.equal(scheduler.snapshot().active,1);assert.equal(scheduler.snapshot().queued,0);await first.release();
});
test('Web Locks holds the origin-wide admission until release and then grants the next job',async()=>{
 let held=false,queued=0;
 const locks={request(name,options,callback){assert.equal(name,'lightforge-analysis-heavy-v1');assert.equal(options.mode,'exclusive');
  return new Promise((resolve,reject)=>{
   const run=async()=>{if(options.signal?.aborted){reject(new DOMException('cancelled','AbortError'));return;}held=true;try{await callback();resolve();}catch(error){reject(error);}finally{held=false;const next=queue.shift();if(next)next();}};
   const queueStart=()=>{if(held){queued++;queue.push(run);}else run();};queueStart();
  });},};
 const queue=[],firstScheduler=load({locks}),secondScheduler=load({locks}),first=await firstScheduler.acquire({key:key(5)}),secondPromise=secondScheduler.acquire({key:key(6)});await new Promise(resolve=>setTimeout(resolve,0));assert.equal(queued,1);assert.equal(first.diagnostics().crossContextMode,'web-locks');
 await first.release();const second=await secondPromise;await second.release();assert.equal(held,false);
});
test('cancelling while another tab owns the Web Lock clears the local admission slot',async()=>{
 let held=false,queuedRun;
 const locks={request(name,options,callback){return new Promise((resolve,reject)=>{
  let settled=false;const run=async()=>{if(settled)return;if(options.signal?.aborted){settled=true;reject(new DOMException('cancelled','AbortError'));return;}settled=true;held=true;try{await callback();resolve();}catch(error){reject(error);}finally{held=false;}};
  if(held){queuedRun=run;options.signal?.addEventListener('abort',()=>{if(!settled){settled=true;reject(new DOMException('cancelled','AbortError'));}},{once:true});}else run();
 });}};
 const owner=load({locks}),waiting=load({locks}),first=await owner.acquire({key:key(7)}),controller=new AbortController(),second=waiting.acquire({key:key(8),signal:controller.signal});
 await new Promise(resolve=>setTimeout(resolve,0));assert.equal(waiting.snapshot().active,1);controller.abort();await assert.rejects(second,error=>error?.name==='AbortError');assert.equal(waiting.snapshot().active,0);await first.release();if(queuedRun)await queuedRun();
});
test('invalid identities fail closed before entering the scheduler',async()=>{
 const scheduler=load();await assert.rejects(scheduler.acquire({key:'not-a-checkpoint'}),/Invalid analysis scheduler identity/);assert.equal(scheduler.snapshot().active,0);
});

test('hostile navigator locks probes fall back to the local scheduler',async()=>{
 const navigator={};Object.defineProperty(navigator,'locks',{get(){throw Error('blocked locks probe');}});
 const context=vm.createContext({AbortController,DOMException,performance,navigator,setTimeout,clearTimeout});context.self=context;vm.runInContext(source,context);
 const scheduler=context.LightForgeAnalysisScheduler,lease=await scheduler.acquire({key:key(9)});
 assert.equal(scheduler.snapshot().crossContextMode,'single-context');assert.equal(lease.diagnostics().crossContextMode,'single-context');await lease.release();
});
