'use strict';
const fs=require('fs'),path=require('path'),crypto=require('crypto'),cp=require('child_process'),assert=require('assert/strict');
const root=path.resolve(__dirname,'../..');process.chdir(root);
require('../../web/analysis/dsp.js');require('../../web/analysis/bass-notes.js');const WavReader=require('../../web/analysis/wav-reader.js');
const config=JSON.parse(fs.readFileSync('web/analysis/models/features.json'));
const sha=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
(async()=>{
 const tests=cp.execFileSync(process.execPath,['--test','tests/bass-notes.test.cjs'],{encoding:'utf8'});fs.writeFileSync(path.join(__dirname,'bass-test.log'),tests);
 const sources=['web/analysis/bass-notes.js','web/analysis/dsp.js','web/analysis/wav-reader.js','tests/bass-notes.test.cjs','qa/release-1.6.0/verify-bass-analysis.cjs'],real=[];
 for(const [name,file]of [['Sample','sample.wav'],['Glass Castle available prefix','glass-castle.wav']]){
  const full=path.join(root,'qa/release-1.5.0/fixtures',file);if(!fs.existsSync(full))continue;
  const bytes=fs.readFileSync(full),reader=new WavReader('memory:'+file);reader.cached=bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength);reader.totalBytes=bytes.length;await reader.open();
  const start=performance.now(),result=await LightForgeBass.analyze(reader,config),elapsedMs=Math.round(performance.now()-start);
  assert.equal(result.envelope.length,Math.ceil(reader.duration*50));assert.ok(result.notes.every(n=>Number.isFinite(n.frequency)&&n.start>=0&&n.end<=reader.duration&&n.end>n.start&&n.frequency>=30&&n.frequency<=220));assert.ok(result.envelope.every(x=>Number.isFinite(x)&&x>=0&&x<=1));
  const {envelope,...summary}=result;fs.writeFileSync(path.join(__dirname,'bass-'+file.replace('.wav','.json')),JSON.stringify(summary,null,2)+'\n');
  real.push({name,duration:reader.duration,preparedWavSha256:sha(full),notes:result.notes.length,phrases:result.phrases.length,confidence:result.confidence,elapsedMs,annotation:'No ground-truth pitch or note timestamps; this verifies execution, finite bounded output and timing coverage, not musical accuracy.'});
 }
 const receipt={status:'passed',version:'1.6.0',release:'1.6.0',passed:true,errors:[],generatedAt:new Date().toISOString(),sourceHashes:Object.fromEntries(sources.map(p=>[p,sha(p)])),tests:{groups:7,result:'passed',syntheticTruth:'Off-grid 41/55/73/82 Hz harmonic notes, legato changes, louder sweeping kicks 50–150 ms before/after, pure 36.7 Hz sustain, kicks/noise/silence rejection, read chunk invariance, four-hour typed summary, cancellation',onsetToleranceMs:40,closestOverlappingKickFixtureOnsetToleranceMs:80,offsetToleranceMs:50},realAudio:real,limitations:['Synthetic timing tolerances do not establish real-track accuracy. The 50 ms adjacent kick fixture has an 80 ms onset limit because closely overlapping low harmonics remain ambiguous.','Low register estimates are not source-separated bass instrument identification.','Octave ambiguity, overlapping sources, quiet bass, glides and short notes can be missed.','Actual Android device and Tesla execution are not tested here.']};
 fs.writeFileSync(path.join(__dirname,'bass-verification.json'),JSON.stringify(receipt,null,2)+'\n');console.log(JSON.stringify(receipt,null,2));
})().catch(e=>{console.error(e);process.exitCode=1;});
