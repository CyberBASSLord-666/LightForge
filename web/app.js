/* LightForge mobile studio — offline UI, native Android storage and live exported-frame preview. */
(() => {
'use strict';
const $ = id => document.getElementById(id);
const diagnostics=window.LightForgeDiagnostics;
const native = () => window.Android && typeof window.Android.pickAudio === 'function';
const clone = x => JSON.parse(JSON.stringify(x));
// A completed background job is restored before the ordinary project fetch
// path is allowed to own the Studio.  Keep its durable payload transport
// bounded: a WebView request that never resolves must not leave the completed
// job, loading overlay and preview permanently latched together.
const COMPLETED_RESTORE_PROJECT_CHUNK_BYTES=48*1024,COMPLETED_RESTORE_PROJECT_MAX_BYTES=64*1024*1024,COMPLETED_RESTORE_PROJECT_READ_TIMEOUT_MS=12000;
const defaults = {style:'festival',intensity:.85,dance:'expressive',stepMs:20,sensitivity:.82,beatDivision:'auto',bpmOverride:null,offsetMs:0,palette:'aurora',enabled:{windows:true,mirrors:true,trunk:true,charge:true,interior:true},optionalFog:false,outerBeamRamping:false,outputEnabled:{},manualCues:[],sectionOverrides:{},seed:2025,analysisQuality:'precision',movementDensity:.7,downbeatAnchor:null,meterOverride:null,tempoScale:1,vocalFocus:.85,bassFocus:.9,vocalRegions:[],musicCues:[],vocalOffsetMs:0,bassOffsetMs:0};
const state = {audition:'mix',auditionAvailable:false,auditionLoading:false,project:null,music:null,show:null,settings:clone(defaults),projects:[],history:[],future:[],compiled:null,exportHeader:null,saveBlocked:false,composing:false,compileId:0,compileAbort:null,renderedSettingsKey:null,showMusic:null,pendingExport:null,busy:false,job:0,abort:null,view:'studio',editing:null,needAnalysis:false,previewMode:0,exportId:null,lastSave:0,acceptProgress:false,selection:0,loadingProject:false,pendingProjectAction:null,soloPreview:null,completedRestore:null,completedRestorePreviewDeferred:false};
const audio=$('audio');let auditionEpoch=0,availabilityEpoch=0,auditionAbort=null,auditionURL=null,auditionIntent=null,auditionSignature=null,analysisFallback=null,completedRestoreEpoch=0;let progressClock,toastTimer,saveTimer,regenTimer,lastDraw=0,lastSection=-1,frameRequest=0,dbPromise;
let previewPaused=document.hidden,nativePreviewPaused=false,pagePreviewPaused=false;
function auditionChanged(){document.dispatchEvent(new CustomEvent('lightforge:changed'));}
function mixAudioUrl(){return state.project?.previewUrl||state.project?.audioUrl||'';}
function stemSignature(meta){return meta&&typeof meta==='object'?JSON.stringify([meta.version,meta.key,meta.samples,meta.duration,meta.sourceId]):'';}
function abandonAudition(){
 auditionEpoch++;availabilityEpoch++;auditionAbort?.abort();auditionAbort=null;auditionIntent=null;auditionSignature=null;
 const old=auditionURL;auditionURL=null;state.audition='mix';state.auditionAvailable=false;state.auditionLoading=false;
 if(old){audio.pause();audio.removeAttribute('src');audio.load();URL.revokeObjectURL(old);}auditionChanged();
}
function loadAuditionSource(src,position,signal){
 return new Promise((resolve,reject)=>{
  let timer;
  const finish=(error)=>{clearTimeout(timer);audio.removeEventListener('loadedmetadata',loaded);audio.removeEventListener('error',failed);signal.removeEventListener('abort',aborted);if(error)reject(error);else resolve();};
  const loaded=()=>{if(audio.src!==src)return;try{audio.currentTime=Math.max(0,Math.min(position,Number.isFinite(audio.duration)?audio.duration:position));finish();}catch(error){finish(error);}};
  const failed=()=>finish(Error('This listening layer could not be decoded. Re-analyze the track to recreate it.'));
  const aborted=()=>finish(new DOMException('Listening layer changed','AbortError'));
  if(signal.aborted){aborted();return;}
  audio.addEventListener('loadedmetadata',loaded);audio.addEventListener('error',failed);signal.addEventListener('abort',aborted,{once:true});
  timer=setTimeout(()=>finish(Error('The listening layer took too long to open. Try again.')),15000);
  if(audio.src===src&&audio.readyState>=1)loaded();else{audio.src=src;audio.load();}
 });
}
async function setAudition(mode,{internal=false,resume=true}={}){
 if(!['mix','vocals','accompaniment'].includes(mode))throw Error('Choose Full song, Voice or Backing.');
 if(!state.project||state.loadingProject||(!internal&&(state.busy||state.composing)))throw Error('Wait for the current operation to finish.');
 const project=state.project,selection=state.selection,meta=state.music?.stemCache,signature=stemSignature(meta);
 const intent=auditionIntent&&auditionIntent.project===project&&auditionIntent.selection===selection?auditionIntent:{project,selection,time:audio.currentTime||0,playing:!audio.paused,replacing:false};
 const ticket=++auditionEpoch;auditionAbort?.abort();const controller=new AbortController();auditionAbort=controller;auditionIntent=intent;
 const current=()=>ticket===auditionEpoch&&state.project===project&&state.selection===selection&&(mode==='mix'||signature===stemSignature(state.music?.stemCache));
 state.auditionLoading=true;updateButtons();let nextURL=null;
 try{
  let src=mixAudioUrl();
  if(mode!=='mix'){
   if(!window.LightForgeStemCache)throw Error('The listening tools are still loading. Try again.');
   if(!meta||!Number.isFinite(meta.duration)||Math.abs(meta.duration-project.duration)>.002)throw Error('Re-analyze this track to create matching voice and backing previews.');
   const files=await LightForgeStemCache.files(meta);if(!current())return false;
   nextURL=URL.createObjectURL(files[mode]);src=nextURL;
  }
  if(!current())return false;
  if(!intent.replacing&&Number.isFinite(audio.currentTime))intent.time=Math.max(0,audio.currentTime);intent.replacing=true;
  audio.pause();const oldURL=auditionURL;auditionURL=nextURL;nextURL=null;
  const loading=loadAuditionSource(src,intent.time,controller.signal);if(oldURL)URL.revokeObjectURL(oldURL);
  await loading;if(!current())return false;
  state.audition=mode;if(mode!=='mix')state.auditionAvailable=true;
  if(intent.playing&&resume&&!state.busy&&!previewPaused&&!document.hidden){try{await audio.play();}catch(error){if(current()&&error.name!=='AbortError')toast('The listening layer is ready. Press play to continue.');}}
  if(!current())return false;renderFrame(audio.currentTime||0);drawWave();return true;
 }catch(error){
  if(!current()||error.name==='AbortError')return false;
  if(mode!=='mix'){
   state.auditionAvailable=false;
   try{await setAudition('mix',{internal:true,resume});}catch{}
  }
  if(mode!=='mix'&&['NotFoundError','NotReadableError','SecurityError'].includes(error.name))throw Error('The saved listening layers are unavailable. Re-analyze this track to create them again.');
  throw error;
 }finally{
  if(nextURL)URL.revokeObjectURL(nextURL);
  if(ticket===auditionEpoch){state.auditionLoading=false;auditionIntent=null;auditionAbort=null;updateButtons();}
 }
}
async function refreshAuditionAvailability({force=false}={}){
 const project=state.project,selection=state.selection,meta=state.music?.stemCache,signature=stemSignature(meta);
 if(!force&&signature===auditionSignature)return state.auditionAvailable;
 const changed=signature!==auditionSignature;auditionSignature=signature;state.auditionAvailable=false;const ticket=++availabilityEpoch;
 if(changed&&(state.audition!=='mix'||state.auditionLoading)&&project&&!state.loadingProject){try{await setAudition('mix',{internal:true,resume:!state.busy});}catch{}}
 const current=()=>ticket===availabilityEpoch&&state.project===project&&state.selection===selection&&signature===stemSignature(state.music?.stemCache);
 if(!current())return false;
 if(!project||!meta||!window.LightForgeStemCache||!Number.isFinite(meta.duration)||Math.abs(meta.duration-project.duration)>.002){auditionChanged();return false;}
 try{await LightForgeStemCache.files(meta);if(current())state.auditionAvailable=true;}catch{if(current()){state.auditionAvailable=false;if(state.audition!=='mix'){try{await setAudition('mix',{internal:true,resume:!state.busy});}catch{}}}}
 if(current())auditionChanged();return current()&&state.auditionAvailable;
}
function restoreAnalysisFallback(){if(analysisFallback&&state.music===analysisFallback.music&&state.renderedSettingsKey===analysisFallback.settingsKey&&state.renderedSettingsKey===JSON.stringify(state.settings))state.needAnalysis=false;analysisFallback=null;}
function parse(value,fallback={}){try{return typeof value==='string'?JSON.parse(value):value||fallback;}catch{return fallback;}}
function formatTime(sec){sec=Number.isFinite(Number(sec))?Math.max(0,Number(sec)):0;return `${Math.floor(sec/60)}:${String(Math.floor(sec%60)).padStart(2,'0')}`;}
function text(el,value){el.textContent=String(value==null?'':value);}
function toast(message,error=false){if(error)diagnostics?.log('error','app',message);clearTimeout(toastTimer);text($('toast'),message);$('toast').hidden=false;$('toast').classList.toggle('error',error);toastTimer=setTimeout(()=>$('toast').hidden=true,error?7500:4200);}
function mergeSettings(s){return {...clone(defaults),...s,enabled:{...defaults.enabled,...(s?.enabled||{})},sectionOverrides:s?.sectionOverrides||{}};}
function bridge(method,...args){try{return window.Android?.[method]?.(...args);}catch(e){diagnostics?.log('error','bridge',e);toast(e.message||'The device action could not be completed.',true);throw e;}}
function completedRestoreNeedsPreviewDeferral(job){return !!job?.id&&job.state==='completed'&&localStorage.getItem('lightforge-background-ack')!==job.id;}
function setCompletedRestorePreviewDeferred(deferred){
 const next=!!deferred;if(state.completedRestorePreviewDeferred===next)return;
 state.completedRestorePreviewDeferred=next;vehiclePreview?.setLoadDeferred?.(next);
}
function nav(view){if(view!=='studio')stopInspection();if(!['studio','shows','guide'].includes(view))view='studio';state.view=view;document.querySelectorAll('.view').forEach(el=>el.classList.toggle('active',el.id===view));document.querySelectorAll('.nav-item').forEach(el=>{el.classList.toggle('active',el.dataset.navigate===view);if(el.dataset.navigate===view)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});if(view==='shows'){if(native()&&!state.busy)applyBootstrap(parse(bridge('getBootstrap'),{}));else renderProjects();}window.scrollTo({top:0,behavior:'instant'});resizeCanvases();}
async function readBootstrap(){
 let background=null;
 if(native()){
  const data=parse(bridge('getBootstrap'),{});background=data.backgroundJob||null;state.backgroundJob=background;
  state.backgroundSyncPending=completedRestoreNeedsPreviewDeferral(background);setCompletedRestorePreviewDeferred(state.backgroundSyncPending);
  applyBootstrap(data);state.lastProjectId=(backgroundActive(background)||state.backgroundSyncPending)?background.projectId:data.lastProjectId;
  renderDeviceCapabilities(data.deviceCapabilities);
 }else{state.projects=parse(localStorage.getItem('lightforge-projects'),[]);state.lastProjectId=localStorage.getItem('lightforge-last-project');renderProjects();}
 try{state.settings=mergeSettings(parse(localStorage.getItem('lightforge-settings'),defaults));}catch{}
 // An unacknowledged completed job owns its restore in handleBackgroundJob.
 // Loading it here first duplicates verification and can reopen the studio
 // after the user has navigated away during that first asynchronous restore.
 syncControls();if(!state.project&&state.lastProjectId&&!state.backgroundSyncPending){const p=state.projects.find(p=>p.id===state.lastProjectId);if(p)await selectProject(p);}
 if(background)await handleBackgroundJob(background);
}
function applyBootstrap(data){if(Array.isArray(data.projects)){state.projects=data.projects;for(const project of data.projects)diagnostics?.protectText(project.name);}if(data.version)text($('appVersion'),data.version);if('pendingExport'in data)state.pendingExport=data.pendingExport;if(state.project){const p=state.projects.find(p=>p.id===state.project.id);if(p){Object.assign(state.project,p);text($('trackTitle'),p.name);}}if(state.pendingProjectAction?.kind==='rename'){state.pendingProjectAction=null;endBusy();toast('Show renamed.');}renderProjects();document.dispatchEvent(new CustomEvent('lightforge:changed'));}
function setProgress(info){diagnostics?.progress('progress',info);const {progress=0,stage='Working',detail,message}=info;if(!state.busy)return;state.progressFacts={...info};state.progressLastAt=Date.now();renderProgressFacts();const p=Math.max(0,Math.min(1,progress>1?progress/100:progress));$('progressBar').style.width=(p*100)+'%';$('progressBar').parentElement.setAttribute('aria-valuenow',String(Math.round(p*100)));text($('progressPercent'),Math.round(p*100)+'%');text($('progressStage'),stage);text($('progressDetail'),detail||message||'Preparing your show…');const titles={separat:'Separating voice and accompaniment',vocal:'Reading the voice phrasing',voice:'Reading the voice phrasing',pitch:'Following notes and holds',restore:'Restoring your show',duplicate:'Creating your new version',import:'Bringing your music in',decode:'Preparing the audio',model:'Warming up the neural engine',neural:'Listening to the rhythm',beats:'Finding the groove',structure:'Reading the arrangement',generate:'Choreographing your show',export:'Packing your light show'};const key=Object.keys(titles).find(k=>String(stage).toLowerCase().includes(k));if(key)text($('progressTitle'),titles[key]);}
function beginBusy(title,detail){diagnostics?.log('info','operation',title);state.busy=true;state.job++;state.busyStartedAt=Date.now();state.progressLastAt=state.busyStartedAt;state.progressFacts={};clearInterval(progressClock);progressClock=setInterval(renderProgressFacts,1000);$('processing').hidden=false;text($('progressTitle'),title);text($('progressDetail'),detail);text($('progressStage'),'Preparing');text($('progressPercent'),'0%');$('progressBar').style.width='0%';$('progressBar').parentElement.setAttribute('aria-valuenow','0');$('cancelWork').disabled=false;renderProgressFacts();renderBackgroundNote();audio.pause();updateButtons();return state.job;}
function endBusy(){if(state.busy)diagnostics?.log('info','operation','Processing dialog closed');state.busy=false;clearInterval(progressClock);if($('backgroundContinue'))$('backgroundContinue').hidden=true;if($('backgroundPower'))$('backgroundPower').hidden=true;$('processing').hidden=true;state.abort=null;updateButtons();}
function openAudioPicker(){if(state.busy)return;if(native()){state.acceptProgress=true;bridge('pickAudio');}else $('browserFile').click();}
async function db(){if(!dbPromise)dbPromise=new Promise((resolve,reject)=>{const r=indexedDB.open('lightforge',1);r.onupgradeneeded=()=>{r.result.createObjectStore('audio');r.result.createObjectStore('projects');};r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});return dbPromise;}
async function dbGet(store,key){const d=await db();return new Promise((resolve,reject)=>{const r=d.transaction(store).objectStore(store).get(key);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
async function dbPut(store,key,value){const d=await db();return new Promise((resolve,reject)=>{const tx=d.transaction(store,'readwrite');tx.objectStore(store).put(value,key);tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error);});}
async function dbDelete(store,key){const d=await db();return new Promise((resolve,reject)=>{const tx=d.transaction(store,'readwrite');tx.objectStore(store).delete(key);tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error);});}
function encodeWav(buffer){const frames=buffer.length,bytes=new ArrayBuffer(44+frames*4),v=new DataView(bytes),write=(p,s)=>{for(let i=0;i<s.length;i++)v.setUint8(p+i,s.charCodeAt(i));};write(0,'RIFF');v.setUint32(4,36+frames*4,true);write(8,'WAVEfmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,2,true);v.setUint32(24,44100,true);v.setUint32(28,176400,true);v.setUint16(32,4,true);v.setUint16(34,16,true);write(36,'data');v.setUint32(40,frames*4,true);const l=buffer.getChannelData(0),r=buffer.getChannelData(Math.min(1,buffer.numberOfChannels-1));for(let i=0;i<frames;i++){v.setInt16(44+i*4,Math.round(Math.max(-1,Math.min(1,l[i]))*32767),true);v.setInt16(46+i*4,Math.round(Math.max(-1,Math.min(1,r[i]))*32767),true);}return new Blob([bytes],{type:'audio/wav'});}
async function importBrowser(file){if(!file)return;diagnostics?.protectText(file.name);diagnostics?.protectText(file.name.replace(/\.[^.]+$/,''));const job=beginBusy('Bringing your music in','Converting audio to the format your Tesla needs.');try{const ctx=new (window.AudioContext||window.webkitAudioContext)();const decoded=await ctx.decodeAudioData(await file.arrayBuffer());await ctx.close();if(job!==state.job)return;const offline=new OfflineAudioContext(2,Math.ceil(decoded.duration*44100),44100),source=offline.createBufferSource();source.buffer=decoded;source.connect(offline.destination);source.start();const pcm=await offline.startRendering();if(job!==state.job)return;const wav=encodeWav(pcm),id='show-'+Date.now(),project={id,name:file.name.replace(/\.[^.]+$/,''),duration:pcm.duration,createdAt:Date.now(),audioUrl:URL.createObjectURL(wav),browser:true};await dbPut('audio',id,wav);state.projects.unshift(project);localStorage.setItem('lightforge-projects',JSON.stringify(state.projects));endBusy();await selectProject(project,true);toast('Music imported. Choose your style and create.');}catch(e){diagnostics?.log('error','operation',e);endBusy();toast('This audio could not be imported. '+(e.message||'Try another file.'),true);}}
async function selectProject(project,isNew=false,{navigate=true,restoreLease=null,restoreSaved=undefined}={}){
 diagnostics?.protectText(project?.name);
 stopInspection(); if(state.busy)return;clearTimeout(saveTimer);if(state.project&&!state.loadingProject&&!(await saveProject()))return;state.compileAbort?.abort();state.compileId++;state.composing=false;const selection=++state.selection,id=project.id;
 const current=()=>selection===state.selection&&state.project?.id===id;
 abandonAudition();audio.pause();clearTimeout(regenTimer);if(project.audioUrl)project.audioUrl=new URL(project.audioUrl,location.href).href;if(project.analysisUrl)project.analysisUrl=new URL(project.analysisUrl,location.href).href;if(project.previewUrl)project.previewUrl=new URL(project.previewUrl,location.href).href;
 state.project=project;state.saveBlocked=false;state.loadingProject=true;state.music=null;state.show=null;state.compiled=null;state.history=[];state.future=[];state.renderedSettingsKey=null;state.showMusic=null;state.editing=null;state.needAnalysis=false;lastSection=-1;
 $('results').hidden=true;$('validationCard').hidden=true;$('sectionEditor').hidden=true;$('noShowOverlay').hidden=false;$('emptyCard').hidden=true;$('workingStudio').hidden=false;
 document.querySelector('.controls-column').inert=true;
 text($('trackTitle'),project.name||'Untitled show');text($('trackMeta'),isNew?'Audio ready':'Opening saved project…');text($('totalTime'),formatTime(project.duration));$('seek').max=project.duration||1;audio.src=project.previewUrl||project.audioUrl||'';if(navigate)nav('studio');else resizeCanvases();updateButtons();
 try{let saved=restoreSaved;
  if(!isNew&&restoreSaved===undefined){if(project.browser){const blob=await dbGet('audio',id);if(!current())return;if(blob){if(project.audioUrl?.startsWith('blob:'))URL.revokeObjectURL(project.audioUrl);project.audioUrl=URL.createObjectURL(blob);audio.src=project.audioUrl;}saved=await dbGet('projects',id);if(!current())return;
   }else if(project.projectUrl){const response=await fetch(project.projectUrl);if(!current())return;if(response.ok){saved=await response.json();if(!current())return;}}}
  if(!current())return;
  if(saved){state.settings=mergeSettings(saved.settings);state.music=saved.music||null;state.compiled=saved.compiled||null;state.needAnalysis=!!saved.needAnalysis;}else state.settings=mergeSettings({...state.settings,sectionOverrides:{},manualCues:[],outputEnabled:{},vocalRegions:[],musicCues:[],vocalOffsetMs:0,bassOffsetMs:0});
  if(restoreLease&&!completedRestorePulse(restoreLease,'project-loaded',typeof state.compiled?.frameData==='string'?state.compiled.frameData.length:0))throw Error('Native completed-restore lease rejected the project load phase.');
  state.loadingProject=false;document.querySelector('.controls-column').inert=false;text($('trackMeta'),`${formatTime(project.duration)} · ${project.previewSampleRate===22050?'Long-track mono preview · Stereo export':'44.1 kHz stereo · On this device'}`);syncControls();
  if(state.music)await regenerate({save:false,restoreCompiled:state.compiled,restoreLease});else{updateButtons();renderFrame(0);drawWave();}
  if(current()){scheduleSave();await refreshAuditionAvailability({force:true});}
 }catch(e){diagnostics?.log('error','operation',e);if(!current())return;state.saveBlocked=true;state.loadingProject=false;document.querySelector('.controls-column').inert=false;syncControls();updateButtons();renderFrame(0);text($('trackMeta'),'Audio ready · Saved settings could not be opened');if(restoreLease)throw e;toast('Audio is ready. Create a new show to rebuild this project.',true);}
}

function currentShowMatches(){return !!state.show&&!state.needAnalysis&&state.showMusic===state.music&&state.renderedSettingsKey===JSON.stringify(state.settings);}
function projectJson(){return {version:1,name:state.project?.name,projectId:state.project?.id,updatedAt:Date.now(),settings:state.settings,music:state.music,needAnalysis:state.needAnalysis,compiled:currentShowMatches()?state.compiled:null,provenance:{app:LightForgeVersion.name,planner:state.show?.version||null,profile:VehicleProfile.version,analysis:state.music?.analysisVersion||null,model:state.music?.engine||null,frameSHA256:currentShowMatches()?state.compiled?.sha256:null}};}
function scheduleSave(){clearTimeout(saveTimer);saveTimer=setTimeout(saveProject,450);try{localStorage.setItem('lightforge-settings',JSON.stringify(state.settings));}catch{}}
async function saveProject(){if(backgroundActive(state.backgroundJob)||state.backgroundSyncPending)return true;if(!state.project||state.loadingProject)return false;if(state.saveBlocked)return true;const project=state.project,body=projectJson(),marker={id:state.project.id,name:state.project.name,settings:JSON.stringify(state.settings),music:state.music,compiled:body.compiled,needAnalysis:state.needAnalysis};if(state.lastSaved&&Object.keys(marker).every(k=>state.lastSaved[k]===marker[k]))return true;try{localStorage.setItem('lightforge-last-project',project.id);if(native()){const saved=bridge('saveProject',project.id,JSON.stringify(body));if(saved!==true&&saved!=='true')throw new Error('The device could not save this project. Free some storage and try again.');}else await dbPut('projects',project.id,body);const p=state.projects.find(p=>p.id===project.id);if(p){p.hasShow=!!body.music;p.style=body.settings.style;p.updatedAt=body.updatedAt;}if(!native())localStorage.setItem('lightforge-projects',JSON.stringify(state.projects));state.lastSaved=marker;state.lastSave=Date.now();document.dispatchEvent(new CustomEvent('lightforge:saved'));return true;}catch(e){toast('This project could not be saved: '+e.message,true);return false;}}

function captureSnapshot(){const retainFrames=!state.show||state.show.frames.byteLength<=16*1024*1024;return {projectId:state.project?.id,settings:clone(state.settings),music:state.music,show:retainFrames?state.show:null,compiled:currentShowMatches()?state.compiled:null,exportHeader:state.exportHeader,needAnalysis:state.needAnalysis,renderedSettingsKey:state.renderedSettingsKey,showMusic:state.showMusic};}
function trimHistory(list){let bytes=0;const seen=new Set();for(let i=list.length-1;i>=0;i--){const show=list[i].show;if(show&&!seen.has(show)){seen.add(show);bytes+=show.frames.byteLength;}if(i<list.length-2&&(bytes>64*1024*1024||list.length-i>20)){list.splice(0,i+1);break;}}}
function snapshot(){state.history.push(captureSnapshot());trimHistory(state.history);state.future=[];$('undo').disabled=false;}
async function restoreSnapshot(saved,{recordHistory=true}={}){
 if(!saved||saved.projectId!==state.project?.id)throw Error('This version belongs to another project.');
 if(state.busy||state.loadingProject)throw Error('Wait for the current operation to finish.');
 if(recordHistory)snapshot();state.compileAbort?.abort();state.compileId++;state.composing=false;
 state.settings=mergeSettings(clone(saved.settings));state.music=saved.music;state.needAnalysis=!!saved.needAnalysis;state.show=saved.show;state.compiled=saved.compiled;state.exportHeader=saved.exportHeader;state.renderedSettingsKey=saved.renderedSettingsKey;state.showMusic=saved.showMusic;
 stopInspection();syncControls();if(state.show&&(currentShowMatches()||state.needAnalysis))presentShow();else if(state.music&&!state.needAnalysis)await regenerate({restoreCompiled:saved.compiled});else{renderFrame(audio.currentTime||0);updateButtons();}scheduleSave();await refreshAuditionAvailability();return true;
}
async function undo(){if(!state.history.length||state.busy||state.loadingProject)return;const saved=state.history.pop();state.future.push(captureSnapshot());trimHistory(state.future);await restoreSnapshot(saved,{recordHistory:false});syncControls();}
async function redo(){if(!state.future.length||state.busy||state.loadingProject)return;const saved=state.future.pop();state.history.push(captureSnapshot());trimHistory(state.history);await restoreSnapshot(saved,{recordHistory:false});syncControls();}
function syncControls(){const s=state.settings;document.querySelectorAll('[data-style]').forEach(b=>{b.classList.toggle('selected',b.dataset.style===s.style);b.setAttribute('aria-checked',String(b.dataset.style===s.style));});document.querySelectorAll('[data-dance]').forEach(b=>{b.classList.toggle('selected',b.dataset.dance===s.dance);b.setAttribute('aria-checked',String(b.dataset.dance===s.dance));});for(const id of ['intensity','stepMs','sensitivity','beatDivision','offsetMs','palette'])$(id).value=s[id];$('bpmOverride').value=s.bpmOverride||'';$('optionalFog').checked=!!s.optionalFog;document.querySelectorAll('[data-feature]').forEach(el=>el.checked=!!s.enabled[el.dataset.feature]);text($('intensityValue'),Math.round(s.intensity*100)+'%');text($('sensitivityValue'),Math.round(s.sensitivity*100)+'%');text($('danceHelp'),s.dance==='off'?'Keep the rhythm in the lights. Powered closures stay still.':s.dance==='balanced'?'Musical gestures with room to breathe between the big moments.':'Coordinated window, mirror, trunk and charge-port moves at musical peaks.');document.querySelectorAll('input[type=range]:not(#seek)').forEach(updateRangeFill);$('undo').disabled=!state.history.length;updateButtons();}
function updateRangeFill(el){el.style.setProperty('--fill',100*(Number(el.value)-Number(el.min))/(Number(el.max)-Number(el.min))+'%');}
function settingsChanged(needsAnalysis=false){
 state.compileAbort?.abort();state.compileId++;state.composing=false;clearTimeout(regenTimer);
 if(needsAnalysis)state.needAnalysis=true;syncControls();scheduleSave();
 if(state.music&&!needsAnalysis&&!state.needAnalysis){state.composing=true;updateButtons();regenTimer=setTimeout(()=>regenerate(),220);}
 else if(state.needAnalysis){$('validationCard').hidden=true;text($('generationHint'),'Create again to analyze the music with your updated rhythm settings.');}
}
function updateButtons(){
 const has=!!state.show,waiting=state.busy||state.loadingProject||state.composing||state.auditionLoading,ready=currentShowMatches()&&state.show.validation?.valid;
 $('generate').disabled=!state.project||waiting;text($('quickAction'),state.composing?'Updating your show…':ready?'Export USB-ready show':state.needAnalysis?'Analyze & recreate':'Create my light show');
 $('quickAction').classList.toggle('export',!!ready);$('quickAction').disabled=waiting;
 text($('generate').querySelector('span'),state.needAnalysis?'Analyze & recreate':has?'Recreate light show':'Create my light show');$('play').disabled=!state.project||state.loadingProject||state.auditionLoading;$('seek').disabled=state.auditionLoading;$('backBeat').disabled=state.auditionLoading;$('forwardBeat').disabled=state.auditionLoading;
 $('undo').disabled=!state.history.length||state.busy||state.loadingProject;if($('redo'))$('redo').disabled=!state.future.length||state.busy||state.loadingProject;
 $('export').disabled=waiting||!ready;$('noShowOverlay').hidden=has;
 if(!state.needAnalysis)text($('generationHint'),state.composing?'Updating the arrangement in the background…':state.music&&(state.music.analysisVersion||1)<6?'Your saved arrangement is preserved. Re-analyze for GAME Large singing transcription and studio source separation.':has?'Tweak a setting to update the preview. Your show saves automatically.':'On-device music analysis. No subscription. No uploads.');
 document.dispatchEvent(new CustomEvent('lightforge:changed'));
}
function elapsedLabel(milliseconds){
 const seconds=Math.max(0,Math.floor(milliseconds/1000)),minutes=Math.floor(seconds/60),hours=Math.floor(minutes/60);
 return hours?`${hours}h ${minutes%60}m ${seconds%60}s`:minutes?`${minutes}m ${seconds%60}s`:`${seconds}s`;
}
function renderProgressFacts(){
 const panel=$('progressMetrics');if(!panel)return;panel.hidden=!state.busy;if(!state.busy)return;
 const facts=state.progressFacts||{},job=backgroundActive(state.backgroundJob)?state.backgroundJob:null,now=Date.now();
 const created=Number(job?.createdAt)||state.busyStartedAt||now;
 text($('progressElapsed'),'Elapsed '+elapsedLabel(now-created));
 const count=Number(facts.passageCount)||0,index=Number(facts.passageIndex)||0;
 text($('progressPassage'),count>0&&index>0?`Passage ${Math.min(index,count)} of ${count}`:'');
 const saved=[];if(facts.passagesCompleted>0)saved.push(`${facts.passagesCompleted} passage${facts.passagesCompleted===1?'':'s'} completed`);
 if(facts.restoredPassages>0)saved.push(`${facts.restoredPassages} reused`);
 if(!saved.length&&facts.completedStages>0)saved.push(`${facts.completedStages} analysis stage${facts.completedStages===1?'':'s'} complete`);
 if(facts.restoredStages>0)saved.push(`${facts.restoredStages} stage${facts.restoredStages===1?'':'s'} reused`);
 $('progressSaved').hidden=!saved.length;text($('progressSaved'),saved.join(' · '));
 const lastUpdate=Number(job?.progressAt)||Number(job?.updatedAt)||state.progressLastAt||now,quiet=now-lastUpdate;
 const waiting=quiet>=90000&&(job||facts.elapsedSeconds!==undefined)&&job?.state!=='cancelling';$('progressActivity').hidden=!waiting;
 if(waiting)text($('progressActivity'),`This model step has not reported progress for ${elapsedLabel(quiet)}. LightForge is checking for a response.${job?' Completed work stays saved.':''}`);
}
function backgroundActive(job){return !!job&&['queued','running','cancelling'].includes(job.state);}
function backgroundSupported(){return native()&&typeof window.Android.startAnalysis==='function';}
function renderBackgroundNote(){
 const active=backgroundActive(state.backgroundJob),note=$('processingNote');
 if(note)text(note,active?(state.deviceCapabilities?.notifications===false?'You can switch apps or lock the screen. Notifications are off; reopen LightForge for progress.':'You can switch apps or lock the screen. Follow progress in your notification.'):'Keep LightForge open for this operation.');
 if($('backgroundContinue'))$('backgroundContinue').hidden=!active;
 if($('backgroundPower'))$('backgroundPower').hidden=!(active&&state.deviceCapabilities?.batteryOptimized);
}
function renderDeviceCapabilities(data){
 if(!data)return;state.deviceCapabilities=data;
 const panel=$('backgroundDevice');if(panel)panel.hidden=false;
 const gb=Number(data.memoryBytes)/(1024**3);
 text($('backgroundDeviceSummary'),`${data.cpuCores||'—'} CPU cores · ${Number.isFinite(gb)?gb.toFixed(1):'—'} GB memory · Android API ${data.androidSdk||'—'}`);
 text($('backgroundDeviceStatus'),data.batteryRestricted?'Android is restricting background work. Open Battery settings and allow unrestricted use for LightForge.':data.notifications===false?'Background analysis is available. Enable notifications to see progress and completion outside the app.':data.batteryOptimized?'Background analysis is ready. Allow background battery use for long jobs with the screen off.':'Background analysis is ready. Progress and Cancel stay available in your notification.');
 renderBackgroundNote();
}
function completedRestoreNonce(){completedRestoreEpoch++;return `${Date.now().toString(36)}-${completedRestoreEpoch.toString(36)}-${Math.random().toString(36).slice(2,14)}`;}
function beginCompletedRestore(job){
 const prior=state.completedRestore;
 const lease={jobId:job.id,projectId:String(job.projectId||''),nonce:completedRestoreNonce(),phase:'bootstrap',sequence:0,bytes:0,renderCountBeforeAdopt:0,workerVerified:false,adoptedProjectId:null,adoptedSelection:0,adoptedCompileId:0,failed:false,terminal:false,ackWritten:false,ackConfirmed:false};
 state.completedRestore=lease;
 let accepted;
 try{accepted=bridge('beginCompletedRestore',lease.jobId,lease.nonce,lease.bytes);}
 catch(error){state.completedRestore=prior||null;setCompletedRestorePreviewDeferred(false);throw error;}
 if(accepted!==true){state.completedRestore=prior||null;setCompletedRestorePreviewDeferred(false);throw Error('Native completed-restore lease was rejected.');}
 setCompletedRestorePreviewDeferred(true);
 if(prior&&prior!==lease&&prior.terminal&&!prior.ackConfirmed&&prior.jobId!==lease.jobId){
  // Native has atomically retired only this old unconfirmed terminal token
  // for the new durable completed job. Keep the old job's persisted cap
  // armed; a later old ACK now fails its exact job+nonce check.
  prior.superseded=true;diagnostics?.log('warn','background','A later completed job superseded an unconfirmed native ACK token.');
 }
 return lease;
}
function completedRestoreOwnsAdoptedProject(lease){return !!lease&&state.completedRestore===lease&&!lease.failed&&!lease.terminal&&!!lease.projectId&&state.project?.id===lease.projectId&&lease.adoptedProjectId===lease.projectId&&lease.adoptedSelection===state.selection&&lease.adoptedCompileId===state.compileId&&!!state.show&&!!state.compiled;}
function completedRestorePulse(lease,phase,bytes=lease?.bytes||0){
 if(!lease||state.completedRestore!==lease||lease.failed||lease.terminal)return false;
 lease.phase=phase;lease.sequence++;lease.bytes=Math.max(0,Number(bytes)||0);
 if(bridge('completedRestorePulse',lease.jobId,lease.nonce,phase,lease.sequence,lease.bytes)===true)return true;
 completedRestoreFailed(lease,'Native completed-restore pulse was rejected.');return false;
}
function completedRestoreFailed(lease,reason){
 if(!lease||state.completedRestore!==lease||lease.failed||lease.terminal)return;
 lease.failed=true;lease.phase='failed';lease.sequence++;setCompletedRestorePreviewDeferred(false);bridge('completedRestoreFailed',lease.jobId,lease.nonce,String(reason||'restore-failed').slice(0,120));
}
function completedRestoreWorkerEvent(lease,event){
 if(!lease||state.completedRestore!==lease||event?.lease?.jobId!==lease.jobId||event.lease?.nonce!==lease.nonce)return;
 if(event.type==='restore-error'){completedRestoreFailed(lease,event.message||'worker-error');return;}
 if(event.type==='restore-started')completedRestorePulse(lease,'worker-started');
 else if(event.type==='restore-pulse')completedRestorePulse(lease,`worker-${event.phase||'pulse'}`,event.total||lease.bytes);
 else if(event.type==='restore-verified'){lease.workerVerified=true;completedRestorePulse(lease,'worker-verified');}
}
function completedRestorePacketBytes(encoded){
 if(typeof encoded!=='string'||encoded.length===0)return new Uint8Array(0);
 const binary=atob(encoded),bytes=new Uint8Array(binary.length);
 for(let index=0;index<binary.length;index++)bytes[index]=binary.charCodeAt(index);
 return bytes;
}
async function readCompletedRestoreProjectFromBridge(project,lease){
 if(typeof window.Android?.readCompletedRestoreProjectChunk!=='function')return null;
 const Decoder=window.TextDecoder||globalThis.TextDecoder;
 if(typeof Decoder!=='function')throw Error('This device cannot safely decode the completed project payload.');
 // Keep decoded chunks separately until the bounded snapshot is complete.
 // Repeated string concatenation becomes quadratic for multi-megabyte FSEQ
 // payloads and can starve the renderer that this recovery is trying to
 // restore.
 const decoder=new Decoder('utf-8',{fatal:true});let offset=0,total=-1,snapshot='',chunks=0;const parts=[];
 for(;;){
  if(!completedRestorePulse(lease,'project-read',offset))throw Error('Native completed-restore lease rejected the project-read phase.');
  const packet=parse(bridge('readCompletedRestoreProjectChunk',lease.jobId,lease.nonce,project.id,offset,COMPLETED_RESTORE_PROJECT_CHUNK_BYTES),null);
  if(!packet||packet.ok!==true)throw Error(packet?.error||'The completed project payload was unavailable.');
  const start=Number(packet.offset),declaredTotal=Number(packet.total),declaredSnapshot=String(packet.snapshot||'');
  if(!Number.isSafeInteger(start)||start!==offset||!Number.isSafeInteger(declaredTotal)||declaredTotal<=0||declaredTotal>COMPLETED_RESTORE_PROJECT_MAX_BYTES)throw Error('The completed project payload was malformed.');
  if(!/^[0-9]+:[0-9a-f-]{36}$/.test(declaredSnapshot))throw Error('The completed project payload has no stable snapshot identity.');
  if(total<0){total=declaredTotal;snapshot=declaredSnapshot;}else if(total!==declaredTotal||snapshot!==declaredSnapshot)throw Error('The completed project payload changed while it was being read.');
  const bytes=completedRestorePacketBytes(packet.base64);if(bytes.length===0||offset+bytes.length>total)throw Error('The completed project payload ended unexpectedly.');
  offset+=bytes.length;parts.push(decoder.decode(bytes,{stream:offset<total}));
  if(offset===total){parts.push(decoder.decode());return JSON.parse(parts.join(''));}
  if(++chunks>Math.ceil(total/COMPLETED_RESTORE_PROJECT_CHUNK_BYTES)+1)throw Error('The completed project payload did not make bounded progress.');
  // Give the renderer/probe queue a turn during a very large saved-show read.
  if(chunks%16===0)await new Promise(resolve=>setTimeout(resolve,0));
 }
}
async function readCompletedRestoreProjectFromFetch(project,lease){
 if(!project?.projectUrl)throw Error('The completed project has no saved payload.');
 if(!completedRestorePulse(lease,'project-read-fallback',lease.bytes))throw Error('Native completed-restore lease rejected the project-read fallback.');
 const Controller=window.AbortController||globalThis.AbortController,controller=Controller?new Controller():null;
 let timer;
 const timeout=new Promise((_,reject)=>{timer=setTimeout(()=>{try{controller?.abort();}catch{}reject(Error('The completed project read timed out before it could be restored.'));},COMPLETED_RESTORE_PROJECT_READ_TIMEOUT_MS);});
 try{
  const response=await Promise.race([fetch(project.projectUrl,controller?{signal:controller.signal}:undefined),timeout]);
  if(!response?.ok)throw Error('The completed project could not be read.');
  const body=typeof response.text==='function'
   ?await Promise.race([response.text(),timeout])
   :JSON.stringify(await Promise.race([response.json?.(),timeout]));
  if(typeof body!=='string'||body.length===0||body.length>COMPLETED_RESTORE_PROJECT_MAX_BYTES)throw Error('The completed project payload is invalid or too large.');
  if(!completedRestorePulse(lease,'project-read',body.length))throw Error('Native completed-restore lease rejected the project-read result.');
  return JSON.parse(body);
 }finally{clearTimeout(timer);}
}
async function readCompletedRestoreProject(project,lease){
 if(typeof window.Android?.readCompletedRestoreProjectChunk==='function')return readCompletedRestoreProjectFromBridge(project,lease);
 // Older native hosts have no scoped payload bridge. Their only escape hatch
 // remains the same-origin project resource, bounded and never treated as a
 // successful restore until the ordinary compiled-show verification finishes.
 return readCompletedRestoreProjectFromFetch(project,lease);
}
function awaitCompletedRestoreRender(lease){return new Promise((resolve,reject)=>{
 let settled=false,frame=null;
 const finish=(callback,value)=>{if(settled)return;settled=true;if(frame!==null){cancelAnimationFrame(frame);frame=null;}callback(value);};
 const fail=error=>finish(reject,error);
 const succeed=()=>finish(resolve);
 const preview=vehiclePreview,ready=preview?.ready;
 // A failed GLTF/WebGL preview cannot provide the required first-frame proof.
 // Keep the completed job pending for a safe retry instead of waiting forever.
 if(ready&&typeof ready.then==='function')Promise.resolve(ready).then(value=>{if(value===false)fail(Error('The 3D preview could not render the completed show.'));},()=>fail(Error('The 3D preview could not render the completed show.')));
 const inspect=()=>{
  frame=null;if(settled)return;
  if(!completedRestoreOwnsAdoptedProject(lease))return fail(Error('Saved arrangement restoration was superseded.'));
  if(preview?.loaded&&Number(preview.renderCount)>lease.renderCountBeforeAdopt){
   if(!completedRestorePulse(lease,'preview-first-render'))return fail(Error('Native completed-restore lease rejected the first web render.'));
   succeed();return;
  }
  frame=requestAnimationFrame(inspect);
 };
 inspect();
});}
function awaitCompletedRestoreVisualCommit(lease){return new Promise((resolve,reject)=>{
 const inspect=()=>{
  if(!completedRestoreOwnsAdoptedProject(lease))return reject(Error('Saved arrangement restoration was superseded before its visual frame committed.'));
  if(bridge('requestCompletedRestoreVisualCommit',lease.jobId,lease.nonce)!==true)return reject(Error('Native completed-restore visual proof was rejected.'));
  if(bridge('completedRestoreVisualCommitted',lease.jobId,lease.nonce)===true){
   if(!completedRestorePulse(lease,'preview-visual-commit'))return reject(Error('Native completed-restore visual phase was rejected.'));
   resolve();return;
  }
  requestAnimationFrame(inspect);
 };
 inspect();
});}
function completeCompletedRestore(lease){
 if(!completedRestoreOwnsAdoptedProject(lease)||!lease.workerVerified)throw Error('Saved arrangement restoration was superseded before worker verification.');
 const priorPhase=lease.phase;lease.phase='terminal';lease.sequence++;
 if(bridge('completedRestoreTerminal',lease.jobId,lease.nonce,lease.sequence,lease.bytes)!==true){lease.phase=priorPhase;lease.sequence--;throw Error('Native completed-restore terminal proof was rejected.');}
 lease.terminal=true;
}
function completedRestoreAwaitingAck(lease,job){
 return !!lease&&state.completedRestore===lease&&!lease.failed&&lease.terminal&&!lease.ackConfirmed&&lease.jobId===job?.id;
}
function completedRestoreAckCommitted(lease){
 // This is a post-write confirmation for the native replacement cap only.
 // It never lets native write, clear, or inspect the browser ACK itself.
 // Do not allow an old lease to confirm a different job, or let an unproven
 // terminal state claim a browser ACK it has not durably written.
 if(!lease||state.completedRestore!==lease||lease.failed||!lease.terminal||lease.ackConfirmed)return false;
 if(localStorage.getItem('lightforge-background-ack')!==lease.jobId)return false;
 try{
  if(bridge('completedRestoreAckCommitted',lease.jobId,lease.nonce)!==true){diagnostics?.log('warn','background','Native replacement cap remains armed after browser ACK confirmation was unavailable.');return false;}
  lease.ackConfirmed=true;return true;
 }catch(error){diagnostics?.log('warn','background','Native replacement cap confirmation failed: '+(error.message||error));return false;}
}
function writeCompletedRestoreAck(lease,job){
 if(!completedRestoreAwaitingAck(lease,job))throw Error('Completed-restore ACK no longer belongs to this job.');
 // Reuse this exact terminal lease after a storage failure.  A fresh lease is
 // intentionally forbidden while native retains its terminal job+nonce token.
 if(!lease.ackWritten||localStorage.getItem('lightforge-background-ack')!==job.id){
  localStorage.setItem('lightforge-background-ack',job.id);
  if(localStorage.getItem('lightforge-background-ack')!==job.id)throw Error('The completed show could not be acknowledged in browser storage.');
  lease.ackWritten=true;
 }
 state.backgroundSyncPending=false;
 return completedRestoreAckCommitted(lease);
}
async function handleBackgroundJob(job){
 if(!job?.id)return;state.backgroundJob=job;
 if(state.diagnosticBackgroundState!==job.id+':'+job.state){state.diagnosticBackgroundState=job.id+':'+job.state;const status=['queued','running','cancelling','completed','failed','interrupted','cancelled'].includes(job.state)?job.state:'unknown';diagnostics?.log(['failed','interrupted'].includes(status)?'error':'info','background','Analysis state='+status);}
 if(job.state==='completed'&&localStorage.getItem('lightforge-background-ack')!==job.id)state.backgroundSyncPending=true;
 if(state.loadingProject||state.backgroundApplying)return;
 if(backgroundActive(job)){
  if(!state.busy)beginBusy('Creating your show in the background','You can switch apps while LightForge works.');
  renderBackgroundNote();setProgress({...job,stage:job.analysisStage||(job.progress>=.96?'generate':'analysis'),detail:job.stage});
  $('cancelWork').disabled=job.state==='cancelling';return;
 }
 // Once native terminal proof exists, a failed browser-storage write must
 // retry that same job+nonce rather than opening a new lease that native
 // correctly rejects until its exact post-ACK confirmation arrives.
 const terminalLease=state.completedRestore;
 if(job.state==='completed'&&completedRestoreAwaitingAck(terminalLease,job)){
  state.backgroundApplying=true;
  try{
   const confirmed=writeCompletedRestoreAck(terminalLease,job);
   state.backgroundSeen=job.id+':'+job.state;
   if(confirmed)toast('Your background show is ready. Press play to review it.');
  }catch(error){
   terminalLease.ackWritten=false;state.backgroundSyncPending=true;state.backgroundSeen=null;
   diagnostics?.log('error','background',error);toast(error.message,true);
  }finally{
   if(terminalLease.ackConfirmed&&state.completedRestore===terminalLease)state.completedRestore=null;
   state.backgroundApplying=false;
  }
  updateButtons();return;
 }
 if(state.backgroundSeen===job.id+':'+job.state)return;
 state.backgroundSeen=job.id+':'+job.state;
 if(state.busy&&!state.abort)endBusy();
 const banner=$('backgroundRecovery');if(banner)banner.hidden=true;
 if(job.state==='completed'){
  if(!state.backgroundSyncPending)return;
  let restoreLease=null;state.backgroundApplying=true;
  try{
   restoreLease=beginCompletedRestore(job);
   clearTimeout(saveTimer);applyBootstrap(parse(bridge('getBootstrap'),{}));
   const project=state.projects.find(p=>p.id===job.projectId);if(!project)throw Error('The completed project could not be found.');
   const restoreSaved=await readCompletedRestoreProject(project,restoreLease);
   state.lastSaved=null;await selectProject(project,false,{navigate:false,restoreLease,restoreSaved});
   if(state.saveBlocked||!completedRestoreOwnsAdoptedProject(restoreLease))throw Error('The completed project was superseded before its saved show could be adopted.');
   await awaitCompletedRestoreRender(restoreLease);await awaitCompletedRestoreVisualCommit(restoreLease);completeCompletedRestore(restoreLease);
   writeCompletedRestoreAck(restoreLease,job);
   toast('Your background show is ready. Press play to review it.');
  }catch(error){completedRestoreFailed(restoreLease,error.message||error);diagnostics?.log('error','background',error);state.backgroundSeen=null;toast(error.message,true);}
  finally{if(restoreLease&&state.completedRestore===restoreLease&&(restoreLease.failed||restoreLease.ackConfirmed))state.completedRestore=null;state.backgroundApplying=false;}
 }else if(['failed','interrupted','cancelled'].includes(job.state)){
  state.backgroundSyncPending=false;
  if(banner){banner.hidden=false;const saved=job.hasCheckpoint?' Completed music analysis is saved; resume skips straight to choreography.':job.resumeAvailable?' Verified progress is saved and will be reused.':' Resume checks for saved progress before continuing.';text($('backgroundRecoveryMessage'),(job.stage||'Your saved show is intact.')+saved);text($('backgroundRetry'),'Resume analysis');}
 }
 updateButtons();
}
async function pollBackgroundJob(){
 if(!backgroundSupported()||document.hidden)return;
 const job=parse(bridge('getAnalysisStatus'),null);if(job)await handleBackgroundJob(job);
}
async function startBackgroundGeneration(){
 if(!(await saveProject()))return;
 clearTimeout(saveTimer);abandonAudition();audio.pause();audio.src=mixAudioUrl();
 const job=parse(bridge('startAnalysis',state.project.id),{});
 if(job.error||!job.id){toast(job.error||'Background analysis could not start.',true);return;}
 state.backgroundSeen=null;state.backgroundSyncPending=false;
 if($('backgroundRecovery'))$('backgroundRecovery').hidden=true;
 await handleBackgroundJob(job);
}
async function generate(){
 stopInspection();if(!state.project||state.busy||state.loadingProject)return;
 if(!window.MusicAnalyzer||!window.ShowCompiler){toast('The show tools are still loading. Try again in a moment.',true);return;}
 clearTimeout(regenTimer);state.compileAbort?.abort();state.compileId++;state.composing=false;
 if(backgroundSupported()){await startBackgroundGeneration();return;}
 const previous=captureSnapshot(),job=beginBusy('Listening to the music','Separating the voice and reading the musical detail on this device.');state.abort=new AbortController();
 analysisFallback=previous.show&&previous.showMusic===previous.music&&previous.renderedSettingsKey===JSON.stringify(previous.settings)?{music:previous.music,settingsKey:previous.renderedSettingsKey}:null;
 try{
  await setAudition('mix',{internal:true,resume:false});if(job!==state.job)return;
  let music=state.music;const settings=clone(state.settings);
  if(!music||state.needAnalysis||(music.analysisVersion||1)<5)music=await MusicAnalyzer.analyze(state.project.audioUrl,{sensitivity:settings.sensitivity,bpmOverride:settings.bpmOverride||undefined,analysisQuality:settings.analysisQuality,projectId:state.project.id,analysisUrl:state.project.analysisUrl||undefined},p=>{if(job===state.job)setProgress({...p,progress:.96*Math.max(0,Math.min(1,Number(p.progress)||0))});},state.abort.signal);
  if(job!==state.job)return;setProgress({progress:.96,stage:'generate',detail:'Composing phrases and preparing movements for musical arrivals.'});
  music=alignedMusic(music);
  const result=await ShowCompiler.generate(music,settings,p=>{if(job===state.job)setProgress({...p,progress:.96+.04*Math.max(0,Math.min(1,Number(p.progress)||0))});},state.abort.signal);
  if(job!==state.job)return;
  if(previous.music){state.history.push(previous);trimHistory(state.history);state.future=[];}
  analysisFallback=null;state.music=music;state.needAnalysis=false;state.settings=settings;adoptShow(result,music,settings);
  const saved=await saveProject();endBusy();await refreshAuditionAvailability({force:true});if(saved)toast('Your show is ready. Press play and make it yours.');$('previewBadge').focus?.();
 }catch(e){diagnostics?.log(e.name==='AbortError'?'info':'error','analysis',e);if(job!==state.job)return;restoreAnalysisFallback();endBusy();await refreshAuditionAvailability({force:true});if(e.name!=='AbortError')toast('Could not create this show. '+(e.message||'Please try again.'),true);}updateButtons();
}
function alignedMusic(music){const duration=Number(state.project?.duration);if(!Number.isFinite(duration)||duration<=0||duration===music.duration)return music;const sections=music.sections?.map(s=>({...s}));if(sections?.length)sections[sections.length-1].end=duration;return {...music,duration,sections};}
function presentShow(){
 const show=state.show;if(!show)return;const music=state.music||{},rhythm=show.choreography?.rhythm;
 $('results').hidden=false;$('noShowOverlay').hidden=true;const bpm=Number(rhythm?.bpm??music.bpm);text($('bpmStat'),Number.isFinite(bpm)&&bpm>0?bpm.toFixed(1):'—');text($('beatStat'),bpm>0?Math.round(60000/bpm)+' ms':'—');text($('sectionStat'),show.sections?.length||music.sections?.length||0);text($('frameStat'),show.stepMs);text($('previewBadge'),music.engine?.neural?'NEURAL BEATS · LIVE':'LIVE PREVIEW');renderSections();renderValidation();renderFrame(audio.currentTime||0);drawWave();updateButtons();
}
function adoptShow(result,music,settings){state.saveBlocked=false;state.show=result.show;state.compiled=result.compiled;state.exportHeader=result.header;state.showMusic=music;state.renderedSettingsKey=JSON.stringify(settings);presentShow();refreshAuditionAvailability().catch(()=>{});}
async function regenerate({save=true,preparedShow=null,restoreCompiled=null,restoreLease=null}={}){
 if(!state.music||!window.ShowCompiler)return null;clearTimeout(regenTimer);state.compileAbort?.abort();const controller=new AbortController(),ticket=++state.compileId,projectId=state.project?.id;
 state.compileAbort=controller;state.composing=true;updateButtons();
 try{
  const music=alignedMusic(state.music),settings=clone(state.settings);let result;
 if(preparedShow)result={show:preparedShow,compiled:null};
  else if(restoreCompiled){if(restoreLease&&!completedRestorePulse(restoreLease,'restore-dispatched'))throw Error('Native completed-restore lease rejected dispatch.');result=await ShowCompiler.restore(restoreCompiled,music,settings,()=>{},controller.signal,restoreLease?{restoreLease,onRestoreEvent:event=>completedRestoreWorkerEvent(restoreLease,event)}:undefined);}
  else result=await ShowCompiler.generate(music,settings,()=>{},controller.signal);
  if(restoreLease?.failed)throw Error('Native completed-restore lease rejected an ordered worker event.');
  if(ticket!==state.compileId||projectId!==state.project?.id)return null;
  if(restoreLease&&(!restoreLease.projectId||state.completedRestore!==restoreLease||restoreLease.projectId!==projectId))return null;
  state.music=music;if(restoreLease)restoreLease.renderCountBeforeAdopt=Number(vehiclePreview?.renderCount)||0;adoptShow(result,music,settings);if(restoreLease){setCompletedRestorePreviewDeferred(false);restoreLease.adoptedProjectId=projectId;restoreLease.adoptedSelection=state.selection;restoreLease.adoptedCompileId=ticket;if(!completedRestorePulse(restoreLease,'show-adopted'))throw Error('Native completed-restore lease rejected the adopted show.');}if(save)scheduleSave();return state.show;
 }catch(e){if(restoreLease)completedRestoreFailed(restoreLease,e.message||e);diagnostics?.log(e.name==='AbortError'?'info':'error','composition-worker',e);if(ticket!==state.compileId||e.name==='AbortError')return null;if(restoreCompiled)state.saveBlocked=true;toast((restoreCompiled?'Saved arrangement could not be verified: ':'The show could not be built: ')+e.message,true);return null;}
 finally{if(ticket===state.compileId){state.composing=false;state.compileAbort=null;updateButtons();}}
}
function renderValidation(){const v=state.show.validation;$('validationCard').hidden=false;$('validationCard').classList.toggle('invalid',!v.valid);text($('validationIcon'),v.valid?'✓':'!');text($('validationTitle'),v.valid?'Ready for your Model 3':'A check needs attention');text($('validationSummary'),v.valid?'Timing, format & movement limits checked':'Adjust the show before exporting');$('export').disabled=!v.valid;const content=$('validationContent');content.replaceChildren();const list=document.createElement('ul');const lines=[`Uncompressed FSEQ v2 · 200 channels · ${state.soloPreview?.show.stepMs||state.show?.stepMs||20} ms`,`Duration ${formatTime(state.show.duration)} · ${state.show.frameCount.toLocaleString()} frames`,'44.1 kHz stereo PCM WAV · matched filenames',`Analysis: ${state.music.engine?.name||'On-device rhythm engine'}`];for(const line of [...lines,...(v.errors||[]).map(x=>'Issue: '+x),...(v.warnings||[]).map(x=>'Note: '+x),...(state.music.warnings||[]).map(x=>'Analysis: '+x)]){const li=document.createElement('li');text(li,line);list.appendChild(li);}content.appendChild(list);}
function renderSections(){const list=$('sectionList');list.replaceChildren();(state.show.sections||state.music.sections||[]).forEach((s,i)=>{const b=document.createElement('button');b.className='section-item'+(state.settings.sectionOverrides[i]?' edited':'');b.dataset.section=i;const small=document.createElement('small'),strong=document.createElement('strong'),bar=document.createElement('div'),fill=document.createElement('i');text(small,formatTime(s.start)+' – '+formatTime(s.end));text(strong,s.label||'Section '+(i+1));bar.className='section-energy';fill.style.width=Math.round((state.settings.sectionOverrides[i]?.intensity??s.energy??.5)*100)+'%';bar.appendChild(fill);b.append(small,strong,bar);b.onclick=()=>editSection(i);list.appendChild(b);});}
function editSection(index){const s=(state.show?.sections||state.music?.sections)[index];if(!s)return;state.editing=index;audio.currentTime=Math.min(s.start,audio.duration||s.start);renderFrame(audio.currentTime);drawWave();text($('editingName'),s.label||'Section '+(index+1));$('sectionStyle').value=state.settings.sectionOverrides[index]?.style||'';$('sectionEnergy').value=state.settings.sectionOverrides[index]?.intensity??state.settings.intensity;text($('sectionEnergyValue'),Math.round($('sectionEnergy').value*100)+'%');updateRangeFill($('sectionEnergy'));$('sectionEditor').hidden=false;document.querySelectorAll('.section-item').forEach(b=>b.classList.toggle('selecting',Number(b.dataset.section)===index));}
function renderProjects(){const list=$('showList');list.replaceChildren();$('noProjects').hidden=state.projects.length>0;for(const p of state.projects){const card=document.createElement('article');card.className='saved-show';const art=document.createElement('button');art.className='album-art';art.setAttribute('aria-label','Open '+p.name);art.style.border='0';art.innerHTML='<svg viewBox="0 0 24 24"><path d="M9 17V5l11-2v12M9 8l11-2"/><ellipse cx="6" cy="18" rx="3" ry="2"/><ellipse cx="17" cy="16" rx="3" ry="2"/></svg><i></i><i></i>';art.onclick=()=>selectProject(p);const copy=document.createElement('div');copy.className='saved-show-copy';copy.tabIndex=0;copy.setAttribute('role','button');const title=document.createElement('h3'),meta=document.createElement('p');text(title,p.name||'Untitled show');text(meta,`${formatTime(p.duration)} · ${p.style?capitalize(p.style):'Ready to create'} · ${new Date(p.createdAt||p.updatedAt||Date.now()).toLocaleDateString(undefined,{month:'short',day:'numeric'})}`);copy.append(title,meta);copy.onclick=()=>selectProject(p);copy.onkeydown=e=>{if(e.key==='Enter'||e.key===' ')selectProject(p);};const del=document.createElement('button');del.className='icon-button project-options';del.setAttribute('aria-label','Options for '+p.name);del.innerHTML='<svg viewBox="0 0 24 24"><circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="12" cy="19" r="1"/></svg>';del.onclick=()=>projectMenu(p);card.append(art,copy,del);list.appendChild(card);}}
function capitalize(x){return String(x).charAt(0).toUpperCase()+String(x).slice(1);}
function confirmAction(title,message){return new Promise(resolve=>{text($('confirmTitle'),title);text($('confirmMessage'),message);$('confirmDialog').showModal();$('confirmCancel').onclick=()=>{$('confirmDialog').close();resolve(false);};$('confirmOkay').onclick=()=>{$('confirmDialog').close();resolve(true);};$('confirmDialog').oncancel=()=>resolve(false);});}
async function deleteProject(p){if(!await confirmAction('Delete “'+p.name+'”?','This removes its music and saved project from this device. Exported files are kept.'))return;if(native())bridge('deleteProject',p.id);else{await dbDelete('audio',p.id);await dbDelete('projects',p.id);}state.projects=state.projects.filter(x=>x.id!==p.id);if(!native())localStorage.setItem('lightforge-projects',JSON.stringify(state.projects));if(state.project?.id===p.id){abandonAudition();audio.pause();audio.removeAttribute('src');state.selection++;state.loadingProject=false;state.project=null;state.music=null;state.show=null;$('workingStudio').hidden=true;$('emptyCard').hidden=false;}renderProjects();toast('Show deleted.');}
async function exportShow(){stopInspection();if(!currentShowMatches()||!state.show.validation.valid||state.busy||state.composing)return;if(!(await saveProject()))return;state.acceptProgress=true;const job=beginBusy('Packing your light show','Preparing correctly named playback files and your validation report.');try{const header=state.exportHeader,frames=state.show.frames;if(!(header instanceof Uint8Array))throw Error('Create this show again to prepare its checked export header.');if(native()){const response=bridge('beginExport',JSON.stringify({projectId:state.project.id,name:state.project.name,stepMs:state.show.stepMs,duration:state.show.duration,validation:state.show.validation,projectState:projectJson()}));const parsed=parse(response,null),id=parsed?.id??response;if(!id||id==='null')throw new Error('The export could not be started.');state.exportId=id;let written=0;const total=header.length+frames.length;for(const part of [header,frames])for(let p=0;p<part.length;p+=49152){if(job!==state.job)return;let binary='';const chunk=part.subarray(p,p+49152);for(let i=0;i<chunk.length;i++)binary+=String.fromCharCode(chunk[i]);const result=bridge('appendExport',String(id),btoa(binary));if(result===false||result==='false')throw new Error('A show-data block could not be written.');written+=chunk.length;setProgress({progress:.15+.65*(written/total),stage:'export',detail:'Writing your light sequence…'});if(p%491520===0)await new Promise(r=>setTimeout(r,0));}setProgress({progress:.9,stage:'export',detail:'Choose where to save your ZIP.'});bridge('finishExport',String(id));}else{const bytes=new Uint8Array(header.length+frames.length);bytes.set(header);bytes.set(frames,header.length);const wav=new Uint8Array(await(await fetch(state.project.audioUrl)).arrayBuffer());if(job!==state.job)return;const enc=new TextEncoder();const zip=zipStored([['LightShow/lightshow.fseq',bytes],['LightShow/lightshow.wav',wav],['START_HERE.txt',enc.encode('LightForge — '+state.project.name+'\n\nExtract this ZIP. Put the LightShow folder at the USB root.\nUse exFAT/FAT32 and glovebox data USB port.\nIn the car open Toybox > Light Show > Schedule Show.\nPreview closure requests are not a physical motor simulation.\n')],['Review/Validation.json',enc.encode(JSON.stringify(state.show.validation,null,2))],['Review/LightForge_Project.json',enc.encode(JSON.stringify(projectJson()))]]);const name=safeName(state.project.name)+'_LightForge.zip';const url=URL.createObjectURL(zip),link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),60000);exported({name});}}catch(e){diagnostics?.log('error','operation',e);endBusy();toast('Export failed: '+e.message,true);} }
function projectMenu(p){text($('menuProjectName'),p.name);$('projectMenu').showModal();$('closeProjectMenu').onclick=()=>$('projectMenu').close();const choose=fn=>()=>{$('projectMenu').close();fn(p);};$('menuOpen').onclick=choose(selectProject);$('menuRename').onclick=choose(renameProject);$('menuDuplicate').onclick=choose(duplicateProject);$('menuDelete').onclick=choose(deleteProject);if($('menuRestoreRevision')){$('menuRestoreRevision').hidden=!p.hasPreviousRevision;$('menuRestoreRevision').onclick=choose(async p=>{if(await confirmAction('Restore previous save?','Restore the previous saved version of “'+p.name+'”? Your current saved version will become the recovery copy.'))restorePreviousProject(p.id);});}}
function namePrompt(title,value,action){return new Promise(resolve=>{text($('nameTitle'),title);text($('nameOkay'),action);$('projectNameInput').value=value;const finish=value=>{diagnostics?.protectText(value);$('nameDialog').close();resolve(value);};const accept=()=>{const value=$('projectNameInput').value.trim();if(value)finish(value);else $('projectNameInput').focus();};$('nameOkay').onclick=accept;$('nameCancel').onclick=()=>finish(null);$('nameDialog').oncancel=()=>resolve(null);$('projectNameInput').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();accept();}};$('projectNameInput').oninput=()=>$('nameOkay').disabled=!$('projectNameInput').value.trim();$('nameOkay').disabled=!value.trim();$('nameDialog').showModal();setTimeout(()=>{$('projectNameInput').focus();$('projectNameInput').select();},50);});}
async function renameProject(p){const name=await namePrompt('Rename your show',p.name,'Save name');if(!name||name===p.name)return;try{if(state.project?.id===p.id&&!(await saveProject()))return;if(native()){state.pendingProjectAction={kind:'rename',id:p.id};beginBusy('Renaming your show','Updating your collection.');bridge('renameProject',p.id,name);return;}const saved=await dbGet('projects',p.id);if(saved){saved.name=name;saved.updatedAt=Date.now();await dbPut('projects',p.id,saved);}p.name=name;p.updatedAt=Date.now();if(state.project?.id===p.id){state.project.name=name;text($('trackTitle'),name);}localStorage.setItem('lightforge-projects',JSON.stringify(state.projects));renderProjects();toast('Show renamed.');}catch(e){diagnostics?.log('error','operation',e);endBusy();toast('Could not rename this show: '+e.message,true);}}
async function duplicateProject(p){const name=await namePrompt('Name your new version',p.name+' copy','Create copy');if(!name)return;try{if(state.project?.id===p.id&&!(await saveProject()))return;const job=beginBusy('Creating your new version','Copying music, analysis and your creative settings.');if(native()){state.pendingProjectAction={kind:'duplicate',id:p.id};bridge('duplicateProject',p.id,name);return;}let blob=await dbGet('audio',p.id);if(job!==state.job)return;if(!blob){const response=await fetch(p.audioUrl);if(job!==state.job)return;blob=await response.blob();if(job!==state.job)return;}const saved=await dbGet('projects',p.id);if(job!==state.job)return;const id='show-'+crypto.randomUUID(),copy={...p,id,name,browser:true,createdAt:Date.now(),updatedAt:Date.now(),audioUrl:URL.createObjectURL(blob)};delete copy.projectUrl;delete copy.analysisUrl;await dbPut('audio',id,blob);if(saved)await dbPut('projects',id,{...saved,name,projectId:id,updatedAt:Date.now()});if(job!==state.job)return;state.projects.unshift(copy);localStorage.setItem('lightforge-projects',JSON.stringify(state.projects));endBusy();await selectProject(copy,false);toast('New version created. Make it your own.');}catch(e){diagnostics?.log('error','operation',e);endBusy();toast('Could not copy this show: '+e.message,true);}}
$('newProject').onclick=openAudioPicker;$('restoreBackup').onclick=()=>{if(!native())return;state.acceptProgress=true;bridge('pickProjectBackup');};

function safeName(name){return String(name||'My_Show').replace(/[^a-zA-Z0-9_-]+/g,'_').replace(/^_+|_+$/g,'').slice(0,70)||'My_Show';}
function zipStored(files){const encoder=new TextEncoder(),table=new Uint32Array(256);for(let n=0;n<256;n++){let c=n;for(let k=0;k<8;k++)c=c&1?0xedb88320^(c>>>1):c>>>1;table[n]=c>>>0;}const crc=data=>{let c=0xffffffff;for(const b of data)c=table[(c^b)&255]^(c>>>8);return(c^0xffffffff)>>>0;};const local=[],central=[];let offset=0,centralSize=0;for(const [name,data] of files){const n=encoder.encode(name),sum=crc(data),h=new Uint8Array(30+n.length),v=new DataView(h.buffer);v.setUint32(0,0x04034b50,true);v.setUint16(4,20,true);v.setUint16(6,0x800,true);v.setUint32(14,sum,true);v.setUint32(18,data.length,true);v.setUint32(22,data.length,true);v.setUint16(26,n.length,true);h.set(n,30);local.push(h,data);const c=new Uint8Array(46+n.length),cv=new DataView(c.buffer);cv.setUint32(0,0x02014b50,true);cv.setUint16(4,20,true);cv.setUint16(6,20,true);cv.setUint16(8,0x800,true);cv.setUint32(16,sum,true);cv.setUint32(20,data.length,true);cv.setUint32(24,data.length,true);cv.setUint16(28,n.length,true);cv.setUint32(42,offset,true);c.set(n,46);central.push(c);centralSize+=c.length;offset+=h.length+data.length;}const end=new Uint8Array(22),ev=new DataView(end.buffer);ev.setUint32(0,0x06054b50,true);ev.setUint16(8,files.length,true);ev.setUint16(10,files.length,true);ev.setUint32(12,centralSize,true);ev.setUint32(16,offset,true);return new Blob([...local,...central,end],{type:'application/zip'});}
function exported(data){state.pendingExport=null;state.acceptProgress=false;endBusy();state.exportId=data.id||data.exportId||state.exportId;text($('exportName'),data.name||'Your light show ZIP');$('shareExport').hidden=!native();$('exportSuccess').hidden=false;}
function resetStudio(){snapshot();state.settings=clone(defaults);state.needAnalysis=!!state.music;settingsChanged(true);toast('Recommended settings restored.');}
function canvasSize(canvas){const rect=canvas.getBoundingClientRect(),ratio=Math.min(window.devicePixelRatio||1,2);if(!rect.width||!rect.height)return null;const w=Math.round(rect.width*ratio),h=Math.round(rect.height*ratio);if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}return {ctx:canvas.getContext('2d'),w:rect.width,h:rect.height,ratio};}
function resizeCanvases(){if(previewPaused||document.hidden)return;renderFrame(audio.currentTime||0);drawWave();}
function rounded(ctx,x,y,w,h,r){ctx.beginPath();ctx.roundRect(x,y,w,h,r);}
const startupPreviewBootstrap=(()=>{try{return native()?parse(window.Android?.getBootstrap?.(),null):null;}catch(error){diagnostics?.log('warn','bootstrap',error);return null;}})();
const startupPreviewDeferred=completedRestoreNeedsPreviewDeferral(startupPreviewBootstrap?.backgroundJob);
state.completedRestorePreviewDeferred=startupPreviewDeferred;
const vehiclePreview=new VehiclePreview($('carCanvas'),(view,label)=>{text($('cameraLabel'),label);document.querySelectorAll('[data-camera]').forEach(el=>{const selected=el.dataset.camera===view;el.classList.toggle('selected',selected);el.setAttribute('aria-pressed',String(selected));});},{deferLoad:startupPreviewDeferred});
const monitorGroups=VehicleProfile.outputs.filter(o=>o.available&&o.kind==='light').map(o=>[o.name,o.channels]);
for(const [name,channels] of monitorGroups){const cell=document.createElement('span');cell.className='lamp-cell';cell.dataset.channels=channels.join(',');const dot=document.createElement('i'),label=document.createElement('span'),value=document.createElement('b');text(label,name);text(value,'0%');cell.append(dot,label,value);$('lampMonitor').appendChild(cell);}
const rgbLabels=['Display','R rear cabin','R front cabin','Dashboard','L front cabin','L rear cabin'];for(let i=0;i<rgbLabels.length;i++){const cell=document.createElement('span');cell.className='lamp-cell';cell.dataset.rgb=i;const dot=document.createElement('i'),label=document.createElement('span'),value=document.createElement('b');text(label,rgbLabels[i]);text(value,'#000000');cell.append(dot,label,value);$('lampMonitor').appendChild(cell);}
let renderedTime=NaN,renderedShow=null;
function updateOutputMonitor(data){text($('frameCounter'),data?`Frame ${data.frame.toLocaleString()} · ${state.soloPreview?.show.stepMs||state.show?.stepMs||20} ms`:'Frame —');const lights=data?.lights||[];for(const el of $('lampMonitor').children){if(el.dataset.rgb!==undefined){const rgb=data?.interior?.[Number(el.dataset.rgb)]||[0,0,0],level=Math.max(...rgb)/255,hex='#'+rgb.map(x=>Math.round(x).toString(16).padStart(2,'0')).join('');el.style.setProperty('--level',level);el.classList.toggle('lit',level>.005);el.querySelector('i').style.background=hex;text(el.querySelector('b'),hex.toUpperCase());el.dataset.level=String(level);continue;}const channels=el.dataset.channels.split(',').map(Number),level=Math.max(...channels.map(ch=>lights[ch-1]||0));el.style.setProperty('--level',level);el.classList.toggle('lit',level>.005);text(el.querySelector('b'),Math.round(level*100)+'%');el.dataset.level=String(level);}}
function renderFrame(time){if(state.soloPreview){const solo=state.soloPreview,t=solo.offset+(performance.now()-solo.started)/1000;if(t>=solo.duration){stopInspection();return;}const data=ShowEngine.stateAt(solo.show,t);vehiclePreview.render(data,t);updateOutputMonitor(data);updateMovementLabels(data.closures||[]);text($('sectionLabel'),'Inspecting · '+solo.name);text($('previewBadge'),'INSPECTION · PREVIEW ONLY');return;}renderedTime=time;renderedShow=state.show;let data=null;try{data=state.show?ShowEngine.stateAt(state.show,time):null;}catch(e){text($('previewBadge'),'PREVIEW UNAVAILABLE');}vehiclePreview.render(data,time);updateOutputMonitor(data);if(data){const sections=state.show.sections||[],si=sections.findIndex(s=>time>=s.start&&time<s.end);if(si!==lastSection){lastSection=si;document.querySelectorAll('.section-item').forEach(el=>el.classList.toggle('current',Number(el.dataset.section)===si));}text($('sectionLabel'),data.section?.label||'Your light show');updateMovementLabels(data.closures||[]);}else{text($('sectionLabel'),'Ready when you are');document.querySelectorAll('#movementStrip b').forEach(b=>{text(b,'—');b.classList.remove('active');});}text($('currentTime'),formatTime(time));$('seek').value=time;}
function updateMovementLabels(closures){const groups=[[37,38,39,40],[35,36],[41],[46]];document.querySelectorAll('#movementStrip b').forEach((b,i)=>{const items=closures.filter(c=>groups[i].includes(c.channel)),moving=items.filter(c=>c.moving),dancing=items.filter(c=>c.dancing);let label=items.some(c=>c.rainbow)?'Rainbow':dancing.length?(i===0?dancing.length+' dancing':'Dancing'):moving.some(c=>c.motion==='opening')?(i===1?'Unfolding':'Opening'):moving.some(c=>c.motion==='closing')?(i===1?'Folding':'Closing'):items.some(c=>c.motion==='stopped')?'Stopped':items.length?items.every(c=>(c.openFraction??c.estimatedPosition)<.02)?(i===1?'Folded':'Closed'):items.every(c=>(c.openFraction??c.estimatedPosition)>.98)?(i===1?'Unfolded':'Open'):'Part open':'—';text(b,label);b.classList.toggle('active',moving.length>0||dancing.length>0);});}
function drawWave(){const can=canvasSize($('waveCanvas'));if(!can)return;const {ctx,w,h,ratio}=can;ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,w,h);const waveform=state.music?.waveform||[],duration=state.project?.duration||1,time=audio.currentTime||0,playX=w*Math.min(1,time/duration);const sections=state.music?.sections||[];for(let i=0;i<sections.length;i++){const s=sections[i];ctx.fillStyle=i%2?'#192d3c66':'#0a192822';ctx.fillRect(w*s.start/duration,0,w*(s.end-s.start)/duration,h);}const bars=Math.floor(w/3);for(let i=0;i<bars;i++){let amp=waveform.length?(waveform[Math.floor(i/bars*waveform.length)]||0):.13;const height=Math.max(2,Math.pow(Math.abs(amp),.7)*(h-6));ctx.fillStyle=i/bars*w<=playX?'#79e9d7':'#415b71';rounded(ctx,i*3,(h-height)/2,1.7,height,.8);ctx.fill();}ctx.fillStyle='#e8ff94';ctx.fillRect(Math.max(0,playX-1),0,1.5,h);}
function tick(ts){frameRequest=0;if(previewPaused||document.hidden)return;if(ts-lastDraw>=15&&state.view==='studio'&&state.project){const time=audio.currentTime||0;if(state.soloPreview||time!==renderedTime||state.show!==renderedShow){lastDraw=ts;renderFrame(time);drawWave();}}frameRequest=requestAnimationFrame(tick);}
function togglePlay(){stopInspection();if(!state.project)return;if(audio.paused)audio.play().catch(e=>toast('Audio playback could not start: '+e.message,true));else audio.pause();}
function updatePlay(){const playing=!audio.paused;$('play').innerHTML=playing?'<svg viewBox="0 0 24 24"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>':'<svg viewBox="0 0 24 24"><path d="m8 5 11 7-11 7z"/></svg>';$('play').setAttribute('aria-label',playing?'Pause preview':'Play preview');}
window.onNativeEvent=(type,payload)=>{if(diagnostics?.handleNativeEvent(type,payload))return;const data=parse(payload,{});if(type==='analysisJob'){handleBackgroundJob(data);return;}if(type==='deviceCapabilities'){renderDeviceCapabilities(data);return;}if(type==='progress'){if(state.abort)return;if(!state.busy&&!state.acceptProgress)return;if(!state.busy)beginBusy('Bringing your music in','Preparing the audio file.');setProgress(data);}else if(type==='imported'){state.acceptProgress=false;endBusy();const p=data.project||data;const existing=state.projects.findIndex(x=>x.id===p.id);if(existing>=0)state.projects[existing]=p;else state.projects.unshift(p);selectProject(p,true);toast('Music imported. Choose your style and create.');}else if(type==='error'){if(state.abort){toast(data.message||'A device action could not be completed.',true);return;}state.pendingProjectAction=null;state.acceptProgress=false;endBusy();toast(data.message||'The device action could not be completed.',true);}else if(type==='exportRecovery'){state.pendingExport=data.pendingExport??data;state.acceptProgress=false;endBusy();updateButtons();}else if(type==='exported')exported(data);else if(type==='projects')applyBootstrap(data);else if(type==='projectReady'){state.pendingProjectAction=null;state.acceptProgress=false;endBusy();const p=data.project||data;const i=state.projects.findIndex(x=>x.id===p.id);if(i>=0)state.projects[i]=p;else state.projects.unshift(p);selectProject(p,false);toast('Project ready. Your music and edits are restored.');}else if(type==='cancelled'||type==='canceled'){if(state.abort)return;state.acceptProgress=false;endBusy();toast('Canceled. Your saved work is still here.');}};

let editQueue=Promise.resolve();
function commitChannelSettings(patch){const copied=clone(patch),projectId=state.project?.id;const apply=()=>{if(projectId!==state.project?.id)throw Error('The project changed before this edit was applied.');return applyChannelSettings(copied);};const task=editQueue.then(apply,apply);editQueue=task.catch(()=>{});return task;}
async function applyChannelSettings(patch){
 if(state.busy||state.loadingProject)throw new Error('Wait for the current operation to finish.');
 const next=mergeSettings(clone({...state.settings,...patch}));if(JSON.stringify(next)===JSON.stringify(state.settings))return true;const needsAnalysis=['analysisQuality','bpmOverride','sensitivity'].some(k=>next[k]!==state.settings[k]);
 clearTimeout(regenTimer);state.compileAbort?.abort();const ticket=++state.compileId,projectId=state.project?.id;
 if(needsAnalysis||state.needAnalysis||!state.music){snapshot();state.settings=next;if(needsAnalysis)state.needAnalysis=true;state.composing=false;syncControls();scheduleSave();return true;}
 const music=alignedMusic(state.music),controller=new AbortController();state.compileAbort=controller;state.composing=true;updateButtons();
 try{const result=await ShowCompiler.generate(music,next,()=>{},controller.signal);if(ticket!==state.compileId||projectId!==state.project?.id)throw new DOMException('Edit superseded','AbortError');snapshot();stopInspection();state.settings=next;state.music=music;adoptShow(result,music,next);syncControls();scheduleSave();return true;}
 finally{if(ticket===state.compileId){state.composing=false;state.compileAbort=null;updateButtons();}}
}
function stopInspection(){if(!state.soloPreview)return;state.soloPreview=null;$('noShowOverlay').hidden=!!state.show;text($('previewBadge'),state.music?.engine?.neural?'NEURAL BEATS · LIVE':'LIVE PREVIEW');renderFrame(audio.currentTime||0);document.dispatchEvent(new CustomEvent('lightforge:inspection'));}
function startInspection(output,value,rgb){
 stopInspection();audio.pause();const stepMs=20,travel=output.channels[0]===41?14:output.channels[0]>=37&&output.channels[0]<=40?4:2;
 let offset=0,run=output.kind==='closure'?Math.max(5,travel+1):5,initial=null;
 if(output.kind==='closure'){
  if(value===191||value===127){initial=63;offset=travel+.2;}
  else if(value===63&&output.channels[0]<37){initial=191;offset=2.2;}
  else if(value===255||value===0){initial=63;offset=Math.min(1,travel/2);}
 }
 const duration=offset+run,frameCount=Math.ceil(duration*50)+1,frames=new Uint8Array(frameCount*200);
 const paint=(a,b,v)=>{for(let f=Math.floor(a*50);f<Math.ceil(b*50);f++)for(let i=0;i<output.channels.length;i++)frames[f*200+output.channels[i]-1]=Array.isArray(v)?v[i]:v;};
 if(initial!==null)paint(0,offset,initial);
 const cueValue=output.kind==='rgb'?rgb:value;
 if(output.kind==='light'&&[0,26,51,77].includes(value)){paint(0,1,255);offset=1;}
 paint(offset,duration,cueValue);
 const show={frames,channels:200,channelCount:200,frameCount,stepMs,duration,settings:state.settings,sections:[{start:0,end:duration,label:output.name}]};
 state.soloPreview={show,name:output.name,started:performance.now(),offset,duration};$('noShowOverlay').hidden=true;vehiclePreview.setView(output.camera);renderFrame(audio.currentTime||0);document.dispatchEvent(new CustomEvent('lightforge:inspection'));
}
$('pickAudio').onclick=$('changeAudio').onclick=openAudioPicker;$('browserFile').onchange=e=>{importBrowser(e.target.files[0]);e.target.value='';};$('loadDemo').onclick=async()=>{if(native()){state.acceptProgress=true;bridge('loadDemo');return;}try{const response=await fetch('demo/glass-castle.wav');if(!response.ok)throw new Error('The demo file is unavailable.');await importBrowser(new File([await response.blob()],'Glass Castle — demo excerpt.wav',{type:'audio/wav'}));}catch(e){toast(e.message,true);}};
$('quickAction').onclick=()=>currentShowMatches()?exportShow():generate();$('quickTune').onclick=()=>document.querySelector('.controls-column').scrollIntoView({behavior:'smooth',block:'start'});$('generate').onclick=generate;$('play').onclick=togglePlay;$('backBeat').onclick=()=>audio.currentTime=Math.max(0,audio.currentTime-10);$('forwardBeat').onclick=()=>audio.currentTime=Math.min(audio.duration||0,audio.currentTime+10);$('mute').onclick=()=>{audio.muted=!audio.muted;$('mute').style.opacity=audio.muted?'.4':'1';$('mute').setAttribute('aria-label',audio.muted?'Unmute audio':'Mute audio');};$('seek').oninput=e=>{stopInspection();audio.currentTime=Number(e.target.value);renderFrame(audio.currentTime);drawWave();};audio.onplay=audio.onpause=audio.onended=()=>{updatePlay();renderFrame(audio.currentTime||0);};audio.onseeked=()=>{renderFrame(audio.currentTime||0);drawWave();};audio.onloadedmetadata=()=>{if(state.project){const duration=Number.isFinite(audio.duration)&&audio.duration>0?audio.duration:state.project.duration;$('seek').max=duration||1;text($('totalTime'),formatTime(duration));}};audio.onerror=()=>{if(!state.auditionLoading&&state.project&&audio.src)toast('This project’s audio could not be opened. Try selecting the song again.',true);};
$('cancelWork').onclick=()=>{diagnostics?.log('info','operation','Cancel requested');if(backgroundActive(state.backgroundJob)){bridge('cancelAnalysis',state.backgroundJob.id);$('cancelWork').disabled=true;text($('progressDetail'),'Cancelling background analysis…');return;}restoreAnalysisFallback();state.acceptProgress=false;state.job++;state.abort?.abort();state.compileAbort?.abort();state.compileId++;state.composing=false;clearTimeout(regenTimer);if(native())bridge('cancelWork');endBusy();updateButtons();toast('Canceled. Your saved work is still here.');};$('previewMode').onclick=()=>{state.previewMode=1-state.previewMode;document.querySelector('.preview-card').classList.toggle('expanded',!!state.previewMode);$('previewMode').setAttribute('aria-pressed',String(!!state.previewMode));text($('previewMode'),state.previewMode?'Reduce ↙':'Expand ↗');renderFrame(audio.currentTime);};document.querySelectorAll('[data-camera]').forEach(el=>el.onclick=()=>{vehiclePreview.setView(el.dataset.camera);renderFrame(audio.currentTime||0);});
document.querySelectorAll('[data-navigate]').forEach(el=>el.onclick=()=>nav(el.dataset.navigate));document.querySelector('.wordmark').onclick=e=>{e.preventDefault();nav('studio');};document.querySelectorAll('[data-style]').forEach(el=>el.onclick=()=>{if(state.settings.style===el.dataset.style)return;snapshot();state.settings.style=el.dataset.style;settingsChanged();});document.querySelectorAll('[data-dance]').forEach(el=>el.onclick=()=>{if(state.settings.dance===el.dataset.dance)return;snapshot();state.settings.dance=el.dataset.dance;settingsChanged();});
for(const id of ['intensity','sensitivity']){$(id).addEventListener('pointerdown',snapshot);$(id).addEventListener('keydown',e=>{if(['ArrowRight','ArrowLeft','ArrowUp','ArrowDown'].includes(e.key))snapshot();});$(id).oninput=()=>{state.settings[id]=Number($(id).value);settingsChanged(id==='sensitivity');};}
for(const id of ['stepMs','beatDivision','palette','bpmOverride','offsetMs'])$(id).onchange=()=>{snapshot();const val=$(id).value;state.settings[id]=['stepMs','bpmOverride','offsetMs'].includes(id)?(val===''?null:Number(val)):val;if(id==='bpmOverride'&&state.settings[id]!==null)state.settings[id]=Math.max(40,Math.min(240,state.settings[id]));if(id==='offsetMs')state.settings[id]=Math.max(-2000,Math.min(2000,state.settings[id]||0));settingsChanged(id==='bpmOverride');};
document.querySelectorAll('[data-feature]').forEach(el=>el.onchange=()=>{snapshot();state.settings.enabled[el.dataset.feature]=el.checked;settingsChanged();});$('optionalFog').onchange=()=>{snapshot();state.settings.optionalFog=$('optionalFog').checked;settingsChanged();};$('undo').onclick=()=>undo().catch(e=>toast(e.message,true));if($('redo'))$('redo').onclick=()=>redo().catch(e=>toast(e.message,true));$('resetSettings').onclick=resetStudio;
$('sectionEnergy').oninput=()=>{text($('sectionEnergyValue'),Math.round($('sectionEnergy').value*100)+'%');updateRangeFill($('sectionEnergy'));};$('applySection').onclick=async()=>{if(state.editing===null)return;snapshot();const override={...state.settings.sectionOverrides[state.editing],intensity:Number($('sectionEnergy').value)};delete override.style;if($('sectionStyle').value)override.style=$('sectionStyle').value;state.settings.sectionOverrides[state.editing]=override;await regenerate();toast('Section updated. Play it back to hear the change in context.');};$('closeSection').onclick=()=>{$('sectionEditor').hidden=true;document.querySelectorAll('.section-item').forEach(b=>b.classList.remove('selecting'));};$('resetSections').onclick=()=>{if(!Object.keys(state.settings.sectionOverrides).length)return;snapshot();state.settings.sectionOverrides={};regenerate();$('sectionEditor').hidden=true;toast('Section overrides cleared.');};
$('export').onclick=exportShow;$('shareExport').onclick=()=>bridge('shareExport',String(state.exportId||''));$('exportDone').onclick=()=>$('exportSuccess').hidden=true;$('officialGuide').onclick=()=>{const url='https://github.com/teslamotors/light-show';if(native())bridge('openExternal',url);else window.open(url,'_blank','noopener');};
function updatePreviewLifecycle(){
 const paused=nativePreviewPaused||pagePreviewPaused||document.hidden,changed=paused!==previewPaused;previewPaused=paused;
 // Native focus loss can precede document.hidden. Suspend the renderer before
 // stopping inspection/audio, since their handlers can request another frame.
 vehiclePreview.setPaused?.(paused);
 if(paused){cancelAnimationFrame(frameRequest);frameRequest=0;lastDraw=0;if(changed){stopInspection();audio.pause();clearTimeout(saveTimer);saveProject();}}
 else{if(!frameRequest)frameRequest=requestAnimationFrame(tick);if(changed){lastDraw=0;resizeCanvases();}}
}
window.pausePreview=()=>{nativePreviewPaused=true;updatePreviewLifecycle();};
window.resumePreview=()=>{nativePreviewPaused=false;updatePreviewLifecycle();};
window.addEventListener('resize',resizeCanvases);document.addEventListener('visibilitychange',()=>{updatePreviewLifecycle();if(!document.hidden){pollBackgroundJob();if(backgroundSupported())renderDeviceCapabilities(parse(bridge('getDeviceCapabilities'),null));}});window.addEventListener('pagehide',()=>{pagePreviewPaused=true;updatePreviewLifecycle();});window.addEventListener('pageshow',()=>{pagePreviewPaused=false;updatePreviewLifecycle();});
async function resumePendingExport(){if(state.busy)return;state.acceptProgress=true;beginBusy('Saving your prepared show','Choose where to save your recovered ZIP.');bridge('resumePendingExport');}
async function restorePreviousProject(id=state.project?.id){if(!native()||state.busy)return;state.acceptProgress=true;beginBusy('Restoring the previous save','Recovering your last saved arrangement.');bridge('restorePreviousProject',id);}
async function discardPendingExport(){bridge('discardPendingExport');state.pendingExport=null;updateButtons();}
$('restoreBackup').hidden=!native();readBootstrap();updatePlay();updatePreviewLifecycle();window.LightForgeApp={state,setAudition,refreshAuditionAvailability,selectProject,generate,regenerate,nav,exportShow,zipStored,renderFrame,drawWave,readBootstrap,vehiclePreview,commitChannelSettings,startInspection,stopInspection,toast,captureSnapshot,restoreSnapshot,undo,redo,editSection,saveProject,projectJson,renderProjects,resumePendingExport,discardPendingExport,restorePreviousProject};

if($('backgroundContinue'))$('backgroundContinue').onclick=()=>bridge('continueInBackground');
if($('backgroundNotifications'))$('backgroundNotifications').onclick=()=>bridge('openBackgroundSettings','notifications');
if($('backgroundBattery'))$('backgroundBattery').onclick=()=>bridge('openBackgroundSettings','power');
if($('backgroundPower'))$('backgroundPower').onclick=()=>bridge('openBackgroundSettings','power');
if($('backgroundRetry'))$('backgroundRetry').onclick=async()=>{const job=state.backgroundJob;const project=state.projects.find(p=>p.id===job?.projectId);if(project){await selectProject(project,false);await generate();}};
if($('backgroundDismiss'))$('backgroundDismiss').onclick=()=>{$('backgroundRecovery').hidden=true;};
if(backgroundSupported())setInterval(pollBackgroundJob,2000);

})();
