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
    private volatile boolean balancedObserverStopped,checkedBalancedStageRelease,observedBalancedNativeRun;
    private volatile Throwable balancedObservationFailure;
    private volatile int balancedPassesAtRelease;
    private Thread balancedObserver;
    private final long testStarted=SystemClock.elapsedRealtime();
    private long phaseStarted=testStarted,lastSnapshot;
    private volatile String currentPhase="starting";
    private JSONObject lastPowerTransition;
    private volatile JSONObject lastUiReadiness;
    private final JSONArray uiReadinessChecks=new JSONArray();
    private static final long UI_READINESS_POLL_MS=100L;
    private static final long UI_JAVASCRIPT_CALLBACK_BUDGET_MS=CompletedRestoreMonitor.CALLBACK_BUDGET_MS;
    // A normal foreground bootstrap must be prompt. If the production
    // completed-restore watchdog performs its one exact, durable recovery,
    // the replacement is a new renderer with its own bounded bootstrap window.
    // Completed restore permits a real, named 45-second GLTF/WebGL startup
    // phase. Retain only a small bounded bootstrap margin around that product
    // policy, including the one verified renderer replacement below.
    private static final long UI_READINESS_INITIAL_BUDGET_MS=60000L;
    private static final long UI_READINESS_RECOVERY_BUDGET_MS=60000L;
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
            if(lastUiReadiness!=null)diagnostic.put("uiReadiness",lastUiReadiness);
            Bundle event=new Bundle();event.putString("stream","LIGHTFORGE_MAIN_THREAD_DELAY "+diagnostic+"\n");sendStatus(0,event);
        }catch(Throwable error){
            android.util.Log.e("LightForgeTest","Could not capture delayed main-thread stacks",error);
        }
    }
    // Failure-only, same-signed instrumentation evidence. Production keeps its
    // existing private, sanitized journal and exposes no additional bridge API.
    private void emitFailureDiagnostics(){
        try{
            AppDiagnostics.flush(1000);
            DiagnosticLog journal=(DiagnosticLog)field(AppDiagnostics.class,"journal");
            if(journal==null)return;
            ByteArrayOutputStream snapshot=new ByteArrayOutputStream();journal.snapshot(snapshot);
            byte[] bytes=snapshot.toByteArray();int start=Math.max(0,bytes.length-64*1024);
            // Keep complete UTF-8 log lines and stay well below Binder limits.
            if(start>0){while(start<bytes.length&&bytes[start]!='\n')start++;if(start<bytes.length)start++;}
            String trace=new String(bytes,start,bytes.length-start,java.nio.charset.StandardCharsets.UTF_8);
            Bundle event=new Bundle();event.putString("stream","LIGHTFORGE_DIAGNOSTICS_BEGIN\n"+trace+"LIGHTFORGE_DIAGNOSTICS_END\n");sendStatus(0,event);
        }catch(Throwable diagnosticError){
            android.util.Log.e("LightForgeTest","Could not capture sanitized failure journal",diagnosticError);
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
        if(lastUiReadiness!=null)value.put("uiReadiness",lastUiReadiness);
        if(files!=null){
            JSONObject job=AnalysisJobStore.status(files);
            value.put("job",job==null?JSONObject.NULL:job);
            AnalysisJobStore.write(new File(files,"background-test-progress.json"),value,65536);
        }
        Bundle event=new Bundle();event.putString("stream","LIGHTFORGE_PROGRESS "+value+"\n");sendStatus(0,event);
    }
    private void check(boolean value,String label){if(!value)throw new AssertionError(label);}
    private void checkCanonicalSemanticAnalysis(JSONObject music,double sourceDuration,String label)throws Exception{
        check(music.getInt("analysisVersion")==8,label+" did not complete canonical schema v8");
        AnalysisJobStore.validateCheckpoint(music,sourceDuration);
        JSONObject timeline=music.getJSONObject("semanticTimeline"),salience=music.getJSONObject("musicSalience");
        check(timeline.getJSONArray("events").length()==salience.getJSONArray("events").length()&&salience.getJSONObject("summary").getInt("eventCount")==timeline.getJSONArray("events").length(),label+" semantic timeline and salience map disagree");
    }
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
    private MainActivity.Bridge bridge()throws Exception{
        return activity.new Bridge((WebView)field(activity,"web"),(Long)field(activity,"previewGeneration"));
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
            if(balancedObservationFailure!=null)throw new AssertionError("Balanced live lifecycle observation failed",balancedObservationFailure);
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
    private String fixture(String name,int seconds)throws Exception{return fixture(name,seconds,"precision");}
    private JSONObject studioSettings()throws Exception{
        final WebView view=(WebView)field(activity,"web");
        check(view!=null,"The initialized studio is required to freeze fixture settings");
        final java.util.concurrent.CountDownLatch completed=new java.util.concurrent.CountDownLatch(1);
        final java.util.concurrent.atomic.AtomicReference<String> result=new java.util.concurrent.atomic.AtomicReference<>();
        runOnMainSync(()->view.evaluateJavascript("(()=>{const a=window.LightForgeApp;return a&&a.state&&a.state.settings;})()",value->{result.set(value);completed.countDown();}));
        check(completed.await(15,java.util.concurrent.TimeUnit.SECONDS),"The studio did not return its complete settings");
        JSONObject settings=new JSONObject(result.get());
        check(settings.has("enabled")&&settings.has("vocalRegions")&&settings.has("outputEnabled"),"The studio settings snapshot is incomplete");
        return settings;
    }
    private String evaluate(WebView view,String source,String failure)throws Exception{
        final java.util.concurrent.CountDownLatch completed=new java.util.concurrent.CountDownLatch(1);
        final java.util.concurrent.atomic.AtomicReference<String> result=new java.util.concurrent.atomic.AtomicReference<>();
        runOnMainSync(()->view.evaluateJavascript(source,value->{result.set(value);completed.countDown();}));
        check(completed.await(15,java.util.concurrent.TimeUnit.SECONDS),failure);
        return result.get();
    }
    private String fixture(String name,int seconds,String quality)throws Exception{
        File source=new File(getTargetContext().getCacheDir(),name+".wav"),mono=new File(getTargetContext().getCacheDir(),name+"-mono.wav");
        float[] pcm=new float[seconds*44100*2];for(int i=0;i<pcm.length;i++)pcm[i]=(float)(.18*Math.sin(2*Math.PI*220*(i/2)/44100));
        try(WavConverter writer=new WavConverter(source,mono,44100)){writer.accept(pcm,pcm.length/2);writer.finish();}
        JSONObject meta;
        try(InputStream in=new FileInputStream(source)){meta=ProjectStore.importAudio(new File(files,"projects"),in,name,new AudioImporter.Progress(){public void update(double p,String s){}public void check(){}});}
        String id=meta.getString("id");File project=new File(AnalysisJobStore.project(files,id),"project.json");
        JSONObject state=AnalysisJobStore.read(project,ProjectStore.MAX_PROJECT_BYTES);
        // Real UI generation saves all studio settings before the native job
        // freezes them. A five-field synthetic object produces an input hash
        // that cannot survive the UI's later default merge on restoration.
        // Read the actual initialized studio, then apply the same test choices.
        state.put("settings",studioSettings().put("analysisQuality",quality).put("dance","off").put("style","festival").put("stepMs",20).put("seed",2025));
        ProjectStore.save(new File(files,"projects"),id,state);return id;
    }
    private void completedRestoreMonitorContract()throws Exception{
        final class Clock implements CompletedRestoreMonitor.Clock {long now;@Override public long now(){return now;}}
        final class Scheduler implements CompletedRestoreMonitor.Scheduler {
            Runnable task;long due=Long.MAX_VALUE;final Clock clock;
            Scheduler(Clock clock){this.clock=clock;}
            @Override public void postDelayed(Runnable next,long delay){task=next;due=clock.now+Math.max(0,delay);}
            @Override public void removeCallbacks(Runnable next){if(task==next){task=null;due=Long.MAX_VALUE;}}
            void drain(){for(int guard=0;guard<100;guard++){if(task==null||due>clock.now)return;Runnable next=task;task=null;due=Long.MAX_VALUE;next.run();}throw new AssertionError("Completed restore monitor scheduled without yielding");}
            void advance(long ms){clock.now+=ms;drain();}
        }
        final class Host implements CompletedRestoreMonitor.Host {
            boolean respond,recoveryUsed;int probes,recoveries,ackMutations;String recoveredJob,recoveredNonce;
            final java.util.List<CompletedRestoreMonitor.ProbeCallback> callbacks=new java.util.ArrayList<>();
            @Override public void requestProbe(String job,String nonce,CompletedRestoreMonitor.ProbeCallback callback){
                probes++;callbacks.add(callback);if(respond)callback.receive(new CompletedRestoreMonitor.Probe(true,true,true,false,job,nonce,"worker-started",0,0,false,0));
            }
            @Override public boolean recoveryAlreadyUsed(String job){return recoveryUsed;}
            @Override public void recover(String job,String nonce,String reason){recoveries++;recoveredJob=job;recoveredNonce=nonce;recoveryUsed=true;}
            @Override public void diagnostic(String message){}
        }
        Clock clock=new Clock();Scheduler scheduler=new Scheduler(clock);Host host=new Host();
        CompletedRestoreMonitor monitor=new CompletedRestoreMonitor(clock,scheduler,host);
        check(monitor.begin("completed-job","lease-a",0),"Completed-restore monitor rejected a valid lease");scheduler.drain();
        check(host.probes==1,"Completed-restore monitor did not dispatch its native liveness probe");
        scheduler.advance(CompletedRestoreMonitor.CALLBACK_BUDGET_MS);
        check(host.recoveries==1&&"completed-job".equals(host.recoveredJob)&&"lease-a".equals(host.recoveredNonce),"A stalled WebView callback did not request exactly one lease-scoped replacement");
        monitor.replacementStarted();check(!monitor.active()&&!monitor.pulse("completed-job","lease-a","worker-verified",1,0),"Retired lease remained able to advance after WebView replacement");
        check(monitor.begin("completed-job","lease-b",0),"Replacement WebView could not start a fresh lease nonce");scheduler.drain();scheduler.advance(CompletedRestoreMonitor.CALLBACK_BUDGET_MS);
        check(host.recoveries==1,"Persisted per-job cap allowed a second completed-restore replacement");

        // A valid ordered bridge pulse supersedes only the old callback. The
        // fresh probe still detects a renderer that dies immediately after it.
        Clock bridgeClock=new Clock();Scheduler bridgeScheduler=new Scheduler(bridgeClock);Host bridgeHost=new Host();
        CompletedRestoreMonitor bridgeProgress=new CompletedRestoreMonitor(bridgeClock,bridgeScheduler,bridgeHost);
        check(bridgeProgress.begin("bridge-job","bridge-lease",0),"Bridge liveness lease did not begin");bridgeScheduler.drain();
        check(bridgeHost.callbacks.size()==1,"Bridge liveness lease did not issue its first probe");
        check(bridgeProgress.pulse("bridge-job","bridge-lease","worker-started",1,0),"Valid bridge progress did not supersede its pending probe");
        bridgeScheduler.advance(CompletedRestoreMonitor.PROBE_INTERVAL_MS);
        check(bridgeHost.callbacks.size()==2,"Bridge progress did not open a fresh bounded probe");
        bridgeScheduler.advance(CompletedRestoreMonitor.CALLBACK_BUDGET_MS-1);
        check(bridgeHost.recoveries==0,"Superseded callback consumed the fresh probe budget");
        bridgeScheduler.advance(1);
        check(bridgeHost.recoveries==1,"A renderer that died after bridge progress was not recovered at the fresh callback budget");

        // A late callback from the superseded probe shares its lease fields but
        // must never satisfy the newer ticketed probe.
        Clock ticketClock=new Clock();Scheduler ticketScheduler=new Scheduler(ticketClock);Host ticketHost=new Host();
        CompletedRestoreMonitor ticketIsolation=new CompletedRestoreMonitor(ticketClock,ticketScheduler,ticketHost);
        check(ticketIsolation.begin("ticket-job","ticket-lease",0),"Ticket-isolation lease did not begin");ticketScheduler.drain();
        CompletedRestoreMonitor.ProbeCallback staleTicketCallback=ticketHost.callbacks.get(0);
        check(ticketIsolation.pulse("ticket-job","ticket-lease","worker-started",1,0),"Ticket-isolation bridge pulse was rejected");
        ticketScheduler.advance(CompletedRestoreMonitor.PROBE_INTERVAL_MS);
        check(ticketHost.callbacks.size()==2,"Ticket-isolation lease did not issue its fresh probe");
        staleTicketCallback.receive(new CompletedRestoreMonitor.Probe(true,true,true,false,"ticket-job","ticket-lease","worker-verified",2,0,false,0));
        ticketScheduler.advance(CompletedRestoreMonitor.CALLBACK_BUDGET_MS);
        check(ticketHost.recoveries==1,"A late superseded callback satisfied a newer same-lease probe");

        // Only an accepted ordered pulse may suppress a callback timeout.
        Clock rejectedClock=new Clock();Scheduler rejectedScheduler=new Scheduler(rejectedClock);Host rejectedHost=new Host();
        CompletedRestoreMonitor rejectedPulse=new CompletedRestoreMonitor(rejectedClock,rejectedScheduler,rejectedHost);
        check(rejectedPulse.begin("rejected-job","rejected-lease",0),"Rejected-pulse lease did not begin");rejectedScheduler.drain();
        check(!rejectedPulse.pulse("rejected-job","rejected-lease","worker-expand",1,0),"Out-of-order pulse suppressed a callback timeout");
        rejectedScheduler.advance(CompletedRestoreMonitor.CALLBACK_BUDGET_MS);
        check(rejectedHost.recoveries==1,"Rejected bridge progress incorrectly prevented recovery");

        Clock callbackClock=new Clock();Scheduler callbackScheduler=new Scheduler(callbackClock);Host callbackHost=new Host();
        CompletedRestoreMonitor callbackIsolation=new CompletedRestoreMonitor(callbackClock,callbackScheduler,callbackHost);
        check(callbackIsolation.begin("callback-job","old-nonce",0),"Old callback-isolation lease did not begin");callbackScheduler.drain();
        check(callbackHost.callbacks.size()==1,"Old lease did not retain its probe callback for isolation test");
        callbackIsolation.replacementStarted();
        check(callbackIsolation.begin("callback-job","new-nonce",0),"New callback-isolation lease did not begin");callbackScheduler.drain();
        callbackHost.callbacks.get(0).receive(new CompletedRestoreMonitor.Probe(true,true,true,false,"callback-job","old-nonce","worker-started",1,0,false,0));
        check(!callbackIsolation.pulse("callback-job","old-nonce","worker-verified",1,0),"Retired nonce pulse advanced a replacement lease");
        callbackHost.callbacks.get(1).receive(new CompletedRestoreMonitor.Probe(true,true,true,true,"callback-job","old-nonce","failed",1,0,false,0));
        check(callbackIsolation.active(),"Foreign failed probe cleared the replacement lease");
        callbackScheduler.advance(CompletedRestoreMonitor.PROBE_INTERVAL_MS);
        callbackScheduler.advance(CompletedRestoreMonitor.CALLBACK_BUDGET_MS);
        check(callbackHost.recoveries==1&&"new-nonce".equals(callbackHost.recoveredNonce),"Stale WebView callback satisfied the replacement lease callback budget");

        // A same-lease fallback probe may recover the monotonic prerequisite
        // closure of a lost bridge response. It must grant the named preview
        // startup interval and allow the later direct first-frame phase, but
        // must not fabricate MainActivity's native visual-commit proof.
        Clock mixedClock=new Clock();Scheduler mixedScheduler=new Scheduler(mixedClock);Host mixedHost=new Host();
        CompletedRestoreMonitor mixed=new CompletedRestoreMonitor(mixedClock,mixedScheduler,mixedHost);
        check(mixed.begin("mixed-job","mixed-lease",0),"Mixed fallback lease did not begin");mixedScheduler.drain();
        check(mixedHost.callbacks.size()==1,"Mixed fallback lease did not issue its probe");
        mixedHost.callbacks.get(0).receive(new CompletedRestoreMonitor.Probe(true,true,true,false,"mixed-job","mixed-lease","preview-starting",4,0,false,0));
        int mixedProbes=mixedHost.probes;
        mixedScheduler.advance(CompletedRestoreMonitor.CALLBACK_BUDGET_MS+1);
        check(mixedHost.recoveries==0&&mixedHost.probes==mixedProbes,"Fallback preview startup did not receive its bounded phase grace");
        check(mixed.pulse("mixed-job","mixed-lease","preview-first-render",5,0),"Direct first frame was wedged after fallback preview startup");
        check(!mixed.terminal("mixed-job","mixed-lease",6,0),"Fallback phase closure fabricated native visual commit");
        check(mixed.pulse("mixed-job","mixed-lease","preview-visual-commit",6,0),"Direct native visual phase was rejected after fallback closure");
        check(mixed.terminal("mixed-job","mixed-lease",7,0),"Mixed fallback/direct restore could not terminally prove completion");

        Clock invalidProbeClock=new Clock();Scheduler invalidProbeScheduler=new Scheduler(invalidProbeClock);Host invalidProbeHost=new Host();
        CompletedRestoreMonitor invalidProbe=new CompletedRestoreMonitor(invalidProbeClock,invalidProbeScheduler,invalidProbeHost);
        check(invalidProbe.begin("invalid-probe-job","invalid-probe-lease",0),"Invalid fallback lease did not begin");invalidProbeScheduler.drain();
        invalidProbeHost.callbacks.get(0).receive(new CompletedRestoreMonitor.Probe(true,true,true,false,"invalid-probe-job","invalid-probe-lease","preview-first-render",5,0,false,0));
        check(!invalidProbe.pulse("invalid-probe-job","invalid-probe-lease","preview-first-render",6,0),"An unrendered fallback probe bypassed phase prerequisites");

        // A malformed same-lease probe must not consume ordered direct bridge
        // sequence space or reset the phase deadline indefinitely.
        Clock unknownProbeClock=new Clock();Scheduler unknownProbeScheduler=new Scheduler(unknownProbeClock);Host unknownProbeHost=new Host();
        CompletedRestoreMonitor unknownProbe=new CompletedRestoreMonitor(unknownProbeClock,unknownProbeScheduler,unknownProbeHost);
        check(unknownProbe.begin("unknown-probe-job","unknown-probe-lease",0),"Unknown fallback lease did not begin");unknownProbeScheduler.drain();
        unknownProbeHost.callbacks.get(0).receive(new CompletedRestoreMonitor.Probe(true,true,true,false,"unknown-probe-job","unknown-probe-lease","unrecognized-phase",99,0,false,0));
        check(unknownProbe.pulse("unknown-probe-job","unknown-probe-lease","worker-started",1,0),"Unknown fallback probe consumed ordered direct bridge progress");

        Clock unknownDeadlineClock=new Clock();Scheduler unknownDeadlineScheduler=new Scheduler(unknownDeadlineClock);Host unknownDeadlineHost=new Host();
        CompletedRestoreMonitor unknownDeadline=new CompletedRestoreMonitor(unknownDeadlineClock,unknownDeadlineScheduler,unknownDeadlineHost);
        check(unknownDeadline.begin("unknown-deadline-job","unknown-deadline-lease",0),"Unknown deadline lease did not begin");unknownDeadlineScheduler.drain();
        // The initial probe is still the outstanding callback until it is
        // answered. Feed that callback an unknown state, then keep later
        // probes responsive so callback-stall cannot mask the bootstrap
        // deadline we are asserting here.
        unknownDeadlineHost.callbacks.get(0).receive(new CompletedRestoreMonitor.Probe(true,true,true,false,"unknown-deadline-job","unknown-deadline-lease","unrecognized-phase",99,0,false,0));
        unknownDeadlineHost.respond=true;
        for(long elapsed=0;elapsed<CompletedRestoreMonitor.BOOTSTRAP_PHASE_BUDGET_MS;elapsed+=CompletedRestoreMonitor.PROBE_INTERVAL_MS){
            unknownDeadlineScheduler.advance(Math.min(CompletedRestoreMonitor.PROBE_INTERVAL_MS,CompletedRestoreMonitor.BOOTSTRAP_PHASE_BUDGET_MS-elapsed));
        }
        check(unknownDeadlineHost.recoveries==1,"Unknown fallback probes postponed the bounded bootstrap recovery");

        // Deferred preview startup is a real GL/WebGL + GLTF load, not a
        // synthetic readiness signal. The ordered bridge phase retires the old
        // probe and grants only that startup interval a bounded grace; a real
        // first frame is still required before terminal proof.
        Clock startupClock=new Clock();Scheduler startupScheduler=new Scheduler(startupClock);Host startupHost=new Host();
        CompletedRestoreMonitor startup=new CompletedRestoreMonitor(startupClock,startupScheduler,startupHost);
        check(startup.begin("startup-job","startup-lease",0),"Preview-startup lease did not begin");startupScheduler.drain();
        check(startup.pulse("startup-job","startup-lease","worker-started",1,0),"Preview-startup worker start was rejected");
        check(startup.pulse("startup-job","startup-lease","worker-verified",2,0),"Preview-startup worker verification was rejected");
        check(startup.pulse("startup-job","startup-lease","show-adopted",3,0),"Preview-startup show adoption was rejected");
        check(!startup.pulse("startup-job","startup-lease","preview-first-render",4,0),"First render bypassed the preview-starting phase");
        check(startup.pulse("startup-job","startup-lease","preview-starting",4,0),"Preview-startup phase was rejected");
        int startupProbes=startupHost.probes;
        startupScheduler.advance(CompletedRestoreMonitor.CALLBACK_BUDGET_MS+1);
        check(startupHost.recoveries==0&&startupHost.probes==startupProbes,"Deferred WebGL/GLTF startup was treated as a generic JavaScript callback stall");
        check(startup.pulse("startup-job","startup-lease","preview-first-render",5,0),"A real first frame was rejected after bounded preview startup");
        check(startup.pulse("startup-job","startup-lease","preview-visual-commit",6,0),"Preview startup did not retain native visual proof");
        check(startup.terminal("startup-job","startup-lease",7,0),"Preview startup did not retain terminal proof after its real first frame");

        Clock stalledStartupClock=new Clock();Scheduler stalledStartupScheduler=new Scheduler(stalledStartupClock);Host stalledStartupHost=new Host();
        CompletedRestoreMonitor stalledStartup=new CompletedRestoreMonitor(stalledStartupClock,stalledStartupScheduler,stalledStartupHost);
        check(stalledStartup.begin("stalled-startup-job","stalled-startup-lease",0),"Stalled preview-startup lease did not begin");stalledStartupScheduler.drain();
        check(stalledStartup.pulse("stalled-startup-job","stalled-startup-lease","worker-started",1,0),"Stalled preview-startup worker start was rejected");
        check(stalledStartup.pulse("stalled-startup-job","stalled-startup-lease","worker-verified",2,0),"Stalled preview-startup worker verification was rejected");
        check(stalledStartup.pulse("stalled-startup-job","stalled-startup-lease","show-adopted",3,0),"Stalled preview-startup adoption was rejected");
        check(stalledStartup.pulse("stalled-startup-job","stalled-startup-lease","preview-starting",4,0),"Stalled preview-startup phase was rejected");
        stalledStartupScheduler.advance(CompletedRestoreMonitor.PREVIEW_STARTUP_BUDGET_MS-1);
        check(stalledStartupHost.recoveries==0,"Bounded preview-startup grace expired early");
        stalledStartupScheduler.advance(1);
        check(stalledStartupHost.recoveries==1,"A genuinely stalled preview startup did not recover at its bounded deadline");

        Clock staleClock=new Clock();Scheduler staleScheduler=new Scheduler(staleClock);Host staleHost=new Host();staleHost.respond=true;
        CompletedRestoreMonitor stale=new CompletedRestoreMonitor(staleClock,staleScheduler,staleHost);
        check(stale.begin("phase-job","lease-phase",0),"Phase lease did not begin");staleScheduler.drain();staleScheduler.advance(CompletedRestoreMonitor.BOOTSTRAP_PHASE_BUDGET_MS);
        check(staleHost.recoveries==1,"Responsive but non-advancing completed restore did not hit its lease phase budget");

        Clock progressClock=new Clock();Scheduler progressScheduler=new Scheduler(progressClock);Host progressHost=new Host();progressHost.respond=true;
        CompletedRestoreMonitor progress=new CompletedRestoreMonitor(progressClock,progressScheduler,progressHost);
        check(progress.begin("completed-job","lease-progress",0),"Progress lease did not begin");progressScheduler.drain();
        check(!progress.pulse("completed-job","stale-nonce","worker-started",1,0),"Foreign lease pulse advanced the monitor");
        check(!progress.pulse("completed-job","lease-progress","worker-expand",1,1024),"Worker pulse bypassed restore-started ordering");
        check(progress.pulse("completed-job","lease-progress","worker-started",1,0),"Ordered restore-started proof was rejected");
        for(long sequence=2;sequence<=5;sequence++){
            progressScheduler.advance(CompletedRestoreMonitor.MIN_PHASE_BUDGET_MS-1);
            check(progress.pulse("completed-job","lease-progress","worker-expand",sequence,sequence*1024),"Ordered restore pulse was rejected");
            check(!progress.pulse("completed-job","lease-progress","replay",sequence,sequence*1024),"Non-monotonic restore pulse advanced the monitor");
            progressScheduler.drain();
        }
        check(progressHost.recoveries==0,"Valid long completed restore was treated as a generic page timeout");
        check(!progress.terminal("completed-job","stale-nonce",6,5120),"Foreign terminal proof disarmed the monitor");
        check(!progress.terminal("completed-job","lease-progress",6,5120),"Terminal proof bypassed verified/adopted/first-render/visual predicates");
        check(progress.pulse("completed-job","lease-progress","worker-verified",6,5120),"Worker verification proof was rejected");
        check(progress.pulse("completed-job","lease-progress","show-adopted",7,5120),"Adopted show proof was rejected");
        check(!progress.pulse("completed-job","lease-progress","preview-first-render",8,5120),"First web render bypassed preview startup ordering");
        check(progress.pulse("completed-job","lease-progress","preview-starting",8,5120),"Preview startup proof was rejected");
        check(progress.pulse("completed-job","lease-progress","preview-first-render",9,5120),"First web render proof was rejected");
        check(!progress.terminal("completed-job","lease-progress",10,5120),"Terminal proof bypassed the native visual-frame predicate");
        check(progress.pulse("completed-job","lease-progress","preview-visual-commit",10,5120),"Native visual-frame proof was rejected");
        check(progress.terminal("completed-job","lease-progress",11,5120),"Ordered terminal proof was rejected");
        check(!progress.ackCommitted("completed-job","stale-lease"),"Foreign post-ACK confirmation released the terminal token");
        check(progress.ackCommitted("completed-job","lease-progress"),"Exact post-ACK confirmation did not release the terminal token");
        check(!progress.ackCommitted("completed-job","lease-progress"),"Replayed post-ACK confirmation released a second token");
        progressScheduler.advance(CompletedRestoreMonitor.MAX_PHASE_BUDGET_MS+CompletedRestoreMonitor.CALLBACK_BUDGET_MS);
        check(!progress.active()&&progressHost.recoveries==0,"Terminal proof did not disarm the monitor");
        check(progressHost.ackMutations==0,"Native monitor mutated the browser ACK");
        Clock ackClock=new Clock();Scheduler ackScheduler=new Scheduler(ackClock);Host ackHost=new Host();
        CompletedRestoreMonitor staleAck=new CompletedRestoreMonitor(ackClock,ackScheduler,ackHost);
        check(staleAck.begin("ack-job","old-terminal",0),"Terminal-token lease did not begin");
        check(staleAck.pulse("ack-job","old-terminal","worker-started",1,0),"Terminal-token start failed");
        check(staleAck.pulse("ack-job","old-terminal","worker-verified",2,0),"Terminal-token verification failed");
        check(staleAck.pulse("ack-job","old-terminal","show-adopted",3,0),"Terminal-token adoption failed");
        check(staleAck.pulse("ack-job","old-terminal","preview-starting",4,0),"Terminal-token preview startup failed");
        check(staleAck.pulse("ack-job","old-terminal","preview-first-render",5,0),"Terminal-token render proof failed");
        check(staleAck.pulse("ack-job","old-terminal","preview-visual-commit",6,0),"Terminal-token visual proof failed");
        check(staleAck.terminal("ack-job","old-terminal",7,0),"Terminal-token proof failed");
        check(!staleAck.begin("ack-job","fresh-lease",0),"Fresh lease bypassed a terminal token awaiting browser ACK confirmation");
        check(staleAck.ackCommitted("ack-job","old-terminal"),"Exact terminal ACK confirmation did not release its token");
        check(staleAck.begin("ack-job","fresh-lease",0),"Fresh lease did not begin after exact ACK confirmation");
        check(!staleAck.ackCommitted("ack-job","old-terminal"),"Old terminal confirmation released a cap after fresh nonce begin");
        Clock laterClock=new Clock();Scheduler laterScheduler=new Scheduler(laterClock);Host laterHost=new Host();
        CompletedRestoreMonitor laterCompleted=new CompletedRestoreMonitor(laterClock,laterScheduler,laterHost);
        check(laterCompleted.begin("older-completed-job","older-terminal",0),"Older terminal lease did not begin");
        check(laterCompleted.pulse("older-completed-job","older-terminal","worker-started",1,0),"Older terminal start failed");
        check(laterCompleted.pulse("older-completed-job","older-terminal","worker-verified",2,0),"Older terminal verification failed");
        check(laterCompleted.pulse("older-completed-job","older-terminal","show-adopted",3,0),"Older terminal adoption failed");
        check(laterCompleted.pulse("older-completed-job","older-terminal","preview-starting",4,0),"Older terminal preview startup failed");
        check(laterCompleted.pulse("older-completed-job","older-terminal","preview-first-render",5,0),"Older terminal render proof failed");
        check(laterCompleted.pulse("older-completed-job","older-terminal","preview-visual-commit",6,0),"Older terminal visual proof failed");
        check(laterCompleted.terminal("older-completed-job","older-terminal",7,0),"Older terminal proof failed");
        check(!laterCompleted.begin("older-completed-job","same-job-retry",0),"Same completed job bypassed its unconfirmed terminal token");
        check(laterCompleted.begin("later-completed-job","later-lease",0),"A later completed job was wedged by an old unconfirmed terminal token");
        check(!laterCompleted.ackCommitted("older-completed-job","older-terminal"),"A stale old ACK released state after the later job began");
        pass("Completed-restore native lease monitor rejects stale nonce/replayed pulses, foreign failed probes, retired callbacks and stale post-ACK tokens; it keeps same-job terminal exclusivity but admits a later completed job without clearing the old cap, survives ordered long restore pulses, gives real deferred WebGL/GLTF startup one bounded named grace without relaxing first-render/visual proof, bounds ordinary stalled callbacks to one persisted same-Activity replacement, retires valid direct-progress probes with ticketed callbacks so late same-lease results cannot mask a dead renderer, and never mutates the browser ACK.");
    }
    private void launch()throws Exception{
        activity=(MainActivity)startActivitySync(new Intent(getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        waitForIdleSync();awaitUiReady();bridge().getBootstrap();
    }
    private final class UiReadiness implements Runnable {
        final MainActivity owner=activity;
        volatile WebView view;
        final int recoveryCountAtStart;
        volatile boolean reboundCompletedRestore;
        final long began=SystemClock.elapsedRealtime();
        volatile long deadline=began+UI_READINESS_INITIAL_BUDGET_MS;
        final java.util.concurrent.CountDownLatch completed=new java.util.concurrent.CountDownLatch(1);
        final java.util.concurrent.atomic.AtomicBoolean finished=new java.util.concurrent.atomic.AtomicBoolean();
        final Runnable dropJavascriptCallbackForTest;
        private boolean javascriptCallbackDroppedForTest;
        private long javascriptRequestSerial;
        private long javascriptRequestAt;
        private WebView javascriptRequested;
        private boolean javascriptResponsePending;
        volatile Throwable failure;
        volatile JSONObject evidence;
        volatile JSONObject latest;
        android.view.ViewTreeObserver tree;
        Runnable commitCallback;
        android.view.ViewTreeObserver.OnDrawListener drawListener;
        UiReadiness()throws Exception{this(null);}
        UiReadiness(Runnable dropJavascriptCallbackForTest)throws Exception{
            this.dropJavascriptCallbackForTest=dropJavascriptCallbackForTest;
            view=(WebView)field(owner,"web");check(view!=null,"Preview WebView missing on launch");
            recoveryCountAtStart=(Integer)field(owner,"completedRestoreRecoveryCount");
        }
        private boolean expectedCompletedRestoreRecovery(WebView current,int recoveryCount,String recovery)throws Exception{
            JSONObject durable=AnalysisJobStore.status(files);
            String jobId=durable==null?"":durable.optString("id");
            String prefix=jobId+":";
            String reason=recovery!=null&&recovery.startsWith(prefix)?recovery.substring(prefix.length()):"";
            return !reboundCompletedRestore&&current!=null&&current!=view
                &&durable!=null&&"completed".equals(durable.optString("state"))&&!jobId.isEmpty()
                &&recoveryCount==recoveryCountAtStart+1
                &&(reason.startsWith("callback-stall")||reason.startsWith("phase-stall")||reason.startsWith("renderer-gone"));
        }
        boolean current()throws Exception{
            if(activity!=owner||owner.isFinishing()||owner.isDestroyed())return false;
            WebView current=(WebView)field(owner,"web");if(current==view)return true;
            // A strict readiness probe may span exactly one recovery of the
            // current durable completed job. Arbitrary reloads remain failures.
            int recoveryCount=(Integer)field(owner,"completedRestoreRecoveryCount");
            String recovery=(String)field(owner,"completedRestoreLastRecovery");
            if(expectedCompletedRestoreRecovery(current,recoveryCount,recovery)){
                cleanup();tree=null;commitCallback=null;drawListener=null;view=current;reboundCompletedRestore=true;
                // The monitor has already persisted its one per-job recovery
                // cap and retired the old lease. Give only this exact
                // replacement its own bounded page/bootstrap interval; do not
                // turn an arbitrary reload into extra readiness time.
                deadline=Math.max(deadline,SystemClock.elapsedRealtime()+UI_READINESS_RECOVERY_BUDGET_MS);
                return true;
            }
            return false;
        }
        private synchronized long beginJavascriptResponse(WebView requested){
            javascriptRequested=requested;javascriptRequestAt=SystemClock.elapsedRealtime();
            javascriptResponsePending=true;return ++javascriptRequestSerial;
        }
        private synchronized boolean ownsJavascriptResponse(WebView requested,long serial){
            return javascriptResponsePending&&javascriptRequested==requested&&javascriptRequestSerial==serial;
        }
        private synchronized boolean completeJavascriptResponse(WebView requested,long serial){
            if(!ownsJavascriptResponse(requested,serial))return false;
            javascriptResponsePending=false;return true;
        }
        private synchronized boolean waitingForJavascriptResponse(){return javascriptResponsePending;}
        private synchronized void clearJavascriptResponse(){
            javascriptResponsePending=false;javascriptRequested=null;javascriptRequestAt=0;javascriptRequestSerial++;
        }
        // Called from the instrumentation thread only. It never touches a View:
        // once an exact production recovery has made a replacement current, it
        // invalidates the orphaned callback and asks the main thread to rebind.
        void recoverMissingJavascriptCallback()throws Exception{
            final WebView requested;final long serial,requestedAt;
            synchronized(this){
                if(finished.get()||!javascriptResponsePending)return;
                requested=javascriptRequested;serial=javascriptRequestSerial;requestedAt=javascriptRequestAt;
            }
            if(requested==null||SystemClock.elapsedRealtime()-requestedAt<UI_JAVASCRIPT_CALLBACK_BUDGET_MS)return;
            WebView current=(WebView)field(owner,"web");
            int recoveryCount=(Integer)field(owner,"completedRestoreRecoveryCount");
            String recovery=(String)field(owner,"completedRestoreLastRecovery");
            boolean replaced=current!=requested;
            if(!replaced||!expectedCompletedRestoreRecovery(current,recoveryCount,recovery))return;
            synchronized(this){
                if(!javascriptResponsePending||javascriptRequested!=requested||javascriptRequestSerial!=serial)return;
                clearJavascriptResponse();
            }
            watchdogMain.post(this);
        }
        private void schedulePoll(){WebView target=view;if(target!=null)target.postDelayed(this,UI_READINESS_POLL_MS);}
        boolean visible(){return view.isAttachedToWindow()&&view.isShown()&&view.getWindowVisibility()==android.view.View.VISIBLE&&view.getWidth()>0&&view.getHeight()>0&&view.hasWindowFocus();}
        void record(String stage,JSONObject state)throws Exception{
            JSONObject value=state!=null?new JSONObject(state.toString()):latest!=null?new JSONObject(latest.toString()):new JSONObject();
            value.put("phase",currentPhase).put("probeStage",stage).put("waitSeconds",(SystemClock.elapsedRealtime()-began)/1000.0)
                .put("nativeAttached",view.isAttachedToWindow()).put("nativeShown",view.isShown())
                .put("nativeWindowVisibility",view.getWindowVisibility()).put("nativeWindowFocus",view.hasWindowFocus())
                .put("viewWidth",view.getWidth()).put("viewHeight",view.getHeight())
                .put("completedRestoreRebound",reboundCompletedRestore)
                .put("completedRestoreRecoveryCount",field(owner,"completedRestoreRecoveryCount"));
            latest=value;lastUiReadiness=value;
        }
        void cleanup(){
            clearJavascriptResponse();view.removeCallbacks(this);
            if(tree!=null&&tree.isAlive()){
                if(Build.VERSION.SDK_INT>=29&&commitCallback!=null)tree.unregisterFrameCommitCallback(commitCallback);
                if(drawListener!=null)tree.removeOnDrawListener(drawListener);
            }
        }
        void finish(Throwable error,JSONObject value){
            if(!finished.compareAndSet(false,true))return;
            try{record(error==null?"complete":"failed",value);evidence=error==null?latest:null;}
            catch(Throwable diagnosticError){if(error==null)error=diagnosticError;}
            failure=error;cleanup();completed.countDown();
        }
        @Override public void run(){
            if(finished.get())return;
            try{
                check(current(),"Preview changed while awaiting its first frame");
                check(SystemClock.elapsedRealtime()<deadline,"Preview JavaScript initialization exceeded its bounded readiness window");
                if(!visible()){record("waiting-for-native-visibility",null);schedulePoll();return;}
                // Export follows readBootstrap's synchronous native inventory
                // load, but its project restoration is asynchronous. Await the
                // existing restore-state flags as well as the actual 3D model
                // and a submitted canvas frame when that canvas is visible.
                record("waiting-for-javascript-response",null);
                // A delayed retry must never add a second renderer IPC while
                // an earlier evaluateJavascript callback is still in flight.
                if(waitingForJavascriptResponse())return;
                final WebView requested=view;
                final long javascriptRequest=beginJavascriptResponse(requested);
                requested.evaluateJavascript("(()=>{const a=window.LightForgeApp,s=a&&a.state,p=a&&a.vehiclePreview,c=document.getElementById('carCanvas'),r=c&&c.getBoundingClientRect();const visible=!!(r&&r.width>0&&r.height>0&&!document.hidden);const boot=!!(s&&Array.isArray(s.projects)&&typeof window.onNativeEvent==='function');const restored=!!(boot&&!s.loadingProject&&!s.composing&&!s.backgroundApplying&&!s.backgroundSyncPending);return {ready:document.readyState==='complete'&&restored&&!!p&&p.loaded&&!p.lost&&(!visible||p.renderCount>0),documentState:document.readyState,documentHidden:document.hidden,bootstrapInventoryReady:boot,projectRestoreIdle:restored,loadingProject:!!(s&&s.loadingProject),composing:!!(s&&s.composing),backgroundApplying:!!(s&&s.backgroundApplying),backgroundSyncPending:!!(s&&s.backgroundSyncPending),saveBlocked:!!(s&&s.saveBlocked),previewModelReady:!!(p&&p.loaded),previewGraphicsInitialized:!!(p&&p.renderer),previewLoadStarted:!!(p&&p._loadStarted),previewLoadDeferred:!!(p&&p._loadDeferred),restorePhase:s&&s.completedRestore?String(s.completedRestore.phase||'').slice(0,80):null,restoreSequence:s&&s.completedRestore?Number(s.completedRestore.sequence)||0:0,previewVisible:visible,previewRendererVisible:!!(p&&p.getPerformance().visible),previewPaused:!!(p&&p._paused),previewIntersecting:!!(p&&p._intersecting),previewHasSize:!!(p&&p._hasSize),previewFrames:p?p.renderCount:0,contextLost:!!(p&&p.lost),canvasRect:r?{left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height}:null,viewport:{width:innerWidth,height:innerHeight,scrollX,scrollY}};})()",value->{
                    if(finished.get()||!ownsJavascriptResponse(requested,javascriptRequest))return;
                    if(dropJavascriptCallbackForTest!=null&&!javascriptCallbackDroppedForTest){
                        javascriptCallbackDroppedForTest=true;
                        try{dropJavascriptCallbackForTest.run();}catch(Throwable error){clearJavascriptResponse();finish(error,null);}
                        return;
                    }
                    if(!completeJavascriptResponse(requested,javascriptRequest))return;
                    try{
                        check(current(),"Preview changed while awaiting its JavaScript response");
                        if(requested!=view){schedulePoll();return;}
                        JSONObject state=new JSONObject(value);
                        record(state.optBoolean("ready")?"waiting-for-visual-state":"waiting-for-app-readiness",state);
                        if(!state.optBoolean("ready")){schedulePoll();return;}
                        final WebView visualView=view;
                        check(current()&&visualView==view&&visible(),"Preview lost visibility before visual-state synchronization");
                        visualView.postVisualStateCallback(began,new WebView.VisualStateCallback(){
                            @Override public void onComplete(long requestId){
                                if(finished.get())return;
                                try{
                                    check(current(),"Preview changed before its first committed frame");
                                    if(visualView!=view){schedulePoll();return;}
                                    check(visible(),"Preview lost visibility before its first committed frame");
                                    record("waiting-for-hardware-frame-commit",state);
                                    check(visualView.isHardwareAccelerated(),"Lifecycle readiness requires the real hardware-accelerated WebView");
                                    tree=visualView.getViewTreeObserver();
                                    check(tree.isAlive(),"Preview view tree was detached before frame commit");
                                    Runnable recorded=()->watchdogMain.post(()->{
                                        if(finished.get())return;
                                        try{
                                            check(current(),"Preview changed before frame-commit acknowledgement");
                                            if(visualView!=view){schedulePoll();return;}
                                            check(visible(),"Preview detached before frame-commit acknowledgement");
                                            finish(null,new JSONObject(state.toString()).put("phase",currentPhase)
                                                .put("visualStateReady",true).put("firstFrameCommitted",true)
                                                .put("frameCommitMethod",Build.VERSION.SDK_INT>=29?"hardware-frame-commit":"on-draw-then-main")
                                                .put("hardwareAccelerated",true).put("viewWidth",visualView.getWidth()).put("viewHeight",visualView.getHeight())
                                                .put("waitSeconds",(SystemClock.elapsedRealtime()-began)/1000.0));
                                        }catch(Throwable error){finish(error,null);}
                                    });
                                    // postVisualStateCallback promises the
                                    // next draw is ready. It does not prove
                                    // that HWUI has completed that draw.
                                    if(Build.VERSION.SDK_INT>=29){commitCallback=recorded;tree.registerFrameCommitCallback(commitCallback);}
                                    else{
                                        java.util.concurrent.atomic.AtomicBoolean drawn=new java.util.concurrent.atomic.AtomicBoolean();
                                        drawListener=()->{if(drawn.compareAndSet(false,true))recorded.run();};
                                        tree.addOnDrawListener(drawListener);
                                    }
                                    visualView.invalidate();
                                }catch(Throwable error){finish(error,null);}
                            }
                        });
                    }catch(Throwable error){finish(error,null);}
                });
            }catch(Throwable error){finish(error,null);}
        }
    }
    private void awaitUiReady()throws Exception{awaitUiReady(null);}
    private void awaitUiReady(Runnable dropJavascriptCallbackForTest)throws Exception{
        UiReadiness probe=new UiReadiness(dropJavascriptCallbackForTest);
        lastUiReadiness=new JSONObject().put("phase",currentPhase).put("state","waiting-for-bootstrap-and-frame");snapshot(true);
        watchdogMain.post(probe);
        try{
            boolean complete=false;
            while(SystemClock.elapsedRealtime()<probe.deadline){
                long remaining=probe.deadline-SystemClock.elapsedRealtime();
                if(probe.completed.await(Math.max(1,Math.min(1000,remaining)),java.util.concurrent.TimeUnit.MILLISECONDS)){complete=true;break;}
                // A renderer can die after evaluateJavascript is accepted but
                // before its callback. This observer only arms a retry after
                // the real production completed-restore recovery has replaced
                // that exact WebView; it never turns callback loss into ready.
                probe.recoverMissingJavascriptCallback();
                snapshot(false);
            }
            if(!complete)snapshot(true);
            check(complete,"Preview bootstrap/first-frame readiness timed out; latest probe: "+probe.latest);
            if(probe.failure!=null)throw new AssertionError("Preview readiness failed",probe.failure);
            check(probe.evidence!=null&&probe.evidence.optBoolean("firstFrameCommitted"),"Preview frame-commit evidence missing");
            lastUiReadiness=probe.evidence;uiReadinessChecks.put(probe.evidence);snapshot(true);
        }finally{probe.finished.set(true);watchdogMain.post(probe::cleanup);}
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
        recordPowerTransition(power,unforced);launch();
    }
    private void requireCompletedRestoreAck(JSONObject completed,String label)throws Exception{
        WebView target=(WebView)field(activity,"web");check(target!=null,label+" has no active preview WebView");
        String raw=evaluate(target,"(()=>{const a=window.LightForgeApp,s=a&&a.state,p=a&&a.vehiclePreview;return JSON.stringify({ack:localStorage.getItem('lightforge-background-ack')||'',backgroundApplying:!!(s&&s.backgroundApplying),backgroundSyncPending:!!(s&&s.backgroundSyncPending),previewFrames:Number(p&&p.renderCount)||0});})()",label+" could not read completed-restore ACK evidence");
        Object decoded=new JSONTokener(raw).nextValue();JSONObject evidence=decoded instanceof String?new JSONObject((String)decoded):(JSONObject)decoded;
        long nativeAckAt=(Long)field(activity,"completedRestoreLastAckConfirmationAt");
        check(completed.getString("id").equals(evidence.optString("ack"))&&!evidence.optBoolean("backgroundApplying")
            &&!evidence.optBoolean("backgroundSyncPending")&&evidence.optLong("previewFrames")>0&&nativeAckAt>0,
            label+" did not retain a terminal native/browser ACK and rendered preview proof: "+evidence);
    }
    private void completedRestorePayloadBypassesProjectFetch(JSONObject completed)throws Exception{
        phase("completed-restore-durable-payload");
        WebView target=(WebView)field(activity,"web");check(target!=null,"No WebView available for durable completed-project payload test");
        String projectId=completed.getString("projectId");
        String injected="(()=>{const a=window.LightForgeApp;if(!a||!window.Android||typeof window.Android.readCompletedRestoreProjectChunk!=='function')throw Error('Scoped completed-project bridge unavailable');localStorage.removeItem('lightforge-background-ack');a.state.backgroundSeen=null;const original=window.fetch;const probe={calls:0,original};window.__lightforgeCompletedProjectFetchProbe=probe;window.fetch=(input,...rest)=>{const url=String(input&&input.url||input||'');if(url.includes('/project/"+projectId+"/project.json')){probe.calls++;return new Promise(()=>{});}return original(input,...rest);};window.onNativeEvent('analysisJob',JSON.parse("+JSONObject.quote(completed.toString())+"));return true;})()";
        try{
            check("true".equals(evaluate(target,injected,"Durable completed-project payload test could not arm its project fetch stall")),"Durable completed-project payload test returned an unexpected result");
            awaitUiReady();
            String proof=evaluate((WebView)field(activity,"web"),"(()=>{const a=window.LightForgeApp,s=a&&a.state,p=window.__lightforgeCompletedProjectFetchProbe;return JSON.stringify({fetchCalls:Number(p&&p.calls)||0,ack:localStorage.getItem('lightforge-background-ack')||'',loadingProject:!!(s&&s.loadingProject),backgroundApplying:!!(s&&s.backgroundApplying),backgroundSyncPending:!!(s&&s.backgroundSyncPending),previewFrames:Number(a&&a.vehiclePreview&&a.vehiclePreview.renderCount)||0});})()","Durable completed-project payload evidence could not be read");
            Object decoded=new JSONTokener(proof).nextValue();JSONObject evidence=decoded instanceof String?new JSONObject((String)decoded):(JSONObject)decoded;
            check(evidence.optInt("fetchCalls")==0,"Completed restore re-entered the stalled appassets project fetch: "+evidence);
            check(completed.getString("id").equals(evidence.optString("ack")),"Completed restore did not ACK after its direct durable payload read: "+evidence);
            check(!evidence.optBoolean("loadingProject")&&!evidence.optBoolean("backgroundApplying")&&!evidence.optBoolean("backgroundSyncPending")&&evidence.optLong("previewFrames")>0,"Direct durable payload restore left UI state latched: "+evidence);
            pass("A real completed-project reconnect bypassed an intentionally never-resolving appassets project.json fetch through the generation- and nonce-bound durable payload bridge, then reached a visible preview and terminal browser ACK.");
        }finally{evaluate((WebView)field(activity,"web"),"(()=>{const p=window.__lightforgeCompletedProjectFetchProbe;if(p&&p.original)window.fetch=p.original;delete window.__lightforgeCompletedProjectFetchProbe;return true;})()","Durable completed-project payload test could not restore fetch");}
    }
    private void completedRestoreActiveRendererGone(JSONObject completed)throws Exception{
        phase("completed-restore-active-renderer-gone");
        MainActivity owner=activity;WebView stalled=(WebView)field(owner,"web");check(stalled!=null,"No WebView available for active renderer-gone lease injection");
        MainActivity.Bridge stalledBridge=bridge();int recoveryCountAtStart=(Integer)field(owner,"completedRestoreRecoveryCount");
        long faultAt=SystemClock.elapsedRealtime();
        String injected="(()=>{const a=window.LightForgeApp;if(!a||!window.ShowCompiler)throw Error('Studio compiler unavailable for test');localStorage.removeItem('lightforge-background-ack');a.state.backgroundSeen=null;const restore=window.ShowCompiler.restore;let held=false;window.ShowCompiler.restore=function(){const result=restore.apply(this,arguments);if(!held){held=true;return new Promise(()=>{});}return result;};window.onNativeEvent('analysisJob',JSON.parse("+JSONObject.quote(completed.toString())+"));return true;})()";
        check("true".equals(evaluate(stalled,injected,"Active renderer-gone lease injection did not arm")),"Active renderer-gone lease injection returned an unexpected result");
        long activeBy=SystemClock.elapsedRealtime()+10000;CompletedRestoreMonitor monitor=(CompletedRestoreMonitor)field(owner,"completedRestoreMonitor");
        while(SystemClock.elapsedRealtime()<activeBy&&!(monitor!=null&&monitor.active()&&(WebView)field(owner,"web")==stalled)){snapshot(false);SystemClock.sleep(50);monitor=(CompletedRestoreMonitor)field(owner,"completedRestoreMonitor");}
        check(monitor!=null&&monitor.active()&&(WebView)field(owner,"web")==stalled,"Completed restore did not hold an active lease before renderer-gone handling");
        String rawLease=evaluate(stalled,"(()=>{const l=window.LightForgeApp&&window.LightForgeApp.state&&window.LightForgeApp.state.completedRestore;return JSON.stringify(l?{jobId:String(l.jobId||''),nonce:String(l.nonce||''),sequence:Number(l.sequence)||0}:null);})()","Active lease identity could not be read before renderer-gone handling");
        Object decodedLease=new JSONTokener(rawLease).nextValue();JSONObject oldLease=decodedLease instanceof String?new JSONObject((String)decodedLease):(JSONObject)decodedLease;
        check(completed.getString("id").equals(oldLease.optString("jobId"))&&oldLease.optString("nonce").length()>0,"Active renderer-gone lease lacked exact job/nonce identity: "+oldLease);
        JSONObject payload=new JSONObject(stalledBridge.readCompletedRestoreProjectChunk(completed.getString("id"),oldLease.getString("nonce"),completed.getString("projectId"),0,1024));
        check(payload.optBoolean("ok")&&payload.optLong("offset")==0&&payload.optLong("total")>0&&payload.optString("snapshot").matches("[0-9]+:[0-9a-f-]{36}")&&payload.optString("base64").length()>0,"Active lease could not read its bounded durable project payload: "+payload);
        JSONObject deniedPayload=new JSONObject(stalledBridge.readCompletedRestoreProjectChunk(completed.getString("id"),oldLease.getString("nonce")+"-stale",completed.getString("projectId"),0,1024));
        check(!deniedPayload.optBoolean("ok"),"A stale completed-restore nonce read durable project payload");
        JSONObject deniedJob=new JSONObject(stalledBridge.readCompletedRestoreProjectChunk(completed.getString("id")+"-stale",oldLease.getString("nonce"),completed.getString("projectId"),0,1024));
        check(!deniedJob.optBoolean("ok"),"A foreign completed job read durable project payload");
        JSONObject deniedProject=new JSONObject(stalledBridge.readCompletedRestoreProjectChunk(completed.getString("id"),oldLease.getString("nonce"),"foreign-project",0,1024));
        check(!deniedProject.optBoolean("ok"),"A foreign completed project read durable project payload");
        // Drop the one test probe callback after the real production
        // renderer-gone recovery is accepted. The readiness watchdog must
        // observe the replacement rather than treating callback loss as ready.
        awaitUiReady(()->check(owner.handlePreviewRenderProcessGone(stalled,false),"Active completed-restore renderer-gone branch rejected recovery"));
        check(lastUiReadiness!=null&&lastUiReadiness.optBoolean("completedRestoreRebound"),"UiReadiness did not rebind after the exact production completed-restore recovery");
        requireCompletedRestoreAck(completed,"Active renderer-gone replacement");
        // handlePreviewRenderProcessGone deliberately posts recovery so the
        // monitor can release its lock before the bridge transaction retires
        // this tuple. Do not race that post: first observe the committed
        // retirement (old instance marked terminating) or its completed
        // same-Activity replacement, then prove the stale bridge is denied.
        long retiredUntil=SystemClock.elapsedRealtime()+10000;
        boolean retired=false;
        while(SystemClock.elapsedRealtime()<retiredUntil){
            snapshot(false);int count=(Integer)field(owner,"completedRestoreRecoveryCount");
            WebView current=(WebView)field(owner,"web");WebView terminating=(WebView)field(owner,"completedRestoreTerminatingWebView");
            if(count==recoveryCountAtStart+1&&(terminating==stalled||current!=stalled)){retired=true;break;}
            SystemClock.sleep(50);
        }
        check(retired,"Active renderer-gone recovery did not commit old-bridge retirement before payload denial");
        JSONObject retiredPayload=new JSONObject(stalledBridge.readCompletedRestoreProjectChunk(completed.getString("id"),oldLease.getString("nonce"),completed.getString("projectId"),0,1024));
        check(!retiredPayload.optBoolean("ok"),"A retired WebView bridge read durable project payload after renderer-gone handoff");
        long until=SystemClock.elapsedRealtime()+30000;WebView replacement=null;
        while(SystemClock.elapsedRealtime()<until){
            snapshot(false);int count=(Integer)field(owner,"completedRestoreRecoveryCount");WebView current=(WebView)field(owner,"web");
            if(count==recoveryCountAtStart+1&&current!=null&&current!=stalled){replacement=current;break;}
            SystemClock.sleep(100);
        }
        check(replacement!=null,"Active completed-restore renderer-gone branch did not replace its WebView in the same Activity");
        check(activity==owner&&!owner.isDestroyed()&&!owner.isFinishing(),"Active renderer-gone recovery recreated or destroyed the Activity");
        check(!((Boolean)field(owner,"previewRecoveryPending"))&&field(owner,"previewRecoveryDialog")==null,"Active completed-restore renderer-gone recovery fell through to the ordinary preview dialog");
        check(!stalledBridge.completedRestoreTerminal(oldLease.getString("jobId"),oldLease.getString("nonce"),oldLease.optLong("sequence")+1,0),"Retired WebView bridge terminal proof was accepted after active renderer-gone retirement");
        check(!stalledBridge.completedRestoreAckCommitted(oldLease.getString("jobId"),oldLease.getString("nonce")),"Retired WebView bridge post-ACK confirmation was accepted after active renderer-gone retirement");
        String recovery=(String)field(owner,"completedRestoreLastRecovery");
        check(recovery!=null&&recovery.contains(completed.getString("id")+":renderer-gone"),"Active renderer-gone did not schedule the lease-specific recovery: "+recovery);
        String replacementPath=(String)field(owner,"completedRestoreReplacementPath");
        if(Build.VERSION.SDK_INT>=29)check(replacementPath!=null&&replacementPath.startsWith("terminate-requested->")&&(replacementPath.contains("render-process-gone")||replacementPath.contains("terminate-callback-budget")),"API 29+ active renderer-gone did not use terminate/onRenderProcessGone replacement: "+replacementPath);
        else check("direct-fallback".equals(replacementPath),"Pre-29 active renderer-gone did not use documented safe same-Activity replacement: "+replacementPath);
        String cap="completed-restore-recovery."+completed.getString("id");
        // The callback-loss readiness regression has already required the
        // replacement's terminal browser ACK, which correctly clears this cap.
        awaitUiReady();
        long replacementGeneration=(Long)field(owner,"previewGeneration"),acceptedGeneration=(Long)field(owner,"completedRestoreLastAcceptedBeginGeneration");
        check(acceptedGeneration==replacementGeneration&&completed.getString("id").equals((String)field(owner,"completedRestoreLastAcceptedBeginJobId")),"Active renderer-gone replacement did not open its own generation-bound lease");
        String ack=evaluate(replacement,"localStorage.getItem('lightforge-background-ack')||''","Active renderer-gone replacement did not report browser ACK");
        check(completed.getString("id").equals(new JSONTokener(ack).nextValue()),"Active renderer-gone replacement did not acknowledge the completed job");
        long visualAt=(Long)field(owner,"completedRestoreLastVisualFrameAt"),terminalAt=(Long)field(owner,"completedRestoreLastTerminalAt"),ackAt=(Long)field(owner,"completedRestoreLastAckConfirmationAt");
        check(visualAt>=faultAt&&terminalAt>=visualAt&&ackAt>=terminalAt,"Active renderer-gone lost visual → terminal → post-ACK ordering: visual="+visualAt+" terminal="+terminalAt+" ack="+ackAt+" fault="+faultAt);
        check(!owner.getPreferences(0).getBoolean(cap,false),"Active renderer-gone terminal ACK did not clear its own persisted cap");
        pass("A real active completed-restore renderer-gone branch queued one same-Activity replacement before its FIFO dialog fallback, rejected terminal and ACK calls from the retired bridge, rebound a generation-scoped lease, and preserved visible hardware-frame proof before terminal/browser ACK.");
    }
    private void completedRestoreCallbackStall(JSONObject completed)throws Exception{
        phase("completed-restore-callback-stall");
        MainActivity owner=activity;WebView stalled=(WebView)field(owner,"web");check(stalled!=null,"No WebView available for completed-restore stall injection");
        MainActivity.Bridge stalledBridge=bridge();
        int recoveryCountAtStart=(Integer)field(owner,"completedRestoreRecoveryCount");
        long faultAt=SystemClock.elapsedRealtime();
        String injected="(()=>{const a=window.LightForgeApp;if(!a||!window.ShowCompiler)throw Error('Studio compiler unavailable for test');localStorage.removeItem('lightforge-background-ack');a.state.backgroundSeen=null;const restore=window.ShowCompiler.restore;let stalledOnce=false;window.ShowCompiler.restore=function(){const result=restore.apply(this,arguments);if(!stalledOnce){stalledOnce=true;setTimeout(()=>{const until=performance.now()+12000;while(performance.now()<until){}},250);}return result;};window.onNativeEvent('analysisJob',JSON.parse("+JSONObject.quote(completed.toString())+"));return true;})()";
        check("true".equals(evaluate(stalled,injected,"Completed-restore fault injection did not arm")),"Completed-restore fault injection returned an unexpected result");
        long until=SystemClock.elapsedRealtime()+30000;WebView replacement=null;
        while(SystemClock.elapsedRealtime()<until){
            snapshot(false);int count=(Integer)field(owner,"completedRestoreRecoveryCount");WebView current=(WebView)field(owner,"web");
            if(count==recoveryCountAtStart+1&&current!=null&&current!=stalled){replacement=current;break;}
            SystemClock.sleep(100);
        }
        check(replacement!=null,"Completed restore callback stall did not replace its WebView in the same Activity");
        check(activity==owner&&!owner.isDestroyed()&&!owner.isFinishing(),"Completed restore recovery recreated or destroyed the Activity");
        check(!stalledBridge.beginCompletedRestore(completed.getString("id"),"retired-bridge-handoff",0),"A bridge bound to the stalled WebView opened a lease after same-Activity replacement began");
        String recovery=(String)field(owner,"completedRestoreLastRecovery");
        check(recovery!=null&&recovery.contains(completed.getString("id")+":callback-stall"),"Recovery was not caused by the bounded native callback lease: "+recovery);
        String replacementPath=(String)field(owner,"completedRestoreReplacementPath");
        if(Build.VERSION.SDK_INT>=29)check(replacementPath!=null&&replacementPath.startsWith("terminate-requested->")&&(replacementPath.contains("render-process-gone")||replacementPath.contains("terminate-callback-budget")),"API 29+ callback stall did not use the terminate/onRenderProcessGone replacement path: "+replacementPath);
        else check("direct-fallback".equals(replacementPath),"Pre-29 callback stall did not use the documented safe same-Activity replacement path: "+replacementPath);
        JSONObject durable=AnalysisJobStore.status(files);check("completed".equals(durable.optString("state"))&&completed.getString("id").equals(durable.optString("id")),"Native recovery mutated the durable completed job");
        String cap="completed-restore-recovery."+completed.getString("id");
        check(owner.getPreferences(0).getBoolean(cap,false),"One-replacement cap was not persisted before the replacement WebView booted");
        // This re-runs the original booted/model/visible-render/
        // postVisualStateCallback/hardware-frame predicate on the replacement
        // WebView. It also verifies the eventual idle state; ordering below is
        // proven from the production native visual → terminal → post-ACK
        // timestamps, not inferred from this post-sync readiness probe.
        awaitUiReady();
        long replacementGeneration=(Long)field(owner,"previewGeneration"),acceptedGeneration=(Long)field(owner,"completedRestoreLastAcceptedBeginGeneration");
        check(acceptedGeneration==replacementGeneration&&completed.getString("id").equals((String)field(owner,"completedRestoreLastAcceptedBeginJobId")),"The replacement WebView did not open its own generation-bound completed-restore lease");
        String ack=evaluate(replacement,"localStorage.getItem('lightforge-background-ack')||''","Replacement WebView did not report its browser ACK");
        check(completed.getString("id").equals(new JSONTokener(ack).nextValue()),"Replacement did not terminally acknowledge the completed job");
        long visualAt=(Long)field(owner,"completedRestoreLastVisualFrameAt"),terminalAt=(Long)field(owner,"completedRestoreLastTerminalAt"),ackAt=(Long)field(owner,"completedRestoreLastAckConfirmationAt");
        check(visualAt>=faultAt&&terminalAt>=visualAt&&ackAt>=terminalAt,"Strict visual/HW frame proof did not precede terminal and post-ACK confirmation: visual="+visualAt+" terminal="+terminalAt+" ack="+ackAt+" fault="+faultAt);
        check(!owner.getPreferences(0).getBoolean(cap,false),"Terminal proof did not disarm the persisted replacement cap");
        pass("A test-only real restore callback stall kept the completed job pending, rejected the retired WebView bridge, admitted the replacement generation's lease, caused exactly one same-Activity WebView replacement, and recorded the unchanged visible model, post-visual-state and hardware-frame proof before terminal and the browser's post-ACK cap confirmation.");
    }
    private JSONObject start(String projectId)throws Exception{
        JSONObject job=new JSONObject(bridge().startAnalysis(projectId));check(!job.has("error"),job.toString());waitService(true);
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
    private void observeBalanced(NativeMdxTask task){
        // Start before Activity teardown/Doze: those transitions may span an
        // entire short inference. Successful-pass counters survive idle
        // release, so completion evidence does not depend on catching a
        // transient output file or native RunOptions pointer between polls.
        balancedObserverStopped=false;checkedBalancedStageRelease=false;observedBalancedNativeRun=false;
        balancedObservationFailure=null;balancedPassesAtRelease=0;
        balancedObserver=new Thread(()->{
            try{
                while(!balancedObserverStopped){
                    JSONObject job=AnalysisJobStore.status(files);
                    if(job!=null&&!AnalysisJobStore.active(job))return;
                    synchronized(task){
                        if(field(task,"session")!=null&&field(task,"activeRun")!=null)observedBalancedNativeRun=true;
                        double progress=job==null?0:job.optDouble("progress");
                        if(job!=null&&AnalysisJobStore.active(job)&&progress>=.96*.83&&progress<.96){
                            check(field(task,"session")==null&&field(task,"inputBuffer")==null&&field(task,"outputBuffer")==null
                                &&field(task,"activeRun")==null&&!(Boolean)field(task,"workerActive"),
                                "Balanced MDX retained its model or tensor buffers during voice/GAME analysis");
                            balancedPassesAtRelease=(Integer)field(task,"completedPasses");
                            check(balancedPassesAtRelease==2,"Balanced polarity ensemble did not complete exactly two native inferences before voice/GAME: "+balancedPassesAtRelease);
                            checkedBalancedStageRelease=true;
                        }
                    }
                    Thread.sleep(25);
                }
            }catch(InterruptedException stopped){Thread.currentThread().interrupt();}
            catch(Throwable error){balancedObservationFailure=error;}
        },"LightForge-balanced-observer");
        balancedObserver.setDaemon(true);balancedObserver.start();
    }
    private void stopBalancedObserver()throws Exception{
        balancedObserverStopped=true;
        if(balancedObserver!=null){balancedObserver.interrupt();balancedObserver.join(5000);check(!balancedObserver.isAlive(),"Balanced observation thread did not stop");}
        if(balancedObservationFailure!=null)throw new AssertionError("Balanced live lifecycle observation failed",balancedObservationFailure);
    }
    private JSONObject balancedScreenOff()throws Exception{
        phase("balanced-screen-off-analysis");String id=fixture("Balanced background audio",3,"balanced");JSONObject job=start(id);
        AnalysisService owner=service();NativeMdxTask task=(NativeMdxTask)field(owner,"nativeMdx");
        JSONObject frozen=AnalysisJobStore.request(files,job.getString("id"));
        check("balanced".equals(frozen.getJSONObject("settings").getString("analysisQuality")),"Balanced fixture was not frozen into the analysis request");
        check(!AnalysisJobStore.status(files).has("settings"),"Routing fixture unexpectedly exposes settings in its notification-only status");
        check(task!=null,"Frozen Balanced request did not allocate the native MDX accelerator");
        observeBalanced(task);long backgroundAt=System.currentTimeMillis();backgroundAndDoze();
        JSONObject completed=waitTerminal(10*60*1000L);
        check("completed".equals(completed.optString("state")),"Balanced screen-off analysis failed: "+completed);
        check(completed.getLong("updatedAt")>backgroundAt,"Balanced analysis made no progress after Activity destruction");
        waitService(false);stopBalancedObserver();
        java.util.concurrent.ExecutorService executor=(java.util.concurrent.ExecutorService)field(task,"executor");
        check(executor.awaitTermination(15,java.util.concurrent.TimeUnit.SECONDS),"Completed Balanced executor did not retire promptly");
        check(field(owner,"nativeMdx")==null&&(Boolean)field(task,"closed"),"Completed service retained its native Balanced task");
        check(checkedBalancedStageRelease,"No live voice/GAME-stage Balanced model and tensor release observation was recorded");
        check((Integer)field(task,"completedPasses")==2,"Balanced fixture did not complete both model passes on Android");
        JSONObject saved=AnalysisJobStore.read(new File(AnalysisJobStore.project(files,id),"project.json"),ProjectStore.MAX_PROJECT_BYTES);
        JSONObject music=saved.getJSONObject("music"),engine=music.getJSONObject("engine"),separation=engine.getJSONObject("separationModel");
        check(engine.optBoolean("neural"),"Balanced fixture did not complete the actual neural pipeline");checkCanonicalSemanticAnalysis(music,frozen.getDouble("duration"),"Balanced fixture");
        check("balanced".equals(engine.optString("quality")),"Balanced quality was silently changed");
        check("uvr-mdx-net-voc-ft".equals(separation.optString("modelId")),"Balanced fixture used the wrong separator");
        check(separation.optBoolean("denoise")&&separation.optInt("modelPasses")==2&&separation.optInt("chunks")==1,
            "Balanced fixture lost the two-pass polarity ensemble or recomputed through fallback: "+separation);
        JSONObject stems=music.getJSONObject("stemCache");
        check(stems.getInt("fullSamples")==3*44100&&stems.getInt("samples")==3*22050&&stems.getInt("sampleRate")==22050,
            "Balanced separation truncated or extended the source/stem sample clock");
        check(Math.abs(stems.getDouble("duration")-3)<1e-9&&Math.abs(music.getDouble("duration")-3)<1e-9,"Balanced source duration changed");
        check(music.getJSONObject("vocals").getJSONObject("transcription").getInt("steps")==8,"Balanced transcription reduced its eight-step estimator");
        JSONObject compiled=saved.getJSONObject("compiled");
        check(compiled.getString("sha256").matches("[a-f0-9]{64}"),"Balanced show did not compile and save");
        check(compiled.getInt("frameCount")==150&&compiled.getInt("stepMs")==20&&Math.abs(compiled.getJSONObject("meta").getDouble("audioDuration")-3)<1e-9,
            "Balanced compiled choreography lost the three-second source clock");
        JSONObject observation=new JSONObject().put("completedNativePasses",(Integer)field(task,"completedPasses"))
            .put("nativePassesBeforeVoice",balancedPassesAtRelease).put("liveNativeRunObserved",observedBalancedNativeRun)
            .put("modelReleasedDuringVoice",checkedBalancedStageRelease).put("sourceSamples",stems.getInt("fullSamples"))
            .put("stemSamples",stems.getInt("samples")).put("separation",separation);
        pass("Frozen Balanced request allocated native MDX and completed both polarity-ensemble passes on Android. The complete show finished with the Activity destroyed and screen off under Doze; model/tensor buffers were released before voice/GAME, preserving 132300 source samples, 66150 stem samples, the eight-step transcription setting and 150 saved choreography frames.");
        return observation;
    }
    @Override public void onCreate(Bundle arguments){super.onCreate(arguments);start();}
    @Override public void onStart(){
        JSONObject receipt=new JSONObject();Bundle output=new Bundle();
        try{
            files=getTargetContext().getFilesDir();startMainWatchdog();phase("completed-restore-monitor-contract");completedRestoreMonitorContract();phase("first-screen-off-analysis");launch();String id=fixture("Background audio");JSONObject job=start(id);double sourceDuration=AnalysisJobStore.request(files,job.getString("id")).getDouble("duration");
            check(field(service(),"nativeMdx")==null,"Precision Studio allocated the Balanced-only accelerator");
            long backgroundAt=System.currentTimeMillis();backgroundAndDoze();
            JSONObject completed=waitTerminal(15*60*1000L);
            check("completed".equals(completed.optString("state")),"Screen-off analysis failed: "+completed);
            check(completed.getLong("updatedAt")>backgroundAt,"No progress after Activity destruction");waitService(false);
            JSONObject saved=AnalysisJobStore.read(new File(AnalysisJobStore.project(files,id),"project.json"),ProjectStore.MAX_PROJECT_BYTES);
            checkCanonicalSemanticAnalysis(saved.getJSONObject("music"),sourceDuration,"Actual analysis");
            check(saved.getJSONObject("music").getJSONObject("engine").optBoolean("neural"),"Neural analysis did not run");
            check(saved.getJSONObject("compiled").getString("sha256").matches("[a-f0-9]{64}"),"Compiled frames missing");
            check(separation(saved).optInt("chunks")==1,"Short Studio fixture did not execute exactly one native passage");
            check(checkedNativeStageRelease,"No live voice/GAME-stage native-buffer release observation was recorded");
            pass("Actual Studio native CPU separation, neural analysis and choreography completed with the Activity destroyed, screen off and Doze forced with user-equivalent battery exemption; result was durably saved.");
            phase("reconnect-completed-project");foreground();
            requireCompletedRestoreAck(completed,"Reopened Activity");
            JSONObject bootstrap=new JSONObject(bridge().getBootstrap());
            check("completed".equals(bootstrap.getJSONObject("backgroundJob").getString("state")),"Reopened Activity did not reconnect");
            pass("Reopened Activity reports the completed job and its saved project.");
            completedRestorePayloadBypassesProjectFetch(completed);
            completedRestoreActiveRendererGone(completed);
            completedRestoreCallbackStall(completed);
            receipt.put("balanced",balancedScreenOff());phase("reopen-after-balanced");foreground();
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
            receipt.put("passed",true).put("checks",checks).put("uiReadiness",uiReadinessChecks).put("sdk",Build.VERSION.SDK_INT).put("scope","Android emulator with initialized hardware-accelerated WebView and committed visible frames before lifecycle actions, actual foreground service, native CPU Studio separation and two-pass Balanced MDX, frozen-request routing and live model/tensor release before WebView/WASM voice/GAME, screen-off/Doze execution, live native cancellation, partial-passage resume and timeout callback; not a physical phone or Tesla.");
            output.putString("stream","BACKGROUND_ANDROID_PASS\n"+receipt.toString()+"\n");finish(Activity.RESULT_OK,output);
        }catch(Throwable error){
            try{snapshot(true);}catch(Exception ignored){}
            emitFailureDiagnostics();
            try{receipt.put("passed",false).put("checks",checks).put("phase",currentPhase).put("error",error.toString());}catch(Exception ignored){}
            StringWriter trace=new StringWriter();error.printStackTrace(new PrintWriter(trace));output.putString("stream","BACKGROUND_ANDROID_FAIL\n"+receipt+"\n"+trace);finish(Activity.RESULT_CANCELED,output);
        }finally{balancedObserverStopped=true;if(balancedObserver!=null)balancedObserver.interrupt();stopMainWatchdog();}
    }
}
