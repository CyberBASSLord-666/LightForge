package com.cyberbasslord.lightforge;

import android.content.Context;
import android.util.Base64;
import ai.onnxruntime.*;
import org.json.JSONObject;
import java.io.*;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.Collections;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/**
 * Native bridge for the unchanged balanced MDX graph. JavaScript keeps the
 * trained STFT/overlap-add code; only the 12.6 MiB model input and output cross
 * the WebView bridge in bounded base64 chunks. This avoids the renderer's
 * long-lived WASM allocator while preserving every model and decoder sample.
 */
final class NativeMdxTask implements AutoCloseable {
    static final int RATE=44100, BINS=3072, FRAMES=256, INPUT_FLOATS=4*BINS*FRAMES;
    static final long INPUT_BYTES=INPUT_FLOATS*4L;
    private static final String ASSET_ROOT="analysis/models/";
    private static final int MAX_CHUNK=64*1024;
    private final Context context;
    private final File modelDirectory,jobDirectory;
    private final String ownerJobId;
    private final NativeRuntimeGuard runtimeGuard;
    private final ExecutorService executor=Executors.newSingleThreadExecutor();
    private final Object lifecycle=new Object();
    private volatile boolean closed,cancelled;
    private volatile OrtSession session;
    private volatile OrtSession.RunOptions activeRun;
    // Guarded by this; terminal state is published only after native cleanup.
    private boolean workerActive;
    private int completedPasses;
    // Keep one bounded pair of direct tensors for the entire service job. This
    // avoids allocating a fresh 25 MiB native buffer pair for every passage.
    private ByteBuffer inputBuffer,outputBuffer;
    private File input,output;
    private FileOutputStream inputStream;
    private String token,state="idle",message="";
    private long received;
    private JSONObject manifest;

    NativeMdxTask(Context context,String jobId)throws IOException {
        this.context=context.getApplicationContext();
        if(jobId==null||!jobId.matches("[a-f0-9-]{36}"))throw new IOException("Invalid native analysis job.");
        ownerJobId=jobId;
        try{runtimeGuard=new NativeRuntimeGuard(new File(this.context.getFilesDir(),"diagnostics"),this.context.getPackageManager().getPackageInfo(this.context.getPackageName(),0).versionCode+"-"+NativeDeux.RUNTIME_VERSION);}
        catch(android.content.pm.PackageManager.NameNotFoundException error){throw new IOException("The native runtime identity could not be checked.",error);}
        jobDirectory=new File(this.context.getCacheDir(),"native-mdx-passages/"+jobId);
        if(!jobDirectory.mkdirs()&&!jobDirectory.isDirectory())throw new IOException("Native analysis storage is unavailable.");
        try {
            byte[] bytes=readAsset("separator-mdx-model.json",262144);
            manifest=new JSONObject(new String(bytes,StandardCharsets.UTF_8));
            if(manifest.optInt("sampleRate")!=RATE||manifest.optInt("frequencyBins")!=BINS||manifest.optInt("frames")!=FRAMES
                ||manifest.optInt("nFFT")!=7680||manifest.optInt("hop")!=1024||manifest.optInt("channels")!=2
                ||!"uvr-mdx-voc-ft.onnx".equals(manifest.optString("file")))throw new IOException("The balanced MDX model configuration is invalid.");
            String sha=manifest.optString("sha256");if(!sha.matches("[0-9a-f]{64}"))throw new IOException("The balanced MDX model inventory is invalid.");
            modelDirectory=new File(this.context.getCacheDir(),"native-mdx/"+sha);if(!modelDirectory.isDirectory()&&!modelDirectory.mkdirs())throw new IOException("Native model storage is unavailable.");
            cleanupStaleFiles();
        }catch(Exception error){throw error instanceof IOException?(IOException)error:new IOException("The balanced MDX model configuration is invalid.",error);}
    }

    synchronized String availability(String owner)throws Exception {
        // Do not extract or construct the 67 MiB model on the synchronous
        // JavaScript bridge call. The first inference performs that work on
        // the dedicated native executor instead.
        owns(owner);
        java.util.List<NativeRuntimeGuard.Exit> exits=new java.util.ArrayList<>();
        NativeRuntimeGuard.State prior=runtimeGuard.state();
        if(android.os.Build.VERSION.SDK_INT>=30&&prior!=null&&!prior.disabled){
            android.app.ActivityManager manager=(android.app.ActivityManager)context.getSystemService(Context.ACTIVITY_SERVICE);
            if(manager==null)throw new IOException("Android native compatibility checks are unavailable.");
            for(android.app.ApplicationExitInfo exit:manager.getHistoricalProcessExitReasons(context.getPackageName(),prior.pid,32))
                exits.add(new NativeRuntimeGuard.Exit(exit.getPid(),exit.getReason(),exit.getStatus(),exit.getTimestamp(),context.getPackageName().equals(exit.getProcessName())));
        }
        boolean available=runtimeGuard.reconcile(exits,System.currentTimeMillis());
        JSONObject result=new JSONObject().put("available",available).put("runtime",NativeDeux.RUNTIME_VERSION).put("graph","mdx").put("inputBytes",INPUT_BYTES);
        if(!available)result.put("reason","previous-native-crash").put("message","Compatibility processing enabled after a native crash. The same balanced model is used; analysis may take longer.");
        return result.toString();
    }

    synchronized String begin(String owner,long bytes)throws Exception {
        owns(owner);if(closed)throw new IOException("Native balanced analysis has stopped.");
        if(workerActive)throw new IOException("A native balanced passage is still retiring.");
        if(!"idle".equals(state)&&!"completed".equals(state)&&!"failed".equals(state)&&!"cancelled".equals(state))throw new IOException("A native balanced passage is already running.");
        if(bytes!=INPUT_BYTES)throw new IOException("The balanced MDX input is incomplete.");
        releaseFiles();token=UUID.randomUUID().toString();state="uploading";message="Sending balanced spectrum to Android";received=0;cancelled=false;
        input=new File(jobDirectory,token+".input");output=new File(jobDirectory,token+".bin");
        try{inputStream=new FileOutputStream(input,false);}catch(IOException error){releaseFiles();throw error;}
        return status(owner,token);
    }

    synchronized String append(String owner,String current,String encoded)throws Exception {
        owns(owner);if(!same(current)||!"uploading".equals(state))throw new IOException("The native balanced passage is no longer accepting input.");
        if(encoded==null||encoded.length()>((MAX_CHUNK+2)/3)*4+8)throw new IOException("The native balanced input chunk is too large.");
        byte[] bytes;try{bytes=Base64.decode(encoded,Base64.DEFAULT);}catch(IllegalArgumentException error){throw new IOException("The native balanced input chunk is invalid.",error);}
        if(bytes.length<1||bytes.length>MAX_CHUNK||received+bytes.length>INPUT_BYTES)throw new IOException("The native balanced input size is invalid.");
        if(inputStream==null)throw new IOException("The native balanced input stream is unavailable.");
        inputStream.write(bytes);received+=bytes.length;message="Sending balanced spectrum to Android · "+received+" / "+INPUT_BYTES+" bytes";return status(owner,current);
    }

    synchronized String run(String owner,String current)throws Exception {
        owns(owner);if(!same(current)||!"uploading".equals(state))throw new IOException("The native balanced passage is not ready.");
        if(received!=INPUT_BYTES)throw new IOException("The native balanced input is incomplete.");
        if(inputStream==null)throw new IOException("The native balanced input stream is unavailable.");
        inputStream.flush();inputStream.getFD().sync();inputStream.close();inputStream=null;
        state="running";message="Running balanced MDX on Android";cancelled=false;workerActive=true;final String active=current;
        executor.execute(()->infer(active));return status(owner,current);
    }

    synchronized String status(String owner,String current)throws Exception {
        owns(owner);if(!same(current))throw new IOException("This native balanced passage is no longer active.");
        JSONObject value=new JSONObject().put("token",token).put("state",state).put("progress",progress()).put("message",message).put("completedPasses",completedPasses);
        if("completed".equals(state))value.put("url","https://appassets.androidplatform.net/background/native-mdx/"+token+".bin");return value.toString();
    }

    /** Returns a completed output for the appassets transport, after ownership checks. */
    synchronized File result(String owner,String current)throws Exception {
        owns(owner);if(!same(current)||!"completed".equals(state)||output==null||!output.isFile()||output.length()!=INPUT_BYTES)
            throw new IOException("The native balanced output is not ready.");
        return output;
    }

    synchronized void cancel(String owner,String current){
        try{if(!ownsQuiet(owner)||!same(current))return;}catch(Exception ignored){return;}
        cancelled=true;
        if("uploading".equals(state)){state="cancelled";message="Native balanced analysis was cancelled.";if(inputStream!=null)try{inputStream.close();}catch(IOException ignored){}inputStream=null;}
        terminateRun();
    }

    synchronized String releaseIdle(String owner)throws Exception {
        owns(owner);if(workerActive||"running".equals(state)||"uploading".equals(state))throw new IOException("The native balanced passage is still running.");
        closeSession();clearBuffers();releaseFiles();state="idle";message="";token=null;return "{}";
    }

    private void infer(String active) {
        boolean acquired=false,completed=false;ByteBuffer inputBytes,outputBytes;OrtSession local=null;OrtSession.RunOptions runOptions=null;String lease=null;Throwable failure=null;
        try {
            while(!NativeDeux.INFERENCE_GATE.tryAcquire(250,TimeUnit.MILLISECONDS)){if(cancelled||closed)throw new InterruptedIOException("Native balanced analysis was cancelled.");}
            acquired=true;if(cancelled||closed)throw new InterruptedIOException("Native balanced analysis was cancelled.");
            // Native library initialization and graph construction may crash,
            // too. The durable lease must exist before the first ORT call.
            lease=runtimeGuard.begin(android.os.Process.myPid(),System.currentTimeMillis());
            ensureModel();if(cancelled||closed)throw new InterruptedIOException("Native balanced analysis was cancelled.");
            local=session;ensureBuffers();inputBytes=inputBuffer;outputBytes=outputBuffer;inputBytes.clear();outputBytes.clear();
            try(FileInputStream stream=new FileInputStream(input)){byte[] block=new byte[64*1024];int at=0,n;while((n=stream.read(block))!=-1){if(cancelled||closed)throw new InterruptedIOException("Native balanced analysis was cancelled.");if(at+n>INPUT_BYTES)throw new IOException("The native balanced input is too large.");inputBytes.position(at);inputBytes.put(block,0,n);at+=n;}if(at!=INPUT_BYTES)throw new IOException("The native balanced input is truncated.");}
            inputBytes.position(0);FloatBuffer inputFloat=inputBytes.asFloatBuffer();FloatBuffer outputFloat=outputBytes.asFloatBuffer();
            runOptions=new OrtSession.RunOptions();synchronized(lifecycle){activeRun=runOptions;if(cancelled||closed)runOptions.setTerminate(true);}
            if(cancelled||closed)throw new InterruptedIOException("Native balanced analysis was cancelled.");
            try(OnnxTensor x=OnnxTensor.createTensor(OrtEnvironment.getEnvironment(),inputFloat,new long[]{1,4,BINS,FRAMES});OnnxTensor y=OnnxTensor.createTensor(OrtEnvironment.getEnvironment(),outputFloat,new long[]{1,4,BINS,FRAMES});OrtSession.Result result=local.run(Collections.singletonMap("input",x),Collections.emptySet(),Collections.singletonMap("output",y),runOptions)){
                if(cancelled||closed)throw new InterruptedIOException("Native balanced analysis was cancelled.");
            }
            File target=output,partial=new File(jobDirectory,active+".partial");try(FileOutputStream stream=new FileOutputStream(partial)){ByteBuffer block=ByteBuffer.allocate(64*1024).order(ByteOrder.LITTLE_ENDIAN);for(int first=0;first<INPUT_FLOATS;){if(cancelled||closed)throw new InterruptedIOException("Native balanced analysis was cancelled.");block.clear();int count=Math.min(block.capacity()/4,INPUT_FLOATS-first);for(int i=0;i<count;i++){float value=outputFloat.get(first+i);if(!Float.isFinite(value))throw new IOException("The balanced MDX model returned invalid audio.");block.putFloat(value);}stream.write(block.array(),0,count*4);first+=count;}stream.getFD().sync();}Files.move(partial.toPath(),target.toPath(),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
            completed=true;
        }catch(Throwable error){failure=error;AppDiagnostics.record(context,"native-mdx-passage",error);}
        finally{
            synchronized(lifecycle){if(activeRun!=null){try{activeRun.close();}catch(Exception ignored){}activeRun=null;}}
            try{
                // A failed graph must release its allocations before the WASM
                // fallback starts. Keep the process gate and lease through
                // native destruction, without blocking the state monitor.
                while(true){
                    synchronized(this){
                        boolean retire=(!completed||closed||cancelled)&&(session!=null||inputBuffer!=null||outputBuffer!=null);
                        if(!retire){
                            try{runtimeGuard.end(lease);}catch(IOException error){AppDiagnostics.record(context,"native-mdx-marker",error);}
                            workerActive=false;
                            if(active.equals(token)){
                                if(completed&&!closed&&!cancelled){completedPasses++;state="completed";message="Balanced MDX complete";}
                                else{state=closed||cancelled?"cancelled":"failed";message=AnalysisJobStore.limited(failure==null||failure.getMessage()==null?"Native balanced analysis was cancelled.":failure.getMessage(),300);if(output!=null)output.delete();new File(jobDirectory,active+".partial").delete();}
                            }
                            if(closed){releaseFiles();jobDirectory.delete();}
                            break;
                        }
                    }
                    closeSession();clearBuffers();
                }
            }finally{if(acquired)NativeDeux.INFERENCE_GATE.release();}
        }
    }

    private double progress(){if("uploading".equals(state))return Math.min(.25,received/(double)INPUT_BYTES*.25);if("running".equals(state))return .75;return "completed".equals(state)?1:0;}
    private boolean same(String current){return current!=null&&current.equals(token);}
    private void owns(String owner)throws IOException{if(closed||!ownerJobId.equals(owner))throw new IOException("Native balanced analysis is no longer active.");}
    private boolean ownsQuiet(String owner){return !closed&&ownerJobId.equals(owner);}

    private void ensureBuffers(){
        if(inputBuffer==null)inputBuffer=ByteBuffer.allocateDirect(INPUT_FLOATS*4).order(ByteOrder.nativeOrder());
        if(outputBuffer==null)outputBuffer=ByteBuffer.allocateDirect(INPUT_FLOATS*4).order(ByteOrder.nativeOrder());
    }

    // Executor-owned while workerActive is true. Never hold the bridge/state
    // monitor across storage, library initialization, or graph construction:
    // status and cancellation must remain responsive if native loading stalls.
    private void ensureModel()throws Exception {
        if(session!=null)return;JSONObject entry=manifest;String filename=entry.getString("file");File model=new File(modelDirectory,filename);long bytes=entry.getLong("bytes");String sha=entry.getString("sha256");
        if(!model.isFile()||model.length()!=bytes||!sha.equals(digest(model))){File partial=File.createTempFile(".mdx-model-",".partial",modelDirectory);MessageDigest hash;try{hash=MessageDigest.getInstance("SHA-256");}catch(Exception error){partial.delete();throw error;}try(InputStream in=context.getAssets().open(ASSET_ROOT+filename);FileOutputStream out=new FileOutputStream(partial)){byte[] block=new byte[262144];int n;long total=0;while((n=in.read(block))!=-1){if(closed||cancelled)throw new InterruptedIOException("Native balanced analysis was cancelled.");total+=n;if(total>bytes)throw new IOException("The balanced MDX model is too large.");out.write(block,0,n);hash.update(block,0,n);}out.getFD().sync();if(total!=bytes||!sha.equals(hex(hash.digest())))throw new IOException("The balanced MDX model checksum does not match.");Files.move(partial.toPath(),model.toPath(),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);}finally{partial.delete();}}
        OrtEnvironment environment=OrtEnvironment.getEnvironment();try(OrtSession.SessionOptions options=new OrtSession.SessionOptions()){options.setIntraOpNumThreads(Math.max(1,Math.min(4,Runtime.getRuntime().availableProcessors())));options.setInterOpNumThreads(1);options.setExecutionMode(OrtSession.SessionOptions.ExecutionMode.SEQUENTIAL);options.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT);options.setCPUArenaAllocator(false);options.setMemoryPatternOptimization(false);options.addConfigEntry("session.intra_op.allow_spinning","0");session=environment.createSession(model.getAbsolutePath(),options);}
    }

    private String digest(File file)throws Exception{MessageDigest hash=MessageDigest.getInstance("SHA-256");try(InputStream in=new FileInputStream(file)){byte[] block=new byte[262144];int n;while((n=in.read(block))!=-1){if(closed||cancelled)throw new InterruptedIOException("Native balanced analysis was cancelled.");hash.update(block,0,n);}}return hex(hash.digest());}
    private byte[] readAsset(String name,int max)throws IOException{try(InputStream in=context.getAssets().open(ASSET_ROOT+name)){ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] block=new byte[8192];int n;while((n=in.read(block))!=-1){if(out.size()+n>max)throw new IOException("The balanced MDX manifest is too large.");out.write(block,0,n);}return out.toByteArray();}}
    private void closeSession(){OrtSession current=session;session=null;if(current!=null)try{current.close();}catch(Exception ignored){}}
    private void clearBuffers(){inputBuffer=null;outputBuffer=null;}
    private synchronized void releaseFiles(){if(inputStream!=null)try{inputStream.close();}catch(IOException ignored){}inputStream=null;if(input!=null)input.delete();if(output!=null)output.delete();input=null;output=null;received=0;}
    private void cleanupStaleFiles(){File[] stale=jobDirectory.listFiles((dir,name)->name.endsWith(".input")||name.endsWith(".bin")||name.endsWith(".partial"));if(stale!=null)for(File file:stale)file.delete();}
    private void terminateRun(){synchronized(lifecycle){OrtSession.RunOptions run=activeRun;if(run!=null)try{run.setTerminate(true);}catch(Exception ignored){}}}
    @Override public synchronized void close(){
        if(closed)return;closed=true;cancelled=true;terminateRun();
        // Keep queued inference alive long enough to observe closed and retire
        // its resources. shutdownNow can discard that sole cleanup owner.
        if(!workerActive)executor.execute(()->{synchronized(this){closeSession();releaseFiles();clearBuffers();jobDirectory.delete();}});
        executor.shutdown();
    }
    private static String hex(byte[] bytes){StringBuilder out=new StringBuilder(bytes.length*2);for(byte b:bytes)out.append(Character.forDigit((b>>>4)&15,16)).append(Character.forDigit(b&15,16));return out.toString();}
}
