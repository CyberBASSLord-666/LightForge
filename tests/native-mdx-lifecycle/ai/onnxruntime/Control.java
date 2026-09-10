package ai.onnxruntime;
import java.util.concurrent.*;
/** Controllable JNI boundary for production task concurrency regression tests. */
public final class Control {
    public static volatile boolean blockCreate,failCreate,blockRun,running,closedDuringRun;
    public static volatile int closes,runs,terminations;
    public static volatile Runnable beforeInitialization=()->{};
    public static volatile Runnable beforeClose=()->{};
    public static CountDownLatch createEntered,createAllowed,runEntered,runAllowed;
    public static void reset(){blockCreate=false;failCreate=false;blockRun=false;running=false;closedDuringRun=false;closes=0;runs=0;terminations=0;beforeInitialization=()->{};beforeClose=()->{};createEntered=new CountDownLatch(1);createAllowed=new CountDownLatch(1);runEntered=new CountDownLatch(1);runAllowed=new CountDownLatch(1);}
    public static void await(CountDownLatch latch)throws OrtException{try{if(!latch.await(15,TimeUnit.SECONDS))throw new OrtException("Test boundary timed out");}catch(InterruptedException error){throw new OrtException("Interrupted");}}
}
