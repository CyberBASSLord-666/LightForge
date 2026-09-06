/* PretrainedSED Frame-MN10: real frame-level singing inference, entirely offline.
 * Strong AudioSet labels distinguish singing from speech and instruments.
 * No source separation, lyric transcription or individual sung-note claims.
 * Upstream model/frontend are MIT; provenance is in models/vocal-model.json.
 */
(function(root){
'use strict';
const RATE=16000,FFT=512,WIN=400,HOP=160,BANDS=128,CONTEXT=160000,FRAMES=1000,OUTPUT=250;
const clamp=(n,a=0,b=1)=>Math.min(b,Math.max(a,n));
const reverse=Uint16Array.from({length:FFT},(_,i)=>{let r=0;for(let b=0;b<9;b++){r=(r<<1)|(i&1);i>>=1;}return r;});
function reflect(i,n){if(n<=1)return 0;while(i<0||i>=n)i=i<0?-i:2*n-2-i;return i;}
function logMel(pcm,frontend){
 const frames=Math.floor((pcm.length-1)/HOP)+1,out=new Float32Array(frames*BANDS),re=new Float64Array(FFT),im=new Float64Array(FFT),power=new Float64Array(257),preamp=new Float32Array(Math.max(1,pcm.length-1));
 // Author's Conv1D [-.97, 1] shortens by one sample. torch.stft centers
 // the 400-point nonperiodic Hann in a 512-point FFT, reflect-padding PCM.
 for(let i=0;i<pcm.length-1;i++)preamp[i]=pcm[i+1]-.97*pcm[i];
 for(let f=0;f<frames;f++){
  re.fill(0);im.fill(0);for(let i=0;i<WIN;i++)re[reverse[56+i]]=preamp[reflect(f*HOP-200+i,preamp.length)]*frontend.windowValues[i];
  for(let len=2;len<=FFT;len*=2){const half=len/2;for(let j=0;j<half;j++){const c=Math.cos(-2*Math.PI*j/len),s=Math.sin(-2*Math.PI*j/len);for(let i=j;i<FFT;i+=len){const k=i+half,r=re[k]*c-im[k]*s,t=re[k]*s+im[k]*c;re[k]=re[i]-r;im[k]=im[i]-t;re[i]+=r;im[i]+=t;}}}
  for(let k=0;k<=256;k++)power[k]=re[k]*re[k]+im[k]*im[k];
  for(let b=0;b<BANDS;b++){let sum=0;for(const [k,w] of frontend.melWeights[b])sum+=power[k]*w;out[b*frames+f]=(Math.log(Math.max(1e-7,sum))+4.5)/5;}
 }
 return out;
}
// Windowed-sinc 22.05 -> 16 kHz resampling with 64 taps and global rational
// coordinates. All chunk boundaries read the same source halo (no phase reset).
const resamplePhases=Array.from({length:320},(_,p)=>{const a=new Float64Array(64),fraction=p/320,cutoff=16000/22050*.94;let sum=0;for(let j=0;j<64;j++){const x=j-31-fraction,w=.42+.5*Math.cos(Math.PI*x/32)+.08*Math.cos(2*Math.PI*x/32),v=Math.abs(x)<1e-10?cutoff:Math.sin(Math.PI*cutoff*x)/(Math.PI*x);a[j]=v*w;sum+=a[j];}for(let j=0;j<64;j++)a[j]/=sum;return a;});
async function pcm16000(reader,start,count,config){
 const first=Math.floor(start*441/320)-32,last=Math.ceil((start+count-1)*441/320)+33;
 const raw=await reader.mono22050(first,last-first,config),out=new Float32Array(count);
 for(let i=0;i<count;i++){const numerator=(start+i)*441,center=Math.floor(numerator/320),phase=numerator-center*320,filter=resamplePhases[phase];let sum=0;for(let j=0;j<64;j++)sum+=(raw[center-31+j-first]||0)*filter[j];out[i]=sum;}
 return out;
}
function quantile(values,q){if(!values.length)return 0;const a=Array.from(values).sort((a,b)=>a-b);return a[Math.min(a.length-1,Math.floor((a.length-1)*q))];}
function summarize(scores,detail,duration,model){
 const step=.02,n=Math.ceil(duration/step),evidence=new Float32Array(n),phrases=[],accents=[];let peak=0,strongFrames=0;
 // Model scores are uncalibrated evidence on 40ms bins. Interpolate from bin
 // centers; retain that origin instead of snapping singing to a drum attack.
 for(let i=0;i<n;i++){const x=Math.max(0,(i*step-.02)/.04),j=Math.floor(x),a=clamp(x-j),s=(scores[Math.min(j,scores.length-1)]||0)*(1-a)+(scores[Math.min(j+1,scores.length-1)]||0)*a;evidence[i]=s;peak=Math.max(peak,s);if(i%2===0&&s>=.35)strongFrames++;}
 const active=Array.from(detail).filter(x=>x>1e-7),floor=quantile(active,.15),ceiling=quantile(active,.9),level=new Float32Array(n);
 for(let i=0;i<n;i++)level[i]=clamp(((detail[i]||0)-floor*.5)/Math.max(1e-5,ceiling-floor*.5));
 let start=-1,gap=0;
 for(let i=0;i<=n;i++){
  const canContinue=i<n&&evidence[i]>=.16&&level[i]>.02;
  if(start<0){if(i<n&&evidence[i]>=.30&&level[i]>.06){start=i;gap=0;}}
  else if(canContinue)gap=0;
  else if(++gap>=12||i===n){let end=i-gap+1;const a=Math.max(0,start-1),b=Math.min(n,end+1);let maxScore=0,peakLevel=0,peakFrame=a;for(let j=a;j<b;j++){maxScore=Math.max(maxScore,evidence[j]);if(evidence[j]*level[j]>peakLevel){peakLevel=evidence[j]*level[j];peakFrame=j;}}
   if((b-a)*step>=.28&&maxScore>=.35){const confidence=clamp(.55+.45*(maxScore-.35)/.65);phrases.push({start:+(a*step).toFixed(3),end:Math.floor(Math.min(duration,b*step)*1000+1e-8)/1000,confidence:+confidence.toFixed(3),modelScore:+maxScore.toFixed(4),strength:+clamp(Math.sqrt(peakLevel)).toFixed(3),peakTime:+(peakFrame*step).toFixed(3),estimated:true});}
   start=-1;gap=0;
  }
 }
 const envelope=new Array(n).fill(0);
 for(const p of phrases){const first=Math.floor(p.start/step),last=Math.min(n,Math.ceil(p.end/step));for(let i=first;i<last;i++)envelope[i]=level[i]>0?+clamp(evidence[i]*(.55+.45*level[i])).toFixed(3):0;
  // Accent estimates require a *singing-score rise* plus supporting mixture
  // dynamics. A bass/kick transient alone cannot invent a vocal accent.
  let previous=p.start-.3;for(let i=first+2;i<last-2;i++){const rise=evidence[i]-Math.min(evidence[i-1],evidence[i-2]);if(level[i]>.05&&evidence[i]>=.30&&rise>.045&&envelope[i]>=envelope[i+1]&&i*step-previous>=.3){accents.push({time:+(i*step).toFixed(3),strength:+clamp(rise*4+.3*level[i]).toFixed(3),confidence:p.confidence,estimated:true});previous=i*step;}}
 }
 const coverage=phrases.reduce((s,p)=>s+p.end-p.start,0)/Math.max(duration,1),presence=phrases.length?'detected':peak>=.16?'uncertain':'not_detected';let confidence=0;for(const p of phrases)confidence=Math.max(confidence,p.confidence);
 return {available:true,presence,confidence:phrases.length?+confidence.toFixed(3):+clamp(peak).toFixed(3),modelScore:+peak.toFixed(4),coverage:+coverage.toFixed(4),phrases,accents,envelope,envelopeStep:step,method:'PretrainedSED Frame-MN10 strong singing events with confidence-gated phrasing',model:{name:model.name,id:model.id,sha256:model.sha256,license:model.license},timing:{contextSeconds:10,classifierFrameMs:40,envelopeMs:20,overlapSeconds:4,alignment:'40 ms sound-event evidence with estimated phrase edges and accents; no separated vocal stem or word alignment'},warnings:presence==='uncertain'?['Singing evidence is weak; the show keeps following the accompaniment.']:[],diagnostics:{frames:scores.length,strongFrames,thresholds:{startModelScore:.30,strongModelScore:.35,continueModelScore:.16},confidenceMeaning:'Relative evidence score; not a calibrated probability'}};
}
function chunkStarts(duration){const n=Math.ceil(duration/.04),starts=[0];if(n<=OUTPUT)return starts;for(let first=150;first+OUTPUT<n;first+=150)starts.push(first);const last=Math.max(0,Math.ceil(duration/.04)-OUTPUT);if(last!==starts[starts.length-1])starts.push(last);return starts;}
async function analyze(reader,config,options={}){
 const runtime=options.ort||root.ort,report=options.report||(()=>{}),model=options.model||await(await fetch('models/vocal-model.json')).json(),frontend=options.frontend||await(await fetch('models/vocal-frontend.json')).json(),n=Math.ceil(reader.duration/.04),scores=new Float32Array(n),weights=new Float32Array(n),detail=new Float32Array(Math.ceil(reader.duration/.02)),starts=chunkStarts(reader.duration);let session;
 try{
  report(0,'Listening for singing','Frame-MN10 • trained on timed sound events • entirely on this device');
  for(let k=0;k<starts.length;k++){
   const first=starts[k],pcm=await pcm16000(reader,first*640,CONTEXT,config);let peak=0;for(const x of pcm)peak=Math.max(peak,Math.abs(x));
   if(peak>1e-7){
    const features=logMel(pcm,frontend);
    // Supporting mixture detail is admitted only where real singing evidence
    // exists. It is never represented as a separated voice or sung note.
    for(let f=0;f<FRAMES;f+=2){const at=first*2+f/2;if(at>=detail.length)break;let sum=0;for(let b=40;b<105;b++)sum+=Math.exp((features[b*FRAMES+f]*5-4.5)/2);let energy=0;for(let j=f*HOP;j<Math.min(pcm.length,(f+2)*HOP);j++)energy+=pcm[j]*pcm[j];if(energy/320>1e-12)detail[at]=Math.max(detail[at],sum/65);}
    if(!session)session=await runtime.InferenceSession.create(new URL('models/'+model.file,root.location.href).href,{executionProviders:['wasm'],graphOptimizationLevel:'all',enableCpuMemArena:true});
    const tensor=new runtime.Tensor('float32',features,[1,1,BANDS,FRAMES]);let out;
    try{out=await session.run({log_mel:tensor});const all=out.scores.data;for(let f=0;f<OUTPUT&&first+f<n;f++){let singing=0;for(const id of model.singingClassIds)singing=Math.max(singing,all[id*OUTPUT+f]);const w=.1+.9*Math.sin(Math.PI*(f+.5)/OUTPUT);scores[first+f]+=singing*w;weights[first+f]+=w;}}finally{if(out)for(const t of Object.values(out))t.dispose?.();tensor.dispose?.();}
   }
   report((k+1)/starts.length,'Following sung phrases',`${Math.min(reader.duration,(first+OUTPUT)*.04).toFixed(0)} / ${reader.duration.toFixed(0)} seconds`);
  }
  for(let i=0;i<n;i++)scores[i]/=weights[i]||1;
  const result=summarize(scores,detail,reader.duration,model);if(options.includeDiagnostics)result.classifierScores=Array.from(scores);return result;
 }finally{if(session)await session.release();}
}
root.LightForgeVocals={analyze,logMel,pcm16000,summarize,chunkStarts};
if(typeof module!=='undefined'&&module.exports)module.exports=root.LightForgeVocals;
})(typeof self!=='undefined'?self:globalThis);
