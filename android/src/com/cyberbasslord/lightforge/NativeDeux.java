package com.cyberbasslord.lightforge;

import android.content.Context;
import ai.onnxruntime.*;
import org.json.*;
import java.io.*;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.LongSupplier;

/**
 * Bounded native CPU inference for the original, unquantized Deux model.
 * The model retains its complete 13-second context and full attention keys/values.
 * Only independent bands/frames are batched. A single graph is resident at a time.
 * Call predict on the job's worker thread, and cancel/close from any thread.
 */
public final class NativeDeux implements AutoCloseable {
    public static final String RUNTIME_VERSION="1.25.1";
    public interface ExecutionScope { void begin() throws Exception; void end(); }
    public interface Listener { void update(double progress,String message); }
    public interface Cancellation { boolean cancelled(); }
    private static final int FRAMES=NativeDeuxTransform.FRAMES, SAMPLES=NativeDeuxTransform.SAMPLES;
    private static final int FEATURES=256, BANDS=60, TIME_BATCH=4, FREQUENCY_BATCH=128;
    private static final String ASSET_ROOT="analysis/models/deux/";
    // Android can stop an old service while its JNI model constructor is still returning.
    // A replacement job must wait before allocating another heavy model/buffer set.
    // All native separators share the same process and crash lease. Serialize
    // their graph execution when a cancelled service is still retiring.
    static final Semaphore INFERENCE_GATE=new Semaphore(1,true);
    private final Context context;
    private final File modelDirectory;
    private final JSONObject files;
    private final int[] indices,bandsPerFrequency;
    private final int headFrames;
    private final Set<String> verified=new HashSet<>();
    private final Object lifecycle=new Object();
    private volatile boolean cancelled,closed;
    private volatile boolean probing;
    private boolean running;
    private OrtSession.RunOptions activeRun;
    // Direct buffers are reused across every batch/passage and are pinned as outputs.
    // Avoid getValue()/getFloatBuffer(), which allocate another full output copy.
    private FloatBuffer spectrum,values,mask,summed,batchInput,batchOutput;
    private FloatBuffer[] parallelInputs,parallelOutputs;
    private long calibrationBufferBytes;
    private NativeDeuxTransform transform;
    private String activeGraph;
    private boolean firstGraphRun;
    private final NativeExecutionPolicy.Key executionKey;
    private final File executionPolicyFile;
    private final NativePassagePolicy passagePolicy;
    private boolean nominationAttempted;
    private int passageOrdinal;
    private final LongSupplier hostAvailableMemory;
    private final NativeExecutionPolicy.Config hostTemporalConfig;
    private final Runnable hostRunStarted;
    private static final long MEMORY_RESERVE=512L*1024*1024;

    public NativeDeux(Context context) throws Exception {
        this(context.getApplicationContext(),null);
    }

    /** Real-model JVM verification uses the same inference and transforms as Android. */
    public NativeDeux(File modelDirectory) throws Exception { this((Context)null,modelDirectory); }

    /** Explicit host entry point for exercising the same device calibration and cache. */
    NativeDeux(File directory,File executionPolicyFile) throws Exception { this(null,directory,executionPolicyFile); }

    /** Explicit host adapter: supplied bytes describe native memory headroom, not Java heap. */
    NativeDeux(File directory,File executionPolicyFile,LongSupplier availableMemory) throws Exception {
        this(null,directory,executionPolicyFile,availableMemory,null,null);
    }

    /** Exercises the production runner on small CI machines; never reachable from Android. */
    NativeDeux(File directory,NativeExecutionPolicy.Config temporalConfig,Runnable runStarted) throws Exception {
        this(null,directory,null,null,temporalConfig,runStarted);
    }

    private NativeDeux(Context context,File directory) throws Exception { this(context,directory,null); }

    private NativeDeux(Context context,File directory,File hostExecutionPolicyFile) throws Exception {
        this(context,directory,hostExecutionPolicyFile,null,null,null);
    }

    private NativeDeux(Context context,File directory,File hostExecutionPolicyFile,LongSupplier hostAvailableMemory,
            NativeExecutionPolicy.Config hostTemporalConfig,Runnable hostRunStarted) throws Exception {
        this.context=context;
        this.hostAvailableMemory=hostAvailableMemory;this.hostTemporalConfig=hostTemporalConfig;this.hostRunStarted=hostRunStarted;
        if((hostAvailableMemory!=null||hostTemporalConfig!=null||hostRunStarted!=null)&&context!=null)
            throw new IllegalArgumentException("Host execution adapters cannot run on Android.");
        if(hostTemporalConfig!=null&&(hostTemporalConfig.intraThreads!=1||hostTemporalConfig.interThreads!=1
                ||hostTemporalConfig.dynamicBlockBase!=0||hostTemporalConfig.parallel||hostTemporalConfig.timeBatch!=1
                ||(hostTemporalConfig.temporalWorkers!=4&&hostTemporalConfig.temporalWorkers!=8)))
            throw new IllegalArgumentException("Invalid host temporal execution geometry.");
        byte[] source;
        try(InputStream in=context==null?new FileInputStream(new File(directory,"manifest.json")):context.getAssets().open(ASSET_ROOT+"manifest.json")) {
            source=readBounded(in,262144);
        }
        JSONObject manifest=new JSONObject(new String(source,StandardCharsets.UTF_8));
        if(!"bounded-independent-batches-v1".equals(manifest.optString("execution")) || manifest.getInt("frames")!=FRAMES || manifest.getInt("samples")!=SAMPLES || manifest.getInt("fftSize")!=2048 || manifest.getInt("hop")!=441)
            throw new IOException("The native studio model configuration is invalid.");
        indices=integers(manifest.getJSONArray("indices"),3958,0,2049);
        bandsPerFrequency=integers(manifest.getJSONArray("bandsPerFrequency"),1025,1,60);
        headFrames=manifest.optInt("headFrames",FRAMES);
        if(headFrames<1 || headFrames>FRAMES)throw new IOException("Invalid studio output batch size.");
        int[] counts=new int[2050];for(int index:indices)counts[index]++;
        for(int i=0;i<1025;i++)if(counts[i*2]!=bandsPerFrequency[i] || counts[i*2+1]!=bandsPerFrequency[i])
            throw new IOException("The studio frequency map is inconsistent.");
        files=manifest.getJSONObject("files");
        validateEntry("front");validateEntry("head-0");validateEntry("head-1");
        for(int i=0;i<12;i++){validateEntry(blockName(i)+"-time");validateEntry(blockName(i)+"-frequency");}
        this.modelDirectory=context==null?directory.getCanonicalFile():new File(context.getCacheDir(),"native-deux/"+hex(MessageDigest.getInstance("SHA-256").digest(source)));
        if(!this.modelDirectory.isDirectory() && !this.modelDirectory.mkdirs())throw new IOException("Not enough storage to prepare studio analysis.");
        executionKey=new NativeExecutionPolicy.Key(hex(MessageDigest.getInstance("SHA-256").digest(source)),
            "native-deux-"+RUNTIME_VERSION+"-complete-passage-v1",
            context==null?System.getProperty("os.name")+":"+System.getProperty("os.version"):android.os.Build.FINGERPRINT,
            context==null?System.getProperty("os.arch"):android.os.Build.MANUFACTURER+":"+android.os.Build.MODEL+":"+Arrays.toString(android.os.Build.SUPPORTED_ABIS),
            Runtime.getRuntime().availableProcessors());
        executionPolicyFile=context==null?hostExecutionPolicyFile:new File(this.modelDirectory,"passage-policy-v1.bin");
        NativePassagePolicy.Seed seed=executionPolicyFile==null?null:NativePassagePolicy.load(executionPolicyFile,executionKey.identity());
        passagePolicy=new NativePassagePolicy(executionKey.identity(),seed);
        nominationAttempted=seed!=null;
    }

    /** Output contains vocals then accompaniment, each exactly 573300 float32 LE samples. */
    public void predict(File audio,long startSample,File output,Listener listener,Cancellation cancellation) throws Exception {
        predict(audio,startSample,output,listener,cancellation,null);
    }

    public synchronized void predict(File audio,long startSample,File output,Listener listener,Cancellation cancellation,ExecutionScope scope) throws Exception {
        predict(audio,startSample,output,listener,cancellation,scope,null);
    }

    /** Legacy callers have no trustworthy remaining-work count and stay on the baseline. */
    synchronized void predict(File audio,long startSample,File output,Listener listener,Cancellation cancellation,
            ExecutionScope scope,NativeInferenceProfile profile) throws Exception {
        predict(audio,startSample,output,listener,cancellation,scope,profile,-1);
    }

    /** remainingUseful includes this passage; unknown work cannot finance optional probes. */
    synchronized void predict(File audio,long startSample,File output,Listener listener,Cancellation cancellation,
            ExecutionScope scope,NativeInferenceProfile profile,int remainingUseful) throws Exception {
        synchronized(lifecycle) {
            if(closed || cancelled)throw new InterruptedIOException("Studio analysis was cancelled.");
            running=true;
        }
        NativeDeuxTransform.Check check=()->check(cancellation);
        Attempt useful=null,candidate=null;boolean acquired=false,entered=false;
        int ordinal=passageOrdinal++;
        try {
            check.check();
            NativeInferenceProfile.Timing gateStarted=profile==null?null:NativeInferenceProfile.started();
            try {
                while(!INFERENCE_GATE.tryAcquire(250,TimeUnit.MILLISECONDS))check.check();
                acquired=true;check.check();
            } finally { if(profile!=null)profile.addGateWait(NativeInferenceProfile.elapsed(gateStarted)); }
            if(scope!=null){scope.begin();entered=true;}
            phase("cache-check-start");
            if(audio.getCanonicalFile().equals(output.getCanonicalFile()))throw new IOException("The studio result cannot replace source audio.");
            NativeInferenceProfile.Timing preflightStarted=profile==null?null:NativeInferenceProfile.started();
            try { preflightCache(check,profile); }
            finally { if(profile!=null)profile.addPreflight(NativeInferenceProfile.elapsed(preflightStarted)); }
            NativeInferenceProfile.Timing buffersStarted=profile==null?null:NativeInferenceProfile.started();
            try { ensureBuffers(profile); }
            finally { if(profile!=null)profile.addBufferInit(NativeInferenceProfile.elapsed(buffersStarted)); }
            File directory=output.getAbsoluteFile().getParentFile();
            if(!directory.isDirectory()&&!directory.mkdirs())throw new IOException("Cannot save the studio passage.");
            if(hostTemporalConfig==null&&executionPolicyFile!=null&&!nominationAttempted&&ordinal==0&&remainingUseful>=24){
                nominationAttempted=true;
                nominate(audio,startSample,check,profile);
            }
            NativePassagePolicy.Plan plan=passagePolicy.plan(ordinal,remainingUseful,availableMemory(),executionKey.cores);
            NativeExecutionPolicy.Config baseline=NativeExecutionPolicy.baseline(executionKey.cores);
            if(hostTemporalConfig!=null){
                useful=attempt(audio,startSample,directory,hostTemporalConfig,listener,check,profile,false,Long.MAX_VALUE);
            }else if(plan.action==NativePassagePolicy.Action.PAIR){
                long pairStarted=System.nanoTime();
                NativeExecutionPolicy.Config selected=workers(plan.workers);
                // Both arms carry the same observational work. Probe graph timings remain
                // isolated so durable production totals never double-count a comparison.
                NativeInferenceProfile probeProfile=profile==null?null:new NativeInferenceProfile();
                if(probeProfile!=null)probeProfile.captureStartMemory();
                Listener baselineProgress=pairProgress(listener,plan.candidateFirst?.5:0);
                Listener candidateProgress=pairProgress(listener,plan.candidateFirst?0:.5);
                long probeStarted=0,comparisonStarted=0;boolean charged=false;
                try {
                    if(plan.candidateFirst){
                        probeStarted=System.nanoTime();
                        candidate=attempt(audio,startSample,directory,selected,candidateProgress,check,probeProfile,true,plan.probeBudgetNanos);
                    }
                    useful=attempt(audio,startSample,directory,baseline,baselineProgress,check,profile,false,Long.MAX_VALUE);
                    if(!plan.candidateFirst){
                        probeStarted=System.nanoTime();
                        candidate=attempt(audio,startSample,directory,selected,candidateProgress,check,probeProfile,true,plan.probeBudgetNanos);
                    }
                    comparisonStarted=System.nanoTime();
                    String baselineHash=digest(useful.file,check),candidateHash=digest(candidate.file,check);
                    long extra=System.nanoTime()-pairStarted-useful.nanos;
                    charged=true;
                    passagePolicy.recordPair(new NativePassagePolicy.Pair(ordinal,plan.candidateFirst,useful.nanos,
                        candidate.nanos,extra,baselineHash,true,baselineHash.equals(candidateHash),true,true,plan.workers),
                        remainingUseful<0?-1:Math.max(0,remainingUseful-1));
                    if(profile!=null)profile.noteSchedulerCalibration(extra);
                } catch(ProbeAborted stopped) {
                    // All sessions/worker Runs have retired before this exception reaches here.
                    // A JNI teardown failure is never swallowed as an optional probe failure.
                    if(stopped.getSuppressed().length!=0)throw stopped;
                    check.check();
                    long extra=Math.max(0,System.nanoTime()-probeStarted);
                    charged=true;
                    passagePolicy.probeAborted(stopped.reason,extra);
                    if(profile!=null)profile.noteSchedulerCalibration(extra);
                    if(useful==null)useful=attempt(audio,startSample,directory,baseline,listener,check,profile,false,Long.MAX_VALUE);
                } finally {
                    if(!charged&&probeStarted!=0){
                        long extra=candidate==null?Math.max(0,System.nanoTime()-probeStarted):candidate.nanos;
                        if(candidate!=null&&comparisonStarted!=0)extra+=System.nanoTime()-comparisonStarted;
                        passagePolicy.probeAborted(cancelled||closed||Thread.currentThread().isInterrupted()?"cancelled":"probe-aborted",extra);
                        if(profile!=null)profile.noteSchedulerCalibration(extra);
                    }
                    noteDirectBufferBytes(profile);
                }
                savePassagePolicy();
            }else{
                NativeExecutionPolicy.Config config=plan.action==NativePassagePolicy.Action.CANDIDATE?workers(plan.workers):baseline;
                useful=attempt(audio,startSample,directory,config,listener,check,profile,false,Long.MAX_VALUE);
                passagePolicy.recordOrdinary(useful.nanos);
                savePassagePolicy();
            }
            check.check();
            NativeInferenceProfile.Timing commitStarted=profile==null?null:NativeInferenceProfile.started();
            try { Files.move(useful.file.toPath(),output.toPath(),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING); }
            finally { if(profile!=null)profile.addOutputCommit(NativeInferenceProfile.elapsed(commitStarted)); }
        } finally {
            try {
                if(useful!=null)useful.file.delete();
                if(candidate!=null)candidate.file.delete();
                if(profile!=null&&hostTemporalConfig==null&&executionPolicyFile!=null)profile.notePassagePolicy(passagePolicy.evidenceRecords());
            } finally {
                try {
                    synchronized(lifecycle) {
                        try{if(activeRun!=null){activeRun.close();activeRun=null;}}
                        finally{running=false;if(closed)clearBuffers();}
                    }
                }finally{try{if(entered)scope.end();}finally{if(acquired)INFERENCE_GATE.release();}}
            }
        }
    }

    private static final class Attempt {
        final File file;final long nanos;
        Attempt(File file,long nanos){this.file=file;this.nanos=nanos;}
    }
    private static Listener pairProgress(Listener listener,double offset){
        return listener==null?null:(value,detail)->listener.update(offset+value*.5,"Checking studio execution · "+detail);
    }
    private static class ProbeAborted extends IOException {
        final String reason;
        ProbeAborted(String reason){super("Optional studio qualification ended: "+reason);this.reason=reason;}
    }
    private static final class ProbeRunRejected extends ProbeAborted {
        ProbeRunRejected(OrtException cause){super("runtime-rejected");initCause(cause);}
    }
    private void beginRun() throws OrtException {
        synchronized(lifecycle){
            if(activeRun!=null)throw new IllegalStateException("Native execution has not retired.");
            activeRun=new OrtSession.RunOptions();if(cancelled||closed)activeRun.setTerminate(true);
        }
    }
    private void endRun() {
        synchronized(lifecycle){if(activeRun!=null){activeRun.close();activeRun=null;}}
    }
    /** Complete independent passage with fresh sessions, including first use and retirement. */
    private Attempt attempt(File audio,long startSample,File directory,NativeExecutionPolicy.Config config,
            Listener listener,NativeDeuxTransform.Check outerCheck,NativeInferenceProfile profile,
            boolean probe,long budgetNanos) throws Exception {
        long started=System.nanoTime();
        NativeDeuxTransform.Check check=()->{
            outerCheck.check();
            if(probe&&System.nanoTime()-started>=budgetNanos)throw new ProbeAborted("probe-budget");
        };
        File partial=null;boolean complete=false;
        probing=probe;
        try {
            NativeInferenceProfile.Timing runtimeStarted=profile==null?null:NativeInferenceProfile.started();
            try { beginRun(); }
            finally { if(profile!=null)profile.addRuntimeInit(NativeInferenceProfile.elapsed(runtimeStarted)); }
            progress(listener,0,"Reading the studio passage");
            NativeInferenceProfile.Timing readStarted=profile==null?null:NativeInferenceProfile.started();
            float[][] passage;
            try { passage=NativeDeuxTransform.readStereo(audio,startSample,check); }
            finally { if(profile!=null)profile.addRead(NativeInferenceProfile.elapsed(readStarted)); }
            NativeInferenceProfile.Timing encodeStarted=profile==null?null:NativeInferenceProfile.started();
            try { transform.encode(passage,spectrum,check); }
            finally { if(profile!=null)profile.addEncode(NativeInferenceProfile.elapsed(encodeStarted)); }
            passage=null; // Permit the 13-second PCM window to be reclaimed before neural inference.
            phase("passage-encoded");
            OrtEnvironment environment=OrtEnvironment.getEnvironment();
            try(OrtSession session=open(environment,"front",check,profile)) {
                run(session,spectrum,new long[]{1,2050,FRAMES,2},values,new long[]{1,FRAMES,BANDS,FEATURES},check,profile);
            }
            progress(listener,1.0/15,"Studio frequency analysis");
            for(int block=0;block<12;block++) {
                final int stage=block;
                NativeExecutionPolicy.Config temporal=config;
                if(hostTemporalConfig==null&&!NativeExecutionPolicy.temporalAllowed(temporal,executionKey,availableMemory())){
                    if(probe)throw new ProbeAborted("memory-pressure");
                    passagePolicy.forceBaseline("memory-pressure");
                    config=temporal=NativeExecutionPolicy.baseline(executionKey.cores);
                }
                if(profile!=null)profile.noteSchedulerConfiguration("temporal",temporal.id());
                try(OrtSession session=openConfigured(environment,blockName(block)+"-time",check,profile,temporal)) {
                    runTemporalGraph(session,blockName(block)+"-time",temporal,stage,listener,check,profile);
                }
                if(profile!=null)profile.noteSchedulerConfiguration("frequency",NativeExecutionPolicy.baseline(executionKey.cores).id());
                try(OrtSession session=open(environment,blockName(block)+"-frequency",check,profile)) {
                    for(int first=0;first<FRAMES;first+=FREQUENCY_BATCH) {
                        check.check();int count=Math.min(FREQUENCY_BATCH,FRAMES-first),size=count*BANDS*FEATURES;
                        FloatBuffer in=slice(values,first*BANDS*FEATURES,size),out=slice(batchOutput,0,size);
                        run(session,in,new long[]{count,BANDS,FEATURES},out,new long[]{count,BANDS,FEATURES},check,profile);
                        NativeInferenceProfile.Timing scatterStarted=profile==null?null:NativeInferenceProfile.started();
                        try { copy(out,0,values,first*BANDS*FEATURES,size); }
                        finally { if(profile!=null)profile.addScatter(blockName(block)+"-frequency",NativeInferenceProfile.elapsed(scatterStarted)); }
                        progress(listener,(1+stage+.75+.25*(first+count)/FRAMES)/15,"Studio harmonic detail · layer "+(stage+1)+"/12");
                    }
                }
            }
            File parent=directory;
            if(!parent.isDirectory() && !parent.mkdirs())throw new IOException("Cannot save the studio passage.");
            partial=File.createTempFile(".native-deux-",".partial",parent);
            try(FileOutputStream stream=new FileOutputStream(partial)) {
                for(int head=0;head<2;head++) {
                    try(OrtSession session=open(environment,"head-"+head,check,profile)) {
                        if(headFrames==FRAMES) {
                            run(session,values,new long[]{1,FRAMES,BANDS,FEATURES},mask,new long[]{1,indices.length,FRAMES,2},check,profile);
                        } else for(int first=0;first<FRAMES;first+=headFrames) {
                            check.check();int count=Math.min(headFrames,FRAMES-first);
                            FloatBuffer in=slice(values,first*BANDS*FEATURES,count*BANDS*FEATURES);
                            FloatBuffer out=slice(batchOutput,0,indices.length*count*2);
                            run(session,in,new long[]{1,count,BANDS,FEATURES},out,new long[]{1,indices.length,count,2},check,profile);
                            NativeInferenceProfile.Timing scatterStarted=profile==null?null:NativeInferenceProfile.started();
                            try { for(int bin=0;bin<indices.length;bin++)copy(out,bin*count*2,mask,(bin*FRAMES+first)*2,count*2); }
                            finally { if(profile!=null)profile.addScatter("head-"+head,NativeInferenceProfile.elapsed(scatterStarted)); }
                            progress(listener,(13+head+(first+count)/(double)FRAMES)/15,"Studio "+(head==0?"vocal":"accompaniment")+" reconstruction");
                        }
                    }
                    NativeInferenceProfile.Timing decodeStarted=profile==null?null:NativeInferenceProfile.started();
                    float[] pcm;
                    try { pcm=transform.decode(spectrum,mask,indices,bandsPerFrequency,summed,check); }
                    finally { if(profile!=null)profile.addDecode("head-"+head,NativeInferenceProfile.elapsed(decodeStarted)); }
                    NativeInferenceProfile.Timing writeStarted=profile==null?null:NativeInferenceProfile.started();
                    try { writeFloats(stream,pcm,check); }
                    finally { if(profile!=null)profile.addWrite(NativeInferenceProfile.elapsed(writeStarted)); }
                    progress(listener,(14.0+head)/15,head==0?"Studio vocals recovered":"Studio accompaniment recovered");
                }
                NativeInferenceProfile.Timing flushStarted=profile==null?null:NativeInferenceProfile.started();
                try { stream.getFD().sync(); }
                finally { if(profile!=null)profile.addFlush(NativeInferenceProfile.elapsed(flushStarted)); }
            }
            check.check();
            if(partial.length()!=2L*SAMPLES*4)throw new IOException("The studio passage is incomplete.");
            complete=true;
        } finally {
            try { endRun(); }
            catch(RuntimeException|Error failure){complete=false;throw failure;}
            finally { probing=false;if(!complete&&partial!=null)partial.delete(); }
        }
        return new Attempt(partial,System.nanoTime()-started);
    }

    /** Stops active ORT kernels as soon as the runtime reaches a cancellation point. */
    public void cancel() {
        synchronized(lifecycle) {
            cancelled=true;
            if(activeRun!=null)try{activeRun.setTerminate(true);}catch(OrtException ignored){/* Checks also observe cancelled. */}
        }
    }

    /** Nonblocking; active inference owns and closes its native resources in finally. */
    @Override public void close() {
        synchronized(lifecycle) {closed=true;cancel();if(!running)clearBuffers();}
    }

    private void check(Cancellation cancellation) throws InterruptedIOException {
        if(cancelled || closed || Thread.currentThread().isInterrupted() || (cancellation!=null&&cancellation.cancelled()))
            throw new InterruptedIOException("Studio analysis was cancelled.");
    }

    private void ensureBuffers(NativeInferenceProfile profile) {
        if(buffersReady()){noteDirectBufferBytes(profile);return;}
        // Direct allocations can fail independently.  Do not publish the transform
        // until the complete buffer set exists: transform used to be assigned first,
        // so a later OOM made the next passage skip initialization and dereference a
        // missing buffer.  Clearing a legacy partial set first also makes retries
        // deterministic after a process survives an allocation failure.
        clearBuffers();
        NativeDeuxTransform nextTransform=new NativeDeuxTransform();
        FloatBuffer nextSpectrum=direct(NativeDeuxTransform.SPECTRUM_FLOATS);
        FloatBuffer nextSummed=direct(NativeDeuxTransform.SPECTRUM_FLOATS);
        FloatBuffer nextValues=direct(FRAMES*BANDS*FEATURES);
        FloatBuffer nextMask=direct(indices.length*FRAMES*2);
        int size=Math.max(TIME_BATCH*FRAMES*FEATURES,FREQUENCY_BATCH*BANDS*FEATURES);
        if(headFrames<FRAMES)size=Math.max(size,headFrames*indices.length*2);
        FloatBuffer nextBatchInput=direct(size);
        FloatBuffer nextBatchOutput=direct(size);
        transform=nextTransform;spectrum=nextSpectrum;summed=nextSummed;values=nextValues;mask=nextMask;
        batchInput=nextBatchInput;batchOutput=nextBatchOutput;
        if(profile!=null)profile.noteDirectBufferBytes(4L*(spectrum.capacity()+summed.capacity()+values.capacity()+mask.capacity()+batchInput.capacity()+batchOutput.capacity()));
    }
    private boolean buffersReady(){return transform!=null&&spectrum!=null&&values!=null&&mask!=null&&summed!=null&&batchInput!=null&&batchOutput!=null;}
    private void clearBuffers(){parallelInputs=null;parallelOutputs=null;spectrum=null;values=null;mask=null;summed=null;batchInput=null;batchOutput=null;transform=null;}

    private void savePassagePolicy(){
        if(executionPolicyFile==null)return;
        NativePassagePolicy.Seed seed=passagePolicy.qualifiedSeed();
        if(seed==null){if(executionPolicyFile.exists()&&!executionPolicyFile.delete())scheduler("cache=delete-unavailable");return;}
        try{NativePassagePolicy.save(executionPolicyFile,executionKey.identity(),seed);}
        catch(IOException unavailable){scheduler("cache=write-unavailable");}
    }
    private NativeExecutionPolicy.Config workers(int count){
        for(NativeExecutionPolicy.Config config:NativeExecutionPolicy.temporalCandidates(executionKey,Long.MAX_VALUE))
            if(config.temporalWorkers==count)return config;
        throw new IllegalArgumentException("Unqualified temporal worker count.");
    }

    /** Native allocations are outside the Java heap; Runtime.freeMemory is not an admission signal. */
    private long availableMemory(){
        long available;
        try{
            if(hostAvailableMemory!=null)available=hostAvailableMemory.getAsLong();
            else if(context!=null){
                Object service=context.getSystemService(Context.ACTIVITY_SERVICE);
                if(!(service instanceof android.app.ActivityManager))return 0;
                android.app.ActivityManager.MemoryInfo info=new android.app.ActivityManager.MemoryInfo();
                ((android.app.ActivityManager)service).getMemoryInfo(info);
                if(info.lowMemory||info.availMem<=info.threshold)return 0;
                available=info.availMem-Math.max(0,info.threshold);
            }else{
                Object bean=Class.forName("java.lang.management.ManagementFactory").getMethod("getOperatingSystemMXBean").invoke(null);
                Class<?> type=Class.forName("com.sun.management.OperatingSystemMXBean");
                java.lang.reflect.Method method;
                try{method=type.getMethod("getFreeMemorySize");}
                catch(NoSuchMethodException oldRuntime){method=type.getMethod("getFreePhysicalMemorySize");}
                available=((Number)method.invoke(bean)).longValue();
                Path limit=Paths.get("/sys/fs/cgroup/memory.max"),used=Paths.get("/sys/fs/cgroup/memory.current");
                if(Files.isReadable(limit)&&Files.isReadable(used)){
                    String maximum=readCounter(limit);
                    if(!"max".equals(maximum)){
                        long cap=Long.parseLong(maximum),current=Long.parseLong(readCounter(used));
                        if(cap<=0||current<0)return 0;
                        available=Math.min(available,Math.max(0,cap-current));
                    }
                }
            }
        }catch(Exception unavailable){return 0;}
        return available>MEMORY_RESERVE?available-MEMORY_RESERVE:0;
    }
    private static String readCounter(Path path)throws IOException{
        try(InputStream in=Files.newInputStream(path)){return new String(readBounded(in,64),StandardCharsets.US_ASCII).trim();}
    }

    private void ensureParallelBuffers(int workers,NativeInferenceProfile profile){
        if(parallelInputs==null||parallelInputs.length<workers){
            FloatBuffer[] inputs=new FloatBuffer[workers],outputs=new FloatBuffer[workers];
            inputs[0]=batchInput;outputs[0]=batchOutput;
            for(int i=1;i<workers;i++){
                inputs[i]=parallelInputs!=null&&i<parallelInputs.length?parallelInputs[i]:direct(FRAMES*FEATURES);
                outputs[i]=parallelOutputs!=null&&i<parallelOutputs.length?parallelOutputs[i]:direct(FRAMES*FEATURES);
            }
            parallelInputs=inputs;parallelOutputs=outputs;
        }
        noteDirectBufferBytes(profile);
    }
    private void noteDirectBufferBytes(NativeInferenceProfile profile){
        if(profile!=null){
            long floats=(long)spectrum.capacity()+summed.capacity()+values.capacity()+mask.capacity()+batchInput.capacity()+batchOutput.capacity();
            if(parallelInputs!=null)for(int i=1;i<parallelInputs.length;i++)floats+=(long)parallelInputs[i].capacity()+parallelOutputs[i].capacity();
            profile.noteDirectBufferBytes(4L*floats+calibrationBufferBytes);
        }
    }

    /** Original graphs and all 1301 attention frames; only independent bands may overlap. */
    private void runTemporalGraph(OrtSession session,String graph,NativeExecutionPolicy.Config config,int stage,
            Listener listener,NativeDeuxTransform.Check check,NativeInferenceProfile profile)throws Exception{
        if(config.temporalWorkers>1){
            runTemporalPipeline(session,graph,config,stage,listener,check,profile);return;
        }
        int batch=config.timeBatch;
        for(int first=0;first<BANDS;first+=batch){
            check.check();int count=Math.min(batch,BANDS-first),size=count*FRAMES*FEATURES;
            FloatBuffer input=slice(batchInput,0,size),output=slice(batchOutput,0,size);
            NativeInferenceProfile.Timing packing=profile==null?null:NativeInferenceProfile.started();
            try{for(int b=0;b<count;b++)for(int f=0;f<FRAMES;f++)
                copy(values,(f*BANDS+first+b)*FEATURES,input,(b*FRAMES+f)*FEATURES,FEATURES);
            }finally{if(profile!=null)profile.addPack(graph,NativeInferenceProfile.elapsed(packing));}
            run(session,input,new long[]{count,FRAMES,FEATURES},output,new long[]{count,FRAMES,FEATURES},check,profile);
            check.check();
            NativeInferenceProfile.Timing scattering=profile==null?null:NativeInferenceProfile.started();
            try{for(int b=0;b<count;b++)for(int f=0;f<FRAMES;f++)
                copy(output,(b*FRAMES+f)*FEATURES,values,(f*BANDS+first+b)*FEATURES,FEATURES);
            }finally{if(profile!=null)profile.addScatter(graph,NativeInferenceProfile.elapsed(scattering));}
            progress(listener,(1+stage+.75*(first+count)/BANDS)/15,"Studio temporal detail · layer "+(stage+1)+"/12");
        }
    }

    /**
     * A completed B1 call returns its private pinned slot to the coordinator immediately.
     * The coordinator copies only that band's output and then fills the slot with a new,
     * untouched band. Other workers never share its buffers or read the activation store.
     * At most four or eight Runs are in flight; all 60 bands retain the original graph.
     */
    private void runTemporalPipeline(OrtSession session,String graph,NativeExecutionPolicy.Config config,int stage,
            Listener listener,NativeDeuxTransform.Check check,NativeInferenceProfile profile)throws Exception{
        final int workers=config.temporalWorkers;
        if(config.timeBatch!=1||(workers!=4&&workers!=8))throw new IllegalArgumentException("Invalid temporal execution geometry.");
        ensureParallelBuffers(workers,profile);
        List<Future<Integer>> futures=new ArrayList<>(BANDS);
        List<BoundTemporalRun> bound=new ArrayList<>(workers);
        FloatBuffer[] inputs=new FloatBuffer[workers],outputs=new FloatBuffer[workers];
        int[] activeBands=new int[workers];
        ExecutorService pool=Executors.newFixedThreadPool(workers);
        boolean complete=false,interrupted=false;
        NativeInferenceProfile.Timing critical=null;
        try{
            CompletionService<Integer> completed=new ExecutorCompletionService<>(pool);
            // Bind once per slot, outside the profiled pipeline, and reuse only after Run returns.
            for(int slot=0;slot<workers;slot++){
                inputs[slot]=slice(parallelInputs[slot],0,FRAMES*FEATURES);
                outputs[slot]=slice(parallelOutputs[slot],0,FRAMES*FEATURES);
                NativeInferenceProfile.Timing binding=profile==null?null:NativeInferenceProfile.started();
                try{bound.add(new BoundTemporalRun(inputs[slot],outputs[slot],1));}
                finally{if(profile!=null)profile.addTensorBind(graph,NativeInferenceProfile.elapsed(binding));}
            }
            if(firstGraphRun)phase("session-run-start; graph="+graph);
            critical=profile==null?null:NativeInferenceProfile.started();
            int next=0,finished=0;
            for(int slot=0;slot<workers&&next<BANDS;slot++){
                activeBands[slot]=next++;
                packTemporalBand(graph,activeBands[slot],inputs[slot],check,profile);
                futures.add(submitTemporalBand(completed,session,graph,bound.get(slot),slot,check,profile));
            }
            while(finished<BANDS){
                check.check();
                int slot;
                try{slot=completed.take().get();}
                catch(ExecutionException failed){
                    check.check(); // Preserve explicit cancellation semantics after an ORT termination.
                    Throwable cause=failed.getCause();
                    if(cause instanceof Exception)throw (Exception)cause;
                    if(cause instanceof Error)throw (Error)cause;
                    throw new RuntimeException(cause);
                }
                if(firstGraphRun){firstGraphRun=false;phase("session-run-complete; graph="+graph);}
                check.check();int band=activeBands[slot];
                NativeInferenceProfile.Timing scattering=profile==null?null:NativeInferenceProfile.started();
                try{for(int f=0;f<FRAMES;f++)copy(outputs[slot],f*FEATURES,values,(f*BANDS+band)*FEATURES,FEATURES);}
                finally{if(profile!=null)profile.addPipelineScatter(graph,NativeInferenceProfile.elapsed(scattering));}
                finished++;
                progress(listener,(1+stage+.75*finished/BANDS)/15,"Studio temporal detail · layer "+(stage+1)+"/12");
                if(next<BANDS){
                    activeBands[slot]=next++;
                    packTemporalBand(graph,activeBands[slot],inputs[slot],check,profile);
                    futures.add(submitTemporalBand(completed,session,graph,bound.get(slot),slot,check,profile));
                }
            }
            check.check();
            complete=true;
        }catch(InterruptedException stopped){
            interrupted=true;throw new InterruptedIOException("Studio analysis was cancelled.");
        }finally{
            // Never Future.cancel: a Future may become cancelled before its JNI call retires.
            // Executor retirement also covers a submission failure before a Future is retained.
            retirePool(pool,!complete);
            for(Future<Integer> future:futures){
                boolean drained=false;
                while(!drained)try{future.get();drained=true;}
                catch(InterruptedException stopped){interrupted=true;}
                catch(ExecutionException failed){drained=true;}
            }
            try{
                // Includes nested coordinator copies and ends only after all native Runs retire.
                if(profile!=null&&critical!=null)profile.addInferencePipeline(NativeInferenceProfile.elapsed(critical));
            }finally{
                Throwable closeFailure=null;
                for(BoundTemporalRun tensors:bound)try{tensors.close();}
                catch(RuntimeException|Error failure){if(closeFailure==null)closeFailure=failure;else closeFailure.addSuppressed(failure);}
                if(interrupted)Thread.currentThread().interrupt();
                if(closeFailure instanceof RuntimeException)throw (RuntimeException)closeFailure;
                if(closeFailure instanceof Error)throw (Error)closeFailure;
            }
        }
    }
    private void packTemporalBand(String graph,int band,FloatBuffer input,NativeDeuxTransform.Check check,NativeInferenceProfile profile)throws Exception{
        check.check();NativeInferenceProfile.Timing packing=profile==null?null:NativeInferenceProfile.started();
        try{for(int f=0;f<FRAMES;f++)copy(values,(f*BANDS+band)*FEATURES,input,f*FEATURES,FEATURES);}
        finally{if(profile!=null)profile.addPipelinePack(graph,NativeInferenceProfile.elapsed(packing));}
    }
    private Future<Integer> submitTemporalBand(CompletionService<Integer> completion,OrtSession session,String graph,
            BoundTemporalRun tensors,int slot,NativeDeuxTransform.Check check,NativeInferenceProfile profile){
        return completion.submit(()->{
            check.check();if(hostRunStarted!=null)hostRunStarted.run();
            NativeInferenceProfile.Timing worker=profile==null?null:NativeInferenceProfile.started();
            try(OrtSession.Result ignored=execute(session,tensors.input,tensors.output)){check.check();}
            finally{if(profile!=null)profile.addConcurrentRun(graph,NativeInferenceProfile.elapsed(worker));}
            return slot;
        });
    }
    private void retirePool(ExecutorService pool,boolean terminate){
        if(terminate)terminateRuns();
        pool.shutdown();boolean interrupted=Thread.interrupted();
        while(!pool.isTerminated())try{pool.awaitTermination(1,TimeUnit.SECONDS);}
        catch(InterruptedException stopped){interrupted=true;terminateRuns();}
        if(interrupted)Thread.currentThread().interrupt();
    }
    private void terminateRuns(){
        synchronized(lifecycle){if(activeRun!=null)try{activeRun.setTerminate(true);}catch(OrtException ignored){}}
    }
    private static final class BoundTemporalRun implements AutoCloseable{
        final OnnxTensor input,output;
        BoundTemporalRun(FloatBuffer in,FloatBuffer out,int count)throws OrtException{
            input=OnnxTensor.createTensor(OrtEnvironment.getEnvironment(),in,new long[]{count,FRAMES,FEATURES});
            try{output=OnnxTensor.createTensor(OrtEnvironment.getEnvironment(),out,new long[]{count,FRAMES,FEATURES});}
            catch(OrtException|RuntimeException|Error failure){input.close();throw failure;}
        }
        @Override public void close(){try{output.close();}finally{input.close();}}
    }
    private OrtSession open(OrtEnvironment environment,String name,NativeDeuxTransform.Check check,NativeInferenceProfile profile) throws Exception {
        NativeExecutionPolicy.Config config=NativeExecutionPolicy.baseline(executionKey.cores);
        return openConfigured(environment,name,check,profile,config);
    }

    private OrtSession openConfigured(OrtEnvironment environment,String name,NativeDeuxTransform.Check check,
            NativeInferenceProfile profile,NativeExecutionPolicy.Config config) throws Exception {
        check.check();NativeInferenceProfile.Timing modelStarted=profile==null?null:NativeInferenceProfile.started();
        File model;
        try{model=model(name,check);}finally{if(profile!=null)profile.addModelPrepare(name,NativeInferenceProfile.elapsed(modelStarted));}
        check.check();
        phase("session-create-start; graph="+name);
        NativeInferenceProfile.Timing sessionStarted=profile==null?null:NativeInferenceProfile.started();boolean recorded=false;
        try(OrtSession.SessionOptions options=new OrtSession.SessionOptions()) {
            options.setIntraOpNumThreads(config.intraThreads);
            options.setInterOpNumThreads(config.interThreads);
            options.setExecutionMode(OrtSession.SessionOptions.ExecutionMode.SEQUENTIAL);
            options.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT);
            options.setCPUArenaAllocator(true);options.setMemoryPatternOptimization(true);
            options.addConfigEntry("session.intra_op.allow_spinning","0");
            if(config.dynamicBlockBase>0)options.addConfigEntry("session.dynamic_block_base",String.valueOf(config.dynamicBlockBase));
            OrtSession session=environment.createSession(model.getAbsolutePath(),options);
            if(profile!=null){profile.addSessionInit(name,NativeInferenceProfile.elapsed(sessionStarted));recorded=true;}
            activeGraph=name;firstGraphRun=true;phase("session-create-complete; graph="+name);
            try{check.check();return session;}catch(Exception e){session.close();throw e;}
        }finally{if(profile!=null&&!recorded)profile.addSessionInit(name,NativeInferenceProfile.elapsed(sessionStarted));}
    }

    /** A cold graph only nominates a candidate; it never authorizes production execution. */
    private void nominate(File audio,long startSample,NativeDeuxTransform.Check outerCheck,NativeInferenceProfile profile)throws Exception{
        long started=System.nanoTime();
        NativeDeuxTransform.Check check=()->{outerCheck.check();if(System.nanoTime()-started>=60000000000L)throw new ProbeAborted("screen-budget");};
        FloatBuffer originalValues=values;int winner=0;long best=Long.MAX_VALUE;
        probing=true;
        try{
            NativeExecutionPolicy.Config[] configs=NativeExecutionPolicy.temporalCandidates(executionKey,availableMemory());
            if(configs.length==0){passagePolicy.forceBaseline("memory-pressure");return;}
            beginRun();
            float[][] passage=NativeDeuxTransform.readStereo(audio,startSample,check);
            transform.encode(passage,spectrum,check);passage=null;
            OrtEnvironment environment=OrtEnvironment.getEnvironment();
            try(OrtSession session=open(environment,"front",check,null)){
                run(session,spectrum,new long[]{1,2050,FRAMES,2},values,new long[]{1,FRAMES,BANDS,FEATURES},check,null);
            }
            values=direct(originalValues.capacity());calibrationBufferBytes=4L*originalValues.capacity();noteDirectBufferBytes(profile);
            NativeExecutionPolicy.Config[] screen=new NativeExecutionPolicy.Config[configs.length+1];
            screen[0]=NativeExecutionPolicy.baseline(executionKey.cores);System.arraycopy(configs,0,screen,1,configs.length);
            byte[] reference=null;long baseline=0;
            for(NativeExecutionPolicy.Config config:screen){
                check.check();if(!NativeExecutionPolicy.temporalAllowed(config,executionKey,availableMemory()))throw new ProbeAborted("memory-pressure");
                copy(originalValues,0,values,0,originalValues.capacity());
                long trial=System.nanoTime();
                try(OrtSession session=openConfigured(environment,"block-00-time",check,null,config)){
                    runTemporalGraph(session,"block-00-time",config,0,null,check,null);
                }
                long elapsed=System.nanoTime()-trial;byte[] hash=tensorHash(values,check);
                if(config.temporalWorkers==1){reference=hash;baseline=elapsed;}
                else if(reference!=null&&Arrays.equals(reference,hash)&&elapsed<baseline*.95&&elapsed<best){winner=config.temporalWorkers;best=elapsed;}
            }
            if(winner==0)passagePolicy.forceBaseline("screen-no-win");
        }catch(ProbeAborted stopped){
            if(stopped.getSuppressed().length!=0)throw stopped;
            outerCheck.check();passagePolicy.forceBaseline(stopped.reason);
        }finally{
            try{endRun();}
            finally{
                try{noteDirectBufferBytes(profile);}
                finally{values=originalValues;calibrationBufferBytes=0;probing=false;}
                long extra=System.nanoTime()-started;
                if(winner!=0)passagePolicy.nominate(winner,extra);else passagePolicy.probeAborted("screen-no-win",extra);
                if(profile!=null)profile.noteSchedulerCalibration(extra);
            }
        }
    }

    /** Hash raw Float32 bits in a bounded buffer; no duplicate multi-megabyte tensor allocation. */
    private static byte[] tensorHash(FloatBuffer tensor,NativeDeuxTransform.Check check) throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");byte[] bytes=new byte[16384];int used=0;
        for(int i=0;i<tensor.capacity();i++){
            if((i&4095)==0)check.check();float value=tensor.get(i);if(!Float.isFinite(value))return null;
            int bits=Float.floatToRawIntBits(value);
            bytes[used++]=(byte)bits;bytes[used++]=(byte)(bits>>>8);bytes[used++]=(byte)(bits>>>16);bytes[used++]=(byte)(bits>>>24);
            if(used==bytes.length){digest.update(bytes);used=0;}
        }
        if(used>0)digest.update(bytes,0,used);return digest.digest();
    }
    private void scheduler(String message){if(context!=null)AppDiagnostics.log(context,"INFO","native-scheduler",message);}

    /** Only a Run rejection is optional; tensor/session construction and retirement still fail normally. */
    private OrtSession.Result execute(OrtSession session,OnnxTensor input,OnnxTensor output)throws Exception{
        try{return session.run(Collections.singletonMap("input",input),Collections.emptySet(),Collections.singletonMap("output",output),activeRun);}
        catch(OrtException rejected){if(probing)throw new ProbeRunRejected(rejected);throw rejected;}
    }

    private void run(OrtSession session,FloatBuffer input,long[] inputShape,FloatBuffer output,long[] outputShape,NativeDeuxTransform.Check check,NativeInferenceProfile profile) throws Exception {
        check.check();
        boolean first=firstGraphRun;if(first)phase("session-run-start; graph="+activeGraph);
        NativeInferenceProfile.Timing bindStarted=profile==null?null:NativeInferenceProfile.started();boolean bound=false;
        try(OnnxTensor x=OnnxTensor.createTensor(OrtEnvironment.getEnvironment(),input,inputShape);
            OnnxTensor y=OnnxTensor.createTensor(OrtEnvironment.getEnvironment(),output,outputShape)) {
            if(profile!=null){profile.addTensorBind(activeGraph,NativeInferenceProfile.elapsed(bindStarted));bound=true;}
            NativeInferenceProfile.Timing runStarted=profile==null?null:NativeInferenceProfile.started();
            try(OrtSession.Result result=execute(session,x,y)) {
                if(first){firstGraphRun=false;phase("session-run-complete; graph="+activeGraph);}
                check.check();
            }finally{if(profile!=null)profile.addRun(activeGraph,NativeInferenceProfile.elapsed(runStarted));}
        }finally{if(profile!=null&&!bound)profile.addTensorBind(activeGraph,NativeInferenceProfile.elapsed(bindStarted));}
    }

    /** Flush only at graph boundaries so a native process death retains its last phase. */
    private void phase(String detail) {
        if(context!=null){AppDiagnostics.log(context,"INFO","native-phase",detail+"; role="+(probing?"probe":"production"));AppDiagnostics.flush(1000);}
    }

    private File model(String name,NativeDeuxTransform.Check check) throws Exception {
        JSONObject entry=validateEntry(name);String filename=name+".onnx";File model=new File(modelDirectory,filename);
        if(verified.contains(filename)&&model.isFile()&&model.length()==entry.getLong("bytes"))return model;
        if(model.isFile()&&model.length()==entry.getLong("bytes")&&entry.getString("sha256").equals(digest(model,check))) {
            verified.add(filename);return model;
        }
        if(context==null)throw new IOException("The studio model checksum does not match: "+filename);
        if(modelDirectory.getUsableSpace()<entry.getLong("bytes")+32L*1024*1024)throw new IOException("Studio analysis needs more free storage to prepare its offline models.");
        File partial=File.createTempFile(".model-",".partial",modelDirectory);
        try {
            MessageDigest hash=MessageDigest.getInstance("SHA-256");long bytes=0;
            try(InputStream in=context.getAssets().open(ASSET_ROOT+filename);FileOutputStream out=new FileOutputStream(partial)) {
                byte[] buffer=new byte[262144];int count;
                while((count=in.read(buffer))!=-1) {
                    check.check();bytes+=count;if(bytes>entry.getLong("bytes"))throw new IOException("The studio model is too large.");
                    out.write(buffer,0,count);hash.update(buffer,0,count);
                }
                out.getFD().sync();
            }
            if(bytes!=entry.getLong("bytes")||!entry.getString("sha256").equals(hex(hash.digest())))throw new IOException("The studio model is damaged: "+filename);
            check.check();Files.move(partial.toPath(),model.toPath(),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
            verified.add(filename);return model;
        }finally{partial.delete();}
    }

    /** Fail before neural work if a first-time extraction cannot finish both heads. */
    private void preflightCache(NativeDeuxTransform.Check check,NativeInferenceProfile profile) throws Exception {
        List<String> names=new ArrayList<>(Arrays.asList("front","head-0","head-1"));
        for(int i=0;i<12;i++){names.add(blockName(i)+"-time");names.add(blockName(i)+"-frequency");}
        long missing=0,largest=0;
        for(String name:names) {
            check.check();JSONObject entry=validateEntry(name);String filename=name+".onnx";File file=new File(modelDirectory,filename);
            long bytes=entry.getLong("bytes");boolean intact=false;
            if(file.isFile()&&file.length()==bytes)intact=verified.contains(filename)||entry.getString("sha256").equals(digest(file,check));
            if(intact){
                verified.add(filename);
                if(profile!=null)profile.noteCacheModelHit(bytes);
            }
            else {
                verified.remove(filename);
                if(profile!=null)profile.noteCacheModelMiss(bytes);
                if(context==null)throw new IOException("The studio model checksum does not match: "+filename);
                missing+=bytes;largest=Math.max(largest,bytes);
            }
        }
        if(context!=null) {
            // Reserve a full head-sized atomic replacement plus checkpoint/output space.
            long needed=missing+largest+32L*1024*1024,available=modelDirectory.getUsableSpace();
            if(available<needed) {
                long mib=1024*1024;
                throw new IOException("Studio analysis needs "+((needed+mib-1)/mib)+" MB of free storage ("+(available/mib)+" MB available). Free "+((needed-available+mib-1)/mib)+" MB and retry.");
            }
        }
    }

    private JSONObject validateEntry(String name) throws Exception {
        if(!name.matches("(?:front|head-[01]|block-(?:0[0-9]|1[01])-(?:time|frequency))"))throw new IOException("Invalid studio model name.");
        JSONObject entry=files.getJSONObject(name+".onnx");long bytes=entry.getLong("bytes");
        if(bytes<1 || bytes>1024L*1024*1024 || !entry.getString("sha256").matches("[0-9a-f]{64}"))throw new IOException("The studio model inventory is invalid.");
        return entry;
    }
    private static int[] integers(JSONArray array,int size,int min,int max) throws Exception {
        if(array.length()!=size)throw new IOException("Invalid studio frequency geometry.");int[] values=new int[size];
        for(int i=0;i<size;i++){values[i]=array.getInt(i);if(values[i]<min||values[i]>max)throw new IOException("Invalid studio frequency index.");}return values;
    }
    private static String blockName(int index){return "block-"+(index<10?"0":"")+index;}
    private static void progress(Listener listener,double progress,String message){if(listener!=null)listener.update(progress,message);}
    private static FloatBuffer direct(int count){return ByteBuffer.allocateDirect(Math.multiplyExact(count,4)).order(ByteOrder.nativeOrder()).asFloatBuffer();}
    private static FloatBuffer slice(FloatBuffer buffer,int offset,int count){FloatBuffer part=buffer.duplicate();part.position(offset);part.limit(offset+count);return part.slice();}
    private static void copy(FloatBuffer from,int source,FloatBuffer to,int target,int count){FloatBuffer src=from.duplicate(),dst=to.duplicate();src.position(source);src.limit(source+count);dst.position(target);dst.put(src);}
    private static byte[] readBounded(InputStream in,int max) throws IOException {
        ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buffer=new byte[8192];int count;
        while((count=in.read(buffer))!=-1){if(out.size()+count>max)throw new IOException("The studio manifest is too large.");out.write(buffer,0,count);}return out.toByteArray();
    }
    private static String digest(File file,NativeDeuxTransform.Check check) throws Exception {
        MessageDigest hash=MessageDigest.getInstance("SHA-256");try(InputStream in=new FileInputStream(file)){byte[] buffer=new byte[262144];int count;
            while((count=in.read(buffer))!=-1){check.check();hash.update(buffer,0,count);}}return hex(hash.digest());
    }
    private static String hex(byte[] bytes){StringBuilder text=new StringBuilder(bytes.length*2);for(byte b:bytes)text.append(Character.forDigit((b>>>4)&15,16)).append(Character.forDigit(b&15,16));return text.toString();}
    private static void writeFloats(OutputStream out,float[] pcm,NativeDeuxTransform.Check check) throws IOException {
        ByteBuffer block=ByteBuffer.allocate(32768).order(ByteOrder.LITTLE_ENDIAN);
        for(int first=0;first<pcm.length;) {
            check.check();int count=Math.min(block.capacity()/4,pcm.length-first);block.clear();
            for(int i=0;i<count;i++){float value=pcm[first+i];if(!Float.isFinite(value))throw new IOException("The studio result contains invalid audio.");block.putFloat(value);}
            out.write(block.array(),0,count*4);first+=count;
        }
    }
}
