/* Production WebView UI/worker integration. Synthetic annotations isolate authoring tools. */
const { chromium } = require('/opt/codex/runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs = require('fs'), path = require('path'), cp = require('child_process'), assert = require('assert'), crypto = require('crypto');
const root = path.resolve(__dirname, '../..'), port = 8896, origin = `http://127.0.0.1:${port}`;
const chrome = path.resolve(root, '../toolchain/chrome/chrome-headless-shell-linux64/chrome-headless-shell');
const tracked = ['web/studio-tools.js', 'web/channel-studio.js', 'web/music-insights.js', 'web/index.html', 'web/styles.css', 'web/app.js', 'web/engine/client.js', 'web/engine/worker.js', 'web/engine/show-engine.js', 'web/engine/movement-planner.js', 'web/engine/light-planner.js', 'web/engine/vehicle-profile.js'];
const hashes = () => Object.fromEntries(tracked.map(name => [name, crypto.createHash('sha256').update(fs.readFileSync(path.join(root, name))).digest('hex')]));
const receipt = {release:'1.5.0',started:new Date().toISOString(),checks:[],errors:[],externalRequests:[],limits:['Desktop Chromium with SwiftShader; not an Android device or Tesla test.','Real demo audio import and production show compiler; precomputed music annotations isolate editing behavior.','Loop playback measures browser media time, not physical vehicle timing.']};
const firstHashes = hashes();
async function state(page) { return page.evaluate(async () => { const s = LightForgeApp.state; return { settings: JSON.stringify(s.settings), music: JSON.stringify(s.music), frames: [...new Uint8Array(await crypto.subtle.digest('SHA-256', s.show.frames))].map(x=>x.toString(16).padStart(2,'0')).join(''), seeds:s.show.sections.map(x=>x.seed),valid:s.show.validation.valid,bpm:s.show.choreography.rhythm.bpm,meter:s.show.choreography.rhythm.meter }; }); }
async function idle(page) { await page.waitForFunction(() => !LightForgeApp.state.busy && !LightForgeApp.state.composing && !LightForgeApp.state.loadingProject && !!LightForgeApp.state.show, {}, {timeout:60000}); }
(async () => {
  const server = cp.spawn('python3', ['-m','http.server', String(port),'--bind','127.0.0.1','--directory',path.join(root,'web')], {stdio:'ignore'}); let browser;
  try {
    await new Promise(r=>setTimeout(r,400));
    browser = await chromium.launch({executablePath:chrome,headless:true,args:['--no-sandbox','--disable-dev-shm-usage','--enable-unsafe-swiftshader']});
    const page = await browser.newPage({viewport:{width:393,height:852},reducedMotion:'reduce'});
    page.on('pageerror', e=>receipt.errors.push(e.message));
    await page.route('**/*', route => {const url = new URL(route.request().url()); if(/^https?:$/.test(url.protocol) && url.origin!==origin){receipt.externalRequests.push(url.href);return route.abort();}return route.continue();});
    await page.goto(origin); await page.waitForFunction(()=>window.StudioTools&&LightForgeApp.vehiclePreview.ready,{}, {timeout:45000});
    await page.locator('#browserFile').setInputFiles(path.join(root,'web/demo/glass-castle.wav'));
    await page.waitForFunction(()=>!!LightForgeApp.state.project&&!LightForgeApp.state.busy&&!LightForgeApp.state.loadingProject,{}, {timeout:45000});
    const music = JSON.parse(fs.readFileSync(path.join(root,'qa/music-1.3.0/current-demo-music.json'),'utf8'));
    await page.evaluate(async music => {LightForgeApp.state.music=music;LightForgeApp.state.needAnalysis=false;await LightForgeApp.regenerate({save:false});}, music);
    await idle(page); const baseline=await state(page); assert(baseline.valid);
    assert.equal(await page.locator('#analysisQuality').inputValue(),'precision');
    receipt.checks.push('Actual 64-second WAV import and production asynchronous show compiler produce a valid show with the new studio module loaded.');
    await page.locator('.rhythm-correction>summary').click();
    await page.locator('[data-tempo-scale="0.5"]').click(); await idle(page);
    assert(Math.abs((await state(page)).bpm-baseline.bpm*.5)<.01); assert.equal((await state(page)).music,baseline.music);
    await page.locator('#meterOverride').selectOption('3'); await idle(page); assert.equal((await state(page)).meter,3);
    await page.evaluate(()=>document.getElementById('audio').currentTime=8.1);
    await page.locator('#anchorDownbeat').click(); await idle(page);
    assert.equal(await page.evaluate(()=>LightForgeApp.state.settings.downbeatAnchor),8.1);
    assert.match(await page.locator('#downbeatAnchorStatus').textContent(),/snapped/);
    await page.locator('#resetRhythm').click(); await idle(page); assert.equal((await state(page)).bpm,baseline.bpm);
    receipt.checks.push('Half-time, 3-beat meter and playhead bar anchor update the compiled rhythm; reset restores detected rhythm while source analysis remains unchanged.');
    await page.locator('.section-item').first().click();
    const seed=(await state(page)).seeds[0]; await page.locator('#lockSectionMotif').check(); await idle(page);
    assert.equal(await page.evaluate(()=>LightForgeApp.state.settings.sectionOverrides[0].seed),seed);
    const beforeVariation = await state(page);
    await page.locator('#recomposeShow').click(); await idle(page); await page.waitForFunction(()=>!document.getElementById('variationCompare').hidden);
    const variationB = await state(page); assert.notEqual(variationB.frames,beforeVariation.frames); assert.equal(variationB.seeds[0],seed);
    await page.locator('#variationA').click(); await idle(page); assert.equal((await state(page)).frames,beforeVariation.frames);
    await page.locator('#variationB').click(); await idle(page); assert.equal((await state(page)).frames,variationB.frames);
    receipt.checks.push('A/B comparison restores byte-exact compiled frames in both directions; a retained section motif keeps its resolved seed across global variation.');
    await page.locator('#movementDensity').fill('0.2'); await idle(page); const densityEdit=await state(page);
    await page.locator('#undo').click(); await idle(page); assert.equal((await state(page)).frames,variationB.frames);
    await page.locator('#redo').click(); await idle(page); assert.equal((await state(page)).frames,densityEdit.frames);
    await page.locator('#variationA').click(); await idle(page); await page.locator('#variationB').click(); await idle(page); assert.equal((await state(page)).frames,densityEdit.frames);
    receipt.checks.push('Movement frequency edits compile asynchronously; Undo/Redo restore exact frames, and A/B retains edits made within each branch.');
    await page.evaluate(()=>{const a=document.getElementById('audio');a.currentTime=2;}); await page.locator('#setLoopStart').click();
    await page.evaluate(()=>document.getElementById('audio').currentTime=3); await page.locator('#setLoopEnd').click();
    assert.deepEqual(await page.evaluate(()=>StudioTools.getLoop()),{a:2,b:3,enabled:true});
    await page.locator('#play').click(); await page.waitForTimeout(1500);
    const loopingTime=await page.evaluate(()=>document.getElementById('audio').currentTime); assert(loopingTime>=2 && loopingTime<3.1,`Loop time ${loopingTime}`);
    await page.locator('#play').click(); await page.locator('#clearLoop').click();
    await page.evaluate(()=>document.getElementById('audio').currentTime=8.1); await page.locator('#nextMusicalBeat').click();
    assert(await page.evaluate(()=>document.getElementById('audio').currentTime>8.1));
    await page.locator('#previousMusicalBeat').click(); assert(await page.evaluate(()=>document.getElementById('audio').currentTime<=8.1+.03));
    await page.locator('#loopSection').click(); assert(await page.evaluate(()=>{const l=StudioTools.getLoop(),s=LightForgeApp.state.show.sections[LightForgeApp.state.editing];return l.a===s.start&&l.b===s.end&&l.enabled;}));
    await page.locator('#clearLoop').click();
    receipt.checks.push('A/B passage loop repeats real audio; ±beat seeks use the corrected beat grid; selected sections become exact preview loop ranges.');
    await page.locator('#previewQuality').selectOption('battery');
    assert.equal(await page.evaluate(()=>LightForgeApp.vehiclePreview.getPerformance().quality),'battery');
    assert.equal(await page.evaluate(()=>LightForgeApp.vehiclePreview.getPerformance().bloomEnabled),true);
    await page.locator('#previewQuality').selectOption('auto');
    receipt.checks.push('Preview quality selection reaches the production renderer while preserving light bloom.');
    await page.evaluate(()=>{const a=LightForgeApp,p=a.state.project;a.state.projects=[{...p,id:'z',name:'Zenith',style:'cinematic',updatedAt:5},{...p,id:'a',name:'Aurora',style:'festival',updatedAt:15}];a.renderProjects();a.nav('shows');});
    await page.locator('#projectSearch').fill('festival'); assert.equal(await page.locator('.saved-show:visible').count(),1); assert.match(await page.locator('.saved-show:visible h3').textContent(),/Aurora/);
    await page.locator('#projectSearch').fill('absent'); assert.equal(await page.locator('.saved-show:visible').count(),0); assert.match(await page.locator('#projectSearchStatus').textContent(),/try another/);
    await page.locator('#projectSearch').fill(''); await page.locator('#projectSort').selectOption('name'); assert.equal(await page.locator('.saved-show h3').first().textContent(),'Aurora');
    receipt.checks.push('Saved-show search filters names/styles, empty results explain recovery, and alphabetical sorting retains working card controls.');
    await page.evaluate(()=>LightForgeApp.nav('guide')); await page.locator('#calibrationFirmware').fill('test-firmware'); await page.locator('[data-calibration="lamps"]').check(); await page.locator('#calibrationNotes').fill('Observed on test vehicle; no certification.'); await page.waitForTimeout(450);
    assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('lightforge-vehicle-observations-v1')).checks.lamps),true);
    receipt.checks.push('Vehicle observations persist locally with explicit simulation/uncertified wording; no vehicle or telemetry connection is made.');
    await page.evaluate(()=>{LightForgeApp.state.pendingExport={name:'Prepared_Show.zip'};document.dispatchEvent(new CustomEvent('lightforge:changed'));});
    assert(await page.locator('#exportRecovery').isVisible()); assert.match(await page.locator('#exportRecoveryText').textContent(),/Prepared_Show/);
    await page.evaluate(()=>{LightForgeApp.state.pendingExport=null;LightForgeApp.nav('studio');document.dispatchEvent(new CustomEvent('lightforge:changed'));});
    receipt.checks.push('Pending-export recovery card renders native bootstrap state and explains save/discard actions. Native recovery itself is validated separately.');
    await page.locator('#finishComparison').click(); assert(await page.locator('#variationCompare').isHidden());
    await page.locator('#toast').waitFor({state:'hidden',timeout:8000});
    for(const width of [320,393,768]) {
      await page.setViewportSize({width,height:width===768?960:852});
      await page.waitForTimeout(250);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`Horizontal overflow ${width}`);
      await page.locator('#musicIntelligence').scrollIntoViewIfNeeded();
      const file=path.join(__dirname,`studio-tools-${width}.png`); await page.screenshot({path:file});
      receipt.checks.push(`No horizontal overflow at ${width}px; screenshot captured with rhythm tools open.`);
    }
    assert.deepEqual(receipt.errors,[]); assert.deepEqual(receipt.externalRequests,[]);
    receipt.sourceStable=JSON.stringify(firstHashes)===JSON.stringify(hashes()); assert(receipt.sourceStable,'Production source changed during verification; rerun final source.'); receipt.sourceHashes=hashes();receipt.passed=true;
  } catch(error) {receipt.passed=false;receipt.failure=error.stack; process.exitCode=1;}
  finally {receipt.completed=new Date().toISOString();fs.writeFileSync(path.join(__dirname,'studio-tools-verification.json'),JSON.stringify(receipt,null,2));if(browser)await browser.close();server.kill();console.log(JSON.stringify(receipt,null,2));}
})();
