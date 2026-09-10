/* Mel-Band RoFormer Deux, original Float32 inference from FP16 author weights.
 * Integration MIT; model and converted weights CC BY-NC 4.0, becruily.
 * Full 13-second context; exact attention split along queries (no truncation).
 * Independent band/frame batches bound attention intermediates on Android.
 */
(function(root){'use strict';
const RATE=44100,NFFT=2048,HOP=441,FRAMES=1301,SAMPLES=573300,HALO=66150,CORE=441000,STRIDE=220500;
function localStageClock(){
 const finite=value=>typeof value==='number'&&Number.isFinite(value)?value:null;
 const read=(object,key)=>{try{return object==null?undefined:object[key];}catch(_){return undefined;}};
 const select=key=>{const receiver=read(root,key),callable=read(receiver,'now');if(typeof callable!=='function')return null;try{const value=finite(callable.call(receiver));return value===null?null:{receiver,callable,value};}catch(_){return null;}};
 const performance=select('performance'),selected=performance||select('Date'),start=selected?.value??0;let last=start,unavailable=!selected;
 const now=()=>{if(unavailable)return null;try{const value=finite(selected.callable.call(selected.receiver));if(value===null||value<last){unavailable=true;return null;}last=value;return value;}catch(_){unavailable=true;return null;}};
 return {start,seconds:()=>{const end=now();return end===null?0:Math.max(0,end-start)/1000;}};
}
function stageClock(){
 let factory;try{factory=root.LightForgeDiagnosticClock;}catch(_){factory=null;}
 if(factory&&typeof factory.create==='function')try{const clock=factory.create(root);if(clock&&typeof clock.measure==='function'&&typeof clock.source==='string'&&Number.isFinite(clock.start)){const mark={milliseconds:clock.start,source:clock.source};return {start:mark,seconds:()=>{try{const result=clock.measure(mark);return result?.measured&&Number.isFinite(result.milliseconds)?Math.max(0,result.milliseconds)/1000:0;}catch(_){return 0;}}};}}catch(_){}
 return localStageClock();
}
class Transform{
 constructor(){this.fft=new root.LightForgeDSP.FFT(NFFT);this.re=new Float64Array(NFFT);this.im=new Float64Array(NFFT);this.window=Float64Array.from({length:NFFT},(_,i)=>.5-.5*Math.cos(2*Math.PI*i/NFFT));this.norm=new Float64Array(SAMPLES+NFFT);for(let f=0;f<FRAMES;f++)for(let i=0;i<NFFT;i++)this.norm[f*HOP+i]+=this.window[i]**2;}
 encode(stereo){const spectrum=new Float32Array(2050*FRAMES*2),{re,im,window}=this;
  for(let c=0;c<2;c++)for(let f=0;f<FRAMES;f++){
   const start=f*HOP-NFFT/2;for(let i=0;i<NFFT;i++){let at=start+i;if(at<0)at=-at;if(at>=SAMPLES)at=2*SAMPLES-at-2;const v=stereo[c][at];if(!Number.isFinite(v))throw Error('Invalid source audio for studio separation.');re[i]=v*window[i];im[i]=0;}this.fft.run(re,im);
   for(let b=0;b<=NFFT/2;b++){const at=((b*2+c)*FRAMES+f)*2;spectrum[at]=re[b];spectrum[at+1]=im[b];}
  }return spectrum;
 }
 decode(spectrum,mask,manifest){
  if(mask.length!==manifest.indices.length*FRAMES*2)throw Error('Studio separator returned an invalid mask.');
  const summed=new Float32Array(spectrum.length),{re,im,window}=this;
  for(let j=0;j<manifest.indices.length;j++){const dst=manifest.indices[j]*FRAMES*2,src=j*FRAMES*2;for(let i=0;i<FRAMES*2;i++)summed[dst+i]+=mask[src+i];}
  const pcm=new Float32Array(SAMPLES+NFFT);
  for(let c=0;c<2;c++)for(let f=0;f<FRAMES;f++){
   re.fill(0);im.fill(0);for(let b=0;b<=NFFT/2;b++){const at=((b*2+c)*FRAMES+f)*2,d=manifest.bandsPerFrequency[b],ar=spectrum[at],ai=spectrum[at+1],mr=summed[at]/Math.max(1e-8,d),mi=summed[at+1]/Math.max(1e-8,d),r=ar*mr-ai*mi,v=ar*mi+ai*mr;if(!Number.isFinite(r)||!Number.isFinite(v))throw Error('Studio separation produced invalid audio.');re[b]=r;im[b]=v;if(b&&b<NFFT/2){re[NFFT-b]=r;im[NFFT-b]=-v;}}
   this.fft.run(re,im,true);for(let i=0;i<NFFT;i++)pcm[f*HOP+i]+=re[i]*window[i]*.5;
  }
  const out=new Float32Array(SAMPLES);for(let i=0;i<SAMPLES;i++)out[i]=pcm[i+NFFT/2]/Math.max(1e-12,this.norm[i+NFFT/2]);return out;
 }
}
async function create({ort,baseUrl,onProgress=()=>{},checkpoint,nativePredict}){
 const manifest=await(await fetch(new URL('manifest.json',baseUrl))).json(),transform=new Transform();let closed=false,session=null,sessionName=null;
 if(manifest.execution!=='bounded-independent-batches-v1'||manifest.headFrames!==128||manifest.frames!==FRAMES||manifest.samples!==SAMPLES||manifest.indices.length!==3958||manifest.bandsPerFrequency.length!==1025)throw Error('Studio separation model configuration is invalid.');
 async function releaseStage(){const previous=session;session=null;sessionName=null;if(previous)await previous.release();}
 async function stage(name,input){
  if(closed)throw Error('Studio separation is closed.');
  if(sessionName!==name){await releaseStage();session=await ort.InferenceSession.create(new URL(name+'.onnx',baseUrl).href,{executionProviders:['wasm'],graphOptimizationLevel:'all',enableCpuMemArena:false,enableMemPattern:false});sessionName=name;}
  return (await session.run({input})).output;
 }
 async function boundedBlock(values,index,progress){
  const name='block-'+String(index).padStart(2,'0');
  for(let first=0;first<60;first+=4){
   const count=Math.min(4,60-first),data=new Float32Array(count*FRAMES*256);
   for(let b=0;b<count;b++)for(let f=0;f<FRAMES;f++)data.set(values.subarray((f*60+first+b)*256,(f*60+first+b+1)*256),(b*FRAMES+f)*256);
   const input=new ort.Tensor('float32',data,[count,FRAMES,256]);let output;
   try{output=await stage(name+'-time',input);for(let b=0;b<count;b++)for(let f=0;f<FRAMES;f++)values.set(output.data.subarray((b*FRAMES+f)*256,(b*FRAMES+f+1)*256),(f*60+first+b)*256);}
   finally{input.dispose();output?.dispose();}progress(.75*(first+count)/60);
  }
  for(let first=0;first<FRAMES;first+=128){
   const count=Math.min(128,FRAMES-first),input=new ort.Tensor('float32',values.slice(first*60*256,(first+count)*60*256),[count,60,256]);let output;
   try{output=await stage(name+'-frequency',input);values.set(output.data,first*60*256);}finally{input.dispose();output?.dispose();}
   progress(.75+.25*(first+count)/FRAMES);
  }
 }
 async function predict(stereo,progress=()=>{}){
  const spectrum=transform.encode(stereo),input=new ort.Tensor('float32',spectrum,[1,2050,FRAMES,2]);let front,values;
  try{front=await stage('front',input);values=Float32Array.from(front.data);}finally{input.dispose();front?.dispose();}progress(1/15);
  for(let i=0;i<12;i++)await boundedBlock(values,i,p=>progress((1+i+p)/15));
  const out={};
  try{for(let role=0;role<2;role++){
   const mask=new Float32Array(manifest.indices.length*FRAMES*2);
   for(let first=0;first<FRAMES;first+=128){
    const count=Math.min(128,FRAMES-first),input=new ort.Tensor('float32',values.slice(first*60*256,(first+count)*60*256),[1,count,60,256]);let y;
    try{
     y=await stage('head-'+role,input);
     if(y.data.length!==manifest.indices.length*count*2)throw Error('Studio separator returned an invalid mask batch.');
     for(let bin=0;bin<manifest.indices.length;bin++)mask.set(y.data.subarray(bin*count*2,(bin+1)*count*2),(bin*FRAMES+first)*2);
    }finally{input.dispose();y?.dispose();}
    progress((13+role+(first+count)/FRAMES)/15);
   }
   // Model creation temporarily copies weights. Release each large head before
   // decoding or opening the next one, and never carry it into another passage.
   await releaseStage();out[role===0?'vocals':'accompaniment']=transform.decode(spectrum,mask,manifest);
  }return out;}finally{await releaseStage();}
 }
 return {manifest,predict,async process(read,total,onChunk,onProgress=()=>{}){
  if(!Number.isSafeInteger(total)||total<1||total>RATE*14401)throw Error('Invalid studio separation length.');
  let pending=null,emitted=0,chunks=0,restoredPassages=0;const timing=stageClock(),passageCount=1+Math.max(0,Math.ceil((total-CORE)/STRIDE));
  for(let start=0;start<total;start+=STRIDE){
   if(closed)throw Error('Studio separation is closed.');
   const keep=Math.min(CORE,total-start),last=start+CORE>=total,stereo=await read(start-HALO,SAMPLES);
   if(!Array.isArray(stereo)||stereo.length!==2||stereo.some(x=>!(x instanceof Float32Array)||x.length!==SAMPLES))throw Error('Studio separation requires complete stereo chunks.');
   let peak=0;for(const channel of stereo)for(const x of channel)peak=Math.max(peak,Math.abs(x));
   const key='deux-'+start,cached=await checkpoint?.readFloats(key);
   const restored=cached?.length===2&&cached.every(a=>a instanceof Float32Array&&a.length===SAMPLES&&a.every(Number.isFinite));
   const report=(p,extra={})=>onProgress({progress:Math.min(1,(start+(last?keep:STRIDE)*p)/total),processedSeconds:start/RATE,passageIndex:chunks+1,passageCount,passagesCompleted:chunks,restoredPassages,checkpointSaved:false,message:'Studio · passage '+(chunks+1)+' of '+passageCount+' · '+Math.round(p*100)+'%',...extra});
   report(0);
   const estimated=restored?{vocals:cached[0],accompaniment:cached[1]}:peak<1e-7?{vocals:new Float32Array(SAMPLES),accompaniment:new Float32Array(SAMPLES)}:nativePredict?await nativePredict(start-HALO,p=>report(p)):await predict(stereo,p=>report(p));
   if(['vocals','accompaniment'].some(role=>!(estimated?.[role] instanceof Float32Array)||estimated[role].length!==SAMPLES||!estimated[role].every(Number.isFinite)))throw Error('Studio separation returned invalid passage audio.');
   let checkpointSaved=restored;
   if(restored)restoredPassages++;
   else if(checkpoint&&peak>=1e-7){await checkpoint.writeFloats(key,[estimated.vocals,estimated.accompaniment]);checkpointSaved=true;}
   const core={};for(const role of ['vocals','accompaniment']){core[role]=estimated[role].slice(HALO,HALO+keep);if(pending){const overlap=Math.min(pending[role].length,keep);for(let i=0;i<overlap;i++){const weight=.5-.5*Math.cos(Math.PI*(i+.5)/STRIDE);core[role][i]=pending[role][i]*(1-weight)+core[role][i]*weight;}}}
   const count=last?keep:STRIDE;if(start!==emitted)throw Error('Studio separation lost the source clock.');
   await onChunk({vocals:core.vocals.slice(0,count),accompaniment:core.accompaniment.slice(0,count),startSample:start,sampleRate:RATE});emitted+=count;chunks++;pending=last?null:{vocals:core.vocals.slice(STRIDE),accompaniment:core.accompaniment.slice(STRIDE)};
   onProgress({progress:emitted/total,processedSeconds:emitted/RATE,passageIndex:chunks,passageCount,passagesCompleted:chunks,restoredPassages,checkpointSaved,message:restored?'Restored completed passage '+chunks+' of '+passageCount:'Studio · passage '+chunks+' of '+passageCount+' complete'});if(last)break;
  }
  if(emitted!==total)throw Error('Studio separation ended before the audio.');
  return {name:'Mel-Band RoFormer Deux',modelId:manifest.id,modelSha256:manifest.checkpointSHA256,runtime:nativePredict?'onnxruntime-android-cpu':'onnxruntime-web-wasm',sourceSeparated:true,sampleRate:RATE,sourceChannels:2,stems:['vocals','accompaniment'],method:'Dual trained stereo source separation; Float32 bounded transformer with complete attention',contextSeconds:13,coreSeconds:10,overlapSeconds:5,chunks,restoredPassages,estimated:true,analysisSeconds:timing.seconds(),alignment:'Original PCM clock; centered STFT and normalized overlap-add with complementary chunk crossfades',limitations:['Vocal and instrumental estimates can contain bleed; neither is an isolated bass instrument.','Lead and backing singers share one vocal source; no lyrics or word alignment.']};
 },async release(){if(closed)return;closed=true;await releaseStage();}};
}
root.LightForgeDeux={create,Transform};if(typeof module!=='undefined'&&module.exports)module.exports=root.LightForgeDeux;
})(typeof self!=='undefined'?self:globalThis);
