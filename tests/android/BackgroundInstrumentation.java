package com.cyberbasslord.lightforge;

import android.app.*;
import android.content.*;
import android.os.*;
import android.webkit.WebView;
import android.service.notification.StatusBarNotification;
import org.json.*;
import java.io.*;
import java.lang.reflect.Field;

/** Separate, same-signed test APK. No instrumentation hooks are shipped in the app. */
public final class BackgroundInstrumentation extends Instrumentation {
    private final JSONArray checks=new JSONArray();
    private File files;
    private MainActivity activity;
    private boolean checkedNativeStageRelease;
    private final long testStarted=SystemClock.elapsedRealtime();
    private long phaseStarted=testStarted,lastSnapshot;
    private volatile String currentPhase="starting";
    private JSONObject lastPowerTransition;
    private final Handler watchdogMain=new Handler(Looper.getMainLooper());
    private volatile boolean watchdogStopped;
    private Thread mainWatchdog;
    private void startMainWatchdog(){
        mainWatchdog=new Thread(()->{
            while(!watchdogStopped){
                java.util.concurrent.atomic.AtomicBoolean acknowledged=new java.util.concurrent.atomic.AtomicBoolean();
                long queuedAt=SystemClock.uptimeMillis(),lastDump=0;
                watchdogMain.post(()->acknowledged.set(true));
                while(!watchdogStopped&&!acknowledged.get()){
                    try{Thread.sleep(250);}catch(InterruptedException stopped){return;}
                    long now=SystemClock.uptimeMillis();
                    if(!acknowledged.get()&&now-queuedAt>=2000&&now-lastDump>=1000){
                        lastDump=now;dumpMainDelay(now-queuedAt);
                    }
                }
                try{Thread.sleep(500);}catch(InterruptedException stopped){return;}
            }
        },"LightForge-main-watchdog");
        mainWatchdog.setDaemon(true);mainWatchdog.start();
    }
    private void dumpMainDelay(long delayMs){
        try{
            JSONArray threads=new JSONArray();Thread mainThread=Looper.getMainLooper().getThread();
            for(java.util.Map.Entry<Thread,StackTraceElement[]> entry:Thread.getAllStackTraces().entrySet()){
                Thread thread=entry.getKey();String name=thread.getName();
                if(thread!=mainThread&&!name.contains("RenderThread")&&!name.contains("JavaBridge")
                    &&!name.startsWith("pool-")&&!name.startsWith("Thread-")&&!name.contains("Native"))continue;
                JSONArray stack=new JSONArray();int count=0;
                for(StackTraceElement frame:entry.getValue()){if(count++==64)break;stack.put(frame.toString());}
                threads.put(new JSONObject().put("name",name).put("id",thread.getId()).put("state",thread.getState().toString()).put("stack",stack));
            }
            JSONObject diagnostic=new JSONObject().put("phase",currentPhase).put("mainHeartbeatDelayMs",delayMs)
                .put("elapsedSeconds",(SystemClock.elapsedRealtime()-testStarted)/1000.0).put("threads",threads);
            Bundle event=new Bundle();event.putString("stream","LIGHTFORGE_MAIN_THREAD_DELAY "+diagnostic+"\n");sendStatus(0,event);
        }catch(Throwable error){
            android.util.Log.e("LightForgeTest","Could not capture delayed main-thread stacks",error);
        }
    }
    private void stopMainWatchdog(){
        watchdogStopped=true;watchdogMain.removeCallbacksAndMessages(null);
        if(mainWatchdog!=null)mainWatchdog.interrupt();
    }
    private void phase(String name)throws Exception{currentPhase=name;phaseStarted=SystemClock.elapsedRealtime();snapshot(true);}
    private void snapshot(boolean force)throws Exception{
        long now=SystemClock.elapsedRealtime();
        if(!force&&now-lastSnapshot<15000)return;
        lastSnapshot=now;
        JSONObject value=new JSONObject().put("phase",currentPhase)
            .put("elapsedSeconds",(now-testStarted)/1000.0)
            .put("phaseElapsedSeconds",(now-phaseStarted)/1000.0)
            .put("checks",new JSONArray(checks.toString()));
        if(lastPowerTransition!=null)value.put("powerTransition",lastPowerTransition);
        if(files!=null){
            JSONObject job=AnalysisJobStore.status(files);
            value.put("job",job==null?JSONObject.NULL:job);
            AnalysisJobStore.write(new File(files,"background-test-progress.json"),value,65536);
        }
        Bundle event=new Bundle();event.putString("stream","LIGHTFORGE_PROGRESS "+value+"\n");sendStatus(0,event);
    }
    private void check(boolean value,String label){if(!value)throw new AssertionError(label);}
    private void pass(String label)throws Exception{checks.put(label);snapshot(true);Bundle event=new Bundle();event.putString("stream",label+"\n");sendStatus(0,event);}
    private String shell(String command)throws Exception{
        try(ParcelFileDescriptor descriptor=getUiAutomation().executeShellCommand(command);InputStream in=new ParcelFileDescriptor.AutoCloseInputStream(descriptor)){
            ByteArrayOutputStream output=new ByteArrayOutputStream();byte[] bytes=new byte[4096];int count;
            while((count=in.read(bytes))!=-1){int keep=Math.min(count,65536-output.size());if(keep>0)output.write(bytes,0,keep);}
            return output.toString("UTF-8").trim();
        }
    }
    private void awaitPower(java.util.function.BooleanSupplier expected,String failure)throws Exception{
        long until=SystemClock.elapsedRealtime()+15000;
        while(!expected.getAsBoolean()&&SystemClock.elapsedRealtime()<until){snapshot(false);SystemClock.sleep(100);}
        if(!expected.getAsBoolean())throw new AssertionError(failure+"; deviceidle: "+shell("dumpsys deviceidle")+"; power: "+shell("dumpsys power"));
    }
    private void recordPowerTransition(PowerManager power,String commandOutput)throws Exception{
        lastPowerTransition=new JSONObject().put("phase",currentPhase)
            .put("interactive",power.isInteractive()).put("deepIdle",power.isDeviceIdleMode())
            .put("batteryExempt",power.isIgnoringBatteryOptimizations(getTargetContext().getPackageName()))
            .put("controllerDeepState",shell("dumpsys deviceidle get deep")).put("commandOutput",commandOutput);
        snapshot(true);
    }
    private Object field(Object object,String name)throws Exception{
        Field field=(object instanceof Class?(Class<?>)object:object.getClass()).getDeclaredField(name);field.setAccessible(true);
        return field.get(object instanceof Class?null:object);
    }
    private AnalysisService service()throws Exception{return (AnalysisService)field(AnalysisService.class,"instance");}
    private void waitService(boolean expected)throws Exception{
        long until=SystemClock.elapsedRealtime()+15000;
        while(SystemClock.elapsedRealtime()<until){snapshot(false);if(AnalysisService.alive()==expected)return;SystemClock.sleep(100);}
        throw new AssertionError("Service lifetime did not reach "+expected);
    }
    private JSONObject waitTerminal(long timeout)throws Exception{
        long until=SystemClock.elapsedRealtime()+timeout;
        while(SystemClock.elapsedRealtime()<until){
            snapshot(false);
            JSONObject job=AnalysisJobStore.status(files);if(job!=null&&!AnalysisJobStore.active(job))return job;
            if(job!=null&&job.optDouble("progress")>=.83){
                AnalysisService owner=service();NativePassageTask task=owner==null?null:(NativePassageTask)field(owner,"nativePassage");
                if(task!=null){check(field(task,"engine")==null,"Native separation buffers remained resident during voice/GAME analysis");checkedNativeStageRelease=true;}
            }
            SystemClock.sleep(100);
        }
        throw new AssertionError("Background job timed out: "+AnalysisJobStore.status(files));
    }
    private String fixture(String name)throws Exception{return fixture(name,3);}
    private String fixture(String name,int seconds)throws Exception{
        File source=new File(getTargetContext().getCacheDir(),name+".wav"),mono=new File(getTargetContext().getCacheDir(),name+"-mono.wav");
        float[] pcm=new float[seconds*44100*2];for(int i=0;i<pcm.length;i++)pcm[i]=(float)(.18*Math.sin(2*Math.PI*220*(i/2)/44100));
        try(WavConverter writer=new WavConverter(source,mono,44100)){writer.accept(pcm,pcm.length/2);writer.finish();}
        JSONObject meta;
        try(InputStream in=new FileInputStream(source)){meta=ProjectStore.importAudio(new File(files,"projects"),in,name,new AudioImporter.Progress(){public void update(double p,String s){}public void check(){}});}
        String id=meta.getString("id");File project=new File(AnalysisJobStore.project(files,id),"project.json");
        JSONObject state=AnalysisJobStore.read(project,ProjectStore.MAX_PROJECT_BYTES);
        state.put("settings",new JSONObject().put("analysisQuality","precision").put("dance","off").put("style","festival").put("stepMs",20).put("seed",2025));
        ProjectStore.save(new File(files,"projects"),id,state);return id;
    }
    private void launch(){
        activity=(MainActivity)startActivitySync(new Intent(getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        waitForIdleSync();activity.new Bridge().getBootstrap();
    }
    private void backgroundAndDoze()throws Exception{
        WebView closingView=(WebView)field(activity,"web");android.view.ViewGroup[] closingParent=new android.view.ViewGroup[1];
        runOnMainSync(()->{
            if(closingView!=null&&closingView.getParent() instanceof android.view.ViewGroup)closingParent[0]=(android.view.ViewGroup)closingView.getParent();
            activity.finishAndRemoveTask();
        });waitForIdleSync();
        long destroyedBy=SystemClock.elapsedRealtime()+15000;
        while(!activity.isDestroyed()&&SystemClock.elapsedRealtime()<destroyedBy)SystemClock.sleep(100);
        check(activity.isDestroyed()&&field(activity,"web")==null,"Activity teardown did not release its preview WebView");
        runOnMainSync(()->check(closingParent[0]==null||closingParent[0].indexOfChild(closingView)<0,"Destroyed preview WebView remains attached to its parent"));
        PowerManager power=(PowerManager)getTargetContext().getSystemService(Context.POWER_SERVICE);
        shell("dumpsys battery unplug");shell("input keyevent KEYCODE_SLEEP");
        awaitPower(()->!power.isInteractive(),"Screen did not turn off");
        check(power.isIgnoringBatteryOptimizations(getTargetContext().getPackageName()),"User-equivalent battery exemption missing");
        String forced=shell("dumpsys deviceidle force-idle deep");
        // DeviceIdleController posts MSG_REPORT_IDLE_ON after advancing its own
        // state. Shell completion does not mean PowerManager has handled it yet.
        awaitPower(()->power.isDeviceIdleMode(),"Android did not enter forced Doze; force-idle output: "+forced);
        check(!power.isInteractive(),"Screen woke during the Doze transition");
        recordPowerTransition(power,forced);
    }
    private void foreground()throws Exception{
        PowerManager power=(PowerManager)getTargetContext().getSystemService(Context.POWER_SERVICE);
        String unforced=shell("dumpsys deviceidle unforce");shell("dumpsys battery reset");
        shell("input keyevent KEYCODE_WAKEUP");shell("wm dismiss-keyguard");
        awaitPower(()->power.isInteractive()&&!power.isDeviceIdleMode(),"Android did not leave Doze and wake for reopening");
        launch();recordPowerTransition(power,unforced);
    }
    private JSONObject start(String projectId)throws Exception{
        JSONObject job=new JSONObject(activity.new Bridge().startAnalysis(projectId));check(!job.has("error"),job.toString());waitService(true);
        long until=SystemClock.elapsedRealtime()+15000;
        while(field(service(),"engine")==null&&SystemClock.elapsedRealtime()<until)SystemClock.sleep(100);
        check(field(service(),"engine")!=null,"Service WebView did not start");
        PowerManager.WakeLock lock=(PowerManager.WakeLock)field(service(),"wakeLock");check(lock!=null&&lock.isHeld(),"Background CPU wake lock missing");return job;
    }
    private NativePassageTask waitNativePassage(AnalysisService owner,int completedPassages,long timeout)throws Exception{
        long until=SystemClock.elapsedRealtime()+timeout;
        while(SystemClock.elapsedRealtime()<until){
            snapshot(false);
            JSONObject job=AnalysisJobStore.status(files);
            check(AnalysisJobStore.active(job),"Analysis ended before the required native passage: "+job);
            NativePassageTask task=(NativePassageTask)field(owner,"nativePassage");
            if(task!=null&&job.optInt("passagesCompleted")>=completedPassages){
                synchronized(task){
                    String token=(String)field(task,"token");
                    if(token!=null){JSONObject status=new JSONObject(task.status(token));
                        if("running".equals(status.optString("state"))&&status.optDouble("progress")>.01)return task;
                    }
                }
            }
            SystemClock.sleep(50);
        }
        throw new AssertionError("Native passage never advanced: "+AnalysisJobStore.status(files));
    }
    private void waitNativeReleased(NativePassageTask task)throws Exception{
        java.util.concurrent.ExecutorService executor=(java.util.concurrent.ExecutorService)field(task,"executor");
        check(executor.awaitTermination(15,java.util.concurrent.TimeUnit.SECONDS),"Cancelled native inference did not terminate promptly");
        check((Boolean)field(task,"closed")&&field(task,"engine")==null,"Native model was retained after cancellation");
    }
    private JSONObject separation(JSONObject saved)throws Exception{
        JSONObject music=saved.getJSONObject("music"),separation=music.getJSONObject("engine").getJSONObject("separationModel");
        check("precision".equals(music.getJSONObject("engine").optString("quality")),"Studio quality was silently changed");
        check("onnxruntime-android-cpu".equals(separation.optString("runtime")),"Studio did not run native CPU inference: "+separation);
        return separation;
    }
    @Override public void onCreate(Bundle arguments){super.onCreate(arguments);start();}
    @Override public void onStart(){
        JSONObject receipt=new JSONObject();Bundle output=new Bundle();
        try{
            files=getTargetContext().getFilesDir();startMainWatchdog();phase("first-screen-off-analysis");launch();String id=fixture("Background audio");JSONObject job=start(id);
            long backgroundAt=System.currentTimeMillis();backgroundAndDoze();
            JSONObject completed=waitTerminal(15*60*1000L);
            check("completed".equals(completed.optString("state")),"Screen-off analysis failed: "+completed);
            check(completed.getLong("updatedAt")>backgroundAt,"No progress after Activity destruction");waitService(false);
            JSONObject saved=AnalysisJobStore.read(new File(AnalysisJobStore.project(files,id),"project.json"),ProjectStore.MAX_PROJECT_BYTES);
            check(saved.getJSONObject("music").getInt("analysisVersion")==6,"Actual analysis missing");
            check(saved.getJSONObject("music").getJSONObject("engine").optBoolean("neural"),"Neural analysis did not run");
            check(saved.getJSONObject("compiled").getString("sha256").matches("[a-f0-9]{64}"),"Compiled frames missing");
            check(separation(saved).optInt("chunks")==1,"Short Studio fixture did not execute exactly one native passage");
            check(checkedNativeStageRelease,"No live voice/GAME-stage native-buffer release observation was recorded");
            pass("Actual Studio native CPU separation, neural analysis and choreography completed with the Activity destroyed, screen off and Doze forced with user-equivalent battery exemption; result was durably saved.");
            phase("reconnect-completed-project");foreground();
            JSONObject bootstrap=new JSONObject(activity.new Bridge().getBootstrap());
            check("completed".equals(bootstrap.getJSONObject("backgroundJob").getString("state")),"Reopened Activity did not reconnect");
            pass("Reopened Activity reports the completed job and its saved project.");
            String cancelId=fixture("Resume fixture",12);File cancelProject=new File(AnalysisJobStore.project(files,cancelId),"project.json");String original=AnalysisJobStore.hash(cancelProject);
            phase("wait-for-second-native-passage");
            JSONObject interruptedJob=start(cancelId);AnalysisService cancelledService=service();PowerManager.WakeLock cancelledLock=(PowerManager.WakeLock)field(cancelledService,"wakeLock");
            backgroundAndDoze();
            NativePassageTask cancelledNative=waitNativePassage(cancelledService,1,15*60*1000L);
            // Reopen only for the real foreground Cancel/Resume interaction.
            // Keep the long native inference phases free of software-rendered 3D work.
            phase("reopen-for-notification-cancel");foreground();
            cancelledNative=waitNativePassage(cancelledService,1,15000L);
            phase("notification-cancel");
            check(AnalysisJobStore.status(files).optBoolean("resumeAvailable"),"Completed passage was not reported as durable");
            NotificationManager notifications=(NotificationManager)getTargetContext().getSystemService(Context.NOTIFICATION_SERVICE);boolean sent=false;
            for(StatusBarNotification notification:notifications.getActiveNotifications()){
                Notification.Action[] actions=notification.getNotification().actions;
                if(actions!=null)for(Notification.Action action:actions)if("Cancel".contentEquals(action.title)){action.actionIntent.send();sent=true;break;}
            }
            check(sent,"Notification Cancel action missing");check("cancelled".equals(waitTerminal(15000).getString("state")),"Notification cancellation failed");waitService(false);
            waitForIdleSync();check(!cancelledLock.isHeld()&&field(cancelledService,"engine")==null,"Cancellation retained the CPU lock or analysis WebView");
            check(original.equals(AnalysisJobStore.hash(cancelProject)),"Cancellation replaced the saved project");
            check(field(cancelledService,"nativePassage")==null,"Service retained cancelled native task");
            // Start the next job without waiting for the old native executor. The
            // process-wide inference gate must prevent overlapping heavy allocations.
            phase("resume-screen-off-analysis");JSONObject resumedJob=start(cancelId);backgroundAndDoze();waitNativeReleased(cancelledNative);
            pass("Notification cancellation interrupts live native Studio work; immediate Resume can start while old native resources quiesce, with the previous project, CPU lock and WebView safely released.");
            check(interruptedJob.getString("analysisIdentity").equals(resumedJob.getString("analysisIdentity")),"Retry discarded the stable source/settings identity");
            JSONObject resumed=waitTerminal(15*60*1000L);check("completed".equals(resumed.optString("state")),"Partial Studio resume failed: "+resumed);waitService(false);
            JSONObject resumedProject=AnalysisJobStore.read(cancelProject,ProjectStore.MAX_PROJECT_BYTES),resumedSeparation=separation(resumedProject);
            check(resumedSeparation.optInt("restoredPassages")>=1,"Retry recomputed every passage instead of restoring completed work");
            check(resumedSeparation.optInt("chunks")==2,"Twelve-second fixture lost or added source passages");
            check(Math.abs(resumedProject.getJSONObject("music").getDouble("duration")-12)<.001,"Resumed source duration changed");
            check(resumedProject.getJSONObject("compiled").getString("sha256").matches("[a-f0-9]{64}"),"Resumed show did not compile");
            pass("Resume reuses at least one verified native passage after notification cancellation, preserves the 12-second source clock and saves a complete two-passage Studio show.");
            phase("reopen-for-timeout-callback");foreground();
            String timeoutId=fixture("Timeout fixture");File timeoutProject=new File(AnalysisJobStore.project(files,timeoutId),"project.json");String beforeTimeout=AnalysisJobStore.hash(timeoutProject);
            phase("timeout-callback");start(timeoutId);AnalysisService timeoutService=service();
            runOnMainSync(()->timeoutService.onTimeout(1,android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROCESSING));
            check("interrupted".equals(waitTerminal(5000).getString("state")),"Timeout callback did not preserve retry state");waitService(false);
            check(beforeTimeout.equals(AnalysisJobStore.hash(timeoutProject)),"Timeout replaced saved project");
            pass("Android media-processing timeout callback stops promptly and leaves a retryable job with the previous show intact.");
            phase("completed");
            receipt.put("passed",true).put("checks",checks).put("sdk",Build.VERSION.SDK_INT).put("scope","Android emulator with actual foreground service, native CPU Studio separation plus WebView/WASM rhythm/voice models, screen-off/Doze execution, live native cancellation, partial-passage resume and timeout callback; not a physical phone or Tesla.");
            output.putString("stream","BACKGROUND_ANDROID_PASS\n"+receipt.toString()+"\n");finish(Activity.RESULT_OK,output);
        }catch(Throwable error){
            try{snapshot(true);}catch(Exception ignored){}
            try{receipt.put("passed",false).put("checks",checks).put("phase",currentPhase).put("error",error.toString());}catch(Exception ignored){}
            StringWriter trace=new StringWriter();error.printStackTrace(new PrintWriter(trace));output.putString("stream","BACKGROUND_ANDROID_FAIL\n"+receipt+"\n"+trace);finish(Activity.RESULT_CANCELED,output);
        }finally{stopMainWatchdog();}
    }
}
