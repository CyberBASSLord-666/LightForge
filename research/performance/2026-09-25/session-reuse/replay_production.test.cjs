'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const crypto=require('node:crypto');
const {validateAudit,safeFile,freshOutput,verifyRawPair,replayRecords,argumentsFrom}=require('./replay_production.cjs');
const engine=require('../../../../tools/game_benchmark/process_capture.cjs');
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const source='a'.repeat(40), tree='b'.repeat(40), verifier='c'.repeat(64);
function syntheticAudit() {
  return {schema:'lightforge.game-session-reuse-independent-audit.v1',verificationPassed:true,
    sourceCommit:source,sourceTree:tree,verifierSha256:verifier,cpuExecuted:true,cudaExecuted:false,
    measured:false,benchmarkTimingAdmitted:false,qualityApproved:false,target75Proven:false,
    androidLifecycleQualified:false,releaseAuthorized:false,
    stages:{readiness:{status:'PREFLIGHT_READY'},qualification:{status:'COMPLETE_DIAGNOSTIC',completedRuns:6,
      sourcePassagesPerRun:6,observerComparisons:24,observerComparisonsPassed:true,withinProviderParityProven:true,
      withinProviderComparisons:Array.from({length:6},(_,index)=>({variant:'cpu_all',passageIndex:index,
        reference:'default',candidate:'reuse',exactParity:true,unroundedNotesIdentical:true,qualityApproved:false,
        tolerance:null,tensors:Array.from({length:16},()=>({shapeAndTypeMatch:true,byteIdentical:true}))}))}}};
}
test('audit gate rejects incomplete parity, relaxed tolerance, wrong source and GPU claims',()=>{
  validateAudit(syntheticAudit(),source,tree,verifier);
  for(const mutate of [
    r=>r.verificationPassed=false,
    r=>r.sourceCommit='d'.repeat(40),
    r=>r.verifierSha256='d'.repeat(64),
    r=>r.cudaExecuted=true,
    r=>r.target75Proven=true,
    r=>r.stages.qualification.status='WITHIN_PROVIDER_EQUIVALENCE_UNPROVEN',
    r=>r.stages.qualification.observerComparisons=23,
    r=>r.stages.qualification.withinProviderComparisons.pop(),
    r=>r.stages.qualification.withinProviderComparisons[0].tolerance=.01,
    r=>r.stages.qualification.withinProviderComparisons[0].tensors.pop(),
    r=>r.stages.qualification.withinProviderComparisons[0].tensors[0].byteIdentical=false,
  ]) {const report=syntheticAudit();mutate(report);assert.throws(()=>validateAudit(report,source,tree,verifier));}
});
test('evidence paths reject traversal and linked parents',()=>{
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'game-replay-path-'));
  try {
    fs.mkdirSync(path.join(directory,'real'));fs.writeFileSync(path.join(directory,'real/file'),'ok');
    fs.symlinkSync('real',path.join(directory,'linked'));
    assert.equal(safeFile(directory,'real/file'),path.join(directory,'real/file'));
    for(const relative of ['../escape','real/../real/file','/real/file','C:/file','real\\file','linked/file'])
      assert.throws(()=>safeFile(directory,relative));
  }finally{fs.rmSync(directory,{recursive:true,force:true});}
});
test('output cannot overwrite evidence or enter it through a linked ancestor',()=>{
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'game-replay-output-'));
  try {
    const input=path.join(directory,'input');fs.mkdirSync(input);
    fs.symlinkSync('input',path.join(directory,'linked'));
    assert.equal(freshOutput(path.join(directory,'new'),input),path.join(directory,'new'));
    for(const output of [input,path.join(input,'new'),path.join(directory,'linked/new')])
      assert.throws(()=>freshOutput(output,input));
  }finally{fs.rmSync(directory,{recursive:true,force:true});}
});
test('raw pair guard rechecks actual bytes and unrounded notes before consumer replay',()=>{
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'game-replay-raw-'));
  try {
    const data=Buffer.alloc(4);data.writeFloatLE(.25);
    const tensors=Array.from({length:16},(_,i)=>({name:'test-'+i,file:'tensor-'+i+'.bin',type:'float32',dims:[1],bytes:4,sha256:hash(data)}));
    const left={notes:[{start:0,end:1,midi:60.1234}],stages:[{label:'synthetic-test',outputs:tensors}]};
    const right=structuredClone(left), inventory={};
    for(const arm of ['left','right']) {
      fs.mkdirSync(path.join(directory,arm));
      for(const tensor of tensors) {fs.writeFileSync(path.join(directory,arm,tensor.file),data);inventory[arm+'/'+tensor.file]=tensor.sha256;}
    }
    const check=()=>verifyRawPair(left,right,'left','right',inventory,directory);
    assert.equal(check(),16);
    right.notes[0].midi+=.000001;assert.throws(check,/Unrounded/);right.notes=structuredClone(left.notes);
    const corrupted=Buffer.from(data);corrupted[0]^=1;
    fs.writeFileSync(path.join(directory,'right/tensor-0.bin'),corrupted);assert.throws(check,/Changed evidence/);
  }finally{fs.rmSync(directory,{recursive:true,force:true});}
});
test('actual unchanged production consumer clips and stitches six synthetic captures and restores checkpoints',async()=>{
  // This synthetic fixture exercises only the consumer, never model inference.
  const samples=64*44100,pcm=Buffer.alloc(samples*4);
  for(let i=0;i<samples;i++)pcm.writeFloatLE(.125,i*4);
  const records=engine.planPassages(samples,0).map(p=>({...p,
    pcmSha256:hash(pcm.subarray(p.first*4,p.last*4)),
    notes:[{start:0,end:(p.last-p.first)/44100,midi:60.1234}]}));
  const arms=await replayRecords(engine,{id:'game-large-1.0.3-lightforge-1',steps:8,sampleRate:44100},pcm,
    {default:records,reuse:structuredClone(records)});
  assert.deepEqual(arms.default.transcription,arms.reuse.transcription);
  assert.deepEqual(arms.default.transcription.notes,[{start:0,end:64,midi:60.12,source:'game-large',estimated:true,continuation:false}]);
  for(const arm of Object.values(arms)) {
    assert.equal(arm.nativeCalls,6);assert.equal(arm.nativeCheckpointResumeIdentical,true);
    assert.equal(arm.independentCheckpointRestoreIdentical,true);
  }
  const changed=structuredClone(records);changed[0].notes[0].midi+=.000001;
  await assert.rejects(()=>replayRecords(engine,{id:'game-large-1.0.3-lightforge-1',steps:8,sampleRate:44100},pcm,
    {default:records,reuse:changed}),/raw records differ/);
});
test('CLI requires explicit distinct execution and verifier commit arguments',()=>{
  assert.throws(()=>argumentsFrom(['--repo','x','--repo','y']));
  assert.throws(()=>argumentsFrom(['--repo','x','--run-directory','y','--verification','z','--output','w']));
  const base=['--repo','x','--run-directory','y','--verification','z','--output','w','--source-commit',source];
  assert.throws(()=>argumentsFrom(base));
  const args=argumentsFrom([...base,'--verifier-source-commit','d'.repeat(40)]);
  assert.equal(args.sourceCommit,source);assert.equal(args.verifierSourceCommit,'d'.repeat(40));
});
