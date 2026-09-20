/* A service-owned document runs the same production workers without the studio UI. */
(function(root){'use strict';
 const controller=new AbortController(),id=new URL(location.href).searchParams.get('job');
 let started=false;
 root.BackgroundAnalysis={cancel(){root.LightForgeDiagnostics?.log('info','background','Cancel received');controller.abort();}};
 const check=()=>{if(controller.signal.aborted)throw new DOMException('Analysis cancelled','AbortError');};
 const PLAYBACK_SAMPLE_RATE=44100,ANALYSIS_SAMPLE_RATE=22050,FRAME_EPSILON=1e-9,SECTION_EPSILON=1e-7;
 const finite=value=>typeof value==='number'&&Number.isFinite(value);
 const close=(left,right,epsilon=FRAME_EPSILON)=>Math.abs(left-right)<=epsilon;
 const normalizeRefreshEpoch=value=>typeof value==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(value)?value.toLowerCase():null;
 const validRefreshEpoch=value=>normalizeRefreshEpoch(value)!==null;
 const own=(value,key)=>!!value&&Object.prototype.hasOwnProperty.call(value,key);
 function analysisExecutionContract(request){
  const hasMode=own(request,'analysisExecutionMode'),hasEpoch=own(request,'analysisRefreshEpoch'),mode=request?.analysisExecutionMode,epoch=normalizeRefreshEpoch(request?.analysisRefreshEpoch);
  // Legacy frozen requests had neither field and use the ordinary namespace.
  if(!hasMode&&!hasEpoch)return {mode:'resume',refreshEpoch:null};
  if(mode==='resume'&&!hasEpoch)return {mode:'resume',refreshEpoch:null};
  if(mode==='fresh'&&hasEpoch&&epoch)return {mode:'fresh',refreshEpoch:epoch};
  return null;
 }
 function cacheIdentityProbe(music,quality,forceWasm=false){
  const saved=music?.engine?.cacheIdentity;
  if(!saved||saved.schemaVersion!==1||saved.persistent!==true||saved.verified!==true)return null;
  const savedEpoch=saved.refreshEpoch===null||saved.refreshEpoch===undefined?null:normalizeRefreshEpoch(saved.refreshEpoch);
  if(saved.refreshEpoch!==null&&saved.refreshEpoch!==undefined&&!savedEpoch)return null;
  const profile=saved.nativeRuntimeProfile,execution=saved.execution;
  const wasm=execution==='wasm-v1'&&profile==='wasm';
  const studio=quality==='precision'&&execution==='native-deux-v1'&&profile===root.LightForgeNativeDeux?.analysisCacheProfile;
  const balanced=quality==='balanced'&&execution==='native-mdx-v1'&&profile===root.LightForgeNativeMdx?.analysisCacheProfile;
  const gameProfile=root.LightForgeNativeGame?.analysisCacheProfile;
  const game=!!gameProfile&&execution==='native-game-v1'&&profile===gameProfile;
  const studioGame=!!gameProfile&&quality==='precision'&&execution==='native-deux-v1+native-game-v1'&&profile===root.LightForgeNativeDeux?.analysisCacheProfile+'+'+gameProfile;
  const balancedGame=!!gameProfile&&quality==='balanced'&&execution==='native-mdx-v1+native-game-v1'&&profile===root.LightForgeNativeMdx?.analysisCacheProfile+'+'+gameProfile;
  // A persisted native failure is an execution fence, not a performance hint:
  // its next result must be derived solely from the WASM namespace. Never
  // admit an old native completed identity after that fence survived a process
  // death.
  if(forceWasm&&!wasm)return null;
  if(!wasm&&!studio&&!balanced&&!game&&!studioGame&&!balancedGame)return null;
  return {cacheIdentityQuery:true,cacheIdentityExecution:execution,cacheIdentityNativeRuntimeProfile:profile,...(savedEpoch?{cacheIdentityRefreshEpoch:savedEpoch}:{})};
 }
 function currentAnalysisCache(music,expected,forceWasm=false){
  const saved=music?.engine?.cacheIdentity;
  return !!music&&!!expected&&expected.persistent===true&&expected.verified===true&&(music.analysisVersion||0)>=8
   &&saved?.schemaVersion===1&&saved.persistent===true&&saved.verified===true&&saved.workId===expected.workId
   &&(!forceWasm||(saved.execution==='wasm-v1'&&expected.execution==='wasm-v1'))
   &&saved.execution===expected.execution&&saved.implementationFingerprint===expected.implementationFingerprint
   &&saved.assetFingerprint===expected.assetFingerprint&&saved.nativeRuntimeProfile===expected.nativeRuntimeProfile
   &&(saved.refreshEpoch??null)===(expected.refreshEpoch??null);
 }
 function framesFor(duration,sampleRate,label){
  if(!finite(duration)||duration<=0)throw Error(label+' is invalid.');
  const frames=Math.round(duration*sampleRate);
  if(!Number.isSafeInteger(frames)||frames<1||!close(duration,frames/sampleRate))throw Error(label+' is not aligned to its decoded audio clock.');
  return frames;
 }
 function normalizeSections(sections,sourceDuration,duration){
  if(!Array.isArray(sections)||!sections.length)throw Error('Analysis sections are missing during clock reconciliation.');
  let previous=0;const normalized=sections.map((section,index)=>{
   if(!section||typeof section!=='object'||!finite(section.start)||!finite(section.end)||section.start<0||section.end<=section.start||section.end>sourceDuration+SECTION_EPSILON||Math.abs(section.start-previous)>SECTION_EPSILON)throw Error('Analysis sections are not canonical source-clock coverage.');
   const end=index===sections.length-1?duration:section.end;
   if(end<=section.start||end>duration+SECTION_EPSILON)throw Error('Analysis sections cannot be reconciled to the playback clock.');
   previous=end;return {...section,end};
  });
  if(Math.abs(previous-duration)>SECTION_EPSILON)throw Error('Analysis sections do not cover the reconciled playback clock.');
  return normalized;
 }
 function normalizeTimes(values,sourceDuration,duration){
  if(!Array.isArray(values))return values;
  return values.filter(value=>!(finite(value)&&value>duration&&value<=sourceDuration+SECTION_EPSILON));
 }
 function normalizePointObjects(values,sourceDuration,duration){
  if(!Array.isArray(values))return values;
  return values.map(value=>{
   if(!value||typeof value!=='object'||!finite(value.time)||value.time>sourceDuration+SECTION_EPSILON)return value;
   if(value.time>duration){const normalized={...value,time:duration};if(finite(normalized.duration)&&normalized.duration>0)normalized.duration=0;return normalized;}
   if(finite(value.duration)&&value.duration>=0&&value.time+value.duration>duration&&value.time+value.duration<=sourceDuration+SECTION_EPSILON)return {...value,duration:Math.max(0,duration-value.time)};
   return value;
  });
 }
 function normalizeSpanObjects(values,sourceDuration,duration){
  if(!Array.isArray(values))return values;
  return values.map(value=>{
   if(!value||typeof value!=='object'||!finite(value.start)||!finite(value.end)||value.end<=duration||value.end>sourceDuration+SECTION_EPSILON)return value;
   if(value.start>=duration)return null;
   const normalized={...value,end:duration};
   for(const key of ['releaseTime','peakTime'])if(finite(normalized[key])&&normalized[key]>duration)normalized[key]=duration;
   return normalized;
  }).filter(value=>value!==null);
 }
 function requireApi(name,methods){
  const api=root[name];if(!api||methods.some(method=>typeof api[method]!=='function'))throw Error(name+' is unavailable for validated clock reconciliation.');
  return api;
 }
 function requireValid(label,check){
  if(check?.valid===true)return;
  const detail=Array.isArray(check?.errors)?check.errors.join('; '):(check?.reason||'invalid result');
  throw Error(label+' validation failed: '+String(detail).slice(0,512));
 }
 function rebuildCanonicalContracts(music){
  const previousTimeline=music.semanticTimeline,previousEvidence=music.recurrenceEvidence,previousSidecar=music.recurrenceSidecar;
  const timelineApi=requireApi('LightForgeSemanticTimeline',['build','validate']),timeline=timelineApi.build(music);requireValid('Canonical semantic timeline',timelineApi.validate(timeline));
  const salienceApi=requireApi('LightForgeMusicSalience',['build','validate']),salience=salienceApi.build(timeline);requireValid('Canonical music salience',salienceApi.validate(salience,timeline));
  if(timeline.duration!==music.duration||salience.duration!==music.duration)throw Error('Canonical duration reconciliation is inconsistent.');
  music.semanticTimeline=timeline;music.musicSalience=salience;
  if(music.rhythmHierarchy){
   const rhythmApi=requireApi('LightForgeRhythmHierarchy',['attach','validate']),outcome=rhythmApi.attach(music);if(!outcome?.hierarchy)throw Error('Rhythm hierarchy could not be rebound to the playback clock.');requireValid('Rhythm hierarchy',rhythmApi.validate(outcome.hierarchy,music));
  }
  if(music.vocalSemantics||music.vocalSemanticLinks){
   const vocalApi=requireApi('LightForgeVocalSemantics',['build','validate','linkTimeline']),input={duration:music.duration,vocals:music.vocals},sidecar=vocalApi.build(input);requireValid('Vocal semantic sidecar',vocalApi.validate(sidecar,input));
   music.vocalSemantics=sidecar;music.vocalSemanticLinks=vocalApi.linkTimeline(sidecar,timeline);
  }
  if(music.recurrenceAnalysis?.enabled===true||music.recurrenceEvidence||music.recurrenceSidecar){
   const recurrenceApi=requireApi('LightForgeRecurrence',['captureEvidence','validateEvidence','build','validate']);
   const previousValid=recurrenceApi.validateEvidence(previousEvidence,previousTimeline)?.valid===true&&recurrenceApi.validate(previousSidecar,previousTimeline,previousEvidence)?.valid===true;
   const input=previousValid&&Array.isArray(previousEvidence.chroma)?{...music,chroma:previousEvidence.chroma,chromaStep:previousEvidence.chromaStep}:music;
   const evidence=recurrenceApi.captureEvidence(input,timeline);requireValid('Recurrence evidence',recurrenceApi.validateEvidence(evidence,timeline));
   const sidecar=recurrenceApi.build(timeline,evidence);requireValid('Recurrence sidecar',recurrenceApi.validate(sidecar,timeline,evidence));
   music.recurrenceEvidence=evidence;music.recurrenceSidecar=sidecar;music.recurrenceAnalysis={schemaVersion:1,enabled:true,cacheDomain:'recurrence',engineVersion:recurrenceApi.version,sidecarSchemaVersion:sidecar.schemaVersion,clock:sidecar.clock,duration:sidecar.duration,timelineFingerprint:sidecar.timelineFingerprint,evidenceFingerprint:sidecar.evidenceFingerprint};
  }
  return music;
 }
 function reconcileMusicDuration(music,duration){
  const sourceDuration=music?.duration;if(!finite(sourceDuration))throw Error('The decoded analysis duration is invalid.');
  const playbackFrames=framesFor(duration,PLAYBACK_SAMPLE_RATE,'Playback duration'),analysisFrames=framesFor(sourceDuration,ANALYSIS_SAMPLE_RATE,'Decoded analysis duration');
  if(Math.abs(analysisFrames*2-playbackFrames)>1)throw Error('The decoded analysis duration is not the permitted one-sample reconciliation for this project.');
  const vocals=music.vocals&&typeof music.vocals==='object'?{...music.vocals,phrases:normalizeSpanObjects(music.vocals.phrases,sourceDuration,duration),notes:normalizeSpanObjects(music.vocals.notes,sourceDuration,duration),accents:normalizePointObjects(music.vocals.accents,sourceDuration,duration)}:music.vocals;
  const bassAnalysis=music.bassAnalysis&&typeof music.bassAnalysis==='object'?{...music.bassAnalysis,phrases:normalizeSpanObjects(music.bassAnalysis.phrases,sourceDuration,duration)}:music.bassAnalysis;
  const percussionAnalysis=music.percussionAnalysis&&typeof music.percussionAnalysis==='object'?{...music.percussionAnalysis,events:normalizePointObjects(music.percussionAnalysis.events,sourceDuration,duration)}:music.percussionAnalysis;
  const normalized={...music,duration,sections:normalizeSections(music.sections,sourceDuration,duration),phrases:normalizeSpanObjects(music.phrases,sourceDuration,duration),beats:normalizeTimes(music.beats,sourceDuration,duration),downbeats:normalizeTimes(music.downbeats,sourceDuration,duration),beatDetails:normalizePointObjects(music.beatDetails,sourceDuration,duration),impacts:normalizePointObjects(music.impacts,sourceDuration,duration),onsets:normalizePointObjects(music.onsets,sourceDuration,duration),bassNotes:normalizeSpanObjects(music.bassNotes,sourceDuration,duration),vocals,bassAnalysis,percussionAnalysis};
  return Number(normalized.analysisVersion)===8?rebuildCanonicalContracts(normalized):normalized;
 }

 const observationClock=()=>{try{const factory=root.LightForgeDiagnosticClock;return factory&&typeof factory.create==='function'?factory.create(root):null;}catch(_){return null;}};
 const observationMark=clock=>{try{return clock&&typeof clock.mark==='function'?clock.mark():null;}catch(_){return null;}};
 const observationMeasure=(clock,mark)=>{try{return clock&&typeof clock.measure==='function'?clock.measure(mark):null;}catch(_){return null;}};
 const report=(progress,detail,info={})=>{
  root.LightForgeDiagnostics?.progress('background',{...info,progress});
  if(typeof BackgroundJob.progressInfo==='function')BackgroundJob.progressInfo(id,progress,detail,JSON.stringify(info));
  else BackgroundJob.progress(id,progress,detail);
 };
 async function run(){
  if(started)return;started=true;root.LightForgeDiagnostics?.log('info','background','Runner started');
  const clock=observationClock(),totalStarted=observationMark(clock);let analysisTiming=null,analysisPerformed=false;
  try{
   const response=await fetch('/background/request.json',{cache:'no-store',signal:controller.signal});
   if(!response.ok)throw Error('The saved analysis request could not be opened.');
   const request=await response.json();root.LightForgeDiagnostics?.protectText(request.name);const settings=request.settings||{},projectId=request.projectId;
   if(!/^[A-Za-z0-9_-]{1,80}$/.test(projectId))throw Error('Invalid analysis project.');
   // Incomplete stem namespaces can belong to an interrupted or another-tab
   // analysis. Their exact owner fences/aborts them; age-based pruning reclaims
   // abandoned data without deleting a live job during background startup.
   const base='/project/'+encodeURIComponent(projectId)+'/';
   let music=request.music,compatibility=false;
   const quality=settings.analysisQuality==='balanced'?'balanced':'precision',needsAnalysis=request.needAnalysis!==false;
   const executionContract=analysisExecutionContract(request),hasEffectiveExecution=own(request,'analysisEffectiveExecution'),forceWasm=request.analysisEffectiveExecution==='wasm-v1';
   if(!executionContract)throw Error('The frozen analysis execution contract is invalid. Start a fresh analysis again.');
   if(hasEffectiveExecution&&!forceWasm)throw Error('The frozen effective analysis runtime is invalid. Start a fresh analysis again.');
   const fallbackReason=request.analysisNativeFallbackReason;
   const legacyAttempt=fallbackReason==='native-deux-fallback'?'native-deux-v1':fallbackReason==='native-mdx-fallback'?'native-mdx-v1':null;
   const attemptedExecution=request.analysisNativeAttemptedExecution??legacyAttempt;
   const validAttempt=typeof attemptedExecution==='string'&&['native-deux-v1','native-mdx-v1','native-game-v1','native-deux-v1+native-game-v1','native-mdx-v1+native-game-v1'].includes(attemptedExecution)
    &&(!attemptedExecution.includes('native-deux-v1')||quality==='precision')&&(!attemptedExecution.includes('native-mdx-v1')||quality==='balanced')
    &&((fallbackReason==='native-game-fallback'&&attemptedExecution.includes('native-game-v1'))||(fallbackReason==='native-deux-fallback'&&attemptedExecution.includes('native-deux-v1'))||(fallbackReason==='native-mdx-fallback'&&attemptedExecution.includes('native-mdx-v1')));
   if(forceWasm&&!validAttempt)throw Error('The persisted native fallback lineage is invalid. Start a fresh analysis again.');
   const baseAnalysisOptions={projectId,analysisIdentity:request.analysisIdentity,analysisUrl:new URL(base+'analysis.wav',location.href).href,sensitivity:settings.sensitivity,
    bpmOverride:settings.bpmOverride||undefined,analysisQuality:settings.analysisQuality,
    vocalSemanticEnrichment:settings.vocalSemanticEnrichment===true,recurrenceAnalysis:settings.recurrenceAnalysis===true};
   let expectedCacheIdentity=null;
   if(!needsAnalysis&&typeof MusicAnalyzer.cacheIdentity==='function'){
    // This probe reconstructs only a fully validated completed identity. Its
    // saved epoch is never copied into a rebuild request. A frozen fresh
    // lineage may reuse only its exact trusted epoch; ordinary resume may
    // inspect a completed fresh identity but never inherits it on a miss.
    const probe=cacheIdentityProbe(music,quality,forceWasm),savedEpoch=music?.engine?.cacheIdentity?.refreshEpoch;
    const freshEpochMatches=executionContract.mode!=='fresh'||(normalizeRefreshEpoch(savedEpoch)===executionContract.refreshEpoch);
    if(probe&&freshEpochMatches)try{const probeOptions={...baseAnalysisOptions,...probe};expectedCacheIdentity=await MusicAnalyzer.cacheIdentity(probeOptions,controller.signal);}
    catch(error){if(error?.name==='AbortError')throw error;root.LightForgeDiagnostics?.log('error','analysis-cache-identity',error);}
   }
   if(needsAnalysis||!currentAnalysisCache(music,expectedCacheIdentity,forceWasm)){
    if(music&&!needsAnalysis)root.LightForgeDiagnostics?.log('info','analysis-cache-identity','Completed music analysis cache identity changed; rebuilding evidence.');
    if(typeof BackgroundJob.clearRunObservation!=='function'||BackgroundJob.clearRunObservation(id)!==true)throw Error('The prior analysis observation could not be cleared.');
    let nativePredict,nativeMdx,nativeGame;
    if(forceWasm){
     compatibility=true;
     report(0,'Resuming the verified WebAssembly retry after native separation fallback.',{stage:'compatibility'});
    }else try{
     if(quality==='precision')nativePredict=root.LightForgeNativeDeux?.create(BackgroundJob,id,message=>{compatibility=true;report(0,message,{stage:'compatibility'});});
     else nativeMdx=root.LightForgeNativeMdx?.create(BackgroundJob,id,message=>{compatibility=true;report(0,message,{stage:'compatibility'});});
     nativeGame=root.LightForgeNativeGame?.create(BackgroundJob,id,message=>{compatibility=true;report(0,message,{stage:'compatibility'});});
     for(const [predictor,api] of [[nativePredict,root.LightForgeNativeDeux],[nativeMdx,root.LightForgeNativeMdx],[nativeGame,root.LightForgeNativeGame]]){
      if(typeof predictor==='function'&&(typeof api?.analysisCacheProfile!=='string'||!/^[A-Za-z0-9._:-]{1,80}$/.test(api.analysisCacheProfile)||predictor.analysisCacheProfile!==api.analysisCacheProfile))throw Error('The native execution profile could not be verified.');
     }
    }catch(error){
     // A bridge availability query is an optimization only. A failed query may
     // never block a verified cached result or silently alter its identity.
     compatibility=true;nativePredict=undefined;nativeMdx=undefined;nativeGame=undefined;
     root.LightForgeDiagnostics?.log('warn','analysis-native-compatibility',error);
     report(0,'Native acceleration is unavailable; using verified WebAssembly.',{stage:'compatibility'});
    }
    // Only a predictor that was actually admitted may label the run native.
    // Compatibility fallbacks therefore retain the wasm cache namespace.
    const nativeRuntimeProfile=[typeof nativePredict==='function'?nativePredict.analysisCacheProfile:typeof nativeMdx==='function'?nativeMdx.analysisCacheProfile:null,typeof nativeGame==='function'?nativeGame.analysisCacheProfile:null].filter(Boolean).join('+')||undefined;
    // Use only the trusted frozen contract. A saved completed epoch is valid
    // for a probe, never as an implicit rebuild namespace.
    const persistNativeFallback=async fallback=>{
     const reason=fallback?.reason;
     if(typeof BackgroundJob.markAnalysisWasmFallbackWithExecution==='function'){
      if(BackgroundJob.markAnalysisWasmFallbackWithExecution(id,reason,fallback.attemptedExecution)!==true)throw Error('The native fallback execution checkpoint could not be persisted safely.');
      return true;
     }
     if(fallback?.attemptedExecution?.includes('native-game-v1'))throw Error('The native singing fallback execution checkpoint is unavailable.');
     if(typeof BackgroundJob.markAnalysisWasmFallback!=='function'||BackgroundJob.markAnalysisWasmFallback(id,reason)!==true)throw Error('The native fallback checkpoint could not be persisted safely.');
     return true;
    };
    const analysisOptions={...baseAnalysisOptions,nativePredict,nativeMdx,nativeGame,nativeRuntimeProfile,...(executionContract.refreshEpoch?{analysisRefreshEpoch:executionContract.refreshEpoch}:{}),...(forceWasm?{analysisNativeFallback:{attemptedExecution,reason:fallbackReason}}:{}),...((typeof nativePredict==='function'||typeof nativeMdx==='function'||typeof nativeGame==='function')?{onNativeFallback:persistNativeFallback}:{})};
    analysisPerformed=true;const analysisStarted=observationMark(clock);
    music=await MusicAnalyzer.analyze(new URL(base+'audio.wav',location.href).href,analysisOptions,p=>report(.96*Math.max(0,Math.min(1,Number(p.progress)||0)),(compatibility?'Compatibility · ':'')+(p.detail||p.message||p.stage||'Analyzing music'),p),controller.signal);
    analysisTiming=observationMeasure(clock,analysisStarted);
   }
   check();const duration=Number(request.duration);
   if(Number.isFinite(duration)&&duration>0&&music.duration!==duration)music=reconcileMusicDuration(music,duration);
   if(!BackgroundJob.checkpoint(id,JSON.stringify(music)))throw Error('The analysis checkpoint could not be saved.');
   check();
   const choreographyStarted=observationMark(clock);
   const result=await ShowCompiler.generate(music,settings,p=>report(.96+.035*Math.max(0,Math.min(1,Number(p.progress)||0)),p.detail||'Choreographing your show',{stage:'generate'}),controller.signal);
   const choreographyTiming=observationMeasure(clock,choreographyStarted),totalTiming=observationMeasure(clock,totalStarted);
   let analysisRunObservation=null;try{analysisRunObservation=root.LightForgeAnalysisRunObservation?.completed({analysisPerformed,engine:music.engine,analysisTiming,choreographyTiming,totalTiming});}catch(_){analysisRunObservation=null;}
   check();report(.999,'Saving your complete show',{stage:'save'});
   const saved={version:1,projectId,name:request.name,updatedAt:Date.now(),settings,music,needAnalysis:false,compiled:result.compiled,
    provenance:{app:LightForgeVersion.name,planner:result.show.version,profile:VehicleProfile.version,analysis:music.analysisVersion,model:music.engine,frameSHA256:result.compiled.sha256}};
   if(analysisRunObservation) saved.analysisRunObservation=analysisRunObservation;
   if(!BackgroundJob.complete(id,JSON.stringify(saved)))throw Error('Your completed show could not be saved.');
   root.LightForgeDiagnostics?.log('info','background','Completed show committed');
  }catch(error){root.LightForgeDiagnostics?.log(error.name==='AbortError'?'info':'error','background',error);BackgroundJob.failed(id,error.message||'Analysis could not finish.',error.name==='AbortError');}
 }
 run();
})(window);
