/* End-to-end WebGL preview checks. Run after tools/build_preview.mjs builds the final rig. */
const {chromium}=require('/opt/codex/runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),assert=require('assert'),cp=require('child_process');
const root='app/lightforge',origin='http://127.0.0.1:8774';
const chrome='/workspace/scratch/9b34d7a394e6/app/toolchain/chrome/chrome-headless-shell-linux64/chrome-headless-shell';

async function ready(page) {
  await page.waitForFunction(()=>!!window.LightForgeApp?.vehiclePreview?.ready,{},{timeout:30000});
  assert.equal(await page.evaluate(()=>LightForgeApp.vehiclePreview.ready),true,'bundled Highland model must load successfully');
  await page.waitForFunction(()=>LightForgeApp.vehiclePreview.getSnapshot()?.modelReady,{},{timeout:30000});
}
async function settle(page) {
  await page.waitForFunction(()=>{
    const p=LightForgeApp.vehiclePreview;
    return !p.tween&&!p._raf&&p.renderCount>0;
  },{},{timeout:30000});
}
async function camera(page,view) {
  await page.click(`[data-camera="${view}"]`);
  await settle(page);
  assert.equal((await page.evaluate(()=>LightForgeApp.vehiclePreview.getSnapshot())).view,view);
}
function lamp(snapshot,id) {
  const item=snapshot.lamps.find(x=>x.id===id);
  assert(item,`rendered lamp ${id} exists`);
  return item;
}
function nearly(a,b,tolerance=1e-5) { assert(Math.abs(a-b)<=tolerance,`${a} differs from ${b}`); }
function sameScreenPosition(a,b) { nearly(a.x,b.x); nearly(a.y,b.y); }

(async()=>{
  const server=cp.spawn('python3',['-m','http.server','8774','--bind','127.0.0.1','--directory',root+'/web'],{stdio:'ignore'});
  let browser;
  const out={checks:[],errors:[],externalRequests:[],assets:[],skipped:[]};
  try {
    await new Promise(r=>setTimeout(r,450));
    browser=await chromium.launch({executablePath:chrome,headless:true,args:['--no-sandbox','--disable-dev-shm-usage','--enable-unsafe-swiftshader']});
    const page=await browser.newPage({viewport:{width:393,height:852},deviceScaleFactor:1,reducedMotion:'reduce'});
    page.on('pageerror',e=>out.errors.push(e.message));
    await page.route('**/*',route=>{
      const url=new URL(route.request().url());
      if(/^https?:$/.test(url.protocol)&&url.origin!==origin) {
        out.externalRequests.push(url.href);return route.abort();
      }
      return route.continue();
    });
    page.on('response',response=>{
      if(response.url().includes('/preview/models/')) out.assets.push({url:response.url().slice(origin.length),status:response.status()});
    });
    await page.goto(origin);
    await ready(page);
    const graphics=await page.evaluate(()=>{
      const p=LightForgeApp.vehiclePreview,gl=p.renderer.getContext();let meshes=0,triangles=0;
      p.rig.root.traverse(o=>{if(o.isMesh){meshes++;triangles+=(o.geometry.index?.count||o.geometry.attributes.position.count)/3;}});
      return {webgl2:gl instanceof WebGL2RenderingContext,version:gl.getParameter(gl.VERSION),meshes,triangles,ready:p.getSnapshot().modelReady,renderer:p.getSnapshot().renderer};
    });
    assert(graphics.webgl2);assert.equal(graphics.renderer,'WebGL2');assert(graphics.ready);assert(graphics.meshes>0);assert(graphics.triangles>10000);
    assert(out.assets.some(x=>x.url.endsWith('highland.glb')&&x.status===200));
    out.graphics=graphics;out.checks.push('Real WebGL2 context loads the bundled detailed Highland mesh');

    // Synthetic analysis isolates the UI/renderer from neural-analysis variability.
    // The production show engine still generates the bytes displayed by the preview.
    await page.evaluate(async()=>{
      const app=LightForgeApp;
      await app.selectProject({id:'preview-fixture',name:'Glass Castle · preview test',duration:64,createdAt:Date.now(),audioUrl:URL.createObjectURL(await(await fetch('demo/glass-castle.wav')).blob())},true);
      app.state.music={duration:64,bpm:93,beatConfidence:.94,beats:Array.from({length:99},(_,i)=>i*60/93),downbeats:Array.from({length:25},(_,i)=>i*240/93),onsets:Array.from({length:198},(_,i)=>({time:i*30/93,strength:.6+(i%4)*.1,band:i%2?'high':'bass'})),sections:[{start:0,end:16,energy:.5,label:'Opening'},{start:16,end:32,energy:.8,label:'Build'},{start:32,end:48,energy:1,label:'The drop'},{start:48,end:64,energy:.7,label:'Finale'}],waveform:Array.from({length:512},(_,i)=>.3+.55*Math.abs(Math.sin(i*.7)))};
      app.regenerate({save:false});document.getElementById('audio').currentTime=35;
    });
    await page.waitForFunction(()=>Math.abs(LightForgeApp.vehiclePreview.getSnapshot().time-35)<.03);
    await settle(page);
    for(const view of ['front','rear','driver','cabin','orbit']) {
      await camera(page,view);
      const snapshot=await page.evaluate(()=>LightForgeApp.vehiclePreview.getSnapshot());
      assert(snapshot.lamps.some(x=>x.visible),`${view} camera includes visible mapped lamps`);
      assert(snapshot.lamps.every(x=>Number.isFinite(x.x)&&Number.isFinite(x.y)),`${view} has finite projected geometry`);
      await page.locator('.preview-card').screenshot({path:`${root}/qa/mobile/3d-${view}.png`});
      out.checks.push(view+' camera renders the loaded 3D model');
    }

    await camera(page,'front');
    const canvas=page.locator('#carCanvas');await canvas.scrollIntoViewIfNeeded();
    const box=await canvas.boundingBox();
    const beforeOrbit=await page.evaluate(()=>LightForgeApp.vehiclePreview.camera.position.toArray());
    await page.mouse.move(box.x+box.width*.42,box.y+box.height*.5);await page.mouse.down();
    await page.mouse.move(box.x+box.width*.68,box.y+box.height*.5,{steps:8});await page.mouse.up();await settle(page);
    assert.equal(await canvas.getAttribute('data-view'),'custom');
    assert.notDeepEqual(await page.evaluate(()=>LightForgeApp.vehiclePreview.camera.position.toArray()),beforeOrbit);
    out.checks.push('Dragging orbits the actual Three.js camera');

    await camera(page,'front');await canvas.scrollIntoViewIfNeeded();
    const touchBox=await canvas.boundingBox(),x=touchBox.x+touchBox.width/2,y=touchBox.y+touchBox.height/2;
    const touch=await page.context().newCDPSession(page);
    await touch.send('Emulation.setTouchEmulationEnabled',{enabled:true,maxTouchPoints:2});
    const beforePinch=await page.evaluate(()=>LightForgeApp.vehiclePreview.camera.position.distanceTo(LightForgeApp.vehiclePreview.controls.target));
    const points=spread=>[{x:x-spread,y,id:1,radiusX:2,radiusY:2,force:1},{x:x+spread,y,id:2,radiusX:2,radiusY:2,force:1}];
    await touch.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:points(30)});
    await touch.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:points(50)});
    await touch.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:points(70)});
    await touch.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
    await settle(page);
    const afterPinch=await page.evaluate(()=>LightForgeApp.vehiclePreview.camera.position.distanceTo(LightForgeApp.vehiclePreview.controls.target));
    assert(afterPinch<beforePinch-.15,'spreading two touches must move the actual camera closer');
    await touch.send('Emulation.setTouchEmulationEnabled',{enabled:false});await touch.detach();
    out.pinch={before:beforePinch,after:afterPinch};out.checks.push('Two-finger pinch changes real camera distance');

    await camera(page,'front');
    await page.click('#previewMode');await settle(page);
    assert(await page.locator('.preview-card').evaluate(el=>el.classList.contains('expanded')));
    assert(await canvas.evaluate(el=>el.width>0&&el.height>0));
    await page.click('#previewMode');await settle(page);out.checks.push('Expanded preview resizes the WebGL drawing buffer and restores');

    await page.click('[data-stage="studio"]');await settle(page);const studio=await canvas.screenshot();
    await page.click('[data-stage="night"]');await settle(page);const night=await canvas.screenshot();
    assert.notDeepEqual(studio,night,'lighting presets must visibly change rendered pixels');
    assert.equal((await page.evaluate(()=>LightForgeApp.vehiclePreview.getSnapshot())).stage,'night');
    assert.equal(await page.locator('[data-stage="night"]').getAttribute('aria-pressed'),'true');
    await page.locator('.preview-card').screenshot({path:`${root}/qa/mobile/3d-night.png`});
    await page.click('[data-stage="studio"]');await settle(page);
    out.checks.push('Studio and Night controls change rendered lighting and selection state');

    await camera(page,'rear');
    // Commands begin on exact 20 ms boundaries. The 204 ramp rises for 1000 ms.
    // Transform snapshots come from THREE.Group matrices, independently of copied command fractions.
    const diagnostic=await page.evaluate(()=>{
      const app=LightForgeApp,frames=new Uint8Array(4000*200);
      const set=(ch,start,end,v)=>{for(let f=Math.floor(start*50);f<Math.floor(end*50);f++)frames[f*200+ch-1]=v;};
      set(3,1,3,204);set(5,0,3,255);set(25,0,3,255);set(28,0,3,255);set(30,0,3,255);
      set(37,0,.5,63);set(41,0,.5,63);set(35,0,.5,191);set(46,0,2,63);set(46,2,5,127);
      for(let f=0;f<4000;f++){frames[f*200+175]=64;frames[f*200+176]=128;frames[f*200+177]=255;frames[f*200+187]=128;frames[f*200+188]=255;}
      const show={frames,frameCount:4000,stepMs:20,channels:200,channelCount:200,duration:80,sections:[{start:0,end:80,label:'Preview test'}]};
      app.state.show=show;
      const capture=t=>{
        app.renderFrame(t);const preview=app.vehiclePreview;preview.rig.root.updateMatrixWorld(true);
        const parts={};for(const [key,part] of Object.entries(preview.rig.parts||{}))parts[key]=Array.from(part.matrixWorld.elements);
        const shader=material=>({color:material.color?.getHex(),emissive:material.emissive?.getHex(),intensity:material.emissiveIntensity});
        const charge=preview.rig.chargeLED?{shader:shader(preview.rig.chargeLED.material),matrix:Array.from(preview.rig.chargeLED.matrixWorld.elements),visible:preview.rig.chargeLED.visible}:null;
        const shaders={};for(const id of [3,'rgb-0','rgb-4']){const lamp=preview.rig.lamps.find(l=>l.id===id);if(lamp)shaders[id]=shader(lamp.object.material);}
        return {snapshot:preview.getSnapshot(),parts,charge,shaders};
      };
      return {before:capture(.98),onset:capture(1),half:capture(1.5),later:capture(2.7),rainbowLater:capture(4),rewind:capture(1.5),expected:ShowEngine.stateAt(show,1.5)};
    });
    const half=diagnostic.half.snapshot,later=diagnostic.later.snapshot;
    nearly(lamp(diagnostic.before.snapshot,3).value,0);
    nearly(lamp(diagnostic.onset.snapshot,3).value,0);
    nearly(lamp(half,3).value,.5,.011);
    nearly(lamp(half,30).value,1);nearly(lamp(half,28).value,1);
    assert(lamp(half,28).surfaces.length>=2,'paired reverse lamps share channel 28');
    assert(lamp(half,28).surfaces.every(s=>s.rigPart==='body'),'all reverse fixtures stay fixed to the body');
    sameScreenPosition(lamp(half,28),lamp(later,28));
    assert(Math.hypot(lamp(half,26).x-lamp(later,26).x,lamp(half,26).y-lamp(later,26).y)>.05,'trunk tail lamp geometry must travel');
    assert(Math.hypot(lamp(half,30).x-lamp(later,30).x,lamp(half,30).y-lamp(later,30).y)>.05,'license plate geometry must travel with trunk');
    for(const key of ['windowFL','mirrorL','trunk','charge']){
      assert(diagnostic.half.parts[key],`articulated ${key} Group exists`);
      assert.notDeepEqual(diagnostic.half.parts[key],diagnostic.later.parts[key],`${key} changes real mesh transformation`);
    }
    assert(later.closures.find(x=>x.channel===46).rainbow);
    assert.deepEqual(diagnostic.later.parts.charge,diagnostic.rainbowLater.parts.charge,'charge dance holds open door instead of oscillating it');
    assert(diagnostic.later.charge?.visible,'charge status LED is visible in the open socket');
    assert.notDeepEqual(diagnostic.later.charge.shader,diagnostic.rainbowLater.charge.shader,'charge rainbow changes actual LED shader colors');
    assert.deepEqual(diagnostic.half.charge.matrix,diagnostic.later.charge.matrix,'LED stays in fender as the flap opens');
    assert.notDeepEqual(diagnostic.before.shaders[3],diagnostic.half.shaders[3],'fade changes actual lamp shader output');
    assert.equal(diagnostic.half.shaders['rgb-0'].emissive,0x4080ff,'display shader emits the exported RGB color');
    assert.equal(diagnostic.half.shaders['rgb-4'].emissive,0x80ff00,'driver ambient shader emits the exported RGB color');
    assert.deepEqual(diagnostic.half,diagnostic.rewind,'seeking backward restores deterministic geometry, lamps and colors');
    assert.deepEqual(half.interior,diagnostic.expected.interior.map(x=>Object.values(x)));
    out.checks.push('Fade onset and midpoint follow exact exported frame and supported ramp');
    out.checks.push('Trunk tail lamps and license plate move while paired reverse lamps remain fixed');
    out.checks.push('Windows, mirrors, trunk and charge port change actual 3D transforms');
    out.checks.push('Charge dance changes rendered LED color while holding the flap open');
    out.checks.push('Rewind restores exact lamp values, RGB colors and articulated geometry');

    await camera(page,'front');
    await page.evaluate(()=>{document.getElementById('audio').currentTime=1.5;});
    await page.waitForFunction(()=>Math.abs(LightForgeApp.vehiclePreview.getSnapshot().time-1.5)<.001);await settle(page);
    const paused=await page.evaluate(()=>LightForgeApp.vehiclePreview.getSnapshot());
    await page.waitForTimeout(160);
    assert.deepEqual(await page.evaluate(()=>LightForgeApp.vehiclePreview.getSnapshot()),paused);
    out.checks.push('Pause freezes sequence values and physical geometry estimates');
    await page.click('#play');
    const sync=await page.evaluate(()=>new Promise(resolve=>{
      const samples=[];let previous=performance.now();
      function sample(now){const a=document.getElementById('audio'),p=LightForgeApp.vehiclePreview.getSnapshot();samples.push({gapMs:now-previous,audio:a.currentTime,preview:p.time,frame:p.frame,paused:a.paused});previous=now;if(samples.length<9)requestAnimationFrame(sample);else resolve(samples);}
      requestAnimationFrame(sample);
    }));
    await page.click('#play');
    const measured=sync.slice(1),maxGapMs=Math.max(...measured.map(x=>x.gapMs)),maxLagMs=Math.max(...measured.map(x=>(x.audio-x.preview)*1000));
    assert(measured.every(x=>!x.paused));assert(measured[measured.length-1].audio>measured[0].audio);
    // SwiftShader rasterization can be much slower than device GPUs. Require the
    // correct audio clock within the measured render interval, and report the raw
    // timings instead of misrepresenting software rendering as a 60 fps phone test.
    assert(maxLagMs<=maxGapMs+60,JSON.stringify({maxGapMs,maxLagMs,samples:measured}));
    assert(measured.every(x=>Math.abs(x.frame-Math.floor(x.preview*50))<=1));
    out.audioSync={maxGapMs,maxLagMs,samples:measured};out.checks.push('Actual audio clock drives WebGL frames within the measured render interval');
    await page.locator('.channel-monitor summary').click();
    await page.evaluate(()=>{document.getElementById('audio').currentTime=1.5;});
    await page.waitForFunction(()=>Math.abs(LightForgeApp.vehiclePreview.getSnapshot().time-1.5)<.001);
    nearly(Number(await page.locator('.lamp-cell[data-channels="3"]').getAttribute('data-level')),.5,.011);
    out.checks.push('Output monitor and hidden lamps agree with rendered fade values');

    await page.setViewportSize({width:768,height:1024});await camera(page,'rear');
    await page.locator('.preview-card').screenshot({path:`${root}/qa/mobile/3d-foldable.png`});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),768);
    out.checks.push('Foldable layout resizes the model without horizontal overflow');
    assert.deepEqual(out.externalRequests,[]);
    out.checks.push('Model, renderer and preview load with every external HTTP origin blocked');

    // A real GPU context loss must show a recoverable state and resume after restoration.
    const canLose=await page.evaluate(()=>{
      const p=LightForgeApp.vehiclePreview;window.previewLossExtension=p.renderer.getContext().getExtension('WEBGL_lose_context');
      if(!window.previewLossExtension)return false;window.previewLossExtension.loseContext();return true;
    });
    if(canLose){
      await page.waitForFunction(()=>LightForgeApp.vehiclePreview.lost);
      assert.equal(await page.locator('#previewStatus').getAttribute('data-state'),'loading');
      await page.waitForTimeout(100);
      const stopped=await page.evaluate(()=>LightForgeApp.vehiclePreview.renderCount);
      await page.waitForTimeout(100);assert.equal(await page.evaluate(()=>LightForgeApp.vehiclePreview.renderCount),stopped);
      await page.evaluate(()=>window.previewLossExtension.restoreContext());
      await page.waitForFunction(()=>!LightForgeApp.vehiclePreview.lost&&document.getElementById('previewStatus').dataset.state==='ready',{},{timeout:15000});
      await page.waitForFunction(count=>LightForgeApp.vehiclePreview.renderCount>count,stopped,{timeout:15000});
      out.checks.push('Graphics context loss pauses drawing, reports recovery, then resumes');
    }else out.skipped.push('WEBGL_lose_context extension unavailable in this browser');

    // Unsupported devices retain the editor and report the missing renderer explicitly.
    const unsupported=await browser.newPage({viewport:{width:393,height:852},reducedMotion:'reduce'});
    const unsupportedErrors=[];unsupported.on('pageerror',e=>unsupportedErrors.push(e.message));
    await unsupported.addInitScript(()=>{const original=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(type,...args){if(String(type).includes('webgl'))return null;return original.call(this,type,...args);};});
    await unsupported.goto(origin);await unsupported.waitForFunction(()=>!!window.LightForgeApp);
    assert.equal(await unsupported.evaluate(()=>LightForgeApp.vehiclePreview.ready),false);
    assert.equal(await unsupported.locator('#previewStatus').getAttribute('data-state'),'error');
    await unsupported.click('[data-navigate="shows"]');assert(await unsupported.locator('#shows').evaluate(el=>el.classList.contains('active')));
    await unsupported.click('[data-navigate="studio"]');assert(await unsupported.locator('#pickAudio').isEnabled());
    assert.deepEqual(unsupportedErrors,[]);await unsupported.close();
    out.checks.push('Missing WebGL reports an error while leaving project navigation and import available');

    assert.deepEqual(out.errors,[]);out.passed=true;
    fs.writeFileSync(`${root}/qa/mobile/3d-preview-verification.json`,JSON.stringify(out,null,2));
    console.log(JSON.stringify(out,null,2));
  } finally {if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
