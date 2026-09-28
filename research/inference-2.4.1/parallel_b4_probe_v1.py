#!/usr/bin/env python3
"""Host-only independent-B4 concurrent Run screen; not an Android candidate.

Keeps every original model byte, B4 time input and all 335 original graph calls.
Per-call inference timings overlap and must NOT be treated as critical-path wall
time. Only the enclosing whole-passage elapsed time is used for comparisons.
"""
import argparse, hashlib, importlib.util, json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'build/inference-screen/parallel'
SOURCE_RECEIPT = ROOT / 'research/inference-2.4.1/separator-scheduler-paired.json'

HELPER = r'''
    // Experimental host-only outer parallelism. A single graph's original B4
    // calls share immutable session weights and own disjoint tensors/buffers.
    private void runTimeBatchesParallel(OrtSession session,String graph,int stage,
            Listener listener,NativeDeuxTransform.Check check,NativeInferenceProfile profile) throws Exception {
        java.util.concurrent.ExecutorService pool=java.util.concurrent.Executors.newFixedThreadPool(PARALLEL_RUNS);
        boolean complete=false;
        try {
            for(int wave=0;wave<BANDS;wave+=PARALLEL_RUNS*TIME_BATCH) {
                check.check();
                int jobs=Math.min(PARALLEL_RUNS,(BANDS-wave+TIME_BATCH-1)/TIME_BATCH);
                final FloatBuffer[] ins=new FloatBuffer[jobs],outs=new FloatBuffer[jobs];
                final int[] counts=new int[jobs];
                // Snapshot every independent input before starting any writeback.
                for(int j=0;j<jobs;j++) {
                    int first=wave+j*TIME_BATCH,count=Math.min(TIME_BATCH,BANDS-first),size=count*FRAMES*FEATURES;
                    counts[j]=count;ins[j]=slice(parallelInputs[j],0,size);outs[j]=slice(parallelOutputs[j],0,size);
                    NativeInferenceProfile.Timing started=profile==null?null:NativeInferenceProfile.started();
                    try { for(int b=0;b<count;b++)for(int f=0;f<FRAMES;f++)
                        copy(values,(f*BANDS+first+b)*FEATURES,ins[j],(b*FRAMES+f)*FEATURES,FEATURES);
                    } finally { if(profile!=null)profile.addPack(graph,NativeInferenceProfile.elapsed(started)); }
                }
                java.util.List<java.util.concurrent.Future<Void>> futures=new java.util.ArrayList<>();
                for(int j=0;j<jobs;j++) {
                    final int at=j;
                    futures.add(pool.submit(()->{
                        check.check();
                        NativeInferenceProfile.Timing bound=profile==null?null:NativeInferenceProfile.started();
                        try(OnnxTensor x=OnnxTensor.createTensor(OrtEnvironment.getEnvironment(),ins[at],new long[]{counts[at],FRAMES,FEATURES});
                            OnnxTensor y=OnnxTensor.createTensor(OrtEnvironment.getEnvironment(),outs[at],new long[]{counts[at],FRAMES,FEATURES})) {
                            if(profile!=null)profile.addTensorBind(graph,NativeInferenceProfile.elapsed(bound));
                            NativeInferenceProfile.Timing started=profile==null?null:NativeInferenceProfile.started();
                            try(OrtSession.Result ignored=session.run(Collections.singletonMap("input",x),Collections.emptySet(),Collections.singletonMap("output",y),activeRun)) {
                                check.check();
                            } finally { if(profile!=null)profile.addRun(graph,NativeInferenceProfile.elapsed(started)); }
                        }
                        return null;
                    }));
                }
                for(java.util.concurrent.Future<Void> future:futures) {
                    try { future.get(); }
                    catch(java.util.concurrent.ExecutionException failure) {
                        Throwable cause=failure.getCause();
                        if(cause instanceof Exception)throw (Exception)cause;
                        if(cause instanceof Error)throw (Error)cause;
                        throw new RuntimeException(cause);
                    }
                }
                for(int j=0;j<jobs;j++) {
                    int first=wave+j*TIME_BATCH,count=counts[j];
                    NativeInferenceProfile.Timing started=profile==null?null:NativeInferenceProfile.started();
                    try { for(int b=0;b<count;b++)for(int f=0;f<FRAMES;f++)
                        copy(outs[j],(b*FRAMES+f)*FEATURES,values,(f*BANDS+first+b)*FEATURES,FEATURES);
                    } finally { if(profile!=null)profile.addScatter(graph,NativeInferenceProfile.elapsed(started)); }
                    progress(listener,(1+stage+.75*(first+count)/BANDS)/15,"Studio temporal detail · layer "+(stage+1)+"/12");
                }
            }
            complete=true;
        } finally {
            // Session/tensors must not be closed while native Run is active.
            if(!complete)try{activeRun.setTerminate(true);}catch(OrtException ignored){}
            pool.shutdown();boolean interrupted=false;
            while(!pool.isTerminated())try{pool.awaitTermination(1,java.util.concurrent.TimeUnit.SECONDS);}
            catch(InterruptedException cancelled){interrupted=true;try{activeRun.setTerminate(true);}catch(OrtException ignored){}}
            if(interrupted)Thread.currentThread().interrupt();
        }
    }
'''


def generate(workers, intra):
    s = json.loads(SOURCE_RECEIPT.read_text())['frozenSourceSnapshots']['baseline/NativeDeux.java']
    s = s.replace('private final Context context;', f'private static final int PARALLEL_RUNS={workers};\n    private FloatBuffer[] parallelInputs,parallelOutputs;\n    private final Context context;')
    s = s.replace('this.context=context;', 'if(context!=null)throw new IllegalArgumentException("Parallel probe is host-only.");\n        this.context=context;')
    start = s.index('                    for(int first=0;first<BANDS;first+=TIME_BATCH) {')
    end = s.index('\n                try(OrtSession session=open(environment,blockName(block)+"-frequency",check,profile))', start)
    s = s[:start] + '                    runTimeBatchesParallel(session,blockName(block)+"-time",stage,listener,check,profile);\n                }' + s[end:]
    s = s.replace('options.setIntraOpNumThreads(Math.max(1,Math.min(4,Runtime.getRuntime().availableProcessors())));',
                  f'options.setIntraOpNumThreads(name.endsWith("-time")?{intra}:Math.max(1,Math.min(4,Runtime.getRuntime().availableProcessors())));')
    s = s.replace('batchInput=nextBatchInput;batchOutput=nextBatchOutput;', '''batchInput=nextBatchInput;batchOutput=nextBatchOutput;
        parallelInputs=new FloatBuffer[PARALLEL_RUNS];parallelOutputs=new FloatBuffer[PARALLEL_RUNS];
        parallelInputs[0]=batchInput;parallelOutputs[0]=batchOutput;
        for(int i=1;i<PARALLEL_RUNS;i++){parallelInputs[i]=direct(TIME_BATCH*FRAMES*FEATURES);parallelOutputs[i]=direct(TIME_BATCH*FRAMES*FEATURES);}''')
    s = s.replace('private void clearBuffers(){spectrum=null;', 'private void clearBuffers(){parallelInputs=null;parallelOutputs=null;spectrum=null;')
    s = s.replace('batchInput.capacity()+batchOutput.capacity()', 'batchInput.capacity()+batchOutput.capacity()+2L*(PARALLEL_RUNS-1)*TIME_BATCH*FRAMES*FEATURES')
    s = s.replace('    private OrtSession open(', HELPER + '\n    private OrtSession open(')
    return s


def main():
    p=argparse.ArgumentParser();p.add_argument('--workers',type=int,choices=[2,4],required=True);p.add_argument('--intra',type=int,choices=[1,2],required=True)
    p.add_argument('--run',action='store_true');p.add_argument('--round',type=int,default=0)
    p.add_argument('--audio',type=Path,default=ROOT/'web/demo/glass-castle.wav');p.add_argument('--start',type=int,default=-66150)
    args=p.parse_args();WORK.mkdir(exist_ok=True);name=f'parallel-{args.workers}-intra-{args.intra}'
    source=WORK/(name+'.java');source.write_text(generate(args.workers,args.intra))
    spec=importlib.util.spec_from_file_location('benchmark',ROOT/'tools/benchmark_deux_execution.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
    formal=json.loads((ROOT/'research/inference-2.4.1/separator-scheduler-paired.json').read_text())
    shared=WORK/'shared';shared.mkdir(exist_ok=True);(WORK/'tests').mkdir(exist_ok=True)
    for path,content in formal['frozenSourceSnapshots'].items():
        if path.startswith('android/'):(shared/Path(path).name).write_text(content)
        if path=='tests/NativeDeuxExecutionBenchmark.java':(WORK/path).write_text(content)
    b.SOURCE=shared;b.ROOT=WORK
    tc=ROOT.parent/'toolchain';java=tc/'jdk17/bin';deps=[tc/'test-json.jar',tc/'android-sdk/platforms/android-35/android.jar',tc/'onnx/onnxruntime-1.25.1.jar']
    target=WORK/name
    if not target.exists():classes,source_sha=b.compile_variant(name,source,WORK,java,deps)
    else:
        classes=target/'classes';source_sha=b.sha(source)
        if b.sha(target/'NativeDeux.java')!=source_sha:raise RuntimeError('Existing variant source differs')
    print(json.dumps({'name':name,'sourceSHA256':source_sha,'compiled':True,'workers':args.workers,'intraTime':args.intra}),flush=True)
    if args.run:
        if list(target.glob(f'screen-{args.round}.*')):raise RuntimeError('Use a fresh round; prior screen evidence must not be overwritten')
        cpu_stat=Path('/sys/fs/cgroup/cpu.stat');before_cpu_stat=cpu_stat.read_text() if cpu_stat.exists() else None
        record=b.measure(name,args.round,'screen',classes,WORK,java,deps,ROOT/'web/analysis/models/deux',args.audio,args.start)
        record.update(scope='host-only screen; inferenceMillis sums overlapping calls, not elapsed critical path',audioSHA256=b.sha(args.audio),startSample=args.start,sourceSHA256=source_sha,
            sharedSourceHashes={p.name:b.sha(p) for p in shared.glob('*.java')},runtimeSha256=b.sha(deps[-1]),modelManifestSha256=b.sha(ROOT/'web/analysis/models/deux/manifest.json'),host=b.host_metadata())
        record.update(cgroupCpuStatBefore=before_cpu_stat,cgroupCpuStatAfter=cpu_stat.read_text() if cpu_stat.exists() else None)
        (target/f'screen-{args.round}.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record,indent=2),flush=True)


if __name__=='__main__':main()
