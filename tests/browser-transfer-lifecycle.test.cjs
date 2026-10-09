'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(process.env.LIGHTFORGE_APP_SOURCE||path.join(__dirname,'../web/app.js'),'utf8');
const extract=(name,next)=>source.slice(source.indexOf('async function '+name+'('),source.indexOf(next,source.indexOf('async function '+name+'(')));
const importSource=extract('importBrowser','async function selectProject(');
const exportSource=extract('exportShow','function projectMenu(');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
function harness(overrides={}){
 const calls={closed:0,deleted:[],revoked:[],selected:[],messages:[],downloads:0,exports:0},state={busy:false,job:0,projects:[],selection:0};
 const context={state,diagnostics:null,crypto:{randomUUID:()=> 'unique'},URL:{createObjectURL:()=> 'blob:audio',revokeObjectURL:url=>calls.revoked.push(url)},
 window:{AudioContext:class{async decodeAudioData(){return {duration:1};}async close(){calls.closed++;}}},
 OfflineAudioContext:class{createBufferSource(){return {connect(){},start(){}};}async startRendering(){return {duration:1};}},
 encodeWav:()=>({audio:true}),dbPut:async()=>{},dbDelete:async(store,id)=>calls.deleted.push([store,id]),localStorage:{setItem(){}},
 beginBusy:()=>{state.busy=true;return ++state.job;},endBusy:()=>{state.busy=false;},selectProject:async p=>{calls.selected.push(p);state.project=p;},toast:msg=>calls.messages.push(msg),
 stopInspection(){},currentShowMatches:()=>true,saveProject:async()=>true,native:()=>false,Uint8Array,TextEncoder,fetch:async()=>({ok:true,arrayBuffer:async()=>new ArrayBuffer(4)}),
 zipStored:()=>({zip:true}),projectJson:()=>({}),safeName:()=> 'song',document:{createElement:()=>({click(){calls.downloads++;}})},setTimeout(){},exported:()=>{calls.exports++;state.busy=false;},...overrides};
 vm.createContext(context);vm.runInContext(importSource+'\n'+exportSource,context);return {context,state,calls,run:()=>context.importBrowser({name:'song.wav',arrayBuffer:async()=>new ArrayBuffer(1)})};
}
function readyExport(h){h.state.project={id:'p',name:'song',audioUrl:'song.wav'};h.state.show={validation:{valid:true},frames:new Uint8Array(4)};h.state.exportHeader=new Uint8Array(8);}
test('decode failure closes its AudioContext and leaves no phantom project',async()=>{
 const h=harness();h.context.window.AudioContext.prototype.decodeAudioData=async()=>{throw Error('bad audio');};await h.run();assert.equal(h.calls.closed,1);assert.equal(h.state.busy,false);assert.equal(h.state.projects.length,0);assert.match(h.calls.messages[0],/bad audio/);
});
test('cancellation during durable import write cannot adopt or dismiss newer work',async()=>{
 const write=deferred(),h=harness({dbPut:()=>write.promise});const pending=h.run();await new Promise(setImmediate);h.state.job++;h.state.busy=true;write.resolve();await pending;
 assert.equal(h.state.busy,true);assert.equal(h.calls.selected.length,0);assert.equal(h.state.projects.length,0);assert.deepEqual(h.calls.deleted,[['audio','show-unique']]);assert.equal(h.calls.messages.length,0);
});
test('late decode failure cannot dismiss or report over a newer operation',async()=>{
 const decode=deferred(),h=harness();h.context.window.AudioContext.prototype.decodeAudioData=()=>decode.promise;const pending=h.run();await new Promise(setImmediate);h.state.job++;h.state.busy=true;decode.reject(Error('old failure'));await pending;
 assert.equal(h.state.busy,true);assert.equal(h.calls.closed,1);assert.equal(h.calls.messages.length,0);
});
test('catalog quota failure rolls back imported audio and its object URL',async()=>{
 const h=harness({localStorage:{setItem(){throw Error('Quota exceeded');}}});await h.run();assert.equal(h.state.projects.length,0);assert.equal(h.calls.selected.length,0);assert.deepEqual(h.calls.revoked,['blob:audio']);assert.equal(h.calls.deleted.length,1);assert.match(h.calls.messages[0],/Quota exceeded/);
});
test('successful import publishes and adopts exactly once; repeated input while busy is ignored',async()=>{
 const write=deferred(),h=harness({dbPut:()=>write.promise});const pending=h.run(),repeated=h.run();write.resolve();await Promise.all([pending,repeated]);assert.equal(h.calls.closed,1);assert.equal(h.calls.selected.length,1);assert.equal(h.state.projects.length,1);assert.equal(h.calls.deleted.length,0);assert.equal(h.calls.revoked.length,0);
});
test('HTTP audio failure prevents export instead of packaging an error body as WAV',async()=>{
 const h=harness({fetch:async()=>({ok:false,arrayBuffer:async()=>{throw Error('should not read error body');}})});readyExport(h);await h.context.exportShow();assert.equal(h.calls.downloads,0);assert.equal(h.calls.exports,0);assert.equal(h.state.busy,false);assert.equal(h.state.acceptProgress,false);assert.match(h.calls.messages[0],/audio could not be read/);
});
test('late failed export cannot dismiss a newer operation after cancellation',async()=>{
 const response=deferred(),h=harness({fetch:()=>response.promise});readyExport(h);const pending=h.context.exportShow();await new Promise(setImmediate);h.state.job++;h.state.busy=true;response.reject(Error('old request'));await pending;assert.equal(h.state.busy,true);assert.equal(h.calls.messages.length,0);assert.equal(h.calls.downloads,0);
});
test('repeated export clicks across the save await start one download',async()=>{
 const save=deferred(),h=harness({saveProject:()=>save.promise});readyExport(h);const first=h.context.exportShow(),second=h.context.exportShow();save.resolve(true);await Promise.all([first,second]);assert.equal(h.state.job,1);assert.equal(h.calls.downloads,1);assert.equal(h.calls.exports,1);
});
test('project change while saving cancels export of the stale selection',async()=>{
 const save=deferred(),h=harness({saveProject:()=>save.promise});readyExport(h);const pending=h.context.exportShow();h.state.selection++;save.resolve(true);await pending;assert.equal(h.calls.downloads,0);assert.equal(h.state.busy,false);
});

function storageHarness(){
 const requests=[],transactions=[],context={indexedDB:{open(){const request={};requests.push(request);return request;}}};
 vm.createContext(context);vm.runInContext('let dbPromise;\n'+source.slice(source.indexOf('async function db(){'),source.indexOf('function encodeWav(')),context);
 const connection={closed:false,close(){this.closed=true;},transaction(){const tx={objectStore:()=>({put(){},delete(){},get:()=>({})})};transactions.push(tx);return tx;}};
 return {context,requests,transactions,connection,open(){const request=requests.at(-1);request.result=connection;request.onsuccess();}};
}
test('failed IndexedDB open can be retried without restarting the app',async()=>{
 const h=storageHarness(),first=h.context.db();h.requests[0].error=Error('temporarily unavailable');h.requests[0].onerror();await assert.rejects(first,/temporarily unavailable/);
 const second=h.context.db();assert.equal(h.requests.length,2);h.open();assert.equal(await second,h.connection);
});
test('IndexedDB write abort rejects promptly rather than leaving import or save stuck',async()=>{
 const h=storageHarness(),pending=h.context.dbPut('audio','track',{});h.open();await new Promise(setImmediate);h.transactions[0].onabort();await assert.rejects(pending,/interrupted/);
});
test('IndexedDB deletion abort preserves the reported storage error',async()=>{
 const h=storageHarness(),pending=h.context.dbDelete('audio','track');h.open();await new Promise(setImmediate);h.transactions[0].error=Error('disk unavailable');h.transactions[0].onabort();await assert.rejects(pending,/disk unavailable/);
});
test('IndexedDB version change releases the old connection and reopens on demand',async()=>{
 const h=storageHarness(),first=h.context.db();h.open();await first;h.connection.onversionchange();assert.equal(h.connection.closed,true);
 const second=h.context.db();assert.equal(h.requests.length,2);h.open();await second;
});
