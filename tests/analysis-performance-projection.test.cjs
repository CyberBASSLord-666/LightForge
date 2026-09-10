'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const Performance=require('../qa/release-2.2.4/analysis-performance.cjs');

function engine(overrides={}){
  return {
    name:'Beat This! full + Deux + GAME Large',modelId:'beat-this-final0',quality:'precision',
    runtime:'ONNX Runtime Web 1.20.1',recoverable:false,analysisSeconds:12.3456789,
    stages:{rhythm:{seconds:1.25,restored:false},separation:{seconds:10.5,restored:true},voice:{seconds:.5,restored:false}},
    separation:{modelId:'mel-band-roformer-deux-lightforge-2',runtime:'onnxruntime-web-wasm',chunks:3,restoredPassages:2},
    ...overrides
  };
}

test('projects bounded stage/cache/profile timing without a performance threshold',()=>{
  const value=Performance.build(engine(),13.87654321);
  assert.deepEqual(value,{
    schemaVersion:1,totalWallClockSeconds:13.876543,analyzerReportedSeconds:12.345679,
    stages:{rhythm:{seconds:1.25,restored:false},separation:{seconds:10.5,restored:true},voice:{seconds:.5,restored:false}},
    cache:{restoredStageCount:1,restoredStageNames:['separation'],separationRestoredPassages:2},
    profile:{name:'Beat This! full + Deux + GAME Large',modelId:'beat-this-final0',quality:'precision',
      runtime:'ONNX Runtime Web 1.20.1',recoverable:false,
      separation:{modelId:'mel-band-roformer-deux-lightforge-2',runtime:'onnxruntime-web-wasm',chunks:3,restoredPassages:2}}
  });
  assert.equal(Performance.validate(value),true);
});

test('rejects nonfinite or malformed timing/cache inputs before receipt publication',()=>{
  assert.throws(()=>Performance.build(engine({analysisSeconds:Infinity}),1),/analyzer reported seconds/);
  assert.throws(()=>Performance.build(engine({stages:{rhythm:{seconds:1,restored:'yes'}}}),1),/restoration state/);
  assert.throws(()=>Performance.build(engine({separation:{modelId:'m',runtime:'r',chunks:1.5,restoredPassages:0}}),1),/chunk count/);
  const value=Performance.build(engine(),1);
  value.cache.restoredStageNames=['rhythm'];
  assert.throws(()=>Performance.validate(value),/restored-stage summary/);
});

test('the browser proof source-binds and emits the performance projection',()=>{
  const browser=fs.readFileSync(path.join(__dirname,'../qa/release-2.2.4/analysis-browser.cjs'),'utf8');
  assert.match(browser,/require\('\.\/analysis-performance\.cjs'\)/);
  assert.match(browser,/qa\/release-2\.2\.4\/analysis-performance\.cjs/);
  assert.match(browser,/AnalysisPerformance\.build\(result\.music\.engine,analysisWallClockSeconds\)/);
  assert.match(browser,/performance};receipt\.checks\.push/);
});
