'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {JSDOM}=require('jsdom'),runWorker=require('./worker-harness.cjs'),root=path.resolve(__dirname,'..');
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
