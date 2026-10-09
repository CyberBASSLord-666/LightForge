package com.cyberbasslord.lightforge;
import java.io.*;
import java.lang.reflect.Field;
import java.nio.file.*;
import java.util.*;

/** Failure injection into real resource owners; no Android codec/phone claim. */
public final class AndroidResourceCleanupTest {
    static int checks;
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);checks++;}
    static Object get(Object value,String name)throws Exception{Field field=value.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(value);}
    static final class FailingOutput extends OutputStream {
        final IOException failure;boolean closed;
        FailingOutput(String message){failure=new IOException(message);}
        public void write(int value){}
        public void close()throws IOException{closed=true;throw failure;}
    }
    static void replaceOutput(Object sink,OutputStream replacement)throws Exception{
        ((OutputStream)get(sink,"out")).close();Field out=sink.getClass().getDeclaredField("out");out.setAccessible(true);out.set(sink,replacement);
    }
    public static void main(String[] args)throws Exception{
        List<String> closed=new ArrayList<>();IOException converter=new IOException("converter"),codec=new IOException("codec");Error extractor=new AssertionError("extractor");
        try{AudioImporter.closeResources(()->{closed.add("converter");throw converter;},()->{closed.add("codec");throw codec;},()->{closed.add("extractor");throw extractor;});throw new AssertionError("cleanup error swallowed");}
        catch(IOException failure){check(failure==converter,"first cleanup error replaced");check(Arrays.equals(failure.getSuppressed(),new Throwable[]{codec,extractor}),"secondary cleanup errors missing");}
        check(closed.equals(Arrays.asList("converter","codec","extractor")),"cleanup skipped a resource");
        IOException original=new IOException("decode");
        try(AutoCloseable cleanup=()->AudioImporter.closeResources(()->{throw converter;},null,null)){throw original;}
        catch(IOException failure){check(failure==original&&failure.getSuppressed()[0]==converter,"decode failure lost during cleanup");}
        AudioImporter.closeResources(null,null,null);checks++;
        Path root=Files.createTempDirectory("wav-cleanup-");
        try{
            File audio=root.resolve("audio.wav").toFile(),analysis=root.resolve("analysis.wav").toFile();
            WavConverter wav=new WavConverter(audio,analysis,44100);
            FailingOutput first=new FailingOutput("audio"),second=new FailingOutput("analysis");
            replaceOutput(get(wav,"audio"),first);replaceOutput(get(wav,"analysis"),second);
            try{wav.close();throw new AssertionError("sink failure swallowed");}
            catch(IOException failure){check(failure==first.failure&&failure.getSuppressed()[0]==second.failure,"sink failure chain replaced");}
            check(first.closed&&second.closed,"failed first sink prevented second close");
            // Constructor cannot return its owner when the second sink fails.
            // On Linux, inspect this exact file's open descriptors, not process totals.
            File descriptors=new File("/proc/self/fd");
            if(descriptors.isDirectory()){
                long before=openDescriptors(descriptors,audio.toPath());
                for(int i=0;i<16;i++)try{new WavConverter(audio,root.toFile(),44100);throw new AssertionError("directory accepted as WAV");}catch(IOException expected){}
                check(openDescriptors(descriptors,audio.toPath())==before,"second sink failure leaked first sink descriptors");
            }
            System.out.println("PASS: "+checks+" production Android resource cleanup checks");
        }finally{for(File child:root.toFile().listFiles())child.delete();Files.delete(root);}
    }
    static long openDescriptors(File descriptors,Path target)throws Exception{
        long count=0;for(File file:descriptors.listFiles())try{if(Files.readSymbolicLink(file.toPath()).equals(target))count++;}catch(IOException vanished){}return count;
    }
}
