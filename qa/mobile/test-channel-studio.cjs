/* UI integration for individual output editing; production renderer and generator. */
const {chromium}=require('/opt/codex/runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),path=require('path'),assert=require('assert'),cp=require('child_process');
const root=path.resolve(__dirname,'../..'),origin='http://127.0.0.1:8778';
const chrome='/workspace/scratch/9b34d7a394e6/app/toolchain/chrome/chrome-headless-shell-linux64/chrome-headless-shell';
const output=path.join(root,'qa/hardware-1.2.0');fs.mkdirSync(output,{recursive:true});
const receipt={checks:[],errors:[],externalRequests:[],limits:['Synthetic beat analysis isolates editing; bundled demo WAV is real audio.','Desktop Chromium WebGL2 uses SwiftShader; this is not a physical phone or vehicle test.']};
async function select(page,id){await page.evaluate(id=>ChannelStudio.select(id),id);assert.equal(await page.locator('#outputSelect').inputValue(),id);}
async function addCue(page,{start,duration,value,rgb}){if(value!==undefined)await page.locator('#cueAction').selectOption(String(value));if(rgb)await page.locator('#cueColor').fill(rgb);await page.locator('#cueStart').fill(String(start));await page.locator('#cueDuration').fill(String(duration));await page.locator('#saveCue').click();}
async function state(page){return page.evaluate(async()=>{const a=LightForgeApp;const digest=async bytes=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(x=>x.toString(16).padStart(2,'0')).join('');return {settings:JSON.stringify(a.state.settings),frames:a.state.show?await digest(a.state.show.frames):null,fseq:a.state.show?await digest(ShowEngine.fseq(a.state.show,'lightshow.wav')):null,history:a.state.history.length,cues:a.state.settings.manualCues};});}
(async()=>{
 const server=cp.spawn('python3',['-m','http.server','8778','--bind','127.0.0.1','--directory',path.join(root,'web')],{stdio:'ignore'});let browser;
 try{
  await new Promise(r=>setTimeout(r,400));
  browser=await chromium.launch({executablePath:chrome,headless:true,args:['--no-sandbox','--disable-dev-shm-usage','--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport:{width:393,height:852},reducedMotion:'reduce',acceptDownloads:true});
  page.on('pageerror',e=>receipt.errors.push(e.message));
  await page.route('**/*',route=>{const url=new URL(route.request().url());if(/^https?:$/.test(url.protocol)&&url.origin!==origin){receipt.externalRequests.push(url.href);return route.abort();}return route.continue();});
  await page.goto(origin);await page.waitForFunction(()=>window.ChannelStudio&&LightForgeApp.vehiclePreview.ready,{},{timeout:45000});
  assert(await page.evaluate(()=>LightForgeApp.vehiclePreview.getSnapshot().modelReady));
  await page.evaluate(async()=>{
   const blob=await(await fetch('demo/glass-castle.wav')).blob();const id='individual-output-fixture';
   await new Promise((resolve,reject)=>{const request=indexedDB.open('lightforge',1);request.onupgradeneeded=()=>{if(!request.result.objectStoreNames.contains('audio'))request.result.createObjectStore('audio');if(!request.result.objectStoreNames.contains('projects'))request.result.createObjectStore('projects');};request.onsuccess=()=>{const tx=request.result.transaction('audio','readwrite');tx.objectStore('audio').put(blob,id);tx.oncomplete=resolve;tx.onerror=reject;};request.onerror=reject;});
   const project={id,name:'Individual output studio',duration:64,createdAt:Date.now(),audioUrl:URL.createObjectURL(blob),browser:true};
   LightForgeApp.state.projects=[project];localStorage.setItem('lightforge-projects',JSON.stringify([project]));await LightForgeApp.selectProject(project,true);
  });
  await page.locator('#channelStudio > summary').click();
  const expected={light:['left-outer','left-inner','left-signature','left-combined','left-front-turn','right-outer','right-inner','right-signature','right-combined','right-front-turn','park-markers','left-repeater','left-rear-turn','right-repeater','right-rear-turn','brakes','left-tail','right-tail','reverse','license-plate'],rgb:['display','rgb-right-rear','rgb-right-front','rgb-dash','rgb-left-front','rgb-left-rear'],closure:['mirrorL','mirrorR','windowFL','windowRL','windowFR','windowRR','trunk','charge']};
  for(const [kind,ids] of Object.entries(expected)){
   await page.locator(`[data-output-kind="${kind}"]`).click();
   assert.deepEqual(await page.locator('#outputSelect option').evaluateAll(nodes=>nodes.map(n=>n.value)),ids);
   for(const id of ids){await select(page,id);const choices=await page.locator('#cueAction option').evaluateAll(nodes=>nodes.map(n=>({value:n.value,label:n.textContent})));if(kind==='closure'){assert.deepEqual(choices.map(c=>c.value),id.startsWith('mirror')?['0','63','191','255']:['0','63','127','191','255']);assert.equal(await page.locator('#cueAction').inputValue(),'63');}if(id==='charge')assert(choices.find(c=>c.value==='127').label.includes('rainbow'));}
  }
  assert.equal(Object.values(expected).flat().length,34);
  assert.equal(await page.locator('.lamp-cell[data-channels="15"],.lamp-cell[data-channels="16"],.lamp-cell[data-channels="29"]').count(),0);
  receipt.checks.push('All 34 independently exposed control groups are selectable; unavailable fog channels are absent.');
  receipt.checks.push('Both mirror tracks expose Idle, Unfold, Fold and Stop; other six movement tracks also expose Dance; charge Dance is labeled rainbow LED.');
  await select(page,'windowFL');assert(await page.locator('#cueAction').isEnabled());assert(await page.locator('#saveCue').isDisabled());
  const beforeNoShow=await state(page);await page.locator('#inspectOutput').click();
  await page.waitForFunction(()=>LightForgeApp.state.soloPreview&&LightForgeApp.vehiclePreview.getSnapshot().time>0);
  assert.equal(await page.locator('#previewBadge').textContent(),'INSPECTION · PREVIEW ONLY');
  await page.evaluate(()=>LightForgeApp.stopInspection());assert.deepEqual(await state(page),beforeNoShow);
  await select(page,'display');assert(await page.locator('#cueColor').isEnabled());await page.locator('#cueColor').fill('#11aaee');await page.locator('#inspectOutput').click();
  await page.waitForFunction(()=>LightForgeApp.state.soloPreview);await page.evaluate(()=>LightForgeApp.stopInspection());
  receipt.checks.push('Before generation, real model inspection accepts movement commands and RGB colors without changing the project. Timed cue saving stays disabled.');
  await page.evaluate(()=>{const a=LightForgeApp;a.state.music={duration:64,bpm:93,beatConfidence:.94,beats:Array.from({length:99},(_,i)=>i*60/93),downbeats:Array.from({length:25},(_,i)=>i*240/93),onsets:Array.from({length:198},(_,i)=>({time:i*30/93,strength:.6+(i%4)*.1,band:i%2?'high':'bass'})),sections:[{start:0,end:16,energy:.5,label:'Opening'},{start:16,end:32,energy:.8,label:'Build'},{start:32,end:48,energy:1,label:'The drop'},{start:48,end:64,energy:.7,label:'Finale'}],waveform:Array.from({length:512},(_,i)=>.3+.55*Math.abs(Math.sin(i*.7)))};a.regenerate({save:false});});
  assert(await page.evaluate(()=>LightForgeApp.state.show.validation.valid));
  await select(page,'left-combined');await addCue(page,{start:2,duration:2,value:204});
  assert.equal((await state(page)).cues.length,1);assert.match(await page.locator('#channelMessage').textContent(),/Cue added/);
  assert.deepEqual(await page.evaluate(()=>{const s=LightForgeApp.state.show;return [7,9,11].map(ch=>s.frames[150*200+ch-1]);}),[204,204,204]);
  await page.locator('.cue-open').click();await addCue(page,{start:3,duration:2,value:230});
  assert.equal((await state(page)).cues.length,1);assert.equal((await state(page)).cues[0].start,3);
  const valid=await state(page);await addCue(page,{start:4,duration:2,value:255});assert.match(await page.locator('#channelMessage').textContent(),/overlap/);assert.deepEqual(await state(page),valid);
  await page.locator('#outputEnabled').uncheck();
  assert(await page.evaluate(()=>{const s=LightForgeApp.state.show;return [7,9,11].every(ch=>{for(let f=0;f<s.frameCount;f++)if(s.frames[f*200+ch-1])return false;return true;});}));
  await page.locator('#outputEnabled').check();await page.locator('.cue-remove').click();assert.equal((await state(page)).cues.length,0);
  await addCue(page,{start:2,duration:2,value:204});await page.locator('#clearOutputCues').click();assert.equal((await state(page)).cues.length,0);
  receipt.checks.push('Light cues add, edit, remove and restore automatic; combined aliases share all bytes; muting zeros all group aliases. Overlapping edits preserve settings, show bytes and undo history.');
  await select(page,'display');await addCue(page,{start:5,duration:2,rgb:'#12abef'});
  assert.deepEqual((await state(page)).cues[0].rgb,[18,171,239]);
  assert.deepEqual(await page.evaluate(()=>Array.from(LightForgeApp.state.show.frames.slice(300*200+175,300*200+178))),[18,171,239]);
  await page.locator('.cue-open').click();await addCue(page,{start:6,duration:1,rgb:'#22cc88'});assert.deepEqual((await state(page)).cues[0].rgb,[34,204,136]);
  await page.locator('.cue-remove').click();await addCue(page,{start:5,duration:2,rgb:'#12abef'});
  await select(page,'windowFL');await addCue(page,{start:1,duration:4,value:63});assert.equal((await state(page)).cues.filter(c=>c.outputId==='windowFL').length,2);assert.match(await page.locator('#outputCueList').textContent(),/Return closed/);await addCue(page,{start:8,duration:4,value:127});await addCue(page,{start:13,duration:4,value:191});
  assert.deepEqual(await page.evaluate(()=>{const s=LightForgeApp.state.show;return [.5,2,6,9,14,25].map(t=>s.frames[Math.floor(t*50)*200+36]);}),[0,63,0,127,191,0]);
  await page.locator('.cue-open').first().click();await addCue(page,{start:1,duration:3,value:63});assert.equal((await state(page)).cues.find(c=>c.outputId==='windowFL'&&c.start===1).end,4);
  await page.locator('.cue-row').filter({hasText:'Dance'}).locator('.cue-remove').click();assert.equal((await state(page)).cues.filter(c=>c.outputId==='windowFL').length,3);
  await page.locator('#clearOutputCues').click();assert.equal((await state(page)).cues.filter(c=>c.outputId==='windowFL').length,0);
  await select(page,'mirrorL');await addCue(page,{start:2,duration:2,value:191});assert.match(await page.locator('#outputCueList').textContent(),/Return unfolded/);assert.equal((await state(page)).cues.filter(c=>c.outputId==='mirrorL').length,2);await page.locator('#clearOutputCues').click();
  await select(page,'trunk');await addCue(page,{start:15,duration:8,value:127});assert.equal((await state(page)).cues.filter(c=>c.outputId==='trunk').length,3);assert.match(await page.locator('#outputCueList').textContent(),/Prepare to dance/);assert.match(await page.locator('#outputCueList').textContent(),/Return closed/);await page.locator('#clearOutputCues').click();
  receipt.checks.push('First window Open and mirror Fold can be added directly with visible automatic return cues. First trunk Dance inserts a visible preparatory Open and final Close.');
  receipt.checks.push('RGB cues write exact selected color bytes and support edit/delete; closure cues replace only their own automatic track with Idle gaps and support edit/delete/restore.');
  const beforeBudget=await state(page);
  const rejected=await page.evaluate(()=>{try{const base=LightForgeApp.state.settings.manualCues;LightForgeApp.commitChannelSettings({manualCues:[...base,...Array.from({length:7},(_,i)=>({id:'budget-'+i,outputId:'windowFL',start:i*5,end:i*5+4,value:i%2?191:63}))]});return null;}catch(e){return e.message;}});
  assert.match(rejected,/6|limit|actuation/i);assert.deepEqual(await state(page),beforeBudget);
  receipt.checks.push('An over-budget window track is rejected atomically; prior settings, exported bytes and undo history remain intact.');
  await select(page,'left-outer');assert.deepEqual(await page.locator('#cueAction option').evaluateAll(n=>n.map(x=>x.value)),['255','0']);await page.locator('#outerBeamRamping').check();assert.deepEqual(await page.locator('#cueAction option').evaluateAll(n=>n.map(x=>x.value)),['255','178','204','230','0','26','51','77']);await page.locator('#outerBeamRamping').uncheck();
  receipt.checks.push('Outer-beam ramps are opt-in; the UI exposes all six documented fade commands when enabled and reverts to on/off by default.');
  await select(page,'left-inner');await page.locator('#cueAction').selectOption('204');
  const beforeInspect=await state(page);await page.locator('#inspectOutput').click();await page.waitForFunction(()=>LightForgeApp.state.soloPreview&&LightForgeApp.vehiclePreview.getSnapshot().time>.15);
  assert.deepEqual(await state(page),beforeInspect);await page.evaluate(()=>LightForgeApp.stopInspection());assert.deepEqual(await state(page),beforeInspect);
  await page.locator('#inspectOutput').click();await page.locator('#play').click();await page.waitForFunction(()=>!LightForgeApp.state.soloPreview&&!document.getElementById('audio').paused);await page.locator('#play').click();
  assert.deepEqual(await state(page),beforeInspect);
  await page.locator('#inspectOutput').click();await page.evaluate(()=>LightForgeApp.state.soloPreview.started-=10000);await page.waitForFunction(()=>!LightForgeApp.state.soloPreview);assert.deepEqual(await state(page),beforeInspect);
  receipt.checks.push('Solo inspection leaves generated and exported FSEQ bytes unchanged; Stop, Play and natural completion restore the show.');
  await select(page,'windowFL');await addCue(page,{start:1,duration:4,value:63});
  await select(page,'left-combined');await addCue(page,{start:2,duration:2,value:204});
  const beforeReload=await state(page);await page.waitForTimeout(700);await page.reload();await page.waitForFunction(()=>window.ChannelStudio&&LightForgeApp.vehiclePreview.ready&&LightForgeApp.state.show&&!LightForgeApp.state.loadingProject,{},{timeout:45000});
  const afterReload=await state(page);assert.equal(afterReload.settings,beforeReload.settings);assert.equal(afterReload.frames,beforeReload.frames);assert.equal(afterReload.fseq,beforeReload.fseq);assert.deepEqual(afterReload.cues,beforeReload.cues);
  receipt.checks.push('Reload restores project metadata, IndexedDB audio, all three cue kinds and byte-identical regenerated export.');
  const downloadPromise=page.waitForEvent('download');await page.evaluate(()=>LightForgeApp.exportShow());const download=await downloadPromise;const archive=path.join(output,'channel-studio-export.zip');await download.saveAs(archive);
  const exported=JSON.parse(cp.execFileSync('python3',['-c',"import sys,zipfile,json,hashlib; z=zipfile.ZipFile(sys.argv[1]); p=json.loads(z.read('Review/LightForge_Project.json')); print(json.dumps({'crcError':z.testzip(),'fseq':hashlib.sha256(z.read('LightShow/lightshow.fseq')).hexdigest(),'cues':p['settings']['manualCues'],'files':z.namelist()}))",archive],{encoding:'utf8'}));assert.equal(exported.crcError,null);assert.equal(exported.fseq,beforeReload.fseq);assert.deepEqual(exported.cues,beforeReload.cues);receipt.export={fseqSHA256:exported.fseq,files:exported.files};await page.locator('#exportDone').click();
  receipt.checks.push('The actual browser Export action produces a CRC-valid USB ZIP containing the same FSEQ bytes and project cue edits.');
  await page.locator('#channelStudio > summary').click();await select(page,'windowFL');
  receipt.mobile=[];
  for(const width of [320,393,768]){await page.setViewportSize({width,height:width===768?1024:852});await page.locator('#channelStudio').scrollIntoViewIfNeeded();const dimensions=await page.evaluate(()=>({viewport:innerWidth,scroll:document.documentElement.scrollWidth,body:document.body.scrollWidth}));assert.equal(dimensions.scroll,width);assert.equal(dimensions.body,width);receipt.mobile.push(dimensions);await page.locator('#channelStudio').screenshot({path:path.join(output,`channel-studio-${width}.png`)});}
  receipt.checks.push('Individual output editor fits 320 px, 393 px and 768 px without document overflow.');
  assert.deepEqual(receipt.externalRequests,[]);assert.deepEqual(receipt.errors,[]);receipt.checks.push('Production bundled model and new editor operate without external network requests or JavaScript errors.');receipt.passed=true;
 }catch(e){receipt.passed=false;receipt.failure=e.stack;throw e;}
 finally{fs.writeFileSync(path.join(output,'channel-ui-verification.json'),JSON.stringify(receipt,null,2));if(browser)await browser.close();server.kill();console.log(JSON.stringify(receipt,null,2));}
})().catch(e=>{console.error(e);process.exitCode=1;});
