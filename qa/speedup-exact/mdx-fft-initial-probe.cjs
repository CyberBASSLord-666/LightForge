'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const root='/workspace/scratch/9a5ec23b7f4b/LightForge',work=__dirname;
require(root+'/web/analysis/dsp.js');
const A=require(root+'/web/analysis/separator-mdx.js'),B=require(work+'/separator-mdx-limited.js'),Reader=require(root+'/web/analysis/wav-reader.js');
const bytes=x=>Buffer.from(x.buffer,x.byteOffset,x.byteLength),sha=x=>crypto.createHash('sha256').update(x).digest('hex');
(async()=>{
 const cases=[];
 for(const [file,start]of [['web/demo/glass-castle.wav',-3840],['web/demo/glass-castle.wav',878160],['qa/release-1.6.0/fixtures/falcon-mix.wav',-3840]]){
  const b=fs.readFileSync(path.join(root,file)),r=new Reader('');r.cached=b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength);r.totalBytes=b.length;await r.open();
  cases.push({file,start,sourceSHA256:sha(b),pcm:await r.stereo44100(start,A.constants.INPUT_LENGTH)});
 }
 let seed=7;const noise=()=>{seed^=seed<<13;seed^=seed>>>17;seed^=seed<<5;return ((seed>>>0)/4294967296-.5)*2;};
 cases.push({file:'seeded full-band stereo and edge floats',pcm:[Float32Array.from({length:A.constants.INPUT_LENGTH},noise),Float32Array.from({length:A.constants.INPUT_LENGTH},noise)]});
 cases[3].pcm[0].set(Float32Array.of(-0,0,1e-40,-1e-40,NaN,Infinity,-Infinity));
 const reports=[],timings={baseline:[],candidate:[]};
 const a=new A.Frontend(),b=new B.Frontend();
 for(let index=0;index<cases.length;index++){
  const c=cases[index],runs={};
  for(let repeat=0;repeat<3;repeat++){
   const order=repeat%2?[['candidate',b],['baseline',a]]:[['baseline',a],['candidate',b]];
   for(const [name,frontend]of order){const at=performance.now();const out=frontend.encode(c.pcm);const ms=performance.now()-at;runs[name]=out;if(index<3&&repeat>0)timings[name].push(ms);}
   assert.ok(bytes(runs.baseline).equals(bytes(runs.candidate)),'Every one of the 3,145,728 consumed float32 spectral values must match, including signed zero.');
  }
  // The inverse retains its complete geometry and exact overlap-add; encoded
  // real spectra provide a full finite decoder stress input independent of ORT.
  const decodedA=a.decode(runs.baseline),decodedB=b.decode(runs.candidate);
  assert.ok(bytes(decodedA).equals(bytes(decodedB)),'Decoded PCM changed.');
  reports.push({fixture:c.file,start:c.start,sourceSHA256:c.sourceSHA256,spectrumSHA256:sha(bytes(runs.baseline)),spectrumValues:runs.baseline.length,pcmSHA256:sha(bytes(decodedA)),pcmSamples:decodedA.length,exact:true});
 }
 const median=x=>x.slice().sort((a,b)=>a-b)[Math.floor(x.length/2)];
 const report={passed:true,scope:'Exact real/stress-input frontend comparison. Local alternating warm CPU timings; excludes inference and bridge and is not a phone benchmark.',sources:{baseline:sha(fs.readFileSync(root+'/web/analysis/separator-mdx.js')),candidate:sha(fs.readFileSync(work+'/separator-mdx-limited.js')),dsp:sha(fs.readFileSync(root+'/web/analysis/dsp.js')),probe:sha(fs.readFileSync(__filename))},cases:reports,timings,medianMilliseconds:{baseline:median(timings.baseline),candidate:median(timings.candidate)},speedup:median(timings.baseline)/median(timings.candidate)};
 fs.writeFileSync(work+'/verification.json',JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({passed:true,cases:reports.length,medianMilliseconds:report.medianMilliseconds,speedup:report.speedup}));
})().catch(e=>{console.error(e);process.exitCode=1;});
