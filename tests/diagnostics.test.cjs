'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {JSDOM}=require('jsdom'),root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'web/diagnostics.js'),'utf8');
const markup=fs.readFileSync(path.join(root,'web/index.html'),'utf8');
function create({native,stored,quota=false}={}){
 const dom=new JSDOM(markup,{url:'https://appassets.androidplatform.net/',runScripts:'outside-only'}),w=dom.window,calls=[];
 w.console={error(){},warn(){}};
 if(stored)w.localStorage.setItem('lightforge-diagnostics-v1',stored);
 if(quota)Object.defineProperty(w,'localStorage',{value:{getItem(){throw Error('Unavailable');},setItem(){throw Error('Quota exceeded');}}});
 if(native)w.Android={logDiagnostic:(...args)=>calls.push(args),exportDiagnostics(){calls.push(['export']);},...native};
 w.LightForgeVersion={name:'2.2.2'};w.eval(source);w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
 return{dom,w,api:w.LightForgeDiagnostics,calls,close:()=>w.close()};
}
test('captures actual script errors, promise rejections and resource failures with bounded original stack context',()=>{
 const t=create({native:{}});try{
  const error=new t.w.Error('Model allocation failed');error.stack='Error: Model allocation failed\n at infer (https://appassets.androidplatform.net/analysis/worker.js:42:8)\n at run (https://appassets.androidplatform.net/analysis/worker.js:91:3)';
  t.w.dispatchEvent(new t.w.ErrorEvent('error',{message:error.message,error}));
  const rejected=new t.w.Event('unhandledrejection');Object.defineProperty(rejected,'reason',{value:new t.w.Error('Checkpoint unavailable')});t.w.dispatchEvent(rejected);
  t.w.document.querySelector('script').dispatchEvent(new t.w.Event('error'));
  const report=t.api.report();assert.match(report,/Model allocation failed/);assert.match(report,/at infer \(analysis\.worker\.js:42:8\)/);assert.match(report,/Checkpoint unavailable/);assert.match(report,/SCRIPT resource failed/);assert.doesNotMatch(report,/appassets\.androidplatform\.net/);
  assert.equal(t.w.document.getElementById('diagnosticRecovery').hidden,false);assert.ok(t.calls.some(x=>x[0]==='error'&&x[1]==='window'));
 }finally{t.close();}
});
test('sanitization excludes credentials, private paths, known names, and raw object or audio payloads',()=>{
 const t=create({native:{}});try{
  t.api.protectText('Private Song Title');
  t.api.log('error','analysis',new t.w.Error('Private Song Title failed for "A Secret Tune" at /storage/emulated/0/Music/private.wav token=secret123 Bearer credential123 sk-testKey123 person@example.com'));
  t.api.log('warn','console',{music:'sensitive lyrics',name:'secret show',pcm:new Uint8Array([1,2,3])});
  t.api.progress('analysis',{stage:'separation Private Song Title',detail:'unredacted private detail',progress:.4,passageIndex:2,passageCount:7,music:{lyrics:'secret lyrics'}});
  const report=t.api.report();assert.doesNotMatch(report,/Private Song Title|A Secret Tune|secret123|credential123|sk-testKey123|person@example.com|storage\/emulated|private.wav|sensitive lyrics|secret show|secret lyrics|unredacted private detail/);
  assert.match(report,/stage=separation progress=40% passageIndex=2 passageCount=7/);assert.match(report,/non-text detail omitted/);
  for(const call of t.calls)assert.equal(call.length,3);
 }finally{t.close();}
});
test('retention and event throttles bound memory, messages and progress even when storage is full',()=>{
 const t=create({quota:true});try{
  let clock=Date.now();t.w.Date.now=()=>clock;
  for(let i=0;i<1000;i++){clock+=1100;t.api.log('info','operation','event '+i+' '+'x'.repeat(6000));}
  let report=t.api.report();assert.ok(report.length<135000);assert.match(report,/event 999/);assert.doesNotMatch(report,/event 0 /);
  for(let i=0;i<200;i++)t.api.progress('analysis',{stage:'separation',progress:i/200,passageIndex:1});
  assert.equal((t.api.report().match(/stage=separation/g)||[]).length,1);
  clock+=15001;t.api.progress('analysis',{stage:'separation',progress:.9,passageIndex:1});assert.equal((t.api.report().match(/stage=separation/g)||[]).length,2);
  for(let i=0;i<10000;i++)t.api.log('warn','app','burst '+i);assert.ok(t.api.report().length<135000);
  assert.doesNotThrow(()=>t.w.dispatchEvent(new t.w.Event('pagehide')));
 }finally{t.close();}
});
test('browser history survives reload and rejects corrupt or oversized persisted history',()=>{
 const first=create();let stored;try{first.api.log('error','analysis',new first.w.Error('Earlier analysis failed'));stored=first.w.localStorage.getItem('lightforge-diagnostics-v1');}finally{first.close();}
 for(const input of [stored,'{broken','x'.repeat(300000)]){
  const t=create({stored:input});try{assert.match(t.api.report(),/Diagnostic capture started/);if(input===stored)assert.match(t.api.report(),/Earlier analysis failed/);}finally{t.close();}
 }
});
test('native export stays pending until actual save acknowledgement and is available during processing',async()=>{
 const t=create({native:{}});try{
  t.w.document.getElementById('processing').hidden=false;
  const button=t.w.document.querySelector('#processing [data-export-diagnostics]');button.click();
  assert.equal(t.calls.filter(x=>x[0]==='export').length,1);assert.equal(button.disabled,true);
  assert.match(t.w.document.querySelector('#processing [data-diagnostic-status]').textContent,/Preparing your log/);
  assert.doesNotMatch(t.w.document.querySelector('#processing [data-diagnostic-status]').textContent,/Saved/);
  const result=t.api.exportLog();let resolved=false;result.then(()=>resolved=true);await Promise.resolve();assert.equal(resolved,false);
  t.w.onNativeEvent('diagnosticExported',JSON.stringify({name:'LightForge-diagnostics.log',location:'Downloads/LightForge',uri:'content://media/external/downloads/1',bytes:1000}));
  const file=await result;assert.equal(file.bytes,1000);assert.equal(button.disabled,false);assert.equal(t.w.document.getElementById('processing').hidden,false);
  assert.match(t.w.document.querySelector('#processing [data-diagnostic-status]').textContent,/Saved LightForge-diagnostics.log to Downloads\/LightForge/);
  assert.equal(t.calls.filter(x=>x[0]==='export').length,1);
 }finally{t.close();}
});
test('native save failure and picker cancellation restore export controls and allow retry',async()=>{
 const t=create({native:{}});try{
  let pending=t.api.exportLog();const rejected=assert.rejects(pending,/Storage is full/);
  assert.equal(t.api.handleNativeEvent('analysisJob',{}),false);
  t.api.handleNativeEvent('diagnosticExportFailed',{message:'Storage is full'});await rejected;
  assert.ok([...t.w.document.querySelectorAll('[data-export-diagnostics]')].every(x=>!x.disabled));
  assert.match(t.w.document.querySelector('[data-diagnostic-status]').textContent,/Storage is full/);
  pending=t.api.exportLog();const cancelled=assert.rejects(pending,{name:'AbortError'});
  t.api.handleNativeEvent('diagnosticExportFailed',{message:'Cancelled',cancelled:true});await cancelled;
  assert.match(t.w.document.querySelector('[data-diagnostic-status]').textContent,/canceled/);
  assert.equal(t.w.document.querySelector('[data-diagnostic-status]').classList.contains('diagnostic-error'),false);
  assert.equal(t.calls.filter(x=>x[0]==='export').length,2);
 }finally{t.close();}
});
test('native bridge invocation failure never claims a saved log or leaves buttons disabled',async()=>{
 const t=create({native:{exportDiagnostics(){throw Error('Bridge disconnected');}}});try{
  await assert.rejects(t.api.exportLog(),/Bridge disconnected/);assert.equal(t.w.document.querySelector('[data-export-diagnostics]').disabled,false);
  assert.doesNotMatch(t.w.document.querySelector('[data-diagnostic-status]').textContent,/Saved/);
 }finally{t.close();}
});
test('browser export creates an actual text log download without claiming a verified filesystem save',async()=>{
 const t=create();try{
  let blob,download;t.w.URL.createObjectURL=value=>{blob=value;return'blob:diagnostic-download';};t.w.URL.revokeObjectURL=()=>{};
  t.w.HTMLAnchorElement.prototype.click=function(){download={name:this.download,href:this.href,attached:this.isConnected};};
  t.api.log('error','analysis',new t.w.Error('Failed to resume'));const result=await t.api.exportLog();
  assert.ok(blob instanceof t.w.Blob);assert.match(blob.type,/text\/plain/);assert.ok(blob.size>100);
  assert.match(download.name,/^LightForge-diagnostics-.*\.log$/);assert.equal(download.attached,true);assert.equal(result.requested,true);
  assert.match(t.w.document.querySelector('[data-diagnostic-status]').textContent,/Your browser chooses the download location/);
  assert.doesNotMatch(t.w.document.querySelector('[data-diagnostic-status]').textContent,/Saved/);
 }finally{t.close();}
});
test('diagnostics initialize before application scripts and export controls work if app startup fails',()=>{
 const t=create({native:{}});try{
  const scripts=[...t.w.document.querySelectorAll('script')];assert.equal(scripts[0].getAttribute('src'),'diagnostics.js');assert.equal(scripts[0].hasAttribute('defer'),false);
  assert.equal(t.w.LightForgeApp,undefined);t.w.dispatchEvent(new t.w.ErrorEvent('error',{error:new t.w.Error('Startup failed')}));
  t.w.document.querySelector('#diagnosticRecovery [data-export-diagnostics]').click();assert.equal(t.calls.filter(x=>x[0]==='export').length,1);
  t.api.handleNativeEvent('diagnosticExported',{name:'test.log',location:'Downloads/LightForge'});
  t.w.document.getElementById('dismissDiagnosticRecovery').click();assert.equal(t.w.document.getElementById('diagnosticRecovery').hidden,true);
 }finally{t.close();}
});
test('composition worker failures retain the originating stack and release the worker',async()=>{
 const dom=new JSDOM('<script src="https://app.test/engine/client.js"></script>',{url:'https://app.test/',runScripts:'outside-only'}),w=dom.window;
 try{
  let worker,terminated=false;const calls=[];w.LightForgeVersion={name:'2.2.2'};w.LightForgeDiagnostics={log:(...args)=>calls.push(args)};
  Object.defineProperty(w.document,'currentScript',{value:w.document.querySelector('script')});
  w.Worker=class{constructor(){worker=this;}postMessage(){}terminate(){terminated=true;}};
  w.eval(fs.readFileSync(path.join(root,'web/engine/client.js'),'utf8'));
  const result=w.ShowCompiler.generate({privateData:'music'},{name:'private'});const failure=assert.rejects(result,/Cannot encode/);
  worker.onmessage({data:{type:'error',message:'Cannot encode',stack:'Error: Cannot encode\n at encode (worker.js:12:9)'}});await failure;
  assert.equal(terminated,true);assert.ok(calls.some(x=>x[0]==='error'&&x[2].stack.includes('worker.js:12:9')));
  assert.doesNotMatch(calls.map(x=>String(x[2])).join('\n'),/privateData|private/);
 }finally{w.close();}
});
