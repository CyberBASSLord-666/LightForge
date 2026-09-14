/* LightForge choreography-quality sidecar.
 *
 * This module is deliberately read-only: it inspects finalized frame bytes and
 * optional planning metadata, but never changes a show, a plan, or FSEQ bytes.
 * Its figures are signal/plan diagnostics. They are not a substitute for human
 * review, music-event ground truth, or physical-vehicle measurement.
 */
(function(root) {
  'use strict';

  let DEFAULT_PROFILE=root.VehicleProfile||null;
  if(!DEFAULT_PROFILE&&typeof require==='function')try{DEFAULT_PROFILE=require('./vehicle-profile.js');}catch(_error){}

  const VERSION='1.0.0';
  const finite=value=>typeof value==='number'&&Number.isFinite(value);
  const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
  const unique=list=>Array.from(new Set(list));
  const number=value=>finite(value)?value:null;
  const positive=(value,fallback)=>finite(value)&&value>0?value:fallback;
  const sortNumeric=(a,b)=>a-b;

  function percentile(values,fraction){
    if(!values.length)return null;
    const index=(values.length-1)*fraction,low=Math.floor(index),high=Math.ceil(index);
    return low===high?values[low]:values[low]+(values[high]-values[low])*(index-low);
  }
  function distribution(values){
    const sorted=values.filter(finite).slice().sort(sortNumeric);
    if(!sorted.length)return {count:0,mean:null,median:null,p90:null,p95:null,p99:null,max:null};
    const mean=sorted.reduce((sum,value)=>sum+value,0)/sorted.length;
    return {count:sorted.length,mean,median:percentile(sorted,.5),p90:percentile(sorted,.9),p95:percentile(sorted,.95),p99:percentile(sorted,.99),max:sorted[sorted.length-1]};
  }
  function hash(value){
    let state=2166136261;
    for(let index=0;index<value.length;index++){
      state^=value.charCodeAt(index);
      state=Math.imul(state,16777619);
    }
    return (state>>>0).toString(16).padStart(8,'0');
  }
  function stableValue(value){
    if(value===undefined)return 'undefined';
    if(value===null)return 'null';
    if(Array.isArray(value))return '['+value.map(stableValue).join(',')+']';
    if(typeof value==='object')return '{'+Object.keys(value).sort().map(key=>key+':'+stableValue(value[key])).join(',')+'}';
    return String(value);
  }
  function interval(value){
    if(!value||typeof value!=='object')return null;
    const start=finite(value.start)?value.start:finite(value.time)?value.time:null;
    const end=finite(value.end)?value.end:finite(value.duration)&&start!==null?start+value.duration:null;
    return start!==null&&end!==null&&end>start?{start,end}:null;
  }
  function setting(options,key,fallback){
    return options&&finite(options[key])?options[key]:fallback;
  }
  function lookupLimit(source,id,kind){
    if(finite(source))return source;
    if(!source||typeof source!=='object'||Array.isArray(source))return null;
    for(const key of [id,kind,'default'])if(finite(source[key]))return source[key];
    return null;
  }

  function profileFor(options){
    return options&&options.profile||DEFAULT_PROFILE||null;
  }
  function validChannel(channel,channelCount){
    return Number.isInteger(channel)&&channel>=1&&channel<=channelCount;
  }
  function descriptors(show,profile,options){
    const channelCount=show.channels||show.channelCount||200;
    const declared=options&&Array.isArray(options.outputs)?options.outputs:profile&&Array.isArray(profile.outputs)?profile.outputs:[];
    const known=new Set(),result=[];
    for(const output of declared){
      if(!output||typeof output.id!=='string')continue;
      const channels=unique((output.channels||[]).filter(channel=>validChannel(channel,channelCount))).sort(sortNumeric);
      if(!channels.length)continue;
      channels.forEach(channel=>known.add(channel));
      result.push({id:output.id,kind:typeof output.kind==='string'?output.kind:'unknown',channels,available:output.available!==false,commandLimit:finite(output.commandLimit)?output.commandLimit:null});
    }
    // Preserve evidence from a partial profile rather than silently ignoring
    // active unclassified channels. Raw fallbacks are deliberately not called
    // "lights" because the profile did not identify them.
    for(let channel=1;channel<=channelCount;channel++)if(!known.has(channel)){
      let used=false;
      for(let frame=0;frame<show.frameCount;frame++)if(show.frames[frame*channelCount+channel-1]!==0){used=true;break;}
      if(used)result.push({id:'channel-'+channel,kind:'unknown',channels:[channel],available:true,commandLimit:null});
    }
    return result.sort((a,b)=>a.id.localeCompare(b.id));
  }
  function rawKey(show,track,frame){
    const offset=frame*(show.channels||show.channelCount||200);
    return track.channels.map(channel=>show.frames[offset+channel-1]).join(',');
  }
  function rawActive(show,track,frame){
    const offset=frame*(show.channels||show.channelCount||200);
    return track.channels.some(channel=>show.frames[offset+channel-1]!==0);
  }
  function visualTrack(track,options){
    if(track.kind==='closure')return false;
    return track.kind!=='unknown'||!(options&&options.includeUnknownVisual===false);
  }
  function visualToken(show,track,frame,levels){
    const width=show.channels||show.channelCount||200,offset=frame*width;
    if(track.kind==='rgb'){
      let token=0,nonZero=false;
      for(const channel of track.channels){
        const value=show.frames[offset+channel-1];
        const bucket=Math.round(value*(levels-1)/255);
        token=token*levels+bucket;
        nonZero=nonZero||value!==0;
      }
      return nonZero?token:0;
    }
    return track.channels.some(channel=>show.frames[offset+channel-1]!==0)?1:0;
  }
  function exactRuns(show,track){
    const runs=[];
    let start=0,previous=rawKey(show,track,0);
    for(let frame=1;frame<=show.frameCount;frame++){
      const next=frame<show.frameCount?rawKey(show,track,frame):null;
      if(next===previous)continue;
      if(previous&&previous.split(',').some(value=>Number(value)!==0)){
        runs.push({startFrame:start,endFrame:frame,start:start*show.stepMs/1000,end:frame*show.stepMs/1000,state:previous});
      }
      start=frame;previous=next;
    }
    return runs;
  }
  function timingRows(show,profile){
    if(!profile||typeof profile.resolvePerceptualTiming!=='function')return null;
    try{
      const resolved=profile.resolvePerceptualTiming(show.settings&&show.settings.vehicleTimingCalibration);
      return resolved&&resolved.outputs||null;
    }catch(_error){return null;}
  }
  function durationLimit(options,timing,id,kind){
    const explicit=lookupLimit(options&&(options.minimumDurationMs||options.minimumDurations),id,kind);
    if(explicit!==null)return explicit;
    const row=timing&&timing[id];
    return row&&finite(row.minimumUsefulDurationMs)?row.minimumUsefulDurationMs:null;
  }
  function repeatLimit(options,timing,id,kind){
    const explicit=lookupLimit(options&&(options.minimumRepeatIntervalMs||options.minimumRepeatIntervals),id,kind);
    if(explicit!==null)return explicit;
    const row=timing&&timing[id];
    return row&&finite(row.minimumRepeatIntervalMs)?row.minimumRepeatIntervalMs:null;
  }

  function samples(show,tracks,options){
    const visual=tracks.filter(track=>visualTrack(track,options));
    const levels=Math.round(clamp(setting(options,'rgbQuantizationLevels',4),2,16));
    const sampleMs=Math.max(show.stepMs,setting(options,'visualSampleMs',100));
    const sampleFrames=Math.max(1,Math.round(sampleMs/show.stepMs));
    const count=Math.ceil(show.frameCount/sampleFrames);
    const tokens=visual.map(()=>new Uint8Array(count));
    const anyActive=new Uint8Array(count),activeOutputs=new Uint16Array(count),changes=new Uint16Array(count);
    const previous=new Uint8Array(visual.length);
    for(let sample=0;sample<count;sample++){
      const frame=Math.min(show.frameCount-1,sample*sampleFrames);
      let active=0,transitions=0;
      for(let index=0;index<visual.length;index++){
        const token=visualToken(show,visual[index],frame,levels);
        tokens[index][sample]=token;
        if(token!==0){active++;anyActive[sample]=1;}
        if((sample===0&&token!==0)||(sample>0&&token!==previous[index]))transitions++;
        previous[index]=token;
      }
      activeOutputs[sample]=active;changes[sample]=transitions;
    }
    return {visual,levels,sampleFrames,sampleMs:sampleFrames*show.stepMs,count,tokens,anyActive,activeOutputs,changes};
  }
  function tokenSignature(sampled,start,end){
    const rows=[];
    for(let sample=start;sample<end;sample++){
      let row='';
      for(let track=0;track<sampled.visual.length;track++)row+=sampled.tokens[track][sample].toString(36)+',';
      rows.push(row);
    }
    return rows.join('|');
  }
  function visualWindows(show,sampled,options){
    const windowFrames=Math.max(1,Math.round(Math.max(show.stepMs,setting(options,'windowMs',2000))/show.stepMs));
    const hopFrames=Math.max(1,Math.round(Math.max(show.stepMs,setting(options,'hopMs',1000))/show.stepMs));
    const includeRows=!!(options&&options.includeWindows),maxRows=Math.max(0,Math.floor(setting(options,'maxWindowRows',200)));
    const densities=[],activeFractions=[],signatures=new Map(),rows=[];
    let windowCount=0,adjacentRepeatCount=0,previousSignature=null;
    for(let startFrame=0;startFrame<show.frameCount;startFrame+=hopFrames){
      const endFrame=Math.min(show.frameCount,startFrame+windowFrames);
      const startSample=Math.floor(startFrame/sampled.sampleFrames),endSample=Math.min(sampled.count,Math.ceil(endFrame/sampled.sampleFrames));
      let transitions=0,activeSamples=0,activeOutputSamples=0;
      for(let sample=startSample;sample<endSample;sample++){
        transitions+=sampled.changes[sample];
        activeSamples+=sampled.anyActive[sample];
        activeOutputSamples+=sampled.activeOutputs[sample];
      }
      const sampleCount=Math.max(1,endSample-startSample),seconds=(endFrame-startFrame)*show.stepMs/1000;
      const density=seconds>0?transitions/seconds:0,activeFraction=activeSamples/sampleCount;
      const signature=tokenSignature(sampled,startSample,endSample),signatureHash=hash(signature);
      const row={index:windowCount,start:startFrame*show.stepMs/1000,end:endFrame*show.stepMs/1000,sampledTransitionCount:transitions,transitionsPerSecond:density,activeSampleFraction:activeFraction,meanActiveOutputs:activeOutputSamples/sampleCount,signatureHash};
      if(includeRows&&rows.length<maxRows)rows.push(row);
      const bucket=signatures.get(signature)||{count:0,firstWindow:windowCount,hash:signatureHash};bucket.count++;signatures.set(signature,bucket);
      if(previousSignature===signature)adjacentRepeatCount++;
      previousSignature=signature;densities.push(density);activeFractions.push(activeFraction);windowCount++;
      if(endFrame===show.frameCount)break;
    }
    const sortedPatterns=Array.from(signatures.values()).filter(row=>row.count>1).sort((a,b)=>b.count-a.count||a.firstWindow-b.firstWindow).slice(0,20).map(row=>({signatureHash:row.hash,count:row.count,firstWindow:row.firstWindow}));
    const probabilities=Array.from(signatures.values()).map(row=>row.count/windowCount);
    const entropy=probabilities.reduce((sum,p)=>sum-(p*Math.log2(p)),0),maxEntropy=windowCount>1?Math.log2(windowCount):0;
    return {
      windowMs:windowFrames*show.stepMs,hopMs:hopFrames*show.stepMs,windowCount,
      density:{sampledTransitionCount:Array.from(sampled.changes).reduce((sum,value)=>sum+value,0),sampledTransitionsPerSecond:sampled.count?Array.from(sampled.changes).reduce((sum,value)=>sum+value,0)/(show.frameCount*show.stepMs/1000):null,transitionsPerSecond:distribution(densities),activeSampleFraction:distribution(activeFractions)},
      repetition:{uniquePatternCount:signatures.size,uniquePatternRate:windowCount?signatures.size/windowCount:null,adjacentRepeatCount,adjacentRepeatRate:windowCount>1?adjacentRepeatCount/(windowCount-1):null,exactRedundancyRate:windowCount?1-signatures.size/windowCount:null,shannonEntropyBits:entropy,normalizedEntropy:maxEntropy?entropy/maxEntropy:null,topRepeatedPatterns:sortedPatterns},
      windows:includeRows?rows:undefined,omittedWindowRows:includeRows?Math.max(0,windowCount-rows.length):windowCount
    };
  }
  function darkRuns(show,sampled,minimumMs){
    const runs=[];let start=null;
    for(let sample=0;sample<=sampled.count;sample++){
      const dark=sample<sampled.count&&sampled.anyActive[sample]===0;
      if(dark&&start===null){start=sample;continue;}
      if((!dark||sample===sampled.count)&&start!==null){
        const from=start*sampled.sampleFrames*show.stepMs/1000,to=Math.min(show.frameCount*show.stepMs/1000,sample*sampled.sampleFrames*show.stepMs/1000);
        if((to-from)*1000+1e-7>=minimumMs)runs.push({start:from,end:to,durationMs:(to-from)*1000});
        start=null;
      }
    }
    return runs;
  }
  function declaredNegativeSpace(show,options,sampled){
    const raw=options&&Array.isArray(options.declaredNegativeSpace)?options.declaredNegativeSpace:show.choreography&&Array.isArray(show.choreography.negativeSpace)?show.choreography.negativeSpace:[];
    const intervals=raw.map(interval).filter(Boolean).sort((a,b)=>a.start-b.start||a.end-b.end);
    if(!intervals.length)return {provided:false,count:0,fullyDarkCount:null,fullyDarkRate:null,intervals:[]};
    const rows=[];
    for(const target of intervals){
      const start=Math.max(0,Math.floor(target.start*1000/show.stepMs)),end=Math.min(show.frameCount,Math.ceil(target.end*1000/show.stepMs));
      const first=Math.floor(start/sampled.sampleFrames),last=Math.min(sampled.count,Math.ceil(end/sampled.sampleFrames));
      let active=0,total=0;
      for(let sample=first;sample<last;sample++){active+=sampled.anyActive[sample];total++;}
      rows.push({start:target.start,end:target.end,activeSampleFraction:total?active/total:0,fullyDark:active===0});
    }
    const fullyDarkCount=rows.filter(row=>row.fullyDark).length;
    return {provided:true,count:rows.length,fullyDarkCount,fullyDarkRate:fullyDarkCount/rows.length,intervals:rows};
  }

  function plannedEvents(show,tracks){
    const trackById=new Map(tracks.map(track=>[track.id,track]));
    const result=[];
    for(const [source,list] of [['lightEvents',show.lightEvents],['movements',show.movements]])for(const event of Array.isArray(list)?list:[]){
      if(!event||typeof event!=='object')continue;
      const id=typeof event.outputId==='string'?event.outputId:typeof event.id==='string'?event.id:null;
      const track=id&&trackById.get(id);
      const channels=unique((Array.isArray(event.channels)?event.channels:track&&track.channels||[]).filter(channel=>validChannel(channel,show.channels||show.channelCount||200))).sort(sortNumeric);
      const start=finite(event.actualStart)?event.actualStart:finite(event.start)?event.start:finite(event.time)?event.time:null;
      const end=finite(event.actualEnd)?event.actualEnd:finite(event.end)?event.end:finite(event.duration)&&start!==null?start+event.duration:null;
      if(start===null||end===null||end<=start||!channels.length)continue;
      const command=event.value!==undefined?event.value:event.command!==undefined?event.command:event.rgb!==undefined?event.rgb:null;
      result.push({source,id:id||channels.join(','),channels,start,end,command:stableValue(command)});
    }
    return result.sort((a,b)=>a.start-b.start||a.end-b.end||a.id.localeCompare(b.id)||a.source.localeCompare(b.source));
  }
  function conflicts(show,tracks,options){
    const events=plannedEvents(show,tracks);
    if(!events.length)return {assessed:false,reason:'No explicit lightEvents or movements metadata was supplied; final FSEQ bytes cannot reveal overwritten planning commands.',count:null,redundantOverlapCount:null,rows:[],truncated:false};
    const byChannel=new Map();events.forEach((event,index)=>event.channels.forEach(channel=>{const rows=byChannel.get(channel)||[];rows.push({event,index});byChannel.set(channel,rows);}));
    const maxRows=Math.max(1,Math.floor(setting(options,'maxConflictRows',200))),pairs=new Set(),rows=[],redundant=new Set();let truncated=false;
    for(const [channel,entries] of byChannel){
      const active=[];
      for(const current of entries.sort((a,b)=>a.event.start-b.event.start||a.index-b.index)){
        for(let index=active.length-1;index>=0;index--)if(active[index].event.end<=current.event.start)active.splice(index,1);
        for(const prior of active){
          const key=prior.index<current.index?prior.index+':'+current.index:current.index+':'+prior.index;
          if(prior.event.command===current.event.command){redundant.add(key);continue;}
          if(pairs.has(key))continue;pairs.add(key);
          if(rows.length<maxRows)rows.push({channel,start:Math.max(prior.event.start,current.event.start),end:Math.min(prior.event.end,current.event.end),first:{source:prior.event.source,outputId:prior.event.id,command:prior.event.command},second:{source:current.event.source,outputId:current.event.id,command:current.event.command}});
          else truncated=true;
        }
        active.push(current);
      }
    }
    return {assessed:true,count:pairs.size,redundantOverlapCount:redundant.size,rows,truncated};
  }

  function hierarchyTargets(show,options){
    const supplied=options&&Array.isArray(options.tierTargets)?options.tierTargets:options&&Array.isArray(options.targets)?options.targets:show.choreography&&Array.isArray(show.choreography.tierTargets)?show.choreography.tierTargets:show.choreography&&Array.isArray(show.choreography.targets)?show.choreography.targets:[];
    return supplied.filter(target=>target&&typeof target.tier==='string'&&finite(target.time)).map(target=>({tier:target.tier,time:target.time,end:finite(target.end)&&target.end>target.time?target.end:target.time,outputIds:unique([target.outputId,...(Array.isArray(target.candidateOutputIds)?target.candidateOutputIds:[])].filter(id=>typeof id==='string'))}));
  }
  function attackAt(show,track,first,last,levels){
    if(!track)return false;
    const start=Math.max(0,first),end=Math.min(show.frameCount-1,last);
    for(let frame=start;frame<=end;frame++){
      const current=visualToken(show,track,frame,levels),previous=frame?visualToken(show,track,frame-1,levels):0;
      if(current!==0&&current!==previous)return true;
    }
    return false;
  }
  function activeBetween(show,track,first,last,levels){
    if(!track)return false;
    for(let frame=Math.max(0,first);frame<=Math.min(show.frameCount-1,last);frame++)if(visualToken(show,track,frame,levels)!==0)return true;
    return false;
  }
  function hierarchy(show,sampled,tracks,options){
    const targets=hierarchyTargets(show,options);
    if(!targets.length)return {assessed:false,reason:'No tier-labelled target list was supplied.',selected:0,attackMatched:null,activeMatched:null,tiers:{}};
    const byId=new Map(tracks.map(track=>[track.id,track])),tolerance=Math.max(0,setting(options,'targetToleranceMs',show.stepMs))/1000,tiers=new Map();
    for(const target of targets){
      const candidates=(target.outputIds.length?target.outputIds.map(id=>byId.get(id)).filter(Boolean):sampled.visual).filter(track=>visualTrack(track,options));
      const attackStart=Math.floor((target.time-tolerance)*1000/show.stepMs),attackEnd=Math.ceil((target.time+tolerance)*1000/show.stepMs);
      const activeStart=attackStart,activeEnd=Math.ceil((target.end+tolerance)*1000/show.stepMs);
      const attackMatched=candidates.some(track=>attackAt(show,track,attackStart,attackEnd,sampled.levels));
      const activeMatched=attackMatched||candidates.some(track=>activeBetween(show,track,activeStart,activeEnd,sampled.levels));
      const aggregate=tiers.get(target.tier)||{selected:0,attackMatched:0,activeMatched:0};aggregate.selected++;if(attackMatched)aggregate.attackMatched++;if(activeMatched)aggregate.activeMatched++;tiers.set(target.tier,aggregate);
    }
    const ordered={};for(const tier of Array.from(tiers.keys()).sort()){
      const row=tiers.get(tier);ordered[tier]={...row,attackCoverage:row.attackMatched/row.selected,activeCoverage:row.activeMatched/row.selected};
    }
    const selected=targets.length,attackMatched=Array.from(tiers.values()).reduce((sum,row)=>sum+row.attackMatched,0),activeMatched=Array.from(tiers.values()).reduce((sum,row)=>sum+row.activeMatched,0);
    return {assessed:true,selected,attackMatched,activeMatched,attackCoverage:attackMatched/selected,activeCoverage:activeMatched/selected,tiers:ordered};
  }
  function outputOveruse(show,sampled,options){
    const durationSeconds=show.frameCount*show.stepMs/1000,outputs=[];let thresholded=0,violations=0;
    for(let index=0;index<sampled.visual.length;index++){
      const track=sampled.visual[index];let transitions=0,active=0,previous=0;
      for(let sample=0;sample<sampled.count;sample++){
        const token=sampled.tokens[index][sample];
        if(token!==0)active++;
        if((sample===0&&token!==0)||(sample>0&&token!==previous))transitions++;
        previous=token;
      }
      const maximumTransitionsPerMinute=lookupLimit(options&&(options.maximumTransitionsPerMinute||options.maxTransitionsPerMinute),track.id,track.kind);
      const transitionsPerMinute=durationSeconds>0?transitions/durationSeconds*60:0;
      const exceeded=maximumTransitionsPerMinute===null?null:transitionsPerMinute>maximumTransitionsPerMinute+1e-7;
      if(maximumTransitionsPerMinute!==null)thresholded++;
      if(exceeded)violations++;
      outputs.push({id:track.id,kind:track.kind,sampledTransitionCount:transitions,sampledTransitionsPerMinute:transitionsPerMinute,activeSampleFraction:sampled.count?active/sampled.count:0,maximumTransitionsPerMinute,transitionRateExceeded:exceeded});
    }
    return {assessed:outputs.length>0,thresholdedOutputCount:thresholded,violationCount:thresholded?violations:null,outputs};
  }
  function actuatorAndDurationMetrics(show,tracks,profile,options){
    const timing=timingRows(show,profile),outputs=[];let limitViolations=0,minViolations=0,repeatViolations=0,assessedMinimums=0;
    for(const track of tracks){
      const minimumMs=durationLimit(options,timing,track.id,track.kind),repeatMs=repeatLimit(options,timing,track.id,track.kind);
      const needsRuns=track.kind==='closure'||minimumMs!==null||repeatMs!==null;
      if(!needsRuns)continue;
      const runs=exactRuns(show,track),minimumRows=minimumMs===null?[]:runs.filter(run=>(run.end-run.start)*1000+1e-7<minimumMs).map(run=>({start:run.start,end:run.end,durationMs:(run.end-run.start)*1000}));
      const repeatRows=[];
      if(repeatMs!==null)for(let index=1;index<runs.length;index++){
        const intervalMs=(runs[index].start-runs[index-1].start)*1000;
        if(intervalMs+1e-7<repeatMs)repeatRows.push({previousStart:runs[index-1].start,start:runs[index].start,intervalMs});
      }
      if(minimumMs!==null)assessedMinimums++;
      minViolations+=minimumRows.length;repeatViolations+=repeatRows.length;
      const commandLimit=track.kind==='closure'&&finite(track.commandLimit)?track.commandLimit:null;
      const overused=commandLimit!==null&&runs.length>commandLimit;
      if(overused)limitViolations++;
      outputs.push({id:track.id,kind:track.kind,observedCommandCount:runs.length,commandLimit,commandLimitExceeded:overused,minimumUsefulDurationMs:minimumMs,minimumDurationViolationCount:minimumRows.length,minimumDurationViolations:minimumRows,minimumRepeatIntervalMs:repeatMs,repeatIntervalViolationCount:repeatRows.length,repeatIntervalViolations:repeatRows});
    }
    const actuators=outputs.filter(output=>output.kind==='closure');
    return {
      actuatorOveruse:{assessed:actuators.length>0,outputCount:actuators.length,overusedOutputCount:limitViolations,outputs:actuators},
      minimumDurations:{assessed:assessedMinimums>0,assessedOutputCount:assessedMinimums,violationCount:assessedMinimums?minViolations:null,repeatIntervalsAssessed:outputs.some(output=>output.minimumRepeatIntervalMs!==null),repeatIntervalViolationCount:outputs.some(output=>output.minimumRepeatIntervalMs!==null)?repeatViolations:null,outputs}
    };
  }
  function reportError(errors){
    return {version:VERSION,validInput:false,errors,scope:'No choreography-quality metric was calculated because the finalized frame sequence is malformed. This module never mutates FSEQ data.'};
  }

  function evaluate(show,options){
    options=options&&typeof options==='object'?options:{};
    if(!show||!(show.frames instanceof Uint8Array))return reportError(['show.frames must be a Uint8Array.']);
    const channelCount=show.channels||show.channelCount||200;
    if(!Number.isInteger(channelCount)||channelCount<1)return reportError(['show.channels or show.channelCount must be a positive integer.']);
    if(!Number.isInteger(show.frameCount)||show.frameCount<1||show.frames.length!==show.frameCount*channelCount)return reportError(['show.frameCount and frames length do not agree.']);
    if(!finite(show.stepMs)||show.stepMs<=0)return reportError(['show.stepMs must be a positive finite number.']);
    const profile=profileFor(options),tracks=descriptors(show,profile,options),sampled=samples(show,tracks,options),windowMetrics=visualWindows(show,sampled,options);
    const minimumNegativeSpaceMs=Math.max(sampled.sampleMs,setting(options,'minimumNegativeSpaceMs',250));
    const observedDarkRuns=darkRuns(show,sampled,minimumNegativeSpaceMs),negative={
      sampledAtMs:sampled.sampleMs,minimumObservedDurationMs:minimumNegativeSpaceMs,
      observedRunCount:observedDarkRuns.length,totalObservedDurationMs:observedDarkRuns.reduce((sum,row)=>sum+row.durationMs,0),longestObservedDurationMs:observedDarkRuns.length?Math.max(...observedDarkRuns.map(row=>row.durationMs)):0,
      runs:observedDarkRuns.slice(0,Math.max(0,Math.floor(setting(options,'maxNegativeSpaceRows',100)))),
      omittedRuns:Math.max(0,observedDarkRuns.length-Math.max(0,Math.floor(setting(options,'maxNegativeSpaceRows',100)))),
      declared:declaredNegativeSpace(show,options,sampled)
    };
    const actuatorMetrics=actuatorAndDurationMetrics(show,tracks,profile,options);
    const outputSummary=tracks.filter(track=>track.kind!=='closure').map(track=>({id:track.id,kind:track.kind,channels:track.channels.slice(),available:track.available}));
    const result={
      version:VERSION,validInput:true,
      scope:'Read-only final-frame and explicit-plan diagnostics. Density, negative space, entropy and tier coverage describe exported signals or declared targets; they do not establish music-detection accuracy, human visual quality, or physical vehicle behavior.',
      sampling:{visualSampleMs:sampled.sampleMs,rgbQuantizationLevels:sampled.levels,profileId:profile&&profile.id||null,visualOutputCount:sampled.visual.length,unclassifiedActiveOutputs:outputSummary.filter(row=>row.kind==='unknown').map(row=>row.id)},
      durationMs:show.frameCount*show.stepMs,
      density:windowMetrics.density,
      windows:{windowMs:windowMetrics.windowMs,hopMs:windowMetrics.hopMs,windowCount:windowMetrics.windowCount,rows:windowMetrics.windows,omittedRows:windowMetrics.omittedWindowRows},
      negativeSpace:negative,
      repetition:windowMetrics.repetition,
      outputOveruse:outputOveruse(show,sampled,options),
      conflictingCommands:conflicts(show,tracks,options),
      hierarchy:hierarchy(show,sampled,tracks,options),
      ...actuatorMetrics
    };
    return result;
  }

  const api={version:VERSION,evaluate,analyze:evaluate};
  root.ChoreographyQuality=api;
  if(typeof module==='object'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
