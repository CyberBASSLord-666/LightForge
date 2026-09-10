/* Deterministic context-aware ranking of existing semantic music events.
 * This module never detects, changes, or invents music events, lyrics, or text. */
(function(root){'use strict';
 const SCHEMA_VERSION=1,ENGINE_VERSION='1.0.0',MAX_HIGHLIGHTS=32;
 const finite=value=>typeof value==='number'&&Number.isFinite(value);
 const clamp=(value,min=0,max=1)=>Math.max(min,Math.min(max,finite(value)?value:0));
 const round=value=>Math.round(value*1000000)/1000000;
 const compareText=(left,right)=>left===right?0:(left<right?-1:1);
 const profiles=new Set(['vocal-led','low-end-led','rhythm-led','balanced','sparse']);
 const tierFor=score=>score>=.90?'climax':score>=.78?'structural':score>=.62?'phrase':score>=.52?'primary':score>=.32?'secondary':'micro';
 const weights={
  'vocal-led':{baseline:.13,confidence:.15,intensity:.12,structural:.14,rhythmic:.09,transition:.08,crossStem:.09,recurrence:.04,sourcePriority:.16},
  'low-end-led':{baseline:.13,confidence:.13,intensity:.13,structural:.15,rhythmic:.15,transition:.10,crossStem:.10,recurrence:.03,sourcePriority:.08},
  'rhythm-led':{baseline:.12,confidence:.12,intensity:.12,structural:.14,rhythmic:.18,transition:.10,crossStem:.10,recurrence:.03,sourcePriority:.09},
  balanced:{baseline:.14,confidence:.13,intensity:.12,structural:.15,rhythmic:.14,transition:.09,crossStem:.10,recurrence:.04,sourcePriority:.09},
  sparse:{baseline:.12,confidence:.14,intensity:.10,structural:.22,rhythmic:.06,transition:.14,crossStem:.08,recurrence:.05,sourcePriority:.09}
 };
 const priorities={
  'vocal-led':{vocals:.96,bass:.60,rhythm:.67,drums:.70,mix:.66,structure:.82},
  'low-end-led':{vocals:.60,bass:.96,rhythm:.85,drums:.86,mix:.82,structure:.84},
  'rhythm-led':{vocals:.60,bass:.75,rhythm:.96,drums:.96,mix:.90,structure:.84},
  balanced:{vocals:.75,bass:.75,rhythm:.80,drums:.80,mix:.76,structure:.82},
  sparse:{vocals:.78,bass:.68,rhythm:.60,drums:.60,mix:.55,structure:.94}
 };
 const validTimeline=timeline=>{
  const errors=[];
  if(!timeline||timeline.schemaVersion!==2||timeline.clock!=='original-decoded-audio'||!finite(timeline.duration)||timeline.duration<=0||!Array.isArray(timeline.events))errors.push('Invalid semantic timeline envelope.');
  let prior=-1;const ids=new Set();
  for(const event of timeline?.events||[]){
   if(!event||typeof event.id!=='string'||!event.id||ids.has(event.id))errors.push('Duplicate or missing event id.');
   ids.add(event?.id);
   if(!finite(event.time)||event.time<0||event.time>timeline.duration||event.time<prior)errors.push('Invalid event order or time.');
   prior=event?.time;
   if(!finite(event?.salience)||event.salience<0||event.salience>1)errors.push('Invalid event salience.');
   if(Object.prototype.hasOwnProperty.call(event||{},'salienceCap')&&
      (!finite(event.salienceCap)||event.salienceCap<0||event.salienceCap>1||event.salience>event.salienceCap+1e-9))errors.push('Invalid event salience cap.');
  }
  return {valid:errors.length===0,errors};
 };
 const stamped=value=>value===undefined?'':value===null?'~':(finite(value)?String(round(value)):String(value));
 function timelineFingerprint(timeline){
  let hash=2166136261;
  const append=value=>{const text=stamped(value);for(let index=0;index<text.length;index++)hash=Math.imul(hash^text.charCodeAt(index),16777619);hash=Math.imul(hash^255,16777619);};
  append(timeline.schemaVersion);append(timeline.duration);append(timeline.clock);
  for(const event of timeline.events){
   append(event.id);append(event.type);append(event.time);append(event.duration);append(event.source);append(event.confidence);append(event.intensity);append(event.salience);
   append(event.rhythm?.barPosition);append(event.rhythm?.beatTime);append(event.structure?.sectionIndex);append(event.structure?.phraseIndex);
   append(event.relationships?.crossStemAgreement);append(event.recurrenceGroup);append(event.repetitionIndex);
   // Preserve legacy cache fingerprints unless an event carries the new explicit
   // low-trust cap; a capped estimate must never reuse an uncapped ranking.
   if(event.salienceCap!==undefined){append('salience-cap-v1');append(event.salienceCap);}
  }
  return ('00000000'+(hash>>>0).toString(16)).slice(-8);
 }
 function evidence(events,expected){
  if(!events.length)return 0;
  let quality=0;for(const event of events)quality+=.6*clamp(event.confidence,.0,1)+.4*clamp(event.intensity,.0,1);
  return round(clamp(.7*(quality/events.length)+.3*Math.sqrt(clamp(events.length/expected,.0,1))));
 }
 function cappedEstimate(event){return finite(event?.salienceCap)&&event.salienceCap<=.51;}
 function contextFor(events,duration){
  const select=predicate=>events.filter(predicate);
  const trusted=event=>!cappedEstimate(event);
  const vocal=evidence(select(event=>event.source==='vocals'),6);
  const bass=evidence(select(event=>event.source==='bass'),6);
  // Low-trust mix estimates may be displayed as secondary evidence, but cannot
  // rewrite the song-level priority profile or promote themselves through it.
  const rhythm=evidence(select(event=>trusted(event)&&(event.source==='rhythm'||event.source==='drums')),16);
  const percussion=evidence(select(event=>trusted(event)&&(event.source==='drums'||event.type==='impact'||event.type==='onset')),8);
  const structural=evidence(select(event=>event.source==='structure'||event.type==='section'||event.type==='phrase'),2);
  const density=round(events.length/duration),rhythmicEvidence=Math.max(rhythm,percussion),strongest=Math.max(vocal,bass,rhythmicEvidence);
  let profile='balanced';
  if(density<.12&&strongest<.58)profile='sparse';
  else if(vocal>=.65&&vocal>=rhythmicEvidence*.85&&vocal>=bass*.95)profile='vocal-led';
  else if(bass>=.65&&bass>=vocal*1.10&&bass>=rhythmicEvidence*.78)profile='low-end-led';
  else if(rhythmicEvidence>=.64&&rhythmicEvidence>=vocal*1.12)profile='rhythm-led';
  return {profile,evidence:{vocal,bass,rhythm,percussion,structural},eventDensity:density,sourcePriorities:{...priorities[profile]},weights:{...weights[profile]}};
 }
 function structuralFactor(event){
  if(event.type==='section')return 1;
  if(event.type==='phrase')return .78;
  if(Number.isInteger(event.structure?.phraseIndex)&&event.structure.phraseIndex>=0)return .64;
  if(Number.isInteger(event.structure?.sectionIndex)&&event.structure.sectionIndex>=0)return .38;
  return 0;
 }
 function rhythmicFactor(event){
  if(event.type==='downbeat')return 1;
  if(event.type==='beat')return .66;
  if(event.type==='impact')return .78;
  if(event.type==='onset')return .54;
  if(event.source==='drums')return .72;
  if(event.source==='rhythm')return .62;
  const position=Number(event.rhythm?.barPosition);
  if(position===1)return .92;
  if(Number.isFinite(position)&&position>0)return .60;
  if(finite(event.rhythm?.beatTime)&&Math.abs(event.rhythm.beatTime-event.time)<=.06)return .66;
  return .16;
 }
 function transitionFactor(event,sectionTimes){
  if(event.type==='section')return 1;
  if(sectionTimes.some(time=>Math.abs(time-event.time)<=.08))return .94;
  return event.type==='phrase'?.52:0;
 }
 function recurrenceFactor(event){
  if(event.recurrenceGroup===undefined||event.recurrenceGroup===null)return .50;
  const repetition=Number(event.repetitionIndex);
  if(!Number.isFinite(repetition))return .56;
  return clamp(.82-Math.min(5,Math.max(0,repetition))*.10,.30,.82);
 }
 function topDrivers(factors,profileWeights){
  return Object.keys(factors).map(key=>({key,value:round(factors[key]*profileWeights[key])})).sort((left,right)=>right.value-left.value||compareText(left.key,right.key)).slice(0,3).map(item=>item.key);
 }
 function build(timeline){
  const check=validTimeline(timeline);if(!check.valid)throw Error('Music salience requires a valid semantic timeline: '+check.errors.join('; ').slice(0,512));
  const context=contextFor(timeline.events,timeline.duration),sectionTimes=timeline.events.filter(event=>event.type==='section').map(event=>event.time),entries=[];
  for(const event of timeline.events){
   const factors={
    baseline:clamp(event.salience),confidence:clamp(event.confidence),intensity:clamp(event.intensity),structural:structuralFactor(event),rhythmic:rhythmicFactor(event),transition:transitionFactor(event,sectionTimes),crossStem:clamp(event.relationships?.crossStemAgreement),recurrence:recurrenceFactor(event),sourcePriority:clamp(context.sourcePriorities[event.source]??.58)
   };
   let score=0;for(const key of Object.keys(factors))score+=factors[key]*context.weights[key];
   score=round(clamp(score));if(cappedEstimate(event))score=Math.min(score,round(clamp(event.salienceCap)));entries.push({id:event.id,time:event.time,score,tier:tierFor(score),drivers:topDrivers(factors,context.weights)});
  }
  const ranked=entries.slice().sort((left,right)=>right.score-left.score||left.time-right.time||compareText(left.id,right.id));
  for(let index=0;index<ranked.length;index++)ranked[index].rank=index+1;
  const byId=new Map(ranked.map(entry=>[entry.id,entry])),countByTier={micro:0,secondary:0,primary:0,phrase:0,structural:0,climax:0};
  const events=timeline.events.map(event=>{const entry=byId.get(event.id),value={id:entry.id,score:entry.score,tier:entry.tier,rank:entry.rank};countByTier[value.tier]++;return value;});
  const highlights=ranked.slice(0,MAX_HIGHLIGHTS).map(entry=>({id:entry.id,score:entry.score,tier:entry.tier,rank:entry.rank,drivers:entry.drivers}));
  return {schemaVersion:SCHEMA_VERSION,engineVersion:ENGINE_VERSION,timelineSchemaVersion:timeline.schemaVersion,timelineFingerprint:timelineFingerprint(timeline),clock:timeline.clock,duration:timeline.duration,events,summary:{eventCount:events.length,countByTier,context,topEventIds:highlights.map(entry=>entry.id),highlights}};
 }
 function validate(salience,timeline){
  const errors=[];
  if(!salience||salience.schemaVersion!==SCHEMA_VERSION||salience.engineVersion!==ENGINE_VERSION||!Number.isInteger(salience.timelineSchemaVersion)||typeof salience.timelineFingerprint!=='string'||!/^[0-9a-f]{8}$/.test(salience.timelineFingerprint)||!finite(salience.duration)||salience.duration<=0||!Array.isArray(salience.events)||!salience.summary||typeof salience.summary!=='object')errors.push('Invalid music salience envelope.');
  let expectedIds=null;
  if(timeline!==undefined){const timelineCheck=validTimeline(timeline);if(!timelineCheck.valid)errors.push('Invalid linked semantic timeline.');else{expectedIds=timeline.events.map(event=>event.id);if(salience?.timelineSchemaVersion!==timeline.schemaVersion||salience?.clock!==timeline.clock||salience?.duration!==timeline.duration||salience?.timelineFingerprint!==timelineFingerprint(timeline))errors.push('Music salience does not match semantic timeline.');}}
  const ids=new Set(),ranks=new Set(),counts={micro:0,secondary:0,primary:0,phrase:0,structural:0,climax:0};
  for(let index=0;index<(salience?.events||[]).length;index++){
   const event=salience.events[index];
   if(!event||typeof event.id!=='string'||!event.id||ids.has(event.id))errors.push('Duplicate or missing salience event id.');ids.add(event?.id);
   if(!finite(event?.score)||event.score<0||event.score>1||tierFor(event.score)!==event.tier)errors.push('Invalid salience score or tier.');
   if(!Number.isInteger(event?.rank)||event.rank<1||ranks.has(event.rank))errors.push('Invalid salience rank.');ranks.add(event?.rank);
   if(Object.prototype.hasOwnProperty.call(counts,event?.tier))counts[event.tier]++;else errors.push('Invalid salience tier.');
   if(expectedIds&&event?.id!==expectedIds[index])errors.push('Salience event order does not match semantic timeline.');
  }
  for(let rank=1;rank<=ranks.size;rank++)if(!ranks.has(rank))errors.push('Non-contiguous salience ranks.');
  const summary=salience?.summary,context=summary?.context;
  if(!Number.isInteger(summary?.eventCount)||summary.eventCount!==(salience?.events||[]).length||!summary.countByTier||Object.keys(counts).some(key=>summary.countByTier[key]!==counts[key]))errors.push('Invalid salience summary counts.');
  if(!context||!profiles.has(context.profile)||!context.evidence||!finite(context.eventDensity)||!context.sourcePriorities||!context.weights)errors.push('Invalid salience context.');
  else{
   for(const key of ['vocal','bass','rhythm','percussion','structural'])if(!finite(context.evidence[key])||context.evidence[key]<0||context.evidence[key]>1)errors.push('Invalid salience evidence.');
   let total=0;for(const key of Object.keys(weights[context.profile])){if(!finite(context.weights[key])||context.weights[key]<0)errors.push('Invalid salience weights.');total+=context.weights[key];}
   for(const key of ['vocals','bass','rhythm','drums','mix','structure'])if(!finite(context.sourcePriorities[key])||context.sourcePriorities[key]<0||context.sourcePriorities[key]>1)errors.push('Invalid salience source priorities.');
   if(Math.abs(total-1)>1e-6)errors.push('Salience weights must sum to one.');
  }
  const highlights=summary?.highlights,topEventIds=summary?.topEventIds;
  if(!Array.isArray(highlights)||highlights.length>MAX_HIGHLIGHTS||!Array.isArray(topEventIds)||topEventIds.length!==highlights.length)errors.push('Invalid salience highlights.');
  else for(let index=0;index<highlights.length;index++){const highlight=highlights[index],event=(salience.events||[]).find(value=>value.id===highlight?.id);if(!event||highlight.id!==topEventIds[index]||highlight.score!==event.score||highlight.tier!==event.tier||highlight.rank!==event.rank||!Array.isArray(highlight.drivers)||highlight.drivers.some(driver=>typeof driver!=='string'))errors.push('Invalid salience highlight.');}
  return {valid:errors.length===0,errors};
 }
 const api={build,validate,version:ENGINE_VERSION};root.LightForgeMusicSalience=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof self!=='undefined'?self:globalThis);
