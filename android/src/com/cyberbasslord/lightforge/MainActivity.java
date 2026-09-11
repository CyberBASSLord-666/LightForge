package com.cyberbasslord.lightforge;

import android.app.*;
import android.content.*;
import android.database.Cursor;
import android.graphics.Color;
import android.net.Uri;
import android.os.*;
import android.provider.OpenableColumns;
import android.util.Base64;
import android.view.*;
import android.webkit.*;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.zip.*;

public final class MainActivity extends Activity {
    private static final String ORIGIN="https://appassets.androidplatform.net";
    private static final int PICK_AUDIO=101,SAVE_ZIP=102,PICK_BACKUP=103,SAVE_DIAGNOSTICS=104;
    // This is only the Android renderer-gone callback budget after the lease
    // supervisor has already declared a stalled completed restore and spent
    // its one replacement. It is not a JavaScript/generation timeout.
    private static final long COMPLETED_RESTORE_TERMINATE_CALLBACK_BUDGET_MS=2500L;
    // JavaScript interfaces must never shuttle an entire saved project in one
    // renderer IPC message. Completed-project recovery reads a bounded,
    // durable snapshot through this small chunk transport instead.
    private static final int COMPLETED_RESTORE_PROJECT_CHUNK_MAX_BYTES=64*1024;
    private static final ExecutorService diagnosticWorker=Executors.newSingleThreadExecutor();
    private static final AtomicBoolean diagnosticExporting=new AtomicBoolean();
    private String diagnosticName;
    private volatile WebView web;
    private volatile long previewGeneration;
    private FrameLayout previewRoot;
    private volatile boolean foreground;
    private final Set<WebView> retiredWebViews=Collections.newSetFromMap(new WeakHashMap<WebView,Boolean>());
    private boolean previewRecoveryPending;
    private AlertDialog previewRecoveryDialog;
    private final Handler completedRestoreHandler=new Handler(Looper.getMainLooper());
    private CompletedRestoreMonitor completedRestoreMonitor;
    // Diagnostics only: this never enables a fault path and is reset with the
    // Activity.  The durable per-job cap below is the recovery authority.
    private int completedRestoreRecoveryCount;
    private String completedRestoreLastRecovery;
    private String completedRestoreReplacementPath;
    // Diagnostics/test evidence only: records the WebView generation whose
    // bridge actually opened the current completed-restore lease.
    private volatile long completedRestoreLastAcceptedBeginGeneration=-1L;
    private volatile String completedRestoreLastAcceptedBeginJobId;
    private volatile WebView completedRestoreTerminatingWebView;
    private Runnable completedRestoreTerminateFallback;
    // Native visual proof for the narrow completed-restore terminal path.
    // These are identity-bound to the lease and stale WebView callbacks are
    // ignored after replacement.
    private String completedRestoreVisualJobId;
    private String completedRestoreVisualNonce;
    private WebView completedRestoreVisualWebView;
    private boolean completedRestoreVisualRequested;
    private boolean completedRestoreVisualCommitted;
    private ViewTreeObserver.OnDrawListener completedRestoreVisualDrawListener;
    // One active lease owns one open descriptor for project.json. ProjectStore
    // publishes edits by atomic replacement, so this descriptor is an
    // immutable completed-result snapshot even if a later write replaces the
    // path. It is deliberately never a whole-project IPC payload.
    private RandomAccessFile completedRestorePayloadFile;
    private String completedRestorePayloadJobId,completedRestorePayloadNonce,completedRestorePayloadProjectId,completedRestorePayloadSnapshot;
    private long completedRestorePayloadLength=-1L;
    // Timestamped diagnostics make the strict visual → terminal → post-ACK
    // ordering inspectable in the real instrumentation path.
    private volatile long completedRestoreLastVisualFrameAt;
    private volatile long completedRestoreLastTerminalAt;
    private volatile long completedRestoreLastAckConfirmationAt;
    // JS bridge methods may arrive on WebView's bridge thread while recovery
    // runs on the UI thread.  Serialize native status validation, monitor
    // transitions, and the persistent recovery-cap update.
    private final Object completedRestoreBridgeLock=new Object();
    private boolean analysisReceiverRegistered;
    private final BroadcastReceiver analysisReceiver=new BroadcastReceiver(){
        @Override public void onReceive(Context context,Intent intent){sendAnalysisStatus();}
    };
    private void sendAnalysisStatus(){
        try{JSONObject job=AnalysisJobStore.status(getFilesDir());event("analysisJob",job);}
        catch(Exception e){error(e);}
    }
    private JSONObject deviceCapabilities(){
        PowerManager power=(PowerManager)getSystemService(POWER_SERVICE);
        ActivityManager manager=(ActivityManager)getSystemService(ACTIVITY_SERVICE);
        ActivityManager.MemoryInfo memory=new ActivityManager.MemoryInfo();manager.getMemoryInfo(memory);
        return json("backgroundAnalysis",true,"androidSdk",Build.VERSION.SDK_INT,
            "notifications",((NotificationManager)getSystemService(NOTIFICATION_SERVICE)).areNotificationsEnabled(),
            "batteryRestricted",Build.VERSION.SDK_INT>=28&&manager.isBackgroundRestricted(),
            "batteryOptimized",!power.isIgnoringBatteryOptimizations(getPackageName()),
            "memoryBytes",memory.totalMem,"availableMemoryBytes",memory.availMem,
            "lowMemory",memory.lowMemory,"cpuCores",Runtime.getRuntime().availableProcessors());
    }
    @Override protected void onResume(){super.onResume();foreground=true;AppDiagnostics.log(this,"INFO","activity","resumed");if(web!=null)web.evaluateJavascript("window.resumePreview && window.resumePreview()",null);sendAnalysisStatus();event("deviceCapabilities",deviceCapabilities());showPreviewRecovery();}
    @Override public void onRequestPermissionsResult(int request,String[] permissions,int[] results){
        super.onRequestPermissionsResult(request,permissions,results);event("deviceCapabilities",deviceCapabilities());
    }

    private final ExecutorService worker=Executors.newSingleThreadExecutor();
    private Future<?> startupRecovery;
    private final AtomicBoolean cancelled=new AtomicBoolean();
    private volatile boolean importing;
    private volatile boolean exporting;
    private File projects, exports;
    private ExportSession activeExport;
    private volatile File pendingZip;
    private volatile String pendingName;
    private volatile Uri lastExportUri;
    private volatile boolean savePickerOpen;
    private final Object exportLock=new Object();

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        AppDiagnostics.initialize(this);
        AppDiagnostics.log(this,"INFO","activity","created; restored="+(state!=null));
        diagnosticName=state==null?null:state.getString("diagnosticName");
        projects=new File(getFilesDir(),"projects");exports=new File(getFilesDir(),"prepared-exports");
        projects.mkdirs();exports.mkdirs();
        startupRecovery=worker.submit(()-> {
            try{ProjectStore.recover(projects);AnalysisService.recoverIfStopped(this);}catch(Exception e){AppDiagnostics.record(this,"startup-recovery",e);runOnUiThread(()->Toast.makeText(this,"Project recovery: "+e.getMessage(),Toast.LENGTH_LONG).show());}
        });
        try {
            JSONObject prepared=PendingExportStore.recover(exports);
            if(prepared!=null){pendingZip=PendingExportStore.file(exports,prepared);pendingName=prepared.getString("name");}
        }catch(Exception e){Toast.makeText(this,"Export recovery: "+e.getMessage(),Toast.LENGTH_LONG).show();}
        cleanupAbandonedCache();
        savePickerOpen=state!=null&&state.getBoolean("savePickerOpen",false)&&pendingZip!=null;
        getWindow().setStatusBarColor(Color.rgb(8,13,24));getWindow().setNavigationBarColor(Color.rgb(8,13,24));
        IntentFilter updates=new IntentFilter(AnalysisService.UPDATE);
        if(Build.VERSION.SDK_INT>=33)registerReceiver(analysisReceiver,updates,Context.RECEIVER_NOT_EXPORTED);
        else registerReceiver(analysisReceiver,updates);
        analysisReceiverRegistered=true;
        FrameLayout root=new FrameLayout(this);root.setBackgroundColor(Color.rgb(8,13,24));previewRoot=root;setContentView(root);
        if(Build.VERSION.SDK_INT>=30) {
            getWindow().setDecorFitsSystemWindows(false);
            root.setOnApplyWindowInsetsListener((v,insets)-> {
                android.graphics.Insets bars=insets.getInsets(WindowInsets.Type.systemBars()|WindowInsets.Type.displayCutout()|WindowInsets.Type.ime());
                v.setPadding(bars.left,bars.top,bars.right,bars.bottom);return insets;
            });
        }
        completedRestoreMonitor=new CompletedRestoreMonitor(SystemClock::elapsedRealtime,new CompletedRestoreMonitor.Scheduler(){
            @Override public void postDelayed(Runnable task,long delayMs){completedRestoreHandler.postDelayed(task,delayMs);}
            @Override public void removeCallbacks(Runnable task){completedRestoreHandler.removeCallbacks(task);}
        },new CompletedRestoreMonitor.Host(){
            @Override public void requestProbe(String jobId,String nonce,CompletedRestoreMonitor.ProbeCallback callback){probeCompletedRestore(jobId,nonce,callback);}
            @Override public boolean recoveryAlreadyUsed(String jobId){return completedRestoreRecoveryUsed(jobId);}
            @Override public void recover(String jobId,String nonce,String reason){recoverCompletedRestore(jobId,nonce,reason);}
            @Override public void diagnostic(String message){AppDiagnostics.log(MainActivity.this,"INFO","completed-restore-watchdog",message);}
        });
        createPreview();
    }
    private void createPreview(){
        if(previewRoot==null||isFinishing()||Build.VERSION.SDK_INT>=17&&isDestroyed())return;
        final long createdGeneration=previewGeneration+1;
        final WebView created=new WebView(this);created.setBackgroundColor(Color.rgb(8,13,24));
        WebSettings s=created.getSettings();s.setJavaScriptEnabled(true);s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);s.setAllowContentAccess(false);s.setMediaPlaybackRequiresUserGesture(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);s.setSupportMultipleWindows(false);
        s.setBuiltInZoomControls(false);s.setTextZoom(100);s.setDatabaseEnabled(false);
        created.addJavascriptInterface(new Bridge(created,createdGeneration),"Android");
        created.setWebChromeClient(new WebChromeClient(){
            @Override public boolean onConsoleMessage(ConsoleMessage message){
                if(message.messageLevel()==ConsoleMessage.MessageLevel.ERROR||message.messageLevel()==ConsoleMessage.MessageLevel.WARNING)
                    AppDiagnostics.log(MainActivity.this,message.messageLevel()==ConsoleMessage.MessageLevel.ERROR?"ERROR":"WARN","preview-console",message.message()+" at "+message.sourceId()+":"+message.lineNumber());
                return true;
            }
        });
        created.setWebViewClient(new WebViewClient() {
            @Override public WebResourceResponse shouldInterceptRequest(WebView view,WebResourceRequest request) {
                return resource(request.getUrl(),request.getRequestHeaders());
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request) {
                Uri uri=request.getUrl();
                if(ORIGIN.equals(uri.getScheme()+"://"+uri.getAuthority())) return false;
                if(request.isForMainFrame()) openExternal(uri.toString());
                return true;
            }
            @Override public boolean onRenderProcessGone(WebView view,RenderProcessGoneDetail detail) {
                return handlePreviewRenderProcessGone(view,detail.didCrash());
            }
            @Override public void onReceivedError(WebView view,WebResourceRequest request,WebResourceError error){
                AppDiagnostics.log(MainActivity.this,"ERROR","preview-resource","code="+error.getErrorCode()+"; mainFrame="+request.isForMainFrame()+"; "+error.getDescription());
            }
        });
        previewGeneration=createdGeneration;web=created;previewRoot.addView(created,new FrameLayout.LayoutParams(-1,-1));
        created.loadUrl(ORIGIN+"/index.html");
    }
    // Shared by WebViewClient and same-signed instrumentation so the real
    // active-lease renderer-gone branch is exercised without a shipped fault
    // switch. This method only performs production recovery behavior.
    boolean handlePreviewRenderProcessGone(WebView view,boolean crashed){
        boolean current=view==web;
        AppDiagnostics.record(this,"preview-renderer",new IOException(crashed?"Preview renderer crashed.":"Android reclaimed the preview renderer."));
        // A callback/phase-stall recovery on API 29+ first terminates the
        // renderer. Complete its same-Activity replacement from that callback,
        // rather than reloading the stalled WebView object.
        if(current&&view==completedRestoreTerminatingWebView){
            finishCompletedRestoreWebViewReplacement(view,"render-process-gone");
            return true;
        }
        // The active completed-restore lease is the sole automatic recovery
        // exception. Non-lease renderer loss retains the explicit dialog.
        if(current&&completedRestoreMonitor!=null&&completedRestoreMonitor.active()){
            completedRestoreMonitor.rendererGone();
            // rendererGone() posts the lease recovery first. Post a second
            // FIFO fallback instead of falling through to the ordinary dialog:
            // recovery gets the first chance to persist its cap, retire this
            // WebView and start same-Activity replacement. The fallback keeps
            // the dialog only when recovery could not arm (for example, cap).
            completedRestoreHandler.post(()->{
                if(view!=web||view==completedRestoreTerminatingWebView)return;
                web=null;releasePreview(view);
                if(!isFinishing()&&!isDestroyed()){
                    previewRecoveryPending=true;showPreviewRecovery();
                }
            });
            return true;
        }
        if(view==web){
            web=null;releasePreview(view);
            if(!isFinishing()&&!isDestroyed()){
                previewRecoveryPending=true;showPreviewRecovery();
            }
        }else releasePreview(view);
        return true;
    }
    private boolean completedRestoreJobMatches(String jobId){
        JSONObject job=analysisStatus();return job!=null&&jobId!=null&&jobId.equals(job.optString("id"))&&"completed".equals(job.optString("state"));
    }
    private String completedRestoreRecoveryKey(String jobId){return "completed-restore-recovery."+jobId;}
    private boolean completedRestoreRecoveryUsed(String jobId){return jobId!=null&&getPreferences(0).getBoolean(completedRestoreRecoveryKey(jobId),false);}
    private boolean markCompletedRestoreRecoveryUsed(String jobId){
        return jobId!=null&&getPreferences(0).edit().putBoolean(completedRestoreRecoveryKey(jobId),true).commit();
    }
    private void clearCompletedRestoreRecoveryUsed(String jobId){
        if(jobId!=null)getPreferences(0).edit().remove(completedRestoreRecoveryKey(jobId)).apply();
    }
    private void recoverCompletedRestore(String jobId,String nonce,String reason){
        Runnable recover=()->{
            if(isFinishing()||Build.VERSION.SDK_INT>=17&&isDestroyed())return;
            final WebView previous;
            // A bridge call takes bridgeLock → monitor. The monitor tick that
            // requested this recovery may still hold its monitor lock, so this
            // runnable is always posted below rather than run inline. Once it
            // executes, make the final ownership check, persisted-cap write,
            // old-WebView retirement marker and lease invalidation one bridge
            // transaction. Terminal/ACK either wins before this transaction
            // (so `owns` fails and no cap is armed) or loses after retirement
            // (so it cannot terminally prove or clear a cap for this nonce).
            synchronized(completedRestoreBridgeLock){
                if(completedRestoreMonitor==null||!completedRestoreMonitor.owns(jobId,nonce))return;
                if(!completedRestoreJobMatches(jobId)){
                    AppDiagnostics.log(this,"WARN","completed-restore-watchdog","recovery skipped; durable job no longer completed job="+jobId);
                    return;
                }
                if(completedRestoreRecoveryUsed(jobId)){
                    AppDiagnostics.log(this,"WARN","completed-restore-watchdog","recovery skipped by persisted cap job="+jobId+" reason="+reason);
                    return;
                }
                previous=web;
                if(previous==null){
                    AppDiagnostics.log(this,"WARN","completed-restore-watchdog","replacement skipped; current WebView already absent job="+jobId);
                    return;
                }
                // Commit the cap before retiring the renderer. A process death
                // between these operations may leave the job pending, but can
                // never cause a replacement loop or forge an ACK.
                if(!markCompletedRestoreRecoveryUsed(jobId)){
                    AppDiagnostics.log(this,"ERROR","completed-restore-watchdog","recovery cap could not persist job="+jobId);
                    return;
                }
                completedRestoreRecoveryCount++;completedRestoreLastRecovery=jobId+":"+reason;
                AppDiagnostics.log(this,"WARN","completed-restore-watchdog","same-activity WebView replacement="+completedRestoreRecoveryCount+" job="+jobId+" reason="+reason);
                // Publish the retiring instance before invalidating the tuple.
                // A queued old bridge is therefore rejected throughout the
                // renderer-termination handoff.
                completedRestoreTerminatingWebView=previous;
                clearCompletedRestorePayloadLocked();
                completedRestoreMonitor.replacementStarted();
            }
            // Never hold bridgeLock while terminating/destroying a WebView or
            // starting the replacement; renderer callbacks may enter bridge
            // paths and must observe the already-committed retirement state.
            beginCompletedRestoreWebViewReplacement(previous,jobId,reason);
        };
        // CompletedRestoreMonitor.tick invokes Host.recover while holding its
        // own lock. Posting even on the UI thread releases that lock before
        // this runnable acquires bridgeLock → monitor, preserving one lock
        // order with JavaScript bridge methods.
        completedRestoreHandler.post(recover);
    }
    private void beginCompletedRestoreWebViewReplacement(WebView previous,String jobId,String reason){
        if(previous==null){
            AppDiagnostics.log(this,"WARN","completed-restore-watchdog","replacement skipped; current WebView already absent job="+jobId);
            return;
        }
        completedRestoreReplacementPath=null;
        completedRestoreTerminatingWebView=previous;
        Runnable fallback=()->{
            if(completedRestoreTerminatingWebView==previous){
                AppDiagnostics.log(this,"WARN","completed-restore-watchdog","renderer-gone callback exceeded native budget job="+jobId+" reason="+reason);
                finishCompletedRestoreWebViewReplacement(previous,"terminate-callback-budget");
            }
        };
        completedRestoreTerminateFallback=fallback;
        if(Build.VERSION.SDK_INT>=29){
            try{
                WebViewRenderProcess renderer=previous.getWebViewRenderProcess();
                if(renderer!=null){
                    completedRestoreReplacementPath="terminate-requested";
                    if(renderer.terminate()){
                        if(completedRestoreTerminatingWebView==previous)completedRestoreHandler.postDelayed(fallback,COMPLETED_RESTORE_TERMINATE_CALLBACK_BUDGET_MS);
                        return;
                    }
                }
            }catch(RuntimeException error){
                AppDiagnostics.record(this,"completed-restore-terminate",error);
            }
        }
        // Older devices and an already-detached renderer have no process to
        // terminate.  They still replace the WebView in this Activity once;
        // the persisted cap prevents any loop.
        finishCompletedRestoreWebViewReplacement(previous,"direct-fallback");
    }
    private void finishCompletedRestoreWebViewReplacement(WebView previous,String path){
        if(completedRestoreTerminatingWebView!=previous)return;
        if(completedRestoreTerminateFallback!=null)completedRestoreHandler.removeCallbacks(completedRestoreTerminateFallback);
        completedRestoreTerminateFallback=null;
        completedRestoreReplacementPath=(completedRestoreReplacementPath==null?"":completedRestoreReplacementPath+"->")+path;
        // Keep the old instance marked retired until it is no longer current.
        // Clearing this marker first creates a bridge-thread window where the
        // destroyed page still equals `web` and can begin a fresh lease after
        // replacementStarted() cleared the retired nonce.  The replacement
        // bridge has a distinct WebView/generation and remains admissible
        // while this old-instance marker is still present.
        if(web==previous){
            web=null;
            releasePreview(previous);
            createPreview();
        }else releasePreview(previous);
        completedRestoreTerminatingWebView=null;
    }
    private boolean completedRestoreFrameEligible(WebView target){
        return target!=null&&target==web&&target.isAttachedToWindow()&&target.isShown()
            &&target.getWindowVisibility()==View.VISIBLE&&target.hasWindowFocus()
            &&target.getWidth()>0&&target.getHeight()>0&&target.isHardwareAccelerated();
    }
    private boolean completedRestoreVisualMatchesLocked(String jobId,String nonce,WebView target){
        return completedRestoreMonitor!=null&&completedRestoreMonitor.owns(jobId,nonce)
            &&jobId!=null&&jobId.equals(completedRestoreVisualJobId)
            &&nonce!=null&&nonce.equals(completedRestoreVisualNonce)
            &&target==completedRestoreVisualWebView&&target==web;
    }
    private void clearCompletedRestoreVisualProofLocked(){
        completedRestoreVisualJobId=null;completedRestoreVisualNonce=null;completedRestoreVisualWebView=null;
        completedRestoreVisualRequested=false;completedRestoreVisualCommitted=false;completedRestoreVisualDrawListener=null;
    }
    private void clearCompletedRestorePayloadLocked(){
        RandomAccessFile previous=completedRestorePayloadFile;completedRestorePayloadFile=null;
        completedRestorePayloadJobId=null;completedRestorePayloadNonce=null;completedRestorePayloadProjectId=null;completedRestorePayloadSnapshot=null;completedRestorePayloadLength=-1L;
        if(previous!=null)try{previous.close();}catch(IOException ignored){}
    }
    private RandomAccessFile completedRestorePayloadLocked(String jobId,String nonce,String projectId,File source)throws IOException{
        if(completedRestorePayloadFile!=null){
            if(jobId.equals(completedRestorePayloadJobId)&&nonce.equals(completedRestorePayloadNonce)&&projectId.equals(completedRestorePayloadProjectId))return completedRestorePayloadFile;
            clearCompletedRestorePayloadLocked();
        }
        RandomAccessFile opened=new RandomAccessFile(source,"r");
        try{
            long length=opened.length();
            if(length<=0||length>ProjectStore.MAX_PROJECT_BYTES)throw new IOException("The completed project payload is unavailable.");
            completedRestorePayloadFile=opened;completedRestorePayloadJobId=jobId;completedRestorePayloadNonce=nonce;completedRestorePayloadProjectId=projectId;
            completedRestorePayloadLength=length;completedRestorePayloadSnapshot=Long.toString(length)+":"+UUID.randomUUID().toString();
            return opened;
        }catch(Throwable failure){try{opened.close();}catch(IOException ignored){}if(failure instanceof IOException)throw (IOException)failure;throw new IOException("The completed project payload is unavailable.",failure);}
    }
    private boolean requestCompletedRestoreVisualCommit(String jobId,String nonce){
        final WebView target;
        synchronized(completedRestoreBridgeLock){
            if(completedRestoreMonitor==null||!completedRestoreMonitor.owns(jobId,nonce)||web==null)return false;
            target=web;
            if(jobId.equals(completedRestoreVisualJobId)&&nonce.equals(completedRestoreVisualNonce)&&target==completedRestoreVisualWebView
                &&(completedRestoreVisualRequested||completedRestoreVisualCommitted))return true;
            clearCompletedRestoreVisualProofLocked();
            completedRestoreVisualJobId=jobId;completedRestoreVisualNonce=nonce;completedRestoreVisualWebView=target;completedRestoreVisualRequested=true;
        }
        Runnable request=()->startCompletedRestoreVisualCommit(jobId,nonce,target);
        if(Looper.myLooper()==Looper.getMainLooper())request.run();else runOnUiThread(request);
        return true;
    }
    private void startCompletedRestoreVisualCommit(String jobId,String nonce,WebView target){
        synchronized(completedRestoreBridgeLock){
            if(!completedRestoreVisualMatchesLocked(jobId,nonce,target))return;
            if(!completedRestoreFrameEligible(target)){
                completedRestoreVisualRequested=false;
                AppDiagnostics.log(this,"INFO","completed-restore-watchdog","visual proof waiting for eligible WebView job="+jobId);
                return;
            }
        }
        try{
            target.postVisualStateCallback(SystemClock.elapsedRealtime(),new WebView.VisualStateCallback(){
                @Override public void onComplete(long requestId){beginCompletedRestoreHardwareCommit(jobId,nonce,target);}
            });
        }catch(RuntimeException error){
            synchronized(completedRestoreBridgeLock){if(completedRestoreVisualMatchesLocked(jobId,nonce,target))completedRestoreVisualRequested=false;}
            AppDiagnostics.record(this,"completed-restore-visual-state",error);
        }
    }
    private void beginCompletedRestoreHardwareCommit(String jobId,String nonce,WebView target){
        synchronized(completedRestoreBridgeLock){
            if(!completedRestoreVisualMatchesLocked(jobId,nonce,target))return;
            if(!completedRestoreFrameEligible(target)){
                completedRestoreVisualRequested=false;
                return;
            }
        }
        ViewTreeObserver tree=target.getViewTreeObserver();
        if(!tree.isAlive()){
            synchronized(completedRestoreBridgeLock){if(completedRestoreVisualMatchesLocked(jobId,nonce,target))completedRestoreVisualRequested=false;}
            return;
        }
        try{
            if(Build.VERSION.SDK_INT>=29){
                tree.registerFrameCommitCallback(()->target.post(()->completeCompletedRestoreVisualCommit(jobId,nonce,target)));
            }else{
                final ViewTreeObserver.OnDrawListener[] listener=new ViewTreeObserver.OnDrawListener[1];
                listener[0]=()->{
                    ViewTreeObserver observer=target.getViewTreeObserver();if(observer.isAlive())observer.removeOnDrawListener(listener[0]);
                    synchronized(completedRestoreBridgeLock){if(completedRestoreVisualDrawListener==listener[0])completedRestoreVisualDrawListener=null;}
                    completeCompletedRestoreVisualCommit(jobId,nonce,target);
                };
                synchronized(completedRestoreBridgeLock){
                    if(!completedRestoreVisualMatchesLocked(jobId,nonce,target))return;
                    completedRestoreVisualDrawListener=listener[0];
                }
                tree.addOnDrawListener(listener[0]);
            }
            target.invalidate();
        }catch(RuntimeException error){
            synchronized(completedRestoreBridgeLock){if(completedRestoreVisualMatchesLocked(jobId,nonce,target))completedRestoreVisualRequested=false;}
            AppDiagnostics.record(this,"completed-restore-frame-commit",error);
        }
    }
    private void completeCompletedRestoreVisualCommit(String jobId,String nonce,WebView target){
        synchronized(completedRestoreBridgeLock){
            if(!completedRestoreVisualMatchesLocked(jobId,nonce,target))return;
            if(!completedRestoreFrameEligible(target)){
                completedRestoreVisualRequested=false;
                return;
            }
            completedRestoreVisualRequested=false;completedRestoreVisualCommitted=true;
            completedRestoreLastVisualFrameAt=SystemClock.elapsedRealtime();
            AppDiagnostics.log(this,"INFO","completed-restore-watchdog","visual hardware frame committed job="+jobId+" nonce="+nonce.substring(0,Math.min(16,nonce.length())));
        }
    }
    private boolean completedRestoreVisualCommitComplete(String jobId,String nonce){
        synchronized(completedRestoreBridgeLock){
            return completedRestoreVisualCommitted&&completedRestoreVisualMatchesLocked(jobId,nonce,completedRestoreVisualWebView);
        }
    }
    private void probeCompletedRestore(String jobId,String nonce,CompletedRestoreMonitor.ProbeCallback callback){
        Runnable probe=()->{
            if(completedRestoreMonitor==null||!completedRestoreMonitor.owns(jobId,nonce))return;
            WebView target=web;
            if(target==null)return;
            try{
                target.evaluateJavascript("(()=>{try{const a=window.LightForgeApp,s=a&&a.state,l=s&&s.completedRestore,p=a&&a.vehiclePreview;return JSON.stringify({booted:!!(a&&typeof window.onNativeEvent==='function'),backgroundApplying:!!(s&&s.backgroundApplying),backgroundPending:!!(s&&s.backgroundSyncPending),failed:!!(l&&l.failed),lease:l?{jobId:String(l.jobId||''),nonce:String(l.nonce||''),phase:String(l.phase||''),sequence:Number(l.sequence)||0,bytes:Number(l.bytes)||0}:null,previewLoaded:!!(p&&p.loaded),previewFrames:Number(p&&p.renderCount)||0});}catch(e){return JSON.stringify({probeError:String(e&&e.message||e)})}})()",raw->callback.receive(completedRestoreProbe(raw)));
            }catch(RuntimeException error){
                AppDiagnostics.log(this,"WARN","completed-restore-watchdog","probe evaluateJavascript failed: "+error.getMessage());
                // Do not turn an Android-side exception into a browser ACK or
                // an app failure.  The monitor's native callback budget will
                // decide whether this specific lease needs its one recovery.
            }
        };
        if(Looper.myLooper()==Looper.getMainLooper())probe.run();else runOnUiThread(probe);
    }
    private CompletedRestoreMonitor.Probe completedRestoreProbe(String raw){
        try{
            Object decoded=new JSONTokener(raw).nextValue();
            JSONObject value=decoded instanceof String?new JSONObject((String)decoded):(JSONObject)decoded;
            JSONObject lease=value.optJSONObject("lease");
            return new CompletedRestoreMonitor.Probe(value.optBoolean("booted"),value.optBoolean("backgroundApplying"),value.optBoolean("backgroundPending"),
                value.optBoolean("failed"),lease==null?"":lease.optString("jobId"),lease==null?"":lease.optString("nonce"),
                lease==null?"":lease.optString("phase"),lease==null?0:lease.optLong("sequence"),lease==null?0:lease.optLong("bytes"),
                value.optBoolean("previewLoaded"),value.optLong("previewFrames"));
        }catch(Exception error){
            AppDiagnostics.log(this,"WARN","completed-restore-watchdog","probe parse failed: "+error.getMessage());
            return null;
        }
    }
    // UI is kept across fold/unfold and rotation by manifest configChanges.
    @Override public void onBackPressed() {
        if(web==null){super.onBackPressed();return;}
        web.evaluateJavascript("window.handleNativeBack ? window.handleNativeBack() : false",result->{
            if(!"true".equals(result)) MainActivity.super.onBackPressed();
        });
    }
    @Override protected void onPause() {
        foreground=false;AppDiagnostics.log(this,"INFO","activity","paused");
        // During finish(), Android can tear down the hardware renderer between
        // onPause() and onDestroy(). Detach the WebView synchronously while the
        // window still owns it; otherwise ViewRootImpl may traverse a dead
        // renderer and stall the Activity teardown.
        if(isFinishing()||Build.VERSION.SDK_INT>=17&&isDestroyed())detachPreviewForTeardown();
        WebView current=web;if(current!=null)current.evaluateJavascript("window.pausePreview && window.pausePreview()",null);
        super.onPause();
    }
    @Override protected void onSaveInstanceState(Bundle state) {
        state.putBoolean("savePickerOpen",savePickerOpen);
        state.putString("diagnosticName",diagnosticName);
        if(web!=null)web.evaluateJavascript("window.pausePreview && window.pausePreview()",null);
        super.onSaveInstanceState(state);
    }
    @Override protected void onDestroy() {
        AppDiagnostics.log(this,"INFO","activity","destroyed; finishing="+isFinishing());
        foreground=false;previewRecoveryPending=false;
        if(previewRecoveryDialog!=null){previewRecoveryDialog.dismiss();previewRecoveryDialog=null;}
        if(analysisReceiverRegistered){unregisterReceiver(analysisReceiver);analysisReceiverRegistered=false;}
        if(completedRestoreMonitor!=null)completedRestoreMonitor.close();
        if(completedRestoreTerminateFallback!=null)completedRestoreHandler.removeCallbacks(completedRestoreTerminateFallback);
        completedRestoreTerminateFallback=null;completedRestoreTerminatingWebView=null;
        synchronized(completedRestoreBridgeLock){clearCompletedRestoreVisualProofLocked();clearCompletedRestorePayloadLocked();}
        cancelled.set(true);worker.shutdownNow();
        synchronized(exportLock) {if(activeExport!=null) activeExport.abort();}
        detachPreviewForTeardown();
        super.onDestroy();
    }
    private void detachPreviewForTeardown(){
        WebView previous=web;web=null;
        releasePreview(previous);
    }
    private void releasePreview(WebView previous){
        if(previous==null||!retiredWebViews.add(previous))return;
        try{ViewParent parent=previous.getParent();if(parent instanceof ViewGroup)((ViewGroup)parent).removeView(previous);}
        catch(RuntimeException error){AppDiagnostics.record(this,"preview-detach",error);}
        try{previous.removeJavascriptInterface("Android");}catch(RuntimeException error){AppDiagnostics.record(this,"preview-bridge-cleanup",error);}
        try{previous.destroy();}catch(RuntimeException error){AppDiagnostics.record(this,"preview-destroy",error);}
    }
    private void showPreviewRecovery(){
        if(!previewRecoveryPending||!foreground||isFinishing()||isDestroyed()||previewRecoveryDialog!=null)return;
        previewRecoveryDialog=new AlertDialog.Builder(this).setTitle("Reload the studio")
            .setMessage("Android restarted the preview engine. Your imported music and saved projects are still on this device.")
            .setPositiveButton("Reload",(dialog,which)->{
                previewRecoveryPending=false;
                if(!isFinishing()&&!isDestroyed())recreate();
            }).setNeutralButton("Export diagnostic log",null).setCancelable(false).create();
        previewRecoveryDialog.setOnDismissListener(dialog->previewRecoveryDialog=null);
        previewRecoveryDialog.show();
        previewRecoveryDialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener(view->exportDiagnostics());
    }
    private void event(String type,JSONObject payload) {
        final JSONObject data=payload==null?new JSONObject():payload;
        runOnUiThread(()-> {if(web!=null&&!isFinishing()) web.evaluateJavascript("window.onNativeEvent && window.onNativeEvent("+JSONObject.quote(type)+","+data.toString()+")",null);});
    }
    private static JSONObject json(Object... values) {
        JSONObject o=new JSONObject();try {for(int i=0;i<values.length;i+=2)o.put(String.valueOf(values[i]),values[i+1]);}catch(Exception ignored){}return o;
    }
    private void error(Throwable e) {
        AppDiagnostics.record(this,"device-operation",e);
        String message=e.getMessage();if(message==null||message.trim().isEmpty()) message="That operation could not finish. Please try again.";
        event("error",json("message",message));
    }
    private void progress(String stage,double value,String message) {event("progress",json("stage",stage,"progress",Math.max(0,Math.min(1,value)),"message",message));}
    private File project(String id) throws IOException {
        if(id==null||!id.matches("[A-Za-z0-9_-]{1,80}")) throw new IOException("Invalid project identifier.");
        return new File(projects,id);
    }
    private static byte[] readSmall(File file,int maximum) throws IOException {
        if(file.length()>maximum) throw new IOException("Project metadata is too large.");
        try(InputStream in=new FileInputStream(file);ByteArrayOutputStream out=new ByteArrayOutputStream()) {
            byte[] buffer=new byte[65536];int n,total=0;
            while((n=in.read(buffer))!=-1){if(n>maximum-total)throw new IOException("Project metadata is too large.");total+=n;out.write(buffer,0,n);}
            return out.toByteArray();
        }
    }
    private static void remove(File file) {if(file.isDirectory()&&!java.nio.file.Files.isSymbolicLink(file.toPath())){File[] children=file.listFiles();if(children!=null)for(File c:children)remove(c);}file.delete();}
    private void cleanupAbandonedCache() {
        File[] files=getCacheDir().listFiles();if(files!=null)for(File file:files)
            if(file.getName().matches("restore-[a-fA-F0-9-]{36}\\.zip")||file.getName().equals("exports"))remove(file);
    }
    private String appVersion() {
        try{return getPackageManager().getPackageInfo(getPackageName(),0).versionName;}catch(Exception unavailable){return "unknown";}
    }
    private long appVersionCode() {
        try{android.content.pm.PackageInfo info=getPackageManager().getPackageInfo(getPackageName(),0);return Build.VERSION.SDK_INT>=28?info.getLongVersionCode():info.versionCode;}catch(Exception unavailable){return 0;}
    }
    private JSONObject preparedExportInfo() {
        try {
            JSONObject value=PendingExportStore.read(exports);
            return value==null?null:json("name",value.optString("name"),"bytes",value.optLong("bytes"),"createdAt",value.optLong("createdAt"),"savePickerOpen",savePickerOpen);
        }catch(Exception invalid){return null;}
    }
    private JSONObject bootstrap() {
        try{if(startupRecovery!=null)startupRecovery.get();}catch(Exception ignored){}
        List<JSONObject> list=new ArrayList<>();File[] folders=projects.listFiles();
        if(folders!=null)for(File folder:folders)try {
            if(!folder.isDirectory()||folder.getName().startsWith("."))continue;
            File meta=new File(folder,"meta.json");if(meta.isFile()&&new File(folder,"audio.wav").isFile())list.add(ProjectPreview.metadata(ProjectStore.describe(projects,folder.getName()),new File(folder,"audio.wav")));
        }catch(Exception ignored){}
        Collections.sort(list,(a,b)->Long.compare(b.optLong("createdAt"),a.optLong("createdAt")));
        return json("version",appVersion(),"versionCode",appVersionCode(),"projects",new JSONArray(list),"lastProjectId",getPreferences(0).getString("lastProjectId",""),"pendingExport",preparedExportInfo(),"backgroundJob",analysisStatus(),"deviceCapabilities",deviceCapabilities());
    }
    private JSONObject analysisStatus(){try{return AnalysisJobStore.status(getFilesDir());}catch(Exception e){return null;}}
    @Override public void onTrimMemory(int level){super.onTrimMemory(level);AppDiagnostics.log(this,"WARN","activity-memory","trimMemory level="+level);}
    @Override public void onLowMemory(){super.onLowMemory();AppDiagnostics.log(this,"WARN","activity-memory","lowMemory");}
    private void diagnosticResult(JSONObject result){
        event("diagnosticExported",result);
        runOnUiThread(()->{if(!isDestroyed())Toast.makeText(this,"Saved "+result.optString("name","diagnostic log")+"\n"+result.optString("location","Your selected location"),Toast.LENGTH_LONG).show();});
    }
    private void diagnosticFailure(Throwable failure){
        AppDiagnostics.record(this,"diagnostic-export",failure);
        String message="The diagnostic log could not be saved. Check available storage and try again.";
        event("diagnosticExportFailed",json("message",message));
        runOnUiThread(()->{if(!isDestroyed())Toast.makeText(this,message,Toast.LENGTH_LONG).show();});
    }
    private void exportDiagnostics(){
        if(!diagnosticExporting.compareAndSet(false,true)){event("diagnosticExportFailed",json("message","A diagnostic export is already in progress."));return;}
        // Separate from import/export and neural workers so reporting remains usable during work.
        diagnosticWorker.execute(()->{
            boolean picker=false;
            try{
                JSONObject result=AppDiagnostics.export(getApplicationContext());
                if(result.optBoolean("requiresPicker")){
                    picker=true;
                    runOnUiThread(()->{
                        try{
                            if(isFinishing()||isDestroyed())throw new IOException("Reopen LightForge to save the diagnostic log.");
                            diagnosticName=result.optString("name");
                            Intent intent=new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("text/plain").putExtra(Intent.EXTRA_TITLE,diagnosticName);
                            intent.putExtra(android.provider.DocumentsContract.EXTRA_INITIAL_URI,Uri.parse("content://com.android.externalstorage.documents/document/primary%3ADownload"));
                            startActivityForResult(intent,SAVE_DIAGNOSTICS);
                        }catch(Exception failure){diagnosticName=null;diagnosticExporting.set(false);diagnosticFailure(failure);}
                    });
                }else diagnosticResult(result);
            }catch(Exception failure){diagnosticFailure(failure);}
            finally{if(!picker)diagnosticExporting.set(false);}
        });
    }
    public final class Bridge {
        private final WebView ownerWeb;
        private final long ownerGeneration;
        Bridge(WebView ownerWeb,long ownerGeneration){this.ownerWeb=ownerWeb;this.ownerGeneration=ownerGeneration;}
        private boolean ownsCurrentCompletedRestoreBridge(){
            return ownerWeb!=null&&ownerWeb==web&&ownerWeb!=completedRestoreTerminatingWebView&&ownerGeneration==previewGeneration
                &&!isFinishing()&&!(Build.VERSION.SDK_INT>=17&&isDestroyed());
        }
        @JavascriptInterface public void logDiagnostic(String level,String source,String message){AppDiagnostics.log(MainActivity.this,level,source,message);}
        @JavascriptInterface public void exportDiagnostics(){MainActivity.this.exportDiagnostics();}
        @JavascriptInterface public String getAnalysisStatus(){JSONObject job=analysisStatus();return job==null?"null":job.toString();}
        @JavascriptInterface public String getDeviceCapabilities(){return deviceCapabilities().toString();}
        @JavascriptInterface public boolean beginCompletedRestore(String jobId,String nonce,long bytes){
            synchronized(completedRestoreBridgeLock){
                if(!ownsCurrentCompletedRestoreBridge()){
                    AppDiagnostics.log(MainActivity.this,"WARN","completed-restore-watchdog","ignored lease begin from retired WebView job="+jobId);
                    return false;
                }
                if(completedRestoreMonitor==null)return false;
                if(!completedRestoreJobMatches(jobId)){
                    AppDiagnostics.log(MainActivity.this,"WARN","completed-restore-watchdog","ignored lease begin for non-completed job="+jobId);
                    return false;
                }
                boolean accepted=completedRestoreMonitor.begin(jobId,nonce,bytes);
                // A recovery can publish retirement while this bridge thread is
                // waiting for the monitor lock. Clear that just-created lease
                // before returning so a late old page cannot block the new
                // WebView's nonce or derive a terminal result.
                if(accepted&&!ownsCurrentCompletedRestoreBridge()){
                    completedRestoreMonitor.failed(jobId,nonce,"retired-webview-begin");
                    clearCompletedRestorePayloadLocked();
                    return false;
                }
                if(accepted){
                    clearCompletedRestoreVisualProofLocked();
                    clearCompletedRestorePayloadLocked();
                    completedRestoreLastAcceptedBeginGeneration=ownerGeneration;
                    completedRestoreLastAcceptedBeginJobId=jobId;
                }
                return accepted;
            }
        }
        @JavascriptInterface public boolean completedRestorePulse(String jobId,String nonce,String phase,long sequence,long bytes){
            synchronized(completedRestoreBridgeLock){
                if(!ownsCurrentCompletedRestoreBridge())return false;
                boolean visualPhase="preview-visual-commit".equals(phase);
                boolean accepted=completedRestoreMonitor!=null&&(!visualPhase||completedRestoreVisualCommitted&&completedRestoreVisualMatchesLocked(jobId,nonce,completedRestoreVisualWebView))
                    &&completedRestoreMonitor.pulse(jobId,nonce,phase,sequence,bytes);
                if(!accepted)
                    AppDiagnostics.log(MainActivity.this,"WARN","completed-restore-watchdog","ignored non-monotonic or foreign pulse job="+jobId+" sequence="+sequence);
                return accepted;
            }
        }
        @JavascriptInterface public boolean completedRestoreTerminal(String jobId,String nonce,long sequence,long bytes){
            synchronized(completedRestoreBridgeLock){
                if(!ownsCurrentCompletedRestoreBridge())return false;
                if(completedRestoreMonitor==null||!completedRestoreJobMatches(jobId)||!completedRestoreMonitor.terminal(jobId,nonce,sequence,bytes)){
                    AppDiagnostics.log(MainActivity.this,"WARN","completed-restore-watchdog","ignored foreign terminal job="+jobId+" sequence="+sequence);
                    return false;
                }
                // The monitor retains this exact terminal token until the
                // browser has written its ACK and confirms that write. Native
                // never reads or writes the browser's localStorage ACK.
                clearCompletedRestoreVisualProofLocked();
                clearCompletedRestorePayloadLocked();
                completedRestoreLastTerminalAt=SystemClock.elapsedRealtime();
                return true;
            }
        }
        @JavascriptInterface public boolean requestCompletedRestoreVisualCommit(String jobId,String nonce){
            if(!ownsCurrentCompletedRestoreBridge())return false;
            return MainActivity.this.requestCompletedRestoreVisualCommit(jobId,nonce);
        }
        @JavascriptInterface public boolean completedRestoreVisualCommitted(String jobId,String nonce){
            if(!ownsCurrentCompletedRestoreBridge())return false;
            return completedRestoreVisualCommitComplete(jobId,nonce);
        }
        @JavascriptInterface public boolean completedRestoreAckCommitted(String jobId,String nonce){
            synchronized(completedRestoreBridgeLock){
                if(!ownsCurrentCompletedRestoreBridge())return false;
                if(!completedRestoreJobMatches(jobId)||completedRestoreMonitor==null||!completedRestoreMonitor.ackCommitted(jobId,nonce)){
                    AppDiagnostics.log(MainActivity.this,"WARN","completed-restore-watchdog","ignored foreign post-ACK confirmation job="+jobId);
                    return false;
                }
                // This releases only the native recovery cap after the browser
                // has committed its own ACK.  It cannot inspect or mutate that
                // ACK and it invalidates the nonce so a replay is harmless.
                clearCompletedRestoreRecoveryUsed(jobId);
                completedRestoreLastAckConfirmationAt=SystemClock.elapsedRealtime();
                return true;
            }
        }
        @JavascriptInterface public boolean completedRestoreFailed(String jobId,String nonce,String reason){
            synchronized(completedRestoreBridgeLock){
                if(!ownsCurrentCompletedRestoreBridge())return false;
                boolean accepted=completedRestoreMonitor!=null&&completedRestoreMonitor.failed(jobId,nonce,reason);
                if(accepted){clearCompletedRestoreVisualProofLocked();clearCompletedRestorePayloadLocked();}
                if(!accepted)
                    AppDiagnostics.log(MainActivity.this,"WARN","completed-restore-watchdog","ignored foreign failed event job="+jobId);
                return accepted;
            }
        }
        @JavascriptInterface public String startAnalysis(String projectId){
            try{
                if(!foreground||importing||exporting)throw new IOException("Open LightForge and finish the current file operation before starting analysis.");
                final JSONObject job=AnalysisJobStore.prepare(getFilesDir(),projectId,appVersion());
                getPreferences(0).edit().putString("lastProjectId",projectId).apply();
                runOnUiThread(()->{
                    try{
                        startForegroundService(new Intent(MainActivity.this,AnalysisService.class).setAction(AnalysisService.ACTION_START).putExtra("jobId",job.optString("id")));
                        if(Build.VERSION.SDK_INT>=33&&checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)!=android.content.pm.PackageManager.PERMISSION_GRANTED)
                            requestPermissions(new String[]{android.Manifest.permission.POST_NOTIFICATIONS},2200);
                    }catch(Exception e){
                        AppDiagnostics.record(MainActivity.this,"analysis-start",e);
                        try{AnalysisJobStore.finish(getFilesDir(),job.optString("id"),"failed",e.getMessage());}catch(Exception ignored){}
                        sendAnalysisStatus();
                    }
                });
                return job.toString();
            }catch(Exception e){AppDiagnostics.record(MainActivity.this,"analysis-prepare",e);return json("error",e.getMessage()).toString();}
        }
        @JavascriptInterface public void cancelAnalysis(String jobId){runOnUiThread(()->{
            try{startService(new Intent(MainActivity.this,AnalysisService.class).setAction(AnalysisService.ACTION_CANCEL).putExtra("jobId",jobId));}
            catch(Exception e){error(e);}
        });}
        @JavascriptInterface public void continueInBackground(){runOnUiThread(()->{if(AnalysisService.alive())moveTaskToBack(true);});}
        @JavascriptInterface public void openBackgroundSettings(String kind){runOnUiThread(()->{
            try{
                Intent intent;
                if("notifications".equals(kind))intent=new Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(android.provider.Settings.EXTRA_APP_PACKAGE,getPackageName());
                else if("power".equals(kind)&&!((PowerManager)getSystemService(POWER_SERVICE)).isIgnoringBatteryOptimizations(getPackageName()))
                    intent=new Intent(android.provider.Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,Uri.parse("package:"+getPackageName()));
                else intent=new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,Uri.parse("package:"+getPackageName()));
                startActivity(intent);
            }catch(Exception e){error(e);}
        });}

        @JavascriptInterface public String getBootstrap() {return bootstrap().toString();}
        @JavascriptInterface public String readCompletedRestoreProjectChunk(String jobId,String nonce,String projectId,long offset,int requestedBytes) {
            try {
                synchronized(completedRestoreBridgeLock){
                    if(!ownsCurrentCompletedRestoreBridge()||completedRestoreMonitor==null||!completedRestoreMonitor.owns(jobId,nonce))throw new IOException("The completed restore lease is no longer active.");
                    if(offset<0||requestedBytes<=0||requestedBytes>COMPLETED_RESTORE_PROJECT_CHUNK_MAX_BYTES)throw new IOException("Invalid completed-project read range.");
                    final RandomAccessFile input;final long total;final String snapshot;
                    synchronized(AnalysisJobStore.class){
                        JSONObject job=analysisStatus();
                        if(job==null||!jobId.equals(job.optString("id"))||!"completed".equals(job.optString("state")))throw new IOException("The completed analysis job is no longer available.");
                        if(projectId==null||!projectId.equals(job.optString("projectId")))throw new IOException("The completed project does not belong to this job.");
                        File source=new File(AnalysisJobStore.project(getFilesDir(),projectId),"project.json");
                        if(!source.isFile())throw new IOException("The completed project payload is unavailable.");
                        input=completedRestorePayloadLocked(jobId,nonce,projectId,source);total=completedRestorePayloadLength;snapshot=completedRestorePayloadSnapshot;
                    }
                    if(offset>=total)throw new IOException("The completed project payload is unavailable.");
                    int count=(int)Math.min(Math.min((long)requestedBytes,total-offset),COMPLETED_RESTORE_PROJECT_CHUNK_MAX_BYTES);
                    byte[] bytes=new byte[count];input.seek(offset);input.readFully(bytes);
                    // Recovery and bridge terminal/failure operations use this
                    // same lock. A teardown that bypassed the monitor still
                    // changes WebView ownership, so check it again at return.
                    if(!ownsCurrentCompletedRestoreBridge()||completedRestoreMonitor==null||!completedRestoreMonitor.owns(jobId,nonce))throw new IOException("The completed restore lease was retired during payload read.");
                    return json("ok",true,"offset",offset,"total",total,"snapshot",snapshot,"base64",Base64.encodeToString(bytes,Base64.NO_WRAP)).toString();
                }
            }catch(Exception failure){
                AppDiagnostics.log(MainActivity.this,"WARN","completed-restore-payload","chunk read rejected: "+(failure.getMessage()==null?failure.getClass().getSimpleName():failure.getMessage()));
                return json("ok",false,"error","The completed project payload could not be read safely.").toString();
            }
        }
        @JavascriptInterface public void pickAudio() {runOnUiThread(()-> {
            if(importing||exporting||AnalysisJobStore.active(analysisStatus())) {error(new IOException("The previous operation is still finishing. Try again in a moment."));return;}
            Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");
            // Some document providers label FLAC, Opus or M4A as generic binary
            // or MP4. Let the importer inspect the actual selected container.
            intent.putExtra(Intent.EXTRA_MIME_TYPES,new String[]{"audio/*","application/ogg","application/octet-stream","application/mp4","video/mp4","video/webm","video/x-matroska","application/x-matroska"});
            try{startActivityForResult(intent,PICK_AUDIO);}catch(Exception e){error(e);}
        });}
        @JavascriptInterface public void loadDemo() {
            if(importing||AnalysisJobStore.active(analysisStatus())) return;
            startImport(null,"Glass Castle • demo excerpt",true);
        }
        @JavascriptInterface public void cancelWork() {
            cancelled.set(true);
            synchronized(exportLock) {
                if(activeExport!=null&&!activeExport.finishing){activeExport.abort();activeExport=null;exporting=false;}
            }
        }
        @JavascriptInterface public boolean saveProject(String id,String contents) {
            try {
                if(contents.length()>64*1024*1024) throw new IOException("This project's analysis metadata is too large to save.");
                synchronized(AnalysisJobStore.class){AnalysisJobStore.requireIdle(getFilesDir());ProjectStore.save(projects,id,new JSONObject(contents));}
                getPreferences(0).edit().putString("lastProjectId",id).apply();
                return true;
            }catch(Exception e){error(e);return false;}
        }
        @JavascriptInterface public void restorePreviousProject(String id) {
            try {
                if(importing||exporting||AnalysisJobStore.active(analysisStatus()))throw new IOException("Finish the current operation first.");
                JSONObject meta=ProjectStore.restorePrevious(projects,id);
                event("projectReady",ProjectPreview.metadata(meta,new File(project(id),"audio.wav")));
            }catch(Exception e){error(e);}
        }
        @JavascriptInterface public void resumePendingExport() {runOnUiThread(()->openSavePicker());}
        @JavascriptInterface public void discardPendingExport() {
            synchronized(exportLock) {
                try {
                    if(exporting||savePickerOpen)throw new IOException("Close the Save dialog or let the current save finish first.");
                    try{JSONObject prepared=PendingExportStore.read(exports);if(prepared!=null)cleanupPartialDestination(prepared);}catch(Exception ignored){}
                    PendingExportStore.discard(exports);pendingZip=null;pendingName=null;
                    event("projects",bootstrap());event("cancelled",json("stage","export"));
                }catch(Exception e){error(e);}
            }
        }
        @JavascriptInterface public void deleteProject(String id) {
            try {
                if(importing||exporting||AnalysisJobStore.active(analysisStatus())) throw new IOException("Finish or cancel the current operation first.");
                synchronized(exportLock) {if(activeExport!=null)throw new IOException("Finish the export before removing a project.");}
                remove(project(id));event("projects",bootstrap());
            }catch(Exception e){error(e);}
        }
        @JavascriptInterface public String beginExport(String metadata) {
            synchronized(exportLock) {
                try {
                    if(importing||exporting||AnalysisJobStore.active(analysisStatus())||activeExport!=null || pendingZip!=null) throw new IOException("The previous operation is still finishing. Try again in a moment.");
                    if(metadata.length()>ProjectStore.MAX_PROJECT_BYTES+1024*1024)throw new IOException("This export's editable project data is too large.");
                    JSONObject meta=new JSONObject(metadata);String id=UUID.randomUUID().toString();
                    File dir=project(meta.getString("projectId"));if(!new File(dir,"audio.wav").isFile()) throw new IOException("The project's audio file is missing.");
                    JSONObject projectState=meta.optJSONObject("projectState");
                    if(projectState!=null) {
                        if(projectState.optInt("version")!=1||!meta.getString("projectId").equals(projectState.optString("projectId")))
                            throw new IOException("The editable project does not match this export.");
                    } else {
                        // Backward compatible bridge callers still freeze the saved
                        // state here, before asynchronous ZIP assembly begins.
                        projectState=new JSONObject(new String(readSmall(new File(dir,"project.json"),ProjectStore.MAX_PROJECT_BYTES),StandardCharsets.UTF_8));
                    }
                    String frozenState=projectState.toString();
                    if(frozenState.getBytes(StandardCharsets.UTF_8).length>ProjectStore.MAX_PROJECT_BYTES)throw new IOException("This project's editable backup is too large.");
                    meta.remove("projectState");
                    activeExport=new ExportSession(id,meta,dir,new File(exports,id+".fseq"),frozenState);exporting=true;cancelled.set(false);return id;
                }catch(Exception e){error(e);return "";}
            }
        }
        @JavascriptInterface public boolean appendExport(String id,String base64) {
            synchronized(exportLock) {
                try {
                    if(activeExport==null||!activeExport.id.equals(id)) throw new IOException("The export session has expired.");
                    if(base64.length()>2*1024*1024) throw new IOException("Export chunk is too large.");
                    byte[] bytes=Base64.decode(base64,Base64.DEFAULT);activeExport.out.write(bytes);activeExport.size+=bytes.length;
                    if(activeExport.size>200_100_000L) throw new IOException("The sequence exceeds Tesla's four-hour limit.");
                    return true;
                }catch(Exception e){if(activeExport!=null)activeExport.abort();activeExport=null;exporting=false;error(e);return false;}
            }
        }
        @JavascriptInterface public void finishExport(String id) {
            final ExportSession session;
            synchronized(exportLock) {
                if(activeExport==null||!activeExport.id.equals(id)){error(new IOException("The export session has expired."));return;}
                session=activeExport;
                try{session.out.close();session.finishing=true;}catch(Exception e){session.abort();activeExport=null;exporting=false;error(e);return;}
            }
            worker.execute(()-> {
                boolean handedOff=false;
                try {
                    File zip=buildZip(session);
                    checkCancelled();
                    String name=safeName(session.meta.optString("name","My Show"))+"_LightShow.zip";
                    PendingExportStore.prepare(exports,zip,name);
                    pendingZip=zip;pendingName=name;
                    handedOff=true;
                    runOnUiThread(()->openSavePicker());
                }catch(Exception e){if(cancelled.get())event("cancelled",json("stage","export"));else error(e);}finally {
                    synchronized(exportLock){if(activeExport==session)activeExport=null;if(!handedOff)exporting=false;}session.file.delete();
                    if(!handedOff)new File(exports,session.id+".zip").delete();
                }
            });
        }
        @JavascriptInterface public void shareExport(String id) {
            final Uri uri=lastExportUri;
            if(uri==null){error(new IOException("Export a show first, then share the saved ZIP."));return;}
            runOnUiThread(()-> {
                try {
                    Intent share=new Intent(Intent.ACTION_SEND).setType("application/zip").putExtra(Intent.EXTRA_STREAM,uri);
                    share.setClipData(ClipData.newRawUri("LightForge show",uri));share.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                    startActivity(Intent.createChooser(share,"Share your light show"));
                }catch(Exception e){error(e);}
            });
        }
        @JavascriptInterface public void openExternal(String url) {MainActivity.this.openExternal(url);}
        @JavascriptInterface public void renameProject(String id,String name) {
            try {
                if(importing||exporting||AnalysisJobStore.active(analysisStatus()))throw new IOException("Finish the current operation first.");
                ProjectStore.rename(projects,id,name);event("projects",bootstrap());
            }catch(Exception e){error(e);}
        }
        @JavascriptInterface public void duplicateProject(String id,String name) {
            if(!claimImport())return;
            worker.execute(()-> {
                try {
                    progress("import",.01,"Making another version of your show");
                    JSONObject metadata=ProjectStore.duplicate(projects,id,name,projectProgress());
                    event("projectReady",ProjectPreview.metadata(metadata,new File(project(metadata.getString("id")),"audio.wav")));
                }catch(Exception e){if(cancelled.get())event("cancelled",json("stage","import"));else error(e);}
                finally{importing=false;}
            });
        }
        @JavascriptInterface public void pickProjectBackup() {runOnUiThread(()-> {
            if(importing||exporting||AnalysisJobStore.active(analysisStatus())){error(new IOException("Finish the current operation first."));return;}
            Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/zip");
            intent.putExtra(Intent.EXTRA_MIME_TYPES,new String[]{"application/zip","application/x-zip-compressed","application/octet-stream"});
            try{startActivityForResult(intent,PICK_BACKUP);}catch(Exception e){error(e);}
        });}
    }
    private static String safeName(String value) {
        String s=value.replaceAll("\\.[A-Za-z0-9]{1,5}$","").replaceAll("[^A-Za-z0-9_-]+","_").replaceAll("^_+|_+$","");
        if(s.isEmpty())s="My_Show";return s.substring(0,Math.min(60,s.length()));
    }
    private void openSavePicker() {
        if(savePickerOpen||isFinishing()||isDestroyed())return;
        try {
            JSONObject prepared=PendingExportStore.read(exports);
            if(prepared==null)throw new IOException("There is no prepared export to save.");
            pendingZip=PendingExportStore.file(exports,prepared);pendingName=prepared.getString("name");
            cleanupPartialDestination(prepared);
            Intent save=new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/zip");
            save.putExtra(Intent.EXTRA_TITLE,pendingName);
            cancelled.set(false);exporting=true;savePickerOpen=true;
            startActivityForResult(save,SAVE_ZIP);
        }catch(Exception e){savePickerOpen=false;exporting=false;error(e);event("exportRecovery",preparedExportInfo()==null?new JSONObject():preparedExportInfo());}
    }
    private void cleanupPartialDestination(JSONObject prepared) throws Exception {
        String previous=prepared.optString("destinationUri","");
        if(!previous.isEmpty()) {
            Uri uri=Uri.parse(previous);
            try{android.provider.DocumentsContract.deleteDocument(getContentResolver(),uri);}catch(Exception ignored){}
            try{getContentResolver().releasePersistableUriPermission(uri,Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_GRANT_WRITE_URI_PERMISSION);}catch(Exception ignored){}
            PendingExportStore.clearDestination(exports);
        }
    }
    private void openExternal(String url) {
        Uri uri=Uri.parse(url);String host=uri.getHost();
        if(!"https".equals(uri.getScheme())||host==null)return;
        if(!(host.equals("github.com")||host.equals("www.tesla.com")||host.equals("tesla.com")))return;
        runOnUiThread(()->{try{startActivity(new Intent(Intent.ACTION_VIEW,uri));}catch(Exception e){error(e);}});
    }
    @Override protected void onActivityResult(int request,int result,Intent intent) {
        super.onActivityResult(request,result,intent);
        if(request==SAVE_DIAGNOSTICS){
            final String name=diagnosticName;diagnosticName=null;
            if(result!=RESULT_OK||intent==null||intent.getData()==null){diagnosticExporting.set(false);event("diagnosticExportFailed",json("cancelled",true,"message","Diagnostic export cancelled. The log remains on this device."));return;}
            final Uri uri=intent.getData();
            diagnosticWorker.execute(()->{
                try{diagnosticResult(AppDiagnostics.exportTo(getApplicationContext(),uri,name));}
                catch(Exception failure){diagnosticFailure(failure);}
                finally{diagnosticExporting.set(false);}
            });
        } else if(request==PICK_AUDIO) {
            if(result!=RESULT_OK||intent==null||intent.getData()==null){event("cancelled",json("stage","import"));return;}
            Uri uri=intent.getData();String name="My track";
            try(Cursor c=getContentResolver().query(uri,new String[]{OpenableColumns.DISPLAY_NAME},null,null,null)){if(c!=null&&c.moveToFirst())name=c.getString(0);}catch(Exception ignored){}
            startImport(uri,name,false);
        } else if(request==PICK_BACKUP) {
            if(result!=RESULT_OK||intent==null||intent.getData()==null){event("cancelled",json("stage","import"));return;}
            restoreBackup(intent.getData());
        } else if(request==SAVE_ZIP) {
            savePickerOpen=false;
            // Recover from durable metadata even when Android recreated this Activity
            // while its document picker was open.
            final File zip;final String name;
            try {
                JSONObject prepared=PendingExportStore.read(exports);
                if(prepared==null)throw new IOException("The prepared export is no longer available. Export it again.");
                zip=PendingExportStore.file(exports,prepared);name=prepared.getString("name");
                pendingZip=zip;pendingName=name;
            }catch(Exception e){exporting=false;error(e);return;}
            if(result!=RESULT_OK||intent==null||intent.getData()==null){
                exporting=false;
                event("cancelled",json("stage","export"));
                event("exportRecovery",preparedExportInfo());
                return;
            }
            final Uri uri=intent.getData();
            try {
                int flags=intent.getFlags()&(Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
                try{getContentResolver().takePersistableUriPermission(uri,flags);}catch(Exception ignored){}
                PendingExportStore.destination(exports,uri.toString());
            }catch(Exception e){exporting=false;error(e);event("exportRecovery",preparedExportInfo());return;}
            exporting=true;cancelled.set(false);
            worker.execute(()-> {
                boolean saved=false;
                try {
                    progress("export",.9,"Saving your complete show");
                    try(InputStream in=new FileInputStream(zip);OutputStream out=getContentResolver().openOutputStream(uri,"wt")) {
                        if(out==null)throw new IOException("That destination could not be opened.");
                        byte[] buffer=new byte[131072];int n;while((n=in.read(buffer))!=-1){checkCancelled();out.write(buffer,0,n);}out.flush();
                    }
                    checkCancelled();
                    long bytes=zip.length();
                    PendingExportStore.clearDestination(exports);
                    PendingExportStore.discard(exports);pendingZip=null;pendingName=null;saved=true;
                    event("exported",json("name",name,"uri",uri.toString(),"bytes",bytes));
                    lastExportUri=uri;
                }catch(Exception e) {
                    try{android.provider.DocumentsContract.deleteDocument(getContentResolver(),uri);}catch(Exception ignored){}
                    try{PendingExportStore.clearDestination(exports);}catch(Exception ignored){}
                    if(cancelled.get())event("cancelled",json("stage","export"));else error(e);
                }finally {exporting=false;if(!saved)event("exportRecovery",preparedExportInfo());}
            });
        }
    }
    private void startImport(Uri uri,String name,boolean demo) {
        if(!claimImport())return;
        worker.execute(()-> {
            try {
                progress("import",.01,"Opening your music");
                JSONObject metadata;
                try(InputStream in=demo?getAssets().open("demo/glass-castle.wav"):getContentResolver().openInputStream(uri)) {
                    metadata=ProjectStore.importAudio(projects,in,name,projectProgress());
                }
                String id=metadata.getString("id");ProjectPreview.metadata(metadata,new File(project(id),"audio.wav"));
                getPreferences(0).edit().putString("lastProjectId",id).apply();
                progress("import",1,"Music is ready");event("imported",metadata);
            }catch(Exception e) {
                if(cancelled.get())event("cancelled",json("stage","import"));else error(e);
            }finally {importing=false;}
        });
    }
    private void checkCancelled() throws IOException {if(cancelled.get()||Thread.currentThread().isInterrupted())throw new IOException("Cancelled.");}
    private boolean claimImport() {
        synchronized(exportLock) {
            if(importing||exporting||AnalysisJobStore.active(analysisStatus())){error(new IOException("The previous operation is still finishing. Try again in a moment."));return false;}
            importing=true;cancelled.set(false);return true;
        }
    }
    private AudioImporter.Progress projectProgress() {return new AudioImporter.Progress(){
        public void update(double fraction,String message){progress("import",fraction,message);}
        public void check()throws IOException{checkCancelled();}
    };}
    private void restoreBackup(Uri uri) {
        if(!claimImport())return;
        worker.execute(()-> {
            File backup=new File(getCacheDir(),"restore-"+UUID.randomUUID()+".zip");
            try {
                progress("import",.01,"Opening your project backup");
                try(InputStream in=getContentResolver().openInputStream(uri);OutputStream out=new BufferedOutputStream(new FileOutputStream(backup))) {
                    if(in==null)throw new IOException("The backup could not be opened.");
                    byte[] b=new byte[131072];int n;long count=0;
                    while((n=in.read(b))!=-1){checkCancelled();count+=n;if(count>3_000_000_000L)throw new IOException("The project backup is too large.");out.write(b,0,n);}
                }
                JSONObject meta=ProjectStore.restore(projects,backup,projectProgress());
                event("projectReady",ProjectPreview.metadata(meta,new File(project(meta.getString("id")),"audio.wav")));
            }catch(Exception e){if(cancelled.get())event("cancelled",json("stage","import"));else error(e);}
            finally{backup.delete();importing=false;}
        });
    }

    private static final class ExportSession {
        final String id,projectState;final JSONObject meta;final File project,file;final OutputStream out;long size;boolean finishing;
        ExportSession(String id,JSONObject meta,File project,File file,String projectState)throws IOException{this.id=id;this.meta=meta;this.project=project;this.file=file;this.projectState=projectState;out=new BufferedOutputStream(new FileOutputStream(file),131072);}
        void abort(){try{out.close();}catch(Exception ignored){}file.delete();}
    }
    private File buildZip(ExportSession session) throws Exception {
        progress("export",.05,"Checking Tesla file requirements");
        File audio=new File(session.project,"audio.wav");
        JSONObject nativeReport=verifySequence(session.file,audio);
        File output=new File(exports,session.id+".zip");
        String sourceName=session.meta.optString("name","My Show");
        String readme="LIGHTFORGE — "+sourceName+"\n2025 Tesla Model 3 Long Range RWD\n\n"+
            "Extract this ZIP. Place the LightShow folder at the top level of an exFAT/FAT32 USB drive.\n"+
            "The playback pair must be LightShow/lightshow.fseq and LightShow/lightshow.wav.\n"+
            "Use a drive without a top-level TeslaCam folder or vehicle update files. Connect it to the glovebox USB-A port.\n"+
            "Select the custom show in Toybox > Light Show > Schedule Show and follow the vehicle prompts.\n\n"+
            "Audio is 44.1 kHz stereo 16-bit PCM. Sequence is FSEQ 2.0 uncompressed, 200 channels.\n"+
            "LightForge validates the file format and movement budget. Preview displays commands; Tesla determines physical motion speed and travel.\n"+
            "Allow room for enabled moving parts. This generated show has not been physically tested on your car.\n\n"+
            "Official guide: https://github.com/teslamotors/light-show\n";
        JSONObject report=json("app","LightForge "+appVersion(),"versionCode",appVersionCode(),"target","2025 Tesla Model 3 Long Range RWD","nativeChecks",nativeReport,"choreographyChecks",session.meta.optJSONObject("validation"),"createdAt",System.currentTimeMillis());
        try(ZipOutputStream zip=new ZipOutputStream(new BufferedOutputStream(new FileOutputStream(output),131072))) {
            zip.setLevel(1);addFile(zip,"LightShow/lightshow.fseq",session.file);checkCancelled();
            progress("export",.3,"Packaging the matched soundtrack");addFile(zip,"LightShow/lightshow.wav",audio);checkCancelled();
            addText(zip,"START_HERE.txt",readme);addText(zip,"Review/Validation.json",report.toString(2));
            addText(zip,"Review/LightForge_Project.json",session.projectState);
        }catch(Exception e){output.delete();throw e;}
        // Read every entry so CRC failures are caught before opening Android's Save dialog.
        progress("export",.72,"Verifying the complete ZIP");
        try(ZipFile z=new ZipFile(output)) {
            Enumeration<? extends ZipEntry> entries=z.entries();byte[] b=new byte[131072];
            while(entries.hasMoreElements()) {
                ZipEntry e=entries.nextElement();CRC32 crc=new CRC32();long count=0;
                try(InputStream in=z.getInputStream(e)){int n;while((n=in.read(b))!=-1){checkCancelled();crc.update(b,0,n);count+=n;}}
                if(crc.getValue()!=e.getCrc()||count!=e.getSize())throw new IOException("ZIP verification failed. Export again.");
            }
        }
        progress("export",.85,"Choose where to save your show");return output;
    }
    private void addFile(ZipOutputStream zip,String name,File file)throws IOException {
        ZipEntry entry=new ZipEntry(name);zip.putNextEntry(entry);
        try(InputStream in=new BufferedInputStream(new FileInputStream(file),131072)) {
            byte[] b=new byte[131072];int n;while((n=in.read(b))!=-1){checkCancelled();zip.write(b,0,n);}
        }
        zip.closeEntry();
    }
    private static void addText(ZipOutputStream zip,String name,String text)throws IOException{zip.putNextEntry(new ZipEntry(name));zip.write(text.getBytes(StandardCharsets.UTF_8));zip.closeEntry();}

    /** Independent verification of the bytes received from the UI, before export. */
    static JSONObject verifySequence(File sequence,File audio)throws Exception {
        byte[] head=new byte[32];long frames;int step,offset;
        try(RandomAccessFile r=new RandomAccessFile(sequence,"r")) {
            r.readFully(head);offset=AudioImporter.u16(head,4);frames=AudioImporter.u32(head,14);step=head[18]&255;
            if(head[0]!='P'||head[1]!='S'||head[2]!='E'||head[3]!='Q'||head[6]!=0||head[7]!=2||head[20]!=0||offset<32||AudioImporter.u32(head,10)!=200||(step!=15&&step!=20)||frames<1)
                throw new IOException("The generated FSEQ header is invalid.");
            if(sequence.length()!=offset+frames*200 || frames*step>14_400_000L)throw new IOException("The generated sequence has an invalid length.");
            byte[] wav=new byte[44];try(RandomAccessFile w=new RandomAccessFile(audio,"r")){w.readFully(wav);}
            if(AudioImporter.u32(wav,24)!=44100||AudioImporter.u16(wav,22)!=2||AudioImporter.u16(wav,34)!=16||AudioImporter.u16(wav,20)!=1)throw new IOException("The soundtrack must be 44.1 kHz stereo PCM WAV.");
            long samples=AudioImporter.u32(wav,40)/4;long expected=(samples*1000+44100L*step-1)/(44100L*step);
            if(frames!=expected)throw new IOException("The sequence and soundtrack durations do not match.");
            // Mirror the public closure semantics: short Open/Close requests
            // continue through Idle, while Stop interrupts immediately. These
            // positions are estimates; they check preparation and final settling.
            class ClosureState {
                final int channel; int raw=0,kind=0,commands=0; long start=0,autoAt=Long.MAX_VALUE,dance=0;
                double from,target,travel,first,low,high;
                ClosureState(int ch){channel=ch;from=target=ch<37?1:0;}
                double seconds(boolean opening){return channel==41?(opening?14000:4000):channel>=37&&channel<=40?4000:2000;}
                double at(long time){
                    double elapsed=Math.max(0,time-start);
                    if(kind==0)return from;
                    if(kind==1)return travel<=0?target:from+(target-from)*Math.min(1,elapsed/travel);
                    double firstTime=Math.abs(first-from)*seconds(first>from);
                    if(elapsed<firstTime)return from+(first-from)*elapsed/firstTime;
                    double up=(high-low)*seconds(true),down=(high-low)*seconds(false),phase=(elapsed-firstTime)%(up+down);
                    if(first==high)return phase<down?high-phase/seconds(false):low+(phase-down)/seconds(true);
                    return phase<up?low+phase/seconds(true):high-(phase-up)/seconds(false);
                }
                boolean moving(long time){return kind==2||kind==1&&time-start<travel;}
                void change(long time,int value,boolean automatic)throws IOException {
                    double current=at(time);
                    if(value==63||value==191){
                        from=current;target=value==63?1:0;start=time;travel=Math.abs(target-from)*seconds(target==1);kind=1;
                        if(channel==46)autoAt=value==63?time+120000:Long.MAX_VALUE;
                    }else if(value==127){
                        if(channel<37)throw new IOException("Mirrors support Fold and Unfold, not Dance.");
                        if((channel==41||channel==46)&&current<.999)throw new IOException("Open the trunk or charge port fully before its Dance cue.");
                        if(channel!=46){from=current;start=time;low=channel==41?.68:.18;high=channel==41?1:.86;first=current>(low+high)/2?low:high;kind=2;}
                    }else if(value==255||kind==2){from=current;start=time;kind=0;}
                }
            }
            int[] closureChannels={35,36,37,38,39,40,41,46};
            ClosureState[] closures=new ClosureState[closureChannels.length];
            for(int i=0;i<closures.length;i++)closures[i]=new ClosureState(closureChannels[i]);
            byte[] row=new byte[200];r.seek(offset);
            for(long f=0;f<frames;f++) {
                r.readFully(row);long time=f*step;
                for(int ch=1;ch<=30;ch++){
                    int value=row[ch-1]&255;
                    if((ch==15||ch==16||ch==29)&&value!=0)throw new IOException("The sequence enables a fog lamp absent from this North American Model 3 Highland profile.");
                    boolean ramp=ch>=1&&ch<=14; // Outer lamps may be ramp-capable on verified hardware.
                    if(ramp){if(value!=0&&value!=26&&value!=51&&value!=77&&value!=178&&value!=204&&value!=230&&value!=255)throw new IOException("Unsupported Tesla light ramp command.");}
                    else if(value!=0&&value!=255)throw new IOException("An on/off lamp contains an unsupported dimming command.");
                }
                for(int ch=31;ch<=34;ch++)if(row[ch-1]!=0)throw new IOException("This sequence contains a movement unsupported by your Model 3.");
                for(int ch=42;ch<=45;ch++)if(row[ch-1]!=0)throw new IOException("This sequence contains a movement unsupported by your Model 3.");
                for(ClosureState closure:closures){
                    int value=row[closure.channel-1]&255;
                    if(value!=0&&value!=63&&value!=127&&value!=191&&value!=255)throw new IOException("Invalid movement command.");
                    if(closure.autoAt<=time){
                        if(closure.raw==127)throw new IOException("Charge-port Dance extends beyond its automatic close window.");
                        closure.change(closure.autoAt,191,true);
                    }
                    if(value==127)closure.dance+=step;
                    if(value!=closure.raw){
                        if(value==63||value==127||value==191)closure.commands++;
                        closure.change(time,value,false);closure.raw=value;
                    }
                }
                for(int ch=47;ch<=175;ch++)if(row[ch-1]!=0)throw new IOException("Unsupported vehicle channel is active.");
                for(int ch=194;ch<=200;ch++)if(row[ch-1]!=0)throw new IOException("Reserved channel is active.");
            }
            for(byte b:row)if(b!=0)throw new IOException("The show must settle all channels at its end.");
            for(ClosureState closure:closures){
                int limit=closure.channel==46?3:closure.channel<37?20:6;
                if(closure.commands>limit||closure.dance>30000)throw new IOException("A movement exceeds its command or 30-second dance budget.");
                long finalTime=frames*step-40;double expectedPosition=closure.channel<37?1:0;
                if(closure.commands>0&&(closure.moving(finalTime)||Math.abs(closure.at(finalTime)-expectedPosition)>.001))throw new IOException("A movement must finish closed, or unfolded for mirrors. Add a final Close or Open cue with enough travel time.");
            }
            return json("status","PASS","frames",frames,"stepMs",step,"channels",200,"audioSampleRate",44100,"duration",frames*step/1000.0,"sha256",sha(sequence));
        }
    }
    private static String sha(File f)throws Exception {
        MessageDigest d=MessageDigest.getInstance("SHA-256");byte[] b=new byte[131072];
        try(InputStream in=new FileInputStream(f)){int n;while((n=in.read(b))!=-1)d.update(b,0,n);}
        StringBuilder s=new StringBuilder();for(byte x:d.digest())s.append(String.format(Locale.US,"%02x",x&255));return s.toString();
    }

    private WebResourceResponse resource(Uri uri,Map<String,String> headers) {
        return new AppResources(this,null).resource(uri,headers);
    }
}
