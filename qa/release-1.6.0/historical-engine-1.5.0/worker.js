/* Cancellable composition and durable frame snapshots, isolated from the UI. */
'use strict';
importScripts('vehicle-profile.js','movement-planner.js','light-planner.js','show-engine.js');
const MAX_FRAMES=960000, CHANNELS=200;
const canonical=value=>JSON.stringify(value,(_,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.keys(item).sort().map(key=>[key,item[key]])):item);
const progress=(value,detail)=>postMessage({type:'progress',value:{progress:value,stage:'generate',detail}});
async function digest(bytes){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');}
function base64(bytes){let s='';for(let p=0;p<bytes.length;p+=24576)s+=String.fromCharCode(...bytes.subarray(p,p+24576));return btoa(s);}
function unbase64(text){if(typeof text!=='string'||text.length>48*1024*1024)throw Error('The saved show is too large or damaged.');const s=atob(text),bytes=new Uint8Array(s.length);for(let i=0;i<s.length;i++)bytes[i]=s.charCodeAt(i);return bytes;}
async function compressed(bytes){
 let p=0;const source=new ReadableStream({pull(controller){if(p>=bytes.length){controller.close();return;}const next=Math.min(bytes.length,p+65536);controller.enqueue(bytes.subarray(p,next));p=next;}});
 return new Uint8Array(await new Response(source.pipeThrough(new CompressionStream('gzip'))).arrayBuffer());
}
async function expand(bytes,expected){
 const output=new Uint8Array(expected),reader=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip')).getReader();let p=0;
 try{for(;;){const {done,value}=await reader.read();if(done)break;if(p+value.length>expected)throw Error('The saved show expands beyond its declared size.');output.set(value,p);p+=value.length;}}finally{await reader.cancel().catch(()=>{});}
 if(p!==expected)throw Error('The saved show data ended unexpectedly.');return output;
}
async function inputDigest(music,settings){return digest(new TextEncoder().encode(canonical({music,settings})));}
async function encode(show,music,settings){
 if(typeof CompressionStream==='undefined')throw Error('Update Android System WebView to save and reopen compiled shows.');
 const frameData=await compressed(show.frames);if(frameData.length>32*1024*1024)throw Error('This compiled show exceeds the project storage limit. Choose a shorter track.');
 const meta={...show};delete meta.frames;delete meta.previewIndex;
 return {format:'lightforge-gzip-frames-v1',engineVersion:show.version,frameCount:show.frameCount,channels:200,stepMs:show.stepMs,sha256:await digest(show.frames),inputDigest:await inputDigest(music,settings),frameData:base64(frameData),metaSHA256:await digest(new TextEncoder().encode(canonical(meta))),meta};
}
async function restore(compiled,music,settings){
 if(!compiled||compiled.format!=='lightforge-gzip-frames-v1'||!Number.isInteger(compiled.frameCount)||compiled.frameCount<1||compiled.frameCount>MAX_FRAMES||compiled.channels!==CHANNELS||![15,20].includes(compiled.stepMs))throw Error('The saved compiled show has an unsupported format.');
 const currentInputDigest=await inputDigest(music,settings);let migrated=false;
 if(compiled.inputDigest!==currentInputDigest){
  // 1.5 adds two composition defaults. Verify the original 1.4 inputs before
  // rebinding its unchanged frames to those defaults; any actual edit still fails.
  const priorSettings={...settings};delete priorSettings.vocalFocus;delete priorSettings.bassFocus;
  if(compiled.engineVersion==='1.4.0'&&settings.vocalFocus===.85&&settings.bassFocus===.9&&compiled.inputDigest===await inputDigest(music,priorSettings))migrated=true;
  else throw Error('The saved show does not match its music and edits. Create again to rebuild it.');
 }
 if(compiled.metaSHA256!==await digest(new TextEncoder().encode(canonical(compiled.meta))))throw Error('The saved show metadata checksum failed. Restore a previous project revision.');
 const frames=await expand(unbase64(compiled.frameData),compiled.frameCount*CHANNELS);
 if(await digest(frames)!==compiled.sha256)throw Error('The saved show checksum failed. Restore a previous project revision.');
 const show={...compiled.meta,frames,frameCount:compiled.frameCount,channels:CHANNELS,channelCount:CHANNELS,stepMs:compiled.stepMs,duration:compiled.frameCount*compiled.stepMs/1000,audioDuration:music.duration,settings:ShowEngine.normalizeSettings(settings)};delete show.previewIndex;
 show.validation=ShowEngine.validate(show,music);if(!show.validation.valid)throw Error('The saved show failed current format checks: '+show.validation.errors.join(' '));
 if(ShowEngine.preparePreview)ShowEngine.preparePreview(show);
 if(migrated){compiled.inputDigest=currentInputDigest;compiled.settingsMigration={from:'1.4.0',to:'1.5.0',addedDefaults:['vocalFocus','bassFocus'],framesPreserved:true};}
 return show;
}
self.onmessage=async({data})=>{try{
 progress(.04,data.action==='restore'?'Verifying your saved arrangement…':'Planning musical phrases and movement arrivals…');
 let show,compiled;
 if(data.action==='restore'){compiled=data.compiled;show=await restore(compiled,data.music,data.settings);}
 else{show=ShowEngine.generate(data.music,data.settings);progress(.78,'Saving an exact, checked copy of your arrangement…');compiled=await encode(show,data.music,data.settings);}
 const header=ShowEngine.fseqHeader(show,'lightshow.wav');progress(1,'Arrangement ready');postMessage({type:'result',value:{show,compiled,header}},[show.frames.buffer,header.buffer]);
}catch(error){postMessage({type:'error',message:error.message||String(error)});}};
