/* Review final FSEQ bytes against selected musical and perceptual targets.
 * This is a realization check, not a substitute for annotated MIR accuracy or
 * measured vehicle latency.  It deliberately keeps those sources separate. */
(function(root){
  'use strict';
  const PROFILE=root.VehicleProfile||(typeof require==='function'?require('./vehicle-profile.js'):null);
  const ATTACK_CODES=new Set([255,178,204,230]),MAX_EVENT_EVIDENCE=10000;
  const finite=value=>typeof value==='number'&&Number.isFinite(value);
  const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
  const key=target=>[target.role,target.cueId||'',Math.round((finite(target.time)?target.time:0)*1e6)].join(':');
  const number=value=>finite(value)?value:null;
  function percentile(values,ratio){
    if(!values.length)return null;
    const index=(values.length-1)*ratio,lo=Math.floor(index),hi=Math.ceil(index);
    return values[lo]===values[hi]?values[lo]:values[lo]+(values[hi]-values[lo])*(index-lo);
  }
  function distribution(values){
    const sorted=values.filter(finite).map(Math.abs).sort((a,b)=>a-b);
    if(!sorted.length)return {count:0,meanMs:null,medianMs:null,p90Ms:null,p95Ms:null,p99Ms:null,maxMs:null};
    const mean=sorted.reduce((sum,value)=>sum+value,0)/sorted.length;
    return {count:sorted.length,meanMs:mean,medianMs:percentile(sorted,.5),p90Ms:percentile(sorted,.9),p95Ms:percentile(sorted,.95),p99Ms:percentile(sorted,.99),maxMs:sorted[sorted.length-1]};
  }
  function outputMap(){return new Map((PROFILE&&PROFILE.outputs||[]).map(output=>[output.id,output]));}
  function frameValues(show,output,frame){
    if(!show||!output||!Array.isArray(output.channels)||!show.frames||!Number.isInteger(frame)||frame<0||frame>=show.frameCount-1)return [];
    return output.channels.map(channel=>({now:show.frames[frame*200+channel-1],before:frame?show.frames[(frame-1)*200+channel-1]:0}));
  }
  function frameState(show,output,frame,expectedValue){
    const values=frameValues(show,output,frame);
    if(!values.length)return {attack:false,active:false};
    const active=values.some(value=>value.now>0);
    const attack=finite(expectedValue)
      ?values.some(value=>value.now===expectedValue&&value.now!==value.before)
      :values.some(value=>ATTACK_CODES.has(value.now)&&value.now!==value.before);
    return {attack,active};
  }
  function manualAt(show,outputId,time){
    return (show&&show.settings&&Array.isArray(show.settings.manualCues)?show.settings.manualCues:[]).some(cue=>cue&&cue.outputId===outputId&&finite(cue.start)&&finite(cue.end)&&time>=cue.start-1e-7&&time<cue.end+1e-7);
  }
  function enabled(show,output){return !!(output&&output.available!==false&&!(show&&show.settings&&show.settings.outputEnabled&&show.settings.outputEnabled[output.id]===false));}
  function uniqueIds(ids){return Array.from(new Set((Array.isArray(ids)?ids:[]).filter(id=>typeof id==='string'&&id)));}
  function isHighSalience(target){
    return finite(target&&target.salience)?target.salience>=.7:['primary','phrase','structural','climax'].includes(target&&target.tier);
  }
  function targetLoss(show,byId,target,expected){
    const candidates=uniqueIds(target.candidateOutputIds);
    if(!candidates.length)return 'unrouted';
    const active=candidates.filter(id=>enabled(show,byId.get(id)));
    if(!active.length)return 'disabled';
    if(active.every(id=>manualAt(show,id,expected)))return 'manualOverride';
    return 'suppressed';
  }
  function movementKindMatches(target,event){
    const kind=String(target.kind||'').toLowerCase(),command=String(event.command||'').toLowerCase();
    if(kind.includes('dance'))return command==='dance';
    if(kind.includes('unfold')||kind.includes('prepare'))return command==='open';
    if(kind.includes('fold')||kind.includes('return'))return command==='close';
    return true;
  }
  function findMovement(show,target,step){
    const events=(show.movements||[]).filter(event=>event&&event.outputId===target.outputId&&!event.manual&&movementKindMatches(target,event));
    const matches=events.map(event=>{
      const intent=event.intent||{};
      const targetTime=finite(intent.targetTime)?intent.targetTime:target.time;
      return {event,distance:Math.abs(targetTime-target.time),semantic:movementKindMatches(target,event)?0:1};
    }).filter(match=>match.distance<=step/2+1e-7).sort((a,b)=>a.distance-b.distance||a.semantic-b.semantic||a.event.start-b.event.start||String(a.event.command).localeCompare(String(b.event.command)));
    return matches.length?matches[0].event:null;
  }
  function updateAggregate(aggregate,status,target){
    aggregate.selected++;
    if(Object.prototype.hasOwnProperty.call(aggregate,status))aggregate[status]++;
    else aggregate.suppressed++;
    if(status==='suppressed'){
      aggregate.collisionLoss++;
      if(isHighSalience(target))aggregate.highSalienceCollisionLoss++;
    }
  }
  function lossRates(aggregate){
    return {count:aggregate.collisionLoss,rate:aggregate.selected?aggregate.collisionLoss/aggregate.selected:null,highSalienceCount:aggregate.highSalienceCollisionLoss,highSalienceRate:aggregate.highSalienceSelected?aggregate.highSalienceCollisionLoss/aggregate.highSalienceSelected:null};
  }
  const nonNegativeInteger=value=>Number.isInteger(value)&&value>=0?value:0;
  const safeText=(value,max=160)=>typeof value==='string'?value.slice(0,max):null;
  const plainObject=value=>!!value&&typeof value==='object'&&!Array.isArray(value);
  function rescueRecord(value){
    if(!plainObject(value))return null;
    const outcome=value.outcome==='rescued'||value.outcome==='suppressed'?value.outcome:'unknown';
    return {
      groupId:safeText(value.groupId),eventType:safeText(value.eventType),
      preferredOutput:safeText(value.preferredOutput),chosenOutput:safeText(value.chosenOutput),
      chosenOutputs:uniqueIds(value.chosenOutputs).slice(0,16),
      time:finite(value.time)?value.time:null,salience:finite(value.salience)?clamp(value.salience,0,1):null,
      tier:['structural','climax'].includes(value.tier)?value.tier:'unknown',outcome,reason:safeText(value.reason,240)
    };
  }
  function highSalienceResolution(show){
    const lighting=show&&show.choreography&&show.choreography.lighting;
    const available=plainObject(lighting)&&(Object.prototype.hasOwnProperty.call(lighting,'rescuedCollisions')||Object.prototype.hasOwnProperty.call(lighting,'unresolvedHighSalienceCollisions'));
    const rescued=available?nonNegativeInteger(lighting.rescuedCollisions):0,unresolved=available?nonNegativeInteger(lighting.unresolvedHighSalienceCollisions):0;
    const records=[];
    if(available&&Array.isArray(lighting.collisionResolutions))for(const value of lighting.collisionResolutions.slice(0,128)){const record=rescueRecord(value);if(record)records.push(record);}
    const attempts=rescued+unresolved;
    return {
      available,source:available?'lighting-planner-high-salience-logical-groups':'not-available-in-this-show',
      attemptedHighSalienceCount:attempts,rescuedHighSalienceCount:rescued,unresolvedHighSalienceCount:unresolved,
      rescuedCollisions:rescued,unresolvedHighSalienceCollisions:unresolved,
      rescueRate:attempts?rescued/attempts:null,resolutionRecords:records,
      omittedResolutionRecords:available?nonNegativeInteger(lighting.collisionResolutionTruncated):0
    };
  }
  function calibrationProvenance(show,byId){
    const calibration=show&&show.settings&&show.settings.vehicleTimingCalibration;
    const base={schemaVersion:1,profileId:PROFILE&&PROFILE.id||null,profileVersion:PROFILE&&PROFILE.version||null,configured:false,calibrationId:null,configuredOutputIds:[],closureLeadAdjustedOutputIds:[],metadataOnlyOutputIds:[],outputs:[],source:'none',note:'No vehicle-response latency is inferred without an explicit calibration.'};
    if(calibration===undefined||calibration===null)return Object.assign({},base,{status:'unconfigured'});
    if(!plainObject(calibration)||typeof calibration.enabled!=='boolean')return Object.assign({},base,{status:'invalid-configuration',source:'show.settings.vehicleTimingCalibration'});
    if(!calibration.enabled)return Object.assign({},base,{status:'disabled',source:'show.settings.vehicleTimingCalibration'});
    const calibrationId=typeof calibration.calibrationId==='string'&&/^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$/.test(calibration.calibrationId)?calibration.calibrationId:null;
    const configuredOutputIds=plainObject(calibration.outputs)?Object.keys(calibration.outputs).filter(id=>byId.has(id)).sort():[];
    if(!calibrationId||!configuredOutputIds.length)return Object.assign({},base,{status:'invalid-configuration',source:'show.settings.vehicleTimingCalibration'});
    const movement=show&&show.choreography&&show.choreography.movement&&show.choreography.movement.perceptualTiming;
    const movementOutputs=movement&&plainObject(movement.outputs)?movement.outputs:{};
    const outputs=configuredOutputIds.map(outputId=>{
      const output=byId.get(outputId),row=plainObject(movementOutputs[outputId])?movementOutputs[outputId]:null,leadAdjusted=!!(row&&row.leadAdjusted===true);
      return {outputId,kind:output&&output.kind||null,leadAdjusted,travelEvidence:safeText(row&&row.travelEvidence,80)};
    });
    const closureLeadAdjustedOutputIds=outputs.filter(row=>row.kind==='closure'&&row.leadAdjusted).map(row=>row.outputId);
    const metadataOnlyOutputIds=outputs.filter(row=>!row.leadAdjusted).map(row=>row.outputId);
    return Object.assign({},base,{status:'explicit-user-configuration',configured:true,calibrationId,configuredOutputIds,closureLeadAdjustedOutputIds,metadataOnlyOutputIds,outputs,source:'show.settings.vehicleTimingCalibration',note:'Configured timing is user-supplied provenance, not independently verified vehicle latency.'});
  }
  function realizationEvidence(eventClass,target,desiredPerceptualTime,realizationStatus,commandTime,predictedPerceptualTime,source){
    const row={eventClass,desiredPerceptualTime,realizationStatus,collisionLoss:realizationStatus==='suppressed',source};
    if(finite(commandTime))row.commandTime=commandTime;
    if(finite(predictedPerceptualTime))row.predictedPerceptualTime=predictedPerceptualTime;
    if(finite(target&&target.salience))row.salience=clamp(target.salience,0,1);
    else if(target&&typeof target.tier==='string')row.tier=target.tier.slice(0,80);
    return row;
  }
  function review(show,targets,movementTargets=[]){
    const step=(show&&finite(show.stepMs)?show.stepMs:20)/1000,byId=outputMap();
    const events=new Map();
    for(const event of show.lightEvents||[])if(event&&event.role){
      const eventKey=key({role:event.role,cueId:event.cueId,time:event.sourceEventTime??event.sourceStart});
      const group=events.get(eventKey)||[];group.push(event);events.set(eventKey,group);
    }
    const roles={vocals:{selected:0,matched:0,suppressed:0,heldWithoutAttack:0},bass:{selected:0,matched:0,suppressed:0,heldWithoutAttack:0}};
    const targetAggregate={selected:0,matched:0,suppressed:0,heldWithoutAttack:0,manualOverride:0,disabled:0,unrouted:0,outsideExport:0,collisionLoss:0,highSalienceSelected:0,highSalienceCollisionLoss:0};
    const issues=[],manual=[],lightErrors=[],seen=new Set(),eventEvidence=[];let omittedEventEvidence=0;
    const recordEvidence=row=>{if(eventEvidence.length<MAX_EVENT_EVIDENCE)eventEvidence.push(row);else omittedEventEvidence++;};
    for(const target of targets||[]){
      if(!target||!roles[target.role]||!finite(target.time))continue;
      const targetKey=key(target);if(seen.has(targetKey))continue;seen.add(targetKey);
      const role=roles[target.role],expected=target.time+(finite(show.settings&&show.settings.offsetMs)?show.settings.offsetMs:0)/1000,frame=Math.round(expected/step);
      let status='suppressed',errorMs=null,output=null,actualCommandTime=null;
      for(const event of events.get(targetKey)||[]){
        const actual=Math.round(event.actualStart/step),candidate=byId.get(event.id);
        if(!candidate||Math.abs(actual*step-expected)>step/2+1e-7)continue;
        const state=frameState(show,candidate,actual);
        if(state.attack){status='matched';actualCommandTime=actual*step;errorMs=(actualCommandTime-expected)*1000;output=event.id;break;}
        if(state.active)status='heldWithoutAttack';
      }
      const realizationStatus=status==='suppressed'?(frame<0||frame>=show.frameCount-1?'outsideExport':targetLoss(show,byId,target,expected)):status;
      // Keep the v1 per-role and manual row vocabulary stable.  The new
      // realizationStatus carries the more precise cause without redefining a
      // manual override as a successful automatic musical attack.
      role.selected++;role[status]++;
      if(isHighSalience(target))targetAggregate.highSalienceSelected++;
      updateAggregate(targetAggregate,realizationStatus,target);
      if(errorMs!==null)lightErrors.push(errorMs);
      const row={role:target.role,time:target.time,end:number(target.end),kind:target.kind,cueId:target.cueId||null,status,realizationStatus,output,errorMs,desiredPerceptualTime:expected};
      recordEvidence(realizationEvidence(target.role,target,expected,realizationStatus,actualCommandTime,null,'sync-review-lighting'));
      if(target.cueId)manual.push(row);
      if(status!=='matched'&&issues.length<200)issues.push({...row,reason:realizationStatus==='outsideExport'?'Outside exportable frames':realizationStatus==='heldWithoutAttack'?'Output was already active':realizationStatus==='manualOverride'?'Manual output override':realizationStatus==='disabled'?'All eligible outputs are disabled':realizationStatus==='unrouted'?'No eligible output route was recorded':'No eligible final output attack'});
    }
    const mechanical={selected:0,matched:0,suppressed:0,heldWithoutAttack:0,manualOverride:0,disabled:0,unrouted:0,outsideExport:0,collisionLoss:0,highSalienceSelected:0,highSalienceCollisionLoss:0};
    const mechanicalIssues=[],commandErrors=[],perceptualErrors=[],movementSeen=new Set();
    for(const target of movementTargets||[]){
      if(!target||!target.outputId||!finite(target.time))continue;
      const targetKey=[target.outputId,target.kind||'',Math.round(target.time*1e6)].join(':');if(movementSeen.has(targetKey))continue;movementSeen.add(targetKey);
      const output=byId.get(target.outputId),event=findMovement(show,target,step);
      let status='suppressed',commandErrorMs=null,predictedPerceptualErrorMs=null,actualCommandTime=null,predictedPerceptualTime=null;
      if(event&&output){
        const frame=Math.round(event.start/step),state=frameState(show,output,frame,event.value);
        actualCommandTime=frame*step;
        if(state.attack){
          status='matched';commandErrorMs=(actualCommandTime-target.time)*1000;
          const intent=event.intent||{};
          // A command transition is observed in the final FSEQ, but it is not
          // evidence of when the physical actuator will be perceived.  Only
          // an explicitly calibrated planner intent may contribute an
          // estimated perceptual timestamp; in particular, a Dance command
          // must never be relabelled as its own perceptual arrival.
          const calibrated=plainObject(intent.perceptualTiming)&&typeof intent.perceptualTiming.calibrationId==='string'&&intent.perceptualTiming.calibrationId.length>0;
          if(calibrated)predictedPerceptualTime=finite(intent.estimatedArrival)?intent.estimatedArrival:finite(event.perceptualStart)?event.perceptualStart:null;
          if(predictedPerceptualTime!==null){predictedPerceptualErrorMs=(predictedPerceptualTime-target.time)*1000;perceptualErrors.push(predictedPerceptualErrorMs);}
          commandErrors.push(commandErrorMs);
        }else if(state.active)status='heldWithoutAttack';
      }
      if(status==='suppressed'){
        if(!enabled(show,output))status='disabled';
        else if(manualAt(show,target.outputId,target.time))status='manualOverride';
        else if(!output)status='unrouted';
      }
      if(isHighSalience(target))mechanical.highSalienceSelected++;
      updateAggregate(mechanical,status,target);
      recordEvidence(realizationEvidence('mechanical',target,target.time,status,actualCommandTime,predictedPerceptualTime,'sync-review-mechanical'));
      if(status!=='matched'&&mechanicalIssues.length<200)mechanicalIssues.push({outputId:target.outputId,time:target.time,kind:target.kind||null,status,reason:status==='manualOverride'?'Manual output override':status==='disabled'?'Output disabled':status==='unrouted'?'Unknown output':'No final mechanical command transition'});
    }
    const sortedLight=lightErrors.map(Math.abs).sort((a,b)=>a-b),selected=roles.vocals.selected+roles.bass.selected,matched=roles.vocals.matched+roles.bass.matched;
    const lightingCandidateCollisions=show&&show.choreography&&show.choreography.lighting&&Number.isFinite(show.choreography.lighting.suppressedCollisions)?show.choreography.lighting.suppressedCollisions:0;
    return {
      version:2,
      scope:'Final FSEQ realization against selected musical targets. Detection accuracy and physical vehicle latency require external ground truth or calibration and are not inferred here.',
      frameStepMs:show.stepMs,
      roles,
      selected,
      matched,
      coverage:selected?matched/selected:null,
      maxErrorMs:sortedLight.length?sortedLight[sortedLight.length-1]:null,
      medianErrorMs:sortedLight.length?percentile(sortedLight,.5):null,
      timing:{command:{lighting:distribution(lightErrors),mechanical:distribution(commandErrors)},predictedPerceptual:{lighting:null,mechanical:distribution(perceptualErrors)}},
      collision:{targetLoss:lossRates(targetAggregate),mechanicalLoss:lossRates(mechanical),candidateSuppressedCollisions:lightingCandidateCollisions,highSalienceResolution:highSalienceResolution(show)},
      calibrationProvenance:calibrationProvenance(show,byId),
      eventEvidence,
      omittedEventEvidence,
      targets:targetAggregate,
      mechanical,
      issues,
      omittedIssues:Math.max(0,selected-matched-issues.length),
      mechanicalIssues,
      omittedMechanicalIssues:Math.max(0,mechanical.selected-mechanical.matched-mechanicalIssues.length),
      manual
    };
  }
  const api={review};root.SyncReview=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
