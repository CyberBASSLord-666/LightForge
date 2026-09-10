'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {JSDOM}=require('jsdom'),runWorker=require('./worker-harness.cjs'),root=path.resolve(__dirname,'..'),{webcrypto}=require('node:crypto');
const music={duration:2,bpm:120,beats:[0,.5,1,1.5],waveform:[.4],beatConfidence:.9,sections:[{start:0,end:2,energy:.7}],analysisVersion:6};
const waitFor=async fn=>{for(let i=0;i<200;i++){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw Error('Timed out');};
test('background runner checkpoints analysis and commits an actual compiled show without a studio document',async()=>{
 const progressEvents=[],events=[],request={analysisIdentity:'a'.repeat(64),version:1,projectId:'show-test',name:'Background',duration:2,settings:{dance:'off'},music:null,needAnalysis:true};let done=false,saved;
 const context={URL,AbortController,DOMException,console,location:{href:'https://appassets.androidplatform.net/background/runner.html?job=job-one'},navigator:{},
  fetch:async()=>({ok:true,json:async()=>request}),LightForgeVersion:require('../web/version.js'),VehicleProfile:require('../web/engine/vehicle-profile.js'),
  MusicAnalyzer:{analyze:async(url,options,progress)=>{assert.equal(options.projectId,'show-test');assert.equal(options.analysisIdentity,request.analysisIdentity);assert.match(url,/\/project\/show-test\/audio.wav$/);progress({progress:.5,stage:'separation',detail:'Analyzing',passageIndex:3,passageCount:8,passagesCompleted:2,restoredPassages:1,checkpointSaved:true});events.push('analysis');return structuredClone(music);}},
  ShowCompiler:{generate:(m,s)=>runWorker(path.join(root,'web/engine'),{action:'generate',music:m,settings:s})},
  BackgroundJob:{progress(){throw Error('Detailed progress bridge was bypassed');},progressInfo(id,value,detail,json){progressEvents.push({id,value,detail,info:JSON.parse(json)});},checkpoint(id,body){assert.equal(id,'job-one');assert.equal(JSON.parse(body).analysisVersion,6);events.push('checkpoint');return true;},complete(id,body){saved=JSON.parse(body);events.push('complete');done=true;return true;},failed(id,message){throw Error(message);}}
 };context.window=context;vm.runInNewContext(fs.readFileSync(path.join(root,'web/background/runner.js'),'utf8'),context);
 await waitFor(()=>done);assert.equal(progressEvents[0].value,.48);assert.equal(progressEvents[0].info.passageIndex,3);assert.equal(progressEvents[0].info.restoredPassages,1);assert.equal(progressEvents[0].info.checkpointSaved,true);assert.deepEqual(events,['analysis','checkpoint','complete']);assert.equal(saved.needAnalysis,false);assert.equal(saved.projectId,'show-test');assert.match(saved.compiled.sha256,/^[a-f0-9]{64}$/);
 const restored=await runWorker(path.join(root,'web/engine'),{action:'restore',compiled:saved.compiled,music:saved.music,settings:saved.settings});assert.ok(restored.show.validation.valid);
});
test('background runner cancellation never submits a completed project',async()=>{
 let entered=false,failed,completed=false;
 const context={URL,AbortController,DOMException,location:{href:'https://appassets.androidplatform.net/background/runner.html?job=job-cancel'},navigator:{},
  fetch:async()=>({ok:true,json:async()=>({projectId:'show-test',settings:{},needAnalysis:true})}),
  MusicAnalyzer:{analyze:(url,options,p,signal)=>new Promise((resolve,reject)=>{entered=true;signal.addEventListener('abort',()=>reject(new DOMException('Cancelled','AbortError')));})},
  BackgroundJob:{progress(){},checkpoint(){throw Error('Unexpected checkpoint');},complete(){completed=true;},failed(id,message,cancelled){failed={id,cancelled};}}
 };context.window=context;vm.runInNewContext(fs.readFileSync(path.join(root,'web/background/runner.js'),'utf8'),context);
 await waitFor(()=>entered);context.BackgroundAnalysis.cancel();await waitFor(()=>failed);assert.deepEqual(failed,{id:'job-cancel',cancelled:true});assert.equal(completed,false);
});
test('native studio delegates work, blocks stale saves, reconnects, and loads the background result',async()=>{
 const dom=new JSDOM(fs.readFileSync(path.join(root,'web/index.html'),'utf8'),{url:'https://appassets.androidplatform.net/',runScripts:'outside-only'}),w=dom.window,d=w.document;
 let saved={version:1,projectId:'show-test',name:'Background',settings:{dance:'off'},music:null,needAnalysis:true},job=null,writes=0,starts=0,cancels=0;
 const project={id:'show-test',name:'Background',duration:2,projectUrl:'/project/show-test/project.json',audioUrl:'/project/show-test/audio.wav'};
 w.scrollTo=()=>{};w.requestAnimationFrame=()=>0;w.cancelAnimationFrame=()=>{};w.matchMedia=()=>({matches:true,addEventListener(){}});
 w.HTMLMediaElement.prototype.pause=function(){};w.HTMLMediaElement.prototype.load=function(){};
 w.VehiclePreview=class{render(){}setCamera(){}setStage(){}setQuality(){}resize(){}};
 w.LightForgeVersion=require('../web/version.js');w.ShowEngine=require('../web/engine/show-engine.js');w.VehicleProfile=require('../web/engine/vehicle-profile.js');w.MusicCues=require('../web/engine/music-cues.js');
 w.ShowCompiler={generate:(m,s)=>runWorker(path.join(root,'web/engine'),{action:'generate',music:m,settings:s}),restore:(compiled,m,s)=>runWorker(path.join(root,'web/engine'),{action:'restore',compiled,music:m,settings:s})};
 w.MusicAnalyzer={analyze(){throw Error('Studio must not own native analysis');}};
 w.Android={pickAudio(){},getBootstrap:()=>JSON.stringify({projects:[project],version:'2.2.0',backgroundJob:job}),saveProject:(id,body)=>{writes++;saved=JSON.parse(body);return true;},getAnalysisStatus:()=>JSON.stringify(job),
  startAnalysis:id=>{starts++;job={id:'native-job',projectId:id,state:'running',progress:.2,stage:'Separating',analysisStage:'separation',createdAt:Date.now()-65000,updatedAt:Date.now(),passageIndex:3,passageCount:8,passagesCompleted:2,restoredPassages:1,resumeAvailable:true};return JSON.stringify(job);},cancelAnalysis:()=>{cancels++;}};
 w.fetch=async()=>({ok:true,json:async()=>structuredClone(saved)});
 try{
  w.eval(fs.readFileSync(path.join(root,'web/app.js'),'utf8'));const app=w.LightForgeApp;await app.selectProject(project);await app.generate();
  assert.equal(starts,1);assert.equal(app.state.busy,true);assert.equal(d.getElementById('backgroundContinue').hidden,false);
  assert.match(d.getElementById('progressElapsed').textContent,/Elapsed 1m/);
  assert.equal(d.getElementById('progressPassage').textContent,'Passage 3 of 8');
  assert.match(d.getElementById('progressSaved').textContent,/2 passages completed.*1 reused/);
  assert.equal(d.querySelector('[role="progressbar"]').getAttribute('aria-valuenow'),'20');
  job={...job,progressAt:Date.now()-96000};w.onNativeEvent('analysisJob',job);
  assert.equal(d.getElementById('progressActivity').hidden,false);assert.match(d.getElementById('progressActivity').textContent,/has not reported progress/);
  job={...job,progressAt:Date.now(),progress:.3};w.onNativeEvent('analysisJob',job);
  assert.equal(d.getElementById('progressActivity').hidden,true);
  const before=writes;await app.saveProject();w.pausePreview();assert.equal(writes,before,'Background UI overwrote frozen inputs');
  d.getElementById('cancelWork').click();assert.equal(cancels,1);assert.equal(app.state.busy,true,'Cancellation was not acknowledged yet');
  const settings=structuredClone(app.state.settings),result=await w.ShowCompiler.generate(music,settings);saved={...saved,settings,music,needAnalysis:false,compiled:result.compiled};
  job={...job,state:'completed',progress:1};w.onNativeEvent('analysisJob',job);await waitFor(()=>app.state.show&&!app.state.backgroundApplying);
  assert.equal(app.state.busy,false);assert.equal(app.state.music.analysisVersion,6);assert.equal(app.state.compiled.sha256,result.compiled.sha256);
  assert.equal(w.localStorage.getItem('lightforge-background-ack'),'native-job');
  job={...job,id:'later-interrupted-job',state:'interrupted',hasCheckpoint:true,stage:'Android stopped analysis.'};w.onNativeEvent('analysisJob',job);
  assert.equal(d.getElementById('backgroundRecovery').hidden,false);
  assert.match(d.getElementById('backgroundRecoveryMessage').textContent,/resume skips straight to choreography/);
  assert.equal(d.getElementById('backgroundRetry').textContent,'Resume analysis');
 }finally{dom.window.close();}
});

async function completedReconnect({acknowledged=false,hold=false,restoreError=null}={}){
 const dom=new JSDOM(fs.readFileSync(path.join(root,'web/index.html'),'utf8'),{url:'https://appassets.androidplatform.net/',runScripts:'outside-only'}),w=dom.window;
 const polls=[];let restores=0,fetches=0,saved,bootstrap={projects:[],version:'2.2.4'},restoreOptions=[];
 const completed={id:'completed-project',name:'Completed',duration:2,projectUrl:'/project/completed/project.json',audioUrl:'/project/completed/audio.wav'};
 const lastSelected={...completed,id:'last-selected-project',name:'Last selected',projectUrl:'/project/last/project.json'};
 const job={id:'completed-job',projectId:completed.id,state:'completed',progress:1};
 let enteredResolve,release;const entered=new Promise(r=>enteredResolve=r),gate=new Promise(r=>release=r);
 Object.defineProperty(w.document,'hidden',{value:false,configurable:true});
 w.scrollTo=()=>{};w.requestAnimationFrame=()=>1;w.cancelAnimationFrame=()=>{};w.matchMedia=()=>({matches:true,addEventListener(){}});
 w.setInterval=(callback,delay)=>{if(delay===2000)polls.push(callback);return polls.length+1;};w.clearInterval=()=>{};
 w.HTMLMediaElement.prototype.pause=function(){};w.HTMLMediaElement.prototype.load=function(){};
 w.VehiclePreview=class{render(){}setPaused(){}setCamera(){}setStage(){}setQuality(){}resize(){}};
 w.LightForgeVersion=require('../web/version.js');w.ShowEngine=require('../web/engine/show-engine.js');w.VehicleProfile=require('../web/engine/vehicle-profile.js');w.MusicCues=require('../web/engine/music-cues.js');
 w.Android={pickAudio(){},getBootstrap:()=>JSON.stringify(bootstrap),saveProject:()=>true,startAnalysis(){throw Error('Reconnection must not restart analysis');},getAnalysisStatus:()=>JSON.stringify(job)};
 w.fetch=async()=>{fetches++;return{ok:true,json:async()=>structuredClone(saved)};};
 w.ShowCompiler={restore:async(compiled,m,s,_progress,signal,options)=>{
  restoreOptions.push(options);restores++;enteredResolve();
  if(restoreError)throw restoreError;
  if(hold)await new Promise((resolve,reject)=>{
   const abort=()=>reject(new w.DOMException('Restore superseded','AbortError'));
   if(signal.aborted){abort();return;}signal.addEventListener('abort',abort,{once:true});
   gate.then(()=>{signal.removeEventListener('abort',abort);resolve();});
  });
  if(signal.aborted)throw new w.DOMException('Restore superseded','AbortError');
  return runWorker(path.join(root,'web/engine'),{action:'restore',compiled,music:m,settings:s});
 }};
 try{
  w.eval(fs.readFileSync(path.join(root,'web/app.js'),'utf8'));const app=w.LightForgeApp,settings=structuredClone(app.state.settings);
  const result=await runWorker(path.join(root,'web/engine'),{action:'generate',music,settings});saved={settings,music,compiled:result.compiled,needAnalysis:false};
  if(acknowledged)w.localStorage.setItem('lightforge-background-ack',job.id);
  bootstrap={projects:[completed,lastSelected],lastProjectId:lastSelected.id,version:'2.2.4',backgroundJob:job};
  return{w,app,job,entered,release,polls,completed,lastSelected,get restores(){return restores;},get fetches(){return fetches;},get restoreOptions(){return restoreOptions;},close:()=>{release();w.close();}};
 }catch(error){release();w.close();throw error;}
}

test('completed bootstrap restores once across poll/native races and preserves later Guide navigation',async()=>{
 const t=await completedReconnect({hold:true});
 try{
  const bootstrap=t.app.readBootstrap();await t.entered;
  assert.equal(t.app.state.backgroundApplying,true,'The completion handler must own the restore before waiting for its worker');
  t.app.nav('guide');
  for(let i=0;i<3;i++)t.w.onNativeEvent('analysisJob',t.job);
  assert.equal(t.polls.length,1);for(const poll of t.polls)await poll();
  assert.equal(t.restores,1,'Repeated completion delivery must not start a second verification worker');
  assert.equal(t.fetches,1);
  assert.equal(t.app.state.view,'guide');
  t.release();await bootstrap;
  assert.equal(t.restores,1);assert.equal(t.fetches,1);
  assert.equal(t.app.state.project.id,t.completed.id);assert.ok(t.app.state.show.validation.valid);
  assert.equal(t.w.localStorage.getItem('lightforge-background-ack'),t.job.id);
  for(const key of ['loadingProject','composing','backgroundApplying','backgroundSyncPending'])assert.equal(t.app.state[key],false,key+' remained latched');
  assert.equal(t.app.state.view,'guide','Completed restoration must not override navigation made while it was pending');
 }finally{t.close();}
});

test('acknowledged completion restores the last selected project once',async()=>{
 const t=await completedReconnect({acknowledged:true});
 try{
  await t.app.readBootstrap();
  assert.equal(t.restores,1);assert.equal(t.fetches,1);
  assert.equal(t.app.state.project.id,t.lastSelected.id,'An old acknowledged job must not replace the last selected project');
  assert.ok(t.app.state.show.validation.valid);assert.equal(t.w.localStorage.getItem('lightforge-background-ack'),t.job.id);
  assert.equal(t.app.state.loadingProject,false);assert.equal(t.app.state.composing,false);assert.equal(t.app.state.backgroundSyncPending,false);
  t.app.nav('guide');await t.app.selectProject(t.completed,true);
  assert.equal(t.app.state.view,'studio','Explicit project selection must still open the studio by default');
 }finally{t.close();}
});

test('a completed job arriving while Guide is open restores without taking over navigation',async()=>{
 const t=await completedReconnect({hold:true});
 try{
  t.app.nav('guide');t.w.onNativeEvent('analysisJob',t.job);await t.entered;
  assert.equal(t.app.state.backgroundApplying,true);
  assert.equal(t.app.state.view,'guide','Completion delivery must not navigate before its asynchronous restore');
  t.release();await waitFor(()=>!t.app.state.backgroundApplying&&!t.app.state.backgroundSyncPending);
  assert.equal(t.restores,1);assert.equal(t.fetches,1);assert.ok(t.app.state.show.validation.valid);
  assert.equal(t.w.localStorage.getItem('lightforge-background-ack'),t.job.id);
  for(const key of ['loadingProject','composing','backgroundApplying','backgroundSyncPending'])assert.equal(t.app.state[key],false,key+' remained latched');
  assert.equal(t.app.state.view,'guide','Completion delivery must not navigate after its asynchronous restore');
 }finally{t.close();}
});

function workerClientHarness(){
 const workers=[],timers=[];let timerId=0;
 class Worker{
  constructor(url){this.url=url;workers.push(this);}
  postMessage(payload){this.payload=structuredClone(payload);}
  terminate(){this.terminated=true;}
  emit(data){this.onmessage?.({data});}
 }
 const context={URL,Worker,DOMException,console,document:{currentScript:{src:'https://appassets.androidplatform.net/engine/client.js'}},LightForgeVersion:{name:'test'},
  setTimeout(callback,delay){const timer={id:++timerId,callback,delay,active:true};timers.push(timer);return timer;},
  clearTimeout(timer){if(timer)timer.active=false;}};
 context.window=context;vm.runInNewContext(fs.readFileSync(path.join(root,'web/engine/client.js'),'utf8'),context);
 const activeTimers=()=>timers.filter(timer=>timer.active);
 const fireStartup=()=>{const [timer]=activeTimers();assert.ok(timer,'Expected a startup timer');timer.active=false;timer.callback();};
 return {compiler:context.ShowCompiler,workers,activeTimers,fireStartup};
}
function workerStartupMessages(){
 const directory=path.join(root,'web/engine'),messages=[];
 const context=vm.createContext({console,crypto:webcrypto,TextEncoder,TextDecoder,Uint8Array,Float32Array,ArrayBuffer,DataView,Blob,Response,ReadableStream,CompressionStream,DecompressionStream,atob,btoa,performance,setTimeout,clearTimeout});
 context.self=context;context.postMessage=data=>messages.push(data);
 context.importScripts=(...files)=>{for(const file of files)vm.runInContext(fs.readFileSync(path.join(directory,file),'utf8'),context,{filename:file});};
 context.importScripts('worker.js');return messages;
}
test('completed reconnect opts only its restore into startup recovery',async()=>{
 const completed=await completedReconnect({hold:true});
 try{
  const bootstrap=completed.app.readBootstrap();await completed.entered;
  assert.deepEqual(completed.restoreOptions.map(options=>options?.retryStartup),[true]);
  completed.release();await bootstrap;
 }finally{completed.close();}
 const ordinary=await completedReconnect({acknowledged:true});
 try{
  await ordinary.app.readBootstrap();
  assert.deepEqual(ordinary.restoreOptions.map(options=>options?.retryStartup),[false]);
 }finally{ordinary.close();}
});
test('a completed restore startup failure clears transient state without acknowledging the saved job',async()=>{
 const failed=await completedReconnect({restoreError:Error('The saved arrangement verification worker did not become ready. Please reopen the project and try again.')});
 try{
  await failed.app.readBootstrap();
  assert.equal(failed.restores,1);assert.equal(failed.app.state.composing,false);assert.equal(failed.app.state.backgroundApplying,false);
  assert.equal(failed.app.state.backgroundSyncPending,true,'A failed validation must remain pending for a safe later retry');
  assert.equal(failed.app.state.saveBlocked,true);assert.equal(failed.w.localStorage.getItem('lightforge-background-ack'),null,'Only a verified restored show may be acknowledged');
 }finally{failed.close();}
});
test('restore worker sends a readiness handshake and the client retries only a missing startup response',async()=>{
 assert.equal(workerStartupMessages()[0]?.type,'ready');
 const first=workerClientHarness(),payload={compiled:{id:'saved'},music:{duration:2},settings:{dance:'off'}},progress=[];
 const restored=first.compiler.restore(payload.compiled,payload.music,payload.settings,value=>progress.push(value),undefined,{retryStartup:true});
 assert.equal(first.workers.length,1);assert.deepEqual(first.workers[0].payload,{action:'restore',...payload});
 assert.equal(first.activeTimers().length,1);assert.equal(first.activeTimers()[0].delay,7500);
 first.fireStartup();
 assert.equal(first.workers.length,2,'Exactly one fresh worker is created after the first missing handshake');
 const stale=first.workers[0];assert.equal(stale.terminated,true);assert.deepEqual(first.workers[1].payload,stale.payload);
 let settled=false;restored.then(()=>{settled=true;},()=>{settled=true;});stale.emit({type:'result',value:{show:{id:'stale'}}});await Promise.resolve();
 assert.equal(settled,false,'A terminated first worker must not settle its retry');
 assert.equal(first.activeTimers().length,1);
 first.workers[1].emit({type:'ready'});
 assert.equal(first.activeTimers().length,0,'A ready worker has no result or progress timeout');
 first.workers[1].emit({type:'progress',value:{progress:.04,detail:'Verifying'}});
 const result={show:{id:'verified'},compiled:{id:'saved'},header:new Uint8Array([1,2])};
 assert.equal(first.workers.length,2,'A ready worker may finish later without another recreation');
 first.workers[1].emit({type:'result',value:result});
 assert.equal(await restored,result);assert.deepEqual(progress,[{progress:.04,detail:'Verifying'}]);assert.equal(first.workers[1].terminated,true);
 const missed=workerClientHarness(),failed=missed.compiler.restore(payload.compiled,payload.music,payload.settings,undefined,undefined,{retryStartup:true});
 missed.fireStartup();assert.equal(missed.workers.length,2);missed.fireStartup();
 await assert.rejects(failed,/did not become ready/);assert.equal(missed.workers[1].terminated,true);assert.equal(missed.activeTimers().length,0);
 const aborted=workerClientHarness(),controller=new AbortController(),abandoned=aborted.compiler.restore(payload.compiled,payload.music,payload.settings,undefined,controller.signal,{retryStartup:true}),abandonedWorker=aborted.workers[0];
 controller.abort();await assert.rejects(abandoned,error=>error.name==='AbortError');assert.equal(abandonedWorker.terminated,true);assert.equal(aborted.activeTimers().length,0);
 abandonedWorker.emit({type:'ready'});assert.equal(aborted.workers.length,1,'Abort must not recreate a worker');
 const ordinary=workerClientHarness(),normal=ordinary.compiler.restore(payload.compiled,payload.music,payload.settings);
 assert.equal(ordinary.activeTimers().length,0,'Non-background restores retain their existing no-timeout behavior');
 ordinary.workers[0].emit({type:'result',value:result});assert.equal(await normal,result);
});
