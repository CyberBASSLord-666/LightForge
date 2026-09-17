/* Low-register note estimates from local PCM. Original implementation, MIT.
 * This is harmonic evidence in a mixture, not a separated bass instrument stem.
 * A tuned sustained 808, low piano, low voice or bass instrument may share it.
 */
(function(scope){'use strict';
const RATE=22050,DECIMATE=4,SR=RATE/DECIMATE,FFT_SIZE=2048,HOP=441,STEP=.02;
const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,v));
const measure=(telemetry,name,fn)=>telemetry&&typeof telemetry.measure==='function'?telemetry.measure('performance.'+name,fn):fn();
function quantile(a,p){if(!a.length)return 0;const b=Array.from(a).sort((x,y)=>x-y);return b[Math.min(b.length-1,Math.floor((b.length-1)*p))];}
function fir(length,cutoff,sampleRate){const out=new Float64Array(length),mid=(length-1)/2;let sum=0;for(let i=0;i<length;i++){const t=i-mid,x=t===0?2*cutoff/sampleRate:Math.sin(2*Math.PI*cutoff/sampleRate*t)/(Math.PI*t),w=.42-.5*Math.cos(2*Math.PI*i/(length-1))+.08*Math.cos(4*Math.PI*i/(length-1));sum+=out[i]=x*w;}for(let i=0;i<length;i++)out[i]/=sum;return out;}
function abort(signal){if(signal?.aborted)throw new DOMException('Analysis cancelled','AbortError');}
class Extractor {
 constructor(telemetry){this.telemetry=telemetry;if(!scope.LightForgeDSP?.FFT)throw new Error('Bass analysis requires LightForgeDSP.FFT.');this.fft=new scope.LightForgeDSP.FFT(FFT_SIZE);this.re=new Float64Array(FFT_SIZE);this.im=new Float64Array(FFT_SIZE);this.mag=new Float64Array(FFT_SIZE/2);this.window=Float64Array.from({length:FFT_SIZE},(_,i)=>.5-.5*Math.cos(2*Math.PI*i/(FFT_SIZE-1)));this.antialias=fir(65,1050,RATE);this.lowpass=fir(129,245,SR);this.highpass=fir(129,27,SR);}
 decimate(samples,firstSample){
  // Use absolute decimation coordinates so arbitrary read boundaries produce
  // identical samples and frame phases. All filters are centred, with real halo.
  const base=Math.ceil((firstSample+32)/DECIMATE),count=Math.max(0,Math.floor((firstSample+samples.length-33)/DECIMATE)-base+1),pcm=new Float32Array(count),a=this.antialias;
  measure(count>0?this.telemetry:null,'resample_normalize',()=>{for(let i=0;i<count;i++){const at=(base+i)*DECIMATE-firstSample;let v=0;for(let k=0;k<a.length;k++)v+=samples[at+k-32]*a[k];pcm[i]=v;}});
  return {pcm,base};
 }
 chunk(samples,firstSample,firstFrame,frames){
  const {pcm,base}=this.decimate(samples,firstSample),count=pcm.length,low=measure(count>128?this.telemetry:null,'feature_generation',()=>{const low=new Float32Array(count);
  for(let i=64;i<count-64;i++){let v=0;for(let k=0;k<129;k++)v+=pcm[i+k-64]*(this.lowpass[k]-this.highpass[k]);low[i]=v;}return low;});
  const result=[];
  for(let f=0;f<frames;f++){
   const energy=measure(this.telemetry,'feature_generation',()=>{
   const center=(firstFrame+f)*HOP/DECIMATE-base,start=Math.round(center-FFT_SIZE/2),{re,im,mag}=this;im.fill(0);
   for(let i=0;i<FFT_SIZE;i++)re[i]=(pcm[start+i]||0)*this.window[i];this.fft.run(re,im);
   for(let i=0;i<mag.length;i++)mag[i]=Math.hypot(re[i],im[i]);
   let energy=0;const from=Math.round(center-SR*.02),to=Math.round(center+SR*.02);for(let i=from;i<to;i++)energy+=(low[i]||0)**2;energy=Math.sqrt(energy/Math.max(1,to-from));
   return energy;});
   result.push({...this.pitch(this.mag),energy});
  }
  return result;
 }
 pitch(mag){
  const bin=SR/FFT_SIZE,min=Math.ceil(30/bin),max=Math.floor(220/bin),upper=Math.floor(880/bin);let total=0,peak=0;
  for(let i=min;i<=upper;i++){total+=mag[i]*mag[i];peak=Math.max(peak,mag[i]);}
  if(peak<.002||total<.0001)return {frequency:0,confidence:0,level:0,harmonics:0};
  const candidates=[];
  for(let k=min;k<=max;k++){
   if(mag[k]<=mag[k-1]||mag[k]<mag[k+1]||mag[k]<peak*.075)continue;
   const left=Math.log(mag[k-1]+1e-12),middle=Math.log(mag[k]+1e-12),right=Math.log(mag[k+1]+1e-12),delta=clamp(.5*(left-right)/(left-2*middle+right||1),-.5,.5),frequency=(k+delta)*bin;
   let matched=0,score=0,harmonics=0;
   for(let h=1;h<=5&&frequency*h<=880;h++){
    const center=Math.round(frequency*h/bin);let local=0,power=0;
    for(let j=Math.max(min,center-1);j<=Math.min(upper,center+1);j++){local=Math.max(local,mag[j]);power+=mag[j]*mag[j];}
    score+=local/Math.sqrt(h);matched+=power;if(local>mag[k]*.12)harmonics++;
   }
   const concentration=clamp(matched/total),neighbors=[];for(let j=Math.max(min,k-9);j<=Math.min(upper,k+9);j++)if(Math.abs(j-k)>2)neighbors.push(mag[j]);
   const prominence=mag[k]/Math.max(.0001,quantile(neighbors,.5)),tonal=clamp((prominence-2)/9),confidence=clamp(.7*concentration+.3*tonal);
   if(concentration<.32||prominence<3.2||confidence<.5)continue;
   // Harmonics can be louder than the fundamental. Reward explained harmonic
   // power while requiring actual fundamental energy; no invented subharmonics.
   candidates.push({frequency,confidence,level:Math.sqrt(matched)/(FFT_SIZE*.25),harmonics,score:score*(.55+.45*concentration)});
  }
  candidates.sort((a,b)=>b.score-a.score);const best=candidates[0];if(!best)return {frequency:0,confidence:0,level:0,harmonics:0};
  // Prefer an evidenced lower fundamental when it explains the same harmonics.
  for(const c of candidates.slice(1)){const ratio=best.frequency/c.frequency;if(ratio>1.8&&ratio<4.2&&Math.abs(ratio-Math.round(ratio))<.08&&c.score>best.score*.78&&c.confidence>=best.confidence*.85)return c;}
  return best;
 }
}
function summarize(frames,duration){
 const count=frames.length,at=Array.isArray(frames)?(i,key)=>frames[i][key]:(i,key)=>frames[key][i],energy=frames.energy||Float32Array.from(frames,f=>f.energy),norm=quantile(energy,.95)||1,floor=Math.max(.00015,norm*.025),pitch=new Float32Array(count);
 for(let i=0;i<count;i++){const f=at(i,'frequency');pitch[i]=f>0&&energy[i]>floor?69+12*Math.log2(f/440):0;}
 // One-frame misassignments are not notes. Keep pitch transitions in place;
 // unlike beat quantization, this does not pull a bass note onto a drum hit.
 const smooth=pitch.map((x,i)=>{if(!x)return 0;const near=pitch.slice(Math.max(0,i-1),Math.min(count,i+2)).filter(v=>v>0&&Math.abs(v-x)<1.5);return near.length?quantile(near,.5):x;});
 const runs=[];let run=null;
 for(let i=0;i<count;i++){
  const p=smooth[i];if(p&&run&&Math.abs(p-run.reference)<=.9&&i-run.last<=3){run.last=i;run.indices.push(i);run.reference=quantile(run.indices.slice(-9).map(j=>smooth[j]),.5);}
  else if(p){if(run)runs.push(run);run={first:i,last:i,reference:p,indices:[i]};}
  else if(run&&i-run.last>2){runs.push(run);run=null;}
 }if(run)runs.push(run);
 const notes=[];let rejectedShort=0,rejectedTransient=0;
 for(const r of runs){
  const values=r.indices.map(i=>smooth[i]),median=quantile(values,.5),spread=quantile(values.map(x=>Math.abs(x-median)),.9),harmonics=quantile(r.indices.map(i=>at(i,'harmonics')),.5);let peak=0,steady=0;
  for(const i of r.indices)peak=Math.max(peak,energy[i]);for(const i of r.indices)if(energy[i]>=peak*.5)steady+=STEP;
  if((r.last-r.first+1)*STEP<.14||r.indices.length<6){rejectedShort++;continue;}
  if(spread>.65||steady<(harmonics<2?.16:.1)){rejectedTransient++;continue;}
  let start=r.first*STEP,end=Math.min(duration,(r.last+1)*STEP);const threshold=Math.max(floor,peak*.12);
  // Do not allow the pitch window to extend a note into measured low-band silence.
  while(end>start+.14&&energy[Math.min(count-1,Math.round(end/STEP)-1)]<threshold)end-=STEP;
  if(end-start<.14){rejectedShort++;continue;}
  const average=r.indices.reduce((s,i)=>s+at(i,'confidence'),0)/r.indices.length,confidence=clamp(average*.8+.2*clamp(1-spread/.8));
  if(confidence<.55)continue;
  notes.push({start:Math.max(0,Math.round(start*1000)/1000),end:Math.min(duration,Math.round(end*1000)/1000),time:Math.max(0,Math.round(start*1000)/1000),midi:Math.round(median*100)/100,frequency:Math.round(440*2**((median-69)/12)*100)/100,confidence:Math.round(confidence*1000)/1000,strength:Math.round(clamp(peak/norm)*1000)/1000});
 }
 // Resolve windows shared by neighbouring notes without delaying an accepted
 // entrance. A continuous change is a new note, not an overlapping bass voice.
 for(let i=0;i<notes.length-1;i++)if(notes[i].end>notes[i+1].start)notes[i].end=notes[i+1].start;
 const accepted=notes.filter(n=>n.end-n.start>=.12),phrases=[];
 for(const n of accepted){const p=phrases[phrases.length-1];if(p&&n.start-p.end<=.65&&n.end-p.start<=16){p.end=n.end;p.confidence=(p.confidence*p.notes+n.confidence)/(p.notes+1);p.notes++;if(n.strength>p.strength){p.strength=n.strength;p.accentTime=n.start;}}else phrases.push({start:n.start,end:n.end,confidence:n.confidence,strength:n.strength,accentTime:n.start,notes:1});}
 for(const p of phrases)p.confidence=Math.round(p.confidence*1000)/1000;
 const envelope=new Float32Array(count);for(const n of accepted)for(let i=Math.max(0,Math.floor(n.start/STEP));i<Math.min(count,Math.ceil(n.end/STEP));i++)envelope[i]=clamp(energy[i]/norm)*n.confidence;
 return {method:'Harmonic low-register tracking',source:'mixture-estimate',confidence:accepted.length?Math.round(accepted.reduce((s,n)=>s+n.confidence,0)/accepted.length*1000)/1000:0,notes:accepted,phrases,envelope:Array.from(envelope,x=>Math.round(x*1000)/1000),envelopeStep:STEP,diagnostics:{version:1,sampleRate:RATE,pitchWindowMs:Math.round(FFT_SIZE/SR*1000),frameMs:20,frequencyRangeHz:[30,220],notes:accepted.length,rejectedShort,rejectedTransient,sourceSeparated:false,pitchIsEstimated:true,confidenceIsProbability:false,limitations:'Low-register harmonic estimates can include piano, low voice or tuned sustained drums. Brief or sweeping kick transients are suppressed; overlapping instruments, glides and quiet bass can be missed. Kicks overlapping a low note can still move its estimated boundary; the 5 ms boundary grid is not an accuracy guarantee.'}};
}
function harmonicBoundary(pcm,base,note,kind,duration,telemetry){
 const window=256,weights=Float64Array.from({length:window},(_,i)=>.5-.5*Math.cos(2*Math.PI*i/(window-1))),mid=(note.start+note.end)/2,anchor=kind==='start'?Math.min(note.start+.1,mid):Math.max(note.end-.1,mid),edge=kind==='start'?note.start:note.end,begin=Math.max(0,kind==='start'?edge-.55:anchor-.04),finish=Math.min(duration,kind==='start'?anchor+.04:edge+.4),step=.005,amps=[];
 const coefficients=Array.from({length:4},(_,i)=>2*Math.cos(2*Math.PI*note.frequency*(i+1)/SR));
 measure(telemetry,'feature_generation',()=>{for(let t=begin;t<=finish+step/2;t+=step){const first=Math.round(t*SR-base-window/2),v=[];for(const coefficient of coefficients){let x1=0,x2=0;for(let j=0;j<window;j++){const x=(pcm[first+j]||0)*weights[j]+coefficient*x1-x2;x2=x1;x1=x;}v.push(Math.sqrt(Math.max(0,x1*x1+x2*x2-coefficient*x1*x2)));}amps.push(v);}});
 if(!amps.length)return edge;
 const ai=Math.max(0,Math.min(amps.length-1,Math.round((anchor-begin)/step))),reference=coefficients.map((_,h)=>quantile(amps.slice(Math.max(0,ai-3),Math.min(amps.length,ai+4)).map(a=>a[h]),.5)),maximum=Math.max(...reference),selected=[];
 for(let h=1;h<4;h++)if(reference[h]>maximum*.085)selected.push(h);if(selected.length<2){selected.length=0;selected.push(0);}
 if(maximum<.005)return edge;
 const score=amps.map(a=>quantile(selected.map(h=>a[h]/Math.max(reference[h],.00001)),.5));
 let at=ai;
 if(kind==='start'){
  // Walk the actual note's harmonic plateau backward, not the loudest nearby
  // low-frequency attack. Sustained evidence may survive a louder kick.
  while(at>0){if(score.slice(Math.max(0,at-4),at).every(x=>x<.5))break;at--;}
 }else while(at<score.length-1){if(score.slice(at+1,Math.min(score.length,at+5)).every(x=>x<.5))break;at++;}
 return clamp(Math.round((begin+at*step)*1000)/1000,0,duration);
}
async function refineBoundaries(reader,config,result,extractor,options){
 if(!result.notes.length)return;
 // One second of real neighbouring PCM on either side keeps boundary evidence
 // continuous across ten-second reads. Audio is never retained track-wide.
 const events=result.notes.flatMap(note=>[{note,kind:'start',time:note.start},{note,kind:'end',time:note.end}]).sort((a,b)=>a.time-b.time),chunkSeconds=10,groups=new Map();
 for(const event of events){const key=Math.floor(event.time/chunkSeconds);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(event);}
 let done=0;for(const [key,group]of groups){abort(options.signal);const start=Math.floor((key*chunkSeconds-1)*RATE),count=(chunkSeconds+2)*RATE+1,samples=await reader.mono22050(start,count,config);abort(options.signal);const {pcm,base}=extractor.decimate(samples,start);
  for(const event of group){const value=harmonicBoundary(pcm,base,event.note,event.kind,reader.duration,options.telemetry);event.note[event.kind==='start'?'refinedStart':'refinedEnd']=value;}
  options.onProgress?.(.7+.2*(++done)/groups.size);
 }
 for(const note of result.notes){note.start=note.refinedStart??note.start;note.end=note.refinedEnd??note.end;note.time=note.start;delete note.refinedStart;delete note.refinedEnd;}
 result.notes.sort((a,b)=>a.start-b.start);for(let i=0;i<result.notes.length-1;i++)if(result.notes[i].end>result.notes[i+1].start)result.notes[i].end=result.notes[i+1].start;
 result.notes=result.notes.filter(n=>n.end-n.start>=.12);
}
function articulationBoundary(pcm,base,note,time,telemetry){
 // A short low-band dip only nominates a location. The note's own harmonics
 // must fall and restart rapidly; a louder nearby kick is not an articulation.
 const step=.005,window=256,begin=time-.22,weights=Float64Array.from({length:window},(_,i)=>.5-.5*Math.cos(2*Math.PI*i/(window-1))),coefficients=Array.from({length:4},(_,i)=>2*Math.cos(2*Math.PI*note.frequency*(i+1)/SR)),amps=[];
 measure(telemetry,'feature_generation',()=>{for(let k=0;k<=72;k++){const first=Math.round((begin+k*step)*SR-base-window/2),value=[];for(const coefficient of coefficients){let x1=0,x2=0;for(let j=0;j<window;j++){const x=(pcm[first+j]||0)*weights[j]+coefficient*x1-x2;x2=x1;x1=x;}value.push(Math.sqrt(Math.max(0,x1*x1+x2*x2-coefficient*x1*x2)));}amps.push(value);}});
 const reference=coefficients.map((_,h)=>quantile(amps.slice(49,63).map(a=>a[h]),.8)),maximum=Math.max(...reference),selected=[];
 if(maximum<.005)return null;
 for(let h=1;h<4;h++)if(reference[h]>maximum*.085)selected.push(h);if(selected.length<2){selected.length=0;selected.push(0);}
 const score=amps.map(a=>quantile(selected.map(h=>a[h]/Math.max(reference[h],.00001)),.5));
 for(let low=35;low<=47;low++){
  if(score[low]>.12||score[low-1]>.2||score[low+1]<=.12)continue;
  // Smooth tremolo has a gradual recovery. Require the deep trough to reach
  // the new harmonic plateau within 30 ms, independently of the beat grid.
  let high=low+1;while(high<=low+6&&score[high]<.8)high++;if(high>low+6)continue;
  const before=quantile(score.slice(low-30,low-12),.8);let trough=low;for(let i=low-8;i<low;i++)if(score[i]<score[trough])trough=i;
  if(before<.06||score[trough]>.04||score[trough]>.45*before||Math.min(score[trough-1],score[trough+1])>.05)continue;
  let onset=low+1;while(onset<high&&score[onset]<.5)onset++;
  let end=trough;while(end>low-30&&score[end]<before*.5)end--;
  const startTime=Math.round((begin+onset*step)*1000)/1000,endTime=Math.round((begin+end*step)*1000)/1000;
  if(endTime-note.start<.14||note.end-startTime<.14||endTime>startTime)continue;
  return {start:startTime,end:endTime};
 }
 return null;
}
async function splitArticulations(reader,config,result,extractor,frames,options){
 const groups=new Map(),energy=frames.energy;
 for(const note of result.notes){let last=-Infinity;for(let i=Math.max(10,Math.ceil((note.start+.14)/STEP));i<Math.min(energy.length-4,Math.floor((note.end-.14)/STEP));i++){
  let after=0,before=0,low=Infinity;for(let j=i;j<i+4;j++)after=Math.max(after,energy[j]);for(let j=i-10;j<i-3;j++)before=Math.max(before,energy[j]);for(let j=i-3;j<i;j++)low=Math.min(low,energy[j]);
  if(after<.00015||low>Math.min(before,after)*.45||energy[i]-energy[i-1]<after*.18||i-last<4)continue;
  last=i;const time=i*STEP,key=Math.floor(time/10);if(!groups.has(key))groups.set(key,[]);groups.get(key).push({note,time});
 }}
 const boundaries=new Map();let done=0;for(const [key,events]of groups){abort(options.signal);const first=Math.floor((key*10-1)*RATE),samples=await reader.mono22050(first,12*RATE+1,config);abort(options.signal);const {pcm,base}=extractor.decimate(samples,first);
  for(const {note,time}of events){abort(options.signal);const boundary=articulationBoundary(pcm,base,note,time,options.telemetry);if(!boundary)continue;if(!boundaries.has(note))boundaries.set(note,[]);boundaries.get(note).push(boundary);}
  options.onProgress?.(.9+.1*(++done)/groups.size);
 }
 const notes=[],norm=boundaries.size?(quantile(energy,.95)||1):1;let added=0;for(const note of result.notes){let start=note.start;const children=[];for(const boundary of (boundaries.get(note)||[]).sort((a,b)=>a.start-b.start)){
  if(boundary.end-start<.14||note.end-boundary.start<.14)continue;
  children.push({...note,start,time:start,end:boundary.end});start=boundary.start;added++;
 }if(!children.length){notes.push(note);continue;}children.push({...note,start,time:start});for(const child of children){let peak=0;for(let i=Math.max(0,Math.ceil(child.start/STEP));i<Math.min(energy.length,Math.ceil(child.end/STEP));i++)peak=Math.max(peak,energy[i]);child.strength=Math.round(clamp(peak/norm)*1000)/1000;notes.push(child);}}
 result.notes=notes;result.diagnostics.repeatedArticulations=added;
 result.diagnostics.articulationMethod='Rapid harmonic restart after a supported deep trough';
}
async function analyze(reader,config,options={}){
 const duration=Number(reader.duration)||0;if(!Number.isFinite(duration)||duration<0||duration>14400.05)throw new Error('Bass analysis supports audio up to four hours.');
 const count=Math.ceil(duration/STEP),extractor=new Extractor(options.telemetry),keys=['frequency','confidence','harmonics','energy'],frames={length:count},chunk=Math.max(1,Math.min(1000,Math.floor(options.chunkFrames||500))),halo=FFT_SIZE*DECIMATE/2+64*DECIMATE+64;
 for(const key of keys)frames[key]=new Float32Array(count);
 for(let first=0;first<count;first+=chunk){abort(options.signal);const n=Math.min(chunk,count-first),start=first*HOP-halo,samples=await reader.mono22050(start,(n-1)*HOP+2*halo+1,config),part=extractor.chunk(samples,start,first,n);for(let i=0;i<n;i++)for(const key of keys)frames[key][first+i]=part[i][key];options.onProgress?.(.7*(first+n)/count);}
 abort(options.signal);const result=summarize(frames,duration);await refineBoundaries(reader,config,result,extractor,options);await splitArticulations(reader,config,result,extractor,frames,options);
 // Refinement may extend a recovered onset beyond the initial coarse window.
 const norm=quantile(frames.energy,.95)||1;result.envelope.fill(0);
 for(const n of result.notes)for(let i=Math.max(0,Math.floor(n.start/STEP));i<Math.min(count,Math.ceil(n.end/STEP));i++)result.envelope[i]=Math.round(clamp(frames.energy[i]/norm)*n.confidence*1000)/1000;
 result.phrases=[];for(const n of result.notes){const p=result.phrases[result.phrases.length-1];if(p&&n.start-p.end<=.65&&n.end-p.start<=16){p.end=n.end;p.confidence=Math.round((p.confidence*p.notes+n.confidence)/(p.notes+1)*1000)/1000;p.notes++;if(n.strength>p.strength){p.strength=n.strength;p.accentTime=n.start;}}else result.phrases.push({start:n.start,end:n.end,confidence:n.confidence,strength:n.strength,accentTime:n.start,notes:1});}
 result.diagnostics.boundaryMethod='Exact-frequency harmonic amplitudes in local PCM';result.diagnostics.boundaryGridMs=5;result.diagnostics.boundaryWindowMs=Math.round(256/SR*1000);result.diagnostics.boundaryGridIsAccuracy=false;result.diagnostics.notes=result.notes.length;options.onProgress?.(1);return result;
}
scope.LightForgeBass={analyze,Extractor,summarize,version:'1.1.0'};
})(typeof self!=='undefined'?self:globalThis);
