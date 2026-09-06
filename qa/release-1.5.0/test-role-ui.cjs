/* Musical-role interface verification. Annotated fixtures isolate UI from model accuracy. */
const {chromium}=require('/opt/codex/runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),path=require('path'),cp=require('child_process'),assert=require('assert'),crypto=require('crypto');
const root=path.resolve(__dirname,'../..'),port=8815,origin=`http://127.0.0.1:${port}`;
const chrome=path.resolve(root,'../toolchain/chrome/chrome-headless-shell-linux64/chrome-headless-shell');
const tracked=['web/music-insights.js','web/studio-tools.js','web/styles.css','web/index.html'];
const hashes=()=>Object.fromEntries(tracked.map(name=>[name,crypto.createHash('sha256').update(fs.readFileSync(path.join(root,name))).digest('hex')]));
const receipt={release:'1.5.0',started:new Date().toISOString(),checks:[],errors:[],externalRequests:[],limits:['Desktop Chromium with SwiftShader; no Android device or Tesla was tested.','Known vocal/bass annotations isolate UI behavior; this test does not measure inference accuracy.']};
const firstHashes=hashes();
async function idle(page){await page.waitForFunction(()=>!LightForgeApp.state.busy&&!LightForgeApp.state.composing&&!LightForgeApp.state.loadingProject&&LightForgeApp.state.show,{}, {timeout:60000});}
(async()=>{
 const server=cp.spawn('python3',['-m','http.server',String(port),'--bind','127.0.0.1','--directory',path.join(root,'web')],{stdio:'ignore'});let browser;
 try{
  await new Promise(r=>setTimeout(r,400));
  browser=await chromium.launch({executablePath:chrome,headless:true,args:['--no-sandbox','--disable-dev-shm-usage','--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport:{width:393,height:852},reducedMotion:'reduce'});
  page.on('pageerror',e=>receipt.errors.push(e.message));
  await page.route('**/*',route=>{const u=new URL(route.request().url());if(/^https?:$/.test(u.protocol)&&u.origin!==origin){receipt.externalRequests.push(u.href);return route.abort();}return route.continue();});
  await page.goto(origin);await page.waitForFunction(()=>window.StudioTools&&window.MusicInsights&&LightForgeApp.vehiclePreview.ready,{}, {timeout:45000});
  await page.locator('#browserFile').setInputFiles(path.join(root,'web/demo/glass-castle.wav'));
  await page.waitForFunction(()=>LightForgeApp.state.project&&!LightForgeApp.state.busy&&!LightForgeApp.state.loadingProject,{}, {timeout:45000});
  const fixture=JSON.parse(fs.readFileSync(path.join(root,'qa/music-1.3.0/current-demo-music.json'),'utf8'));
  fixture.analysisVersion=4;
  fixture.vocals={available:true,presence:'detected',confidence:.9,method:'Annotated UI fixture',phrases:[{start:2,end:4,confidence:.9,strength:.8},{start:7,end:9,confidence:.85,strength:.7},{start:14,end:19,confidence:.95,strength:.9}],envelope:[],envelopeStep:.02};
  fixture.bassNotes=[{start:1,end:1.6,midi:40,frequency:82.407,confidence:.9,strength:.9},{start:4,end:5,midi:45,frequency:110,confidence:.8,strength:.7},{start:7.2,end:8.5,midi:43,frequency:97.999,confidence:.9,strength:.8},{start:14.1,end:15,midi:40,frequency:82.407,confidence:.9,strength:.9}];
  fixture.bassAnalysis={method:'Annotated UI fixture',source:'mixture-estimate',confidence:.82,phrases:[],envelope:[],envelopeStep:.02};
  await page.evaluate(async music=>{LightForgeApp.state.music=music;LightForgeApp.state.needAnalysis=false;await LightForgeApp.regenerate({save:false});},fixture);await idle(page);
  assert.equal(await page.locator('#vocalPhraseCount').textContent(),'3');assert.equal(await page.locator('#bassNoteCount').textContent(),'4');
  assert.equal(await page.locator('#vocalConfidence').textContent(),'Strong evidence');
  assert(await page.locator('#musicalRoleTimelines').isVisible());
  assert.equal(await page.locator('#vocalFocus').inputValue(),'0.85');assert.equal(await page.locator('#bassFocus').inputValue(),'0.9');
  assert(await page.locator('#vocalFocus').isEnabled());
  receipt.checks.push('Known vocal/bass metadata renders separate estimated phrase/note counts and evidence labels; recommended emphasis controls are accessible and enabled.');
  await page.locator('#vocalTimelineSeek').fill('2.5');assert(Math.abs(await page.evaluate(()=>document.getElementById('audio').currentTime)-2.5)<.03);
  assert(await page.locator('#vocalNow').evaluate(e=>e.classList.contains('active')));assert(!(await page.locator('#bassNow').evaluate(e=>e.classList.contains('active'))));
  await page.locator('#nextBassNote').click();assert(Math.abs(await page.evaluate(()=>document.getElementById('audio').currentTime)-4)<.03);
  assert.match(await page.locator('#bassNow').textContent(),/A2/);
  await page.locator('#nextVocalPhrase').click();assert(Math.abs(await page.evaluate(()=>document.getElementById('audio').currentTime)-7)<.03);
  await page.locator('#bassTimelineSeek').fill('7.5');assert(await page.locator('#vocalNow').evaluate(e=>e.classList.contains('active')));assert(await page.locator('#bassNow').evaluate(e=>e.classList.contains('active')));
  assert.match(await page.locator('#bassTimelineSeek').getAttribute('aria-valuetext'),/estimated bass G2/);
  await page.locator('#vocalTimelineSeek').focus();await page.keyboard.press('ArrowRight');assert(Math.abs(await page.evaluate(()=>document.getElementById('audio').currentTime)-7.52)<.04);
  await page.evaluate(()=>{const a=document.getElementById('audio');a.currentTime=7.7;a.dispatchEvent(new Event('timeupdate'));});
  assert.equal(await page.locator('#vocalTimelineSeek').inputValue(),'7.7');
  receipt.checks.push('Pointer/range and keyboard timeline seeking drive real preview media time; next phrase/note buttons land on annotation boundaries; playhead chips distinguish overlap, rests and pitched note names.');
  await page.evaluate(()=>{const s=LightForgeApp.state;s.composing=true;document.dispatchEvent(new CustomEvent('lightforge:changed'));});
  for(const id of ['vocalFocus','bassFocus','resetMusicalFocus','nextVocalPhrase','nextBassNote','vocalTimelineSeek','bassTimelineSeek'])assert(await page.locator('#'+id).isDisabled(),id);
  await page.evaluate(()=>{LightForgeApp.state.composing=false;document.dispatchEvent(new CustomEvent('lightforge:changed'));});
  receipt.checks.push('Composition gating disables focus edits and analysis-lane actions while a replacement show is being compiled.');
  await page.locator('#toast').waitFor({state:'hidden',timeout:8000});
  for(const width of [320,393,768]){
   await page.setViewportSize({width,height:width===768?960:852});await page.waitForTimeout(250);
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`overflow ${width}`);
   await page.locator('#musicalRoles').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(__dirname,`musical-roles-${width}.png`)});
   await page.locator('.musical-focus').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(__dirname,`musical-focus-${width}.png`)});
  }
  receipt.checks.push('Role diagnostics and emphasis cards have no horizontal overflow at 320, 393 and 768 CSS pixels; screenshots captured for visual inspection.');
  await page.setViewportSize({width:393,height:852});await page.locator('.preview-card').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(__dirname,'musical-playhead-393.png')});
  // Empty/uncertain/failed model states must not claim instrumental certainty or relabel a transient as bass.
  for(const mode of ['not_detected','uncertain','unavailable','silent','legacy']){
   const music=JSON.parse(JSON.stringify(fixture));music.vocals.phrases=[];music.bassNotes=[];music.vocals.presence=mode==='not_detected'?'not_detected':'uncertain';music.vocals.available=mode!=='unavailable';if(mode==='legacy')music.analysisVersion=3;
   await page.evaluate(({music,mode})=>{const s=LightForgeApp.state;s.music=music;s.show={...s.show,stats:{...s.show.stats,silent:mode==='silent'}};document.dispatchEvent(new CustomEvent('lightforge:changed'));},{music,mode});
   const text=await page.locator('#roleAnalysisStatus').textContent();
   if(mode==='not_detected')assert.match(text,/No confident singing found/);
   if(mode==='uncertain')assert.match(text,/uncertain/);
   if(mode==='unavailable')assert.match(text,/unavailable/);
   if(mode==='silent')assert.match(text,/Silent audio/);
   if(mode==='legacy'){assert.match(text,/earlier music analysis/);assert(await page.locator('#vocalFocus').isDisabled());assert(await page.locator('#analyzeMusicalFocus').isVisible());assert(await page.locator('#musicalNow').isHidden());}
   assert(await page.locator('#musicalRoleTimelines').isHidden());assert(await page.locator('#nextVocalPhrase').isDisabled());assert(await page.locator('#nextBassNote').isDisabled());
  }
  receipt.checks.push('No-detection, uncertain, unavailable, silence and legacy analysis states use distinct honest wording; absent events never create timeline cues. Legacy focus controls remain disabled until re-analysis.');
  assert.deepEqual(receipt.errors,[]);assert.deepEqual(receipt.externalRequests,[]);
  receipt.sourceStable=JSON.stringify(firstHashes)===JSON.stringify(hashes());assert(receipt.sourceStable,'UI source changed during verification');receipt.sourceHashes=hashes();receipt.passed=true;
 }catch(error){receipt.passed=false;receipt.failure=error.stack;process.exitCode=1;}
 finally{receipt.completed=new Date().toISOString();fs.writeFileSync(path.join(__dirname,'role-ui-verification.json'),JSON.stringify(receipt,null,2));if(browser)await browser.close();server.kill();console.log(JSON.stringify(receipt,null,2));}
})();
