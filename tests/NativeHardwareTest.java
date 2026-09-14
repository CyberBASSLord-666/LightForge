package com.cyberbasslord.lightforge;
import java.io.*;
import java.nio.file.*;
import java.util.*;

/** Host check of production verifySequence; no Android codec or vehicle invoked. */
public final class NativeHardwareTest {
    static int checks=0;
    static void require(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    interface Mutation {void apply(byte[] data,int offset,int step);}
    static void reject(File root,String fixture,String label,Mutation mutate,String message)throws Exception{
        byte[] data=Files.readAllBytes(new File(root,fixture+".fseq").toPath());
        int offset=AudioImporter.u16(data,4),step=data[18]&255;mutate.apply(data,offset,step);
        File bad=new File(root,"invalid-"+label+".fseq");Files.write(bad.toPath(),data);
        try{MainActivity.verifySequence(bad,new File(root,fixture+".wav"));throw new AssertionError("Accepted "+label);}
        catch(IOException expected){require(expected.getMessage().contains(message),label+": "+expected.getMessage());}
    }
    static void paint(byte[] data,int offset,int step,int ch,double a,double b,int value){
        for(int f=(int)Math.round(a*1000/step);f<(int)Math.round(b*1000/step);f++)data[offset+f*200+ch-1]=(byte)value;
    }
    public static void main(String[] args)throws Exception{
        File root=new File(args[0]);
        for(String name:Arrays.asList("stop-and-close","all-closures","all-lamps","outer-ramp","precision-15"))
            require("PASS".equals(MainActivity.verifySequence(new File(root,name+".fseq"),new File(root,name+".wav")).getString("status")),name);
        reject(root,"all-lamps","boolean",(d,o,s)->paint(d,o,s,25,1,2,99),"on/off lamp");
        reject(root,"all-lamps","ramp",(d,o,s)->paint(d,o,s,3,1,2,99),"ramp command");
        reject(root,"all-lamps","fog",(d,o,s)->paint(d,o,s,15,1,2,255),"fog lamp absent");
        reject(root,"all-lamps","rear-fog",(d,o,s)->paint(d,o,s,29,1,2,255),"fog lamp absent");
        reject(root,"all-lamps","mirror-dance",(d,o,s)->paint(d,o,s,35,1,2,127),"not Dance");
        reject(root,"all-lamps","window-budget",(d,o,s)->{for(int i=0;i<7;i++)paint(d,o,s,37,1+i*5,1.02+i*5,i%2==0?63:191);},"command or 30-second");
        reject(root,"all-lamps","dance-budget",(d,o,s)->{paint(d,o,s,37,1,32,127);paint(d,o,s,37,33,33.02,191);},"command or 30-second");
        reject(root,"all-lamps","trunk-preparation",(d,o,s)->paint(d,o,s,41,1,2,127),"fully before");
        reject(root,"stop-and-close","partial-stop",(d,o,s)->paint(d,o,s,41,12,12.02,0),"finish closed");
        reject(root,"all-lamps","unsupported-door",(d,o,s)->paint(d,o,s,42,1,2,63),"unsupported by your Model 3");
        reject(root,"all-lamps","reserved",(d,o,s)->paint(d,o,s,194,1,2,255),"Reserved channel");
        reject(root,"all-lamps","final-frame",(d,o,s)->d[d.length-200]=(byte)255,"settle all channels");
        reject(root,"all-lamps","invalid-step",(d,o,s)->d[18]=14,"header is invalid");
        reject(root,"all-lamps","precision-step",(d,o,s)->d[18]=25,"header is invalid");
        System.out.println("PASS: "+checks+" production native sequence checks; valid manual Stop/Idle, all closures, all lamps/RGB, and optional outer ramps; corrupt commands and impossible choreography rejected.");
    }
}
