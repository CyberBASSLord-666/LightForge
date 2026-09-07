package com.cyberbasslord.lightforge;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.net.Uri;
import android.os.*;
import android.webkit.*;
import org.json.JSONObject;
import java.io.*;

/** Owns the analysis WebView independently of any Activity or screen surface. */
public final class AnalysisService extends Service {
    static final String ACTION_START="com.cyberbasslord.lightforge.ANALYZE";
    static final String ACTION_CANCEL="com.cyberbasslord.lightforge.CANCEL_ANALYSIS";
    static final String CHANNEL="analysis", UPDATE="com.cyberbasslord.lightforge.ANALYSIS_UPDATE";
    private static final int NOTIFICATION=2200;
    private static final long MAX_RUNTIME=6*60*60*1000L;
    private static volatile AnalysisService instance;
    private final Handler main=new Handler(Looper.getMainLooper());
    private WebView engine;
    private PowerManager.WakeLock wakeLock;
    private volatile String jobId;
    private volatile boolean stopped;
    private long lastProgress;
    private volatile NativePassageTask nativePassage;

    static boolean alive(){return instance!=null&&!instance.stopped;}
    static void recoverIfStopped(Context context) throws Exception {
        if(!alive())AnalysisJobStore.recover(context.getFilesDir());
    }
    @Override public void onCreate(){super.onCreate();instance=this;createChannel();}
    @Override public IBinder onBind(Intent intent){return null;}
    @Override public int onStartCommand(Intent intent,int flags,int startId) {
        if(intent==null){stopSelf();return START_NOT_STICKY;}
        String id=intent.getStringExtra("jobId");
        if(ACTION_CANCEL.equals(intent.getAction())){if(jobId==null)jobId=id;cancel(id);return START_NOT_STICKY;}
        if(!ACTION_START.equals(intent.getAction())){stopSelf();return START_NOT_STICKY;}
        // A retry can arrive between stopSelf and onDestroy. Android may reuse
        // this service instance for the newer start command.
        if(stopped){stopped=false;jobId=null;lastProgress=0;instance=this;}
        if(jobId!=null){if(!jobId.equals(id))signal();return START_NOT_STICKY;}
        jobId=id;
        try {
            JSONObject job=AnalysisJobStore.matching(getFilesDir(),jobId,true);
            Notification notification=notification(job,false);
            if(Build.VERSION.SDK_INT>=35)startForeground(NOTIFICATION,notification,ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROCESSING);
            else if(Build.VERSION.SDK_INT>=29)startForeground(NOTIFICATION,notification,ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
            else startForeground(NOTIFICATION,notification);
            PowerManager power=(PowerManager)getSystemService(POWER_SERVICE);
            wakeLock=power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"LightForge:Analysis");wakeLock.setReferenceCounted(false);wakeLock.acquire(MAX_RUNTIME+10000);
            main.postDelayed(()->finish("interrupted","Android's background processing window ended. Resume from saved passages when you are ready."),MAX_RUNTIME);
            startEngine(job);
        }catch(Exception error){finish("failed",message(error));}
        return START_NOT_STICKY;
    }
    private void startEngine(JSONObject job) throws Exception {
        nativePassage=new NativePassageTask(this,new File(AnalysisJobStore.project(getFilesDir(),job.getString("projectId")),"audio.wav"),jobId);
        final NativePassageTask ownedPassage=nativePassage;
        final String ownedJobId=jobId;
        engine=new WebView(getApplicationContext());
        WebSettings settings=engine.getSettings();settings.setJavaScriptEnabled(true);settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);settings.setAllowContentAccess(false);settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSupportMultipleWindows(false);settings.setMediaPlaybackRequiresUserGesture(true);
        // Keep the out-of-process WASM renderer protected while the service runs,
        // including when no Activity is visible. No screen-on flag or fake media.
        engine.setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT,false);
        engine.addJavascriptInterface(new JobBridge(ownedJobId,ownedPassage),"BackgroundJob");
        AppResources resources=new AppResources(this,job.getString("projectId"));
        engine.setWebViewClient(new WebViewClient(){
            @Override public WebResourceResponse shouldInterceptRequest(WebView view,WebResourceRequest request){
                Uri uri=request.getUrl();
                String nativePath=uri.getPath();
                if("https".equals(uri.getScheme())&&"appassets.androidplatform.net".equals(uri.getHost())&&nativePath!=null&&nativePath.matches("/background/native/[a-f0-9-]{36}\\.bin")){
                    try{
                        if(stopped||!ownedJobId.equals(jobId))throw new IOException("Native analysis stopped.");
                        String token=nativePath.substring("/background/native/".length(),nativePath.length()-4);
                        File result=ownedPassage.result(token);
                        String range=null;for(java.util.Map.Entry<String,String> entry:request.getRequestHeaders().entrySet())if("Range".equalsIgnoreCase(entry.getKey()))range=entry.getValue();
                        WebViewFileTransport.Response data=WebViewFileTransport.open(result,range);
                        return AppResources.response(data.status,data.reason,"application/octet-stream",data.body,data.length,data.contentRange);
                    }catch(Exception error){return AppResources.response(404,"Not Found","text/plain",new ByteArrayInputStream(new byte[0]),0,null);}
                }
                if("https://appassets.androidplatform.net/background/request.json".equals(uri.toString())) {
                    try{return AppResources.response(200,"OK","application/json",new FileInputStream(new File(AnalysisJobStore.directory(getFilesDir()),"request.json")),-1,null);}
                    catch(Exception error){return AppResources.response(404,"Not Found","text/plain",new ByteArrayInputStream(new byte[0]),0,null);}
                }
                return resources.resource(uri,request.getRequestHeaders());
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request){return true;}
            @Override public boolean onRenderProcessGone(WebView view,RenderProcessGoneDetail detail){
                boolean current=view==engine;if(current)engine=null;view.destroy();if(current)finish("interrupted",detail.didCrash()
                    ?"The analysis engine stopped unexpectedly. Resume checks saved passages and continues from verified progress. Your saved show is intact."
                    :"Android reclaimed the analysis engine. Resume checks saved passages and continues from verified progress. Your saved show is intact.");return true;
            }
            @Override public void onReceivedError(WebView view,WebResourceRequest request,WebResourceError error){
                if(view==engine&&request.isForMainFrame())finish("failed","The background analysis engine could not load.");
            }
        });
        engine.loadUrl("https://appassets.androidplatform.net/background/runner.html?job="+Uri.encode(jobId));
        signal();
    }
    public final class JobBridge {
        private final String ownerJobId;
        private final NativePassageTask ownerTask;
        JobBridge(String ownerJobId,NativePassageTask ownerTask){this.ownerJobId=ownerJobId;this.ownerTask=ownerTask;}
        private boolean owns(String id){return !stopped&&ownerJobId.equals(id)&&ownerJobId.equals(jobId);}
        @JavascriptInterface public String nativeDeuxStart(String id,long startSample){
            try{if(!owns(id))throw new IOException("Native analysis job is no longer active.");return ownerTask.start(startSample);}
            catch(Exception error){return bridgeError(error);}
        }
        @JavascriptInterface public String nativeDeuxStatus(String id,String token){
            try{if(!owns(id))throw new IOException("Native analysis job is no longer active.");return ownerTask.status(token);}
            catch(Exception error){return bridgeError(error);}
        }
        @JavascriptInterface public void nativeDeuxCancel(String id,String token){if(owns(id))ownerTask.cancel(token);}
        @JavascriptInterface public String nativeDeuxRelease(String id){
            try{if(!owns(id))throw new IOException("Native analysis job is no longer active.");ownerTask.releaseIdle();return "{}";}
            catch(Exception error){return bridgeError(error);}
        }
        @JavascriptInterface public void progress(String id,double value,String stage){
            progressInfo(id,value,stage,"{}");
        }
        @JavascriptInterface public void progressInfo(String id,double value,String stage,String details){
            if(stopped||!jobId.equals(id))return;
            try{
                if(details==null||details.length()>4096)return;
                JSONObject info=new JSONObject(details);
                long now=SystemClock.elapsedRealtime();if(now-lastProgress<1000&&value<.96&&!info.optBoolean("checkpointSaved"))return;lastProgress=now;
                JSONObject job=AnalysisJobStore.progress(getFilesDir(),id,value,stage,info);main.post(()->{if(!stopped&&id.equals(jobId)){notifyJob(job,false);signal();}});
            }
            catch(Exception ignored){} // A cancelled job can still have an in-flight progress message.
        }
        @JavascriptInterface public boolean checkpoint(String id,String contents){
            if(stopped||!jobId.equals(id))return false;
            try{AnalysisJobStore.checkpoint(getFilesDir(),id,contents);return true;}catch(Exception error){main.post(()->{if(!stopped&&id.equals(jobId))finish("failed",message(error));});return false;}
        }
        @JavascriptInterface public boolean complete(String id,String contents){
            if(stopped||!jobId.equals(id))return false;
            try{JSONObject job=AnalysisJobStore.complete(getFilesDir(),id,contents);main.post(()->{if(!stopped&&id.equals(jobId))shutdown(job,true);});return true;}
            catch(Exception error){main.post(()->{if(!stopped&&id.equals(jobId))finish("failed",message(error));});return false;}
        }
        @JavascriptInterface public void failed(String id,String detail,boolean cancelled){
            if(stopped||!jobId.equals(id))return;
            main.post(()->{if(!stopped&&id.equals(jobId))finish(cancelled?"cancelled":"failed",cancelled?"Analysis cancelled. Your saved show is intact.":detail);});
        }
    }
    private void cancel(String id){
        if(stopped||id==null||!id.equals(jobId))return;
        try{
            JSONObject job=AnalysisJobStore.finish(getFilesDir(),id,"cancelling","Cancelling analysis…");
            if(!AnalysisJobStore.active(job)){shutdown(job,false);return;}
            notifyJob(job,false);signal();
            if(engine!=null)engine.evaluateJavascript("window.BackgroundAnalysis && window.BackgroundAnalysis.cancel()",null);
            else {finish("cancelled","Analysis cancelled. Your saved show is intact.");return;}
            main.postDelayed(()->finish("cancelled","Analysis cancelled. Your saved show is intact."),3000);
        }catch(Exception error){finish("failed",message(error));}
    }
    @Override public void onTimeout(int startId,int fgsType){finish("interrupted","Android paused background media processing after its time allowance. Open LightForge and resume from saved passages.");}
    private void finish(String state,String detail){
        if(stopped)return;
        try{
            JSONObject current=AnalysisJobStore.status(getFilesDir());
            if(current!=null&&"cancelling".equals(current.optString("state"))){state="cancelled";detail="Analysis cancelled. Your saved show is intact.";}
            shutdown(AnalysisJobStore.finish(getFilesDir(),jobId,state,detail),!state.equals("cancelled"));
        }
        catch(Exception error){shutdown(null,false);}
    }
    private void shutdown(JSONObject job,boolean notify){
        if(stopped)return;stopped=true;main.removeCallbacksAndMessages(null);
        if(nativePassage!=null){nativePassage.close();nativePassage=null;}
        if(engine!=null){engine.removeJavascriptInterface("BackgroundJob");engine.destroy();engine=null;}
        if(wakeLock!=null&&wakeLock.isHeld())wakeLock.release();wakeLock=null;
        stopForeground(STOP_FOREGROUND_REMOVE);signal();
        if(notify&&job!=null)notifyJob(job,true);
        stopSelf();
    }
    @Override public void onDestroy(){
        if(!stopped)finish("interrupted","Android stopped analysis. Your saved show is intact. Reopen LightForge to resume from saved passages.");
        if(instance==this)instance=null;super.onDestroy();
    }
    // Swiping the Activity out of Recents deliberately leaves this user-started service running.
    @Override public void onTaskRemoved(Intent rootIntent){super.onTaskRemoved(rootIntent);}
    private void signal(){sendBroadcast(new Intent(UPDATE).setPackage(getPackageName()));}
    private void createChannel(){
        NotificationChannel channel=new NotificationChannel(CHANNEL,"Show creation",NotificationManager.IMPORTANCE_LOW);
        channel.setDescription("Background audio analysis, choreography and completion");channel.setShowBadge(false);
        ((NotificationManager)getSystemService(NOTIFICATION_SERVICE)).createNotificationChannel(channel);
    }
    private Notification notification(JSONObject job,boolean terminal){
        Intent open=new Intent(this,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent content=PendingIntent.getActivity(this,0,open,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        String stage=job.optString("stage","Creating your show");
        Notification.Builder builder=new Notification.Builder(this,CHANNEL).setSmallIcon(R.drawable.ic_analysis)
            .setContentTitle(terminal?stage:"Creating · "+job.optString("name","My show")).setContentText(terminal?job.optString("name"):stage)
            .setStyle(new Notification.BigTextStyle().bigText(stage)).setContentIntent(content).setOnlyAlertOnce(true)
            .setOngoing(!terminal).setAutoCancel(terminal).setCategory(Notification.CATEGORY_PROGRESS)
            .setVisibility(Notification.VISIBILITY_PRIVATE);
        if(!terminal){
            // Android updates the chronometer without waking the analysis renderer.
            builder.setWhen(job.optLong("createdAt",System.currentTimeMillis())).setShowWhen(true).setUsesChronometer(true);
            builder.setProgress(1000,(int)(job.optDouble("progress")*1000),job.optDouble("progress")<=0);
            Intent cancel=new Intent(this,AnalysisService.class).setAction(ACTION_CANCEL).putExtra("jobId",job.optString("id"));
            PendingIntent action=PendingIntent.getService(this,1,cancel,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
            builder.addAction(new Notification.Action.Builder(null,"Cancel",action).build());
            if(Build.VERSION.SDK_INT>=31)builder.setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE);
        }
        return builder.build();
    }
    private void notifyJob(JSONObject job,boolean terminal){
        try{((NotificationManager)getSystemService(NOTIFICATION_SERVICE)).notify(NOTIFICATION,notification(job,terminal));}catch(SecurityException ignored){}
    }
    private static String message(Throwable error){return AnalysisJobStore.limited(error.getMessage()==null?"Background analysis could not finish. Try again.":error.getMessage(),500);}
    private static String bridgeError(Throwable error){try{return new JSONObject().put("error",message(error)).toString();}catch(Exception ignored){return "{\"error\":\"Native analysis could not start.\"}";}}
}
