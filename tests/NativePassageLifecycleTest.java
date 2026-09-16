package com.cyberbasslord.lightforge;

import android.content.Context;
import java.io.*;
import java.lang.reflect.Field;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.json.JSONObject;

/** Real task/executor/storage lifecycle with a controlled native boundary; no inference claim. */
public final class NativePassageLifecycleTest {
    private static final String JOB="12345678-1234-1234-1234-123456789abc";
    private static int checks;
    private static File root;
    public static void main(String[] args)throws Exception{
        root=new File(args[0]);root.mkdirs();
        closeBeforeStart();closeQueuedStart();closeRunningAndReplace();
        System.out.println("PASS: "+checks+" production NativePassageTask lifecycle checks");
    }
    private static Context context(String name){return new Context(new File(root,name),new File(root,"assets"));}
    private static NativePassageTask task(Context context)throws Exception{return new NativePassageTask(context,new File(root,"audio.wav"),JOB);}
    private static Object field(Object target,String name)throws Exception{Field field=target.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(target);}
    private static ExecutorService executor(NativePassageTask task)throws Exception{return (ExecutorService)field(task,"executor");}
    private static File directory(NativePassageTask task)throws Exception{return (File)field(task,"directory");}
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);checks++;}
    private static void retired(NativePassageTask task)throws Exception{
        require(executor(task).awaitTermination(5,TimeUnit.SECONDS),"executor did not finish cleanup");
        require(task.isRetired(),"finished closed task is not retired");
        require(field(task,"engine")==null,"retired task retained its native engine");
        require(!directory(task).exists(),"retired task retained passage storage");
        require(((NativeRuntimeGuard)field(task,"runtimeGuard")).state()==null,"retired task retained execution lease");
    }
    private static void closeBeforeStart()throws Exception{
        NativeDeux.reset();NativePassageTask task=task(context("before-start"));
        try{
            task.close();task.close();retired(task);
            try{task.start(0);throw new AssertionError("closed task accepted a start");}catch(IOException expected){checks++;}
            require(NativeDeux.constructed.get()==0,"close-before-start allocated native resources");
        }finally{task.close();}
    }
    private static void closeQueuedStart()throws Exception{
        NativeDeux.reset();NativePassageTask task=task(context("queued-start"));
        CountDownLatch occupied=new CountDownLatch(1),release=new CountDownLatch(1);
        executor(task).execute(()->{occupied.countDown();NativeDeux.await(release);});
        require(occupied.await(5,TimeUnit.SECONDS),"executor barrier did not start");
        String token=new JSONObject(task.start(0)).getString("token");
        try{
            task.close();require(!task.isRetired(),"queued cleanup was reported retired before executor returned");
            require(NativeDeux.constructed.get()==0,"queued close allocated a native model");
        }finally{release.countDown();task.close();}
        retired(task);
        require("cancelled".equals(new JSONObject(task.status(token)).getString("state")),"queued start lost its cancellation/finally owner");
        require(NativeDeux.constructed.get()==0&&NativeDeux.runs.get()==0,"closed queued work reached native inference");
    }
    private static void closeRunningAndReplace()throws Exception{
        NativeDeux.reset();NativeDeux.blockRetirement=true;
        Context context=context("active-start");NativePassageTask task=task(context);
        task.start(0);
        try{
            require(NativeDeux.runEntered.await(5,TimeUnit.SECONDS),"native boundary did not start");
            require(((NativeRuntimeGuard)field(task,"runtimeGuard")).state()!=null,"active native work lacks execution lease");
            long before=System.nanoTime();task.close();
            require(System.nanoTime()-before<TimeUnit.SECONDS.toNanos(1),"close waited for active native retirement");
            require(!task.isRetired(),"active native work was reported retired");
            NativeDeux.runAllowed.countDown();
            require(NativeDeux.retirementEntered.await(5,TimeUnit.SECONDS),"worker cleanup did not begin");
            require(NativeDeux.INFERENCE_GATE.availablePermits()==1,"native prediction did not release its gate");
            require(!task.isRetired(),"gate release was mistaken for completed resource/file cleanup");
            require(((File)field(task,"output")).exists(),"controlled cleanup boundary was not exercised");
        }finally{NativeDeux.runAllowed.countDown();NativeDeux.retirementAllowed.countDown();task.close();}
        retired(task);require(NativeDeux.liveResources.get()==0,"native resources survived retirement");

        // A same-job replacement reuses its directory. Old idempotent close
        // must not remove output produced by the replacement after retirement.
        NativeDeux.blockRetirement=false;NativePassageTask replacement=task(context);
        String token=new JSONObject(replacement.start(0)).getString("token");
        try{
            long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(5);
            while("running".equals(new JSONObject(replacement.status(token)).getString("state"))&&System.nanoTime()<deadline)Thread.sleep(5);
            require("completed".equals(new JSONObject(replacement.status(token)).getString("state")),"replacement did not complete");
            File result=replacement.result(token);task.close();
            require(result.isFile()&&result.length()==573300L*2*4,"retired task removed replacement output");
            require(NativeDeux.maxActive.get()==1,"native execution overlapped across replacement");
        }finally{replacement.close();}
        retired(replacement);require(NativeDeux.liveResources.get()==0,"replacement native resources leaked");
    }
}

/** Delays only native execution/retirement; task locking and executor behavior are production code. */
final class NativeDeux implements AutoCloseable {
    static final String RUNTIME_VERSION="controlled-test-boundary";
    static final Semaphore INFERENCE_GATE=new Semaphore(1,true);
    static final AtomicInteger constructed=new AtomicInteger(),runs=new AtomicInteger(),active=new AtomicInteger(),maxActive=new AtomicInteger(),liveResources=new AtomicInteger();
    static volatile boolean blockRetirement;
    static CountDownLatch runEntered,runAllowed,retirementEntered,retirementAllowed;
    private volatile boolean closed,running;
    private boolean released;
    interface Progress{void update(double value,String detail);}
    interface Cancellation{boolean cancelled();}
    interface ExecutionScope{void begin()throws Exception;void end();}
    NativeDeux(Context context){constructed.incrementAndGet();liveResources.incrementAndGet();}
    static void reset(){
        if(active.get()!=0||liveResources.get()!=0||INFERENCE_GATE.availablePermits()!=1)throw new AssertionError("Previous native boundary leaked");
        constructed.set(0);runs.set(0);maxActive.set(0);blockRetirement=false;
        runEntered=new CountDownLatch(1);runAllowed=new CountDownLatch(1);retirementEntered=new CountDownLatch(1);retirementAllowed=new CountDownLatch(1);
    }
    static void await(CountDownLatch latch){
        boolean interrupted=false;long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(10);
        try{while(true){long left=deadline-System.nanoTime();if(left<=0)throw new AssertionError("Controlled boundary timed out");try{if(!latch.await(left,TimeUnit.NANOSECONDS))throw new AssertionError("Controlled boundary timed out");return;}catch(InterruptedException expected){interrupted=true;}}}
        finally{if(interrupted)Thread.currentThread().interrupt();}
    }
    void predict(File audio,long sample,File output,Progress progress,Cancellation cancellation,ExecutionScope scope,NativeInferenceProfile profile)throws Exception{
        while(!INFERENCE_GATE.tryAcquire(25,TimeUnit.MILLISECONDS)){if(closed||cancellation.cancelled())throw new IOException("cancelled while waiting");}
        boolean entered=false;
        try{
            if(closed||cancellation.cancelled())throw new IOException("cancelled before inference");
            scope.begin();entered=true;running=true;runs.incrementAndGet();maxActive.accumulateAndGet(active.incrementAndGet(),Math::max);
            try(RandomAccessFile file=new RandomAccessFile(output,"rw")){file.setLength(573300L*2*4);}
            runEntered.countDown();await(runAllowed);
            if(closed||cancellation.cancelled())throw new IOException("cancelled native boundary");
        }finally{if(running){running=false;active.decrementAndGet();}try{if(entered)scope.end();}finally{INFERENCE_GATE.release();}}
    }
    void cancel(){closed=true;}
    @Override public void close(){
        closed=true;
        if(running)return;
        if(blockRetirement){retirementEntered.countDown();await(retirementAllowed);}
        synchronized(this){if(!released){released=true;liveResources.decrementAndGet();}}
    }
}

final class AppDiagnostics {
    static void record(Context context,String source,Throwable failure){}
    static void log(Context context,String level,String source,String message){}
    static void sample(Context context,String event){}
    static void profile(Context context,NativeInferenceProfile.Snapshot snapshot){}
}
