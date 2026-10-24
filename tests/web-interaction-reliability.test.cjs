'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const {JSDOM} = require('jsdom');
const root = path.resolve(__dirname, '..');
function compilerHarness() {
 const workers=[];
 class Worker { constructor(){ workers.push(this); } postMessage(){} terminate(){this.terminated=true;} emit(data){this.onmessage({data});} }
 const context={URL, Worker, DOMException, document:{currentScript:{src:'https://app.test/engine/client.js'}}, LightForgeVersion:{name:'test'}};
 context.window=context; vm.runInNewContext(fs.readFileSync(path.join(root,'web/engine/client.js'),'utf8'),context);
 return {compiler:context.ShowCompiler,workers};
}
test('composition rejects malformed worker messages and releases each worker',async()=>{
 for(const message of [null,undefined,'result',{}, {type:'surprise'}]) {
  const t=compilerHarness(), promise=t.compiler.generate({},{}), rejected=assert.rejects(promise,/invalid|unexpected/);
  t.workers[0].emit(message); await rejected; assert.equal(t.workers[0].terminated,true);
 }
});
test('composition progress callback failures reject instead of hanging',async()=>{
 const t=compilerHarness(), error=new Error('UI callback failed'), promise=t.compiler.generate({}, {},()=>{throw error;}), rejected=assert.rejects(promise,e=>e===error);
 t.workers[0].emit({type:'progress',value:{progress:.5}});await rejected;assert.equal(t.workers[0].terminated,true);
 t.workers[0].emit({type:'result',value:'late'});
});
test('composition ignores worker ready and settles once on result or abort',async()=>{
 const t=compilerHarness(), controller=new AbortController();
 const promise=t.compiler.generate({}, {},undefined,controller.signal), rejected=assert.rejects(promise,{name:'AbortError'});
 t.workers[0].emit({type:'ready'});assert.notEqual(t.workers[0].terminated,true);controller.abort();await rejected;
 t.workers[0].emit({type:'result',value:'late'});
 const next=t.compiler.generate({},{});t.workers[1].emit({type:'result',value:'done'});assert.equal(await next,'done');
});
function uiHarness(){
 const dom=new JSDOM('<button id="trigger">Open</button><aside id="already" inert></aside><audio id="audio"></audio><input id="seek"><div class="modal-backdrop" id="first" hidden><section role="dialog"><button id="firstButton">One</button><textarea id="notes"></textarea><button id="lastButton">Last</button></section></div><div class="modal-backdrop" id="second" hidden><section role="dialog"><button id="secondButton">Two</button></section></div>', {url:'https://app.test',runScripts:'outside-only'});
 const w=dom.window,d=w.document,frames=[];
 w.matchMedia=()=>({matches:true});w.requestAnimationFrame=fn=>{frames.push(fn);return frames.length;};
 // Layout is deliberately simulated: DOM behavior only, not rendered-browser QA.
 w.HTMLElement.prototype.getClientRects=function(){return this.closest('[hidden]')?[]:[{}];};
 w.eval(fs.readFileSync(path.join(root,'web/ui-polish.js'),'utf8'));
 return {w,d,async close(){await Promise.resolve();await Promise.resolve();w.close();},async flush(){await Promise.resolve();frames.splice(0).forEach(fn=>fn());}};
}
test('modal isolation restores existing inert state and opener across overlapping overlays',async()=>{
 const t=uiHarness(),{d}=t;try {
  d.getElementById('trigger').focus();d.getElementById('first').hidden=false;await t.flush();
  assert.equal(d.activeElement.id,'firstButton');assert.equal(d.getElementById('trigger').hasAttribute('inert'),true);
  d.getElementById('second').hidden=false;await t.flush();assert.equal(d.activeElement.id,'secondButton');assert.equal(d.getElementById('first').hasAttribute('inert'),true);
  d.getElementById('second').hidden=true;await t.flush();assert.equal(d.activeElement.id,'firstButton');assert.equal(d.getElementById('first').hasAttribute('inert'),false);
  d.getElementById('first').hidden=true;await t.flush();assert.equal(d.activeElement.id,'trigger');assert.equal(d.getElementById('trigger').hasAttribute('inert'),false);assert.equal(d.getElementById('already').hasAttribute('inert'),true);
 }finally{await t.close();}
});
test('modal tab wrap includes textareas and skips hidden or negative-tabindex controls',async()=>{
 const t=uiHarness(),{d,w}=t;try {
  d.getElementById('lastButton').tabIndex=-1;d.getElementById('first').hidden=false;await t.flush();
  d.getElementById('notes').focus();const key=new w.KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true});d.activeElement.dispatchEvent(key);
  assert.equal(key.defaultPrevented,true);assert.equal(d.activeElement.id,'firstButton');
  d.activeElement.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true,cancelable:true}));assert.equal(d.activeElement.id,'notes');
 }finally{await t.close();}
});
test('empty modal gets focus and non-finite audio duration has a finite spoken value',async()=>{
 const t=uiHarness(),{d}=t;try {
  Object.defineProperty(d.getElementById('audio'),'duration',{value:Infinity});d.getElementById('audio').dispatchEvent(new t.w.Event('loadedmetadata'));
  assert.doesNotMatch(d.getElementById('seek').getAttribute('aria-valuetext'),/Infinity|NaN/);
  d.getElementById('second').querySelector('button').remove();d.getElementById('second').hidden=false;await t.flush();assert.equal(d.activeElement.getAttribute('role'),'dialog');
 }finally{await t.close();}
});
function studioHarness(stored){
 const dom=new JSDOM(fs.readFileSync(path.join(root,'web/index.html'),'utf8'),{url:'https://app.test',runScripts:'outside-only'}),w=dom.window,d=w.document;
 w.requestAnimationFrame=()=>0;w.cancelAnimationFrame=()=>{};w.matchMedia=()=>({matches:true});
 w.LightForgeApp={state:{project:{id:'test-project',duration:12},settings:{},projects:[]},vehiclePreview:{},toast(){},stopInspection(){},renderFrame(){},drawWave(){}};
 w.localStorage.setItem('lightforge-rehearsal-loops-v1',JSON.stringify(stored));
 w.eval(fs.readFileSync(path.join(root,'web/studio-tools.js'),'utf8'));
 return {w,d,close:()=>w.close()};
}
test('rehearsal storage recovers from wrong-shaped JSON and malformed retained entries',()=>{
 for(const stored of [17,'bad',[],{old:null,other:{a:1,b:2,updated:1}}]) {
  const t=studioHarness(stored);try {
   t.d.getElementById('audio').currentTime=2;t.d.getElementById('setLoopStart').onclick();
   t.d.getElementById('audio').currentTime=4;t.d.getElementById('setLoopEnd').onclick();
   const saved=JSON.parse(t.w.localStorage.getItem('lightforge-rehearsal-loops-v1'));
   assert.equal(saved['test-project'].a,2);assert.equal(saved['test-project'].b,4);assert.equal(saved.old,undefined);
   if(stored?.other)assert.equal(saved.other.b,2);
  }finally{t.close();}
 }
});
test('malformed completed restore records terminal failure without accepting a result',async()=>{
 const t=compilerHarness(), events=[], lease={jobId:'job',nonce:'nonce'};
 const promise=t.compiler.restore({}, {}, {},undefined,undefined,{restoreLease:lease,onRestoreEvent:event=>events.push(event)}), rejected=assert.rejects(promise,/invalid/);
 t.workers[0].emit({type:'restore-started',lease});t.workers[0].emit(null);await rejected;
 assert.deepEqual(events.map(event=>event.type),['restore-started','restore-error']);assert.equal(events[1].lease,lease);
});


test('the shipped page loads modal and keyboard accessibility behavior exactly once after the app',()=>{
 const dom=new JSDOM(fs.readFileSync(path.join(root,'web/index.html'),'utf8'));
 try{
  const scripts=[...dom.window.document.querySelectorAll('script[src]')].map(el=>el.getAttribute('src'));
  assert.equal(scripts.filter(src=>src==='ui-polish.js').length,1);
  assert.ok(scripts.indexOf('ui-polish.js')>scripts.indexOf('cockpit.js'));
  const release=JSON.parse(fs.readFileSync(path.join(root,'version.json'),'utf8')).name;
  const inventory=JSON.parse(fs.readFileSync(path.join(root,`qa/release-${release}/browser-source-inventory.json`),'utf8'));
  assert.ok(inventory.common.includes('web/ui-polish.js'),'browser evidence must bind the activated interaction layer');
 }finally{dom.window.close();}
});

function appHarness(){
 const dom=new JSDOM(fs.readFileSync(path.join(root,'web/index.html'),'utf8'),{url:'https://app.test/',runScripts:'outside-only'}),w=dom.window,d=w.document,frames=[];
 w.scrollTo=()=>{};w.requestAnimationFrame=fn=>{frames.push(fn);return frames.length;};w.cancelAnimationFrame=()=>{};w.matchMedia=()=>({matches:true,addEventListener(){}});
 w.HTMLElement.prototype.getClientRects=function(){return this.closest('[hidden]')?[]:[{}];};
 w.HTMLMediaElement.prototype.pause=function(){};w.HTMLMediaElement.prototype.load=function(){};
 w.VehiclePreview=class{render(){}setPaused(){}setView(){}};
 w.LightForgeVersion=require('../web/version.js');w.ShowEngine=require('../web/engine/show-engine.js');w.VehicleProfile=require('../web/engine/vehicle-profile.js');
 const calls={deleted:[],exports:[]};
 w.Android={pickAudio(){},getBootstrap:()=>JSON.stringify({projects:[]}),saveProject:()=>true,deleteProject:id=>calls.deleted.push(id),beginExport:()=> 'export-one',appendExport:()=>true,finishExport:id=>calls.exports.push(id)};
 w.eval(fs.readFileSync(path.join(root,'web/app.js'),'utf8'));w.eval(fs.readFileSync(path.join(root,'web/ui-polish.js'),'utf8'));
 return {w,d,calls,app:w.LightForgeApp,close:()=>w.close(),async flush(){await Promise.resolve();frames.splice(0).forEach(fn=>fn());await Promise.resolve();}};
}
test('shipped accessibility layer isolates real export dialogs and restores the opener',async()=>{
 const t=appHarness(),{w,d,app}=t;
 try{
  d.getElementById('workingStudio').hidden=false;d.getElementById('validationCard').hidden=false;
  app.state.project={id:'a',name:'Export integration',duration:1};app.state.music={duration:1};app.state.showMusic=app.state.music;app.state.renderedSettingsKey=JSON.stringify(app.state.settings);
  app.state.show={frames:new w.Uint8Array(200),duration:1,stepMs:20,validation:{valid:true}};app.state.exportHeader=new w.Uint8Array(32);
  const opener=d.getElementById('export');opener.disabled=false;opener.focus();await app.exportShow();await t.flush();
  assert.equal(t.calls.exports.length,1);assert.equal(d.querySelector('.app-shell').hasAttribute('inert'),true);assert.ok(d.getElementById('processing').contains(d.activeElement));
  w.onNativeEvent('exported',{id:'export-one',name:'Checked show'});await t.flush();
  assert.ok(d.getElementById('exportSuccess').contains(d.activeElement));assert.equal(d.querySelector('.app-shell').hasAttribute('inert'),true);
  d.getElementById('exportDone').click();await t.flush();assert.equal(d.querySelector('.app-shell').hasAttribute('inert'),false);assert.equal(d.activeElement,opener);
 }finally{t.close();}
});
test('native deletion acknowledgement removes only its target, clears stale editor state and never claims an error succeeded',async()=>{
 const t=appHarness(),{w,app,d}=t;
 try{
  const p={id:'remove',name:'Remove'},other={id:'keep',name:'Keep'};app.state.projects=[p,other];app.state.project=p;app.state.history=[{}];app.state.future=[{}];app.state.compiled={frameData:'old'};
  app.state.pendingProjectAction={kind:'delete',id:p.id};app.state.busy=true;
  w.onNativeEvent('projects',{projects:[p,other]});assert.equal(app.state.project,p);assert.equal(app.state.pendingProjectAction.kind,'delete');
  w.onNativeEvent('error',{message:'Delete denied by active export'});assert.equal(app.state.project,p);assert.equal(app.state.projects.length,2);assert.match(d.getElementById('toast').textContent,/Delete denied/);
  app.state.pendingProjectAction={kind:'delete',id:p.id};app.state.busy=true;w.onNativeEvent('projects',{projects:[other]});
  assert.equal(app.state.project,null);assert.equal(app.state.projects.length,1);assert.equal(app.state.projects[0].id,'keep');assert.equal(app.state.compiled,null);assert.equal(app.state.history.length,0);assert.equal(app.state.future.length,0);assert.equal(app.state.busy,false);assert.equal(d.getElementById('toast').textContent,'Show deleted.');await t.flush();
 }finally{t.close();}
});
test('saved-show keyboard activation prevents scrolling and repeated opening on held keys',()=>{
 const t=appHarness(),{app,d,w}=t;
 try{
  app.state.projects=[{id:'keyboard',name:'Keyboard project'}];app.renderProjects();const card=d.querySelector('.saved-show-copy');
  app.state.busy=true;const space=new w.KeyboardEvent('keydown',{key:' ',bubbles:true,cancelable:true});card.dispatchEvent(space);assert.equal(space.defaultPrevented,true);
  const held=new w.KeyboardEvent('keydown',{key:'Enter',repeat:true,bubbles:true,cancelable:true});card.dispatchEvent(held);assert.equal(held.defaultPrevented,true);assert.equal(app.state.project,null);
 }finally{t.close();}
});
