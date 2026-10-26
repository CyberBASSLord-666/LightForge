/* LightForge — opt-in semantic choreography strategy.
 * This strategy is deliberately conservative: it only uses timeline events
 * that ShowEngine has already bound to a matching salience record, and it only
 * changes scheduling when the caller opts in. It is not a music detector.
 */
(function(root){
  'use strict';
  const TIERS=Object.freeze(['micro','secondary','primary','phrase','structural','climax']);
  const TIER_INDEX=Object.freeze(Object.fromEntries(TIERS.map((tier,index)=>[tier,index])));
  const FRAME_INTERVALS=Object.freeze([15,20]);
  const PRIORITY_BOOST=Object.freeze({micro:0,secondary:2,primary:7,phrase:13,structural:20,climax:27});
  const finite=Number.isFinite;
  const round=value=>Math.round(value*1000000)/1000000;
  const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
  const safeRole=value=>typeof value==='string'?value:'';
  const compareText=(left,right)=>left<right?-1:left>right?1:0;
  const SOURCE_ROLES=new Set(['vocals','bass','rhythm','structure','mix','drums']);
  const canonicalRole=value=>{const role=safeRole(value);return role==='onset'||role==='onsets'?'mix':role==='percussion'?'drums':role;};
  const lower=(items,time,key)=>{let lo=0,hi=items.length;while(lo<hi){const mid=(lo+hi)>>>1;if((key?items[mid][key]:items[mid])<time)lo=mid+1;else hi=mid;}return lo;};

  function validSemantic(semantic){
    if(!semantic||!Array.isArray(semantic.events)||!semantic.events.length)return null;
    const ids=new Set(),events=[];
    for(const raw of semantic.events){
      if(!raw||typeof raw.id!=='string'||!raw.id||ids.has(raw.id)||!finite(raw.time)||raw.time<0||!finite(raw.score)||raw.score<0||raw.score>1||!Object.hasOwn(TIER_INDEX,raw.tier))return null;
      ids.add(raw.id);
      events.push(Object.freeze({id:raw.id,time:round(raw.time),source:safeRole(raw.source),score:round(raw.score),tier:raw.tier}));
    }
    events.sort((a,b)=>a.time-b.time||compareText(a.id,b.id));
    return Object.freeze(events);
  }
  function indexItems(items,timeOf,itemRole){
    const all=items.slice().sort((a,b)=>timeOf(a)-timeOf(b)),byRole=new Map();
    for(const item of all){const role=canonicalRole(itemRole(item)),group=byRole.get(role)||[];group.push(item);byRole.set(role,group);}
    return {all,byRole,timeOf,itemRole};
  }
  function nearest(index,time,role,windowSeconds){
    if(!finite(time))return null;
    const wanted=canonicalRole(role),preferred=SOURCE_ROLES.has(wanted)?wanted:'';
    const items=preferred?(index.byRole.get(preferred)||[]):index.all;
    const timeOf=index.timeOf,itemRole=index.itemRole;
    let lo=0,hi=items.length;
    while(lo<hi){const mid=(lo+hi)>>>1;if(timeOf(items[mid])<time-windowSeconds-1e-9)lo=mid+1;else hi=mid;}
    let best=null;
    for(let position=lo;position<items.length;position++){
      const item=items[position],itemTime=timeOf(item);if(itemTime>time+windowSeconds+1e-9)break;
      const distance=Math.abs(itemTime-time);
      if(distance>windowSeconds+1e-9)continue;
      const itemSource=canonicalRole(itemRole(item));
      // A nearby beat/drop cannot lend its authority to a vocal/bass attack.
      // Explicit musical roles require evidence from that same source; only
      // roleless decoration may borrow nearby context.
      if(preferred&&itemSource!==preferred)continue;
      const sourcePenalty=preferred&&itemSource===preferred?0:1;
      const score=finite(item.score)?item.score:0;
      const better=!best||distance<best.distance-1e-9||
        Math.abs(distance-best.distance)<=1e-9&&(sourcePenalty<best.sourcePenalty||
          sourcePenalty===best.sourcePenalty&&(score>best.score+1e-9||
            Math.abs(score-best.score)<=1e-9&&(itemTime<best.time-1e-9||
              Math.abs(itemTime-best.time)<=1e-9&&compareText(String(item.id),String(best.item.id))<0)));
      if(better){
        best={item,distance,sourcePenalty,score,time:itemTime};
      }
    }
    return best;
  }
  function mergeWindows(windows){
    const sorted=windows.slice().sort((a,b)=>a.start-b.start||a.end-b.end||compareText(a.semanticEventId,b.semanticEventId)),merged=[];
    for(const current of sorted){
      const previous=merged[merged.length-1];
      if(previous&&current.start<=previous.end+1e-9){
        previous.end=Math.max(previous.end,current.end);
        if(TIER_INDEX[current.tier]>TIER_INDEX[previous.tier]){previous.tier=current.tier;previous.semanticEventId=current.semanticEventId;}
      }else merged.push({...current});
    }
    return merged;
  }
  function create(semantic, options={}){
    const events=validSemantic(semantic);if(!events)return null;
    const stepMs=FRAME_INTERVALS.includes(options.stepMs)?options.stepMs:20;
    const matchWindowSeconds=Math.max(.08,stepMs/1000*4);
    const densityWindowSeconds=1.2;
    const targetLinkLimit=10000;
    const eventIndex=indexItems(events,item=>item.time,item=>item.source),stateIndices=new WeakMap();
    // Only use an explicit ordered grid. Invalid/absent data retains the old
    // wall-clock budget, rather than deriving a tempo from arbitrary targets.
    const rawBeats=options.beats;
    const beats=(Array.isArray(rawBeats)||ArrayBuffer.isView(rawBeats))&&rawBeats.length>=2&&rawBeats.length<=100000
      ?Array.from(rawBeats):null;
    const rhythmAvailable=!!beats&&beats.every((time,index)=>finite(time)&&time>=0&&(!index||time>beats[index-1]));
    function densityWindowAt(time){
      if(!rhythmAvailable||time<beats[0]||time>beats[beats.length-1])return densityWindowSeconds;
      const index=Math.min(beats.length-2,Math.max(0,lower(beats,time+1e-9)-1));
      const period=beats[index+1]-beats[index];
      // Gaps and out-of-range clocks are not local tempo evidence. A bounded
      // two-beat budget adapts ordinary/variable tempo without making gaps in
      // the music into giant exclusion windows.
      return period>=.15&&period<=3?round(clamp(period*2,.3,2.4)):densityWindowSeconds;
    }

    function prepareTargets(targets){
      const safeTargets=Array.isArray(targets)?targets:[],links=[];
      for(let index=0;index<safeTargets.length&&links.length<targetLinkLimit;index++){
        const target=safeTargets[index];
        if(!target||!finite(target.time))continue;
        const match=nearest(eventIndex,target.time,target.semanticRole||target.role,matchWindowSeconds);
        if(!match)continue;
        links.push(Object.freeze({
          targetIndex:index,role:canonicalRole(target.semanticRole||target.role),musicTime:round(target.time),
          semanticEventId:match.item.id,semanticEventTime:match.item.time,
          semanticDeltaMs:round((target.time-match.item.time)*1000),
          score:match.item.score,tier:match.item.tier
        }));
      }
      links.sort((a,b)=>a.musicTime-b.musicTime||compareText(a.semanticEventId,b.semanticEventId)||a.targetIndex-b.targetIndex);
      const anchorsById=new Map();
      for(const link of links)if(TIER_INDEX[link.tier]>=TIER_INDEX.phrase){
        const previous=anchorsById.get(link.semanticEventId);
        if(!previous||TIER_INDEX[link.tier]>TIER_INDEX[previous.tier]||TIER_INDEX[link.tier]===TIER_INDEX[previous.tier]&&link.score>previous.score)anchorsById.set(link.semanticEventId,link);
      }
      const tierTargets=Object.fromEntries(TIERS.map(tier=>[tier,links.filter(link=>link.tier===tier).length]));
      const state={targetCount:safeTargets.length,links,anchors:Array.from(anchorsById.values()).sort((a,b)=>a.semanticEventTime-b.semanticEventTime||compareText(a.semanticEventId,b.semanticEventId)),tierTargets,hierarchyMatchedCandidateCount:0,hierarchyBoostedCandidateCount:0};
      stateIndices.set(state,indexItems(links,item=>item.musicTime,item=>item.role));
      return state;
    }
    function classifyCandidate(candidate,state){
      if(!candidate||!state||!state.links.length)return candidate;
      const musicTime=finite(candidate.sourceEventTime)?candidate.sourceEventTime:finite(candidate.musicTime)?candidate.musicTime:null;
      if(!finite(musicTime))return candidate;
      const linkIndex=stateIndices.get(state)||indexItems(state.links,item=>item.musicTime,item=>item.role);
      const match=nearest(linkIndex,musicTime,candidate.semanticRole||candidate.role,matchWindowSeconds);
      if(!match)return candidate;
      const link=match.item,boost=round((PRIORITY_BOOST[link.tier]||0)*(.5+.5*link.score));
      state.hierarchyMatchedCandidateCount++;
      if(boost>0)state.hierarchyBoostedCandidateCount++;
      return Object.assign({},candidate,{
        semanticEventId:link.semanticEventId,semanticEventTime:link.semanticEventTime,
        semanticTargetTime:link.musicTime,semanticTargetDeltaMs:round((musicTime-link.musicTime)*1000),
        semanticTier:link.tier,semanticScore:link.score,semanticPriorityBoost:boost,
        // Density may thin decoration, but must not erase a selected measured
        // vocal/bass attack merely because its salience tier is secondary.
        semanticTargetAttack:link.role===candidate.role&&['vocals','bass'].includes(candidate.role)&&finite(candidate.sourceConfidence)&&candidate.sourceConfidence>0&&candidate.sourceConfidence<=1&&Math.abs(musicTime-link.musicTime)<=1e-6&&
          (candidate.role==='bass'||candidate.sourceSeparated===true),
        priority:(finite(candidate.priority)?candidate.priority:0)+boost
      });
    }
    function lowAuthority(candidate){
      return candidate&&!candidate.manual&&candidate.semanticTargetAttack!==true&&Object.hasOwn(TIER_INDEX,candidate.semanticTier)&&TIER_INDEX[candidate.semanticTier]<=TIER_INDEX.secondary;
    }
    function candidateMusicTime(candidate){
      return finite(candidate?.sourceEventTime)?candidate.sourceEventTime:finite(candidate?.musicTime)?candidate.musicTime:null;
    }
    function negativeSpaceWindows(state){
      return mergeWindows(state.anchors.map(anchor=>{
        const tier=anchor.tier,before=tier==='climax'?.08:tier==='structural'?.06:.04,after=tier==='climax'?.36:tier==='structural'?.30:.22;
        return {start:round(Math.max(0,anchor.semanticEventTime-before)),end:round(anchor.semanticEventTime+after),tier,semanticEventId:anchor.semanticEventId};
      }));
    }
    function filterCandidates(candidates,state){
      const original=Array.isArray(candidates)?candidates:[];
      if(!state||!state.links.length)return {candidates:original.slice(),diagnostics:{schemaVersion:1,requested:true,active:false,reason:'no-linkable-semantic-targets',targetCount:state?.targetCount||0,linkedTargetCount:0}};
      const rejected=new Set(),windows=negativeSpaceWindows(state);let negativeSpaceSuppressedCandidateCount=0;
      for(let index=0;index<original.length;index++){
        const candidate=original[index],time=candidateMusicTime(candidate);
        if(!lowAuthority(candidate)||!finite(time))continue;
        const span=windows[lower(windows,time+1e-9,'start')-1];
        const window=span&&candidate.semanticEventId!==span.semanticEventId&&time<=span.end+1e-9?span:null;
        if(window){rejected.add(index);negativeSpaceSuppressedCandidateCount++;}
      }
      const groups=new Map();
      for(let index=0;index<original.length;index++){
        const candidate=original[index],time=candidateMusicTime(candidate);
        if(rejected.has(index)||!lowAuthority(candidate)||!finite(time))continue;
        const key=candidate.semanticEventId+'|'+round(time)+'|'+safeRole(candidate.role)+'|'+String(candidate.kind||'event');
        let group=groups.get(key);
        if(!group){group={key,time,windowSeconds:densityWindowAt(time),score:candidate.semanticScore||0,priority:candidate.priority||0,indices:[]};groups.set(key,group);}
        group.indices.push(index);group.score=Math.max(group.score,candidate.semanticScore||0);group.priority=Math.max(group.priority,candidate.priority||0);
      }
      const ordered=Array.from(groups.values()).sort((a,b)=>b.score-a.score||b.priority-a.priority||a.time-b.time||compareText(a.key,b.key)),keptBins=new Map();
      const binSeconds=.3,maximumWindow=rhythmAvailable?2.4:densityWindowSeconds,neighborBins=Math.ceil(maximumWindow/binSeconds);
      let densitySuppressedCandidateCount=0,densitySuppressedGroupCount=0;
      for(const group of ordered){
        const bin=Math.floor(group.time/binSeconds);let occupancy=0;
        for(let key=bin-neighborBins;key<=bin+neighborBins&&occupancy<2;key++){
          for(const keptGroup of keptBins.get(key)||[])if(Math.abs(keptGroup.time-group.time)<Math.max(group.windowSeconds,keptGroup.windowSeconds)-1e-9){occupancy++;if(occupancy>=2)break;}
        }
        if(occupancy<2){const bucket=keptBins.get(bin)||[];bucket.push(group);keptBins.set(bin,bucket);continue;}
        densitySuppressedGroupCount++;
        for(const index of group.indices)if(!rejected.has(index)){rejected.add(index);densitySuppressedCandidateCount++;}
      }
      const tierAnchors=Object.fromEntries(TIERS.map(tier=>[tier,state.anchors.filter(anchor=>anchor.tier===tier).length]));
      return {candidates:original.filter((_,index)=>!rejected.has(index)),diagnostics:{
        schemaVersion:1,requested:true,active:true,reason:null,targetCount:state.targetCount,linkedTargetCount:state.links.length,
        targetTierCounts:state.tierTargets,hierarchy:{matchedCandidateCount:state.hierarchyMatchedCandidateCount,boostedCandidateCount:state.hierarchyBoostedCandidateCount},
        density:{windowSeconds:densityWindowSeconds,windowBasis:rhythmAvailable?'bounded-local-two-beat':'fixed-seconds',localBeatCount:rhythmAvailable?beats.length:0,windowBoundsSeconds:rhythmAvailable?[.3,2.4]:[densityWindowSeconds,densityWindowSeconds],maxLowAuthorityGroups:2,protectedTargetCandidateCount:original.filter(candidate=>candidate?.semanticTargetAttack===true).length,candidateGroupCount:groups.size,suppressedGroupCount:densitySuppressedGroupCount,suppressedCandidateCount:densitySuppressedCandidateCount},
        negativeSpace:{windowCount:windows.length,windows:windows.slice(0,128),truncatedWindowCount:Math.max(0,windows.length-128),anchorTierCounts:tierAnchors,suppressedCandidateCount:negativeSpaceSuppressedCandidateCount},
        scope:'Opt-in scheduling uses only validated semantic target links. It does not establish music-detection accuracy or perceptual quality.'
      }};
    }
    return Object.freeze({version:'1.2.0',prepareTargets,classifyCandidate,filterCandidates});
  }
  const api=Object.freeze({version:'1.2.0',create,tiers:TIERS.slice()});
  root.SemanticChoreography=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);

