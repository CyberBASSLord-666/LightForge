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
async function create({ort,baseUrl,onProgress=()=>{},checkpoint}){
 const sessions={},manifest=await(await fetch(new URL('manifest.json',baseUrl))).json();let loaded=false,released=false;
 async function load(){
  if(released)throw Error('Singing transcription is closed.');if(loaded)return;
  try{for(const name of ['encoder','dur2bd','segmenter','bd2dur','estimator']){onProgress('Loading '+name);sessions[name]=await ort.InferenceSession.create(new URL(name+'.onnx',baseUrl).href,{executionProviders:['wasm'],graphOptimizationLevel:'all',enableCpuMemArena:false,enableMemPattern:false});}loaded=true;}
  catch(e){await Promise.allSettled(Object.values(sessions).map(s=>s.release()));for(const name of Object.keys(sessions))delete sessions[name];throw e;}
 }
 const tensor=(type,data,dims)=>new ort.Tensor(type,data,dims);
 async function infer(pcm,language,seed,onStep=()=>{}){
  await load();
  const owned=[],own=t=>(owned.push(t),t);let encoded,known,previous,timing,estimated;
  try{
   encoded=await sessions.encoder.run({waveform:own(tensor('float32',pcm,[1,pcm.length])),duration:own(tensor('float32',Float32Array.of(pcm.length/RATE),[1]))});onStep(1/(STEPS+2));
   known=await sessions.dur2bd.run({durations:own(tensor('float32',Float32Array.of(pcm.length/RATE),[1,1])),maskT:encoded.maskT});
   const lang=own(tensor('int64',BigInt64Array.of(BigInt(language)),[1])),threshold=own(tensor('float32',Float32Array.of(.2),[])),radius=own(tensor('int64',BigInt64Array.of(2n),[]));
   for(let k=0;k<STEPS;k++){
    const time=tensor('float32',Float32Array.of(k/STEPS),[1]),random=tensor('float32',noise(encoded.maskT.data.length,(seed+k*2654435761)>>>0),encoded.maskT.dims);
    let next;try{next=await sessions.segmenter.run({x_seg:encoded.x_seg,maskT:encoded.maskT,known_boundaries:known.boundaries,prev_boundaries:previous?.boundaries||known.boundaries,language:lang,threshold,radius,t:time,random_uniform:random});}finally{time.dispose();random.dispose();}
    free(previous);previous=next;onStep((k+2)/(STEPS+2));
   }
   timing=await sessions.bd2dur.run({boundaries:previous.boundaries,maskT:encoded.maskT});
   estimated=await sessions.estimator.run({x_est:encoded.x_est,boundaries:previous.boundaries,maskT:encoded.maskT,maskN:timing.maskN,threshold});
   const result=[];let start=0;
   for(let i=0;i<timing.durations.data.length;i++){const length=timing.durations.data[i],end=start+length,midi=estimated.scores.data[i];if(!Number.isFinite(length)||length<0||!Number.isFinite(midi))throw Error('Singing transcription returned invalid note data.');if(timing.maskN.data[i]&&estimated.presence.data[i]&&length>=.06&&midi>=0&&midi<=127)result.push({start,end,midi});start=end;}
   onStep(1);return result;
  }finally{free(encoded);free(known);free(previous);free(timing);free(estimated);owned.forEach(t=>t.dispose());}
 }
 return {manifest,infer,async process(read,total,{language=0,onProgress=()=>{}}={}){
  if(released)throw Error('Singing transcription is closed.');
  if(![0,1,2,3,4].includes(language)||!Number.isSafeInteger(total)||total<1||total>RATE*14401)throw Error('Invalid transcription request.');
  const notes=[],duration=total/RATE,chunks=Math.ceil(duration/CORE);let restoredPassages=0;
  for(let i=0;i<chunks;i++){
   const coreStart=i*CORE,coreEnd=Math.min(duration,coreStart+CORE),start=Math.max(0,coreStart-HALO),end=Math.min(duration,coreEnd+HALO),first=Math.round(start*RATE),last=Math.min(total,Math.round(end*RATE));
   const key='game-'+language+'-'+i,stored=await checkpoint?.read(key);
   const restored=stored&&stored.model===manifest.id&&stored.steps===STEPS&&stored.first===first&&stored.last===last&&Array.isArray(stored.notes)&&stored.notes.every((n,j)=>Number.isFinite(n.start)&&Number.isFinite(n.end)&&Number.isFinite(n.midi)&&n.midi>=0&&n.midi<=127&&n.start>=0&&n.end-n.start>=.06-1e-6&&n.end<=(last-first)/RATE+.001&&(!j||n.start>=stored.notes[j-1].end-1e-6));
   let candidates;
   onProgress(i/chunks,{passageIndex:i+1,passageCount:chunks,passagesCompleted:i,restoredPassages});
   if(restored){candidates=stored.notes;restoredPassages++;}
   else{
    const pcm=await read(first,last-first);if(!(pcm instanceof Float32Array)||pcm.length!==last-first)throw Error('Singing audio clock is incomplete.');
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
  }
  notes.sort((a,b)=>a.start-b.start);for(let i=0;i<notes.length-1;i++)notes[i].end=Math.min(notes[i].end,notes[i+1].start);
  return {notes:notes.filter(n=>n.end-n.start>=.06-1e-6),model:manifest.id,frameSeconds:.01,steps:STEPS,language,sourceClock:'Original decoded PCM',lyricsAligned:false,confidenceIsProbability:false};
 },async release(){if(released)return;released=true;await Promise.allSettled(Object.values(sessions).map(s=>s.release()));for(const name of Object.keys(sessions))delete sessions[name];}};
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
