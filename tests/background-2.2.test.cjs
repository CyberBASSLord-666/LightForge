'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {JSDOM}=require('jsdom'),runWorker=require('./worker-harness.cjs'),root=path.resolve(__dirname,'..'),{webcrypto}=require('node:crypto');
const music={duration:2,bpm:120,beats:[0,.5,1,1.5],waveform:[.4],beatConfidence:.9,sections:[{start:0,end:2,energy:.7}],analysisVersion:6};
const waitFor=async fn=>{for(let i=0;i<200;i++){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw Error('Timed out');};
test('background runner loads the same analysis scheduler before MusicAnalyzer',()=>{
 const html=fs.readFileSync(path.join(root,'web/background/runner.html'),'utf8'),store=html.indexOf('../analysis/work-store.js'),scheduler=html.indexOf('../analysis/scheduler.js'),analyzer=html.indexOf('../analysis/analyzer.js');
 assert.ok(store>=0&&scheduler>store&&analyzer>scheduler,'Background runner must load checkpoint storage, scheduler, then analyzer in order.');
});
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
 w.VehiclePreview=class{constructor(){this.loaded=true;this.renderCount=0;}render(){this.renderCount++;}setCamera(){}setStage(){}setQuality(){}resize(){}};
 w.LightForgeVersion=require('../web/version.js');w.ShowEngine=require('../web/engine/show-engine.js');w.VehicleProfile=require('../web/engine/vehicle-profile.js');w.MusicCues=require('../web/engine/music-cues.js');
 w.ShowCompiler={generate:(m,s)=>runWorker(path.join(root,'web/engine'),{action:'generate',music:m,settings:s}),restore:async(compiled,m,s,_progress,_signal,options)=>{options?.onRestoreEvent?.({type:'restore-started',lease:options?.restoreLease});const result=await runWorker(path.join(root,'web/engine'),{action:'restore',compiled,music:m,settings:s});options?.onRestoreEvent?.({type:'restore-verified',lease:options?.restoreLease});return result;}};
 w.MusicAnalyzer={analyze(){throw Error('Studio must not own native analysis');}};
 w.Android={pickAudio(){},getBootstrap:()=>JSON.stringify({projects:[project],version:'2.2.0',backgroundJob:job}),saveProject:(id,body)=>{writes++;saved=JSON.parse(body);return true;},getAnalysisStatus:()=>JSON.stringify(job),
  startAnalysis:id=>{starts++;job={id:'native-job',projectId:id,state:'running',progress:.2,stage:'Separating',analysisStage:'separation',createdAt:Date.now()-65000,updatedAt:Date.now(),passageIndex:3,passageCount:8,passagesCompleted:2,restoredPassages:1,resumeAvailable:true};return JSON.stringify(job);},cancelAnalysis:()=>{cancels++;},beginCompletedRestore:()=>true,completedRestorePulse:()=>true,requestCompletedRestoreVisualCommit:()=>true,completedRestoreVisualCommitted:()=>true,completedRestoreTerminal:()=>true,completedRestoreAckCommitted:()=>true,completedRestoreFailed:()=>true};
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

async function completedReconnect({acknowledged=false,hold=false,restoreError=null,terminalRejected=false,beginRejected=false,pulseRejected=false,ackConfirmationRejected=false,ackWriteFailures=0}={}){
 const dom=new JSDOM(fs.readFileSync(path.join(root,'web/index.html'),'utf8'),{url:'https://appassets.androidplatform.net/',runScripts:'outside-only'}),w=dom.window;
 const polls=[],leaseCalls=[],nativeCapClears=[];let restores=0,fetches=0,saved,bootstrap={projects:[],version:'2.2.4'},restoreOptions=[],nativeTerminalToken=null;
 const completed={id:'completed-project',name:'Completed',duration:2,projectUrl:'/project/completed/project.json',audioUrl:'/project/completed/audio.wav'};
 const lastSelected={...completed,id:'last-selected-project',name:'Last selected',projectUrl:'/project/last/project.json'};
 const job={id:'completed-job',projectId:completed.id,state:'completed',progress:1};
 let enteredResolve,release,remainingAckWriteFailures=ackWriteFailures,ackConfirmationRejectedNow=ackConfirmationRejected;const entered=new Promise(r=>enteredResolve=r),gate=new Promise(r=>release=r);
 Object.defineProperty(w.document,'hidden',{value:false,configurable:true});
 w.scrollTo=()=>{};w.requestAnimationFrame=()=>1;w.cancelAnimationFrame=()=>{};w.matchMedia=()=>({matches:true,addEventListener(){}});
 w.setInterval=(callback,delay)=>{if(delay===2000)polls.push(callback);return polls.length+1;};w.clearInterval=()=>{};
 w.HTMLMediaElement.prototype.pause=function(){};w.HTMLMediaElement.prototype.load=function(){};
 const storageSetItem=w.Storage.prototype.setItem;
 w.Storage.prototype.setItem=function(key,value){
  if(this===w.localStorage&&key==='lightforge-background-ack'&&remainingAckWriteFailures>0){remainingAckWriteFailures--;throw new w.DOMException('Storage quota','QuotaExceededError');}
  return storageSetItem.call(this,key,value);
 };
 w.VehiclePreview=class{constructor(){this.loaded=true;this.renderCount=0;}render(){this.renderCount++;}setPaused(){}setCamera(){}setStage(){}setQuality(){}resize(){}};
 w.LightForgeVersion=require('../web/version.js');w.ShowEngine=require('../web/engine/show-engine.js');w.VehicleProfile=require('../web/engine/vehicle-profile.js');w.MusicCues=require('../web/engine/music-cues.js');
 w.Android={pickAudio(){},getBootstrap:()=>JSON.stringify(bootstrap),saveProject:()=>true,startAnalysis(){throw Error('Reconnection must not restart analysis');},getAnalysisStatus:()=>JSON.stringify(job),
  beginCompletedRestore:(...args)=>{leaseCalls.push({type:'begin',args});if(beginRejected)return false;if(nativeTerminalToken){if(nativeTerminalToken.jobId===args[0])return false;nativeTerminalToken=null;}return true;},completedRestorePulse:(...args)=>{leaseCalls.push({type:'pulse',args});return !pulseRejected;},requestCompletedRestoreVisualCommit:(...args)=>{leaseCalls.push({type:'visual-request',args});return true;},completedRestoreVisualCommitted:(...args)=>{leaseCalls.push({type:'visual-committed',args});return true;},completedRestoreTerminal:(...args)=>{leaseCalls.push({type:'terminal',args,ackAtCall:w.localStorage.getItem('lightforge-background-ack')});if(terminalRejected)return false;nativeTerminalToken={jobId:args[0],nonce:args[1]};return true;},completedRestoreAckCommitted:(...args)=>{leaseCalls.push({type:'ack-committed',args,ackAtCall:w.localStorage.getItem('lightforge-background-ack')});if(ackConfirmationRejectedNow||nativeTerminalToken?.jobId!==args[0]||nativeTerminalToken?.nonce!==args[1])return false;nativeCapClears.push(args[0]);nativeTerminalToken=null;return true;},completedRestoreFailed:(...args)=>{leaseCalls.push({type:'failed',args});return true;}};
 w.fetch=async()=>{fetches++;return{ok:true,json:async()=>structuredClone(saved)};};
 w.ShowCompiler={restore:async(compiled,m,s,_progress,signal,options)=>{
  restoreOptions.push(options);restores++;enteredResolve();
  options?.onRestoreEvent?.({type:'restore-started',lease:options?.restoreLease});
  if(restoreError)throw restoreError;
  if(hold)await new Promise((resolve,reject)=>{
   const abort=()=>reject(new w.DOMException('Restore superseded','AbortError'));
   if(signal.aborted){abort();return;}signal.addEventListener('abort',abort,{once:true});
   gate.then(()=>{signal.removeEventListener('abort',abort);resolve();});
  });
  if(signal.aborted)throw new w.DOMException('Restore superseded','AbortError');
  const result=await runWorker(path.join(root,'web/engine'),{action:'restore',compiled,music:m,settings:s});
  options?.onRestoreEvent?.({type:'restore-verified',lease:options?.restoreLease});return result;
 }};
 try{
  w.eval(fs.readFileSync(path.join(root,'web/app.js'),'utf8'));const app=w.LightForgeApp,settings=structuredClone(app.state.settings);
  const result=await runWorker(path.join(root,'web/engine'),{action:'generate',music,settings});saved={settings,music,compiled:result.compiled,needAnalysis:false};
  if(acknowledged)w.localStorage.setItem('lightforge-background-ack',job.id);
  bootstrap={projects:[completed,lastSelected],lastProjectId:lastSelected.id,version:'2.2.4',backgroundJob:job};
  return{w,app,job,entered,release,polls,completed,lastSelected,leaseCalls,nativeCapClears,setAckConfirmationRejected:value=>{ackConfirmationRejectedNow=!!value;},get restores(){return restores;},get fetches(){return fetches;},get restoreOptions(){return restoreOptions;},close:()=>{release();w.close();}};
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
 const workers=[];
 class Worker{
  constructor(url){this.url=url;workers.push(this);}
  postMessage(payload){this.payload=structuredClone(payload);}
  terminate(){this.terminated=true;}
  emit(data){this.onmessage?.({data});}
 }
 const context={URL,Worker,DOMException,console,document:{currentScript:{src:'https://appassets.androidplatform.net/engine/client.js'}},LightForgeVersion:{name:'test'}};
 context.window=context;vm.runInNewContext(fs.readFileSync(path.join(root,'web/engine/client.js'),'utf8'),context);
 return {compiler:context.ShowCompiler,workers};
}
test('completed reconnect opens a lease and commits terminal proof before its ACK',async()=>{
 const completed=await completedReconnect({hold:true});
 try{
  const bootstrap=completed.app.readBootstrap();await completed.entered;
  assert.equal(completed.restoreOptions.length,1);assert.equal(completed.restoreOptions[0].restoreLease.jobId,completed.job.id);
  assert.equal(typeof completed.restoreOptions[0].restoreLease.nonce,'string');assert.equal(typeof completed.restoreOptions[0].onRestoreEvent,'function');
  assert.equal(completed.leaseCalls[0]?.type,'begin');assert.equal(completed.leaseCalls[0]?.args[0],completed.job.id);
  completed.release();await bootstrap;
  const terminal=completed.leaseCalls.findIndex(call=>call.type==='terminal');assert.ok(terminal>0,'A completed restore must publish terminal proof');
  const firstRender=completed.leaseCalls.findIndex(call=>call.type==='pulse'&&call.args[2]==='preview-first-render');
  assert.ok(firstRender>=0&&firstRender<terminal,'Terminal proof follows adopted show and its first web render');
  const visualCommit=completed.leaseCalls.findIndex(call=>call.type==='pulse'&&call.args[2]==='preview-visual-commit');
  assert.ok(visualCommit>firstRender&&visualCommit<terminal,'Terminal proof follows the native visual/HW-frame lease phase');
  const visualRequest=completed.leaseCalls.findIndex(call=>call.type==='visual-request'),visualCommitted=completed.leaseCalls.findIndex(call=>call.type==='visual-committed');
  assert.ok(visualRequest>=0&&visualCommitted>=visualRequest&&visualCommitted<visualCommit,'Visual proof must be requested and identity-checked before its terminal phase');
  assert.deepEqual(completed.leaseCalls[visualRequest].args.slice(0,2),completed.leaseCalls[terminal].args.slice(0,2),'Visual bridge query must bind the same job and nonce as terminal');
  assert.equal(completed.leaseCalls[terminal].ackAtCall,null,'Browser ACK is absent while native terminal proof is delivered');
  assert.equal(completed.w.localStorage.getItem('lightforge-background-ack'),completed.job.id,'ACK follows terminal proof only');
  const ackCommitted=completed.leaseCalls.findIndex(call=>call.type==='ack-committed');
  assert.ok(ackCommitted>terminal,'The cap confirmation follows terminal proof and the browser ACK write');
  assert.equal(completed.leaseCalls[ackCommitted].ackAtCall,completed.job.id,'Native cap confirmation cannot precede the browser ACK write');
  assert.deepEqual(completed.leaseCalls[ackCommitted].args,completed.leaseCalls[terminal].args.slice(0,2),'Post-ACK cap confirmation must use the terminal job and nonce exactly');
}finally{completed.close();}
 const ordinary=await completedReconnect({acknowledged:true});
 try{await ordinary.app.readBootstrap();assert.equal(ordinary.restoreOptions.length,1);assert.equal(ordinary.restoreOptions[0],undefined);assert.equal(ordinary.leaseCalls.length,0,'Ordinary foreground restoration must not open a completed-job lease');}
 finally{ordinary.close();}
});
test('a completed restore failure clears transient state without acknowledging the saved job',async()=>{
 const failed=await completedReconnect({restoreError:Error('The saved arrangement verification worker stopped.')});
 try{
  await failed.app.readBootstrap();
  assert.equal(failed.restores,1);assert.equal(failed.app.state.composing,false);assert.equal(failed.app.state.backgroundApplying,false);
  assert.equal(failed.app.state.backgroundSyncPending,true,'A failed validation must remain pending for a safe later retry');
  assert.equal(failed.app.state.saveBlocked,true);assert.equal(failed.w.localStorage.getItem('lightforge-background-ack'),null,'Only a verified restored show may be acknowledged');
  assert.equal(failed.leaseCalls.some(call=>call.type==='terminal'),false);assert.equal(failed.leaseCalls.filter(call=>call.type==='failed').length,1);
 }finally{failed.close();}
});
test('a rejected native terminal proof leaves the completed job pending and unacknowledged',async()=>{
 const rejected=await completedReconnect({terminalRejected:true});
 try{
  await rejected.app.readBootstrap();
  assert.equal(rejected.leaseCalls.some(call=>call.type==='terminal'),true,'The app attempted native terminal proof');
  assert.equal(rejected.leaseCalls.some(call=>call.type==='failed'),true,'Rejected terminal is reported as a failed lease');
  assert.equal(rejected.w.localStorage.getItem('lightforge-background-ack'),null,'A rejected native terminal may not write browser ACK');
  assert.equal(rejected.app.state.backgroundSyncPending,true);assert.equal(rejected.app.state.backgroundApplying,false);
 }finally{rejected.close();}
});
test('a browser ACK write failure retries the same terminal lease without reopening native proof',async()=>{
 const retry=await completedReconnect({ackWriteFailures:1});
 try{
  await retry.app.readBootstrap();
  await waitFor(()=>retry.leaseCalls.some(call=>call.type==='terminal')&&!retry.app.state.backgroundApplying);
  assert.equal(retry.leaseCalls.filter(call=>call.type==='begin').length,1,'The first restore opened exactly one native lease');
  assert.equal(retry.leaseCalls.filter(call=>call.type==='terminal').length,1,'Storage failure happens only after terminal proof');
  assert.equal(retry.w.localStorage.getItem('lightforge-background-ack'),null,'A failed browser write must not invent an ACK');
  assert.equal(retry.app.state.backgroundSyncPending,true,'The completed job remains pending after a browser ACK write failure');
  assert.equal(retry.app.state.completedRestore?.terminal,true,'The exact native terminal lease is retained for retry');
  assert.equal(retry.leaseCalls.some(call=>call.type==='ack-committed'),false,'Native cap confirmation cannot run before the browser ACK exists');
  retry.w.onNativeEvent('analysisJob',retry.job);
  await waitFor(()=>retry.w.localStorage.getItem('lightforge-background-ack')===retry.job.id&&!retry.app.state.backgroundApplying);
  assert.equal(retry.leaseCalls.filter(call=>call.type==='begin').length,1,'Retry must not open a fresh lease while native holds the terminal token');
  assert.equal(retry.leaseCalls.filter(call=>call.type==='terminal').length,1,'Retry must not repeat terminal proof');
  const confirmations=retry.leaseCalls.filter(call=>call.type==='ack-committed');
  assert.equal(confirmations.length,1,'The retained terminal lease confirms exactly once after browser storage succeeds');
  assert.deepEqual(confirmations[0].args,retry.leaseCalls.find(call=>call.type==='terminal').args.slice(0,2),'Post-ACK confirmation retains the terminal job and nonce');
  assert.equal(retry.app.state.completedRestore,null,'Exact accepted post-ACK confirmation releases the retained JS lease');
  assert.equal(retry.app.state.backgroundSyncPending,false);
 }finally{retry.close();}
});
test('an unconfirmed ACK for one completed job does not wedge a later completed job',async()=>{
 const handoff=await completedReconnect({ackConfirmationRejected:true});
 try{
  await handoff.app.readBootstrap();
  await waitFor(()=>handoff.leaseCalls.some(call=>call.type==='terminal')&&!handoff.app.state.backgroundApplying);
  const firstTerminal=handoff.leaseCalls.find(call=>call.type==='terminal');
  assert.equal(handoff.w.localStorage.getItem('lightforge-background-ack'),handoff.job.id,'The browser ACK was written before the simulated native confirmation failure');
  assert.equal(handoff.app.state.completedRestore?.terminal,true,'The first job retains its terminal lease until exact confirmation');
  assert.equal(handoff.app.state.completedRestore?.ackConfirmed,false,'A rejected native confirmation must not be treated as accepted');
  handoff.setAckConfirmationRejected(false);
  const later={...handoff.job,id:'later-completed-job'};
  handoff.w.onNativeEvent('analysisJob',later);
  await waitFor(()=>handoff.leaseCalls.some(call=>call.type==='terminal'&&call.args[0]===later.id)&&!handoff.app.state.backgroundApplying);
  const begins=handoff.leaseCalls.filter(call=>call.type==='begin'),terminals=handoff.leaseCalls.filter(call=>call.type==='terminal');
  assert.equal(begins.length,2,'Later completed work must open a distinct native lease rather than reuse the old terminal nonce');
  assert.equal(begins[1].args[0],later.id);
  assert.equal(terminals.length,2);assert.notDeepEqual(terminals[1].args.slice(0,2),firstTerminal.args.slice(0,2),'Later completed work must not borrow the old terminal identity');
  assert.equal(handoff.w.localStorage.getItem('lightforge-background-ack'),later.id,'The later job owns the browser ACK after its own proof');
  assert.equal(handoff.app.state.completedRestore,null,'The later exact confirmation releases only its own JS lease');
  assert.deepEqual(handoff.nativeCapClears,[later.id],'Retiring A for B must leave A\'s persisted cap armed and clear only B\'s cap');
  assert.equal(handoff.w.Android.completedRestoreAckCommitted(...firstTerminal.args.slice(0,2)),false,'A stale post-ACK confirmation cannot release B\'s cap after B completed');
  assert.deepEqual(handoff.nativeCapClears,[later.id]);
 }finally{handoff.close();}
});
test('a rejected native begin or pulse leaves the completed job pending without a terminal ACK',async()=>{
 const beginRejected=await completedReconnect({beginRejected:true});
 try{
  await beginRejected.app.readBootstrap();
  assert.equal(beginRejected.restores,0,'Rejected native begin must prevent worker restoration');
  assert.equal(beginRejected.leaseCalls.some(call=>call.type==='terminal'),false);assert.equal(beginRejected.w.localStorage.getItem('lightforge-background-ack'),null);
  assert.equal(beginRejected.app.state.backgroundSyncPending,true);
 }finally{beginRejected.close();}
 const pulseRejected=await completedReconnect({pulseRejected:true});
 try{
  await pulseRejected.app.readBootstrap();
  assert.equal(pulseRejected.leaseCalls.some(call=>call.type==='terminal'),false,'Rejected native pulse cannot be masked by later terminal proof');
  assert.equal(pulseRejected.leaseCalls.some(call=>call.type==='failed'),true);assert.equal(pulseRejected.w.localStorage.getItem('lightforge-background-ack'),null);
  assert.equal(pulseRejected.app.state.backgroundSyncPending,true);
 }finally{pulseRejected.close();}
});
test('a selection that supersedes the completed job cannot borrow another render for its terminal ACK',async()=>{
 const superseded=await completedReconnect({hold:true});
 try{
  const bootstrap=superseded.app.readBootstrap();await superseded.entered;
  // The held harness intentionally pauses every restore.  Start the later
  // selection, wait until it owns its own restore, then release that shared
  // gate; awaiting selectProject before release would deadlock the test rather
  // than exercise the supersession path.
  const selection=superseded.app.selectProject(superseded.lastSelected);
  await waitFor(()=>superseded.app.state.project?.id===superseded.lastSelected.id&&superseded.restores===2);
  superseded.release();await selection;await bootstrap;
  assert.equal(superseded.app.state.project.id,superseded.lastSelected.id);
  assert.equal(superseded.leaseCalls.some(call=>call.type==='terminal'),false,'A different selected project must not terminally prove the completed job');
  assert.equal(superseded.w.localStorage.getItem('lightforge-background-ack'),null);
  assert.equal(superseded.app.state.backgroundSyncPending,true);
 }finally{superseded.close();}
});
test('restore client forwards only ordered matching lease events and has no page timeout authority',async()=>{
 const first=workerClientHarness(),payload={compiled:{id:'saved'},music:{duration:2},settings:{dance:'off'}},progress=[],events=[],lease={jobId:'completed-job',nonce:'nonce-one'};
  const restored=first.compiler.restore(payload.compiled,payload.music,payload.settings,value=>progress.push(value),undefined,{restoreLease:lease,onRestoreEvent:event=>events.push(event)});
  assert.equal(first.workers.length,1);assert.deepEqual(first.workers[0].payload,{action:'restore',...payload,restoreLease:lease});
  first.workers[0].emit({type:'ready'});assert.deepEqual(events,[],'Import readiness is not restore liveness');
  first.workers[0].emit({type:'restore-pulse',lease,phase:'expand-frames'});first.workers[0].emit({type:'restore-verified',lease});assert.deepEqual(events,[],'Out-of-order worker events cannot create a restore proof');
  first.workers[0].emit({type:'restore-started',lease:{jobId:lease.jobId,nonce:'wrong'}});assert.deepEqual(events,[],'A stale lease cannot extend this restore');
  first.workers[0].emit({type:'restore-started',lease});first.workers[0].emit({type:'restore-pulse',lease,phase:'expand-frames',completed:128,total:256});first.workers[0].emit({type:'restore-verified',lease,sha256:'a'.repeat(64)});
  first.workers[0].emit({type:'restore-pulse',lease,phase:'late'});
 first.workers[0].emit({type:'progress',value:{progress:.04,detail:'Verifying'}});const result={show:{id:'verified'},compiled:{id:'saved'},header:new Uint8Array([1,2])};first.workers[0].emit({type:'result',value:result});
 assert.equal(await restored,result);assert.deepEqual(events.map(event=>event.type),['restore-started','restore-pulse','restore-verified']);assert.deepEqual(progress,[{progress:.04,detail:'Verifying'}]);assert.equal(first.workers[0].terminated,true);
 const aborted=workerClientHarness(),controller=new AbortController(),abandoned=aborted.compiler.restore(payload.compiled,payload.music,payload.settings,undefined,controller.signal,{restoreLease:lease,onRestoreEvent:event=>events.push(event)}),abandonedWorker=aborted.workers[0];
  controller.abort();await assert.rejects(abandoned,error=>error.name==='AbortError');assert.equal(abandonedWorker.terminated,true);abandonedWorker.emit({type:'restore-started',lease});
  const readyOnly=workerClientHarness(),readyEvents=[],readyResult=readyOnly.compiler.restore(payload.compiled,payload.music,payload.settings,undefined,undefined,{restoreLease:lease,onRestoreEvent:event=>readyEvents.push(event)});
  readyOnly.workers[0].emit({type:'ready'});readyOnly.workers[0].emit({type:'result',value:result});await assert.rejects(readyResult,/without verified worker proof/);assert.deepEqual(readyEvents.map(event=>event.type),['restore-error'],'Ready-only worker import cannot stand in for restore terminal proof');
  const ordinary=workerClientHarness(),normal=ordinary.compiler.restore(payload.compiled,payload.music,payload.settings);assert.equal(ordinary.workers[0].payload.restoreLease,undefined,'Ordinary foreground restores retain no completed-job protocol');ordinary.workers[0].emit({type:'result',value:result});assert.equal(await normal,result);
});
test('actual restore emits ordered request-scoped pulses before its verified result',async()=>{
 const generated=await runWorker(path.join(root,'web/engine'),{action:'generate',music,settings:{dance:'off'}}),trace=[],lease={jobId:'completed-job',nonce:'trace-one'};
 const restored=await runWorker(path.join(root,'web/engine'),{action:'restore',compiled:generated.compiled,music,settings:{dance:'off'},restoreLease:lease},{onMessage:event=>trace.push(event)});
 assert.ok(restored.show.validation.valid);assert.equal(trace[0]?.type,'restore-started');const restoreTrace=trace.filter(event=>event.type.startsWith('restore-'));
 assert.equal(restoreTrace[0]?.type,'restore-started');assert.ok(restoreTrace.every(event=>event.lease?.jobId===lease.jobId&&event.lease?.nonce===lease.nonce));
 const phases=restoreTrace.filter(event=>event.type==='restore-pulse').map(event=>event.phase),required=['input-digest','metadata-digest','decode-base64','expand-frames','frame-digest','validate-show','prepare-preview'];
 let previous=-1;for(const phase of required){const index=phases.indexOf(phase);assert.ok(index>previous,phase+' pulse is ordered');previous=index;}
 assert.equal(restoreTrace.at(-1)?.type,'restore-verified');
});
