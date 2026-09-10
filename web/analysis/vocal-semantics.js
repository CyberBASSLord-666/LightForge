/*
 * Normalized acoustic vocal semantics.
 *
 * This is deliberately a zero-inference sidecar: it only normalizes the
 * already accepted separated-vocal phrase, note and accent evidence from
 * LightForgeVocalDetail/GAME.  It never reads PCM, never runs a model, and
 * never creates linguistic content.  "syllableLike" means an existing acoustic
 * articulation marker, not a recognised syllable, phoneme, or word.
 */
(function(root){'use strict';
 const SCHEMA_VERSION=1,ENGINE_VERSION='1.0.1',SOURCE='separated-vocals';
 const finite=value=>typeof value==='number'&&Number.isFinite(value);
 const clamp=(value,min=0,max=1)=>Math.max(min,Math.min(max,finite(value)?value:0));
 const round=value=>Math.round(value*1000000)/1000000;
 const near=(left,right,epsilon=1e-6)=>Math.abs(left-right)<=epsilon;
 const span=(value,duration)=>value&&finite(value.start)&&finite(value.end)&&value.start>=0&&value.end>value.start&&value.end<=duration+1e-6;
 const point=(value,duration)=>value&&finite(value.time)&&value.time>=0&&value.time<=duration+1e-6;
 const phraseKinds=new Set(['singing','speech','vocal']);
 const accentKinds=new Set(['entrance','syllabic-accent']);
 const noteKinds=new Set(['note','held-note']);
 const forbidden=/^(?:word|words|text|lyric|lyrics|phoneme|phonemes)$/i;
 const safeKind=value=>phraseKinds.has(value)?value:'vocal';
 const id=(prefix,index)=>prefix+String(index).padStart(4,'0');
 const compare=(left,right)=>left===right?0:(left<right?-1:1);
 const sortSpans=items=>items.slice().sort((left,right)=>left.start-right.start||left.end-right.end||compare(left.kind||'',right.kind||'')||left.index-right.index);
 const sortPoints=items=>items.slice().sort((left,right)=>left.time-right.time||compare(left.kind||'',right.kind||'')||left.index-right.index);
 function median(values){
  if(!values.length)return 0;
  const copy=values.slice().sort((left,right)=>left-right),middle=(copy.length-1)/2;
  return middle%1?(copy[Math.floor(middle)]+copy[Math.ceil(middle)])/2:copy[middle];
 }
 function weightedMean(values){
  let total=0,weight=0;for(const value of values){const w=Math.max(1e-6,value.weight||1);total+=value.value*w;weight+=w;}return weight?total/weight:0;
 }
 function hash(values){
  // Two independent 32-bit lanes give a compact deterministic 64-bit binding
  // without making this synchronous worker sidecar depend on WebCrypto.
  let first=2166136261,second=0x9e3779b9;
  for(const entry of values){const text=String(entry);for(let index=0;index<text.length;index++){const code=text.charCodeAt(index);first=Math.imul(first^code,16777619);second=Math.imul(second^(code+0x9e3779b9),0x85ebca6b);}first=Math.imul(first^255,16777619);second=Math.imul(second^0x85ebca6b,0xc2b2ae35);}
  const part=value=>('00000000'+(value>>>0).toString(16)).slice(-8);
  return part(first)+part(second);
 }
 function inputEnvelope(input){
  const duration=input?.duration,vocals=input?.vocals;
  if(!finite(duration)||duration<=0)throw Error('Vocal semantics requires a positive original-audio duration.');
  if(!vocals||typeof vocals!=='object'||vocals.sourceSeparated!==true)throw Error('Vocal semantics requires accepted separated-vocal evidence.');
  return {duration,vocals};
 }
 function sourcePhrases(vocals,duration){
  const values=[];
  for(const [index,value] of (Array.isArray(vocals.phrases)?vocals.phrases:[]).entries()){
   if(!span(value,duration)||!finite(value.confidence)||!finite(value.strength))continue;
   const start=round(value.start),end=round(value.end),release=finite(value.releaseTime)&&value.releaseTime>=value.start&&value.releaseTime<=value.end?round(value.releaseTime):end;
   values.push({index,start,end,release,kind:safeKind(value.kind),confidence:round(clamp(value.confidence)),intensity:round(clamp(value.strength)),peakTime:finite(value.peakTime)&&value.peakTime>=value.start&&value.peakTime<=value.end?round(value.peakTime):undefined,estimated:value.estimated!==false});
  }
  return sortSpans(values);
 }
 function sourceNotes(vocals,duration){
  const values=[];
  for(const [index,value] of (Array.isArray(vocals.notes)?vocals.notes:[]).entries()){
   if(!span(value,duration)||!finite(value.confidence)||!finite(value.strength)||!finite(value.midi)||value.midi<0||value.midi>127)continue;
   values.push({index,start:round(value.start),end:round(value.end),midi:round(value.midi),frequency:finite(value.frequency)&&value.frequency>0?round(value.frequency):undefined,confidence:round(clamp(value.confidence)),intensity:round(clamp(value.strength)),kind:noteKinds.has(value.type)?value.type:'note',estimated:value.estimated!==false});
  }
  return values.sort((left,right)=>left.start-right.start||left.end-right.end||left.midi-right.midi||left.index-right.index);
 }
 function sourceAccents(vocals,duration){
  const values=[];
  for(const [index,value] of (Array.isArray(vocals.accents)?vocals.accents:[]).entries()){
   if(!point(value,duration)||!accentKinds.has(value.kind)||!finite(value.confidence)||!finite(value.strength))continue;
   values.push({index,time:round(value.time),kind:value.kind,confidence:round(clamp(value.confidence)),intensity:round(clamp(value.strength)),estimated:value.estimated!==false});
  }
  return sortPoints(values);
 }
 function sourceFingerprint(input){
  const {duration,vocals}=inputEnvelope(input),values=['vocal-semantics',SCHEMA_VERSION,round(duration),vocals.source===SOURCE?1:0,vocals.sourceSeparated===true?1:0];
  for(const phrase of sourcePhrases(vocals,duration))values.push('p',phrase.start,phrase.end,phrase.release,phrase.kind,phrase.confidence,phrase.intensity,phrase.peakTime??'',phrase.estimated?1:0);
  for(const note of sourceNotes(vocals,duration))values.push('n',note.start,note.end,note.midi,note.frequency??'',note.confidence,note.intensity,note.kind,note.estimated?1:0);
  for(const accent of sourceAccents(vocals,duration))values.push('a',accent.time,accent.kind,accent.confidence,accent.intensity,accent.estimated?1:0);
  const contour=vocals.pitchContour;
  if(contour&&finite(contour.step)&&contour.step>0&&Array.isArray(contour.midi)&&Array.isArray(contour.confidence)){
   values.push('c',round(contour.step),contour.midi.length,contour.confidence.length);
   const count=Math.min(contour.midi.length,contour.confidence.length);
   for(let index=0;index<count;index++)if(finite(contour.midi[index])&&finite(contour.confidence[index])&&contour.midi[index]>0&&contour.confidence[index]>0)values.push(index,round(contour.midi[index]),round(clamp(contour.confidence[index])));
  }
  return 'vs1-'+hash(values);
 }
 function findPhrase(phrases,time){
  let selected=null;
  for(const phrase of phrases){if(time<phrase.onset-1e-6||time>phrase.release+1e-6)continue;if(!selected||phrase.confidence>selected.confidence||phrase.confidence===selected.confidence&&phrase.start<selected.start)selected=phrase;}
  return selected;
 }
 function overlap(left,right){return Math.max(0,Math.min(left.end,right.end)-Math.max(left.start,right.start));}
 function contourObservations(vocals,phrase){
  const contour=vocals.pitchContour;
  if(!contour||!finite(contour.step)||contour.step<=0||!Array.isArray(contour.midi)||!Array.isArray(contour.confidence))return [];
  const observations=[];
  for(let index=0;index<Math.min(contour.midi.length,contour.confidence.length);index++){
   const midi=contour.midi[index],confidence=contour.confidence[index],time=index*contour.step;
   if(time<phrase.onset||time>phrase.release||!finite(midi)||midi<=0||midi>127||!finite(confidence)||confidence<=0)continue;
   observations.push({time:round(time),midi:round(midi),confidence:round(clamp(confidence)),weight:Math.max(.01,clamp(confidence))});
  }
  return observations;
 }
 function trajectory(phrase,notes,vocals){
  let observations=notes.filter(note=>note.phraseId===phrase.id).map(note=>({time:round((note.start+note.end)/2),midi:note.midi,confidence:note.confidence,weight:Math.max(.01,note.end-note.start)*Math.max(.01,note.confidence)})),source='existing-note-output';
  if(!observations.length){observations=contourObservations(vocals,phrase);source='acoustic-pitch-contour';}
  if(!observations.length)return undefined;
  observations.sort((left,right)=>left.time-right.time||left.midi-right.midi);
  const start=median(observations.slice(0,Math.max(1,Math.ceil(observations.length*.25))).map(value=>value.midi)),end=median(observations.slice(Math.max(0,Math.floor(observations.length*.75))).map(value=>value.midi)),change=end-start;
  return {source,observations:observations.length,startMidi:round(start),endMidi:round(end),medianMidi:round(median(observations.map(value=>value.midi))),movement:change>.35?'rising':change<-.35?'falling':'stable',confidence:round(clamp(Math.min(phrase.confidence,weightedMean(observations.map(value=>({value:value.confidence,weight:value.weight}))))))};
 }
 function build(input){
  const {duration,vocals}=inputEnvelope(input),fingerprint=sourceFingerprint({duration,vocals}),phrases=[];
  for(const source of sourcePhrases(vocals,duration))phrases.push({id:id('vp',phrases.length),start:source.start,end:source.end,duration:round(source.end-source.start),onset:source.start,release:source.release,kind:source.kind,confidence:source.confidence,intensity:source.intensity,peakTime:source.peakTime,estimated:source.estimated,source:SOURCE,linguistic:false});
  const regions=[];let region;
  for(const phrase of phrases){
   if(!region||region.kind!==phrase.kind||phrase.onset-region.release>.28){region={id:id('vr',regions.length),start:phrase.onset,end:phrase.end,onset:phrase.onset,release:phrase.release,kind:phrase.kind,confidence:phrase.confidence,intensity:phrase.intensity,phraseIds:[],estimated:phrase.estimated,source:SOURCE,linguistic:false};regions.push(region);}
   region.end=Math.max(region.end,phrase.end);region.release=Math.max(region.release,phrase.release);region.confidence=Math.max(region.confidence,phrase.confidence);region.intensity=Math.max(region.intensity,phrase.intensity);region.estimated=region.estimated&&phrase.estimated;region.phraseIds.push(phrase.id);phrase.regionId=region.id;
  }
  for(const region of regions)region.duration=round(region.end-region.start);
  const notes=[];
  for(const source of sourceNotes(vocals,duration)){
   let selected=null,best=0;
   for(const phrase of phrases){if(phrase.kind==='speech')continue;const amount=overlap(source,{start:phrase.onset,end:phrase.release});if(amount>best+1e-9||near(amount,best)&&selected&&phrase.start<selected.start){best=amount;selected=phrase;}}
   if(!selected||best<=0)continue;
   notes.push({id:id('vn',notes.length),phraseId:selected.id,start:source.start,end:source.end,duration:round(source.end-source.start),midi:source.midi,frequency:source.frequency,confidence:source.confidence,intensity:source.intensity,kind:source.kind,estimated:source.estimated,source:SOURCE,pitchSource:'existing-note-output',linguistic:false});
  }
  for(const phrase of phrases){const value=phrase.kind==='speech'?undefined:trajectory(phrase,notes,vocals);if(value)phrase.pitchTrajectory=value;}
  const provisional=[];
  for(const source of sourceAccents(vocals,duration)){
   const phrase=findPhrase(phrases,source.time);if(!phrase)continue;
   provisional.push({phrase,source});
  }
  const maxima=new Map();for(const value of provisional)maxima.set(value.phrase.id,Math.max(maxima.get(value.phrase.id)||0,value.source.intensity));
  const articulations=[];
  for(const value of provisional){const {phrase,source}=value,maximum=maxima.get(phrase.id)||1,relative=clamp(source.intensity/Math.max(maximum,1e-6)),syllableLike=source.kind==='syllabic-accent',stress=relative>=.85?'primary':relative>=.55?'secondary':'light';
   articulations.push({id:id('va',articulations.length),phraseId:phrase.id,regionId:phrase.regionId,time:source.time,role:source.kind==='entrance'?'onset':'acoustic-articulation',syllableLike,stress,stressConfidence:round(clamp(Math.min(phrase.confidence,source.confidence)*(.65+.35*relative))),confidence:source.confidence,intensity:source.intensity,estimated:source.estimated,source:SOURCE,linguistic:false});
  }
  const summary={regionCount:regions.length,phraseCount:phrases.length,articulationCount:articulations.length,syllableLikeCount:articulations.filter(value=>value.syllableLike).length,noteCount:notes.length,pitchedPhraseCount:phrases.filter(value=>value.pitchTrajectory).length,spokenPhraseCount:phrases.filter(value=>value.kind==='speech').length,linguisticContent:false};
  const sidecar={schemaVersion:SCHEMA_VERSION,engineVersion:ENGINE_VERSION,clock:'original-decoded-audio',duration:round(duration),source:SOURCE,sourceSeparated:true,linguisticAlignment:false,sourceFingerprint:fingerprint,cacheIdentity:{stage:'vocal-semantics',schemaVersion:SCHEMA_VERSION,engineVersion:ENGINE_VERSION,sourceFingerprint:fingerprint},regions,phrases,articulations,notes,summary};
  const check=validate(sidecar,{duration,vocals});if(!check.valid)throw Error('Built invalid vocal semantic sidecar: '+check.errors.join('; '));
  return sidecar;
 }
 function hasForbidden(value,seen=new Set()){
  if(!value||typeof value!=='object'||seen.has(value))return false;seen.add(value);
  for(const key of Object.keys(value)){if(forbidden.test(key))return true;if(hasForbidden(value[key],seen))return true;}
  return false;
 }
 function validate(sidecar,input){
  const errors=[];
  if(!sidecar||sidecar.schemaVersion!==SCHEMA_VERSION||sidecar.engineVersion!==ENGINE_VERSION||sidecar.clock!=='original-decoded-audio'||sidecar.source!==SOURCE||sidecar.sourceSeparated!==true||sidecar.linguisticAlignment!==false||!finite(sidecar.duration)||sidecar.duration<=0||typeof sidecar.sourceFingerprint!=='string'||!/^vs1-[0-9a-f]{16}$/.test(sidecar.sourceFingerprint)||!sidecar.cacheIdentity||sidecar.cacheIdentity.stage!=='vocal-semantics'||sidecar.cacheIdentity.schemaVersion!==SCHEMA_VERSION||sidecar.cacheIdentity.engineVersion!==ENGINE_VERSION||sidecar.cacheIdentity.sourceFingerprint!==sidecar.sourceFingerprint||!Array.isArray(sidecar.regions)||!Array.isArray(sidecar.phrases)||!Array.isArray(sidecar.articulations)||!Array.isArray(sidecar.notes)||!sidecar.summary)errors.push('Invalid vocal semantic sidecar envelope.');
  if(hasForbidden(sidecar))errors.push('Vocal semantic sidecar contains prohibited linguistic content.');
  const phraseIds=new Set(),regionIds=new Set(),noteIds=new Set(),articulationIds=new Set(),regionsById=new Map();
  for(const region of sidecar?.regions||[]){
   if(!region||typeof region.id!=='string'||regionIds.has(region.id)||!span(region,sidecar.duration)||!near(region.onset,region.start)||!finite(region.release)||region.release<region.onset||region.release>region.end||!near(region.duration,region.end-region.start)||!phraseKinds.has(region.kind)||!finite(region.confidence)||region.confidence<0||region.confidence>1||!finite(region.intensity)||region.intensity<0||region.intensity>1||region.source!==SOURCE||region.linguistic!==false||!Array.isArray(region.phraseIds))errors.push('Invalid vocal region.');
   regionIds.add(region?.id);regionsById.set(region?.id,region);
  }
  for(const phrase of sidecar?.phrases||[]){
   if(!phrase||typeof phrase.id!=='string'||phraseIds.has(phrase.id)||!span(phrase,sidecar.duration)||!near(phrase.onset,phrase.start)||!finite(phrase.release)||phrase.release<phrase.onset||phrase.release>phrase.end||!near(phrase.duration,phrase.end-phrase.start)||!phraseKinds.has(phrase.kind)||!finite(phrase.confidence)||phrase.confidence<0||phrase.confidence>1||!finite(phrase.intensity)||phrase.intensity<0||phrase.intensity>1||phrase.source!==SOURCE||phrase.linguistic!==false||!regionsById.has(phrase.regionId))errors.push('Invalid vocal phrase.');
   if(phrase.pitchTrajectory!==undefined){const value=phrase.pitchTrajectory;if(!value||!['existing-note-output','acoustic-pitch-contour'].includes(value.source)||!Number.isInteger(value.observations)||value.observations<1||!finite(value.startMidi)||!finite(value.endMidi)||!finite(value.medianMidi)||!['rising','falling','stable'].includes(value.movement)||!finite(value.confidence)||value.confidence<0||value.confidence>1)errors.push('Invalid vocal pitch trajectory.');}
   phraseIds.add(phrase?.id);
  }
  const regionPhraseIds=[];for(const region of sidecar?.regions||[])for(const phraseId of region?.phraseIds||[]){regionPhraseIds.push(phraseId);if(!phraseIds.has(phraseId))errors.push('Vocal region links an unknown phrase.');}
  if(new Set(regionPhraseIds).size!==regionPhraseIds.length||regionPhraseIds.length!==phraseIds.size)errors.push('Vocal region links must partition phrases.');
  const phrasesById=new Map((sidecar?.phrases||[]).map(value=>[value.id,value]));
  for(const note of sidecar?.notes||[]){if(!note||typeof note.id!=='string'||noteIds.has(note.id)||!span(note,sidecar.duration)||!near(note.duration,note.end-note.start)||!phrasesById.has(note.phraseId)||!finite(note.midi)||note.midi<0||note.midi>127||note.frequency!==undefined&&(!finite(note.frequency)||note.frequency<=0)||!finite(note.confidence)||note.confidence<0||note.confidence>1||!finite(note.intensity)||note.intensity<0||note.intensity>1||!noteKinds.has(note.kind)||note.source!==SOURCE||note.pitchSource!=='existing-note-output'||note.linguistic!==false)errors.push('Invalid vocal note semantic.');noteIds.add(note?.id);}
  for(const articulation of sidecar?.articulations||[]){const phrase=phrasesById.get(articulation?.phraseId);if(!articulation||typeof articulation.id!=='string'||articulationIds.has(articulation.id)||!phrase||articulation.regionId!==phrase.regionId||!finite(articulation.time)||articulation.time<phrase.onset-1e-6||articulation.time>phrase.release+1e-6||!['onset','acoustic-articulation'].includes(articulation.role)||articulation.syllableLike!==(articulation.role==='acoustic-articulation')||!['primary','secondary','light'].includes(articulation.stress)||!finite(articulation.stressConfidence)||articulation.stressConfidence<0||articulation.stressConfidence>1||!finite(articulation.confidence)||articulation.confidence<0||articulation.confidence>1||!finite(articulation.intensity)||articulation.intensity<0||articulation.intensity>1||articulation.source!==SOURCE||articulation.linguistic!==false)errors.push('Invalid vocal articulation semantic.');articulationIds.add(articulation?.id);}
  const summary=sidecar?.summary;if(!summary||summary.regionCount!==(sidecar?.regions||[]).length||summary.phraseCount!==(sidecar?.phrases||[]).length||summary.articulationCount!==(sidecar?.articulations||[]).length||summary.syllableLikeCount!==(sidecar?.articulations||[]).filter(value=>value.syllableLike).length||summary.noteCount!==(sidecar?.notes||[]).length||summary.pitchedPhraseCount!==(sidecar?.phrases||[]).filter(value=>value.pitchTrajectory).length||summary.spokenPhraseCount!==(sidecar?.phrases||[]).filter(value=>value.kind==='speech').length||summary.linguisticContent!==false)errors.push('Invalid vocal semantic summary.');
  if(input!==undefined)try{const expected=inputEnvelope(input);if(!near(sidecar?.duration,expected.duration)||sidecar?.sourceFingerprint!==sourceFingerprint(expected))errors.push('Vocal semantic sidecar does not match current vocal evidence.');}catch(error){errors.push(String(error.message||error));}
  return {valid:errors.length===0,errors};
 }
 function canonicalTimelineTokens(value,tokens,seen=new Set()){
  if(value===null){tokens.push('null');return;}
  const type=typeof value;
  if(type==='string'){tokens.push('string',value);return;}
  if(type==='boolean'){tokens.push('boolean',value?1:0);return;}
  if(type==='number'){tokens.push('number',finite(value)?round(value):String(value));return;}
  if(type==='undefined'){tokens.push('undefined');return;}
  if(type==='bigint'){tokens.push('bigint',String(value));return;}
  if(type==='symbol'||type==='function')throw Error('Vocal semantic timeline link received a non-data timeline value.');
  if(seen.has(value))throw Error('Vocal semantic timeline link received a cyclic timeline.');
  seen.add(value);
  if(Array.isArray(value)){
   tokens.push('array',value.length);
   for(const item of value)canonicalTimelineTokens(item,tokens,seen);
  }else{
   const keys=Object.keys(value).sort(compare);
   tokens.push('object',keys.length);
   for(const key of keys){tokens.push('key',key);canonicalTimelineTokens(value[key],tokens,seen);}
  }
  seen.delete(value);
 }
 function timelineFingerprint(timeline){
  // Links bind the complete canonical timeline, not just their matching vocal
  // events. This includes salience caps and any future semantic fields so a
  // planner cannot reuse a link after a cap-aware timeline mutation.
  const values=[];canonicalTimelineTokens(timeline,values);return 'vt1-'+hash(values);
 }
 function linkTimeline(sidecar,timeline){
  const sidecarCheck=validate(sidecar);if(!sidecarCheck.valid)throw Error('Cannot link invalid vocal semantic sidecar: '+sidecarCheck.errors.join('; '));
  if(!timeline||!finite(timeline.duration)||!near(timeline.duration,sidecar.duration)||!Array.isArray(timeline.events))throw Error('Vocal semantic timeline link requires a matching semantic timeline.');
  let prior=-1;const ids=new Set();for(const event of timeline.events){if(!event||typeof event.id!=='string'||ids.has(event.id)||!finite(event.time)||event.time<prior||event.time>timeline.duration)throw Error('Vocal semantic timeline link received an invalid timeline.');ids.add(event.id);prior=event.time;}
  const used=new Set(),match=(type,time,duration,kind)=>{const value=timeline.events.find(event=>!used.has(event.id)&&event.type===type&&event.source==='vocals'&&near(event.time,time)&&near(event.duration,duration)&&(!kind||event.kind===kind));if(!value)throw Error('Vocal semantic sidecar cannot be linked to the current semantic timeline.');used.add(value.id);return value.id;};
  const phrases=sidecar.phrases.map(phrase=>({semanticId:phrase.id,eventId:match('vocal_phrase',phrase.start,phrase.duration,phrase.kind)}));
  const notes=sidecar.notes.map(note=>({semanticId:note.id,eventId:match('vocal_note',note.start,note.duration)}));
  const articulations=sidecar.articulations.map(articulation=>({semanticId:articulation.id,eventId:match('vocal_accent',articulation.time,0,articulation.role==='onset'?'entrance':'syllabic-accent')}));
  return {schemaVersion:1,clock:'original-decoded-audio',duration:sidecar.duration,sidecarFingerprint:sidecar.sourceFingerprint,timelineFingerprint:timelineFingerprint(timeline),phrases,notes,articulations};
 }
 const api={build,validate,sourceFingerprint,linkTimeline,version:ENGINE_VERSION};root.LightForgeVocalSemantics=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof self!=='undefined'?self:globalThis);
