package com.cyberbasslord.lightforge;
import ai.onnxruntime.Control;
import android.content.Context;
import org.json.JSONObject;
import java.io.*;
import java.lang.reflect.Field;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;

/** Exercises the production task with controllable native boundaries. No phone claims. */
public final class NativeMdxLifecycleTest {
    private static final String JOB="12345678-1234-1234-1234-123456789abc";
    private static int checks;
    private static File root,assets;
    public static void main(String[] args)throws Exception{
        root=new File(args[0]);assets=new File(args[1]);root.mkdirs();
        stalledConstruction();failedConstruction();cancelRunning();successfulRelease();sharedGate();
        System.out.println("PASS: "+checks+" production NativeMdxTask lifecycle checks");
    }
    private static NativeMdxTask task(String name)throws Exception{return new NativeMdxTask(new Context(new File(root,name),assets),JOB);}
    private static Object field(Object object,String name)throws Exception{Field field=object.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(object);}
    private static NativeRuntimeGuard guard(NativeMdxTask task)throws Exception{return (NativeRuntimeGuard)field(task,"runtimeGuard");}
    private static void leaseBeforeOrt(NativeMdxTask task){Control.beforeInitialization=()->{try{require(guard(task).state()!=null,"durable lease precedes every ORT initialization");}catch(Exception error){throw new AssertionError(error);}};}
    private static void leasedRetirement(NativeMdxTask task){Control.beforeClose=()->{try{require(guard(task).state()!=null,"active retirement keeps native crash lease");require(NativeDeux.INFERENCE_GATE.availablePermits()==0,"active retirement keeps process gate");}catch(Exception error){throw new AssertionError(error);}};}
    private static String start(NativeMdxTask task)throws Exception{
        String token=new JSONObject(task.begin(JOB,NativeMdxTask.INPUT_BYTES)).getString("token");
        String chunk=Base64.getEncoder().encodeToString(new byte[64*1024]);
        for(long at=0;at<NativeMdxTask.INPUT_BYTES;at+=64*1024)task.append(JOB,token,chunk);
        task.run(JOB,token);return token;
    }
    private static void terminal(NativeMdxTask task,String token,String expected)throws Exception{
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(10);
        while(System.nanoTime()<deadline){String state=new JSONObject(task.status(JOB,token)).getString("state");if(!state.equals("running")){require(state.equals(expected),"expected "+expected+", got "+state);return;}Thread.sleep(5);}
        throw new AssertionError("Task did not publish terminal state");
    }
    private static void stopped(NativeMdxTask task)throws Exception{require(((ExecutorService)field(task,"executor")).awaitTermination(10,TimeUnit.SECONDS),"executor retired");require(guard(task).state()==null,"retired task clears lease");require(!Control.closedDuringRun,"never closes an executing graph");}
    private interface Checked {void run()throws Exception;}
    private static void prompt(Checked action,String message)throws Exception{
        ExecutorService executor=Executors.newSingleThreadExecutor();
        try{Future<?> future=executor.submit(()->{try{action.run();}catch(Exception error){throw new RuntimeException(error);}});future.get(1,TimeUnit.SECONDS);checks++;}
        catch(TimeoutException error){throw new AssertionError(message,error);}finally{executor.shutdownNow();}
    }
    private static void stalledConstruction()throws Exception{
        Control.reset();Control.blockCreate=true;NativeMdxTask task=task("construct");leaseBeforeOrt(task);leasedRetirement(task);String token=start(task);
        require(Control.createEntered.await(5,TimeUnit.SECONDS),"graph construction entered");
        try{prompt(()->task.status(JOB,token),"status blocks on graph construction");prompt(()->task.cancel(JOB,token),"cancel blocks on graph construction");prompt(task::close,"service shutdown blocks on graph construction");require(Control.closes==0,"incomplete creation remains executor-owned");}
        finally{Control.createAllowed.countDown();task.close();}
        stopped(task);require(Control.closes==1,"created graph retired once after close");require(Control.runs==0,"cancelled creation never reaches inference");
    }
    private static void failedConstruction()throws Exception{
        Control.reset();Control.failCreate=true;NativeMdxTask task=task("failure");leaseBeforeOrt(task);String token=start(task);
        terminal(task,token,"failed");require(guard(task).state()==null,"Java construction failure clears lease");task.releaseIdle(JOB);task.close();stopped(task);
    }
    private static void cancelRunning()throws Exception{
        Control.reset();Control.blockRun=true;NativeMdxTask task=task("cancel");leaseBeforeOrt(task);leasedRetirement(task);String token=start(task);
        require(Control.runEntered.await(5,TimeUnit.SECONDS),"native run entered");require(guard(task).state()!=null,"run is covered by lease");
        prompt(()->task.cancel(JOB,token),"native cancel blocks");terminal(task,token,"cancelled");require(Control.terminations>0,"native cancellation terminates run");require(guard(task).state()==null,"cancelled run clears lease before terminal publication");
        require(field(task,"session")==null&&field(task,"inputBuffer")==null&&field(task,"outputBuffer")==null,"cancelled graph allocations retire before fallback can begin");
        require(((Number)field(task,"completedPasses")).intValue()==0,"cancelled pass is not reported complete");task.releaseIdle(JOB);task.close();stopped(task);
    }
    private static void successfulRelease()throws Exception{
        Control.reset();NativeMdxTask task=task("success");leaseBeforeOrt(task);String token=start(task);terminal(task,token,"completed");
        require(task.result(JOB,token).length()==NativeMdxTask.INPUT_BYTES,"completed output has exact geometry");require(guard(task).state()==null,"completed state requires lease cleanup");require(new JSONObject(task.status(JOB,token)).getInt("completedPasses")==1,"completed pass counter published");
        task.releaseIdle(JOB);require(field(task,"session")==null&&field(task,"inputBuffer")==null&&field(task,"outputBuffer")==null,"idle release frees model and both tensor buffers");require(((Number)field(task,"completedPasses")).intValue()==1,"completed counter survives idle release");task.close();stopped(task);require(Control.closes==1,"normal release closes graph once");
    }
    private static void sharedGate()throws Exception{
        Control.reset();NativeDeux.INFERENCE_GATE.acquire();NativeMdxTask task=task("gate");String token=start(task);
        try{require(!Control.createEntered.await(350,TimeUnit.MILLISECONDS),"MDX cannot initialize while another separator owns process gate");require(guard(task).state()==null,"waiting separator cannot overwrite current lease");prompt(()->task.cancel(JOB,token),"gate-wait cancellation blocks");prompt(task::close,"gate-wait close blocks");}
        finally{NativeDeux.INFERENCE_GATE.release();task.close();}
        stopped(task);require(Control.runs==0,"cancelled gate waiter never executes");require(NativeDeux.INFERENCE_GATE.availablePermits()==1,"shared gate returns exactly one permit");
    }
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);checks++;}
}
