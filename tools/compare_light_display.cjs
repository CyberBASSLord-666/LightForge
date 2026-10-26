#!/usr/bin/env node
'use strict';
// Recorded analysis snapshots exercise composition without re-running models.
// These are deterministic digital-output comparisons, not listener/vehicle proof.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {execFileSync}=require('node:child_process');
const sha=x=>crypto.createHash('sha256').update(x).digest('hex');
const fixtures=['qa/music-1.3.0/current-demo-music.json','qa/music-1.3.0/current-sample-music.json',
 'qa/release-1.6.0/actual-music-user-glass-prefix64-analysis.json','qa/release-1.6.0/actual-music-nightowl-mix-analysis.json','qa/release-1.6.0/actual-music-falcon-mix-analysis.json'];
if(process.argv[2]==='--capture'){
 const root=path.resolve(process.argv[3]);
 const Engine=require(path.join(root,'web/engine/show-engine.js'));
 const Timeline=require(path.join(root,'web/analysis/semantic-timeline.js'));
 const Salience=require(path.join(root,'web/analysis/salience.js'));
 const rows=[];
 for(const fixture of fixtures){
  const bytes=fs.readFileSync(path.join(root,fixture)),music=JSON.parse(bytes);
  music.semanticTimeline=Timeline.build(music);music.musicSalience=Salience.build(music.semanticTimeline);
  for(const stepMs of [15,20])for(const style of ['festival','cinematic','pulse']){
   const settings={style,stepMs,seed:2025,dance:'expressive',semanticChoreography:true,vocalChoreography:true};
   const show=Engine.generate(music,settings),strategy=show.choreography.semanticStrategy,events=show.lightEvents;
   const ramps=events.filter(e=>e.fade>0);let shortFullRamps=0;
   for(const e of ramps){const ch=Engine.getCapabilities().outputs.find(o=>o.id===e.id).channels[0]-1,up=show.frames[e.a*200+ch];let pivot=e.a;while(pivot<e.b&&show.frames[pivot*200+ch]===up)pivot++;
    if((pivot-e.a)*stepMs<e.fade*1000+50-1e-6||(e.b-pivot)*stepMs<e.fade*1000+50-1e-6)shortFullRamps++;
   }
   rows.push({fixture,fixtureSha256:sha(bytes),style,stepMs,duration:music.duration,frameSha256:sha(show.frames),valid:show.validation.valid,
    semanticActive:strategy?.active===true,linkedTargets:strategy?.linkedTargetCount||0,boostedCandidates:strategy?.hierarchy?.boostedCandidateCount||0,
    negativeSpaceWindows:strategy?.negativeSpace?.windowCount||0,lowAuthoritySuppressed:(strategy?.density?.suppressedCandidateCount||0)+(strategy?.negativeSpace?.suppressedCandidateCount||0),
    acceptedLightCues:events.length,vocalCues:show.stats.vocalCues,bassCues:show.stats.bassNoteCues,
    vocalAttacks:events.filter(e=>e.role==='vocals').map(e=>[e.id,e.sourceEventTime,e.actualStart]),bassAttacks:events.filter(e=>e.role==='bass').map(e=>[e.id,e.sourceEventTime,e.actualStart]),
    quantizationMaxMs:show.stats.lightQuantizationMaxMs,automaticFullRamps:ramps.length,shortFullRamps,
    synchronization:show.synchronization.summary,quality:show.choreography.quality.summary||null});
  }
 }
 process.stdout.write(JSON.stringify(rows));
}else{
 const baseline=path.resolve(process.argv[2]||''),candidate=path.resolve(process.argv[3]||path.join(__dirname,'..'));
 if(!process.argv[2])throw new Error('Usage: node tools/compare_light_display.cjs BASELINE_CHECKOUT [CANDIDATE_CHECKOUT]');
 const capture=root=>JSON.parse(execFileSync(process.execPath,[__filename,'--capture',root],{maxBuffer:32*1024*1024,encoding:'utf8'}));
 const before=capture(baseline),after=capture(candidate);
 const rows=after.map((row,index)=>{const old=before[index];if(old.fixtureSha256!==row.fixtureSha256||old.style!==row.style||old.stepMs!==row.stepMs)throw new Error('Mismatched comparison inputs');
  const beforeAttacks=new Set(old.vocalAttacks.concat(old.bassAttacks).map(JSON.stringify)),afterAttacks=new Set(row.vocalAttacks.concat(row.bassAttacks).map(JSON.stringify));
  return {baseline:old,candidate:row,removedSourceOutputAttacks:[...beforeAttacks].filter(x=>!afterAttacks.has(x)).map(JSON.parse),addedSourceOutputAttacks:[...afterAttacks].filter(x=>!beforeAttacks.has(x)).map(JSON.parse)};
 });
 console.log(JSON.stringify({schema:'lightforge.display-comparison.v1',scope:'Paired deterministic digital composition of five unchanged recorded-analysis snapshots, three styles, 15/20 ms. No new neural inference, annotated detector accuracy, listener preference, Android or physical vehicle claim.',baselineCommit:execFileSync('git',['-C',baseline,'rev-parse','HEAD'],{encoding:'utf8'}).trim(),candidateBaseCommit:execFileSync('git',['-C',candidate,'rev-parse','HEAD'],{encoding:'utf8'}).trim(),sourceHashes:Object.fromEntries(['show-engine.js','light-planner.js','semantic-choreography.js'].map(file=>[file,sha(fs.readFileSync(path.join(candidate,'web/engine',file)))])),rows},null,2));
}
