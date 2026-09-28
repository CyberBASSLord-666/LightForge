package com.cyberbasslord.lightforge;

import java.lang.reflect.Method;

/** Fixed-size, passage-local GAME timing; never accepts audio, notes, paths or job identifiers. */
final class NativeGameProfile {
    private static final String[] GRAPHS={"encoder","dur2bd","segmenter","bd2dur","estimator"};
    private static final long UNAVAILABLE=-1L;
    interface Clock { long wallNanos(); long processCpuNanos(); }
    private static final Clock SYSTEM_CLOCK=systemClock();
    private final Clock clock;
    private final Stamp beginning;
    private final int threads;
    private final Metric read=new Metric(),wait=new Metric(),engineInit=new Metric(),prepare=new Metric(),
            runtimeInit=new Metric(),sessionInit=new Metric(),inference=new Metric(),cleanup=new Metric();
    private final Metric[] graphInit=new Metric[GRAPHS.length],graphRun=new Metric[GRAPHS.length];
    private int cacheHits,cacheMisses;
    private boolean cacheObserved;
    private Snapshot snapshot;

    NativeGameProfile(int threads){this(threads,SYSTEM_CLOCK);}
    NativeGameProfile(int threads,Clock clock){
        this.clock=clock;this.threads=Math.max(1,Math.min(4,threads));beginning=started();
        for(int i=0;i<GRAPHS.length;i++){graphInit[i]=new Metric();graphRun[i]=new Metric();}
    }
    Stamp started(){return new Stamp(clock.wallNanos(),clock.processCpuNanos());}
    void addRead(Stamp stamp){add(read,stamp);}
    void addWait(Stamp stamp){add(wait,stamp);}
    void addEngineInit(Stamp stamp){add(engineInit,stamp);}
    void addPrepare(Stamp stamp){add(prepare,stamp);}
    void addRuntimeInit(Stamp stamp){add(runtimeInit,stamp);}
    void addCleanup(Stamp stamp){add(cleanup,stamp);}
    void addSessionInit(String graph,Stamp stamp){addGraph(sessionInit,graphInit,graph,stamp);}
    void addInference(String graph,Stamp stamp){addGraph(inference,graphRun,graph,stamp);}
    void cache(boolean hit){if(snapshot==null){cacheObserved=true;if(hit)cacheHits++;else cacheMisses++;}}
    private void add(Metric metric,Stamp stamp){if(snapshot==null)metric.add(elapsed(stamp));}
    private void addGraph(Metric total,Metric[] graphs,String graph,Stamp stamp){
        if(snapshot!=null)return;
        int index=-1;for(int i=0;i<GRAPHS.length;i++)if(GRAPHS[i].equals(graph)){index=i;break;}
        if(index<0)throw new IllegalArgumentException("Unknown GAME graph.");
        Stamp elapsed=elapsed(stamp);total.add(elapsed);graphs[index].add(elapsed);
    }
    private Stamp elapsed(Stamp started){
        Stamp now=started();
        return new Stamp(Math.max(0,now.wall-started.wall),started.cpu<0||now.cpu<started.cpu?UNAVAILABLE:now.cpu-started.cpu);
    }
    /** Idempotent and immutable, including when failure cleanup calls it a second time. */
    Snapshot finish(String outcome){
        if(snapshot!=null)return snapshot;
        if(!"completed".equals(outcome)&&!"failed".equals(outcome)&&!"cancelled".equals(outcome)&&!"retirement-failed".equals(outcome))outcome="unknown";
        Stamp total=elapsed(beginning);
        StringBuilder record=new StringBuilder(2048);
        record.append("schema=native-game-profile-v1 route=native-game-v1 runtime=onnxruntime-1.25.1")
            .append(" provider=cpu precision=float32 steps=8 execution=sequential")
            .append(" intraOpThreads=").append(threads).append(" interOpThreads=1")
            .append(" cpuScope=process-all-app-threads acceleratorTelemetry=unavailable")
            .append(" outcome=").append(outcome).append(" wallMs=").append(ms(total.wall))
            .append(" processCpuMs=").append(ms(total.cpu))
            .append(" readWallMs=").append(read.wall()).append(" waitWallMs=").append(wait.wall())
            .append(" engineInitWallMs=").append(engineInit.wall()).append(" modelPrepareWallMs=").append(prepare.wall())
            .append(" runtimeInitWallMs=").append(runtimeInit.wall()).append(" modelInitWallMs=").append(sessionInit.wall())
            .append(" sessionInitCount=").append(sessionInit.count)
            .append(" inferenceWallMs=").append(inference.wall()).append(" inferenceCount=").append(inference.count)
            .append(" inferenceThreadCpuMs=unavailable inferenceProcessCpuMs=").append(inference.cpu())
            .append(" cleanupWallMs=").append(cleanup.wall())
            .append(" cacheModelHits=").append(cacheObserved?String.valueOf(cacheHits):"unavailable")
            .append(" cacheModelMisses=").append(cacheObserved?String.valueOf(cacheMisses):"unavailable");
        for(int i=0;i<GRAPHS.length;i++)record.append(' ').append(GRAPHS[i]).append("InitWallMs=").append(graphInit[i].wall())
            .append(' ').append(GRAPHS[i]).append("RunCount=").append(graphRun[i].count)
            .append(' ').append(GRAPHS[i]).append("RunWallMs=").append(graphRun[i].wall())
            .append(' ').append(GRAPHS[i]).append("RunProcessCpuMs=").append(graphRun[i].cpu());
        snapshot=new Snapshot(record.toString());return snapshot;
    }
    static final class Snapshot {
        private final String summary;
        Snapshot(String summary){this.summary=summary;}
        String summary(){return summary;}
    }
    static final class Stamp {
        final long wall,cpu;
        Stamp(long wall,long cpu){this.wall=wall;this.cpu=cpu;}
    }
    private static final class Metric {
        long wall,cpu;int count;boolean cpuUnavailable;
        void add(Stamp value){count++;wall+=value.wall;if(value.cpu<0)cpuUnavailable=true;else cpu+=value.cpu;}
        String wall(){return count==0?"unavailable":ms(wall);}
        String cpu(){return count==0||cpuUnavailable?"unavailable":ms(cpu);}
    }
    private static String ms(long nanos){return nanos<0?"unavailable":String.valueOf(nanos/1000000L);}
    private static Clock systemClock(){
        Method method=null;Object target=null;long scale=1;
        // Android's elapsed CPU clock includes ORT worker threads. A thread CPU
        // clock would omit their work and must not be interpreted as core usage.
        try {
            method=Class.forName("android.os.Process").getMethod("getElapsedCpuTime");
            method.invoke(null);scale=1000000L;
        }catch(Throwable unavailable){
            try {
                target=Class.forName("java.lang.management.ManagementFactory").getMethod("getOperatingSystemMXBean").invoke(null);
                method=Class.forName("com.sun.management.OperatingSystemMXBean").getMethod("getProcessCpuTime");
                method.invoke(target);
            }catch(Throwable unsupported){method=null;target=null;}
        }
        final Method cpuMethod=method;final Object cpuTarget=target;final long cpuScale=scale;
        return new Clock(){
            public long wallNanos(){return System.nanoTime();}
            public long processCpuNanos(){
                if(cpuMethod==null)return UNAVAILABLE;
                try {long value=((Number)cpuMethod.invoke(cpuTarget)).longValue();return value<0?UNAVAILABLE:Math.multiplyExact(value,cpuScale);}
                catch(Throwable unavailable){return UNAVAILABLE;}
            }
        };
    }
}
