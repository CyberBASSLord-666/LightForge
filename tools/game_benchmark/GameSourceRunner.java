package com.cyberbasslord.lightforge;

import ai.onnxruntime.*;
import org.json.*;
import java.io.*;
import java.nio.*;
import java.nio.file.*;
import java.util.*;

/** Bounded full-source research runner. The production engine and observer are copied unchanged. */
public final class GameSourceRunner {
    private static final int RATE=44100, CORE=12*RATE, HALO=2*RATE, MAX=64*RATE;
    private static final String[] GRAPHS={"encoder","dur2bd","segmenter","bd2dur","estimator"};

    private static void write(Path path,JSONObject value)throws Exception {
        Path temporary=path.resolveSibling(path.getFileName()+".partial");
        Files.write(temporary,(value.toString(2)+"\n").getBytes("UTF-8"),StandardOpenOption.CREATE_NEW);
        Files.move(temporary,path,StandardCopyOption.REPLACE_EXISTING);
    }

    private static void moveTraces(Path source,Path destination)throws Exception {
        Files.createDirectory(destination);
        List<Path> paths=new ArrayList<>();
        try(DirectoryStream<Path> stream=Files.newDirectoryStream(source)){for(Path path:stream)paths.add(path);}
        if(paths.size()!=5)throw new IOException("Exactly five completed passage traces required");
        for(String graph:GRAPHS){
            Path found=null;
            for(Path path:paths)if(path.getFileName().toString().startsWith(graph+"_")&&path.toString().endsWith(".json")){
                if(found!=null||Files.isSymbolicLink(path)||!Files.isRegularFile(path))throw new IOException("Duplicate/invalid graph trace");
                found=path;
            }
            if(found==null)throw new IOException("Missing graph trace: "+graph);
            Files.move(found,destination.resolve(found.getFileName()));
        }
    }

    public static void main(String[] args)throws Exception {
        if(args.length!=7)throw new IllegalArgumentException("models full-pcm-f32le new-output language capture library-maps-or-empty trace-directory-or-empty");
        Path models=Paths.get(args[0]),input=Paths.get(args[1]),output=Paths.get(args[2]);
        long size=Files.size(input);
        if(size<4||size>4L*MAX||size%4!=0||Files.isSymbolicLink(input))throw new IOException("Invalid bounded full PCM");
        if(Files.exists(output))throw new IOException("Output already exists");Files.createDirectory(output);
        byte[] bytes=Files.readAllBytes(input);
        FloatBuffer buffer=ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer();
        float[] pcm=new float[buffer.remaining()];buffer.get(pcm);
        for(float x:pcm)if(!Float.isFinite(x))throw new IOException("Nonfinite full PCM");
        int language=Integer.parseInt(args[3]);if(language<0||language>4)throw new IOException("Invalid language");
        if(!args[4].equals("true")&&!args[4].equals("false"))throw new IOException("Invalid capture switch");
        boolean capture=Boolean.parseBoolean(args[4]);Path maps=args[5].isEmpty()?null:Paths.get(args[5]);
        Path traceDirectory=args[6].isEmpty()?null:Paths.get(args[6]);
        if(traceDirectory!=null&&!capture)throw new IOException("Profiling requires capture");
        JSONObject manifest=new JSONObject(new String(Files.readAllBytes(models.resolve("manifest.json")),"UTF-8"));
        JSONArray passages=new JSONArray();List<Path> receiptPaths=new ArrayList<>();
        long started=System.nanoTime();NativeGame engine=new NativeGame(models.toFile());
        try {
            int count=(pcm.length+CORE-1)/CORE;
            for(int index=0;index<count;index++){
                int first=Math.max(0,index*CORE-HALO),last=Math.min(pcm.length,(index+1)*CORE+HALO);
                long seed=(2025L+index*104729L)&0xffffffffL;
                float[] passage=Arrays.copyOfRange(pcm,first,last);double peak=0;
                for(float x:passage)peak=Math.max(peak,Math.abs((double)x));
                // The first bounded experiment deliberately rejects silent windows:
                // this is not a replacement for production's exact silence shortcut.
                if(peak<=1e-5)throw new IOException("Silent passage unsupported by this complete-capture experiment");
                Path directory=output.resolve(String.format(Locale.ROOT,"passage-%03d",index));Files.createDirectory(directory);
                GameAcceleratorCapture.configure(capture?directory:null,maps);
                int before=GameAcceleratorCapture.stages().length();long passStarted=System.nanoTime();
                JSONArray notes=engine.predict(passage,language,seed,null,()->false);
                long passWall=System.nanoTime()-passStarted;
                JSONArray stages=new JSONArray();int segments=0;double inference=0;
                JSONArray all=GameAcceleratorCapture.stages();
                for(int i=before;i<all.length();i++){
                    JSONObject stage=new JSONObject(all.getJSONObject(i).toString());
                    String label=stage.getString("label");stage.put("captureOriginalLabel",label);
                    if(stage.getString("graph").equals("segmenter")){
                        if(!label.equals("segmenter-"+(index*8+segments)))throw new IOException("Unexpected global capture segment");
                        stage.put("label","segmenter-"+(segments++));
                    }
                    inference+=stage.getDouble("seconds");stages.put(stage);
                }
                if(capture&&(stages.length()!=12||segments!=8))throw new IOException("Incomplete passage capture");
                if(!capture&&stages.length()!=0)throw new IOException("Unexpected plain observer");
                if(traceDirectory!=null)moveTraces(traceDirectory,directory.resolve("traces"));
                byte[] passageBytes=Arrays.copyOfRange(bytes,first*4,last*4);
                JSONObject receipt=new JSONObject().put("schema","lightforge-game-benchmark-1")
                    .put("runtime","onnxruntime-java-"+OrtEnvironment.getEnvironment().getVersion())
                    .put("sampleRate",RATE).put("samples",last-first).put("pcmSHA256",GameAcceleratorCapture.hash(passageBytes))
                    .put("sourcePcmSHA256",GameAcceleratorCapture.hash(bytes)).put("sourceSamples",pcm.length)
                    .put("passageIndex",index).put("firstSample",first).put("lastSample",last)
                    .put("modelFiles",manifest.getJSONObject("files")).put("seed",seed).put("language",language)
                    .put("steps",NativeGame.STEPS).put("capture",capture).put("stages",stages).put("notes",notes)
                    .put("wallNanos",passWall).put("wallSeconds",passWall/1e9).put("wallIncludesCapture",capture)
                    .put("inferenceSeconds",capture?(Object)inference:JSONObject.NULL)
                    .put("retirementConfirmed",false).put("benchmarkTimingAdmitted",false)
                    .put("scope","One production-scheduled passage in a same-object full-source run; model sessions retain original per-predict retirement");
                Path path=directory.resolve("receipt.json");write(path,receipt);receiptPaths.add(path);passages.put(receipt);
                System.out.println(new JSONObject().put("passageIndex",index).put("passageCount",count).put("notes",notes.length()).toString());
            }
        } finally {engine.close();}
        long wall=System.nanoTime()-started;
        if(!engine.isRetired())throw new IOException("Production engine retirement unconfirmed");
        for(int i=0;i<passages.length();i++){
            JSONObject receipt=passages.getJSONObject(i).put("retirementConfirmed",true)
                .put("retirementScope","Shared original engine closed after every passage returned and retired its JNI resources");
            write(receiptPaths.get(i),receipt);
        }
        JSONObject receipt=new JSONObject().put("schema","lightforge-game-source-run-1")
            .put("runtime","onnxruntime-java-"+OrtEnvironment.getEnvironment().getVersion())
            .put("sampleRate",RATE).put("samples",pcm.length).put("pcmSHA256",GameAcceleratorCapture.hash(bytes))
            .put("modelFiles",manifest.getJSONObject("files")).put("steps",NativeGame.STEPS).put("language",language)
            .put("capture",capture).put("profiled",traceDirectory!=null).put("passages",passages)
            .put("passageCount",passages.length()).put("engineObjects",1).put("retirementConfirmed",true)
            .put("sessionLifecycle","Original NativeGame creates and retires graph sessions on each predict; no persistent-session optimization")
            .put("wallNanos",wall).put("benchmarkTimingAdmitted",false).put("qualityApproved",false)
            .put("target75Proven",false).put("releaseAuthorized",false);
        write(output.resolve("receipt.json"),receipt);
    }
}
