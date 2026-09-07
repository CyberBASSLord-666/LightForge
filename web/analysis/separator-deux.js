/* Mel-Band RoFormer Deux, original Float32 inference from FP16 author weights.
 * Integration MIT; model and converted weights CC BY-NC 4.0, becruily.
 * Full 13-second context; exact attention split along queries (no truncation).
 * Stages are released sequentially to bound the live model weights on Android.
 */
(function(root){'use strict';
const RATE=44100,NFFT=2048,HOP=441,FRAMES=1301,SAMPLES=573300,HALO=66150,CORE=441000,STRIDE=220500;
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
async function create({ort,baseUrl,onProgress=()=>{}}){
 const manifest=await(await fetch(new URL('manifest.json',baseUrl))).json(),transform=new Transform();let closed=false;
 if(manifest.frames!==FRAMES||manifest.samples!==SAMPLES||manifest.indices.length!==3958||manifest.bandsPerFrequency.length!==1025)throw Error('Studio separation model configuration is invalid.');
 async function stage(name,input){if(closed)throw Error('Studio separation is closed.');let session;try{session=await ort.InferenceSession.create(new URL(name+'.onnx',baseUrl).href,{executionProviders:['wasm'],graphOptimizationLevel:'all',enableCpuMemArena:false,enableMemPattern:false});return (await session.run({input})).output;}finally{if(session)await session.release();}}
 async function predict(stereo,progress){const spectrum=transform.encode(stereo);let x=new ort.Tensor('float32',spectrum,[1,2050,FRAMES,2]);
  try{const names=['front',...Array.from({length:12},(_,i)=>'block-'+String(i).padStart(2,'0'))];for(let i=0;i<names.length;i++){const y=await stage(names[i],x);x.dispose();x=y;progress((i+1)/15);}
   const out={};for(let i=0;i<2;i++){let y;try{y=await stage('head-'+i,x);out[i===0?'vocals':'accompaniment']=transform.decode(spectrum,y.data,manifest);}finally{y?.dispose();}progress((14+i)/15);}return out;
  }finally{x.dispose();}
 }
 return {manifest,predict,async process(read,total,onChunk,onProgress=()=>{}){
  if(!Number.isSafeInteger(total)||total<1||total>RATE*14401)throw Error('Invalid studio separation length.');
  let pending=null,emitted=0,chunks=0;const started=performance.now();
  for(let start=0;start<total;start+=STRIDE){
   const keep=Math.min(CORE,total-start),last=start+CORE>=total,stereo=await read(start-HALO,SAMPLES);
   if(!Array.isArray(stereo)||stereo.length!==2||stereo.some(x=>!(x instanceof Float32Array)||x.length!==SAMPLES))throw Error('Studio separation requires complete stereo chunks.');
   let peak=0;for(const channel of stereo)for(const x of channel)peak=Math.max(peak,Math.abs(x));
   const estimated=peak<1e-7?{vocals:new Float32Array(SAMPLES),accompaniment:new Float32Array(SAMPLES)}:await predict(stereo,p=>onProgress({progress:Math.min(1,(start+(last?keep:STRIDE)*p)/total),processedSeconds:start/RATE,message:'Deux · '+Math.round(p*100)+'% of current passage'}));
   const core={};for(const role of ['vocals','accompaniment']){core[role]=estimated[role].slice(HALO,HALO+keep);if(pending){const overlap=Math.min(pending[role].length,keep);for(let i=0;i<overlap;i++){const weight=.5-.5*Math.cos(Math.PI*(i+.5)/STRIDE);core[role][i]=pending[role][i]*(1-weight)+core[role][i]*weight;}}}
   const count=last?keep:STRIDE;if(start!==emitted)throw Error('Studio separation lost the source clock.');
   await onChunk({vocals:core.vocals.slice(0,count),accompaniment:core.accompaniment.slice(0,count),startSample:start,sampleRate:RATE});emitted+=count;chunks++;pending=last?null:{vocals:core.vocals.slice(STRIDE),accompaniment:core.accompaniment.slice(STRIDE)};
   onProgress({progress:emitted/total,processedSeconds:emitted/RATE,message:'Studio source separation'});if(last)break;
  }
  if(emitted!==total)throw Error('Studio separation ended before the audio.');
  return {name:'Mel-Band RoFormer Deux',modelId:manifest.id,modelSha256:manifest.checkpointSHA256,sourceSeparated:true,sampleRate:RATE,sourceChannels:2,stems:['vocals','accompaniment'],method:'Dual trained stereo source separation; Float32 staged transformer with complete attention',contextSeconds:13,coreSeconds:10,overlapSeconds:5,chunks,estimated:true,analysisSeconds:(performance.now()-started)/1000,alignment:'Original PCM clock; centered STFT and normalized overlap-add with complementary chunk crossfades',limitations:['Vocal and instrumental estimates can contain bleed; neither is an isolated bass instrument.','Lead and backing singers share one vocal source; no lyrics or word alignment.']};
 },async release(){closed=true;}};
}
root.LightForgeDeux={create,Transform};if(typeof module!=='undefined'&&module.exports)module.exports=root.LightForgeDeux;
})(typeof self!=='undefined'?self:globalThis);
