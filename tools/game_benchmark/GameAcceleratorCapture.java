package com.cyberbasslord.lightforge;

import ai.onnxruntime.*;
import org.json.*;
import java.io.*;
import java.nio.*;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;

/** Research observer only; compiled beside an isolated NativeGame snapshot. */
public final class GameAcceleratorCapture {
    private static Path output, maps;
    private static int segment;
    private static final JSONArray stages = new JSONArray();
    static void configure(Path directory, Path libraryMaps) {output=directory;maps=libraryMaps;}
    static JSONArray stages(){return stages;}
    static String hash(byte[] bytes)throws Exception {
        StringBuilder result=new StringBuilder();
        for(byte b:MessageDigest.getInstance("SHA-256").digest(bytes))result.append(String.format(Locale.ROOT,"%02x",b&255));
        return result.toString();
    }
    static void record(String graph,OrtSession.Result result,long elapsed)throws Exception {
        if(output==null)throw new IOException("Capture not configured");
        if(ByteOrder.nativeOrder()!=ByteOrder.LITTLE_ENDIAN)throw new IOException("Little-endian capture required");
        String label=graph.equals("segmenter")?"segmenter-"+(segment++):graph;
        JSONArray tensors=new JSONArray();
        for(Map.Entry<String,OnnxValue> entry:result){
            if(!(entry.getValue() instanceof OnnxTensor))throw new IOException("Non-tensor GAME output");
            OnnxTensor tensor=(OnnxTensor)entry.getValue();TensorInfo info=tensor.getInfo();
            String type;
            switch(info.type){
                case FLOAT:type="float32";break;case BOOL:type="bool";break;
                case INT64:type="int64";break;case INT32:type="int32";break;
                case DOUBLE:type="float64";break;default:throw new IOException("Unsupported tensor type");
            }
            ByteBuffer buffer=tensor.getByteBuffer();byte[] bytes=new byte[buffer.remaining()];buffer.get(bytes);
            if(!entry.getKey().matches("[A-Za-z0-9_]+"))throw new IOException("Unsafe tensor name");
            String file=label+"-"+entry.getKey()+".bin";
            Files.write(output.resolve(file),bytes,StandardOpenOption.CREATE_NEW);
            tensors.put(new JSONObject().put("name",entry.getKey()).put("type",type)
                .put("dims",new JSONArray(info.getShape())).put("file",file).put("bytes",bytes.length).put("sha256",hash(bytes)));
        }
        stages.put(new JSONObject().put("graph",graph).put("label",label).put("seconds",elapsed/1e9).put("outputs",tensors));
        if(maps!=null){
            StringBuilder selected=new StringBuilder();
            for(String line:Files.readAllLines(Paths.get("/proc/self/maps")))
                if(line.contains("/libcuda")||line.contains("/libcudnn")||line.contains("/libcublas")||line.contains("/libnvrtc")||line.contains("/libnvJitLink"))selected.append(line).append('\n');
            Files.write(maps,selected.toString().getBytes("UTF-8"),StandardOpenOption.CREATE,StandardOpenOption.APPEND);
        }
    }
}
