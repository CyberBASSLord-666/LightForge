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
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;

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
    private NativeDeuxTransform transform;
    private String activeGraph;
    private boolean firstGraphRun;

    public NativeDeux(Context context) throws Exception {
        this(context.getApplicationContext(),null);
    }

    /** Real-model JVM verification uses the same inference and transforms as Android. */
    public NativeDeux(File modelDirectory) throws Exception { this(null,modelDirectory); }

    private NativeDeux(Context context,File directory) throws Exception {
        this.context=context;
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
            try(OrtSession session=open(environment,"front",check,profile)) {
                run(session,spectrum,new long[]{1,2050,FRAMES,2},values,new long[]{1,FRAMES,BANDS,FEATURES},check,profile);
            }
            progress(listener,1.0/15,"Studio frequency analysis");
            for(int block=0;block<12;block++) {
                final int stage=block;
                try(OrtSession session=open(environment,blockName(block)+"-time",check,profile)) {
                    for(int first=0;first<BANDS;first+=TIME_BATCH) {
                        check.check();int count=Math.min(TIME_BATCH,BANDS-first),size=count*FRAMES*FEATURES;
                        FloatBuffer in=slice(batchInput,0,size),out=slice(batchOutput,0,size);
                        NativeInferenceProfile.Timing packStarted=profile==null?null:NativeInferenceProfile.started();
                        try {
                            for(int b=0;b<count;b++)for(int f=0;f<FRAMES;f++)
                                copy(values,(f*BANDS+first+b)*FEATURES,in,(b*FRAMES+f)*FEATURES,FEATURES);
                        } finally { if(profile!=null)profile.addPack(blockName(block)+"-time",NativeInferenceProfile.elapsed(packStarted)); }
                        run(session,in,new long[]{count,FRAMES,FEATURES},out,new long[]{count,FRAMES,FEATURES},check,profile);
                        NativeInferenceProfile.Timing scatterStarted=profile==null?null:NativeInferenceProfile.started();
                        try {
                            for(int b=0;b<count;b++)for(int f=0;f<FRAMES;f++)
                                copy(out,(b*FRAMES+f)*FEATURES,values,(f*BANDS+first+b)*FEATURES,FEATURES);
                        } finally { if(profile!=null)profile.addScatter(blockName(block)+"-time",NativeInferenceProfile.elapsed(scatterStarted)); }
                        progress(listener,(1+stage+.75*(first+count)/BANDS)/15,"Studio temporal detail · layer "+(stage+1)+"/12");
                    }
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
        if(buffersReady())return;
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
    private void clearBuffers(){spectrum=null;values=null;mask=null;summed=null;batchInput=null;batchOutput=null;transform=null;}

    private OrtSession open(OrtEnvironment environment,String name,NativeDeuxTransform.Check check,NativeInferenceProfile profile) throws Exception {
        check.check();NativeInferenceProfile.Timing modelStarted=profile==null?null:NativeInferenceProfile.started();
        File model;
        try{model=model(name,check);}finally{if(profile!=null)profile.addModelPrepare(name,NativeInferenceProfile.elapsed(modelStarted));}
        check.check();
        phase("session-create-start; graph="+name);
        NativeInferenceProfile.Timing sessionStarted=profile==null?null:NativeInferenceProfile.started();boolean recorded=false;
        try(OrtSession.SessionOptions options=new OrtSession.SessionOptions()) {
            options.setIntraOpNumThreads(Math.max(1,Math.min(4,Runtime.getRuntime().availableProcessors())));
            options.setInterOpNumThreads(1);
            options.setExecutionMode(OrtSession.SessionOptions.ExecutionMode.SEQUENTIAL);
            options.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT);
            options.setCPUArenaAllocator(false);options.setMemoryPatternOptimization(false);
            options.addConfigEntry("session.intra_op.allow_spinning","0");
            OrtSession session=environment.createSession(model.getAbsolutePath(),options);
            if(profile!=null){profile.addSessionInit(name,NativeInferenceProfile.elapsed(sessionStarted));recorded=true;}
            activeGraph=name;firstGraphRun=true;phase("session-create-complete; graph="+name);
            try{check.check();return session;}catch(Exception e){session.close();throw e;}
        }finally{if(profile!=null&&!recorded)profile.addSessionInit(name,NativeInferenceProfile.elapsed(sessionStarted));}
    }

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
