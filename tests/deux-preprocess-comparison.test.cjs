'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),crypto=require('node:crypto'),{spawnSync}=require('node:child_process');
const {compareBytes,validateReport,sameBinding,createEvidenceState}=require(path.resolve(__dirname,'../tools/compare_deux_preprocess_reuse.cjs'));

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

test('resumable exactness state commits only complete hash-bound arms and rejects altered or incomplete state',()=>{
 const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'lightforge-deux-evidence-state-'));
 const implementation=path.resolve(__dirname,'../web/analysis/separator-deux.js');
 const binding={schema:'lightforge.deux-preprocess-evidence-binding.v1',comparatorSHA256:'comparator',benchmarkSHA256:'benchmark',implementationSHA256:'source',modelManifestSHA256:'manifest',analysisAssetManifestSHA256:'assets',fixtureSHA256:'fixture',fixtureProvenanceSHA256:'fixture-proof',invocation:{threads:4,total:5,minPassages:3,verifyRecovery:true},checkout:{commit:'a'.repeat(40),tree:'b'.repeat(40)},assetInventory:{sha256:'inventory'}};
 try{
  const state=createEvidenceState(temporary,binding),staging=state.stage('cold-baseline'),stored=report(false);
  stored.samples=5;stored.fixtureProvenance={path:'benchmark/provenance.json',sha256:'fixture-proof',schema:'lightforge.deux-benchmark-fixture.v1'};
  fs.writeFileSync(path.join(staging,'report.json'),JSON.stringify(stored));
  for(const [index,role] of ['vocals','accompaniment'].entries())fs.writeFileSync(path.join(staging,'pcm-'+role+'.f32'),Buffer.from(new Float32Array([index,1,2,3,4]).buffer));
  state.commit('cold-baseline',staging,{enabled:false,recoveryAfter:0,report:stored,implementation});
  const loaded=state.load('cold-baseline',{enabled:false,minPassages:3,recovery:false,recoveryAfter:0,implementation});
  assert.equal(loaded.resumed,true);assert.equal(loaded.report.samples,5);assert.match(loaded.completion.report.sha256,/^[0-9a-f]{64}$/);assert.match(loaded.completion.pcm.vocals.sha256,/^[0-9a-f]{64}$/);
  const incomplete=path.join(temporary,'arms','cold-candidate');fs.mkdirSync(incomplete,{recursive:true});
  assert.throws(()=>state.load('cold-candidate',{enabled:true,minPassages:3,recovery:false,recoveryAfter:0,implementation}),/incomplete/);
  fs.rmSync(incomplete,{recursive:true,force:true});
  assert.throws(()=>createEvidenceState(temporary,{...binding,fixtureSHA256:'different'}),/does not exactly match/);
  const reportPath=path.join(temporary,'arms','cold-baseline','report.json'),originalReport=fs.readFileSync(reportPath);
  fs.writeFileSync(reportPath,Buffer.concat([originalReport,Buffer.from('\n')]));
  assert.throws(()=>state.load('cold-baseline',{enabled:false,minPassages:3,recovery:false,recoveryAfter:0,implementation}),/report hash changed/);
  fs.writeFileSync(reportPath,originalReport);
  fs.writeFileSync(path.join(temporary,'arms','cold-baseline','pcm-vocals.f32'),Buffer.from(new Float32Array([9,1,2,3,4]).buffer));
 assert.throws(()=>state.load('cold-baseline',{enabled:false,minPassages:3,recovery:false,recoveryAfter:0,implementation}),/PCM changed/);
 }finally{fs.rmSync(temporary,{recursive:true,force:true});}
});

test('resumed full-arm receipt rehashes PCM and cannot become timing acceptance evidence',()=>{
 const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'lightforge-deux-resume-integration-')),repository=path.resolve(__dirname,'..'),implementation=path.join(repository,'web/analysis/separator-deux.js'),analysis=path.join(temporary,'analysis'),models=path.join(analysis,'models/deux'),assetManifest=path.join(analysis,'ASSET_MANIFEST.json'),benchmark=path.join(temporary,'fake-benchmark.cjs'),fixture=path.join(temporary,'fixture.wav'),provenance=path.join(temporary,'provenance.json'),checkout=path.join(temporary,'checkout.json'),inventory=path.join(temporary,'inventory.json'),stateDirectory=path.join(temporary,'state'),counter=path.join(temporary,'calls.txt'),firstOutput=path.join(temporary,'first.json'),secondOutput=path.join(temporary,'second.json'),corruptOutput=path.join(temporary,'corrupt.json');
 const hash=value=>crypto.createHash('sha256').update(fs.readFileSync(value)).digest('hex'),separatorPath=path.relative(repository,implementation),assetPath=path.relative(repository,assetManifest),modelManifest=path.join(models,'manifest.json');
 try{
  fs.mkdirSync(models,{recursive:true});fs.writeFileSync(path.join(models,'manifest.json'),'{}');fs.writeFileSync(assetManifest,'{}');
  fs.writeFileSync(fixture,Buffer.from([1,2,3,4,5]));fs.writeFileSync(provenance,JSON.stringify({fixture:'licensed-test'}));
  fs.writeFileSync(checkout,JSON.stringify({schema:'lightforge.deux-checkout-identities.v1',commit:'a'.repeat(40),tree:'b'.repeat(40),files:{[separatorPath]:{gitBlobSha1:'c'.repeat(40),sha256:hash(implementation)},[assetPath]:{gitBlobSha1:'d'.repeat(40),sha256:hash(assetManifest)}}}));
  fs.writeFileSync(inventory,JSON.stringify({schema:'lightforge.analysis-asset-manifest.v1',scope:'deux',upToDate:true,generatedManifestSha256:hash(assetManifest),actualManifestSha256:hash(assetManifest),graphInventory:{matches:true,requiredGraphCount:27,manifestGraphCount:27,actualGraphCount:27,boundGraphCount:27},assetCount:27,allowedAssetPaths:[]}));
  fs.writeFileSync(benchmark,"'use strict';const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');const argv=process.argv.slice(2),options={};for(let i=0;i<argv.length;i+=2)options[argv[i].slice(2)]=argv[i+1];const hash=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'),samples=Number(options['total-samples']),enabled=options['spectrum-reuse']==='on',recovery=Boolean(options['recover-after-chunks']),root=process.cwd(),implementation=options.implementation,fixture=options.fixture,provenance=options['fixture-provenance'],models=options.models;fs.appendFileSync(process.env.LIGHTFORGE_FAKE_BENCHMARK_COUNTER,'call\\n');const report={passed:true,sourceSHA256:hash(implementation),fixtureSHA256:hash(fixture),fixtureProvenance:{path:provenance,sha256:hash(provenance),schema:'lightforge.deux-benchmark-fixture.v1'},manifestSHA256:hash(path.join(models,'manifest.json')),model:{checkpointSHA256:'test-model'},source_hashes:{[path.relative(root,implementation)]:hash(implementation),'tools/benchmark_deux_runtime.cjs':hash(__filename)},threads:Number(options.threads),samples,mode:{spectrumReuse:{enabled},coldProcess:true,filesystemCache:{state:'uncontrolled',strictColdIo:false},thermalState:{available:false}},result:{chunks:3,preprocessing:{spectrumReuse:{enabled}}},runtime:{ortWebVersion:'1.20.1',sessionConfiguration:{executionProviders:['wasm'],graphOptimizationLevel:'all',enableCpuMemArena:false,enableMemPattern:false}},performanceProfile:{resources:{cpuTimeMs:{available:false}},counters:{'transform.frames.reused':enabled?1:0}},...(recovery?{recovery:{controlledInterruption:true,restoredPassages:1}}:{})};fs.mkdirSync(path.dirname(options.output),{recursive:true});fs.writeFileSync(options.output,JSON.stringify(report));for(const [index,role] of ['vocals','accompaniment'].entries())fs.writeFileSync(options.pcm+'-'+role+'.f32',Buffer.from(new Float32Array([index,1,2,3,4]).buffer));");
  const invoke=output=>spawnSync(process.execPath,[path.join(repository,'tools/compare_deux_preprocess_reuse.cjs'),'--benchmark',benchmark,'--implementation',implementation,'--models',models,'--fixture',fixture,'--fixture-provenance',provenance,'--total-samples','5','--threads','4','--verify-recovery','on','--min-passages','3','--evidence-mode','resumable-exactness','--state-dir',stateDirectory,'--checkout-identities',checkout,'--asset-inventory',inventory,'--output',output],{cwd:repository,encoding:'utf8',env:{...process.env,LIGHTFORGE_FAKE_BENCHMARK_COUNTER:counter}});
  const first=invoke(firstOutput);assert.equal(first.status,0,first.stderr||first.stdout);assert.equal(fs.readFileSync(counter,'utf8').trim().split('\n').length,3);
  const firstReceipt=JSON.parse(fs.readFileSync(firstOutput,'utf8'));assert.equal(firstReceipt.passed,true);assert.equal(firstReceipt.performanceAcceptance.accepted,false);assert.equal(firstReceipt.observedWallClockReductionPercent,null);assert.deepEqual(Object.keys(firstReceipt.resumableEvidence.arms).sort(),['cold-baseline','cold-candidate','warm-recovery']);
  const second=invoke(secondOutput);assert.equal(second.status,0,second.stderr||second.stdout);assert.equal(fs.readFileSync(counter,'utf8').trim().split('\n').length,3);
  const secondReceipt=JSON.parse(fs.readFileSync(secondOutput,'utf8'));assert.deepEqual(secondReceipt.measurement.resumedArms,['cold-baseline','cold-candidate','warm-recovery']);assert.equal(secondReceipt.performanceAcceptance.accepted,false);assert.equal(secondReceipt.observedWallClockReductionPercent,null);
  fs.writeFileSync(path.join(stateDirectory,'arms','cold-baseline','pcm-vocals.f32'),Buffer.alloc(20,9));
  const corrupt=invoke(corruptOutput);assert.notEqual(corrupt.status,0);assert.match(fs.readFileSync(corruptOutput,'utf8'),/PCM changed/);
 }finally{fs.rmSync(temporary,{recursive:true,force:true});}
});
