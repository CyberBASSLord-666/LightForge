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
  function nearest(items,time,role,windowSeconds,timeOf,itemRole){
    if(!finite(time))return null;
    const wanted=safeRole(role),preferred=wanted==='vocals'||wanted==='bass'?wanted:'';
    let best=null;
    for(const item of items){
      const itemTime=timeOf(item),distance=Math.abs(itemTime-time);
      if(distance>windowSeconds+1e-9)continue;
      const itemSource=itemRole(item),sourcePenalty=preferred&&itemSource===preferred?0:1;
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

    function prepareTargets(targets){
      const safeTargets=Array.isArray(targets)?targets:[],links=[];
      for(let index=0;index<safeTargets.length&&links.length<targetLinkLimit;index++){
        const target=safeTargets[index];
        if(!target||!finite(target.time))continue;
        const match=nearest(events,target.time,target.role,matchWindowSeconds,item=>item.time,item=>item.source);
        if(!match)continue;
        links.push(Object.freeze({
          targetIndex:index,role:safeRole(target.role),musicTime:round(target.time),
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
      return {targetCount:safeTargets.length,links,anchors:Array.from(anchorsById.values()).sort((a,b)=>a.semanticEventTime-b.semanticEventTime||compareText(a.semanticEventId,b.semanticEventId)),tierTargets,hierarchyMatchedCandidateCount:0,hierarchyBoostedCandidateCount:0};
    }
    function classifyCandidate(candidate,state){
      if(!candidate||!state||!state.links.length)return candidate;
      const musicTime=finite(candidate.sourceEventTime)?candidate.sourceEventTime:finite(candidate.musicTime)?candidate.musicTime:null;
      if(!finite(musicTime))return candidate;
      const match=nearest(state.links,musicTime,candidate.role,matchWindowSeconds,item=>item.musicTime,item=>item.role);
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
        const window=windows.find(span=>candidate.semanticEventId!==span.semanticEventId&&time>=span.start-1e-9&&time<=span.end+1e-9);
        if(window){rejected.add(index);negativeSpaceSuppressedCandidateCount++;}
      }
      const groups=new Map();
      for(let index=0;index<original.length;index++){
        const candidate=original[index],time=candidateMusicTime(candidate);
        if(rejected.has(index)||!lowAuthority(candidate)||!finite(time))continue;
        const key=candidate.semanticEventId+'|'+round(time)+'|'+safeRole(candidate.role)+'|'+String(candidate.kind||'event');
        let group=groups.get(key);
        if(!group){group={key,time,score:candidate.semanticScore||0,priority:candidate.priority||0,indices:[]};groups.set(key,group);}
        group.indices.push(index);group.score=Math.max(group.score,candidate.semanticScore||0);group.priority=Math.max(group.priority,candidate.priority||0);
      }
      const ordered=Array.from(groups.values()).sort((a,b)=>b.score-a.score||b.priority-a.priority||a.time-b.time||compareText(a.key,b.key)),kept=[];
      let densitySuppressedCandidateCount=0,densitySuppressedGroupCount=0;
      for(const group of ordered){
        const occupancy=kept.filter(keptGroup=>Math.abs(keptGroup.time-group.time)<densityWindowSeconds-1e-9).length;
        if(occupancy<2){kept.push(group);continue;}
        densitySuppressedGroupCount++;
        for(const index of group.indices)if(!rejected.has(index)){rejected.add(index);densitySuppressedCandidateCount++;}
      }
      const tierAnchors=Object.fromEntries(TIERS.map(tier=>[tier,state.anchors.filter(anchor=>anchor.tier===tier).length]));
      return {candidates:original.filter((_,index)=>!rejected.has(index)),diagnostics:{
        schemaVersion:1,requested:true,active:true,reason:null,targetCount:state.targetCount,linkedTargetCount:state.links.length,
        targetTierCounts:state.tierTargets,hierarchy:{matchedCandidateCount:state.hierarchyMatchedCandidateCount,boostedCandidateCount:state.hierarchyBoostedCandidateCount},
        density:{windowSeconds:densityWindowSeconds,maxLowAuthorityGroups:2,protectedTargetCandidateCount:original.filter(candidate=>candidate?.semanticTargetAttack===true).length,candidateGroupCount:groups.size,suppressedGroupCount:densitySuppressedGroupCount,suppressedCandidateCount:densitySuppressedCandidateCount},
        negativeSpace:{windowCount:windows.length,windows:windows.slice(0,128),truncatedWindowCount:Math.max(0,windows.length-128),anchorTierCounts:tierAnchors,suppressedCandidateCount:negativeSpaceSuppressedCandidateCount},
        scope:'Opt-in scheduling uses only validated semantic target links. It does not establish music-detection accuracy or perceptual quality.'
      }};
    }
    return Object.freeze({version:'1.1.0',prepareTargets,classifyCandidate,filterCandidates});
  }
  const api=Object.freeze({version:'1.1.0',create,tiers:TIERS.slice()});
  root.SemanticChoreography=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);

