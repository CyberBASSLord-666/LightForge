/* Private worker: bounded PCM chunks -> exact log-mel -> pretrained Beat This! transformer. */
'use strict';
importScripts('diagnostic-clock.js','resource-diagnostics.js','telemetry.js','semantic-timeline.js','stem-routing.js','salience.js','rhythm-hierarchy.js','wav-reader.js','dsp.js','bass-notes.js','vocal.js','vocal-detail.js','vocal-semantics.js','stem-cache.js','work-store.js','feature-store.js','separator-mdx.js','separator-deux.js','game.js','vendor/ort.wasm.min.js');
const report=(progress,stage,detail='',extra={})=>postMessage({type:'progress',value:{...extra,progress,stage,detail}});
function createTelemetry(stage,metadata){
 const factory=self.LightForgeAnalysisTelemetry;
 if(factory&&typeof factory.create==='function')try{
  const telemetry=factory.create(stage,metadata);
  if(telemetry&&typeof telemetry.begin==='function'&&typeof telemetry.end==='function'&&typeof telemetry.cache==='function'&&typeof telemetry.snapshot==='function')return telemetry;
 }catch(_){}
 // Profiling must never make a resumable analysis fail when a test harness,
 // older WebView cache, or constrained worker cannot load its optional module.
 return {begin:()=>null,end:()=>{},cache:()=>{},resource:null,snapshot:()=>null};
}
function createDiagnosticClock(){
 let factory;try{factory=self.LightForgeDiagnosticClock;}catch(_){factory=null;}
 if(factory&&typeof factory.create==='function')try{
  const clock=factory.create(self);
  if(clock&&typeof clock.mark==='function'&&typeof clock.measure==='function')return clock;
 }catch(_){ }
 return {mark:()=>({milliseconds:0,source:'unavailable'}),measure:()=>({milliseconds:0,measured:false,status:'unavailable',reason:'clock-unavailable',source:'unavailable'})};
}
function fullResolutionStemClock(stemCache){
 const samples=stemCache?.fullSamples,duration=stemCache?.duration;
 // The verified full-resolution vocal cache is bound to this original sample
 // clock. It intentionally never uses elapsed-time telemetry.
 if(!Number.isSafeInteger(samples)||!Number.isFinite(duration)||Math.abs(samples/44100-duration)>1/44100)throw Error('Re-analyze to recover full-resolution voice audio.');
 return {samples,duration:samples/44100};
}
function safeValidation(api,value,context){
 // Checkpoints are persisted independently from the worker script. Treat a
 // validator exception as corrupt/stale evidence so analysis can rebuild.
 try{return api&&typeof api.validate==='function'?api.validate(value,context):null;}catch(_){return null;}
}
function ensureSemanticTimeline(result){
 const api=self.LightForgeSemanticTimeline;
 if(!api||typeof api.build!=='function'||typeof api.validate!=='function')throw Error('Semantic timeline module is unavailable.');
 if(result&&result.semanticTimeline){
  const existing=safeValidation(api,result.semanticTimeline);
  if(existing&&existing.valid)return result.semanticTimeline;
 }
 const timeline=api.build(result),check=safeValidation(api,timeline);
 if(!check||!check.valid)throw Error('Semantic timeline validation failed: '+(check?.errors||[]).join('; ').slice(0,512));
 result.semanticTimeline=timeline;
 return timeline;
}
function ensureStemRouting(result){
 const api=self.LightForgeStemRouting;
 if(!api||typeof api.ensureAnalysis!=='function'||typeof api.validate!=='function')throw Error('Stem-routing module is unavailable.');
 const attached=api.ensureAnalysis(result),routing=attached?.routing,check=api.validate(routing);
 if(!check||!check.valid)throw Error('Stem-routing validation failed: '+(check?.errors||[]).join('; ').slice(0,512));
 return {routing,rebuilt:attached.rebuilt===true};
}
function ensureMusicSalience(result,timeline){
 const api=self.LightForgeMusicSalience;
 if(!api||typeof api.build!=='function'||typeof api.validate!=='function')throw Error('Music salience module is unavailable.');
 const semanticTimeline=timeline||ensureSemanticTimeline(result);
 if(result&&result.musicSalience){
  const existing=safeValidation(api,result.musicSalience,semanticTimeline);
  if(existing&&existing.valid)return result.musicSalience;
 }
 const musicSalience=api.build(semanticTimeline),check=safeValidation(api,musicSalience,semanticTimeline);
 if(!check||!check.valid)throw Error('Music salience validation failed: '+(check?.errors||[]).join('; ').slice(0,512));
 result.musicSalience=musicSalience;
 return musicSalience;
}
function recurrenceAnalysisEnabled(options){return options?.recurrenceAnalysis===true;}
function clearRecurrenceAnalysis(result){
 if(!result)return;
 delete result.recurrenceAnalysis;
 delete result.recurrenceEvidence;
 delete result.recurrenceSidecar;
}
function recurrenceMarker(api,evidence,sidecar){
 return {schemaVersion:1,enabled:true,cacheDomain:'recurrence',engineVersion:api.version,sidecarSchemaVersion:sidecar.schemaVersion,
  clock:sidecar.clock,duration:sidecar.duration,timelineFingerprint:sidecar.timelineFingerprint,evidenceFingerprint:sidecar.evidenceFingerprint};
}
function recurrenceCacheValid(record,timeline,currentEvidence,api){
 try{
  if(!record||record.schemaVersion!==1||record.kind!=='recurrence-analysis-cache'||record.engineVersion!==api.version||typeof record.timelineFingerprint!=='string'||typeof record.evidenceFingerprint!=='string'||!record.evidence||!record.sidecar)return false;
  const currentEvidenceCheck=api.validateEvidence(currentEvidence,timeline);
  if(!currentEvidenceCheck?.valid)return false;
  const evidenceCheck=api.validateEvidence(record.evidence,timeline);
  if(!evidenceCheck?.valid)return false;
  const sidecarCheck=api.validate(record.sidecar,timeline,record.evidence);
  return !!sidecarCheck?.valid&&record.timelineFingerprint===record.sidecar.timelineFingerprint&&record.evidenceFingerprint===record.sidecar.evidenceFingerprint&&record.timelineFingerprint===api.timelineFingerprint(timeline)&&record.evidenceFingerprint===api.evidenceFingerprint(record.evidence)&&record.evidenceFingerprint===api.evidenceFingerprint(currentEvidence);
 }catch(_){return false;}
}
function attachRecurrenceAnalysis(result,api,evidence,sidecar){
 result.recurrenceEvidence=evidence;
 result.recurrenceSidecar=sidecar;
 result.recurrenceAnalysis=recurrenceMarker(api,evidence,sidecar);
 return result.recurrenceAnalysis;
}
async function ensureRecurrenceAnalysis(result,options,store,telemetry,featureConfig){
 if(!recurrenceAnalysisEnabled(options)){
  clearRecurrenceAnalysis(result);
  return {enabled:false,restored:false,sidecar:null};
 }
 const api=self.LightForgeRecurrence;
 if(!api||typeof api.captureEvidence!=='function'||typeof api.validateEvidence!=='function'||typeof api.evidenceFingerprint!=='function'||typeof api.timelineFingerprint!=='function'||typeof api.build!=='function'||typeof api.validate!=='function')throw Error('Recurrence analysis module is unavailable.');
 clearRecurrenceAnalysis(result);
 const timeline=ensureSemanticTimeline(result);
 const evidenceInput=await recurrenceEvidenceInput(result,options,featureConfig,telemetry);
 const evidence=api.captureEvidence(evidenceInput,timeline),evidenceCheck=api.validateEvidence(evidence,timeline);
 if(!evidenceCheck?.valid)throw Error('Recurrence evidence validation failed: '+(evidenceCheck?.errors||[]).join('; ').slice(0,512));
 let cached=null;
 try{cached=await store.read('recurrence');}catch(_){telemetry.cache('recurrence','corrupt');}
 if(cached&&recurrenceCacheValid(cached,timeline,evidence,api)){
  attachRecurrenceAnalysis(result,api,cached.evidence,cached.sidecar);
  telemetry.cache('recurrence','restore');
  return {enabled:true,restored:true,sidecar:cached.sidecar};
 }
 if(cached){
  telemetry.cache('recurrence','invalidate');
  try{await store.invalidate(['recurrence']);}catch(_){ }
 }
 telemetry.cache('recurrence','miss');
 // captureEvidence has a strict whitelist: canonical section spans plus the
 // existing normalized energy/chroma features. It cannot promote labels or
 // create events from stems, lyrics, or raw PCM.
 const sidecar=api.build(timeline,evidence),sidecarCheck=api.validate(sidecar,timeline,evidence);
 if(!sidecarCheck?.valid)throw Error('Recurrence sidecar validation failed: '+(sidecarCheck?.errors||[]).join('; ').slice(0,512));
 const record={schemaVersion:1,kind:'recurrence-analysis-cache',engineVersion:api.version,timelineFingerprint:sidecar.timelineFingerprint,evidenceFingerprint:sidecar.evidenceFingerprint,evidence,sidecar};
 await store.write('recurrence',record);
 attachRecurrenceAnalysis(result,api,evidence,sidecar);
 telemetry.cache('recurrence','write');
 return {enabled:true,restored:false,sidecar};
}
function vocalSemanticsEnabled(options){return options?.vocalSemanticEnrichment===true;}
function persistableAnalysis(result){
 const {vocalSemantics,vocalSemanticLinks,recurrenceAnalysis,recurrenceEvidence,recurrenceSidecar,...persisted}=result||{};
 return persisted;
}
async function ensureVocalSemantics(result,options,store,telemetry){
 if(!vocalSemanticsEnabled(options)){
  if(result){delete result.vocalSemantics;delete result.vocalSemanticLinks;}
  return null;
 }
 const api=self.LightForgeVocalSemantics;
 if(!api||typeof api.build!=='function'||typeof api.validate!=='function'||typeof api.linkTimeline!=='function')throw Error('Vocal semantic enrichment module is unavailable.');
 if(!result?.vocals||!Number.isFinite(result.duration)||result.duration<=0)throw Error('Vocal semantic enrichment requires completed vocal analysis on the original audio clock.');
 delete result.vocalSemanticLinks;
 const input={duration:result.duration,vocals:result.vocals},phase=telemetry.begin('vocal.semantics');
 let cached=null;
 try{cached=await store.read('vocal-semantics');}catch(_){telemetry.cache('vocal-semantics','corrupt');}
 if(cached){
  const check=safeValidation(api,cached,input);
  if(check?.valid){result.vocalSemantics=cached;telemetry.cache('vocal-semantics','restore');telemetry.end(phase,{restored:true,phraseCount:cached.summary.phraseCount,articulationCount:cached.summary.articulationCount});return cached;}
  if(!check)telemetry.cache('vocal-semantics','corrupt');
  telemetry.cache('vocal-semantics','invalidate');
  try{await store.invalidate(['vocal-semantics']);}catch(_){}
 }
 telemetry.cache('vocal-semantics','miss');
 const sidecar=api.build(input),check=safeValidation(api,sidecar,input);
 if(!check?.valid)throw Error('Vocal semantic enrichment validation failed: '+(check?.errors||[]).join('; ').slice(0,512));
 await store.write('vocal-semantics',sidecar);
 result.vocalSemantics=sidecar;
 telemetry.end(phase,{restored:false,phraseCount:sidecar.summary.phraseCount,articulationCount:sidecar.summary.articulationCount});
 return sidecar;
}
function linkVocalSemantics(result){
 if(!result?.vocalSemantics){if(result)delete result.vocalSemanticLinks;return null;}
 const api=self.LightForgeVocalSemantics,input={duration:result.duration,vocals:result.vocals},check=safeValidation(api,result.vocalSemantics,input);
 if(!check?.valid)throw Error('Vocal semantic enrichment no longer matches vocal analysis.');
 const link=api.linkTimeline(result.vocalSemantics,result.semanticTimeline);
 result.vocalSemanticLinks=link;
 return link;
}
function ensureRhythmHierarchy(result,options={}){
 if(options?.rhythmHierarchy!==true)return {enabled:false,attached:false,reused:false};
 const api=self.LightForgeRhythmHierarchy;
 if(!api||typeof api.attach!=='function'||typeof api.validate!=='function')throw Error('Rhythm hierarchy module is unavailable.');
 const outcome=api.attach(result);
 if(!outcome?.hierarchy)throw Error('Rhythm hierarchy rejected unvalidated rhythm evidence.');
 const check=api.validate(outcome.hierarchy,result);
 if(!check||!check.valid)throw Error('Rhythm hierarchy validation failed: '+(check?.reason||'unknown'));
 return {enabled:true,attached:outcome.attached===true,reused:outcome.reused===true,hierarchy:outcome.hierarchy};
}
function normalizeBassProvenance(result){
 const analysis=result?.bassAnalysis;
 if(!analysis||typeof analysis!=='object')return false;
 // Earlier releases conflated a vocal-separated accompaniment mixture with an
 // isolated bass stem. Keep that context, but never promote it to bass isolation.
 const legacy=analysis.source==='separated-accompaniment'&&analysis.sourceSeparated===true&&analysis.instrumentSeparated===undefined;
 const inputStem=analysis.inputStem==='bass'?'bass':analysis.inputStem==='accompaniment'||legacy?'accompaniment':(analysis.inputStem||'mixture');
 const inputStemSeparated=analysis.inputStemSeparated===true||legacy;
 const instrumentSeparated=analysis.instrumentSeparated===true;
 const source=instrumentSeparated?'isolated-bass-stem':inputStem==='accompaniment'?'accompaniment-mixture-estimate':(analysis.source||'mixture-estimate');
 const limitation=inputStem==='accompaniment'?'Bass notes are estimated from a vocal-separated accompaniment mixture, not an isolated bass stem.':null;
 const oldLimitations=Array.isArray(analysis.limitations)?analysis.limitations:[];
 const limitations=limitation&&!oldLimitations.includes(limitation)?[...oldLimitations,limitation]:oldLimitations;
 const tag=value=>value&&typeof value==='object'?{...value,source,inputStem,inputStemSeparated,instrumentSeparated,sourceSeparated:instrumentSeparated,estimated:value.estimated!==false}:value;
 const noteChanged=Array.isArray(result.bassNotes)&&result.bassNotes.some(value=>value&&typeof value==='object'&&(value.source!==source||value.inputStem!==inputStem||value.inputStemSeparated!==inputStemSeparated||value.instrumentSeparated!==instrumentSeparated||value.sourceSeparated!==instrumentSeparated||value.estimated===undefined));
 const phraseChanged=Array.isArray(analysis.phrases)&&analysis.phrases.some(value=>value&&typeof value==='object'&&(value.source!==source||value.inputStem!==inputStem||value.inputStemSeparated!==inputStemSeparated||value.instrumentSeparated!==instrumentSeparated||value.sourceSeparated!==instrumentSeparated||value.estimated===undefined));
 const role=result?.roleAnalysis,roleBassSource=inputStem==='accompaniment'?'Low-register harmonics in a vocal-separated accompaniment mixture; not an isolated bass stem.':role?.bassSource;
 const roleChanged=!!role&&(Number(role.version||0)<5||role.bassSource!==roleBassSource||role.bassInputStem!==inputStem||role.accompanimentStemSeparated!==(inputStem==='accompaniment'&&inputStemSeparated)||role.bassInstrumentSeparated!==instrumentSeparated);
 const changed=legacy||analysis.source!==source||analysis.inputStem!==inputStem||analysis.inputStemSeparated!==inputStemSeparated||analysis.instrumentSeparated!==instrumentSeparated||analysis.sourceSeparated!==instrumentSeparated||analysis.estimated===undefined||limitations!==oldLimitations||noteChanged||phraseChanged||roleChanged;
 result.bassAnalysis={...analysis,source,inputStem,inputStemSeparated,instrumentSeparated,sourceSeparated:instrumentSeparated,estimated:analysis.estimated!==false,limitations,phrases:Array.isArray(analysis.phrases)?analysis.phrases.map(tag):analysis.phrases};
 if(Array.isArray(result.bassNotes))result.bassNotes=result.bassNotes.map(tag);
 if(roleChanged)result.roleAnalysis={...role,version:Math.max(5,Number(role.version||0)),bassSource:roleBassSource,bassInputStem:inputStem,accompanimentStemSeparated:inputStem==='accompaniment'&&inputStemSeparated,bassInstrumentSeparated:instrumentSeparated};
 if(changed&&Number(result.analysisVersion||0)<8)result.analysisVersion=8;
 return changed;
}
let nativeSequence=0;const nativeRequests=new Map();
let nativeMdxSequence=0;const nativeMdxRequests=new Map();
const NATIVE_DEUX_FALLBACK_CODE='native-deux-fallback',NATIVE_MDX_FALLBACK_CODE='native-mdx-fallback';
function nativeFallbackError(code){const error=new Error('Native separation requested a verified WASM restart.');error.code=code;return error;}
function nativeDeuxFallbackError(){return nativeFallbackError(NATIVE_DEUX_FALLBACK_CODE);}
function nativeMdxFallbackError(){return nativeFallbackError(NATIVE_MDX_FALLBACK_CODE);}
function nativeAbortError(message){try{return new DOMException(message||'Analysis cancelled','AbortError');}catch(_){const error=new Error(message||'Analysis cancelled');error.name='AbortError';return error;}}
async function normalizeNativeFailure(error,onFallback,fallback){
 if(error?.name==='AbortError')throw error;
 if(error?.code===fallback().code)throw error;
 await onFallback();throw fallback();
}
function nativePredict(startSample,onProgress=()=>{},onFallback=()=>{}){return new Promise((resolve,reject)=>{const requestId=++nativeSequence;nativeRequests.set(requestId,{resolve,reject,onProgress,onFallback});try{postMessage({type:'native-deux',requestId,startSample});}catch(error){nativeRequests.delete(requestId);reject(error);}}).then(async url=>{
 if(typeof url!=='string')throw Error('Native studio audio is unavailable.');
 const response=await fetch(url);if(!response.ok)throw Error('Native studio audio could not be read.');const bytes=await response.arrayBuffer(),samples=573300;
 if(bytes.byteLength!==samples*8)throw Error('Native studio audio is incomplete.');const view=new DataView(bytes),result={};let at=0;
 for(const role of ['vocals','accompaniment']){const pcm=new Float32Array(samples);for(let i=0;i<samples;i++,at+=4){pcm[i]=view.getFloat32(at,true);if(!Number.isFinite(pcm[i]))throw Error('Native studio audio contains invalid samples.');}result[role]=pcm;}return result;
}).catch(error=>normalizeNativeFailure(error,onFallback,nativeDeuxFallbackError));}
function nativeMdxPredict(encoded,onProgress=()=>{},onFallback=()=>{}){
 const payload=encoded.slice();
 return new Promise((resolve,reject)=>{const requestId=++nativeMdxSequence,expectedBytes=payload.byteLength;nativeMdxRequests.set(requestId,{resolve,reject,onProgress,onFallback,expectedBytes});try{postMessage({type:'native-mdx',requestId,buffer:payload.buffer},[payload.buffer]);}catch(error){nativeMdxRequests.delete(requestId);reject(error);}}).catch(error=>normalizeNativeFailure(error,onFallback,nativeMdxFallbackError));
}
function separationStoragePlan(total,quality){
 const samples=quality==='precision'?573300:LightForgeMdxSeparator.constants.INPUT_LENGTH;
 const core=quality==='precision'?441000:LightForgeMdxSeparator.constants.CORE,stride=quality==='precision'?220500:LightForgeMdxSeparator.constants.STRIDE;
 const passages=[];
 for(let start=0;start<total;start+=stride){passages.push({name:(quality==='precision'?'deux-':'mdx-ensemble-')+start,counts:quality==='precision'?[samples,samples]:[samples]});if(start+core>=total)break;}
 return {passages,stemBytes:132+Math.ceil(total/2)*8+total*4};
}
const dispose=outputs=>{for(const value of Object.values(outputs))if(value.dispose)value.dispose();};
const sigmoid=x=>1/(1+Math.exp(-Math.max(-50,Math.min(50,x))));
// Full-track mel coordinates with real neighbouring audio, even at inference seams.
// Two extra hops on each side isolate STFT's 512-sample reflection halo.
async function melForFrames(reader,session,first,frames,config){
 const halo=2,start=(first-halo)*441,count=(frames+halo*2-1)*441+1;
 const pcm=await reader.mono22050(start,count,config),total=Math.ceil(reader.duration*22050);
 for(let i=0;i<pcm.length;i++){const at=start+i;if(at<0){const source=-at-start;if(source<pcm.length)pcm[i]=pcm[source];}else if(at>=total){const source=2*(total-1)-at-start;if(source>=0)pcm[i]=pcm[source];}}
 const tensor=new ort.Tensor('float32',pcm,[1,pcm.length]);let output;
 try{output=await session.run({audio_pcm:tensor});const mel=output.mel_spectrogram;return new Float32Array(mel.data.subarray(halo*128,(halo+frames)*128));}finally{if(output)dispose(output);tensor.dispose();}
}
const RHYTHM_FEATURE='rhythm-dsp-v1',RHYTHM_FEATURE_VERSION='dsp-feature-extractor-v1',RHYTHM_PREPROCESSING='pcm-44100-mono22050-reflect-v1';
const floatFeature=(value,length)=>value instanceof Float32Array&&value.length===length;
function rhythmFeaturePayload(data,n){return {version:1,frameCount:n,duration:data.duration,chromaStep:data.chromaStep,rms:data.rms,bass:data.bass,mid:data.mid,high:data.high,colour:data.colour,fineRms:data.fineRms,chroma:data.chroma};}
function validRhythmFeature(value,n,duration){return !!value&&value.version===1&&value.frameCount===n&&value.duration===duration&&value.chromaStep===.2&&floatFeature(value.rms,n)&&floatFeature(value.bass,n)&&floatFeature(value.mid,n)&&floatFeature(value.high,n)&&floatFeature(value.colour,n*3)&&floatFeature(value.fineRms,n*4)&&floatFeature(value.chroma,Math.ceil(n/10)*12);}
function rhythmDataFromFeature(value,n){return {duration:value.duration,beat:new Float32Array(n),down:new Float32Array(n),rms:value.rms,bass:value.bass,mid:value.mid,high:value.high,colour:value.colour,fineRms:value.fineRms,chroma:value.chroma,chromaStep:value.chromaStep};}
async function reusableRhythmFeatures(options,config,resourceDiagnostics=null){
 const audioIdentity=options.analysisIdentity,assetFingerprint=options.analysisAssetFingerprint,api=self.LightForgeFeatureStore,store=self.LightForgeAnalysisStore;
 if(typeof audioIdentity!=='string'||!/^[a-f0-9]{64}$/.test(audioIdentity)||typeof assetFingerprint!=='string'||!/^[a-f0-9]{64}$/.test(assetFingerprint)||!api||typeof api.open!=='function'||!store||typeof store.contentAddress!=='function')return null;
 try{
  const configIdentity=await store.contentAddress('dsp-feature-config',config);
  return await api.open({audioIdentity,preprocessingVersion:RHYTHM_PREPROCESSING,modelVersions:{'analysis-assets':assetFingerprint,'dsp-config':configIdentity,'dsp-extractor':RHYTHM_FEATURE_VERSION},analysisConfiguration:{analysisRate:22050,featureChunk:500,frameHopSamples:441,frameRateHz:50,chromaStep:.2,reflectionHaloHops:2}},{resourceDiagnostics});
 }catch(_){return null;}
}
async function recurrenceEvidenceInput(result,options,config,telemetry){
 const input={duration:result?.duration,sections:result?.sections,energy:result?.energy,energyStep:result?.energyStep};
 if(result?.chroma!==undefined||result?.chromaStep!==undefined){input.chroma=result.chroma;input.chromaStep=result.chromaStep;return input;}
 // The rhythm stage already owns these feature frames. Reuse an exact,
 // version-bound shared record when it is available; no new decode, FFT, or
 // resample is permitted for recurrence analysis.
 const featureStore=config?await reusableRhythmFeatures(options,config,telemetry.resource):null;
 if(!featureStore)return input;
 let hit=null;
 const phase=telemetry.begin('shared-feature.recurrence.read');
 try{hit=await featureStore.read(RHYTHM_FEATURE);}catch(_){telemetry.cache('shared-features','corrupt');}
 telemetry.end(phase,{hit:!!hit});
 const frames=Math.ceil(Number(result?.duration||0)*50);
 if(hit&&!validRhythmFeature(hit.value,frames,result.duration)){
  telemetry.cache('shared-features','corrupt');
  try{await featureStore.invalidate([RHYTHM_FEATURE]);}catch(_){}
  hit=null;
 }
 if(!hit)return input;
 telemetry.cache('shared-features','recurrence-restore');
 input.chroma=hit.value.chroma;
 input.chromaStep=hit.value.chromaStep;
 return input;
}
function wasmThreadCount(){
 // Privacy wrappers may intentionally deny hardware-concurrency access. The
 // safe fallback keeps analysis running single-threaded instead of turning a
 // diagnostic capability probe into a worker-stage failure.
 try{
  if(!self.crossOriginIsolated||typeof SharedArrayBuffer!=='function')return 1;
  const nav=typeof navigator==='undefined'?null:navigator,reported=nav&&nav.hardwareConcurrency;
  const cores=typeof reported==='number'&&Number.isFinite(reported)&&reported>0?reported:2;
  return Math.min(4,Math.max(1,Math.floor(cores/2)));
 }catch(_){return 1;}
}
function workerTimingAttributes(timing){
 return {workerClockStatus:timing.status,workerClockSource:timing.source,workerClockMeasured:timing.measured,workerClockReason:timing.reason||'none'};
}
function workerTimingSeconds(timing){return timing.measured?timing.milliseconds/1000:0;}
self.onmessage=async e=>{
 if(e.data?.type==='native-deux-result'||e.data?.type==='native-deux-progress'){
  const pending=nativeRequests.get(e.data.requestId);if(!pending)return;
  if(e.data.type==='native-deux-progress'){pending.onProgress(e.data.value.progress,e.data.value.message);return;}
  nativeRequests.delete(e.data.requestId);
  if(e.data.aborted){pending.reject(nativeAbortError(e.data.message));return;}
  if(e.data.fallback||e.data.error||typeof e.data.url!=='string')Promise.resolve().then(()=>pending.onFallback()).then(()=>pending.reject(nativeDeuxFallbackError()),error=>pending.reject(error));
  else pending.resolve(e.data.url);
  return;
 }
 if(e.data?.type==='native-mdx-result'||e.data?.type==='native-mdx-progress'){
  const pending=nativeMdxRequests.get(e.data.requestId);if(!pending)return;
  if(e.data.type==='native-mdx-progress'){pending.onProgress(e.data.value);return;}
  nativeMdxRequests.delete(e.data.requestId);
  if(e.data.aborted){pending.reject(nativeAbortError(e.data.message));return;}
  if(e.data.fallback||e.data.error||!(e.data.buffer instanceof ArrayBuffer)||e.data.buffer.byteLength!==pending.expectedBytes||e.data.buffer.byteLength%Float32Array.BYTES_PER_ELEMENT!==0)Promise.resolve().then(()=>pending.onFallback()).then(()=>pending.reject(nativeMdxFallbackError()),error=>pending.reject(error));
  else pending.resolve(new Float32Array(e.data.buffer));
  return;
 }
 let session,melSession,separator,game,cacheWriter;let nativeMdxFallback=false,nativeDeuxFallback=false,nativeMdxFencing=false,nativeDeuxFencing=false,nativeMdxFence=null,nativeDeuxFence=null;const workerClock=createDiagnosticClock(),started=workerClock.mark();try{
 const {audioUrl,options={},stage}=e.data;
 if(!['rhythm','separation','voice','bass','recurrence'].includes(stage))throw Error('Invalid music analysis stage.');
 const cacheKey=options.cacheKey,quality=options.analysisQuality==='balanced'?'balanced':'precision';
 const telemetry=createTelemetry(stage,{quality});
 const storeOpen=telemetry.begin('store.open');
 const store=await LightForgeAnalysisStore.open(options.workId,{sourceId:options.projectId||'',resourceDiagnostics:telemetry.resource});
 telemetry.end(storeOpen);
 if(stage==='recurrence'){
  if(!self.LightForgeRecurrence)importScripts('recurrence.js');
  const result=e.data.value||{};
  let featureConfig=null;
  if(typeof options.analysisIdentity==='string'&&/^[a-f0-9]{64}$/.test(options.analysisIdentity)){
   const featureConfigPhase=telemetry.begin('shared-feature.recurrence.config');
   featureConfig=await(await fetch('models/features.json')).json();
   telemetry.end(featureConfigPhase);
  }
  const recurrencePhase=telemetry.begin('structure.recurrence');
  const recurrence=await ensureRecurrenceAnalysis(result,options,store,telemetry,featureConfig),sidecar=recurrence.sidecar;
  telemetry.end(recurrencePhase,{enabled:recurrence.enabled,restored:recurrence.restored,motifCount:sidecar?.summary?.motifCount||0,repeatedSectionCount:sidecar?.summary?.repeatedSectionCount||0});
  if(recurrence.enabled)report(1,'Mapping recurring material','Validated generic repeated-section evidence saved',{checkpointSaved:true,analysisStage:stage});
  else report(1,'Mapping recurring material','Opt-in recurrence analysis is disabled');
  const recurrenceTiming=workerClock.measure(started);
  postMessage({type:'result',value:result,restored:recurrence.restored,seconds:recurrence.restored?0:workerTimingSeconds(recurrenceTiming),profile:telemetry.snapshot({restored:recurrence.restored,...workerTimingAttributes(recurrenceTiming)})});
  return;
 }
 const manifestLoad=telemetry.begin('model.manifest');
 const config=await(await fetch('models/features.json')).json(),models=await(await fetch('models/model-manifest.json')).json(),selected=models[quality];
 telemetry.end(manifestLoad);
 const cacheRead=telemetry.begin('cache.read');
 let result=e.data.value||{};
 clearRecurrenceAnalysis(result);
 let cached=await store.read(stage);
 telemetry.end(cacheRead,{hit:!!cached});
 if(cached&&stage==='separation')try{await LightForgeStemCache.files(cached.stemCache);await LightForgeStemCache.fullVoice(cached.stemCache);}catch{cached=null;telemetry.cache(stage,'corrupt');}
 if(stage==='separation'&&!cached){telemetry.cache(stage,'invalidate');await store.invalidate(['separation','voice','vocal-semantics','game','bass','recurrence']);}
 if(cached){
  telemetry.cache(stage,'restore');
  const restored={...result,...cached};
  if(stage==='rhythm'){
   if(options.rhythmHierarchy===true){
    const hierarchyPhase=telemetry.begin('rhythm.hierarchy');
    const hierarchy=ensureRhythmHierarchy(restored,options);
    telemetry.end(hierarchyPhase,{restored:true,attached:hierarchy.attached,reused:hierarchy.reused,beatCount:hierarchy.hierarchy.beats.length,barCount:hierarchy.hierarchy.bars.length});
    if(hierarchy.attached)await store.write(stage,restored);
   }else if(Object.prototype.hasOwnProperty.call(restored,'rhythmHierarchy'))delete restored.rhythmHierarchy;
  }
  if(stage==='voice')await ensureVocalSemantics(restored,options,store,telemetry);
  if(stage==='bass'){
   const provenanceChanged=normalizeBassProvenance(restored),cachedStemRouting=restored.stemRouting;
   const vocalSemantics=await ensureVocalSemantics(restored,options,store,telemetry);
   const stemRoutingPhase=telemetry.begin('stem.routing');
   const stemRouting=ensureStemRouting(restored),stemRoutingWasCurrent=cachedStemRouting===stemRouting.routing;
   telemetry.end(stemRoutingPhase,{restored:true,stemCount:stemRouting.routing.stems.length,rebuilt:stemRouting.rebuilt,cacheReused:stemRoutingWasCurrent});
   const cachedTimeline=restored.semanticTimeline,timelinePhase=telemetry.begin('semantic.timeline');
   const timeline=ensureSemanticTimeline(restored),timelineWasCurrent=cachedTimeline===timeline;
   telemetry.end(timelinePhase,{restored:true,eventCount:timeline.events.length,provenanceMigrated:provenanceChanged,cacheReused:timelineWasCurrent});
   const cachedSalience=restored.musicSalience,saliencePhase=telemetry.begin('semantic.salience');
   const musicSalience=ensureMusicSalience(restored,timeline),salienceWasCurrent=cachedSalience===musicSalience;
   telemetry.end(saliencePhase,{restored:true,eventCount:musicSalience.events.length,profile:musicSalience.summary.context.profile,cacheReused:salienceWasCurrent});
   if(!stemRoutingWasCurrent||!timelineWasCurrent||!salienceWasCurrent||provenanceChanged)await store.write(stage,persistableAnalysis(restored));
   if(vocalSemantics)linkVocalSemantics(restored);
  }
  report(({rhythm:.4,separation:.82,voice:.985,bass:1})[stage],'Restoring saved progress','Completed '+stage+' work restored',{checkpointSaved:true,restoredStage:stage});
  const restoredTiming=workerClock.measure(started);
  // Restored work remains zero-cost in analyzer stage accounting. The clock
  // evidence is attached only to diagnostics, so a hostile runtime cannot
  // alter cache semantics or any downstream FSEQ/default behavior.
  postMessage({type:'result',value:restored,restored:true,seconds:0,profile:telemetry.snapshot({restored:true,...workerTimingAttributes(restoredTiming)})});
  return;
 }
 telemetry.cache(stage,'miss');
 ort.env.wasm.wasmPaths=new URL('vendor/',self.location.href).href;ort.env.wasm.numThreads=wasmThreadCount();ort.env.wasm.proxy=false;
 const sessionOptions={executionProviders:['wasm'],graphOptimizationLevel:'all',enableCpuMemArena:false,enableMemPattern:false};
 if(stage==='rhythm'){
  report(.01,'Opening music','Reading your music locally');const reader=new LightForgeWavReader(options.analysisUrl||audioUrl);await reader.open();
 const n=Math.ceil(reader.duration*50),featureStore=await reusableRhythmFeatures(options,config,telemetry.resource);let featureHit=null;
 if(featureStore){
  const featureRead=telemetry.begin('shared-feature.read');
  try{featureHit=await featureStore.read(RHYTHM_FEATURE);}catch(_){featureHit=null;}
  telemetry.end(featureRead,{hit:!!featureHit});
 }
 if(featureHit&&!validRhythmFeature(featureHit.value,n,reader.duration)){telemetry.cache('shared-features','corrupt');try{await featureStore.invalidate([RHYTHM_FEATURE]);}catch(_){}featureHit=null;}
 let data=featureHit?rhythmDataFromFeature(featureHit.value,n):null;
 if(data){telemetry.cache('shared-features','hit');report(.025,'Restoring musical detail','Verified reusable energy and tonal features restored');}
 else{
  if(featureStore)telemetry.cache('shared-features','miss');
  const chromaCount=Math.ceil(n/10)*12,rhythmBytes=(n*6+n*3+n*4+chromaCount)*4;
  data={duration:reader.duration,beat:new Float32Array(n),down:new Float32Array(n),rms:new Float32Array(n),bass:new Float32Array(n),mid:new Float32Array(n),high:new Float32Array(n),colour:new Float32Array(n*3),fineRms:new Float32Array(n*4),chroma:new Float32Array(chromaCount),chromaStep:.2};
  telemetry.allocation?.(rhythmBytes,9);
  const extractor=new LightForgeDSP.FeatureExtractor(config),featureChunk=500;
  report(.025,'Listening to musical detail','Measuring attacks, tonal colour and quiet passages');
  for(let first=0;first<n;first+=featureChunk){const frames=Math.min(featureChunk,n-first),samples=await reader.mono22050(first*441-705,(frames-1)*441+1411,config),f=extractor.extract(samples,0,frames);for(const name of ['rms','bass','mid','high'])data[name].set(f[name],first);data.colour.set(f.colour,first*3);data.fineRms.set(f.fineRms,first*4);for(let i=0;i<frames;i++)for(let b=0;b<12;b++)data.chroma[Math.floor((first+i)/10)*12+b]+=f.chroma[i*12+b]/10;report(.03+.18*(first+frames)/n,'Listening to musical detail',`${Math.min(reader.duration,(first+frames)*.02).toFixed(0)} / ${reader.duration.toFixed(0)} seconds`);}
  if(featureStore){
   const featureWrite=telemetry.begin('shared-feature.write');
   try{await featureStore.write(RHYTHM_FEATURE,rhythmFeaturePayload(data,n),{producer:RHYTHM_FEATURE_VERSION,frameCount:n});telemetry.cache('shared-features','write');}catch(_){telemetry.cache('shared-features','corrupt');}
   telemetry.end(featureWrite);
  }
 }
 report(.22,'Loading music AI',quality==='precision'?'Beat This! full transformer • entirely on this device':'Beat This! compact transformer • entirely on this device');

 const chunk=1500,border=6,stride=chunk-border*2,starts=[];for(let s=-border;s<n-border;s+=stride)starts.push(s);if(n>stride)starts[starts.length-1]=n-(chunk-border);
 let copiedUntil=0;
 for(let k=0;k<starts.length;k++){
  const first=starts[k],length=Math.min(chunk,n+border-first),lo=Math.max(0,first),hi=Math.min(n,first+length);let peak=0;for(let i=lo;i<hi;i++)peak=Math.max(peak,data.rms[i]);
  if(peak<=1e-7){copiedUntil=Math.max(copiedUntil,Math.min(n,first+length-border));report(.24+.15*(k+1)/starts.length,'Recognizing a quiet passage','Keeping complete silence clear of invented beats');continue;}
  if(!session){session=await ort.InferenceSession.create(new URL('models/'+selected.file,self.location.href).href,sessionOptions);melSession=await ort.InferenceSession.create(new URL('models/'+models.frontend.file,self.location.href).href,sessionOptions);}
  const features=new Float32Array(length*128),mel=await melForFrames(reader,melSession,lo,hi-lo,config);telemetry.allocation?.(features.byteLength,1);features.set(mel,(lo-first)*128);telemetry.copy?.(mel.byteLength,1);
  const input=new ort.Tensor('float32',features,[1,length,128]);let out;
  try{out=await session.run({spectrogram:input});const beats=out.beat.data,down=out.downbeat.data;const begin=Math.max(copiedUntil,0,first+border),end=Math.min(n,first+length-border);for(let i=begin;i<end;i++){const b=sigmoid(beats[i-first]),d=sigmoid(down[i-first]);data.beat[i]=Math.max(0,b-d);data.down[i]=d;}copiedUntil=Math.max(copiedUntil,end);}finally{if(out)dispose(out);input.dispose();}
  report(.24+.15*(k+1)/starts.length,'Understanding beats and bar accents',`${Math.min(reader.duration,copiedUntil*.02).toFixed(0)} / ${reader.duration.toFixed(0)} seconds • ${quality==='precision'?'Precision':'Balanced'}`);
 }
 if(copiedUntil!==n)throw new Error('The music analysis did not cover the full track. Please try again.');
 if(session)await session.release();session=null;if(melSession)await melSession.release();melSession=null;
 report(.40,'Recognizing musical structure','Finding recurring passages, groove and confident movement moments');
 result=LightForgeDSP.summarize(data,{...options,decoder:'transformer'});
 if(options.rhythmHierarchy===true){
  const hierarchyPhase=telemetry.begin('rhythm.hierarchy');
  const hierarchy=ensureRhythmHierarchy(result,options);
  telemetry.end(hierarchyPhase,{restored:false,attached:hierarchy.attached,reused:hierarchy.reused,beatCount:hierarchy.hierarchy.beats.length,barCount:hierarchy.hierarchy.bars.length});
 }
 // Release rhythm feature buffers and both transformer sessions before the
 // independent musical-role passes. Every pass uses the same original PCM clock.
 data=null;

  await store.write(stage,result);
  // OPFS has a durable, checksummed rhythm result even before the Java
  // checkpoint is committed. Surface that fact immediately so a killed
  // renderer offers Resume instead of reporting a blank status.
  report(.40,'Recognizing musical structure','Progress saved',{checkpointSaved:true,analysisStage:stage});
 }else if(stage==='separation'){
  const sourceReader=new LightForgeWavReader(audioUrl);
  await sourceReader.open();
  telemetry.increment?.('source_wav_reader_opens');
 const storagePlan=separationStoragePlan(sourceReader.samples,quality);
 report(.405,'Checking analysis storage','Protecting enough space for this song and its saved progress');
 await LightForgeStemCache.prune(cacheKey,storagePlan.stemBytes);
 await store.reserve({...storagePlan,onProgress:(done,total)=>report(.405,'Checking saved analysis storage','Verified '+done+' / '+total+' passage checkpoints')});
 report(.41,'Separating voice and instruments','Recoverable passages • your music stays on this device');
 cacheWriter=await LightForgeStemCache.create(cacheKey,sourceReader.samples,config,options.projectId||'');
 const markNativeDeuxFallback=()=>{
  if(nativeDeuxFence)return nativeDeuxFence;
  nativeDeuxFencing=true;
  // Fence all DEUX-dependent passages before the parent can admit the new
  // WASM identity. Do not mark fallback complete until invalidation succeeds.
  nativeDeuxFence=Promise.resolve().then(()=>store.invalidate(['separation','deux','voice','vocal-semantics','game','bass','recurrence'])).then(()=>{nativeDeuxFallback=true;});
  return nativeDeuxFence;
 };
 const markNativeMdxFallback=()=>{
  if(nativeMdxFence)return nativeMdxFence;
  nativeMdxFencing=true;
  // Fence all MDX-dependent passages before the parent can admit the new
  // WASM identity. Do not mark fallback complete until invalidation succeeds.
  nativeMdxFence=Promise.resolve().then(()=>store.invalidate(['separation','mdx','voice','vocal-semantics','game','bass','recurrence'])).then(()=>{nativeMdxFallback=true;});
  return nativeMdxFence;
 };
 const nativeStudioPredict=quality==='precision'&&options.supportsNativeDeux?(start,onProgress)=>nativePredict(start,onProgress,markNativeDeuxFallback):undefined;
 const nativeBalancedPredict=quality==='balanced'&&options.supportsNativeMdx?(encoded,onProgress)=>nativeMdxPredict(encoded,onProgress,markNativeMdxFallback):undefined;
 separator=await (quality==='precision'?LightForgeDeux:LightForgeMdxSeparator).create({ort,baseUrl:new URL(quality==='precision'?'models/deux/':'models/',self.location.href).href,onProgress:p=>report(.41,'Loading studio vocal separation',p.message),checkpoint:store,nativePredict:nativeStudioPredict||nativeBalancedPredict});
 result.separation=await separator.process((start,count)=>sourceReader.stereo44100(start,count),sourceReader.samples,chunk=>{
  if(nativeMdxFallback||nativeDeuxFallback||nativeMdxFencing||nativeDeuxFencing)return;
  return cacheWriter.append(chunk);
 },p=>report(.42+.40*p.progress,'Separating voice and instruments',`${p.message} • ${Math.min(sourceReader.duration,p.processedSeconds||0).toFixed(0)} / ${sourceReader.duration.toFixed(0)} seconds`,p));
 await separator.release();separator=null;
 if(nativeDeuxFallback)throw nativeDeuxFallbackError();
 if(nativeMdxFallback)throw nativeMdxFallbackError();
 result.stemCache=await cacheWriter.finish();cacheWriter=null;

   await store.write(stage,{separation:result.separation,stemCache:result.stemCache});
   report(.82,'Separating voice and instruments','Progress saved',{checkpointSaved:true,analysisStage:stage});
  }else if(stage==='voice'){
 const stems=await LightForgeStemCache.readers(result.stemCache),fullVoice=await LightForgeStemCache.fullVoice(result.stemCache),sourceClock=fullResolutionStemClock(result.stemCache);
 report(.83,'Recognizing the isolated voice','Distinguishing singing, speech and remaining instrument bleed');
 const classified=await store.read('voice-classifier')||await LightForgeVocals.analyze(stems.vocals,config,{ort,includeClassifierScores:true,report:(p,stage,detail)=>report(.83+.075*p,'Recognizing the isolated voice',detail)});
 await store.write('voice-classifier',classified);
 const detailExtractor=new LightForgeVocalDetail.Extractor({sampleRate:22050,duration:sourceClock.duration}),detailCount=result.stemCache.samples,detailChunk=22050*8;
 for(let start=0;start<detailCount;start+=detailChunk){const count=Math.min(detailChunk,detailCount-start),voice=await stems.vocals.mono22050(start,count,config),backing=await stems.accompaniment.mono22050(start,count,config);detailExtractor.push(voice,start,backing);report(.905+.035*(start+count)/detailCount,'Following vocal expression','Measuring entrances, syllabic attacks, held notes and pauses');}
 report(.942,'Transcribing sung notes','GAME Large • identifying entrances, pitch changes and held notes');
 game=await LightForgeGAME.create({ort,baseUrl:new URL('models/game/',self.location.href).href,onProgress:detail=>report(.942,'Loading singing transcription',detail),checkpoint:store});
 const transcription=await game.process(fullVoice,sourceClock.samples,{onProgress:(p,info)=>report(.945+.04*p,'Transcribing sung notes','GAME Large • '+Math.round(p*100)+'%',info)});
 result.vocals=LightForgeGAME.fuse(detailExtractor.finish({classifier:classified.classifier,model:classified.model,transcription}),transcription);classified.classifier=null;await game.release();game=null;
 await ensureVocalSemantics(result,options,store,telemetry);

   await store.write(stage,{vocals:result.vocals});
   report(.985,'Recognizing the isolated voice','Progress saved',{checkpointSaved:true,analysisStage:stage});
  }else{
   const stems=await LightForgeStemCache.readers(result.stemCache);
 report(.985,'Following bass notes','Listening beneath the separated singing');
 const bass=await LightForgeBass.analyze(stems.accompaniment,config,{onProgress:p=>report(.985+.014*p,'Following bass notes','Distinguishing sustained low notes from brief drum attacks')});
 const {notes,...bassAnalysis}=bass;result.bassNotes=notes;result.bassAnalysis={...bassAnalysis,source:'accompaniment-mixture-estimate',inputStem:'accompaniment',inputStemSeparated:true,instrumentSeparated:false,sourceSeparated:false,limitations:[...(bassAnalysis.limitations||[]),'Bass notes are estimated from a vocal-separated accompaniment mixture, not an isolated bass stem.']};
 normalizeBassProvenance(result);
 result.analysisVersion=8;
 result.roleAnalysis={version:5,clock:'Original decoded audio',vocalSource:'Separated vocal waveform with singing and speech evidence',bassSource:'Low-register harmonics in a vocal-separated accompaniment mixture; not an isolated bass stem',bassInputStem:'accompaniment',accompanimentStemSeparated:true,bassInstrumentSeparated:false,sourceSeparated:true,lyricsAligned:false};
 for(const warning of [...(result.vocals.warnings||[]),...(result.separation.limitations||[])])if(!result.warnings.includes(warning))result.warnings.push(warning);
  const engineTiming=workerClock.measure(started);
  result.engine={name:'Beat This! '+(quality==='precision'?'full + Deux':'compact + MDX')+' + GAME Large',neural:true,detail:'Bundled pretrained rhythm transformer, stereo vocal separation, isolated-voice singing and speech classification, GAME Large neural sung-note transcription, measured source expression, and independent accompaniment bass tracking. All audio stays on this device.',model:selected.model,modelId:selected.id,modelSha256:selected.sha256,frontendSha256:models.frontend.sha256,vocalModel:result.vocals.model,noteModel:result.vocals.transcription.model,separationModel:result.separation,bassMethod:result.bassAnalysis.method,quality,runtime:(result.separation.nativeModelPasses>0||result.separation.runtime==='onnxruntime-android-cpu')?'ONNX Runtime Android CPU + ONNX Runtime Web 1.20.1':'ONNX Runtime Web 1.20.1',analysisSeconds:Math.round(workerTimingSeconds(engineTiming)*10)/10};
 const vocalSemantics=await ensureVocalSemantics(result,options,store,telemetry);
 const stemRoutingPhase=telemetry.begin('stem.routing');
 const stemRouting=ensureStemRouting(result);
 telemetry.end(stemRoutingPhase,{stemCount:stemRouting.routing.stems.length,rebuilt:stemRouting.rebuilt});
 const timelinePhase=telemetry.begin('semantic.timeline');
 const semanticTimeline=ensureSemanticTimeline(result);
 telemetry.end(timelinePhase,{eventCount:semanticTimeline.events.length,tiers:semanticTimeline.summary.countByTier});
 const saliencePhase=telemetry.begin('semantic.salience');
 const musicSalience=ensureMusicSalience(result,semanticTimeline);
 telemetry.end(saliencePhase,{eventCount:musicSalience.events.length,tiers:musicSalience.summary.countByTier,profile:musicSalience.summary.context.profile});
 if(vocalSemantics)linkVocalSemantics(result);
 result.recommendedAudio={sampleRate:44100,channels:2,format:'PCM16 WAV'};report(1,'Music understood',(result.bpm?result.bpm+' BPM':'No pulse detected')+' • '+result.sections.length+' sections');

   await store.write(stage,persistableAnalysis(result));
   report(1,'Music understood','Progress saved',{checkpointSaved:true,analysisStage:stage});
  }
 const completionTiming=workerClock.measure(started);
 postMessage({type:'result',value:result,restored:false,seconds:workerTimingSeconds(completionTiming),profile:telemetry.snapshot({restored:false,...workerTimingAttributes(completionTiming)})});
 }catch(error){
  if(cacheWriter)try{await cacheWriter.abort();}catch(_){}
  postMessage({type:'error',message:String(error.message||error).slice(0,3072),code:typeof error.code==='string'?error.code:undefined,stack:typeof error.stack==='string'?error.stack.slice(0,8192):undefined});
 }finally{
  if(game)try{await game.release();}catch(_){}if(separator)try{await separator.release();}catch(_){}
  if(session)try{await session.release();}catch(_){}if(melSession)try{await melSession.release();}catch(_){}
 }};

