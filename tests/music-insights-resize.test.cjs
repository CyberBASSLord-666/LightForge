'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{JSDOM}=require('jsdom');
const root=path.resolve(__dirname,'..');
function fixture({notes=true,dpr=2,width=500}={}){
 const dom=new JSDOM(fs.readFileSync(path.join(root,'web/index.html'),'utf8'),{url:'https://lightforge.test/',runScripts:'outside-only'}),w=dom.window,d=w.document;
 const frames=new Map(),draws=[],observers=[];let nextFrame=0,shown=false;
 w.requestAnimationFrame=fn=>{frames.set(++nextFrame,fn);return nextFrame;};w.cancelAnimationFrame=id=>frames.delete(id);
 Object.defineProperty(w,'devicePixelRatio',{value:dpr});
 w.IntersectionObserver=class{observe(){}};
 w.ResizeObserver=class{constructor(callback){this.callback=callback;observers.push(this);}observe(target){this.target=target;}};
 for(const role of ['vocal','bass']){
  const canvas=d.getElementById(role+'Timeline');
  canvas.parentElement.getBoundingClientRect=()=>({width:shown?width:0});
  const context=new Proxy({},{get:(_,method)=>(...args)=>draws.push({role,method,args}),set:()=>true});
  canvas.getContext=()=>context;
 }
 const vocals={available:true,sourceSeparated:true,source:'separated-vocals',confidence:.9,phrases:[{start:1,end:4}],notes:notes?[{start:1,end:2,midi:60,confidence:.9}]:[]};
 const music={duration:12,analysisVersion:5,vocals,bassNotes:[{start:2,end:3,midi:36}]};
 w.LightForgeApp={state:{music,show:{stats:{},choreography:{}},project:{duration:12},settings:{dance:'off'}},toast(){}};
 w.eval(fs.readFileSync(path.join(root,'web/music-insights.js'),'utf8'));
 assert.equal(observers.length,1);assert.equal(observers[0].target.id,'musicalRoleTimelines');
 return {w,d,frames,draws,show:value=>{shown=value;},resize:()=>observers[0].callback([{target:observers[0].target}]),flush:()=>{const pending=[...frames.values()];frames.clear();for(const fn of pending)fn(0);},close:()=>w.close()};
}
function geometry(f,role='vocal'){
 const canvas=f.d.getElementById(role+'Timeline');return {width:canvas.width,height:canvas.height,pitched:canvas.parentElement.classList.contains('with-pitch')};
}

test('revealing a pitched music lane defers all resize drawing and coalesces notifications',()=>{
 const f=fixture();try{
  const before=geometry(f);assert.equal(before.pitched,false);assert.equal(f.draws.length,0);
  f.show(true);for(let i=0;i<5;i++)f.resize();
  assert.deepEqual(geometry(f),before,'ResizeObserver delivery must not change the observed ancestor height');
  assert.equal(f.draws.length,0,'canvas writes must also leave the observer delivery stack');
  assert.equal(f.frames.size,1,'a burst schedules one frame');
  f.flush();
  assert.deepEqual(geometry(f),{width:1000,height:106,pitched:true});
  assert.deepEqual(geometry(f,'bass'),{width:1000,height:70,pitched:false});
  assert.deepEqual(f.draws.filter(x=>x.method==='clearRect').map(x=>x.args),[[0,0,500,53],[0,0,500,35]]);
  assert.ok(f.draws.some(x=>x.role==='vocal'&&x.method==='fillRect'&&x.args[3]===2),'pitch ribbon remains drawn');
  assert.equal(f.frames.size,0,'resize rendering must not become an animation loop');
 }finally{f.close();}
});

test('a follow-up observer notification settles without another lane height change',()=>{
 const f=fixture();try{
  f.show(true);f.resize();f.flush();const settled=geometry(f);
  f.resize();assert.deepEqual(geometry(f),settled);assert.equal(f.frames.size,1);f.flush();
  assert.deepEqual(geometry(f),settled);assert.equal(f.frames.size,0);
 }finally{f.close();}
});

test('hiding a lane before the queued frame preserves zero-width canvas-work suppression',()=>{
 const f=fixture();try{
  f.show(true);f.resize();f.show(false);const before=geometry(f);f.flush();
  assert.deepEqual(geometry(f),before);assert.equal(f.draws.length,0);assert.equal(f.frames.size,0);
  f.show(true);f.resize();f.flush();assert.equal(geometry(f).pitched,true);assert.ok(f.draws.length>0);
 }finally{f.close();}
});

test('unpitched lanes retain their original height, fractional-width rounding and DPR cap',()=>{
 const f=fixture({notes:false,dpr:3,width:320.25});try{
  f.show(true);f.resize();f.flush();
  assert.deepEqual(geometry(f),{width:642,height:70,pitched:false});
  assert.deepEqual(f.draws.filter(x=>x.method==='scale').map(x=>x.args),[[2,2],[2,2]]);
 }finally{f.close();}
});

test('the aggregate gate runs the resize regression and browser evidence binds its product source',()=>{
 const gate=fs.readFileSync(path.join(root,'tools/verify_v2.py'),'utf8');
 assert.equal((gate.match(/'music-insights-resize\.test\.cjs'/g)||[]).length,1);
 const inventory=JSON.parse(fs.readFileSync(path.join(root,'qa/release-2.4.1/browser-source-inventory.json'),'utf8'));
 assert.ok(inventory.common.includes('web/music-insights.js'));
});
