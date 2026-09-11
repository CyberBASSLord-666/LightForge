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
    private final java.util.Set<WebView> retiredWebViews=java.util.Collections.newSetFromMap(new java.util.WeakHashMap<WebView,Boolean>());
    private PowerManager.WakeLock wakeLock;
    private volatile String jobId;
    private volatile boolean stopped;
    private long lastProgress;
    private long lastDiagnosticProgress;
    private volatile NativePassageTask nativePassage;
    private volatile NativeMdxTask nativeMdx;

    static boolean alive(){return instance!=null&&!instance.stopped;}
    static void recoverIfStopped(Context context) throws Exception {
        if(!alive())AnalysisJobStore.recover(context.getFilesDir());
    }
    @Override public void onCreate(){super.onCreate();AppDiagnostics.initialize(this);AppDiagnostics.log(this,"INFO","analysis-service","created");instance=this;createChannel();}
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
        AppDiagnostics.log(this,"INFO","analysis-service","starting job="+jobId);
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
        }catch(Exception error){AppDiagnostics.record(this,"analysis-start",error);finish("failed",message(error));}
        return START_NOT_STICKY;
    }
    private void startEngine(JSONObject job) throws Exception {
        nativePassage=new NativePassageTask(this,new File(AnalysisJobStore.project(getFilesDir(),job.getString("projectId")),"audio.wav"),jobId);
        final NativePassageTask ownedPassage=nativePassage;
        NativeMdxTask mdx=null;
        // The status record intentionally contains only bounded notification
        // fields. Read the frozen request to select the accelerator; never
        // infer quality from a mutable UI object.
        JSONObject request=AnalysisJobStore.request(getFilesDir(),job.getString("id"));
        JSONObject requestSettings=request.optJSONObject("settings");
        boolean balanced=requestSettings!=null&&"balanced".equals(requestSettings.optString("analysisQuality"));
        if(balanced)try{mdx=new NativeMdxTask(this,jobId);}catch(Exception error){
            // Balanced analysis remains fully functional on devices where the
            // optional native MDX graph cannot be prepared; the worker falls
            // back to its quality-checked WebAssembly path. Precision Studio
            // never pays the setup cost for an accelerator it cannot use.
            AppDiagnostics.record(this,"native-mdx-compatibility",error);
        }
        nativeMdx=mdx;
        final NativeMdxTask ownedMdx=mdx;
        final String ownedJobId=jobId;
        engine=new WebView(getApplicationContext());
        WebSettings settings=engine.getSettings();settings.setJavaScriptEnabled(true);settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);settings.setAllowContentAccess(false);settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSupportMultipleWindows(false);settings.setMediaPlaybackRequiresUserGesture(true);
        // Keep the out-of-process WASM renderer protected while the service runs,
        // including when no Activity is visible. No screen-on flag or fake media.
        engine.setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT,false);
        engine.addJavascriptInterface(new JobBridge(ownedJobId,ownedPassage,ownedMdx),"BackgroundJob");
        engine.setWebChromeClient(new WebChromeClient(){
            @Override public boolean onConsoleMessage(ConsoleMessage message){
                if(message.messageLevel()==ConsoleMessage.MessageLevel.ERROR||message.messageLevel()==ConsoleMessage.MessageLevel.WARNING)
                    AppDiagnostics.log(AnalysisService.this,message.messageLevel()==ConsoleMessage.MessageLevel.ERROR?"ERROR":"WARN","analysis-console",message.message()+" at "+message.sourceId()+":"+message.lineNumber());
                return true;
            }
        });
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
                if("https".equals(uri.getScheme())&&"appassets.androidplatform.net".equals(uri.getHost())&&nativePath!=null&&nativePath.matches("/background/native-mdx/[a-f0-9-]{36}\\.bin")){
                    try{
                        if(ownedMdx==null||stopped||!ownedJobId.equals(jobId))throw new IOException("Native analysis stopped.");
                        String token=nativePath.substring("/background/native-mdx/".length(),nativePath.length()-4);
                        File result=ownedMdx.result(ownedJobId,token);
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
                AppDiagnostics.record(AnalysisService.this,"analysis-renderer",new IOException(detail.didCrash()?"Analysis renderer crashed.":"Android reclaimed the analysis renderer."));
                boolean current=view==engine;if(current)engine=null;releaseEngine(view);if(current&&!stopped)finish("interrupted",detail.didCrash()
                    ?"The analysis engine stopped unexpectedly. Resume checks saved passages and continues from verified progress. Your saved show is intact."
                    :"Android reclaimed the analysis engine. Resume checks saved passages and continues from verified progress. Your saved show is intact.");return true;
            }
            @Override public void onReceivedError(WebView view,WebResourceRequest request,WebResourceError error){
                AppDiagnostics.log(AnalysisService.this,"ERROR","analysis-resource","code="+error.getErrorCode()+"; mainFrame="+request.isForMainFrame()+"; "+error.getDescription());
                if(view==engine&&request.isForMainFrame())finish("failed","The background analysis engine could not load.");
            }
        });
        engine.loadUrl("https://appassets.androidplatform.net/background/runner.html?job="+Uri.encode(jobId));
        signal();
    }
    public final class JobBridge {
        private final String ownerJobId;
        private final NativePassageTask ownerTask;
        private final NativeMdxTask ownerMdx;
        JobBridge(String ownerJobId,NativePassageTask ownerTask,NativeMdxTask ownerMdx){this.ownerJobId=ownerJobId;this.ownerTask=ownerTask;this.ownerMdx=ownerMdx;}
        private boolean owns(String id){return !stopped&&ownerJobId.equals(id)&&ownerJobId.equals(jobId);}
        @JavascriptInterface public void logDiagnostic(String level,String source,String message){if(owns(ownerJobId))AppDiagnostics.log(AnalysisService.this,level,source,message);}
        @JavascriptInterface public String nativeDeuxAvailability(String id){
            try{if(!owns(id))throw new IOException("Native analysis job is no longer active.");return ownerTask.availability();}
            catch(Exception error){AppDiagnostics.record(AnalysisService.this,"native-compatibility",error);return bridgeError(error);}
        }
        @JavascriptInterface public String nativeDeuxStart(String id,long startSample){
            try{if(!owns(id))throw new IOException("Native analysis job is no longer active.");return ownerTask.start(startSample);}
            catch(Exception error){AppDiagnostics.record(AnalysisService.this,"native-start",error);return bridgeError(error);}
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
        @JavascriptInterface public String nativeMdxAvailability(String id){
            try{if(ownerMdx==null||!owns(id))throw new IOException("Native balanced analysis is unavailable.");return ownerMdx.availability(id);}
            catch(Exception error){AppDiagnostics.record(AnalysisService.this,"native-mdx-compatibility",error);return bridgeError(error);}
        }
        @JavascriptInterface public String nativeMdxBegin(String id,long bytes){
            try{if(ownerMdx==null||!owns(id))throw new IOException("Native balanced analysis is unavailable.");return ownerMdx.begin(id,bytes);}
            catch(Exception error){AppDiagnostics.record(AnalysisService.this,"native-mdx-begin",error);return bridgeError(error);}
        }
        @JavascriptInterface public String nativeMdxAppend(String id,String token,String chunk){
            try{if(ownerMdx==null||!owns(id))throw new IOException("Native balanced analysis is unavailable.");return ownerMdx.append(id,token,chunk);}
            catch(Exception error){AppDiagnostics.record(AnalysisService.this,"native-mdx-append",error);return bridgeError(error);}
        }
        @JavascriptInterface public String nativeMdxRun(String id,String token){
            try{if(ownerMdx==null||!owns(id))throw new IOException("Native balanced analysis is unavailable.");return ownerMdx.run(id,token);}
            catch(Exception error){AppDiagnostics.record(AnalysisService.this,"native-mdx-run",error);return bridgeError(error);}
        }
        @JavascriptInterface public String nativeMdxStatus(String id,String token){
            try{if(ownerMdx==null||!owns(id))throw new IOException("Native balanced analysis is unavailable.");return ownerMdx.status(id,token);}
            catch(Exception error){return bridgeError(error);}
        }
        @JavascriptInterface public void nativeMdxCancel(String id,String token){if(ownerMdx!=null&&owns(id))ownerMdx.cancel(id,token);}
        @JavascriptInterface public String nativeMdxRelease(String id){
            try{if(ownerMdx==null||!owns(id))throw new IOException("Native balanced analysis is unavailable.");return ownerMdx.releaseIdle(id);}
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
                if(now-lastDiagnosticProgress>=15000||info.optBoolean("checkpointSaved")){
                    lastDiagnosticProgress=now;
                    AppDiagnostics.log(AnalysisService.this,"INFO","analysis-progress","job="+id+"; progress="+value+"; stage="+stage+"; checkpoint="+info.optBoolean("checkpointSaved")+"; passage="+info.optInt("passageIndex",-1)+"; completed="+info.optInt("passagesCompleted",-1));
                }
            }
            catch(Exception ignored){} // A cancelled job can still have an in-flight progress message.
        }
        @JavascriptInterface public boolean clearRunObservation(String id){
            if(stopped||!jobId.equals(id))return false;
            try{AnalysisJobStore.clearRunObservation(getFilesDir(),id);return true;}
            catch(Exception error){AppDiagnostics.record(AnalysisService.this,"analysis-observation-clear",error);main.post(()->{if(!stopped&&id.equals(jobId))finish("failed",message(error));});return false;}
        }
        @JavascriptInterface public boolean checkpoint(String id,String contents){
            if(stopped||!jobId.equals(id))return false;
            try{AnalysisJobStore.checkpoint(getFilesDir(),id,contents);AppDiagnostics.log(AnalysisService.this,"INFO","analysis-checkpoint","saved; job="+id);return true;}catch(Exception error){AppDiagnostics.record(AnalysisService.this,"analysis-checkpoint",error);main.post(()->{if(!stopped&&id.equals(jobId))finish("failed",message(error));});return false;}
        }
        @JavascriptInterface public boolean complete(String id,String contents){
            if(stopped||!jobId.equals(id))return false;
            try{JSONObject job=AnalysisJobStore.complete(getFilesDir(),id,contents);main.post(()->{if(!stopped&&id.equals(jobId))shutdown(job,true);});return true;}
            catch(Exception error){AppDiagnostics.record(AnalysisService.this,"analysis-complete",error);main.post(()->{if(!stopped&&id.equals(jobId))finish("failed",message(error));});return false;}
        }
        @JavascriptInterface public void failed(String id,String detail,boolean cancelled){
            if(stopped||!jobId.equals(id))return;
            main.post(()->{if(!stopped&&id.equals(jobId))finish(cancelled?"cancelled":"failed",cancelled?"Analysis cancelled. Your saved show is intact.":detail);});
        }
    }
    private void cancel(String id){
        if(stopped||id==null||!id.equals(jobId))return;
        AppDiagnostics.log(this,"INFO","analysis-cancel","requested; job="+id);
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
        AppDiagnostics.log(this,"failed".equals(state)?"ERROR":"WARN","analysis-finish","job="+jobId+"; state="+state+"; "+detail);
        try{
            JSONObject current=AnalysisJobStore.status(getFilesDir());
            if(current!=null&&"cancelling".equals(current.optString("state"))){state="cancelled";detail="Analysis cancelled. Your saved show is intact.";}
            shutdown(AnalysisJobStore.finish(getFilesDir(),jobId,state,detail),!state.equals("cancelled"));
        }
        catch(Exception error){AppDiagnostics.record(this,"analysis-finish",error);shutdown(null,false);}
    }
    private void shutdown(JSONObject job,boolean notify){
        if(stopped)return;stopped=true;main.removeCallbacksAndMessages(null);
        AppDiagnostics.log(this,"INFO","analysis-shutdown","job="+jobId+"; state="+(job==null?"unknown":job.optString("state")));
        NativePassageTask previousTask=nativePassage;nativePassage=null;
        try{if(previousTask!=null)previousTask.close();}catch(RuntimeException error){AppDiagnostics.record(this,"native-shutdown",error);}
        NativeMdxTask previousMdx=nativeMdx;nativeMdx=null;
        try{if(previousMdx!=null)previousMdx.close();}catch(RuntimeException error){AppDiagnostics.record(this,"native-mdx-shutdown",error);}
        WebView previous=engine;engine=null;releaseEngine(previous);
        try{if(wakeLock!=null&&wakeLock.isHeld())wakeLock.release();}catch(RuntimeException error){AppDiagnostics.record(this,"wake-lock-release",error);}finally{wakeLock=null;}
        stopForeground(STOP_FOREGROUND_REMOVE);signal();
        if(notify&&job!=null)notifyJob(job,true);
        stopSelf();
    }
    private void releaseEngine(WebView previous){
        if(previous==null||!retiredWebViews.add(previous))return;
        try{android.view.ViewParent parent=previous.getParent();if(parent instanceof android.view.ViewGroup)((android.view.ViewGroup)parent).removeView(previous);}
        catch(RuntimeException error){AppDiagnostics.record(this,"analysis-detach",error);}
        try{previous.removeJavascriptInterface("BackgroundJob");}catch(RuntimeException error){AppDiagnostics.record(this,"analysis-bridge-cleanup",error);}
        try{previous.destroy();}catch(RuntimeException error){AppDiagnostics.record(this,"analysis-destroy",error);}
    }
    @Override public void onDestroy(){
        AppDiagnostics.log(this,"INFO","analysis-service","destroyed; stopped="+stopped);
        if(!stopped)finish("interrupted","Android stopped analysis. Your saved show is intact. Reopen LightForge to resume from saved passages.");
        if(instance==this)instance=null;super.onDestroy();
    }
    // Swiping the Activity out of Recents deliberately leaves this user-started service running.
    @Override public void onTaskRemoved(Intent rootIntent){AppDiagnostics.log(this,"INFO","analysis-service","task removed; continuing="+!stopped);super.onTaskRemoved(rootIntent);}
    @Override public void onTrimMemory(int level){super.onTrimMemory(level);AppDiagnostics.log(this,"WARN","analysis-memory","trimMemory level="+level);}
    @Override public void onLowMemory(){super.onLowMemory();AppDiagnostics.log(this,"WARN","analysis-memory","lowMemory");}
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
