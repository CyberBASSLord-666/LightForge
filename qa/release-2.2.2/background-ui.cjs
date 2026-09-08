'use strict';
const {chromium}=require('playwright'),fs=require('fs'),path=require('path'),http=require('http'),crypto=require('crypto'),assert=require('assert/strict');
const root=path.resolve(__dirname,'../..'),out=__dirname;
const inputs=['qa/release-2.2.2/background-ui.cjs','version.json','web/version.js','web/app.js','web/diagnostics.js','web/diagnostics.css','web/index.html','web/styles.css','web/cockpit.css','web/cockpit.js'];
const receipt={release:'2.2.2',passed:false,checks:[],errors:[],source_hashes:Object.fromEntries(inputs.map(p=>[p,crypto.createHash('sha256').update(fs.readFileSync(path.join(root,p))).digest('hex')])),scope:'Real Chromium UI with a simulated Android job/status bridge; native background lifetime is tested separately on Android.'};
(async()=>{
 const server=http.createServer((req,res)=>{
  const url=new URL(req.url,'http://local');
  if(url.pathname==='/fixture.json'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({version:1,projectId:'qa-background',name:'Background session',settings:{dance:'off'},music:null,needAnalysis:true}));return;}
  const file=path.resolve(root,'web','.'+(url.pathname==='/'?'/index.html':url.pathname));
  if(!file.startsWith(path.join(root,'web')+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404).end();return;}
  res.setHeader('Content-Type',({'.js':'text/javascript','.html':'text/html','.css':'text/css','.json':'application/json','.wasm':'application/wasm','.wav':'audio/wav','.glb':'model/gltf-binary'})[path.extname(file)]||'application/octet-stream');
  res.setHeader('Cross-Origin-Opener-Policy','same-origin');res.setHeader('Cross-Origin-Embedder-Policy','require-corp');fs.createReadStream(file).pipe(res);
 });await new Promise(r=>server.listen(0,'127.0.0.1',r));let browser;
 try{
  browser=await chromium.launch({headless:true,args:['--no-sandbox','--enable-unsafe-swiftshader']});
  for(const width of [320,393,768]){
   const page=await browser.newPage({viewport:{width,height:852}});page.on('pageerror',e=>receipt.errors.push(e.message));
   await page.addInitScript(()=>{
    const project={id:'qa-background',name:'Background session',duration:12,audioUrl:'/demo/glass-castle.wav',projectUrl:'/fixture.json'};
    const capabilities={backgroundAnalysis:true,cpuCores:8,memoryBytes:16*1024**3,androidSdk:35,notifications:false,batteryOptimized:true,batteryRestricted:false};
    window.qaBackground={job:{id:'qa-job',projectId:project.id,name:project.name,state:'running',progress:.37,stage:'Studio · passage 3 of 24 · 47%',analysisStage:'separation',createdAt:Date.now()-245000,updatedAt:Date.now(),passageIndex:3,passageCount:24,passagesCompleted:2,restoredPassages:1,resumeAvailable:true},saves:0,continued:false,settings:[],logs:[],exports:0};
    window.Android={pickAudio(){},logDiagnostic:(...args)=>qaBackground.logs.push(args),exportDiagnostics(){qaBackground.exports++;},getBootstrap:()=>JSON.stringify({projects:[project],lastProjectId:project.id,version:'2.2.2',backgroundJob:qaBackground.job,deviceCapabilities:capabilities}),
     saveProject(){if(['running','queued'].includes(qaBackground.job?.state))throw Error('Stale UI save during background work');qaBackground.saves++;return true;},
     getAnalysisStatus:()=>JSON.stringify(qaBackground.job),getDeviceCapabilities:()=>JSON.stringify(capabilities),startAnalysis:()=>JSON.stringify(qaBackground.job),
     cancelAnalysis(){qaBackground.job={...qaBackground.job,state:'cancelled',stage:'Analysis cancelled. Your saved show is intact.'};},continueInBackground(){qaBackground.continued=true;},openBackgroundSettings(kind){qaBackground.settings.push(kind);}};
   });
   await page.goto('http://127.0.0.1:'+server.address().port);await page.locator('#processing').waitFor({state:'visible'});
   await page.waitForFunction(()=>document.getElementById('progressPercent').textContent==='37%');
   assert.match(await page.locator('#progressElapsed').textContent(),/Elapsed 4m/);
   assert.equal(await page.locator('#progressPassage').textContent(),'Passage 3 of 24');
   assert.match(await page.locator('#progressSaved').textContent(),/2 passages completed.*1 reused/);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'Viewport overflow at '+width);
   const box=await page.locator('.processing-dialog').boundingBox();assert.ok(box.x>=0&&box.x+box.width<=width+1);
   let previousBottom=0;
   for(const selector of ['#backgroundContinue','#backgroundPower','#cancelWork','#processing [data-export-diagnostics]']){
    const action=await page.locator(selector).boundingBox();
    assert.ok(action.height>=44&&action.y>=previousBottom+7,'Background actions need separate, accessible touch targets at '+width);
    previousBottom=action.y+action.height;
   }
   await page.screenshot({path:path.join(out,'background-progress-'+width+'.png')});
   await page.evaluate(()=>{qaBackground.job={...qaBackground.job,progressAt:Date.now()-100000};window.onNativeEvent('analysisJob',qaBackground.job);});
   assert.equal(await page.locator('#progressActivity').isVisible(),true);
   assert.match(await page.locator('#progressActivity').textContent(),/has not reported progress/);
   await page.screenshot({path:path.join(out,'background-waiting-'+width+'.png')});
   await page.evaluate(()=>{qaBackground.job={...qaBackground.job,progressAt:Date.now()};window.onNativeEvent('analysisJob',qaBackground.job);});
   await page.locator('#processing [data-export-diagnostics]').click();
   assert.equal(await page.locator('#processing [data-export-diagnostics]').isDisabled(),true);
   assert.match(await page.locator('#processing [data-diagnostic-status]').textContent(),/Preparing your log/);
   assert.equal(await page.evaluate(()=>qaBackground.exports),1);
   await page.evaluate(()=>window.onNativeEvent('diagnosticExportFailed',{message:'Not enough storage to save the log.'}));
   assert.equal(await page.locator('#processing [data-export-diagnostics]').isEnabled(),true);
   assert.match(await page.locator('#processing [data-diagnostic-status]').textContent(),/Not enough storage/);
   assert.equal(await page.evaluate(()=>LightForgeApp.state.busy),true);
   await page.locator('#processing [data-export-diagnostics]').click();
   await page.evaluate(()=>window.onNativeEvent('diagnosticExported',{name:'LightForge-diagnostics-test.txt',location:'Downloads/LightForge',uri:'content://media/external/downloads/1',bytes:2048}));
   assert.match(await page.locator('#processing [data-diagnostic-status]').textContent(),/Saved LightForge-diagnostics-test.txt to Downloads\/LightForge/);
   assert.equal(await page.evaluate(()=>LightForgeApp.state.busy),true);
   assert.equal(await page.evaluate(()=>qaBackground.saves),0);
   assert.ok(await page.evaluate(()=>qaBackground.logs.some(row=>row[1]==='progress'&&row[2].includes('passageIndex=3'))));
   await page.locator('#processing [data-export-diagnostics]').scrollIntoViewIfNeeded();
   await page.screenshot({path:path.join(out,'diagnostics-processing-'+width+'.png')});
   await page.locator('#backgroundPower').click();await page.locator('#backgroundContinue').click();
   assert.deepEqual(await page.evaluate(()=>({continued:qaBackground.continued,settings:qaBackground.settings,saves:qaBackground.saves})),{continued:true,settings:['power'],saves:0});
   await page.locator('#cancelWork').click();await page.locator('#backgroundRecovery').waitFor({state:'visible'});
   await page.screenshot({path:path.join(out,'background-recovery-'+width+'.png')});
   await page.locator('#backgroundRecovery [data-export-diagnostics]').click();
   await page.evaluate(()=>window.onNativeEvent('diagnosticExportFailed',{cancelled:true,message:'Canceled'}));
   assert.equal(await page.locator('#backgroundRecovery [data-export-diagnostics]').isEnabled(),true);
   await page.locator('#dismissDiagnosticRecovery').click();
   await page.evaluate(()=>LightForgeApp.nav('guide'));
   await page.locator('.diagnostics-card').scrollIntoViewIfNeeded();
   assert.equal(await page.locator('.diagnostics-card [data-export-diagnostics]').isVisible(),true);
   await page.screenshot({path:path.join(out,'diagnostics-guide-'+width+'.png')});
   await page.evaluate(()=>LightForgeApp.nav('guide'));await page.locator('#backgroundDevice').scrollIntoViewIfNeeded();
   const panel=await page.locator('#backgroundDevice').boundingBox();assert.ok(panel.x>=0&&panel.x+panel.width<=width+1,'Device panel overflow');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'Guide overflow at '+width);
   await page.screenshot({path:path.join(out,'background-settings-'+width+'.png')});
   receipt.checks.push('Elapsed time, passage completion/reuse, delayed progress, cancellation recovery and device settings and diagnostic export fit '+width+'px; export failure/retry/success/cancel acknowledgements preserve active work; background/power controls dispatch correctly and active inputs remain frozen.');await page.close();
  }
  for(const [p,h] of Object.entries(receipt.source_hashes))assert.equal(crypto.createHash('sha256').update(fs.readFileSync(path.join(root,p))).digest('hex'),h,'Source changed during visual verification: '+p);
  assert.equal(receipt.errors.length,0);receipt.passed=true;
 }catch(error){receipt.errors.push(error.stack);process.exitCode=1;}finally{await browser?.close();await new Promise(r=>server.close(r));}
 receipt.completedAt=new Date().toISOString();fs.writeFileSync(path.join(out,'background-ui-verification.json'),JSON.stringify(receipt,null,2));console.log(JSON.stringify(receipt));
})();
