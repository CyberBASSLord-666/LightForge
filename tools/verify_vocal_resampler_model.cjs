#!/usr/bin/env node
'use strict';
// Actual retained Frame-MN10 WASM comparison; no torch/conversion required.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),crypto=require('node:crypto'),assert=require('node:assert/strict'),cp=require('node:child_process'),os=require('node:os'),{performance}=require('node:perf_hooks');
const ROOT=path.resolve(__dirname,'..'),BASELINE='de831259',currentPath='web/analysis/vocal.js',modelPath='web/analysis/models/frame-mn10-singing.onnx',vendor='web/analysis/vendor/';
const hash=b=>crypto.createHash('sha256').update(b).digest('hex'),bytes=a=>Buffer.from(a.buffer,a.byteOffset,a.byteLength);
const at=process.argv.indexOf('--output'),output=at>=0?process.argv[at+1]:null;
async function main(){
 assert.ok(output,'--output NEW_FILE is required');assert.ok(!fs.existsSync(output),'Refusing to replace existing receipt.');
 // Bind identities before loading either implementation or any model/runtime.
 const configPath='web/analysis/models/features.json',frontendPath='web/analysis/models/vocal-frontend.json',manifestPath='web/analysis/models/vocal-model.json',fixture='web/demo/glass-castle.wav';
 const sourcePaths=[currentPath,modelPath,manifestPath,frontendPath,configPath,fixture,'web/analysis/wav-reader.js',vendor+'ort.wasm.min.js',vendor+'ort-wasm-simd-threaded.mjs',vendor+'ort-wasm-simd-threaded.wasm','tools/verify_vocal_resampler_model.cjs'];
 const sourceIdentities=()=>Object.fromEntries(sourcePaths.map(file=>{const data=fs.readFileSync(path.join(ROOT,file));return [file,{bytes:data.length,sha256:hash(data)}];}));
 const sources=sourceIdentities();
 const baselineCommit=cp.execFileSync('git',['rev-parse',BASELINE],{cwd:ROOT,encoding:'utf8'}).trim(),baselineSource=cp.execFileSync('git',['show',baselineCommit+':'+currentPath],{cwd:ROOT,encoding:'utf8'});
 const location={href:'https://lightforge.invalid/analysis/'},sandbox={module:{exports:{}},URL,Float32Array,Float64Array,Uint16Array,Uint32Array,location};vm.runInNewContext(baselineSource,sandbox,{filename:currentPath+'@'+baselineCommit});
 const baseline=sandbox.module.exports,current=require(path.join(ROOT,currentPath)),WavReader=require(path.join(ROOT,'web/analysis/wav-reader.js')),ort=require(path.join(ROOT,vendor,'ort.wasm.min.js'));
 ort.env.wasm.numThreads=4;ort.env.wasm.proxy=false;ort.env.wasm.wasmPaths=path.join(ROOT,vendor);
 const audio=fs.readFileSync(path.join(ROOT,fixture)),config=JSON.parse(fs.readFileSync(path.join(ROOT,configPath))),frontend=JSON.parse(fs.readFileSync(path.join(ROOT,frontendPath))),model=JSON.parse(fs.readFileSync(path.join(ROOT,manifestPath))),weights=fs.readFileSync(path.join(ROOT,modelPath));
 assert.equal(hash(weights),model.sha256,'Pinned vocal model must match its manifest.');
 const inputs=[],outputs=[],passes=[];let expectedResult,expectedReads;global.location=location;
 for(const [variant,implementation] of [['baseline-de831259',baseline],['verified-overlap',current]]){
  const reader=new WavReader('');reader.totalBytes=audio.length;reader.bytes=async(start,end)=>audio.buffer.slice(audio.byteOffset+start,audio.byteOffset+Math.min(audio.length,end+1));await reader.open();
  const reads=[],read=reader.mono22050.bind(reader);reader.mono22050=async(...args)=>{reads.push(args.slice(0,2));return read(...args);};
  let calls=0,releases=0;const counters={},windowHashes=[],runtime={Tensor:ort.Tensor,InferenceSession:{async create(url,options){
   assert.equal(new URL(url).pathname,'/analysis/models/'+model.file);
   const session=await ort.InferenceSession.create(weights,options);
   return {async run(feeds){const index=calls++,input=feeds.log_mel.data;assert.ok(input.every(Number.isFinite));if(variant==='baseline-de831259')inputs.push(input.slice());else assert.ok(bytes(input).equals(bytes(inputs[index])),'Model input mismatch at passage '+index);
    const result=await session.run(feeds),scores=result.scores.data;assert.ok(scores.every(Number.isFinite));if(variant==='baseline-de831259')outputs.push(scores.slice());else assert.ok(bytes(scores).equals(bytes(outputs[index])),'Actual model output mismatch at passage '+index);
    windowHashes.push({index,inputSHA256:hash(bytes(input)),outputSHA256:hash(bytes(scores)),inputValues:input.length,outputValues:scores.length});return result;
   },async release(){releases++;await session.release();}};
  }}};
  const start=performance.now(),result=await implementation.analyze(reader,config,{ort:runtime,model,frontend,includeDiagnostics:true,includeClassifierScores:true,telemetry:{increment(name,value){counters[name]=(counters[name]||0)+value;}}}),elapsedMs=performance.now()-start;
  assert.equal(calls,current.chunkStarts(reader.duration).length);assert.equal(releases,1);
  const serialized=JSON.stringify(result);if(variant==='baseline-de831259'){expectedResult=serialized;expectedReads=reads;}else{assert.equal(serialized,expectedResult,'Final classifier, phrase, accent and envelope result differs');assert.deepEqual(reads,expectedReads);}
  passes.push({variant,calls,releases,elapsedMs,counters,readerRequests:reads,resultSHA256:hash(serialized),windowHashes});
  console.log(variant+': '+calls+' actual model calls passed');
 }
 assert.deepEqual(sourceIdentities(),sources,'Source bytes changed during actual-model qualification; refusing receipt.');
 const receipt={schemaVersion:1,kind:'actual-frame-mn10-vocal-resampler-equivalence',createdAt:new Date().toISOString(),baseline:{commit:baselineCommit,path:currentPath,sha256:hash(baselineSource)},scope:'Complete public demo through unchanged baseline and current production vocal analyze functions, actual retained Frame-MN10 ONNX model and production WASM session options. Every original input, raw output tensor, source read and final classifier/phrase/accent/envelope result compared exactly.',runtime:{node:process.version,v8:process.versions.v8,platform:process.platform,cpuModel:os.cpus()[0]?.model,wasmThreads:4},fixture:{path:fixture,bytes:audio.length,sha256:hash(audio)},equivalence:{sourceIdentitiesUnchangedAcrossExecution:true,allInputBytesIdentical:true,allRawModelOutputBytesIdentical:true,allFinalResultJSONIdentical:true,allReaderRequestsIdentical:true,finiteModelInputsAndOutputs:true},passes,sources,limitations:['Single public mixture fixture, not separated vocals or a musical-quality corpus.','Host WASM only; not Android/physical-phone/Tesla qualification.','Elapsed times are observations under concurrent workloads, not a performance comparison.','Does not replace complete pipeline, JNI, build or release gates.']};
 fs.mkdirSync(path.dirname(path.resolve(output)),{recursive:true});fs.writeFileSync(output,JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});console.log(output);
}
main().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
