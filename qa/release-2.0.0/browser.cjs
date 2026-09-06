'use strict';
/* CI browser integration. The Android bridge is simulated; WebGL, workers,
 * project editing, storage, audio, and exported bytes use the real web app. */
const {chromium}=require('playwright'),fs=require('node:fs'),path=require('node:path'),http=require('node:http'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),out=__dirname;
const music=JSON.parse(fs.readFileSync(path.join(root,'qa/release-1.6.0/actual-music-user-glass-prefix64-analysis.json')));
const fixture={version:1,name:'Glass Castle · Precision QA',settings:{style:'cinematic',dance:'off',seed:2025,vocalFocus:.85,bassFocus:.9,vocalRegions:[]},music};
const hashes=()=>Object.fromEntries(['web/app.js','web/index.html','web/styles.css','web/precision-studio.js','web/engine/worker.js','web/engine/client.js','web/engine/show-engine.js','web/engine/light-planner.js','web/engine/music-cues.js','web/engine/sync-review.js'].map(f=>[f,crypto.createHash('sha256').update(fs.readFileSync(path.join(root,f))).digest('hex')]));
(async()=>{
 const receipt={release:'2.0.0',passed:false,checks:[],errors:[],source_hashes:hashes(),scope:'Desktop Chromium with actual WebGL and web workers; simulated Android bridge. No Android device or Tesla.'};
 const server=http.createServer((req,res)=>{
  const pathname=decodeURIComponent(req.url.split('?')[0]);
  if(pathname==='/fixture.json'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify(fixture));return;}
  const p=path.resolve(root,'web','.'+(pathname==='/'?'/index.html':pathname));if(!p.startsWith(path.join(root,'web')+path.sep)){res.writeHead(403).end();return;}
  if(!fs.existsSync(p)||!fs.statSync(p).isFile()){res.writeHead(404).end();return;}
  res.setHeader('Content-Type',({'.js':'text/javascript','.html':'text/html','.css':'text/css','.json':'application/json','.wasm':'application/wasm','.wav':'audio/wav','.glb':'model/gltf-binary'})[path.extname(p)]||'application/octet-stream');
  res.setHeader('Cross-Origin-Opener-Policy','same-origin');res.setHeader('Cross-Origin-Embedder-Policy','require-corp');
  fs.createReadStream(p).pipe(res);
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));let browser;
 try{
  browser=await chromium.launch({headless:true,args:['--no-sandbox','--enable-unsafe-swiftshader']});const page=await browser.newPage({viewport:{width:393,height:852}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{
   const project={id:'qa-project',name:'Glass Castle · Precision QA',duration:64,audioUrl:'/demo/glass-castle.wav',projectUrl:'/fixture.json'};
   const fetchOriginal=window.fetch.bind(window);window.fetch=(input,options)=>String(input).endsWith('/fixture.json')&&localStorage.getItem('qa-saved')?Promise.resolve(new Response(localStorage.getItem('qa-saved'),{headers:{'Content-Type':'application/json'}})):fetchOriginal(input,options);
   window.Android={pickAudio(){},getBootstrap:()=>JSON.stringify({projects:[project],lastProjectId:project.id,version:'2.0.0'}),saveProject:(id,body)=>{localStorage.setItem('qa-saved',body);return true;},beginExport:metadata=>{window.qaExport={metadata:JSON.parse(metadata),chunks:[]};return 'qa-export';},appendExport:(id,data)=>{window.qaExport.chunks.push(data);return true;},finishExport:()=>window.onNativeEvent('exported',{name:'QA export',id:'qa-export'})};
  });
  await page.goto('http://127.0.0.1:'+server.address().port);await page.waitForFunction(()=>window.LightForgeApp?.state.show&&!LightForgeApp.state.composing,{},{timeout:60000});
  await page.locator('#cueWorkspace').evaluate(e=>e.open=true);
  await page.locator('#musicCueStart').fill('24.137');await page.locator('#musicCueEnd').fill('25.719');await page.locator('#musicCueAction').selectOption('hold');await page.locator('#musicCueLabel').fill('Final voice hold');await page.locator('#saveMusicCue').click();
  await page.waitForFunction(()=>LightForgeApp.state.settings.musicCues.length===1&&!LightForgeApp.state.composing);
  const frameHash=await page.evaluate(()=>LightForgeApp.state.compiled.sha256);
  assert.equal(await page.evaluate(()=>LightForgeApp.state.show.synchronization.manual[0].status),'matched');receipt.checks.push('Visible cue form generated a matching final FSEQ attack using actual browser workers.');
  await page.locator('#undo').click();await page.waitForFunction(()=>!LightForgeApp.state.settings.musicCues.length&&!LightForgeApp.state.composing);await page.locator('#redo').click();await page.waitForFunction(()=>LightForgeApp.state.settings.musicCues.length===1&&!LightForgeApp.state.composing);assert.equal(await page.evaluate(()=>LightForgeApp.state.compiled.sha256),frameHash);receipt.checks.push('Undo/Redo restored identical frame checksum.');
  await page.locator('#export').click();await page.waitForFunction(()=>window.qaExport?.chunks.length&&!LightForgeApp.state.busy);
  const exp=await page.evaluate(()=>qaExport),bytes=Buffer.concat(exp.chunks.map(c=>Buffer.from(c,'base64'))),offset=bytes.readUInt16LE(4);
  assert.equal(crypto.createHash('sha256').update(bytes.subarray(offset)).digest('hex'),frameHash);assert.equal(exp.metadata.projectState.provenance.app,'2.0.0');assert.equal(exp.metadata.validation.synchronization.manual[0].status,'matched');
  fs.writeFileSync(path.join(out,'browser-export.fseq'),bytes);fs.writeFileSync(path.join(out,'browser-export-project.json'),JSON.stringify(exp.metadata.projectState));receipt.checks.push('Streamed export payload matches the saved frame SHA-256 and contains synchronization review.');
  await page.locator('#exportDone').click();await page.reload();await page.waitForFunction(()=>window.LightForgeApp?.state.show&&!LightForgeApp.state.composing);assert.equal(await page.evaluate(()=>LightForgeApp.state.compiled.sha256),frameHash);receipt.checks.push('Reload preserved exact compiled frames and musical edits.');
  await page.locator('#cueWorkspace').evaluate(e=>e.open=true);await page.locator('#syncDetails').evaluate(e=>e.open=true);
  for(const width of [320,393,768,1440]){
   await page.setViewportSize({width,height:960});await page.locator('#precisionStudio').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'precision-'+width+'.png'),fullPage:true});
   const layout=await page.evaluate(()=>({client:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,duplicates:[...document.querySelectorAll('[id]')].map(e=>e.id).filter((x,i,a)=>a.indexOf(x)!==i)}));assert.ok(layout.scroll<=layout.client+1,JSON.stringify({width,layout}));assert.equal(layout.duplicates.length,0);
  }
  receipt.checks.push('320, 393, 768 and 1440 px layouts have no horizontal overflow or duplicate IDs; screenshots retained.');assert.deepEqual(errors,[]);assert.deepEqual(hashes(),receipt.source_hashes);receipt.passed=true;
 }catch(e){receipt.errors.push(e.stack);console.error(e.stack);}finally{await browser?.close();await new Promise(r=>server.close(r));}
 receipt.completedAt=new Date().toISOString();fs.writeFileSync(path.join(out,'browser-verification.json'),JSON.stringify(receipt,null,2)+'\n');console.log(JSON.stringify(receipt,null,2));if(!receipt.passed)process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1;});
