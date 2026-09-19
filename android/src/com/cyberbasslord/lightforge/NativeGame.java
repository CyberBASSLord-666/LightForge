package com.cyberbasslord.lightforge;

import android.content.Context;
import ai.onnxruntime.*;
import org.json.*;
import java.io.*;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;

/**
 * One bounded passage through the original float32 GAME graphs and eight steps.
 * No normalization, rounding, quantization, graph specialization or context change.
 * The caller owns the process-wide inference gate and durable native crash lease.
 * Constructors read the manifest only; predict owns and retires every JNI resource.
 */
public final class NativeGame implements AutoCloseable {
    public static final String MODEL_ID="game-large-1.0.3-lightforge-1", RUNTIME_VERSION="1.25.1";
    public static final int SAMPLE_RATE=44100, MAX_SAMPLES=16*SAMPLE_RATE, STEPS=8;
    public interface Listener { void update(double progress,String message); }
    public interface Cancellation { boolean cancelled(); }
    private static final int MAX_FRAMES=1601, FEATURES=256;
    private static final String ASSET_ROOT="analysis/models/game/";
    private static final String[] GRAPHS={"encoder","dur2bd","segmenter","bd2dur","estimator"};
    // Pin the existing graph derivative, not merely a mutable manifest assertion.
    private static final long[] BYTES={80398908,2632,159935846,4569,153459702};
    private static final String[] HASHES={
        "fbda7df8791d5cafd02ed33c65f9926c5514c750278c27fb8a59259b4c1d7464",
        "49d10d1ea186e43c51fd2c51cedb01a3852d363f1c7056ae77df50f7e8dd0996",
        "9db605a2ad3c179e9c4e4ae5b970727006020c65936773c26b2cbc27d8ef892f",
        "6672d56b00f27a20e9bfaa92801c15e394bb520e49031d3ed2515b0a6cf27402",
        "0d4a6e13bf475f79967e252b401bb5f317aa6b96bbe6665d5f8b14b42b179926"
    };
    private final Context context;
    private final File modelDirectory;
    private final Object lifecycle=new Object();
    private final Map<String,OrtSession> sessions=new LinkedHashMap<>();
    private volatile boolean cancelled,closed,running,retirementUnconfirmed;
    private OrtSession.RunOptions activeRun;

    public NativeGame(Context context) throws Exception { this(context.getApplicationContext(),null); }
    /** Host proof executes this same engine without calling Android runtime APIs. */
    public NativeGame(File directory) throws Exception { this(null,directory); }

    private NativeGame(Context context,File directory) throws Exception {
        this.context=context;
        if(context==null && (directory==null || !directory.isDirectory()))
            throw new IOException("The singing model directory is missing.");
        byte[] source;
        try(InputStream in=context==null?new FileInputStream(new File(directory,"manifest.json")):
                context.getAssets().open(ASSET_ROOT+"manifest.json")) {
            source=readBounded(in,262144);
        }
        JSONObject manifest=new JSONObject(new String(source,StandardCharsets.UTF_8));
        if(!MODEL_ID.equals(manifest.getString("id")) || manifest.getDouble("sampleRate")!=SAMPLE_RATE ||
                manifest.getDouble("steps")!=STEPS || manifest.getDouble("radius")!=2 ||
                manifest.getDouble("frameSeconds")!=.01 || manifest.getDouble("boundaryThreshold")!=.2 ||
                manifest.getDouble("presenceThreshold")!=.2)
            throw new IOException("The singing model configuration is invalid.");
        JSONObject files=manifest.getJSONObject("files");
        for(int i=0;i<GRAPHS.length;i++) {
            JSONObject entry=files.getJSONObject(GRAPHS[i]+".onnx");
            if(entry.getLong("bytes")!=BYTES[i] || !HASHES[i].equals(entry.getString("sha256")))
                throw new IOException("The singing model identity is invalid.");
        }
        modelDirectory=context==null?directory.getCanonicalFile():new File(context.getCacheDir(),
                "native-game/"+hex(MessageDigest.getInstance("SHA-256").digest(source)));
        if(!modelDirectory.isDirectory() && !modelDirectory.mkdirs())
            throw new IOException("Not enough storage to prepare singing analysis.");
    }

    /** Returns unrounded passage-local {start,end,midi} notes. Seed is unsigned 32-bit. */
    public synchronized JSONArray predict(float[] pcm,int language,long seed,Listener listener,
            Cancellation cancellation) throws Exception {
        check(cancellation);
        float[] samples=validatedPcm(pcm,language,seed);
        synchronized(lifecycle){check(cancellation);running=true;}
        Throwable failure=null;
        try {
            prepareModels(cancellation);
            check(cancellation);
            OrtEnvironment environment=OrtEnvironment.getEnvironment();
            if(!RUNTIME_VERSION.equals(environment.getVersion()))
                throw new IOException("The singing inference runtime version is invalid.");
            synchronized(lifecycle) {
                check(cancellation);
                activeRun=new OrtSession.RunOptions();
            }
            for(int i=0;i<GRAPHS.length;i++) {
                check(cancellation);
                progress(listener,0,"Loading singing model "+(i+1)+"/"+GRAPHS.length);
                try(Owned<OrtSession.SessionOptions> resource=owned(new OrtSession.SessionOptions())) {
                    OrtSession.SessionOptions options=resource.value;
                    options.setIntraOpNumThreads(Math.max(1,Math.min(4,Runtime.getRuntime().availableProcessors())));
                    options.setInterOpNumThreads(1);
                    options.setExecutionMode(OrtSession.SessionOptions.ExecutionMode.SEQUENTIAL);
                    options.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT);
                    options.setCPUArenaAllocator(false);
                    options.setMemoryPatternOptimization(false);
                    options.addConfigEntry("session.intra_op.allow_spinning","0");
                    // Store before checking cancellation so even a constructor
                    // returning after cancellation is retired by the worker.
                    sessions.put(GRAPHS[i],environment.createSession(
                            new File(modelDirectory,GRAPHS[i]+".onnx").getAbsolutePath(),options));
                }
                check(cancellation);
            }
            JSONArray notes=infer(environment,samples,language,seed,listener,cancellation);
            check(cancellation);
            return notes;
        } catch(Exception|Error error) {
            failure=error;
            synchronized(lifecycle){cancelled=true;}
            throw error;
        } finally {
            // No JNI close holds lifecycle: cancel/close must remain nonblocking.
            Throwable retirement=null;boolean cleanupConfirmed=false;
            try {
                for(OrtSession session:sessions.values())try{retire(session);}catch(Throwable error){
                    if(retirement==null)retirement=error;
                }
                sessions.clear();
                OrtSession.RunOptions retiringRun;
                synchronized(lifecycle) {
                    retiringRun=activeRun;activeRun=null;
                }
                // cancel cannot terminate a RunOptions handle once its destructor
                // starts, and a slow native destructor must not hold lifecycle.
                if(retiringRun!=null)try{retire(retiringRun);}catch(Throwable error){
                    if(retirement==null)retirement=error;
                }
                cleanupConfirmed=retirement==null;
            } finally {
                synchronized(lifecycle){
                    running=false;
                    // Even if another cleanup operation fails unexpectedly, never
                    // mistake an attempted destructor for confirmed retirement.
                    if(!cleanupConfirmed){retirementUnconfirmed=true;cancelled=true;}
                }
            }
            if(retirement!=null) {
                if(failure!=null)failure.addSuppressed(retirement);
                else if(retirement instanceof Exception)throw (Exception)retirement;
                else if(retirement instanceof Error)throw (Error)retirement;
                else throw new IOException("The singing runtime could not be retired.",retirement);
            }
        }
    }

    private JSONArray infer(OrtEnvironment environment,float[] pcm,int language,long seed,
            Listener listener,Cancellation cancellation) throws Exception {
        float duration=(float)(pcm.length/(double)SAMPLE_RATE);
        try(Owned<OnnxTensor> waveform=owned(floats(environment,pcm,1,pcm.length));
            Owned<OnnxTensor> encoderDuration=owned(floats(environment,new float[]{duration},1));
            Owned<OnnxTensor> durations=owned(floats(environment,new float[]{duration},1,1));
            Owned<OnnxTensor> lang=owned(longs(environment,language,1));
            Owned<OnnxTensor> threshold=owned(floats(environment,new float[]{.2f}));
            Owned<OnnxTensor> radius=owned(longs(environment,2));
            Owned<OrtSession.Result> encoded=owned(run("encoder",feeds("waveform",waveform.value,"duration",encoderDuration.value),cancellation))) {
            OnnxTensor maskT=tensor(encoded.value,"maskT");
            long[] frameShape=maskT.getInfo().getShape();
            if(frameShape.length!=2 || frameShape[0]!=1 || frameShape[1]<1 || frameShape[1]>MAX_FRAMES)
                throw new IOException("Invalid singing frame geometry.");
            int frames=(int)frameShape[1];
            checked(maskT,OnnxJavaType.BOOL,cancellation,1,frames);
            OnnxTensor xSeg=checked(tensor(encoded.value,"x_seg"),OnnxJavaType.FLOAT,cancellation,1,frames,FEATURES);
            OnnxTensor xEst=checked(tensor(encoded.value,"x_est"),OnnxJavaType.FLOAT,cancellation,1,frames,FEATURES);
            progress(listener,1.0/(STEPS+2),"Singing features recovered");
            try(Owned<OrtSession.Result> known=owned(run("dur2bd",feeds("durations",durations.value,"maskT",maskT),cancellation))) {
                OnnxTensor knownBoundaries=checked(tensor(known.value,"boundaries"),OnnxJavaType.BOOL,cancellation,1,frames);
                OrtSession.Result previous=null;
                try {
                    for(int k=0;k<STEPS;k++) {
                        check(cancellation);
                        try(Owned<OnnxTensor> time=owned(floats(environment,new float[]{k/(float)STEPS},1));
                            Owned<OnnxTensor> random=owned(floats(environment,noise(frames,(seed+k*2654435761L)&0xffffffffL),frameShape))) {
                            OrtSession.Result next=run("segmenter",feeds("x_seg",xSeg,"maskT",maskT,
                                    "known_boundaries",knownBoundaries,"prev_boundaries",
                                    previous==null?knownBoundaries:tensor(previous,"boundaries"),
                                    "language",lang.value,"threshold",threshold.value,"radius",radius.value,"t",time.value,
                                    "random_uniform",random.value),cancellation);
                            OrtSession.Result old=previous;previous=next;
                            if(old!=null)retire(old);
                            checked(tensor(previous,"boundaries"),OnnxJavaType.BOOL,cancellation,1,frames);
                            progress(listener,(k+2.0)/(STEPS+2),"Singing detail "+(k+1)+"/"+STEPS);
                        }
                    }
                    OnnxTensor boundaries=tensor(previous,"boundaries");
                    try(Owned<OrtSession.Result> timing=owned(run("bd2dur",feeds("boundaries",boundaries,"maskT",maskT),cancellation))) {
                        OnnxTensor lengths=tensor(timing.value,"durations");long[] noteShape=lengths.getInfo().getShape();
                        if(noteShape.length!=2 || noteShape[0]!=1 || noteShape[1]<0 || noteShape[1]>frames+1)
                            throw new IOException("Invalid singing note geometry.");
                        int count=(int)noteShape[1];
                        checked(lengths,OnnxJavaType.FLOAT,cancellation,1,count);
                        OnnxTensor maskN=checked(tensor(timing.value,"maskN"),OnnxJavaType.BOOL,cancellation,1,count);
                        try(Owned<OrtSession.Result> estimated=owned(run("estimator",feeds("x_est",xEst,"boundaries",boundaries,
                                "maskT",maskT,"maskN",maskN,"threshold",threshold.value),cancellation))) {
                            OnnxTensor pitches=checked(tensor(estimated.value,"scores"),OnnxJavaType.FLOAT,cancellation,1,count);
                            OnnxTensor presence=checked(tensor(estimated.value,"presence"),OnnxJavaType.BOOL,cancellation,1,count);
                            JSONArray notes=notes(lengths.getFloatBuffer(),pitches.getFloatBuffer(),maskN.getByteBuffer(),
                                    presence.getByteBuffer(),duration);
                            check(cancellation);progress(listener,1,"Singing passage recovered");
                            return notes;
                        }
                    }
                }finally{if(previous!=null)retire(previous);}
            }
        }
    }

    /** Stops kernels cooperatively; the active worker alone retires its sessions. */
    public void cancel() {
        synchronized(lifecycle) {
            cancelled=true;
            if(activeRun!=null)try{activeRun.setTerminate(true);}catch(OrtException ignored){/* check also observes cancellation. */}
        }
    }
    /** Nonblocking; callers must confirm isRetired before releasing native ownership. */
    @Override public void close(){synchronized(lifecycle){closed=true;cancel();}}
    /** False after any failed destructor until this process is restarted. */
    public boolean isRetired(){synchronized(lifecycle){return closed&&!running&&!retirementUnconfirmed;}}

    private void check(Cancellation cancellation) throws InterruptedIOException {
        if(cancelled || closed || Thread.currentThread().isInterrupted() ||
                (cancellation!=null&&cancellation.cancelled()))
            throw new InterruptedIOException("Singing analysis was cancelled.");
    }
    private OrtSession.Result run(String graph,Map<String,OnnxTensor> input,Cancellation cancellation) throws Exception {
        check(cancellation);
        OrtSession.Result result=sessions.get(graph).run(input,activeRun);
        try{check(cancellation);return result;}catch(Exception|Error error){retire(result);throw error;}
    }
    /** Every JNI owner, including tensors and results, uses this tracked close. */
    private void retire(AutoCloseable resource)throws Exception {
        try{resource.close();}
        catch(Throwable error){
            synchronized(lifecycle){retirementUnconfirmed=true;cancelled=true;}
            if(error instanceof Exception)throw (Exception)error;
            if(error instanceof Error)throw (Error)error;
            throw new IOException("The singing runtime could not be retired.",error);
        }
    }
    private <T extends AutoCloseable> Owned<T> owned(T value)throws Exception {
        try{return new Owned<T>(value);}
        catch(RuntimeException|Error failure){
            // Wrapper allocation itself must not orphan an already-created JNI owner.
            try{retire(value);}catch(Exception|Error cleanup){failure.addSuppressed(cleanup);}
            throw failure;
        }
    }
    private final class Owned<T extends AutoCloseable> implements AutoCloseable {
        final T value;
        Owned(T value){this.value=value;}
        @Override public void close()throws Exception {retire(value);}
    }
    private OnnxTensor checked(OnnxTensor value,OnnxJavaType type,Cancellation cancellation,long... shape) throws Exception {
        if(value.getInfo().type!=type || !Arrays.equals(value.getInfo().getShape(),shape))
            throw new IOException("Unexpected singing tensor type or shape.");
        if(type==OnnxJavaType.FLOAT) {
            FloatBuffer values=value.getFloatBuffer();
            for(int i=0;i<values.remaining();i++) {
                if((i&4095)==0)check(cancellation);
                if(!Float.isFinite(values.get(i)))throw new IOException("Singing inference returned a non-finite tensor.");
            }
        } else if(type==OnnxJavaType.BOOL) {
            ByteBuffer values=value.getByteBuffer();
            for(int i=0;i<values.remaining();i++)if(values.get(i)!=0&&values.get(i)!=1)
                throw new IOException("Singing inference returned an invalid mask.");
        }
        return value;
    }
    static float[] validatedPcm(float[] pcm,int language,long seed) throws IOException {
        if(pcm==null || pcm.length<1 || pcm.length>MAX_SAMPLES || language<0 || language>4 || seed<0 || seed>0xffffffffL)
            throw new IOException("Expected one nonempty singing passage of at most 16 seconds and valid language/seed.");
        float[] result=pcm.clone();
        for(float value:result)if(!Float.isFinite(value))throw new IOException("Singing audio contains invalid samples.");
        return result;
    }
    static float[] noise(int count,long seed) {
        float[] values=new float[count];int x=(int)seed;
        for(int i=0;i<count;i++){x^=x<<13;x^=x>>>17;x^=x<<5;values[i]=(float)((Integer.toUnsignedLong(x)+.5)/4294967296.0);}
        return values;
    }
    static JSONArray notes(FloatBuffer lengths,FloatBuffer pitches,ByteBuffer mask,ByteBuffer present,double duration) throws Exception {
        int count=lengths.remaining();
        if(pitches.remaining()!=count || mask.remaining()!=count || present.remaining()!=count ||
                !Double.isFinite(duration) || duration<=0 || duration>16)
            throw new IOException("Invalid singing note buffers.");
        JSONArray notes=new JSONArray();double start=0;
        for(int i=0;i<count;i++) {
            double length=lengths.get(lengths.position()+i),end=start+length,midi=pitches.get(pitches.position()+i);
            byte valid=mask.get(mask.position()+i),voiced=present.get(present.position()+i);
            if(!Double.isFinite(length) || length<0 || !Double.isFinite(midi) || !Double.isFinite(end) ||
                    end>duration+.02 || (valid!=0&&valid!=1) || (voiced!=0&&voiced!=1))
                throw new IOException("Singing transcription returned invalid note data.");
            if(valid!=0 && voiced!=0 && length>=.06 && midi>=0 && midi<=127) {
                if(end>duration+.001)throw new IOException("Singing notes exceed the passage clock.");
                notes.put(new JSONObject().put("start",start).put("end",end).put("midi",midi));
            }
            start=end;
        }
        return notes;
    }
    private static OnnxTensor tensor(OrtSession.Result result,String name) throws IOException {
        OnnxValue value=result.get(name).orElse(null);
        if(!(value instanceof OnnxTensor))throw new IOException("Missing singing tensor output.");
        return (OnnxTensor)value;
    }
    private static OnnxTensor floats(OrtEnvironment environment,float[] values,long... shape) throws Exception {
        FloatBuffer data=ByteBuffer.allocateDirect(Math.multiplyExact(values.length,4)).order(ByteOrder.nativeOrder()).asFloatBuffer();
        data.put(values).flip();return OnnxTensor.createTensor(environment,data,shape);
    }
    private static OnnxTensor longs(OrtEnvironment environment,long value,long... shape) throws Exception {
        LongBuffer data=ByteBuffer.allocateDirect(8).order(ByteOrder.nativeOrder()).asLongBuffer();
        data.put(value).flip();return OnnxTensor.createTensor(environment,data,shape);
    }
    private static Map<String,OnnxTensor> feeds(Object... pairs) {
        Map<String,OnnxTensor> values=new LinkedHashMap<>();
        for(int i=0;i<pairs.length;i+=2)values.put((String)pairs[i],(OnnxTensor)pairs[i+1]);return values;
    }
    private void prepareModels(Cancellation cancellation) throws Exception {
        List<Integer> missing=new ArrayList<>();long missingBytes=0,largest=0;
        for(int i=0;i<GRAPHS.length;i++) {
            check(cancellation);File file=new File(modelDirectory,GRAPHS[i]+".onnx");
            if(file.isFile() && file.length()==BYTES[i] && HASHES[i].equals(digest(file,cancellation)))continue;
            if(context==null)throw new IOException("The singing model checksum does not match: "+GRAPHS[i]);
            missing.add(i);missingBytes+=BYTES[i];largest=Math.max(largest,BYTES[i]);
        }
        if(!missing.isEmpty() && modelDirectory.getUsableSpace()<missingBytes+largest+32L*1024*1024)
            throw new IOException("Singing analysis needs more free storage to prepare its models.");
        for(int index:missing) {
            check(cancellation);String filename=GRAPHS[index]+".onnx";
            File partial=File.createTempFile(".model-",".partial",modelDirectory);
            try {
                MessageDigest hash=MessageDigest.getInstance("SHA-256");long bytes=0;
                try(InputStream in=context.getAssets().open(ASSET_ROOT+filename);FileOutputStream out=new FileOutputStream(partial)) {
                    byte[] buffer=new byte[262144];int count;
                    while((count=in.read(buffer))!=-1) {
                        check(cancellation);bytes+=count;
                        if(bytes>BYTES[index])throw new IOException("The singing model is too large.");
                        out.write(buffer,0,count);hash.update(buffer,0,count);
                    }
                    out.getFD().sync();
                }
                if(bytes!=BYTES[index] || !HASHES[index].equals(hex(hash.digest())))
                    throw new IOException("The singing model is damaged.");
                check(cancellation);
                Files.move(partial.toPath(),new File(modelDirectory,filename).toPath(),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
            }finally{partial.delete();}
        }
    }
    private String digest(File file,Cancellation cancellation) throws Exception {
        MessageDigest hash=MessageDigest.getInstance("SHA-256");
        try(InputStream in=new FileInputStream(file)){byte[] buffer=new byte[262144];int count;
            while((count=in.read(buffer))!=-1){check(cancellation);hash.update(buffer,0,count);}}
        return hex(hash.digest());
    }
    private static byte[] readBounded(InputStream in,int limit) throws IOException {
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();byte[] buffer=new byte[8192];int count;
        while((count=in.read(buffer))!=-1){if(bytes.size()+count>limit)throw new IOException("The singing manifest is too large.");bytes.write(buffer,0,count);}
        return bytes.toByteArray();
    }
    private static String hex(byte[] bytes){StringBuilder text=new StringBuilder(bytes.length*2);for(byte b:bytes)text.append(Character.forDigit((b>>>4)&15,16)).append(Character.forDigit(b&15,16));return text.toString();}
    private static void progress(Listener listener,double value,String message){if(listener!=null)listener.update(value,message);}
}
