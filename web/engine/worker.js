/* Cancellable composition and durable frame snapshots, isolated from the UI. */
'use strict';
importScripts('../version.js','../analysis/resource-diagnostics.js','../analysis/telemetry.js','../analysis/semantic-timeline.js','../analysis/vocal-semantics.js','../analysis/salience.js','../analysis/recurrence.js','vehicle-profile.js','movement-planner.js','light-planner.js','music-cues.js','sync-review.js','choreography-quality.js','semantic-choreography.js','motif-evolution.js','vocal-choreography.js','perceptual-validation.js','show-engine.js');
const MAX_FRAMES=960000, CHANNELS=200;
const canonical=value=>JSON.stringify(value,(_,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.keys(item).sort().map(key=>[key,item[key]])):item);
const progress=(value,detail)=>postMessage({type:'progress',value:{progress:value,stage:'generate',detail}});
const restoreEvent=(lease,type,detail={})=>{if(lease&&typeof lease.jobId==='string'&&typeof lease.nonce==='string')postMessage({type,lease:{jobId:lease.jobId,nonce:lease.nonce},...detail});};
const pause=()=>new Promise(resolve=>setTimeout(resolve,0));
async function digest(bytes){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');}
function base64(bytes){let s='';for(let p=0;p<bytes.length;p+=24576)s+=String.fromCharCode(...bytes.subarray(p,p+24576));return btoa(s);}
async function unbase64(text,pulse){if(typeof text!=='string'||text.length>48*1024*1024)throw Error('The saved show is too large or damaged.');const s=atob(text),bytes=new Uint8Array(s.length);for(let i=0;i<s.length;i++){bytes[i]=s.charCodeAt(i);if(i&&i%524288===0){pulse?.('decode-base64',i,s.length);await pause();}}pulse?.('decode-base64',s.length,s.length);return bytes;}
async function compressed(bytes){
 let p=0;const source=new ReadableStream({pull(controller){if(p>=bytes.length){controller.close();return;}const next=Math.min(bytes.length,p+65536);controller.enqueue(bytes.subarray(p,next));p=next;}});
 return new Uint8Array(await new Response(source.pipeThrough(new CompressionStream('gzip'))).arrayBuffer());
}
async function expand(bytes,expected,pulse){
 const output=new Uint8Array(expected),reader=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip')).getReader();let p=0;
 try{for(;;){const {done,value}=await reader.read();if(done)break;if(p+value.length>expected)throw Error('The saved show expands beyond its declared size.');output.set(value,p);p+=value.length;pulse?.('expand-frames',p,expected);}}finally{await reader.cancel().catch(()=>{});}
 if(p!==expected)throw Error('The saved show data ended unexpectedly.');return output;
}
async function inputDigest(music,settings){return digest(new TextEncoder().encode(canonical({music,settings})));}
async function encode(show,music,settings){
 if(typeof CompressionStream==='undefined')throw Error('Update Android System WebView to save and reopen compiled shows.');
 const frameData=await compressed(show.frames);if(frameData.length>32*1024*1024)throw Error('This compiled show exceeds the project storage limit. Choose a shorter track.');
 const meta={...show};delete meta.frames;delete meta.previewIndex;
 return {format:'lightforge-gzip-frames-v1',engineVersion:show.version,frameCount:show.frameCount,channels:200,stepMs:show.stepMs,sha256:await digest(show.frames),inputDigest:await inputDigest(music,settings),frameData:base64(frameData),metaSHA256:await digest(new TextEncoder().encode(canonical(meta))),meta};
}
async function restore(compiled,music,settings,pulse=()=>{},timing=null){
 if(!compiled||compiled.format!=='lightforge-gzip-frames-v1'||!Number.isInteger(compiled.frameCount)||compiled.frameCount<1||compiled.frameCount>MAX_FRAMES||compiled.channels!==CHANNELS||![15,20].includes(compiled.stepMs))throw Error('The saved compiled show has an unsupported format.');
 pulse('input-digest');
 const currentInputDigest=await inputDigest(music,settings);let migration=null;
 if(compiled.inputDigest!==currentInputDigest){
  // Default-only upgrades must reproduce a prior exact input checksum.
  // Never replace frames or relax checksum validation to accept a changed edit.
  const priorSettings={...settings},addedDefaults=[];
  const supported=['1.4.0','1.5.0','1.6.0'].includes(compiled.engineVersion);
  let matched=false;
  if(supported){
   for(const [key,value] of [['musicCues',[]],['vocalOffsetMs',0],['bassOffsetMs',0]]){
    if(Object.prototype.hasOwnProperty.call(priorSettings,key)&&canonical(priorSettings[key])===canonical(value)){
     delete priorSettings[key];addedDefaults.push(key);
    }
   }
   matched=compiled.inputDigest===await inputDigest(music,priorSettings);
   if(!matched&&['1.4.0','1.5.0'].includes(compiled.engineVersion)&&Array.isArray(priorSettings.vocalRegions)&&priorSettings.vocalRegions.length===0){
    delete priorSettings.vocalRegions;addedDefaults.push('vocalRegions');matched=compiled.inputDigest===await inputDigest(music,priorSettings);
   }
   if(!matched&&compiled.engineVersion==='1.4.0'&&priorSettings.vocalFocus===.85&&priorSettings.bassFocus===.9){
    delete priorSettings.vocalFocus;delete priorSettings.bassFocus;addedDefaults.push('vocalFocus','bassFocus');
    matched=compiled.inputDigest===await inputDigest(music,priorSettings);
   }
  }
  if(!matched)throw Error('The saved show does not match its music and edits. Create again to rebuild it.');
  migration={from:compiled.engineVersion,to:ShowEngine.version,addedDefaults,framesPreserved:true};
  if(compiled.settingsMigration)migration.previous=compiled.settingsMigration;
 }
 pulse('metadata-digest');
 if(compiled.metaSHA256!==await digest(new TextEncoder().encode(canonical(compiled.meta))))throw Error('The saved show metadata checksum failed. Restore a previous project revision.');
 const frameBytes=compiled.frameCount*CHANNELS;
 pulse('decode-base64',0,frameBytes);
 const frames=await expand(await unbase64(compiled.frameData,pulse),frameBytes,pulse);
 pulse('frame-digest');
 if(await digest(frames)!==compiled.sha256)throw Error('The saved show checksum failed. Restore a previous project revision.');
 const show={...compiled.meta,frames,frameCount:compiled.frameCount,channels:CHANNELS,channelCount:CHANNELS,stepMs:compiled.stepMs,duration:compiled.frameCount*compiled.stepMs/1000,audioDuration:music.duration,settings:ShowEngine.normalizeSettings(settings)};delete show.previewIndex;
 pulse('validate-show');
 show.validation=ShowEngine.validate(show,music,timing);if(show.synchronization)show.validation.synchronization=show.synchronization;if(!show.validation.valid)throw Error('The saved show failed current format checks: '+show.validation.errors.join(' '));
 pulse('prepare-preview');
 if(ShowEngine.preparePreview)ShowEngine.preparePreview(show);
 // Rebind only after metadata, decompression, payload hash, physical format and
 // preview preparation have all succeeded. Failed restores leave recovery data
 // and its original checksum untouched.
 if(migration){compiled.inputDigest=currentInputDigest;compiled.settingsMigration=migration;}
 return show;
}
// Header bytes are generated here, while the already realized frame buffer is
// transferred separately. This is not a measurement of full FSEQ assembly or
// native export, and project gzip/digests are not FSEQ generation.
const compilerProfile=(timing,action,outcome)=>timing.snapshot({action:action==='restore'?'restore':'generate',outcome,
 timingContract:'compiler-phases-v1',phaseAccounting:'sequential-selected-boundaries',
 fseqGenerationScope:'header-only',fseqPayloadAssembly:'not-executed'});
 self.onmessage=async({data})=>{const lease=data.action==='restore'?data.restoreLease:null,timing=LightForgeAnalysisTelemetry.create('compiler');try{
 if(lease)restoreEvent(lease,'restore-started');
 progress(.04,data.action==='restore'?'Verifying your saved arrangement…':'Planning musical phrases and movement arrivals…');
 let show,compiled;
 if(data.action==='restore'){compiled=data.compiled;show=await restore(compiled,data.music,data.settings,(phase,completed,total)=>restoreEvent(lease,'restore-pulse',{phase,completed,total}),timing);restoreEvent(lease,'restore-verified',{sha256:compiled.sha256});}
 else{show=ShowEngine.generate(data.music,data.settings,timing);progress(.78,'Saving an exact, checked copy of your arrangement…');compiled=await encode(show,data.music,data.settings);}
 const header=ShowEngine.fseqHeader(show,'lightshow.wav',timing),profile=compilerProfile(timing,data.action,'completed');progress(1,'Arrangement ready');postMessage({type:'result',value:{show,compiled,header,profile}},[show.frames.buffer,header.buffer]);
}catch(error){const message=String(error.message||error).slice(0,3072);if(lease)restoreEvent(lease,'restore-error',{message});postMessage({type:'error',message,stack:typeof error.stack==='string'?error.stack.slice(0,8192):undefined,profile:compilerProfile(timing,data.action,'failed')});}};
