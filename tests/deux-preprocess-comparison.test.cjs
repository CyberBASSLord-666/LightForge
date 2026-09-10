'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path');
const {compareBytes,validateReport,sameBinding}=require(path.resolve(__dirname,'../tools/compare_deux_preprocess_reuse.cjs'));

function report(enabled,{recovery=false}={}){
 return {passed:true,sourceSHA256:'source',fixtureSHA256:'fixture',fixtureProvenance:{path:'benchmark/provenance.json',sha256:'fixture-proof',schema:'lightforge.deux-benchmark-fixture.v1'},manifestSHA256:'manifest',model:{checkpointSHA256:'model'},source_hashes:{'web/analysis/separator-deux.js':'source','tools/benchmark_deux_runtime.cjs':'benchmark'},threads:4,samples:661501,mode:{spectrumReuse:{enabled},coldProcess:true,filesystemCache:{state:'uncontrolled',strictColdIo:false},thermalState:{available:false}},result:{chunks:3,preprocessing:{spectrumReuse:{enabled}}},runtime:{ortWebVersion:'1.20.1',sessionConfiguration:{executionProviders:['wasm'],graphOptimizationLevel:'all',enableCpuMemArena:false,enableMemPattern:false}},performanceProfile:{resources:{cpuTimeMs:{available:false}},counters:{'transform.frames.reused':enabled?795:0}},...(recovery?{recovery:{controlledInterruption:true,restoredPassages:1}}:{})};
}

test('paired preprocessing comparison fails closed on a single changed byte',()=>{
 assert.deepEqual(compareBytes(Buffer.from([1,2,3]),Buffer.from([1,2,3])),{byteIdentical:true,byteLengthLeft:3,byteLengthRight:3,firstDifferentByte:null});
 const mismatch=compareBytes(Buffer.from([1,2,3]),Buffer.from([1,9,3]));
 assert.equal(mismatch.byteIdentical,false);assert.equal(mismatch.firstDifferentByte,1);
 assert.equal(compareBytes(Buffer.from([1]),Buffer.from([1,2])).byteIdentical,false);
});

test('paired gate requires matching bindings, odd multi-passage output and actual reuse',()=>{
 validateReport(report(false),{enabled:false,minPassages:3});
 validateReport(report(true,{recovery:true}),{enabled:true,minPassages:3,recovery:true});
 assert.throws(()=>validateReport({...report(true,{recovery:true}),result:{...report(true).result,chunks:2}},{enabled:true,minPassages:3,recovery:true}),/did not exercise 3 passages/);
 assert.equal(sameBinding(report(false),report(true)),true);
 assert.throws(()=>validateReport({...report(true),samples:661500},{enabled:true,minPassages:3}),/odd final/);
 assert.throws(()=>validateReport({...report(true),performanceProfile:{resources:{cpuTimeMs:{available:false}},counters:{'transform.frames.reused':0}}},{enabled:true,minPassages:3}),/did not reuse/);
 assert.throws(()=>validateReport({...report(true),mode:{...report(true).mode,filesystemCache:{state:'cold',strictColdIo:true}}},{enabled:true,minPassages:3}),/uncontrolled filesystem cache/);
 assert.equal(sameBinding(report(false),{...report(true),threads:1}),false);
 assert.equal(sameBinding(report(false),{...report(true),fixtureProvenance:{...report(true).fixtureProvenance,sha256:'changed'}}),false);
 assert.equal(sameBinding(report(false),{...report(true),source_hashes:{'web/analysis/separator-deux.js':'source','tools/benchmark_deux_runtime.cjs':'changed'}}),false);
 assert.equal(sameBinding(report(false),{...report(true),runtime:{...report(true).runtime,ortWebVersion:'other'}}),false);
});
