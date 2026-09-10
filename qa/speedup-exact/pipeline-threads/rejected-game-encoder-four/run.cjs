'use strict';
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const ROOT='/workspace/scratch/9a5ec23b7f4b/LightForge',OUT=__dirname,{chromium}=require(ROOT+'/node_modules/playwright');
const fixture=path.resolve(OUT,'../falcon-3s.wav'),sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const input=JSON.parse(fs.readFileSync(path.resolve(OUT,'../input-binding.json')));assert.equal(sha(fixture),input.fixtureSha256);
const baselinePath=path.resolve(OUT,'../initial-1-vs-4/verification.json'),baseline=JSON.parse(fs.readFileSync(baselinePath));assert.equal(baseline.runs['1'].graphs.length,350);assert.ok(baseline.runs['1'].analysis);
const receipt={schema:'lightforge-full-pipeline-android-classifier-handoff-1',passed:false,scope:'Candidate-only actual public MusicAnalyzer replay against the preserved 350-graph original one-thread baseline. Final production Android private classifier1-to-GAME4 handoff and stage routing are exercised with a probe-only Android.pickAudio marker, actual COI/SAB and navigator.hardwareConcurrency=8. This is host byte qualification, not a physical Android provider test or controlled timing.',input,controls:{quality:'precision',baselineHardwareConcurrency:2,candidateHardwareConcurrency:8,threadPolicy:'Final Android production route: rhythm1, Precision separation4, private voice-classifier1, fresh voice GAME4, bass1; actual COI/SAB and >=8 cores required.',expectedEffectiveThreads:{rhythm:1,separation:4,'voice-classifier':1,voice:4,bass:1},androidMarker:'window.Android.pickAudio is a probe-only function; no method is called.',nativePrediction:false,gamePool:false,checkpoints:'Fresh independent browser context per run; same fixed analysisIdentity equal to WAV SHA256.'},sourceHashes:{},baselineBinding:{path:baselinePath,sha256:sha(baselinePath),originalSourceHashes:baseline.sourceHashes,originalExecutedSourceSnapshot:path.resolve(OUT,'../initial-1-vs-4/executed-source')},runs:{'1':baseline.runs['1'],'4':{sessions:[],graphs:[]}},errors:[],firstMismatch:null};
const bindings=['web/analysis/worker.js','web/analysis/analyzer.js','web/analysis/game.js','web/analysis/separator-deux.js','web/analysis/vocal.js','web/analysis/vocal-detail.js','web/analysis/bass-notes.js','web/analysis/stem-cache.js','web/analysis/work-store.js','web/analysis/dsp.js','web/analysis/wav-reader.js','web/analysis/ASSET_MANIFEST.json'];
for(const p of bindings)receipt.sourceHashes[p]=sha(path.join(ROOT,p));
receipt.harness={path:__filename,sha256:sha(__filename),bootstrapPath:path.join(OUT,'worker-bootstrap.js'),bootstrapSha256:sha(path.join(OUT,'worker-bootstrap.js'))};
const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(k=>[k,canonical(value[k])])):value;
function comparable(record){const {type,stage,call,modelPath,inputs,outputs}=record;return canonical({type,stage:stage==='voice-classifier'?'voice':stage,call,modelPath,inputs,outputs});}
receipt.traceMetadataNormalization={stageMap:{'voice-classifier':'voice'},ignoredComparisonFields:['sessionId'],reason:'The private classifier now has its own worker and GAME starts fresh, resetting the worker-local session counter. Raw traces retain original stage/session IDs. Model path, global invocation order, per-model call number, every tensor type/dimension/byte count and full-byte SHA remain exact.'};
function save(){fs.writeFileSync(path.join(OUT,'verification.json'),JSON.stringify(receipt,null,2)+'\n');}
function headers(res,type){res.setHeader('Cross-Origin-Opener-Policy','same-origin');res.setHeader('Cross-Origin-Embedder-Policy','require-corp');res.setHeader('Content-Type',type);}
const server=http.createServer(async(req,res)=>{
 try{
  const url=new URL(req.url,'http://local');
  if(url.pathname==='/__thread-probe/record'){
   let body='';for await(const chunk of req){body+=chunk;if(body.length>4*1024*1024)throw Error('Oversized trace');}
   const record=JSON.parse(body),run=receipt.runs[String(record.run)];if(!run)throw Error('Unknown probe run');
   const list=record.type==='graph'?run.graphs:run.sessions,index=list.length;list.push(record);let error;
   if(record.type==='graph'&&record.run===4){
    const expected=receipt.runs['1'].graphs[index];
    if(!expected||JSON.stringify(comparable(expected))!==JSON.stringify(comparable(record))){
     error='Raw graph mismatch at invocation '+index+' '+record.modelPath;
     receipt.firstMismatch={index,error,baseline:expected,candidate:record};save();
    }
   }
   if(record.type==='graph'&&(index%20===0||record.stage!=='separation'))console.log(JSON.stringify({run:record.run,graph:index,stage:record.stage,model:record.modelPath,seconds:record.seconds,exact:!error}));
   if(record.type==='session')console.log(JSON.stringify({run:record.run,session:record.sessionId,stage:record.stage,model:record.modelPath,threads:record.threads}));
   if(record.type==='graph'&&index%20===0)save();
   headers(res,'application/json');res.writeHead(error?409:200).end(JSON.stringify(error?{accepted:false,error}:{accepted:true}));return;
  }
  let p;
  if(url.pathname==='/analysis/thread-probe-worker.js')p=path.join(OUT,'worker-bootstrap.js');
  else if(url.pathname==='/qa/falcon.wav')p=fixture;
  else p=path.resolve(ROOT,'web','.'+(url.pathname==='/'?'/index.html':url.pathname));
  if(![fixture,path.join(OUT,'worker-bootstrap.js')].includes(p)&&!p.startsWith(path.join(ROOT,'web')+path.sep))throw Error('Invalid asset path');
  if(!fs.existsSync(p)||!fs.statSync(p).isFile()){res.writeHead(404).end();return;}
  if(p.startsWith(path.join(ROOT,'web','analysis')+path.sep)){const relative=path.relative(ROOT,p);if(!receipt.sourceHashes[relative])receipt.sourceHashes[relative]=sha(p);}
  const size=fs.statSync(p).size,range=/^bytes=(\d+)-(\d+)$/.exec(req.headers.range||'');let start=0,end=size-1;
  headers(res,({'.js':'text/javascript','.mjs':'text/javascript','.html':'text/html','.json':'application/json','.css':'text/css','.wasm':'application/wasm','.wav':'audio/wav'})[path.extname(p)]||'application/octet-stream');
  if(range){start=Number(range[1]);end=Math.min(Number(range[2]),size-1);if(start>end){res.writeHead(416).end();return;}res.statusCode=206;res.setHeader('Content-Range',`bytes ${start}-${end}/${size}`);}
  res.setHeader('Content-Length',end-start+1);fs.createReadStream(p,{start,end}).pipe(res);
 }catch(error){headers(res,'application/json');res.writeHead(500).end(JSON.stringify({error:error.message}));}
});
const excludedPaths=['separation.analysisSeconds','engine.analysisSeconds','engine.separationModel.analysisSeconds','engine.stages.rhythm.seconds','engine.stages.separation.seconds','engine.stages.voice.seconds','engine.stages.bass.seconds','stemCache.createdAt'];
function musical(value){const result=structuredClone(value);for(const p of excludedPaths){const parts=p.split('.'),last=parts.pop();let at=result;for(const key of parts)at=at[key];delete at[last];}return canonical(result);}
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));let browser;
 try{
  browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_EXECUTABLE_PATH?{executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH}:{}),args:['--no-sandbox','--enable-unsafe-swiftshader']});receipt.browserVersion=browser.version();
  for(const threads of [4]){
   const context=await browser.newContext({viewport:{width:393,height:852}}),page=await context.newPage();page.setDefaultTimeout(1200000);page.on('pageerror',e=>receipt.errors.push(e.stack));page.on('console',msg=>{if(msg.type()==='log'&&msg.text().startsWith('THREAD-PROBE'))console.log(msg.text());});
   await context.addInitScript(({threads})=>{window.Android={pickAudio(){throw Error('Probe marker must not be called');}};const OriginalWorker=window.Worker;window.Worker=class extends OriginalWorker{constructor(url,options){const target=new URL(String(url),location.href);if(target.pathname==='/analysis/worker.js')super(new URL('/analysis/thread-probe-worker.js?run='+threads,location.href),options);else super(url,options);}};},{threads});
   await page.goto('http://127.0.0.1:'+server.address().port);await page.waitForFunction(()=>!!window.MusicAnalyzer);assert.equal(await page.evaluate(()=>crossOriginIsolated),true);
   const start=performance.now();const result=await page.evaluate(async({identity,threads})=>{
    let lastStage='';const music=await MusicAnalyzer.analyze('/qa/falcon.wav',{projectId:'exact-thread-probe',analysisQuality:'precision',analysisIdentity:identity},p=>{if(p.stage!==lastStage){lastStage=p.stage;console.log('THREAD-PROBE '+threads+' '+p.stage);}});
    const files=await LightForgeStemCache.files(music.stemCache),hash=async bytes=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join(''),stemHashes={};
    for(const [name,file] of Object.entries(files))if(file?.arrayBuffer)stemHashes[name]=await hash(await file.arrayBuffer());
    const read=await LightForgeStemCache.fullVoice(music.stemCache),pcm=await read(0,music.stemCache.fullSamples);stemHashes.fullVoice=await hash(pcm.buffer.slice(pcm.byteOffset,pcm.byteOffset+pcm.byteLength));
    return {music,stemHashes,fullVoiceSamples:pcm.length};
   },{identity:input.fixtureSha256,threads});
   receipt.runs[String(threads)].wallSeconds=(performance.now()-start)/1000;receipt.runs[String(threads)].analysis=result;fs.writeFileSync(path.join(OUT,'analysis-'+threads+'.json'),JSON.stringify(result,null,2)+'\n');save();
   assert.equal(result.music.duration,3);assert.equal(result.fullVoiceSamples,132300);assert.equal(result.music.separation.modelId,'mel-band-roformer-deux-lightforge-2');assert.equal(result.music.vocals.transcription.steps,8);
   await context.close();
   if(receipt.firstMismatch)throw Error(receipt.firstMismatch.error);
  }
  const first=receipt.runs['1'],second=receipt.runs['4'];assert.equal(first.graphs.length,second.graphs.length);assert.deepEqual(second.analysis.stemHashes,first.analysis.stemHashes);assert.deepEqual(musical(second.analysis.music),musical(first.analysis.music));
  receipt.finalComparison={finalAndroidStageRoutingExercised:true,allGraphInputsOutputsExact:true,graphCalls:first.graphs.length,stemHashesExact:true,fullVoiceSamples:first.analysis.fullVoiceSamples,musicalFieldsExact:true,excludedPaths,exclusionReason:'Recorded elapsed durations and stem-cache creation wall-clock timestamp only. No musical timing, notes, confidence, thresholds, boundaries, waveform, or model metadata is excluded.'};
  for(const [p,h] of Object.entries(receipt.sourceHashes))assert.equal(sha(path.join(ROOT,p)),h,'Source changed during qualification: '+p);
  assert.equal(receipt.errors.length,0);receipt.passed=true;
 }catch(error){receipt.errors.push(error.stack);console.error(error.stack);}finally{await browser?.close();await new Promise(resolve=>server.close(resolve));}
 receipt.completedAt=new Date().toISOString();save();console.log(JSON.stringify({passed:receipt.passed,firstMismatch:receipt.firstMismatch&&{index:receipt.firstMismatch.index,error:receipt.firstMismatch.error},errors:receipt.errors}));if(!receipt.passed)process.exitCode=1;
})();
