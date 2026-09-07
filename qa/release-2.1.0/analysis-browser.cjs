'use strict';
/* Actual public analyzer, bundled ONNX models, Chromium workers and OPFS.
 * Reference audio is a licensed MUSDB excerpt, never an oracle input stem.
 * The Android bridge and physical vehicle are outside this check's scope. */
const {chromium}=require('playwright'),fs=require('fs'),path=require('path'),http=require('http'),crypto=require('crypto'),assert=require('assert/strict');
const root=path.resolve(__dirname,'../..'),qa=__dirname,fixture=path.join(root,'qa/release-1.6.0/fixtures/falcon-mix.wav');
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const sources=['web/analysis/worker.js','web/analysis/analyzer.js','web/analysis/game.js','web/analysis/separator-deux.js','web/analysis/stem-cache.js','web/analysis/vocal.js','web/analysis/vocal-detail.js','web/analysis/bass-notes.js','web/analysis/models/game/manifest.json','web/analysis/models/deux/manifest.json'];
(async()=>{
 const receipt={release:'2.1.0',passed:false,errors:[],checks:[],source_hashes:Object.fromEntries(sources.map(p=>[p,sha(path.join(root,p))])),scope:'Actual Chromium public MusicAnalyzer with production Deux, GAME Large, Beat This and Frame-MN10. Test controls and original-stem reference scoring are independent of model inputs. No physical Android or Tesla.'};
 const server=http.createServer((req,res)=>{
  const u=new URL(req.url,'http://local'),p=u.pathname==='/qa/falcon.wav'?fixture:path.resolve(root,'web','.'+(u.pathname==='/'?'/index.html':u.pathname));
  if((p!==fixture&&!p.startsWith(path.join(root,'web')+path.sep))||!fs.existsSync(p)||!fs.statSync(p).isFile()){res.writeHead(404).end();return;}
  const size=fs.statSync(p).size,range=/^bytes=(\d+)-(\d+)$/.exec(req.headers.range||'');let start=0,end=size-1;
  res.setHeader('Cross-Origin-Opener-Policy','same-origin');res.setHeader('Cross-Origin-Embedder-Policy','require-corp');res.setHeader('Content-Type',({'.js':'text/javascript','.mjs':'text/javascript','.html':'text/html','.json':'application/json','.css':'text/css','.wasm':'application/wasm','.wav':'audio/wav'})[path.extname(p)]||'application/octet-stream');
  if(range){start=+range[1];end=Math.min(+range[2],size-1);if(start>end){res.writeHead(416).end();return;}res.statusCode=206;res.setHeader('Content-Range',`bytes ${start}-${end}/${size}`);}res.setHeader('Content-Length',end-start+1);fs.createReadStream(p,{start,end}).pipe(res);
 });await new Promise(r=>server.listen(0,'127.0.0.1',r));let browser;
 try{
  browser=await chromium.launch({headless:true,args:['--no-sandbox','--enable-unsafe-swiftshader']});const page=await browser.newPage({viewport:{width:393,height:852}});page.setDefaultTimeout(1200000);page.on('pageerror',e=>receipt.errors.push(e.message));page.on('console',m=>{if(m.type()==='log')console.log(m.text());});
  await page.goto('http://127.0.0.1:'+server.address().port);await page.waitForFunction(()=>!!window.MusicAnalyzer);assert.equal(await page.evaluate(()=>crossOriginIsolated),true);
  const result=await page.evaluate(async()=>{
   const progress=[];let last=-1;const music=await MusicAnalyzer.analyze('/qa/falcon.wav',{projectId:'model-runtime',analysisQuality:'precision'},p=>{progress.push(p);if(Math.floor(p.progress*20)!==last){last=Math.floor(p.progress*20);console.log(p.stage+' · '+Math.round(p.progress*100)+'%');}});
   const files=await LightForgeStemCache.files(music.stemCache),bytes=await files.vocals.arrayBuffer(),full=await LightForgeStemCache.fullVoice(music.stemCache),first=await full(0,Math.min(44100,music.stemCache.fullSamples));
   const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');window.modelResult=music;
   return {music,cacheHash:hash,fullVoiceSamples:first.length,progressMonotonic:progress.every((p,i)=>!i||p.progress>=progress[i-1].progress-1e-9)};
  });
  assert.equal(result.music.analysisVersion,6);assert.equal(result.music.separation.modelId,'mel-band-roformer-deux-lightforge-1');assert.equal(result.music.vocals.transcription.model,'game-large-1.0.3-lightforge-1');assert.ok(result.music.vocals.notes.length>0);assert.equal(result.fullVoiceSamples,44100);assert.ok(result.progressMonotonic);assert.equal(result.music.vocals.lyricsAligned,false);
  fs.writeFileSync(path.join(qa,'actual-analysis-falcon.json'),JSON.stringify(result.music));receipt.analysis={engine:result.music.engine,separation:result.music.separation,noteCount:result.music.vocals.notes.length,bassNoteCount:result.music.bassNotes.length,cacheHash:result.cacheHash,progressMonotonic:result.progressMonotonic};receipt.checks.push('Full production analyzer completed actual precision-model inference, retained full-resolution source-clock vocals, and returned learned sung notes.');
  const cancel=await page.evaluate(async()=>{
   const root=await navigator.storage.getDirectory(),dir=await root.getDirectoryHandle('lightforge-stems-v1'),before=[];for await(const [k]of dir.entries())before.push(k);
   const controller=new AbortController();let stage='';try{await MusicAnalyzer.analyze('/qa/falcon.wav',{projectId:'cancel-runtime',analysisQuality:'balanced'},p=>{if(p.progress>=.42){stage=p.stage;controller.abort();}},controller.signal);return {aborted:false};}catch(e){if(e.name!=='AbortError')throw e;}
   let extra=[];for(let i=0;i<24;i++){extra=[];for await(const [k]of dir.entries())if(!before.includes(k))extra.push(k);if(!extra.length)break;await new Promise(r=>setTimeout(r,500));}return {aborted:controller.signal.aborted,stage,remainingNamespaces:extra.length};
  });assert.ok(cancel.aborted);assert.equal(cancel.remainingNamespaces,0);receipt.cancellation=cancel;receipt.checks.push('Public analyzer cancellation during source separation removed its incomplete OPFS namespace.');
  for(const [p,h]of Object.entries(receipt.source_hashes))assert.equal(sha(path.join(root,p)),h);assert.equal(receipt.errors.length,0);receipt.passed=true;
 }catch(e){receipt.errors.push(e.stack);console.error(e.stack);}finally{await browser?.close();await new Promise(r=>server.close(r));}
 receipt.completedAt=new Date().toISOString();fs.writeFileSync(path.join(qa,'analysis-browser-verification.json'),JSON.stringify(receipt,null,2));console.log(JSON.stringify({passed:receipt.passed,errors:receipt.errors}));if(!receipt.passed)process.exitCode=1;
})();
