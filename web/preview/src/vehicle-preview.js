/* LightForge 1.4 — offline WebGL2 studio. Geometry provenance in MODEL-CREDITS.md.
 * Rendering is observational: only ShowEngine.stateAt() changes vehicle outputs.
 */
import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';

import {EffectComposer} from 'three/addons/postprocessing/EffectComposer.js';
import {RenderPass} from 'three/addons/postprocessing/RenderPass.js';
import {UnrealBloomPass} from 'three/addons/postprocessing/UnrealBloomPass.js';
import {OutputPass} from 'three/addons/postprocessing/OutputPass.js';
import {buildHighlandRig} from './highland-rig.js';
import {loadStudioEnvironment,createStudioEnvironmentTexture} from './studio-environment.js';
const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,Number(v)||0));
const presets={front:[-.70,.24],rear:[Math.PI+.64,.27],driver:[-Math.PI/2,.19],cabin:[-.38,.99]};
const qualityPresets={high:{pixelRatio:1.6,shadowSize:1024,samples:2},balanced:{pixelRatio:1.15,shadowSize:512,samples:0},battery:{pixelRatio:.85,shadowSize:256,samples:0}};
const qualityOrder=['high','balanced','battery'];
const labels={front:'Front · driver side',rear:'Rear · driver side',driver:'Driver side',cabin:'Cabin · roof cutaway',orbit:'Orbit · drag to explore',custom:'Custom view · drag to orbit'};
class VehiclePreview {
 constructor(canvas,onViewChange,{deferLoad=false}={}){
  this.canvas=canvas;this.onViewChange=onViewChange;this.view='front';this.stage='studio';this.yaw=-.70;this.pitch=.24;this.zoom=1;this.last=[null,0];this.snapshot=null;this.loaded=false;this.lost=false;this.animating=false;this._raf=0;this.tween=null;this.renderCount=0;this._snapshotDirty=true;this._intersecting=true;this._hasSize=false;this._disposed=false;this._paused=false;this._restorePending=false;this._loadDeferred=!!deferLoad;this._loadStarted=false;this._readyResolve=null;this._lastRenderAt=0;this._sampleCount=0;this._slowSamples=0;this._fastSamples=0;this._warmupFrames=5;this._renderCpuMs=0;this._frameIntervalMs=0;this._lastQualityChange=0;this.quality='auto';this.effectiveQuality='high';this.adaptationReason='Automatic quality starts at high detail.';
  try{const saved=localStorage.getItem('lightforge-preview-quality');if(saved==='auto'||qualityPresets[saved])this.quality=saved;}catch{}
  this.effectiveQuality=this.quality==='auto'?((navigator.deviceMemory||8)<=4?'balanced':'high'):this.quality;this.adaptationReason=this.quality==='auto'?'Automatic quality starts at '+this.effectiveQuality+' detail.':'Quality selected by you.';
  this._snapshotPosition=new THREE.Vector3();this._snapshotNormal=new THREE.Vector3();this._snapshotDirection=new THREE.Vector3();
  this.reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
  this.status=document.getElementById('previewStatus');this.setStatus('Loading Highland 3D model…','loading');
  try{this.stage=localStorage.getItem('lightforge-stage')==='night'?'night':'studio';}catch{}
  // A pending completed restore must not allocate a WebGL context, render
  // targets, or observers while its saved arrangement is being verified.
  // Keep one readiness promise across deferred startup, failure, and disposal.
  this.ready=new Promise(resolve=>{this._readyResolve=resolve;});
  if(!this._loadDeferred)this.startLoad();
 }
 setStatus(message,state){if(this.status){this.status.hidden=false;this.status.textContent=message;this.status.dataset.state=state;}this.canvas.dataset.rendererState=state;}
 fail(e){this.error=String(e?.message||e);this.setStatus('3D unavailable — update Android System WebView. Your show can still be edited and exported.','error');console.warn('LightForge preview:',this.error);}
 startLoad(){
  if(this._loadStarted||this._disposed)return this.ready;
  this._loadStarted=true;
  const settle=value=>{this._readyResolve?.(value);this._readyResolve=null;};
  try{
   this.init();
   Promise.resolve(this.load()).then(settle,error=>{this.fail(error);settle(false);});
  }catch(error){this.fail(error);settle(false);}
  return this.ready;
 }
 setLoadDeferred(deferred){
  this._loadDeferred=!!deferred;
  if(!this._loadDeferred)this.startLoad();
 }
 init(){
  this.renderer=new THREE.WebGLRenderer({canvas:this.canvas,antialias:true,alpha:false,powerPreference:'high-performance',stencil:false});
  this.renderer.setPixelRatio(Math.min(devicePixelRatio||1,qualityPresets[this.effectiveQuality].pixelRatio));this.renderer.info.autoReset=false;this.renderer.outputColorSpace=THREE.SRGBColorSpace;
  this.renderer.toneMapping=THREE.ACESFilmicToneMapping;this.renderer.toneMappingExposure=1.08;
  this.renderer.shadowMap.enabled=true;this.renderer.shadowMap.autoUpdate=false;this.renderer.shadowMap.needsUpdate=true;this.renderer.shadowMap.type=THREE.PCFSoftShadowMap;
  this.scene=new THREE.Scene();this.scene.background=new THREE.Color('#10171e');this.scene.fog=new THREE.Fog('#10171e',14,36);
  this.camera=new THREE.PerspectiveCamera(32,1,.08,60);this.camera.position.set(-5,2.7,-6);
  this.controls=new OrbitControls(this.camera,this.canvas);this.controls.target.set(0,.72,0);this.controls.enabled=!this._paused;this.controls.enablePan=false;this.controls.enableDamping=true;this.controls.dampingFactor=.11;this.controls.rotateSpeed=.6;this.controls.zoomSpeed=.7;this.controls.minDistance=3.7;this.controls.maxDistance=22;this.controls.minPolarAngle=.14;this.controls.maxPolarAngle=Math.PI/2-.035;
  this.controls.addEventListener('start',()=>{this.tween=null;this.view='custom';this.onViewChange?.(this.view,labels.custom);this.requestDraw();});
  this.controls.addEventListener('change',()=>{if(!this._drawing)this.requestDraw();});this.controls.addEventListener('end',()=>this.requestDraw());
  this.canvas.addEventListener('keydown',e=>{let a=0,b=0;if(e.key==='ArrowLeft')a=-.12;if(e.key==='ArrowRight')a=.12;if(e.key==='ArrowUp')b=.08;if(e.key==='ArrowDown')b=-.08;if(!a&&!b)return;e.preventDefault();this.view='custom';this.tween=null;const s=new THREE.Spherical().setFromVector3(this.camera.position.clone().sub(this.controls.target));s.theta-=a;s.phi=clamp(s.phi-b,.14,Math.PI/2-.035);this.camera.position.copy(new THREE.Vector3().setFromSpherical(s).add(this.controls.target));this.onViewChange?.(this.view,labels.custom);this.requestDraw();});
  // Build the lighting texture with the first visible, loaded model. Rendering
  // the empty stage here competes with model loading and project restoration.
  this.ambient=new THREE.HemisphereLight(0xc4dcf2,0x30323b,.65);this.scene.add(this.ambient);
  this.key=new THREE.DirectionalLight(0xe5f2ff,1.25);this.key.position.set(-3,6,-4);this.key.castShadow=true;this.key.shadow.mapSize.set(qualityPresets[this.effectiveQuality].shadowSize,qualityPresets[this.effectiveQuality].shadowSize);Object.assign(this.key.shadow.camera,{left:-4,right:4,top:4,bottom:-4,near:.1,far:15});this.key.shadow.normalBias=.035;this.key.shadow.bias=-.0004;this.key.shadow.radius=3;this.scene.add(this.key);
  this.rim=new THREE.DirectionalLight(0xb1c8df,.85);this.rim.position.set(4,3,3);this.scene.add(this.rim);
  this.ground=new THREE.Mesh(new THREE.PlaneGeometry(100,100),new THREE.MeshStandardMaterial({color:0x171c23,metalness:0,roughness:1,envMapIntensity:.03}));this.ground.rotation.x=-Math.PI/2;this.ground.position.y=-.018;this.ground.receiveShadow=true;this.scene.add(this.ground);
  // The contact layer supplies soft ambient occlusion beneath the chassis.
  const cv=document.createElement('canvas');cv.width=cv.height=128;const cx=cv.getContext('2d');const gr=cx.createRadialGradient(64,64,8,64,64,64);gr.addColorStop(0,'rgba(0,0,0,.80)');gr.addColorStop(.52,'rgba(0,0,0,.50)');gr.addColorStop(1,'rgba(0,0,0,0)');cx.fillStyle=gr;cx.fillRect(0,0,128,128);
  const shadow=new THREE.Mesh(new THREE.PlaneGeometry(3.1,6.1),new THREE.MeshBasicMaterial({map:new THREE.CanvasTexture(cv),transparent:true,depthWrite:false,opacity:.75}));shadow.rotation.x=-Math.PI/2;shadow.position.y=-.012;this.scene.add(shadow);
  this.headlights=[];for(const side of [-1,1]){const spot=new THREE.SpotLight(0xd5eaff,0,12,.37,.78,1.8);spot.position.set(side*.65,.68,-2.1);spot.target.position.set(side*.7,.03,-6.7);this.scene.add(spot,spot.target);this.headlights.push(spot);}
  this.rearSpill=new THREE.PointLight(0xff1d22,0,3.4,2);this.rearSpill.position.set(0,.23,2.7);this.scene.add(this.rearSpill);
  const target=new THREE.WebGLRenderTarget(1,1,{type:THREE.HalfFloatType});target.samples=qualityPresets[this.effectiveQuality].samples;
  this.composer=new EffectComposer(this.renderer,target);this.composer.addPass(new RenderPass(this.scene,this.camera));
  this.bloom=new UnrealBloomPass(new THREE.Vector2(1,1),.28,.40,2.3);this.composer.addPass(this.bloom);this.composer.addPass(new OutputPass());
  this._resizeObserver=new ResizeObserver(()=>{this.resize();this.requestDraw();});this._resizeObserver.observe(this.canvas);
  if(typeof IntersectionObserver!=='undefined'){this._intersectionObserver=new IntersectionObserver(entries=>{for(const entry of entries)if(entry.target===this.canvas){this._intersecting=entry.isIntersecting&&entry.intersectionRect.width>0&&entry.intersectionRect.height>0;if(this._intersecting){this._lastRenderAt=0;this.requestDraw();}else{cancelAnimationFrame(this._raf);this._raf=0;}this.reportPerformance();}},{threshold:0});this._intersectionObserver.observe(this.canvas);}
  document.querySelectorAll('[data-stage]').forEach(b=>b.addEventListener('click',()=>this.setStage(b.dataset.stage)));
  this._onContextLost=e=>{e.preventDefault();this.lost=true;cancelAnimationFrame(this._raf);this._raf=0;this._lastRenderAt=0;this.setStatus('3D paused — waiting for graphics to recover…','loading');this.reportPerformance();};this.canvas.addEventListener('webglcontextlost',this._onContextLost);
  this._onContextRestored=()=>{this.lost=false;this._restorePending=true;this.requestDraw();this.reportPerformance();};this.canvas.addEventListener('webglcontextrestored',this._onContextRestored);
  this._onVisibility=()=>{this._lastRenderAt=0;if(document.hidden){cancelAnimationFrame(this._raf);this._raf=0;}else{this.resize();this.requestDraw();}this.reportPerformance();};document.addEventListener('visibilitychange',this._onVisibility);
  this.resize();this.reportPerformance();this.positionCamera(this.yaw,this.pitch);this.controls.update();this.setStage(this.stage);
 }
 createEnvironment(){
  // Upload the complete, losslessly baked HDR atlas. Runtime PMREM convolution
  // monopolized Android's graphics queue before the first completed-show frame.
  // Context recovery re-uploads these same lighting values without new passes.
  this.environment?.dispose();this.environment=createStudioEnvironmentTexture(this._environmentData);this.scene.environment=this.environment;this.scene.environmentIntensity=this.stage==='night'?.25:.9;
 }
 async load(){
  try {const [gltf,environmentData]=await Promise.all([new GLTFLoader().loadAsync('preview/models/highland.glb'),loadStudioEnvironment()]);if(this._disposed)return false;this._environmentData=environmentData;this.rig=buildHighlandRig(gltf.scene);this.scene.add(this.rig.root);this.rig.setCutaway(this.view==='cabin');this.renderer.shadowMap.needsUpdate=true;if(this.view!=='custom'){this.positionCamera(this.yaw,this.pitch);this.controls.update();}this.loaded=true;this.setStatus('3D · Highland','ready');this.render(...this.last);this.canvas.dispatchEvent(new CustomEvent('previewready'));return true;}catch(e){this.fail(e);return false;}
 }
 setStage(stage){this.stage=stage==='night'?'night':'studio';this._snapshotDirty=true;const night=this.stage==='night';if(this.scene){
  this.scene.background.set(night?'#050a10':'#10171e');this.scene.fog.color.copy(this.scene.background);this.scene.environmentIntensity=night?.25:.9;this.ambient.intensity=night?.18:.65;this.key.intensity=night?.35:1.25;this.rim.intensity=night?.25:.85;this.ground.material.color.set(night?0x0b1019:0x171c23);this.bloom.strength=night?.42:.28;}
  document.querySelectorAll('[data-stage]').forEach(b=>{b.classList.toggle('selected',b.dataset.stage===this.stage);b.setAttribute('aria-pressed',String(b.dataset.stage===this.stage));});try{localStorage.setItem('lightforge-stage',this.stage);}catch{}this.requestDraw();
 }
 resize(){if(!this.renderer||this._disposed||this._paused||document.hidden)return;const r=this.canvas.getBoundingClientRect();this._hasSize=r.width>=1&&r.height>=1;if(!this._hasSize){cancelAnimationFrame(this._raf);this._raf=0;return;}const w=Math.round(r.width),h=Math.round(r.height);if(w===this.width&&h===this.height)return;this.width=w;this.height=h;this.renderer.setSize(w,h,false);this.composer.setSize(w,h);this.camera.aspect=w/h;this.camera.updateProjectionMatrix();this._snapshotDirty=true;if(this.view!=='custom'){this.positionCamera(this.yaw,this.pitch);this.controls.update();}}
 distance(){
  // Fit the full car and the trunk travel envelope inside the actual viewport.
  // A fixed distance crops a long vehicle on tall phone screens after zoom/reset.
  const aspect=this.width/this.height||1,tan=Math.tan(THREE.MathUtils.degToRad(this.camera.fov/2));
  const sy=Math.sin(this.yaw),cy=Math.cos(this.yaw),sp=Math.sin(this.pitch),cp=Math.cos(this.pitch);
  const outward=new THREE.Vector3(sy*cp,sp,-cy*cp),right=new THREE.Vector3(-cy,0,-sy),up=new THREE.Vector3(-sy*sp,cp,cy*sp);
  const cabin=this.view==='cabin';let points=this.rig?.fitPoints;
  if(cabin||!points){points=[];const bounds=cabin?[[-.87,.34,-1.18],[.87,1.5,1.5]]:[[-1.1,0,-2.39],[1.1,1.9,2.45]];for(const x of [bounds[0][0],bounds[1][0]])for(const y of [bounds[0][1],bounds[1][1]])for(const z of [bounds[0][2],bounds[1][2]])points.push(new THREE.Vector3(x,y,z));}
  let distance=4;for(const v of points){const x=v.x,y=v.y-.72,z=v.z,depth=x*outward.x+y*outward.y+z*outward.z;distance=Math.max(distance,depth+Math.abs(x*right.x+y*right.y+z*right.z)/(tan*aspect*.87),depth+Math.abs(x*up.x+y*up.y+z*up.z)/(tan*.78));}
  return distance/this.zoom;
 }
 positionCamera(yaw,pitch,distance=this.distance()){this.camera.position.set(distance*Math.sin(yaw)*Math.cos(pitch),.72+distance*Math.sin(pitch),-distance*Math.cos(yaw)*Math.cos(pitch));this.camera.lookAt(this.controls.target);}
 setView(view){if(!presets[view]&&view!=='orbit')return;this.view=view;const [yaw,pitch]=presets[view]||[-.7,.28];this.yaw=yaw;this.pitch=pitch;this.zoom=view==='cabin'?1.12:1;this.onViewChange?.(view,labels[view]);if(!this.camera)return;const from=this.camera.position.clone();this.positionCamera(yaw,pitch);const to=this.camera.position.clone();this.camera.position.copy(from);this.tween={from,to,start:performance.now(),duration:this.reducedMotion.matches?0:460};this.rig?.setCutaway(view==='cabin');this.renderer.shadowMap.needsUpdate=true;this._snapshotDirty=true;this.requestDraw();}
 setZoom(z){this._snapshotDirty=true;this.zoom=clamp(z,.8,1.7);if(this.camera){this.positionCamera(this.yaw,this.pitch);this.requestDraw();}}
 render(data,time=0){this.last[0]=data;this.last[1]=time;this._snapshotDirty=true;if(!this.renderer)return;if(this.rig?.update(data))this.renderer.shadowMap.needsUpdate=true;
  if(this.headlights){const l=data?.lights||[];for(let i=0;i<2;i++)this.headlights[i].intensity=8*Math.max(l[i]||0,l[i+2]||0);this.rearSpill.intensity=.35*Math.max(l[24]||0,l[25]||0,l[26]||0);}
  if(this.view==='orbit'&&!this.tween){this.yaw=-.7+time*.12;this.positionCamera(this.yaw,.28);}
  this.canvas.dataset.frame=String(data?.frame??'');this.canvas.dataset.time=Number(data?.time??time).toFixed(4);this.canvas.dataset.view=this.view;this.requestDraw();
 }
 updateSnapshot(){
  if(!this.scene)return;const [data,time]=this.last;this.scene.updateMatrixWorld(true);this.camera.updateMatrixWorld();
  const lamps=(this.rig?.lamps||[]).map(l=>{if(!l.object.geometry.boundingSphere)l.object.geometry.computeBoundingSphere();const pos=this._snapshotPosition.copy(l.object.geometry.boundingSphere.center).applyMatrix4(l.object.matrixWorld);const normal=this._snapshotNormal.copy(l.normal).transformDirection(l.object.matrixWorld);const visible=normal.dot(this._snapshotDirection.copy(this.camera.position).sub(pos))>0;pos.project(this.camera);
   // Geometry provenance is immutable; cache it once instead of rebuilding it on
   // every playback frame. Snapshot projection itself is demand-driven by QA/UI.
   if(!l.snapshotSurfaces)l.snapshotSurfaces=(l.objects||[l.object]).map(o=>Object.freeze({name:o.name,sourceMesh:o.userData.sourceMesh??null,sourceComponent:o.userData.sourceComponent??null,rigPart:o.userData.rigPart||'body'}));
   return {id:l.id,channels:l.channels||[],value:l.value||0,physicalValue:l.physicalValue||0,estimatedMapping:!!l.estimatedMapping,surfaces:l.snapshotSurfaces,visible:visible&&pos.z<1,x:(pos.x+1)*(this.width||0)/2,y:(1-pos.y)*(this.height||0)/2};});
  this.snapshot={time:Number(data?.time??time),frame:data?.frame??null,view:this.view,lamps,closures:(data?.closures||[]).map(x=>({channel:x.channel,position:clamp(x.openFraction??x.estimatedPosition),motion:x.motion,command:x.command,rainbow:x.rainbow})),interior:(data?.interior||[]).map(x=>Array.from(x)),renderer:'WebGL2',modelReady:this.loaded,stage:this.stage};this._snapshotDirty=false;
 }
 isVisible(){return !this._disposed&&!this._paused&&!document.hidden&&!this.lost&&this._intersecting&&this._hasSize;}
 setPaused(paused){paused=!!paused;if(this._disposed||paused===this._paused)return;this._paused=paused;if(this.controls)this.controls.enabled=!paused;this._lastRenderAt=0;if(paused){cancelAnimationFrame(this._raf);this._raf=0;}else{this.resize();this.requestDraw();}this.reportPerformance();}
 setQuality(quality){
  if(quality!=='auto'&&!qualityPresets[quality])throw new RangeError('Preview quality must be auto, high, balanced or battery.');
  this.quality=quality;try{localStorage.setItem('lightforge-preview-quality',quality);}catch{}
  const effective=quality==='auto'?((navigator.deviceMemory||8)<=4?'balanced':'high'):quality;
  this.applyQuality(effective,quality==='auto'?'Automatic quality measures sustained render performance.':'Quality selected by you.',true);return this.getPerformance();
 }
 applyQuality(effective,reason,force=false){
  if(!qualityPresets[effective]||(!force&&effective===this.effectiveQuality))return;
  this.effectiveQuality=effective;this.adaptationReason=reason;this._lastQualityChange=performance.now();this._slowSamples=0;this._fastSamples=0;this._warmupFrames=5;this._lastRenderAt=0;
  if(this.renderer&&this.composer&&!this.lost){const profile=qualityPresets[effective],ratio=Math.min(devicePixelRatio||1,profile.pixelRatio);this.renderer.setPixelRatio(ratio);this.composer.setPixelRatio(ratio);
   // Bloom, material response and every emitter remain enabled at all qualities.
   // Only raster resolution, MSAA and shadow-map resolution change.
   this.composer.renderTarget1.samples=profile.samples;this.composer.renderTarget2.samples=profile.samples;this.composer.renderTarget1.dispose();this.composer.renderTarget2.dispose();
   if(this.key.shadow.mapSize.x!==profile.shadowSize){this.key.shadow.map?.dispose();this.key.shadow.map=null;this.key.shadow.mapSize.set(profile.shadowSize,profile.shadowSize);}this.renderer.shadowMap.needsUpdate=true;
  }
  this.reportPerformance();this.requestDraw();
 }
 getPerformance(){return {quality:this.quality,effectiveQuality:this.effectiveQuality,pixelRatio:this.renderer?.getPixelRatio()||0,shadowSize:qualityPresets[this.effectiveQuality].shadowSize,bloomEnabled:!!this.bloom?.enabled,renderCpuMs:Number(this._renderCpuMs.toFixed(2)),frameIntervalMs:Number(this._frameIntervalMs.toFixed(2)),measurement:'CPU submission and continuous visible render intervals; not GPU or vehicle latency',framesRendered:this.renderCount,samples:this._sampleCount,visible:this.isVisible(),contextLost:this.lost,adaptationReason:this.adaptationReason};}
 reportPerformance(){this.canvas.dataset.quality=this.quality;this.canvas.dataset.effectiveQuality=this.effectiveQuality;this.canvas.dispatchEvent(new CustomEvent('previewperformance',{detail:this.getPerformance()}));}
 recordPerformance(now,cpuMs){
  const interval=this._lastRenderAt?now-this._lastRenderAt:0;this._lastRenderAt=now;
  // Ignore shader warmup and pauses. Changes require a sustained sample window,
  // and recovery requires a longer fast window to prevent quality oscillation.
  if(this._warmupFrames>0){this._warmupFrames--;return;}if(interval<=0||interval>750)return;
  this._sampleCount++;this._renderCpuMs=this._sampleCount===1?cpuMs:this._renderCpuMs*.9+cpuMs*.1;this._frameIntervalMs=this._sampleCount===1?interval:this._frameIntervalMs*.9+interval*.1;
  if(this.quality!=='auto')return;const level=qualityOrder.indexOf(this.effectiveQuality),slow=this._renderCpuMs>(level===0?26:45)||this._frameIntervalMs>(level===0?55:85),fast=this._renderCpuMs<12&&this._frameIntervalMs<24;
  this._slowSamples=slow?this._slowSamples+1:0;this._fastSamples=fast?this._fastSamples+1:0;
  if(level<2&&this._slowSamples>=24&&now-this._lastQualityChange>1500)this.applyQuality(qualityOrder[level+1],'Automatic quality reduced raster detail after sustained slow frames. Lamp brightness, fades and movement timing are unchanged.');
  else if(level>0&&this._fastSamples>=180&&now-this._lastQualityChange>8000)this.applyQuality(qualityOrder[level-1],'Automatic quality increased raster detail after sustained headroom.');
 }
 requestDraw(){if(!this._raf&&this.loaded&&this.isVisible())this._raf=requestAnimationFrame(t=>this.draw(t));}
 draw(now){this._raf=0;if(!this.renderer||!this.loaded||!this.isVisible()||!this.width||!this.height)return;
  this._drawing=true;let animate=false;const start=performance.now();
  try{if(this._restorePending){this._restorePending=false;this.createEnvironment();this.composer.reset();this.applyQuality(this.effectiveQuality,'Graphics recovered; keeping your selected quality.',true);this.renderer.shadowMap.needsUpdate=true;this.resize();this.setStatus('3D · Highland','ready');}
   else if(!this.environment)this.createEnvironment();
   if(this.tween){const u=this.tween.duration?clamp((now-this.tween.start)/this.tween.duration):1;this.camera.position.lerpVectors(this.tween.from,this.tween.to,1-Math.pow(1-u,3));this._snapshotDirty=true;if(u>=1)this.tween=null;else animate=true;}
   if(this.controls.update()){animate=true;this._snapshotDirty=true;}this.renderer.info.reset();this.composer.render();this.renderCount++;
  }finally{this._drawing=false;}
  this.recordPerformance(now,performance.now()-start);if(animate)this.requestDraw();
 }
 redraw(){this.render(...this.last);}
 getSnapshot(){if(this._snapshotDirty)this.updateSnapshot();return this.snapshot;}
 dispose(){if(this._disposed)return;this._disposed=true;this._readyResolve?.(false);this._readyResolve=null;cancelAnimationFrame(this._raf);this._raf=0;this._resizeObserver?.disconnect();this._intersectionObserver?.disconnect();document.removeEventListener('visibilitychange',this._onVisibility);this.canvas.removeEventListener('webglcontextlost',this._onContextLost);this.canvas.removeEventListener('webglcontextrestored',this._onContextRestored);this.controls?.dispose();this.composer?.dispose();this.bloom?.dispose();this.environment?.dispose();const geometries=new Set(),materials=new Set();this.scene?.traverse(o=>{if(o.geometry)geometries.add(o.geometry);if(o.material)for(const m of Array.isArray(o.material)?o.material:[o.material])materials.add(m);});for(const g of geometries)g.dispose();for(const m of materials)m.dispose();this.renderer?.dispose();}
}
window.VehiclePreview=VehiclePreview;
