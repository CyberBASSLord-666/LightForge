'use strict';
/* CI browser integration. The Android bridge is simulated; WebGL, workers,
 * project editing, storage, audio, and exported bytes use the real web app. */
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),out=__dirname,output=path.join(out,'browser-verification.json');
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
const hashes=()=>Object.fromEntries(['qa/release-2.2.4/browser.cjs','qa/release-1.6.0/actual-music-user-glass-prefix64-analysis.json','version.json','web/cockpit.js','web/cockpit.css','web/version.js','web/app.js','web/diagnostics.js','web/diagnostics.css','web/index.html','web/styles.css','web/precision-studio.js','web/engine/worker.js','web/engine/client.js','web/engine/show-engine.js','web/engine/light-planner.js','web/engine/music-cues.js','web/engine/sync-review.js'].map(f=>[f,crypto.createHash('sha256').update(fs.readFileSync(path.join(root,f))).digest('hex')]));
(async()=>{
 const evidenceSession=process.env.LIGHTFORGE_EVIDENCE_SESSION;
 const sessionError=evidenceSession!==undefined&&!EVIDENCE_SESSION_PATTERN.test(evidenceSession)?
  new Error('Invalid LIGHTFORGE_EVIDENCE_SESSION'):null;
 const receipt={release:'2.2.4',passed:false,checks:[],errors:[],source_hashes:{},scope:'Desktop Chromium with actual WebGL and web workers; simulated Android bridge. No Android device or Tesla.'};
 if(!sessionError&&evidenceSession!==undefined){receipt.evidenceSessionSchema=EVIDENCE_SESSION_SCHEMA;receipt.evidenceSession=evidenceSession;}
 // Do this before imports, fixtures, hashing, or starting a server so a failed
 // setup cannot leave a previous successful receipt visible.
 writeJsonAtomic(output,receipt);
 let server,browser,page,verified=false;
 try{
  if(sessionError)throw sessionError;
  const {chromium}=require('playwright');
  const music=JSON.parse(fs.readFileSync(path.join(root,'qa/release-1.6.0/actual-music-user-glass-prefix64-analysis.json')));
  const fixture={version:1,name:'Glass Castle · Precision QA',settings:{style:'cinematic',dance:'off',seed:2025,vocalFocus:.85,bassFocus:.9,vocalRegions:[]},music};
  receipt.source_hashes=hashes();
  server=http.createServer((req,res)=>{
  const pathname=decodeURIComponent(req.url.split('?')[0]);
  if(pathname==='/fixture.json'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify(fixture));return;}
  const p=path.resolve(root,'web','.'+(pathname==='/'?'/index.html':pathname));if(!p.startsWith(path.join(root,'web')+path.sep)){res.writeHead(403).end();return;}
  if(!fs.existsSync(p)||!fs.statSync(p).isFile()){res.writeHead(404).end();return;}
  res.setHeader('Content-Type',({'.js':'text/javascript','.html':'text/html','.css':'text/css','.json':'application/json','.wasm':'application/wasm','.wav':'audio/wav','.glb':'model/gltf-binary'})[path.extname(p)]||'application/octet-stream');
  res.setHeader('Cross-Origin-Opener-Policy','same-origin');res.setHeader('Cross-Origin-Embedder-Policy','require-corp');
  res.setHeader('Content-Length',fs.statSync(p).size);fs.createReadStream(p).pipe(res);
  });
  await listen(server);
  browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_EXECUTABLE_PATH?{executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH}:{}),args:['--no-sandbox','--enable-unsafe-swiftshader']});page=await browser.newPage({viewport:{width:393,height:852}});
  const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.error('PAGE ERROR',e.stack);});page.on('console',m=>{if(m.type()==='error')console.error('CONSOLE',m.text());});
  await page.addInitScript(()=>{
   const project={id:'qa-project',name:'Glass Castle · Precision QA',duration:64,audioUrl:'/demo/glass-castle.wav',projectUrl:'/fixture.json'};
   const fetchOriginal=window.fetch.bind(window);window.fetch=(input,options)=>String(input).endsWith('/fixture.json')&&localStorage.getItem('qa-saved')?Promise.resolve(new Response(localStorage.getItem('qa-saved'),{headers:{'Content-Type':'application/json'}})):fetchOriginal(input,options);
   window.Android={pickAudio(){},getBootstrap:()=>JSON.stringify({projects:[project],lastProjectId:project.id,version:'2.2.4'}),saveProject:(id,body)=>{localStorage.setItem('qa-saved',body);return true;},beginExport:metadata=>{window.qaExport={metadata:JSON.parse(metadata),chunks:[]};return 'qa-export';},appendExport:(id,data)=>{window.qaExport.chunks.push(data);return true;},finishExport:()=>window.onNativeEvent('exported',{name:'QA export',id:'qa-export'})};
  });
  await page.goto('http://127.0.0.1:'+server.address().port);await page.waitForFunction(()=>window.LightForgeApp?.state.show&&!LightForgeApp.state.composing,{},{timeout:60000});
  assert.equal(await page.evaluate(()=>LightForgeApp.vehiclePreview.ready),true);
  await page.locator('#workspace-review').click();await page.locator('#cueWorkspace').evaluate(e=>e.open=true);
  await page.locator('#musicCueStart').fill('24.137');await page.locator('#musicCueEnd').fill('25.719');await page.locator('#musicCueAction').selectOption('hold');await page.locator('#musicCueLabel').fill('Final voice hold');await page.locator('#saveMusicCue').click();
  await page.waitForFunction(()=>LightForgeApp.state.settings.musicCues.length===1&&!LightForgeApp.state.composing);
  const frameHash=await page.evaluate(()=>LightForgeApp.state.compiled.sha256);
  assert.equal(await page.evaluate(()=>LightForgeApp.state.show.synchronization.manual[0].status),'matched');receipt.checks.push('Visible cue form generated a matching final FSEQ attack using actual browser workers.');
  await page.locator('#workspace-compose').click();await page.locator('#undo').click();await page.waitForFunction(()=>!LightForgeApp.state.settings.musicCues.length&&!LightForgeApp.state.composing);await page.locator('#redo').click();await page.waitForFunction(()=>LightForgeApp.state.settings.musicCues.length===1&&!LightForgeApp.state.composing);assert.equal(await page.evaluate(()=>LightForgeApp.state.compiled.sha256),frameHash);receipt.checks.push('Undo/Redo restored identical frame checksum.');
  await page.locator('#export').click();await page.waitForFunction(()=>window.qaExport?.chunks.length&&!LightForgeApp.state.busy);
  const exp=await page.evaluate(()=>qaExport),bytes=Buffer.concat(exp.chunks.map(c=>Buffer.from(c,'base64'))),offset=bytes.readUInt16LE(4);
  assert.equal(crypto.createHash('sha256').update(bytes.subarray(offset)).digest('hex'),frameHash);assert.equal(exp.metadata.projectState.provenance.app,'2.2.4');assert.equal(exp.metadata.validation.synchronization.manual[0].status,'matched');
  fs.writeFileSync(path.join(out,'browser-export.fseq'),bytes);fs.writeFileSync(path.join(out,'browser-export-project.json'),JSON.stringify(exp.metadata.projectState));receipt.checks.push('Streamed export payload matches the saved frame SHA-256 and contains synchronization review.');
  await page.locator('#exportDone').click();await page.reload();await page.waitForFunction(()=>window.LightForgeApp?.state.show&&!LightForgeApp.state.composing);assert.equal(await page.evaluate(()=>LightForgeApp.state.compiled.sha256),frameHash);receipt.checks.push('Reload preserved exact compiled frames and musical edits.');
  await page.locator('#export').click();await page.waitForFunction(()=>window.qaExport?.chunks.length&&!LightForgeApp.state.busy);assert.equal(await page.evaluate(()=>qaExport.metadata.validation.synchronization.manual[0].status),'matched');await page.locator('#exportDone').click();receipt.checks.push('Export after reopening retained the verified synchronization report.');
  await page.locator('#workspace-review').click();await page.locator('#cueWorkspace').evaluate(e=>e.open=true);await page.locator('#syncDetails').evaluate(e=>e.open=true);
  for(const width of [320,393,768,1440]){
   await page.setViewportSize({width,height:960});await page.locator('#workspace-compose').click();await page.locator('#carCanvas').scrollIntoViewIfNeeded();await page.evaluate(async()=>{await LightForgeApp.vehiclePreview.ready;LightForgeApp.renderFrame(0);await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);});await page.screenshot({path:path.join(out,'precision-'+width+'.png'),fullPage:true,animations:'disabled'});
   assert.doesNotMatch(await page.locator('#totalTime').innerText(),/NaN|Infinity/);
   const layout=await page.evaluate(()=>({client:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,duplicates:[...document.querySelectorAll('[id]')].map(e=>e.id).filter((x,i,a)=>a.indexOf(x)!==i)}));assert.ok(layout.scroll<=layout.client+1,JSON.stringify({width,layout}));assert.equal(layout.duplicates.length,0);
  }
  for(const id of ['compose','music','outputs','review']){await page.locator('#workspace-'+id).click();assert.equal(await page.locator('#panel-'+id).isVisible(),true);await page.locator('#panel-'+id).screenshot({path:path.join(out,'workspace-'+id+'.png')});}await page.locator('#workspace-compose').focus();await page.keyboard.press('ArrowRight');assert.equal(await page.locator('#workspace-music').getAttribute('aria-selected'),'true');await page.locator('#scoreZoomIn').click();await page.waitForFunction(()=>document.getElementById('scoreScale').textContent!=='Full track');assert.doesNotMatch(await page.locator('#scoreScale').innerText(),/Full track/);receipt.checks.push('Workspace tabs support keyboard navigation; musical score zoom is operational.');
  receipt.checks.push('320, 393, 768 and 1440 px layouts have no horizontal overflow or duplicate IDs; screenshots retained.');
  for(const width of [393,1440]){await page.setViewportSize({width,height:960});for(const view of ['shows','guide']){await page.locator('.nav-item[data-navigate="'+view+'"]').click();assert.equal(await page.locator('#'+view).isVisible(),true);assert.equal(await page.locator('#'+view+'Title').isVisible(),true);assert.equal(await page.locator('.nav-item[data-navigate="'+view+'"]').getAttribute('aria-current'),'page');if(view==='shows')assert.equal(await page.locator('#showList .saved-show').count(),1);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth+1));await page.screenshot({path:path.join(out,view+'-'+width+'.png'),fullPage:true,animations:'disabled'});}}
  const backgroundDraws=await page.evaluate(async()=>{await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);const canvas=document.getElementById('scoreCanvas'),context=canvas.getContext('2d'),original=context.clearRect;let draws=0;context.clearRect=function(...args){draws++;return original.apply(this,args);};const audio=document.getElementById('audio');await audio.play();await new Promise(r=>setTimeout(r,400));audio.pause();context.clearRect=original;return draws;});assert.equal(backgroundDraws,0);receipt.checks.push('The source-time score stops drawing when its workspace is offscreen during audio playback.');
  const fresh=await browser.newPage({viewport:{width:393,height:852}});fresh.on('pageerror',e=>errors.push(e.message));await fresh.addInitScript(()=>{window.Android={pickAudio(){},getBootstrap:()=>JSON.stringify({projects:[],version:'2.2.4'})};});await fresh.goto('http://127.0.0.1:'+server.address().port);await fresh.waitForFunction(()=>!!window.LightForgeApp);assert.equal(await fresh.locator('#emptyCard').isVisible(),true);assert.ok(await fresh.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth+1));await fresh.screenshot({path:path.join(out,'first-launch-393.png'),fullPage:true,animations:'disabled'});await fresh.close();receipt.checks.push('First launch, saved-show collection and vehicle guide render without overflow or page errors at phone and desktop sizes.');
  assert.deepEqual(errors,[]);assert.deepEqual(hashes(),receipt.source_hashes);verified=true;
 }catch(error){if(page){await page.screenshot({path:path.join(out,'failure.png'),fullPage:true,animations:'disabled'}).catch(()=>{});receipt.failure=await page.evaluate(()=>({text:document.body.innerText,state:window.LightForgeApp?{project:LightForgeApp.state.project,loading:LightForgeApp.state.loadingProject,music:!!LightForgeApp.state.music,show:!!LightForgeApp.state.show,saveBlocked:LightForgeApp.state.saveBlocked,composing:LightForgeApp.state.composing}:null})).catch(()=>null);}receipt.errors.push(errorText(error));console.error(errorText(error));}finally{
  try{await browser?.close();}catch(error){receipt.errors.push(errorText(error));console.error(errorText(error));}
  if(server?.listening)try{await new Promise((resolve,reject)=>server.close(error=>error?reject(error):resolve()));}catch(error){receipt.errors.push(errorText(error));console.error(errorText(error));}
 }
 receipt.passed=verified&&receipt.errors.length===0;receipt.completedAt=new Date().toISOString();writeJsonAtomic(output,receipt);console.log(JSON.stringify(receipt,null,2));if(!receipt.passed)process.exitCode=1;
})().catch(error=>{console.error(errorText(error));process.exitCode=1;});
