/* Production browser/neural/project/export integration for LightForge 1.3.0. */
const {chromium}=require('/opt/codex/runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),path=require('path'),assert=require('assert'),cp=require('child_process'),crypto=require('crypto');
const root=path.resolve(__dirname,'../..'),out=__dirname,port=8794,origin=`http://127.0.0.1:${port}`;
const chrome=path.resolve(root,'../toolchain/chrome/chrome-headless-shell-linux64/chrome-headless-shell');
const tracked=['web/app.js','web/music-insights.js','web/index.html','web/styles.css','web/engine/show-engine.js','web/engine/movement-planner.js','web/engine/light-planner.js','web/analysis/analyzer.js','web/analysis/dsp.js','web/engine/vehicle-profile.js','web/analysis/worker.js','web/preview/vehicle-preview.js','android/src/com/cyberbasslord/lightforge/MainActivity.java'];
const hashes=()=>Object.fromEntries(tracked.filter(p=>fs.existsSync(path.join(root,p))).map(p=>[p,crypto.createHash('sha256').update(fs.readFileSync(path.join(root,p))).digest('hex')]));
const receipt={release:'1.3.0',started:new Date().toISOString(),checks:[],errors:[],externalRequests:[],limits:['Desktop Chromium WebGL2/SwiftShader, not a physical phone or Tesla test.','Native export validator executes on the host JVM with production Java sources; Android codec/device execution is not claimed.']};
const startHashes=hashes();
async function snapshot(page){return page.evaluate(async()=>{const a=LightForgeApp,s=a.state;const digest=async bytes=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(x=>x.toString(16).padStart(2,'0')).join('');const light=[];for(let f=0;f<s.show.frameCount;f++)for(let c=0;c<30;c++)light.push(s.show.frames[f*200+c]);return{projectId:s.project.id,settings:JSON.stringify(s.settings),cues:s.settings.manualCues,mutes:s.settings.outputEnabled,frames:await digest(s.show.frames),lights:await digest(new Uint8Array(light)),fseq:await digest(ShowEngine.fseq(s.show)),audio:await digest(await(await fetch(s.project.audioUrl)).arrayBuffer()),music:JSON.stringify(s.music),analysisVersion:s.music.analysisVersion||1,workers:window.__workers.slice(),history:s.history.length,validation:s.show.validation,targets:s.show.choreography.targets};});}
async function ready(page){await page.waitForFunction(()=>window.LightForgeApp?.vehiclePreview?.getSnapshot()?.modelReady&&!LightForgeApp.state.loadingProject,{},{timeout:45000});}
(async()=>{
 const server=cp.spawn('python3',['-m','http.server',String(port),'--bind','127.0.0.1','--directory',path.join(root,'web')],{stdio:'ignore'});let browser;
 try{
  await new Promise(r=>setTimeout(r,450));browser=await chromium.launch({executablePath:chrome,headless:true,args:['--no-sandbox','--disable-dev-shm-usage','--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport:{width:393,height:852},reducedMotion:'reduce',acceptDownloads:true});
  page.on('pageerror',e=>receipt.errors.push(e.message));
  await page.addInitScript(()=>{window.__workers=[];const Native=window.Worker;window.Worker=class extends Native{constructor(url,options){super(url,options);window.__workers.push(String(url));}};});
  await page.route('**/*',route=>{const url=new URL(route.request().url());if(/^https?:$/.test(url.protocol)&&url.origin!==origin){receipt.externalRequests.push(url.href);return route.abort();}return route.continue();});
  await page.goto(origin);await ready(page);
  await page.locator('#browserFile').setInputFiles(path.join(root,'web/demo/glass-castle.wav'));
  await page.waitForFunction(()=>!!LightForgeApp.state.project&&!LightForgeApp.state.busy&&!LightForgeApp.state.loadingProject,{},{timeout:60000});
  assert.equal(await page.evaluate(()=>LightForgeApp.state.project.duration),64);
  await page.locator('#quickAction').click();await page.waitForFunction(()=>!LightForgeApp.state.busy&&!!LightForgeApp.state.show,{},{timeout:180000});
  assert.equal(await page.evaluate(()=>LightForgeApp.state.music.analysisVersion),2);
  assert.equal(await page.evaluate(()=>LightForgeApp.state.music.engine.neural),true);
  assert.equal(await page.evaluate(()=>ShowEngine.version),'1.3.0');
  const analysis=await page.evaluate(()=>{const m=LightForgeApp.state.music;return{engine:m.engine,analysisVersion:m.analysisVersion,bpm:m.bpm,meter:m.meter,beats:m.beats.length,downbeats:m.downbeats.length,onsets:m.onsets.length,phrases:m.phrases.length,impacts:m.impacts.length,timing:m.timing};});
  assert(analysis.beats>20);assert(analysis.phrases>1);assert(analysis.onsets>20);receipt.analysis=analysis;
  receipt.checks.push('Actual file-picker import converts the bundled 64-second music to project audio; a real offline BeatNet ONNX worker returns analysisVersion 2 and generates a valid 1.3.0 show.');
  await page.evaluate(()=>LightForgeApp.commitChannelSettings({manualCues:[{id:'integration-light',outputId:'left-combined',start:2,end:4,value:204},{id:'integration-rgb',outputId:'display',start:5,end:7,rgb:[18,171,239]},{id:'integration-fold',outputId:'mirrorL',start:8,end:10,value:191},{id:'integration-unfold',outputId:'mirrorL',start:13,end:15,value:63}],outputEnabled:{'right-tail':false}}));
  const current=await snapshot(page);assert(current.validation.valid,JSON.stringify(current.validation));
  await page.waitForTimeout(650);
  // Explicitly save a real 1.2-era analysis object with the new editor settings.
  const legacy=JSON.parse(fs.readFileSync(path.join(out,'baseline-demo-music.json'),'utf8'));
  await page.evaluate(async music=>{const a=LightForgeApp;a.state.music=music;a.regenerate();await new Promise(r=>setTimeout(r,650));},legacy);
  await page.reload();await ready(page);await page.waitForFunction(()=>!!LightForgeApp.state.show);
  const old=await snapshot(page);assert.equal(old.analysisVersion,1);assert.deepEqual(old.cues,current.cues);assert.deepEqual(old.mutes,current.mutes);assert.equal(old.projectId,current.projectId);assert.equal(old.audio,current.audio);assert.equal(old.workers.length,0);assert(old.validation.valid);
  assert.match(await page.locator('#musicInsightText').textContent(),/earlier beat analysis/);
  await page.locator('#channelStudio > summary').click();await page.evaluate(()=>ChannelStudio.select('left-combined'));await page.locator('.cue-open').first().click();await page.locator('#cueStart').fill('2.5');await page.locator('#saveCue').click();
  assert.equal((await snapshot(page)).cues.find(c=>c.id==='integration-light').start,2.5);
  const oldEdited=await snapshot(page);assert.equal(oldEdited.workers.length,0);
  await page.locator('#reanalyzeMusic').click();await page.waitForFunction(()=>!LightForgeApp.state.busy&&LightForgeApp.state.music?.analysisVersion===2,{},{timeout:180000});
  const upgraded=await snapshot(page);assert(upgraded.validation.valid,JSON.stringify(upgraded.validation));assert.equal(upgraded.projectId,current.projectId);assert.equal(upgraded.audio,current.audio);assert.deepEqual(upgraded.cues,oldEdited.cues);assert.deepEqual(upgraded.mutes,current.mutes);assert.equal(upgraded.workers.length,1);assert(!await page.locator('#reanalyzeMusic').evaluate(e=>e.classList.contains('upgrade-available')));
  receipt.checks.push('A stored version-1 analysis recalls and edits without a neural rerun. Re-analyze upgrades to version 2 while preserving project identity, exact audio, edited light/RGB/mirror cues and muted outputs.');
  await page.locator('#recomposeShow').click();const varied=await snapshot(page);assert.notEqual(varied.frames,upgraded.frames);assert.notEqual(varied.lights,upgraded.lights);assert.equal(varied.music,upgraded.music);assert.equal(varied.workers.length,upgraded.workers.length);assert.deepEqual(varied.cues,upgraded.cues);assert.deepEqual(varied.mutes,upgraded.mutes);
  await page.locator('#undo').click();await page.waitForTimeout(400);const undone=await snapshot(page);assert.equal(undone.frames,upgraded.frames);assert.equal(undone.fseq,upgraded.fseq);assert.equal(undone.settings,upgraded.settings);assert.equal(undone.workers.length,1);
  receipt.checks.push('New variation changes actual light-frame bytes without another Worker or audio analysis; custom cues and mutes persist. Undo restores the exact previous FSEQ and settings.');
  const displayed=await page.evaluate(()=>({meter:document.getElementById('insightMeter').textContent,phrases:Number(document.getElementById('insightPhrases').textContent),moments:Number(document.getElementById('insightMoments').textContent),targets:LightForgeApp.state.show.choreography.targets,phrasesActual:LightForgeApp.state.show.choreography.phrases.length,meterActual:LightForgeApp.state.music.meter}));
  assert.equal(Number(displayed.meter),displayed.meterActual);assert.equal(displayed.phrases,displayed.phrasesActual);assert.equal(displayed.moments,new Set(displayed.targets.map(t=>Math.round(t.time*50))).size);assert(displayed.moments>0);
  await page.locator('#movementPlanDetails > summary').click();
  const moment=await page.locator('.movement-moment').evaluateAll(nodes=>nodes.map(n=>({time:Number(n.dataset.time),label:n.textContent})));
  receipt.moments=[];
  for(const item of moment.slice(0,3)){
   await page.locator(`.movement-moment[data-time="${item.time}"]`).click();await page.waitForFunction(t=>Math.abs(LightForgeApp.vehiclePreview.getSnapshot().time-t)<.021,item.time);
   const data=await page.evaluate(t=>{const a=LightForgeApp,p=a.vehiclePreview,s=a.state.show;const group=s.choreography.targets.filter(x=>Math.round(x.time*50)===Math.round(t*50));const primary=group.find(x=>x.outputId==='trunk')||group[0],o=VehicleProfile.outputs.find(x=>x.id===primary.outputId);return{time:document.getElementById('audio').currentTime,paused:document.getElementById('audio').paused,preview:p.getSnapshot(),expected:ShowEngine.stateAt(s,t),camera:o?.camera||'front'};},item.time);
   assert(Math.abs(data.time-item.time)<.001);assert(data.paused);assert.equal(data.preview.view,data.camera);assert.equal(data.preview.frame,data.expected.frame);assert.deepEqual(data.preview.interior,data.expected.interior);
   for(const closure of data.preview.closures){const expected=data.expected.closures.find(c=>c.channel===closure.channel);assert.equal(closure.command,expected.command);assert(Math.abs(closure.position-expected.openFraction)<1e-8);}
   receipt.moments.push({time:item.time,label:item.label,camera:data.camera,frame:data.preview.frame});
  }
  receipt.checks.push('Music statistics match the actual generated plan. Tapping three planned moments seeks the audio clock and correct camera; preview RGB, closure command and estimated motor position match the same exported frame timeline.');
  const final=await snapshot(page);assert.equal(final.fseq,upgraded.fseq);await page.waitForTimeout(650);await page.reload();await ready(page);await page.waitForFunction(()=>!!LightForgeApp.state.show);
  const reloaded=await snapshot(page);assert.equal(reloaded.fseq,final.fseq);assert.equal(reloaded.settings,final.settings);assert.equal(reloaded.audio,final.audio);assert.equal(reloaded.projectId,final.projectId);assert.equal(reloaded.workers.length,0);
  const downloadPromise=page.waitForEvent('download');await page.evaluate(()=>LightForgeApp.exportShow());const download=await downloadPromise,archive=path.join(out,'integration-export.zip');await download.saveAs(archive);await page.locator('#exportDone').click();
  const py="import sys,zipfile,json,hashlib,wave,io,struct; z=zipfile.ZipFile(sys.argv[1]); a=z.read('LightShow/lightshow.wav'); s=z.read('LightShow/lightshow.fseq'); w=wave.open(io.BytesIO(a)); print(json.dumps({'crcError':z.testzip(),'fseq':hashlib.sha256(s).hexdigest(),'audio':hashlib.sha256(a).hexdigest(),'files':z.namelist(),'wav':[w.getnchannels(),w.getsampwidth(),w.getframerate(),w.getnframes()],'frameCount':struct.unpack_from('<I',s,14)[0],'step':s[18],'terminalDark':not any(s[-200:]),'project':json.loads(z.read('Review/LightForge_Project.json'))}))";
  const exported=JSON.parse(cp.execFileSync('python3',['-c',py,archive],{encoding:'utf8',maxBuffer:10000000}));assert.equal(exported.crcError,null);assert.equal(exported.fseq,final.fseq);assert.equal(exported.audio,final.audio);assert.deepEqual(exported.wav,[2,2,44100,2822400]);assert(exported.terminalDark);assert.equal(exported.project.projectId,final.projectId);assert.deepEqual(exported.project.settings.manualCues,final.cues);assert.deepEqual(exported.project.settings.outputEnabled,final.mutes);
  const regenerated=cp.execFileSync('node',['-e',"const E=require(process.argv[1]);let t='';process.stdin.on('data',s=>t+=s).on('end',()=>{const p=JSON.parse(t);process.stdout.write(Buffer.from(E.fseq(E.generate(p.music,p.settings))));});",path.join(root,'web/engine/show-engine.js')],{input:JSON.stringify(exported.project),maxBuffer:10000000});assert.equal(crypto.createHash('sha256').update(regenerated).digest('hex'),final.fseq);
  receipt.export={filename:download.suggestedFilename(),fseqSHA256:exported.fseq,audioSHA256:exported.audio,files:exported.files,frames:exported.frameCount,stepMs:exported.step};
  receipt.checks.push('Autosave/reload restores byte-identical show, music and edits without analysis. Actual Export produces a CRC-valid ZIP with 44.1 kHz stereo PCM16 WAV, terminal dark FSEQ and full editable project; fresh Node regeneration from that project is byte-identical.');
  receipt.mobile=[];await page.locator('#movementPlanDetails > summary').click();
  for(const width of [320,393,768]){await page.setViewportSize({width,height:width===768?1024:852});await page.locator('#musicIntelligence').scrollIntoViewIfNeeded();const size=await page.evaluate(()=>({viewport:innerWidth,scroll:document.documentElement.scrollWidth,body:document.body.scrollWidth}));assert.equal(size.scroll,width);assert.equal(size.body,width);receipt.mobile.push(size);await page.locator('#musicIntelligence').screenshot({path:path.join(out,`music-intelligence-${width}.png`)});}
  await page.setViewportSize({width:393,height:852});await page.locator('.movement-moment').first().click();await page.waitForTimeout(400);await page.locator('.preview-card').screenshot({path:path.join(out,'musical-arrival-preview.png')});
  receipt.checks.push('New music intelligence controls and movement moment cards fit 320, 393 and 768 pixel viewports with no horizontal overflow.');
  assert.deepEqual(receipt.errors,[]);assert.deepEqual(receipt.externalRequests,[]);receipt.checks.push('Bundled WebGL model, audio, neural analysis and editing complete with no JavaScript errors or external network requests.');
  const javaRoot=path.resolve(root,'../toolchain/jdk17/bin'),androidJar=path.resolve(root,'../toolchain/android-sdk/platforms/android-35/android.jar'),jsonJar=path.resolve(root,'../toolchain/test-json.jar'),classes=path.join(out,'native-classes');fs.mkdirSync(classes,{recursive:true});
  const javaSources=fs.readdirSync(path.join(root,'android/src/com/cyberbasslord/lightforge')).filter(n=>n.endsWith('.java')).map(n=>path.join(root,'android/src/com/cyberbasslord/lightforge',n));
  const sourceList=[...javaSources,path.join(root,'build/generated/com/cyberbasslord/lightforge/R.java'),path.join(root,'tests/NativeHardwareTest.java'),path.join(out,'NativeMusicIntegrationTest.java')];
  cp.execFileSync(path.join(javaRoot,'javac'),['-encoding','UTF-8','--release','8','-classpath',androidJar,'-d',classes,...sourceList],{stdio:'pipe'});
  const classpath=[classes,jsonJar,androidJar].join(':');
  const nativeReport=JSON.parse(cp.execFileSync(path.join(javaRoot,'java'),['-cp',classpath,'com.cyberbasslord.lightforge.NativeMusicIntegrationTest',archive,path.join(out,'native-export')],{encoding:'utf8'}));
  const nativeRegressions=cp.execFileSync(path.join(javaRoot,'java'),['-cp',classpath,'com.cyberbasslord.lightforge.NativeHardwareTest',path.join(root,'qa/hardware-1.2.0/fixtures')],{encoding:'utf8'}).trim();
  assert.equal(nativeReport.status,'PASS');assert.match(nativeRegressions,/PASS: 16/);assert.equal(nativeReport.sha256,final.fseq);
  receipt.native={report:nativeReport,regressions:nativeRegressions,source_hashes:Object.fromEntries(javaSources.map(p=>[path.relative(root,p),crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex')]))};
  fs.writeFileSync(path.join(out,'native-integration-verification.json'),JSON.stringify(receipt.native,null,2)+'\n');
  receipt.checks.push('Freshly compiled production Android Java export validator accepts the actual neural-composed USB archive; all 16 valid/invalid native command regressions pass on the host JVM.');
  receipt.source_hashes=hashes();assert.deepEqual(receipt.source_hashes,startHashes,'Production sources changed during integration; rerun the final test.');receipt.passed=true;
 }catch(e){receipt.passed=false;receipt.failure=e.stack;throw e;}
 finally{receipt.completed=new Date().toISOString();fs.writeFileSync(path.join(out,'integration-verification.json'),JSON.stringify(receipt,null,2)+'\n');if(browser)await browser.close();server.kill();console.log(JSON.stringify(receipt,null,2));}
})().catch(e=>{console.error(e);process.exitCode=1;});
