'use strict';
const assert=require('node:assert/strict');
const telemetry=require('../web/analysis/telemetry.js');

async function main(){
 const profile=telemetry.create('separation');
 const token=profile.begin('model.initialization');
 profile.end(token,{model:'Deux'});
 profile.cache('stems','hit',{bytes:42});
 profile.increment('passages',2);
 await profile.measureAsync('checkpoint.write',async()=>{});
 const out=profile.snapshot({quality:'precision'});
 assert.equal(out.schemaVersion,1);assert.equal(out.stage,'separation');
 assert.equal(out.cache[0].outcome,'hit');assert.equal(out.counters.passages,2);
 assert.ok(out.totalWallClockMs>=0);assert.equal(out.attributes.quality,'precision');
 assert.ok(out.spanSummary['model.initialization'].count===1);
 console.log('Analysis telemetry contract passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
