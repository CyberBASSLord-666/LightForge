'use strict';
// Actual WebGL comparison of the complete vehicle using live and baked PMREM.
// This establishes texture/render equivalence, not Android lifecycle approval.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'../..'),out=path.resolve(process.env.LIGHTFORGE_ENVIRONMENT_QA_OUTPUT||path.join(root,'qa/restore-preview/environment-result'));
const graphics=process.env.LF_GRAPHICS_NODE_MODULES||path.resolve(root,'../toolchain/graphics/node_modules');
const {chromium}=require('playwright'),esbuild=require(path.join(graphics,'esbuild'));
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const bundle=await esbuild.build({stdin:{contents:`import * as THREE from 'three';import {createStudioEnvironmentScene} from './web/preview/src/studio-environment-source.js';
 window.liveStudio=renderer=>{const scene=createStudioEnvironmentScene(THREE),generator=new THREE.PMREMGenerator(renderer),target=generator.fromScene(scene,.055);generator.dispose();scene.traverse(o=>{o.geometry?.dispose();o.material?.dispose();});return target;};`,resolveDir:root,loader:'js'},write:false,bundle:true,format:'iife',nodePaths:[graphics]});
 const html='<html><head><style>body{margin:0;background:#10171e}canvas{display:block;width:393px;height:330px}</style></head><body><canvas id="car"></canvas><script src="/preview/vehicle-preview.js"></script></body></html>';
 const server=http.createServer((req,res)=>{const url=new URL(req.url,'http://local').pathname;if(url==='/'){res.setHeader('Content-Type','text/html');res.end(html);return;}const file=path.resolve(root,'web','.'+url);if(!file.startsWith(path.join(root,'web')+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404).end();return;}res.setHeader('Content-Type',url.endsWith('.js')?'text/javascript':'application/octet-stream');fs.createReadStream(file).pipe(res);});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));let browser;
 try{
  browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_EXECUTABLE_PATH?{executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH}:{}),args:['--no-sandbox','--enable-unsafe-swiftshader','--use-gl=angle','--use-angle=swiftshader']});
  const page=await browser.newPage({viewport:{width:393,height:330},reducedMotion:'reduce'}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));await page.goto('http://127.0.0.1:'+server.address().port);await page.addScriptTag({content:bundle.outputFiles[0].text});
  const {cases,startup}=await page.evaluate(async()=>{
   window.startupMarkers=[];window.LightForgeDiagnostics={log:(level,source,message)=>startupMarkers.push({level,source,message})};
   const preview=window.preview=new VehiclePreview(document.getElementById('car'));if(await preview.ready!==true)throw Error(preview.error||'Preview failed');
   await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
   if(preview.renderCount<1)throw Error('Baked preview did not submit an initial full frame');
   const baked=preview.environment,liveTarget=liveStudio(preview.renderer),cases=[];
   const digest=async bytes=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(x=>x.toString(16).padStart(2,'0')).join('');
   const draw=()=>{preview.renderer.shadowMap.needsUpdate=true;preview.draw(performance.now());const gl=preview.renderer.getContext(),pixels=new Uint8Array(gl.drawingBufferWidth*gl.drawingBufferHeight*4);gl.readPixels(0,0,gl.drawingBufferWidth,gl.drawingBufferHeight,gl.RGBA,gl.UNSIGNED_BYTE,pixels);return pixels;};
   const lights=Array(200).fill(0);for(const c of [0,2,5,7,20,24,26,29])lights[c]=.82;
   preview.render({frame:27,time:.54,lights,closures:[],interior:[]},.54);
   for(const [stage,view,quality] of [['studio','front','high'],['night','rear','high'],['studio','cabin','balanced'],['night','driver','battery']]){
    preview.setStage(stage);preview.setView(view);preview.tween=null;preview.positionCamera(preview.yaw,preview.pitch);preview.controls.update();preview.setQuality(quality);
    preview.environment=baked;preview.scene.environment=baked;const a=draw();
    preview.environment=liveTarget.texture;preview.scene.environment=liveTarget.texture;const b=draw();
    let different=0,maxDifference=0;for(let i=0;i<a.length;i++){if(a[i]!==b[i])different++;maxDifference=Math.max(maxDifference,Math.abs(a[i]-b[i]));}
    const distinct=new Set();for(let i=0;i<a.length;i+=4)distinct.add(a[i]+','+a[i+1]+','+a[i+2]);
    cases.push({stage,view,quality,pixel_bytes:a.length,baked_sha256:await digest(a),live_sha256:await digest(b),different_components:different,max_component_difference:maxDifference,distinct_colors:distinct.size});
   }
   preview.environment=baked;preview.scene.environment=baked;liveTarget.dispose();preview.redraw();return {cases,startup:startupMarkers};
  });
  const recoveryBefore=await page.evaluate(()=>{window.recoveryAtlas=preview._environmentData;window.recoveryFrames=preview.renderCount;window.contextLoss=preview.renderer.getContext().getExtension('WEBGL_lose_context');if(!contextLoss)throw Error('Context-loss extension unavailable');contextLoss.loseContext();return recoveryFrames;});
  await page.waitForFunction(()=>preview.lost===true);
  assert.equal(await page.evaluate(()=>preview.renderCount),recoveryBefore,'Lost context must not report a rendered frame');
  await page.evaluate(()=>contextLoss.restoreContext());
  await page.waitForFunction(()=>!preview.lost&&preview.renderCount>recoveryFrames);
  const recovery=await page.evaluate(()=>({atlasRetained:preview._environmentData===recoveryAtlas,uploadedSameValues:preview.environment.image.data===recoveryAtlas,loaded:preview.loaded,firstFrameAfterRecovery:preview.renderCount>recoveryFrames}));
  assert.deepEqual(recovery,{atlasRetained:true,uploadedSameValues:true,loaded:true,firstFrameAfterRecovery:true});
  assert.equal(startup.length,6,'Actual preview startup must emit exactly six bounded markers');
  const phases=startup.map(event=>event.message.match(/^preview-startup phase=([a-z-]+) elapsedMs=\d+\.\d{2}(?: durationMs=\d+\.\d{2})?$/)?.[1]);
  assert.deepEqual([...phases].sort(),['graphics-initialized','gltf-loaded','atlas-loaded','rig-built','first-composer-start','first-composer-end'].sort());
  assert.equal(await page.evaluate(()=>startupMarkers.length),6,'Context recovery and later frames must not repeat startup markers');
  await page.screenshot({path:path.join(out,'full-vehicle.png')});
  assert.deepEqual(errors,[]);for(const c of cases){assert.ok(c.distinct_colors>100,'Comparison must render a detailed vehicle');assert.equal(c.different_components,0,JSON.stringify(c));assert.equal(c.baked_sha256,c.live_sha256);}
  const receipt={passed:true,scope:'Desktop Chromium WebGL2, complete vehicle with unchanged shadow/bloom/output passes; pixel-identical lighting comparison, real context loss/recovery and bounded startup diagnostics, not Android approval.',browser:browser.version(),cases,recovery,startup,source_hashes:Object.fromEntries(['web/preview/src/studio-environment-source.js','web/preview/src/studio-environment.js','web/preview/src/vehicle-preview.js','web/preview/vehicle-preview.js','web/preview/models/highland.glb','web/preview/models/studio-environment.rgba16f.gz','qa/restore-preview/environment.cjs'].map(name=>[name,hash(fs.readFileSync(path.join(root,name)))]))};
  fs.writeFileSync(path.join(out,'verification.json'),JSON.stringify(receipt,null,2)+'\n');console.log(JSON.stringify(receipt,null,2));
 }finally{await browser?.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;});
