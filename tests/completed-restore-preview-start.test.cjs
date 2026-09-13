'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

const root=process.env.LIGHTFORGE_ROOT||path.join(__dirname,'..');
const app=fs.readFileSync(process.env.LIGHTFORGE_APP_SOURCE||path.join(root,'web/app.js'),'utf8');
const monitor=fs.readFileSync(process.env.LIGHTFORGE_MONITOR_SOURCE||path.join(root,'android/src/com/cyberbasslord/lightforge/CompletedRestoreMonitor.java'),'utf8');

test('completed restore arms an explicit preview-starting pulse before releasing deferred WebGL startup',()=>{
 const adopted=app.indexOf("completedRestorePulse(restoreLease,'show-adopted')");
 const starting=app.indexOf("completedRestorePulse(restoreLease,'preview-starting')");
 const release=app.indexOf('setCompletedRestorePreviewDeferred(false);',adopted);
 assert.ok(adopted>=0&&starting>adopted&&release>starting,'show adoption, preview-starting, and deferred renderer release must be strictly ordered');
});

test('Android monitor grants only a named bounded preview-startup phase and still requires first render',()=>{
 assert.match(monitor,/PREVIEW_STARTUP_BUDGET_MS=30000L/);
 assert.match(monitor,/"preview-starting"\.equals\(nextPhase\).*previewStarting/s);
 assert.match(monitor,/"preview-first-render"\.equals\(nextPhase\).*\!previewStarting/s);
 assert.match(monitor,/if\("preview-starting"\.equals\(phase\)\)\{[\s\S]*?nextProbeAt=now\+PREVIEW_STARTUP_BUDGET_MS/);
 assert.match(monitor,/if\("preview-starting"\.equals\(phase\)\)return PREVIEW_STARTUP_BUDGET_MS/);
 assert.match(monitor,/terminalSequence<=sequence\|\|!workerStarted\|\|!workerVerified\|\|!showAdopted\|\|!previewFirstRender\|\|!visualCommitted/);
});
