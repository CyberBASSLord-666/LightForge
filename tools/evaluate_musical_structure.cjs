#!/usr/bin/env node
'use strict';
// Reuse a saved approved beat map and the production WAV/DSP frontend. This is
// a structure/composition comparison, not a rerun or accuracy test of models.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),crypto=require('node:crypto'),{performance}=require('node:perf_hooks');
const ROOT=path.resolve(__dirname,'..');
const args={};for(let i=2;i<process.argv.length;i+=2){if(!process.argv[i].startsWith('--')||!process.argv[i+1])throw Error('Expected --wav PATH --project PATH --output PATH [--baseline-dsp PATH]');args[process.argv[i].slice(2)]=process.argv[i+1];}
for(const key of ['wav','project','output'])if(!args[key])throw Error('Missing --'+key);
const digest=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
function load(source){const context=vm.createContext({console});context.self=context;vm.runInContext(source.replace('scope.LightForgeDSP={FFT,','scope.LightForgeDSP={sectionsFromFeatures,phrasesAndImpacts,FFT,'),context);return context.LightForgeDSP;}
const currentSource=fs.readFileSync(path.join(ROOT,'web/analysis/dsp.js'),'utf8'),current=load(currentSource),baseline=args['baseline-dsp']?load(fs.readFileSync(args['baseline-dsp'],'utf8')):null;
const projectBytes=fs.readFileSync(args.project),project=JSON.parse(projectBytes),music=project.music;
if(!music||!Number.isFinite(music.duration)||!Array.isArray(music.beats)||!Array.isArray(music.sections))throw Error('Expected a LightForge project with saved analysis.');
const config=JSON.parse(fs.readFileSync(path.join(ROOT,'web/analysis/models/features.json'))),wav=fs.readFileSync(args.wav),WavReader=require('../web/analysis/wav-reader.js');
global.fetch=async(url,options)=>{const range=/^bytes=(\d+)-(\d+)$/.exec(options?.headers?.Range||'');if(!range)throw Error('Only bounded production WAV reads are supported.');const start=Number(range[1]),end=Math.min(Number(range[2]),wav.length-1);return new Response(wav.subarray(start,end+1),{status:206,headers:{'Content-Range':`bytes ${start}-${end}/${wav.length}`,'Content-Length':String(end-start+1)}});};
(async()=>{
 const reader=new WavReader('local-audit');await reader.open();if(Math.abs(reader.duration-music.duration)>1/reader.rate)throw Error('Project and WAV durations do not match.');
 const started=performance.now(),n=Math.ceil(reader.duration*50),data={duration:reader.duration,rms:new Float32Array(n),colour:new Float32Array(n*3),chroma:new Float32Array(Math.ceil(n/10)*12),chromaStep:.2},extractor=new current.FeatureExtractor(config);
 for(let first=0;first<n;first+=500){const frames=Math.min(500,n-first),samples=await reader.mono22050(first*441-705,(frames-1)*441+1411,config),features=extractor.extract(samples,0,frames);data.rms.set(features.rms,first);data.colour.set(features.colour,first*3);for(let i=0;i<frames;i++)for(let b=0;b<12;b++)data.chroma[Math.floor((first+i)/10)*12+b]+=features.chroma[i*12+b]/10;}
 const extractionMs=performance.now()-started;
 function evaluate(dsp,enhanced){const start=performance.now(),tonal=enhanced?dsp.tonalStructure(data,music):null,structure=dsp.sectionsFromFeatures(data.rms,data.colour,music,data.duration,tonal);dsp.recurringSections(structure.sections,data);const landmarks=dsp.phrasesAndImpacts(music,structure,music.onsets||[],data.duration);return {milliseconds:performance.now()-start,tonal,structure,landmarks};}
 const next=evaluate(current,true),old=baseline?evaluate(baseline,false):null,engine=require('../web/engine/show-engine.js');
 function composition(result){const show=engine.generate({...music,sections:result.structure.sections,energy:result.structure.energy,...result.landmarks},{...project.settings,semanticChoreography:false,vocalChoreography:false,motifEvolution:false});return {frameSha256:digest(show.frames),valid:show.validation.valid,sectionCount:show.sections.length,phraseCount:result.landmarks.phrases.length,synchronization:show.synchronization};}
 function summarize(result){if(!result)return null;return {structuralAnalysisMs:result.milliseconds,sections:result.structure.sections,phrases:result.landmarks.phrases,tonal:result.tonal,composition:composition(result)};}
 const result={schemaVersion:1,scope:'Original supplied audio, production DSP frontend, unchanged saved beat map; structure and default-composer comparison only. Detector accuracy and listener preference are not established.',source:{projectSha256:digest(projectBytes),audioSha256:digest(wav),duration:reader.duration,beatCount:music.beats.length,downbeatCount:music.downbeats.length},implementation:{currentDspSha256:digest(currentSource),baselineDspSha256:args['baseline-dsp']?digest(fs.readFileSync(args['baseline-dsp'])):null},featureExtractionMs:extractionMs,baseline:summarize(old),candidate:summarize(next)};
 fs.writeFileSync(args.output,JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify({output:args.output,featureExtractionMs:extractionMs,baselineSections:old?.structure.sections.length,candidateSections:next.structure.sections.length,baselinePhrases:old?.landmarks.phrases.length,candidatePhrases:next.landmarks.phrases.length,tonalSectionCandidates:next.tonal.sections.length,tonalPhraseCandidates:next.tonal.phrases.length,currentStructuralAnalysisMs:next.milliseconds}));
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
