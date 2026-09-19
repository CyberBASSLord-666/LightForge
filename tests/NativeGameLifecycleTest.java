package com.cyberbasslord.lightforge;

import android.content.Context;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.lang.reflect.Field;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Base64;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;

/** Production task/guard/executor tests with a controlled model boundary, not inference evidence. */
public final class NativeGameLifecycleTest {
    private static final String JOB="12345678-1234-1234-1234-123456789abc",OTHER="22345678-1234-1234-1234-123456789abc";
    private static int checks;
    private static File root;
    private interface Checked {void run()throws Exception;}
    public static void main(String[] args)throws Exception {
        root=new File(args[0]);root.mkdirs();
        if(args.length==2){fatalRetirement("throw".equals(args[1]));System.out.println("PASS: native retirement failure blocks fallback until process restart");return;}
        ownershipAndBounds();invalidPcm();invalidNotes();successfulFreshPassages();stalledConstruction();failedConstruction();
        cancelRunning();terminalWaitsForRetirement();cancelDuringRetirement();sharedGate();closeQueued();queueRejection();closeUploading();symlinkStorage();
        System.out.println("PASS: "+checks+" production NativeGameTask lifecycle checks");
    }
    private static NativeGameTask task(String name)throws Exception {return new NativeGameTask(new Context(new File(root,name),new File(root,"assets")),JOB);}
    private static Object field(Object target,String name)throws Exception {Field value=target.getClass().getDeclaredField(name);value.setAccessible(true);return value.get(target);}
    private static NativeRuntimeGuard guard(NativeGameTask task)throws Exception {return (NativeRuntimeGuard)field(task,"runtimeGuard");}
    private static ExecutorService executor(NativeGameTask task)throws Exception {return (ExecutorService)field(task,"executor");}
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);checks++;}
    private static void rejected(Checked action,String message)throws Exception {try{action.run();throw new AssertionError(message);}catch(IOException expected){checks++;}}
    private static void prompt(Checked action,String message)throws Exception {
        ExecutorService executor=Executors.newSingleThreadExecutor();
        try{executor.submit(()->{try{action.run();}catch(Exception error){throw new RuntimeException(error);}}).get(1,TimeUnit.SECONDS);checks++;}
        catch(TimeoutException error){throw new AssertionError(message,error);}finally{executor.shutdownNow();}
    }
    private static void leaseBoundaries(NativeGameTask task){
        NativeGame.beforeConstruct=()->{try{require(guard(task).state()!=null,"durable lease precedes engine/library construction");require(NativeDeux.INFERENCE_GATE.availablePermits()==0,"engine construction owns shared gate");}catch(Exception error){throw new AssertionError(error);}};
        NativeGame.beforeClose=()->{try{require(guard(task).state()!=null,"native destruction retains crash lease");require(NativeDeux.INFERENCE_GATE.availablePermits()==0,"native destruction retains shared gate");}catch(Exception error){throw new AssertionError(error);}};
    }
    private static String upload(NativeGameTask task,int samples)throws Exception {
        String token=new JSONObject(task.begin(JOB,samples*4L,0,0xffffffffL)).getString("token");
        byte[] bytes=new byte[samples*4];
        for(int first=0;first<bytes.length;first+=65536){int size=Math.min(65536,bytes.length-first);task.append(JOB,token,Base64.getEncoder().encodeToString(java.util.Arrays.copyOfRange(bytes,first,first+size)));}
        return token;
    }
    private static String start(NativeGameTask task)throws Exception {String token=upload(task,4410);task.run(JOB,token);return token;}
    private static JSONObject terminal(NativeGameTask task,String token,String expected)throws Exception {
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(10);
        while(System.nanoTime()<deadline){JSONObject state=new JSONObject(task.status(JOB,token));if(!"running".equals(state.getString("state"))){require(expected.equals(state.getString("state")),"expected "+expected+", got "+state);return state;}require(!state.has("notes"),"running status never exposes partial notes");Thread.sleep(5);}
        throw new AssertionError("Task did not publish terminal status");
    }
    private static void stopped(NativeGameTask task)throws Exception {
        task.close();require(executor(task).awaitTermination(10,TimeUnit.SECONDS),"executor retires");require(task.isRetired(),"retirement includes executor cleanup");
        require(guard(task).state()==null,"retired task has no crash lease");require(field(task,"engine")==null,"retired task has no engine");
        require(!((File)field(task,"jobDirectory")).exists(),"retired task has no passage storage");
        require(NativeGame.live.get()==0&&!NativeGame.closedDuringRun,"native resources retire without closing an active run");
        require(NativeDeux.INFERENCE_GATE.availablePermits()==1,"exactly one process gate permit survives");
        require(NativeGameTask.runtimeRetirementConfirmed(),"ordinary retirement releases process-wide admission");
    }
    private static void ownershipAndBounds()throws Exception {
        NativeGame.reset();NativeGameTask task=task("bounds");
        try{
            require(new JSONObject(task.availability(JOB)).getBoolean("available"),"availability works without model loading");
            require(NativeGame.constructed.get()==0,"availability does not construct native engine");
            rejected(()->task.availability(OTHER),"another owner obtained availability");
            for(long bytes:new long[]{0,1,3,5,NativeGameTask.MAX_INPUT_BYTES+4})rejected(()->task.begin(JOB,bytes,0,2025),"invalid geometry accepted");
            rejected(()->task.begin(JOB,4,-1,2025),"invalid language accepted");rejected(()->task.begin(JOB,4,5,2025),"invalid language accepted");
            rejected(()->task.begin(JOB,4,0,-1),"negative seed accepted");rejected(()->task.begin(JOB,4,0,0x100000000L),"oversized seed accepted");
            String token=new JSONObject(task.begin(JOB,8,4,0xffffffffL)).getString("token");
            rejected(()->task.begin(JOB,4,0,0),"parallel upload accepted");
            rejected(()->task.append(OTHER,token,"AAAAAA=="),"another owner appended");rejected(()->task.append(JOB,"wrong","AAAAAA=="),"stale token appended");
            rejected(()->task.append(JOB,token,""),"empty chunk accepted");rejected(()->task.append(JOB,token,"not base64!"),"invalid chunk accepted");
            rejected(()->task.append(JOB,token,Base64.getEncoder().encodeToString(new byte[65537])),"oversized chunk accepted");
            rejected(()->task.run(JOB,token),"incomplete input ran");
            task.append(JOB,token,"AAAAAA==");rejected(()->task.run(JOB,token),"partial input ran");
            task.cancel(OTHER,token);task.cancel(JOB,"wrong");require("uploading".equals(new JSONObject(task.status(JOB,token)).getString("state")),"stale cancellation is fenced");
            task.cancel(JOB,token);require(!new JSONObject(task.status(JOB,token)).has("notes"),"cancelled upload has no notes");
            task.releaseIdle(JOB);rejected(()->task.status(JOB,token),"released token retained authority");
            String maximum=new JSONObject(task.begin(JOB,NativeGameTask.MAX_INPUT_BYTES,0,0)).getString("token");task.cancel(JOB,maximum);
        }finally{stopped(task);}
    }
    private static void invalidPcm()throws Exception {
        NativeGame.reset();NativeGameTask task=task("invalid-pcm");
        try{String token=new JSONObject(task.begin(JOB,4,0,2025)).getString("token");byte[] raw=ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putFloat(Float.NaN).array();task.append(JOB,token,Base64.getEncoder().encodeToString(raw));task.run(JOB,token);
            JSONObject state=terminal(task,token,"failed");require(!state.has("notes"),"nonfinite PCM never exposes notes");require(NativeGame.constructed.get()==0,"nonfinite PCM fails before native loading");require(field(task,"input")==null,"invalid PCM is removed");
        }finally{stopped(task);}
    }
    private static void invalidNotes()throws Exception {
        NativeGame.reset();NativeGame.invalidNotes=true;NativeGameTask task=task("invalid-notes");leaseBoundaries(task);
        try{String token=start(task);JSONObject state=terminal(task,token,"failed");require(!state.has("notes"),"invalid result never leaks notes");require(NativeGame.closed.get()==1,"invalid-result engine is retired");}
        finally{stopped(task);}
    }
    private static void successfulFreshPassages()throws Exception {
        NativeGame.reset();NativeGameTask task=task("success");leaseBoundaries(task);
        try{
            String first=start(task);JSONObject state=terminal(task,first,"completed");
            require(state.getJSONArray("notes").length()==1,"complete unrounded notes are returned inline");require(state.getJSONArray("notes").getJSONObject(0).getDouble("midi")==60.123456789,"pitch is never rounded");
            require(state.getLong("seed")==0xffffffffL&&state.getLong("samples")==4410,"input settings are bound to completion");
            require(guard(task).state()==null&&NativeGame.live.get()==0&&NativeDeux.INFERENCE_GATE.availablePermits()==1,"completion follows native and lease/gate retirement");
            require(field(task,"input")==null,"successful PCM is removed before completion");
            task.cancel(JOB,first);require("completed".equals(new JSONObject(task.status(JOB,first)).getString("state")),"late cancellation cannot rewrite completed evidence");
            task.releaseIdle(JOB);String second=start(task);terminal(task,second,"completed");
            rejected(()->task.status(JOB,first),"old passage status survived replacement");
            require(NativeGame.constructed.get()==2&&NativeGame.closed.get()==2,"every passage owns a fresh retired engine");
            require(new JSONObject(task.status(JOB,second)).getInt("completedPasses")==2,"completed count survives idle release");
        }finally{stopped(task);}
    }
    private static void stalledConstruction()throws Exception {
        NativeGame.reset();NativeGame.blockCreate=true;NativeGameTask task=task("construct");leaseBoundaries(task);String token=start(task);
        try{require(NativeGame.createEntered.await(5,TimeUnit.SECONDS),"engine construction entered");prompt(()->task.status(JOB,token),"status blocked on native construction");prompt(()->task.cancel(JOB,token),"cancel blocked on native construction");prompt(task::close,"shutdown blocked on native construction");require(!task.isRetired(),"constructing engine is not retired");}
        finally{NativeGame.createAllowed.countDown();stopped(task);}
        require(NativeGame.runs.get()==0&&NativeGame.closed.get()==1,"cancelled constructor is retired without inference");
    }
    private static void failedConstruction()throws Exception {
        NativeGame.reset();NativeGame.failCreate=true;NativeGameTask task=task("failed-construction");leaseBoundaries(task);
        try{String token=start(task);terminal(task,token,"failed");require(guard(task).state()==null,"failed constructor clears lease");}
        finally{stopped(task);}
    }
    private static void cancelRunning()throws Exception {
        NativeGame.reset();NativeGame.blockRun=true;NativeGameTask task=task("cancel-run");leaseBoundaries(task);String token=start(task);
        try{require(NativeGame.runEntered.await(5,TimeUnit.SECONDS),"native execution entered");prompt(()->task.cancel(JOB,token),"active cancellation blocked");JSONObject state=terminal(task,token,"cancelled");require(!state.has("notes")&&state.getInt("completedPasses")==0,"cancelled pass has no completed result");require(NativeGame.cancellations.get()>0,"active native execution is terminated");}
        finally{NativeGame.runAllowed.countDown();stopped(task);}
    }
    private static void terminalWaitsForRetirement()throws Exception {
        NativeGame.reset();NativeGame.blockClose=true;NativeGameTask task=task("retirement");leaseBoundaries(task);String token=start(task);
        try{require(NativeGame.closeEntered.await(5,TimeUnit.SECONDS),"native destruction entered");JSONObject state=new JSONObject(task.status(JOB,token));require("running".equals(state.getString("state"))&&!state.has("notes"),"prepared notes stay private during retirement");
            require(guard(task).state()!=null&&NativeDeux.INFERENCE_GATE.availablePermits()==0,"blocked destructor retains lease and gate");
            require(!NativeGameTask.runtimeRetirementConfirmed(),"a replacement service cannot start WASM while native destruction is pending");
            rejected(()->task.releaseIdle(JOB),"release overlapped retirement");rejected(()->task.begin(JOB,4,0,0),"replacement overlapped retirement");
            NativeGame.closeAllowed.countDown();terminal(task,token,"completed");
        }finally{NativeGame.closeAllowed.countDown();stopped(task);}
    }
    private static void cancelDuringRetirement()throws Exception {
        NativeGame.reset();NativeGame.blockClose=true;NativeGameTask task=task("cancel-retirement");leaseBoundaries(task);String token=start(task);
        try{require(NativeGame.closeEntered.await(5,TimeUnit.SECONDS),"cancel test reaches destruction");prompt(()->task.cancel(JOB,token),"cancellation blocks on destruction");NativeGame.closeAllowed.countDown();JSONObject state=terminal(task,token,"cancelled");require(!state.has("notes"),"late cancellation discards prepared notes");}
        finally{NativeGame.closeAllowed.countDown();stopped(task);}
    }
    private static void sharedGate()throws Exception {
        NativeGame.reset();NativeDeux.INFERENCE_GATE.acquire();NativeGameTask task=task("gate");String token=start(task);
        try{require(!NativeGame.createEntered.await(350,TimeUnit.MILLISECONDS),"waiting GAME task cannot load an engine");require(guard(task).state()==null,"gate waiter cannot overwrite another native lease");prompt(()->task.cancel(JOB,token),"gate-wait cancellation blocks");}
        finally{NativeDeux.INFERENCE_GATE.release();}
        try{terminal(task,token,"cancelled");require(NativeGame.constructed.get()==0,"cancelled waiter never constructs native engine");}finally{stopped(task);}
    }
    private static void closeQueued()throws Exception {
        NativeGame.reset();NativeGameTask task=task("queued");CountDownLatch entered=new CountDownLatch(1),allowed=new CountDownLatch(1);
        executor(task).execute(()->{entered.countDown();NativeGame.await(allowed);});require(entered.await(5,TimeUnit.SECONDS),"queued-work barrier entered");start(task);
        try{require(!NativeGameTask.runtimeRetirementConfirmed(),"queued native worker fences replacement service admission");prompt(task::close,"queued shutdown blocks");require(!task.isRetired(),"queued cleanup is not already retired");}
        finally{allowed.countDown();stopped(task);}
        require(NativeGame.constructed.get()==0,"closed queued task never initializes native runtime");
    }
    private static void closeUploading()throws Exception {
        NativeGame.reset();NativeGameTask task=task("upload-close");task.begin(JOB,4,0,0);stopped(task);task.close();
        require(NativeGame.constructed.get()==0,"closing upload does not allocate native engine");
        rejected(()->task.begin(JOB,4,0,0),"closed task accepted input");
    }
    private static void queueRejection()throws Exception {
        NativeGame.reset();NativeGameTask task=task("rejected-queue");ExecutorService rejected=executor(task);rejected.shutdown();String token=upload(task,4410);
        try {
            try{task.run(JOB,token);throw new AssertionError("Rejected executor accepted work");}catch(RejectedExecutionException expected){checks++;}
            require(NativeGameTask.runtimeRetirementConfirmed(),"failed queue submission releases its process-wide reservation");
            require("failed".equals(new JSONObject(task.status(JOB,token)).getString("state")),"rejected queue exposes no active or completed work");
            require(!((Boolean)field(task,"workerActive"))&&field(task,"input")==null,"rejected queue drops only unowned PCM and worker state");
            require(NativeGame.constructed.get()==0&&guard(task).state()==null,"rejected queue never touches native resources");
        } finally {
            // Replace only the test-controlled stopped executor so ordinary
            // asynchronous close can exercise its normal storage cleanup path.
            Field slot=NativeGameTask.class.getDeclaredField("executor");slot.setAccessible(true);slot.set(task,Executors.newSingleThreadExecutor());stopped(task);
        }
    }
    private static void symlinkStorage()throws Exception {
        File outside=new File(root,"outside"),contextRoot=new File(root,"symlink-root");outside.mkdirs();
        Context context=new Context(contextRoot,new File(root,"assets"));
        java.nio.file.Files.createSymbolicLink(new File(context.getCacheDir(),"native-game-passages").toPath(),outside.toPath());
        rejected(()->new NativeGameTask(context,JOB),"symlinked passage root accepted");require(outside.list().length==0,"symlink target was not touched");
        Context jobContext=new Context(new File(root,"symlink-job"),new File(root,"assets"));File cacheRoot=new File(jobContext.getCacheDir(),"native-game-passages");cacheRoot.mkdir();
        java.nio.file.Files.createSymbolicLink(new File(cacheRoot,JOB).toPath(),outside.toPath());
        rejected(()->new NativeGameTask(jobContext,JOB),"symlinked job directory accepted");require(outside.list().length==0,"job symlink target was not touched");
        rejected(()->new NativeGameTask(new Context(new File(root,"invalid-owner"),outside),"------------------------------------"),"non-UUID owner accepted");
    }
    private static void fatalRetirement(boolean throwFromClose)throws Exception {
        NativeGame.reset();NativeGame.failClose=throwFromClose;NativeGame.unconfirmedClose=!throwFromClose;
        NativeGameTask task=task("fatal-retirement");leaseBoundaries(task);String token=start(task);
        JSONObject state=terminal(task,token,"retirement-failed");
        require(!state.has("notes")&&state.getInt("completedPasses")==0,"failed destructor never publishes completed notes");
        require(guard(task).state()!=null&&NativeDeux.INFERENCE_GATE.availablePermits()==0,"unknown native retirement retains durable lease and process gate");
        require(!NativeGameTask.runtimeRetirementConfirmed(),"unknown native handles poison process-wide admission");
        require(field(task,"engine")!=null&&NativeGame.live.get()==1,"unknown engine ownership is not discarded");
        rejected(()->task.releaseIdle(JOB),"unknown retirement allowed fallback release");
        rejected(()->task.begin(JOB,4,0,0),"unknown retirement allowed another passage");
        rejected(()->task.availability(JOB),"unknown retirement advertised availability");
        task.cancel(JOB,token);require("retirement-failed".equals(new JSONObject(task.status(JOB,token)).getString("state")),"late cancellation cannot hide unknown retirement");
        prompt(task::close,"closing an unconfirmed engine blocked");
        require(executor(task).awaitTermination(5,TimeUnit.SECONDS),"fatal worker executor finishes without losing native ownership fence");
        require(!task.isRetired(),"executor termination is not native retirement proof");
        require(guard(task).state()!=null&&NativeDeux.INFERENCE_GATE.availablePermits()==0,"shutdown cannot erase unknown native lease/gate");
        NativeGameTask replacement=task("replacement-after-fatal");
        try{rejected(()->replacement.begin(JOB,4,0,0),"replacement task bypassed process poison");rejected(()->replacement.availability(JOB),"replacement availability bypassed process poison");}
        finally{replacement.close();require(executor(replacement).awaitTermination(5,TimeUnit.SECONDS),"unused replacement executor retires");}
    }
}

/** Only the model boundary is replaced; task, guard, ownership and executor are production code. */
final class NativeGame implements AutoCloseable {
    static final String MODEL_ID="game-large-1.0.3-lightforge-1";
    interface Listener {void update(double progress,String message);}
    interface Cancellation {boolean cancelled();}
    static final AtomicInteger constructed=new AtomicInteger(),runs=new AtomicInteger(),closed=new AtomicInteger(),live=new AtomicInteger(),cancellations=new AtomicInteger();
    static volatile boolean blockCreate,failCreate,blockRun,blockClose,failClose,unconfirmedClose,invalidNotes,closedDuringRun;
    static volatile Runnable beforeConstruct,beforeClose;
    static CountDownLatch createEntered,createAllowed,runEntered,runAllowed,closeEntered,closeAllowed;
    private volatile boolean cancelled,running;
    private boolean retired;
    NativeGame(Context context)throws Exception {
        if(beforeConstruct!=null)beforeConstruct.run();constructed.incrementAndGet();createEntered.countDown();
        if(blockCreate)await(createAllowed);if(failCreate)throw new IOException("Controlled creation failure");live.incrementAndGet();
    }
    static void reset(){
        if(live.get()!=0||NativeDeux.INFERENCE_GATE.availablePermits()!=1)throw new AssertionError("Previous native boundary leaked");
        constructed.set(0);runs.set(0);closed.set(0);cancellations.set(0);blockCreate=failCreate=blockRun=blockClose=failClose=unconfirmedClose=invalidNotes=closedDuringRun=false;
        beforeConstruct=beforeClose=null;createEntered=new CountDownLatch(1);createAllowed=new CountDownLatch(1);runEntered=new CountDownLatch(1);runAllowed=new CountDownLatch(1);closeEntered=new CountDownLatch(1);closeAllowed=new CountDownLatch(1);
    }
    static void await(CountDownLatch latch){try{if(!latch.await(10,TimeUnit.SECONDS))throw new AssertionError("Controlled native boundary timed out");}catch(InterruptedException error){Thread.currentThread().interrupt();throw new AssertionError(error);}}
    JSONArray predict(float[] pcm,int language,long seed,Listener listener,Cancellation cancellation)throws Exception {
        running=true;runs.incrementAndGet();runEntered.countDown();
        try{while(blockRun&&!runAllowed.await(10,TimeUnit.MILLISECONDS)){if(cancelled||cancellation.cancelled())throw new InterruptedIOException("Controlled cancellation");}
            if(cancelled||cancellation.cancelled())throw new InterruptedIOException("Controlled cancellation");
            listener.update(.5,"Do not expose model text");
            return new JSONArray().put(new JSONObject().put("start",0).put("end",invalidNotes?17:.08).put("midi",60.123456789));
        }finally{running=false;}
    }
    void cancel(){cancelled=true;cancellations.incrementAndGet();}
    @Override public void close(){
        if(running)closedDuringRun=true;if(beforeClose!=null)beforeClose.run();closeEntered.countDown();if(blockClose)await(closeAllowed);
        if(failClose)throw new IllegalStateException("Controlled native destructor failure");
        if(unconfirmedClose)return;
        synchronized(this){if(!retired){retired=true;closed.incrementAndGet();live.decrementAndGet();}}
    }
    boolean isRetired(){return retired&&!running;}
}
