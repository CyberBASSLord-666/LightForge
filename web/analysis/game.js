/* GAME Large singing transcription adapter. Original integration: MIT.
 * Model weights / deterministic-input graph derivative: CC BY-NC-SA 4.0.
 * openvpi/GAME v1.0.3. Float32, 8 diffusion steps, author's 0.2 thresholds.
 * Output is estimated dominant sung notes, never lyrics or calibrated certainty.
 */
(function(root){'use strict';
const RATE=44100,CORE=12,HALO=2,STEPS=8;
const round=n=>Math.round(n*1000)/1000;
function noise(length,seed){const out=new Float32Array(length);let x=seed>>>0;for(let i=0;i<length;i++){x^=x<<13;x^=x>>>17;x^=x<<5;out[i]=((x>>>0)+.5)/4294967296;}return out;}
function free(out){if(out)for(const t of Object.values(out))t.dispose?.();}
async function create({ort,baseUrl,onProgress=()=>{},checkpoint,parallelism=1}){
 const sessions={},manifest=await(await fetch(new URL('manifest.json',baseUrl))).json();let loaded=false,released=false,activeInference=null,processing=false,releasePending=null;
 // The caller owns native memory admission and the durable crash guard. An
 // independent child retains the exact single-thread kernels of this lane.
 const poolEligible=parallelism===2&&ort.env?.wasm?.numThreads===1&&typeof root.Worker==='function';
 let child=null,childPending=null,childSequence=0,childUses=0,childDisabled=false,localUses=0;
 const closedError=()=>{const error=new Error('Singing transcription is closed.');error.name='AbortError';return error;};
 const ensureOpen=()=>{if(released)throw closedError();};
 const validNotes=(notes,samples)=>Array.isArray(notes)&&notes.length<=Math.ceil(samples/RATE/.06)+1&&notes.every((n,j)=>n&&Number.isFinite(n.start)&&Number.isFinite(n.end)&&Number.isFinite(n.midi)&&n.midi>=0&&n.midi<=127&&n.start>=0&&n.end-n.start>=.06-1e-6&&n.end<=samples/RATE+.001&&(!j||n.start>=notes[j-1].end-1e-6));
 function stopChild(error=closedError()){
  const pending=childPending,worker=child;childPending=null;child=null;childUses=0;
  if(pending){root.clearTimeout(pending.timer);pending.reject(error);}
  if(worker){worker.onmessage=worker.onerror=worker.onmessageerror=null;try{worker.terminate();}catch(_){}}
 }
 function inferChild(pcm,language,seed,onStep){
  ensureOpen();
  if(childPending)throw Error('A singing passage is already running in the child worker.');
  if(!child){
   child=new root.Worker(new URL('../../game-worker.js',baseUrl).href);childUses=0;
   child.onerror=event=>{event.preventDefault?.();stopChild(Error('The parallel singing worker could not finish.'));};
   child.onmessageerror=()=>stopChild(Error('The parallel singing result could not be read.'));
   child.onmessage=event=>{
    const value=event.data,pending=childPending;if(!pending||value?.requestId!==pending.requestId)return;
    if(value.type==='progress'){
     if(Number.isFinite(value.progress)&&value.progress>=pending.progress&&value.progress>=0&&value.progress<=1){pending.progress=value.progress;try{pending.onStep(value.progress);}catch(error){stopChild({progressCallbackError:error});}}
     return;
    }
    if(value.type==='error'){stopChild(Error(String(value.message||'The parallel singing worker failed.').slice(0,2048)));return;}
    if(value.type!=='result')return;
    if(value.model!==manifest.id||value.steps!==STEPS||value.samples!==pending.samples||value.language!==pending.language||value.seed!==pending.seed||!validNotes(value.notes,pending.samples)){
     stopChild(Error('The parallel singing result does not match its passage.'));return;
    }
    childPending=null;root.clearTimeout(pending.timer);childUses++;pending.resolve(value.notes);
    // Destroying the child also retires its WASM heap, not only model handles.
    if(childUses>=4)stopChild();
   };
  }
  // Retain this passage's original PCM until its durable result is accepted,
  // so a transport or child failure can recompute the exact same samples.
  const copy=pcm.slice(),requestId=++childSequence;
  return new Promise((resolve,reject)=>{
   const timer=root.setTimeout(()=>stopChild(Error('The parallel singing worker did not finish.')),15*60*1000);
   childPending={requestId,resolve,reject,timer,progress:0,onStep,samples:pcm.length,language,seed};
   try{child.postMessage({type:'infer',requestId,buffer:copy.buffer,language,seed,model:manifest.id},[copy.buffer]);}
   catch(error){stopChild(error);}
  });
 }
 async function load(){
  if(released)throw Error('Singing transcription is closed.');if(loaded)return;
  try{for(const name of ['encoder','dur2bd','segmenter','bd2dur','estimator']){ensureOpen();onProgress('Loading '+name);sessions[name]=await ort.InferenceSession.create(new URL(name+'.onnx',baseUrl).href,{executionProviders:['wasm'],graphOptimizationLevel:'all',enableCpuMemArena:false,enableMemPattern:false});ensureOpen();}loaded=true;}
  catch(e){await Promise.allSettled(Object.values(sessions).map(async s=>s.release()));for(const name of Object.keys(sessions))delete sessions[name];throw e;}
 }
 async function reset(){
  stopChild();localUses=0;
  const active=Object.values(sessions);for(const name of Object.keys(sessions))delete sessions[name];loaded=false;
  await Promise.allSettled(active.map(async s=>s.release?.()));
 }
 const tensor=(type,data,dims)=>new ort.Tensor(type,data,dims);
 async function infer(pcm,language,seed,onStep=()=>{}){
  ensureOpen();if(activeInference)throw Error('Singing passages must run one at a time in each worker.');
  const pending=runInference(pcm,language,seed,onStep);activeInference=pending;
  try{return await pending;}finally{if(activeInference===pending)activeInference=null;}
 }
 async function runInference(pcm,language,seed,onStep){
  await load();ensureOpen();
  const owned=[],own=t=>(owned.push(t),t);let encoded,known,previous,timing,estimated;
  try{
   encoded=await sessions.encoder.run({waveform:own(tensor('float32',pcm,[1,pcm.length])),duration:own(tensor('float32',Float32Array.of(pcm.length/RATE),[1]))});ensureOpen();onStep(1/(STEPS+2));
   known=await sessions.dur2bd.run({durations:own(tensor('float32',Float32Array.of(pcm.length/RATE),[1,1])),maskT:encoded.maskT});ensureOpen();
   const lang=own(tensor('int64',BigInt64Array.of(BigInt(language)),[1])),threshold=own(tensor('float32',Float32Array.of(.2),[])),radius=own(tensor('int64',BigInt64Array.of(2n),[]));
   for(let k=0;k<STEPS;k++){
    const time=tensor('float32',Float32Array.of(k/STEPS),[1]),random=tensor('float32',noise(encoded.maskT.data.length,(seed+k*2654435761)>>>0),encoded.maskT.dims);
    let next;try{next=await sessions.segmenter.run({x_seg:encoded.x_seg,maskT:encoded.maskT,known_boundaries:known.boundaries,prev_boundaries:previous?.boundaries||known.boundaries,language:lang,threshold,radius,t:time,random_uniform:random});}finally{time.dispose();random.dispose();}
    free(previous);previous=next;ensureOpen();onStep((k+2)/(STEPS+2));
   }
   timing=await sessions.bd2dur.run({boundaries:previous.boundaries,maskT:encoded.maskT});ensureOpen();
   estimated=await sessions.estimator.run({x_est:encoded.x_est,boundaries:previous.boundaries,maskT:encoded.maskT,maskN:timing.maskN,threshold});ensureOpen();
   const result=[];let start=0;
   for(let i=0;i<timing.durations.data.length;i++){const length=timing.durations.data[i],end=start+length,midi=estimated.scores.data[i];if(!Number.isFinite(length)||length<0||!Number.isFinite(midi))throw Error('Singing transcription returned invalid note data.');if(timing.maskN.data[i]&&estimated.presence.data[i]&&length>=.06&&midi>=0&&midi<=127)result.push({start,end,midi});start=end;}
   onStep(1);return result;
  }finally{free(encoded);free(known);free(previous);free(timing);free(estimated);owned.forEach(t=>t.dispose());}
 }
 async function processParallel(read,total,language,onProgress){
  const notes=[],duration=total/RATE,chunks=Math.ceil(duration/CORE);let restoredPassages=0,completed=0;
  const emit=(item,extra={})=>onProgress(Math.min(1,(completed+item.filter(p=>!p.done).reduce((sum,p)=>sum+p.progress,0))/chunks),{passageIndex:(item.find(p=>!p.done)||item[item.length-1]).index+1,passageCount:chunks,passagesCompleted:completed,restoredPassages,parallelism:childDisabled?1:2,...extra});
  async function prepare(index){
   ensureOpen();
   const coreStart=index*CORE,coreEnd=Math.min(duration,coreStart+CORE),start=Math.max(0,coreStart-HALO),end=Math.min(duration,coreEnd+HALO),first=Math.round(start*RATE),last=Math.min(total,Math.round(end*RATE)),key='game-'+language+'-'+index;
   const stored=await checkpoint?.read(key);ensureOpen();
   const restored=!!(stored&&stored.model===manifest.id&&stored.steps===STEPS&&stored.first===first&&stored.last===last&&validNotes(stored.notes,last-first));
   const item={index,coreStart,coreEnd,start,first,last,key,restored,progress:0,done:false,candidates:restored?stored.notes:null,pcm:null,peak:0};
   if(!restored){
    item.pcm=await read(first,last-first);ensureOpen();
    if(!(item.pcm instanceof Float32Array)||item.pcm.length!==last-first)throw Error('Singing audio clock is incomplete.');
    for(const x of item.pcm){if(!Number.isFinite(x))throw Error('Singing audio contains invalid samples.');item.peak=Math.max(item.peak,Math.abs(x));}
   }
   return item;
  }
  async function complete(item,candidates,batch){
   ensureOpen();
   if(!item.restored)await checkpoint?.write(item.key,{first:item.first,last:item.last,model:manifest.id,steps:STEPS,notes:candidates});
   ensureOpen();item.candidates=candidates;item.pcm=null;item.done=true;item.progress=1;completed++;if(item.restored)restoredPassages++;
   emit(batch,{checkpointSaved:!!checkpoint});
  }
  function stitch(item){
   for(const n of item.candidates){
    const a=item.start+n.start,b=Math.min(duration,item.start+n.end);
    if(b<=item.coreStart||a>=item.coreEnd)continue;
    const previous=notes[notes.length-1],carry=a<item.coreStart;
    if(carry&&previous&&previous.end>=item.coreStart-.04&&Math.abs(previous.midi-n.midi)<.75){previous.end=round(Math.min(item.coreEnd,b));continue;}
    const na=Math.max(item.coreStart,a),nb=Math.min(item.coreEnd,b);
    if(nb>na)notes.push({start:round(na),end:round(nb),midi:Math.round(n.midi*100)/100,source:'game-large',estimated:true,continuation:carry});
   }
  }
  async function local(item,batch){
   ensureOpen();
   if(localUses>=4)await reset();
   const candidates=await infer(item.pcm,language,(2025+item.index*104729)>>>0,p=>{item.progress=Math.min(p,.999999);emit(batch);});
   localUses++;await complete(item,candidates,batch);
  }
  // Each iteration owns at most two PCM passages. No later reads are issued
  // until both results are durable and applied in original source order.
  for(let index=0;index<chunks;index+=2){
   const batch=[await prepare(index)];if(index+1<chunks)batch.push(await prepare(index+1));
   emit(batch);
   for(const item of batch)if(item.restored||item.peak<=1e-5)await complete(item,item.candidates||[],batch);
   const pending=batch.filter(item=>!item.done);
   if(pending.length===2&&!childDisabled){
    // Reset before dispatch, so retiring this lane cannot kill an active child.
    if(localUses>=4)await reset();
    const remoteItem=pending[1];
    const remote=(async()=>{
     let candidates;
     try{candidates=await inferChild(remoteItem.pcm,language,(2025+remoteItem.index*104729)>>>0,p=>{remoteItem.progress=Math.min(p,.999999);emit(batch);});}
     catch(error){return error&&Object.prototype.hasOwnProperty.call(error,'progressCallbackError')?{kind:'completion-error',error:error.progressCallbackError}:{kind:'inference-error',error};}
     try{await complete(remoteItem,candidates,batch);return {kind:'complete'};}
     catch(error){return {kind:'completion-error',error};}
    })();
    try{
     await local(pending[0],batch);
     const result=await remote;ensureOpen();
     if(result.kind==='completion-error')throw result.error;
     if(result.kind==='inference-error'){
      stopChild();childDisabled=true;remoteItem.progress=0;emit(batch,{workerFallback:true});
      await local(remoteItem,batch);
     }
    }catch(error){stopChild(error);await remote;throw error;}
   }else for(const item of pending)await local(item,batch);
   for(const item of batch)stitch(item);
  }
  notes.sort((a,b)=>a.start-b.start);for(let i=0;i<notes.length-1;i++)notes[i].end=Math.min(notes[i].end,notes[i+1].start);
  return {notes:notes.filter(n=>n.end-n.start>=.06-1e-6),model:manifest.id,frameSeconds:.01,steps:STEPS,language,sourceClock:'Original decoded PCM',lyricsAligned:false,confidenceIsProbability:false};
 }
 async function process(read,total,{language=0,onProgress=()=>{}}={}){
  ensureOpen();if(![0,1,2,3,4].includes(language)||!Number.isSafeInteger(total)||total<1||total>RATE*14401)throw Error('Invalid transcription request.');if(processing)throw Error('Singing transcription is already processing.');processing=true;
  try{return await (poolEligible&&!childDisabled?processParallel(read,total,language,onProgress):processSerial(read,total,{language,onProgress}));}
  finally{processing=false;stopChild();}
 }
 async function processSerial(read,total,{language=0,onProgress=()=>{}}={}){
  if(released)throw Error('Singing transcription is closed.');
  if(![0,1,2,3,4].includes(language)||!Number.isSafeInteger(total)||total<1||total>RATE*14401)throw Error('Invalid transcription request.');
  const notes=[],duration=total/RATE,chunks=Math.ceil(duration/CORE);let restoredPassages=0;
  for(let i=0;i<chunks;i++){
   ensureOpen();
   const coreStart=i*CORE,coreEnd=Math.min(duration,coreStart+CORE),start=Math.max(0,coreStart-HALO),end=Math.min(duration,coreEnd+HALO),first=Math.round(start*RATE),last=Math.min(total,Math.round(end*RATE));
   const key='game-'+language+'-'+i,stored=await checkpoint?.read(key);ensureOpen();
   const restored=stored&&stored.model===manifest.id&&stored.steps===STEPS&&stored.first===first&&stored.last===last&&Array.isArray(stored.notes)&&stored.notes.every((n,j)=>Number.isFinite(n.start)&&Number.isFinite(n.end)&&Number.isFinite(n.midi)&&n.midi>=0&&n.midi<=127&&n.start>=0&&n.end-n.start>=.06-1e-6&&n.end<=(last-first)/RATE+.001&&(!j||n.start>=stored.notes[j-1].end-1e-6));
   let candidates;
   onProgress(i/chunks,{passageIndex:i+1,passageCount:chunks,passagesCompleted:i,restoredPassages});
   if(restored){candidates=stored.notes;restoredPassages++;}
   else{
    const pcm=await read(first,last-first);ensureOpen();if(!(pcm instanceof Float32Array)||pcm.length!==last-first)throw Error('Singing audio clock is incomplete.');
    let peak=0;for(const x of pcm){if(!Number.isFinite(x))throw Error('Singing audio contains invalid samples.');peak=Math.max(peak,Math.abs(x));}
    candidates=peak>1e-5?await infer(pcm,language,(2025+i*104729)>>>0,p=>onProgress((i+p)/chunks,{passageIndex:i+1,passageCount:chunks,passagesCompleted:i,restoredPassages})):[];await checkpoint?.write(key,{first,last,model:manifest.id,steps:STEPS,notes:candidates});
   }
   for(const n of candidates){
    const a=start+n.start,b=Math.min(duration,start+n.end);
    // Each chunk owns its core. A note carried in from the left context
    // extends the preceding same-pitch sustain instead of creating a seam
    // attack. Real within-core rearticulations retain separate boundaries.
    if(b<=coreStart||a>=coreEnd)continue;
    const previous=notes[notes.length-1],carry=a<coreStart;
    if(carry&&previous&&previous.end>=coreStart-.04&&Math.abs(previous.midi-n.midi)<.75){previous.end=round(Math.min(coreEnd,b));continue;}
    const na=Math.max(coreStart,a),nb=Math.min(coreEnd,b);
    if(nb>na)notes.push({start:round(na),end:round(nb),midi:Math.round(n.midi*100)/100,source:'game-large',estimated:true,continuation:carry});
   }
   onProgress((i+1)/chunks,{passageIndex:i+1,passageCount:chunks,passagesCompleted:i+1,restoredPassages,checkpointSaved:!!checkpoint});
   // GAME's five graphs are much larger than the compact rhythm model. A
   // bounded reload every four 12-second passages prevents allocator growth
   // from turning a long song into a renderer kill. It does not alter graph
   // inputs, diffusion steps, note filtering, or checkpoint contents.
   if((i+1)%4===0&&i+1<chunks){onProgress((i+1)/chunks,{passageIndex:i+1,passageCount:chunks,passagesCompleted:i+1,restoredPassages,sessionReset:true});await reset();}
  }
  notes.sort((a,b)=>a.start-b.start);for(let i=0;i<notes.length-1;i++)notes[i].end=Math.min(notes[i].end,notes[i+1].start);
  return {notes:notes.filter(n=>n.end-n.start>=.06-1e-6),model:manifest.id,frameSeconds:.01,steps:STEPS,language,sourceClock:'Original decoded PCM',lyricsAligned:false,confidenceIsProbability:false};
 }
 return {manifest,infer,process,release(){
  if(releasePending)return releasePending;released=true;stopChild();
  releasePending=(async()=>{if(activeInference)await Promise.allSettled([activeInference]);await reset();})();
  return releasePending;
 }};
}
function fuse(detail,transcription){
 const notes=[],accents=detail.accents.filter(a=>a.kind==='entrance'),contour={step:.04,midi:new Array(detail.pitchContour.midi.length).fill(0),confidence:new Array(detail.pitchContour.midi.length).fill(0)};
 for(const n of transcription.notes){
  // Two independent checks: learned sung-note presence and actual vocal-source
  // phrasing/classifier evidence. Speech and separation bleed do not become
  // certain singing merely because the pitch model returns a MIDI value.
  const phrase=detail.phrases.find(p=>p.kind!=='speech'&&Math.min(p.end,n.end)-Math.max(p.start,n.start)>=Math.min(.08,(n.end-n.start)*.5));
  if(!phrase)continue;
  const start=Math.max(n.start,phrase.start),end=Math.min(n.end,phrase.end);if(end-start<.06-1e-6)continue;
  const step=detail.envelopeStep||.02;let strength=0,peakTime=start;
  for(let i=Math.floor(start/step);i<Math.ceil(end/step);i++)if((detail.envelope[i]||0)>strength){strength=detail.envelope[i];peakTime=i*step;}
  const note={...n,start:round(start),end:round(end),frequency:round(440*2**((n.midi-69)/12)),confidence:phrase.confidence,strength:round(strength),peakTime:round(Math.min(end,Math.max(start,peakTime))),type:end-start>=.35?'held-note':'note'};
  notes.push(note);if(!n.continuation&&!accents.some(a=>Math.abs(a.time-start)<.06))accents.push({time:note.start,strength:Math.max(.25,note.strength),confidence:phrase.confidence,kind:'sung-note-onset',source:'game-large',estimated:true});
  for(let i=Math.ceil(start/.04);i*.04<end&&i<contour.midi.length;i++){contour.midi[i]=note.midi;contour.confidence[i]=phrase.confidence;}
 }
 // Unvoiced articulations still matter; retain measured source-energy events
 // when they are separated from a neural note onset by at least 80 ms.
 for(const a of detail.accents)if(a.kind!=='entrance'&&!accents.some(b=>Math.abs(a.time-b.time)<.08))accents.push(a);
 return {...detail,notes,accents:accents.sort((a,b)=>a.time-b.time),pitchContour:contour,transcription,method:'GAME Large neural sung-note boundaries and pitches, with separated-source expression and singing/speech evidence',timing:{...detail.timing,pitchFrameMs:10,alignment:'Neural note boundaries on the source PCM clock, gated by separated voice evidence; no word alignment'},diagnostics:{...detail.diagnostics,version:2,noteModel:transcription.model,notes:notes.length,heldNotes:notes.filter(n=>n.type==='held-note').length,neuralCandidates:transcription.notes.length,neuralRejected:transcription.notes.length-notes.length,confidenceMeaning:'Containing voice phrase evidence, not a calibrated GAME note probability'}};
}
root.LightForgeGAME={create,fuse,noise};
if(typeof module!=='undefined'&&module.exports)module.exports=root.LightForgeGAME;
})(typeof self!=='undefined'?self:globalThis);
