'use strict';
const assert=require('node:assert/strict');
const {test}=require('node:test');
const crypto=require('node:crypto'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {compareCudaSource,REQUIRED_SOURCES,IDENTITIES}=require('../replay_cuda_source.cjs');
const {planPassages}=require('../process_capture.cjs');
const ROOT=path.resolve(__dirname,'../../..');
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const labels=['encoder','dur2bd',...Array.from({length:8},(_,i)=>'segmenter-'+i),'bd2dur','estimator'];
const outputs={encoder:['x_seg','x_est','maskT'],dur2bd:['boundaries'],segmenter:['boundaries'],bd2dur:['durations','maskN'],estimator:['scores','presence']};

function fixture() {
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'lightforge-game-cuda-replay-'));
  const pcm=Buffer.alloc(24*44100*4);
  for(let i=0;i<pcm.length;i+=4)pcm.writeFloatLE(.125,i);
  const model=JSON.parse(fs.readFileSync(path.join(ROOT,'web/analysis/models/game/manifest.json')));
  const plan=planPassages(pcm.length/4,0), receipts={cpu:[],cuda:[]};
  const input={schema:'lightforge-game-cuda-source-input-1',totalSamples:pcm.length/4,language:0,
    inputPcmSha256:hash(pcm),modelManifest:model,modelManifestSha256:hash(fs.readFileSync(path.join(ROOT,'web/analysis/models/game/manifest.json'))),
    inputProvenance:{schema:'lightforge.game-source-input.v1',sourceSamples:pcm.length/4,pcmSHA256:hash(pcm),
      sourceSHA256:hash(pcm),sourceKind:'synthetic',sampleRate:44100,language:0,derivation:'Synthetic constant PCM fixture; no model inference.'},
    qualityApproved:false,benchmarkTimingAdmitted:false,target75Proven:false,releaseAuthorized:false,
    sourceBindings:REQUIRED_SOURCES.map(p=>({path:p,sha256:hash(fs.readFileSync(path.join(ROOT,p)))})),
    arms:{},passages:plan.map(p=>({...p,pcmSha256:hash(pcm.subarray(p.first*4,p.last*4))}))};
  const write=(relative,value)=>{
    const bytes=Buffer.isBuffer(value)?value:Buffer.from(JSON.stringify(value));
    const file=path.join(directory,relative);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,bytes);return hash(bytes);
  };
  for(const arm of ['cpu','cuda']) {
    for(let i=0;i<plan.length;i++) {
      const r={schema:'lightforge-game-benchmark-1',runtime:'onnxruntime-java-1.25.1',sampleRate:44100,
        samples:plan[i].last-plan[i].first,seed:plan[i].seed,language:0,steps:8,
        pcmSHA256:input.passages[i].pcmSha256,modelFiles:model.files,capture:true,retirementConfirmed:true,
        sourcePcmSHA256:hash(pcm),sourceSamples:pcm.length/4,passageIndex:i,firstSample:plan[i].first,lastSample:plan[i].last,wallNanos:1,
        notes:i===0?[{start:11,end:13,midi:60.001}]:[{start:1,end:3,midi:60.002},{start:3,end:4,midi:60.002}],
        stages:[]};
      for(const label of labels) {
        const graph=label.split('-')[0], stage={label,graph,seconds:.001,
          captureOriginalLabel:graph==='segmenter'?'segmenter-'+(i*8+Number(label.split('-')[1])):label,outputs:[]};
        for(const name of outputs[graph]) {
          const bytes=Buffer.alloc(4);bytes.writeFloatLE(.25);
          const file=label+'-'+name+'.bin';
          stage.outputs.push({name,type:'float32',dims:[1],file,bytes:4,sha256:write(`${arm}/passage-${i}/${file}`,bytes)});
        }
        r.stages.push(stage);
      }
      receipts[arm].push(r);input.passages[i][arm+'Receipt']=`${arm}/passage-${i}/receipt.json`;
    }
    input.arms[arm]={executionIdentity:structuredClone(IDENTITIES[arm]),aggregateReceipt:`${arm}/aggregate.json`,
      profiledAggregateReceipt:`${arm}/profiled/receipt.json`,sourceSnapshot:`${arm}/NativeGame.java`,
      profilePlacement:plan.map(p=>({passageIndex:p.index,observedProviders:arm==='cpu'?['CPUExecutionProvider']:['CPUExecutionProvider','CUDAExecutionProvider'],
        heavyGraphsExecuteCudaArithmetic:arm==='cuda',durationBoundaryGraphsRequiredOnCpu:true})),
      sourceSnapshotSha256:write(`${arm}/NativeGame.java`,fs.readFileSync(path.join(ROOT,'android/src/com/cyberbasslord/lightforge/NativeGame.java')))};
  }
  function save() {
    write('input.f32',pcm);
    const experiment={schema:'lightforge.game-source-cuda-experiment.v1',status:'NUMERICAL_EQUIVALENCE_UNPROVEN',
      sourceHashes:Object.fromEntries(input.sourceBindings.map(p=>[p.path,p.sha256])),inputProvenance:input.inputProvenance,
      passagePlan:input.passages.map(p=>Object.fromEntries(['index','key','first','last','seed','pcmSha256'].map(k=>[k,p[k]]))),
      variants:['cpu_all','cuda_basic'],modes:['plain','captured','profiled'],runs:[],placement:{},executionIdentity:{},artifactHashes:{},
      inputsRecheckedAfterQualification:true,observerComparisonsPassed:true,qualityApproved:false,benchmarkTimingAdmitted:false,
      target75Proven:false,wholeSongSpeedupProven:false,fullVocalStageSpeedupProven:false,androidSpeedupProven:false,releaseAuthorized:false,measured:false};
    for(const arm of ['cpu','cuda']) {
      for(let i=0;i<plan.length;i++) {
        if(input.passages[i]) {
          const digest=write(`${arm}/passage-${i}/receipt.json`,receipts[arm][i]);
          input.passages[i][arm+'ReceiptSha256']=digest;
          experiment.artifactHashes[`${arm}/passage-${i}/receipt.json`]=digest;
        }
        for(const stage of receipts[arm][i].stages) for(const tensor of stage.outputs)
          fs.cpSync(path.join(directory,`${arm}/passage-${i}/${tensor.file}`),
            path.join(directory,`${arm}/profiled/passage-${String(i).padStart(3,'0')}/${tensor.file}`),{recursive:true});
      }
      const common={schema:'lightforge-game-source-run-1',runtime:'onnxruntime-java-1.25.1',sampleRate:44100,
        samples:input.totalSamples,pcmSHA256:input.inputPcmSha256,modelFiles:model.files,steps:8,language:0,
        capture:true,passageCount:plan.length,engineObjects:1,retirementConfirmed:true,
        passages:structuredClone(receipts[arm]),wallNanos:1,
        benchmarkTimingAdmitted:false,qualityApproved:false,target75Proven:false,releaseAuthorized:false};
      input.arms[arm].aggregateReceiptSha256=write(input.arms[arm].aggregateReceipt,{...common,profiled:false});
      input.arms[arm].profiledAggregateReceiptSha256=write(input.arms[arm].profiledAggregateReceipt,{...common,profiled:true});
      const variant=arm==='cpu'?'cpu_all':'cuda_basic';
      const plain=`${arm}/plain.json`,plainDigest=write(plain,{...common,capture:false,profiled:false,
        passages:common.passages.map(p=>({...p,capture:false,stages:[],inferenceSeconds:null}))});
      experiment.runs.push(...[['plain',plain,plainDigest],['captured',input.arms[arm].aggregateReceipt,input.arms[arm].aggregateReceiptSha256],
        ['profiled',input.arms[arm].profiledAggregateReceipt,input.arms[arm].profiledAggregateReceiptSha256]].map(([mode,receipt,receiptSha256])=>
        ({variant,mode,receipt,receiptSha256,passageCount:plan.length,timingEligible:false})));
      experiment.placement[variant]=structuredClone(input.arms[arm].profilePlacement);
      experiment.executionIdentity[variant]=structuredClone(input.arms[arm].executionIdentity);
      experiment.artifactHashes[input.arms[arm].sourceSnapshot]=input.arms[arm].sourceSnapshotSha256;
    }
    input.experimentReceipt='experiment.json';input.experimentReceiptSha256=write('experiment.json',experiment);
    write('replay-manifest.json',input);
  }
  save();
  return {directory,input,pcm,receipts,save,write,
    run:()=>compareCudaSource(path.join(directory,'replay-manifest.json'),path.join(directory,'input.f32')),
    remove:()=>fs.rmSync(directory,{recursive:true,force:true})};
}

test('actual production callback, carry stitching, rearticulation and checkpoint resume consume the full source',async()=>{
  const f=fixture();try {
    const original=structuredClone(f.receipts);
    const result=await f.run();
    assert.equal(result.passageCount,2);assert.equal(result.capturedTensorArtifactsVerified,128);
    assert.equal(result.productionTranscriptionIdentical,true);
    for(const arm of ['cpu','cuda']) {
      assert.equal(result.arms[arm].productionReplay.nativeCalls,2);
      assert.equal(result.arms[arm].productionReplay.nativeCheckpointResumeIdentical,true);
      assert.equal(result.arms[arm].checkpointReplayIdentical,true);
      assert.equal(result.arms[arm].productionReplay.transcription.runtime,'onnxruntime-android-cpu');
      assert.match(result.arms[arm].runtimeLabel.meaning,/not the research/);
      assert.deepEqual(result.arms[arm].productionReplay.transcription.notes.map(n=>[n.start,n.end,n.midi,n.continuation]),
        [[11,13,60,false],[13,14,60,false]]);
    }
    assert.equal(result.arms.cuda.researchExecutionIdentity.provider,'CUDAExecutionProvider');
    assert.deepEqual(f.receipts,original);
    for(const key of ['fullAnalysisQualityApproved','androidIntegrationApproved','performanceTargetProven','measuredSpeedupApproved','releaseApproved','rawTensorParityAsserted'])assert.equal(result[key],false);
  }finally{f.remove();}
});

test('unrounded pitch and boundary deltas remain explicit even when final transcription is exact',async()=>{
  const f=fixture();try {
    f.receipts.cuda[0].notes[0].midi+=.00001;
    f.receipts.cuda[0].notes[0].start+=.00001;f.save();
    const result=await f.run();
    assert.equal(result.productionTranscriptionIdentical,true);
    assert.equal(result.rawNoteDiagnostics[0].unroundedNotesExactlyIdentical,false);
    assert.equal(result.rawNoteDiagnostics[0].boundariesExactlyIdentical,false);
    assert.ok(result.rawNoteDiagnostics[0].maxAbsolutePitchDifferenceMidi>0);
    assert.ok(result.rawNoteDiagnostics[0].maxAbsoluteStartDifferenceSeconds>0);
    assert.equal(result.fullAnalysisQualityApproved,false);
    f.receipts.cuda[0].notes[0].midi=61;f.save();
    assert.equal((await f.run()).productionTranscriptionIdentical,false);
  }finally{f.remove();}
});

test('missing, duplicate, extra, reordered and modified canonical passages fail closed',async()=>{
  const f=fixture();try {
    const original=structuredClone(f.input.passages);
    const edits=[p=>p.pop(),p=>p.push(p[0]),p=>p.reverse(),p=>{p[1]=structuredClone(p[0]);},
      p=>{p[1].seed++;},p=>{p[1].key='game-0-wrong';},p=>{p[1].first++;}];
    for(const change of edits){f.input.passages=structuredClone(original);change(f.input.passages);f.save();await assert.rejects(f.run(),/passage plan/);}
  }finally{f.remove();}
});

test('PCM, source, model, identity, receipt and tensor mismatches are rejected',async()=>{
  const f=fixture();try {
    const original=structuredClone(f.input);
    f.input.inputPcmSha256='0'.repeat(64);f.save();await assert.rejects(f.run(),/PCM binding/);
    Object.assign(f.input,structuredClone(original));f.input.sourceBindings[0].sha256='0'.repeat(64);f.save();await assert.rejects(f.run(),/digest mismatch/);
    Object.assign(f.input,structuredClone(original));f.input.modelManifest.steps=7;f.save();await assert.rejects(f.run(),/manifest differs/);
    Object.assign(f.input,structuredClone(original));f.input.arms.cuda.executionIdentity.provider='CPUExecutionProvider';f.save();await assert.rejects(f.run(),/identity mismatch/);
    Object.assign(f.input,structuredClone(original));f.save();fs.appendFileSync(path.join(f.directory,f.input.passages[0].cpuReceipt),' ');await assert.rejects(f.run(),/digest mismatch/);
    f.save();fs.writeFileSync(path.join(f.directory,'cuda/passage-0/encoder-x_seg.bin'),Buffer.alloc(4));await assert.rejects(f.run(),/digest mismatch/);
  }finally{f.remove();}
});

test('invalid notes, nonfinite values, malformed stages and tensor metadata are rejected',async()=>{
  const f=fixture();try {
    const original=structuredClone(f.receipts.cuda[0]);
    for(const notes of [[{start:0,end:99,midi:60}],[{start:0,end:1,midi:128}],[{start:0,end:1,midi:null}],
      [{start:0,end:1,midi:60},{start:.5,end:2,midi:61}],[{start:0,end:1,midi:60,confidence:.9}]]) {
      f.receipts.cuda[0]=structuredClone(original);f.receipts.cuda[0].notes=notes;f.save();await assert.rejects(f.run(),/Invalid captured notes|Unexpected captured note fields/);
    }
    f.receipts.cuda[0]=structuredClone(original);f.receipts.cuda[0].stages.reverse();f.save();await assert.rejects(f.run(),/reordered captured stages/);
    f.receipts.cuda[0]=structuredClone(original);f.receipts.cuda[0].stages[0].outputs[0].dims=[2];f.save();await assert.rejects(f.run(),/tensor dimensions/);
    f.receipts.cuda[0]=structuredClone(original);f.save();
    const filename=path.join(f.directory,f.input.passages[0].cudaReceipt);
    const text=fs.readFileSync(filename,'utf8').replace('60.001','1e999');fs.writeFileSync(filename,text);
    f.input.passages[0].cudaReceiptSha256=hash(text);f.write('replay-manifest.json',f.input);
    await assert.rejects(f.run(),/Nonfinite JSON/);
    f.save();f.pcm.writeFloatLE(NaN,0);f.input.inputPcmSha256=hash(f.pcm);f.save();await assert.rejects(f.run(),/Nonfinite source PCM/);
  }finally{f.remove();}
});

test('silent passages are rejected explicitly rather than fabricating callback or inference counts',async()=>{
  const f=fixture();try {
    f.pcm.fill(0);f.input.inputPcmSha256=hash(f.pcm);
    f.input.inputProvenance.pcmSHA256=hash(f.pcm);
    for(const p of f.input.passages) {
      p.pcmSha256=hash(f.pcm.subarray(p.first*4,p.last*4));
      for(const arm of ['cpu','cuda']) {
        f.receipts[arm][p.index].pcmSHA256=p.pcmSha256;
        f.receipts[arm][p.index].sourcePcmSHA256=f.input.inputPcmSha256;
      }
    }
    f.save();await assert.rejects(f.run(),/Silent passage/);
  }finally{f.remove();}
});

test('legacy schemas and path escapes cannot be relabeled as CUDA source evidence',async()=>{
  const f=fixture();try {
    f.input.schema='lightforge-game-production-process-input-1';f.save();await assert.rejects(f.run(),/Unknown CUDA/);
    f.input.schema='lightforge-game-cuda-source-input-1';f.input.arms.cuda.sourceSnapshot='../outside.java';f.save();
    await assert.rejects(f.run(),/Invalid artifact path/);
  }finally{f.remove();}
});
