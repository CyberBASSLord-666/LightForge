package com.cyberbasslord.lightforge;

import ai.onnxruntime.*;
import org.json.*;
import java.io.*;
import java.nio.*;
import java.nio.file.*;

/** Runs one original production passage; no audio preparation or note rounding. */
public final class GameAcceleratorRunner {
    public static void main(String[] args)throws Exception {
        if(args.length!=7)throw new IllegalArgumentException("models pcm-f32le new-output seed language capture library-maps-or-empty");
        Path models=Paths.get(args[0]),input=Paths.get(args[1]),output=Paths.get(args[2]);
        long size=Files.size(input);
        if(size<4||size>4L*NativeGame.MAX_SAMPLES||size%4!=0)throw new IOException("Invalid PCM length");
        if(Files.exists(output))throw new IOException("Output already exists");Files.createDirectory(output);
        byte[] bytes=Files.readAllBytes(input);
        FloatBuffer buffer=ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer();
        float[] pcm=new float[buffer.remaining()];buffer.get(pcm);
        long seed=Long.parseUnsignedLong(args[3]);int language=Integer.parseInt(args[4]);
        if(!args[5].equals("true")&&!args[5].equals("false"))throw new IOException("Invalid capture switch");
        boolean capture=Boolean.parseBoolean(args[5]);
        GameAcceleratorCapture.configure(capture?output:null,args[6].isEmpty()?null:Paths.get(args[6]));
        long started=System.nanoTime();JSONArray notes;NativeGame engine=new NativeGame(models.toFile());
        try{notes=engine.predict(pcm,language,seed,null,()->false);}finally{engine.close();}
        long wall=System.nanoTime()-started;
        if(!engine.isRetired())throw new IOException("Production engine retirement unconfirmed");
        JSONObject manifest=new JSONObject(new String(Files.readAllBytes(models.resolve("manifest.json")),"UTF-8"));
        JSONArray stages=GameAcceleratorCapture.stages();double inference=0;
        for(int i=0;i<stages.length();i++)inference+=stages.getJSONObject(i).getDouble("seconds");
        JSONObject receipt=new JSONObject().put("schema","lightforge-game-benchmark-1")
            .put("runtime","onnxruntime-java-"+OrtEnvironment.getEnvironment().getVersion())
            .put("sampleRate",NativeGame.SAMPLE_RATE).put("samples",pcm.length)
            .put("pcmSHA256",GameAcceleratorCapture.hash(bytes)).put("modelFiles",manifest.getJSONObject("files"))
            .put("seed",seed).put("language",language).put("steps",NativeGame.STEPS)
            .put("capture",capture).put("stages",stages).put("notes",notes)
            .put("wallNanos",wall).put("wallSeconds",wall/1e9).put("wallIncludesCapture",capture)
            .put("inferenceSeconds",capture?(Object)inference:JSONObject.NULL)
            .put("requestedThreads",Math.max(1,Math.min(4,Runtime.getRuntime().availableProcessors())))
            .put("effectiveThreads",JSONObject.NULL).put("retirementConfirmed",true)
            .put("scope","One host GAME passage, including model verification/loading and retirement; no network, Android, full-vocal-stage or quality claim");
        Files.write(output.resolve("receipt.json"),(receipt.toString(2)+"\n").getBytes("UTF-8"),StandardOpenOption.CREATE_NEW);
        System.out.println(new JSONObject().put("wallNanos",wall).put("notes",notes.length()).toString());
    }
}
