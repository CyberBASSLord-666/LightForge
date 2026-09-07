'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),{JSDOM}=require('jsdom'),fs=require('node:fs'),path=require('node:path');
const run=require('./worker-harness.cjs'),root=path.resolve(__dirname,'..');
test('real app facade commits, undoes, redoes, saves, and isolates musical edits through the DOM',async()=>{
 const dom=new JSDOM(fs.readFileSync(path.join(root,'web/index.html'),'utf8'),{url:'https://lightforge.test/',runScripts:'outside-only'}),w=dom.window,d=w.document;
 const music={duration:12,bpm:120,beats:Array.from({length:24},(_,i)=>i*.5),waveform:[.7],beatConfidence:.9,sections:[{start:0,end:12,energy:.7}],analysisVersion:5};
 const saved={settings:{dance:'off',seed:5},music},writes=[];
 w.scrollTo=()=>{};w.requestAnimationFrame=()=>0;w.cancelAnimationFrame=()=>{};w.matchMedia=()=>({matches:true,addEventListener(){}});
 w.HTMLMediaElement.prototype.pause=function(){};w.HTMLMediaElement.prototype.load=function(){};
 w.VehiclePreview=class{render(){}setCamera(){}setStage(){}setQuality(){}resize(){}};
 w.LightForgeVersion=require('../web/version.js');w.ShowEngine=require('../web/engine/show-engine.js');w.VehicleProfile=require('../web/engine/vehicle-profile.js');w.MusicCues=require('../web/engine/music-cues.js');
 w.ShowCompiler={generate:(music,settings)=>run(path.join(root,'web/engine'),{action:'generate',music,settings}),restore:(compiled,music,settings)=>run(path.join(root,'web/engine'),{action:'restore',compiled,music,settings})};
 w.Android={pickAudio(){},getBootstrap:()=>JSON.stringify({projects:[],version:'2.0.0'}),saveProject:(id,body)=>{writes.push(JSON.parse(body));return true;}};
 w.fetch=async()=>({ok:true,json:async()=>structuredClone(saved)});
 const loops=[];w.StudioTools={loopPassage:(...range)=>{loops.push(range);return true;}};
 try{
  w.eval(fs.readFileSync(path.join(root,'web/app.js'),'utf8'));w.eval(fs.readFileSync(path.join(root,'web/precision-studio.js'),'utf8'));
  const app=w.LightForgeApp;await app.selectProject({id:'a',name:'Cue fixture',duration:12,audioUrl:'song.wav',projectUrl:'project.json'});
  const audio=d.querySelector('audio');Object.defineProperty(audio,'duration',{value:Infinity,configurable:true});audio.onloadedmetadata();assert.equal(d.getElementById('totalTime').textContent,'0:12');assert.equal(d.getElementById('seek').max,'12');
  assert.equal(app.state.show.version,require('../web/version.js').name);assert.equal(d.getElementById('precisionStudio').hidden,false);
  const val=(id,x)=>d.getElementById(id).value=String(x);
  val('musicCueStart',3.137);val('musicCueEnd',4.719);val('musicCueAction','hold');val('musicCueLabel','Final note');
  await d.getElementById('musicCueForm').onsubmit({preventDefault(){}});
  assert.equal(app.state.settings.musicCues.length,1);assert.equal(app.state.show.synchronization.manual[0].status,'matched');
  assert.match(d.getElementById('savedMusicCues').textContent,/Final note/);assert.match(d.getElementById('precisionMessage').textContent,/saved/);
  const frames=app.state.show.frames.slice();await app.undo();assert.equal(app.state.settings.musicCues.length,0);await app.redo();assert.deepEqual(app.state.show.frames,frames);
  val('musicCueStart',3.2);val('musicCueEnd',3.8);await d.getElementById('musicCueForm').onsubmit({preventDefault(){}});assert.match(d.getElementById('precisionMessage').textContent,/overlap/);assert.deepEqual(app.state.show.frames,frames);
  val('vocalOffset',-125);val('bassOffset',210);await d.getElementById('roleTimingForm').onsubmit({preventDefault(){}});assert.equal(app.state.settings.vocalOffsetMs,-125);assert.equal(app.state.settings.musicCues[0].start,3.137);
  await app.saveProject();assert.equal(writes.at(-1).provenance.app,require('../web/version.js').name);assert.equal(writes.at(-1).settings.musicCues[0].label,'Final note');assert.ok(writes.at(-1).compiled.sha256);
  d.getElementById('listenMusicCue').onclick();assert.equal(loops.length,1);
  await app.selectProject({id:'b',name:'New song',duration:12,audioUrl:'new.wav'},true);assert.equal(app.state.settings.musicCues.length,0);assert.equal(app.state.settings.vocalOffsetMs,0);assert.equal(app.state.settings.bassOffsetMs,0);
 }finally{w.close();}
});
