package com.cyberbasslord.lightforge;

import android.content.Context;
import org.json.JSONObject;
import java.io.File;
import java.io.IOException;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** One native passage at a time. Only its owning service may expose its result. */
final class NativePassageTask implements AutoCloseable {
    private static final long OUTPUT_BYTES=573300L*2*4;
    private final Context context;
    private final File audio,directory;
    private final NativeRuntimeGuard runtimeGuard;
    private final ExecutorService executor=Executors.newSingleThreadExecutor();
    private volatile NativeDeux engine;
    private volatile boolean closed,cancelled;
    private String token,state="idle",message="";
    private double progress;
    private long startedAt,lastDiagnosticAt;
    private File output;
    // A completed profile is retained until releaseIdle so one passage yields one compact receipt.
    private NativeInferenceProfile inferenceProfile;
    private boolean profileEmitted;

    NativePassageTask(Context context,File audio,String jobId)throws IOException {
        this.context=context.getApplicationContext();this.audio=audio;
        try{runtimeGuard=new NativeRuntimeGuard(new File(context.getFilesDir(),"diagnostics"),context.getPackageManager().getPackageInfo(context.getPackageName(),0).versionCode+"-"+NativeDeux.RUNTIME_VERSION);}
        catch(android.content.pm.PackageManager.NameNotFoundException error){throw new IOException("The native runtime identity could not be checked.",error);}
        if(!jobId.matches("[a-f0-9-]{36}"))throw new IOException("Invalid native job.");
        directory=new File(context.getCacheDir(),"native-passages/"+jobId);
        if(!directory.mkdirs()&&!directory.isDirectory())throw new IOException("Native analysis storage is unavailable.");
    }
    /** Called by the JavaScript bridge thread, before any native runtime is loaded. */
    synchronized String availability()throws Exception {
        if(closed)throw new IOException("Native analysis has stopped.");
        java.util.List<NativeRuntimeGuard.Exit> exits=new java.util.ArrayList<>();
        NativeRuntimeGuard.State prior=runtimeGuard.state();
        if(android.os.Build.VERSION.SDK_INT>=30&&prior!=null&&!prior.disabled){
            android.app.ActivityManager manager=(android.app.ActivityManager)context.getSystemService(Context.ACTIVITY_SERVICE);
            if(manager==null)throw new IOException("Android native compatibility checks are unavailable.");
            for(android.app.ApplicationExitInfo exit:manager.getHistoricalProcessExitReasons(context.getPackageName(),prior.pid,32))
                exits.add(new NativeRuntimeGuard.Exit(exit.getPid(),exit.getReason(),exit.getStatus(),exit.getTimestamp(),context.getPackageName().equals(exit.getProcessName())));
        }
        boolean available=runtimeGuard.reconcile(exits,System.currentTimeMillis());
        JSONObject result=new JSONObject().put("available",available).put("runtime",NativeDeux.RUNTIME_VERSION);
        if(!available)result.put("reason","previous-native-crash").put("message","Compatibility processing enabled after a native crash. The same Studio models are used; analysis may take longer.");
        return result.toString();
    }
    synchronized String start(long startSample)throws Exception {
        if(closed)throw new IOException("Native analysis has stopped.");
        if("running".equals(state))throw new IOException("A native passage is already running.");
        // cancel() permanently terminates a NativeDeux instance.  A failed or
        // cancelled passage must therefore never donate that instance to a retry.
        if(cancelled||!"completed".equals(state))retireEngine(null);
        if(!new JSONObject(availability()).getBoolean("available"))throw new IOException("Resume in compatibility mode after the previous native crash.");
        if(startSample < -66150L||startSample>44100L*14400)throw new IOException("Invalid native passage position.");
        if(output!=null&&output.exists()&&!output.delete())throw new IOException("Previous native passage could not be released.");
        emitProfile(inferenceProfile,"released");
        final NativeInferenceProfile profile=new NativeInferenceProfile();profile.captureStartMemory();
        inferenceProfile=profile;profileEmitted=false;
        token=UUID.randomUUID().toString();state="running";progress=0;message="Preparing native Studio analysis";cancelled=false;
        startedAt=android.os.SystemClock.elapsedRealtime();lastDiagnosticAt=startedAt;
        AppDiagnostics.log(context,"INFO","native-passage","started; passage="+token.substring(0,8)+"; startSample="+startSample+"; cacheFreeBytes="+directory.getUsableSpace());
        AppDiagnostics.sample(context,"native-start-memory");
        final String current=token;output=new File(directory,current+".bin");final File result=output;
        executor.execute(()->{
            NativeDeux model=null;
            try {
                if(closed||cancelled)throw new IOException("Native analysis cancelled.");
                model=engine;
                if(model==null){
                    NativeInferenceProfile.Timing engineStarted=NativeInferenceProfile.started();
                    try{model=new NativeDeux(context);engine=model;}finally{profile.addEngineInit(NativeInferenceProfile.elapsed(engineStarted));}
                }
                final String[] lease={null};
                model.predict(audio,startSample,result,(value,detail)->update(current,value,detail),()->closed||cancelled||Thread.currentThread().isInterrupted(),new NativeDeux.ExecutionScope(){
                    @Override public void begin()throws Exception {
                        if(closed||cancelled)throw new IOException("Native analysis cancelled.");
                        lease[0]=runtimeGuard.begin(android.os.Process.myPid(),System.currentTimeMillis());
                    }
                    @Override public void end(){try{runtimeGuard.end(lease[0]);}catch(IOException error){AppDiagnostics.record(context,"native-marker",error);}}
                },profile);
                synchronized(this){
                    if(closed||cancelled)throw new IOException("Native analysis cancelled.");
                    if(result.length()!=OUTPUT_BYTES)throw new IOException("Native separation returned incomplete audio.");
                    state="completed";progress=1;message="Native passage complete";
                    profile.finish("completed");
                    AppDiagnostics.log(context,"INFO","native-passage","completed; passage="+current.substring(0,8)+"; elapsedMs="+(android.os.SystemClock.elapsedRealtime()-startedAt));
                    AppDiagnostics.sample(context,"native-complete-memory");
                }
                // A completed passage must leave a receipt even if its consumer never calls
                // releaseIdle (for example after a process interruption between result and release).
                emitProfile(profile,"completed");
            }catch(Throwable error){
                // This covers native cancellation, failed direct-buffer setup and
                // failed inference.  Keeping the instance would reuse its permanent
                // cancelled flag or a partially initialized direct-buffer set.
                retireEngine(model);
                AppDiagnostics.record(context,"native-passage",error);
                String outcome;
                synchronized(this){outcome=closed||cancelled?"cancelled":"failed";state=outcome;message=AnalysisJobStore.limited(error.getMessage()==null?"Native Studio analysis could not finish.":error.getMessage(),500);}
                emitProfile(profile,outcome);
                result.delete();
            }finally{
                if(closed){emitProfile(profile,"cancelled");retireEngine(model);result.delete();directory.delete();}
            }
        });
        return status(current);
    }
    private synchronized void update(String current,double value,String detail){
        if(closed||cancelled||!current.equals(token))return;
        progress=Math.max(progress,Math.max(0,Math.min(1,Double.isFinite(value)?value:0)));
        message=AnalysisJobStore.limited(detail,200);
        long now=android.os.SystemClock.elapsedRealtime();
        if(now-lastDiagnosticAt>=15000){lastDiagnosticAt=now;AppDiagnostics.log(context,"INFO","native-progress","passage="+current.substring(0,8)+"; progress="+progress+"; elapsedMs="+(now-startedAt)+"; "+message);}
    }
    synchronized String status(String current)throws Exception {
        if(current==null||!current.equals(token))throw new IOException("This native passage is no longer active.");
        JSONObject value=new JSONObject().put("token",token).put("state",state).put("progress",progress).put("message",message);
        if("completed".equals(state))value.put("url","https://appassets.androidplatform.net/background/native/"+token+".bin");
        return value.toString();
    }
    synchronized File result(String current)throws IOException {
        if(closed||!"completed".equals(state)||!current.equals(token)||output==null||output.length()!=OUTPUT_BYTES)throw new IOException("Native passage is unavailable.");
        return output;
    }
    synchronized void cancel(String current){
        if(current==null||!current.equals(token))return;cancelled=true;
        NativeDeux model=engine;if(model!=null)model.cancel();
    }
    synchronized void releaseIdle()throws Exception {
        if("running".equals(state))throw new IOException("The native passage is still running.");
        emitProfile(inferenceProfile,"released");inferenceProfile=null;
        NativeDeux model=engine;engine=null;if(model!=null)model.close();
        if(output!=null)output.delete();output=null;token=null;state="idle";
    }
    /** Detach the exact worker engine before closing it, so a later start can only allocate fresh state. */
    private void retireEngine(NativeDeux expected){
        NativeDeux model=null;
        synchronized(this){
            if(expected==null){model=engine;engine=null;}
            else if(engine==expected){model=expected;engine=null;}
        }
        if(model!=null)try{model.close();}catch(Exception ignored){}
    }
    private void emitProfile(NativeInferenceProfile profile,String outcome){
        if(profile==null)return;
        NativeInferenceProfile.Snapshot snapshot=profile.finish(outcome);
        synchronized(this){if(profile!=inferenceProfile||profileEmitted)return;profileEmitted=true;}
        AppDiagnostics.profile(context,snapshot);
    }
    @Override public synchronized void close(){
        if(closed)return;closed=true;cancelled=true;
        emitProfile(inferenceProfile,"cancelled");
        NativeDeux model=engine;if(model!=null)model.close();
        executor.shutdownNow();
        if(!"running".equals(state)){
            engine=null;if(model!=null)try{model.close();}catch(Exception ignored){}
            if(output!=null)output.delete();directory.delete();
        }
    }
    /** True only after queued/running work and its finally cleanup have ended. */
    boolean isRetired(){return closed&&executor.isTerminated();}
}
