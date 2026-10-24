package com.cyberbasslord.lightforge;

import ai.onnxruntime.OrtException;
import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.json.*;

/** Actual production retirement/classifiers, real executor Futures, no model or native allocation. */
public final class NativeDeuxFailureRetirementTest {
    private static final Method RETIRE=method("retireTemporalPipeline",ExecutorService.class,boolean.class,List.class,List.class,
        Runnable.class,Runnable.class,Runnable.class,Throwable.class,boolean.class);
    private static final Method PROBE=method("cleanProbeAbort",Throwable.class);
    private static final Method INTERRUPTED=method("interrupted",InterruptedException.class);
    private static final Constructor<?> ABORT=constructor("ProbeAborted",String.class);
    private static final Constructor<?> REJECTED=constructor("ProbeRunRejected",OrtException.class);

    public static void main(String[] args)throws Exception{
        workerAndCleanupFailures();cleanWorkers();ownerInterrupt();classifiers();failedPredictionInvalidatesSeed();
        System.out.println("PASS: production temporal retirement preserves every failure, waits for workers, restores interruption, and classifies only bounded clean stops.");
    }
    private static void workerAndCleanupFailures()throws Exception{
        ExecutorService pool=Executors.newFixedThreadPool(2);
        CompletionService<Integer> completion=new ExecutorCompletionService<>(pool);
        CountDownLatch secondRunning=new CountDownLatch(1),releaseSecond=new CountDownLatch(1);
        AtomicInteger active=new AtomicInteger(),closed=new AtomicInteger(),profile=new AtomicInteger();
        InterruptedIOException first=new InterruptedIOException("caller cancelled");
        IOException resultClose=new IOException("worker Result.close failed");
        IOException second=new IOException("second worker native failure");
        RuntimeException outputClose=new RuntimeException("output tensor close failed");
        Error inputClose=new AssertionError("input tensor close failed");
        Future<Integer> one=completion.submit(()->{
            try(AutoCloseable result=()->{throw resultClose;}){throw first;}
        });
        Future<Integer> two=completion.submit(()->{
            active.incrementAndGet();secondRunning.countDown();
            try{require(releaseSecond.await(5,TimeUnit.SECONDS),"second worker not released");throw second;}
            finally{active.decrementAndGet();}
        });
        require(secondRunning.await(5,TimeUnit.SECONDS),"worker did not start");
        Throwable observed=failure(completion.take());require(observed==first,"original completed failure");
        List<AutoCloseable> resources=Arrays.asList(
            ()->{require(pool.isTerminated()&&active.get()==0&&one.isDone()&&two.isDone(),"output closed before worker retirement");closed.incrementAndGet();throw outputClose;},
            ()->{closed.incrementAndGet();throw inputClose;});
        Throwable thrown=retire(pool,true,Arrays.asList(one,two),resources,releaseSecond::countDown,()->{
            require(pool.isTerminated()&&active.get()==0,"profile finished before retirement");profile.incrementAndGet();
        },observed,false);
        require(thrown==first,"primary worker cause replaced");
        require(Arrays.equals(first.getSuppressed(),new Throwable[]{resultClose,second,outputClose,inputClose}),"worker/teardown causes lost or duplicated");
        require(closed.get()==2&&profile.get()==1,"all resources/profile not retired");
        require(!NativeDeux.cleanCancellation(first),"cleanup failure classified as cancellation");
    }
    private static void cleanWorkers()throws Exception{
        for(boolean probe:new boolean[]{false,true}){
            ExecutorService pool=Executors.newFixedThreadPool(8);
            List<Future<?>> futures=new ArrayList<>();List<Throwable> failures=new ArrayList<>();
            AtomicInteger closed=new AtomicInteger();
            for(int i=0;i<60;i++){
                Throwable failure=probe?(i%2==0?abort():rejected()):cancel(i%2==0?new OrtException("terminated"):null);
                failures.add(failure);
                FutureTask<Integer> future=new FutureTask<Integer>(()->{throw (Exception)failure;}){
                    @Override public boolean cancel(boolean interrupt){throw new AssertionError("Future.cancel used before JNI retirement");}
                };
                futures.add(future);pool.execute(future);
            }
            Throwable thrown=retireWithOwnerCancellation(pool,true,futures,Collections.singletonList(()->closed.incrementAndGet()),()->{},
                ()->{throw new AssertionError("Optional stop incorrectly cancelled whole prediction");},()->{},failures.get(0),false);
            require(thrown==failures.get(0)&&thrown.getSuppressed().length==59,"all terminal failures preserved once");
            for(int i=1;i<60;i++)require(thrown.getSuppressed()[i-1]==failures.get(i),"future cause order changed");
            require(closed.get()==1&&pool.isTerminated(),"clean workers did not retire");
            require(probe?cleanProbe(thrown):NativeDeux.cleanCancellation(thrown),"clean sibling stops incorrectly rejected");
        }
    }
    private static void ownerInterrupt()throws Exception{
        ExecutorService pool=Executors.newSingleThreadExecutor();
        CountDownLatch running=new CountDownLatch(1),release=new CountDownLatch(1),ownerStarted=new CountDownLatch(1);
        Future<Integer> worker=pool.submit(()->{running.countDown();require(release.await(5,TimeUnit.SECONDS),"owner did not terminate worker");return 0;});
        require(running.await(5,TimeUnit.SECONDS),"interrupt worker start");
        AtomicReference<Throwable> thrown=new AtomicReference<>();AtomicBoolean interruptRestored=new AtomicBoolean();AtomicInteger closed=new AtomicInteger(),ownerCancelled=new AtomicInteger();
        Thread owner=new Thread(()->{
            ownerStarted.countDown();
            thrown.set(retireWithOwnerCancellation(pool,false,Collections.singletonList(worker),Collections.singletonList(()->{
                require(pool.isTerminated()&&worker.isDone(),"interrupt closed resources early");closed.incrementAndGet();
            }),()->{throw new AssertionError("Owner interruption used probe termination");},()->{ownerCancelled.incrementAndGet();release.countDown();},()->{},null,false));
            interruptRestored.set(Thread.currentThread().isInterrupted());
        },"actual-retirement-owner");
        owner.start();require(ownerStarted.await(5,TimeUnit.SECONDS),"owner start");
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(5);
        while(owner.getState()!=Thread.State.TIMED_WAITING&&owner.isAlive()&&System.nanoTime()<deadline)Thread.yield();
        require(owner.getState()==Thread.State.TIMED_WAITING,"owner did not await executor retirement");
        owner.interrupt();owner.join(5000);
        require(!owner.isAlive()&&closed.get()==1&&interruptRestored.get(),"owner interruption/lifetime not preserved");
        require(ownerCancelled.get()==1,"owner interruption was not shared with workers");
        require(NativeDeux.cleanCancellation(thrown.get())&&thrown.get().getCause() instanceof InterruptedException,"owner interrupt cause lost");
        InterruptedException initial=new InterruptedException("completion.take interrupted");
        Throwable normalized=(Throwable)INTERRUPTED.invoke(null,initial);
        require(normalized.getCause()==initial&&NativeDeux.cleanCancellation(normalized),"initial take interruption lost");
        ExecutorService empty=Executors.newSingleThreadExecutor();
        Throwable retained=retireWithOwnerCancellation(empty,true,Collections.emptyList(),Collections.emptyList(),
            ()->{throw new AssertionError("Initial owner interruption used probe termination");},ownerCancelled::incrementAndGet,()->{},normalized,true);
        require(retained==normalized&&Thread.interrupted(),"initial owner interruption not restored");
        require(ownerCancelled.get()==2,"initial owner interruption did not publish shared cancellation");
    }
    private static void classifiers()throws Exception{
        require(cleanProbe(abort())&&cleanProbe(rejected()),"known probe shapes rejected");
        require(NativeDeux.cleanCancellation(cancel(null))&&NativeDeux.cleanCancellation(cancel(new OrtException("Run terminated"))),"known cancellation shapes rejected");
        require(!NativeDeux.cleanCancellation(new InterruptedIOException(){})&&!cleanProbe(new IOException()),"unknown subclass accepted");
        require(!NativeDeux.cleanCancellation(cancel(new IOException("unknown"))),"unknown cancellation cause accepted");
        OrtException annotated=new OrtException("Run failed");annotated.addSuppressed(new IOException("cleanup"));
        require(!NativeDeux.cleanCancellation(cancel(annotated))&&!cleanProbe(REJECTED.newInstance(annotated)),"annotated native cause accepted");
        Throwable probe=abort();probe.addSuppressed(new IOException("close failed"));require(!cleanProbe(probe),"probe close failure swallowed");
        probe=abort();probe.initCause(new IOException("unknown"));require(!cleanProbe(probe),"unknown probe cause accepted");
        probe=abort();probe.addSuppressed(cancel(null));require(!cleanProbe(probe),"explicit cancellation swallowed as optional probe");
        InterruptedIOException cancellation=cancel(null);cancellation.addSuppressed(abort());require(!NativeDeux.cleanCancellation(cancellation),"mixed failure accepted as clean cancellation");
        cancellation=cancel(null);InterruptedIOException child=cancel(null);cancellation.addSuppressed(child);child.addSuppressed(cancellation);
        require(!NativeDeux.cleanCancellation(cancellation),"cyclic suppression accepted");
        cancellation=cancel(null);child=cancellation;
        for(int i=0;i<34;i++){InterruptedIOException next=cancel(null);child.addSuppressed(next);child=next;}
        require(!NativeDeux.cleanCancellation(cancellation),"unbounded recursive graph accepted");
        cancellation=cancel(null);for(int i=0;i<256;i++)cancellation.addSuppressed(cancel(null));
        require(!NativeDeux.cleanCancellation(cancellation),"unbounded wide graph accepted");
        ExecutorService empty=Executors.newSingleThreadExecutor();IOException primary=new IOException("worker failed");Error profile=new AssertionError("profile failed");
        AtomicBoolean closed=new AtomicBoolean();
        Throwable retained=retire(empty,true,Collections.emptyList(),Collections.singletonList(()->closed.set(true)),()->{},()->{throw profile;},primary,false);
        require(retained==primary&&closed.get()&&Arrays.equals(primary.getSuppressed(),new Throwable[]{profile}),"profile failure masked worker failure or skipped resources");
    }
    private static void failedPredictionInvalidatesSeed()throws Exception{
        Path root=Files.createTempDirectory("deux-failed-seed-");
        try{
            File directory=root.toFile();
            JSONObject manifest=new JSONObject().put("execution","bounded-independent-batches-v1").put("frames",1301)
                .put("samples",573300).put("fftSize",2048).put("hop",441);
            JSONArray indices=new JSONArray(),bands=new JSONArray();
            for(int i=0;i<2050;i++)indices.put(i);for(int i=0;i<1908;i++)indices.put(i);
            for(int i=0;i<1025;i++)bands.put(i<954?2:1);
            JSONObject files=new JSONObject();String digest=repeat('a');
            for(String name:new String[]{"front","head-0","head-1"})files.put(name+".onnx",new JSONObject().put("bytes",1).put("sha256",digest));
            for(int i=0;i<12;i++)for(String kind:new String[]{"time","frequency"})
                files.put(String.format(Locale.ROOT,"block-%02d-%s.onnx",i,kind),new JSONObject().put("bytes",1).put("sha256",digest));
            manifest.put("indices",indices).put("bandsPerFrequency",bands).put("files",files);
            Files.write(root.resolve("manifest.json"),manifest.toString().getBytes(StandardCharsets.UTF_8));
            File cache=new File(directory,"passage-policy.bin"),audio=new File(directory,"source.wav"),output=new File(directory,"output.f32");
            String identity;
            try(NativeDeux engine=new NativeDeux(directory,cache)){
                identity=((NativeExecutionPolicy.Key)field(engine,"executionKey")).identity();
            }
            NativePassagePolicy qualified=new NativePassagePolicy(identity,null);qualified.nominate(4,0);
            for(int ordinal=0;ordinal<3;ordinal++){
                NativePassagePolicy.Plan plan=qualified.plan(ordinal,35-ordinal,Long.MAX_VALUE,8);
                require(plan.action==NativePassagePolicy.Action.PAIR,"synthetic seed qualification denied");
                qualified.recordPair(new NativePassagePolicy.Pair(ordinal,ordinal==1,60000000000L,40000000000L,40000000000L,
                    repeat('b'),true,true,true,true,4),34-ordinal);
            }
            NativePassagePolicy.Seed seed=qualified.qualifiedSeed();require(seed!=null,"synthetic valid seed missing");
            for(int mode=0;mode<6;mode++){
                NativePassagePolicy.save(cache,identity,seed);
                try(NativeDeux engine=new NativeDeux(directory,cache)){
                    NativePassagePolicy policy=(NativePassagePolicy)field(engine,"passagePolicy");
                    require(policy.qualifiedSeed()!=null,"host constructor did not load valid seed");
                    final int fault=mode;
                    Error cleanup=new AssertionError("scope cleanup failed"),begin=new AssertionError("scope begin failed");
                    AtomicInteger ended=new AtomicInteger();
                    NativeDeux.ExecutionScope scope=new NativeDeux.ExecutionScope(){
                        public void begin(){if(fault==4)throw begin;}
                        public void end(){ended.incrementAndGet();if(fault==3)throw cleanup;}
                    };
                    if(mode==5)engine.cancel();
                    Throwable failure=null;
                    try{engine.predict(audio,0,mode==1?output:audio,null,()->fault==2,scope,null,35);}
                    catch(Throwable expected){failure=expected;}
                    require(failure!=null,"fault did not fail prediction");
                    require(!cache.exists()&&policy.qualifiedSeed()==null,"failed prediction retained durable or in-memory qualification");
                    require(!(Boolean)field(engine,"running")&&field(engine,"activeRun")==null,"failure did not retire prediction lifecycle");
                    require(NativeDeux.INFERENCE_GATE.availablePermits()==1,"failure retained inference gate");
                    require(!output.exists(),"fault committed output");
                    if(mode==0)require(failure instanceof IOException&&failure.getMessage().contains("cannot replace source"),"invalid output failure changed");
                    if(mode==1)require(failure instanceof IOException&&failure.getMessage().contains("checksum"),"preflight failure changed");
                    if(mode==2||mode==5)require(NativeDeux.cleanCancellation(failure),"cancellation failure changed");
                    if(mode==3)require(failure instanceof IOException&&Arrays.equals(failure.getSuppressed(),new Throwable[]{cleanup})&&ended.get()==1,"cleanup replaced original prediction failure");
                    if(mode==4)require(failure==begin&&ended.get()==0,"scope begin original error or ownership changed");
                }
            }
            NativePassagePolicy.save(cache,identity,seed);
            try(NativeDeux unused=new NativeDeux(directory,cache)){}
            require(NativePassagePolicy.load(cache,identity)!=null,"normal close invalidated qualified seed");
            final RuntimeException deletion=new IllegalStateException("injected cache deletion failure");
            AtomicBoolean rejectPath=new AtomicBoolean();
            File faultCache=new File(cache.getPath()){
                @Override public Path toPath(){if(rejectPath.get())throw deletion;return super.toPath();}
            };
            try(NativeDeux engine=new NativeDeux(directory,faultCache)){
                require(((NativePassagePolicy)field(engine,"passagePolicy")).qualifiedSeed()!=null,"deletion fixture seed not loaded");
                rejectPath.set(true);Throwable failure=null;
                try{engine.predict(audio,0,audio,null,()->false);}
                catch(Throwable expected){failure=expected;}
                require(failure instanceof IOException&&failure.getMessage().contains("cannot replace source")
                    &&Arrays.equals(failure.getSuppressed(),new Throwable[]{deletion}),"cache invalidation failure replaced original error or was lost");
                require(((NativePassagePolicy)field(engine,"passagePolicy")).qualifiedSeed()==null,"failed durable deletion retained in-memory seed");
                require(NativeDeux.INFERENCE_GATE.availablePermits()==1,"invalidation error retained gate");
            }
        }finally{
            try(java.util.stream.Stream<Path> paths=Files.walk(root)){
                for(Path path:(Iterable<Path>)paths.sorted(Comparator.reverseOrder())::iterator)Files.deleteIfExists(path);
            }
        }
    }
    private static Object field(Object target,String name)throws Exception{Field field=target.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(target);}
    private static String repeat(char value){char[] chars=new char[64];Arrays.fill(chars,value);return new String(chars);}
    private static Throwable retire(ExecutorService pool,boolean terminate,List<? extends Future<?>> futures,List<? extends AutoCloseable> resources,
            Runnable terminateRuns,Runnable profile,Throwable primary,boolean interrupted){
        return retireWithOwnerCancellation(pool,terminate,futures,resources,terminateRuns,terminateRuns,profile,primary,interrupted);
    }
    private static Throwable retireWithOwnerCancellation(ExecutorService pool,boolean terminate,List<? extends Future<?>> futures,List<? extends AutoCloseable> resources,
            Runnable terminateRuns,Runnable cancelOwner,Runnable profile,Throwable primary,boolean interrupted){
        try{RETIRE.invoke(null,pool,terminate,futures,resources,terminateRuns,cancelOwner,profile,primary,interrupted);return null;}
        catch(InvocationTargetException failed){return failed.getCause();}catch(Exception failed){throw new AssertionError(failed);}
    }
    private static Throwable failure(Future<?> future)throws Exception{try{future.get();throw new AssertionError("expected worker failure");}catch(ExecutionException failure){return failure.getCause();}}
    private static InterruptedIOException cancel(Throwable cause){InterruptedIOException failure=new InterruptedIOException("cancelled");if(cause!=null)failure.initCause(cause);return failure;}
    private static Throwable abort()throws Exception{return (Throwable)ABORT.newInstance("probe-budget");}
    private static Throwable rejected()throws Exception{return (Throwable)REJECTED.newInstance(new OrtException("native Run rejected"));}
    private static boolean cleanProbe(Object failure)throws Exception{return (Boolean)PROBE.invoke(null,failure);}
    private static Method method(String name,Class<?>...types){try{Method method=NativeDeux.class.getDeclaredMethod(name,types);method.setAccessible(true);return method;}catch(Exception failed){throw new AssertionError(failed);}}
    private static Constructor<?> constructor(String name,Class<?>...types){try{Constructor<?> constructor=Class.forName(NativeDeux.class.getName()+"$"+name).getDeclaredConstructor(types);constructor.setAccessible(true);return constructor;}catch(Exception failed){throw new AssertionError(failed);}}
    private static void require(boolean condition,String message){if(!condition)throw new AssertionError(message);}
}
