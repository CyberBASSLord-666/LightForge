/* UVR MDX-Net Voc FT. True complex-spectrogram vocal source separation.
 * Original weights are unchanged; attribution and parameters are bundled.
 * Audio stays on its original 44.1 kHz clock throughout STFT and overlap-add. */
(function(root){'use strict';
const RATE=44100,NFFT=7680,HOP=1024,FRAMES=256,BINS=3072,TRIM=NFFT/2,INPUT_LENGTH=HOP*(FRAMES-1),CORE=INPUT_LENGTH-2*TRIM,OVERLAP=CORE/2,STRIDE=CORE-OVERLAP;
const finite=x=>Number.isFinite(x)?x:0;
// A mixed-radix 15 x 512 transform preserves MDX's trained 7680-point FFT.
// Padding to 8192 would move every spectral bin and invalidate the model.
class FFT7680{
 constructor(){this.small=new root.LightForgeDSP.FFT(512);this.ar=new Float64Array(NFFT);this.ai=new Float64Array(NFFT);this.r=new Float64Array(512);this.im=new Float64Array(512);this.cos=new Float64Array(NFFT*15);this.sin=new Float64Array(NFFT*15);for(let k=0;k<NFFT;k++)for(let j=0;j<15;j++){const a=2*Math.PI*((k*j)%NFFT)/NFFT;this.cos[k*15+j]=Math.cos(a);this.sin[k*15+j]=Math.sin(a);}}
 run(real,imag,inverse=false,outputBins=NFFT){const{r,im,ar,ai,small,cos,sin}=this;for(let j=0;j<15;j++){for(let i=0;i<512;i++){r[i]=real[i*15+j];im[i]=imag[i*15+j];}small.run(r,im,inverse);ar.set(r,j*512);ai.set(im,j*512);}for(let k=0;k<outputBins;k++){let re=0,ii=0;const f=k%512,w=k*15;for(let j=0;j<15;j++){const index=j*512+f,c=cos[w+j],s=sin[w+j]*(inverse?1:-1);re+=ar[index]*c-ai[index]*s;ii+=ar[index]*s+ai[index]*c;}real[k]=inverse?re/15:re;imag[k]=inverse?ii/15:ii;}}
}
class Frontend{
 constructor(){if(!root.LightForgeDSP?.FFT)throw new Error('The source-separation FFT is unavailable.');this.fft=new FFT7680();this.r=new Float64Array(NFFT);this.im=new Float64Array(NFFT);this.window=new Float64Array(NFFT);this.norm=new Float64Array(INPUT_LENGTH+NFFT);this.spectrum=new Float32Array(4*BINS*FRAMES);for(let i=0;i<NFFT;i++)this.window[i]=.5-.5*Math.cos(2*Math.PI*i/NFFT);for(let f=0;f<FRAMES;f++)for(let i=0;i<NFFT;i++)this.norm[f*HOP+i]+=this.window[i]*this.window[i];}
 encode(stereo){if(!Array.isArray(stereo)||stereo.length!==2||stereo.some(x=>!(x instanceof Float32Array)||x.length!==INPUT_LENGTH))throw new Error('The vocal separator received incomplete stereo audio.');const output=this.spectrum;output.fill(0);const{r,im,fft,window}=this;for(let c=0;c<2;c++)for(let f=0;f<FRAMES;f++){const start=f*HOP-TRIM;for(let i=0;i<NFFT;i++){let p=start+i;if(p<0)p=-p;else if(p>=INPUT_LENGTH)p=2*INPUT_LENGTH-p-2;r[i]=finite(stereo[c][p])*window[i];im[i]=0;}fft.run(r,im,false,BINS);for(let b=3;b<BINS;b++){output[(c*2*BINS+b)*FRAMES+f]=r[b];output[((c*2+1)*BINS+b)*FRAMES+f]=im[b];}}return output;}
 decode(spectrum,compensate=1.021){if(spectrum.length!==4*BINS*FRAMES)throw new Error('The vocal separator returned an invalid spectrum.');const full=new Float32Array(INPUT_LENGTH+NFFT),{r,im,fft,window,norm}=this;let invalid=0;for(let c=0;c<2;c++)for(let f=0;f<FRAMES;f++){r.fill(0);im.fill(0);for(let b=0;b<BINS;b++){let re=spectrum[(c*2*BINS+b)*FRAMES+f],ii=spectrum[((c*2+1)*BINS+b)*FRAMES+f];if(!Number.isFinite(re)||!Number.isFinite(ii)){invalid++;continue;}r[b]=re;im[b]=ii;if(b){r[NFFT-b]=re;im[NFFT-b]=-ii;}}fft.run(r,im,true);for(let i=0;i<NFFT;i++)full[f*HOP+i]+=r[i]*window[i]*.5;}if(invalid)throw new Error('The vocal model produced invalid audio. Free device memory and analyze again.');const output=new Float32Array(INPUT_LENGTH);for(let i=0;i<INPUT_LENGTH;i++)output[i]=full[i+TRIM]/Math.max(1e-12,norm[i+TRIM])*compensate;return output;}
}
async function create(options={}){
 const ort=options.ort||root.ort;if(!ort)throw new Error('The offline vocal-separation runtime is unavailable.');const base=options.baseUrl||'models/',manifest=options.manifest||await(await fetch(base+'separator-mdx-model.json')).json();if(manifest.sampleRate!==RATE||manifest.nFFT!==NFFT||!manifest.file)throw new Error('The vocal-separation model configuration is invalid.');const frontend=new Frontend(),denoise=options.denoise!==false;let session=null,sessionPromise=null,released=false,sessionRestarts=0;
 const sessionOptions={executionProviders:['wasm'],enableCpuMemArena:false,enableMemPattern:false,graphOptimizationLevel:'all'};
 // A long balanced run can outlive the WebView renderer's native WASM heap.
 // Load lazily (a fully restored job needs no model) and retire the session at
 // each passage boundary. The model, FFT geometry and outputs are unchanged;
 // only allocator lifetime is bounded.
 async function ensureSession(){
  if(released)throw new Error('This vocal-separation session is closed.');
  if(session)return session;
  if(!sessionPromise)sessionPromise=(async()=>{options.onProgress?.({stage:'loading',progress:0,message:'Loading studio vocal separation'});try{return await ort.InferenceSession.create(base+manifest.file,sessionOptions);}catch(e){throw new Error('Could not load studio vocal separation. Free device memory and retry. '+(e?.message||e));}})();
 try{session=await sessionPromise;return session;}finally{sessionPromise=null;}
 }
 async function retireSession(){const current=session;session=null;if(current){sessionRestarts++;await current.release?.();}}
 async function runWasm(encoded){
  const active=await ensureSession();let tensor,result,prediction;
  try{tensor=new ort.Tensor('float32',encoded,[1,4,BINS,FRAMES]);result=await active.run({[active.inputNames[0]]:tensor});prediction=Float32Array.from(result[active.outputNames[0]].data);return prediction;}
  finally{tensor?.dispose?.();if(result)for(const value of Object.values(result))value.dispose?.();}
 }
 return{manifest,async process(readStereo44100,sampleCount,onChunk,onProgress){
  if(released)throw new Error('This vocal-separation session is closed.');if(typeof readStereo44100!=='function'||typeof onChunk!=='function'||!Number.isSafeInteger(sampleCount)||sampleCount<1||sampleCount>RATE*14401)throw new Error('Invalid source-separation audio request.');let pending=null,emitted=0,chunks=0,passes=0,nativePasses=0,wasmPasses=0;const clock=performance.now();
  for(let start=0;start<sampleCount;start+=STRIDE){const keep=Math.min(CORE,sampleCount-start),last=sampleCount-start<=CORE,stereo=await readStereo44100(start-TRIM,INPUT_LENGTH);let peak=0;for(let c=0;c<2;c++)for(let i=0;i<stereo[c].length;i++)peak=Math.max(peak,Math.abs(finite(stereo[c][i])));let decoded;
   const report=(phase,fraction)=>onProgress?.({stage:'separating',progress:Math.min(.99,(start+STRIDE*fraction)/sampleCount),processedSeconds:start/RATE,totalSeconds:sampleCount/RATE,message:phase});report('Separating singing from the instruments',0);
   const checkpointName='mdx-'+(denoise?'ensemble-':'single-')+start,cached=await options.checkpoint?.readFloats(checkpointName);
   if(cached?.length===1&&cached[0].length===INPUT_LENGTH){decoded=cached[0];report('Restoring a completed vocal passage',.9);}
   else if(peak<1e-7)decoded=new Float32Array(INPUT_LENGTH);else{const encoded=frontend.encode(stereo);let prediction,nativeUsed=false;
    const valid=value=>{if(!(value instanceof Float32Array)||value.length!==4*BINS*FRAMES)return false;for(let i=0;i<value.length;i++)if(!Number.isFinite(value[i]))return false;return true;};
    const nativeProgress=p=>report(p?.message||'Running balanced MDX',Math.max(0,Math.min(1,Number(p?.progress)||0)));
    if(typeof options.nativePredict==='function'){
     const candidate=await options.nativePredict(encoded,nativeProgress);
     if(valid(candidate)){prediction=candidate;nativeUsed=true;passes++;nativePasses++;}
    }
    if(!prediction){prediction=await runWasm(encoded);passes++;wasmPasses++;}
    if(denoise){report('Refining vocal isolation with a second listening pass',.5);const reversed=encoded.slice();for(let i=0;i<reversed.length;i++)reversed[i]=-reversed[i];let reverse;
     if(nativeUsed){reverse=await options.nativePredict(reversed,nativeProgress);if(valid(reverse)){for(let i=0;i<prediction.length;i++)prediction[i]=(prediction[i]-reverse[i])*.5;passes++;nativePasses++;}else{
      // Never mix native and WebAssembly passes. If the optional bridge stops
      // halfway through a polarity pair, recompute both with the verified
      // WebAssembly graph so the denoiser remains deterministic.
      prediction=await runWasm(encoded);passes++;wasmPasses++;reverse=await runWasm(reversed);passes++;wasmPasses++;for(let i=0;i<prediction.length;i++)prediction[i]=(prediction[i]-reverse[i])*.5;
     }}else{reverse=await runWasm(reversed);passes++;wasmPasses++;for(let i=0;i<prediction.length;i++)prediction[i]=(prediction[i]-reverse[i])*.5;}
    }
    decoded=frontend.decode(prediction,manifest.compensate);await options.checkpoint?.writeFloats(checkpointName,[decoded]);}
   const vocals=decoded.slice(TRIM,TRIM+keep),mixture=new Float32Array(keep);for(let i=0;i<keep;i++)mixture[i]=(finite(stereo[0][i+TRIM])+finite(stereo[1][i+TRIM]))*.5;if(pending){for(let i=0;i<Math.min(OVERLAP,keep,pending.length);i++){const w=.5-.5*Math.cos(Math.PI*(i+.5)/OVERLAP);vocals[i]=pending[i]*(1-w)+vocals[i]*w;}}
   const count=last?keep:STRIDE,outputVocals=vocals.slice(0,count),accompaniment=new Float32Array(count);for(let i=0;i<count;i++)accompaniment[i]=mixture[i]-outputVocals[i];if(start!==emitted)throw new Error('Vocal-separation timing continuity was lost.');await onChunk({vocals:outputVocals,accompaniment,startSample:start,sampleRate:RATE});emitted+=count;chunks++;pending=last?null:vocals.slice(STRIDE);if(last)break;await retireSession();await new Promise(resolve=>setTimeout(resolve,0));
  }
  if(emitted!==sampleCount)throw new Error('The separated vocal track is incomplete. Your original music is unchanged.');onProgress?.({stage:'complete',progress:1,processedSeconds:sampleCount/RATE,totalSeconds:sampleCount/RATE,message:'Studio vocal separation complete'});return{sourceSeparated:true,runtime:nativePasses?(wasmPasses?'onnxruntime-android-cpu+onnxruntime-web-wasm':'onnxruntime-android-cpu'):'onnxruntime-web-wasm',nativeModelPasses:nativePasses,wasmModelPasses:wasmPasses,name:'UVR MDX-Net Voc FT',modelId:manifest.id,modelSha256:manifest.sha256,sampleRate:RATE,sourceChannels:2,stems:['vocals','accompaniment'],method:denoise?'Pretrained stereo complex-spectrum separation with polarity ensemble':'Pretrained stereo complex-spectrum separation',vocalBandwidthHz:BINS*RATE/NFFT,fftWindowSamples:NFFT,fftHopSamples:HOP,contextSamples:TRIM,overlapSamples:OVERLAP,overlapFraction:.5,denoise,modelPasses:passes,alignment:'Original sample clock; normalized overlap-add and complementary chunk crossfades; no latency subtraction',estimated:true,analysisSeconds:(performance.now()-clock)/1000,chunks,limitations:['Separation can retain instrument bleed or soften quiet and heavily processed singing.','Lead and backing vocals are combined; this is not lyric transcription.']};
  },async release(){if(released)return;released=true;const pending=sessionPromise;sessionPromise=null;try{if(pending)await pending.catch(()=>{});}finally{await retireSession();}}
}}
root.LightForgeMdxSeparator={create,Frontend,FFT7680,constants:{RATE,NFFT,HOP,FRAMES,BINS,TRIM,INPUT_LENGTH,CORE,OVERLAP,STRIDE}};if(typeof module!=='undefined'&&module.exports)module.exports=root.LightForgeMdxSeparator;
})(typeof self!=='undefined'?self:globalThis);
