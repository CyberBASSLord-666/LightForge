/* LightForge music features. Exact BeatNet log-spectrum geometry; no network access. */
(function(scope){'use strict';
const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x));
// Optional per-worker probes wrap only the computation they name.
const measure=(telemetry,name,fn)=>telemetry&&typeof telemetry.measure==='function'?telemetry.measure('performance.'+name,fn):fn();
function percentile(a,p){if(!a.length)return 0;const b=Float64Array.from(a);b.sort();return b[Math.min(b.length-1,Math.floor(p*(b.length-1)))];}
class FFT {
 constructor(n){this.n=n;this.rev=new Uint32Array(n);this.cos=new Float64Array(n/2);this.sin=new Float64Array(n/2);let bits=Math.log2(n);for(let i=0;i<n;i++){let a=i,r=0;for(let j=0;j<bits;j++){r=(r<<1)|(a&1);a>>=1;}this.rev[i]=r;}for(let i=0;i<n/2;i++){this.cos[i]=Math.cos(2*Math.PI*i/n);this.sin[i]=Math.sin(2*Math.PI*i/n);}}
 run(r,im,inverse=false){const n=this.n;for(let i=0;i<n;i++){const j=this.rev[i];if(i<j){let t=r[i];r[i]=r[j];r[j]=t;t=im[i];im[i]=im[j];im[j]=t;}}for(let len=2;len<=n;len*=2){const half=len/2,step=n/len;for(let start=0;start<n;start+=len){for(let j=0;j<half;j++){let k=j*step,c=this.cos[k],s=this.sin[k]*(inverse?1:-1),a=start+j,b=a+half,tr=r[b]*c-im[b]*s,ti=r[b]*s+im[b]*c;r[b]=r[a]-tr;im[b]=im[a]-ti;r[a]+=tr;im[a]+=ti;}}}if(inverse){for(let i=0;i<n;i++){r[i]/=n;im[i]/=n;}}}
}
class Spectrum {
 constructor(n){this.n=n;let m=1;while(m<n*2-1)m*=2;this.m=m;this.fft=new FFT(m);this.cr=new Float64Array(n);this.ci=new Float64Array(n);this.window=new Float64Array(n);this.br=new Float64Array(m);this.bi=new Float64Array(m);this.r=new Float64Array(m);this.im=new Float64Array(m);for(let i=0;i<n;i++){let p=Math.PI*((i*i)%(2*n))/n;this.cr[i]=Math.cos(p);this.ci[i]=Math.sin(p);this.window[i]=0.5-0.5*Math.cos(2*Math.PI*i/(n-1));this.br[i]=this.cr[i];this.bi[i]=this.ci[i];if(i){this.br[m-i]=this.cr[i];this.bi[m-i]=this.ci[i];}}this.fft.run(this.br,this.bi);this.mag=new Float64Array(Math.floor(n/2));}
 run(samples,offset){const {r,im,n,m}=this;r.fill(0);im.fill(0);for(let i=0;i<n;i++){let a=(samples[offset+i]||0)*this.window[i];r[i]=a*this.cr[i];im[i]=-a*this.ci[i];}this.fft.run(r,im);for(let i=0;i<m;i++){let re=r[i]*this.br[i]-im[i]*this.bi[i];im[i]=r[i]*this.bi[i]+im[i]*this.br[i];r[i]=re;}this.fft.run(r,im,true);for(let i=0;i<this.mag.length;i++)this.mag[i]=Math.hypot(r[i],im[i]);return this.mag;}
}
class FeatureExtractor {
 constructor(config,telemetry){this.telemetry=telemetry;this.cfg=config;this.spectrum=new Spectrum(config.windowLength);this.previous=new Float32Array(136);this.hadFrame=false;}
 extract(samples,firstOffset,frames){return measure(frames>0?this.telemetry:null,'feature_generation',()=>{const features=new Float32Array(frames*272),bass=new Float32Array(frames),mid=new Float32Array(frames),high=new Float32Array(frames),rms=new Float32Array(frames),colour=new Float32Array(frames*3),fineRms=new Float32Array(frames*4),chroma=new Float32Array(frames*12);let maxSample=0;
 for(let f=0;f<frames;f++){let offset=firstOffset+f*this.cfg.hop,mag=this.spectrum.run(samples,offset),energy=0;for(let j=0;j<1411;j++){let a=samples[offset+j]||0;energy+=a*a;maxSample=Math.max(maxSample,Math.abs(a));}rms[f]=Math.sqrt(energy/1411);for(let b=0;b<136;b++){let band=this.cfg.bands[b],sum=0;for(let k=0;k<band.weights.length;k++)sum+=mag[band.start+k]*band.weights[k];let v=Math.log10(1+sum),d=this.hadFrame?Math.max(0,v-this.previous[b]):0;features[f*272+b]=v;features[f*272+136+b]=d;this.previous[b]=v;if(band.frequency>=60&&band.frequency<=4000){const pitch=((Math.round(69+12*Math.log2(band.frequency/440))%12)+12)%12;chroma[f*12+pitch]+=v;}let n=band.frequency<180?0:band.frequency<2400?1:2;colour[f*3+n]+=v;if(n===0)bass[f]+=d;else if(n===1)mid[f]+=d;else high[f]+=d;}this.hadFrame=true;
 // Forward 5 ms PCM bins use the SAME audio clock as the centered neural frame.
 // No assumed model latency or global timestamp subtraction is applied.
 for(let q=0;q<4;q++){const a=offset+Math.floor(this.cfg.windowLength/2)+Math.round(q*this.cfg.hop/4),b=offset+Math.floor(this.cfg.windowLength/2)+Math.round((q+1)*this.cfg.hop/4);let e=0;for(let j=a;j<b;j++){const v=samples[j]||0;e+=v*v;}fineRms[f*4+q]=Math.sqrt(e/Math.max(1,b-a));}}
 return {features,bass,mid,high,rms,colour,fineRms,chroma,maxSample};});}
}
function rolling(a,radius){let out=new Float32Array(a.length),sum=0,left=0,right=-1;for(let i=0;i<a.length;i++){while(right<Math.min(a.length-1,i+radius))sum+=a[++right];while(left<Math.max(0,i-radius))sum-=a[left++];out[i]=sum/(right-left+1);}return out;}
function pickOnsets(a,band,sensitivity){const baseline=rolling(a,25),scale=percentile(a,0.94)||1,out=[];let last=-10;for(let i=1;i<a.length-1;i++){if(a[i]>=a[i-1]&&a[i]>a[i+1]&&a[i]>Math.max(scale*(0.14-0.10*sensitivity),baseline[i]*(1.65-0.8*sensitivity))&&i-last>=3){out.push({time:i*0.02,strength:clamp(a[i]/scale),band});last=i;}}return out;}
// Activity is measured independently of the neural output. Short inter-note gaps
// remain inside a musical passage; a sustained quiet rest is an explicit boundary.
function activityFromEnvelope(envelope,step,duration){
 const floor=Math.max(0.00008,percentile(envelope,0.95)*0.004),raw=[];let first=-1,last=-1;
 for(let i=0;i<envelope.length;i++)if(envelope[i]>floor){if(first<0)first=i;else if((i-last)*step>0.65){raw.push({start:Math.max(0,first*step-0.015),end:Math.min(duration,(last+1)*step+0.02)});first=i;}last=i;}
 if(first>=0)raw.push({start:Math.max(0,first*step-0.015),end:Math.min(duration,(last+1)*step+0.02)});
 return {ranges:raw.filter(r=>r.end-r.start>=0.015),floor};
}
function lowerBound(a,t,key=x=>x){let lo=0,hi=a.length;while(lo<hi){const m=(lo+hi)>>1;if(key(a[m])<t)lo=m+1;else hi=m;}return lo;}
function insideRanges(t,ranges){const i=lowerBound(ranges,t,r=>r.end);return i<ranges.length&&t>=ranges[i].start;}
function pcmAttacks(envelope,step=0.005){
 const norm=percentile(envelope,0.96)||1,out=[];let last=-1e6;
 for(let i=1;i<envelope.length-1;i++){
  let before=0;for(let j=Math.max(0,i-5);j<i;j++)before+=envelope[j];before/=Math.min(i,5);
  const rise=envelope[i]-before,next=envelope[i+1]-before;
  if(rise<Math.max(0.00025,norm*0.035)||rise<before*0.18||next>rise*1.03)continue;
  // Recover the beginning of this specific attack, rather than shifting all beats.
  const threshold=before+rise*0.12;let start=i;while(start>Math.max(0,i-4)&&envelope[start-1]>threshold)start--;
  const time=start*step,strength=clamp(rise/(norm*0.8)),candidate={time,strength};
  if(time-last<0.04){if(out.length&&strength>out[out.length-1].strength){out[out.length-1]=candidate;last=time;}continue;}
  out.push(candidate);last=time;
 }
 return out;
}
function alignToAttack(time,attacks,tolerance=0.045){
 let best=null,score=-Infinity;for(let i=lowerBound(attacks,time-tolerance,x=>x.time);i<attacks.length&&attacks[i].time<=time+tolerance;i++){
  const a=attacks[i],s=a.strength*(1-0.45*Math.abs(a.time-time)/tolerance);if(a.strength>=0.09&&s>score){best=a;score=s;}
 }
 return best?best.time:time;
}
function estimatePeriod(sm,start,end,anchor=26){
 let best=0,period=anchor;for(let lag=13;lag<=75;lag++){
  let cross=0,power=0;for(let i=start+lag;i<end;i++){cross+=sm[i]*sm[i-lag];power+=0.5*(sm[i]*sm[i]+sm[i-lag]*sm[i-lag]);}
  // Prefer a supported metrical level without forcing a fixed tempo throughout.
  const score=cross/(power+1e-9)*Math.exp(-0.5*Math.pow(Math.log(lag/anchor)/0.65,2));
  if(score>best){best=score;period=lag;}
 }
 return {period,confidence:clamp(best)};
}
function phaseForMeter(entries,down,meter){
 let best=-Infinity,phase=0,mean=0,count=0;const evidence=entries.map(e=>{let v=0;const frame=Math.round(e.neuralTime/0.02);for(let j=Math.max(0,frame-2);j<=Math.min(down.length-1,frame+2);j++)v=Math.max(v,down[j]);mean+=v;count++;return v;});mean/=Math.max(1,count);
 for(let p=0;p<meter;p++){let on=0,n=0,off=0,k=0;for(let j=0;j<entries.length;j++){if(entries[j].sequenceIndex%meter===p){on+=evidence[j];n++;}else{off+=evidence[j];k++;}}
  const score=(n?on/n:0)-(k?off/k:0);if(n>=2&&score>best){best=score;phase=p;}
 }
 const alternatives=[];for(let p=0;p<meter;p++){let sum=0,n=0;for(let j=0;j<entries.length;j++)if(entries[j].sequenceIndex%meter===p){sum+=evidence[j];n++;}alternatives.push({phase:p,evidence:n?sum/n:0});}alternatives.sort((a,b)=>b.evidence-a.evidence);const confidence=clamp((alternatives[0].evidence-(alternatives[1]?.evidence||0))/Math.max(.12,alternatives[0].evidence));
 return {phase,score:Number.isFinite(best)?best:0,mean,confidence,alternatives};
}
function trackBeats(beat,down,rms,options={}){
 const n=beat.length,duration=options.duration??n*0.02,envelope=options.fineRms||rms,envelopeStep=options.fineRms?0.005:0.02,activity=activityFromEnvelope(envelope,envelopeStep,duration),attacks=options.attacks||[];
 const empty={beats:[],downbeats:[],beatDetails:[],bpm:0,meter:4,meterConfidence:0,beatConfidence:0,activityRanges:activity.ranges};
 if(!activity.ranges.length||n<10)return empty;
 const act=new Float32Array(n);for(let i=0;i<n;i++)act[i]=Math.min(1,Math.max(0,beat[i])+Math.max(0,down[i]));
 const sm=rolling(act,1),manual=Number(options.bpmOverride||0),manualTempo=manual>=40&&manual<=240;
 const global=measure(options.telemetry,'tempo_inference',()=>estimatePeriod(sm,0,n)),period=manualTempo?3000/manual:global.period,entries=[];
 // Preserve a beat lattice through short breaks, but decode independent passages
 // around sustained silence so a restart can establish its own phase and tempo.
 const passages=measure(options.telemetry,'beat_tracking',()=>{const passages=[];for(const r of activity.ranges){const previous=passages[passages.length-1];if(previous&&r.start-previous.end<Math.max(1.2,period*0.06))previous.end=r.end;else passages.push({...r});}return passages;});
 if(manualTempo){
  measure(options.telemetry,'beat_tracking',()=>{
  const seconds=60/manual,bins=Math.ceil(seconds/0.005),fold=new Float64Array(bins);
  // Fold observations modulo the exact requested period; no rounded frame grid.
  for(let i=0;i<n;i++){if(!insideRanges(i*0.02,activity.ranges))continue;const p=Math.round(((i*0.02)%seconds)/seconds*bins)%bins;for(let j=-3;j<=3;j++)fold[(p+j+bins)%bins]+=act[i]*Math.exp(-j*j/4);}
  for(const a of attacks){const p=Math.round((a.time%seconds)/seconds*bins)%bins;for(let j=-2;j<=2;j++)fold[(p+j+bins)%bins]+=0.4*a.strength*Math.exp(-j*j/2);}
  let phase=0;for(let i=1;i<bins;i++)if(fold[i]>fold[phase])phase=i;phase=phase/bins*seconds;
  // Refine the grid phase only, never independently pull its individual beats.
  let correction=0,weight=0;for(const a of attacks){const nearest=phase+Math.round((a.time-phase)/seconds)*seconds,delta=a.time-nearest;if(Math.abs(delta)<=0.035){correction+=delta*a.strength;weight+=a.strength;}}
  if(weight)phase+=correction/weight;
  for(let j=Math.ceil(-phase/seconds),t=phase+j*seconds;t<duration;j++,t=phase+j*seconds){if(insideRanges(t,activity.ranges))entries.push({time:Math.max(0,t),neuralTime:Math.max(0,t),sequenceIndex:j,passage:0,confidence:clamp(act[Math.min(n-1,Math.round(t*50))]||0)});}
  });
 }else if(options.decoder==='transformer'){
  measure(options.telemetry,'beat_tracking',()=>{
  // The pretrained transformer is trained for direct peak decoding. Retain its
  // flexible tempo instead of forcing its activations through the older CRNN lattice.
  const peaks=[];for(let i=0;i<n;i++){if(act[i]<.5)continue;let peak=true;for(let j=Math.max(0,i-3);j<=Math.min(n-1,i+3);j++)if(act[j]>act[i]||(j<i&&act[j]===act[i])){peak=false;break;}if(peak)peaks.push(i);}
  let passage=0,index=0;for(const frame of peaks){const neuralTime=frame*.02,time=alignToAttack(neuralTime,attacks);if(time>=duration||!insideRanges(time,activity.ranges))continue;while(passage<passages.length-1&&time>passages[passage].end){passage++;index=0;}const prev=entries[entries.length-1];if(prev&&time-prev.time<.15)continue;entries.push({time,neuralTime,sequenceIndex:index++,passage,confidence:clamp(act[frame])});}
  });
 }else{
  passages.forEach((range,passage)=>{
   const begin=Math.max(0,Math.floor(range.start*50)),end=Math.min(n,Math.ceil(range.end*50));if(end-begin<5)return;
   const local=measure(options.telemetry,'tempo_inference',()=>{const local=[];for(let i=begin;i<end;i+=200){const estimate=estimatePeriod(sm,Math.max(begin,i-300),Math.min(end,i+300),period);local.push(estimate.confidence>0.08?estimate.period:period);}return local;});
   measure(options.telemetry,'beat_tracking',()=>{
   const count=end-begin,score=new Float64Array(count),back=new Int32Array(count),interval=new Float32Array(count);back.fill(-1);let terminal=-1,terminalScore=-Infinity;
   for(let j=0;j<count;j++){
    const i=begin+j,lp=(i-begin)/200,k=Math.floor(lp),p=(local[k]||period)*(1-(lp-k))+(local[Math.min(local.length-1,k+1)]||period)*(lp-k),reward=act[i]*5;
    let value=reward,pred=-1,bestInterval=p;const low=Math.max(8,Math.floor(p*0.68)),high=Math.min(110,Math.ceil(p*1.48));
    for(let lag=low;lag<=high&&lag<=j;lag++){const prior=j-lag,delta=Math.log(lag/p),change=interval[prior]?Math.log(lag/interval[prior]):0,s=score[prior]+reward-12*delta*delta-3*change*change-0.55;if(s>value){value=s;pred=prior;bestInterval=lag;}}
    score[j]=value;back[j]=pred;interval[j]=bestInterval;
    // End on a supported observation rather than fabricating a final weak beat.
    if(act[i]>0.08&&value>terminalScore){terminal=j;terminalScore=value;}
   }
   if(terminal<0)return;const path=[];for(let j=terminal;j>=0;j=back[j]){path.push(begin+j);if(back[j]<0)break;}path.reverse();
   path.forEach((frame,sequenceIndex)=>{
    const neuralTime=frame*0.02,time=alignToAttack(neuralTime,attacks),e=envelope[Math.min(envelope.length-1,Math.round(time/envelopeStep))]||0;
    if(time>=duration||!insideRanges(time,activity.ranges)||e<activity.floor*0.7||act[frame]<0.055)return;
    if(entries.length&&time-entries[entries.length-1].time<0.15)return;
    entries.push({time,neuralTime,sequenceIndex,passage,confidence:clamp(act[frame])});
   });
   });
  });
 }
 if(!entries.length)return empty;
 const {meter,meterConfidence,phases,phaseFits,downbeatConfidence}=measure(options.telemetry,'downbeat_tracking',()=>{
 let meter=4,bestMeter=-Infinity;const meterScores={};for(const m of [3,4]){let total=0,weight=0;for(let p=0;p<(manualTempo?1:passages.length);p++){const group=entries.filter(e=>e.passage===p),fit=phaseForMeter(group,down,m);total+=fit.score*group.length;weight+=group.length;}const s=total/Math.max(1,weight);meterScores[m]=s;if(s>bestMeter+0.012||(Math.abs(s-bestMeter)<0.012&&m===4)){bestMeter=s;meter=m;}}
 const meterConfidence=clamp(bestMeter*1.6)*clamp((bestMeter-Math.min(meterScores[3],meterScores[4]))/0.15);
 const phases=[],phaseFits=[];for(let p=0;p<(manualTempo?1:passages.length);p++){const fit=phaseForMeter(entries.filter(e=>e.passage===p),down,meter);phases[p]=fit.phase;phaseFits.push(fit);}const downbeatConfidence=phaseFits.length?phaseFits.reduce((s,x)=>s+x.confidence,0)/phaseFits.length:0;
 return {meter,meterConfidence,phases,phaseFits,downbeatConfidence};});
 const {intervals,typical,bpm}=measure(options.telemetry,'tempo_inference',()=>{
 const intervals=[];for(let i=1;i<entries.length;i++){const dt=entries[i].time-entries[i-1].time;if(entries[i].passage===entries[i-1].passage&&dt>=0.24&&dt<=1.55&&entries[i].sequenceIndex-entries[i-1].sequenceIndex===1)intervals.push(dt);}
 const medianPeriod=percentile(intervals,0.5)||period*0.02,nearIntervals=intervals.filter(dt=>Math.abs(dt-medianPeriod)<medianPeriod*0.08),typical=nearIntervals.length>intervals.length*0.85?intervals.reduce((s,x)=>s+x,0)/intervals.length:medianPeriod,bpm=manualTempo?manual:60/typical;
 return {intervals,typical,bpm};});
 const {beatDetails,strength,consistency,beats}=measure(options.telemetry,'beat_tracking',()=>{
 const beatDetails=entries.map((e,i)=>{const nearby=[];for(let j=Math.max(1,i-3);j<=Math.min(entries.length-1,i+3);j++){const a=entries[j-1],b=entries[j],dt=b.time-a.time;if(a.passage===e.passage&&b.passage===e.passage&&b.sequenceIndex-a.sequenceIndex===1&&dt>=0.24&&dt<=1.55)nearby.push(dt);}return {time:e.time,confidence:e.confidence,alignmentOffsetMs:manualTempo?0:Math.round((e.time-e.neuralTime)*1000),localBpm:manualTempo?manual:Math.round(6000/(nearby.length?nearby.reduce((s,x)=>s+x,0)/nearby.length:typical))/100,barPosition:((e.sequenceIndex-phases[e.passage])%meter+meter)%meter+1};});
 const strength=entries.reduce((s,e)=>s+e.confidence,0)/entries.length,consistency=intervals.length?intervals.filter((dt,i)=>!i||Math.abs(Math.log(dt/intervals[i-1]))<0.15).length/intervals.length:0;
 return {beatDetails,strength,consistency,beats:entries.map(e=>e.time)};});
 const {downbeats,barPhaseAlternatives}=measure(options.telemetry,'downbeat_tracking',()=>({downbeats:beatDetails.filter(e=>e.barPosition===1).map(e=>e.time),barPhaseAlternatives:phaseFits.map((fit,passage)=>({passage,confidence:fit.confidence,candidates:fit.alternatives}))}));
 return {beats,downbeats,beatDetails,bpm:Math.round(bpm*100)/100,meter,meterConfidence,downbeatConfidence,barPhaseAlternatives,beatConfidence:clamp(strength*0.7+consistency*0.3),activityRanges:activity.ranges};
}
// Multi-scale box-checkerboard novelty without constructing an O(n²)
// self-similarity matrix: ||mean(left)-mean(right)||² / 2 is the
// normalized within-region minus cross-region dot-product contrast.
// Chroma is evidence of tonal change, never a key/chord/song-form label.
const STRUCTURE_VERSION=2;
function tonalStructure(data,rhythm){
 const empty=reason=>({version:STRUCTURE_VERSION,available:false,reason,sections:[],phrases:[],frameCount:0});
 if(!Number.isFinite(data.duration)||data.duration<=0||data.duration>14400.05)return empty('invalid-duration');
 const chroma=data.chroma,step=data.chromaStep;
 if(!(Array.isArray(chroma)||ArrayBuffer.isView(chroma))||!Number.isFinite(step)||step<.02||step>1||chroma.length%12)return empty('missing-or-invalid-chroma');
 const count=chroma.length/12;
 if(count<12||count>72000||Math.abs(count*step-data.duration)>step+.021)return empty('chroma-coverage');
 for(const value of chroma)if(!Number.isFinite(value)||value<0)return empty('invalid-chroma-value');
 const rms=data.rms,norm=percentile(rms,.94);
 if(!(norm>1e-7))return empty('silent-audio');
 const width=13,prefix=new Float64Array((count+1)*width),beatLength=rhythm.bpm?60/rhythm.bpm:.5;
 // Weak or absent meter does not justify a guessed long bar; four seconds is
 // then only an analysis window, and no alternate beat grid is synthesized.
 const bar=rhythm.meterConfidence>=.35&&rhythm.meter>=2?clamp(beatLength*rhythm.meter,1,6):2;
 let usable=0;
 for(let i=0;i<count;i++){
  const previous=i*width,next=(i+1)*width;for(let b=0;b<width;b++)prefix[next+b]=prefix[previous+b];
  let square=0,total=0,floor=Infinity;for(let b=0;b<12;b++){const value=chroma[i*12+b];square+=value*value;total+=value;floor=Math.min(floor,value);}
  if(!Number.isFinite(square)||!Number.isFinite(total))return empty('invalid-chroma-scale');
  let envelope=0,frames=0;for(let f=Math.floor(i*step*50);f<Math.min(rms.length,Math.ceil((i+1)*step*50));f++){envelope+=rms[f];frames++;}
  // Flat pitch-class noise and near-silence cannot become tonal boundaries.
  const concentration=total>0?Math.sqrt(clamp((12*square/(total*total)-1)/11)):0;
  if(!Number.isFinite(concentration))return empty('invalid-chroma-scale');
  if(square<=1e-20||envelope/Math.max(1,frames)<Math.max(1e-7,norm*.025)||concentration<.035)continue;
  // Remove only the shared pitch-class floor, after the concentration gate;
  // otherwise broadband energy can mask harmony, or flat numerical noise can
  // be amplified into an apparently certain chord change.
  let tonalSquare=0;for(let b=0;b<12;b++)tonalSquare+=(chroma[i*12+b]-floor)**2;
  if(!Number.isFinite(tonalSquare)||tonalSquare<=0)return empty('invalid-chroma-scale');
  const scale=1/Math.sqrt(tonalSquare);for(let b=0;b<12;b++)prefix[next+b]+=(chroma[i*12+b]-floor)*scale;
  prefix[next+12]++;usable++;
 }
 if(usable<count*.5)return empty('insufficient-tonal-evidence');
 const contrast=(index,radius)=>{
  if(index<radius||index+radius>count)return 0;
  const a=(index-radius)*width,b=index*width,c=(index+radius)*width,leftCount=prefix[b+12]-prefix[a+12],rightCount=prefix[c+12]-prefix[b+12];
  if(leftCount<radius*.8||rightCount<radius*.8)return 0;
  let distance=0;for(let k=0;k<12;k++){const delta=(prefix[b+k]-prefix[a+k])/leftCount-(prefix[c+k]-prefix[b+k])/rightCount;distance+=delta*delta;}
  return clamp(distance*.5);
 };
 const radii=[Math.max(2,Math.round(bar/step)),Math.max(3,Math.round(2*bar/step)),Math.max(4,Math.round(4*bar/step))];
 const curves=[new Float32Array(count),new Float32Array(count)];
 for(let i=0;i<count;i++){
  const short=contrast(i,radii[0]),medium=contrast(i,radii[1]),long=contrast(i,radii[2]);
  // Both scales must agree: a one-frame artifact or a passing chord must not
  // masquerade as a long-lived musical transition.
  curves[0][i]=Math.sqrt(short*medium);curves[1][i]=Math.sqrt(medium*long);
 }
 function peaks(curve,minimum,kind,radius){
  const localRadius=Math.max(2,Math.round(bar/step)),backgroundRadius=Math.max(localRadius*4,10),result=[];
  for(let i=radius+localRadius;i<=count-radius-localRadius;i++){
   const strength=curve[i];if(strength<minimum)continue;
   let peak=true;for(let j=i-localRadius;j<=i+localRadius;j++)if(curve[j]>strength+1e-7||(j<i&&Math.abs(curve[j]-strength)<1e-7)){peak=false;break;}
   if(!peak)continue;
   const baseline=percentile(curve.subarray(Math.max(0,i-backgroundRadius),Math.min(count,i+backgroundRadius+1)),.5);
   if(strength<baseline+.035)continue;
   result.push({time:Math.round(i*step*1e6)/1e6,strength:clamp(strength),source:'tonal-novelty',kind,estimated:true});
  }
  return result;
 }
 return {version:STRUCTURE_VERSION,available:true,reason:null,sections:peaks(curves[1],.085,'section',radii[2]),phrases:peaks(curves[0],.10,'phrase',radii[1]),frameCount:count,validFrameCount:usable,windowSeconds:radii.map(radius=>radius*step)};
}
function sectionsFromFeatures(rms,colour,rhythm,duration,tonal=null){
 const fast=rolling(rms,6),slow=rolling(rms,40),norm=percentile(fast,0.94)||1,energy=Array.from(fast,x=>clamp(x/norm)),novelty=new Float32Array(rms.length),r=100;
 const sum=(array,a,b,stride=1,offset=0)=>{let value=0,n=0;for(let j=Math.max(0,a);j<Math.min(rms.length,b);j+=stride){value+=array[j*(array===colour?3:1)+offset];n++;}return value/Math.max(1,n);};
 for(let i=r;i<rms.length-r;i+=5){const before=sum(slow,i-r,i,5),after=sum(slow,i,i+r,5);novelty[i]=Math.abs(after-before)/Math.max(norm*0.12,after+before)*0.7;for(let b=0;b<3;b++){const a=sum(colour,i-r,i,5,b),c=sum(colour,i,i+r,5,b);novelty[i]+=Math.abs(a-c)/Math.max(0.1,a+c)*0.1;}}
 const candidates=[];for(let i=r;i<rms.length-r;i+=5){const v=novelty[i];if(v<0.11)continue;let peak=true;for(let k=Math.max(r,i-75);k<=Math.min(rms.length-r-1,i+75);k+=5)if(novelty[k]>v){peak=false;break;}if(peak)candidates.push({time:i*0.02,strength:clamp(v),source:'energy-spectral-novelty',estimated:true});}
 if(tonal?.available)candidates.push(...tonal.sections);
 const beatLength=rhythm.bpm?60/rhythm.bpm:0.5,barLength=beatLength*rhythm.meter,boundaries=[{time:0,strength:1},{time:duration,strength:1}],minimum=Math.max(3.5,barLength*2);
 // Silence boundaries are musical events and must survive minimum-section spacing.
 for(let i=0;i<rhythm.activityRanges.length;i++){const a=rhythm.activityRanges[i],next=rhythm.activityRanges[i+1];if(i===0&&a.start>0.7)boundaries.push({time:a.start,strength:1});if(next&&next.start-a.end>0.7){boundaries.push({time:a.end,strength:1},{time:next.start,strength:1});}if(i===rhythm.activityRanges.length-1&&duration-a.end>0.7)boundaries.push({time:a.end,strength:1});}
 for(const c of candidates.sort((a,b)=>b.strength-a.strength)){
  let t=c.time;const near=rhythm.meterConfidence>0.12?rhythm.downbeats:rhythm.beats;let delta=Math.min(0.7,beatLength*0.8);for(let j=lowerBound(near,t-delta);j<near.length&&near[j]<=t+delta;j++)if(Math.abs(near[j]-t)<delta){delta=Math.abs(near[j]-t);c.snap=near[j];}if(c.snap!==undefined)t=c.snap;
  if(!rhythm.activityRanges.some(range=>t>=range.start&&t<range.end))continue;
  if(boundaries.every(b=>Math.abs(b.time-t)>=minimum))boundaries.push({time:t,strength:c.strength,source:c.source,detectedTime:c.time});
 }

 boundaries.sort((a,b)=>a.time-b.time);const unique=boundaries.filter((b,i)=>!i||b.time-boundaries[i-1].time>0.15),sections=[];
 for(let i=0;i<unique.length-1;i++){const start=unique[i].time,end=unique[i+1].time,e=sum(fast,Math.floor(start*50),Math.ceil(end*50))/norm,prev=sections.length?sections[sections.length-1].energy:e,active=rhythm.activityRanges.some(a=>a.start<end&&a.end>start+0.04);const label=!active?'Silence':i===0?'Opening':i===unique.length-2?'Finale':e>0.79?'Peak':e>prev+0.13?'Build':e<0.35?'Breakdown':'Groove';sections.push({start,end,energy:clamp(e),label,confidence:clamp(unique[i].strength),estimated:true,boundarySource:unique[i].source||'activity-boundary',detectedBoundaryTime:unique[i].detectedTime??start});}
 return {sections,energy,transitions:candidates,tonal};
}
function phrasesAndImpacts(rhythm,structure,onsets,duration){
 const phrases=[],impacts=[],beatLength=rhythm.bpm?60/rhythm.bpm:0.5,meter=rhythm.meter,energy=structure.energy;
 const mean=(a,b)=>{let s=0,n=0;for(let i=Math.max(0,Math.floor(a*50));i<Math.min(energy.length,Math.ceil(b*50));i++){s+=energy[i];n++;}return s/Math.max(1,n);};
 for(const section of structure.sections){
  const anchors=[{time:section.start,source:section.boundarySource||'section-boundary',confidence:section.confidence},{time:section.end,source:'section-end',confidence:section.confidence}],minimum=Math.max(1,beatLength*meter*2);
  // Give measured changes priority, including three-/five-bar phrases. The
  // four-bar grid remains a low-confidence scaffold only in unsupported gaps.
  if(section.label!=='Silence')for(const candidate of (structure.tonal?.phrases||[]).slice().sort((a,b)=>b.strength-a.strength||a.time-b.time)){
   let time=candidate.time;
   if(rhythm.downbeatConfidence>=.35){const near=lowerBound(rhythm.downbeats,time),choices=[rhythm.downbeats[near-1],rhythm.downbeats[near]].filter(Number.isFinite).sort((a,b)=>Math.abs(a-time)-Math.abs(b-time));if(choices.length&&Math.abs(choices[0]-time)<=Math.min(.35,beatLength*.5))time=choices[0];}
   if(time<=section.start||time>=section.end||anchors.some(anchor=>Math.abs(anchor.time-time)<minimum-1e-6))continue;
   anchors.push({time,source:candidate.source,confidence:clamp(.35+candidate.strength*.6)});
  }
  anchors.sort((a,b)=>a.time-b.time);const boundaries=[];
  for(let a=0;a<anchors.length-1;a++){
   const left=anchors[a],right=anchors[a+1];boundaries.push(left);let bars=0,previous=left.time;
   if(section.label==='Silence')continue;
   for(let j=lowerBound(rhythm.downbeats,left.time+beatLength*.5);j<rhythm.downbeats.length&&rhythm.downbeats[j]<right.time-beatLength;j++){
    if(++bars<4)continue;const time=rhythm.downbeats[j];if(time-previous>=minimum&&right.time-time>=minimum){boundaries.push({time,source:'meter-scaffold',confidence:clamp(rhythm.beatConfidence*.35+rhythm.meterConfidence*.15)});previous=time;bars=0;}
   }
  }
  boundaries.push(anchors[anchors.length-1]);const points=boundaries.map(boundary=>boundary.time);
  for(let i=0;i<points.length-1;i++){const start=points[i],end=points[i+1],e=mean(start,end),mid=(start+end)/2,change=mean(mid,end)-mean(start,mid),kind=section.label==='Silence'?'silence':e<0.3?'quiet':change>0.16?'build':change< -0.16?'release':e>0.78?'peak':'groove';let accentTime=start,best=0;for(let j=lowerBound(onsets,start,x=>x.time);j<onsets.length&&onsets[j].time<Math.min(end,start+beatLength*meter);j++){const o=onsets[j],score=o.strength*(o.band==='bass'?1:0.7);if(score>best){best=score;accentTime=o.time;}}
   phrases.push({start,end,energy:e,kind,recurrenceGroup:section.recurrenceGroup,repetitionIndex:section.repetitionIndex,similarity:section.similarity,confidence:clamp(boundaries[i].confidence??0),estimated:true,boundarySource:boundaries[i].source,accentTime});
  }
 }
 const norm=percentile(onsets.map(o=>o.strength),0.8)||1;
 for(const o of onsets){if(o.strength<Math.max(0.58,norm*0.8)||o.band==='high')continue;const pre=mean(Math.max(0,o.time-0.7),o.time-0.08),post=mean(o.time,Math.min(duration,o.time+0.6)),b=lowerBound(rhythm.downbeats,o.time-0.07),downbeat=b<rhythm.downbeats.length&&Math.abs(rhythm.downbeats[b]-o.time)<=0.07;
  const arrival=post-pre>0.22&&post>0.4&&post>pre*1.7&&o.strength>0.75;if(arrival||(downbeat&&o.band==='bass'))impacts.push({time:o.time,strength:clamp(o.strength*0.65+Math.max(0,post-pre)*0.7),kind:arrival?'arrival':'accent'});
 }
 for(let i=1;i<rhythm.activityRanges.length;i++){const r=rhythm.activityRanges[i],prev=rhythm.activityRanges[i-1];if(r.start-prev.end>0.7){let time=r.start;const onset=onsets[lowerBound(onsets,r.start,x=>x.time)];if(onset&&onset.time-r.start<0.2)time=onset.time;impacts.push({time,strength:clamp(0.6+mean(time,time+0.5)*0.4),kind:'return'});}}
 impacts.sort((a,b)=>a.time-b.time);const merged=[];for(const i of impacts){const last=merged[merged.length-1];if(last&&i.time-last.time<Math.max(0.15,beatLength*0.4)){if(i.strength>last.strength)merged[merged.length-1]=i;}else merged.push(i);}
 return {phrases,impacts:merged};
}
// Bounded fingerprints describe repetition without claiming verse/chorus semantics.
function recurringSections(sections,data){
 const representatives=[],counts=new Map(),chroma=data.chroma,step=data.chromaStep||.2;
 const fingerprint=section=>{const values=[];for(let bin=0;bin<8;bin++){const a=section.start+(section.end-section.start)*bin/8,b=section.start+(section.end-section.start)*(bin+1)/8;let e=0,n=0,colour=[0,0,0],tone=new Float64Array(12);for(let j=Math.floor(a*50);j<Math.min(data.rms.length,Math.ceil(b*50));j+=5){e+=data.rms[j];for(let k=0;k<3;k++)colour[k]+=data.colour[j*3+k];n++;}const cs=colour.reduce((s,x)=>s+x,0)||1;values.push(e/Math.max(1,n),...colour.map(x=>x/cs));if(chroma){for(let j=Math.floor(a/step);j<Math.min(chroma.length/12,Math.ceil(b/step));j++)for(let k=0;k<12;k++)tone[k]+=chroma[j*12+k];const total=tone.reduce((s,x)=>s+x,0)||1;values.push(...Array.from(tone,x=>x/total));}}
  const norm=Math.hypot(...values)||1;return values.map(x=>x/norm);};
 for(let i=0;i<sections.length;i++){const section=sections[i],vector=fingerprint(section);let best=null,similarity=0;for(const rep of representatives){const ratio=(section.end-section.start)/(rep.end-rep.start);if(section.label==='Silence'||rep.label==='Silence'||ratio<.65||ratio>1.55||Math.abs(section.energy-rep.energy)>.28)continue;let score=0;for(let k=0;k<vector.length;k++)score+=vector[k]*rep.vector[k];if(score>similarity){similarity=score;best=rep;}}
  // Adjacent feature windows can be similar by continuity alone. Reuse requires a
  // separated passage and strong spectral/tonal evidence, not loudness alone.
  const match=best&&similarity>=.985&&section.start-best.end>=1;
  section.recurrenceGroup=match?best.group:'section-'+i;section.similarity=match?Math.round(similarity*1000)/1000:0;section.repetitionIndex=counts.get(section.recurrenceGroup)||0;counts.set(section.recurrenceGroup,section.repetitionIndex+1);
  if(!match){representatives.push({...section,group:section.recurrenceGroup,vector});if(representatives.length>512)representatives.shift();}
 }
 return sections;
}
function grooveFromOnsets(rhythm,onsets){
 const ratios=[];for(let i=0;i<rhythm.beats.length-1;i++){const a=rhythm.beats[i],b=rhythm.beats[i+1],span=b-a;if(span<.25||span>1.2)continue;let best=null,weight=0;for(let j=lowerBound(onsets,a+span*.34,o=>o.time);j<onsets.length&&onsets[j].time<=a+span*.76;j++){const o=onsets[j],w=o.strength*(o.band==='high'?1:.7);if(w>weight){weight=w;best=(o.time-a)/span;}}if(best!==null&&weight>.25)ratios.push(best);}
 const ratio=percentile(ratios,.5)||.5,spread=percentile(ratios.map(x=>Math.abs(x-ratio)),.75),confidence=clamp(ratios.length/24)*clamp(1-spread/.13),swing=ratio>.58&&ratio<.73&&confidence>.45;
 return {feel:swing?'swing':Math.abs(ratio-.5)<.05&&confidence>.45?'straight':'free',subdivisionRatio:Math.round(ratio*1000)/1000,confidence,observations:ratios.length};
}
const ESTIMATED_PERCUSSION_SOURCE='mix-feature-estimate',ESTIMATED_PERCUSSION_SALIENCE_CAP=.41;
function nearestAttackStrength(attacks,time){
 let best=0;for(let i=lowerBound(attacks,time-.035,x=>x.time);i<attacks.length&&attacks[i].time<=time+.035;i++)best=Math.max(best,clamp(attacks[i].strength)*(1-Math.abs(attacks[i].time-time)/.05));return best;
}
function normalizedFlux(values,time,scale){
 if(!values||!values.length||!scale)return 0;const at=Math.max(0,Math.min(values.length-1,Math.round(time/.02)));let peak=0;for(let index=Math.max(0,at-1);index<=Math.min(values.length-1,at+1);index++)peak=Math.max(peak,values[index]||0);return clamp(peak/scale);
}
/*
 * Opt-in, low-trust percussion evidence from the original-mix feature pass.
 * This is not a drum model and never claims separated instruments. A candidate
 * needs an already localized spectral-flux peak plus an independent 5 ms PCM
 * attack; its class/confidence are deliberately capped before semantic ranking.
 */
function estimatePercussionEvidence(data,context={}){
 if(context.enabled!==true)return null;
 return measure(context.telemetry,'drum_analysis',()=>{
 const onsets=Array.isArray(context.onsets)?context.onsets:[],attacks=Array.isArray(context.attacks)?context.attacks:[],ranges=Array.isArray(context.activityRanges)?context.activityRanges:[],duration=Number(data?.duration);
 const empty=()=>({schemaVersion:1,source:ESTIMATED_PERCUSSION_SOURCE,method:'Conservative original-mix spectral-flux and PCM-attack agreement; not a dedicated percussion model.',inputStem:'mixture',inputStemSeparated:false,sourceSeparated:false,estimated:true,salienceCap:ESTIMATED_PERCUSSION_SALIENCE_CAP,events:[],limitations:['Estimated from original-mix features; no isolated drum stem or classed drum model was used.','Low-trust estimates are capped below primary salience until independent evidence is supplied.']});
 if(!Number.isFinite(duration)||duration<=0||!attacks.length)return empty();
 const scale={bass:percentile(data.bass||[],.94)||0,mid:percentile(data.mid||[],.94)||0,high:percentile(data.high||[],.94)||0},candidates=[],rank={kick:0,snare:1,hat:2};
 for(const onset of onsets){
  if(!onset||!Number.isFinite(onset.time)||onset.time<0||onset.time>=duration||!['bass','mid','high'].includes(onset.band)||!Number.isFinite(onset.strength))continue;
  if(ranges.length&&!insideRanges(onset.time,ranges))continue;
  const low=normalizedFlux(data.bass,onset.time,scale.bass),mid=normalizedFlux(data.mid,onset.time,scale.mid),high=normalizedFlux(data.high,onset.time,scale.high),attack=nearestAttackStrength(attacks,onset.time),strength=clamp(onset.strength);
  let kind=null,dominance=0,limit=0;
  if(onset.band==='bass'&&strength>=.74&&attack>=.14&&low>=.82&&low>=mid*.86&&low>=high*.86){kind='kick';dominance=low-Math.max(mid,high)*.28;limit=.58;}
  else if(onset.band==='mid'&&strength>=.76&&attack>=.16&&mid>=.84&&mid>=low*.88&&mid>=high*.80){kind='snare';dominance=mid-Math.max(low,high)*.24;limit=.53;}
  else if(onset.band==='high'&&strength>=.80&&attack>=.12&&high>=.88&&high>=mid*.90&&high>=low*1.04){kind='hat';dominance=high-Math.max(mid,low)*.20;limit=.48;}
  if(!kind)continue;
  const evidence=clamp(.45*strength+.35*clamp(dominance)+.20*attack),confidence=Math.min(limit,clamp(.20+.46*evidence));
  if(confidence<.38)continue;
  candidates.push({time:onset.time,kind,confidence:Math.round(confidence*1e6)/1e6,strength:Math.round(evidence*1e6)/1e6,estimated:true,source:ESTIMATED_PERCUSSION_SOURCE,inputStem:'mixture',inputStemSeparated:false,sourceSeparated:false,salienceCap:ESTIMATED_PERCUSSION_SALIENCE_CAP});
 }
 candidates.sort((a,b)=>a.time-b.time||(rank[a.kind]-rank[b.kind])||b.confidence-a.confidence);
 const spacing={kick:.12,snare:.12,hat:.06},events=[];
 for(const candidate of candidates){
  let previous=-1;for(let i=events.length-1;i>=0;i--)if(events[i].kind===candidate.kind){previous=i;break;}
  if(previous>=0&&candidate.time-events[previous].time<spacing[candidate.kind]){if(candidate.confidence>events[previous].confidence)events[previous]=candidate;continue;}
  events.push(candidate);
 }
 events.sort((a,b)=>a.time-b.time||(rank[a.kind]-rank[b.kind]));
 const result=empty();result.events=events;return result;
 });
}
function summarize(data,options={}){
 const sensitivity=clamp(Number(options.sensitivity??0.82)),attacks=data.fineRms?pcmAttacks(data.fineRms):[],rhythm=trackBeats(data.beat,data.down,data.rms,{...options,duration:data.duration,fineRms:data.fineRms,attacks});
 const onsets=[...pickOnsets(data.bass,'bass',sensitivity),...pickOnsets(data.mid,'mid',sensitivity),...pickOnsets(data.high,'high',sensitivity)].map(o=>({...o,time:alignToAttack(o.time,attacks)})).filter(o=>o.time<data.duration&&insideRanges(o.time,rhythm.activityRanges)).sort((a,b)=>a.time-b.time);
 // Re-alignment can bring adjacent spectral peaks onto the same physical attack.
 for(let i=onsets.length-1;i>0;i--)if(onsets.slice(Math.max(0,i-4),i).some(o=>o.band===onsets[i].band&&Math.abs(o.time-onsets[i].time)<0.025))onsets.splice(i,1);
 const {structure,landmarks}=measure(options.telemetry,'structural_analysis',()=>{const tonal=tonalStructure(data,rhythm),structure=sectionsFromFeatures(data.rms,data.colour,rhythm,data.duration,tonal);recurringSections(structure.sections,data);const landmarks=phrasesAndImpacts(rhythm,structure,onsets,data.duration);return {structure,landmarks};}),waveform=[],bins=Math.min(1800,data.rms.length),max=percentile(data.rms,0.98)||1;
 for(let i=0;i<bins;i++){let a=Math.floor(i*data.rms.length/bins),b=Math.ceil((i+1)*data.rms.length/bins),v=0;for(let j=a;j<b;j++)v=Math.max(v,data.rms[j]);waveform.push(clamp(v/max));}
 const warnings=[];if(rhythm.downbeatConfidence<.35&&rhythm.beats.length)warnings.push('The first beat of the bar is uncertain. Mark a downbeat to align recurring accents.');if(!rhythm.bpm)warnings.push('No reliable musical pulse was detected. Choose audible music or enter a tempo.');else if(rhythm.beatConfidence<0.48)warnings.push('The beat estimate has low confidence. Preview the rhythm and adjust BPM if needed.');if(rhythm.meterConfidence<0.18&&rhythm.beats.length)warnings.push('Bar accents are uncertain; phrase boundaries use measured energy and pulse evidence.');
 const shifts=rhythm.beatDetails.map(b=>Math.abs(b.alignmentOffsetMs||0)/1000),manual=Number(options.bpmOverride)>=40&&Number(options.bpmOverride)<=240;
 const result={duration:data.duration,...rhythm,onsets,sections:structure.sections,energy:structure.energy,...landmarks,waveform,energyStep:0.02,recommendedBeatLength:rhythm.bpm?60/rhythm.bpm:0,recommendedStepTime:20,analysisVersion:3,groove:grooveFromOnsets(rhythm,onsets),structure:{version:STRUCTURE_VERSION,method:'Multi-scale tonal novelty with energy, spectral change and measured phrase boundaries',tonalEvidence:{available:structure.tonal.available,reason:structure.tonal.reason,frameCount:structure.tonal.frameCount,validFrameCount:structure.tonal.validFrameCount||0,windowSeconds:structure.tonal.windowSeconds||[],sectionCandidates:structure.tonal.sections.length,phraseCandidates:structure.tonal.phrases.length},recurringGroups:[...new Set(structure.sections.filter(s=>s.repetitionIndex>0).map(s=>s.recurrenceGroup))],semanticLabels:false},timing:{neuralFrameMs:20,pcmEnvelopeMs:data.fineRms?5:null,decoder:options.decoder==='transformer'?'Transformer direct peak decoding':'Adaptive CRNN lattice',alignment:manual?'Exact manual-tempo grid with evidence-based phase':'Neural pulse with local tempo and nearby measured PCM attacks',manualTempo:manual,attackCount:attacks.length,refinedBeatCount:manual?0:shifts.filter(s=>s>0.001).length,appliedGlobalOffsetMs:0},warnings};
 const percussionAnalysis=estimatePercussionEvidence(data,{enabled:options.enableEstimatedPercussionEvidence===true,telemetry:options.telemetry,onsets,attacks,activityRanges:rhythm.activityRanges});
 if(percussionAnalysis)result.percussionAnalysis=percussionAnalysis;
 return result;
}
scope.LightForgeDSP={FFT,Spectrum,FeatureExtractor,rolling,percentile,activityFromEnvelope,pcmAttacks,alignToAttack,trackBeats,tonalStructure,sectionsFromFeatures,phrasesAndImpacts,recurringSections,grooveFromOnsets,estimatePercussionEvidence,summarize};
})(typeof self!=='undefined'?self:globalThis);
