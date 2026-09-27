'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const Quality=require('../web/engine/choreography-quality.js');

function expectedRuns(rows){
  const result=[];
  for(let i=0;i<rows.length;){
    const start=i,state=JSON.stringify(rows[i]);
    while(++i<rows.length&&JSON.stringify(rows[i])===state){}
    if(rows[start].some(Boolean))result.push({start:start*20/1000,end:i*20/1000});
  }
  return result;
}

test('duration diagnostics preserve all multi-channel runs including zero components and final-frame changes',()=>{
  const patterns=[
    [[0,0,0]],[[63,0,0]],[[0,0,0],[0,0,63]],
    [[1,2,3],[1,2,3],[1,2,0],[1,2,0],[0,0,0],[0,2,0]],
    Array.from({length:4000},()=>[0,0,0]),
    Array.from({length:4000},()=>[0,255,0]),
    Array.from({length:4000},(_,i)=>[i%2?63:191,i%3?0:255,i%7])
  ];
  for(const rows of patterns){
    const show={channels:4,frameCount:rows.length,stepMs:20,frames:Uint8Array.from(rows.flatMap(row=>[...row,0])),settings:{}};
    const profile={id:'run-scan',outputs:[{id:'group',kind:'closure',channels:[1,2,3],commandLimit:1}]};
    const report=Quality.evaluate(show,{profile,minimumDurationMs:1000000,minimumRepeatIntervalMs:1000000});
    const result=report.minimumDurations.outputs[0],expected=expectedRuns(rows);
    assert.equal(result.observedCommandCount,expected.length);
    assert.equal(result.minimumDurationViolationCount,expected.length);
    assert.deepEqual(result.minimumDurationViolations.map(({start,end})=>[start,end]),expected.map(({start,end})=>[start,end]));
    assert.equal(result.repeatIntervalViolationCount,Math.max(0,expected.length-1));
    assert.deepEqual(Array.from(show.frames),rows.flatMap(row=>[...row,0]));
  }
});
