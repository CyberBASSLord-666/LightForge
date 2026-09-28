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

/** Actual original graphs: complete outputs, admitted/cache paths and parallel JNI retirement. */
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
        NativeInferenceProfile profile=new NativeInferenceProfile();profile.captureStartMemory();
        try(NativeDeux owned=runner){owned.predict(audio,start,output,null,()->false,null,profile);}
        NativeInferenceProfile.Snapshot snapshot=profile.finish("completed");
        require("27".equals(summary(snapshot,"graphRecords")),"Original graph inventory changed");
        require("0".equals(summary(snapshot,"droppedGraphRecords")),"Graph observations were dropped");
        int forcedBindings=expectedTemporalCalls==60?(summary(snapshot,"temporalConfig").endsWith("-w4-b1")?4:8):0;
        int calls=0,timeGraphs=0,frequencyGraphs=0,heads=0,fronts=0,pipelines=0;
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
                if(count==60)pipelines++;
                timeGraphs++;
            }else if(graph.matches("block-[0-9]{2}-frequency")){
                int block=Integer.parseInt(graph.substring(6,8));require(block<12&&count==11,"Partial frequency frame coverage");frequencyGraphs++;
            }else if(graph.equals("head-0")||graph.equals("head-1")){require(count==11,"Partial reconstruction coverage");heads++;}
            else {require(graph.equals("front")&&count==1,"Unknown graph or repeated front");fronts++;}
            calls+=count;
        }
        require(timeGraphs==12&&frequencyGraphs==12&&heads==2&&fronts==1,"Incomplete graph coverage");
        require(calls==Integer.parseInt(summary(snapshot,"inferenceCount")),"Coordinator intervals were confused with native Run calls");
        boolean foundInference=false;
        for(String record:snapshot.records())if(record.startsWith("schema=native-inference-stage-v1 stage=inference ")){
            foundInference=true;
            require(Integer.parseInt(field(record,"samples"))==335-14*pipelines,"Pipeline coordinator intervals were counted as old waves or native Runs");
        }
        require(foundInference,"The complete inference critical-path stage was not observed");
        require(snapshot.recordCount()==43,"Full-passage profile topology changed");
        fullOutput(output);
        return new JSONObject().put("outputSha256",hash(output)).put("outputBytes",output.length()).put("finite",true)
            .put("inferenceCalls",calls).put("profileRecords",new JSONArray(Arrays.asList(snapshot.records())));
    }
    private static boolean insideNativeRun(Thread worker){
        if(!worker.isAlive())return false;
        for(StackTraceElement frame:worker.getStackTrace())
            if(frame.isNativeMethod()&&frame.getClassName().startsWith("ai.onnxruntime.")&&frame.getMethodName().equals("run"))return true;
        return false;
    }
    private static JSONObject cancelDuringNative(File models,File audio,long start,File output,boolean interrupt)throws Exception {
        Set<Thread> workers=Collections.newSetFromMap(new ConcurrentHashMap<Thread,Boolean>());
        AtomicReference<Throwable> failure=new AtomicReference<>();AtomicBoolean interruptPreserved=new AtomicBoolean();
        NativeDeux runner=new NativeDeux(models,parallel(8),()->workers.add(Thread.currentThread()));
        Thread owner=new Thread(()->{
            try{runner.predict(audio,start,output,null,()->false);}
            catch(Throwable error){failure.set(error);}
            finally{interruptPreserved.set(Thread.currentThread().isInterrupted());runner.close();}
        },"native-deux-qualification-owner");
        int observed=0;
        try{
            owner.start();long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(90);
            while(owner.isAlive()&&System.nanoTime()<deadline){
                int active=0;for(Thread worker:workers)if(insideNativeRun(worker))active++;
                if(active>=2){observed=active;break;}
                Thread.sleep(10);
            }
            require(observed>=2,"Did not observe two concurrent real native Run stacks; no during-JNI cancellation proof");
            require(NativeDeux.INFERENCE_GATE.availablePermits()==0,"Concurrent native execution did not retain the process gate");
            if(interrupt)owner.interrupt();else runner.cancel();
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
        require(!output.exists(),"Cancellation committed a stem output");
        for(Thread worker:workers)require(!worker.isAlive(),"A parallel worker survived the prediction owner");
        require(NativeDeux.INFERENCE_GATE.availablePermits()==1,"Cancellation released ownership before all workers retired");
        require(!interrupt||interruptPreserved.get(),"Worker retirement consumed the owner's interrupt flag");
        return new JSONObject().put("mode",interrupt?"owner-interrupt":"runner-cancel")
            .put("observedNativeWorkers",observed).put("allObservedWorkersRetired",true).put("ownerRetired",true)
            .put("noOutputCommitted",true).put("gateHeldWhileNative",true).put("gateReleased",true).put("interruptionReported",true)
            .put("ownerInterruptPreserved",interrupt?Boolean.TRUE:JSONObject.NULL);
    }
    public static void main(String[] args)throws Exception {
        if(args.length!=3)throw new IllegalArgumentException("models audio new-output-directory");
        File models=new File(args[0]),audio=new File(args[1]),directory=new File(args[2]);
        require(!directory.exists()&&directory.mkdirs(),"Use a fresh calibration proof directory");
        File cache=new File(directory,"policy.bin");long startSample=661500;
        JSONObject runs=new JSONObject();
        JSONObject reference=run(new NativeDeux(models),audio,startSample,new File(directory,"reference.f32"),15);
        runs.put("reference",reference);
        JSONObject calibrated=run(new NativeDeux(models,cache,()->Long.MAX_VALUE),audio,startSample,new File(directory,"calibrated.f32"),0);
        runs.put("calibrated",calibrated);
        int cores=Runtime.getRuntime().availableProcessors();
        require(Integer.toString(cores>=4?2:1).equals(field(calibrated.getJSONArray("profileRecords").getString(0),"schedulerCalibrationCount")),"Calibration probes did not cover each eligible graph family");
        require(cache.isFile()&&cache.length()<NativeExecutionPolicy.MAX_BYTES,"Complete device decision was not persisted");
        byte[] committed=Files.readAllBytes(cache.toPath());
        JSONObject cached=run(new NativeDeux(models,cache,()->Long.MAX_VALUE),audio,startSample,new File(directory,"cached.f32"),0);
        runs.put("cached",cached);
        require("unavailable".equals(field(cached.getJSONArray("profileRecords").getString(0),"schedulerCalibrationWallMs")),"Cached decision repeated calibration");
        require(Arrays.equals(committed,Files.readAllBytes(cache.toPath())),"Cached execution rewrote the decision");
        require(calibrated.getInt("inferenceCalls")==cached.getInt("inferenceCalls"),"Unchanged headroom did not reuse the calibrated geometry");
        JSONObject four=run(new NativeDeux(models,parallel(4),null),audio,startSample,new File(directory,"four.f32"),60);
        require(parallel(4).id().equals(field(four.getJSONArray("profileRecords").getString(0),"temporalConfig")),"Four-worker host fixture was not executed");
        runs.put("forcedFour",four);
        JSONArray cancellation=new JSONArray();
        cancellation.put(cancelDuringNative(models,audio,startSample,new File(directory,"cancelled.f32"),false));
        cancellation.put(cancelDuringNative(models,audio,startSample,new File(directory,"interrupted.f32"),true));
        JSONObject eight=run(new NativeDeux(models,parallel(8),null),audio,startSample,new File(directory,"recovered.f32"),60);
        require(parallel(8).id().equals(field(eight.getJSONArray("profileRecords").getString(0),"temporalConfig")),"Eight-worker recovery fixture was not executed");
        runs.put("recoveredEight",eight);
        String expected=reference.getString("outputSha256");
        for(String name:new String[]{"calibrated","cached","forcedFour","recoveredEight"})
            require(expected.equals(runs.getJSONObject(name).getString("outputSha256")),"Full finite Float32 output changed for "+name);
        File cancelledCache=new File(directory,"cancelled-policy.bin"),cancelledOutput=new File(directory,"cancelled-calibration.f32");
        AtomicBoolean cancel=new AtomicBoolean();boolean stopped=false;
        try(NativeDeux runner=new NativeDeux(models,cancelledCache,()->Long.MAX_VALUE)){
            runner.predict(audio,startSample,cancelledOutput,(progress,message)->{if(message.startsWith("Optimizing"))cancel.set(true);},cancel::get);
        }catch(InterruptedIOException expectedCancellation){stopped=true;}
        require(stopped&&!cancelledCache.exists()&&!cancelledOutput.exists(),"Early calibration cancellation committed partial state");
        require(NativeDeux.INFERENCE_GATE.availablePermits()==1,"Cancelled calibration leaked the process gate");
        JSONObject result=new JSONObject().put("schema","lightforge.native-scheduler-calibration.v2").put("passed",true)
            .put("samplesPerStem",SAMPLES).put("outputBytes",OUTPUT_BYTES).put("startSample",startSample)
            .put("availableProcessors",cores)
            .put("runs",runs).put("forcedWorkers",new JSONArray(Arrays.asList(4,8))).put("forcedTimeBatch",1)
            .put("cacheReused",true).put("cacheBytes",committed.length).put("cancelledCalibrationIsolated",true)
            .put("duringNativeCancellation",cancellation).put("finite",true).put("byteIdentical",true);
        System.out.println(result.toString());
    }
}
