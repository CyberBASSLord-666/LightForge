'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const release=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../version.json'),'utf8')).name;
const harness=path.resolve(__dirname,`../qa/release-${release}/browser.cjs`);
const source=fs.readFileSync(harness,'utf8');
function helpers(extra={}){
 const safeRequire=name=>(name==='node:fs'||name==='fs')?{...fs,writeFileSync(){},renameSync(){},existsSync(){return false;}}:require(name);
 const context={require:safeRequire,process:{pid:123},__dirname:path.dirname(harness),...extra};
 vm.runInNewContext(source.slice(0,source.indexOf('\n(async()=>{'))+'\nglobalThis.api={recordApplicationDiagnostics,captureApplicationDiagnostics,captureVisibleScore,DIAGNOSTIC_LIMITS};',context,{filename:harness});
 return context.api;
}
const error='2026-10-23T18:21:41.000Z ERROR [app] A handled application failure';

test('retains handled application errors without pageerror and ignores unrelated payloads',()=>{
 const {recordApplicationDiagnostics}=helpers(),receipt={};
 recordApplicationDiagnostics(receipt,'workspace-review',{report:'LightForge diagnostic log\n'+error+'\n',recoveryVisible:true,project:{name:'PRIVATE PROJECT'},music:{data:'PRIVATE MUSIC'}});
 assert.equal(receipt.applicationDiagnostics.hasUnexpectedErrors,true);
 assert.equal(receipt.applicationDiagnostics.checkpoints[0].errorCount,1);
 assert.equal(receipt.applicationDiagnostics.checkpoints[0].recoveryVisible,true);
 assert.equal(receipt.applicationDiagnostics.unexpectedErrors[0].phase,'workspace-review');
 assert.equal(receipt.applicationDiagnostics.unexpectedErrors[0].message,error);
 assert.doesNotMatch(JSON.stringify(receipt),/PRIVATE PROJECT|PRIVATE MUSIC/);
 recordApplicationDiagnostics(receipt,'guide',{report:error,recoveryVisible:true});
 assert.equal(receipt.applicationDiagnostics.unexpectedErrors.length,1,'repeated reports must not duplicate an error');
});

test('checks the whole sanitized report for errors before truncating retained excerpts',()=>{
 const {recordApplicationDiagnostics,DIAGNOSTIC_LIMITS:limits}=helpers(),receipt={};
 recordApplicationDiagnostics(receipt,'final',{report:error+'\n'+'x'.repeat(limits.reportChars+20),recoveryVisible:true});
 const diagnostics=receipt.applicationDiagnostics;
 assert.equal(diagnostics.hasUnexpectedErrors,true);
 assert.equal(diagnostics.checkpoints[0].reportTruncated,true);
 assert.equal(diagnostics.checkpoints[0].report.length,limits.reportChars);
 assert.equal(diagnostics.unexpectedErrors[0].message,error);
 assert.doesNotMatch(diagnostics.checkpoints[0].report,/ERROR/);
});

test('retained checkpoints, phase text, report text and error summaries have fixed caps',()=>{
 const {recordApplicationDiagnostics,DIAGNOSTIC_LIMITS:limits}=helpers(),receipt={};
 const report=Array.from({length:40},(_,i)=>`2026-10-23T18:21:41.000Z ERROR [app] Error ${i} `+'x'.repeat(2000)).join('\n');
 for(let i=0;i<40;i++)recordApplicationDiagnostics(receipt,'p'.repeat(100),{report,recoveryVisible:true});
 const diagnostics=receipt.applicationDiagnostics;
 assert.equal(diagnostics.checkpoints.length,limits.checkpoints);
 assert.equal(diagnostics.checkpointOverflow,true);
 assert.equal(diagnostics.unexpectedErrors.length,limits.errors);
 for(const entry of diagnostics.checkpoints){assert.equal(entry.phase.length,64);assert.equal(entry.report.length,limits.reportChars);}
 for(const entry of diagnostics.unexpectedErrors)assert.equal(entry.message.length,limits.errorChars);
 assert.ok(JSON.stringify(diagnostics).length<100000);
});

test('missing sanitized diagnostics fails closed, while info/warning text is not an error',()=>{
 const {recordApplicationDiagnostics}=helpers(),receipt={};
 assert.throws(()=>recordApplicationDiagnostics(receipt,'missing',{}),/unavailable/);
 recordApplicationDiagnostics(receipt,'ready',{report:'2026-10-23T18:21:41Z INFO [app] No ERROR log entry\n2026-10-23T18:21:42Z WARN [app] Expected warning',recoveryVisible:false});
 assert.equal(receipt.applicationDiagnostics.hasUnexpectedErrors,false);
 assert.equal(receipt.applicationDiagnostics.checkpoints[0].errorCount,0);
});

test('page capture reads only the existing sanitized report and recovery visibility',async()=>{
 const receiptPath=path.join(path.dirname(harness),'browser-verification.json');
 const before=fs.existsSync(receiptPath)?fs.readFileSync(receiptPath):null;
 const {captureApplicationDiagnostics}=helpers({window:{LightForgeDiagnostics:{report:()=>error}},document:{getElementById:id=>{assert.equal(id,'diagnosticRecovery');return {hidden:false};}}});
 const receipt={};await captureApplicationDiagnostics({evaluate:fn=>fn()},receipt,'guide');
 assert.equal(receipt.applicationDiagnostics.unexpectedErrors[0].message,error);
 const after=fs.existsSync(receiptPath)?fs.readFileSync(receiptPath):null;
 assert.deepEqual(after,before,'helper unit tests must never write the real browser receipt');
});

test('score capture waits for visibility, matching DPR dimensions and two frames before screenshot',async()=>{
 const events=[];let visible=false;
 const canvas={width:338,height:154,clientWidth:736,clientHeight:154,getBoundingClientRect:()=>({top:visible?100:1500,bottom:visible?254:1654})};
 const {captureVisibleScore}=helpers({devicePixelRatio:1,innerHeight:960,document:{getElementById:id=>{assert.equal(id,'scoreCanvas');return canvas;}},requestAnimationFrame:fn=>{events.push('frame');fn();}});
 const page={locator:selector=>({scrollIntoViewIfNeeded:async()=>{assert.equal(selector,'#scoreCanvas');events.push('scroll');visible=true;},screenshot:async options=>{assert.equal(selector,'#scoreTimeline');assert.match(options.path,/score-1440\.png$/);assert.equal(options.animations,'disabled');events.push('screenshot');}}),waitForFunction:async(fn,arg,options)=>{assert.equal(options.timeout,10000);assert.equal(fn(),false,'stale backing dimensions must not pass');canvas.width=736;assert.equal(fn(),true);events.push('dimensions-match');},evaluate:fn=>fn()};
 const result=await captureVisibleScore(page,1440);
 assert.deepEqual(events,['scroll','dimensions-match','frame','frame','screenshot']);
 assert.equal(result.intrinsicWidth,736);assert.equal(result.cssWidth,736);assert.equal(result.viewportWidth,1440);
});

test('diagnostic evidence is persisted before the fail-closed assertion and before page cleanup',()=>{
 const save=source.indexOf('writeJsonAtomic(output,receipt);',source.indexOf("await captureApplicationDiagnostics(page,receipt,'final')"));
 const fail=source.indexOf('assert.equal(receipt.applicationDiagnostics.hasUnexpectedErrors,false');
 assert.ok(save>=0&&save<fail);
 assert.ok(source.indexOf("captureApplicationDiagnostics(fresh,receipt,'first-launch')")<source.indexOf('await fresh.close()'));
 assert.match(source,/captureApplicationDiagnostics\(page,receipt,'failure'\)/);
 assert.match(source,/assert\.deepEqual\(errors,\[\]\);assert\.deepEqual\(hashes\(\),receipt.source_hashes\)/);
 assert.doesNotMatch(source,/dismissDiagnosticRecovery.*click|LightForgeDiagnostics[^\n]*clear/);
 assert.doesNotMatch(source,/text:document\.body\.innerText|project:LightForgeApp\.state\.project/);
 const capture=source.slice(source.indexOf('async function captureApplicationDiagnostics'),source.indexOf('async function captureVisibleScore'));
 assert.match(capture,/recordApplicationDiagnostics\(receipt,phase,snapshot\);\s*writeJsonAtomic\(output,receipt\)/);
});

test('the aggregate gate registers diagnostic capture and the source inventory binds its harness',()=>{
 const gate=fs.readFileSync(path.resolve(__dirname,'../tools/verify_v2.py'),'utf8');
 assert.equal((gate.match(/'browser-diagnostic-capture\.test\.cjs'/g)||[]).length,1);
 const inventory=JSON.parse(fs.readFileSync(path.join(path.dirname(harness),'browser-source-inventory.json'),'utf8'));
 assert.ok(inventory.browser.includes(`qa/release-${release}/browser.cjs`));
});

test('a visible unexpected recovery banner cannot pass when earlier errors fell out of the application ring',()=>{
 const {recordApplicationDiagnostics}=helpers(),receipt={};
 recordApplicationDiagnostics(receipt,'guide',{report:'2026-10-23T18:21:41Z INFO [app] Later work',recoveryVisible:true});
 assert.equal(receipt.applicationDiagnostics.hasUnexpectedErrors,false);
 assert.equal(receipt.applicationDiagnostics.hasUnexpectedRecovery,true);
 recordApplicationDiagnostics(receipt,'final',{report:'2026-10-23T18:21:42Z INFO [app] Later work',recoveryVisible:false});
 assert.equal(receipt.applicationDiagnostics.hasUnexpectedRecovery,true);
 assert.match(source,/assert\.equal\(receipt\.applicationDiagnostics\.hasUnexpectedRecovery,false/);
});
