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
    private final ExecutorService executor=Executors.newSingleThreadExecutor();
    private volatile NativeDeux engine;
    private volatile boolean closed,cancelled;
    private String token,state="idle",message="";
    private double progress;
    private long startedAt,lastDiagnosticAt;
    private File output;

    NativePassageTask(Context context,File audio,String jobId)throws IOException {
        this.context=context.getApplicationContext();this.audio=audio;
        if(!jobId.matches("[a-f0-9-]{36}"))throw new IOException("Invalid native job.");
        directory=new File(context.getCacheDir(),"native-passages/"+jobId);
        if(!directory.mkdirs()&&!directory.isDirectory())throw new IOException("Native analysis storage is unavailable.");
    }
    synchronized String start(long startSample)throws Exception {
        if(closed)throw new IOException("Native analysis has stopped.");
        if("running".equals(state))throw new IOException("A native passage is already running.");
        if(startSample < -66150L||startSample>44100L*14400)throw new IOException("Invalid native passage position.");
        if(output!=null&&output.exists()&&!output.delete())throw new IOException("Previous native passage could not be released.");
        token=UUID.randomUUID().toString();state="running";progress=0;message="Preparing native Studio analysis";cancelled=false;
        startedAt=android.os.SystemClock.elapsedRealtime();lastDiagnosticAt=startedAt;
        AppDiagnostics.log(context,"INFO","native-passage","started; passage="+token.substring(0,8)+"; startSample="+startSample+"; cacheFreeBytes="+directory.getUsableSpace());
        AppDiagnostics.sample(context,"native-start-memory");
        final String current=token;output=new File(directory,current+".bin");final File result=output;
        executor.execute(()->{
            try {
                if(closed||cancelled)throw new IOException("Native analysis cancelled.");
                NativeDeux model=engine;
                if(model==null){model=new NativeDeux(context);engine=model;}
                model.predict(audio,startSample,result,(value,detail)->update(current,value,detail),()->closed||cancelled||Thread.currentThread().isInterrupted());
                synchronized(this){
                    if(closed||cancelled)throw new IOException("Native analysis cancelled.");
                    if(result.length()!=OUTPUT_BYTES)throw new IOException("Native separation returned incomplete audio.");
                    state="completed";progress=1;message="Native passage complete";
                    AppDiagnostics.log(context,"INFO","native-passage","completed; passage="+current.substring(0,8)+"; elapsedMs="+(android.os.SystemClock.elapsedRealtime()-startedAt));
                    AppDiagnostics.sample(context,"native-complete-memory");
                }
            }catch(Throwable error){
                AppDiagnostics.record(context,"native-passage",error);
                synchronized(this){state=closed||cancelled?"cancelled":"failed";message=AnalysisJobStore.limited(error.getMessage()==null?"Native Studio analysis could not finish.":error.getMessage(),500);}
                result.delete();
            }finally{
                if(closed){NativeDeux model=engine;engine=null;if(model!=null)try{model.close();}catch(Exception ignored){}result.delete();directory.delete();}
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
        NativeDeux model=engine;engine=null;if(model!=null)model.close();
        if(output!=null)output.delete();output=null;token=null;state="idle";
    }
    @Override public synchronized void close(){
        if(closed)return;closed=true;cancelled=true;
        NativeDeux model=engine;if(model!=null)model.close();
        executor.shutdownNow();
        if(!"running".equals(state)){
            engine=null;if(model!=null)try{model.close();}catch(Exception ignored){}
            if(output!=null)output.delete();directory.delete();
        }
    }
}
