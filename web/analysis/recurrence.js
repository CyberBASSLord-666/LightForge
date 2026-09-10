/*
 * LightForge recurrence and motif sidecar.
 *
 * This module deliberately consumes only already-produced structural evidence:
 * section spans, normalized energy and optional chroma.  It never decodes PCM,
 * runs a model, inspects lyrics, assigns song-form labels, or emits vehicle
 * commands.  The output is an opt-in planning hint which remains bound to the
 * exact semantic timeline that supplied its section IDs.
 */
(function(root){
 'use strict';

 const SCHEMA_VERSION=1;
 const ENGINE_VERSION='1.0.0';
 const MAX_SECTIONS=512;
 const MAX_ENERGY_FRAMES=360000;
 const MAX_CHROMA_FRAMES=72000;
 const FINGERPRINT_BINS=8;
 const CHROMA_BINS=12;
 const MIN_REPEAT_SEPARATION_SECONDS=1;
 const MIN_DURATION_RATIO=.65;
 const MAX_DURATION_RATIO=1.55;
 const MAX_ENERGY_DELTA=.28;
 const MIN_MATCH_SIMILARITY=.985;
 const finite=value=>typeof value==='number'&&Number.isFinite(value);
 const clamp=(value,min=0,max=1)=>Math.max(min,Math.min(max,finite(value)?value:0));
 const round=value=>Math.round(value*1000000)/1000000;
 const compareText=(left,right)=>left===right?0:(left<right?-1:1);
 const safeArray=value=>Array.isArray(value)||ArrayBuffer.isView(value)?Array.from(value):null;
 const validId=value=>typeof value==='string'&&value.length>0&&value.length<=160&&/^[A-Za-z0-9_.:-]+$/.test(value);
 const validGroup=value=>typeof value==='string'&&value.length>0&&value.length<=160&&/^[A-Za-z0-9_.:-]+$/.test(value);

 function stamped(value){
  if(value===undefined)return '';
  if(value===null)return '~';
  return finite(value)?String(round(value)):String(value);
 }
 function fnvAppend(state,value){
  const text=stamped(value);let hash=state;
  for(let index=0;index<text.length;index++)hash=Math.imul(hash^text.charCodeAt(index),16777619);
  return Math.imul(hash^255,16777619);
 }
 function hex(hash){return ('00000000'+(hash>>>0).toString(16)).slice(-8);}

 /* Kept byte-for-byte compatible with the semantic-timeline fingerprint shape
  * used by the salience sidecar.  That means a recurrence record can prove it
  * refers to the same canonical event IDs without importing another analyzer. */
 function timelineFingerprint(timeline){
  let hash=2166136261;
  const append=value=>{hash=fnvAppend(hash,value);};
  append(timeline.schemaVersion);append(timeline.duration);append(timeline.clock);
  for(const event of timeline.events){
   append(event.id);append(event.type);append(event.time);append(event.duration);append(event.source);append(event.confidence);append(event.intensity);append(event.salience);
   append(event.rhythm?.barPosition);append(event.rhythm?.beatTime);append(event.structure?.sectionIndex);append(event.structure?.phraseIndex);
   append(event.relationships?.crossStemAgreement);append(event.recurrenceGroup);append(event.repetitionIndex);
  }
  return hex(hash);
 }

 function validTimeline(timeline){
  const errors=[];
  if(!timeline||!Number.isInteger(timeline.schemaVersion)||!finite(timeline.duration)||timeline.duration<=0||!Array.isArray(timeline.events))errors.push('Invalid semantic timeline envelope.');
  let prior=-1;const ids=new Set();
  for(const event of timeline?.events||[]){
   if(!event||!validId(event.id)||ids.has(event.id))errors.push('Duplicate or missing semantic event id.');
   ids.add(event?.id);
   if(!finite(event?.time)||event.time<0||event.time>timeline.duration||event.time<prior)errors.push('Invalid semantic event order or time.');
   prior=event?.time;
   if(!finite(event?.duration)||event.duration<0||event.time+event.duration>timeline.duration+1e-6)errors.push('Invalid semantic event duration.');
  }
  return {valid:errors.length===0,errors};
 }
 function sectionEvents(timeline){
  return timeline.events.filter(event=>event&&event.type==='section'&&event.source==='structure'&&finite(event.time)&&finite(event.duration)&&event.duration>0)
   .map((event,index)=>({id:event.id,index,start:event.time,end:round(event.time+event.duration),duration:event.duration,energy:clamp(event.intensity),confidence:clamp(event.confidence),recurrenceGroup:validGroup(event.recurrenceGroup)?event.recurrenceGroup:null,similarity:finite(event.similarity)?clamp(event.similarity):null,repetitionIndex:Number.isInteger(event.repetitionIndex)&&event.repetitionIndex>=0?event.repetitionIndex:null}));
 }
 function numberSeries(value,maximum,name,errors,nonNegative=false){
  if(value===undefined||value===null)return null;
  const values=safeArray(value);
  if(!values||values.length>maximum){errors.push('Invalid '+name+' evidence length.');return null;}
  for(const item of values)if(!finite(item)||(nonNegative&&item<0)){errors.push('Invalid '+name+' evidence value.');return null;}
  return values.map(round);
 }
 function normalizedStep(value,name,errors){
  if(value===undefined||value===null)return null;
  if(!finite(value)||value<=0||value>2){errors.push('Invalid '+name+'.');return null;}
  return round(value);
 }
 function sameSpan(left,right){return Math.abs(left.start-right.start)<=1e-6&&Math.abs(left.end-right.end)<=1e-6;}
 function captureEvidence(music,timeline){
  const timelineCheck=validTimeline(timeline);if(!timelineCheck.valid)throw Error('Recurrence evidence requires a valid semantic timeline: '+timelineCheck.errors.join('; ').slice(0,512));
  const canonicalSections=sectionEvents(timeline);
  if(canonicalSections.length>MAX_SECTIONS)throw Error('Recurrence evidence exceeds the bounded section limit.');
  const inputSections=Array.isArray(music?.sections)?music.sections:[];
  const sections=canonicalSections.map((section,sectionIndex)=>{
   const source=inputSections.find(candidate=>candidate&&finite(candidate.start)&&finite(candidate.end)&&sameSpan(section,{start:candidate.start,end:candidate.end}));
   /* Semantic timeline fields are authoritative.  The optional DSP values are
    * copied only when they exactly describe the same span. */
   const energy=finite(source?.energy)?clamp(source.energy):section.energy;
   const confidence=finite(source?.confidence)?clamp(source.confidence):section.confidence;
   const recurrenceGroup=validGroup(source?.recurrenceGroup)?source.recurrenceGroup:section.recurrenceGroup;
   const similarity=finite(source?.similarity)?clamp(source.similarity):section.similarity;
   const repetitionIndex=Number.isInteger(source?.repetitionIndex)&&source.repetitionIndex>=0?source.repetitionIndex:section.repetitionIndex;
   return {sectionId:section.id,sectionIndex,start:section.start,end:section.end,duration:section.duration,energy,confidence,recurrenceGroup,similarity,repetitionIndex};
  });
  const errors=[];
  const energy=numberSeries(music?.energy,MAX_ENERGY_FRAMES,'energy',errors,true);
  const energyStep=normalizedStep(music?.energyStep,'energy step',errors);
  const chroma=numberSeries(music?.chroma,MAX_CHROMA_FRAMES*CHROMA_BINS,'chroma',errors,true);
  const chromaStep=normalizedStep(music?.chromaStep,'chroma step',errors);
  if((energy===null)!==(energyStep===null))errors.push('Energy evidence requires both values and a step.');
  if((chroma===null)!==(chromaStep===null))errors.push('Chroma evidence requires both values and a step.');
  if(chroma!==null&&chroma.length%CHROMA_BINS!==0)errors.push('Chroma evidence must contain twelve bins per frame.');
  if(energy!==null&&energy.length*energyStep+energyStep<timeline.duration)errors.push('Energy evidence does not cover the semantic timeline.');
  if(chroma!==null&&chroma.length/CHROMA_BINS*chromaStep+chromaStep<timeline.duration)errors.push('Chroma evidence does not cover the semantic timeline.');
  if(errors.length)throw Error('Invalid recurrence evidence: '+errors.join('; ').slice(0,512));
  return {schemaVersion:SCHEMA_VERSION,timelineSchemaVersion:timeline.schemaVersion,timelineFingerprint:timelineFingerprint(timeline),clock:timeline.clock,duration:timeline.duration,sections,energy,energyStep,chroma,chromaStep};
 }

 function validateEvidence(evidence,timeline){
  const errors=[];
  const timelineCheck=validTimeline(timeline);if(!timelineCheck.valid)errors.push('Invalid linked semantic timeline.');
  if(!evidence||evidence.schemaVersion!==SCHEMA_VERSION||!Number.isInteger(evidence.timelineSchemaVersion)||typeof evidence.timelineFingerprint!=='string'||!/^[0-9a-f]{8}$/.test(evidence.timelineFingerprint)||typeof evidence.clock!=='string'||!finite(evidence.duration)||evidence.duration<=0||!Array.isArray(evidence.sections))errors.push('Invalid recurrence evidence envelope.');
  if(timelineCheck.valid&&(evidence?.timelineSchemaVersion!==timeline.schemaVersion||evidence?.timelineFingerprint!==timelineFingerprint(timeline)||evidence?.clock!==timeline.clock||evidence?.duration!==timeline.duration))errors.push('Recurrence evidence does not match semantic timeline.');
  const canonical=timelineCheck.valid?sectionEvents(timeline):[];
  if((evidence?.sections||[]).length!==canonical.length||canonical.length>MAX_SECTIONS)errors.push('Recurrence evidence section count does not match semantic timeline.');
  const ids=new Set();
  for(let index=0;index<(evidence?.sections||[]).length;index++){
   const section=evidence.sections[index],expected=canonical[index];
   if(!section||!validId(section.sectionId)||ids.has(section.sectionId)||!Number.isInteger(section.sectionIndex)||section.sectionIndex!==index||!finite(section.start)||!finite(section.end)||!finite(section.duration)||section.duration<=0||!finite(section.energy)||section.energy<0||section.energy>1||!finite(section.confidence)||section.confidence<0||section.confidence>1)errors.push('Invalid recurrence evidence section.');
   ids.add(section?.sectionId);
   if(expected&&(!section||section.sectionId!==expected.id||!sameSpan(section,expected)||Math.abs(section.duration-expected.duration)>1e-6))errors.push('Recurrence evidence section does not match semantic timeline.');
   if(section?.recurrenceGroup!==null&&section?.recurrenceGroup!==undefined&&!validGroup(section.recurrenceGroup))errors.push('Invalid recurrence group evidence.');
   if(section?.similarity!==null&&section?.similarity!==undefined&&(!finite(section.similarity)||section.similarity<0||section.similarity>1))errors.push('Invalid recurrence similarity evidence.');
   if(section?.repetitionIndex!==null&&section?.repetitionIndex!==undefined&&(!Number.isInteger(section.repetitionIndex)||section.repetitionIndex<0))errors.push('Invalid recurrence repetition index evidence.');
  }
  const energy=numberSeries(evidence?.energy,MAX_ENERGY_FRAMES,'energy',errors,true),energyStep=normalizedStep(evidence?.energyStep,'energy step',errors);
  const chroma=numberSeries(evidence?.chroma,MAX_CHROMA_FRAMES*CHROMA_BINS,'chroma',errors,true),chromaStep=normalizedStep(evidence?.chromaStep,'chroma step',errors);
  if((energy===null)!==(energyStep===null))errors.push('Energy evidence requires both values and a step.');
  if((chroma===null)!==(chromaStep===null))errors.push('Chroma evidence requires both values and a step.');
  if(chroma!==null&&chroma.length%CHROMA_BINS!==0)errors.push('Chroma evidence must contain twelve bins per frame.');
  if(energy!==null&&energy.length*energyStep+energyStep<(timeline?.duration||0))errors.push('Energy evidence does not cover the semantic timeline.');
  if(chroma!==null&&chroma.length/CHROMA_BINS*chromaStep+chromaStep<(timeline?.duration||0))errors.push('Chroma evidence does not cover the semantic timeline.');
  return {valid:errors.length===0,errors};
 }

 function evidenceFingerprint(evidence){
  let hash=2166136261;
  const append=value=>{hash=fnvAppend(hash,value);};
  append(evidence.schemaVersion);append(evidence.timelineSchemaVersion);append(evidence.timelineFingerprint);append(evidence.clock);append(evidence.duration);append(evidence.energyStep);append(evidence.chromaStep);
  for(const section of evidence.sections){append(section.sectionId);append(section.sectionIndex);append(section.start);append(section.end);append(section.duration);append(section.energy);append(section.confidence);append(section.recurrenceGroup);append(section.similarity);append(section.repetitionIndex);}
  for(const value of evidence.energy||[])append(value);
  for(const value of evidence.chroma||[])append(value);
  return hex(hash);
 }

 function average(values,begin,end,step,dimensions=1){
  if(!values||!values.length||!finite(step)||step<=0)return null;
  const frames=Math.floor(values.length/dimensions),lo=Math.max(0,Math.floor(begin/step)),hi=Math.min(frames,Math.ceil(end/step));
  if(hi<=lo)return null;
  const result=new Float64Array(dimensions);let count=0;
  for(let frame=lo;frame<hi;frame++){
   for(let dimension=0;dimension<dimensions;dimension++)result[dimension]+=values[frame*dimensions+dimension];
   count++;
  }
  if(!count)return null;
  for(let dimension=0;dimension<dimensions;dimension++)result[dimension]/=count;
  return result;
 }
 function normalize(vector){
  if(!vector)return null;
  let norm=0;for(const value of vector)norm+=value*value;
  norm=Math.sqrt(norm);if(norm<=1e-12)return null;
  return Array.from(vector,value=>round(value/norm));
 }
 function cosine(left,right){
  if(!left||!right||left.length!==right.length)return 0;
  let value=0;for(let index=0;index<left.length;index++)value+=left[index]*right[index];
  return clamp(value,-1,1);
 }
 function descriptor(section,evidence){
  const values=[],energyBins=[];let energyFrames=0,chromaFrames=0;
  for(let bin=0;bin<FINGERPRINT_BINS;bin++){
   const start=section.start+section.duration*bin/FINGERPRINT_BINS,end=section.start+section.duration*(bin+1)/FINGERPRINT_BINS;
   const energy=average(evidence.energy,start,end,evidence.energyStep,1);
   if(energy){values.push(energy[0]);energyBins.push(energy[0]);energyFrames++;}else{values.push(section.energy);energyBins.push(section.energy);}
   const chroma=average(evidence.chroma,start,end,evidence.chromaStep,CHROMA_BINS);
   const normalizedChroma=normalize(chroma);
   if(normalizedChroma){values.push(...normalizedChroma);chromaFrames++;}else values.push(...new Array(CHROMA_BINS).fill(0));
  }
  const vector=normalize(values);
  const meanEnergy=energyBins.reduce((sum,value)=>sum+value,0)/Math.max(1,energyBins.length);
  return {vector,energy:round(meanEnergy),energyCoverage:round(energyFrames/FINGERPRINT_BINS),chromaCoverage:round(chromaFrames/FINGERPRINT_BINS)};
 }
 function qualifiedExistingGroup(items){
  if(items.length<2)return false;
  const later=items.slice(1);
  return later.every(item=>finite(item.section.similarity)&&item.section.similarity>=MIN_MATCH_SIMILARITY&&item.section.start-item.previous.section.end>=MIN_REPEAT_SEPARATION_SECONDS);
 }
 function freshMatch(candidate,representative){
  const durationRatio=candidate.section.duration/representative.section.duration;
  if(durationRatio<MIN_DURATION_RATIO||durationRatio>MAX_DURATION_RATIO)return null;
  if(Math.abs(candidate.descriptor.energy-representative.descriptor.energy)>MAX_ENERGY_DELTA)return null;
  if(candidate.section.start-representative.section.end<MIN_REPEAT_SEPARATION_SECONDS)return null;
  if(candidate.descriptor.chromaCoverage<1||representative.descriptor.chromaCoverage<1)return null;
  const similarity=cosine(candidate.descriptor.vector,representative.descriptor.vector);
  if(similarity<MIN_MATCH_SIMILARITY)return null;
  const confidence=clamp(.70*similarity+.15*Math.min(candidate.descriptor.energyCoverage,representative.descriptor.energyCoverage)+.15*Math.min(candidate.descriptor.chromaCoverage,representative.descriptor.chromaCoverage));
  return {similarity:round(similarity),confidence:round(confidence)};
 }
 function motifId(firstSectionId,ordinal){return 'motif-'+String(ordinal).padStart(3,'0')+'-'+firstSectionId;}
 function evolution(instances){
  const energies=instances.map(instance=>instance.energy),minimum=Math.min(...energies),maximum=Math.max(...energies),rawSpread=maximum-minimum,spread=Math.max(.001,rawSpread);
  return instances.map((instance,index)=>{
   const previous=index?instances[index-1].energy:instance.energy,delta=round(instance.energy-previous),relativeEnergy=round(rawSpread<=.001?.5:clamp((instance.energy-minimum)/spread));
   let phase='repeat';
   if(index===0)phase='establish';
   else if(delta>=.12)phase='escalate';
   else if(delta<=-.12)phase='release';
   else if(index>=2)phase='develop';
   const variation=round(index===0?0:clamp(.18+index*.12+Math.abs(delta)*.5,0,.85));
   return {...instance,repetitionIndex:index,evolution:{phase,energyDelta:delta,relativeEnergy,variation,requiresChoreographyOptIn:true}};
  });
 }
 function motifConfidence(instances){
  if(!instances.length)return 0;
  let score=0;for(const instance of instances)score+=instance.confidence;
  return round(clamp(score/instances.length));
 }

 function build(timeline,evidence){
  const evidenceCheck=validateEvidence(evidence,timeline);if(!evidenceCheck.valid)throw Error('Recurrence sidecar requires valid evidence: '+evidenceCheck.errors.join('; ').slice(0,512));
  const descriptors=evidence.sections.map(section=>({section,descriptor:descriptor(section,evidence)}));
  const assigned=new Set(),motifs=[],groups=new Map();
  for(const item of descriptors)if(item.section.recurrenceGroup){const group=groups.get(item.section.recurrenceGroup)||[];group.push(item);groups.set(item.section.recurrenceGroup,group);}
  /* Preserve a prevalidated DSP relation only when every repeat contains the
   * existing high-confidence tonal/energy similarity score.  A group name alone
   * is never treated as a musical event. */
  for(const [groupId,items] of Array.from(groups.entries()).sort((left,right)=>compareText(left[0],right[0]))){
   items.sort((left,right)=>left.section.start-right.section.start||compareText(left.section.sectionId,right.section.sectionId));
   const withPrevious=items.map((item,index)=>({...item,previous:index?items[index-1]:null}));
   if(!qualifiedExistingGroup(withPrevious))continue;
   const instances=evolution(withPrevious.map((item,index)=>({sectionId:item.section.sectionId,sectionIndex:item.section.sectionIndex,start:item.section.start,duration:item.section.duration,energy:item.descriptor.energy,similarity:index?round(item.section.similarity):1,confidence:index?round(clamp(.65*item.section.similarity+.20*item.section.confidence+.15*item.descriptor.energyCoverage)):round(clamp(.65+.20*item.section.confidence+.15*item.descriptor.energyCoverage))})));
   const id=motifId(instances[0].sectionId,motifs.length);
   motifs.push({id,evidence:'prevalidated-section-recurrence',confidence:motifConfidence(instances),instances});
   for(const item of items)assigned.add(item.section.sectionId);
  }
  /* Chroma may be retained by a feature-store consumer even when the older DSP
   * record had no recurrence group.  In that case we use the same deliberately
   * strict duration, energy, tonal and separation gates to form a new sidecar
   * identity.  It is still only a planning hint, never a structural label. */
  const representatives=[];
  for(const item of descriptors.slice().sort((left,right)=>left.section.start-right.section.start||compareText(left.section.sectionId,right.section.sectionId))){
   if(assigned.has(item.section.sectionId))continue;
   let best=null;
   for(const representative of representatives){
    const match=freshMatch(item,representative.item);
    if(!match)continue;
    if(!best||match.similarity>best.match.similarity+1e-9||Math.abs(match.similarity-best.match.similarity)<=1e-9&&compareText(representative.item.section.sectionId,best.representative.item.section.sectionId)<0)best={representative,match};
   }
   if(!best){representatives.push({item,instances:[{item,similarity:1,confidence:round(clamp(.55*.5+.25*item.section.confidence+.20*item.descriptor.chromaCoverage))}]});continue;}
   best.representative.instances.push({item,similarity:best.match.similarity,confidence:best.match.confidence});
  }
  for(const representative of representatives){
   if(representative.instances.length<2)continue;
   const instances=evolution(representative.instances.map(value=>({sectionId:value.item.section.sectionId,sectionIndex:value.item.section.sectionIndex,start:value.item.section.start,duration:value.item.section.duration,energy:value.item.descriptor.energy,similarity:value.similarity,confidence:value.confidence})));
   const id=motifId(instances[0].sectionId,motifs.length);
   motifs.push({id,evidence:'section-chroma-energy',confidence:motifConfidence(instances),instances});
  }
  motifs.sort((left,right)=>left.instances[0].start-right.instances[0].start||compareText(left.id,right.id));
  const assignments=[];
  /* Assignments are a denormalized read model for choreographers.  Keep their
   * evolution object independent from the motif record so an editor cannot
   * accidentally mutate the evidence record through a convenience view. */
  for(const motif of motifs)for(const instance of motif.instances)assignments.push({sectionId:instance.sectionId,sectionIndex:instance.sectionIndex,motifId:motif.id,confidence:instance.confidence,similarity:instance.similarity,repetitionIndex:instance.repetitionIndex,evolution:{...instance.evolution}});
  assignments.sort((left,right)=>left.sectionIndex-right.sectionIndex||compareText(left.sectionId,right.sectionId));
  const prevalidatedCount=motifs.filter(motif=>motif.evidence==='prevalidated-section-recurrence').length;
  const chromaCount=motifs.filter(motif=>motif.evidence==='section-chroma-energy').length;
  return {schemaVersion:SCHEMA_VERSION,engineVersion:ENGINE_VERSION,timelineSchemaVersion:timeline.schemaVersion,timelineFingerprint:timelineFingerprint(timeline),evidenceFingerprint:evidenceFingerprint(evidence),clock:timeline.clock,duration:timeline.duration,motifs,assignments,summary:{sectionCount:evidence.sections.length,motifCount:motifs.length,repeatedSectionCount:assignments.length,unassignedSectionCount:evidence.sections.length-assignments.length,evidence:{hasEnergy:Array.isArray(evidence.energy),hasChroma:Array.isArray(evidence.chroma),prevalidatedMotifCount:prevalidatedCount,chromaEnergyMotifCount:chromaCount},scope:'Opt-in motif metadata derived only from bound section, energy and chroma evidence. It does not label song form, create music events, or schedule vehicle outputs.'}};
 }

 function validEvolution(value){
  return !!value&&['establish','repeat','develop','escalate','release'].includes(value.phase)&&finite(value.energyDelta)&&value.energyDelta>=-1&&value.energyDelta<=1&&finite(value.relativeEnergy)&&value.relativeEnergy>=0&&value.relativeEnergy<=1&&finite(value.variation)&&value.variation>=0&&value.variation<=.85&&value.requiresChoreographyOptIn===true;
 }
 function validate(sidecar,timeline,evidence){
  const errors=[];
  const timelineCheck=validTimeline(timeline);if(!timelineCheck.valid)errors.push('Invalid linked semantic timeline.');
  const evidenceCheck=validateEvidence(evidence,timeline);if(!evidenceCheck.valid)errors.push('Invalid linked recurrence evidence.');
  if(!sidecar||sidecar.schemaVersion!==SCHEMA_VERSION||sidecar.engineVersion!==ENGINE_VERSION||!Number.isInteger(sidecar.timelineSchemaVersion)||typeof sidecar.timelineFingerprint!=='string'||!/^[0-9a-f]{8}$/.test(sidecar.timelineFingerprint)||typeof sidecar.evidenceFingerprint!=='string'||!/^[0-9a-f]{8}$/.test(sidecar.evidenceFingerprint)||typeof sidecar.clock!=='string'||!finite(sidecar.duration)||sidecar.duration<=0||!Array.isArray(sidecar.motifs)||!Array.isArray(sidecar.assignments)||!sidecar.summary||typeof sidecar.summary!=='object')errors.push('Invalid recurrence sidecar envelope.');
  if(timelineCheck.valid&&(sidecar?.timelineSchemaVersion!==timeline.schemaVersion||sidecar?.timelineFingerprint!==timelineFingerprint(timeline)||sidecar?.clock!==timeline.clock||sidecar?.duration!==timeline.duration))errors.push('Recurrence sidecar does not match semantic timeline.');
  if(evidenceCheck.valid&&sidecar?.evidenceFingerprint!==evidenceFingerprint(evidence))errors.push('Recurrence sidecar does not match recurrence evidence.');
  const sections=new Map((evidence?.sections||[]).map(section=>[section.sectionId,section]));
  const motifIds=new Set(),assignmentIds=new Set(),instancesBySection=new Map();let priorStart=-1;
  for(const motif of sidecar?.motifs||[]){
   if(!motif||!validId(motif.id)||motifIds.has(motif.id)||!['prevalidated-section-recurrence','section-chroma-energy'].includes(motif.evidence)||!finite(motif.confidence)||motif.confidence<0||motif.confidence>1||!Array.isArray(motif.instances)||motif.instances.length<2)errors.push('Invalid recurrence motif.');
   motifIds.add(motif?.id);
   let prior=-1;const localIds=new Set();
   for(let index=0;index<(motif?.instances||[]).length;index++){
    const instance=motif.instances[index],section=sections.get(instance?.sectionId);
    if(!instance||!section||localIds.has(instance.sectionId)||instance.sectionIndex!==section.sectionIndex||!finite(instance.start)||Math.abs(instance.start-section.start)>1e-6||!finite(instance.duration)||Math.abs(instance.duration-section.duration)>1e-6||!finite(instance.energy)||instance.energy<0||instance.energy>1||!finite(instance.similarity)||instance.similarity<0||instance.similarity>1||!finite(instance.confidence)||instance.confidence<0||instance.confidence>1||instance.repetitionIndex!==index||!validEvolution(instance.evolution)||instance.start<prior)errors.push('Invalid recurrence motif instance.');
    localIds.add(instance?.sectionId);instancesBySection.set(instance?.sectionId,{motifId:motif?.id,instance});prior=instance?.start;
   }
   if(motif?.instances?.[0]?.start<priorStart)errors.push('Recurrence motifs are not in canonical order.');
   priorStart=motif?.instances?.[0]?.start;
  }
  let priorAssignmentIndex=-1;
  for(const assignment of sidecar?.assignments||[]){
   const section=sections.get(assignment?.sectionId);
   const linked=instancesBySection.get(assignment?.sectionId);
   if(!assignment||!section||assignmentIds.has(assignment.sectionId)||!motifIds.has(assignment.motifId)||assignment.sectionIndex!==section.sectionIndex||assignment.sectionIndex<priorAssignmentIndex||!finite(assignment.confidence)||assignment.confidence<0||assignment.confidence>1||!finite(assignment.similarity)||assignment.similarity<0||assignment.similarity>1||!Number.isInteger(assignment.repetitionIndex)||assignment.repetitionIndex<0||!validEvolution(assignment.evolution)||!linked||linked.motifId!==assignment.motifId||linked.instance.confidence!==assignment.confidence||linked.instance.similarity!==assignment.similarity||linked.instance.repetitionIndex!==assignment.repetitionIndex||JSON.stringify(linked.instance.evolution)!==JSON.stringify(assignment.evolution))errors.push('Invalid recurrence assignment.');
   assignmentIds.add(assignment?.sectionId);
   priorAssignmentIndex=assignment?.sectionIndex;
  }
  const motifInstances=(sidecar?.motifs||[]).flatMap(motif=>motif.instances||[]);
  if(motifInstances.length!==assignmentIds.size)errors.push('Recurrence assignment count does not match motif instances.');
  for(const instance of motifInstances)if(!assignmentIds.has(instance.sectionId))errors.push('Recurrence motif instance is missing an assignment.');
  const summary=sidecar?.summary;
  const prevalidatedCount=(sidecar?.motifs||[]).filter(motif=>motif.evidence==='prevalidated-section-recurrence').length;
  const chromaCount=(sidecar?.motifs||[]).filter(motif=>motif.evidence==='section-chroma-energy').length;
  if(!Number.isInteger(summary?.sectionCount)||summary.sectionCount!==sections.size||!Number.isInteger(summary?.motifCount)||summary.motifCount!==(sidecar?.motifs||[]).length||!Number.isInteger(summary?.repeatedSectionCount)||summary.repeatedSectionCount!==(sidecar?.assignments||[]).length||!Number.isInteger(summary?.unassignedSectionCount)||summary.unassignedSectionCount!==sections.size-(sidecar?.assignments||[]).length||!summary?.evidence||summary.evidence.hasEnergy!==Array.isArray(evidence?.energy)||summary.evidence.hasChroma!==Array.isArray(evidence?.chroma)||summary.evidence.prevalidatedMotifCount!==prevalidatedCount||summary.evidence.chromaEnergyMotifCount!==chromaCount||typeof summary.scope!=='string')errors.push('Invalid recurrence sidecar summary.');
  return {valid:errors.length===0,errors};
 }

 const api=Object.freeze({version:ENGINE_VERSION,captureEvidence,validateEvidence,evidenceFingerprint,timelineFingerprint,build,validate,constants:Object.freeze({MAX_SECTIONS,MAX_ENERGY_FRAMES,MAX_CHROMA_FRAMES,FINGERPRINT_BINS,CHROMA_BINS,MIN_MATCH_SIMILARITY})});
 root.LightForgeRecurrence=api;
 if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof self!=='undefined'?self:globalThis);
