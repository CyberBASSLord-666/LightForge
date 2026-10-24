package com.cyberbasslord.lightforge;

import ai.onnxruntime.*;
import java.io.*;
import java.nio.*;
import java.nio.file.*;
import java.security.*;
import java.lang.management.ManagementFactory;
import java.util.*;
import java.util.concurrent.*;

/** Isolated host-only, original frequency graph screen. No production changes. */
public final class NativeFrequencyScreen {
    static final int FRAMES=1301,BANDS=60,FEATURES=256,SIZE=FRAMES*BANDS*FEATURES;
    static final OrtEnvironment ENV=OrtEnvironment.getEnvironment();
    static FloatBuffer direct(int n){return ByteBuffer.allocateDirect(n*4).order(ByteOrder.nativeOrder()).asFloatBuffer();}
    static FloatBuffer slice(FloatBuffer x,int at,int n){FloatBuffer y=x.duplicate();y.position(at);y.limit(at+n);return y.slice();}
    static void copy(FloatBuffer x,int from,FloatBuffer y,int to,int n){FloatBuffer z=y.duplicate();z.position(to);z.put(slice(x,from,n));}
    static OrtSession open(Path models,String graph,int intra)throws Exception{
        try(OrtSession.SessionOptions o=new OrtSession.SessionOptions()){
            o.setIntraOpNumThreads(intra);o.setInterOpNumThreads(1);
            o.setExecutionMode(OrtSession.SessionOptions.ExecutionMode.SEQUENTIAL);
            o.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT);
            o.setCPUArenaAllocator(true);o.setMemoryPatternOptimization(true);
            o.addConfigEntry("session.intra_op.allow_spinning","0");
            return ENV.createSession(models.resolve(graph+".onnx").toString(),o);
        }
    }
    static final class Bound implements AutoCloseable{
        final OnnxTensor in,out;
        Bound(FloatBuffer x,long[] xs,FloatBuffer y,long[] ys)throws Exception{
            in=OnnxTensor.createTensor(ENV,x,xs);
            try{out=OnnxTensor.createTensor(ENV,y,ys);}catch(Exception|Error e){try{in.close();}catch(Throwable t){e.addSuppressed(t);}throw e;}
        }
        void run(OrtSession s,OrtSession.RunOptions opts)throws Exception{
            try(OrtSession.Result r=s.run(Collections.singletonMap("input",in),Collections.emptySet(),Collections.singletonMap("output",out),opts)){}
        }
        public void close(){try{out.close();}finally{in.close();}}
    }
    static String hash(FloatBuffer x)throws Exception{
        MessageDigest d=MessageDigest.getInstance("SHA-256");ByteBuffer b=ByteBuffer.allocate(16384).order(ByteOrder.LITTLE_ENDIAN);
        for(int i=0;i<x.capacity();i++){
            float v=x.get(i);if(!Float.isFinite(v))throw new IllegalStateException("Nonfinite output");
            b.putFloat(v);if(!b.hasRemaining()){d.update(b.array());b.clear();}
        }
        d.update(b.array(),0,b.position());return HexFormat.of().formatHex(d.digest());
    }
    static long cpu(){return ((com.sun.management.OperatingSystemMXBean)ManagementFactory.getOperatingSystemMXBean()).getProcessCpuTime();}
    static long rss()throws Exception{
        for(String s:Files.readAllLines(Path.of("/proc/self/status")))if(s.startsWith("VmHWM:"))return Long.parseLong(s.trim().split("\\s+")[1])*1024;
        throw new IllegalStateException("No RSS");
    }
    static void prepare(Path models,Path audio,Path input)throws Exception{
        FloatBuffer spectrum=direct(NativeDeuxTransform.SPECTRUM_FLOATS),values=direct(SIZE);
        new NativeDeuxTransform().encode(NativeDeuxTransform.readStereo(audio.toFile(),661500,()->{}),spectrum,()->{});
        try(OrtSession.RunOptions opts=new OrtSession.RunOptions();OrtSession s=open(models,"front",4);
            Bound b=new Bound(spectrum,new long[]{1,2050,FRAMES,2},values,new long[]{1,FRAMES,BANDS,FEATURES})){b.run(s,opts);}
        FloatBuffer x=direct(4*FRAMES*FEATURES),y=direct(4*FRAMES*FEATURES);
        try(OrtSession.RunOptions opts=new OrtSession.RunOptions();OrtSession s=open(models,"block-00-time",4);
            Bound b=new Bound(x,new long[]{4,FRAMES,FEATURES},y,new long[]{4,FRAMES,FEATURES})){
            for(int first=0;first<BANDS;first+=4){
                for(int band=0;band<4;band++)for(int f=0;f<FRAMES;f++)copy(values,(f*BANDS+first+band)*FEATURES,x,(band*FRAMES+f)*FEATURES,FEATURES);
                b.run(s,opts);
                for(int band=0;band<4;band++)for(int f=0;f<FRAMES;f++)copy(y,(band*FRAMES+f)*FEATURES,values,(f*BANDS+first+band)*FEATURES,FEATURES);
            }
        }
        try(FileOutputStream o=new FileOutputStream(input.toFile())){
            ByteBuffer b=ByteBuffer.allocate(65536).order(ByteOrder.LITTLE_ENDIAN);
            for(int i=0;i<SIZE;i++){b.putFloat(values.get(i));if(!b.hasRemaining()){o.write(b.array());b.clear();}}
            o.write(b.array(),0,b.position());
        }
        System.out.println("{\"phase\":\"prepare\",\"inputSha256\":\""+hash(values)+"\",\"bytes\":"+(SIZE*4L)+"}");
    }
    static FloatBuffer read(Path p)throws Exception{
        if(Files.size(p)!=SIZE*4L)throw new IllegalStateException("Wrong input size");
        FloatBuffer x=direct(SIZE);byte[] raw=new byte[65536];
        try(InputStream in=Files.newInputStream(p)){
            int n,at=0;while((n=in.read(raw))!=-1){if(n%4!=0)throw new IllegalStateException("Partial float");FloatBuffer y=ByteBuffer.wrap(raw,0,n).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer();while(y.hasRemaining())x.put(at++,y.get());}
        }return x;
    }
    static void measure(Path models,Path input,int batch,int workers,int round,String phase)throws Exception{
        FloatBuffer source=read(input),output=direct(SIZE);
        long start=System.nanoTime(),cpuStart=cpu();int calls=0;
        try(OrtSession.RunOptions opts=new OrtSession.RunOptions();OrtSession session=open(models,"block-00-frequency",workers==1?4:1)){
            if(workers==1){
                for(int first=0;first<FRAMES;first+=batch){int count=Math.min(batch,FRAMES-first),size=count*BANDS*FEATURES;
                    try(Bound b=new Bound(slice(source,first*BANDS*FEATURES,size),new long[]{count,BANDS,FEATURES},slice(output,first*BANDS*FEATURES,size),new long[]{count,BANDS,FEATURES})){b.run(session,opts);}calls++;
                }
            }else{
                FloatBuffer[] xs=new FloatBuffer[workers],ys=new FloatBuffer[workers];Bound[] bound=new Bound[workers];
                int[] firsts=new int[workers],counts=new int[workers];
                ExecutorService pool=Executors.newFixedThreadPool(workers);
                CompletionService<Integer> done=new ExecutorCompletionService<>(pool);List<Future<Integer>> futures=new ArrayList<>();
                Throwable failure=null;
                try{
                    for(int slot=0;slot<workers;slot++){xs[slot]=direct(batch*BANDS*FEATURES);ys[slot]=direct(batch*BANDS*FEATURES);bound[slot]=new Bound(xs[slot],new long[]{batch,BANDS,FEATURES},ys[slot],new long[]{batch,BANDS,FEATURES});}
                    int next=0,finished=0;
                    for(int slot=0;slot<workers&&next<FRAMES;slot++){
                        firsts[slot]=next;counts[slot]=Math.min(batch,FRAMES-next);copy(source,next*BANDS*FEATURES,xs[slot],0,counts[slot]*BANDS*FEATURES);next+=counts[slot];
                        final int at=slot;final int count=counts[slot];futures.add(done.submit(()->{runBound(session,opts,bound[at],xs[at],ys[at],count,batch);return at;}));calls++;
                    }
                    while(finished<FRAMES){int slot=done.take().get();copy(ys[slot],0,output,firsts[slot]*BANDS*FEATURES,counts[slot]*BANDS*FEATURES);finished+=counts[slot];
                        if(next<FRAMES){firsts[slot]=next;counts[slot]=Math.min(batch,FRAMES-next);copy(source,next*BANDS*FEATURES,xs[slot],0,counts[slot]*BANDS*FEATURES);next+=counts[slot];
                            final int at=slot;final int count=counts[slot];futures.add(done.submit(()->{runBound(session,opts,bound[at],xs[at],ys[at],count,batch);return at;}));calls++;
                        }
                    }
                }catch(Throwable t){failure=t;opts.setTerminate(true);}
                finally{
                    pool.shutdown();while(!pool.awaitTermination(1,TimeUnit.SECONDS)){}
                    for(Future<Integer> f:futures)try{f.get();}catch(Throwable t){if(failure==null)failure=t;else if(failure!=t)failure.addSuppressed(t);}
                    for(Bound b:bound)if(b!=null)try{b.close();}catch(Throwable t){if(failure==null)failure=t;else failure.addSuppressed(t);}
                }
                if(failure!=null)throw new RuntimeException(failure);
            }
        }
        long wall=System.nanoTime()-start,cpu=cpu()-cpuStart;
        System.out.println("{\"phase\":\""+phase+"\",\"round\":"+round+",\"batch\":"+batch+",\"workers\":"+workers+",\"calls\":"+calls+",\"wallNanos\":"+wall+",\"processCpuNanos\":"+cpu+",\"peakRssBytes\":"+rss()+",\"outputSha256\":\""+hash(output)+"\",\"finite\":true}");
    }
    static void runBound(OrtSession session,OrtSession.RunOptions opts,Bound bound,FloatBuffer x,FloatBuffer y,int count,int batch)throws Exception{
        if(count==batch)bound.run(session,opts);
        else try(Bound tail=new Bound(slice(x,0,count*BANDS*FEATURES),new long[]{count,BANDS,FEATURES},slice(y,0,count*BANDS*FEATURES),new long[]{count,BANDS,FEATURES})){tail.run(session,opts);}
    }
    public static void main(String[] args)throws Exception{
        if(!ENV.getVersion().equals("1.25.1"))throw new IllegalStateException("Pinned runtime required");
        if(args[0].equals("prepare"))prepare(Path.of(args[1]),Path.of(args[2]),Path.of(args[3]));
        else measure(Path.of(args[1]),Path.of(args[2]),Integer.parseInt(args[3]),Integer.parseInt(args[4]),Integer.parseInt(args[5]),args[6]);
    }
}
