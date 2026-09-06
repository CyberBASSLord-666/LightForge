/* Private worker: bounded PCM chunks -> exact log-mel -> pretrained Beat This! transformer. */
'use strict';
importScripts('wav-reader.js','dsp.js','bass-notes.js','vocal.js','vocal-detail.js','stem-cache.js','separator-mdx.js','vendor/ort.wasm.min.js');
const report=(progress,stage,detail='')=>postMessage({type:'progress',value:{progress,stage,detail}});
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
self.onmessage=async e=>{let session,melSession,separator,cacheWriter,cacheKey;try{
 const {audioUrl,options={}}=e.data;cacheKey=options.cacheKey;const quality=options.analysisQuality==='balanced'?'balanced':'precision';
 report(.01,'Opening music','Reading your music locally');const reader=new LightForgeWavReader(options.analysisUrl||audioUrl);await reader.open();
 const config=await(await fetch('models/features.json')).json(),models=await(await fetch('models/model-manifest.json')).json(),selected=models[quality];
 const n=Math.ceil(reader.duration*50);let data={duration:reader.duration,beat:new Float32Array(n),down:new Float32Array(n),rms:new Float32Array(n),bass:new Float32Array(n),mid:new Float32Array(n),high:new Float32Array(n),colour:new Float32Array(n*3),fineRms:new Float32Array(n*4),chroma:new Float32Array(Math.ceil(n/10)*12),chromaStep:.2};
 const started=performance.now(),extractor=new LightForgeDSP.FeatureExtractor(config),featureChunk=500;
 report(.025,'Listening to musical detail','Measuring attacks, tonal colour and quiet passages');
 for(let first=0;first<n;first+=featureChunk){const frames=Math.min(featureChunk,n-first),samples=await reader.mono22050(first*441-705,(frames-1)*441+1411,config),f=extractor.extract(samples,0,frames);for(const name of ['rms','bass','mid','high'])data[name].set(f[name],first);data.colour.set(f.colour,first*3);data.fineRms.set(f.fineRms,first*4);for(let i=0;i<frames;i++)for(let b=0;b<12;b++)data.chroma[Math.floor((first+i)/10)*12+b]+=f.chroma[i*12+b]/10;report(.03+.18*(first+frames)/n,'Listening to musical detail',`${Math.min(reader.duration,(first+frames)*.02).toFixed(0)} / ${reader.duration.toFixed(0)} seconds`);}
 report(.22,'Loading music AI',quality==='precision'?'Beat This! full transformer • entirely on this device':'Beat This! compact transformer • entirely on this device');
 ort.env.wasm.wasmPaths=new URL('vendor/',self.location.href).href;ort.env.wasm.numThreads=self.crossOriginIsolated&&typeof SharedArrayBuffer==='function'?Math.min(4,Math.max(1,Math.floor((navigator.hardwareConcurrency||2)/2))):1;ort.env.wasm.proxy=false;
 const sessionOptions={executionProviders:['wasm'],graphOptimizationLevel:'all',enableCpuMemArena:true};

 const chunk=1500,border=6,stride=chunk-border*2,starts=[];for(let s=-border;s<n-border;s+=stride)starts.push(s);if(n>stride)starts[starts.length-1]=n-(chunk-border);
 let copiedUntil=0;
 for(let k=0;k<starts.length;k++){
  const first=starts[k],length=Math.min(chunk,n+border-first),lo=Math.max(0,first),hi=Math.min(n,first+length);let peak=0;for(let i=lo;i<hi;i++)peak=Math.max(peak,data.rms[i]);
  if(peak<=1e-7){copiedUntil=Math.max(copiedUntil,Math.min(n,first+length-border));report(.24+.15*(k+1)/starts.length,'Recognizing a quiet passage','Keeping complete silence clear of invented beats');continue;}
  if(!session){session=await ort.InferenceSession.create(new URL('models/'+selected.file,self.location.href).href,sessionOptions);melSession=await ort.InferenceSession.create(new URL('models/'+models.frontend.file,self.location.href).href,sessionOptions);}
  const features=new Float32Array(length*128),mel=await melForFrames(reader,melSession,lo,hi-lo,config);features.set(mel,(lo-first)*128);
  const input=new ort.Tensor('float32',features,[1,length,128]);let out;
  try{out=await session.run({spectrogram:input});const beats=out.beat.data,down=out.downbeat.data;const begin=Math.max(copiedUntil,0,first+border),end=Math.min(n,first+length-border);for(let i=begin;i<end;i++){const b=sigmoid(beats[i-first]),d=sigmoid(down[i-first]);data.beat[i]=Math.max(0,b-d);data.down[i]=d;}copiedUntil=Math.max(copiedUntil,end);}finally{if(out)dispose(out);input.dispose();}
  report(.24+.15*(k+1)/starts.length,'Understanding beats and bar accents',`${Math.min(reader.duration,copiedUntil*.02).toFixed(0)} / ${reader.duration.toFixed(0)} seconds • ${quality==='precision'?'Precision':'Balanced'}`);
 }
 if(copiedUntil!==n)throw new Error('The music analysis did not cover the full track. Please try again.');
 if(session)await session.release();session=null;if(melSession)await melSession.release();melSession=null;
 report(.40,'Recognizing musical structure','Finding recurring passages, groove and confident movement moments');
 const result=LightForgeDSP.summarize(data,{...options,decoder:'transformer'});
 // Release rhythm feature buffers and both transformer sessions before the
 // independent musical-role passes. Every pass uses the same original PCM clock.
 data=null;
 // Separation consumes original stereo, never the mono analysis proxy. Keep
 // bounded Float32 stem audio on disk; unload the large model before detail AI.
 report(.41,'Separating voice and instruments','Studio quality • your music stays on this device');
 const sourceReader=new LightForgeWavReader(audioUrl);await sourceReader.open();
 cacheWriter=await LightForgeStemCache.create(cacheKey,sourceReader.samples,config,options.projectId||'');
 separator=await LightForgeMdxSeparator.create({ort,baseUrl:new URL('models/',self.location.href).href,onProgress:p=>report(.41,'Loading studio vocal separation',p.message)});
 result.separation=await separator.process((start,count)=>sourceReader.stereo44100(start,count),sourceReader.samples,chunk=>cacheWriter.append(chunk),p=>report(.42+.40*p.progress,'Separating voice and instruments',`${p.message} • ${Math.min(sourceReader.duration,p.processedSeconds||0).toFixed(0)} / ${sourceReader.duration.toFixed(0)} seconds`));
 await separator.release();separator=null;
 result.stemCache=await cacheWriter.finish();cacheWriter=null;
 const stems=await LightForgeStemCache.readers(result.stemCache);
 report(.83,'Recognizing the isolated voice','Distinguishing singing, speech and remaining instrument bleed');
 const classified=await LightForgeVocals.analyze(stems.vocals,config,{ort,includeClassifierScores:true,report:(p,stage,detail)=>report(.83+.075*p,'Recognizing the isolated voice',detail)});
 const detailExtractor=new LightForgeVocalDetail.Extractor({sampleRate:22050,duration:sourceReader.duration}),detailCount=result.stemCache.samples,detailChunk=22050*8;
 for(let start=0;start<detailCount;start+=detailChunk){const count=Math.min(detailChunk,detailCount-start),voice=await stems.vocals.mono22050(start,count,config),backing=await stems.accompaniment.mono22050(start,count,config);detailExtractor.push(voice,start,backing);report(.905+.035*(start+count)/detailCount,'Following vocal expression','Measuring entrances, syllabic attacks, held notes and pauses');}
 result.vocals=detailExtractor.finish({classifier:classified.classifier,model:classified.model});
 classified.classifier=null;
 report(.94,'Following bass notes','Listening beneath the separated singing');
 const bass=await LightForgeBass.analyze(stems.accompaniment,config,{onProgress:p=>report(.94+.055*p,'Following bass notes','Distinguishing sustained low notes from brief drum attacks')});
 const {notes,...bassAnalysis}=bass;result.bassNotes=notes;result.bassAnalysis={...bassAnalysis,source:'separated-accompaniment',sourceSeparated:true,limitations:[...(bassAnalysis.limitations||[]),'Bass notes are estimated from combined accompaniment, not an isolated bass instrument.']};
 result.analysisVersion=5;
 result.roleAnalysis={version:2,clock:'Original decoded audio',vocalSource:'Separated vocal waveform with singing and speech evidence',bassSource:'Low-register harmonics in separated accompaniment',sourceSeparated:true,lyricsAligned:false};
 for(const warning of [...(result.vocals.warnings||[]),...(result.separation.limitations||[])])if(!result.warnings.includes(warning))result.warnings.push(warning);
 result.engine={name:'Beat This! '+(quality==='precision'?'full transformer':'compact transformer')+' + studio vocal separation',neural:true,detail:'Bundled pretrained rhythm transformer, stereo vocal separation with polarity refinement, isolated-voice singing and speech classification, measured articulation and held notes, and independent accompaniment bass tracking. All audio stays on this device.',model:selected.model,modelId:selected.id,modelSha256:selected.sha256,frontendSha256:models.frontend.sha256,vocalModel:result.vocals.model,separationModel:result.separation,bassMethod:result.bassAnalysis.method,quality,runtime:'ONNX Runtime Web 1.20.1',analysisSeconds:Math.round((performance.now()-started)/100)/10};
 result.recommendedAudio={sampleRate:44100,channels:2,format:'PCM16 WAV'};report(1,'Music understood',`${result.bpm?result.bpm+' BPM':'No pulse detected'} • ${result.sections.length} sections`);postMessage({type:'result',value:result});
 }catch(error){if(separator)try{await separator.release();}catch(_){}if(cacheWriter)try{await cacheWriter.abort();}catch(_){}else if(cacheKey)await LightForgeStemCache.discard(cacheKey);if(session)try{await session.release();}catch(_){}if(melSession)try{await melSession.release();}catch(_){}postMessage({type:'error',message:error.message||String(error)});}};
