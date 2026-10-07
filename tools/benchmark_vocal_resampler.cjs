#!/usr/bin/env node
'use strict';
// Public-demo resampling comparison. Prepared reads exclude IO; no model/phone claim.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),os=require('node:os'),assert=require('node:assert/strict'),{performance}=require('node:perf_hooks');
const ROOT=path.resolve(__dirname,'..'),priorPath='tests/fixtures/performance/vocal-resampler-de831259.cjs',currentPath='web/analysis/vocal.js';
const {pcm16000:prior}=require(path.join(ROOT,priorPath)),current=require(path.join(ROOT,currentPath)),WavReader=require(path.join(ROOT,'web/analysis/wav-reader.js'));
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex'),bytes=a=>Buffer.from(a.buffer,a.byteOffset,a.byteLength),median=a=>a.slice().sort((a,b)=>a-b)[Math.floor(a.length/2)];
function option(name,fallback){const at=process.argv.indexOf(name);return at<0?fallback:process.argv[at+1];}
async function main(){
 const output=option('--output',null),rounds=Number(option('--rounds','7'));assert.ok(output,'--output NEW_FILE is required');assert.ok(Number.isInteger(rounds)&&rounds>=3&&rounds<=31);
 if(fs.existsSync(output))throw Error('Refusing to replace an existing benchmark receipt.');
 const fixture='web/demo/glass-castle.wav',audio=fs.readFileSync(path.join(ROOT,fixture)),reader=new WavReader('');reader.totalBytes=audio.length;reader.bytes=async(start,end)=>audio.buffer.slice(audio.byteOffset+start,audio.byteOffset+Math.min(audio.length,end+1));await reader.open();
 const configPath='web/analysis/models/features.json',config=JSON.parse(fs.readFileSync(path.join(ROOT,configPath))),starts=current.chunkStarts(reader.duration).map(x=>x*640),reads=[],expected=[];
 for(const start of starts){const recording={async mono22050(first,count,c){const raw=await reader.mono22050(first,count,c);reads.push({first,count,raw});return raw;}};expected.push(await prior(recording,start,160000,config));}
 const variants=['reference-de831259','verified-overlap'],measurements=Object.fromEntries(variants.map(name=>[name,[]]));let reusedSamples=0,computedSamples=0,maxRetainedCacheBytes=0;
 async function execute(name){
  global.gc?.();let index=0,reused=0,computed=0,maxBytes=0;const cache=name==='verified-overlap'?new current.VocalResampler():null,outputs=[];
  const prepared={async mono22050(first,count){const r=reads[index++];assert.equal(first,r.first);assert.equal(count,r.count);return r.raw;}};
  const at=performance.now();for(const start of starts){outputs.push(await(cache?current.pcm16000(prepared,start,160000,config,null,cache):prior(prepared,start,160000,config)));if(cache){reused+=cache.reusedSamples;computed+=cache.computedSamples;maxBytes=Math.max(maxBytes,cache.retainedBytes);}}
  cache?.clear();const wallMs=performance.now()-at;assert.equal(index,starts.length);
  for(let i=0;i<outputs.length;i++)assert.ok(bytes(outputs[i]).equals(bytes(expected[i])),name+' changed Float32 output at '+starts[i]);
  if(cache){assert.equal(cache.retainedBytes,0);reusedSamples=reused;computedSamples=computed;maxRetainedCacheBytes=maxBytes;}return wallMs;
 }
 for(let warmup=0;warmup<2;warmup++)for(const name of variants)await execute(name);
 const orders=[];for(let round=0;round<rounds;round++){const order=round%2?variants.slice().reverse():variants;orders.push(order);for(const name of order)measurements[name].push(await execute(name));}
 const summary={};for(const name of variants){const samples=measurements[name];summary[name]={medianWallMs:median(samples),minWallMs:Math.min(...samples),maxWallMs:Math.max(...samples),samplesWallMs:samples};}
 summary['verified-overlap'].medianWallReductionPercent=(1-summary['verified-overlap'].medianWallMs/summary['reference-de831259'].medianWallMs)*100;
 const sources={};for(const file of [priorPath,currentPath,configPath,'web/analysis/wav-reader.js','tools/benchmark_vocal_resampler.cjs']){const data=fs.readFileSync(path.join(ROOT,file));sources[file]={bytes:data.length,sha256:hash(data)};}
 const digest=crypto.createHash('sha256');for(const pcm of expected)digest.update(bytes(pcm));
 const receipt={schemaVersion:1,kind:'vocal-resampler-exact-equivalence-benchmark',createdAt:new Date().toISOString(),scope:'Every original 16 kHz Frame-MN10 resampled window of complete public demo; source reads prepared outside timing; includes bit validation and cache snapshots; excludes IO, mel extraction, neural inference and complete analysis.',baselineCommit:'de831259',runtime:{node:process.version,v8:process.versions.v8,platform:process.platform,architecture:process.arch,cpuModel:os.cpus()[0]?.model,logicalCpus:os.cpus().length,gcBeforeEachTrial:typeof global.gc==='function'},fixture:{path:fixture,bytes:audio.length,sha256:hash(audio),seconds:reader.duration,sampleStarts:starts},method:{warmupsPerVariant:2,measuredRounds:rounds,orders,comparison:'Every output Float32 byte and original reader request checked on every warmup and measured trial; any mismatch aborts.'},equivalence:{allOutputBytesIdentical:true,outputSHA256:digest.digest('hex'),float32ValuesPerTrial:expected.reduce((n,a)=>n+a.length,0),reusedSamples,computedSamples,maxRetainedCacheBytes},measurements:summary,sources,limitations:['Host resampling only; no whole-song or phone speedup claim.','Retained array bytes are not peak process memory.','Single public fixture; no general musical-quality claim.','Actual-model execution is not part of this benchmark; downstream model gate remains required.']};
 fs.mkdirSync(path.dirname(path.resolve(output)),{recursive:true});fs.writeFileSync(output,JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify({output,summary,...receipt.equivalence},null,2));
}
main().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
