package com.cyberbasslord.lightforge;
import java.io.*;
import java.nio.*;
import java.nio.file.*;
import java.util.*;
public final class ImportAuditTest {
 static void check(boolean b,String m){if(!b)throw new AssertionError(m);}
 static byte[] wave(int rate,int channels,int bits,boolean fp,boolean extensible,int frames,int incomplete)throws Exception{
  ByteArrayOutputStream chunks=new ByteArrayOutputStream(); chunks.write("JUNK".getBytes("US-ASCII"));WavConverter.le32(chunks,3);chunks.write(new byte[]{1,2,3,0});
  chunks.write("fmt ".getBytes("US-ASCII"));WavConverter.le32(chunks,extensible?40:16);WavConverter.le16(chunks,extensible?65534:fp?3:1);WavConverter.le16(chunks,channels);WavConverter.le32(chunks,rate);WavConverter.le32(chunks,rate*channels*bits/8);WavConverter.le16(chunks,channels*bits/8);WavConverter.le16(chunks,bits);
  if(extensible){WavConverter.le16(chunks,22);WavConverter.le16(chunks,bits);WavConverter.le32(chunks,channels==1?4:3);WavConverter.le32(chunks,fp?3:1);chunks.write(new byte[]{0,0,16,0,(byte)128,0,0,(byte)170,0,56,(byte)155,113});}
  int bytes=frames*channels*bits/8+incomplete;chunks.write("data".getBytes("US-ASCII"));WavConverter.le32(chunks,bytes);
  ByteBuffer pcm=ByteBuffer.allocate(bytes).order(ByteOrder.LITTLE_ENDIAN);
  for(int i=0;i<frames;i++)for(int c=0;c<channels;c++){double a=.5*Math.sin(2*Math.PI*257*i/rate)*(c==0?1:.8);if(fp)pcm.putFloat((float)a);else if(bits==8)pcm.put((byte)(128+Math.round(a*128)));else if(bits==16)pcm.putShort((short)Math.round(a*32768));else if(bits==24){int n=(int)Math.round(a*8388608);pcm.put((byte)n);pcm.put((byte)(n>>>8));pcm.put((byte)(n>>>16));}else pcm.putInt((int)Math.round(a*2147483648L));}
  chunks.write(pcm.array());if((bytes&1)!=0)chunks.write(0);ByteArrayOutputStream all=new ByteArrayOutputStream();all.write("RIFF".getBytes("US-ASCII"));WavConverter.le32(all,chunks.size()+4);all.write("WAVE".getBytes("US-ASCII"));all.write(chunks.toByteArray());return all.toByteArray();
 }
 static long inspect(File f,int rate,int channels)throws Exception{byte[] bytes=Files.readAllBytes(f.toPath());check(new String(bytes,0,4,"US-ASCII").equals("RIFF"),"RIFF");check(AudioImporter.u32(bytes,4)+8==bytes.length,"RIFF byte size");check(AudioImporter.u32(bytes,40)+44==bytes.length,"data byte size");check(AudioImporter.u32(bytes,24)==rate,"output rate");check(AudioImporter.u16(bytes,22)==channels,"output channels");check(AudioImporter.u16(bytes,34)==16,"output bits");return(bytes.length-44)/(2*channels);}
 public static void main(String[] args)throws Exception{File dir=new File(args[0]);dir.mkdirs();AudioImporter.Progress quiet=new AudioImporter.Progress(){public void update(double v,String m){}public void check(){}};int cases=0;double worstDelta=0;
  for(int rate:new int[]{8000,22050,44100,48000,96000,384000})for(int channels:new int[]{1,2})for(int format:new int[]{8,16,24,32,132}){
   int bits=format==132?32:format,frames=rate+137;File input=new File(dir,"input.wav"),audio=new File(dir,"audio.wav"),analysis=new File(dir,"analysis.wav");Files.write(input.toPath(),wave(rate,channels,bits,format==132,(cases%2)==0,frames,0));Double duration=AudioImporter.readWave(input,audio,analysis,quiet);check(duration!=null,"direct decoded");long af=inspect(audio,44100,2),nf=inspect(analysis,22050,1);check(af==Math.round(frames*44100./rate),"playback frame count");check(nf==Math.round(frames*22050./rate),"analysis frame count");check(duration==af/44100.,"metadata uses playback duration");worstDelta=Math.max(worstDelta,Math.abs(af/44100.-nf/22050.));cases++;
  }
  File input=new File(dir,"partial-frame.wav"),audio=new File(dir,"partial-output.wav"),analysis=new File(dir,"partial-analysis.wav");Files.write(input.toPath(),wave(48000,2,16,false,false,48137,1));boolean rejected=false;try{AudioImporter.readWave(input,audio,analysis,quiet);}catch(IOException expected){rejected=true;}
  System.out.println("{\"pcmCases\":"+cases+",\"validHeadersAndExactSampleCounts\":true,\"maxPlaybackAnalysisDurationDifference\":"+worstDelta+",\"partialSourceFrameRejected\":"+rejected+",\"compressedAndroidCodecExecution\":\"Unavailable in host JVM; Android framework stubs\"}");
 }
}
