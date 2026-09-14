'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const Timeline=require('../web/analysis/semantic-timeline.js');

function fixture(){return {duration:8,beatConfidence:.9,beats:[0,.5,1,1.5,2,2.5,3,3.5],downbeats:[0,2],beatDetails:[{time:0,confidence:.9,barPosition:1,localBpm:120},{time:.5,confidence:.9,barPosition:2,localBpm:120},{time:1,confidence:.9,barPosition:3,localBpm:120},{time:1.5,confidence:.9,barPosition:4,localBpm:120},{time:2,confidence:.9,barPosition:1,localBpm:120}],sections:[{start:0,end:4,energy:.4,label:'verse'},{start:4,end:8,energy:1,label:'chorus'}],phrases:[{start:0,end:2,energy:.5,kind:'phrase'},{start:2,end:4,energy:.9,kind:'phrase'}],onsets:[{time:2,band:'bass',strength:.9}],impacts:[{time:2,strength:1,kind:'drop'}],vocals:{sourceSeparated:true,phrases:[{start:1.98,end:2.8,confidence:.9,strength:.9,kind:'singing'}],notes:[{start:2,end:2.5,confidence:.9,strength:.8,midi:60}],accents:[{time:2,confidence:.9,strength:1,kind:'syllabic-accent'}]},bassNotes:[{start:1.99,end:2.4,confidence:.9,strength:.9,midi:40,frequency:82.4}],bassAnalysis:{sourceSeparated:true,phrases:[{start:1.99,end:2.4,confidence:.8,strength:.8}]}};}
test('timeline preserves source-clock events and exposes cross-stem salience',()=>{const out=Timeline.build(fixture());assert.equal(Timeline.validate(out).valid,true);const accent=out.events.find(x=>x.type==='vocal_accent');assert.equal(accent.rhythm.barPosition,1);assert.ok(accent.relationships.crossStemAgreement>0);assert.ok(out.events.some(x=>x.type==='bass_note'));assert.equal(out.summary.hasSeparatedVocals,true);});
test('timeline reports accompaniment context without falsely claiming an isolated bass stem',()=>{const music=fixture();music.bassAnalysis={source:'separated-accompaniment',sourceSeparated:true,phrases:[{start:1.99,end:2.4,confidence:.8,strength:.8}]};const out=Timeline.build(music),event=out.events.find(x=>x.type==='bass_note');assert.equal(out.schemaVersion,2);assert.equal(out.summary.hasSeparatedBass,false);assert.equal(out.summary.hasSeparatedAccompaniment,true);assert.equal(event.sourceSeparated,false);assert.equal(event.instrumentSeparated,false);assert.equal(event.inputStem,'accompaniment');assert.equal(event.inputStemSeparated,true);});
test('timeline accepts a bass-isolated source only with explicit instrument provenance',()=>{const music=fixture();music.bassAnalysis={source:'isolated-bass-stem',inputStem:'bass',inputStemSeparated:true,instrumentSeparated:true,phrases:[{start:1.99,end:2.4,confidence:.8,strength:.8,instrumentSeparated:true}]};music.bassNotes[0].instrumentSeparated=true;const out=Timeline.build(music),event=out.events.find(x=>x.type==='bass_note');assert.equal(out.summary.hasSeparatedBass,true);assert.equal(out.summary.hasSeparatedAccompaniment,false);assert.equal(event.sourceSeparated,true);assert.equal(event.instrumentSeparated,true);});
test('timeline rejects invalid duration',()=>assert.throws(()=>Timeline.build({duration:0}))); 


test('timeline maps only explicitly supplied dedicated-percussion events',()=>{
 const music=fixture();
 music.percussionAnalysis={source:'unit-drum-model',model:'unit-drum-v1',inputStem:'drums',inputStemSeparated:true,sourceSeparated:true,events:[
  {time:3.5,kind:'fill',duration:.25,confidence:.76,strength:.8},
  {time:.5,kind:'hat',confidence:.72,strength:.45},
  {time:1,kind:'snare',confidence:.84,strength:.9},
  {time:2,kind:'kick',confidence:.94,strength:1},
  {time:2.25,kind:'clap',confidence:.82,strength:.8},
  {time:2.5,kind:'crash',confidence:.88,strength:.95},
  {time:3,kind:'tom',confidence:.8,strength:.74}
 ]};
 const out=Timeline.build(music),percussion=out.events.filter(event=>event.type.startsWith('percussion_'));
 assert.deepEqual(new Set(percussion.map(event=>event.type)),new Set(['percussion_kick','percussion_snare','percussion_clap','percussion_hat','percussion_crash','percussion_tom','percussion_fill']));
 assert.ok(percussion.every(event=>event.analysisSource==='unit-drum-model'&&event.model==='unit-drum-v1'&&event.inputStem==='drums'&&event.inputStemSeparated===true&&event.sourceSeparated===true));
 assert.deepEqual(out.summary.percussion,{status:'supplied',acceptedEventCount:7,kickBassCoincidenceCount:1,source:'unit-drum-model',model:'unit-drum-v1',sourceSeparated:true,inputStem:'drums',inputStemSeparated:true});
 assert.equal(Timeline.validate(out).valid,true);
});

test('timeline does not promote generic onsets or unsupported labels into drum events',()=>{
 const music=fixture();
 music.impacts=[{time:1,kind:'kick',confidence:.99,strength:1}];
 music.onsets=[{time:1,band:'kick',confidence:.99,strength:1}];
 music.percussionAnalysis={source:'unit-drum-model',events:[{time:1,kind:'ride',confidence:.99,strength:1},{time:-1,kind:'kick',confidence:.99,strength:1}]};
 const out=Timeline.build(music);
 assert.equal(out.events.filter(event=>event.source==='drums').length,0);
 assert.equal(out.events.filter(event=>event.type==='kick_bass_coincidence').length,0);
 assert.deepEqual(out.summary.percussion,{status:'no-valid-events',acceptedEventCount:0,kickBassCoincidenceCount:0,source:'unit-drum-model',model:null,sourceSeparated:false,inputStem:null,inputStemSeparated:false});
 assert.equal(Timeline.build(fixture()).summary.percussion,undefined);
});

test('timeline records kick+bass coincidence only from supplied kick and bass-note evidence',()=>{
 const music=fixture();
 music.percussionAnalysis={source:'unit-drum-model',events:[{time:2.02,kind:'kick',confidence:.95,strength:1}]};
 const first=Timeline.build(music),second=Timeline.build(JSON.parse(JSON.stringify(music)));
 assert.deepEqual(first,second);
 const kick=first.events.find(event=>event.type==='percussion_kick'),bass=first.events.find(event=>event.type==='bass_note'),coincidence=first.events.find(event=>event.type==='kick_bass_coincidence');
 assert.ok(kick&&bass&&coincidence);
 assert.deepEqual(coincidence.relationships.kickBass,{kickEventId:kick.id,bassEventId:bass.id,timingOffsetMs:30});
 assert.ok(kick.relationships.kickBassCoincidenceIds.includes(coincidence.id));
 assert.ok(bass.relationships.kickBassCoincidenceIds.includes(coincidence.id));
 assert.ok(coincidence.relationships.coincidentEventIds.includes(kick.id));
 assert.ok(coincidence.relationships.coincidentEventIds.includes(bass.id));
 const withoutNotes=fixture();delete withoutNotes.bassNotes;withoutNotes.percussionAnalysis=music.percussionAnalysis;
 assert.equal(Timeline.build(withoutNotes).events.some(event=>event.type==='kick_bass_coincidence'),false);
});
