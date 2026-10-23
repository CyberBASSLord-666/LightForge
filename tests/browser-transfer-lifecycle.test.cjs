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

const duplicateSource=extract('duplicateProject',"$('musicalExpression')");
function duplicateHarness(overrides={}){
 const t=harness({namePrompt:async()=> 'New version',dbGet:async store=>store==='audio'?{audio:true}:{name:'Original',projectId:'original',music:{duration:1}},...overrides});
 t.state.projects=[{id:'original',name:'Original',audioUrl:'source.wav',previewUrl:'old-preview.wav',hasShow:true}];
 vm.runInContext(duplicateSource,t.context);
 t.copy=()=>t.context.duplicateProject(t.state.projects[0]);return t;
}
test('duplicate rejects an HTTP audio error without creating phantom storage',async()=>{
 const t=duplicateHarness({dbGet:async()=>null,fetch:async()=>({ok:false,blob:async()=>{throw Error('must not consume error page');}})});
 await t.copy();assert.equal(t.state.projects.length,1);assert.equal(t.calls.selected.length,0);assert.equal(t.state.busy,false);assert.match(t.calls.messages[0],/audio could not be read/);
});
test('cancelled duplicate rolls back both records and cannot dismiss newer work',async()=>{
 const write=deferred(),t=duplicateHarness({dbPut:()=>write.promise});const pending=t.copy();await new Promise(setImmediate);
 t.state.job++;t.state.busy=true;write.resolve();await pending;
 assert.equal(t.state.busy,true);assert.equal(t.state.projects.length,1);assert.equal(t.calls.selected.length,0);assert.equal(t.calls.messages.length,0);assert.deepEqual(t.calls.deleted,[['audio','show-unique'],['projects','show-unique']]);
});
test('duplicate catalog quota failure rolls back both stores and the preview URL',async()=>{
 const t=duplicateHarness({localStorage:{setItem(){throw Error('Quota exceeded');}}});await t.copy();
 assert.equal(t.state.projects.length,1);assert.equal(t.calls.selected.length,0);assert.deepEqual(t.calls.revoked,['blob:audio']);assert.deepEqual(t.calls.deleted,[['audio','show-unique'],['projects','show-unique']]);assert.match(t.calls.messages[0],/Quota exceeded/);
});
test('a late failed duplicate never reports over a newer operation',async()=>{
 const read=deferred(),t=duplicateHarness({dbGet:()=>read.promise});const pending=t.copy();await new Promise(setImmediate);
 t.state.job++;t.state.busy=true;read.reject(Error('old failure'));await pending;assert.equal(t.state.busy,true);assert.equal(t.calls.messages.length,0);
});
test('successful duplicate owns its audio URL, preserves saved composition, and publishes once',async()=>{
 const writes=[],t=duplicateHarness({dbPut:async(...args)=>writes.push(args)});await t.copy();
 assert.equal(t.state.projects.length,2);assert.equal(t.calls.selected.length,1);assert.equal(t.state.projects[0].previewUrl,undefined);assert.equal(t.state.projects[0].audioUrl,'blob:audio');
 const saved=writes.find(x=>x[0]==='projects')[2];assert.equal(saved.projectId,'show-unique');assert.equal(saved.name,'New version');assert.deepEqual(saved.music,{duration:1});assert.equal(t.calls.deleted.length,0);
});

const savedReadSource=extract('readSavedProject','async function selectProject(');
const selectSource=extract('selectProject','function currentShowMatches(');
function selectionHarness(overrides={}){
 const elements=new Map(),calls={saved:0,regenerated:[],scheduled:0,messages:[]};
 const state={selection:0,compileId:0,projects:[],settings:{style:'cinematic'}};
 const element=id=>{if(!elements.has(id))elements.set(id,{hidden:false});return elements.get(id);};
 const context={state,$:element,diagnostics:null,saveProject:async()=>true,stopInspection(){},abandonAudition(){},clearTimeout,setTimeout,AbortController,DOMException,saveTimer:0,regenTimer:0,lastSection:-1,audio:{pause(){},src:''},URL,location:{href:'https://test.local/'},
 document:{querySelector:()=>({inert:false})},text:(el,value)=>el.textContent=value,formatTime:String,nav(){},resizeCanvases(){},updateButtons(){},syncControls(){},renderFrame(){},drawWave(){},recommendedExpression:{},
 mergeSettings:value=>({...value}),scheduleSave:()=>calls.scheduled++,refreshAuditionAvailability:async()=>{},toast:msg=>calls.messages.push(msg),
 regenerate:async options=>{calls.regenerated.push(options);},fetch:async()=>({ok:true,json:async()=>({settings:{style:'festival'},music:{duration:1},compiled:{frameData:'saved-bytes'}})}),...overrides};
 vm.createContext(context);vm.runInContext(savedReadSource+'\n'+selectSource,context);return {context,state,calls,elements,open:(p={id:'a',name:'Saved',projectUrl:'project.json'})=>context.selectProject(p)};
}
test('failed saved-project HTTP read is fail-closed and never schedules an empty replacement',async()=>{
 const t=selectionHarness({fetch:async()=>({ok:false})});assert.equal(await t.open(),false);
 assert.equal(t.state.saveBlocked,true);assert.equal(t.state.loadingProject,false);assert.equal(t.calls.scheduled,0);assert.equal(t.calls.regenerated.length,0);assert.match(t.calls.messages[0],/saved work has not been replaced/);
});
test('damaged or cross-project saved state is rejected without replacing saved frames',async()=>{
 for(const saved of [null,false,0,'',[],42,{settings:[]},{music:[]},{compiled:'invalid'},{projectId:'different',settings:{}}]){
  const t=selectionHarness({fetch:async()=>({ok:true,json:async()=>saved})});await t.open();
  assert.equal(t.state.saveBlocked,true);assert.equal(t.calls.scheduled,0);assert.equal(t.calls.regenerated.length,0);
 }
});
test('retry after an HTTP failure restores original compiled bytes without generating a replacement',async()=>{
 let failed=true;const compiled={frameData:'original-arrangement'},t=selectionHarness({fetch:async()=>({ok:!failed,json:async()=>({settings:{style:'cinematic'},music:{duration:1},compiled})})});
 assert.equal(await t.open(),false);failed=false;assert.equal(await t.open(),true);
 assert.equal(t.state.saveBlocked,false);assert.equal(t.calls.regenerated.length,1);assert.equal(t.calls.regenerated[0].restoreCompiled,compiled);assert.equal(t.calls.scheduled,1);
});
test('newest project-open intent wins when earlier save promises finish last',async()=>{
 const first=deferred(),second=deferred();let save=0;const t=selectionHarness({saveProject:()=>++save===1?first.promise:second.promise});t.state.project={id:'old'};
 const older=t.open({id:'a'}),newer=t.open({id:'b'});second.resolve(true);await newer;first.resolve(true);assert.equal(await older,false);assert.equal(t.state.project.id,'b');assert.equal(t.state.selection,1);
});
test('project opening cannot adopt after an unrelated operation starts during save',async()=>{
 const saved=deferred(),t=selectionHarness({saveProject:()=>saved.promise});t.state.project={id:'old'};
 const pending=t.open();t.state.busy=true;saved.resolve(true);assert.equal(await pending,false);assert.equal(t.state.project.id,'old');
});
test('missing browser soundtrack or saved arrangement is reported instead of silently creating defaults',async()=>{
 for(const missing of ['audio','projects']){
  const t=selectionHarness({URL:{createObjectURL:()=> 'blob:restored',revokeObjectURL(){}},dbGet:async store=>store===missing?null:{audio:true}});
  await t.open({id:'a',browser:true,hasShow:true});assert.equal(t.state.saveBlocked,true);assert.equal(t.calls.scheduled,0);
 }
});

test('browser deletion removes audio and project in one abortable transaction',async()=>{
 const h=storageHarness(),stores=[],deleted=[];h.connection.transaction=(names,mode)=>{stores.push([names,mode]);const tx={objectStore:name=>({delete:id=>deleted.push([name,id])})};h.transactions.push(tx);return tx;};
 const pending=h.context.dbDeleteProject('remove-me');h.open();await new Promise(setImmediate);
 assert.equal(JSON.stringify(stores),JSON.stringify([[['audio','projects'],'readwrite']]));assert.deepEqual(deleted,[['audio','remove-me'],['projects','remove-me']]);
 h.transactions[0].onabort();await assert.rejects(pending,/deletion was interrupted/);
});

const deletionSource=source.slice(source.indexOf('function finishProjectDeletion('),source.indexOf('async function exportShow('));
function deletionHarness(overrides={}){
 const t=harness({confirmAction:async()=>true,$:()=>({}),clearTimeout(){},saveTimer:0,dbDeleteProject:async()=>{},...overrides});
 vm.runInContext(deletionSource,t.context);t.state.projects=[{id:'original',name:'Original'}];
 return {...t,remove:()=>t.context.deleteProject(t.state.projects[0])};
}
test('native deletion keeps the project until a collection acknowledgement arrives',async()=>{
 const actions=[],t=deletionHarness({native:()=>true,bridge:(...args)=>actions.push(args)});
 await t.remove();assert.equal(t.state.projects.length,1);assert.equal(t.state.pendingProjectAction.kind,'delete');assert.equal(t.state.busy,true);assert.deepEqual(actions,[['deleteProject','original']]);assert.equal(t.calls.messages.length,0);
});
test('failed browser deletion retains the collection and reports the actual failure',async()=>{
 const t=deletionHarness({dbDeleteProject:async()=>{throw Error('Storage write interrupted');}});
 await t.remove();assert.equal(t.state.projects.length,1);assert.equal(t.state.busy,false);assert.match(t.calls.messages[0],/Storage write interrupted/);
});
test('starting another operation while delete confirmation is open prevents conflicting deletion',async()=>{
 const choice=deferred(),t=deletionHarness({confirmAction:()=>choice.promise});const pending=t.remove();t.state.busy=true;choice.resolve(true);await pending;assert.equal(t.state.projects.length,1);assert.equal(t.state.job,0);
});

test('a save freezes mutable editor settings before asynchronous storage opens',async()=>{
 const write=deferred(),writes=[],state={project:{id:'p',name:'Saved'},projects:[],settings:{style:'festival',enabled:{trunk:true}},music:null,compiled:null};
 const context={state,backgroundActive:()=>false,clone:value=>JSON.parse(JSON.stringify(value)),projectJson:()=>({settings:state.settings,music:null,compiled:null}),localStorage:{setItem(){}},native:()=>false,dbPut:async(store,id,body)=>{writes.push(body);await write.promise;},document:{dispatchEvent(){}},CustomEvent:class{},toast(){}};
 vm.createContext(context);vm.runInContext(extract('saveProject','function captureSnapshot('),context);
 const pending=context.saveProject();state.settings.enabled.trunk=false;write.resolve();await pending;assert.equal(writes[0].settings.enabled.trunk,true);
});

test('native analysis start is cancelled if project selection changes while saving',async()=>{
 const save=deferred(),calls=[],state={project:{id:'a'},selection:1};
 const context={state,saveProject:()=>save.promise,clearTimeout(){},saveTimer:0,abandonAudition(){},audio:{pause(){}},mixAudioUrl:()=>'',window:{Android:{}},bridge:(...args)=>calls.push(args)};
 vm.createContext(context);vm.runInContext(extract('startBackgroundGeneration','async function generate('),context);
 const pending=context.startBackgroundGeneration();state.project={id:'b'};state.selection++;save.resolve(true);await pending;assert.deepEqual(calls,[]);
});
test('native analysis double-click cannot start a second job after the first save await',async()=>{
 const saves=deferred(),calls=[],state={project:{id:'a'},selection:1,analysisExecutionMode:'resume'};
 const context={state,saveProject:()=>saves.promise,clearTimeout(){},saveTimer:0,abandonAudition(){},audio:{pause(){}},mixAudioUrl:()=>'',window:{Android:{}},bridge:(...args)=>{calls.push(args);return {id:'one'};},parse:value=>value,$:()=>null,handleBackgroundJob:async()=>{state.busy=true;}};
 vm.createContext(context);vm.runInContext(extract('startBackgroundGeneration','async function generate('),context);
 const first=context.startBackgroundGeneration(),second=context.startBackgroundGeneration();saves.resolve(true);await Promise.all([first,second]);assert.equal(calls.length,1);
});
test('completed foreground analysis save cannot dismiss newer work after cancellation',async()=>{
 const save=deferred(),state={project:{id:'a',audioUrl:'song'},settings:{},music:{duration:1,analysisVersion:8},job:0,compileId:0},messages=[];
 const context={state,window:{MusicAnalyzer:{},ShowCompiler:{}},stopInspection(){},clearTimeout(){},regenTimer:0,backgroundSupported:()=>false,captureSnapshot:()=>({}),
 beginBusy:()=>{state.busy=true;return ++state.job;},AbortController,setAudition:async()=>{},clone:value=>({...value}),alignedMusic:value=>value,setProgress(){},ShowCompiler:{generate:async()=>({})},adoptShow(){},saveProject:()=>save.promise,endBusy:()=>state.busy=false,refreshAuditionAvailability:async()=>{},toast:msg=>messages.push(msg),$:()=>({focus(){}}),updateButtons(){},diagnostics:null,analysisFallback:null};
 vm.createContext(context);vm.runInContext(extract('generate','function alignedMusic('),context);
 const pending=context.generate();await new Promise(setImmediate);state.job++;state.busy=true;save.resolve(true);await pending;
 assert.equal(state.busy,true);assert.equal(messages.length,0);
});


test('ordinary saved-project opening times out response headers and bodies without saving replacement data',async()=>{
 for(const phase of ['headers','body']){
  let fire,controllerSignal,cleared=false;
  const t=selectionHarness({setTimeout:callback=>{fire=callback;return 7;},clearTimeout:id=>{if(id===7)cleared=true;},fetch:async(url,{signal})=>{controllerSignal=signal;return phase==='headers'?new Promise(()=>{}):{ok:true,json:()=>new Promise(()=>{})};}});
  const pending=t.open();await new Promise(setImmediate);fire();assert.equal(await pending,false);
  assert.equal(controllerSignal.aborted,true);assert.equal(cleared,true);assert.equal(t.state.loadingProject,false);assert.equal(t.state.saveBlocked,true);assert.equal(t.calls.scheduled,0);assert.match(t.calls.messages[0],/took too long/);
 }
});
test('superseding a project open aborts its fetch promptly even if transport ignores AbortSignal',async()=>{
 let oldSignal;const t=selectionHarness({fetch:async(url,{signal})=>{if(url.endsWith('old.json')){oldSignal=signal;return new Promise(()=>{});}return {ok:true,json:async()=>({settings:{style:'festival'}})};}});
 const older=t.open({id:'old',projectUrl:'old.json'});await new Promise(setImmediate);
 assert.equal(await t.open({id:'new',projectUrl:'new.json'}),true);await older;
 assert.equal(oldSignal.aborted,true);assert.equal(t.state.project.id,'new');assert.equal(t.state.projectReadAbort,null);assert.equal(t.calls.messages.length,0);
});


test('missing native deletion acknowledgement is rechecked and released as failure, never success',async()=>{
 let fire;const actions=[],t=deletionHarness({native:()=>true,setTimeout:callback=>{fire=callback;},parse:value=>value,applyBootstrap(){},bridge:(...args)=>{actions.push(args);return {projects:[{id:'original'}]};}});
 await t.remove();assert.equal(t.state.busy,true);fire();
 assert.equal(t.state.busy,false);assert.equal(t.state.pendingProjectAction,null);assert.equal(t.state.projects.length,1);assert.deepEqual(actions,[['deleteProject','original'],['getBootstrap']]);assert.match(t.calls.messages[0],/did not confirm deletion/);
});
test('confirmed native deletion leaves its delayed acknowledgement watchdog inert',async()=>{
 let fire;const actions=[],t=deletionHarness({native:()=>true,setTimeout:callback=>{fire=callback;},bridge:(...args)=>actions.push(args)});
 await t.remove();t.state.pendingProjectAction=null;t.state.job++;t.state.busy=true;fire();
 assert.equal(t.state.busy,true);assert.deepEqual(actions,[['deleteProject','original']]);assert.equal(t.calls.messages.length,0);
});


test('a deleting target is save-fenced while another current project remains saveable',async()=>{
 const writes=[],state={deletingProjectId:'deleting',project:{id:'deleting',name:'Held'},projects:[],settings:{}};
 const context={state,backgroundActive:()=>false,clone:value=>JSON.parse(JSON.stringify(value)),projectJson:()=>({settings:state.settings}),localStorage:{setItem(){}},native:()=>false,dbPut:async(...args)=>writes.push(args),document:{dispatchEvent(){}},CustomEvent:class{},toast(){}};
 vm.createContext(context);vm.runInContext(extract('saveProject','function captureSnapshot('),context);
 assert.equal(await context.saveProject(),true);assert.equal(writes.length,0);
 state.project={id:'other',name:'Other'};assert.equal(await context.saveProject(),true);assert.equal(writes.length,1);assert.equal(writes[0][1],'other');
});
test('deletion retires pending load and composition before storage yields and releases its save fence on failure',async()=>{
 const deletion=deferred(),aborted=[],t=deletionHarness({regenTimer:0,document:{querySelector:()=>({inert:true})},dbDeleteProject:()=>deletion.promise});
 t.state.project=t.state.projects[0];t.state.loadingProject=true;t.state.selection=3;t.state.compileId=2;t.state.composing=true;t.state.compileAbort={abort:()=>aborted.push('compile')};t.state.projectReadAbort={abort:()=>aborted.push('read')};
 const pending=t.remove();await new Promise(setImmediate);
 assert.equal(t.state.deletingProjectId,'original');assert.equal(t.state.loadingProject,false);assert.equal(t.state.saveBlocked,true);assert.equal(t.state.composing,false);assert.equal(t.state.selection,4);assert.equal(t.state.compileId,3);assert.deepEqual(aborted,['read','compile']);
 deletion.reject(Error('Delete interrupted'));await pending;
 assert.equal(t.state.deletingProjectId,null);assert.equal(t.state.projects.length,1);assert.equal(t.state.project.id,'original');assert.equal(t.state.busy,false);
});
