package com.cyberbasslord.lightforge;

import java.io.*;
import java.lang.management.BufferPoolMXBean;
import java.lang.management.ManagementFactory;
import java.lang.reflect.*;
import java.nio.FloatBuffer;
import java.security.MessageDigest;
import java.util.*;
import java.util.function.LongSupplier;
import org.json.*;

/** Real original front/temporal graphs; synthetic headroom and delay test orchestration, not speed. */
public final class NativeDeuxNominationMemoryTest {
    private static final long RESERVE=512L*1024*1024;
    private static final long ACTIVATION_BYTES=1301L*60*256*4;
    private static final long WORKER_SLOT_BYTES=2L*1301*256*4;
    private static final Field VALUES=field("values"),GRAPH=field("activeGraph"),INPUTS=field("parallelInputs"),RUN=field("activeRun"),POLICY=field("passagePolicy");
    private static final Method ENSURE=method("ensureBuffers",NativeInferenceProfile.class);
    private static final Method NOMINATE=method("nominate",File.class,long.class,NativeDeuxTransform.Check.class,NativeInferenceProfile.class);
    private static final BufferPoolMXBean DIRECT=directPool();
    private static void require(boolean ok,String message){if(!ok)throw new AssertionError(message);}
    private static Field field(String name){try{Field f=NativeDeux.class.getDeclaredField(name);f.setAccessible(true);return f;}catch(Exception e){throw new AssertionError(e);}}
    private static Method method(String name,Class<?>... types){try{Method m=NativeDeux.class.getDeclaredMethod(name,types);m.setAccessible(true);return m;}catch(Exception e){throw new AssertionError(e);}}
    private static BufferPoolMXBean directPool(){for(BufferPoolMXBean p:ManagementFactory.getPlatformMXBeans(BufferPoolMXBean.class))if("direct".equals(p.getName()))return p;throw new AssertionError("No actual direct-buffer pool observation");}
    private static String hash(FloatBuffer data)throws Exception{
        MessageDigest digest=MessageDigest.getInstance("SHA-256");byte[] block=new byte[16384];int used=0;
        for(int i=0;i<data.capacity();i++){
            float value=data.get(i);require(Float.isFinite(value),"Nonfinite original activation");int bits=Float.floatToRawIntBits(value);
            block[used++]=(byte)bits;block[used++]=(byte)(bits>>>8);block[used++]=(byte)(bits>>>16);block[used++]=(byte)(bits>>>24);
            if(used==block.length){digest.update(block);used=0;}
        }
        if(used!=0)digest.update(block,0,used);
        StringBuilder text=new StringBuilder();for(byte b:digest.digest())text.append(String.format(Locale.ROOT,"%02x",b&255));return text.toString();
    }
    private static Throwable unwrapped(Throwable error){return error instanceof InvocationTargetException?((InvocationTargetException)error).getCause():error;}
    private static IOException abort()throws Exception{
        for(Class<?> c:NativeDeux.class.getDeclaredClasses())if("ProbeAborted".equals(c.getSimpleName())){
            Constructor<?> constructor=c.getDeclaredConstructor(String.class);constructor.setAccessible(true);return (IOException)constructor.newInstance("screen-budget");
        }
        throw new AssertionError("Missing actual probe deadline type");
    }
    private static final class Observation implements LongSupplier,NativeDeuxTransform.Check {
        final String scenario;
        NativeDeux runner;FloatBuffer original;
        long directBefore,directPeak,temporalStarted;int memoryCalls,fronts,temporals,maximumWorkers;boolean sameValues=true,delayInjected,fourDelayInjected,stopped;
        String graph;
        final List<String> order=new ArrayList<>(),frontHashes=new ArrayList<>(),temporalHashes=new ArrayList<>();
        final List<Long> memoryValues=new ArrayList<>();
        final List<Long> temporalBoundarySpans=new ArrayList<>();
        final Thread owner=Thread.currentThread();final Set<Thread> workers=new HashSet<>();
        Observation(String scenario){this.scenario=scenario;}
        synchronized void sample(){
            directPeak=Math.max(directPeak,DIRECT.getMemoryUsed());
            try{
                sameValues&=VALUES.get(runner)==original;
                FloatBuffer[] inputs=(FloatBuffer[])INPUTS.get(runner);maximumWorkers=Math.max(maximumWorkers,inputs==null?0:inputs.length);
            }catch(IllegalAccessException e){throw new AssertionError(e);}
        }
        @Override public synchronized long getAsLong(){
            sample();finishTemporalSpan();long headroom=NativeExecutionPolicy.EIGHT_WORKER_HEADROOM;
            if("four-only".equals(scenario)||"drop-eight-before".equals(scenario)&&memoryCalls>0)headroom=NativeExecutionPolicy.FOUR_WORKER_HEADROOM;
            if("drop-all-before-four".equals(scenario)&&temporals>=1)headroom=NativeExecutionPolicy.FOUR_WORKER_HEADROOM-1;
            if("drop-eight-final".equals(scenario)&&temporals>=3)headroom=NativeExecutionPolicy.FOUR_WORKER_HEADROOM;
            memoryCalls++;memoryValues.add(headroom+RESERVE);return headroom+RESERVE;
        }
        @Override public synchronized void check()throws IOException {
            try{observeCheck();}
            catch(IOException error){throw error;}
            catch(InterruptedException error){Thread.currentThread().interrupt();InterruptedIOException stopped=new InterruptedIOException("Fixture observer interrupted");stopped.initCause(error);throw stopped;}
            catch(Exception error){throw new IOException("Fixture observer failed",error);}
        }
        private void observeCheck()throws Exception {
            if(Thread.currentThread()!=owner)workers.add(Thread.currentThread());
            sample();String current=(String)GRAPH.get(runner);
            if(current==null||current.equals(graph))return;
            if("block-00-time".equals(graph))temporalHashes.add(hash((FloatBuffer)VALUES.get(runner)));
            graph=current;order.add(current);
            if("front".equals(current)){
                fronts++;
                if(fronts==3&&scenario.endsWith("after-four")){
                    stopped=true;
                    if("cancel-after-four".equals(scenario))throw new InterruptedIOException("Controlled caller cancellation after completed four-worker screening");
                    if("abort-after-four".equals(scenario))throw abort();
                    if("runtime-after-four".equals(scenario))throw new IOException("Controlled runtime failure after completed four-worker screening");
                }
            }else if("block-00-time".equals(current)){
                temporals++;temporalStarted=System.nanoTime();frontHashes.add(hash((FloatBuffer)VALUES.get(runner)));
                // Deliberately make the baseline nominate a real exact candidate. This
                // delay is solely a deterministic decision fixture, never timing proof.
                if(temporals==1){Thread.sleep("drop-eight-final".equals(scenario)?6000:2000);delayInjected=true;}
                if(temporals==2&&"drop-eight-final".equals(scenario)){Thread.sleep(3000);fourDelayInjected=true;}
            }else throw new AssertionError("Unexpected screening graph: "+current);
        }
        synchronized void finish()throws Exception{
            sample();finishTemporalSpan();if(!stopped&&"block-00-time".equals(graph))temporalHashes.add(hash((FloatBuffer)VALUES.get(runner)));
        }
        private void finishTemporalSpan(){if(temporalStarted!=0){temporalBoundarySpans.add(System.nanoTime()-temporalStarted);temporalStarted=0;}}
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=4)throw new IllegalArgumentException("models audio scenario new-output-directory");
        String scenario=args[2];Set<String> supported=new HashSet<>(Arrays.asList("four-only","drop-eight-before","drop-all-before-four","drop-eight-final","cancel-after-four","abort-after-four","runtime-after-four"));
        require(supported.contains(scenario),"Unknown reviewed scenario");
        require(Runtime.getRuntime().availableProcessors()>=8,"Observe at least eight actual CPUs; do not spoof processor count");
        File directory=new File(args[3]);require(!directory.exists()&&directory.mkdirs(),"Use a fresh fixture output directory");
        Observation observation=new Observation(scenario);NativeInferenceProfile profile=new NativeInferenceProfile();
        NativeDeux runner=new NativeDeux(new File(args[0]),new File(directory,"policy.bin"),observation);observation.runner=runner;
        Throwable failure=null;String[] policy;long measuredGrowth;
        NativeDeux.INFERENCE_GATE.acquire();
        try{
            ENSURE.invoke(runner,profile);observation.original=(FloatBuffer)VALUES.get(runner);
            require(observation.original.capacity()*4L==ACTIVATION_BYTES,"Original complete Float32 activation geometry changed");
            observation.directBefore=DIRECT.getMemoryUsed();observation.directPeak=observation.directBefore;
            try{NOMINATE.invoke(runner,new File(args[1]),661500L,observation,profile);}catch(Throwable e){failure=unwrapped(e);}
            observation.finish();
            require(RUN.get(runner)==null,"Screening left native RunOptions live");
            policy=((NativePassagePolicy)POLICY.get(runner)).evidenceRecords();
            measuredGrowth=observation.directPeak-observation.directBefore;
        }finally{runner.close();NativeDeux.INFERENCE_GATE.release();}
        JSONObject result=new JSONObject().put("schema","lightforge.nomination-memory-orchestration.v1").put("scenario",scenario)
            .put("scope","Actual original front/temporal JNI and Float32 activations; synthetic headroom and injected baseline delay; not performance or complete-passage proof")
            .put("syntheticBaselineDelayMillis","drop-eight-final".equals(scenario)?6000:2000).put("delayInjected",observation.delayInjected)
            .put("syntheticFourWorkerDelayMillis","drop-eight-final".equals(scenario)?3000:0).put("fourWorkerDelayInjected",observation.fourDelayInjected)
            .put("temporalBoundarySpansNanos",new JSONArray(observation.temporalBoundarySpans))
            .put("boundarySpanScope","Observer boundaries include validation and exclude temporal session creation; not production trial clocks or performance proof")
            .put("activationBytes",ACTIVATION_BYTES).put("sameActivationBufferIdentity",observation.sameValues)
            .put("directBufferBeforeBytes",observation.directBefore).put("directBufferPeakBytes",observation.directPeak)
            .put("directBufferGrowthBytes",measuredGrowth).put("maximumWorkerSlots",observation.maximumWorkers)
            .put("graphSessionOrder",new JSONArray(observation.order)).put("frontOutputHashes",new JSONArray(observation.frontHashes))
            .put("temporalOutputHashes",new JSONArray(observation.temporalHashes)).put("rawAvailableMemorySequence",new JSONArray(observation.memoryValues))
            .put("policyRecords",new JSONArray(Arrays.asList(policy))).put("failureClass",failure==null?JSONObject.NULL:failure.getClass().getName())
            .put("failureMessage",failure==null?JSONObject.NULL:failure.getMessage())
            .put("failureCauseClass",failure==null||failure.getCause()==null?JSONObject.NULL:failure.getCause().getClass().getName())
            .put("failureSuppressedCount",failure==null?0:failure.getSuppressed().length)
            .put("failureInjectionScope",scenario.endsWith("after-four")?"Cooperative Check failure after completed actual JNI trials; not a native Run failure":"none")
            .put("runOptionsRetired",true).put("inferenceGateReleased",NativeDeux.INFERENCE_GATE.availablePermits()==1);
        List<String> violations=new ArrayList<>();
        if(!observation.sameValues)violations.add("screening replaced the original activation buffer");
        long permittedGrowth=Math.max(0,observation.maximumWorkers-1)*WORKER_SLOT_BYTES+65536;
        if(measuredGrowth>permittedGrowth)violations.add("screening allocated more than reusable worker slots: "+measuredGrowth+" > "+permittedGrowth);
        if(observation.frontHashes.size()!=observation.temporals||new HashSet<>(observation.frontHashes).size()!=1)violations.add("temporal trials did not receive identical finite full Float32 activations");
        if(new HashSet<>(observation.temporalHashes).size()!=1)violations.add("temporal trials changed complete finite output bytes");
        int expectedTrials="drop-all-before-four".equals(scenario)?1:"drop-eight-final".equals(scenario)?3:2;
        if(observation.temporals!=expectedTrials||observation.temporalHashes.size()!=expectedTrials)violations.add("unexpected complete temporal trial count");
        int expectedFronts=scenario.endsWith("after-four")?3:expectedTrials;
        if(observation.fronts!=expectedFronts)violations.add("front reconstruction count differs from safe current shortlist");
        int expectedWorkers=expectedTrials==1?0:expectedTrials==3?8:4;
        if(observation.maximumWorkers!=expectedWorkers)violations.add("memory-ineligible worker buffers were allocated, or eligible work was skipped");
        boolean nominated=false,nominatedFour=false;for(String row:policy){nominated|=row.contains("reason=nominated");nominatedFour|=row.contains("reason=nominated")&&row.contains("workers=4");}
        if(scenario.endsWith("after-four")||"drop-all-before-four".equals(scenario)){
            if(nominated)violations.add("aborted or ineligible screening retained a winner");
        }else if(!nominatedFour)violations.add("completed exact eligible four-worker winner was discarded");
        if("cancel-after-four".equals(scenario)){
            if(!(failure instanceof InterruptedIOException)||!NativeDeux.cleanCancellation(failure))violations.add("caller cancellation was swallowed or cleanup was uncertain");
            if(failure!=null&&(!"Controlled caller cancellation after completed four-worker screening".equals(failure.getMessage())||failure.getCause()!=null||failure.getSuppressed().length!=0))violations.add("caller cancellation provenance or cleanup shape changed");
        }else if("runtime-after-four".equals(scenario)){
            if(!(failure instanceof IOException)||failure instanceof InterruptedIOException)violations.add("runtime failure was swallowed");
            if(failure!=null&&(!"Controlled runtime failure after completed four-worker screening".equals(failure.getMessage())||failure.getCause()!=null||failure.getSuppressed().length!=0))violations.add("injected Check failure provenance or cleanup shape changed");
        }else if(failure!=null)violations.add("unexpected screening failure: "+failure);
        if("drop-eight-final".equals(scenario)&&(!observation.fourDelayInjected||observation.temporalBoundarySpans.size()!=3
            ||observation.temporalBoundarySpans.get(1)<=observation.temporalBoundarySpans.get(2)))violations.add("synthetic faster-eight boundary fixture did not execute");
        if(!observation.delayInjected)violations.add("deterministic decision-fixture delay was not exercised");
        if(new File(directory,"policy.bin").exists())violations.add("graph screening published a complete-passage cache");
        boolean workersRetired=true;for(Thread worker:observation.workers)if(worker.isAlive())workersRetired=false;
        if(!workersRetired)violations.add("native worker survived screening");
        result.put("observedWorkerThreads",observation.workers.size()).put("allObservedWorkersRetired",workersRetired)
            .put("permittedWorkerBufferGrowthBytes",permittedGrowth).put("violations",new JSONArray(violations)).put("passed",violations.isEmpty());
        System.out.println(result.toString());
        if(!violations.isEmpty())throw new AssertionError("Nomination memory/orchestration checks failed: "+violations);
    }
}
