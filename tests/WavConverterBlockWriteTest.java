package com.cyberbasslord.lightforge;

import java.io.*;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;

/** Exact streaming comparisons with the frozen pre-batching converter. */
public final class WavConverterBlockWriteTest {
    interface Converter extends AutoCloseable {
        void accept(float[] values,int frames)throws Exception;
        double finish()throws Exception;
        void close()throws IOException;
    }
    static Converter converter(boolean reference,File audio,File analysis,int rate)throws Exception {
        if(reference) {
            final FrozenWavConverter value=new FrozenWavConverter(audio,analysis,rate);
            return new Converter(){public void accept(float[] v,int n)throws Exception{value.accept(v,n);}
                public double finish()throws Exception{return value.finish();}public void close()throws IOException{value.close();}};
        }
        final WavConverter value=new WavConverter(audio,analysis,rate);
        return new Converter(){public void accept(float[] v,int n)throws Exception{value.accept(v,n);}
            public double finish()throws Exception{return value.finish();}public void close()throws IOException{value.close();}};
    }
    static float[] fixture(int frames) {
        float[] values=new float[frames*2];int random=0x13579bdf;
        for(int i=0;i<values.length;i++) {
            random^=random<<13;random^=random>>>17;random^=random<<5;
            values[i]=(float)(random/2147483648.0*1.2);
        }
        return values;
    }
    static void exceptionalSamples(float[] values) {
        float[] edges={Float.NaN,Float.POSITIVE_INFINITY,Float.NEGATIVE_INFINITY,-0f,0f,
            Float.MIN_VALUE,-Float.MIN_VALUE,Float.MAX_VALUE,-Float.MAX_VALUE,1f,-1f,
            .5f/32768,-.5f/32768,32767f/32768,-32768f/32768};
        for(int i=0;i<Math.min(values.length,edges.length);i++)values[i]=edges[i];
    }
    static double convert(boolean reference,Path root,int rate,float[] values,int block,boolean finish)throws Exception {
        Path dir=root.resolve(reference?"reference":"candidate");Files.createDirectories(dir);
        float[] buffer=new float[block*2];double seconds=0;
        try(Converter value=converter(reference,dir.resolve("audio.wav").toFile(),dir.resolve("analysis.wav").toFile(),rate)) {
            for(int first=0;first<values.length/2;) {
                int count=Math.min(block,values.length/2-first);
                System.arraycopy(values,first*2,buffer,0,count*2);value.accept(buffer,count);first+=count;
            }
            if(finish) {
                seconds=value.finish();
                if(Double.doubleToRawLongBits(seconds)!=Double.doubleToRawLongBits(value.finish()))
                    throw new AssertionError("Repeated finish changed the source clock");
            }
            value.close(); // The outer close must remain harmless.
        }
        return seconds;
    }
    static String compare(Path root,String name)throws Exception {
        Path a=root.resolve("reference").resolve(name),b=root.resolve("candidate").resolve(name);
        if(Files.size(a)!=Files.size(b))throw new AssertionError("WAV size differs: "+name);
        MessageDigest hash=MessageDigest.getInstance("SHA-256");byte[] left=new byte[65536],right=new byte[65536];
        try(InputStream source=Files.newInputStream(a);DataInputStream candidate=new DataInputStream(Files.newInputStream(b))) {
            int count;
            while((count=source.read(left))!=-1) {
                candidate.readFully(right,0,count);
                for(int i=0;i<count;i++)if(left[i]!=right[i])throw new AssertionError("WAV byte differs: "+name);
                hash.update(left,0,count);
            }
            if(candidate.read()!=-1)throw new AssertionError("WAV contains extra bytes");
        }
        StringBuilder text=new StringBuilder();for(byte value:hash.digest())text.append(String.format("%02x",value&255));
        return text.toString();
    }
    static int check(Path root)throws Exception {
        int cases=0;
        for(int rate:new int[]{8000,22050,44100,48000,96000,192000,384000}) {
            for(int block:new int[]{137,4096,32768}) {
                float[] values=fixture(rate/3+137);exceptionalSamples(values);
                double before=convert(true,root,rate,values,block,true),after=convert(false,root,rate,values,block,true);
                if(Double.doubleToRawLongBits(before)!=Double.doubleToRawLongBits(after))throw new AssertionError("Source clock differs");
                compare(root,"audio.wav");compare(root,"analysis.wav");cases++;
            }
        }
        // Empty/tiny inputs, both PCM block boundaries and incomplete final
        // blocks exercise finish and early-close flushing without a full song.
        for(int frames:new int[]{0,1,137,4095,4096,4097,8191,8192,8193,16384,16385}) {
            for(boolean finish:new boolean[]{false,true}) {
                float[] values=fixture(frames);exceptionalSamples(values);
                convert(true,root,44100,values,137,finish);convert(false,root,44100,values,137,finish);
                compare(root,"audio.wav");compare(root,"analysis.wav");cases++;
            }
        }
        return cases;
    }
    static String benchmark(Path root,int seconds)throws Exception {
        StringBuilder rows=new StringBuilder("[");
        for(int rate:new int[]{44100,48000,96000}) {
            float[] values=fixture(rate*seconds);
            convert(true,root,rate,values,4096,true);convert(false,root,rate,values,4096,true);
            long[] reference=new long[3],candidate=new long[3];
            for(int pair=0;pair<3;pair++) {
                for(int order=0;order<2;order++) {
                    boolean baseline=pair%2==0?order==0:order!=0;
                    long start=System.nanoTime();convert(baseline,root,rate,values,4096,true);
                    (baseline?reference:candidate)[pair]=System.nanoTime()-start;
                }
                compare(root,"audio.wav");compare(root,"analysis.wav");
            }
            long[] sortedReference=reference.clone(),sortedCandidate=candidate.clone();
            Arrays.sort(sortedReference);Arrays.sort(sortedCandidate);
            if(rows.length()>1)rows.append(',');
            rows.append("{\"source_rate\":").append(rate).append(",\"source_seconds\":").append(seconds)
                .append(",\"reference_ns\":").append(Arrays.toString(reference))
                .append(",\"candidate_ns\":").append(Arrays.toString(candidate))
                .append(",\"median_reduction_percent\":").append(100.0*(1-sortedCandidate[1]/(double)sortedReference[1]))
                .append(",\"audio_sha256\":\"").append(compare(root,"audio.wav"))
                .append("\",\"analysis_sha256\":\"").append(compare(root,"analysis.wav")).append("\"}");
        }
        return rows.append(']').toString();
    }
    public static void main(String[] args)throws Exception {
        Path root=Paths.get(args[0]);Files.createDirectories(root);int cases=check(root);
        String rows=args.length>1?benchmark(root,Integer.parseInt(args[1])):"[]";
        System.out.println("{\"schema\":\"lightforge.wav-block-write-host.v1\",\"differential_cases\":"+cases+
            ",\"byte_identical\":true,\"outputs_per_case\":2,\"benchmark\":"+rows+"}");
    }
}
