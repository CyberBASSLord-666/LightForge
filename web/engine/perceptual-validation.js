/*
 * Bounded perceptual-validation sidecar.
 *
 * This report consumes explicit realization evidence.  It never treats an MIR
 * detector timestamp as ground truth, never estimates a vehicle response from
 * an uncalibrated light command, and never mutates a show or FSEQ frame.
 */
(function(root){
 'use strict';
 const VERSION=1,MAX_EVENTS=10000,MAX_CLASSES=32;
 const DEFAULT_CLASSES=Object.freeze(['vocals','bass','kick','snare','percussion','beat','downbeat','section','climax','mechanical']);
 const HIGH_TIERS=new Set(['primary','phrase','structural','climax']);
 const finite=value=>typeof value==='number'&&Number.isFinite(value);
 const clamp=(value,low=0,high=1)=>Math.max(low,Math.min(high,value));
 const round=value=>Math.round(value*1000000)/1000000;
 const stableObject=value=>value&&typeof value==='object'&&!Array.isArray(value);
 function percentile(values,ratio){
  if(!values.length)return null;
  const index=(values.length-1)*ratio,low=Math.floor(index),high=Math.ceil(index);
  return low===high?values[low]:values[low]+(values[high]-values[low])*(index-low);
 }
 function unavailable(reason,basis){return {state:'unavailable',basis,count:0,medianMs:null,p90Ms:null,p95Ms:null,p99Ms:null,maxMs:null,reason};}
 function timing(values,basis,state='available'){
  const sorted=values.filter(finite).map(Math.abs).sort((left,right)=>left-right);
  if(!sorted.length)return unavailable('No matched timing pairs with explicit '+basis+' evidence.',basis);
  return {state,basis,count:sorted.length,medianMs:round(percentile(sorted,.5)),p90Ms:round(percentile(sorted,.9)),p95Ms:round(percentile(sorted,.95)),p99Ms:round(percentile(sorted,.99)),maxMs:round(sorted[sorted.length-1])};
 }
 function unavailableCoverage(reason){return {state:'unavailable',selected:0,matched:0,coverage:null,reason};}
 function coverage(rows,selector=()=>true){
  const observed=rows.filter(row=>row.coverageObserved&&selector(row));
  if(!observed.length)return unavailableCoverage('No explicit realization status was supplied for this event class.');
  const matched=observed.filter(row=>row.matched).length;
  return {state:'available',selected:observed.length,matched,coverage:matched/observed.length};
 }
 function className(value){
  if(typeof value!=='string')return null;
  const normalized=value.trim().toLowerCase().replace(/[\s_]+/g,'-');
  if(!normalized||normalized.length>80)return null;
  return ({vocal:'vocals',voice:'vocals','vocal-phrase':'vocals','vocal-accent':'vocals',lowend:'bass','low-end':'bass',drums:'percussion',drum:'percussion',hihat:'percussion','hi-hat':'percussion',hat:'percussion','section-transition':'section',transition:'section',drop:'climax',arrival:'climax',mechanism:'mechanical'})[normalized]||normalized;
 }
 function status(value){
  if(typeof value!=='string')return null;
  const normalized=value.trim().toLowerCase();
  return ['matched','suppressed','heldwithoutattack','held-without-attack','manualoverride','manual-override','disabled','unrouted','outsideexport','outside-export','timed'].includes(normalized)?normalized.replace(/-/g,''):null;
 }
 function targetTime(event){
  for(const key of ['desiredPerceptualTime','targetPerceptualTime','targetTime','time'])if(finite(event[key]))return event[key];
  return null;
 }
 function commandTime(event){for(const key of ['commandTime','actualCommandTime','realizedCommandTime'])if(finite(event[key]))return event[key];return null;}
 function measuredPerceptualTime(event){
  if(finite(event.measuredPerceptualTime))return event.measuredPerceptualTime;
  return event.perceptualEvidence==='measured'&&finite(event.perceptualTime)?event.perceptualTime:null;
 }
 function predictedPerceptualTime(event){for(const key of ['predictedPerceptualTime','estimatedPerceptualTime'])if(finite(event[key]))return event[key];return null;}
 function highSalience(event){return finite(event.salience)?event.salience>=.7:HIGH_TIERS.has(String(event.tier||'').toLowerCase());}
 function salienceKnown(event){return finite(event.salience)||typeof event.tier==='string';}
 function normalize(event,index){
  if(!stableObject(event))return null;
  const eventClass=className(event.eventClass||event.class||event.role||event.type||event.kind);
  const target=targetTime(event);
  if(!eventClass||target===null)return null;
  const rowStatus=status(event.realizationStatus)||status(event.status),command=commandTime(event),measured=measuredPerceptualTime(event),predicted=predictedPerceptualTime(event);
  const matched=rowStatus==='matched',timed=rowStatus==='timed'||event.timingEvidence==='command';
  const collisionObserved=typeof event.collisionLoss==='boolean'||typeof event.collisionStatus==='string';
  return {index,eventClass,target,command,measured,predicted,status:rowStatus,coverageObserved:rowStatus!==null,matched,timed,commandUsable:matched||timed,perceptualUsable:matched||event.timingEvidence==='perceptual',high:highSalience(event),salienceKnown:salienceKnown(event),collisionObserved,collisionLoss:event.collisionLoss===true||event.collisionStatus==='lost',source:typeof event.source==='string'?event.source:null};
 }
 function collision(rows){
  const observed=rows.filter(row=>row.collisionObserved);
  if(!observed.length)return {state:'unavailable',selected:0,count:null,rate:null,highSalienceSelected:0,highSalienceCount:null,highSalienceRate:null,reason:'No explicit collision outcome was supplied for this event class.'};
  const count=observed.filter(row=>row.collisionLoss).length,high=observed.filter(row=>row.high),highCount=high.filter(row=>row.collisionLoss).length;
  return {state:'available',selected:observed.length,count,rate:count/observed.length,highSalienceSelected:high.length,highSalienceCount:highCount,highSalienceRate:high.length?highCount/high.length:null};
 }
 function classSummary(name,rows){
  const commandErrors=[],measuredErrors=[],predictedErrors=[];
  for(const row of rows){
   if(row.commandUsable&&row.command!==null)commandErrors.push((row.command-row.target)*1000);
   if(row.perceptualUsable&&row.measured!==null)measuredErrors.push((row.measured-row.target)*1000);
   if(row.perceptualUsable&&row.predicted!==null)predictedErrors.push((row.predicted-row.target)*1000);
  }
  const salienceRows=rows.filter(row=>row.salienceKnown),highRows=salienceRows.filter(row=>row.high);
  return {eventClass:name,eventEvidence:rows.length?{state:'available',count:rows.length}:{state:'unavailable',count:0,reason:'No explicit event evidence was supplied for this class.'},timing:{command:timing(commandErrors,'command timestamp minus intended perceptual target'),perceptual:timing(measuredErrors,'measured perceptual response minus intended target'),predictedPerceptual:timing(predictedErrors,'predicted perceptual response minus intended target','estimated')},coverage:coverage(rows),highSalienceCoverage:salienceRows.length?coverage(rows,row=>row.high):unavailableCoverage('No salience or tier evidence was supplied for this event class.'),collisionLoss:collision(rows)};
 }
 function syncCollision(sync){
  const target=sync&&sync.collision&&sync.collision.targetLoss,mechanical=sync&&sync.collision&&sync.collision.mechanicalLoss;
  const summarize=value=>value&&finite(value.count)&&finite(value.highSalienceCount)?{state:'available',count:value.count,rate:finite(value.rate)?value.rate:null,highSalienceCount:value.highSalienceCount,highSalienceRate:finite(value.highSalienceRate)?value.highSalienceRate:null}:{state:'unavailable',count:null,rate:null,highSalienceCount:null,highSalienceRate:null,reason:'No SyncReview collision evidence was supplied.'};
  return {lighting:summarize(target),mechanical:summarize(mechanical)};
 }
 function feasibility(quality){
  if(!quality||quality.validInput!==true)return {state:'unavailable',knownViolationCount:null,components:{},reason:'No valid choreography-quality report was supplied.'};
  const components={};
  const add=(name,source,key)=>{
   if(source&&source.assessed===true&&finite(source[key]))components[name]={state:'available',violationCount:source[key]};
   else components[name]={state:'unavailable',violationCount:null,reason:'This feasibility component was not assessed.'};
  };
  add('conflictingCommands',quality.conflictingCommands,'count');
  add('minimumDurations',quality.minimumDurations,'violationCount');
  add('repeatIntervals',quality.minimumDurations,'repeatIntervalViolationCount');
  add('actuatorOveruse',quality.actuatorOveruse,'overusedOutputCount');
  add('outputOveruse',quality.outputOveruse,'violationCount');
  const available=Object.values(components).filter(component=>component.state==='available'),unknown=Object.keys(components).filter(name=>components[name].state!=='available');
  if(!available.length)return {state:'unavailable',knownViolationCount:null,components,reason:'No feasibility component was assessed.'};
  return {state:unknown.length?'partial':'available',knownViolationCount:available.reduce((sum,component)=>sum+component.violationCount,0),components,unavailableComponents:unknown};
 }
 function evidenceSource(show,options){
  if(Array.isArray(options.events))return {events:options.events,source:'options.events'};
  if(Array.isArray(options.eventEvidence))return {events:options.eventEvidence,source:'options.eventEvidence'};
  const embedded=show&&show.choreography&&show.choreography.perceptualEventEvidence;
  return Array.isArray(embedded)?{events:embedded,source:'show.choreography.perceptualEventEvidence'}:{events:[],source:null};
 }
 function evaluate(show,options){
  options=stableObject(options)?options:{};
  const supplied=evidenceSource(show,options),raw=supplied.events,accepted=[];let invalid=0;
  for(let index=0;index<Math.min(raw.length,MAX_EVENTS);index++){
   const row=normalize(raw[index],index);if(row)accepted.push(row);else invalid++;
  }
  const classes=[],omittedClasses=new Set();
  for(const name of DEFAULT_CLASSES)classes.push(name);
  for(const row of accepted)if(!classes.includes(row.eventClass)){if(classes.length<MAX_CLASSES)classes.push(row.eventClass);else omittedClasses.add(row.eventClass);}
  const grouped=new Map(classes.map(name=>[name,[]]));for(const row of accepted)if(grouped.has(row.eventClass))grouped.get(row.eventClass).push(row);
  const perEventClass={};for(const name of classes)perEventClass[name]=classSummary(name,grouped.get(name));
  const quality=options.choreographyQuality||options.quality||show&&show.choreography&&show.choreography.quality||null;
  const sync=options.syncReview||options.synchronization||show&&show.synchronization||null;
  const aggregate=classSummary('all',accepted);
  return {version:VERSION,scope:'Read-only realization diagnostics from explicit command/perceptual, salience, collision and feasibility evidence. It does not establish detector accuracy, human perceptual quality, or physical vehicle latency without external ground truth/calibration.',eventEvidence:{state:supplied.source?'available':'unavailable',source:supplied.source,suppliedCount:raw.length,acceptedCount:accepted.length,invalidCount:invalid,omittedCount:Math.max(0,raw.length-MAX_EVENTS),maximumEvents:MAX_EVENTS,maximumClasses:MAX_CLASSES,omittedClassCount:omittedClasses.size},perEventClass,aggregate:{timing:aggregate.timing,coverage:aggregate.coverage,highSalienceCoverage:aggregate.highSalienceCoverage,collisionLoss:aggregate.collisionLoss},collision:{eventEvidence:aggregate.collisionLoss,syncReview:syncCollision(sync)},feasibility:feasibility(quality)};
 }
 const api={version:VERSION,evaluate,analyze:evaluate};
 root.PerceptualValidation=api;if(typeof module==='object'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
