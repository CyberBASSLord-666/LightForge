'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const Strategy=require('../web/engine/semantic-choreography.js');

const event=(id,time,source='vocals',score=.3,tier='secondary')=>({id,time,source,score,tier});
const target=(time,role='vocals')=>({time,role,end:time+.12});
function runDensity(times,beats,extra={}){
 const semantic={events:times.map((time,index)=>event('detail-'+index,time,'mix',.3+(index%60)*.01))};
 const strategy=Strategy.create(semantic,{stepMs:20,...(beats===undefined?{}:{beats})});
 const state=strategy.prepareTargets(times.map(time=>target(time,'mix')));
 const raw=times.map((time,serial)=>({serial,musicTime:time,semanticRole:'mix',priority:20,kind:'ornament',...extra}));
 const classified=raw.map(candidate=>strategy.classifyCandidate(candidate,state));
 return {raw,classified,result:strategy.filterCandidates(classified,state)};
}

test('source timing links cannot borrow closer rhythm or structural salience',()=>{
 const strategy=Strategy.create({events:[event('beat',1,'rhythm',.98,'climax'),event('voice',1.025,'vocals',.3),event('bass',1.03,'bass',.4)]});
 const state=strategy.prepareTargets([target(1),target(1,'bass')]);
 assert.deepEqual(state.links.slice().sort((a,b)=>a.targetIndex-b.targetIndex).map(link=>link.semanticEventId),['voice','bass']);
 const vocal=strategy.classifyCandidate({role:'vocals',sourceEventTime:1,sourceSeparated:true,sourceConfidence:.7,priority:60},state);
 assert.equal(vocal.semanticEventId,'voice');
 assert.equal(vocal.semanticTier,'secondary');
 assert.equal(vocal.semanticTargetAttack,true,'selected measured source timing remains protected');
 assert.ok(vocal.priority<62,'unrelated climax cannot promote this voice to structural priority');
});

test('a missing role source leaves the target unlinked instead of inventing authority',()=>{
 const strategy=Strategy.create({events:[event('beat',2,'rhythm',.99,'climax')]});
 assert.equal(strategy.prepareTargets([target(2,'vocals'),target(2,'bass')]).links.length,0);
 const generic=strategy.prepareTargets([target(2,'manual-custom-role')]);
 assert.equal(generic.links.length,1,'unknown legacy role compatibility remains nearest context');
});

test('semanticRole connects arrangement sources without turning them into instrument attacks',()=>{
 const strategy=Strategy.create({events:[event('onset',2,'mix',.3),event('hit',3,'drums',.4)]});
 const state=strategy.prepareTargets([{time:2,semanticRole:'onset'},{time:3,role:'percussion'}]);
 assert.deepEqual(state.links.map(link=>link.role),['mix','drums']);
 const onset=strategy.classifyCandidate({musicTime:2,semanticRole:'onsets',priority:20},state);
 assert.equal(onset.semanticEventId,'onset');assert.equal(onset.semanticTargetAttack,false);
 const unrelated=strategy.classifyCandidate({musicTime:2,semanticRole:'structure',priority:20},state);
 assert.equal(unrelated.semanticEventId,undefined,'explicit structural candidates cannot borrow onset evidence');
});

test('fast local beat budgets retain spaced detail that a fixed wall-clock budget erased',()=>{
 const times=[1,1.4,1.8],beats=Array.from({length:25},(_,i)=>i*.25);
 const legacy=runDensity(times),adaptive=runDensity(times,beats);
 assert.equal(legacy.result.candidates.length,2);
 assert.equal(adaptive.result.candidates.length,3);
 assert.equal(adaptive.result.diagnostics.density.windowBasis,'bounded-local-two-beat');
 assert.deepEqual(adaptive.result.candidates.map(candidate=>candidate.musicTime),times,'retained attacks never shift');
 assert.deepEqual(adaptive,runDensity(times,beats),'same grid and candidates remain deterministic');
});

test('slow local beat budgets give sparse music breathing space instead of fixed-second busyness',()=>{
 const times=[1,1.7,2.4],beats=[0,1,2,3,4,5];
 assert.equal(runDensity(times).result.candidates.length,3);
 const adaptive=runDensity(times,beats);
 assert.equal(adaptive.result.candidates.length,2);
 assert.equal(adaptive.result.diagnostics.density.suppressedGroupCount,1);
});

test('variable-tempo density follows local beat intervals, not average BPM',()=>{
 const beats=[0,1,2,3,4,4.25,4.5,4.75,5,5.25,5.5,5.75,6];
 const early=runDensity([1,1.7,2.4],beats),late=runDensity([4.5,4.9,5.3],beats);
 assert.equal(early.result.candidates.length,2);
 assert.equal(late.result.candidates.length,3);
});

test('malformed, absent, and out-of-range beat intervals retain bounded fallback behavior',()=>{
 const times=[1,1.4,1.8],baseline=runDensity(times).result.candidates;
 for(const beats of [[],[0],[0,0,1],[1,0],[0,NaN,2],[0,Infinity],[0,-1],[0,.01,.02],[0,10]]){
  assert.deepEqual(runDensity(times,beats).result.candidates,baseline,JSON.stringify(beats));
 }
 const outside=runDensity(times,[5,5.25,5.5]);
 assert.deepEqual(outside.result.candidates,baseline,'no extrapolated tempo outside supported grid');
 const beats=[0,.5,1,1.5,2];const copy=beats.slice();runDensity(times,beats);assert.deepEqual(beats,copy);
});

test('adaptive density never prunes manual cues or selected measured source attacks',()=>{
 const beats=[0,1,2,3],times=[1,1.1,1.2,1.3];
 assert.equal(runDensity(times,beats,{manual:true}).result.candidates.length,4);
 for(const role of ['vocals','bass']){
  const semantic={events:times.map((time,index)=>event('source-'+index,time,role))};
  const strategy=Strategy.create(semantic,{beats}),state=strategy.prepareTargets(times.map(time=>target(time,role)));
  const candidates=times.map((time,serial)=>strategy.classifyCandidate({serial,role,sourceEventTime:time,sourceSeparated:role==='vocals',sourceConfidence:.5,priority:65},state));
  const result=strategy.filterCandidates(candidates,state);
  assert.equal(result.candidates.length,4);
  assert.equal(result.diagnostics.density.protectedTargetCandidateCount,4);
 }
});

test('indexed matching and binned density agree with an independent exhaustive oracle',()=>{
 const times=Array.from({length:400},(_,i)=>.2+i*.137),beats=Array.from({length:180},(_,i)=>i<80?i*.4:32+(i-80)*.25);
 const {classified,result}=runDensity(times,beats),ranked=classified.slice().sort((a,b)=>b.semanticScore-a.semanticScore||b.priority-a.priority||a.musicTime-b.musicTime),kept=[];
 const windowAt=time=>{
  if(time<beats[0]||time>beats.at(-1))return 1.2;
  let index=0;while(index+1<beats.length-1&&beats[index+1]<=time+1e-9)index++;
  const period=beats[index+1]-beats[index];return period>=.15&&period<=3?Math.round(Math.min(2.4,Math.max(.3,period*2))*1e6)/1e6:1.2;
 };
 for(const cue of ranked){
  const window=windowAt(cue.musicTime);
  if(kept.filter(other=>Math.abs(other.musicTime-cue.musicTime)<Math.max(window,windowAt(other.musicTime))-1e-9).length<2)kept.push(cue);
 }
 assert.deepEqual(result.candidates.map(cue=>cue.serial),kept.map(cue=>cue.serial).sort((a,b)=>a-b));
 for(const cue of classified)assert.ok(Math.abs(cue.semanticTargetTime-cue.musicTime)<1e-6);
});

test('large source-indexed target lists retain exact links within the documented bound',()=>{
 const semantic={events:Array.from({length:12000},(_,i)=>event('e'+i,i*.1,i%2?'bass':'vocals',.3))};
 const targets=semantic.events.map(item=>target(item.time,item.source));
 const strategy=Strategy.create(semantic),state=strategy.prepareTargets(targets);
 assert.equal(state.links.length,10000);
 assert.equal(state.targetCount,12000);
 assert.equal(state.links[0].semanticEventId,'e0');
 assert.equal(state.links.at(-1).semanticEventId,'e9999');
 for(const index of [0,1,4999,9999]){
  const source=semantic.events[index],cue=strategy.classifyCandidate({sourceEventTime:source.time,role:source.source},state);
  assert.equal(cue.semanticEventId,source.id);
 }
});
