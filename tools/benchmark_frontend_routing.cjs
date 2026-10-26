#!/usr/bin/env node
'use strict';
// Bounded host experiment. Supply a directory containing frozen pre-change dsp.js.
// No model inference, downloads, release admission or whole-job speed claims.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{performance}=require('node:perf_hooks');
const root=path.resolve(__dirname,'..'),baselineDirectory=process.argv[2];
if(!baselineDirectory)throw new Error('Usage: node tools/benchmark_frontend_routing.cjs /path/to/frozen/baseline-directory');
// Keep normal host intrinsics and separate module namespaces. VM-context Math
// lookups introduce overhead that does not represent the production worker.
function load(directory){const namespace={};new Function('self',fs.readFileSync(path.join(directory,'dsp.js'),'utf8'))(namespace);return namespace;}
const baseline=load(baselineDirectory),candidate=load(path.join(root,'web/analysis')),config=JSON.parse(fs.readFileSync(path.join(root,'web/analysis/models/features.json')));
const frames=500,halo=4644,samples=new Float32Array((frames-1)*441+2*halo+1);let seed=32973;
for(let i=0;i<samples.length;i++){seed=(Math.imul(seed,1664525)+1013904223)>>>0;const time=i/22050,envelope=time%3<.18?0:.6+.4*Math.sin(time*1.7);samples[i]=envelope*(.22*Math.sin(2*Math.PI*55*time)+.13*Math.sin(2*Math.PI*440*time)+.015*(seed/4294967296-.5));}
function equalFeatures(left,right){assert.equal(Object.keys(left).join(),Object.keys(right).join());for(const key of Object.keys(left))if(ArrayBuffer.isView(left[key])){assert.ok(left[key].every(Number.isFinite),key);assert.equal(Buffer.compare(Buffer.from(left[key].buffer,left[key].byteOffset,left[key].byteLength),Buffer.from(right[key].buffer,right[key].byteOffset,right[key].byteLength)),0,key);}else assert.equal(left[key],right[key],key);}
const sourceConfigs=[structuredClone(config),structuredClone(config)],extractors=[new baseline.LightForgeDSP.FeatureExtractor(sourceConfigs[0]),new candidate.LightForgeDSP.FeatureExtractor(sourceConfigs[1])];
for(const count of [0,1,17,frames])equalFeatures(extractors[0].extract(samples,0,count),extractors[1].extract(samples,0,count));
for(const frequency of [59.999,60,179.999,180,2399.999,2400,4000,4000.001,NaN,Infinity,-Infinity]){for(const cfg of sourceConfigs)cfg.bands[0].frequency=frequency;equalFeatures(extractors[0].extract(samples,3,7),extractors[1].extract(samples,3,7));}
for(const cfg of sourceConfigs)cfg.bands=structuredClone(config.bands);equalFeatures(extractors[0].extract(samples,3,33),extractors[1].extract(samples,3,33));
// Fresh extractors measure the production configuration; exclude one warmup pair.
const feature=[new baseline.LightForgeDSP.FeatureExtractor(config),new candidate.LightForgeDSP.FeatureExtractor(config)];
function measure(fn){const cpu=process.cpuUsage(),start=performance.now();fn();const wallMs=performance.now()-start,used=process.cpuUsage(cpu);return {wallMs,cpuMs:(used.user+used.system)/1000};}
for(let i=0;i<2;i++)feature[i].extract(samples,0,frames);
const timing={features:{baseline:[],candidate:[]}};
for(let pair=0;pair<5;pair++)for(const index of pair%2?[1,0]:[0,1]){const key=index?'candidate':'baseline';timing.features[key].push(measure(()=>feature[index].extract(samples,0,frames)));}
const median=values=>values.slice().sort((a,b)=>a-b)[Math.floor(values.length/2)];
for(const stage of Object.values(timing))for(const key of ['baseline','candidate'])stage[key+'Median']={wallMs:median(stage[key].map(row=>row.wallMs)),cpuMs:median(stage[key].map(row=>row.cpuMs))};
console.log(JSON.stringify({scope:'Bounded synthetic PCM host frontend experiment; not model, whole-analysis, Android or release qualification',frames,byteIdenticalFeatureArrays:true,excludedWarmupPairs:1,alternatingMeasuredPairs:5,timing},null,2));
