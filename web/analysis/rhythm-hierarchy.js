/*
 * Evidence-aware rhythm hierarchy sidecar.
 *
 * This module deliberately does not decode a second beat grid or rewrite the
 * Beat This! output.  It turns already validated legacy rhythm evidence into a
 * bounded, confidence-carrying hierarchy that consumers may opt into.  When
 * the evidence is incomplete, the relevant level is left empty/uncertain rather
 * than filled with guessed beats, bars, or meter changes.
 */
(function(scope){'use strict';
const VERSION=1,EPSILON=1e-6,MAX_ONSETS=12000;
const finite=value=>typeof value==='number'&&Number.isFinite(value);
const clamp=(value,low=0,high=1)=>Math.max(low,Math.min(high,value));
const round=value=>Math.round(value*1000000)/1000000;
const ordered=(values,low,high)=>Array.isArray(values)&&values.every((value,index)=>finite(value)&&value>=low-EPSILON&&value<=high+EPSILON&&(!index||value>values[index-1]+EPSILON));
const median=values=>{if(!values.length)return 0;const copy=values.slice().sort((a,b)=>a-b),middle=Math.floor(copy.length/2);return copy.length%2?copy[middle]:(copy[middle-1]+copy[middle])/2;};
const mean=values=>values.length?values.reduce((sum,value)=>sum+value,0)/values.length:0;
const relative=(left,right)=>Math.abs(left-right)/Math.max(EPSILON,Math.abs(left),Math.abs(right));
const fingerprint=text=>{let hash=0x811c9dc5;for(let index=0;index<text.length;index++)hash=Math.imul(hash^text.charCodeAt(index),0x01000193)>>>0;return hash.toString(16).padStart(8,'0');};
function nearestIndex(values,time,tolerance){
 let lo=0,hi=values.length;while(lo<hi){const middle=(lo+hi)>>1;if(values[middle]<time)lo=middle+1;else hi=middle;}
 const candidates=[lo-1,lo].filter(index=>index>=0&&index<values.length);let best=-1,bestDelta=Infinity;
 for(const index of candidates){const delta=Math.abs(values[index]-time);if(delta<bestDelta){best=index;bestDelta=delta;}}
 return bestDelta<=tolerance?best:-1;
}
function legacyEvidence(analysis){
 if(!analysis||typeof analysis!=='object'||!finite(analysis.duration)||analysis.duration<0)return {valid:false,reason:'duration'};
 const duration=analysis.duration,beats=Array.isArray(analysis.beats)?analysis.beats:[];
 if(!ordered(beats,0,duration))return {valid:false,reason:'beats'};
 const downbeats=Array.isArray(analysis.downbeats)?analysis.downbeats:[];
 if(!ordered(downbeats,0,duration))return {valid:false,reason:'downbeats'};
 if(downbeats.some(time=>nearestIndex(beats,time,.081)<0))return {valid:false,reason:'downbeats-not-on-grid'};
 const meter=Number.isInteger(analysis.meter)&&analysis.meter>=2&&analysis.meter<=12?analysis.meter:null;
 const bpm=finite(analysis.bpm)&&analysis.bpm>0&&analysis.bpm<=400?analysis.bpm:null;
 const details=Array.isArray(analysis.beatDetails)?analysis.beatDetails:[];
 if(details.length&&details.length!==beats.length)return {valid:false,reason:'beat-details-length'};
 for(let index=0;index<details.length;index++){
  const detail=details[index];
  if(!detail||typeof detail!=='object'||!finite(detail.time)||Math.abs(detail.time-beats[index])>.081)return {valid:false,reason:'beat-details'};
  if(detail.confidence!==undefined&&(!finite(detail.confidence)||detail.confidence<0||detail.confidence>1))return {valid:false,reason:'beat-detail-confidence'};
  if(detail.localBpm!==undefined&&(!finite(detail.localBpm)||detail.localBpm<=0||detail.localBpm>400))return {valid:false,reason:'beat-detail-tempo'};
  if(detail.barPosition!==undefined&&(!Number.isInteger(detail.barPosition)||detail.barPosition<1||detail.barPosition>12))return {valid:false,reason:'beat-detail-bar-position'};
 }
 const baseConfidence=clamp(finite(analysis.beatConfidence)?analysis.beatConfidence:0);
 const downbeatConfidence=clamp(finite(analysis.downbeatConfidence)?analysis.downbeatConfidence:0);
 const meterConfidence=clamp(finite(analysis.meterConfidence)?analysis.meterConfidence:0);
 return {valid:true,duration,beats:beats.slice(),downbeats:downbeats.slice(),details:details.slice(),meter,bpm,baseConfidence,downbeatConfidence,meterConfidence};
}
function evidenceSignature(analysis){
 const evidence=legacyEvidence(analysis);if(!evidence.valid)return null;
 // This is a cache coherence signature, not a cryptographic identity.  The
 // durable work store already binds the underlying rhythm stage to audio/model
 // identity; this catches a sidecar copied onto a different beat map.
 const detail=analysis.beatDetails||[];
 const encode=values=>values.map(value=>round(value)).join(',');
 const onsets=(Array.isArray(analysis.onsets)?analysis.onsets:[]).filter(value=>value&&typeof value==='object'&&finite(value.time)&&value.time>=0&&value.time<=evidence.duration&&finite(value.strength)&&value.strength>=0).slice(0,MAX_ONSETS).sort((left,right)=>left.time-right.time).map(value=>[round(value.time),round(clamp(value.strength)),typeof value.band==='string'?value.band:'unknown'].join(':')).join(',');
 const spans=values=>(Array.isArray(values)?values:[]).filter(value=>validSpan(value,evidence.duration)).map(value=>[round(value.start),round(value.end),value.kind||value.label||'',round(clamp(finite(value.confidence)?value.confidence:0)),value.estimated!==false,typeof value.recurrenceGroup==='string'?value.recurrenceGroup:'',Number.isInteger(value.repetitionIndex)?value.repetitionIndex:''].join(':')).join(',');
 return ['rhythm-hierarchy',VERSION,round(evidence.duration),evidence.meter||'unknown',evidence.bpm===null?'unknown':round(evidence.bpm),round(evidence.baseConfidence),round(evidence.downbeatConfidence),round(evidence.meterConfidence),encode(evidence.beats),encode(evidence.downbeats),detail.map(value=>[round(value.time),value.localBpm===undefined?'':round(value.localBpm),value.barPosition===undefined?'':value.barPosition,value.confidence===undefined?'':round(value.confidence)].join(':')).join(','),fingerprint(onsets),fingerprint(spans(analysis.phrases)),fingerprint(spans(analysis.sections))].join('|');
}
function intervalEvidence(evidence){
 const intervals=[];
 for(let index=1;index<evidence.beats.length;index++){
  const duration=evidence.beats[index]-evidence.beats[index-1],previous=evidence.details[index-1],detail=evidence.details[index];
  if(duration<.15||duration>2)continue;
  const confidence=clamp(Math.min(detail?.confidence??evidence.baseConfidence,previous?.confidence??evidence.baseConfidence));
  intervals.push({index:index-1,start:evidence.beats[index-1],end:evidence.beats[index],duration,bpm:60/duration,confidence});
 }
 return intervals;
}
function tempoSegments(intervals){
 if(!intervals.length)return [];
 const runs=[],close=(left,right)=>relative(left.bpm,right.bpm)<=.085;
 let start=0;
 // A new tempo needs two consecutive compatible intervals.  An isolated bad
 // peak therefore remains a low-confidence fluctuation rather than becoming a
 // fictional tempo change.
 for(let index=2;index<intervals.length;index++){
  const candidate=intervals[index],previous=intervals[index-1],prefix=intervals.slice(start,index),reference=median(prefix.map(value=>value.bpm));
  if(relative(candidate.bpm,reference)>.12&&close(candidate,previous)){
   // The first of the two agreeing intervals belongs to the new tempo.  Keep
   // it with its supporting neighbour rather than contaminating the previous
   // segment with one beat of a confirmed transition.
   const boundary=index-1;
   if(boundary-start>=2){runs.push(intervals.slice(start,boundary));start=boundary;}
  }
 }
 runs.push(intervals.slice(start));
 return runs.filter(run=>run.length).map((run,index)=>{
  const tempos=run.map(value=>value.bpm),typical=median(tempos),spread=median(tempos.map(value=>relative(value,typical))),confidence=clamp(mean(run.map(value=>value.confidence))*(1-clamp(spread/.16)));
  return {index,start:round(run[0].start),end:round(run[run.length-1].end),startBeatIndex:run[0].index,endBeatIndex:run[run.length-1].index+1,bpm:round(typical),confidence:round(confidence),intervalCount:run.length,variable:spread>.025};
 });
}
function tempoSummary(evidence,intervals){
 const typical=median(intervals.map(value=>value.bpm)),segments=tempoSegments(intervals),ratios=typical?intervals.map(value=>value.duration/Math.max(EPSILON,60/typical)):[];
 const doubled=ratios.filter(value=>Math.abs(value-2)<=.1).length,halved=ratios.filter(value=>Math.abs(value-.5)<=.055).length;
 const irregular=intervals.length-ratios.filter(value=>value>=.65&&value<=1.5).length;
 const localTempi=evidence.details.map(value=>value?.localBpm).filter(finite),localAgreement=localTempi.length&&typical?median(localTempi.map(value=>relative(value,typical))):null;
 const confidence=intervals.length?clamp(mean(intervals.map(value=>value.confidence))*(1-clamp(median(intervals.map(value=>relative(value.bpm,typical)))/.22))):0;
 const ambiguityEvidence=[];
 if(doubled)ambiguityEvidence.push({kind:'missing-or-half-time-interval',count:doubled});
 if(halved)ambiguityEvidence.push({kind:'double-time-interval',count:halved});
 if(localAgreement!==null&&localAgreement>.35)ambiguityEvidence.push({kind:'local-tempo-disagreement',relativeError:round(localAgreement)});
 return {globalBpm:evidence.bpm===null?null:round(evidence.bpm),observedBpm:typical?round(typical):null,confidence:round(confidence),intervalCount:intervals.length,variable:segments.length>1||segments.some(segment=>segment.variable),segments,halfDouble:{ambiguous:ambiguityEvidence.length>0,evidence:ambiguityEvidence,candidates:typical?[{multiplier:.5,bpm:round(typical*.5)},{multiplier:1,bpm:round(typical)},{multiplier:2,bpm:round(typical*2)}]:[],safeguard:'No alternate grid is substituted for the approved beat map.'},irregularIntervalCount:irregular};
}
function hierarchyBeats(evidence,intervals){
 const downbeatIndices=new Set(evidence.downbeats.map(time=>nearestIndex(evidence.beats,time,.081)).filter(index=>index>=0));
 const localByIndex=new Map(intervals.map(value=>[value.index,value]));
 return evidence.beats.map((time,index)=>{
  const detail=evidence.details[index]||{},interval=localByIndex.get(index)||localByIndex.get(index-1);
  return {index,time:round(time),confidence:round(clamp(detail.confidence??evidence.baseConfidence)),localBpm:finite(detail.localBpm)?round(detail.localBpm):(interval?round(interval.bpm):null),barPosition:Number.isInteger(detail.barPosition)?detail.barPosition:null,downbeat:downbeatIndices.has(index)};
 });
}
function barsFromEvidence(beats,evidence){
 const starts=beats.filter(beat=>beat.downbeat),bars=[];
 for(let index=0;index<starts.length;index++){
  const start=starts[index],next=starts[index+1],endIndex=next?next.index:beats.length,beatCount=endIndex-start.index;
  const complete=evidence.meter!==null&&!!next&&beatCount===evidence.meter;
  bars.push({index,start:round(start.time),end:next?round(next.time):null,startBeatIndex:start.index,endBeatIndex:next?next.index:null,beatCount,meter:evidence.meter,confidence:round(clamp(Math.min(evidence.downbeatConfidence,start.confidence,next?.confidence??start.confidence))),complete,verified:complete&&evidence.downbeatConfidence>=.35});
 }
 return bars;
}
function meterEvidence(evidence,bars){
 const counts=bars.filter(bar=>bar.end!==null&&bar.beatCount>=2&&bar.beatCount<=12).map(bar=>bar.beatCount),details=evidence.details;
 const values=[2,3,4,5,6,7,8];if(evidence.meter!==null&&!values.includes(evidence.meter))values.push(evidence.meter);
 const candidates=values.map(value=>{
  const measured=counts.length?counts.filter(count=>count===value).length/counts.length:0;
  let positionCount=0,positionMatches=0;
  details.forEach((detail,index)=>{if(Number.isInteger(detail?.barPosition)){positionCount++;if(detail.barPosition===((index%value)+1))positionMatches++;}});
  const positional=positionCount?positionMatches/positionCount:0;
  // Downbeat spacing is stronger evidence than the decoder's existing bar
  // labels, but neither is enough to replace the legacy meter on its own.
  const confidence=clamp((measured*.75+positional*.25)*Math.max(evidence.downbeatConfidence,evidence.meterConfidence*.5));
  return {value,confidence:round(confidence),measuredBarMatches:counts.filter(count=>count===value).length,observedBars:counts.length};
 }).sort((left,right)=>right.confidence-left.confidence||left.value-right.value);
 const best=candidates[0]||null,legacy=candidates.find(candidate=>candidate.value===evidence.meter)||null;
 return {value:evidence.meter,confidence:round(evidence.meterConfidence),candidates,legacyAgreement:legacy&&best?round(1-Math.abs(legacy.confidence-best.confidence)):null,safeguard:'Legacy meter remains authoritative; alternative evidence is exposed without changing the beat grid.'};
}
function validSpan(value,duration){return value&&typeof value==='object'&&finite(value.start)&&finite(value.end)&&value.start>=0&&value.end>value.start&&value.end<=duration+EPSILON;}
function structures(analysis,duration){
 const copy=(values,kind)=>Array.isArray(values)?values.filter(value=>validSpan(value,duration)).map((value,index)=>({index,start:round(value.start),end:round(value.end),duration:round(value.end-value.start),kind:value.kind||value.label||kind,confidence:round(clamp(finite(value.confidence)?value.confidence:0)),estimated:value.estimated!==false,recurrenceGroup:typeof value.recurrenceGroup==='string'?value.recurrenceGroup:null,repetitionIndex:Number.isInteger(value.repetitionIndex)?value.repetitionIndex:null})):[];
 return {phrases:copy(analysis.phrases,'phrase'),sections:copy(analysis.sections,'section')};
}
function subdivisions(analysis,beats,duration){
 if(!Array.isArray(analysis.onsets)||beats.length<2)return {microOnsets:[],subdivisions:[]};
 const source=analysis.onsets.filter(value=>value&&typeof value==='object'&&finite(value.time)&&value.time>=0&&value.time<=duration&&finite(value.strength)&&value.strength>=0).slice(0,MAX_ONSETS).sort((left,right)=>left.time-right.time);
 const microOnsets=source.map((value,index)=>({index,time:round(value.time),strength:round(clamp(value.strength)),band:typeof value.band==='string'?value.band:'unknown'}));
 const values=[];
 for(const onset of microOnsets){
  let before=-1;for(let index=0;index<beats.length&&beats[index].time<=onset.time+EPSILON;index++)before=index;
  if(before<0||before>=beats.length-1)continue;
  const left=beats[before],right=beats[before+1],span=right.time-left.time;
  if(span<.15||span>2)continue;
  const phase=(onset.time-left.time)/span,grids=[{ratio:.25,label:'quarter-subdivision'},{ratio:1/3,label:'triplet-subdivision'},{ratio:.5,label:'eighth-subdivision'},{ratio:2/3,label:'triplet-subdivision'},{ratio:.75,label:'quarter-subdivision'}];
  let candidate=grids[0],error=Infinity;for(const grid of grids){const delta=Math.abs(phase-grid.ratio);if(delta<error){candidate=grid;error=delta;}}
  // An onset must really support a grid location.  Weak/off-grid material stays
  // as a micro-onset but is not promoted to a subdivision event.
  const confidence=clamp(onset.strength*Math.min(left.confidence,right.confidence)*(1-error/.075));
  if(error<=.075&&confidence>=.12)values.push({time:onset.time,betweenBeats:[left.index,right.index],ratio:round(candidate.ratio),kind:candidate.label,confidence:round(confidence),sourceOnsetIndex:onset.index});
 }
 return {microOnsets,subdivisions:values};
}
function build(analysis){
 const evidence=legacyEvidence(analysis);if(!evidence.valid)return null;
 const intervals=intervalEvidence(evidence),beats=hierarchyBeats(evidence,intervals),bars=barsFromEvidence(beats,evidence),levels=subdivisions(analysis,beats,evidence.duration),structure=structures(analysis,evidence.duration),meter=meterEvidence(evidence,bars);
 const limitations=[];
 if(!beats.length)limitations.push('No approved beat evidence was available; no rhythm grid was synthesized.');
 if(!evidence.downbeats.length)limitations.push('No approved downbeats were available; bars remain unverified.');
 if(evidence.meterConfidence<.35&&beats.length)limitations.push('Meter confidence is low; bar positions are retained as uncertainty-bearing evidence.');
 if(!intervals.length&&beats.length>1)limitations.push('Beat intervals were outside the bounded tempo range; tempo changes were not inferred.');
 const tempo=tempoSummary(evidence,intervals);
 if(tempo.halfDouble.ambiguous)limitations.push('Half/double-time ambiguity is reported without replacing the approved beat grid.');
 return {schemaVersion:VERSION,kind:'evidence-aware-rhythm-hierarchy',source:'approved-rhythm-summary',inputSignature:evidenceSignature(analysis),duration:round(evidence.duration),status:beats.length?'partial-evidence':'no-pulse',confidence:{beat:round(evidence.baseConfidence),downbeat:round(evidence.downbeatConfidence),meter:round(evidence.meterConfidence),tempo:tempo.confidence},tempo,meter,microOnsets:levels.microOnsets,subdivisions:levels.subdivisions,beats,downbeats:beats.filter(beat=>beat.downbeat).map(beat=>({time:beat.time,beatIndex:beat.index,confidence:round(clamp(Math.min(beat.confidence,evidence.downbeatConfidence)))})),bars,phrases:structure.phrases,sections:structure.sections,limitations};
}
function validate(hierarchy,analysis){
 const evidence=legacyEvidence(analysis);if(!evidence.valid)return {valid:false,reason:'legacy-'+evidence.reason};
 if(!hierarchy||typeof hierarchy!=='object'||hierarchy.schemaVersion!==VERSION||hierarchy.kind!=='evidence-aware-rhythm-hierarchy')return {valid:false,reason:'schema'};
 if(hierarchy.inputSignature!==evidenceSignature(analysis)||!finite(hierarchy.duration)||Math.abs(hierarchy.duration-evidence.duration)>EPSILON)return {valid:false,reason:'stale'};
 if(!Array.isArray(hierarchy.beats)||hierarchy.beats.length!==evidence.beats.length||hierarchy.beats.some((beat,index)=>!beat||!finite(beat.time)||Math.abs(beat.time-evidence.beats[index])>EPSILON))return {valid:false,reason:'beat-map'};
 if(!Array.isArray(hierarchy.downbeats)||hierarchy.downbeats.some(value=>!value||nearestIndex(evidence.downbeats,value.time,EPSILON)<0))return {valid:false,reason:'downbeat-map'};
 if(!Array.isArray(hierarchy.bars)||hierarchy.bars.some(value=>!value||nearestIndex(evidence.downbeats,value.start,EPSILON)<0))return {valid:false,reason:'bars'};
 if(!hierarchy.tempo||!Array.isArray(hierarchy.tempo.segments)||!hierarchy.meter)return {valid:false,reason:'levels'};
 return {valid:true};
}
function attach(analysis){
 const existing=validate(analysis?.rhythmHierarchy,analysis);if(existing.valid)return {attached:false,reused:true,hierarchy:analysis.rhythmHierarchy};
 const hierarchy=build(analysis);if(!hierarchy)return {attached:false,reused:false,reason:'unvalidated-rhythm-evidence'};
 analysis.rhythmHierarchy=hierarchy;return {attached:true,reused:false,hierarchy};
}
scope.LightForgeRhythmHierarchy={VERSION,legacyEvidence,evidenceSignature,build,validate,attach};
})(typeof self!=='undefined'?self:globalThis);
