package com.cyberbasslord.lightforge;

import java.io.*;
import java.nio.*;
import java.nio.file.*;
import org.json.*;

/** Real-model comparison entry point; no graph substitutions or Android simulation. */
public final class NativeGamePairComparison {
    private static float[] pcm(String name)throws IOException {
        byte[] bytes=Files.readAllBytes(Paths.get(name));
        if(bytes.length<4||bytes.length>NativeGame.MAX_SAMPLES*4||bytes.length%4!=0)
            throw new IOException("Invalid original passage fixture");
        FloatBuffer values=ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer();
        float[] result=new float[values.remaining()];values.get(result);return result;
    }
    public static void main(String[] args)throws Exception {
        if(args.length!=5&&args.length!=7)throw new IllegalArgumentException("MODE MODELS FIRST_PCM SECOND_PCM OUTPUT [FIRST_SEED SECOND_SEED]");
        String mode=args[0];
        if(!mode.equals("single")&&!mode.equals("pair"))throw new IllegalArgumentException("Unknown execution mode");
        float[][] input={pcm(args[2]),pcm(args[3])};int[] languages={0,0};
        long[] seeds=args.length==7?new long[]{Long.parseLong(args[5]),Long.parseLong(args[6])}:new long[]{2025,106754};
        JSONArray notes=new JSONArray(),profiles=new JSONArray();long started=System.nanoTime();
        if(mode.equals("single")){
            for(int i=0;i<2;i++){
                NativeGameProfile profile=new NativeGameProfile(NativeGame.inferenceThreads());
                NativeGame engine=new NativeGame(new File(args[1]));
                try{notes.put(engine.predict(input[i],languages[i],seeds[i],null,()->false,profile));}
                finally{engine.close();if(!engine.isRetired())throw new IOException("Single GAME resources not retired");}
                profiles.put(profile.finish("completed").summary());
            }
        }else{
            NativeGameProfile profile=new NativeGameProfile(NativeGame.inferenceThreads());
            NativeGame engine=new NativeGame(new File(args[1]));
            try{notes=engine.predictBatch(input,languages,seeds,null,()->false,profile);}
            finally{engine.close();if(!engine.isRetired())throw new IOException("Paired GAME resources not retired");}
            profiles.put(profile.finish("completed").summary());
        }
        double wallSeconds=(System.nanoTime()-started)/1e9;
        JSONObject result=new JSONObject().put("mode",mode).put("wallSeconds",wallSeconds)
            .put("notes",notes).put("profiles",profiles).put("samples",new JSONArray().put(input[0].length).put(input[1].length))
            .put("seeds",new JSONArray().put(seeds[0]).put(seeds[1])).put("language",0)
            .put("runtime",NativeGame.RUNTIME_VERSION).put("steps",NativeGame.STEPS)
            .put("scope","Two original production-context passages on the host JVM; not a whole-job or phone measurement");
        Files.write(Paths.get(args[4]),(result.toString(2)+"\n").getBytes("UTF-8"),StandardOpenOption.CREATE_NEW);
    }
}
