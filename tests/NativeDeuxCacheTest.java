package com.cyberbasslord.lightforge;

import android.content.Context;
import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.*;
import org.json.JSONObject;

/** Production cache preparation with small synthetic graph bytes; no ONNX sessions or inference. */
public final class NativeDeuxCacheTest {
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
    private static final List<String> NAMES=new ArrayList<>(Arrays.asList("front","head-0","head-1"));
    static {for(int i=0;i<12;i++){String block=String.format(Locale.ROOT,"block-%02d",i);NAMES.add(block+"-time");NAMES.add(block+"-frequency");}}
    private static String hash(byte[] bytes)throws Exception {
        StringBuilder value=new StringBuilder();
        for(byte b:MessageDigest.getInstance("SHA-256").digest(bytes))value.append(String.format(Locale.ROOT,"%02x",b&255));
        return value.toString();
    }
    private static String field(NativeInferenceProfile.Snapshot profile,String name){
        for(String token:profile.records()[0].split(" "))if(token.startsWith(name+"="))return token.substring(name.length()+1);
        throw new AssertionError("Missing profile field "+name);
    }
    private static final class Fixture implements AutoCloseable {
        final File assets,cache;
        final NativeDeux engine;
        final Map<String,byte[]> expected=new LinkedHashMap<>();
        Fixture(File root,File originalManifest)throws Exception {
            File assetRoot=new File(root,"assets");assets=new File(assetRoot,"analysis/models/deux");require(assets.mkdirs(),"Fresh asset directory required");
            JSONObject manifest=new JSONObject(new String(Files.readAllBytes(originalManifest.toPath()),StandardCharsets.UTF_8));
            JSONObject inventory=new JSONObject();
            for(int index=0;index<NAMES.size();index++){
                String filename=NAMES.get(index)+".onnx";byte[] bytes=new byte[8192+index];Arrays.fill(bytes,(byte)(index+1));
                expected.put(filename,bytes);Files.write(new File(assets,filename).toPath(),bytes);
                inventory.put(filename,new JSONObject().put("bytes",bytes.length).put("sha256",hash(bytes)));
            }
            manifest.put("files",inventory);
            Files.write(new File(assets,"manifest.json").toPath(),manifest.toString().getBytes(StandardCharsets.UTF_8));
            engine=new NativeDeux(new Context(new File(root,"app"),assetRoot));
            Field directory=NativeDeux.class.getDeclaredField("modelDirectory");directory.setAccessible(true);cache=(File)directory.get(engine);
        }
        void complete()throws Exception {
            for(Map.Entry<String,byte[]> entry:expected.entrySet())require(Arrays.equals(entry.getValue(),
                Files.readAllBytes(new File(cache,entry.getKey()).toPath())),"Cache graph was not fully materialized: "+entry.getKey());
            noPartials();
        }
        void noPartials(){
            File[] partials=cache.listFiles((parent,name)->name.endsWith(".partial"));
            require(partials!=null&&partials.length==0,"Cache preparation leaked an atomic partial");
        }
        boolean partialExists(){File[] files=cache.listFiles((parent,name)->name.endsWith(".partial"));return files!=null&&files.length>0;}
        @Override public void close(){engine.close();}
    }
    private static Object invoke(String name,Class<?>[] types,Object target,Object... args)throws Exception {
        Method method=NativeDeux.class.getDeclaredMethod(name,types);method.setAccessible(true);
        try{return method.invoke(target,args);}
        catch(InvocationTargetException wrapped){Throwable cause=wrapped.getCause();if(cause instanceof Exception)throw (Exception)cause;throw (Error)cause;}
    }
    private static NativeInferenceProfile.Snapshot preflight(Fixture fixture,NativeDeuxTransform.Check check)throws Exception {
        NativeInferenceProfile profile=new NativeInferenceProfile();NativeInferenceProfile.Timing started=NativeInferenceProfile.started();
        try{invoke("preflightCache",new Class<?>[]{NativeDeuxTransform.Check.class,NativeInferenceProfile.class},fixture.engine,check,profile);}
        finally{profile.addPreflight(NativeInferenceProfile.elapsed(started));}
        return profile.finish("completed");
    }
    private static void counts(NativeInferenceProfile.Snapshot profile,int hits,int misses){
        require(Integer.toString(hits).equals(field(profile,"cacheModelHits")),"Cache hits counted twice or after extraction");
        require(Integer.toString(misses).equals(field(profile,"cacheModelMisses")),"Cache misses counted twice or after extraction");
        require("0".equals(field(profile,"graphRecords"))&&"0".equals(field(profile,"inferenceCount"))
            &&"0".equals(field(profile,"sessionInitCount")),"Common preparation created a graph/session observation");
        require("unavailable".equals(field(profile,"modelInitWallMs"))&&"unavailable".equals(field(profile,"schedulerCalibrationWallMs")),
            "Common extraction was double-counted as graph preparation or optional calibration");
        require(!"unavailable".equals(field(profile,"preflightWallMs")),"Common preparation lost its timing");
    }
    public static void main(String[] args)throws Exception {
        File root=new File(args[0]),manifest=new File(args[1]);require(root.mkdirs(),"Fresh test directory required");
        try(Fixture fixture=new Fixture(new File(root,"cold"),manifest)){
            counts(preflight(fixture,()->{}),0,27);fixture.complete();
            NativeInferenceProfile.ModelSetup common=fixture.engine.modelSetupObservation();
            long expectedBytes=0;for(byte[] bytes:fixture.expected.values())expectedBytes+=bytes.length;
            require(common.verifiedModels==27&&common.extractionAttempts==27&&common.extractionBytesRead==expectedBytes
                &&common.existingFileChecksumAttempts==0&&common.existingFileChecksumBytesRead==0,
                "Common setup counters must report actual cold extraction rather than invented cache hits");
            // Both comparison arms must work even when the original asset copies are unavailable.
            for(String filename:fixture.expected.keySet())require(new File(fixture.assets,filename).delete(),"Remove test asset after common preparation");
            for(int arm=0;arm<2;arm++)for(String name:NAMES){
                File file=(File)invoke("model",new Class<?>[]{String.class,NativeDeuxTransform.Check.class},fixture.engine,name,(NativeDeuxTransform.Check)()->{});
                require(file.equals(new File(fixture.cache,name+".onnx")),"Timed arm resolved a different graph");
            }
            NativeInferenceProfile.ModelSetup afterArms=fixture.engine.modelSetupObservation();
            require(afterArms.extractionAttempts==common.extractionAttempts&&afterArms.extractionBytesRead==common.extractionBytesRead
                &&afterArms.existingFileChecksumAttempts==0&&afterArms.existingFileChecksumBytesRead==0,
                "Prepared model lookups in both arms must not fabricate extraction/checksum work");
            counts(preflight(fixture,()->{}),27,0);fixture.complete();
        }
        try(Fixture fixture=new Fixture(new File(root,"corrupt"),manifest)){
            counts(preflight(fixture,()->{}),0,27);
            String damaged="block-11-frequency.onnx";byte[] bytes=fixture.expected.get(damaged).clone();bytes[0]^=1;
            Files.write(new File(fixture.cache,damaged).toPath(),bytes);
            // A new engine performs fresh inventory hashing rather than trusting the old process-local set.
            fixture.engine.close();
            File assetRoot=fixture.assets.getParentFile().getParentFile().getParentFile();
            try(NativeDeux reopened=new NativeDeux(new Context(new File(root,"corrupt/app"),assetRoot))){
                NativeInferenceProfile profile=new NativeInferenceProfile();
                invoke("preflightCache",new Class<?>[]{NativeDeuxTransform.Check.class,NativeInferenceProfile.class},reopened,(NativeDeuxTransform.Check)()->{},profile);
                NativeInferenceProfile.Snapshot snapshot=profile.finish("completed");
                require("26".equals(field(snapshot,"cacheModelHits"))&&"1".equals(field(snapshot,"cacheModelMisses")),"Corrupt cache was not repaired in common preflight");
                NativeInferenceProfile.ModelSetup repaired=reopened.modelSetupObservation();
                long bytesRead=fixture.expected.get(damaged).length;for(byte[] item:fixture.expected.values())bytesRead+=item.length;
                require(repaired.existingFileChecksumAttempts==28&&repaired.existingFileChecksumBytesRead==bytesRead
                    &&repaired.extractionAttempts==1&&repaired.extractionBytesRead==fixture.expected.get(damaged).length,
                    "Repair reports every actual existing-file checksum attempt and extracted byte");
            }
            fixture.complete();
        }
        try(Fixture fixture=new Fixture(new File(root,"cancelled"),manifest)){
            boolean cancelled=false;
            try{preflight(fixture,()->{if(fixture.partialExists())throw new InterruptedIOException("test cancellation during atomic extraction");});}
            catch(InterruptedIOException expected){cancelled=true;}
            require(cancelled,"Cancellation was not observed during actual extraction");fixture.noPartials();
            NativeInferenceProfile.ModelSetup partial=fixture.engine.modelSetupObservation();
            require(partial.extractionAttempts==1&&partial.extractionBytesRead>0&&partial.verifiedModels==0,
                "Interrupted extraction records bytes already read without claiming a verified model");
            counts(preflight(fixture,()->{}),0,27);fixture.complete();
        }
        try(Fixture fixture=new Fixture(new File(root,"invalid-asset"),manifest)){
            String damaged="block-11-frequency.onnx";byte[] bytes=fixture.expected.get(damaged).clone();bytes[0]^=1;
            Files.write(new File(fixture.assets,damaged).toPath(),bytes);boolean rejected=false;
            try{preflight(fixture,()->{});}catch(IOException expected){rejected=true;}
            require(rejected&&!new File(fixture.cache,damaged).exists(),"Corrupt final graph reached a comparison-ready cache");fixture.noPartials();
            Files.write(new File(fixture.assets,damaged).toPath(),fixture.expected.get(damaged));
            counts(preflight(fixture,()->{}),26,1);fixture.complete();
        }
        System.out.println("production NativeDeux common-cache extraction, repair, cancellation and no-double-count checks passed; no neural execution");
    }
}
