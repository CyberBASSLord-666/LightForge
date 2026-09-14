/* LightForge - opt-in recurrence motif evolution bridge.
 *
 * This module never discovers recurrence. It consumes a caller-supplied
 * recurrence sidecar only after the recurrence contract validates it against
 * the exact semantic timeline and captured evidence.
 */
(function(root){
  'use strict';
  const RECURRENCE=root.LightForgeRecurrence||(typeof require==='function'?require('../analysis/recurrence.js'):null);
  const MAX_ITEMS=512;
  const PHASE_VARIANT=Object.freeze({establish:0,repeat:1,develop:2,escalate:3,release:4});
  const PHASE_INTENSITY=Object.freeze({establish:0,repeat:.01,develop:.03,escalate:.06,release:-.045});
  const finite=value=>typeof value==='number'&&Number.isFinite(value);
  const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
  const round=value=>Math.round(value*1000000)/1000000;
  const own=(value,key)=>!!value&&Object.prototype.hasOwnProperty.call(value,key);

  function sceneSeed(seed,key){
    let value=seed>>>0;
    const text=String(key);
    for(let index=0;index<text.length;index++)value=Math.imul(value^text.charCodeAt(index),16777619)>>>0;
    return value>>>0;
  }
  function spanKey(start,end){return String(round(start))+'|'+String(round(end));}
  function validEvolution(value){
    return !!value&&own(PHASE_VARIANT,value.phase)&&finite(value.energyDelta)&&value.energyDelta>=-1&&value.energyDelta<=1&&finite(value.relativeEnergy)&&value.relativeEnergy>=0&&value.relativeEnergy<=1&&finite(value.variation)&&value.variation>=0&&value.variation<=.85&&value.requiresChoreographyOptIn===true;
  }
  function inactive(scenes,requested,reason,details={}){
    return {scenes:scenes.slice(),diagnostics:{schemaVersion:1,requested:requested===true,active:false,reason,...details,
      scope:'No motif is inferred here. A caller must supply a recurrence sidecar that validates against the exact semantic timeline and recurrence evidence.'}};
  }
  function validContainer(value,limit){return Array.isArray(value)&&value.length<=limit;}

  function resolve(options={}){
    const scenes=Array.isArray(options.scenes)?options.scenes:[];
    const sections=Array.isArray(options.sections)?options.sections:null;
    const requested=options.requested===true;
    if(!requested)return inactive(scenes,false,'disabled');
    if(!sections||sections.length!==scenes.length)return inactive(scenes,true,'section-scene-contract-invalid');
    if(!RECURRENCE||typeof RECURRENCE.validate!=='function')return inactive(scenes,true,'recurrence-validator-unavailable');
    const music=options.music&&typeof options.music==='object'?options.music:null;
    const timeline=music&&music.semanticTimeline,evidence=music&&music.recurrenceEvidence,sidecar=music&&music.recurrenceSidecar;
    if(!timeline)return inactive(scenes,true,'semantic-timeline-missing');
    if(!evidence)return inactive(scenes,true,'recurrence-evidence-missing');
    if(!sidecar)return inactive(scenes,true,'recurrence-sidecar-missing');
    if(!validContainer(sidecar.motifs,MAX_ITEMS)||!validContainer(sidecar.assignments,MAX_ITEMS))return inactive(scenes,true,'recurrence-sidecar-bounds-invalid');
    let validation;
    try{validation=RECURRENCE.validate(sidecar,timeline,evidence);}catch(_){return inactive(scenes,true,'recurrence-sidecar-validation-error');}
    if(!validation||validation.valid!==true)return inactive(scenes,true,'recurrence-sidecar-binding-invalid');

    const evidenceById=new Map();
    for(const section of evidence.sections||[])if(section&&typeof section.sectionId==='string'&&finite(section.start)&&finite(section.end))evidenceById.set(section.sectionId,section);
    const sectionsBySpan=new Map();
    for(let index=0;index<sections.length;index++){
      const section=sections[index];
      if(!section||!finite(section.start)||!finite(section.end)||section.end<=section.start)return inactive(scenes,true,'normalized-section-invalid');
      const key=spanKey(section.start,section.end);
      if(sectionsBySpan.has(key))return inactive(scenes,true,'normalized-section-span-ambiguous');
      sectionsBySpan.set(key,index);
    }

    const overrides=options.sectionOverrides&&typeof options.sectionOverrides==='object'?options.sectionOverrides:{};
    const assignmentsByIndex=new Map(),phaseCounts=Object.fromEntries(Object.keys(PHASE_VARIANT).map(phase=>[phase,0]));
    let unmappedSectionCount=0,lockedSectionCount=0;
    for(const assignment of sidecar.assignments){
      if(!assignment||typeof assignment.sectionId!=='string'||typeof assignment.motifId!=='string'||!Number.isInteger(assignment.repetitionIndex)||assignment.repetitionIndex<0||!validEvolution(assignment.evolution)){unmappedSectionCount++;continue;}
      const evidenceSection=evidenceById.get(assignment.sectionId);
      const index=evidenceSection&&sectionsBySpan.get(spanKey(evidenceSection.start,evidenceSection.end));
      if(index===undefined||assignmentsByIndex.has(index)){unmappedSectionCount++;continue;}
      const override=overrides[index];
      if(finite(override&&override.seed)){lockedSectionCount++;continue;}
      assignmentsByIndex.set(index,assignment);
    }
    if(!assignmentsByIndex.size)return inactive(scenes,true,'no-compatible-unlocked-assignments',{motifCount:sidecar.motifs.length,assignmentCount:sidecar.assignments.length,unmappedSectionCount,lockedSectionCount});

    const seed=finite(options.seed)?options.seed>>>0:0;
    const resolved=scenes.map((scene,index)=>{
      const assignment=assignmentsByIndex.get(index);
      if(!assignment)return scene;
      if(!scene||typeof scene!=='object')return scene;
      const evolution=assignment.evolution,phase=evolution.phase,motifSeed=sceneSeed(seed,'recurrence:'+assignment.motifId);
      const variationStep=Math.min(2,Math.floor(evolution.variation*3+1e-9));
      const baseVariant=motifSeed%6;
      const variant=(baseVariant+assignment.repetitionIndex+PHASE_VARIANT[phase]+variationStep)%6;
      const instanceSeed=sceneSeed(motifSeed,assignment.sectionId+'|'+assignment.repetitionIndex+'|'+phase+'|'+Math.round(evolution.variation*1000));
      const baseIntensity=finite(scene.intensity)?clamp(scene.intensity,0,1):.85;
      const override=overrides[index],intensityLocked=finite(override&&override.intensity);
      const requestedDelta=clamp(PHASE_INTENSITY[phase]+(evolution.relativeEnergy-.5)*.06+clamp(evolution.energyDelta,-.25,.25)*.12,-.12,.12);
      const intensity=intensityLocked?baseIntensity:round(clamp(baseIntensity+requestedDelta,0,1));
      phaseCounts[phase]++;
      return Object.assign({},scene,{seed:instanceSeed,variant,intensity,motifGroup:assignment.motifId,recurrenceMotifId:assignment.motifId,
        motifEvolution:{motifId:assignment.motifId,phase,repetitionIndex:assignment.repetitionIndex,variation:evolution.variation,energyDelta:evolution.energyDelta,relativeEnergy:evolution.relativeEnergy,baseVariant,variant,intensityDelta:round(intensity-baseIntensity),requiresChoreographyOptIn:true}});
    });
    return {scenes:resolved,diagnostics:{schemaVersion:1,requested:true,active:true,reason:null,validator:'LightForgeRecurrence.validate',timelineFingerprint:sidecar.timelineFingerprint,evidenceFingerprint:sidecar.evidenceFingerprint,motifCount:sidecar.motifs.length,assignmentCount:sidecar.assignments.length,appliedSectionCount:assignmentsByIndex.size,unmappedSectionCount,lockedSectionCount,phaseCounts,
      scope:'Opt-in motif evolution changes only deterministic section scene seed, variant, and bounded intensity. It does not infer motifs, create musical events, apply timing offsets, or bypass vehicle/collision validation.'}};
  }
  const api=Object.freeze({version:'1.0.0',resolve});
  root.MotifEvolution=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);

