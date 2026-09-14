'use strict';
/* Actual public analyzer, bundled ONNX models, Chromium workers and OPFS.
 * Reference audio is a licensed MUSDB excerpt, never an oracle input stem.
 * The Android bridge and physical vehicle are outside this check's scope. */
const fs=require('fs'),path=require('path'),http=require('http'),crypto=require('crypto'),assert=require('assert/strict');
const root=path.resolve(__dirname,'../..'),qa=__dirname,fixture=path.join(root,'qa/release-1.6.0/fixtures/falcon-mix.wav'),output=path.join(qa,'analysis-browser-verification.json');
const EVIDENCE_SESSION_SCHEMA='lightforge.evidence-session.v1';
const EVIDENCE_SESSION_PATTERN=/^[0-9a-f]{32,128}$/;
// CI supplies a session. Its deliberate absence retains no-session local runs.
function writeJsonAtomic(file,value){
 const temporary=`${file}.${process.pid}.${crypto.randomBytes(8).toString('hex')}.tmp`;
 try{fs.writeFileSync(temporary,JSON.stringify(value,null,2)+'\n');fs.renameSync(temporary,file);}
 finally{if(fs.existsSync(temporary))fs.unlinkSync(temporary);}
}
function errorText(error){return error&&error.stack?error.stack:String(error);}
function listen(server){
 return new Promise((resolve,reject)=>{
  const failed=error=>{server.off('listening',ready);reject(error);};
  const ready=()=>{server.off('error',failed);resolve();};
  server.once('error',failed);server.once('listening',ready);server.listen(0,'127.0.0.1');
 });
}
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const sources=['qa/release-2.2.5/analysis-browser.cjs','qa/release-2.2.5/analysis-performance.cjs','qa/release-1.6.0/fixtures/falcon-mix.wav','version.json','web/index.html','web/analysis/ASSET_MANIFEST.json','web/analysis/diagnostic-clock.js','web/analysis/resource-diagnostics.js','web/analysis/telemetry.js','web/analysis/scheduler.js','web/analysis/worker.js','web/analysis/analyzer.js','web/analysis/feature-store.js','web/analysis/game.js','web/analysis/salience.js','web/analysis/semantic-timeline.js','web/analysis/separator-deux.js','web/analysis/stem-cache.js','web/analysis/stem-routing.js','web/analysis/work-store.js','web/analysis/vocal.js','web/analysis/vocal-detail.js','web/analysis/bass-notes.js','web/analysis/models/game/manifest.json','web/analysis/models/deux/manifest.json','web/engine/show-engine.js','web/engine/light-planner.js','web/engine/music-cues.js','web/engine/sync-review.js','web/engine/worker.js'];
(async()=>{
 const evidenceSession=process.env.LIGHTFORGE_EVIDENCE_SESSION;
 const sessionError=evidenceSession!==undefined&&!EVIDENCE_SESSION_PATTERN.test(evidenceSession)?
  new Error('Invalid LIGHTFORGE_EVIDENCE_SESSION'):null;
 const receipt={release:'2.2.5',passed:false,errors:[],checks:[],source_hashes:{},scope:'Actual Chromium public MusicAnalyzer with production Deux, GAME Large, Beat This and Frame-MN10. Test controls and original-stem reference scoring are independent of model inputs. No physical Android or Tesla.'};
 if(!sessionError&&evidenceSession!==undefined){receipt.evidenceSessionSchema=EVIDENCE_SESSION_SCHEMA;receipt.evidenceSession=evidenceSession;}
 // Publish failure before every fallible import, source read, fixture access, or server action.
 writeJsonAtomic(output,receipt);
 let server,browser,verified=false;
 try{
  if(sessionError)throw sessionError;
  const {chromium}=require('playwright'),AnalysisPerformance=require('./analysis-performance.cjs');
  receipt.source_hashes=Object.fromEntries(sources.map(p=>[p,sha(path.join(root,p))]));
  server=http.createServer((req,res)=>{
  const u=new URL(req.url,'http://local'),p=u.pathname==='/qa/falcon.wav'?fixture:path.resolve(root,'web','.'+(u.pathname==='/'?'/index.html':u.pathname));
  if((p!==fixture&&!p.startsWith(path.join(root,'web')+path.sep))||!fs.existsSync(p)||!fs.statSync(p).isFile()){res.writeHead(404).end();return;}
  const size=fs.statSync(p).size,range=/^bytes=(\d+)-(\d+)$/.exec(req.headers.range||'');let start=0,end=size-1;
  res.setHeader('Cross-Origin-Opener-Policy','same-origin');res.setHeader('Cross-Origin-Embedder-Policy','require-corp');res.setHeader('Content-Type',({'.js':'text/javascript','.mjs':'text/javascript','.html':'text/html','.json':'application/json','.css':'text/css','.wasm':'application/wasm','.wav':'audio/wav'})[path.extname(p)]||'application/octet-stream');
  if(range){start=+range[1];end=Math.min(+range[2],size-1);if(start>end){res.writeHead(416).end();return;}res.statusCode=206;res.setHeader('Content-Range',`bytes ${start}-${end}/${size}`);}res.setHeader('Content-Length',end-start+1);fs.createReadStream(p,{start,end}).pipe(res);
  });await listen(server);
  browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_EXECUTABLE_PATH?{executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH}:{}),args:['--no-sandbox','--enable-unsafe-swiftshader']});const page=await browser.newPage({viewport:{width:393,height:852}});page.setDefaultTimeout(1200000);page.on('pageerror',e=>receipt.errors.push(e.message));page.on('console',m=>{if(m.type()==='log')console.log(m.text());});
  await page.goto('http://127.0.0.1:'+server.address().port);await page.waitForFunction(()=>!!window.MusicAnalyzer);assert.equal(await page.evaluate(()=>crossOriginIsolated),true);
  const analysisStartedAt=process.hrtime.bigint();
  const result=await page.evaluate(async()=>{
   const progress=[];let last=-1;const music=await MusicAnalyzer.analyze('/qa/falcon.wav',{projectId:'model-runtime',analysisQuality:'precision'},p=>{progress.push(p);if(Math.floor(p.progress*20)!==last){last=Math.floor(p.progress*20);console.log(p.stage+' · '+Math.round(p.progress*100)+'%');}});
   const files=await LightForgeStemCache.files(music.stemCache),bytes=await files.vocals.arrayBuffer(),full=await LightForgeStemCache.fullVoice(music.stemCache),first=await full(0,Math.min(44100,music.stemCache.fullSamples));
   const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');window.modelResult=music;
   return {music,cacheHash:hash,fullVoiceSamples:first.length,progressMonotonic:progress.every((p,i)=>!i||p.progress>=progress[i-1].progress-1e-9)};
  });
  const analysisWallClockSeconds=Number(process.hrtime.bigint()-analysisStartedAt)/1e9,performance=AnalysisPerformance.build(result.music.engine,analysisWallClockSeconds);
  assert.equal(AnalysisPerformance.validate(performance),true);
  assert.equal(performance.resources.status,'available');
  assert.deepEqual(Object.keys(performance.resources.pipeline.stages).sort(),['bass','rhythm','separation','voice']);
  const sourceReaderOpens=Object.fromEntries(['separation','voice','bass'].map(stage=>[stage,Number(result.music.engine.stages?.[stage]?.profile?.counters?.source_wav_reader_opens??0)]));
  assert.deepEqual(sourceReaderOpens,{separation:1,voice:0,bass:0},'only separation may reopen the original PCM WAV; voice and bass must use the verified stem cache');
  const minimumSemanticAnalysisVersion=8;assert.ok(Number.isInteger(result.music.analysisVersion)&&result.music.analysisVersion>=minimumSemanticAnalysisVersion,`Expected semantic analysis schema version >= ${minimumSemanticAnalysisVersion}; received ${result.music.analysisVersion}.`);assert.equal(result.music.separation.modelId,'mel-band-roformer-deux-lightforge-2');assert.equal(result.music.vocals.transcription.model,'game-large-1.0.3-lightforge-1');assert.ok(result.music.vocals.notes.length>0);assert.equal(result.fullVoiceSamples,44100);assert.ok(result.progressMonotonic);assert.equal(result.music.vocals.lyricsAligned,false);
  fs.writeFileSync(path.join(qa,'actual-analysis-falcon.json'),JSON.stringify(result.music));receipt.analysis={engine:result.music.engine,separation:result.music.separation,noteCount:result.music.vocals.notes.length,bassNoteCount:result.music.bassNotes.length,cacheHash:result.cacheHash,progressMonotonic:result.progressMonotonic,sourceReaderOpens,performance};receipt.checks.push('Full production analyzer completed actual precision-model inference, retained full-resolution source-clock vocals, and returned learned sung notes. Only separation reopened original PCM; voice and bass reused verified stem-cache sample-clock evidence. The receipt records observed timing/cache/profile/resource metadata without a performance threshold or a claim of CPU/GPU utilisation.');
  const composition=await page.evaluate(async()=>{const settings={...LightForgeApp.state.settings,dance:'off'},first=await ShowCompiler.generate(window.modelResult,settings),restored=await ShowCompiler.restore(first.compiled,window.modelResult,settings);const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',first.show.frames)),x=>x.toString(16).padStart(2,'0')).join('');return {valid:first.show.validation.valid,hash,savedHash:first.compiled.sha256,restoredHash:restored.compiled.sha256,frameCount:first.show.frameCount,synchronization:first.show.synchronization};});assert.ok(composition.valid);assert.equal(composition.hash,composition.savedHash);assert.equal(composition.restoredHash,composition.savedHash);receipt.composition=composition;receipt.checks.push('Actual newly analyzed music composes into legal FSEQ frames and restores with an identical frame hash.');
  const cancel=await page.evaluate(async()=>{
   const root=await navigator.storage.getDirectory(),dir=await root.getDirectoryHandle('lightforge-stems-v1'),before=[];for await(const [k]of dir.entries())before.push(k);
   const controller=new AbortController();let stage='';try{await MusicAnalyzer.analyze('/qa/falcon.wav',{projectId:'cancel-runtime',analysisQuality:'balanced'},p=>{if(p.progress>=.42){stage=p.stage;controller.abort();}},controller.signal);return {aborted:false};}catch(e){if(e.name!=='AbortError')throw e;}
   let extra=[];for(let i=0;i<24;i++){extra=[];for await(const [k]of dir.entries())if(!before.includes(k))extra.push(k);if(!extra.length)break;await new Promise(r=>setTimeout(r,500));}return {aborted:controller.signal.aborted,stage,remainingNamespaces:extra.length};
  });assert.ok(cancel.aborted);assert.equal(cancel.remainingNamespaces,0);receipt.cancellation=cancel;receipt.checks.push('Public analyzer cancellation during source separation removed its incomplete OPFS namespace.');
  for(const [p,h]of Object.entries(receipt.source_hashes))assert.equal(sha(path.join(root,p)),h);assert.equal(receipt.errors.length,0);verified=true;
 }catch(error){receipt.errors.push(errorText(error));console.error(errorText(error));}finally{
  try{await browser?.close();}catch(error){receipt.errors.push(errorText(error));console.error(errorText(error));}
  if(server?.listening)try{await new Promise((resolve,reject)=>server.close(error=>error?reject(error):resolve()));}catch(error){receipt.errors.push(errorText(error));console.error(errorText(error));}
 }
 receipt.passed=verified&&receipt.errors.length===0;receipt.completedAt=new Date().toISOString();writeJsonAtomic(output,receipt);console.log(JSON.stringify({passed:receipt.passed,errors:receipt.errors}));if(!receipt.passed)process.exitCode=1;
})().catch(error=>{console.error(errorText(error));process.exitCode=1;});
