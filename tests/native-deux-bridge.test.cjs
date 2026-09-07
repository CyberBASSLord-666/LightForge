'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const token='12345678-1234-1234-1234-123456789abc';
function load(){const window={};vm.runInNewContext(fs.readFileSync(require.resolve('../web/background/native-deux.js'),'utf8'),{window,DOMException,setTimeout:callback=>setTimeout(callback,0)});return window.LightForgeNativeDeux;}
function bridge(states){const calls=[];return{calls,nativeDeuxStart(id,start){calls.push(['start',id,start]);return JSON.stringify({token,state:'running',progress:0});},nativeDeuxStatus(id,t){calls.push(['status',id,t]);return JSON.stringify({token,...states.shift()});},nativeDeuxCancel(id,t){calls.push(['cancel',id,t]);}};}
test('native bridge exposes only complete audio from the matching private passage',async()=>{
 const url='https://appassets.androidplatform.net/background/native/'+token+'.bin',b=bridge([{state:'running',progress:.5,message:'Following voice'},{state:'completed',progress:1,url}]),progress=[];
 const result=await load().create(b,'job')(-66150,new AbortController().signal,p=>progress.push(p.progress));
 assert.equal(result.url,url);assert.deepEqual(progress,[0,.5,1]);assert.equal(b.calls.filter(x=>x[0]==='cancel').length,0);
});
test('abort cancels the native operation and never reports a result',async()=>{
 const b=bridge([]),controller=new AbortController();await assert.rejects(load().create(b,'job')(0,controller.signal,()=>controller.abort()),{name:'AbortError'});
 assert.ok(b.calls.some(x=>x[0]==='cancel'));assert.equal(b.calls.some(x=>x[0]==='status'),false);
});
test('a stale token or external result URL cannot become source audio',async()=>{
 for(const response of [{token:'stale',state:'completed',url:'https://appassets.androidplatform.net/background/native/'+token+'.bin'},{state:'completed',url:'https://example.com/audio.bin'}]){
  const b=bridge([response]);await assert.rejects(load().create(b,'job')(0),/identity changed|Invalid native audio/);assert.ok(b.calls.some(x=>x[0]==='cancel'));
 }
});
test('native failures remain actionable and do not silently switch the model',async()=>{
 const b=bridge([{state:'failed',message:'Insufficient memory for Studio'}]);await assert.rejects(load().create(b,'job')(0),/Insufficient memory/);assert.equal(b.calls.filter(x=>x[0]==='start').length,1);
 assert.equal(load().create({},'job'),undefined);
});
test('invalid source position is rejected before starting native work',async()=>{
 const b=bridge([]);for(const position of [NaN,Infinity,1.2,-66151,44100*14400+1])await assert.rejects(load().create(b,'job')(position),/Invalid native passage position/);
 assert.equal(b.calls.length,0);
});
