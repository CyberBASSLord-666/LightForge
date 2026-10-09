package com.cyberbasslord.lightforge;

import java.io.*;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONArray;
import org.json.JSONObject;

/** Actual original graphs: unfunded work stays baseline, old graph caches are ignored, JNI retires. */
public final class NativeDeuxCalibrationTest {
    private static final int SAMPLES=573300, OUTPUT_BYTES=2*SAMPLES*4;
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
    private static String hash(File file)throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");byte[] buffer=new byte[65536];
        try(InputStream in=new FileInputStream(file)){int count;while((count=in.read(buffer))!=-1)digest.update(buffer,0,count);}
        StringBuilder value=new StringBuilder();for(byte b:digest.digest())value.append(String.format(Locale.ROOT,"%02x",b&255));return value.toString();
    }
    private static String field(String record,String name){
        for(String value:record.split(" "))if(value.startsWith(name+"="))return value.substring(name.length()+1);
        throw new AssertionError("Missing profile field "+name);
    }
    private static String summary(NativeInferenceProfile.Snapshot profile,String name){return field(profile.records()[0],name);}
    private static void fullOutput(File file)throws Exception {
        require(file.length()==OUTPUT_BYTES,"Incomplete calibrated output");
        try(DataInputStream in=new DataInputStream(new BufferedInputStream(new FileInputStream(file)))){
            for(int i=0;i<2*SAMPLES;i++)require(Float.isFinite(Float.intBitsToFloat(Integer.reverseBytes(in.readInt()))),"Nonfinite calibrated output");
        }
    }
    private static NativeExecutionPolicy.Config parallel(int workers){
        NativeExecutionPolicy.Key key=new NativeExecutionPolicy.Key("qualification-model","qualification-runtime","qualification-os","qualification-device",8);
        for(NativeExecutionPolicy.Config candidate:NativeExecutionPolicy.temporalCandidates(key,Long.MAX_VALUE))
            if(candidate.temporalWorkers==workers&&candidate.timeBatch==1)return candidate;
        throw new AssertionError("Missing explicitly reviewed host parallel configuration: "+workers);
    }
    private static JSONObject run(NativeDeux runner,File audio,long start,File output,int expectedTemporalCalls)throws Exception {
        return run(runner,audio,start,output,expectedTemporalCalls,-1,false);
    }
    private static JSONObject run(NativeDeux runner,File audio,long start,File output,int expectedTemporalCalls,int remainingUseful,boolean policyExpected)throws Exception {
        NativeInferenceProfile profile=new NativeInferenceProfile();profile.captureStartMemory();
        if(remainingUseful==35)profile.enableCandidateEvidence();
        try(NativeDeux owned=runner){
            if(remainingUseful<0)owned.predict(audio,start,output,null,()->false,null,profile);
            else owned.predict(audio,start,output,null,()->false,null,profile,remainingUseful);
        }
        NativeInferenceProfile.Snapshot snapshot=profile.finish("completed");
        require("27".equals(summary(snapshot,"graphRecords")),"Original graph inventory changed");
        require("0".equals(summary(snapshot,"droppedGraphRecords")),"Graph observations were dropped");
        int forcedBindings=expectedTemporalCalls==60?(summary(snapshot,"temporalConfig").endsWith("-w4-b1")?4:8):0;
        int calls=0,timeGraphs=0,frequencyGraphs=0,heads=0,fronts=0,timePipelines=0,frequencyPipelines=0,workerCalls=0;
        Set<String> graphs=new HashSet<>();
        for(String record:snapshot.records())if(record.startsWith("schema=native-inference-graph-v2 ")){
            String graph=field(record,"graph");int count=Integer.parseInt(field(record,"runCount"));
            require(graphs.add(graph),"Duplicate graph observation");
            if(graph.matches("block-[0-9]{2}-time")){
                int block=Integer.parseInt(graph.substring(6,8));require(block<12,"Unknown temporal graph");
                require(count==15||count==60,"Partial temporal band coverage");
                if(expectedTemporalCalls!=0)require(count==expectedTemporalCalls,"Wrong forced temporal geometry");
                int bindings=Integer.parseInt(field(record,"tensorBindCount"));
                require(count==15?bindings==15:(bindings==4||bindings==8),"Persistent temporal bindings were confused with native Run calls");
                if(forcedBindings!=0)require(bindings==forcedBindings,"Forced worker count did not match persistent tensor slots");
                String copyScope=count==60?"nested-in-inference-pipeline":"sequential-intervals";
                require(copyScope.equals(field(record,"packWallScope"))&&copyScope.equals(field(record,"scatterWallScope")),"Temporal copy intervals lost their enclosing pipeline scope");
                if(count==60)for(String copy:new String[]{"pack","scatter"})
                    require("unavailable-overlapping-intervals".equals(field(record,copy+"ProcessCpuScope"))&&"unavailable".equals(field(record,copy+"ProcessCpuMs")),"Nested copies double-counted the pipeline's process CPU");
                if(count==60){timePipelines++;workerCalls+=count;}
                timeGraphs++;
            }else if(graph.matches("block-[0-9]{2}-frequency")){
                int block=Integer.parseInt(graph.substring(6,8));require(block<12&&(count==11||count==82),"Partial frequency frame coverage");
                if(expectedTemporalCalls!=0)require(count==(expectedTemporalCalls==60?82:11),"Wrong forced frequency geometry");
                int bindings=Integer.parseInt(field(record,"tensorBindCount"));
                require(count==11?bindings==11:(bindings==5||bindings==9),"Frequency bindings lost a worker or the five-frame tail");
                if(count==82){
                    require(forcedBindings==0||bindings==forcedBindings+1,"Forced frequency bindings did not include every worker and tail");
                    for(String copy:new String[]{"pack","scatter"})require(
                        "nested-in-inference-pipeline".equals(field(record,copy+"WallScope"))
                        &&"unavailable-overlapping-intervals".equals(field(record,copy+"ProcessCpuScope"))
                        &&"unavailable".equals(field(record,copy+"ProcessCpuMs")),"Frequency copies lost their enclosing pipeline scope");
                    frequencyPipelines++;workerCalls+=count;
                }
                frequencyGraphs++;
            }else if(graph.equals("head-0")||graph.equals("head-1")){require(count==11,"Partial reconstruction coverage");heads++;}
            else {require(graph.equals("front")&&count==1,"Unknown graph or repeated front");fronts++;}
            calls+=count;
        }
        require(timeGraphs==12&&frequencyGraphs==12&&heads==2&&fronts==1,"Incomplete graph coverage");
        require(calls==Integer.parseInt(summary(snapshot,"inferenceCount")),"Coordinator intervals were confused with native Run calls");
        require(workerCalls==Integer.parseInt(summary(snapshot,"inferenceWorkerRunCount")),"Concurrent temporal/frequency call coverage changed");
        require((forcedBindings==0?NativeExecutionPolicy.baseline(Runtime.getRuntime().availableProcessors()).id():"cpu-i1-j1-d0-sequential-w"+forcedBindings+"-b16")
            .equals(summary(snapshot,"frequencyConfig")),"Frequency configuration did not match complete frame geometry");
        boolean foundInference=false;
        for(String record:snapshot.records())if(record.startsWith("schema=native-inference-stage-v1 stage=inference ")){
            foundInference=true;
            require(Integer.parseInt(field(record,"samples"))==335-14*timePipelines-10*frequencyPipelines,"Pipeline coordinator intervals were counted as old waves or native Runs");
        }
        require(foundInference,"The complete inference critical-path stage was not observed");
        boolean automatic=remainingUseful==35;
        int policyRecords=0,pairRecords=0;
        for(String record:snapshot.records())if(record.startsWith("schema=native-passage-policy-v1 ")){
            policyRecords++;
            if(!automatic)require("0".equals(field(record,"extraNanos"))&&"0".equals(field(record,"qualificationPairs"))
                    &&"0".equals(field(record,"currentJobPairs"))&&"false".equals(field(record,"seeded")),
                    "Unknown or short work financed probes or reused an old graph-only decision");
            else require(Long.parseLong(field(record,"extraNanos"))>0
                    &&Long.parseLong(field(record,"extraNanos"))<=NativePassagePolicy.EXTRA_CAP_NANOS,
                    "Automatic first-passage qualification exceeded its extra-work bound");
            require(!"qualified".equals(field(record,"state")),"One or zero pairs were admitted as complete qualification");
        }else if(record.startsWith("schema=native-passage-pair-v1 ")){
            pairRecords++;
            require(automatic&&"0".equals(field(record,"ordinal"))&&"false".equals(field(record,"candidateFirst")),
                "Automatic initial pair order changed");
            for(String key:new String[]{"finite","exact","fullGeometry","coldSessions"})
                require("true".equals(field(record,key)),"Automatic pair did not preserve "+key);
            require(hash(output).equals(field(record,"outputSha256")),"Automatic pair was not bound to the useful output");
            NativeInferenceProfile.CandidateEvidence auxiliary=profile.candidateEvidence();
            require(auxiliary!=null&&auxiliary.ordinal==0&&!auxiliary.candidateFirst&&auxiliary.workers==Integer.parseInt(field(record,"workers")),
                "Actual paired candidate did not retain its separate bounded observation");
            require("completed".equals(auxiliary.candidate.outcome)&&"completed".equals(auxiliary.baseline.outcome)
                &&auxiliary.baseline.armWallNanos==Long.parseLong(field(record,"baselineNanos"))
                &&auxiliary.candidate.armWallNanos==Long.parseLong(field(record,"candidateNanos")),
                "Auxiliary arm clocks differ from the actual completed paired attempts");
            require(auxiliary.commonPreflightVerifiedModelCount==27&&auxiliary.profile.recordCount()<=NativeInferenceProfile.MAX_RECORDS
                &&"27".equals(summary(auxiliary.profile,"graphRecords"))&&"1727".equals(summary(auxiliary.profile,"inferenceCount")),
                "Actual candidate evidence lost full geometry or common preparation");
            for(NativeInferenceProfile.ArmEvidence arm:new NativeInferenceProfile.ArmEvidence[]{auxiliary.baseline,auxiliary.candidate})
                require(arm.before.verifiedModels==27&&arm.after.verifiedModels==27
                    &&arm.before.extractionAttempts==arm.after.extractionAttempts&&arm.before.extractionBytesRead==arm.after.extractionBytesRead
                    &&arm.before.existingFileChecksumAttempts==arm.after.existingFileChecksumAttempts
                    &&arm.before.existingFileChecksumBytesRead==arm.after.existingFileChecksumBytesRead,
                    "A compared arm paid model extraction or file checksum cost after common preparation");
        }
        if(!automatic)require(profile.candidateEvidence()==null,"Ordinary production/forced execution manufactured a candidate observation");
        require(pairRecords<2&&policyRecords==(policyExpected?1:0)&&snapshot.recordCount()==43+policyRecords+pairRecords,
            "Full-passage profile topology changed");
        if(!automatic)require("unavailable".equals(summary(snapshot,"schedulerCalibrationCount"))
                &&"unavailable".equals(summary(snapshot,"schedulerCalibrationWallMs")),"Unfunded or forced work ran optional probes");
        else require(("1".equals(summary(snapshot,"schedulerCalibrationCount"))||"2".equals(summary(snapshot,"schedulerCalibrationCount")))
                &&Double.parseDouble(summary(snapshot,"schedulerCalibrationWallMs"))>0,
                "Automatic nomination and optional first pair were not measured");
        fullOutput(output);
        return new JSONObject().put("outputSha256",hash(output)).put("outputBytes",output.length()).put("finite",true)
            .put("inferenceCalls",calls).put("profileRecords",new JSONArray(Arrays.asList(snapshot.records())));
    }
    /** Synthetic timings create an old-format positive cache only; they never qualify new execution. */
    private static int legacyWarmCache(File models,File cache)throws Exception {
        NativeExecutionPolicy.Key key=new NativeExecutionPolicy.Key(hash(new File(models,"manifest.json")),
            "native-deux-1.25.1-parallel-b1-v3",System.getProperty("os.name")+":"+System.getProperty("os.version"),
            System.getProperty("os.arch"),Runtime.getRuntime().availableProcessors());
        NativeExecutionPolicy.Config[] temporal=NativeExecutionPolicy.temporalCandidates(key,Long.MAX_VALUE);
        NativeExecutionPolicy.Candidate[] timeTrials=new NativeExecutionPolicy.Candidate[temporal.length];
        for(int i=0;i<temporal.length;i++)timeTrials[i]=new NativeExecutionPolicy.Candidate(temporal[i],legacySamples(true));
        NativeExecutionPolicy.Config[] frequency=NativeExecutionPolicy.candidates(key.cores);
        NativeExecutionPolicy.Candidate[] frequencyTrials=new NativeExecutionPolicy.Candidate[frequency.length];
        for(int i=0;i<frequency.length;i++)frequencyTrials[i]=new NativeExecutionPolicy.Candidate(frequency[i],legacySamples(false));
        NativeExecutionPolicy.save(cache,key,new NativeExecutionPolicy.Calibration(
            NativeExecutionPolicy.selectTemporal(key,Long.MAX_VALUE,temporal,timeTrials),NativeExecutionPolicy.select(key,frequencyTrials)));
        require(NativeExecutionPolicy.load(cache,key).complete(),"Old-format fixture is not a complete valid cache");
        return Math.toIntExact(cache.length());
    }
    private static NativeExecutionPolicy.Sample[] legacySamples(boolean temporal){
        NativeExecutionPolicy.Sample[] samples=new NativeExecutionPolicy.Sample[3];
        for(int i=0;i<samples.length;i++)samples[i]=new NativeExecutionPolicy.Sample(1000000000L,400000000L,
            (i&1)!=0,true,true,temporal?60:0);
        return samples;
    }
    private static boolean insideNativeRun(Thread worker){
        if(!worker.isAlive())return false;
        for(StackTraceElement frame:worker.getStackTrace())
            if(frame.isNativeMethod()&&frame.getClassName().startsWith("ai.onnxruntime.")&&frame.getMethodName().equals("run"))return true;
        return false;
    }
    private static JSONObject cancelDuringNative(File models,File audio,long start,File output,boolean interrupt)throws Exception {
        return cancelDuringNative(models,audio,start,output,interrupt,null);
    }
    private static JSONObject cancelDuringNative(File models,File audio,long start,File output,boolean interrupt,String targetGraph)throws Exception {
        require(targetGraph==null||"block-00-frequency".equals(targetGraph),"Unsupported native cancellation target");
        Set<Thread> workers=Collections.newSetFromMap(new ConcurrentHashMap<Thread,Boolean>());
        AtomicReference<Throwable> failure=new AtomicReference<>();AtomicBoolean interruptPreserved=new AtomicBoolean();
        NativeDeux runner=new NativeDeux(models,parallel(8),()->workers.add(Thread.currentThread()));
        java.lang.reflect.Field lifecycleField=NativeDeux.class.getDeclaredField("lifecycle");
        java.lang.reflect.Field graphField=NativeDeux.class.getDeclaredField("activeGraph");
        java.lang.reflect.Field optionsField=NativeDeux.class.getDeclaredField("activeRun");
        lifecycleField.setAccessible(true);graphField.setAccessible(true);optionsField.setAccessible(true);
        Object lifecycle=lifecycleField.get(runner);
        Thread owner=new Thread(()->{
            try{runner.predict(audio,start,output,null,()->false);}
            catch(Throwable error){failure.set(error);}
            finally{
                interruptPreserved.set(Thread.currentThread().isInterrupted());
                try{runner.close();}
                catch(Throwable closeFailure){
                    Throwable original=failure.get();
                    if(original==null)failure.set(closeFailure);else original.addSuppressed(closeFailure);
                }
            }
        },"native-deux-qualification-owner");
        int observed=0;
        try{
            owner.start();long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(90);
            while(owner.isAlive()&&System.nanoTime()<deadline){
                synchronized(lifecycle){
                    if(targetGraph==null||targetGraph.equals(graphField.get(runner))){
                        int active=0;for(Thread worker:workers)if(insideNativeRun(worker))active++;
                        if(active>=2&&(targetGraph==null||targetGraph.equals(graphField.get(runner)))){
                            require(optionsField.get(runner)!=null,"Observed concurrent native calls without active RunOptions");
                            require(NativeDeux.INFERENCE_GATE.availablePermits()==0,"Concurrent native execution did not retain the process gate");
                            boolean acquired=NativeDeux.INFERENCE_GATE.tryAcquire();
                            if(acquired)NativeDeux.INFERENCE_GATE.release();
                            require(!acquired,"Another inference owner could enter while native workers were running");
                            observed=active;
                            if(interrupt)owner.interrupt();else runner.cancel();
                            break;
                        }
                    }
                }
                Thread.sleep(targetGraph==null?10:1);
            }
            require(observed>=2,"Did not observe two concurrent real native Run stacks in "+(targetGraph==null?"the current graph":targetGraph)+"; no during-JNI cancellation proof");
            deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(60);
            while(owner.isAlive()&&System.nanoTime()<deadline){
                int permits=NativeDeux.INFERENCE_GATE.availablePermits();
                if(permits!=0)for(Thread worker:workers)require(!insideNativeRun(worker),"The gate was released while a worker was still in native Run");
                owner.join(10);
            }
            require(!owner.isAlive(),"Cancellation did not retire the prediction owner within the bounded wait");
        }finally{
            if(owner.isAlive()){runner.cancel();owner.interrupt();owner.join(TimeUnit.SECONDS.toMillis(60));}
            runner.close();
        }
        require(failure.get() instanceof InterruptedIOException,"Cancellation did not report the interrupted prediction: "+failure.get());
        if(!NativeDeux.cleanCancellation(failure.get()))
            throw new AssertionError("Native cancellation contained an unclassified cleanup failure",failure.get());
        require(!output.exists(),"Cancellation committed a stem output");
        synchronized(lifecycle){require(optionsField.get(runner)==null,"RunOptions did not close after native workers retired");}
        require(NativeDeux.INFERENCE_GATE.availablePermits()==1,"Cancellation released ownership before all workers retired");
        for(Thread worker:workers){
            // Pool termination and drained Futures prove all native tasks returned,
            // but ThreadPoolExecutor can become TERMINATED before its last Java
            // Thread leaves the worker-loop epilogue. Reject a surviving JNI Run
            // immediately, then allow that bounded epilogue to finish.
            require(!insideNativeRun(worker),"A parallel worker remained in native Run after the prediction owner retired");
            if(worker.isAlive())worker.join(TimeUnit.SECONDS.toMillis(5));
            require(!worker.isAlive(),"A parallel worker survived the prediction owner");
        }
        require(!interrupt||interruptPreserved.get(),"Worker retirement consumed the owner's interrupt flag");
        JSONObject observation=new JSONObject().put("mode",targetGraph!=null?(interrupt?"frequency-owner-interrupt":"frequency-runner-cancel"):interrupt?"owner-interrupt":"runner-cancel")
            .put("observedNativeWorkers",observed).put("allObservedWorkersRetired",true).put("ownerRetired",true)
            .put("noOutputCommitted",true).put("gateHeldWhileNative",true).put("gateReleased",true).put("interruptionReported",true)
            .put("ownerInterruptPreserved",interrupt?Boolean.TRUE:JSONObject.NULL);
        if(targetGraph!=null)observation.put("observedGraph",targetGraph);
        return observation;
    }
    /** Observe the original synchronous B4 owner in JNI before terminating its actual RunOptions. */
    private static JSONObject cancelBaselineDuringNative(File models,File audio,long start,File output)throws Exception {
        NativeDeux runner=new NativeDeux(models);
        AtomicReference<Throwable> failure=new AtomicReference<>();
        AtomicBoolean temporalStarted=new AtomicBoolean();
        java.lang.reflect.Field lifecycleField=NativeDeux.class.getDeclaredField("lifecycle");
        java.lang.reflect.Field optionsField=NativeDeux.class.getDeclaredField("activeRun");
        lifecycleField.setAccessible(true);optionsField.setAccessible(true);
        Object lifecycle=lifecycleField.get(runner);
        Thread owner=new Thread(()->{
            try{runner.predict(audio,start,output,(progress,message)->{
                if(message.startsWith("Studio temporal detail"))temporalStarted.set(true);
            },()->false);}
            catch(Throwable error){failure.set(error);}
            finally{
                try{runner.close();}
                catch(Throwable closeFailure){
                    Throwable original=failure.get();
                    if(original==null)failure.set(closeFailure);else original.addSuppressed(closeFailure);
                }
            }
        },"native-deux-baseline-cancellation-owner");
        boolean nativeObserved=false;
        try{
            owner.start();long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(90);
            while(owner.isAlive()&&System.nanoTime()<deadline){
                if(temporalStarted.get())synchronized(lifecycle){
                    if(insideNativeRun(owner)){
                        require(optionsField.get(runner)!=null,"Observed native owner without active RunOptions");
                        require(NativeDeux.INFERENCE_GATE.availablePermits()==0,"Baseline JNI did not retain the process gate");
                        boolean acquired=NativeDeux.INFERENCE_GATE.tryAcquire();
                        if(acquired)NativeDeux.INFERENCE_GATE.release();
                        require(!acquired,"Another inference owner could enter during baseline JNI");
                        // This calls setTerminate on the observed, still-owned RunOptions.
                        runner.cancel();nativeObserved=true;break;
                    }
                }
                Thread.sleep(1);
            }
            require(nativeObserved,"Did not observe the baseline owner in real temporal JNI; no cancellation proof");
            deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(60);
            while(owner.isAlive()&&System.nanoTime()<deadline){
                if(NativeDeux.INFERENCE_GATE.availablePermits()!=0)
                    require(!insideNativeRun(owner),"The gate was released while the baseline owner remained in JNI");
                owner.join(10);
            }
            require(!owner.isAlive(),"Baseline cancellation did not retire the native owner within the bounded wait");
        }finally{
            if(owner.isAlive()){runner.cancel();owner.interrupt();owner.join(TimeUnit.SECONDS.toMillis(60));}
            runner.close();
        }
        Throwable stopped=failure.get();
        require(stopped instanceof InterruptedIOException,"Baseline native cancellation was not normalized: "+stopped);
        require(stopped.getCause() instanceof ai.onnxruntime.OrtException,
            "Cancellation did not retain the real native Run failure; a cooperative boundary is insufficient");
        require(stopped.getSuppressed().length==0&&stopped.getCause().getSuppressed().length==0,
            "Baseline cancellation contained an unclassified cleanup failure");
        synchronized(lifecycle){require(optionsField.get(runner)==null,"RunOptions did not close after the native owner retired");}
        require(!output.exists(),"Baseline cancellation committed an output");
        require(NativeDeux.INFERENCE_GATE.availablePermits()==1,"Baseline cancellation did not release exclusive ownership");
        File[] leftovers=output.getParentFile().listFiles((parent,name)->name.endsWith(".partial")||name.endsWith(".tmp"));
        require(leftovers!=null&&leftovers.length==0,"Baseline cancellation leaked a temporary output");
        return new JSONObject().put("mode","baseline-runner-cancel").put("observedNativeOwner",true)
            .put("activeRunOptionsObserved",true).put("gateHeldWhileNative",true).put("exclusiveGate",true)
            .put("ownerRetired",true).put("runOptionsClosed",true).put("gateReleased",true)
            .put("interruptionReported",true).put("originalOrtCauseRetained",true).put("noSuppressedCleanupFailures",true)
            .put("noOutputCommitted",true).put("noTemporaryOutputs",true);
    }
    public static void main(String[] args)throws Exception {
        boolean baselineCancellation=args.length==4&&"baseline-cancellation-only".equals(args[3]);
        boolean ownerInterrupt=args.length==4&&"owner-interrupt-only".equals(args[3]);
        boolean frequencyInterrupt=args.length==4&&"frequency-owner-interrupt-only".equals(args[3]);
        if(args.length!=3&&!baselineCancellation&&!ownerInterrupt&&!frequencyInterrupt)
            throw new IllegalArgumentException("models audio new-output-directory [baseline-cancellation-only|owner-interrupt-only|frequency-owner-interrupt-only]");
        File models=new File(args[0]),audio=new File(args[1]),directory=new File(args[2]);
        require(!directory.exists()&&directory.mkdirs(),"Use a fresh calibration proof directory");
        File cache=new File(directory,"policy.bin");long startSample=661500;
        if(ownerInterrupt||frequencyInterrupt){
            JSONObject cancelled=cancelDuringNative(models,audio,startSample,new File(directory,"interrupted.f32"),true,
                frequencyInterrupt?"block-00-frequency":null);
            File[] leftovers=directory.listFiles((parent,name)->name.endsWith(".partial")||name.endsWith(".tmp"));
            require(leftovers!=null&&leftovers.length==0,"Owner interruption leaked a temporary output");
            System.out.println(new JSONObject().put("schema","lightforge.native-owner-interruption.v1").put("passed",true)
                .put("scope","Targeted during-JNI interruption and retirement only; no complete-output quality or speed claim")
                .put("startSample",startSample).put("cancellation",cancelled).put("noTemporaryOutputs",true).toString());
            return;
        }
        if(baselineCancellation){
            JSONObject cancelled=cancelBaselineDuringNative(models,audio,startSample,new File(directory,"cancelled.f32"));
            JSONObject recovery=run(new NativeDeux(models),audio,startSample,new File(directory,"recovery.f32"),15);
            System.out.println(new JSONObject().put("schema","lightforge.native-baseline-cancellation.v1").put("passed",true)
                .put("samplesPerStem",SAMPLES).put("outputBytes",OUTPUT_BYTES).put("startSample",startSample)
                .put("cancellation",cancelled).put("recovery",recovery).toString());
            return;
        }
        JSONObject runs=new JSONObject();
        JSONObject reference=run(new NativeDeux(models),audio,startSample,new File(directory,"reference.f32"),15);
        runs.put("reference",reference);
        int legacyCacheBytes=legacyWarmCache(models,cache);
        JSONObject unknown=run(new NativeDeux(models,cache,()->Long.MAX_VALUE),audio,startSample,new File(directory,"unknown.f32"),15,-1,true);
        runs.put("unknownWork",unknown);
        int cores=Runtime.getRuntime().availableProcessors();
        require(!cache.exists(),"Graph-only legacy cache survived as a complete-passage decision");
        JSONObject shortWork=run(new NativeDeux(models,cache,()->Long.MAX_VALUE),audio,startSample,new File(directory,"short.f32"),15,1,true);
        runs.put("shortWork",shortWork);
        require(!cache.exists(),"One useful passage created an unqualified cache");
        JSONObject automatic=run(new NativeDeux(models,cache,()->Long.MAX_VALUE),audio,startSample,new File(directory,"automatic.f32"),15,35,true);
        runs.put("automaticFirstPassage",automatic);
        require(!cache.exists(),"One automatic pair created a fully qualified cache");
        boolean automaticPairObserved=false;
        JSONArray automaticRecords=automatic.getJSONArray("profileRecords");
        for(int i=0;i<automaticRecords.length();i++)
            if(automaticRecords.getString(i).startsWith("schema=native-passage-pair-v1 "))automaticPairObserved=true;
        JSONObject four=run(new NativeDeux(models,parallel(4),null),audio,startSample,new File(directory,"four.f32"),60);
        require(parallel(4).id().equals(field(four.getJSONArray("profileRecords").getString(0),"temporalConfig")),"Four-worker host fixture was not executed");
        runs.put("forcedFour",four);
        JSONArray cancellation=new JSONArray();
        cancellation.put(cancelDuringNative(models,audio,startSample,new File(directory,"cancelled.f32"),false));
        cancellation.put(cancelDuringNative(models,audio,startSample,new File(directory,"interrupted.f32"),true));
        cancellation.put(cancelDuringNative(models,audio,startSample,new File(directory,"frequency-cancelled.f32"),false,"block-00-frequency"));
        JSONObject eight=run(new NativeDeux(models,parallel(8),null),audio,startSample,new File(directory,"recovered.f32"),60);
        require(parallel(8).id().equals(field(eight.getJSONArray("profileRecords").getString(0),"temporalConfig")),"Eight-worker recovery fixture was not executed");
        runs.put("recoveredEight",eight);
        String expected=reference.getString("outputSha256");
        for(String name:new String[]{"unknownWork","shortWork","automaticFirstPassage","forcedFour","recoveredEight"})
            require(expected.equals(runs.getJSONObject(name).getString("outputSha256")),"Full finite Float32 output changed for "+name);
        File cancelledCache=new File(directory,"cancelled-policy.bin"),cancelledOutput=new File(directory,"cancelled-passage.f32");
        AtomicBoolean cancel=new AtomicBoolean();boolean stopped=false;
        try(NativeDeux runner=new NativeDeux(models,cancelledCache,()->Long.MAX_VALUE)){
            runner.predict(audio,startSample,cancelledOutput,(progress,message)->{if(message.equals("Reading the studio passage"))cancel.set(true);},cancel::get);
        }catch(InterruptedIOException expectedCancellation){stopped=true;}
        require(stopped&&!cancelledCache.exists()&&!cancelledOutput.exists(),"Early passage cancellation committed partial state");
        require(NativeDeux.INFERENCE_GATE.availablePermits()==1,"Cancelled passage leaked the process gate");
        File[] leftovers=directory.listFiles((parent,name)->name.endsWith(".partial")||name.endsWith(".tmp"));
        require(leftovers!=null&&leftovers.length==0,"Cancelled or completed attempt leaked a temporary output");
        JSONObject result=new JSONObject().put("schema","lightforge.native-scheduler-calibration.v4").put("passed",true)
            .put("samplesPerStem",SAMPLES).put("outputBytes",OUTPUT_BYTES).put("startSample",startSample)
            .put("availableProcessors",cores)
            .put("runs",runs).put("forcedWorkers",new JSONArray(Arrays.asList(4,8))).put("forcedTimeBatch",1).put("forcedFrequencyBatch",16)
            .put("unknownWorkNoProbe",true).put("shortWorkNoProbe",true).put("legacyPolicyIgnored",true)
            .put("legacyCacheFixture","synthetic-v2-warmgraph").put("legacyCacheBytes",legacyCacheBytes)
            .put("automaticRemainingUseful",35).put("automaticPairObserved",automaticPairObserved).put("automaticCacheNotQualified",true)
            .put("cancelledPassageIsolated",true).put("noPartialOutputs",true)
            .put("duringNativeCancellation",cancellation).put("finite",true).put("byteIdentical",true);
        System.out.println(result.toString());
    }
}
