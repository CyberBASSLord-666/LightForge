package com.cyberbasslord.lightforge;

import ai.onnxruntime.*;
import org.json.*;
import java.io.*;
import java.nio.*;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;

/** Host observer used only in an isolated copy of the production GAME engine. */
public final class NativeGameExecutionBenchmark {
    private static Path output;
    private static final JSONArray stages=new JSONArray();
    private static int segment;
    static void capture(String graph,OrtSession.Result result)throws Exception {
        String label=graph.equals("segmenter")?graph+"-"+(segment++):graph;
        JSONArray tensors=new JSONArray();
        for(Map.Entry<String,OnnxValue> entry:result){
            OnnxTensor tensor=(OnnxTensor)entry.getValue();TensorInfo info=tensor.getInfo();
            ByteBuffer raw=tensor.getByteBuffer();byte[] bytes=new byte[raw.remaining()];raw.get(bytes);
            String type;
            switch(info.type){case FLOAT:type="float32";break;case BOOL:type="bool";break;default:throw new IOException("Unexpected GAME output type.");}
            String file=label+"-"+entry.getKey()+".bin";Files.write(output.resolve(file),bytes,StandardOpenOption.CREATE_NEW);
            tensors.put(new JSONObject().put("name",entry.getKey()).put("type",type).put("dims",new JSONArray(info.getShape()))
                .put("file",file).put("bytes",bytes.length).put("sha256",hash(bytes)));
        }
        stages.put(new JSONObject().put("graph",graph).put("label",label).put("outputs",tensors));
    }
    private static String hash(byte[] bytes)throws Exception {
        StringBuilder text=new StringBuilder();for(byte value:MessageDigest.getInstance("SHA-256").digest(bytes))text.append(String.format("%02x",value&255));return text.toString();
    }
    private static Object peakRssKiB(){
        try{for(String line:Files.readAllLines(Paths.get("/proc/self/status")))if(line.startsWith("VmHWM:"))return Long.parseLong(line.trim().split("\\s+")[1]);}
        catch(Exception unavailable){/* Optional host measurement, never a synthetic zero. */}
        return JSONObject.NULL;
    }
    public static void main(String[] args)throws Exception {
        if(args.length!=5||ByteOrder.nativeOrder()!=ByteOrder.LITTLE_ENDIAN)throw new IllegalArgumentException("models pcm output seed language; little-endian host required");
        Path models=Paths.get(args[0]),input=Paths.get(args[1]);output=Paths.get(args[2]);Files.createDirectory(output);
        byte[] bytes=Files.readAllBytes(input);FloatBuffer buffer=ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer();
        float[] pcm=new float[buffer.remaining()];buffer.get(pcm);
        if(bytes.length!=pcm.length*4)throw new IOException("Incomplete PCM sample.");
        long seed=Long.parseLong(args[3]);int language=Integer.parseInt(args[4]);
        NativeGameProfile profile=new NativeGameProfile(NativeGame.inferenceThreads());
        long started=System.nanoTime();NativeGame engine=new NativeGame(models.toFile());JSONArray notes;
        try{notes=engine.predict(pcm,language,seed,null,()->false,profile);}finally{engine.close();}
        if(!engine.isRetired())throw new IOException("Native retirement was not confirmed.");
        double wall=(System.nanoTime()-started)/1e9;
        JSONObject manifest=new JSONObject(new String(Files.readAllBytes(models.resolve("manifest.json")),"UTF-8"));
        JSONObject graphs=new JSONObject();for(String graph:new String[]{"encoder","dur2bd","segmenter","bd2dur","estimator"})graphs.put(graph+".onnx",manifest.getJSONObject("files").getJSONObject(graph+".onnx"));
        JSONObject receipt=new JSONObject().put("schema","lightforge-game-benchmark-1").put("runtime","onnxruntime-java-"+NativeGame.RUNTIME_VERSION)
            .put("sampleRate",44100).put("samples",pcm.length).put("pcmSHA256",hash(bytes)).put("modelFiles",graphs)
            .put("seed",seed).put("language",language).put("steps",8).put("capture",true).put("stages",stages).put("notes",notes)
            .put("wallSeconds",wall).put("wallIncludesCapture",true).put("retired",true).put("profile",profile.finish("completed").summary())
            .put("processPeakRssKiB",peakRssKiB()).put("memoryScope","Child /proc/self/status VmHWM observed after native retirement, before report serialization")
            .put("scope","Isolated production-source host experiment; captures all graph outputs. No Android performance or general quality claim.");
        Files.write(output.resolve("receipt.json"),(receipt.toString(2)+"\n").getBytes("UTF-8"),StandardOpenOption.CREATE_NEW);
    }
}
