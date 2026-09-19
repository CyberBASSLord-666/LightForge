package com.cyberbasslord.lightforge;

import android.content.Context;
import android.util.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Job-owned, bounded mono-PCM transport for the unchanged GAME graphs.
 * A fresh engine owns each passage. Native cleanup completes under the shared
 * process gate and crash lease before any terminal result becomes observable.
 * Neither audio nor inferred notes are written to diagnostic logs.
 */
final class NativeGameTask implements AutoCloseable {
    static final int RATE=44100,MAX_SAMPLES=16*RATE,MAX_NOTES=1601;
    static final long MAX_INPUT_BYTES=MAX_SAMPLES*4L;
    private static final int MAX_CHUNK=64*1024;
    private static final String UUID_PATTERN="[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}";
    // Shared with service admission. Only process death can prove that unknown
    // native handles no longer overlap a replacement native or WASM analysis.
    private static volatile boolean processRetirementUnconfirmed;
    private static final AtomicInteger outstandingWorkers=new AtomicInteger();
    private final Context context;
    private final String ownerJobId;
    private final File jobDirectory;
    private final NativeRuntimeGuard runtimeGuard;
    private final ExecutorService executor=Executors.newSingleThreadExecutor();
    private volatile boolean closed,cancelled,retirementUnconfirmed;
    private volatile NativeGame engine;
    // Bridge state is guarded by this. The worker never holds this monitor
    // across model loading, inference, or native destruction.
    private boolean workerActive;
    private String token,state="idle",message="";
    private File input;
    private FileOutputStream inputStream;
    private long expectedBytes,received,seed;
    private int language,completedPasses;
    private double runningProgress;
    private JSONArray notes;

    NativeGameTask(Context context,String jobId)throws IOException {
        this.context=context.getApplicationContext();
        if(jobId==null||!jobId.matches(UUID_PATTERN))throw new IOException("Invalid native singing job.");
        ownerJobId=jobId;
        try{runtimeGuard=new NativeRuntimeGuard(new File(this.context.getFilesDir(),"diagnostics"),this.context.getPackageManager().getPackageInfo(this.context.getPackageName(),0).versionCode+"-"+NativeDeux.RUNTIME_VERSION);}
        catch(android.content.pm.PackageManager.NameNotFoundException error){throw new IOException("The native runtime identity could not be checked.",error);}
        // Replacement tasks cannot delete the retiring task's still-open PCM,
        // and an old idempotent close cannot remove replacement input.
        File root=directory(this.context.getCacheDir(),"native-game-passages");
        jobDirectory=directory(directory(root,jobId),UUID.randomUUID().toString());
    }

    synchronized String availability(String owner)throws Exception {
        owns(owner);
        requireRuntimeRetirement();
        List<NativeRuntimeGuard.Exit> exits=new ArrayList<>();
        NativeRuntimeGuard.State prior=runtimeGuard.state();
        if(android.os.Build.VERSION.SDK_INT>=30&&prior!=null&&!prior.disabled){
            android.app.ActivityManager manager=(android.app.ActivityManager)context.getSystemService(Context.ACTIVITY_SERVICE);
            if(manager==null)throw new IOException("Android native compatibility checks are unavailable.");
            for(android.app.ApplicationExitInfo exit:manager.getHistoricalProcessExitReasons(context.getPackageName(),prior.pid,32))
                exits.add(new NativeRuntimeGuard.Exit(exit.getPid(),exit.getReason(),exit.getStatus(),exit.getTimestamp(),context.getPackageName().equals(exit.getProcessName())));
        }
        boolean available=runtimeGuard.reconcile(exits,System.currentTimeMillis());
        JSONObject result=new JSONObject().put("available",available).put("runtime",NativeDeux.RUNTIME_VERSION).put("graph","game")
            .put("sampleRate",RATE).put("maxSamples",MAX_SAMPLES).put("maxInputBytes",MAX_INPUT_BYTES).put("steps",8);
        if(!available)result.put("reason","previous-native-crash").put("message","Compatibility processing enabled after a native crash. The same singing model is used; analysis may take longer.");
        return result.toString();
    }

    synchronized String begin(String owner,long bytes,int language,long seed)throws Exception {
        owns(owner);
        requireRuntimeRetirement();
        if(workerActive)throw new IOException("A native singing passage is still retiring.");
        if("uploading".equals(state)||"running".equals(state))throw new IOException("A native singing passage is already running.");
        if(bytes<4||bytes>MAX_INPUT_BYTES||bytes%4!=0)throw new IOException("The native singing input size is invalid.");
        if(language<0||language>4||seed<0||seed>0xffffffffL)throw new IOException("The native singing settings are invalid.");
        releaseInput();notes=null;token=UUID.randomUUID().toString();expectedBytes=bytes;received=0;
        this.language=language;this.seed=seed;cancelled=false;runningProgress=0;
        input=new File(jobDirectory,token+".input");
        try{inputStream=new FileOutputStream(input,false);}
        catch(IOException error){releaseInput();token=null;state="idle";throw error;}
        state="uploading";message="Sending singing audio to Android";
        return status(owner,token);
    }

    synchronized String append(String owner,String current,String encoded)throws Exception {
        owns(owner);
        if(!same(current)||!"uploading".equals(state))throw new IOException("The native singing passage is no longer accepting input.");
        if(encoded==null||encoded.length()>((MAX_CHUNK+2)/3)*4+8)throw new IOException("The native singing input chunk is too large.");
        byte[] bytes;
        try{bytes=Base64.decode(encoded,Base64.DEFAULT);}catch(IllegalArgumentException error){throw new IOException("The native singing input chunk is invalid.",error);}
        if(bytes.length<1||bytes.length>MAX_CHUNK||received+bytes.length>expectedBytes)throw new IOException("The native singing input size is invalid.");
        if(inputStream==null)throw new IOException("The native singing input stream is unavailable.");
        inputStream.write(bytes);received+=bytes.length;
        return status(owner,current);
    }

    synchronized String run(String owner,String current)throws Exception {
        owns(owner);
        if(!same(current)||!"uploading".equals(state))throw new IOException("The native singing passage is not ready.");
        if(received!=expectedBytes)throw new IOException("The native singing input is incomplete.");
        if(inputStream==null)throw new IOException("The native singing input stream is unavailable.");
        inputStream.flush();inputStream.getFD().sync();inputStream.close();inputStream=null;
        state="running";message="Running singing analysis on Android";cancelled=false;workerActive=true;
        final String active=current;
        // Reserve before queueing: a stopped service may be reused while this
        // queued/retiring worker still owns future or live native resources.
        outstandingWorkers.incrementAndGet();
        try{executor.execute(()->infer(active));}
        catch(RuntimeException|Error error){outstandingWorkers.decrementAndGet();workerActive=false;state="failed";message="Native singing analysis could not start.";releaseInput();throw error;}
        return status(owner,current);
    }

    synchronized String status(String owner,String current)throws Exception {
        owns(owner);
        if(!same(current))throw new IOException("This native singing passage is no longer active.");
        double progress="completed".equals(state)?1:"running".equals(state)?.1+.8*runningProgress:"uploading".equals(state)?received/(double)expectedBytes*.1:0;
        JSONObject result=new JSONObject().put("token",token).put("state",state).put("message",message).put("progress",progress)
            .put("completedPasses",completedPasses).put("sampleRate",RATE).put("samples",expectedBytes/4)
            .put("language",language).put("seed",seed).put("steps",8).put("model",NativeGame.MODEL_ID);
        if("completed".equals(state)&&notes!=null)result.put("notes",notes);
        return result.toString();
    }

    synchronized void cancel(String owner,String current){
        if(closed||!ownerJobId.equals(owner)||!same(current))return;
        if(!"uploading".equals(state)&&!"running".equals(state))return;
        cancelled=true;notes=null;
        NativeGame active=engine;if(active!=null)active.cancel();
        if("uploading".equals(state)){releaseInput();state="cancelled";message="Native singing analysis was cancelled.";}
    }

    synchronized String releaseIdle(String owner)throws Exception {
        owns(owner);
        if(retirementUnconfirmed)throw new IOException("Native singing cleanup could not be confirmed. Restart the app before analyzing again.");
        if(workerActive||"running".equals(state)||"uploading".equals(state))throw new IOException("The native singing passage is still running.");
        releaseInput();notes=null;token=null;state="idle";message="";return "{}";
    }

    private void infer(String active){
        boolean acquired=false;String lease=null;NativeGame local=null;JSONArray completed=null;Throwable failure=null;
        try{
            // Reject malformed or nonfinite PCM before touching the native runtime.
            float[] pcm=readPcm();checkCancelled();
            while(!NativeDeux.INFERENCE_GATE.tryAcquire(250,TimeUnit.MILLISECONDS))checkCancelled();
            acquired=true;checkCancelled();
            // Covers library loading, session construction, inference and destruction.
            lease=runtimeGuard.begin(android.os.Process.myPid(),System.currentTimeMillis());
            local=new NativeGame(context);engine=local;checkCancelled();
            completed=local.predict(pcm,language,seed,(value,detail)->{
                synchronized(this){if(active.equals(token)&&!cancelled&&!closed&&Double.isFinite(value))runningProgress=Math.max(runningProgress,Math.max(0,Math.min(1,value)));}
            },()->cancelled||closed||Thread.currentThread().isInterrupted());
            checkCancelled();validateNotes(completed,pcm.length);
            completed=new JSONArray(completed.toString());
        }catch(Throwable error){failure=error;completed=null;}
        finally{
            // Never hold the bridge monitor while a native destructor is running.
            boolean retired=true;
            try{if(local!=null){local.close();retired=local.isRetired();}}catch(Throwable error){failure=error;completed=null;retired=false;}
            if(!retired){retirementUnconfirmed=true;processRetirementUnconfirmed=true;completed=null;}
            else engine=null;
            synchronized(this){releaseInput();}
            // A failed native destructor is not a recoverable model failure.
            // Preserve the process gate and durable lease: neither fallback nor
            // a replacement renderer may overlap unknown native allocations.
            if(retired){
                try{runtimeGuard.end(lease);}catch(IOException error){failure=error;completed=null;}
                if(acquired)NativeDeux.INFERENCE_GATE.release();
                outstandingWorkers.decrementAndGet();
            }
            synchronized(this){
                workerActive=false;
                if(active.equals(token)){
                    if(retirementUnconfirmed){notes=null;state="retirement-failed";message="Native singing cleanup could not be confirmed. Restart the app before analyzing again.";}
                    else if(failure==null&&completed!=null&&!closed&&!cancelled){notes=completed;completedPasses++;state="completed";message="Singing analysis complete";}
                    else{notes=null;state=closed||cancelled?"cancelled":"failed";message=closed||cancelled?"Native singing analysis was cancelled.":"Native singing analysis failed. Retry in compatibility mode.";}
                }
                if(closed)removeDirectory();
            }
        }
    }

    private float[] readPcm()throws IOException {
        checkCancelled();
        if(input==null||!input.isFile()||input.length()!=expectedBytes)throw new IOException("The native singing input is incomplete.");
        byte[] bytes=new byte[(int)expectedBytes];
        try(DataInputStream stream=new DataInputStream(new FileInputStream(input))){stream.readFully(bytes);if(stream.read()!=-1)throw new IOException("The native singing input is too large.");}
        ByteBuffer buffer=ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);float[] pcm=new float[bytes.length/4];
        for(int i=0;i<pcm.length;i++){if((i&1023)==0)checkCancelled();pcm[i]=buffer.getFloat();if(!Float.isFinite(pcm[i]))throw new IOException("The native singing input contains invalid samples.");}
        return pcm;
    }

    private static void validateNotes(JSONArray result,int samples)throws Exception {
        if(result==null||result.length()>MAX_NOTES)throw new IOException("The native singing result is too large.");
        double previous=0,duration=samples/(double)RATE;
        for(int i=0;i<result.length();i++){
            JSONObject note=result.getJSONObject(i);
            if(note.length()!=3||!(note.get("start") instanceof Number)||!(note.get("end") instanceof Number)||!(note.get("midi") instanceof Number))throw new IOException("The native singing result is invalid.");
            double start=note.getDouble("start"),end=note.getDouble("end"),midi=note.getDouble("midi");
            if(!Double.isFinite(start)||!Double.isFinite(end)||!Double.isFinite(midi)||start<0||start<previous-1e-6||end-start<.06-1e-6||end>duration+.001||midi<0||midi>127)throw new IOException("The native singing result is invalid.");
            previous=end;
        }
    }

    private void checkCancelled()throws InterruptedIOException {if(closed||cancelled||Thread.currentThread().isInterrupted())throw new InterruptedIOException("Native singing analysis was cancelled.");}
    private boolean same(String current){return current!=null&&current.equals(token);}
    private void owns(String owner)throws IOException {if(closed||!ownerJobId.equals(owner))throw new IOException("Native singing analysis is no longer active.");}
    private void releaseInput(){if(inputStream!=null)try{inputStream.close();}catch(IOException ignored){}inputStream=null;if(input!=null)input.delete();input=null;}
    private void removeDirectory(){jobDirectory.delete();jobDirectory.getParentFile().delete();}
    @Override public synchronized void close(){
        if(closed)return;closed=true;cancelled=true;notes=null;
        NativeGame active=engine;if(active!=null)active.cancel();
        // A queued worker remains the sole cleanup owner; shutdownNow would
        // discard it and could falsely report that native retirement finished.
        if(!workerActive)executor.execute(()->{synchronized(this){releaseInput();removeDirectory();}});
        executor.shutdown();
    }
    boolean isRetired(){return closed&&!retirementUnconfirmed&&executor.isTerminated();}
    static boolean runtimeRetirementConfirmed(){return !processRetirementUnconfirmed&&outstandingWorkers.get()==0;}
    private static void requireRuntimeRetirement()throws IOException {
        if(processRetirementUnconfirmed)throw new IOException("Native singing cleanup could not be confirmed. Restart the app before analyzing again.");
        if(outstandingWorkers.get()!=0)throw new IOException("A native singing passage is still retiring.");
    }
    private static File directory(File parent,String name)throws IOException {
        File directory=new File(parent,name);
        if(Files.isSymbolicLink(directory.toPath())||(!directory.mkdir()&&!directory.isDirectory())||Files.isSymbolicLink(directory.toPath()))throw new IOException("Native singing storage is unavailable.");
        return directory;
    }
}
