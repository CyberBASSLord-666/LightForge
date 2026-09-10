'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const Routing=require('../web/analysis/stem-routing.js');

const key='stem-12345678-1234-1234-1234-123456789abc';
const legacyAnalysis=()=>({stemCache:{key},separation:{modelId:'deux-test-model'}});

test('legacy vocal/accompaniment stems stay distinct and do not invent drum or bass stems',()=>{
 const analysis=legacyAnalysis(),before=JSON.parse(JSON.stringify(analysis)),contract=Routing.fromAnalysis(analysis);
 assert.deepEqual(analysis,before);
 assert.equal(Routing.validate(contract).valid,true);
 assert.deepEqual(contract.stems.map(stem=>[stem.role,stem.origin,stem.provenance.isolationEvidence]),[
  ['accompaniment','legacy-separated','pipeline-separated'],
  ['combined-vocals','legacy-separated','pipeline-separated']
 ]);
 assert.equal(Routing.route(contract,'vocal-transcription').selected.role,'combined-vocals');
 assert.equal(Routing.route(contract,'bass-analysis').routeKind,'fallback-accompaniment-mixture');
 assert.equal(Routing.route(contract,'harmonic-analysis').routeKind,'fallback-accompaniment-mixture');
 assert.equal(Routing.route(contract,'drum-analysis').status,'unavailable');
 assert.equal(contract.stems.some(stem=>['lead-vocals','backing-vocals','drums','bass','harmonic'].includes(stem.role)),false);
});

test('externally supplied semantic stems select their own task routes with provenance and confidence',()=>{
 const contract=Routing.build({semanticStems:[
  {id:'lead-low',role:'lead-vocals',audioRef:'external://lead-low',clock:'original-decoded-audio',confidence:.55,provenance:{source:'annotated-lead',isolationEvidence:'declared'}},
  {id:'lead-high',role:'lead-vocals',audioRef:'external://lead-high',clock:'original-decoded-audio',confidence:.93,provenance:{source:'annotated-lead',model:'lead-model-v2',isolationEvidence:'verified'}},
  {id:'backing',role:'backing-vocals',audioRef:'external://backing',clock:'original-decoded-audio',confidence:.8,provenance:{source:'annotated-backing',isolationEvidence:'declared'}},
  {id:'drums',role:'drums',audioRef:'external://drums',clock:'original-decoded-audio',confidence:.9,provenance:{source:'drum-model',isolationEvidence:'declared'}},
  {id:'bass',role:'bass',audioRef:'external://bass',clock:'original-decoded-audio',confidence:.86,provenance:{source:'bass-model',isolationEvidence:'verified'}},
  {id:'harmonic',role:'harmonic',audioRef:'external://harmonic',clock:'original-decoded-audio',confidence:.84,provenance:{source:'harmonic-model',isolationEvidence:'unknown'}}
 ]});
 assert.equal(Routing.validate(contract).valid,true);
 assert.equal(Routing.route(contract,'vocal-transcription').selected.id,'lead-high');
 assert.equal(Routing.route(contract,'vocal-activity').selected.id,'lead-high');
 assert.equal(Routing.route(contract,'backing-vocal-analysis').selected.id,'backing');
 const drums=Routing.route(contract,'drum-analysis');assert.equal(drums.selected.id,'drums');assert.equal(drums.routeKind,'supplied-semantic-stem');assert.equal(drums.selected.provenance.isolationEvidence,'declared');
 assert.equal(Routing.route(contract,'bass-analysis').selected.id,'bass');
 assert.equal(Routing.route(contract,'harmonic-analysis').selected.id,'harmonic');
});

test('missing, mistimed, unsupported, and duplicate semantic descriptors are rejected instead of routed',()=>{
 const contract=Routing.build({semanticStems:[
  {id:'no-ref',role:'drums',clock:'original-decoded-audio',confidence:.9,provenance:{source:'drum-model',isolationEvidence:'declared'}},
  {id:'wrong-clock',role:'bass',audioRef:'external://bass',clock:'resampled-audio',confidence:.9,provenance:{source:'bass-model',isolationEvidence:'verified'}},
  {id:'unsupported',role:'accompaniment',audioRef:'external://other',clock:'original-decoded-audio',confidence:.9,provenance:{source:'other',isolationEvidence:'declared'}},
  {id:'duplicate',role:'drums',audioRef:'external://one',clock:'original-decoded-audio',confidence:.2,provenance:{source:'drum-model',isolationEvidence:'declared'}},
  {id:'duplicate',role:'drums',audioRef:'external://two',clock:'original-decoded-audio',confidence:.95,provenance:{source:'drum-model',isolationEvidence:'declared'}}
 ]});
 assert.equal(Routing.validate(contract).valid,true);
 assert.equal(contract.stems.length,1);
 assert.equal(contract.stems[0].id,'duplicate');
 assert.equal(Routing.route(contract,'drum-analysis').selected.id,'duplicate');
 assert.ok(contract.diagnostics.rejected.some(item=>item.reason==='missing-audio-ref'));
 assert.ok(contract.diagnostics.rejected.some(item=>item.reason==='clock-must-match-original-decoded-audio'));
 assert.ok(contract.diagnostics.rejected.some(item=>item.reason==='role-must-be-a-supported-external-semantic-stem'));
 assert.ok(contract.diagnostics.rejected.some(item=>item.reason==='duplicate-stem-id'));
});

test('absence of semantic stems remains deterministic and does not alter legacy analysis objects',()=>{
 const empty=Routing.build(),again=Routing.build();
 assert.deepEqual(empty,again);
 assert.equal(empty.stems.length,0);
 assert.equal(Routing.route(empty,'drum-analysis').status,'unavailable');
 const noSeparation={stemCache:{key},separation:null};
 assert.deepEqual(Routing.fromAnalysis(noSeparation),empty);
 const invalid=Routing.fromAnalysis({stemCache:{key:'not-a-cache-key'},separation:{}});
 assert.deepEqual(invalid,empty);
});


test('ensureAnalysis adds only missing or invalid routing metadata without changing analysis schema',()=>{
 const analysis=legacyAnalysis();analysis.analysisVersion=8;
 const before=JSON.parse(JSON.stringify(analysis)),first=Routing.ensureAnalysis(analysis);
 assert.equal(first.rebuilt,true);
 assert.equal(analysis.analysisVersion,8);
 assert.deepEqual({...analysis,stemRouting:undefined},{...before,stemRouting:undefined});
 assert.equal(Routing.validate(analysis.stemRouting).valid,true);
 const saved=analysis.stemRouting,second=Routing.ensureAnalysis(analysis);
 assert.equal(second.rebuilt,false);
 assert.equal(second.routing,saved);
 analysis.stemRouting={schemaVersion:99};
 const repaired=Routing.ensureAnalysis(analysis);
 assert.equal(repaired.rebuilt,true);
 assert.equal(Routing.validate(analysis.stemRouting).valid,true);
});
