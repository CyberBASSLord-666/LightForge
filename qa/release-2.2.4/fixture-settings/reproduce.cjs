'use strict';
// Production app + production composition worker; only DOM/media/native IO is hosted.
// Run from any directory: node qa/release-2.2.4/fixture-settings/reproduce.cjs
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {JSDOM}=require('jsdom');
const root=path.resolve(__dirname,'../../..');
const runWorker=require(path.join(root,'tests/worker-harness.cjs'));
const engine=path.join(root,'web/engine');
const overrides={analysisQuality:'precision',dance:'off',style:'festival',stepMs:20,seed:2025};
const music={duration:2,bpm:120,beats:[0,.5,1,1.5],waveform:[.4],beatConfidence:.9,sections:[{start:0,end:2,energy:.7}],analysisVersion:6};
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const canonical=value=>JSON.stringify(value,(_,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.keys(item).sort().map(key=>[key,item[key]])):item);
const inputDigest=(m,s)=>sha(canonical({music:m,settings:s}));
const stateKeys=['loadingProject','composing','backgroundApplying','backgroundSyncPending','saveBlocked'];
const flags=app=>Object.fromEntries(stateKeys.map(key=>[key,app.state[key]]));
const expectedError='The saved show does not match its music and edits. Create again to rebuild it.';
async function waitFor(predicate){
 for(let i=0;i<200;i++){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,5));}
 throw Error('Timed out waiting for app state.');
}

async function reproduce(completeSettings){
 const dom=new JSDOM(fs.readFileSync(path.join(root,'web/index.html'),'utf8'),{url:'https://appassets.androidplatform.net/',runScripts:'outside-only'});
 const w=dom.window,polls=[],workerErrors=[];
 let bootstrap={projects:[],version:'2.2.4'},saved,fetches=0,restores=0,writes=0;
 let releaseFetch;const fetchGate=new Promise(resolve=>releaseFetch=resolve);
 const project={id:'fixture-settings-project',name:'Fixture settings',duration:music.duration,projectUrl:'/project/fixture-settings-project/project.json',audioUrl:'/project/fixture-settings-project/audio.wav'};
 const job={id:'fixture-settings-completed',projectId:project.id,state:'completed',progress:1};
 Object.defineProperty(w.document,'hidden',{value:false,configurable:true});
 w.scrollTo=()=>{};w.requestAnimationFrame=()=>1;w.cancelAnimationFrame=()=>{};
 w.matchMedia=()=>({matches:true,addEventListener(){}});
 // Keep the actual app's poll callback, but invoke it deterministically below.
 w.setInterval=(callback,delay)=>{if(delay===2000)polls.push(callback);return polls.length+1;};w.clearInterval=()=>{};
 w.HTMLMediaElement.prototype.pause=function(){};w.HTMLMediaElement.prototype.load=function(){};
 w.VehiclePreview=class{render(){}setPaused(){}setCamera(){}setStage(){}setQuality(){}resize(){}};
 w.LightForgeVersion=require(path.join(root,'web/version.js'));
 w.ShowEngine=require(path.join(engine,'show-engine.js'));
 w.VehicleProfile=require(path.join(engine,'vehicle-profile.js'));
 w.MusicCues=require(path.join(engine,'music-cues.js'));
 w.Android={pickAudio(){},getBootstrap:()=>JSON.stringify(bootstrap),saveProject(){writes++;return true;},startAnalysis(){throw Error('Reconnection must not restart analysis.');},getAnalysisStatus:()=>JSON.stringify(job)};
 w.fetch=async()=>{
  fetches++;
  // Hold only the negative case's second IO, exposing its real retry flags.
  if(!completeSettings&&fetches===2)await fetchGate;
  return{ok:true,json:async()=>structuredClone(saved)};
 };
 w.ShowCompiler={restore:async(compiled,m,s)=>{
  restores++;
  try{return await runWorker(engine,{action:'restore',compiled,music:m,settings:s});}
  catch(error){workerErrors.push(error.message);throw error;}
 }};
 try{
  w.eval(fs.readFileSync(path.join(root,'web/app.js'),'utf8'));
  const app=w.LightForgeApp,initialSettings=structuredClone(app.state.settings);
  const settings=completeSettings?{...initialSettings,...overrides}:{...overrides};
  const generated=await runWorker(engine,{action:'generate',music,settings});
  assert.equal(generated.compiled.engineVersion,'2.2.4');
  assert.equal(generated.compiled.inputDigest,inputDigest(music,settings));
  // The sparse file is internally valid: unmodified inputs restore successfully.
  const direct=await runWorker(engine,{action:'restore',compiled:generated.compiled,music,settings});
  assert.equal(sha(direct.show.frames),generated.compiled.sha256);
  saved={version:1,projectId:project.id,settings,music,compiled:generated.compiled,needAnalysis:false};
  bootstrap={projects:[project],lastProjectId:project.id,version:'2.2.4',backgroundJob:job};
  await app.readBootstrap();
  const afterFirstRestore=flags(app),effectiveSettings=structuredClone(app.state.settings);
  const outcome={settings,settings_key_count:Object.keys(settings).length,effective_settings:effectiveSettings,effective_settings_key_count:Object.keys(effectiveSettings).length,
   engine_version:generated.compiled.engineVersion,generated_input_digest:generated.compiled.inputDigest,effective_input_digest:inputDigest(music,effectiveSettings),generated_frame_sha256:generated.compiled.sha256,
   original_input_restore_frame_sha256:sha(direct.show.frames),after_first_restore:afterFirstRestore,first_restore_fetches:fetches,first_restore_worker_calls:restores};
  assert.equal(polls.length,1);
  if(completeSettings){
   assert.equal(workerErrors.length,0);
   assert.ok(app.state.show.validation.valid);
   assert.equal(sha(app.state.show.frames),generated.compiled.sha256);
   assert.equal(app.state.compiled.sha256,generated.compiled.sha256);
   assert.equal(w.localStorage.getItem('lightforge-background-ack'),job.id);
   for(const key of stateKeys)assert.equal(app.state[key],false,key+' remained set');
   await polls[0]();
   assert.equal(fetches,1);assert.equal(restores,1);
   Object.assign(outcome,{passed:true,restored_frame_sha256:sha(app.state.show.frames),input_digest_preserved:true,frame_hash_preserved:true,acknowledged:true,fetches_after_poll:fetches,worker_calls_after_poll:restores});
  }else{
   assert.deepEqual(workerErrors,[expectedError]);
   assert.equal(app.state.show,null);
   assert.equal(app.state.backgroundSeen,null);
   assert.equal(w.localStorage.getItem('lightforge-background-ack'),null);
   assert.deepEqual(afterFirstRestore,{loadingProject:false,composing:false,backgroundApplying:false,backgroundSyncPending:true,saveBlocked:true});
   assert.notEqual(outcome.generated_input_digest,outcome.effective_input_digest);
   const pendingPoll=polls[0]();await waitFor(()=>fetches===2);
   const retryFlags=flags(app);
   assert.deepEqual(retryFlags,{loadingProject:true,composing:false,backgroundApplying:true,backgroundSyncPending:true,saveBlocked:false});
   assert.equal(writes,0,'A failed restore must not overwrite saved project data.');
   Object.assign(outcome,{passed:true,expected_rejection:expectedError,background_seen_after_rejection:null,retry_flags:retryFlags,fetches_during_retry:fetches,saved_project_writes_during_retry:writes,acknowledged:false});
   releaseFetch();await pendingPoll;
   assert.deepEqual(workerErrors,[expectedError,expectedError]);
  }
  outcome.observed_worker_errors=workerErrors;
  return outcome;
 }finally{releaseFetch();w.close();}
}

(async()=>{
 const oldFiveFields=await reproduce(false),completeUiSettings=await reproduce(true);
 const sources=['qa/release-2.2.4/fixture-settings/reproduce.cjs','tests/worker-harness.cjs','tests/android/BackgroundInstrumentation.java','web/index.html','web/app.js','web/background/runner.js','web/version.js','web/engine/worker.js','web/engine/vehicle-profile.js','web/engine/movement-planner.js','web/engine/light-planner.js','web/engine/music-cues.js','web/engine/sync-review.js','web/engine/show-engine.js','package-lock.json'];
 const receipt={schema:1,passed:true,created_at:new Date().toISOString(),runtime:{node:process.version,jsdom:require('jsdom/package.json').version},
  scope:'Actual production app settings merge, composition worker generation/restore, and background completion/poll state. DOM, media, GPU preview, and native IO are hosted; no audio inference or Android performance claim.',
  command:'node qa/release-2.2.4/fixture-settings/reproduce.cjs',
  fixture:{music,overrides,origin:'Same five settings choices as Android BackgroundInstrumentation; complete case reads defaults from initialized LightForgeApp.state.settings.'},
  source_sha256:Object.fromEntries(sources.map(file=>[file,sha(fs.readFileSync(path.join(root,file)))])),
  old_five_fields:oldFiveFields,complete_ui_settings:completeUiSettings};
 fs.writeFileSync(path.join(__dirname,'verification.json'),JSON.stringify(receipt,null,2)+'\n');
 console.log(JSON.stringify({passed:receipt.passed,old_settings_keys:oldFiveFields.settings_key_count,effective_settings_keys:oldFiveFields.effective_settings_key_count,expected_error:oldFiveFields.expected_rejection,retry_flags:oldFiveFields.retry_flags,complete_settings_keys:completeUiSettings.settings_key_count,positive_frame_sha256:completeUiSettings.restored_frame_sha256,positive_fetches_after_poll:completeUiSettings.fetches_after_poll},null,2));
})().catch(error=>{console.error(error);process.exitCode=1;});
