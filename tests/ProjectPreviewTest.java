package com.cyberbasslord.lightforge;
import java.io.*;
import org.json.JSONObject;
public final class ProjectPreviewTest {
 public static void main(String[] args)throws Exception {
  File file=File.createTempFile("lightforge-preview-", ".wav");int checks=0;
  try(RandomAccessFile disk=new RandomAccessFile(file,"rw")) {
   for(long bytes:new long[]{1044,Integer.MAX_VALUE,Integer.MAX_VALUE+1L,44100L*4*14400+44}) {
    disk.setLength(bytes);
    JSONObject metadata=new JSONObject().put("audioUrl","/project/example/audio.wav").put("analysisUrl","/project/example/analysis.wav").put("duration",14400).put("name","Saved show");
    JSONObject result=ProjectPreview.metadata(metadata,file);boolean proxy=bytes>Integer.MAX_VALUE;
    if(!result.getString("previewUrl").equals(metadata.getString(proxy?"analysisUrl":"audioUrl")))throw new AssertionError("Wrong preview audio");checks++;
    if(result.getInt("previewSampleRate")!=(proxy?22050:44100)||result.getInt("previewChannels")!=(proxy?1:2))throw new AssertionError("Wrong preview format");checks++;
    if(!result.getString("audioUrl").equals("/project/example/audio.wav")||file.length()!=bytes)throw new AssertionError("Original export audio changed");checks++;
    if(!result.getString("name").equals("Saved show")||result.getDouble("duration")!=14400)throw new AssertionError("Project metadata changed");checks++;
   }
  }finally{if(!file.delete())throw new IOException("Temporary sparse file could not be removed");}
  System.out.println("{\"result\":\"PASS\",\"checks\":"+checks+",\"threshold\":2147483647,\"longTrackPreview\":\"22050 Hz mono\",\"export\":\"44100 Hz stereo unchanged\"}");
 }
}
