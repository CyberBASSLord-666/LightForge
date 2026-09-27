package ai.onnxruntime;

import java.util.*;
import java.util.concurrent.*;

/** Deterministic Java-only native-boundary fault controls; never a JNI emulator. */
public final class Control {
    public interface Hook { void call() throws Exception; }
    public static final List<Resource> resources=new ArrayList<>();
    public static final Map<String,Integer> creations=new LinkedHashMap<>(), closes=new LinkedHashMap<>();
    public static volatile int sessionAttempts,runCalls,terminations,prepareCalls,running;
    public static int failSessionAttempt,failRunCall,failPrepareCall;
    public static String failCloseKind;
    public static int failCloseOrdinal;
    public static boolean failCloseWithError;
    public static Hook beforeCreate=()->{},beforeRun=()->{},beforeSessionClose=()->{},beforeRunClose=()->{};
    public static CountDownLatch runEntered,runAllowed,closeEntered,closeAllowed;
    public static volatile boolean blockRun;

    public static void reset(){
        resources.clear();creations.clear();closes.clear();
        sessionAttempts=runCalls=terminations=prepareCalls=running=0;
        failSessionAttempt=failRunCall=failPrepareCall=failCloseOrdinal=0;
        failCloseKind=null;failCloseWithError=false;blockRun=false;
        beforeCreate=()->{};beforeRun=()->{};beforeSessionClose=()->{};beforeRunClose=()->{};
        runEntered=new CountDownLatch(1);runAllowed=new CountDownLatch(1);
        closeEntered=new CountDownLatch(1);closeAllowed=new CountDownLatch(1);
    }
    public static void await(CountDownLatch gate)throws Exception {
        if(!gate.await(5,TimeUnit.SECONDS))throw new AssertionError("Controlled boundary timed out");
    }
    public static void prepare()throws Exception {
        prepareCalls++;if(prepareCalls==failPrepareCall)throw new java.io.IOException("Injected preparation failure");
    }
    public static int created(String kind){return creations.getOrDefault(kind,0);}
    public static int closed(String kind){return closes.getOrDefault(kind,0);}
    public static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    public static class Resource implements AutoCloseable {
        public final String kind;
        public final int ordinal;
        public boolean closeAttempted,retired;
        public int attempts;
        public Resource(String kind){this.kind=kind;ordinal=created(kind)+1;creations.put(kind,ordinal);resources.add(this);}
        public void usable(){check(!closeAttempted,"Retired resource reused: "+kind+ordinal);}
        @Override public void close()throws Exception {
            check(!closeAttempted,"Duplicate retirement: "+kind+ordinal);
            closeAttempted=true;attempts++;closes.put(kind,closed(kind)+1);
            if(kind.equals(failCloseKind)&&ordinal==failCloseOrdinal){
                if(failCloseWithError)throw new AssertionError("Injected destructor Error");
                throw new OrtException("Injected destructor failure");
            }
            retired=true;
        }
    }
    public static void allAttempted(){
        for(Resource resource:resources)check(resource.attempts==1,"Unretired/double resource "+resource.kind+resource.ordinal+" attempts="+resource.attempts);
    }
}
