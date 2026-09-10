/* Deterministic, confidence-aware musical event timeline. Never invents lyrics. */
(function(root){'use strict';
 const finite=x=>typeof x==='number'&&Number.isFinite(x);
 const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x));
 const round=x=>Math.round(x*1000000)/1000000;
 const sorted=(items,key='time')=>items.filter(Boolean).slice().sort((a,b)=>a[key]-b[key]||String(a.id||'').localeCompare(String(b.id||'')));
 const scalar=(value,fallback=0)=>clamp(finite(value)?value:fallback);
 const validSpan=(value,duration)=>value&&finite(value.start)&&finite(value.end)&&value.start>=0&&value.end>value.start&&value.end<=duration+1e-6;
 const validPoint=(value,duration)=>value&&finite(value.time)&&value.time>=0&&value.time<duration+1e-6;
 const typeWeight={section:.92,phrase:.68,downbeat:.72,beat:.38,impact:.70,onset:.28,vocal_phrase:.66,vocal_note:.55,vocal_accent:.76,bass_note:.58,bass_phrase:.64};
 function bassProvenance(music,item){
  const analysis=music?.bassAnalysis||{};
  // A vocal-separated accompaniment is still an instrument mixture. Isolation
  // is true only when a dedicated bass stem explicitly proves it.
  const instrumentSeparated=item?.instrumentSeparated===true||analysis.instrumentSeparated===true;
  const inputStem=item?.inputStem||analysis.inputStem||(analysis.source==='separated-accompaniment'?'accompaniment':null);
  const inputStemSeparated=item?.inputStemSeparated===true||analysis.inputStemSeparated===true||(analysis.source==='separated-accompaniment'&&analysis.sourceSeparated===true);
  return {instrumentSeparated,inputStem,inputStemSeparated};
 }
 function locate(spans,time){let low=0,high=spans.length-1;while(low<=high){const mid=(low+high)>>1,s=spans[mid];if(time<s.start)high=mid-1;else if(time>=s.end)low=mid+1;else return mid;}return -1;}
 function nearest(values,time){if(!values.length)return -1;let low=0,high=values.length-1;while(low<high){const mid=(low+high)>>1;if(values[mid]<time)low=mid+1;else high=mid;}const right=low,left=Math.max(0,right-1);return Math.abs(values[left]-time)<=Math.abs(values[right]-time)?left:right;}
 function tier(value){return value>=.90?'climax':value>=.76?'structural':value>=.60?'phrase':value>=.42?'primary':value>=.25?'secondary':'micro';}
 function build(music){
  const duration=finite(music?.duration)&&music.duration>0?music.duration:0;if(!duration)throw Error('Semantic timeline requires a positive duration.');
  const sections=sorted((music.sections||[]).filter(x=>validSpan(x,duration)),'start');
  const phrases=sorted((music.phrases||[]).filter(x=>validSpan(x,duration)),'start');
  const beats=Array.from(music.beats||[]).filter(t=>finite(t)&&t>=0&&t<duration).sort((a,b)=>a-b);
  const downbeats=new Set(Array.from(music.downbeats||[]).filter(t=>finite(t)&&t>=0&&t<duration).map(round));
  const details=new Map((music.beatDetails||[]).filter(x=>validPoint(x,duration)).map(x=>[round(x.time),x]));
  const events=[];let sequence=0;
  function add(type,time,durationValue,source,attributes={}){
   if(!finite(time)||time<0||time>duration||!finite(durationValue)||durationValue<0)return;
   const confidence=scalar(attributes.confidence,attributes.estimated===false?1:.5),intensity=scalar(attributes.strength,scalar(attributes.energy,.5));
   const sectionIndex=locate(sections,Math.min(time,Math.max(0,duration-1e-7))),phraseIndex=locate(phrases,Math.min(time,Math.max(0,duration-1e-7)));
   const beatIndex=nearest(beats,time),beatTime=beatIndex<0?null:beats[beatIndex],beatDetail=beatTime===null?null:details.get(round(beatTime));
   const structural = type === 'section' ? 1 : (type === 'phrase' ? 0.72 : ((sectionIndex >= 0 && Math.abs(time-sections[sectionIndex].start) <= 0.08) ? 0.82 : 0.28));
   const rhythmic = (type === 'downbeat' || type === 'beat' || type === 'impact' || type === 'onset') ? 1 : ((beatTime !== null && Math.abs(beatTime-time) <= 0.07) ? 0.7 : 0.15);
   const base=typeWeight[type]??.3;
   const salience=clamp(.34*base+.20*confidence+.17*intensity+.17*structural+.12*rhythmic);
   const event={id:'m'+String(sequence++).padStart(6,'0'),type,time:round(time),duration:round(Math.min(durationValue,Math.max(0,duration-time))),source,confidence,intensity,
    salience, tier:tier(salience),rhythm:{beatIndex:beatIndex<0?null:beatIndex,beatTime:beatTime===null?null:round(beatTime),barPosition:finite(beatDetail?.barPosition)?beatDetail.barPosition:null,localBpm:finite(beatDetail?.localBpm)?beatDetail.localBpm:null},
    structure:{sectionIndex:sectionIndex<0?null:sectionIndex,phraseIndex:phraseIndex<0?null:phraseIndex},relationships:{crossStemAgreement:0,coincidentEventIds:[]}};
   for(const key of ['kind','midi','frequency','articulation','recurrenceGroup','repetitionIndex','label','estimated','sourceSeparated','instrumentSeparated','inputStem','inputStemSeparated','manual'])if(attributes[key]!==undefined)event[key]=attributes[key];
   events.push(event);
  }
  sections.forEach((s,i)=>add('section',s.start,s.end-s.start,'structure',{confidence:finite(s.confidence)?s.confidence:1,energy:s.energy,kind:s.label,recurrenceGroup:s.recurrenceGroup,repetitionIndex:s.repetitionIndex,estimated:s.estimated!==false}));
  phrases.forEach(p=>add('phrase',p.start,p.end-p.start,'structure',{confidence:p.confidence,energy:p.energy,kind:p.kind,recurrenceGroup:p.recurrenceGroup,repetitionIndex:p.repetitionIndex,estimated:p.estimated!==false}));
  beats.forEach(t=>{const d=details.get(round(t)),isDown=downbeats.has(round(t));add(isDown?'downbeat':'beat',t,0,'rhythm',{confidence:d?.confidence??music.beatConfidence,strength:isDown?1:.5,estimated:true});});
  for(const impact of music.impacts||[])if(validPoint(impact,duration))add('impact',impact.time,0,'mix',{confidence:impact.confidence,strength:impact.strength,kind:impact.kind,estimated:impact.estimated!==false});
  for(const onset of music.onsets||[])if(validPoint(onset,duration))add('onset',onset.time,0,'mix',{confidence:onset.confidence,strength:onset.strength,kind:onset.band,estimated:onset.estimated!==false});
  const vocals=music.vocals||{};
  for(const phrase of vocals.phrases||[])if(validSpan(phrase,duration))add('vocal_phrase',phrase.start,phrase.end-phrase.start,'vocals',{confidence:phrase.confidence,strength:phrase.strength,kind:phrase.kind,midi:phrase.midi,sourceSeparated:phrase.sourceSeparated===true||vocals.sourceSeparated===true,estimated:phrase.estimated!==false});
  for(const note of vocals.notes||[])if(validSpan(note,duration))add('vocal_note',note.start,note.end-note.start,'vocals',{confidence:note.confidence,strength:note.strength,kind:note.kind,midi:note.midi,sourceSeparated:note.sourceSeparated===true||vocals.sourceSeparated===true,estimated:note.estimated!==false});
  for(const accent of vocals.accents||[])if(validPoint(accent,duration))add('vocal_accent',accent.time,0,'vocals',{confidence:accent.confidence,strength:accent.strength,kind:accent.kind,articulation:accent.articulation,sourceSeparated:accent.sourceSeparated===true||vocals.sourceSeparated===true,estimated:accent.estimated!==false});
  const bassAnalysis=music.bassAnalysis||{},bassSummaryProvenance=bassProvenance(music);
  for(const note of music.bassNotes||[])if(validSpan(note,duration)){const provenance=bassProvenance(music,note);add('bass_note',note.start,note.end-note.start,'bass',{confidence:note.confidence,strength:note.strength,midi:note.midi,frequency:note.frequency,sourceSeparated:provenance.instrumentSeparated,instrumentSeparated:provenance.instrumentSeparated,inputStem:provenance.inputStem,inputStemSeparated:provenance.inputStemSeparated,estimated:note.estimated!==false});}
  for(const phrase of bassAnalysis.phrases||[])if(validSpan(phrase,duration)){const provenance=bassProvenance(music,phrase);add('bass_phrase',phrase.start,phrase.end-phrase.start,'bass',{confidence:phrase.confidence,strength:phrase.strength,midi:phrase.midi,frequency:phrase.frequency,sourceSeparated:provenance.instrumentSeparated,instrumentSeparated:provenance.instrumentSeparated,inputStem:provenance.inputStem,inputStemSeparated:provenance.inputStemSeparated,estimated:phrase.estimated!==false});}
  events.sort((a,b)=>a.time-b.time||b.salience-a.salience||a.type.localeCompare(b.type));
  for(let i=0;i<events.length;i++){
   const current=events[i],related=[];for(let j=i-1;j>=0&&current.time-events[j].time<=.055;j--)related.push(events[j]);for(let j=i+1;j<events.length&&events[j].time-current.time<=.055;j++)related.push(events[j]);
   const stems=new Set(related.filter(x=>x.source!==current.source).map(x=>x.source));
   current.relationships.crossStemAgreement=clamp(stems.size/3);current.relationships.coincidentEventIds=related.filter(x=>x.source!==current.source).slice(0,8).map(x=>x.id);
   current.salience=clamp(current.salience+.12*current.relationships.crossStemAgreement);current.tier=tier(current.salience);
  }
  const countByTier={micro:0,secondary:0,primary:0,phrase:0,structural:0,climax:0};for(const event of events)countByTier[event.tier]++;
  return {schemaVersion:2,clock:'original-decoded-audio',duration,events,summary:{eventCount:events.length,countByTier,hasSeparatedVocals:vocals.sourceSeparated===true,hasSeparatedBass:bassSummaryProvenance.instrumentSeparated,hasSeparatedAccompaniment:bassSummaryProvenance.inputStem==='accompaniment'&&bassSummaryProvenance.inputStemSeparated,lyricsAligned:music.roleAnalysis?.lyricsAligned===true}};
 }
 function validate(timeline){const errors=[];if(!timeline||timeline.schemaVersion!==2||!finite(timeline.duration)||timeline.duration<=0||!Array.isArray(timeline.events))errors.push('Invalid semantic timeline envelope.');
  let prior=-1,ids=new Set();for(const event of timeline?.events||[]){if(!event||typeof event.id!=='string'||ids.has(event.id))errors.push('Duplicate or missing event id.');ids.add(event?.id);if(!finite(event.time)||event.time<0||event.time>timeline.duration||event.time<prior)errors.push('Invalid event order or time.');prior=event.time;if(!finite(event.salience)||event.salience<0||event.salience>1)errors.push('Invalid event salience.');}return {valid:errors.length===0,errors};}
 const api={build,validate};root.LightForgeSemanticTimeline=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof self!=='undefined'?self:globalThis);
