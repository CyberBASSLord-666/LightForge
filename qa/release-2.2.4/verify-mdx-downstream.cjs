'use strict';
/* Paired real-model downstream check. Only file transport is adapted for Node;
 * the production centered resampler, classifier, feature extractor, GAME eight
 * steps and vocal fusion execute unchanged on measured MDX waveform outputs.
 * A single core excerpt does not test full-song overlap or population accuracy. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process'),{fileURLToPath,pathToFileURL}=require('node:url');
const ROOT=path.resolve(__dirname,'../..'),QA=__dirname,WORK=path.resolve(process.env.LIGHTFORGE_MDX_DOWNSTREAM_DIR||path.join(ROOT,'../native-mdx-downstream-2.2.4'));
const PAIR=path.resolve(process.env.LIGHTFORGE_MDX_DOWNSTREAM_PAIR||path.join(ROOT,'../native-mdx-comparison-2.2.4/demo-20s'));
const SOURCE='web/demo/glass-castle.wav',CORE_START=882000,FIXTURE='demo-20s';
const EVIDENCE_SESSION_SCHEMA='lightforge.evidence-session.v1',EVIDENCE_SESSION=process.env.LIGHTFORGE_EVIDENCE_SESSION;
if(EVIDENCE_SESSION!==undefined)assert.match(EVIDENCE_SESSION,/^[0-9a-f]{32,128}$/,'Invalid LIGHTFORGE_EVIDENCE_SESSION');
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const json=(value)=>JSON.stringify(value,(_,v)=>ArrayBuffer.isView(v)?Array.from(v):v,2)+'\n';
function writeJsonAtomic(file,value){
 const temporary=file+'.tmp-'+process.pid+'-'+crypto.randomBytes(12).toString('hex');
 try{fs.writeFileSync(temporary,json(value));fs.renameSync(temporary,file);}
 finally{try{fs.unlinkSync(temporary);}catch(_){}}
}
const buffer=b=>b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength);
function readFloats(p){const b=fs.readFileSync(p);assert.equal(b.length,261120*4);const out=new Float32Array(buffer(b));assert.ok(out.every(Number.isFinite));return out;}
class MemoryStream{
 constructor(){this.parts=[];this.closed=false;}
 async write(bytes){assert.equal(this.closed,false);this.parts.push(Buffer.from(bytes));}
 async close(){this.closed=true;}
 bytes(){assert.equal(this.closed,true);return Buffer.concat(this.parts);}
}
async function child(kind){
 assert.ok(['native','wasm'].includes(kind));fs.mkdirSync(WORK,{recursive:true});
 require(ROOT+'/web/analysis/dsp.js');require(ROOT+'/web/analysis/stem-cache.js');
 const Wav=require(ROOT+'/web/analysis/wav-reader.js'),M=require(ROOT+'/web/analysis/separator-mdx.js'),V=require(ROOT+'/web/analysis/vocal.js'),Detail=require(ROOT+'/web/analysis/vocal-detail.js'),GAME=require(ROOT+'/web/analysis/game.js');
 const config=JSON.parse(fs.readFileSync(ROOT+'/web/analysis/models/features.json'));
 global.location={href:pathToFileURL(ROOT+'/web/analysis/worker.js').href};
 global.fetch=async input=>{const p=fileURLToPath(new URL(String(input),global.location.href));assert.ok(p.startsWith(ROOT+'/web/analysis/'));return new Response(fs.readFileSync(p));};
 const raw=require(ROOT+'/web/analysis/vendor/ort.wasm.min.js');raw.env.wasm.numThreads=4;raw.env.wasm.proxy=false;raw.env.wasm.wasmPaths=ROOT+'/web/analysis/vendor/';
 const executions={},loadedModels={};
 const ort={Tensor:raw.Tensor,env:raw.env,InferenceSession:{async create(source,options){
  const p=fileURLToPath(source);assert.ok(p.startsWith(ROOT+'/web/analysis/models/'));
  const name=path.basename(p),role=name==='frame-mn10-singing.onnx'?'frameMn10':name.replace(/\.onnx$/,'');loadedModels[path.relative(ROOT,p)]=sha(p);
  const session=await raw.InferenceSession.create(fs.readFileSync(p),options);
  return{async run(feeds){executions[role]=(executions[role]||0)+1;return session.run(feeds);},async release(){return session.release();}};
 }}};
 // Exact kept-core crop used by separator-mdx.js, with no sample-rate or
 // onset shift. The paired graph passage retains real neighbouring context.
 const decoded=readFloats(path.join(PAIR,kind+'-waveform.float32le'));
 const voice=decoded.slice(M.constants.TRIM,M.constants.TRIM+M.constants.CORE),count=voice.length,duration=count/44100;
 assert.equal(count,253440);
 const bytes=fs.readFileSync(path.join(ROOT,SOURCE)),source=new Wav('host://source');source.cached=buffer(bytes);source.totalBytes=bytes.length;await source.open();
 const stereo=await source.stereo44100(CORE_START,count),mixture=new Float32Array(count),backing=new Float32Array(count);
 for(let i=0;i<count;i++){mixture[i]=(stereo[0][i]+stereo[1][i])*.5;backing[i]=mixture[i]-voice[i];}
 async function downsample(pcm){
  const stream=new MemoryStream(),writer=new LightForgeStemCache.DownsampleWriter(stream,config.resampleHalfFIR,pcm.length);
  // Exercise a real halo across a non-round write boundary, followed by tail flush.
  const split=65537;await writer.push(pcm.subarray(0,split),0);await writer.push(pcm.subarray(split),split);await writer.finish();
  const payload=stream.bytes(),wav=Buffer.concat([Buffer.from(LightForgeStemCache.header(Math.ceil(pcm.length/2))),payload]);
  const reader=new Wav('host://stem');reader.cached=buffer(wav);reader.totalBytes=wav.length;await reader.open();
  return{reader,pcm:new Float32Array(buffer(payload))};
 }
 const vocals=await downsample(voice),accompaniment=await downsample(backing);
 console.log(kind+': running actual Frame-MN10');
 const classified=await V.analyze(vocals.reader,config,{ort,includeClassifierScores:true});
 const extractor=new Detail.Extractor({sampleRate:22050,duration});extractor.push(vocals.pcm,0,accompaniment.pcm);
 console.log(kind+': running actual GAME Large eight diffusion steps');
 const game=await GAME.create({ort,baseUrl:pathToFileURL(ROOT+'/web/analysis/models/game/').href});let transcription;
 try{transcription=await game.process(async(start,length)=>{assert.ok(Number.isSafeInteger(start)&&Number.isSafeInteger(length)&&start>=0&&start+length<=voice.length);return voice.slice(start,start+length);},count,{language:0});}finally{await game.release();}
 const detail=extractor.finish({classifier:classified.classifier,model:classified.model,transcription});
 const fused=GAME.fuse(detail,transcription);
 const result={samples44100:count,samples22050:vocals.pcm.length,transcription,classified,
  features:{fineEnergy:extractor.fineEnergy,residualEnergy:extractor.residualEnergy,frequency:extractor.frequency,periodicity:extractor.periodicity},
  vocals:fused,executions,loadedModels,runtime:raw.env.versions.web,
  sourceClock:{fixture:FIXTURE,source:SOURCE,coreStartSample:CORE_START,coreSamples:count,sampleRate:44100,contextReadStart:CORE_START-M.constants.TRIM,contextReadSamples:M.constants.INPUT_LENGTH},
  waveformSha256:sha(path.join(PAIR,kind+'-waveform.float32le'))};
 writeJsonAtomic(path.join(WORK,kind+'-downstream.json'),result);
 console.log(JSON.stringify({runtime:kind,gameNotes:transcription.notes.length,fusedNotes:fused.notes.length,phrases:fused.phrases.length,executions}));
}
async function main(){
 fs.mkdirSync(WORK,{recursive:true});
 const {compare}=require('./mdx-downstream-compare.cjs');
 const sourceNames=['version.json','qa/release-2.2.4/verify-mdx-downstream.cjs','qa/release-2.2.4/mdx-downstream-compare.cjs','tests/mdx-downstream-compare.test.cjs','web/analysis/vocal.js','web/analysis/vocal-detail.js','web/analysis/game.js','web/analysis/dsp.js','web/analysis/stem-cache.js','web/analysis/wav-reader.js','web/analysis/separator-mdx.js','web/analysis/worker.js','web/analysis/models/features.json','web/analysis/models/vocal-model.json','web/analysis/models/vocal-frontend.json','web/analysis/models/game/manifest.json','web/analysis/models/separator-mdx-model.json',SOURCE];
 const sources=Object.fromEntries(sourceNames.map(p=>[p,sha(path.join(ROOT,p))]));
 const gameManifest=JSON.parse(fs.readFileSync(ROOT+'/web/analysis/models/game/manifest.json')),vocalModel=JSON.parse(fs.readFileSync(ROOT+'/web/analysis/models/vocal-model.json'));
 const assetNames=Object.keys(gameManifest.files).map(p=>'web/analysis/models/game/'+p).concat(['web/analysis/models/'+vocalModel.file],fs.readdirSync(ROOT+'/web/analysis/vendor').map(p=>'web/analysis/vendor/'+p));
 const assets=Object.fromEntries(assetNames.filter(p=>fs.statSync(path.join(ROOT,p)).isFile()).map(p=>[p,sha(path.join(ROOT,p))]));
 const receipt={release:'2.2.4',passed:false,errors:[],source_hashes:sources,analysis_asset_hashes:assets,
  scope:'Paired actual production centered resampling, Frame-MN10, vocal expression, GAME Large eight-step transcription and fusion on a measured native-ALL/4 versus WASM MDX kept-core excerpt. Node filesystem adapters supply bytes; original model graphs and numeric code execute. Nonempty voice coverage is mandatory. Not full-song OLA, corpus accuracy, Android execution, or physical-car validation.',
  fixture:{id:FIXTURE,source:SOURCE,sourceSha256:sources[SOURCE],contextReadStart:CORE_START-3840,contextReadSamples:261120,coreStart:CORE_START,coreSamples:253440,sampleRate:44100},
  inputs:Object.fromEntries(['native','wasm'].map(k=>[k,{file:k+'-waveform.float32le',bytes:fs.statSync(path.join(PAIR,k+'-waveform.float32le')).size,sha256:sha(path.join(PAIR,k+'-waveform.float32le'))}]))};
 if(EVIDENCE_SESSION!==undefined){
  const upstreamPath=path.join(QA,'native-mdx-comparison-verification.json'),upstream=JSON.parse(fs.readFileSync(upstreamPath,'utf8'));
  assert.equal(upstream.evidenceSessionSchema,EVIDENCE_SESSION_SCHEMA,'Upstream MDX receipt does not declare the evidence-session schema');
  assert.equal(upstream.evidenceSession,EVIDENCE_SESSION,'Upstream MDX receipt belongs to a different evidence session');
  receipt.evidenceSessionSchema=EVIDENCE_SESSION_SCHEMA;receipt.evidenceSession=EVIDENCE_SESSION;
  receipt.upstreamMdx={path:path.relative(ROOT,upstreamPath).split(path.sep).join('/'),sha256:sha(upstreamPath),evidenceSession:EVIDENCE_SESSION};
 }
 const output=path.join(QA,'native-mdx-downstream-verification.json');writeJsonAtomic(output,receipt);
 try{
  for(const kind of ['native','wasm']){
   const log=fs.openSync(path.join(WORK,kind+'.log'),'w');let p;
   try{p=spawnSync(process.execPath,[__filename,'--child',kind],{cwd:ROOT,env:process.env,stdio:['ignore',log,log],timeout:600000});}finally{fs.closeSync(log);}
   console.log(fs.readFileSync(path.join(WORK,kind+'.log'),'utf8'));
   if(p.error)throw p.error;assert.equal(p.status,0,kind+' downstream actual model run failed');
  }
  const results=Object.fromEntries(['native','wasm'].map(k=>[k,JSON.parse(fs.readFileSync(path.join(WORK,k+'-downstream.json')))]));
  for(const value of Object.values(results)){
   assert.equal(value.runtime,'1.20.1');
   for(const [p,h]of Object.entries(value.loadedModels))assert.equal(h,assets[p]);
  }
  // Upstream waveforms are deliberately distinct measured files. Compare
  // downstream values; validate each waveform's provenance separately.
  const comparable={};for(const kind of ['native','wasm']){const {waveformSha256,...value}=results[kind];assert.equal(waveformSha256,receipt.inputs[kind].sha256);comparable[kind]=value;}
  receipt.comparison=compare(comparable.native,comparable.wasm);receipt.thresholds=receipt.comparison.thresholds;
  receipt.runs=Object.fromEntries(['native','wasm'].map(k=>[k,{executions:results[k].executions,runtime:results[k].runtime,loadedModels:results[k].loadedModels,sourceClock:results[k].sourceClock,
   output:{bytes:fs.statSync(path.join(WORK,k+'-downstream.json')).size,sha256:sha(path.join(WORK,k+'-downstream.json'))}}]));
  // Retain detailed note/feature evidence in the versioned QA handoff.
  for(const kind of ['native','wasm'])fs.copyFileSync(path.join(WORK,kind+'-downstream.json'),path.join(QA,'native-mdx-downstream-'+kind+'.json'));
  assert.equal(receipt.comparison.passed,true,JSON.stringify(receipt.comparison.errors));
  for(const [p,h]of Object.entries({...sources,...assets}))assert.equal(sha(path.join(ROOT,p)),h,'Source changed during paired downstream run: '+p);
  for(const [kind,item]of Object.entries(receipt.inputs))assert.equal(sha(path.join(PAIR,kind+'-waveform.float32le')),item.sha256,'Measured MDX output changed during downstream run');
  receipt.passed=true;
 }catch(error){receipt.errors.push(error.stack||String(error));throw error;}
 finally{receipt.completedAt=new Date().toISOString();writeJsonAtomic(output,receipt);}
 console.log(JSON.stringify({passed:receipt.passed,coverage:receipt.comparison.coverage,errors:receipt.errors}));
}
(process.argv[2]==='--child'?child(process.argv[3]):main()).catch(error=>{console.error(error);process.exitCode=1;});
