/* Actual offline WebGL renderer regression with source-bound, fail-closed results. */
const fs=require('fs'),assert=require('assert'),http=require('http'),crypto=require('crypto'),path=require('path');
const root=path.resolve(__dirname,'..'),version=JSON.parse(fs.readFileSync(path.join(root,'version.json'))).name,outDir=process.env.LIGHTFORGE_PREVIEW_OUTPUT||path.join(root,'qa','release-'+version),port=Number(process.env.LIGHTFORGE_PREVIEW_PORT||8899),origin='http://127.0.0.1:'+port;
fs.mkdirSync(outDir,{recursive:true});
const receiptPath=path.join(outDir,'preview-verification.json');
const out={release:version,scope:'Desktop Chromium WebGL2 with SwiftShader software rasterization; no Android phone GPU or vehicle testing.',startedAt:new Date().toISOString(),status:'running',passed:false,checks:[],errors:[],externalRequests:[],quality:[],screenshots:[]};
// Invalidate any earlier success before loading browser dependencies or assets.
fs.writeFileSync(receiptPath,JSON.stringify(out,null,2));
const files=['qa/locked-benchmark/local-http-security.cjs','web/version.js','web/preview/src/vehicle-preview.js','web/preview/src/highland-rig.js','web/preview/src/trunk-interior.js','web/preview/vehicle-preview.js','web/engine/show-engine.js','web/engine/light-planner.js','web/engine/movement-planner.js','web/engine/vehicle-profile.js','web/app.js','web/preview/models/highland.glb','tools/verify_preview_browser.cjs'];
const hashes=()=>Object.fromEntries(files.map(p=>[p,crypto.createHash('sha256').update(fs.readFileSync(root+'/'+p)).digest('hex')]));
const firstHashes=hashes();
const html=`<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>body{margin:0;background:#080d13;color:#e4efff;font:16px system-ui}main{width:390px;max-width:100%;padding-top:12px}h1,p{margin:12px;font-size:16px}canvas{display:block;width:100%;height:340px}button{padding:10px}#spacer{height:1800px}</style></head><body><main><h1>LightForge · Highland preview</h1><canvas id="carCanvas" tabindex="0"></canvas><p id="previewStatus"></p><button data-stage="studio">Studio</button><button data-stage="night">Night</button><p>2025 Model 3 · LR RWD · estimated motor travel</p></main><div id="spacer"></div><script src="version.js"></script><script src="engine/vehicle-profile.js"></script><script src="engine/light-planner.js"></script><script src="engine/movement-planner.js"></script><script src="engine/show-engine.js"></script><script src="preview/vehicle-preview.js"></script><script>window.preview=new VehiclePreview(document.querySelector('canvas'));window.qualityEvents=[];preview.canvas.addEventListener('previewperformance',e=>qualityEvents.push(e.detail));const frames=new Uint8Array(4000*200);function set(ch,start,end,v){for(let f=Math.floor(start*50);f<Math.floor(end*50);f++)frames[f*200+ch-1]=v;}set(3,1,3,204);set(5,0,3,255);set(25,0,3,255);set(28,0,3,255);set(30,0,3,255);set(37,0,.5,63);set(41,0,.5,63);set(35,0,.5,191);set(46,0,2,63);set(46,2,5,127);for(let f=0;f<4000;f++){frames[f*200+175]=64;frames[f*200+176]=128;frames[f*200+177]=255;}window.show={frames,frameCount:4000,stepMs:20,channels:200,channelCount:200,duration:80,sections:[{start:0,end:80,label:'Preview test'}]};window.renderAt=t=>preview.render(ShowEngine.stateAt(show,t),t);</script></body></html>`;
async function settle(page){await page.waitForFunction(()=>preview.loaded&&!preview._raf&&!preview.tween&&preview.renderCount>0,{},{timeout:30000});}
function assetServer(){
 const {allowLocalRequest}=require('../qa/locked-benchmark/local-http-security.cjs');
 const webRoot=path.join(root,'web');
 const mime={'.js':'application/javascript','.glb':'model/gltf-binary','.gz':'application/gzip','.json':'application/json','.png':'image/png','.jpg':'image/jpeg'};
 return http.createServer((request,response)=>{
  if(!allowLocalRequest(request,response))return;
  let name;try{name=path.resolve(webRoot,'.'+decodeURIComponent(new URL(request.url,origin).pathname));}catch{response.writeHead(400);response.end();return;}
  if(!name.startsWith(webRoot+path.sep)){response.writeHead(403);response.end();return;}
  const stream=fs.createReadStream(name);stream.once('open',()=>{response.setHeader('Content-Type',mime[path.extname(name)]||'application/octet-stream');stream.pipe(response);});stream.once('error',()=>{if(!response.headersSent)response.writeHead(404);response.end();});
 });
}
(async()=>{const server=assetServer();let browser;try{
 const {chromium}=require('playwright');
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',resolve);});
 browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_EXECUTABLE_PATH?{executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH}:{}),args:['--no-sandbox','--disable-dev-shm-usage','--enable-unsafe-swiftshader']});const page=await browser.newPage({viewport:{width:393,height:852},deviceScaleFactor:2,reducedMotion:'reduce'});page.on('pageerror',e=>out.errors.push(e.message));await page.route('**/*',r=>{const u=new URL(r.request().url());if(u.origin!==origin){out.externalRequests.push(u.href);return r.abort();}if(u.pathname==='/preview-test')return r.fulfill({contentType:'text/html',body:html});return r.continue();});await page.goto(origin+'/preview-test');assert(await page.evaluate(()=>preview.ready));await settle(page);
 out.graphics=await page.evaluate(()=>{const p=preview,gl=p.renderer.getContext();let meshes=0,triangles=0;p.rig.root.traverse(o=>{if(o.isMesh){meshes++;triangles+=(o.geometry.index?.count||o.geometry.attributes.position.count)/3;}});return {webgl2:gl instanceof WebGL2RenderingContext,renderer:gl.getParameter(gl.RENDERER),meshes,triangles};});assert(out.graphics.webgl2);assert(out.graphics.triangles>170000);out.checks.push('Loads unchanged detailed Highland geometry in actual WebGL2.');
 // Simulated media-clock delay verifies the actual bundled GPU submission path.
 const presentation=await page.evaluate(async()=>{window.mediaTime=0;preview.setStateSource(()=>({data:ShowEngine.stateAt(show,mediaTime),time:mediaTime,clock:'test-media-time'}));renderAt(0);mediaTime=1.5;await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);const result={snapshot:preview.getSnapshot(),presentation:preview.getPerformance().presentation};preview.setStateSource(null);return result;});
 assert.equal(presentation.presentation.frame,75);assert.equal(presentation.presentation.time,1.5);assert.equal(presentation.snapshot.frame,75);out.clockSubmission=presentation.presentation;out.checks.push('Bundled renderer reads the authoritative clock at GPU submission and replaces a deliberately stale queued frame.');
 await page.evaluate(()=>renderAt(1.5));await settle(page);
 const physicalSpill=await page.evaluate(()=>{const p=preview,world=light=>light.getWorldPosition(light.position.clone()).toArray();p.getSnapshot();const before={tail:world(p.tailSpill[0]),reverse:world(p.reverseSpill[0])};renderAt(15);p.getSnapshot();const after={tail:world(p.tailSpill[0]),reverse:world(p.reverseSpill[0])};const result={before,after,tailAttached:p.tailSpill.every(light=>light.parent===p.rig.parts.trunk&&light.target.parent===p.rig.parts.trunk),reverseBodyFixed:p.reverseSpill.every(light=>light.parent===p.scene),headlights:p.headlights.map(light=>light.intensity)};renderAt(1.5);p.getSnapshot();return result;});
 assert(physicalSpill.tailAttached&&physicalSpill.reverseBodyFixed);assert.deepStrictEqual(physicalSpill.before.reverse,physicalSpill.after.reverse);assert.notDeepStrictEqual(physicalSpill.before.tail,physicalSpill.after.tail);out.physicalSpill=physicalSpill;out.checks.push('Tail illumination originates at lid-mounted optics and moves with the trunk while fascia reverse illumination stays body-fixed.');
 // Probe decoded FSEQ frames against the bundled mesh, including a backwards
 // seek across the lid handoff. Pixel samples are inside physical optic faces.
 const fascia=await page.evaluate(()=>{
  const p=preview,frameCount=700,frames=new Uint8Array(frameCount*200);
  for(let frame=0;frame<frameCount;frame++){
   const offset=frame*200;
   if(frame===50)frames[offset+40]=63; // Trunk open at one second.
   if(frame<450)for(const channel of [23,27,28])frames[offset+channel-1]=255;
   else frames[offset+(frame<550?24:29)-1]=255;
  }
  const fixture={...show,frames,frameCount,duration:14};
  const lamp=id=>p.rig.lamps.find(l=>l.id===id);
  const pose=t=>{
   p.render(ShowEngine.stateAt(fixture,t),t);
   p.getSnapshot();
   return {lid:p.rig.usesFasciaTails(),logicalTurn:lamp(23).value,
    deck:[23,24,26,27].map(id=>lamp(id).physicalValue),
    lower:['fascia-turn-left','fascia-turn-right','fascia-tail-left','fascia-tail-right',28].map(id=>lamp(id).physicalValue),
    spill:p.tailSpill.map(light=>({onFascia:light.userData.onFascia,intensity:light.intensity})),
    reverse:p.reverseSpill.map(light=>light.position.toArray())};
  };
  const closed=pose(.4),open=pose(7);
  const targets=[lamp('fascia-tail-left'),lamp('fascia-turn-left'),lamp(28)].map(l=>l.objects.filter(o=>o.name.includes('_left_')));
  const vector=()=>p.camera.position.clone();
  const samplePoints=targets.map(meshes=>{
   let area=0,center;
   for(const mesh of meshes){
    const vertices=mesh.geometry.attributes.position;
    for(let i=0;i<vertices.count;i+=3){
     const a=vector().fromBufferAttribute(vertices,i),b=vector().fromBufferAttribute(vertices,i+1),c=vector().fromBufferAttribute(vertices,i+2);
     const faceArea=b.clone().sub(a).cross(c.clone().sub(a)).lengthSq();
     if(faceArea>area){area=faceArea;center=a.add(b).add(c).multiplyScalar(1/3).applyMatrix4(mesh.matrixWorld);}
    }
   }
   return center;
  });
  const cameraPosition=p.camera.position.clone(),cameraRotation=p.camera.quaternion.clone();
  p.camera.position.set(0,.47,3.9);p.camera.lookAt(0,.35,2.28);p.camera.updateMatrixWorld();
  const pixels=()=>{
   p.composer.render();
   const gl=p.renderer.getContext();
   return samplePoints.map(point=>{
    const ndc=point.clone().project(p.camera),pixel=new Uint8Array(4);
    gl.readPixels(Math.floor((ndc.x+1)*gl.drawingBufferWidth/2),Math.floor((ndc.y+1)*gl.drawingBufferHeight/2),1,1,gl.RGBA,gl.UNSIGNED_BYTE,pixel);
    return Array.from(pixel.slice(0,3));
   });
  };
  const illuminated=pixels(),detail=p.canvas.toDataURL('image/png');
  const rightOnly=pose(10),fogOnly=pose(12),unlit=pixels();
  p.camera.position.copy(cameraPosition);p.camera.quaternion.copy(cameraRotation);p.camera.updateMatrixWorld();
  const rewind=pose(.4);
  renderAt(1.5);p.getSnapshot();
  return {closed,open,rightOnly,fogOnly,rewind,illuminated,unlit,detail,samplePoints:samplePoints.map(v=>v.toArray())};
 });
 assert(!fascia.closed.lid&&fascia.open.lid);
 assert.deepStrictEqual(fascia.closed.deck,[1,0,0,1]);assert.deepStrictEqual(fascia.closed.lower,[0,0,0,0,1]);
 assert.equal(fascia.open.logicalTurn,1);assert.deepStrictEqual(fascia.open.deck,[0,0,0,0]);
 assert.deepStrictEqual(fascia.open.lower,[1,0,1,1,1]);assert(fascia.open.spill.every(light=>light.onFascia&&light.intensity>0));
 assert.deepStrictEqual(fascia.rightOnly.lower,[0,1,0,0,0]);assert.deepStrictEqual(fascia.fogOnly.lower,[0,0,0,0,0]);
 assert.deepStrictEqual(fascia.closed.reverse,fascia.open.reverse);assert.deepStrictEqual(fascia.rewind,fascia.closed);
 const [red,amber,white]=fascia.illuminated;
 assert(red[0]>red[1]*2&&red[0]>red[2]*2,'Lower tail must render red: '+red);
 assert(amber[0]>amber[1]&&amber[1]>amber[2]*2&&amber[1]>red[1]+25,'Lower turn must render amber: '+amber);
 assert(Math.min(...white)>130&&Math.max(...white)-Math.min(...white)<45,'Reverse must render white: '+white);
 for(let i=0;i<3;i++)assert(fascia.illuminated[i][0]>fascia.unlit[i][0]+30,'Each fixed optic must actually brighten: '+JSON.stringify(fascia));
 const fasciaDetail=path.join(outDir,'preview-rear-fascia.png');
 fs.writeFileSync(fasciaDetail,Buffer.from(fascia.detail.split(',')[1],'base64'));delete fascia.detail;
 out.screenshots.push(fasciaDetail);out.rearFascia=fascia;out.checks.push('FSEQ frames drive spatially distinct red, amber and white fascia pixels, independent turns, shared tails, bidirectional seeks and no North American fog output.');
 const otherFixtures=await page.evaluate(()=>{
  const rig=preview.rig,frameCount=700,frames=new Uint8Array(frameCount*200);
  for(let frame=0;frame<frameCount;frame++){
   const offset=frame*200;
   if(frame===50){frames[offset+45]=63;frames[offset+36]=63;}
   if(frame>=200&&frame<300)frames[offset+45]=127;
   if(frame===350)frames[offset+45]=191;
   for(let channel=176;channel<=193;channel++)frames[offset+channel-1]=255;
  }
  const fixture={...show,frames,frameCount,duration:14};
  const pose=time=>{preview.render(ShowEngine.stateAt(fixture,time),time);preview.getSnapshot();};
  const world=o=>o.getWorldPosition(o.position.clone()).toArray();
  const lens=rig.parts.charge.children.find(o=>o.userData.sourceMesh===14);
  const vertices=lens.geometry.attributes.position;
  let tip=0;for(let i=1;i<vertices.count;i++)if(vertices.getZ(i)>vertices.getZ(tip))tip=i;
  const coverTip=()=>lens.position.clone().fromBufferAttribute(vertices,tip).applyMatrix4(lens.matrixWorld).toArray();
  const port=()=>({tip:coverTip(),led:world(rig.chargeLED),inlet:world(rig.root.getObjectByName('Charge_inlet')),
   visible:rig.chargeLED.visible,intensity:rig.chargeLED.material.emissiveIntensity,color:rig.chargeLED.material.emissive.getHex()});
  pose(0);const closed=port();pose(3.5);const ready=port();pose(4.2);const first=port();pose(5.2);const second=port();pose(6.5);const stopped=port();
  const windows=['windowFL','windowRL','windowFR','windowRR'].map(key=>rig.parts[key].position.y);
  const interior=Array.from({length:6},(_,i)=>{const lamp=rig.lamps.find(l=>l.id==='rgb-'+i);return {intensity:lamp.object.material.emissiveIntensity,surface:lamp.object.name};});
  pose(10);const shut=port();pose(3.5);const rewind=port();renderAt(1.5);preview.getSnapshot();
  return {closed,ready,first,second,stopped,shut,rewind,windows,interior};
 });
 assert(!otherFixtures.closed.visible&&!otherFixtures.shut.visible&&otherFixtures.ready.visible&&otherFixtures.ready.intensity>0);
 assert(otherFixtures.ready.tip[1]-otherFixtures.closed.tip[1]>.10&&otherFixtures.ready.tip[0]<otherFixtures.closed.tip[0]-.02,'Charge flap must rise and swing clear of the fender');
 assert.deepStrictEqual(otherFixtures.closed.inlet,otherFixtures.ready.inlet);assert.deepStrictEqual(otherFixtures.closed.led,otherFixtures.ready.led);
 assert(Math.abs(otherFixtures.ready.led[2]-otherFixtures.ready.inlet[2])>.07,'Ready indicator must be beside the inlet');
 assert.deepStrictEqual(otherFixtures.first.tip,otherFixtures.ready.tip);assert.deepStrictEqual(otherFixtures.second.tip,otherFixtures.ready.tip);
 assert.notEqual(otherFixtures.first.color,otherFixtures.second.color);assert.equal(otherFixtures.ready.color,0xe6f3ff);assert.equal(otherFixtures.stopped.color,otherFixtures.ready.color);
 assert.deepStrictEqual(otherFixtures.ready,otherFixtures.rewind);assert.deepStrictEqual(otherFixtures.closed,otherFixtures.shut);
 assert(otherFixtures.windows[0]<-.5&&otherFixtures.windows.slice(1).every(position=>position===0),'Window command must move only its own glass');
 assert.deepStrictEqual(otherFixtures.interior.map(l=>l.surface),['mat01_mesh01_component000','mat03_mesh03_component001','mat06_mesh06_component001','mat06_mesh06_component002','mat06_mesh06_component000','mat03_mesh03_component000']);
 assert(otherFixtures.interior[0].intensity>otherFixtures.interior[1].intensity&&otherFixtures.interior.slice(1).every(l=>l.intensity===otherFixtures.interior[1].intensity&&l.intensity>0));
 out.chargeAndCabin=otherFixtures;out.checks.push('Decoded show commands raise the charge cover above the fixed inlet, light the unplugged indicator, animate its Dance colors, and drive four independent windows and six cabin RGB surfaces with a brighter front display.');
 const expected=await page.evaluate(()=>preview.getSnapshot());assert(Math.abs(expected.lamps.find(x=>x.id===3).value-.5)<.011);
 for(const quality of ['high','balanced','battery']){
  await page.evaluate(q=>preview.setQuality(q),quality);await settle(page);const current=await page.evaluate(()=>({snapshot:preview.getSnapshot(),performance:preview.getPerformance(),emitter:preview.rig.lamps.find(x=>x.id===3).object.material.emissiveIntensity,frame:preview.last[0].frame,shadowAuto:preview.renderer.shadowMap.autoUpdate}));assert.deepStrictEqual(current.snapshot,expected);assert.equal(current.emitter,3.5);assert(current.performance.bloomEnabled);assert.equal(current.performance.effectiveQuality,quality);assert.equal(current.shadowAuto,false);out.quality.push(current.performance);
  const path=`${outDir}/preview-${quality}.png`;await page.locator('main').screenshot({path});out.screenshots.push(path);
 }
 assert(out.quality[0].pixelRatio>out.quality[1].pixelRatio&&out.quality[1].pixelRatio>out.quality[2].pixelRatio);assert.deepStrictEqual(out.quality.map(x=>x.shadowSize),[1024,512,256]);out.checks.push('All manual qualities change raster/shadow resolution while preserving exact frames, fades, RGB, closure states, every emitter and estimated-mapping flags.');
 assert(await page.evaluate(()=>{try{preview.setQuality('invalid');return false;}catch(e){return e instanceof RangeError;}}));assert.equal(await page.evaluate(()=>localStorage.getItem('lightforge-preview-quality')),'battery');out.checks.push('Quality preference persists and invalid modes fail explicitly.');
 const frozen=await page.evaluate(()=>preview.renderCount);await page.waitForTimeout(250);assert.equal(await page.evaluate(()=>preview.renderCount),frozen);out.checks.push('Paused, settled preview does not continually redraw.');
 // Projection data is lazy. During playback update neither scans provenance nor allocates snapshots until asked.
 const lazy=await page.evaluate(()=>{let calls=0;const original=preview.updateSnapshot;preview.updateSnapshot=function(...a){calls++;return original.apply(this,a);};for(let i=0;i<40;i++)renderAt(1+i*.02);const before=calls;const snap=preview.getSnapshot(),after=calls;preview.updateSnapshot=original;return {before,after,time:snap.time,frame:snap.frame};});assert.equal(lazy.before,0);assert.equal(lazy.after,1);assert.equal(lazy.frame,89);out.checks.push('Forty sequence updates perform no snapshot projections until requested; the requested snapshot uses the latest exported frame.');
 await settle(page);await page.evaluate(()=>window.scrollTo(0,1200));await page.waitForFunction(()=>!preview.getPerformance().visible);const offscreen=await page.evaluate(()=>preview.renderCount);await page.evaluate(()=>{for(let i=0;i<20;i++)renderAt(2+i*.02);});await page.waitForTimeout(250);assert.equal(await page.evaluate(()=>preview.renderCount),offscreen);await page.evaluate(()=>window.scrollTo(0,0));await page.waitForFunction(()=>preview.renderCount>0&&preview.getPerformance().visible);await settle(page);assert.equal(await page.evaluate(()=>preview.getSnapshot().frame),119);out.checks.push('IntersectionObserver stops all offscreen drawing and resumes at the newest sequence frame.');
 // Actual display:none removes size, also guarded without relying on viewport intersection.
 await page.evaluate(()=>preview.canvas.style.display='none');await page.waitForFunction(()=>!preview.getPerformance().visible);const hidden=await page.evaluate(()=>preview.renderCount);await page.evaluate(()=>renderAt(3));await page.waitForTimeout(150);assert.equal(await page.evaluate(()=>preview.renderCount),hidden);await page.evaluate(()=>preview.canvas.style.display='block');await page.waitForFunction(()=>preview.getPerformance().visible);await settle(page);out.checks.push('Zero-size/hidden canvases do not submit graphics work.');
 // Clock does not change when quality changes or when draw intervals are irregular.
 const rewind=await page.evaluate(()=>{renderAt(1.5);const a=preview.getSnapshot();renderAt(2.7);const b=preview.getSnapshot();preview.setQuality('high');renderAt(1.5);return {a,b,c:preview.getSnapshot()};});assert.deepStrictEqual(rewind.a,rewind.c);assert.notDeepStrictEqual(rewind.a.closures,rewind.b.closures);out.checks.push('Backward seeking restores deterministic geometry, fade/RGB values and frame across quality changes.');
 // Sustained policy test feeds named synthetic timing samples; this is not a device performance benchmark.
 out.adaptationPolicy=await page.evaluate(()=>{const p=preview;p.setQuality('auto');p.applyQuality('high','Policy fixture');p._warmupFrames=0;p._sampleCount=0;p._lastRenderAt=10000;p._lastQualityChange=0;for(let i=1;i<=30;i++)p.recordPerformance(10000+i*90,60);const slow=p.getPerformance();p.applyQuality('balanced','Policy recovery fixture');p._warmupFrames=0;p._sampleCount=0;p._lastRenderAt=30000;p._lastQualityChange=0;for(let i=1;i<=190;i++)p.recordPerformance(30000+i*16,4);const fast=p.getPerformance();p.setQuality('high');p._warmupFrames=0;p._sampleCount=0;p._lastRenderAt=50000;p._lastQualityChange=0;for(let i=1;i<=40;i++)p.recordPerformance(50000+i*100,75);return {slow,fast,manual:p.getPerformance(),synthetic:true};});assert.equal(out.adaptationPolicy.slow.effectiveQuality,'balanced');assert.equal(out.adaptationPolicy.fast.effectiveQuality,'high');assert.equal(out.adaptationPolicy.manual.effectiveQuality,'high');assert(out.adaptationPolicy.slow.bloomEnabled);out.checks.push('Synthetic sustained timing samples verify adaptive downgrade, slower recovery hysteresis, and no override of explicit quality.');
 await page.evaluate(()=>{preview.setQuality('battery');preview._warmupFrames=0;preview._sampleCount=0;preview._lastRenderAt=0;});await settle(page);
 out.measuredVisibleRendering=await page.evaluate(()=>new Promise(resolve=>{let i=0;const intervals=[];let previous=performance.now();function run(now){intervals.push(now-previous);previous=now;renderAt(1.5+(i++)*.02);if(i<18)requestAnimationFrame(run);else requestAnimationFrame(()=>resolve({...preview.getPerformance(),intervals}));}requestAnimationFrame(run);}));assert(out.measuredVisibleRendering.samples>0);out.checks.push('Reports observed continuous rendering intervals and CPU submission time with explicit software-renderer scope.');
 await settle(page);await page.evaluate(()=>{preview.setQuality('high');preview.setView('rear');});await settle(page);await page.locator('main').screenshot({path:outDir+'/preview-rear.png'});out.screenshots.push(outDir+'/preview-rear.png');
 const cargoVisibility=await page.evaluate(()=>{
  const {rig,renderer,scene,camera}=preview;
  const carpet=rig.root.getObjectByName('Static_Cargo_carpet').material;
  const trim=rig.root.getObjectByName('Trunk_lid_trim');
  if(trim.parent!==rig.parts.trunk||rig.root.getObjectByName('Trunk_painted_edge_returns')?.parent!==trim.parent)throw Error('The fitted trim and painted deck edges must move with the trunk');
  const shoulders=rig.root.getObjectByName('Rear_quarter_returns'),hinges=['Trunk_hinge_L','Trunk_hinge_R'].map(name=>rig.root.getObjectByName(name));
  if(shoulders.parent!==rig.root||rig.root.getObjectByName('Rear_body_lamp_recesses').parent!==rig.root)throw Error('The rear quarter returns and lamp pockets must stay on the body');
  const pos=trim.geometry.attributes.position,sample=trim.position.clone();
  for(const hinge of hinges){
   const tip=hinge.geometry.parameters.path.getPoint(1);let nearest=Infinity;
   for(let i=0;i<pos.count;i++)nearest=Math.min(nearest,sample.fromBufferAttribute(pos,i).distanceTo(tip));
   if(hinge.parent!==trim.parent||nearest>.045)throw Error('Hinge must remain connected to the moving trim');
  }
  const gl=renderer.getContext(),testCamera=camera.clone();
  const pixels=()=>{renderer.render(scene,testCamera);const rgba=new Uint8Array(gl.drawingBufferWidth*gl.drawingBufferHeight*4);gl.readPixels(0,0,gl.drawingBufferWidth,gl.drawingBufferHeight,gl.RGBA,gl.UNSIGNED_BYTE,rgba);return rgba;};
  const samples=[];
  const saved=[carpet,trim.material].map(m=>[m.emissive.clone(),m.emissiveIntensity]);
  try{
   for(const view of [[0,1.53,4.15],[1.55,1.70,4.50],[-1.55,1.70,4.50]]){
    testCamera.position.set(...view);testCamera.lookAt(0,1.09,1.85);
    for(const time of [0,7,15]){
     rig.update(ShowEngine.stateAt(show,time));
     // Two colour-ID passes share the same depth buffer rules and geometry.
     // Only pixels actually reaching the viewer change their colour signature.
     carpet.emissiveIntensity=trim.material.emissiveIntensity=3;
     carpet.emissive.setHex(0xff0000);trim.material.emissive.setHex(0x0000ff);
     const before=pixels();
     carpet.emissive.setHex(0x00ff00);trim.material.emissive.setHex(0xff0000);
     const after=pixels();let cargoPixels=0,trimPixels=0;
     for(let i=0;i<after.length;i+=4){
      const dr=after[i]-before[i],dg=after[i+1]-before[i+1],db=after[i+2]-before[i+2];
      if(dr < -60 && dg > 60)cargoPixels++;
      if(dr > 60 && db < -60)trimPixels++;
     }
     samples.push({view:view[0],time,cargoPixels,trimPixels});
    }
   }
  }finally{
   [carpet,trim.material].forEach((m,i)=>{m.emissive.copy(saved[i][0]);m.emissiveIntensity=saved[i][1];});
   rig.update(preview.last[0]);preview.requestDraw();
  }
  return samples;
 });
 for(let i=0;i<cargoVisibility.length;i+=3){
  const [closed,partial,open]=cargoVisibility.slice(i,i+3);
  for(const surface of ['cargoPixels','trimPixels']){
   assert(open[surface]>closed[surface]+150,'Open decklid must expose '+surface+' from view '+open.view);
   assert(partial[surface]>closed[surface]+50,'Intermediate decklid must expose '+surface+' from view '+partial.view);
  }
 }
 out.cargoVisibility=cargoVisibility;out.checks.push('Depth-tested framebuffer shows the cargo compartment and moving lid lining through partial and full opening from three rear views.');
 const previousTime=await page.evaluate(()=>preview.last[1]);await page.evaluate(()=>renderAt(15));await settle(page);
 await page.locator('main').screenshot({path:outDir+'/preview-trunk-open.png'});out.screenshots.push(outDir+'/preview-trunk-open.png');
 await page.evaluate(t=>renderAt(t),previousTime);await settle(page);
 const hue=await page.evaluate(()=>{preview.composer.render();const gl=preview.renderer.getContext(),pixels=new Uint8Array(gl.drawingBufferWidth*gl.drawingBufferHeight*4);gl.readPixels(0,0,gl.drawingBufferWidth,gl.drawingBufferHeight,gl.RGBA,gl.UNSIGNED_BYTE,pixels);let red=0,amber=0;for(let i=0;i<pixels.length;i+=4){const r=pixels[i],g=pixels[i+1],b=pixels[i+2];if(r>100&&r>g*1.8&&r>b*1.8)red++;if(r>100&&g>r*.4&&g<r*.8&&b<r*.3)amber++;}return {redPixels:red,amberPixels:amber};});assert(hue.redPixels>50&&hue.redPixels>hue.amberPixels,'Stop/tail fixture must remain visibly red, not tone-mapped into amber');out.stopLampHue=hue;out.checks.push('Actual output framebuffer preserves red stop/tail optics instead of desaturating them into amber.');await page.evaluate(()=>preview.setView('cabin'));await settle(page);assert.equal(await page.evaluate(()=>preview.getSnapshot().view),'cabin');await page.locator('main').screenshot({path:outDir+'/preview-cabin.png'});out.screenshots.push(outDir+'/preview-cabin.png');out.checks.push('Rear and cabin cutaway cameras remain functional after adaptive quality changes.');
 await page.evaluate(()=>preview.setQuality('battery'));await settle(page);
 const hasExtension=await page.evaluate(()=>{window.loss=preview.renderer.getContext().getExtension('WEBGL_lose_context');if(!loss)return false;loss.loseContext();return true;});assert(hasExtension);await page.waitForFunction(()=>preview.lost);const stopped=await page.evaluate(()=>preview.renderCount);await page.waitForTimeout(100);assert.equal(await page.evaluate(()=>preview.renderCount),stopped);await page.evaluate(()=>loss.restoreContext());await page.waitForFunction(()=>!preview.lost&&preview.canvas.dataset.rendererState==='ready');await page.waitForFunction(n=>preview.renderCount>n,stopped);assert.equal(await page.evaluate(()=>preview.effectiveQuality),'battery');assert(await page.evaluate(()=>preview.bloom.enabled));out.checks.push('Actual graphics-context loss pauses and restores current quality, bloom and drawing.');
 await settle(page);const beforeDispose=await page.evaluate(()=>{const n=preview.renderCount;preview.dispose();preview.requestDraw();return n;});await page.waitForTimeout(100);assert.equal(await page.evaluate(()=>preview.renderCount),beforeDispose);out.checks.push('Disposal disconnects observers and stops scheduling further frames.');
 assert.deepStrictEqual(out.errors,[]);assert.deepStrictEqual(out.externalRequests,[]);out.sourceHashes=hashes();assert.deepStrictEqual(out.sourceHashes,firstHashes,'Preview dependencies changed during verification; rerun final source.');out.passed=true;out.status='passed';out.completedAt=new Date().toISOString();fs.writeFileSync(receiptPath,JSON.stringify(out,null,2));console.log(JSON.stringify(out,null,2));
 }finally{await browser?.close();server.closeAllConnections?.();await new Promise(resolve=>server.close(resolve));}})().catch(e=>{out.passed=false;out.status='failed';out.completedAt=new Date().toISOString();out.failure=String(e.stack||e);fs.writeFileSync(receiptPath,JSON.stringify(out,null,2));console.error(e);process.exitCode=1;});
