#!/usr/bin/env node
'use strict';
// Paired host benchmark: no model, sampling, output or diagnostic reduction.
// The baseline is read from Git so the comparison remains source-identifiable.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {execFileSync}=require('node:child_process'),{performance}=require('node:perf_hooks'),Module=require('node:module');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),relative='web/engine/choreography-quality.js';
const baselineRef=process.argv[2]||'1cdc96773b2a5c54411d2a7170a799dd19efd7ea';
const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
function load(source){
  const filename=path.join(root,relative),module=new Module(filename,moduleParent);
  module.filename=filename;module.paths=Module._nodeModulePaths(path.dirname(filename));module._compile(source,filename);return module.exports;
}
const moduleParent=module,baselineSource=execFileSync('git',['show',baselineRef+':'+relative],{cwd:root,encoding:'utf8'});
const candidateSource=fs.readFileSync(path.join(root,relative),'utf8'),baseline=load(baselineSource),candidate=load(candidateSource);
const Engine=require('../web/engine/show-engine.js');
const music=JSON.parse(fs.readFileSync(path.join(root,'qa/release-1.6.0/actual-music-user-glass-prefix64-analysis.json')));
const recorded=Engine.generate(music,{style:'cinematic',dance:'balanced',seed:2025});
const duration=240,beats=Array.from({length:duration*2},(_,i)=>i/2);
const synthetic=Engine.generate({duration,bpm:120,beatConfidence:.9,beats,downbeats:beats.filter((_,i)=>i%4===0),onsets:[],waveform:Array(1200).fill(.65),sections:[{start:0,end:120,energy:.5,label:'A'},{start:120,end:duration,energy:.8,label:'B'}]},{dance:'balanced',seed:2025});
const median=values=>values.slice().sort((a,b)=>a-b)[Math.floor(values.length/2)];
const cases=[];
for(const [name,show] of [['recorded-analysis-64s',recorded],['synthetic-240s',synthetic]])for(const [configuration,options] of [['default',{}],['all-output-duration-checks',{minimumDurationMs:100,minimumRepeatIntervalMs:100}]]){
  const before=sha(show.frames),expected=baseline.evaluate(show,options);
  assert.deepEqual(candidate.evaluate(show,options),expected,'All report fields must remain identical');
  const timings={baseline:[],candidate:[]};
  for(let round=0;round<12;round++){
    const order=round%2?['candidate','baseline']:['baseline','candidate'];
    for(const id of order){
      const start=performance.now(),result=({baseline,candidate})[id].evaluate(show,options),elapsed=performance.now()-start;
      assert.deepEqual(result,expected,'Warmup and measured reports must remain identical');
      if(round>=3)timings[id].push(elapsed);
    }
  }
  assert.equal(sha(show.frames),before,'Read-only analysis must preserve all FSEQ bytes');
  const baselineMs=median(timings.baseline),candidateMs=median(timings.candidate);
  cases.push({name,configuration,frameCount:show.frameCount,frameSha256:before,reportSha256:sha(JSON.stringify(expected)),baselineMs,candidateMs,reductionPercent:(1-candidateMs/baselineMs)*100,timingsMs:timings,exactReports:true,unchangedFrames:true});
}
console.log(JSON.stringify({schema:'lightforge.choreography-quality-benchmark.v1',completedAt:new Date().toISOString(),scope:'Paired alternating Node host quality-diagnostics stage only. Not neural analysis, whole-song generation, Android or physical vehicle performance.',runtime:process.version,baselineRef,sourceHashes:{baseline:sha(baselineSource),candidate:sha(candidateSource)},warmups:3,measurements:9,cases},null,2));
