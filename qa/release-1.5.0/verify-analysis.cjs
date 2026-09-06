/* Actual complete production Worker, including both local trained models. */
'use strict';
const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert'),crypto=require('crypto');
const {chromium}=require('/opt/codex/runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'../..'),web=path.join(root,'web'),port=8879;
const files=['web/analysis/worker.js','web/analysis/dsp.js','web/analysis/analyzer.js','web/analysis/wav-reader.js','web/analysis/bass-notes.js','web/analysis/vocal.js'];
const hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const source_hashes=()=>Object.fromEntries(files.map(p=>[p,hash(path.join(root,p))]));
const record={release:'1.5.0',analysisVersion:4,passed:false,checks:[],tracks:[],errors:[],externalRequests:[],scope:'Production Chromium Worker and shipped ONNX Runtime WASM. Supplied 48 kHz audio converted to 44.1 kHz PCM with FFmpeg for this reader test; native converter tested separately. No Android device or Tesla test.'};
function checkMusic(m){
 assert.equal(m.analysisVersion,4);assert(m.vocals.available);assert(['detected','not_detected','uncertain'].includes(m.vocals.presence));assert(m.vocals.model.sha256);assert.equal(m.bassAnalysis.source,'mixture-estimate');
 for(const values of [m.vocals.envelope,m.bassAnalysis.envelope])assert(values.every(x=>Number.isFinite(x)&&x>=0&&x<=1));
 for(const note of [...m.bassNotes,...m.vocals.phrases])assert(Number.isFinite(note.start)&&note.start>=0&&note.end>note.start&&note.end<=m.duration+.001&&note.confidence>=0&&note.confidence<=1);
 assert.equal(m.roleAnalysis.sourceSeparated,false);assert.equal(m.roleAnalysis.lyricsAligned,false);
}
(async()=>{
 const requests=[];
 const server=http.createServer((req,res)=>{
  const url=new URL(req.url,'http://local');requests.push(url.pathname);
  if(url.pathname==='/'){res.setHeader('content-type','text/html');return res.end('<script src="analysis/analyzer.js"></script>');}
  let file=url.pathname==='/synthetic.wav'?'/tmp/lightforge-1.3.0-rhythm-fixture.wav':url.pathname==='/silence.wav'?path.join(__dirname,'fixtures/silence.wav'):url.pathname==='/sample.wav'?path.join(__dirname,'fixtures/sample.wav'):url.pathname==='/glass-castle.wav'?path.join(__dirname,'fixtures/glass-castle.wav'):path.join(web,url.pathname);
  if(!fs.existsSync(file)){res.statusCode=404;return res.end();}
  const ext=path.extname(file);res.setHeader('content-type',({'.js':'text/javascript','.mjs':'text/javascript','.json':'application/json','.wasm':'application/wasm','.wav':'audio/wav'})[ext]||'application/octet-stream');
  const size=fs.statSync(file).size,range=/bytes=(\d+)-(\d+)/.exec(req.headers.range||'');
  if(range){const start=+range[1],end=Math.min(+range[2],size-1);res.statusCode=206;res.setHeader('content-range',`bytes ${start}-${end}/${size}`);res.setHeader('content-length',end-start+1);return fs.createReadStream(file,{start,end}).pipe(res);}
  res.setHeader('content-length',size);fs.createReadStream(file).pipe(res);
 });
 await new Promise(r=>server.listen(port,'127.0.0.1',r));let browser;
 try{
  record.source_hashes=source_hashes();browser=await chromium.launch({executablePath:path.resolve(root,'../toolchain/chrome/chrome-headless-shell-linux64/chrome-headless-shell'),args:['--no-sandbox','--disable-dev-shm-usage']});const page=await browser.newPage();
  page.on('request',req=>{if(!req.url().startsWith(`http://127.0.0.1:${port}/`)&&!req.url().startsWith('blob:'))record.externalRequests.push(req.url());});
  await page.goto(`http://127.0.0.1:${port}`);
  for(const [track,quality] of [['synthetic','balanced'],['synthetic','precision'],['glass-castle','precision'],['sample','balanced']]){
   const m=await page.evaluate(async({track,quality})=>MusicAnalyzer.analyze('/'+track+'.wav',{analysisQuality:quality}),{track,quality});checkMusic(m);
   if(track==='synthetic'){
    const old=JSON.parse(fs.readFileSync(path.join(root,'qa/release-1.4.0/final-synthetic-'+quality+'-music.json')));
    assert.deepEqual(m.beats,old.beats);assert.deepEqual(m.downbeats,old.downbeats);assert.deepEqual(m.onsets,old.onsets);
    record.checks.push(quality+' retains all exact 1.4 beat, downbeat and three-band onset times on the existing annotated synthetic fixture.');
   }
   fs.writeFileSync(path.join(__dirname,'current-'+track+'-'+quality+'-music.json'),JSON.stringify(m));
   record.tracks.push({track,quality,duration:m.duration,beats:m.beats.length,downbeats:m.downbeats.length,vocalPresence:m.vocals.presence,vocalPhrases:m.vocals.phrases.length,vocalCoverage:m.vocals.coverage,bassNotes:m.bassNotes.length,analysisSeconds:m.engine.analysisSeconds,engine:m.engine,annotation:'Synthetic fixture has beat annotations only; supplied songs have no independent vocal or bass timing labels.'});
   console.log(JSON.stringify(record.tracks.at(-1)));
  }
  requests.length=0;const quiet=await page.evaluate(()=>MusicAnalyzer.analyze('/silence.wav'));checkMusic(quiet);assert.equal(quiet.beats.length,0);assert.equal(quiet.vocals.phrases.length,0);assert.equal(quiet.bassNotes.length,0);assert(!requests.some(p=>p.endsWith('.onnx')));record.checks.push('Digital silence invents no beats, singing or bass notes and loads no neural graph.');
  const cancelled=await page.evaluate(async()=>{const c=new AbortController();const p=MusicAnalyzer.analyze('/glass-castle.wav',{},()=>{},c.signal);c.abort();try{await p;return false;}catch(e){return e.name==='AbortError';}});assert(cancelled);record.checks.push('Cancellation terminates the complete analysis Worker.');
  assert.equal(record.externalRequests.length,0);assert.deepEqual(record.source_hashes,source_hashes());record.checks.push('All graph, frontend, runtime and audio requests remain on the local origin.');record.passed=true;
 }catch(e){record.errors.push(e.stack||String(e));throw e;}
 finally{fs.writeFileSync(path.join(__dirname,'analysis-worker-verification.json'),JSON.stringify(record,null,2));if(browser)await browser.close();server.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
