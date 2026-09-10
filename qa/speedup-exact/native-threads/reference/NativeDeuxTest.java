package com.cyberbasslord.lightforge;

import java.io.*;
import java.nio.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;

/** Native studio source-clock, PCM, cancellation, and optional full-model verification. */
public final class NativeDeuxTest {
    private static final NativeDeuxTransform.Check CHECK=()->{};
    public static void main(String[] args) throws Exception {
        if(args.length>=3){inference(args);return;}
        wav();roundTrip();
        System.out.println("NativeDeux: stereo WAVE, zero padding, source-clock reconstruction, stereo averaging, invalid input and cancellation checks passed.");
    }
    private static void wav() throws Exception {
        File dir=Files.createTempDirectory("deux-wav-test-").toFile(),file=new File(dir,"source.wav");
        try {
            try(FileOutputStream out=new FileOutputStream(file)) {
                out.write("RIFF".getBytes("US-ASCII"));le32(out,56);out.write("WAVE".getBytes("US-ASCII"));
                out.write("JUNK".getBytes("US-ASCII"));le32(out,3);out.write(new byte[]{1,2,3,0});
                out.write("fmt ".getBytes("US-ASCII"));le32(out,16);le16(out,1);le16(out,2);le32(out,44100);le32(out,176400);le16(out,4);le16(out,16);
                out.write("data".getBytes("US-ASCII"));le32(out,8);le16(out,16384);le16(out,-8192);le16(out,32767);le16(out,-32768);
            }
            float[][] padded=NativeDeuxTransform.readStereo(file,-1,CHECK);
            require(padded[0].length==573300&&padded[0][0]==0&&padded[0][1]==.5f&&padded[1][1]==-.25f&&padded[0][2]==32767/32768f&&padded[1][2]==-1&&padded[0][3]==0,"WAVE stereo/source offset");
            float[][] end=NativeDeuxTransform.readStereo(file,1,CHECK);
            require(end[1][0]==-1&&end[0][1]==0,"end zero padding");
            try{NativeDeuxTransform.readStereo(file,0,()->{throw new InterruptedIOException();});throw new AssertionError("cancel ignored");}catch(InterruptedIOException expected){}
            try(RandomAccessFile out=new RandomAccessFile(file,"rw")){out.setLength(file.length()-1);}
            try{NativeDeuxTransform.readStereo(file,0,CHECK);throw new AssertionError("truncated WAVE accepted");}catch(IOException expected){}
        }finally{file.delete();dir.delete();}
    }
    private static void roundTrip() throws Exception {
        int n=NativeDeuxTransform.SAMPLES,frames=NativeDeuxTransform.FRAMES;
        float[][] stereo=new float[2][n];
        for(int i=0;i<n;i++) {
            stereo[0][i]=(float)(.21*Math.sin(2*Math.PI*111*i/44100)+.07*Math.sin(2*Math.PI*4311*i/44100));
            stereo[1][i]=(float)(.13*Math.cos(2*Math.PI*233*i/44100));
        }
        // Check physical clock at endpoints, centered-window boundaries and passage joins.
        for(int i:new int[]{0,1,440,441,1024,66150,220500,441000,n-2,n-1})stereo[0][i]=.8f;
        FloatBuffer spectrum=FloatBuffer.allocate(NativeDeuxTransform.SPECTRUM_FLOATS);
        NativeDeuxTransform transform=new NativeDeuxTransform();transform.encode(stereo,spectrum,CHECK);
        int[] indices=new int[2050],counts=new int[1025];Arrays.fill(counts,1);
        FloatBuffer mask=FloatBuffer.allocate(NativeDeuxTransform.SPECTRUM_FLOATS);
        for(int i=0;i<indices.length;i++){indices[i]=i;for(int frame=0;frame<frames;frame++)mask.put((i*frames+frame)*2,1);}
        FloatBuffer sum=FloatBuffer.allocate(NativeDeuxTransform.SPECTRUM_FLOATS);
        float[] output=transform.decode(spectrum,mask,indices,counts,sum,CHECK);
        double max=0;for(int i=0;i<n;i++)max=Math.max(max,Math.abs(output[i]-(stereo[0][i]+(double)stereo[1][i])*.5));
        require(output.length==n&&max<3e-7,"identity reconstruction/stereo average: "+max);
        mask.put(0,Float.NaN);
        try{transform.decode(spectrum,mask,indices,counts,sum,CHECK);throw new AssertionError("invalid mask accepted");}catch(IOException expected){}
        try{transform.encode(stereo,spectrum,()->{throw new InterruptedIOException();});throw new AssertionError("encode cancel ignored");}catch(InterruptedIOException expected){}
        System.out.println("Identity-mask maximum sample error="+max);
    }
    private static void inference(String[] args) throws Exception {
        File model=new File(args[0]),audio=new File(args[1]),output=new File(args[2]);
        long start=args.length>3?Long.parseLong(args[3]):0,t=System.nanoTime();
        long[] peak={0};
        Thread monitor=new Thread(()->{
            while(!Thread.currentThread().isInterrupted()) {
                try{for(String line:Files.readAllLines(Paths.get("/proc/self/status")))if(line.startsWith("VmRSS:"))peak[0]=Math.max(peak[0],Long.parseLong(line.trim().split("\\s+")[1])*1024);}catch(Exception ignored){}
                try{Thread.sleep(50);}catch(InterruptedException e){return;}
            }
        },"native-deux-memory");monitor.setDaemon(true);monitor.start();
        try(NativeDeux runner=new NativeDeux(model)) {
            int[] last={-1};runner.predict(audio,start,output,(p,message)->{int percent=(int)(p*100);if(percent>=last[0]+5){last[0]=percent;System.out.println(percent+"% "+message);}},()->false);
        }finally{monitor.interrupt();monitor.join();}
        require(output.length()==2L*573300*4,"exact native result sample count");
        MessageDigest digest=MessageDigest.getInstance("SHA-256");try(InputStream in=new FileInputStream(output)){byte[] bytes=new byte[262144];int read;while((read=in.read(bytes))!=-1)digest.update(bytes,0,read);}
        StringBuilder sha=new StringBuilder();for(byte b:digest.digest())sha.append(String.format(Locale.ROOT,"%02x",b&255));
        System.out.println("{\"seconds\":"+(System.nanoTime()-t)/1e9+",\"peakRssBytes\":"+peak[0]+",\"samplesPerStem\":573300,\"sha256\":\""+sha+"\"}");
    }
    private static void le16(OutputStream out,int value) throws IOException {out.write(value&255);out.write((value>>>8)&255);}
    private static void le32(OutputStream out,int value) throws IOException {le16(out,value);le16(out,value>>>16);}
    private static void require(boolean condition,String message){if(!condition)throw new AssertionError(message);}
}
