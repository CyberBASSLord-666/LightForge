package com.cyberbasslord.lightforge;
import java.io.*;import java.nio.*;import java.nio.file.*;import java.util.*;
public final class RepairAuditTest {
 static void check(boolean b,String m){if(!b)throw new AssertionError(m);}
 static void valid(File a,int rate,int channels)throws Exception{byte[] b=Files.readAllBytes(a.toPath());check(AudioImporter.u32(b,4)+8==b.length && AudioImporter.u32(b,40)+44==b.length,"complete output");check(AudioImporter.u32(b,24)==rate && AudioImporter.u16(b,22)==channels,"canonical output");}
 static void noTemp(File d){for(File f:d.listFiles())check(!f.getName().startsWith(".repair-"),"temporary cleanup");}
 public static void main(String[]args)throws Exception{
  File dir=new File(args[0]);dir.mkdirs();File input=new File(dir,"original.wav"),audio=new File(dir,"audio.wav"),analysis=new File(dir,"analysis.wav");
  Files.write(input.toPath(),ImportAuditTest.wave(48000,2,24,false,true,960137,0));
  AudioImporter.readWave(input,audio,analysis,new AudioImporter.Progress(){public void check(){}public void update(double f,String m){}});
  byte[] original=Files.readAllBytes(audio.toPath()),good=Files.readAllBytes(analysis.toPath());Files.write(new File(dir,"project.json").toPath(),"preserve editable project".getBytes("UTF-8"));
  long timestamp=analysis.lastModified();check(!ProjectStore.ensureAnalysis(dir,null),"valid analysis unchanged");check(timestamp==analysis.lastModified(),"good file not replaced");
  try(RandomAccessFile f=new RandomAccessFile(analysis,"rw")){f.setLength(f.length()-37);}
  check(ProjectStore.ensureAnalysis(dir,null),"truncated analysis repaired");valid(analysis,22050,1);noTemp(dir);
  analysis.delete();check(ProjectStore.ensureAnalysis(dir,null),"missing analysis repaired");valid(analysis,22050,1);
  byte[] malformed=Files.readAllBytes(analysis.toPath());malformed[32]=4;Files.write(analysis.toPath(),malformed);check(ProjectStore.ensureAnalysis(dir,null),"bad block alignment repaired");
  malformed=Files.readAllBytes(analysis.toPath());malformed[24]=99;Files.write(analysis.toPath(),malformed);check(ProjectStore.ensureAnalysis(dir,null),"wrong sample rate repaired");
  byte[] shortComplete=Arrays.copyOf(good,good.length-1000);ByteBuffer.wrap(shortComplete).order(ByteOrder.LITTLE_ENDIAN).putInt(4,shortComplete.length-8).putInt(40,shortComplete.length-44);Files.write(analysis.toPath(),shortComplete);check(ProjectStore.ensureAnalysis(dir,null),"internally complete but wrong duration repaired");
  Files.write(analysis.toPath(),new byte[]{0,0,0});boolean cancelled=false;try{ProjectStore.ensureAnalysis(dir,new AudioImporter.Progress(){int n;public void update(double f,String m){}public void check()throws IOException{if(++n>2)throw new IOException("Cancelled");}});}catch(IOException expected){cancelled=true;}
  check(cancelled,"repair cancellation");check(analysis.length()==3,"cancelled repair leaves prior file intact");noTemp(dir);check(ProjectStore.ensureAnalysis(dir,null),"retry repair after cancellation");
  check(Arrays.equals(original,Files.readAllBytes(audio.toPath())),"playback remains byte exact");check(new String(Files.readAllBytes(new File(dir,"project.json").toPath()),"UTF-8").equals("preserve editable project"),"settings untouched");
  int channelCases=0;for(int channels=3;channels<=8;channels++)for(int i=0;i<channels;i++){float[] solo=new float[channels],stereo=new float[2];solo[i]=1;AudioImporter.downmix(solo,stereo,0);check(stereo[0]!=0 || stereo[1]!=0,"every canonical surround channel retained");channelCases++;}
  float[] masked=new float[2];AudioImporter.downmix(new float[]{0,0,0,1},masked,0,15);check(masked[0]>0 && masked[1]>0,"explicit 3.1 LFE reaches both channels");AudioImporter.downmix(new float[]{0,0,0,1},masked,0,51);check(masked[0]==0 && masked[1]>0,"explicit quad back-right stays right");
  try(RandomAccessFile f=new RandomAccessFile(audio,"rw")){f.setLength(f.length()-4);}byte[] before=Files.readAllBytes(analysis.toPath());boolean rejected=false;try{ProjectStore.ensureAnalysis(dir,null);}catch(IOException expected){rejected=true;}check(rejected,"truncated playback rejected");check(Arrays.equals(before,Files.readAllBytes(analysis.toPath())),"bad playback never destroys analysis");
  int pcmCases=0;for(int channels:new int[]{1,2,6})for(int encoding:new int[]{2,3,4,21,22}){
   int width=encoding==3?1:encoding==2?2:encoding==21?3:4,count=48017;byte[] pcm=new byte[count*channels*width];new Random(121+encoding).nextBytes(pcm);
   if(encoding==4){ByteBuffer b=ByteBuffer.wrap(pcm).order(ByteOrder.nativeOrder());for(int i=0;i<count*channels;i++)b.putFloat((float)Math.sin(i*.02)*.2f);}
   for(int chunk:new int[]{pcm.length,137}){
    File full=new File(dir,"chunks-"+chunk+".wav"),mono=new File(dir,"chunks-"+chunk+"-analysis.wav");AudioImporter.PcmFrames reader=new AudioImporter.PcmFrames(channels,encoding);
    try(WavConverter writer=new WavConverter(full,mono,48000)){for(int at=0;at<pcm.length;at+=chunk){int n=Math.min(chunk,pcm.length-at);reader.accept(ByteBuffer.wrap(pcm,at,n).slice().order(ByteOrder.nativeOrder()),writer);}reader.finish();writer.finish();}
   }
   check(Arrays.equals(Files.readAllBytes(new File(dir,"chunks-"+pcm.length+".wav").toPath()),Files.readAllBytes(new File(dir,"chunks-137.wav").toPath())),"decoder byte fragments preserve PCM "+channels+" / "+encoding);pcmCases++;
  }
  AudioImporter.PcmFrames reader=new AudioImporter.PcmFrames(2,2);try(WavConverter c=new WavConverter(new File(dir,"partial.wav"),new File(dir,"partial-analysis.wav"),44100)){reader.accept(ByteBuffer.wrap(new byte[]{1,2,3}).order(ByteOrder.nativeOrder()),c);rejected=false;try{reader.finish();}catch(IOException expected){rejected=true;}check(rejected,"partial decoder frame rejected");}
  System.out.println("{\"derivedRepairCasesPassed\":10,\"validFilesUnchanged\":true,\"playbackAndSettingsPreserved\":true,\"cancelCleanupAndRetry\":true,\"decoderFragmentCasesPassed\":"+pcmCases+",\"surroundSoloCasesPassed\":"+channelCases+",\"explicitChannelMasksPassed\":2,\"incompleteDecoderFrameRejected\":true}");
 }
}
