#!/usr/bin/env node
'use strict';
// Full public-demo frontend comparison. No inference, phone, or whole-job claim.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),os=require('node:os'),assert=require('node:assert/strict'),{performance}=require('node:perf_hooks');
const ROOT=path.resolve(__dirname,'..');
const priorPath='tests/fixtures/performance/vocal-frontend-2.3.2.cjs',currentPath='web/analysis/vocal.js';
const {logMel:prior}=require(path.join(ROOT,priorPath)),current=require(path.join(ROOT,currentPath)),WavReader=require(path.join(ROOT,'web/analysis/wav-reader.js'));
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const bytes=values=>Buffer.from(values.buffer,values.byteOffset,values.byteLength);
const median=values=>values.slice().sort((a,b)=>a-b)[Math.floor(values.length/2)];
function option(name,fallback){const at=process.argv.indexOf(name);return at<0?fallback:process.argv[at+1];}
async function main(){
 const output=option('--output',null),rounds=Number(option('--rounds','7'));assert.ok(output,'--output NEW_FILE is required');assert.ok(Number.isInteger(rounds)&&rounds>=3&&rounds<=31,'use 3–31 measured rounds');
 if(fs.existsSync(output))throw Error('Refusing to replace an existing benchmark receipt.');
 const fixture='web/demo/glass-castle.wav',audio=fs.readFileSync(path.join(ROOT,fixture)),reader=new WavReader('');reader.totalBytes=audio.length;reader.bytes=async(start,end)=>audio.buffer.slice(audio.byteOffset+start,audio.byteOffset+Math.min(audio.length,end+1));await reader.open();
 const configPath='web/analysis/models/features.json',frontendPath='web/analysis/models/vocal-frontend.json',config=JSON.parse(fs.readFileSync(path.join(ROOT,configPath))),frontend=JSON.parse(fs.readFileSync(path.join(ROOT,frontendPath))),starts=current.chunkStarts(reader.duration),windows=[];
 for(const first of starts)windows.push({start:first*640,pcm:await current.pcm16000(reader,first*640,160000,config)});
 const expected=windows.map(({pcm})=>prior(pcm,frontend)),expectedDigest=crypto.createHash('sha256');for(const features of expected)expectedDigest.update(bytes(features));
 const variants=['released-2.3.2','fixed-twiddles','fixed-twiddles-and-overlap'],measurements=Object.fromEntries(variants.map(name=>[name,[]]));let reusedFrames=null,computedFrames=null;
 function execute(name){
  global.gc?.();const at=performance.now(),mel=name==='fixed-twiddles-and-overlap'?new current.MelFrontend(frontend):null,outputs=[];let reused=0,computed=0;
  for(const {pcm,start}of windows){outputs.push(mel?mel.extract(pcm,start):name==='released-2.3.2'?prior(pcm,frontend):current.logMel(pcm,frontend));if(mel){reused+=mel.reusedFrames;computed+=mel.computedFrames;}}
  mel?.clear();const wallMs=performance.now()-at;
  for(let i=0;i<outputs.length;i++)assert.ok(bytes(outputs[i]).equals(bytes(expected[i])),name+' changed Float32 features in window '+i);
  if(mel){reusedFrames=reused;computedFrames=computed;}return wallMs;
 }
 for(let warmup=0;warmup<2;warmup++)for(const name of variants)execute(name);
 const orders=[];for(let round=0;round<rounds;round++){const order=variants.slice(round%3).concat(variants.slice(0,round%3));orders.push(order);for(const name of order)measurements[name].push(execute(name));}
 const summary={};for(const name of variants){const values=measurements[name];summary[name]={medianWallMs:median(values),minWallMs:Math.min(...values),maxWallMs:Math.max(...values),samplesWallMs:values};}
 const baseline=summary['released-2.3.2'].medianWallMs;for(const name of variants.slice(1))summary[name].medianWallReductionPercent=(1-summary[name].medianWallMs/baseline)*100;
 const sources={};for(const file of [priorPath,currentPath,configPath,frontendPath,'web/analysis/wav-reader.js','tools/benchmark_vocal_frontend.cjs']){const data=fs.readFileSync(path.join(ROOT,file));sources[file]={bytes:data.length,sha256:hash(data)};}
 const receipt={schemaVersion:1,kind:'vocal-frontend-exact-equivalence-benchmark',createdAt:new Date().toISOString(),scope:'Every original Frame-MN10 log-mel window of the complete public demo; prepared 16 kHz PCM input; model inference, resampling, reader IO, and whole-analysis time excluded.',baselineCommit:'1cdc96773b2a5c54411d2a7170a799dd19efd7ea',runtime:{node:process.version,v8:process.versions.v8,platform:process.platform,architecture:process.arch,cpuModel:os.cpus()[0]?.model||null,logicalCpus:os.cpus().length,gcBeforeEachTrial:typeof global.gc==='function'},fixture:{path:fixture,bytes:audio.length,sha256:hash(audio),seconds:reader.duration,windows:windows.length,sampleStarts:windows.map(window=>window.start)},method:{warmupsPerVariant:2,measuredRounds:rounds,orders,comparison:'All Float32 feature bytes compared after every warmup and measured trial; any mismatch aborts without a receipt.'},equivalence:{allFeatureBytesIdentical:true,featuresSHA256:expectedDigest.digest('hex'),float32ValuesPerTrial:expected.reduce((sum,x)=>sum+x.length,0),computedFrames,reusedFrames,retainedCacheBytes:4*(160000+128000)},measurements:summary,sources,limitations:['Host JavaScript frontend timing only; not Android, neural inference or end-to-end speedup.','Single public fixture; no general musical-quality claim.','Retained cache bytes are the explicit arrays, not measured peak application memory.','The 75 percent complete-analysis target remains unmeasured.']};
 fs.mkdirSync(path.dirname(path.resolve(output)),{recursive:true});fs.writeFileSync(output,JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify({output,summary,reusedFrames,computedFrames,allFeatureBytesIdentical:true},null,2));
}
main().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
