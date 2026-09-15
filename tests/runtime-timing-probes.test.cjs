'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
// Lightweight ORT doubles exercise production adapter dispatch and arithmetic;
// they are not model quality, runtime speed, or native inference benchmarks.
const MDX=require('../web/analysis/separator-mdx.js');
const DEUX=require('../web/analysis/separator-deux.js');
const GAME=require('../web/analysis/game.js');
const VOCAL=require('../web/analysis/vocal.js');
const P='performance.';
function timing(){
 const open=new Set(),events=[];
 const begin=name=>{assert.equal(open.size,0,'canonical subphases must be disjoint');open.add(name);events.push(['begin',name]);};
 const end=name=>{assert.equal(open.delete(name),true);events.push(['end',name]);};
 return {open,events,measure(name,fn){begin(name);try{return fn();}finally{end(name);}},async measureAsync(name,fn){begin(name);try{return await fn();}finally{end(name);}},
  inside(name){assert.deepEqual([...open],[P+name]);},outside(){assert.equal(open.size,0);},count(name){return events.filter(([kind,label])=>kind==='end'&&label===P+name).length;}};
}
class Tensor{constructor(type,data,dims){Object.assign(this,{type,data,dims});}dispose(){this.disposed=true;}}
const value=(data,dims=[data.length])=>new Tensor('float32',data,dims);
const mdxManifest={id:'mdx-test',sampleRate:44100,nFFT:7680,file:'mdx.onnx',sha256:'a'.repeat(64),compensate:1};
async function mdxCase({telemetry,native=false,restored=false,fail=false}={}){
 const previousDSP=global.LightForgeDSP,encode=MDX.Frontend.prototype.encode,decode=MDX.Frontend.prototype.decode;
 global.LightForgeDSP={FFT:class {run(){}}};
 MDX.Frontend.prototype.encode=function(){telemetry?.inside('preprocessing');const x=new Float32Array(4*3072*256);x[0]=.75;return x;};
 MDX.Frontend.prototype.decode=function(prediction){telemetry?.inside('postprocessing');return new Float32Array(MDX.constants.INPUT_LENGTH).fill(prediction[0]);};
 let creates=0,runs=0,nativeRuns=0,releases=0;const outputs=[];
 const ort={Tensor,InferenceSession:{create:async()=>{telemetry?.inside('model_initialization');creates++;return {inputNames:['input'],outputNames:['output'],async run({input}){telemetry?.inside('model_inference');runs++;if(fail)throw Error('mdx run failed');return {output:value(Float32Array.from(input.data,x=>x*2))};},async release(){telemetry?.outside();releases++;}};}}};
 const nativePredict=native?async input=>{telemetry?.outside();nativeRuns++;return Float32Array.from(input,x=>x*2);}:undefined;
 const checkpoint={async readFloats(){telemetry?.outside();return restored?[new Float32Array(MDX.constants.INPUT_LENGTH).fill(1.5)]:null;},async writeFloats(){telemetry?.outside();}};
 let separator;
 try{separator=await MDX.create({ort,manifest:mdxManifest,telemetry,nativePredict,checkpoint});
  const read=async()=>{telemetry?.outside();return [new Float32Array(MDX.constants.INPUT_LENGTH).fill(.1),new Float32Array(MDX.constants.INPUT_LENGTH).fill(.2)];};
  const process=separator.process(read,441,chunk=>{telemetry?.outside();outputs.push(chunk);},()=>telemetry?.outside());
  if(fail)await assert.rejects(process,/mdx run failed/);else await process;
  return {creates,runs,nativeRuns,outputs};
 }finally{await separator?.release();assert.equal(releases,creates);global.LightForgeDSP=previousDSP;MDX.Frontend.prototype.encode=encode;MDX.Frontend.prototype.decode=decode;}
}
test('MDX times both ensemble calls and preserves output; restores and native calls do not claim WASM inference',async()=>{
 const reference=await mdxCase(),telemetry=timing(),observed=await mdxCase({telemetry});
 assert.deepEqual(observed,reference);assert.equal(telemetry.count('model_initialization'),1);assert.equal(telemetry.count('model_inference'),2);telemetry.outside();
 for(const mode of [{native:true},{restored:true}]){const t=timing(),result=await mdxCase({...mode,telemetry:t});assert.deepEqual(result.outputs,reference.outputs);assert.equal(t.count('model_initialization'),0);assert.equal(t.count('model_inference'),0);t.outside();}
});
test('an MDX rejected run closes inference timing and retains release behavior',async()=>{
 const telemetry=timing(),result=await mdxCase({telemetry,fail:true});assert.equal(result.runs,1);assert.equal(telemetry.count('model_inference'),1);telemetry.outside();
});
function gameOrt(telemetry,log,failName){
 return {Tensor,InferenceSession:{create:async url=>{telemetry?.inside('model_initialization');const name=url.split('/').pop().replace('.onnx','');log.push(['create',name]);return {async run(feed){telemetry?.inside('model_inference');log.push(['run',name,Object.fromEntries(Object.entries(feed).map(([k,v])=>[k,{dims:v.dims,data:Array.from(v.data,x=>typeof x==='bigint'?String(x):x)}]))]);if(name===failName)throw Error('game run failed');
  if(name==='encoder')return {maskT:value(Float32Array.of(1,1,1,1),[1,4]),x_seg:value(Float32Array.of(.2)),x_est:value(Float32Array.of(.3))};
  if(name==='dur2bd'||name==='segmenter')return {boundaries:value(Float32Array.of(1,0,1,0),[1,4])};
  if(name==='bd2dur')return {durations:value(Float32Array.of(.25,.75)),maskN:value(Float32Array.of(1,1))};
  return {scores:value(Float32Array.of(60,64)),presence:value(Float32Array.of(1,1))};
 },async release(){telemetry?.outside();log.push(['release',name]);}};}}};
}
async function gameCase(telemetry,failName){
 const old=global.fetch;global.fetch=async()=>({json:async()=>({id:'game-test'})});const log=[];let game;
 try{game=await GAME.create({ort:gameOrt(telemetry,log,failName),baseUrl:'https://models.invalid/game/',telemetry,onProgress:()=>telemetry?.outside()});
  const pending=game.infer(Float32Array.of(.1,.2,.3),0,2025,()=>telemetry?.outside());
  if(failName){await assert.rejects(pending,/game run failed/);return {log};}
  return {notes:await pending,log};
 }finally{await game?.release();global.fetch=old;}
}
test('GAME times five session creations and all twelve runs without changing diffusion inputs or notes',async()=>{
 const reference=await gameCase(),telemetry=timing(),observed=await gameCase(telemetry);
 assert.deepEqual(observed,reference);assert.equal(telemetry.count('model_initialization'),5);assert.equal(telemetry.count('model_inference'),12);assert.equal(telemetry.count('preprocessing'),8);assert.equal(telemetry.count('postprocessing'),1);telemetry.outside();
 assert.deepEqual(observed.notes,[{start:0,end:.25,midi:60},{start:.25,end:1,midi:64}]);
});
test('a failed GAME diffusion run closes its span and releases all five sessions',async()=>{
 const telemetry=timing(),result=await gameCase(telemetry,'segmenter');assert.equal(telemetry.count('model_inference'),3);assert.equal(result.log.filter(([op])=>op==='release').length,5);telemetry.outside();
});
test('GAME restored passages stitch notes outside persistence and never report model execution',async()=>{
 const old=global.fetch;global.fetch=async()=>({json:async()=>({id:'game-test'})});const telemetry=timing();let game;
 try{game=await GAME.create({ort:{InferenceSession:{create(){assert.fail('restored passages must not load models');}}},baseUrl:'https://models.invalid/game/',telemetry,checkpoint:{async read(){telemetry.outside();return {first:0,last:44100,model:'game-test',steps:8,notes:[{start:.1,end:.9,midi:63.25}]};},async write(){assert.fail('restored passage must not rewrite checkpoint');}}});
  const result=await game.process(()=>assert.fail('restored passage must not reread PCM'),44100,{onProgress:()=>telemetry.outside()});assert.equal(result.notes[0].start,.1);assert.equal(result.notes[0].end,.9);assert.equal(telemetry.count('model_inference'),0);assert.equal(telemetry.count('model_initialization'),0);assert.equal(telemetry.count('postprocessing'),2);
 }finally{await game?.release();global.fetch=old;}
});
async function vocalCase(telemetry){
 const old=global.location;global.location={href:'https://models.invalid/worker.js'};
 const reader={duration:.12,async mono22050(first,count){telemetry?.outside();return Float32Array.from({length:count},(_,i)=>Math.sin((first+i)*.017)*.1);}};
 const model={name:'vocal-test',id:'vocal-test',file:'vocal.onnx',sha256:'a'.repeat(64),license:'MIT',singingClassIds:[0],speechClassIds:[1]},frontend={windowValues:Array.from({length:400},(_,i)=>.5-.5*Math.cos(2*Math.PI*i/399)),melWeights:Array.from({length:128},(_,i)=>[[i+1,1]])};
 let creates=0,runs=0,releases=0,features;
 const ort={Tensor,InferenceSession:{create:async()=>{telemetry?.inside('model_initialization');creates++;return {async run({log_mel}){telemetry?.inside('model_inference');runs++;features=log_mel.data.slice();return {scores:value(Float32Array.from({length:500},(_,i)=>i<250?.65:.1))};},async release(){telemetry?.outside();releases++;}};}}};
 try{const result=await VOCAL.analyze(reader,{}, {ort,model,frontend,telemetry,includeDiagnostics:true,includeClassifierScores:true,report:()=>telemetry?.outside()});return {result,features,creates,runs,releases};}finally{global.location=old;}
}
test('vocal resampling, logMel features and scoring retain exact outputs and exclude reader I/O',async()=>{
 const reference=await vocalCase(),telemetry=timing(),observed=await vocalCase(telemetry);assert.deepEqual(observed,reference);
 assert.equal(telemetry.count('resample_normalize'),1);assert.equal(telemetry.count('feature_generation'),2);assert.equal(telemetry.count('model_initialization'),1);assert.equal(telemetry.count('model_inference'),1);assert.equal(telemetry.count('postprocessing'),2);telemetry.outside();
});
test('DEUX times every bounded WASM graph batch and ends spans before progress and decoding',async()=>{
 const previousDSP=global.LightForgeDSP,previousFetch=global.fetch,encode=DEUX.Transform.prototype.encode,decode=DEUX.Transform.prototype.decode,telemetry=timing();
 global.LightForgeDSP={FFT:class {run(){}}};
 const manifest={id:'deux-test',execution:'bounded-independent-batches-v1',headFrames:128,frames:1301,samples:573300,indices:Array(3958).fill(0),bandsPerFrequency:Array(1025).fill(1)};
 global.fetch=async()=>({json:async()=>manifest});
 DEUX.Transform.prototype.encode=function(){telemetry.inside('preprocessing');return Float32Array.of(.125);};
 DEUX.Transform.prototype.decode=function(spectrum,mask){telemetry.inside('postprocessing');assert.equal(spectrum[0],.125);assert.equal(mask[0],mask[mask.length-1]);return Float32Array.of(mask[0]);};
 const creations=[],runs=[],releases=[];
 const ort={Tensor,InferenceSession:{create:async url=>{telemetry.inside('model_initialization');const name=url.split('/').pop().replace('.onnx','');creations.push(name);return {async run({input}){telemetry.inside('model_inference');runs.push(name);
  if(name==='front')return {output:value(new Float32Array(1301*60*256).fill(.125))};
  if(name.startsWith('head-'))return {output:value(new Float32Array(3958*input.dims[1]*2).fill(name==='head-0'?.25:.75))};
  assert.equal(input.data[0],.125);assert.equal(input.data[input.data.length-1],.125);return {output:value(input.data,input.dims)};
 },async release(){telemetry.outside();releases.push(name);}};}}};let separator;
 try{separator=await DEUX.create({ort,baseUrl:'https://models.invalid/deux/',telemetry});const out=await separator.predict([],()=>telemetry.outside());
  assert.deepEqual(out,{vocals:Float32Array.of(.25),accompaniment:Float32Array.of(.75)});
  assert.equal(creations.length,27);assert.equal(runs.length,335);assert.deepEqual(releases,creations);assert.equal(telemetry.count('model_initialization'),27);assert.equal(telemetry.count('model_inference'),335);telemetry.outside();
 }finally{await separator?.release();global.LightForgeDSP=previousDSP;global.fetch=previousFetch;DEUX.Transform.prototype.encode=encode;DEUX.Transform.prototype.decode=decode;}
});
