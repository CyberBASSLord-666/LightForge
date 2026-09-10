/* Mel-Band RoFormer Deux, original Float32 inference from FP16 author weights.
 * Integration MIT; model and converted weights CC BY-NC 4.0, becruily.
 * Full 13-second context; exact attention split along queries (no truncation).
 * Independent band/frame batches bound attention intermediates on Android.
 */
(function(root){'use strict';
const RATE=44100,NFFT=2048,HOP=441,FRAMES=1301,SAMPLES=573300,HALO=66150,CORE=441000,STRIDE=220500;
const SPECTRUM_GROUPS=(NFFT/2+1)*2,COMPLEX=2;
// Adjacent passage starts differ by exactly 500 hops. The surrounding three
// frames on each input use local reflection, so they must always be recomputed.
// These are deliberately derived from the transform geometry rather than tuned.
const REUSE_SOURCE_FIRST=3+STRIDE/HOP,REUSE_SOURCE_LAST=FRAMES-4;
const REUSE_TARGET_FIRST=3,REUSE_FRAMES=REUSE_SOURCE_LAST-REUSE_SOURCE_FIRST+1;
function monotonicNow(){return typeof performance!=='undefined'&&typeof performance.now==='function'?performance.now():Date.now();}
function finite(value){return Number.isFinite(value)?value:null;}
class PerformanceProfile{
 constructor(){this.started=monotonicNow();this.spans=new Map();this.counters=new Map();const heap=globalThis.performance?.memory?.usedJSHeapSize;this.startHeap=finite(heap);}
 begin(name,scope=''){return {name,scope:String(scope||''),started:monotonicNow()};}
 end(token){if(!token||typeof token.name!=='string')return;const elapsed=Math.max(0,monotonicNow()-token.started),entry=this.spans.get(token.name)||{name:token.name,count:0,totalMs:0,minMs:Infinity,maxMs:0,scopes:new Map()};entry.count++;entry.totalMs+=elapsed;entry.minMs=Math.min(entry.minMs,elapsed);entry.maxMs=Math.max(entry.maxMs,elapsed);if(token.scope){const scope=entry.scopes.get(token.scope)||{count:0,totalMs:0};scope.count++;scope.totalMs+=elapsed;entry.scopes.set(token.scope,scope);}this.spans.set(token.name,entry);}
 increment(name,amount=1){if(!Number.isFinite(amount))return;this.counters.set(name,(this.counters.get(name)||0)+amount);}
 cache(name,outcome){this.increment('cache.'+name+'.'+String(outcome||'unknown'));}
 snapshot(extra={}){const heap=finite(globalThis.performance?.memory?.usedJSHeapSize),segments=Array.from(this.spans.values(),entry=>({name:entry.name,count:entry.count,totalMs:entry.totalMs,minMs:entry.minMs===Infinity?0:entry.minMs,maxMs:entry.maxMs,scopes:Array.from(entry.scopes.entries(),([name,value])=>({name,...value})).sort((a,b)=>a.name.localeCompare(b.name))})).sort((a,b)=>a.name.localeCompare(b.name)),counters=Object.fromEntries(Array.from(this.counters.entries()).sort(([a],[b])=>a.localeCompare(b)));return {schema:1,wallClockMs:Math.max(0,monotonicNow()-this.started),segments,counters,resources:{wallClockMs:{available:true},cpuTimeMs:{available:false,reason:'The browser worker exposes no portable CPU-time counter.'},heapBytes:heap===null?{available:false,reason:'performance.memory is unavailable.'}:{available:true,start:this.startHeap,end:heap,delta:this.startHeap===null?null:heap-this.startHeap},acceleratorUtilization:{available:false,reason:'The WebAssembly runtime exposes no portable accelerator-utilization counter.'}},...extra};}
}
function profileAdapter(observer){
 const call=(method,...args)=>{try{return typeof observer?.[method]==='function'?observer[method](...args):undefined;}catch(_){return undefined;}};
 return {begin:(name,scope)=>call('begin',name,scope),end:token=>call('end',token),increment:(name,amount)=>call('increment',name,amount),cache:(name,outcome)=>call('cache',name,outcome)};
}
function measured(profile,name,scope,work){const token=profile.begin(name,scope);try{return work();}finally{profile.end(token);}}
async function measuredAsync(profile,name,scope,work){const token=profile.begin(name,scope);try{return await work();}finally{profile.end(token);}}
class Transform{
 constructor(){this.fft=new root.LightForgeDSP.FFT(NFFT);this.re=new Float64Array(NFFT);this.im=new Float64Array(NFFT);this.window=Float64Array.from({length:NFFT},(_,i)=>.5-.5*Math.cos(2*Math.PI*i/NFFT));this.norm=new Float64Array(SAMPLES+NFFT);for(let f=0;f<FRAMES;f++)for(let i=0;i<NFFT;i++)this.norm[f*HOP+i]+=this.window[i]**2;}
 encodeFrames(stereo,spectrum,first,last){const {re,im,window}=this;
  for(let c=0;c<2;c++)for(let f=first;f<last;f++){
   const start=f*HOP-NFFT/2;for(let i=0;i<NFFT;i++){let at=start+i;if(at<0)at=-at;if(at>=SAMPLES)at=2*SAMPLES-at-2;const v=stereo[c][at];if(!Number.isFinite(v))throw Error('Invalid source audio for studio separation.');re[i]=v*window[i];im[i]=0;}this.fft.run(re,im);
   for(let b=0;b<=NFFT/2;b++){const at=((b*2+c)*FRAMES+f)*2;spectrum[at]=re[b];spectrum[at+1]=im[b];}
  }
 }
 encode(stereo){return this.encodeWithReuse(stereo).spectrum;}
 encodeWithReuse(stereo,reusableSpectrum,measurePhase){
  const measure=typeof measurePhase==='function'?measurePhase:(_name,work)=>work();
  const reusable=reusableSpectrum instanceof Float32Array&&reusableSpectrum.length===SPECTRUM_GROUPS*FRAMES*COMPLEX;
  const spectrum=reusable?reusableSpectrum:measure('spectrum.allocate',()=>new Float32Array(SPECTRUM_GROUPS*FRAMES*COMPLEX));
  if(!reusable){measure('fft.full',()=>this.encodeFrames(stereo,spectrum,0,FRAMES));return {spectrum,reusedFrames:0,encodedFrames:FRAMES,allocated:true};}
  measure('spectrum.copyInterior',()=>{for(let group=0;group<SPECTRUM_GROUPS;group++){const offset=group*FRAMES*COMPLEX;spectrum.copyWithin(offset+REUSE_TARGET_FIRST*COMPLEX,offset+REUSE_SOURCE_FIRST*COMPLEX,offset+(REUSE_SOURCE_FIRST+REUSE_FRAMES)*COMPLEX);}});
  measure('fft.boundaries',()=>{this.encodeFrames(stereo,spectrum,0,REUSE_TARGET_FIRST);this.encodeFrames(stereo,spectrum,REUSE_TARGET_FIRST+REUSE_FRAMES,FRAMES);});
  return {spectrum,reusedFrames:REUSE_FRAMES,encodedFrames:FRAMES-REUSE_FRAMES,allocated:false};
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
async function create({ort,baseUrl,onProgress=()=>{},checkpoint,nativePredict,profile:providedProfile,reuseSpectrum=false}){
 const profile=profileAdapter(providedProfile);
 const experimentalSpectrumReuse=reuseSpectrum===true;
 const manifest=await measuredAsync(profile,'manifest.load','deux',async()=>await(await fetch(new URL('manifest.json',baseUrl))).json()),transform=new Transform();let closed=false,session=null,sessionName=null;
 if(manifest.execution!=='bounded-independent-batches-v1'||manifest.headFrames!==128||manifest.frames!==FRAMES||manifest.samples!==SAMPLES||manifest.indices.length!==3958||manifest.bandsPerFrequency.length!==1025)throw Error('Studio separation model configuration is invalid.');
 async function releaseStage(){const previous=session,name=sessionName;session=null;sessionName=null;if(previous)await measuredAsync(profile,'session.release',name,async()=>await previous.release());}
 async function stage(name,input){
  if(closed)throw Error('Studio separation is closed.');
  if(sessionName!==name){await releaseStage();session=await measuredAsync(profile,'session.create',name,async()=>await ort.InferenceSession.create(new URL(name+'.onnx',baseUrl).href,{executionProviders:['wasm'],graphOptimizationLevel:'all',enableCpuMemArena:false,enableMemPattern:false}));sessionName=name;profile.increment('session.created');}
  profile.increment('session.run.count');return (await measuredAsync(profile,'session.run',name,async()=>await session.run({input}))).output;
 }
 async function boundedBlock(values,index,progress){
  const name='block-'+String(index).padStart(2,'0');
  for(let first=0;first<60;first+=4){
   const count=Math.min(4,60-first),data=measured(profile,'tensor.time.allocate',name,()=>new Float32Array(count*FRAMES*256));
   measured(profile,'tensor.time.pack',name,()=>{for(let b=0;b<count;b++)for(let f=0;f<FRAMES;f++)data.set(values.subarray((f*60+first+b)*256,(f*60+first+b+1)*256),(b*FRAMES+f)*256);});
   const input=new ort.Tensor('float32',data,[count,FRAMES,256]);let output;
   try{output=await stage(name+'-time',input);measured(profile,'tensor.time.scatter',name,()=>{for(let b=0;b<count;b++)for(let f=0;f<FRAMES;f++)values.set(output.data.subarray((b*FRAMES+f)*256,(b*FRAMES+f+1)*256),(f*60+first+b)*256);});}
   finally{input.dispose();output?.dispose();}progress(.75*(first+count)/60);
  }
  for(let first=0;first<FRAMES;first+=128){
   const count=Math.min(128,FRAMES-first),data=measured(profile,'tensor.frequency.copy',name,()=>values.slice(first*60*256,(first+count)*60*256)),input=new ort.Tensor('float32',data,[count,60,256]);let output;
   try{output=await stage(name+'-frequency',input);measured(profile,'tensor.frequency.scatter',name,()=>values.set(output.data,first*60*256));}finally{input.dispose();output?.dispose();}
   progress(.75+.25*(first+count)/FRAMES);
  }
 }
 async function predictInternal(stereo,progress=()=>{},reusableSpectrum){
  const encodeScope=reusableSpectrum?'overlap-reuse':'full',encoded=measured(profile,'transform.encode',encodeScope,()=>transform.encodeWithReuse(stereo,reusableSpectrum,(name,work)=>measured(profile,'transform.'+name,encodeScope,work))),spectrum=encoded.spectrum;
  profile.increment('transform.frames.encoded',encoded.encodedFrames);profile.increment('transform.frames.reused',encoded.reusedFrames);profile.increment(encoded.allocated?'transform.spectrum.allocations':'transform.spectrum.reusedBuffers');
  const input=new ort.Tensor('float32',spectrum,[1,SPECTRUM_GROUPS,FRAMES,COMPLEX]);let front,values;
  try{front=await stage('front',input);values=measured(profile,'tensor.front.copy','front',()=>Float32Array.from(front.data));}finally{input.dispose();front?.dispose();}progress(1/15);
  for(let i=0;i<12;i++)await boundedBlock(values,i,p=>progress((1+i+p)/15));
  const out={};
  try{for(let role=0;role<2;role++){
   const mask=measured(profile,'mask.allocate','head-'+role,()=>new Float32Array(manifest.indices.length*FRAMES*2));
   for(let first=0;first<FRAMES;first+=128){
    const count=Math.min(128,FRAMES-first),data=measured(profile,'tensor.head.copy','head-'+role,()=>values.slice(first*60*256,(first+count)*60*256)),input=new ort.Tensor('float32',data,[1,count,60,256]);let y;
    try{
     y=await stage('head-'+role,input);
     if(y.data.length!==manifest.indices.length*count*2)throw Error('Studio separator returned an invalid mask batch.');
     measured(profile,'tensor.head.scatter','head-'+role,()=>{for(let bin=0;bin<manifest.indices.length;bin++)mask.set(y.data.subarray(bin*count*2,(bin+1)*count*2),(bin*FRAMES+first)*2);});
    }finally{input.dispose();y?.dispose();}
    progress((13+role+(first+count)/FRAMES)/15);
   }
   // Model creation temporarily copies weights. Release each large head before
   // decoding or opening the next one, and never carry it into another passage.
   await releaseStage();out[role===0?'vocals':'accompaniment']=measured(profile,'transform.decode',role===0?'vocals':'accompaniment',()=>transform.decode(spectrum,mask,manifest));
  }return {estimated:out,spectrum};}finally{await releaseStage();}
 }
 async function predict(stereo,progress=()=>{}){return (await predictInternal(stereo,progress)).estimated;}
 return {manifest,predict,async process(read,total,onChunk,onProgress=()=>{}){
  if(!Number.isSafeInteger(total)||total<1||total>RATE*14401)throw Error('Invalid studio separation length.');
  let pending=null,emitted=0,chunks=0,restoredPassages=0,spectrumCache=null,spectrumReuseHits=0,spectrumReuseMisses=0;const started=performance.now(),passageCount=1+Math.max(0,Math.ceil((total-CORE)/STRIDE));
  for(let start=0;start<total;start+=STRIDE){
   if(closed)throw Error('Studio separation is closed.');
   const keep=Math.min(CORE,total-start),last=start+CORE>=total,stereo=await measuredAsync(profile,'passage.read','pcm',async()=>await read(start-HALO,SAMPLES));
   if(!Array.isArray(stereo)||stereo.length!==2||stereo.some(x=>!(x instanceof Float32Array)||x.length!==SAMPLES))throw Error('Studio separation requires complete stereo chunks.');
   const peak=measured(profile,'passage.peak','pcm',()=>{let value=0;for(const channel of stereo)for(const x of channel)value=Math.max(value,Math.abs(x));return value;});
   const key='deux-'+start,cached=await measuredAsync(profile,'checkpoint.read','passage',async()=>await checkpoint?.readFloats(key));
   const restored=measured(profile,'checkpoint.validate','passage',()=>cached?.length===2&&cached.every(a=>a instanceof Float32Array&&a.length===SAMPLES&&a.every(Number.isFinite)));
   const report=(p,extra={})=>onProgress({progress:Math.min(1,(start+(last?keep:STRIDE)*p)/total),processedSeconds:start/RATE,passageIndex:chunks+1,passageCount,passagesCompleted:chunks,restoredPassages,checkpointSaved:false,message:'Studio · passage '+(chunks+1)+' of '+passageCount+' · '+Math.round(p*100)+'%',...extra});
   report(0);
   let estimated;
   if(restored){spectrumCache=null;profile.cache('passage','restore');estimated={vocals:cached[0],accompaniment:cached[1]};}
   else if(peak<1e-7){spectrumCache=null;profile.cache('passage','silence');estimated={vocals:new Float32Array(SAMPLES),accompaniment:new Float32Array(SAMPLES)};}
   else if(nativePredict){spectrumCache=null;profile.cache('passage','native');estimated=await measuredAsync(profile,'native.predict','deux',async()=>await nativePredict(start-HALO,p=>report(p)));}
   else{
    const reusable=experimentalSpectrumReuse&&spectrumCache?.nextStart===start?spectrumCache.spectrum:undefined;
    if(experimentalSpectrumReuse){profile.cache('spectrum',reusable?'hit':'miss');if(reusable)spectrumReuseHits++;else spectrumReuseMisses++;}else profile.cache('spectrum','disabled');
    const predicted=await measuredAsync(profile,'predict.local',reusable?'overlap-reuse':'full',async()=>await predictInternal(stereo,p=>report(p),reusable));
    estimated=predicted.estimated;spectrumCache=experimentalSpectrumReuse&&!last?{nextStart:start+STRIDE,spectrum:predicted.spectrum}:null;
   }
   if(['vocals','accompaniment'].some(role=>!(estimated?.[role] instanceof Float32Array)||estimated[role].length!==SAMPLES||!estimated[role].every(Number.isFinite)))throw Error('Studio separation returned invalid passage audio.');
   let checkpointSaved=restored;
   if(restored)restoredPassages++;
   else if(checkpoint&&peak>=1e-7){await measuredAsync(profile,'checkpoint.write','passage',async()=>await checkpoint.writeFloats(key,[estimated.vocals,estimated.accompaniment]));checkpointSaved=true;}
   const core=measured(profile,'passage.stitch','crossfade',()=>{const output={};for(const role of ['vocals','accompaniment']){output[role]=estimated[role].slice(HALO,HALO+keep);if(pending){const overlap=Math.min(pending[role].length,keep);for(let i=0;i<overlap;i++){const weight=.5-.5*Math.cos(Math.PI*(i+.5)/STRIDE);output[role][i]=pending[role][i]*(1-weight)+output[role][i]*weight;}}}return output;});
   const count=last?keep:STRIDE;if(start!==emitted)throw Error('Studio separation lost the source clock.');
   await measuredAsync(profile,'chunk.emit','stem-cache',async()=>await onChunk({vocals:core.vocals.slice(0,count),accompaniment:core.accompaniment.slice(0,count),startSample:start,sampleRate:RATE}));emitted+=count;chunks++;pending=last?null:{vocals:core.vocals.slice(STRIDE),accompaniment:core.accompaniment.slice(STRIDE)};
   onProgress({progress:emitted/total,processedSeconds:emitted/RATE,passageIndex:chunks,passageCount,passagesCompleted:chunks,restoredPassages,checkpointSaved,message:restored?'Restored completed passage '+chunks+' of '+passageCount:'Studio · passage '+chunks+' of '+passageCount+' complete'});if(last)break;
  }
  if(emitted!==total)throw Error('Studio separation ended before the audio.');
  const result={name:'Mel-Band RoFormer Deux',modelId:manifest.id,modelSha256:manifest.checkpointSHA256,runtime:nativePredict?'onnxruntime-android-cpu':'onnxruntime-web-wasm',sourceSeparated:true,sampleRate:RATE,sourceChannels:2,stems:['vocals','accompaniment'],method:'Dual trained stereo source separation; Float32 bounded transformer with complete attention',contextSeconds:13,coreSeconds:10,overlapSeconds:5,chunks,restoredPassages,estimated:true,analysisSeconds:(performance.now()-started)/1000,alignment:'Original PCM clock; centered STFT and normalized overlap-add with complementary chunk crossfades',preprocessing:{spectrumReuse:{experimental:true,enabled:experimentalSpectrumReuse,sourceFrames:{first:REUSE_SOURCE_FIRST,last:REUSE_SOURCE_LAST},targetFrames:{first:REUSE_TARGET_FIRST,last:REUSE_TARGET_FIRST+REUSE_FRAMES-1},reusedFramesPerPassage:REUSE_FRAMES,recomputedFramesPerPassage:FRAMES-REUSE_FRAMES,hits:spectrumReuseHits,misses:spectrumReuseMisses}},limitations:['Vocal and instrumental estimates can contain bleed; neither is an isolated bass instrument.','Lead and backing singers share one vocal source; no lyrics or word alignment.']};
  if(typeof providedProfile?.snapshot==='function')try{result.performanceProfile=providedProfile.snapshot({passages:chunks,spectrumReuse:{enabled:experimentalSpectrumReuse,hits:spectrumReuseHits,misses:spectrumReuseMisses}});}catch(_){}
  return result;
 },async release(){if(closed)return;closed=true;await releaseStage();}};
}
root.LightForgeDeux={create,Transform,PerformanceProfile,createPerformanceProfile:()=>new PerformanceProfile(),constants:{RATE,NFFT,HOP,FRAMES,SAMPLES,HALO,CORE,STRIDE,REUSE_SOURCE_FIRST,REUSE_SOURCE_LAST,REUSE_TARGET_FIRST,REUSE_FRAMES}};if(typeof module!=='undefined'&&module.exports)module.exports=root.LightForgeDeux;
})(typeof self!=='undefined'?self:globalThis);
