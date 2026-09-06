package com.cyberbasslord.lightforge;

import java.io.*;
import java.nio.*;
import java.nio.file.*;
import java.util.*;

/** Host verification of the exact Java PCM/resampling/export code shipped in APK. */
public final class NativeAudioTest {
    static void require(boolean result,String message){if(!result)throw new AssertionError(message);}
    static void tone(File dir,String name,int rate,double frequency,int block)throws Exception{
        dir.mkdirs();int total=rate*3+137;float[] buffer=new float[block*2];
        try(WavConverter c=new WavConverter(new File(dir,name+".wav"),new File(dir,name+"-analysis.wav"),rate)){
            for(int n=0;n<total;){int count=Math.min(block,total-n);
                for(int j=0;j<count;j++){float v=(float)(.5*Math.sin(2*Math.PI*frequency*(n+j)/rate));buffer[j*2]=v;buffer[j*2+1]=v;}
                c.accept(buffer,count);n+=count;
            }c.finish();
        }
    }
    static double[] samples(File f)throws Exception{
        byte[] bytes=Files.readAllBytes(f.toPath());int channels=AudioImporter.u16(bytes,22);
        require(bytes.length==AudioImporter.u32(bytes,40)+44,"WAV data length");
        ByteBuffer b=ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);double[] result=new double[(bytes.length-44)/(2*channels)];
        for(int i=0;i<result.length;i++)result[i]=b.getShort(44+i*channels*2)/32768.;return result;
    }
    static double rms(double[] values){double total=0;for(int i=1000;i<values.length-1000;i++)total+=values[i]*values[i];return Math.sqrt(total/(values.length-2000));}
    public static void main(String[] args)throws Exception{
        File dir=new File(args[0]);dir.mkdirs();
        tone(dir,"tone48000",48000,1000,4096);tone(dir,"tone48000-small",48000,1000,137);
        require(Arrays.equals(Files.readAllBytes(new File(dir,"tone48000.wav").toPath()),Files.readAllBytes(new File(dir,"tone48000-small.wav").toPath())),"Resampling must not depend on chunk boundaries");
        double[] full=samples(new File(dir,"tone48000.wav"));
        require(full.length==Math.round((48000*3+137)*44100./48000),"Resampling output duration");
        double error=0;for(int i=1000;i<full.length-1000;i++){double diff=full[i]-.5*Math.sin(2*Math.PI*1000*i/44100);error+=diff*diff;}
        error=Math.sqrt(error/(full.length-2000));require(error<.00015,"Passband fidelity and zero timing offset");
        tone(dir,"high48000",48000,17000,8192);double rejection=rms(samples(new File(dir,"high48000-analysis.wav")));
        require(rejection<.003,"Analysis anti-alias filter attenuation");
        tone(dir,"tone44100",44100,800,700);
        File copied=new File(dir,"copy.wav"),analysis=new File(dir,"copy-analysis.wav");
        AudioImporter.readWave(new File(dir,"tone44100.wav"),copied,analysis,new AudioImporter.Progress(){public void update(double v,String m){}public void check(){}});
        require(Arrays.equals(Files.readAllBytes(copied.toPath()),Files.readAllBytes(new File(dir,"tone44100.wav").toPath())),"44.1 kHz stereo input preserves sample bytes");
        if(args.length>=3){System.out.println(MainActivity.verifySequence(new File(args[1]),new File(args[2])).toString());
            byte[] damaged=Files.readAllBytes(new File(args[1]).toPath());damaged[20]=1;File bad=new File(dir,"bad.fseq");Files.write(bad.toPath(),damaged);
            boolean rejected=false;try{MainActivity.verifySequence(bad,new File(args[2]));}catch(IOException expected){rejected=true;}require(rejected,"Reject compressed/malformed FSEQ");}
        System.out.println("PASS: chunk invariance, exact sample duration, passband RMSE="+error+", analysis alias RMS="+rejection+", PCM byte preservation"+(args.length>=3?", exported FSEQ verification":"")+".");
    }
}
