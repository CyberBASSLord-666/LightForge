package com.cyberbasslord.lightforge;

import ai.onnxruntime.OrtEnvironment;
import org.json.*;
import java.io.*;
import java.nio.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** Research-only complete-source runner; original NativeDeux and transforms are unchanged. */
public final class DeuxSourceRunner {
    private static final int RATE=44100, SAMPLES=573300, HALO=66150, CORE=441000, STRIDE=220500, MAX=64*RATE;

    private static String hash(byte[] data)throws Exception {
        byte[] digest=MessageDigest.getInstance("SHA-256").digest(data);StringBuilder result=new StringBuilder();
        for(byte x:digest)result.append(String.format(Locale.ROOT,"%02x",x&255));return result.toString();
    }
    private static String hashFile(Path path)throws Exception {return hash(Files.readAllBytes(path));}
    private static void write(Path path,JSONObject value)throws Exception {
        Path temporary=path.resolveSibling(path.getFileName()+".partial");
        Files.write(temporary,(value.toString(2)+"\n").getBytes(StandardCharsets.UTF_8),StandardOpenOption.CREATE_NEW);
        Files.move(temporary,path); // Fresh evidence only; never replace a result.
    }
    private static Set<String> graphs(){
        Set<String> names=new TreeSet<>(Arrays.asList("front","head-0","head-1"));
        for(int i=0;i<12;i++)for(String axis:Arrays.asList("time","frequency"))
            names.add(String.format(Locale.ROOT,"block-%02d-%s",i,axis));
        return names;
    }
    private static void moveTraces(Path source,Path destination)throws Exception {
        Files.createDirectory(destination);List<Path> paths=new ArrayList<>();
        try(DirectoryStream<Path> stream=Files.newDirectoryStream(source)){for(Path path:stream)paths.add(path);}
        if(paths.size()!=27)throw new IOException("Exactly 27 completed passage traces required");
        for(String graph:graphs()){
            Path found=null;
            for(Path path:paths)if(path.getFileName().toString().startsWith(graph+"_")&&path.toString().endsWith(".json")){
                if(found!=null||Files.isSymbolicLink(path)||!Files.isRegularFile(path))throw new IOException("Invalid graph trace");
                found=path;
            }
            if(found==null)throw new IOException("Missing graph trace: "+graph);
            Files.move(found,destination.resolve(found.getFileName()));
        }
    }
    private static String inputProof(File audio,long start)throws Exception {
        // This extra diagnostic read uses the actual production PCM reader. It is
        // outside predict timing, and is not a replacement for its own source read.
        float[][] stereo=NativeDeuxTransform.readStereo(audio,start,()->{});
        ByteBuffer bytes=ByteBuffer.allocate(2*SAMPLES*4).order(ByteOrder.LITTLE_ENDIAN);double peak=0;
        for(float[] channel:stereo){
            if(channel.length!=SAMPLES)throw new IOException("Incomplete production input read");
            for(float x:channel){if(!Float.isFinite(x))throw new IOException("Nonfinite input");bytes.putFloat(x);peak=Math.max(peak,Math.abs((double)x));}
        }
        if(peak<1e-7)throw new IOException("Silent context unsupported by this complete-capture experiment");
        return hash(bytes.array());
    }
    private static String outputProof(Path output)throws Exception {
        if(Files.isSymbolicLink(output)||Files.size(output)!=2L*SAMPLES*4)throw new IOException("Incomplete two-stem output");
        byte[] bytes=Files.readAllBytes(output);FloatBuffer values=ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer();
        while(values.hasRemaining())if(!Float.isFinite(values.get()))throw new IOException("Nonfinite output");
        return hash(bytes);
    }
    public static void main(String[] args)throws Exception {
        if(args.length!=5)throw new IllegalArgumentException("models wav plan-json new-output active-traces-or-empty");
        Path models=Paths.get(args[0]),audio=Paths.get(args[1]),planPath=Paths.get(args[2]),output=Paths.get(args[3]);
        JSONObject plan=new JSONObject(new String(Files.readAllBytes(planPath),StandardCharsets.UTF_8));
        int total=plan.getInt("audioFrames");String inputSha=hashFile(audio);
        if(total<1||total>MAX||Files.isSymbolicLink(audio)||!inputSha.equals(plan.getString("audioSha256")))throw new IOException("Invalid source binding");
        JSONArray planned=plan.getJSONArray("passagePlan");int count=1+Math.max(0,(total-CORE+STRIDE-1)/STRIDE);
        if(planned.length()!=count)throw new IOException("Invalid production passage count");
        if(Files.exists(output))throw new IOException("Output already exists");Files.createDirectory(output);
        Path traces=args[4].isEmpty()?null:Paths.get(args[4]);
        JSONObject manifest=new JSONObject(new String(Files.readAllBytes(models.resolve("manifest.json")),StandardCharsets.UTF_8));
        JSONArray passages=new JSONArray();long sourceStarted=System.nanoTime();
        // Same original object and reusable buffers across passages, just like a
        // native job. Original predict still opens/closes all 27 graph sessions.
        try(NativeDeux engine=new NativeDeux(models.toFile())){
            for(int index=0;index<count;index++){
                JSONObject expected=planned.getJSONObject(index);int offset=index*STRIDE,start=offset-HALO;
                int keep=Math.min(CORE,total-offset),emit=offset+CORE>=total?keep:STRIDE;
                if(expected.getInt("index")!=index||expected.getInt("startSample")!=start||
                   expected.getInt("outputOffset")!=offset||expected.getInt("emitSamples")!=emit)
                    throw new IOException("Production schedule changed");
                String readSha=inputProof(audio.toFile(),start);
                if(!readSha.equals(expected.getString("inputStereoSha256")))throw new IOException("Production input read differs from independent PCM proof");
                Path directory=output.resolve(String.format(Locale.ROOT,"passage-%03d",index));Files.createDirectory(directory);
                Path stems=directory.resolve("stems.f32"),profilePath=directory.resolve("profile.txt");
                NativeInferenceProfile profile=new NativeInferenceProfile();profile.captureStartMemory();long started=System.nanoTime();
                engine.predict(audio.toFile(),start,stems.toFile(),null,()->false,null,profile);
                long elapsed=System.nanoTime()-started;
                NativeInferenceProfile.Snapshot snapshot=profile.finish("completed");
                Files.write(profilePath,Arrays.asList(snapshot.records()),StandardCharsets.UTF_8,StandardOpenOption.CREATE_NEW);
                if(traces!=null)moveTraces(traces,directory.resolve("traces"));
                JSONObject receipt=new JSONObject().put("schema","lightforge-deux-source-passage-1")
                    .put("index",index).put("startSample",start).put("outputOffset",offset).put("emitSamples",emit)
                    .put("sampleRate",RATE).put("samplesPerStem",SAMPLES).put("sourceSamples",total).put("sourceSha256",inputSha)
                    .put("inputStereoSha256",readSha).put("outputFile",String.format(Locale.ROOT,"passage-%03d/stems.f32",index))
                    .put("outputBytes",Files.size(stems)).put("outputSha256",outputProof(stems))
                    .put("profileSha256",hashFile(profilePath)).put("profiled",traces!=null).put("wallNanos",elapsed)
                    .put("predictReturned",true).put("benchmarkTimingAdmitted",false);
                write(directory.resolve("receipt.json"),receipt);passages.put(receipt);
                System.out.println(new JSONObject().put("passageIndex",index).put("passageCount",count).toString());
            }
        }
        long elapsed=System.nanoTime()-sourceStarted;
        if(!inputSha.equals(hashFile(audio)))throw new IOException("Source changed during inference");
        JSONObject receipt=new JSONObject().put("schema","lightforge-deux-source-run-1")
            .put("runtime","onnxruntime-java-"+OrtEnvironment.getEnvironment().getVersion())
            .put("sampleRate",RATE).put("audioFrames",total).put("audioSha256",inputSha)
            .put("modelFiles",manifest.getJSONObject("files")).put("passageCount",count).put("passages",passages)
            .put("profiled",traces!=null).put("engineObjects",1).put("engineCloseReturned",true).put("allPredictionsReturned",true)
            .put("sessionLifecycle","Original NativeDeux closes all graph sessions per predict; same object retains production buffers and verification cache")
            .put("wallNanos",elapsed).put("wallIncludesInputProofAndEvidenceWrites",true)
            .put("benchmarkTimingAdmitted",false).put("qualityApproved",false).put("target75Proven",false).put("releaseAuthorized",false);
        write(output.resolve("receipt.json"),receipt);
    }
}
