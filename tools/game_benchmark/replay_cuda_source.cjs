#!/usr/bin/env node
'use strict';
// Research-only, source-bound replay. The production adapter is never rewritten.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {isDeepStrictEqual} = require('node:util');
const {planPassages, processNativeRecords, processRecords} = require('./process_capture.cjs');
const GAME = require('../../web/analysis/game.js');
const ROOT = path.resolve(__dirname, '../..');
const SHA = /^[a-f0-9]{64}$/;
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const REQUIRED_SOURCES = [
  'web/analysis/game.js', 'web/analysis/models/game/manifest.json',
  'android/src/com/cyberbasslord/lightforge/NativeGame.java', 'android/native-runtime.json',
  'tools/benchmark_game_accelerator.py', 'tools/game_benchmark/GameAcceleratorCapture.java',
  'tools/benchmark_game_source_cuda.py', 'tools/game_benchmark/GameSourceRunner.java',
  'tools/game_benchmark/compare.py', 'tools/benchmark_deux_accelerator.py',
  'tools/profile_deux_operators.py', 'tools/benchmark_deux_execution.py',
  'tools/game_benchmark/process_capture.cjs', 'tools/game_benchmark/replay_cuda_source.cjs'
];
const IDENTITIES = {
  cpu:{runtime:'onnxruntime-java-1.25.1', package:'cpu', provider:'CPUExecutionProvider',
       optimization:'ALL_OPT', cudaHeavyOnly:false, cudaDeterministicCompute:false},
  cuda:{runtime:'onnxruntime-java-1.25.1', package:'gpu', provider:'CUDAExecutionProvider',
        optimization:'BASIC_OPT', cudaHeavyOnly:true, cudaDeterministicCompute:true}
};
const LABELS = ['encoder','dur2bd',...Array.from({length:8},(_,i)=>'segmenter-'+i),'bd2dur','estimator'];
const OUTPUTS = {encoder:['maskT','x_est','x_seg'], dur2bd:['boundaries'], segmenter:['boundaries'],
                 bd2dur:['durations','maskN'], estimator:['presence','scores']};
const WIDTHS = {float32:4,float64:8,bool:1,int32:4,int64:8};

function requireCondition(ok, message) { if (!ok) throw Error(message); }
function rejectNonfinite(value) {
  if (typeof value === 'number') requireCondition(Number.isFinite(value), 'Nonfinite JSON number');
  else if (Array.isArray(value)) value.forEach(rejectNonfinite);
  else if (value && typeof value === 'object') Object.values(value).forEach(rejectNonfinite);
}
function parseJson(bytes) { const value = JSON.parse(bytes.toString('utf8')); rejectNonfinite(value); return value; }
function checkedArtifact(directory, relative, expectedHash) {
  requireCondition(typeof relative === 'string' && relative.length && !path.isAbsolute(relative) &&
    !relative.split(/[\\/]/).some(part=>!part || part==='.' || part==='..') && SHA.test(expectedHash),
    'Invalid artifact path or SHA-256');
  const base = fs.realpathSync(directory), resolved = fs.realpathSync(path.join(base, relative));
  requireCondition(resolved.startsWith(base + path.sep) && fs.statSync(resolved).isFile(), 'Artifact escapes bound directory');
  const bytes = fs.readFileSync(resolved);
  requireCondition(hash(bytes)===expectedHash, 'Artifact digest mismatch: '+relative);
  return {bytes, resolved};
}
function checkedJson(directory, relative, expectedHash) {
  const artifact=checkedArtifact(directory,relative,expectedHash);
  return {...artifact, value:parseJson(artifact.bytes)};
}
function validateSources(bindings) {
  requireCondition(Array.isArray(bindings) && bindings.length>=REQUIRED_SOURCES.length, 'Missing source bindings');
  const seen=new Set();
  for (const binding of bindings) {
    requireCondition(binding && !seen.has(binding.path), 'Duplicate source binding');
    checkedArtifact(ROOT,binding.path,binding.sha256); seen.add(binding.path);
  }
  for (const name of REQUIRED_SOURCES) requireCondition(seen.has(name),'Missing required source binding: '+name);
  return Object.fromEntries(bindings.map(v=>[v.path,v.sha256]));
}
function validatePcm(bytes, input) {
  requireCondition(Number.isSafeInteger(input.totalSamples) && input.totalSamples>0 && input.totalSamples<=64*44100,
    'Invalid complete source sample count');
  requireCondition(bytes.length===input.totalSamples*4 && SHA.test(input.inputPcmSha256) && hash(bytes)===input.inputPcmSha256,
    'Complete PCM binding mismatch');
  for (let i=0; i<bytes.length; i+=4) requireCondition(Number.isFinite(bytes.readFloatLE(i)), 'Nonfinite source PCM');
}
function validateNotes(notes,samples) {
  requireCondition(GAME.validNotes(notes,samples), 'Invalid captured notes');
  for (const note of notes) {
    requireCondition(isDeepStrictEqual(Object.keys(note).sort(),['end','midi','start']), 'Unexpected captured note fields');
  }
}
function validateTensors(receipt, directory) {
  requireCondition(Array.isArray(receipt.stages) && isDeepStrictEqual(receipt.stages.map(s=>s.label),LABELS),
    'Missing, duplicated or reordered captured stages');
  const files=new Set(); let count=0;
  for (const stage of receipt.stages) {
    const graph=stage.label.split('-')[0];
    requireCondition(stage.graph===graph && Array.isArray(stage.outputs) &&
      isDeepStrictEqual(stage.outputs.map(t=>t.name).sort(),OUTPUTS[graph]), 'Unexpected captured graph outputs');
    requireCondition(typeof stage.seconds==='number' && stage.seconds>=0, 'Invalid captured graph duration');
    for (const tensor of stage.outputs) {
      requireCondition(Object.hasOwn(WIDTHS,tensor.type) && Array.isArray(tensor.dims) &&
        tensor.dims.every(n=>Number.isSafeInteger(n)&&n>=0) && typeof tensor.file==='string' &&
        path.basename(tensor.file)===tensor.file && !files.has(tensor.file), 'Invalid captured tensor identity');
      files.add(tensor.file);
      const elements=tensor.dims.reduce((a,b)=>a*b,1), size=elements*WIDTHS[tensor.type];
      requireCondition(Number.isSafeInteger(size) && size>=0 && tensor.bytes===size, 'Invalid captured tensor dimensions');
      const {bytes}=checkedArtifact(directory,tensor.file,tensor.sha256);
      requireCondition(bytes.length===size, 'Captured tensor size mismatch');
      if (tensor.type==='float32' || tensor.type==='float64') {
        const width=WIDTHS[tensor.type];
        for(let i=0;i<bytes.length;i+=width) requireCondition(Number.isFinite(width===4?bytes.readFloatLE(i):bytes.readDoubleLE(i)),
          'Nonfinite captured tensor');
      }
      count++;
    }
  }
  requireCondition(count===16,'Incomplete captured tensors');
  return count;
}
function diagnoseNotes(left,right,productionRounded=false) {
  const sameCount=left.length===right.length;
  const pairs=sameCount?left.map((note,index)=>({index,startDifferenceSeconds:right[index].start-note.start,
    endDifferenceSeconds:right[index].end-note.end,pitchDifferenceMidi:right[index].midi-note.midi})):null;
  return {noteCounts:[left.length,right.length],
    [productionRounded?'productionRoundedNotesExactlyIdentical':'unroundedNotesExactlyIdentical']:isDeepStrictEqual(left,right),
    boundariesExactlyIdentical:sameCount&&pairs.every(p=>p.startDifferenceSeconds===0&&p.endDifferenceSeconds===0),
    maxAbsoluteStartDifferenceSeconds:sameCount?Math.max(0,...pairs.map(p=>Math.abs(p.startDifferenceSeconds))):null,
    maxAbsoluteEndDifferenceSeconds:sameCount?Math.max(0,...pairs.map(p=>Math.abs(p.endDifferenceSeconds))):null,
    maxAbsolutePitchDifferenceMidi:sameCount?Math.max(0,...pairs.map(p=>Math.abs(p.pitchDifferenceMidi))):null,
    indexAlignedDifferences:pairs,
    comparisonRule:'Exact numeric equality; index-aligned deltas only when counts agree. No pitch or timing tolerance.'};
}

function validatePassage(receipt, passage, input, manifest, capture) {
  requireCondition(receipt.schema==='lightforge-game-benchmark-1' && receipt.runtime==='onnxruntime-java-1.25.1' &&
    receipt.sampleRate===44100 && receipt.samples===passage.last-passage.first && receipt.seed===passage.seed &&
    receipt.language===input.language && receipt.steps===8 && receipt.pcmSHA256===passage.pcmSha256 &&
    receipt.sourcePcmSHA256===input.inputPcmSha256 && receipt.sourceSamples===input.totalSamples &&
    receipt.passageIndex===passage.index && receipt.firstSample===passage.first && receipt.lastSample===passage.last &&
    receipt.capture===capture && receipt.retirementConfirmed===true &&
    Number.isSafeInteger(receipt.wallNanos) && receipt.wallNanos>0, 'Captured passage receipt binding mismatch');
  assert.deepEqual(receipt.modelFiles,manifest.files,'Captured graph identity differs');
  validateNotes(receipt.notes,receipt.samples);
  if(capture) for(const stage of receipt.stages) {
    const original=stage.label.startsWith('segmenter-')?'segmenter-'+(passage.index*8+Number(stage.label.split('-')[1])):stage.label;
    requireCondition(stage.captureOriginalLabel===original,'Global captured stage identity mismatch');
  }
  else requireCondition(Array.isArray(receipt.stages)&&receipt.stages.length===0&&receipt.inferenceSeconds===null,
    'Plain receipt contains observer data');
}
function validateAggregate(receipt,input,manifest,plan,mode) {
  requireCondition(receipt.schema==='lightforge-game-source-run-1' && receipt.runtime==='onnxruntime-java-1.25.1' &&
    receipt.sampleRate===44100 && receipt.samples===input.totalSamples && receipt.pcmSHA256===input.inputPcmSha256 &&
    receipt.steps===8 && receipt.language===input.language && receipt.capture===(mode!=='plain') &&
    receipt.profiled===(mode==='profiled') && receipt.passageCount===plan.length && receipt.engineObjects===1 &&
    receipt.retirementConfirmed===true && Number.isSafeInteger(receipt.wallNanos) && receipt.wallNanos>0 &&
    Array.isArray(receipt.passages)&&receipt.passages.length===plan.length,'Complete-source aggregate binding mismatch');
  assert.deepEqual(receipt.modelFiles,manifest.files,'Aggregate graph identity differs');
  for(const key of ['qualityApproved','benchmarkTimingAdmitted','target75Proven','releaseAuthorized'])
    requireCondition(receipt[key]===false,'Unexpected approval in aggregate receipt');
  for(let i=0;i<plan.length;i++)validatePassage(receipt.passages[i],input.passages[i],input,manifest,mode!=='plain');
}
function tensorIdentities(receipt) {
  return receipt.stages.flatMap(stage=>stage.outputs.map(t=>({label:stage.label,name:t.name,type:t.type,dims:t.dims,bytes:t.bytes,sha256:t.sha256})))
    .sort((a,b)=>(a.label+'/'+a.name).localeCompare(b.label+'/'+b.name));
}

async function compareCudaSource(inputFile, pcmFile) {
  const inputBytes=fs.readFileSync(inputFile), input=parseJson(inputBytes);
  requireCondition(input.schema==='lightforge-game-cuda-source-input-1','Unknown CUDA source capture schema');
  const directory=path.dirname(path.resolve(inputFile)), pcm=fs.readFileSync(pcmFile);
  validatePcm(pcm,input);
  const sourceHashes=validateSources(input.sourceBindings);
  const manifest=parseJson(fs.readFileSync(path.join(ROOT,'web/analysis/models/game/manifest.json')));
  assert.deepEqual(input.modelManifest,manifest,'Captured GAME model manifest differs from bound source');
  requireCondition(manifest.id==='game-large-1.0.3-lightforge-1' && manifest.steps===8 && manifest.sampleRate===44100,
    'Unexpected original GAME contract');
  const plan=planPassages(input.totalSamples,input.language);
  requireCondition(Array.isArray(input.passages)&&input.passages.length===plan.length,'Incomplete captured passage plan');
  for(let i=0;i<plan.length;i++) for(const key of ['index','key','first','last','seed'])
    requireCondition(input.passages[i][key]===plan[i][key],'Captured passage plan mismatch: '+key);
  requireCondition(input.modelManifestSha256===sourceHashes['web/analysis/models/game/manifest.json'], 'Model manifest byte binding mismatch');
  for(const key of ['qualityApproved','benchmarkTimingAdmitted','target75Proven','releaseAuthorized'])
    requireCondition(input[key]===false,'Unexpected approval in replay manifest');
  const experiment=checkedJson(directory,input.experimentReceipt,input.experimentReceiptSha256).value;
  requireCondition(experiment.schema==='lightforge.game-source-cuda-experiment.v1' &&
    ['COMPLETE_DIAGNOSTIC','NUMERICAL_EQUIVALENCE_UNPROVEN'].includes(experiment.status) &&
    experiment.inputsRecheckedAfterQualification===true && experiment.observerComparisonsPassed===true,
    'Incomplete or rejected collector experiment');
  for(const key of ['qualityApproved','benchmarkTimingAdmitted','target75Proven','wholeSongSpeedupProven',
    'fullVocalStageSpeedupProven','androidSpeedupProven','releaseAuthorized','measured'])
    requireCondition(experiment[key]===false,'Unexpected approval in collector experiment');
  assert.deepEqual(experiment.sourceHashes,sourceHashes,'Collector source bindings differ');
  assert.deepEqual(experiment.inputProvenance,input.inputProvenance,'Collector input provenance differs');
  requireCondition(input.inputProvenance?.schema==='lightforge.game-source-input.v1' &&
    input.inputProvenance.pcmSHA256===input.inputPcmSha256 && input.inputProvenance.sourceSamples===input.totalSamples &&
    input.inputProvenance.language===input.language && input.inputProvenance.sampleRate===44100 &&
    SHA.test(input.inputProvenance.sourceSHA256) && ['public-mixture','public-separated-vocals','synthetic'].includes(input.inputProvenance.sourceKind),
    'Incomplete source provenance');
  assert.deepEqual(experiment.passagePlan,input.passages.map(p=>Object.fromEntries(['index','key','first','last','seed','pcmSha256'].map(k=>[k,p[k]]))),
    'Collector passage plan differs');
  assert.deepEqual(experiment.variants,['cpu_all','cuda_basic'],'Unexpected collector variants');
  assert.deepEqual(experiment.modes,['plain','captured','profiled'],'Unexpected collector modes');
  requireCondition(Array.isArray(experiment.runs)&&experiment.runs.length===6,'Incomplete collector run matrix');
  const runs={};
  for(const [i,expected] of ['cpu_all/plain','cpu_all/captured','cpu_all/profiled','cuda_basic/plain','cuda_basic/captured','cuda_basic/profiled'].entries()) {
    const row=experiment.runs[i];
    requireCondition(row.variant+'/'+row.mode===expected && row.passageCount===plan.length && row.timingEligible===false,
      'Collector run matrix mismatch');
    const aggregate=checkedJson(directory,row.receipt,row.receiptSha256);
    validateAggregate(aggregate.value,input,manifest,plan,row.mode); runs[expected]=aggregate;
  }
  requireCondition(input.arms && isDeepStrictEqual(Object.keys(input.arms).sort(),['cpu','cuda']), 'Expected exactly CPU and CUDA research arms');
  const armEvidence={};
  for (const arm of ['cpu','cuda']) {
    const description=input.arms[arm];
    assert.deepEqual(description.executionIdentity,IDENTITIES[arm],'Research execution identity mismatch');
    const aggregate=checkedJson(directory,description.aggregateReceipt,description.aggregateReceiptSha256);
    const profiled=checkedJson(directory,description.profiledAggregateReceipt,description.profiledAggregateReceiptSha256);
    const variant=arm==='cpu'?'cpu_all':'cuda_basic';
    assert.deepEqual(experiment.executionIdentity[variant],IDENTITIES[arm],'Collector execution identity mismatch');
    requireCondition(description.aggregateReceiptSha256===hash(runs[variant+'/captured'].bytes) &&
      description.profiledAggregateReceiptSha256===hash(runs[variant+'/profiled'].bytes), 'Arm aggregate differs from collector run');
    checkedArtifact(directory,description.sourceSnapshot,description.sourceSnapshotSha256);
    requireCondition(experiment.artifactHashes?.[description.sourceSnapshot]===description.sourceSnapshotSha256,
      'Snapshot is not bound by completed collector');
    assert.deepEqual(description.profilePlacement,experiment.placement[variant],'Profile placement differs from collector');
    requireCondition(Array.isArray(description.profilePlacement)&&description.profilePlacement.length===plan.length,
      'Incomplete provider placement');
    for(let i=0;i<plan.length;i++) {
      const placement=description.profilePlacement[i],providers=placement.observedProviders;
      requireCondition(placement.passageIndex===i&&placement.heavyGraphsExecuteCudaArithmetic===(arm==='cuda') &&
        placement.durationBoundaryGraphsRequiredOnCpu===true&&Array.isArray(providers)&&
        providers.includes('CPUExecutionProvider')&&providers.every(p=>p==='CPUExecutionProvider'||arm==='cuda'&&p==='CUDAExecutionProvider')&&
        (arm==='cpu'||providers.includes('CUDAExecutionProvider')),'Provider placement contract mismatch');
    }
    armEvidence[arm]={aggregate,profiled,plain:runs[variant+'/plain']};
  }
  const records={cpu:[],cuda:[]}, diagnostics=[], usedReceipts=new Set();
  let tensorsVerified=0;
  for (let i=0;i<plan.length;i++) {
    const passage=input.passages[i];
    for (const field of ['index','key','first','last','seed']) requireCondition(passage[field]===plan[i][field], 'Captured passage plan mismatch: '+field);
    const window=pcm.subarray(passage.first*4,passage.last*4);
    requireCondition(SHA.test(passage.pcmSha256)&&hash(window)===passage.pcmSha256,'Passage PCM digest mismatch');
    let peak=0; for(let j=0;j<window.length;j+=4) peak=Math.max(peak,Math.abs(window.readFloatLE(j)));
    requireCondition(peak>1e-5,'Silent passage is outside this all-callback replay schema');
    for (const arm of ['cpu','cuda']) {
      const relative=passage[arm+'Receipt'];
      requireCondition(!usedReceipts.has(relative),'Duplicate captured receipt'); usedReceipts.add(relative);
      const loaded=checkedJson(directory,relative,passage[arm+'ReceiptSha256']), receipt=loaded.value;
      validatePassage(receipt,passage,input,manifest,true);
      assert.deepEqual(receipt,armEvidence[arm].aggregate.value.passages[i],'Nested captured receipt differs');
      tensorsVerified+=validateTensors(receipt,path.dirname(loaded.resolved));
      const evidence=armEvidence[arm],profileReceipt=evidence.profiled.value.passages[i];
      const profileDirectory=path.join(path.dirname(evidence.profiled.resolved),'passage-'+String(i).padStart(3,'0'));
      requireCondition(experiment.artifactHashes?.[relative]===passage[arm+'ReceiptSha256'],'Passage receipt is not bound by completed collector');
      tensorsVerified+=validateTensors(profileReceipt,profileDirectory);
      assert.deepEqual(receipt.notes,evidence.plain.value.passages[i].notes,'Plain/capture notes differ');
      assert.deepEqual(receipt.notes,profileReceipt.notes,'Capture/profile notes differ');
      assert.deepEqual(tensorIdentities(receipt),tensorIdentities(profileReceipt),'Capture/profile tensor bytes differ');
      records[arm].push({...plan[i],pcmSha256:passage.pcmSha256,notes:structuredClone(receipt.notes)});
    }
    diagnostics.push({index:i,...diagnoseNotes(records.cpu[i].notes,records.cuda[i].notes),
      cpuUnroundedNotes:structuredClone(records.cpu[i].notes),cudaUnroundedNotes:structuredClone(records.cuda[i].notes)});
  }
  const arms={};
  for (const arm of ['cpu','cuda']) {
    const before=structuredClone(records[arm]);
    const replay=await processNativeRecords(manifest,pcm,input.language,records[arm]);
    const checkpoint=await processRecords(manifest,input.totalSamples,input.language,records[arm],true);
    assert.deepEqual(replay.transcription,checkpoint,'Fresh callback and checkpoint-only replay differ');
    assert.deepEqual(records[arm],before,'Replay changed original captured records');
    requireCondition(replay.transcription.runtime==='onnxruntime-android-cpu','Unexpected production adapter runtime label');
    arms[arm]={researchExecutionIdentity:structuredClone(input.arms[arm].executionIdentity),
      productionReplay:replay,checkpointReplayIdentical:true,
      runtimeLabel:{value:replay.transcription.runtime,meaning:'Unmodified production native adapter label; not the research execution runtime.'},
      recordedProviderPlacement:structuredClone(input.arms[arm].profilePlacement),
      providerEvidenceScope:'Source-bound collector profile validation; this replay does not execute CUDA or independently reclassify trace operators.',
      aggregateReceiptSha256:input.arms[arm].aggregateReceiptSha256,
      profiledAggregateReceiptSha256:input.arms[arm].profiledAggregateReceiptSha256,
      sourceSnapshotSha256:input.arms[arm].sourceSnapshotSha256};
  }
  // Recheck bound material after replay; no source or PCM mutation can be hidden by an earlier read.
  assert.deepEqual(validateSources(input.sourceBindings),sourceHashes);
  requireCondition(hash(fs.readFileSync(inputFile))===hash(inputBytes)&&hash(fs.readFileSync(pcmFile))===input.inputPcmSha256,
    'Source capture or PCM changed during replay');
  checkedArtifact(directory,input.experimentReceipt,input.experimentReceiptSha256);
  requireCondition(experiment.artifactHashes&&Object.keys(experiment.artifactHashes).length>0,'Missing completed artifact bindings');
  for(const [relative,digest] of Object.entries(experiment.artifactHashes))checkedArtifact(directory,relative,digest);
  const exact=isDeepStrictEqual(arms.cpu.productionReplay.transcription,arms.cuda.productionReplay.transcription);
  return {schema:'lightforge-game-cuda-source-comparison-1',captureInputSha256:hash(inputBytes),
    inputPcmSha256:input.inputPcmSha256,experimentReceiptSha256:input.experimentReceiptSha256,
    sourceHashes,totalSamples:input.totalSamples,language:input.language,
    passageCount:plan.length,capturedTensorArtifactsVerified:tensorsVerified,
    verificationMode:'fresh-pcm-native-callback-and-checkpoint-replay',freshNativeCallbackInputsRevalidated:true,
    productionTranscriptionIdentical:exact,nativeCheckpointResumeIdentical:true,
    finalTranscriptionDiagnostics:diagnoseNotes(arms.cpu.productionReplay.transcription.notes,arms.cuda.productionReplay.transcription.notes,true),
    arms,rawNoteDiagnostics:diagnostics,rawTensorParityAsserted:false,
    fullAnalysisQualityApproved:false,androidIntegrationApproved:false,performanceTargetProven:false,
    measuredSpeedupApproved:false,releaseApproved:false,
    scope:'Complete declared source GAME passage captures replayed through unchanged production PCM callback, note validation, clipping, continuation, stitching, sorting, rounding and checkpoint resume. No model inference is performed by this replay.',
    limitations:['Research Java CPU and CUDA execution identities are separate from the unchanged production adapter runtime label.',
      'Exact equality is diagnostic, not musical quality approval; raw tensor comparison and provider placement belong to the bound collector evidence.',
      'This schema requires every canonical passage to exceed the production silence threshold and rejects silent passages.',
      'Excludes separation, source transfer, vocal fusion, show generation, Android transport/lifecycle and complete analysis timing.']};
}

async function main() {
  if(process.argv.length!==5) throw Error('Usage: replay_cuda_source.cjs replay-manifest.json complete-pcm.f32 new-comparison.json');
  const result=await compareCudaSource(process.argv[2],process.argv[3]);
  fs.writeFileSync(process.argv[4],JSON.stringify(result,null,2)+'\n',{flag:'wx'});
  console.log(JSON.stringify({productionTranscriptionIdentical:result.productionTranscriptionIdentical,
    nativeCheckpointResumeIdentical:result.nativeCheckpointResumeIdentical,passageCount:result.passageCount,
    fullAnalysisQualityApproved:false,performanceTargetProven:false}));
  if(!result.productionTranscriptionIdentical)process.exitCode=2;
}
module.exports={compareCudaSource,diagnoseNotes,REQUIRED_SOURCES,IDENTITIES};
if(require.main===module)main().catch(error=>{console.error(error);process.exitCode=1;});
