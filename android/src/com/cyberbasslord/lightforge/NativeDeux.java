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
    private NativeExecutionPolicy.Calibration executionPolicy;
    private boolean frequencyCalibrationAttempted,policyReported;
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
            "native-deux-"+RUNTIME_VERSION+"-parallel-b1-v3",
            context==null?System.getProperty("os.name")+":"+System.getProperty("os.version"):android.os.Build.FINGERPRINT,
            context==null?System.getProperty("os.arch"):android.os.Build.MANUFACTURER+":"+android.os.Build.MODEL+":"+Arrays.toString(android.os.Build.SUPPORTED_ABIS),
            Runtime.getRuntime().availableProcessors());
        executionPolicyFile=context==null?hostExecutionPolicyFile:new File(this.modelDirectory,"execution-policy.bin");
        executionPolicy=executionPolicyFile==null?NativeExecutionPolicy.defaults(executionKey):NativeExecutionPolicy.load(executionPolicyFile,executionKey);
    }

    /** Output contains vocals then accompaniment, each exactly 573300 float32 LE samples. */
    public void predict(File audio,long startSample,File output,Listener listener,Cancellation cancellation) throws Exception {
        predict(audio,startSample,output,listener,cancellation,null);
    }

    public synchronized void predict(File audio,long startSample,File output,Listener listener,Cancellation cancellation,ExecutionScope scope) throws Exception {
        predict(audio,startSample,output,listener,cancellation,scope,null);
    }

    /** Package-private so the service can collect timing without exposing a profiling API. */
    synchronized void predict(File audio,long startSample,File output,Listener listener,Cancellation cancellation,ExecutionScope scope,NativeInferenceProfile profile) throws Exception {
        synchronized(lifecycle) {
            if(closed || cancelled)throw new InterruptedIOException("Studio analysis was cancelled.");
            running=true;
        }
        NativeDeuxTransform.Check check=()->check(cancellation);
        File partial=null;boolean acquired=false,entered=false;
        try {
            check.check();
            if(profile!=null){
                profile.noteSchedulerConfiguration("temporal",executionPolicy.temporal.config.id());
                profile.noteSchedulerConfiguration("frequency",executionPolicy.frequency.config.id());
            }
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
            phase("runtime-load-start; version="+RUNTIME_VERSION);
            NativeInferenceProfile.Timing runtimeStarted=profile==null?null:NativeInferenceProfile.started();
            try { synchronized(lifecycle){activeRun=new OrtSession.RunOptions();if(cancelled||closed)activeRun.setTerminate(true);} }
            finally { if(profile!=null)profile.addRuntimeInit(NativeInferenceProfile.elapsed(runtimeStarted)); }
            phase("runtime-load-complete");
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
            if(!policyReported){
                policyReported=true;
                scheduler("cache="+(executionPolicy.complete()?"hit":"miss")+" temporal="+executionPolicy.temporal.config.id()+" frequency="+executionPolicy.frequency.config.id());
            }
            try(OrtSession session=open(environment,"front",check,profile)) {
                run(session,spectrum,new long[]{1,2050,FRAMES,2},values,new long[]{1,FRAMES,BANDS,FEATURES},check,profile);
            }
            progress(listener,1.0/15,"Studio frequency analysis");
            for(int block=0;block<12;block++) {
                final int stage=block;
                if(block==0&&executionPolicyFile!=null){
                    long headroom=availableMemory();
                    NativeExecutionPolicy.Decision previous=executionPolicy.temporal;
                    if(!previous.complete||NativeExecutionPolicy.temporalNeedsExpansion(previous,executionKey,headroom)){
                        NativeExecutionPolicy.Config[] candidates=NativeExecutionPolicy.temporalCandidates(executionKey,headroom);
                        NativeExecutionPolicy.Decision decision;
                        if(candidates.length>0){
                            progress(listener,1.0/15,"Optimizing studio execution for this device");
                            decision=calibrateTemporal(environment,candidates,headroom,check,profile);
                        }else decision=NativeExecutionPolicy.retainedTemporal(executionKey);
                        // A previously measured choice remains valid while a larger shortlist
                        // is unavailable. Retry expansion on a later passage after pressure clears.
                        if(decision.complete||!previous.complete){
                            executionPolicy=new NativeExecutionPolicy.Calibration(decision,executionPolicy.frequency);
                            if(decision.complete)savePolicy();
                        }
                    }
                }
                NativeExecutionPolicy.Config temporal=temporalConfiguration();
                if(profile!=null)profile.noteSchedulerConfiguration("temporal",temporal.id());
                try(OrtSession session=openConfigured(environment,blockName(block)+"-time",check,profile,temporal)) {
                    runTemporalGraph(session,blockName(block)+"-time",temporal,stage,listener,check,profile);
                }
                if(block==0&&!frequencyCalibrationAttempted&&executionPolicyFile!=null&&!executionPolicy.frequency.complete){
                    frequencyCalibrationAttempted=true;
                    int size=FREQUENCY_BATCH*BANDS*FEATURES;
                    progress(listener,1.75/15,"Optimizing studio execution for this device");
                    NativeExecutionPolicy.Decision decision=calibrate(environment,"block-00-frequency",
                        slice(values,0,size),slice(batchOutput,0,size),new long[]{FREQUENCY_BATCH,BANDS,FEATURES},check,profile);
                    executionPolicy=new NativeExecutionPolicy.Calibration(executionPolicy.temporal,decision);
                    if(profile!=null)profile.noteSchedulerConfiguration("frequency",decision.config.id());
                    savePolicy();
                }
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
            File parent=output.getAbsoluteFile().getParentFile();
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
            NativeInferenceProfile.Timing commitStarted=profile==null?null:NativeInferenceProfile.started();
            try { Files.move(partial.toPath(),output.toPath(),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);partial=null; }
            finally { if(profile!=null)profile.addOutputCommit(NativeInferenceProfile.elapsed(commitStarted)); }
        } finally {
            if(partial!=null)partial.delete();
            try {
                synchronized(lifecycle) {
                    if(activeRun!=null){activeRun.close();activeRun=null;}
                    running=false;if(closed)clearBuffers();
                }
            }finally{try{if(entered)scope.end();}finally{if(acquired)INFERENCE_GATE.release();}}
        }
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

    private void savePolicy(){
        if(executionPolicyFile!=null&&executionPolicy.complete())try{NativeExecutionPolicy.save(executionPolicyFile,executionKey,executionPolicy);}
        catch(IOException unavailable){scheduler("cache=write-unavailable; using measured in-memory configuration");}
    }

    /** Recheck native headroom before every graph, including a cached fast path. */
    private NativeExecutionPolicy.Config temporalConfiguration(){
        if(hostTemporalConfig!=null)return hostTemporalConfig;
        NativeExecutionPolicy.Config selected=executionPolicy.temporal.config;
        if(selected.temporalWorkers==1||NativeExecutionPolicy.temporalAllowed(selected,executionKey,availableMemory()))return selected;
        scheduler("family=temporal decision=memory-baseline; measured configuration retained for later passages");
        return NativeExecutionPolicy.baseline(executionKey.cores);
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
            try(OrtSession.Result ignored=session.run(Collections.singletonMap("input",tensors.input),Collections.emptySet(),
                    Collections.singletonMap("output",tensors.output),activeRun)){check.check();}
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
        NativeExecutionPolicy.Config config=name.endsWith("-time")?executionPolicy.temporal.config:
            name.endsWith("-frequency")?executionPolicy.frequency.config:NativeExecutionPolicy.baseline(executionKey.cores);
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

    /** Compare the complete original temporal graph over all 60 real input bands. */
    private NativeExecutionPolicy.Decision calibrateTemporal(OrtEnvironment environment,NativeExecutionPolicy.Config[] configs,
            long admittedHeadroom,NativeDeuxTransform.Check check,NativeInferenceProfile profile)throws Exception{
        long started=System.nanoTime();
        NativeExecutionPolicy.Config baseline=NativeExecutionPolicy.baseline(executionKey.cores);
        NativeExecutionPolicy.Candidate[] trials=new NativeExecutionPolicy.Candidate[configs.length];
        byte[] reference=null;
        // Preserve the original front activations by reference. Every calibration pass
        // mutates one bounded working buffer, exactly as normal production inference does.
        FloatBuffer originalValues=values;
        try{
            FloatBuffer working=direct(originalValues.capacity());
            values=working;calibrationBufferBytes=4L*originalValues.capacity();
            noteDirectBufferBytes(profile);
            for(int c=0;c<configs.length;c++){
                NativeExecutionPolicy.Sample[] samples=new NativeExecutionPolicy.Sample[NativeExecutionPolicy.MIN_PAIRS];
                for(int pair=0;pair<samples.length;pair++){
                    check.check();boolean candidateFirst=(pair&1)!=0;
                    CalibrationTrial a,b;
                    if(candidateFirst){
                        b=temporalCalibrationTrial(environment,configs[c],configs[c],originalValues,check);
                        a=temporalCalibrationTrial(environment,baseline,configs[c],originalValues,check);
                    }else{
                        a=temporalCalibrationTrial(environment,baseline,configs[c],originalValues,check);
                        b=temporalCalibrationTrial(environment,configs[c],configs[c],originalValues,check);
                    }
                    if(reference==null&&a.finite)reference=a.outputHash;
                    boolean finite=a.finite&&b.finite;
                    boolean exact=finite&&Arrays.equals(reference,a.outputHash)&&Arrays.equals(reference,a.warmupHash)
                        &&Arrays.equals(reference,b.outputHash)&&Arrays.equals(reference,b.warmupHash);
                    samples[pair]=new NativeExecutionPolicy.Sample(a.nanos,b.nanos,candidateFirst,finite,exact,BANDS);
                }
                trials[c]=new NativeExecutionPolicy.Candidate(configs[c],samples);
            }
            NativeExecutionPolicy.Decision decision=NativeExecutionPolicy.selectTemporal(executionKey,admittedHeadroom,configs,trials);
            scheduler("graph=block-00-time selected="+decision.config.id()+" decision="+decision.reason+
                " pairs="+decision.pairCount+" baselineMedianNanos="+decision.baselineMedianNanos+
                " candidateMedianNanos="+decision.candidateMedianNanos+" scope=all-60-real-bands-production-path");
            return decision;
        }catch(TemporalMemoryUnavailable pressure){
            check.check();scheduler("family=temporal decision=memory-baseline; calibration=incomplete");
            return NativeExecutionPolicy.retainedTemporal(executionKey);
        }finally{
            try{noteDirectBufferBytes(profile);}
            finally{
                values=originalValues;calibrationBufferBytes=0;
                if(profile!=null)profile.noteSchedulerCalibration(System.nanoTime()-started);
            }
        }
    }
    private CalibrationTrial temporalCalibrationTrial(OrtEnvironment environment,NativeExecutionPolicy.Config config,
            NativeExecutionPolicy.Config required,FloatBuffer originalValues,NativeDeuxTransform.Check check)throws Exception{
        check.check();
        if(!NativeExecutionPolicy.temporalAllowed(required,executionKey,availableMemory()))throw new TemporalMemoryUnavailable();
        try(OrtSession session=openConfigured(environment,"block-00-time",check,null,config)){
            copy(originalValues,0,values,0,originalValues.capacity());check.check();
            runTemporalGraph(session,"block-00-time",config,0,null,check,null);
            byte[] warmup=tensorHash(values,check);
            copy(originalValues,0,values,0,originalValues.capacity());check.check();
            // Time the actual production call, including all binding, worker setup,
            // packing, kernels, scatter and retirement. Reset and validation happen
            // only outside this interval, with no overlapping native work.
            long started=System.nanoTime();
            runTemporalGraph(session,"block-00-time",config,0,null,check,null);
            long elapsed=System.nanoTime()-started;
            byte[] measured=tensorHash(values,check);
            return new CalibrationTrial(elapsed,warmup,measured);
        }
    }
    private static final class TemporalMemoryUnavailable extends Exception{}

    /** Probe only unchanged graphs, serially under the existing native lease and inference gate. */
    private NativeExecutionPolicy.Decision calibrate(OrtEnvironment environment,String graph,FloatBuffer input,
            FloatBuffer output,long[] shape,NativeDeuxTransform.Check check,NativeInferenceProfile profile) throws Exception {
        long started=System.nanoTime();
        NativeExecutionPolicy.Config baseline=NativeExecutionPolicy.baseline(executionKey.cores);
        NativeExecutionPolicy.Config[] configs=NativeExecutionPolicy.candidates(executionKey.cores);
        NativeExecutionPolicy.Candidate[] trials=new NativeExecutionPolicy.Candidate[configs.length];
        byte[] reference=null;
        try {
            for(int c=0;c<configs.length;c++){
                NativeExecutionPolicy.Sample[] samples=new NativeExecutionPolicy.Sample[NativeExecutionPolicy.MIN_PAIRS];
                for(int pair=0;pair<samples.length;pair++){
                    check.check();boolean candidateFirst=(pair&1)!=0;
                    CalibrationTrial a,b;
                    if(candidateFirst){
                        b=calibrationTrial(environment,graph,configs[c],input,output,shape,check);
                        a=calibrationTrial(environment,graph,baseline,input,output,shape,check);
                    }else{
                        a=calibrationTrial(environment,graph,baseline,input,output,shape,check);
                        b=calibrationTrial(environment,graph,configs[c],input,output,shape,check);
                    }
                    if(reference==null&&a.finite)reference=a.outputHash;
                    boolean finite=a.finite&&b.finite;
                    boolean exact=finite&&Arrays.equals(reference,a.outputHash)&&Arrays.equals(reference,a.warmupHash)
                        &&Arrays.equals(reference,b.outputHash)&&Arrays.equals(reference,b.warmupHash);
                    samples[pair]=new NativeExecutionPolicy.Sample(a.nanos,b.nanos,candidateFirst,finite,exact);
                }
                trials[c]=new NativeExecutionPolicy.Candidate(configs[c],samples);
            }
            NativeExecutionPolicy.Decision decision=NativeExecutionPolicy.select(executionKey,trials);
            scheduler("graph="+graph+" selected="+decision.config.id()+" decision="+decision.reason+
                " pairs="+decision.pairCount+" baselineMedianNanos="+decision.baselineMedianNanos+
                " candidateMedianNanos="+decision.candidateMedianNanos+" scope=first-real-batch");
            return decision;
        }catch(CalibrationUnavailable unavailable){
            check.check();
            scheduler("graph="+graph+" decision=runtime-rejected; baseline retained; cache=incomplete");
            return NativeExecutionPolicy.defaults(executionKey).frequency;
        }finally{if(profile!=null)profile.noteSchedulerCalibration(System.nanoTime()-started);}
    }

    private CalibrationTrial calibrationTrial(OrtEnvironment environment,String graph,NativeExecutionPolicy.Config config,
            FloatBuffer input,FloatBuffer output,long[] shape,NativeDeuxTransform.Check check) throws Exception {
        OrtException rejected=null;CalibrationTrial measured=null;
        // Only an ORT Run rejection with confirmed session retirement is recoverable.
        // Constructor, destructor, I/O, cancellation and Error failures keep their normal path.
        try(OrtSession session=openConfigured(environment,graph,check,null,config)){
            try{
                run(session,input,shape,output,shape,check,null);
                byte[] warmup=tensorHash(output,check);
                long started=System.nanoTime();
                run(session,input,shape,output,shape,check,null);
                long elapsed=System.nanoTime()-started;
                byte[] result=tensorHash(output,check);
                measured=new CalibrationTrial(elapsed,warmup,result);
            }catch(OrtException error){rejected=error;}
        }
        if(rejected!=null)throw new CalibrationUnavailable(rejected);
        return measured;
    }
    private static final class CalibrationUnavailable extends Exception {
        CalibrationUnavailable(OrtException cause){super(cause);}
    }
    private static final class CalibrationTrial {
        final long nanos;final byte[] warmupHash,outputHash;final boolean finite;
        CalibrationTrial(long nanos,byte[] warmup,byte[] result){this.nanos=nanos;warmupHash=warmup;outputHash=result;finite=warmup!=null&&result!=null;}
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

    private void run(OrtSession session,FloatBuffer input,long[] inputShape,FloatBuffer output,long[] outputShape,NativeDeuxTransform.Check check,NativeInferenceProfile profile) throws Exception {
        check.check();
        boolean first=firstGraphRun;if(first)phase("session-run-start; graph="+activeGraph);
        NativeInferenceProfile.Timing bindStarted=profile==null?null:NativeInferenceProfile.started();boolean bound=false;
        try(OnnxTensor x=OnnxTensor.createTensor(OrtEnvironment.getEnvironment(),input,inputShape);
            OnnxTensor y=OnnxTensor.createTensor(OrtEnvironment.getEnvironment(),output,outputShape)) {
            if(profile!=null){profile.addTensorBind(activeGraph,NativeInferenceProfile.elapsed(bindStarted));bound=true;}
            NativeInferenceProfile.Timing runStarted=profile==null?null:NativeInferenceProfile.started();
            try(OrtSession.Result result=session.run(Collections.singletonMap("input",x),Collections.emptySet(),Collections.singletonMap("output",y),activeRun)) {
                if(first){firstGraphRun=false;phase("session-run-complete; graph="+activeGraph);}
                check.check();
            }finally{if(profile!=null)profile.addRun(activeGraph,NativeInferenceProfile.elapsed(runStarted));}
        }finally{if(profile!=null&&!bound)profile.addTensorBind(activeGraph,NativeInferenceProfile.elapsed(bindStarted));}
    }

    /** Flush only at graph boundaries so a native process death retains its last phase. */
    private void phase(String detail) {
        if(context!=null){AppDiagnostics.log(context,"INFO","native-phase",detail);AppDiagnostics.flush(1000);}
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
