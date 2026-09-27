#!/usr/bin/env node
'use strict';
// Research adapter only. All inference and production code remain unchanged.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const {isDeepStrictEqual} = require('node:util');
const SHA = /^[a-f0-9]{64}$/;
const COMMIT = /^[a-f0-9]{40}$/;
const VERIFIER = 'tools/game_benchmark/verify_session_reuse_evidence.py';
const HELPER = 'tools/game_benchmark/process_capture.cjs';
const APP = 'web/analysis/game.js';
const MANIFEST = 'web/analysis/models/game/manifest.json';
const PCM_SHA = '298f7a549c4bb8dfc53c47d1078cea842c5e818a3e7c82bf289bffcec0ba30c2';
const FALSE_FLAGS = ['measured', 'benchmarkTimingAdmitted', 'qualityApproved', 'target75Proven',
  'androidLifecycleQualified', 'releaseAuthorized'];
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const pin = bytes => ({bytes:bytes.length, sha256:hash(bytes)});
function requireCondition(ok, message) { if (!ok) throw Error(message); }
function finite(value) {
  if (typeof value === 'number') requireCondition(Number.isFinite(value), 'Nonfinite JSON number');
  else if (Array.isArray(value)) value.forEach(finite);
  else if (value && typeof value === 'object') Object.values(value).forEach(finite);
}
function json(bytes) { const result = JSON.parse(bytes.toString('utf8')); finite(result); return result; }
function safeFile(root, relative) {
  requireCondition(typeof relative === 'string' && relative && !path.isAbsolute(relative) &&
    !relative.includes('\\') && !relative.includes('\0') && !/^[A-Za-z]:/.test(relative) &&
    relative.split('/').every(p=>p && p!=='.' && p!=='..'), 'Unsafe artifact path');
  let result = root;
  for (const part of relative.split('/')) {
    result = path.join(result, part);
    requireCondition(!fs.lstatSync(result).isSymbolicLink(), 'Linked evidence path');
  }
  requireCondition(fs.statSync(result).isFile(), 'Evidence is not a regular file');
  return result;
}
function freshOutput(output, input) {
  output=path.resolve(output);input=fs.realpathSync(input);
  requireCondition(!fs.existsSync(output) && !output.startsWith(input+path.sep) && output!==input,
    'Use a new output directory outside the evidence run');
  for(let parent=path.dirname(output);;parent=path.dirname(parent)) {
    if(fs.existsSync(parent)) requireCondition(fs.lstatSync(parent).isDirectory() && !fs.lstatSync(parent).isSymbolicLink(),
      'Output ancestor is linked or not a directory');
    if(parent===path.dirname(parent))break;
  }
  return output;
}
function checkedBytes(root, relative, expected) {
  requireCondition(SHA.test(expected), 'Missing artifact digest');
  const data = fs.readFileSync(safeFile(root, relative));
  requireCondition(hash(data) === expected, 'Changed evidence artifact: ' + relative);
  return data;
}
function git(repo, ...args) {
  const result = spawnSync('git', ['-C', repo, ...args], {maxBuffer:32*1024*1024});
  requireCondition(result.status === 0, 'Git source verification failed: ' + String(result.stderr));
  return result.stdout;
}
function gitVerified(source, repo, commit, relative) {
  const filename = safeFile(source, relative), bytes = fs.readFileSync(filename);
  requireCondition(bytes.equals(git(repo, 'show', commit + ':' + relative)), 'Archived source differs from immutable Git: ' + relative);
  return {filename, ...pin(bytes)};
}
function validateAudit(report, sourceCommit, sourceTree, verifierSha) {
  requireCondition(report.schema === 'lightforge.game-session-reuse-independent-audit.v1' &&
    report.verificationPassed === true && report.sourceCommit === sourceCommit &&
    report.sourceTree === sourceTree && report.verifierSha256 === verifierSha &&
    report.cpuExecuted === true && report.cudaExecuted === false, 'Completed frozen CPU audit required');
  requireCondition(FALSE_FLAGS.every(flag=>report[flag] === false), 'Audit contains unsupported approval');
  const qualification = report.stages?.qualification;
  requireCondition(report.stages?.readiness?.status === 'PREFLIGHT_READY' &&
    qualification?.status === 'COMPLETE_DIAGNOSTIC' && qualification.completedRuns === 6 &&
    qualification.sourcePassagesPerRun === 6 && qualification.observerComparisons === 24 &&
    qualification.observerComparisonsPassed === true && qualification.withinProviderParityProven === true,
    'Completed exact default/reuse parity and observer gates required');
  const comparisons = qualification.withinProviderComparisons;
  requireCondition(Array.isArray(comparisons) && comparisons.length === 6 && comparisons.every((item, index)=>
    item.variant === 'cpu_all' && item.passageIndex === index && item.reference === 'default' &&
    item.candidate === 'reuse' && item.exactParity === true && item.unroundedNotesIdentical === true &&
    item.qualityApproved === false && item.tolerance === null && Array.isArray(item.tensors) &&
    item.tensors.length === 16 && item.tensors.every(t=>t.shapeAndTypeMatch === true && t.byteIdentical === true)),
    'Six exact 16-tensor comparisons are required');
}
function verifyRawPair(left, right, leftDirectory, rightDirectory, artifactHashes, qualificationDirectory) {
  requireCondition(isDeepStrictEqual(left.notes, right.notes), 'Unrounded default/reuse notes differ');
  const tensors = receipt=>receipt.stages.flatMap(stage=>stage.outputs.map(t=>({label:stage.label, ...t})));
  const a = tensors(left), b = tensors(right);
  requireCondition(a.length === 16 && b.length === 16, 'Incomplete raw tensor comparison');
  const identities = new Set();
  for (let index=0; index<a.length; index++) {
    const x=a[index], y=b[index], identity=x.label+'/'+x.name;
    requireCondition(!identities.has(identity), 'Duplicate raw tensor identity'); identities.add(identity);
    requireCondition(['label','name','type','dims','bytes','sha256'].every(k=>isDeepStrictEqual(x[k],y[k])),
      'Raw tensor default/reuse identity differs');
    requireCondition(path.basename(x.file)===x.file && path.basename(y.file)===y.file, 'Unsafe raw tensor filename');
    const leftRelative=leftDirectory+'/'+x.file, rightRelative=rightDirectory+'/'+y.file;
    requireCondition(artifactHashes[leftRelative]===x.sha256 && artifactHashes[rightRelative]===y.sha256,
      'Raw tensor is absent from completed collector inventory');
    const xb=checkedBytes(qualificationDirectory,leftRelative,x.sha256);
    const yb=checkedBytes(qualificationDirectory,rightRelative,y.sha256);
    requireCondition(xb.length===x.bytes && yb.length===y.bytes && xb.equals(yb), 'Raw tensor bytes differ');
  }
  return a.length;
}
async function replayRecords(engine, manifest, pcm, recordsByArm) {
  assert.deepEqual(recordsByArm.default, recordsByArm.reuse, 'Default/reuse raw records differ');
  const arms = {};
  for (const arm of ['default', 'reuse']) {
    const fresh = await engine.processNativeRecords(manifest, pcm, 0, recordsByArm[arm]);
    const restored = await engine.processRecords(manifest, pcm.length/4, 0, recordsByArm[arm], true);
    assert.deepEqual(restored, fresh.transcription, 'Fresh native replay and independent checkpoint restore differ');
    requireCondition(fresh.nativeCalls===6 && fresh.nativeCheckpointResumeIdentical===true,
      'Native callback count or checkpoint resume differs');
    arms[arm] = {...fresh, independentCheckpointRestoreIdentical:true};
  }
  assert.deepEqual(arms.default.transcription, arms.reuse.transcription, 'Production default/reuse transcriptions differ');
  return arms;
}
async function run(args) {
  requireCondition(COMMIT.test(args.sourceCommit), 'Exact immutable source commit required');
  requireCondition(COMMIT.test(args.verifierSourceCommit), 'Exact immutable verifier source commit required');
  const repo=fs.realpathSync(args.repo), input=path.resolve(args.runDirectory);
  requireCondition(fs.lstatSync(input).isDirectory() && !fs.lstatSync(input).isSymbolicLink(), 'Real input directory required');
  const runDirectory=fs.realpathSync(input);
  const output=freshOutput(args.output,runDirectory);
  const sourceTree=git(repo,'rev-parse',args.sourceCommit+'^{tree}').toString().trim();
  requireCondition(!args.sourceTree || args.sourceTree===sourceTree, 'Explicit source tree differs');
  const verifierSourceTree=git(repo,'rev-parse',args.verifierSourceCommit+'^{tree}').toString().trim();
  const verifierBytes=git(repo,'show',args.verifierSourceCommit+':'+VERIFIER);
  const verifierPin=pin(verifierBytes);
  const source=path.join(runDirectory,'execution-source');
  const bindings=Object.fromEntries([VERIFIER,HELPER,APP,MANIFEST].map(name=>[name,gitVerified(source,repo,args.sourceCommit,name)]));
  requireCondition(!fs.lstatSync(args.verification).isSymbolicLink(), 'Linked verification report');
  const auditBytes=fs.readFileSync(args.verification), audit=json(auditBytes);
  validateAudit(audit,args.sourceCommit,sourceTree,verifierPin.sha256);
  fs.mkdirSync(output,{recursive:true});
  const status={schema:'lightforge.game-session-reuse-production-replay.v1', status:'INCOMPLETE',
    executionSourceCommit:args.sourceCommit, executionSourceTree:sourceTree,
    verificationSourceCommit:args.verifierSourceCommit, verificationSourceTree:verifierSourceTree,
    verificationSource:{path:VERIFIER,...verifierPin},
    inputRunDirectory:runDirectory, inputVerification:pin(auditBytes),
    replayAdapter:pin(fs.readFileSync(__filename)), nodeVersion:process.version,
    sourceBindings:Object.fromEntries(Object.entries(bindings).map(([name,value])=>[name,{bytes:value.bytes,sha256:value.sha256}])),
    cpuInferenceCapturedPreviously:true, modelInferenceExecuted:false, cudaExecuted:false,
    ...Object.fromEntries(FALSE_FLAGS.map(flag=>[flag,false])), wholeSongSpeedupProven:false,
    fullVocalStageSpeedupProven:false, androidSpeedupProven:false, appLifecycleEquivalent:false};
  try {
    // A later, explicitly reviewed verifier may audit an unchanged earlier run.
    // Keep that code separate from the original archived execution-source.
    const verifierRelative='verification-source/'+VERIFIER;
    const verifierFile=path.join(output,verifierRelative);
    fs.mkdirSync(path.dirname(verifierFile),{recursive:true});
    fs.writeFileSync(verifierFile,verifierBytes,{flag:'wx'});
    checkedBytes(output,verifierRelative,verifierPin.sha256);
    // A prior report is mandatory, but never grants trust to a subsequently edited run.
    const recheck=spawnSync('python3',[verifierFile,'--run-directory',runDirectory,
      '--repo',repo,'--source-commit',args.sourceCommit,'--source-tree',sourceTree,'--variants','cpu_all',
      '--output-dir',path.join(output,'independent-audit')],{encoding:'utf8',maxBuffer:4*1024*1024,timeout:600000});
    fs.writeFileSync(path.join(output,'independent-audit.log'),(recheck.stdout||'')+(recheck.stderr||''),{flag:'wx'});
    requireCondition(recheck.status===0, 'Fresh independent audit failed: '+(recheck.error?.message||recheck.status));
    const recheckedBytes=fs.readFileSync(path.join(output,'independent-audit/verification.json'));
    const rechecked=json(recheckedBytes);
    validateAudit(rechecked,args.sourceCommit,sourceTree,verifierPin.sha256);
    checkedBytes(output,verifierRelative,verifierPin.sha256);
    assert.deepEqual(rechecked.stages,audit.stages,'Provided audit differs from fresh evidence');
    status.freshVerification=pin(recheckedBytes);
    const qualificationDirectory=path.join(runDirectory,'qualification');
    const qualificationBytes=fs.readFileSync(safeFile(runDirectory,'qualification/receipt.json'));
    const qualification=json(qualificationBytes);
    const driverBytes=fs.readFileSync(safeFile(runDirectory,'driver-receipt.json')), driver=json(driverBytes);
    requireCondition(hash(qualificationBytes)===driver.qualificationReceipt.sha256 &&
      qualificationBytes.length===driver.qualificationReceipt.bytes, 'Driver qualification binding changed');
    requireCondition(qualification.status==='COMPLETE_DIAGNOSTIC' && qualification.withinProviderRawAndUnroundedParityProven===true,
      'Collector exact parity gate is not complete');
    const pcm=fs.readFileSync(safeFile(runDirectory,'public-demo-mixture-full64s.f32'));
    requireCondition(pcm.length===64*44100*4 && hash(pcm)===PCM_SHA, 'Exact public 64-second source required');
    for (const name of [VERIFIER,HELPER,APP,MANIFEST]) gitVerified(source,repo,args.sourceCommit,name);
    checkedBytes(output,verifierRelative,verifierPin.sha256);
    const engine=require(bindings[HELPER].filename), manifest=json(fs.readFileSync(bindings[MANIFEST].filename));
    const plan=engine.planPassages(pcm.length/4,0), records={default:[],reuse:[]}, passageBindings=[];
    const inventory=qualification.artifactHashes;
    let rawTensorPairs=0;
    for (const passage of plan) {
      const local={};
      for (const arm of ['default','reuse']) {
        const directory='cpu_all_'+arm+'_captured/output/passage-'+String(passage.index).padStart(3,'0');
        const relative=directory+'/receipt.json';
        const bytes=checkedBytes(qualificationDirectory,relative,inventory[relative]), receipt=json(bytes);
        const pcmSha256=hash(pcm.subarray(passage.first*4,passage.last*4));
        requireCondition(receipt.passageIndex===passage.index && receipt.firstSample===passage.first &&
          receipt.lastSample===passage.last && receipt.seed===passage.seed && receipt.language===0 &&
          receipt.steps===8 && receipt.pcmSHA256===pcmSha256, 'Captured passage input binding differs');
        records[arm].push({...passage,pcmSha256,notes:receipt.notes});
        local[arm]={directory,receipt};
        passageBindings.push({arm,index:passage.index,receipt:relative,...pin(bytes)});
      }
      rawTensorPairs+=verifyRawPair(local.default.receipt,local.reuse.receipt,
        local.default.directory,local.reuse.directory,inventory,qualificationDirectory);
    }
    const arms=await replayRecords(engine,manifest,pcm,records);
    // Recheck every directly used source/receipt after replay. Tensor bytes were
    // compared immediately before use; cached notes and PCM cannot drift.
    for (const item of passageBindings) checkedBytes(qualificationDirectory,item.receipt,item.sha256);
    requireCondition(fs.readFileSync(safeFile(runDirectory,'qualification/receipt.json')).equals(qualificationBytes) &&
      fs.readFileSync(safeFile(runDirectory,'driver-receipt.json')).equals(driverBytes), 'Completion receipts changed during replay');
    for (const name of [VERIFIER,HELPER,APP,MANIFEST]) gitVerified(source,repo,args.sourceCommit,name);
    checkedBytes(output,verifierRelative,verifierPin.sha256);
    Object.assign(status,{status:'COMPLETE_DIAGNOSTIC',qualificationReceipt:pin(qualificationBytes),driverReceipt:pin(driverBytes),
      inputPcm:pin(pcm),passageCount:6,passageBindings,rawTensorPairsByteIdentical:rawTensorPairs,
      unroundedDefaultReuseNotesIdentical:true,productionTranscriptionsIdentical:true,
      freshNativeCallbackInputsRevalidated:true,arms,
      scope:'Unchanged production GAME clipping, continuation, stitching, sorting, rounding and native checkpoint validation over six already captured CPU default/reuse passages.',
      limitations:['The public input is a mixture, not a separated vocal stem.',
        'The native callback returns existing captured notes. This replay performs no model inference.',
        'Production runtime labels are retained as data; no Android runtime, lifecycle, device or CUDA execution is established.',
        'Source separation, vocal fusion, show generation and complete analysis timing remain outside this replay.']});
  } catch (error) {
    status.status='BLOCKED_OR_REJECTED'; status.failure=error.message; throw error;
  } finally {
    fs.writeFileSync(path.join(output,'replay.json'),JSON.stringify(status,null,2)+'\n',{flag:'wx'});
  }
  return status;
}
function argumentsFrom(argv) {
  const names={'--repo':'repo','--run-directory':'runDirectory','--verification':'verification',
    '--source-commit':'sourceCommit','--source-tree':'sourceTree','--verifier-source-commit':'verifierSourceCommit',
    '--output':'output'}, result={};
  for(let index=0;index<argv.length;index+=2) {
    requireCondition(names[argv[index]] && argv[index+1] && !Object.hasOwn(result,names[argv[index]]), 'Unknown, incomplete or duplicate option');
    result[names[argv[index]]]=argv[index+1];
  }
  requireCondition(['repo','runDirectory','verification','sourceCommit','verifierSourceCommit','output'].every(k=>result[k]),
    'Required: --repo --run-directory --verification --source-commit --verifier-source-commit --output');
  return result;
}
module.exports={validateAudit,safeFile,freshOutput,verifyRawPair,replayRecords,run,argumentsFrom};
if(require.main===module)run(argumentsFrom(process.argv.slice(2))).then(result=>console.log(JSON.stringify({
  status:result.status,passageCount:result.passageCount,rawTensorPairsByteIdentical:result.rawTensorPairsByteIdentical,
  finalNotes:result.arms.default.transcription.notes.length,target75Proven:false}))).catch(error=>{console.error(error);process.exitCode=1;});
