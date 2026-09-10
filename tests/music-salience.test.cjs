'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const Timeline=require('../web/analysis/semantic-timeline.js');
const Salience=require('../web/analysis/salience.js');

function fixture(){return {duration:8,beatConfidence:.9,beats:[0,.5,1,1.5,2,2.5,3,3.5,4,4.5,5,5.5,6,6.5,7,7.5],downbeats:[0,2,4,6],beatDetails:[{time:0,confidence:.9,barPosition:1,localBpm:120},{time:.5,confidence:.9,barPosition:2,localBpm:120},{time:1,confidence:.9,barPosition:3,localBpm:120},{time:1.5,confidence:.9,barPosition:4,localBpm:120},{time:2,confidence:.9,barPosition:1,localBpm:120},{time:4,confidence:.9,barPosition:1,localBpm:120}],sections:[{start:0,end:4,energy:.35,label:'verse'},{start:4,end:8,energy:1,label:'chorus'}],phrases:[{start:0,end:2,energy:.4,kind:'phrase'},{start:2,end:4,energy:.9,kind:'phrase'}],onsets:[{time:1,band:'bass',strength:.18},{time:4,band:'bass',strength:.92}],impacts:[{time:4,strength:1,kind:'drop'}],vocals:{sourceSeparated:true,phrases:[{start:3.98,end:4.8,confidence:.98,strength:.95,kind:'singing',word:'never-copy-this'}],notes:[{start:4,end:4.5,confidence:.95,strength:.9,midi:60}],accents:[{time:4,confidence:.98,strength:1,kind:'syllabic-accent'}]},bassNotes:[{start:3.99,end:4.4,confidence:.9,strength:.9,midi:40,frequency:82.4}],bassAnalysis:{sourceSeparated:true,phrases:[{start:3.99,end:4.4,confidence:.8,strength:.8}]}};}
function rhythmFixture(){return {duration:8,beatConfidence:.98,beats:[0,.25,.5,.75,1,1.25,1.5,1.75,2,2.25,2.5,2.75,3,3.25,3.5,3.75,4,4.25,4.5,4.75,5,5.25,5.5,5.75,6,6.25,6.5,6.75,7,7.25,7.5,7.75],downbeats:[0,1,2,3,4,5,6,7],beatDetails:[{time:0,confidence:.98,barPosition:1},{time:.25,confidence:.98,barPosition:2},{time:.5,confidence:.98,barPosition:3},{time:.75,confidence:.98,barPosition:4}],sections:[{start:0,end:4,energy:.7,label:'first'},{start:4,end:8,energy:.9,label:'second'}],phrases:[],onsets:[{time:1,strength:.95,band:'high'},{time:2,strength:.95,band:'high'},{time:3,strength:.95,band:'high'},{time:4,strength:1,band:'high'},{time:5,strength:.95,band:'high'},{time:6,strength:.95,band:'high'}],impacts:[{time:2,strength:.9,kind:'impact'},{time:4,strength:1,kind:'impact'},{time:6,strength:.9,kind:'impact'}],vocals:{phrases:[],notes:[],accents:[]},bassNotes:[],bassAnalysis:{phrases:[]}};}
const eventAt=(timeline,type,time)=>timeline.events.find(event=>event.type===type&&event.time===time);
const salienceFor=(salience,event)=>salience.events.find(value=>value.id===event.id);

test('music salience deterministically ranks existing events without fabricating lyric content',()=>{
 const timeline=Timeline.build(fixture());timeline.events.find(event=>event.type==='vocal_phrase').word='never-copy-this';const before=structuredClone(timeline),first=Salience.build(timeline),second=Salience.build(structuredClone(timeline));
 assert.deepEqual(first,second);assert.deepEqual(timeline,before);assert.equal(Salience.validate(first,timeline).valid,true);assert.equal(first.events.length,timeline.events.length);assert.deepEqual(first.events.map(event=>event.id),timeline.events.map(event=>event.id));assert.equal(first.summary.context.profile,'vocal-led');assert.equal(JSON.stringify(first).includes('never-copy-this'),false);assert.equal(first.events.some(event=>'word'in event||'text'in event),false);
});
test('section transition and cross-stem evidence outrank an isolated low-salience onset',()=>{
 const timeline=Timeline.build(fixture()),out=Salience.build(timeline),transition=salienceFor(out,eventAt(timeline,'section',4)),isolated=salienceFor(out,eventAt(timeline,'onset',1));
 assert.ok(transition.score>isolated.score);assert.ok(transition.rank<isolated.rank);assert.ok(['structural','climax'].includes(transition.tier));assert.equal(out.summary.highlights[0].id,out.summary.topEventIds[0]);
});
test('context profiles adapt from detected evidence and cached output rejects a changed timeline',()=>{
 const vocalTimeline=Timeline.build(fixture()),rhythmTimeline=Timeline.build(rhythmFixture()),vocal=Salience.build(vocalTimeline),rhythm=Salience.build(rhythmTimeline);
 assert.equal(vocal.summary.context.profile,'vocal-led');assert.equal(rhythm.summary.context.profile,'rhythm-led');const changed=structuredClone(vocalTimeline);changed.events[0].confidence=.01;assert.equal(Salience.validate(vocal,changed).valid,false);
});
test('unknown semantic event types remain rankable for future analysis extensions',()=>{
 const timeline=Timeline.build(rhythmFixture()),extended=structuredClone(timeline),event=extended.events.find(value=>value.type==='onset');event.type='drum_hit';event.source='drums';const out=Salience.build(extended);
 assert.equal(Salience.validate(out,extended).valid,true);assert.ok(salienceFor(out,event).score>0);
});
