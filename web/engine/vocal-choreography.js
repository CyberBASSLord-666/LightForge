/*
 * LightForge — opt-in acoustic vocal choreography bridge.
 *
 * This module is intentionally a planning adapter, not a detector. It accepts
 * only the validated, separated-vocal sidecar produced by
 * LightForgeVocalSemantics and only a freshly recomputed exact link to the
 * current semantic timeline. It never reads audio, infers lyrics, creates
 * words, or invents a vocal event. When its proof cannot be reproduced it
 * returns an inactive strategy and the legacy planner remains untouched.
 */
(function(root){
  'use strict';
  const VERSION='1.0.0';
  const finite=value=>typeof value==='number'&&Number.isFinite(value);
  const clamp=(value,min=0,max=1)=>Math.max(min,Math.min(max,finite(value)?value:0));
  const round=value=>Math.round(value*1000000)/1000000;
  const near=(left,right,epsilon=1e-4)=>finite(left)&&finite(right)&&Math.abs(left-right)<=epsilon;
  const forbidden=/^(?:word|words|text|lyric|lyrics|phoneme|phonemes)$/i;
  const compare=(left,right)=>left===right?0:(left<right?-1:1);

  function canonical(value){
    if(value===null)return 'null';
    if(typeof value==='number')return finite(value)?JSON.stringify(value):'null';
    if(typeof value==='boolean'||typeof value==='string')return JSON.stringify(value);
    if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
    if(!value||typeof value!=='object')return JSON.stringify(null);
    return '{'+Object.keys(value).sort(compare).map(key=>JSON.stringify(key)+':'+canonical(value[key])).join(',')+'}';
  }
  function containsLinguisticField(value,seen=new Set()){
    if(!value||typeof value!=='object'||seen.has(value))return false;
    seen.add(value);
    for(const key of Object.keys(value)){
      if(forbidden.test(key)||containsLinguisticField(value[key],seen))return true;
    }
    return false;
  }
  function inactive(requested,reason,details={}){
    const report=Object.freeze({schemaVersion:1,requested:requested===true,active:false,reason,...details,
      scope:'No cues are added or removed while inactive. Acoustic vocal choreography requires a validated separated-vocal sidecar and an exact current semantic-timeline link.'});
    return Object.freeze({version:VERSION,active:false,classifyCandidate:candidate=>candidate,directionFor:()=>null,diagnostics:()=>report});
  }
  function resolveApi(override){
    if(override)return override;
    if(root.LightForgeVocalSemantics)return root.LightForgeVocalSemantics;
    if(typeof require==='function')try{return require('../analysis/vocal-semantics.js');}catch(_){return null;}
    return null;
  }
  function exactLink(sidecar,links,timeline,api){
    if(!links||links.schemaVersion!==1||links.clock!=='original-decoded-audio'||!finite(links.duration)||!near(links.duration,sidecar.duration,1e-6)||links.sidecarFingerprint!==sidecar.sourceFingerprint)return null;
    if(!timeline||timeline.clock!==links.clock||!finite(timeline.duration)||!near(timeline.duration,links.duration,1e-6))return null;
    let recomputed;
    try{recomputed=api.linkTimeline(sidecar,timeline);}catch(_){return null;}
    // The supplied receipt must be byte-for-byte canonical-equivalent to the
    // link generated from the current timeline. A matching fingerprint alone
    // would permit a removed or remapped event to slip through.
    return canonical(recomputed)===canonical(links)?recomputed:null;
  }
  function indexed(records,sidecarRecords){
    if(!Array.isArray(records)||!Array.isArray(sidecarRecords)||records.length!==sidecarRecords.length)return null;
    const source=new Map(sidecarRecords.map(value=>[value&&value.id,value]));
    const result=new Map(),eventIds=new Set();
    for(const record of records){
      if(!record||typeof record.semanticId!=='string'||typeof record.eventId!=='string'||result.has(record.semanticId)||eventIds.has(record.eventId)||!source.has(record.semanticId))return null;
      result.set(record.semanticId,{semantic:source.get(record.semanticId),eventId:record.eventId});
      eventIds.add(record.eventId);
    }
    return result;
  }
  function uniqueAt(values,time,key,offset){
    const matches=values.filter(value=>near(value.semantic[key]+offset,time));
    return matches.length===1?matches[0]:null;
  }
  function validPhrase(value){
    return value&&typeof value.id==='string'&&finite(value.start)&&finite(value.end)&&finite(value.onset)&&finite(value.release)&&value.start<=value.onset&&value.onset<=value.release&&value.release<=value.end&&finite(value.confidence)&&finite(value.intensity)&&['singing','speech','vocal'].includes(value.kind)&&value.linguistic===false;
  }
  function validArticulation(value){
    return value&&typeof value.id==='string'&&typeof value.phraseId==='string'&&finite(value.time)&&['onset','acoustic-articulation'].includes(value.role)&&typeof value.syllableLike==='boolean'&&['primary','secondary','light'].includes(value.stress)&&finite(value.stressConfidence)&&finite(value.confidence)&&finite(value.intensity)&&value.linguistic===false;
  }
  function validNote(value){
    return value&&typeof value.id==='string'&&typeof value.phraseId==='string'&&finite(value.start)&&finite(value.end)&&value.end>value.start&&finite(value.midi)&&['note','held-note'].includes(value.kind)&&finite(value.confidence)&&finite(value.intensity)&&value.linguistic===false;
  }
  function create(input,options={}){
    const requested=options.enabled===true;
    if(!requested)return inactive(false,'not-requested');
    const music=input&&input.music,normalized=input&&input.normalizedMusic,settings=input&&input.settings||{};
    if(!music||!normalized||!music.vocalSemantics||!music.vocalSemanticLinks||!music.semanticTimeline)return inactive(true,'vocal-semantics-unavailable');
    if(Array.isArray(settings.vocalRegions)&&settings.vocalRegions.length)return inactive(true,'vocal-evidence-edited');
    if(Array.isArray(normalized.musicCues)&&normalized.musicCues.some(cue=>cue&&cue.role==='vocals'))return inactive(true,'vocal-evidence-edited');
    const sidecar=music.vocalSemantics,links=music.vocalSemanticLinks,api=resolveApi(options.api);
    if(!api||typeof api.validate!=='function'||typeof api.linkTimeline!=='function')return inactive(true,'vocal-semantics-module-unavailable');
    if(!sidecar||sidecar.schemaVersion!==1||sidecar.clock!=='original-decoded-audio'||sidecar.source!=='separated-vocals'||sidecar.sourceSeparated!==true||sidecar.linguisticAlignment!==false||!finite(sidecar.duration)||sidecar.duration<=0||typeof sidecar.sourceFingerprint!=='string'||containsLinguisticField(sidecar))return inactive(true,'invalid-vocal-semantics');
    let validation;
    try{validation=api.validate(sidecar,{duration:music.duration,vocals:music.vocals});}catch(_){return inactive(true,'invalid-vocal-semantics');}
    if(!validation||validation.valid!==true)return inactive(true,'invalid-vocal-semantics');
    const current=exactLink(sidecar,links,music.semanticTimeline,api);
    if(!current)return inactive(true,'vocal-semantic-links-mismatch');
    if(!Array.isArray(sidecar.phrases)||!Array.isArray(sidecar.articulations)||!Array.isArray(sidecar.notes)||!sidecar.phrases.every(validPhrase)||!sidecar.articulations.every(validArticulation)||!sidecar.notes.every(validNote))return inactive(true,'invalid-vocal-semantics');
    const phraseIndex=indexed(current.phrases,sidecar.phrases),articulationIndex=indexed(current.articulations,sidecar.articulations),noteIndex=indexed(current.notes,sidecar.notes);
    if(!phraseIndex||!articulationIndex||!noteIndex)return inactive(true,'vocal-semantic-links-mismatch');
    const phrases=Array.from(phraseIndex.values()),articulations=Array.from(articulationIndex.values()),notes=Array.from(noteIndex.values());
    const phraseById=new Map(sidecar.phrases.map(value=>[value.id,value]));
    if(sidecar.articulations.some(value=>!phraseById.has(value.phraseId))||sidecar.notes.some(value=>!phraseById.has(value.phraseId)))return inactive(true,'invalid-vocal-semantics');
    const vocalOffset=finite(settings.vocalOffsetMs)?settings.vocalOffsetMs/1000:0;
    const observed={candidateEventIds:new Set(),primaryArticulationIds:new Set(),heldNoteIds:new Set(),phraseReleaseIds:new Set(),directionPhraseIds:new Set(),releaseTrimmedCandidateCount:0};
    const phraseFor=value=>value&&phraseById.get(value.phraseId)||null;
    function matched(candidate){
      if(!candidate||candidate.role!=='vocals')return null;
      if(candidate.articulation===true){
        const articulation=uniqueAt(articulations,candidate.sourceEventTime,'time',vocalOffset);
        return articulation?{type:'articulation',entry:articulation,phrase:phraseFor(articulation.semantic)}:null;
      }
      if(candidate.vocalNote===true){
        const note=uniqueAt(notes,candidate.sourceEventTime,'start',vocalOffset);
        return note?{type:'note',entry:note,phrase:phraseFor(note.semantic)}:null;
      }
      const phrase=uniqueAt(phrases,candidate.sourceStart,'start',vocalOffset);
      return phrase?{type:'phrase',entry:phrase,phrase:phrase.semantic}:null;
    }
    function directionFor(point){
      const phrase=uniqueAt(phrases,point&&point.sourceStart,'start',vocalOffset);
      const trajectory=phrase&&phrase.semantic&&phrase.semantic.pitchTrajectory;
      if(!phrase||!trajectory||trajectory.confidence<.65||phrase.semantic.confidence<.55||!['rising','falling'].includes(trajectory.movement))return null;
      const direction=trajectory.movement==='rising'?'right':'left';
      observed.directionPhraseIds.add(phrase.semantic.id);
      return Object.freeze({direction,side:direction==='right',phraseId:phrase.semantic.id,eventId:phrase.eventId,movement:trajectory.movement,confidence:round(Math.min(trajectory.confidence,phrase.semantic.confidence))});
    }
    function classifyCandidate(candidate){
      const match=matched(candidate);if(!match||!match.phrase)return candidate;
      const phrase=match.phrase,base=Object.assign({},candidate,{vocalSemanticEventId:match.entry.eventId,vocalSemanticId:match.entry.semantic.id,vocalPhraseId:phrase.id,vocalPhraseKind:phrase.kind,vocalSemanticConfidence:round(Math.min(clamp(phrase.confidence),clamp(match.entry.semantic.confidence)))});
      observed.candidateEventIds.add(match.entry.eventId);
      const trajectory=phrase.pitchTrajectory;
      if(trajectory&&trajectory.confidence>=.65&&['rising','falling'].includes(trajectory.movement))base.vocalPitchMovement=trajectory.movement;
      if(match.type==='articulation'){
        const articulation=match.entry.semantic,weight=clamp(Math.min(articulation.stressConfidence,articulation.confidence));
        const boost=articulation.stress==='primary'?round(5+6*weight):articulation.stress==='secondary'?round(2+3*weight):0;
        base.vocalAcousticArticulation=true;base.vocalStress=articulation.stress;base.vocalStressConfidence=round(weight);
        if(boost){base.priority=(finite(base.priority)?base.priority:0)+boost;base.strength=clamp(Math.max(finite(base.strength)?base.strength:0,articulation.intensity*.90));}
        if(articulation.stress==='primary')observed.primaryArticulationIds.add(articulation.id);
      }
      if(match.type==='note'){
        const note=match.entry.semantic;base.vocalNoteKind=note.kind;
        if(note.kind==='held-note'&&finite(base.start)&&finite(base.end)&&base.end-base.start>=.5){
          base.release=Math.max(finite(base.release)?base.release:0,round(Math.min(.5,(base.end-base.start)*.30)));
          base.vocalHeldNote=true;observed.heldNoteIds.add(note.id);
        }
      }
      // A measured release can end before the extractor's enclosing phrase span.
      // Trim only an existing phrase-scale cue that already covers it; this never
      // shifts an onset, creates a cue, or truncates a cue below the legal length.
      const expectedSourceEnd=phrase.end+vocalOffset;
      if(finite(base.sourceEnd)&&near(base.sourceEnd,expectedSourceEnd)&&finite(base.musicTime)&&finite(base.start)&&finite(base.end)){
        const desiredMusicEnd=phrase.release+vocalOffset,commandOffset=base.start-base.musicTime,desiredCommandEnd=desiredMusicEnd+commandOffset;
        if(desiredCommandEnd>=base.start+.10&&desiredCommandEnd<base.end-.02){
          base.end=round(desiredCommandEnd);base.release=Math.max(finite(base.release)?base.release:0,round(Math.min(.5,(base.end-base.start)*.30)));base.vocalPhraseRelease=round(desiredMusicEnd);base.vocalReleaseTrimmed=true;observed.phraseReleaseIds.add(phrase.id);observed.releaseTrimmedCandidateCount++;
        }
      }
      return base;
    }
    function diagnostics(){return Object.freeze({schemaVersion:1,requested:true,active:true,reason:null,clock:sidecar.clock,sidecarSchemaVersion:sidecar.schemaVersion,sidecarFingerprint:sidecar.sourceFingerprint,timelineFingerprint:current.timelineFingerprint,linked:{phrases:phrases.length,articulations:articulations.length,notes:notes.length},applied:{matchedEventCount:observed.candidateEventIds.size,primaryArticulationCount:observed.primaryArticulationIds.size,heldNoteCount:observed.heldNoteIds.size,phraseReleaseCount:observed.phraseReleaseIds.size,pitchDirectionPhraseCount:observed.directionPhraseIds.size,releaseTrimmedCandidateCount:observed.releaseTrimmedCandidateCount},scope:'Uses only linked acoustic articulation stress, held-note duration, measured phrase release, and pitch trajectory as bounded planning hints. It contains no lyrics, words, or phonemes and never creates a musical event.'});}
    return Object.freeze({version:VERSION,active:true,classifyCandidate,directionFor,diagnostics});
  }
  const api=Object.freeze({version:VERSION,create});
  root.VocalChoreography=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
