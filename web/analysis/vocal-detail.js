/* Separated-vocal musical articulation. Original LightForge implementation, MIT.
 * The supplied PCM must be an actual trained separator's vocal output. A stem
 * can contain bleed: waveform periodicity alone never proves a human singer.
 * This module estimates source-clock phrasing/pitch; it does not align lyrics.
 */
(function(scope){'use strict';
const RATE=11025,WINDOW=1024,FFT_SIZE=2048,FINE=.005,STEP=.02,CONTOUR_STEP=.04;
const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,v)),round=(v,p=3)=>Number(v.toFixed(p));
function quantile(values,q){if(!values.length)return 0;const a=Float32Array.from(values);a.sort();return a[Math.floor((a.length-1)*q)];}
function append(a,b){const out=new Float32Array(a.length+b.length);out.set(a);out.set(b,a.length);return out;}
function filter(rate){const out=new Float64Array(65),cutoff=4600/rate;let total=0;for(let i=0;i<65;i++){const t=i-32,w=.42+.5*Math.cos(Math.PI*t/32)+.08*Math.cos(2*Math.PI*t/32);out[i]=(t?Math.sin(2*Math.PI*cutoff*t)/(Math.PI*t):2*cutoff)*w;total+=out[i];}for(let i=0;i<65;i++)out[i]/=total;return out;}
function maxRange(values,start,end){let max=0;for(let i=Math.max(0,start);i<Math.min(values.length,end);i++)max=Math.max(max,values[i]||0);return max;}
function rollingMaximum(values,radius){const out=new Float32Array(values.length),deque=new Int32Array(values.length);let head=0,tail=0,right=0;for(let i=0;i<values.length;i++){while(right<Math.min(values.length,i+radius+1)){while(tail>head&&values[deque[tail-1]]<=values[right])tail--;deque[tail++]=right++;}while(tail>head&&deque[head]<i-radius)head++;out[i]=values[deque[head]]||0;}return out;}
function localPowerRatio(voice,residual,radius=3){const out=new Float32Array(voice.length);if(!residual){out.fill(1);return out;}let a=0,b=0,left=0,right=0;for(let i=0;i<voice.length;i++){while(right<Math.min(voice.length,i+radius+1)){a+=voice[right]*voice[right];const r=residual[Math.min(residual.length-1,right*4)]||0;b+=r*r;right++;}while(left<Math.max(0,i-radius)){a-=voice[left]*voice[left];const r=residual[Math.min(residual.length-1,left*4)]||0;b-=r*r;left++;}out[i]=clamp(a/(a+b+1e-14));}return out;}
function classifierAt(classifier,time,key){const values=key==='singing'?(classifier?.singingScores||classifier?.classifierScores):classifier?.speechScores;if(!values?.length)return 0;const step=classifier.frameStep||classifier.frameSeconds||.04,x=time/step-.5,i=Math.floor(x),f=clamp(x-i);return clamp((values[Math.max(0,Math.min(values.length-1,i))]||0)*(1-f)+(values[Math.max(0,Math.min(values.length-1,i+1))]||0)*f);}

class Pitch {
 constructor(){if(!scope.LightForgeDSP?.FFT)throw new Error('Vocal detail requires LightForgeDSP.FFT.');this.fft=new scope.LightForgeDSP.FFT(FFT_SIZE);this.re=new Float64Array(FFT_SIZE);this.im=new Float64Array(FFT_SIZE);this.energy=new Float64Array(WINDOW+1);this.window=Float64Array.from({length:WINDOW},(_,i)=>.5-.5*Math.cos(2*Math.PI*i/(WINDOW-1)));}
 measure(pcm,start){const {re,im,energy,window}=this;re.fill(0);im.fill(0);energy[0]=0;let mean=0;for(let i=0;i<WINDOW;i++)mean+=pcm[start+i]||0;mean/=WINDOW;
  for(let i=0;i<WINDOW;i++){const v=((pcm[start+i]||0)-mean)*window[i];re[i]=v;energy[i+1]=energy[i]+v*v;}if(energy[WINDOW]<1e-8)return {frequency:0,confidence:0};
  this.fft.run(re,im);for(let i=0;i<FFT_SIZE;i++){re[i]=re[i]*re[i]+im[i]*im[i];im[i]=0;}this.fft.run(re,im,true);
  const min=Math.floor(RATE/1100),max=Math.ceil(RATE/55),correlation=new Float64Array(max+2);let best=0;
  for(let lag=min-1;lag<=max+1;lag++){const denominator=Math.sqrt(energy[WINDOW-lag]*(energy[WINDOW]-energy[lag]));correlation[lag]=denominator>1e-12?clamp(re[lag]/denominator):0;if(lag>=min&&lag<=max)best=Math.max(best,correlation[lag]);}
  if(best<.62)return {frequency:0,confidence:0};
  // Select the earliest strong periodic maximum, reducing octave-down errors.
  // Local energy normalization accommodates expression and vibrato. This is a
  // periodicity estimate, not a neural sung-note transcription model.
  let lag=0;for(let i=min;i<=max;i++)if(correlation[i]>=Math.max(.62,best*.94)&&correlation[i]>=correlation[i-1]&&correlation[i]>correlation[i+1]){lag=i;break;}
  if(!lag)return {frequency:0,confidence:0};const a=correlation[lag-1],b=correlation[lag],c=correlation[lag+1],delta=clamp(.5*(a-c)/(a-2*b+c||1),-.5,.5),frequency=RATE/(lag+delta);
  return frequency>=55&&frequency<=1100?{frequency,confidence:clamp((b-.42)/.58)}:{frequency:0,confidence:0};
 }
}

class Extractor {
 constructor({sampleRate=44100,duration}={}){if(![22050,44100].includes(sampleRate))throw new Error('Separated vocals must use 22.05 or 44.1 kHz PCM.');if(!Number.isFinite(duration)||duration<0||duration>14400.05)throw new Error('Vocal detail supports music up to four hours.');this.sampleRate=sampleRate;this.duration=duration;this.totalSamples=Math.ceil(duration*sampleRate);this.factor=sampleRate/RATE;this.filter=filter(sampleRate);this.pitch=new Pitch();this.raw=new Float32Array(0);this.residual=new Float32Array(0);this.rawBase=0;this.received=0;this.down=new Float32Array(0);this.downBase=0;this.nextDown=0;this.nextFine=0;this.nextPitch=0;this.hasResidual=null;this.finished=false;this.fineEnergy=new Float32Array(Math.ceil(duration/FINE));this.residualEnergy=new Float32Array(this.fineEnergy.length);this.frequency=new Float32Array(Math.ceil(duration/STEP));this.periodicity=new Float32Array(this.frequency.length);this.maxBufferedSamples=0;}
 push(samples,startSample=this.received,accompaniment){if(this.finished)throw new Error('Vocal detail is already complete.');if(!(samples instanceof Float32Array)||!Number.isInteger(startSample)||startSample!==this.received)throw new Error('Separated vocal chunks must be contiguous Float32 PCM on the original sample clock.');if(this.received+samples.length>this.totalSamples+1)throw new Error('Separated vocal data exceeds its declared duration.');if(accompaniment&&(!(accompaniment instanceof Float32Array)||accompaniment.length!==samples.length))throw new Error('Accompaniment and vocal chunks must have matching sample counts.');if(samples.length){const has=!!accompaniment;if(this.hasResidual===null)this.hasResidual=has;else if(this.hasResidual!==has)throw new Error('Separated accompaniment must be supplied consistently.');for(let i=0;i<samples.length;i++)if(!Number.isFinite(samples[i])||(has&&!Number.isFinite(accompaniment[i])))throw new Error('Separated audio contains invalid samples.');}
  this.raw=append(this.raw,samples);if(this.hasResidual)this.residual=append(this.residual,accompaniment||new Float32Array(0));this.received+=samples.length;this.maxBufferedSamples=Math.max(this.maxBufferedSamples,this.raw.length+this.down.length);this.process(false);return this;
 }
 process(final){const rate=this.sampleRate,readEnd=this.received,energyHalf=Math.round(rate*.005);
  while(this.nextFine<this.fineEnergy.length){const center=Math.round(this.nextFine*FINE*rate);if(!final&&center+energyHalf>readEnd)break;let a=0,b=0;for(let i=center-energyHalf;i<center+energyHalf;i++){const at=i-this.rawBase,v=this.raw[at]||0,r=this.residual[at]||0;a+=v*v;b+=r*r;}this.fineEnergy[this.nextFine]=Math.sqrt(a/(energyHalf*2));if(this.hasResidual)this.residualEnergy[this.nextFine]=Math.sqrt(b/(energyHalf*2));this.nextFine++;}
  const limit=final?Math.ceil(this.totalSamples/this.factor):Math.max(this.nextDown,Math.floor((readEnd-33)/this.factor)+1),count=Math.max(0,limit-this.nextDown),part=new Float32Array(count);
  for(let i=0;i<count;i++){const center=(this.nextDown+i)*this.factor-this.rawBase;let v=0;for(let k=0;k<65;k++)v+=(this.raw[center+k-32]||0)*this.filter[k];part[i]=v;}this.nextDown=limit;this.down=append(this.down,part);
  while(this.nextPitch<this.frequency.length){const center=Math.round(this.nextPitch*STEP*RATE);if(!final&&center+WINDOW/2>this.nextDown)break;const p=this.pitch.measure(this.down,center-WINDOW/2-this.downBase);this.frequency[this.nextPitch]=p.frequency;this.periodicity[this.nextPitch]=p.confidence;this.nextPitch++;}
  const rawKeep=Math.max(this.rawBase,Math.min(Math.round(this.nextFine*FINE*rate)-energyHalf,this.nextDown*this.factor-32)),discard=Math.max(0,rawKeep-this.rawBase);if(discard){this.raw=this.raw.slice(discard);if(this.hasResidual)this.residual=this.residual.slice(discard);this.rawBase=rawKeep;}
  const downKeep=Math.max(this.downBase,Math.round(this.nextPitch*STEP*RATE)-WINDOW/2),downDiscard=Math.max(0,downKeep-this.downBase);if(downDiscard){this.down=this.down.slice(downDiscard);this.downBase=downKeep;}
 }
 finish(options={}){if(this.finished)throw new Error('Vocal detail is already complete.');if(Math.abs(this.received-this.totalSamples)>1)throw new Error('Separated vocal audio ended before its declared duration.');this.process(true);this.finished=true;const result=summarize({duration:this.duration,fineEnergy:this.fineEnergy,residualEnergy:this.hasResidual?this.residualEnergy:null,frequency:this.frequency,periodicity:this.periodicity},options);result.diagnostics.sampleRate=this.sampleRate;result.diagnostics.maxBufferedPcmSamples=this.maxBufferedSamples;this.raw=this.down=this.residual=new Float32Array(0);return result;}
}

function summarize(data,{classifier={},model}={}){
 const {duration,fineEnergy,residualEnergy,frequency,periodicity}=data,n=Math.ceil(duration/STEP),count=fineEnergy.length,levels=new Float32Array(n),reference=new Float32Array(n),singing=new Float32Array(n),speech=new Float32Array(n),sourceSupport=new Uint8Array(n),sourceLed=new Uint8Array(n),active=new Uint8Array(n),pitch=new Float32Array(n);let peakScore=0;
 // Local four-second percentiles prevent a loud chorus from suppressing a
 // quiet verse. Interpolation avoids hard normalization jumps at block edges.
 const frameEnergy=Float32Array.from({length:n},(_,i)=>maxRange(fineEnergy,i*4,i*4+4)),localPeak=rollingMaximum(frameEnergy,10),sourceRatio=localPowerRatio(frameEnergy,residualEnergy);
 for(let i=0;i<n;i++){singing[i]=classifierAt(classifier,i*STEP,'singing');speech[i]=classifierAt(classifier,i*STEP,'speech');}
 const semanticContext=rollingMaximum(Float32Array.from({length:n},(_,i)=>Math.max(singing[i],speech[i])),50);
 const block=200,blocks=Math.ceil(n/block),scales=new Float32Array(blocks);for(let b=0;b<blocks;b++){const from=Math.max(0,(b*block-100)*4),to=Math.min(count,((b+1)*block+100)*4);scales[b]=Math.max(.00004,quantile(fineEnergy.subarray(from,to),.85));}
 for(let i=0;i<n;i++){const x=i/block-.5,b=Math.floor(x),fraction=clamp(x-b),scale=scales[Math.max(0,b)]*(1-fraction)+scales[Math.min(blocks-1,b+1)]*fraction,e=maxRange(fineEnergy,i*4,i*4+4);singing[i]=classifierAt(classifier,i*STEP,'singing');speech[i]=classifierAt(classifier,i*STEP,'speech');const learned=Math.max(singing[i],speech[i]),quietEvidence=sourceRatio[i]>.08||learned>.4;reference[i]=Math.max(.00004,quietEvidence?Math.min(scale,localPeak[i]*1.15):scale);levels[i]=clamp(e/reference[i]);sourceSupport[i]=sourceRatio[i]>=(learned>.4?.0008:.008)?1:0;peakScore=Math.max(peakScore,singing[i]);const conf=periodicity[i]||0;pitch[i]=frequency[i]>0&&conf>=.45?69+12*Math.log2(frequency[i]/440):0;
  // Separation is evidence of a vocal source, not a guarantee: retain source
  // dynamics only when supported by learned singing/speech evidence nearby.
  const voiceEvidence=Math.max(singing[i],speech[i]);
  // The trained separator is independent learned evidence. Distorted or softly
  // sung voices may have weak event-classifier scores and intermittent pitch.
  // A locally prominent isolated source (at least 2.5% of combined power) may
  // therefore retain its acoustic phrase with a weak semantic seed within one
  // second. It remains an uncertain vocal source, never confident singing.
  sourceLed[i]=sourceRatio[i]>=.025&&levels[i]>=.20&&semanticContext[i]>=.035?1:0;
  active[i]=sourceSupport[i]&&e>Math.max(.000035,reference[i]*.10)&&(voiceEvidence>=.09||(pitch[i]&&voiceEvidence>=.045)||sourceLed[i])?1:0;
 }
 const raw=[];let first=-1,last=-1;
 for(let i=0;i<n;i++)if(active[i]){if(first<0)first=i;else if(i-last>12){raw.push({first,last});first=i;}last=i;}if(first>=0)raw.push({first,last});
 const articulated=new Float32Array(count);for(let i=0;i<count;i++){let total=0;const from=Math.max(0,i-2),to=Math.min(count,i+3);for(let j=from;j<to;j++)total+=fineEnergy[j];articulated[i]=total/(to-from);}
 const phrases=[],accents=[],notes=[],envelope=new Array(n).fill(0),contour={step:CONTOUR_STEP,midi:new Array(Math.ceil(duration/CONTOUR_STEP)).fill(0),confidence:new Array(Math.ceil(duration/CONTOUR_STEP)).fill(0)};let rejectedLeakage=0,rejectedAmbiguous=0;
 for(const run of raw){let a=run.first,b=run.last+1;if((b-a)*STEP<.16-1e-8)continue;let maxSing=0,maxSpeech=0,voiced=0,peakLevel=0,peakFrame=a,totalEnergy=0,totalResidual=0,separatedSupport=0,contextScore=0;
  for(let i=a;i<b;i++){separatedSupport+=sourceLed[i];contextScore=Math.max(contextScore,semanticContext[i]);maxSing=Math.max(maxSing,singing[i]);maxSpeech=Math.max(maxSpeech,speech[i]);if(pitch[i])voiced++;if(levels[i]>peakLevel){peakLevel=levels[i];peakFrame=i;}const e=fineEnergy[i*4]||0,r=residualEnergy?.[i*4]||0;totalEnergy+=e*e;totalResidual+=r*r;}
  const voicedFraction=voiced/(b-a),stemRatio=totalEnergy/(totalEnergy+totalResidual+1e-14),speechDominates=maxSpeech>=.24&&maxSpeech>maxSing*1.35,kind=speechDominates?'speech':maxSing>=.19?'singing':'vocal';
  const sourceLedAdmission=separatedSupport*STEP>=.20&&separatedSupport/(b-a)>=.35&&stemRatio>=.025&&contextScore>=.035;
  if(maxSing<.11&&maxSpeech<.19&&!(maxSing>=.055&&voicedFraction>.65&&stemRatio>.4)&&!sourceLedAdmission){rejectedAmbiguous++;continue;}
  if(residualEnergy&&stemRatio<.0015&&maxSing<.3&&maxSpeech<.35){rejectedLeakage++;continue;}
  // Recover edges from this stem's measured energy around the classifier's
  // support. No drum onset or beat grid participates in the vocal clock.
  const threshold=Math.max(.000035,quantile(fineEnergy.subarray(a*4,Math.min(count,b*4)),.8)*.10);let af=a*4,bf=Math.min(count,b*4),lower=Math.max(0,af-60),upper=Math.min(count,bf+60);
  while(af>lower&&fineEnergy[af-1]>=threshold&&sourceSupport[Math.min(n-1,Math.floor((af-1)/4))])af--;while(af<bf&&fineEnergy[af]<threshold)af++;while(bf<upper&&fineEnergy[bf]>=threshold&&sourceSupport[Math.min(n-1,Math.floor(bf/4))])bf++;while(bf>af&&fineEnergy[bf-1]<threshold)bf--;
  const start=round(af*FINE),end=Math.min(duration,round(bf*FINE));if(end-start<.16-1e-8)continue;const confidence=clamp(.30+.4*Math.max(maxSing,maxSpeech)+.2*voicedFraction+.1*Math.sqrt(stemRatio));
  const phrase={start,end,releaseTime:end,confidence:round(confidence),modelScore:round(maxSing,4),speechScore:round(maxSpeech,4),strength:round(peakLevel),peakTime:round(clamp(peakFrame*STEP,start,end)),kind,evidenceMode:sourceLedAdmission&&maxSing<.11&&maxSpeech<.19?'separation-led':'classifier-supported',estimated:true,source:'separated-vocals',voicedFraction:round(voicedFraction),stemEnergyRatio:round(stemRatio,4)};phrases.push(phrase);a=Math.max(0,Math.floor(start/STEP));b=Math.min(n,Math.ceil(end/STEP));
  for(let i=a;i<b;i++){envelope[i]=round(clamp(levels[i])*(.5+.5*confidence));if(i%2===0&&kind!=='speech'&&pitch[i]&&periodicity[i]>=.55){contour.midi[i/2]=round(pitch[i],2);contour.confidence[i/2]=round(periodicity[i]*confidence);}}
  accents.push({time:start,strength:round(Math.max(.35,levels[Math.min(n-1,a+1)])),confidence:phrase.confidence,kind:'entrance',source:'separated-vocals',estimated:true});
  // Positive vocal energy change on a 5 ms grid, with a 40 ms baseline and
  // 100 ms refractory period. These are articulations, never claimed syllables.
  let previous=start;for(let i=af+8;i<bf-2;i++){let baseline=0,nextBaseline=0,priorBaseline=0;for(let j=i-8;j<i-2;j++){baseline+=articulated[j];nextBaseline+=articulated[j+1];priorBaseline+=articulated[j-1];}baseline/=6;const e=articulated[i],rise=e-baseline,local=reference[Math.min(n-1,Math.floor(i/4))];if(rise<Math.max(.00004,local*.13)||rise<baseline*.27||rise<articulated[i+1]-nextBaseline/6||rise<=articulated[i-1]-priorBaseline/6)continue;let edge=i;while(edge>Math.max(af,i-20)&&articulated[edge-1]<articulated[edge])edge--;const time=round(edge*FINE);if(time-previous<.10-1e-8||end-time<.035)continue;accents.push({time,strength:round(clamp(rise/local)),confidence:round(confidence*(.7+.3*clamp(rise/Math.max(e,.00001)))),kind:'syllabic-accent',source:'separated-vocals',estimated:true});previous=time;}
  if(kind==='speech')continue;
  const runs=[];let note=null;for(let i=a;i<b;i++){const p=pitch[i];if(p&&periodicity[i]>=.55&&levels[i]>.1){if(note&&i-note.last<=2&&Math.abs(p-note.reference)<=.95){note.last=i;note.values.push(p);note.reference=quantile(note.values.slice(-7),.5);}else{if(note)runs.push(note);note={first:i,last:i,reference:p,values:[p]};}}else if(note&&i-note.last>1){runs.push(note);note=null;}}if(note)runs.push(note);
  for(const r of runs){let ns=Math.max(start,r.first*STEP),ne=Math.min(end,(r.last+1)*STEP);if(ne-ns<.14-1e-8||r.values.length<6)continue;const midi=quantile(r.values,.5),spread=quantile(r.values.map(p=>Math.abs(p-midi)),.9);if(spread>.8)continue;
   // Pitch windows smear entrances; the containing source-energy phrase keeps
   // them from extending into silence. Adjacent notes retain their pitch clock.
   if(ns-start<.07)ns=start;if(end-ne<.07)ne=end;let strength=0,peak=ns,meanConfidence=0;for(let i=r.first;i<=r.last;i++){meanConfidence+=periodicity[i];if(levels[i]>strength){strength=levels[i];peak=i*STEP;}}
   const noteConfidence=confidence*meanConfidence/(r.last-r.first+1)*clamp(1-spread*.25);if(noteConfidence<.38)continue;notes.push({start:round(ns),end:Math.min(end,round(ne)),midi:round(midi,2),frequency:round(440*2**((midi-69)/12),2),confidence:round(noteConfidence),strength:round(strength),peakTime:round(clamp(peak,ns,ne)),type:ne-ns>=.35-1e-8?'held-note':'note',estimated:true,source:'separated-vocals'});
  }
 }
 // Adjacent classifier candidates can expand into the same source sustain.
 // Merge compatible phrases and deduplicate entrances without changing clocks.
 const merged=[];for(const p of phrases){const previous=merged[merged.length-1];if(previous&&p.start<=previous.end&&p.kind===previous.kind){previous.end=Math.max(previous.end,p.end);previous.releaseTime=previous.end;previous.confidence=Math.max(previous.confidence,p.confidence);previous.modelScore=Math.max(previous.modelScore,p.modelScore);if(p.strength>previous.strength){previous.strength=p.strength;previous.peakTime=p.peakTime;}}else merged.push(p);}
 notes.sort((a,b)=>a.start-b.start);for(let i=0;i<notes.length-1;i++)notes[i].end=Math.min(notes[i].end,notes[i+1].start);const acceptedNotes=notes.filter(n=>n.end-n.start>=.12-1e-8),uniqueAccents=accents.sort((a,b)=>a.time-b.time).filter((a,i,all)=>!i||a.time-all[i-1].time>=.095-1e-8);
 const coverage=merged.reduce((sum,p)=>sum+p.end-p.start,0)/Math.max(.001,duration),singingCount=merged.filter(p=>p.kind==='singing').length,presence=singingCount?'detected':merged.length||peakScore>.09?'uncertain':'not_detected',warnings=[];
 if(!singingCount&&merged.some(p=>p.kind==='vocal'))warnings.push('The separated voice is present, but singing versus speech remains uncertain in some passages.');if(!singingCount&&merged.length&&merged.every(p=>p.kind==='speech'))warnings.push('Spoken voice is detected; sung-note contours are not inferred for spoken passages.');if(!merged.length&&peakScore>.09)warnings.push('Voice evidence is ambiguous; uncertain passages stay with the accompaniment.');
 return {available:true,source:'separated-vocals',sourceSeparated:true,lyricsAligned:false,presence,confidence:round(merged.reduce((m,p)=>Math.max(m,p.confidence),0)),modelScore:round(peakScore,4),coverage:round(coverage,4),phrases:merged,accents:uniqueAccents,notes:acceptedNotes,envelope,envelopeStep:STEP,pitchContour:contour,method:'Trained vocal separation with learned voice evidence, local source-energy articulation and periodic pitch tracking',model:model||classifier.model||null,timing:{energyFrameMs:5,envelopeMs:20,pitchFrameMs:20,pitchWindowMs:round(WINDOW/RATE*1000,1),classifierFrameMs:round((classifier.frameStep||.04)*1000),alignment:'Separated vocal PCM clock; measured energy edges and estimated pitch; no lyric or word alignment',gridIsAccuracy:false},warnings,diagnostics:{version:1,pitchRangeHz:[55,1100],sourceSeparated:true,lyricsAligned:false,pitchIsEstimated:true,confidenceIsProbability:false,localNormalizationSeconds:4,quietRecoveryContextSeconds:.4,sourceLedThresholds:{combinedPowerFraction:.025,normalizedLocalLevel:.20,semanticSeed:.035,contextRadiusSeconds:1,minimumSupportSeconds:.20},phrases:merged.length,singingPhrases:singingCount,speechPhrases:merged.filter(p=>p.kind==='speech').length,notes:acceptedNotes.length,heldNotes:acceptedNotes.filter(n=>n.type==='held-note').length,rejectedLeakage,rejectedAmbiguous,limitations:'Separation bleed, layered voices, distortion, unvoiced consonants and rapid pitch changes can remain ambiguous. Pitch follows a dominant periodic voice, not every harmony. Articulation markers are not transcribed words.'}};
}
scope.LightForgeVocalDetail={Extractor,Pitch,summarize,version:'1.0.0'};
if(typeof module!=='undefined'&&module.exports)module.exports=scope.LightForgeVocalDetail;
})(typeof self!=='undefined'?self:globalThis);
