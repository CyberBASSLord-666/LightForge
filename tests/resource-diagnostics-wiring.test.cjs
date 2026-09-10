'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.join(__dirname,'..');
const read=file=>fs.readFileSync(path.join(root,file),'utf8');

test('resource diagnostics is loaded before telemetry and forwarded only as an optional observer',()=>{
 const worker=read('web/analysis/worker.js'),store=read('web/analysis/work-store.js'),features=read('web/analysis/feature-store.js');
 assert.match(worker,/importScripts\('diagnostic-clock\.js','resource-diagnostics\.js','telemetry\.js'/);
 assert.match(worker,/resourceDiagnostics:telemetry\.resource/);
 assert.match(worker,/reusableRhythmFeatures\(options,config,telemetry\.resource\)/);
 assert.match(store,/resourceDiagnostics=null/);
 assert.match(store,/resourceDiagnostics\.io\('read'|resourceDiagnostics\.io\(direction/);
 assert.match(features,/open\(identity,\{resourceDiagnostics=null\}=\{\}\)/);
 // Resource evidence is observational: timing hardening must never become a
 // choreography or sequence-generation input, preserving default FSEQ bytes.
 const executableWorker=worker.replace(/\/\*[\s\S]*?\*\/|\/\/[^\n]*/g,'');
 assert.doesNotMatch(executableWorker,/FSEQ|ShowEngine|SequenceCompiler/);
});

test('main-thread aggregation and public page load order preserve the measurement-only boundary',()=>{
 const analyzer=read('web/analysis/analyzer.js'),page=read('web/index.html');
 assert.match(analyzer,/function resourceDiagnostics\(timings,scheduler,totalWallClockMs\)/);
 assert.match(analyzer,/value\.engine\.resourceDiagnostics=resources/);
 assert.ok(page.indexOf('analysis/resource-diagnostics.js')<page.indexOf('analysis/analyzer.js'));
 const executableAnalyzer=analyzer.replace(/\/\*[\s\S]*?\*\/|\/\/[^\n]*/g,'');
 assert.doesNotMatch(executableAnalyzer,/ShowCompiler|FSEQ|frames/);
});
