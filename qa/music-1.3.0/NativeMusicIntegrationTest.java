package com.cyberbasslord.lightforge;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.zip.*;
import org.json.*;
/** Executes the actual APK export validator on the actual browser-generated USB archive. */
public final class NativeMusicIntegrationTest {
 public static void main(String[] args)throws Exception{
  File root=new File(args[1]);root.mkdirs();
  try(ZipFile z=new ZipFile(args[0])){
   for(String name:Arrays.asList("lightshow.fseq","lightshow.wav")){
    try(InputStream in=z.getInputStream(z.getEntry("LightShow/"+name))){Files.copy(in,new File(root,name).toPath(),StandardCopyOption.REPLACE_EXISTING);}
   }
  }
  JSONObject report=MainActivity.verifySequence(new File(root,"lightshow.fseq"),new File(root,"lightshow.wav"));
  if(!"PASS".equals(report.getString("status")))throw new AssertionError(report.toString());
  System.out.println(report.toString(2));
 }
}
