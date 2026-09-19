package com.cyberbasslord.lightforge;

import java.io.*;
import java.nio.*;
import java.nio.file.*;
import java.util.*;
import java.lang.reflect.Method;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.json.*;

/** Lightweight contract checks, plus an explicitly requested real-model entrypoint. */
public final class NativeGameTest {
    private interface Action { void run() throws Exception; }
    public static void main(String[] args) throws Exception {
        if((args.length==4 || args.length==6) && "infer".equals(args[0])){infer(args);return;}
        if(args.length!=1)throw new IllegalArgumentException("Expected manifest path, or infer models pcm-f32le notes.json [seed language]");
        pcm();noise();notes();manifest(Paths.get(args[0]));retirement(Paths.get(args[0]));
        System.out.println("NativeGame: bounded PCM, unsigned seed, deterministic noise, unrounded notes, pinned manifest and pre-runtime cancellation checks passed.");
    }
    private static void pcm() throws Exception {
        float[] input={-2,0,.1f,2};float[] copy=NativeGame.validatedPcm(input,4,0xffffffffL);
        require(copy!=input && Arrays.equals(copy,input),"PCM is copied without normalization");
        input[0]=7;require(copy[0]==-2,"PCM snapshot independence");
        NativeGame.validatedPcm(new float[NativeGame.MAX_SAMPLES],0,0);
        for(float[] invalid:new float[][]{null,new float[0],new float[NativeGame.MAX_SAMPLES+1],
                {Float.NaN},{Float.POSITIVE_INFINITY},{Float.NEGATIVE_INFINITY}})
            expect(IOException.class,()->NativeGame.validatedPcm(invalid,0,2025));
        for(int language:new int[]{-1,5})expect(IOException.class,()->NativeGame.validatedPcm(copy,language,2025));
        for(long seed:new long[]{-1,0x100000000L,Long.MAX_VALUE})expect(IOException.class,()->NativeGame.validatedPcm(copy,0,seed));
    }
    private static void noise() {
        float[] zero=NativeGame.noise(16,0);
        for(float value:zero)require(value==(float)(.5/4294967296.0),"zero-seed xorshift semantics");
        for(long seed:new long[]{2025,0xffffffffL,0x80000000L}) {
            float[] first=NativeGame.noise(1601,seed),second=NativeGame.noise(1601,seed);
            require(Arrays.equals(first,second),"deterministic diffusion input");
            long x=seed;
            for(float value:first) {
                // A separate unsigned-long implementation checks Java int shifts.
                x=(x^(x<<13))&0xffffffffL;x=(x^(x>>>17))&0xffffffffL;x=(x^(x<<5))&0xffffffffL;
                require(Float.floatToIntBits(value)==Float.floatToIntBits((float)((x+.5)/4294967296.0)),"unsigned xorshift parity");
            }
        }
    }
    private static void notes() throws Exception {
        float[] durations={.02f,.1f,.03f,.2f},pitches={60,60.123456f,63,70};
        JSONArray notes=NativeGame.notes(FloatBuffer.wrap(durations),FloatBuffer.wrap(pitches),
                ByteBuffer.wrap(new byte[]{1,1,1,0}),ByteBuffer.wrap(new byte[]{1,1,1,1}),1);
        require(notes.length()==1,"unchanged duration and presence filter");
        JSONObject note=notes.getJSONObject(0);
        require(note.getDouble("start")==durations[0] && note.getDouble("end")==durations[0]+(double)durations[1],"unrounded cumulative timing");
        require(note.getDouble("midi")==pitches[1],"unrounded float32 pitch");
        require(note.length()==3,"notes contain only start, end and midi");
        // Buffer positions are honored without altering the caller's buffers.
        FloatBuffer length=FloatBuffer.wrap(new float[]{999,.2f});length.position(1);
        FloatBuffer pitch=FloatBuffer.wrap(new float[]{999,64});pitch.position(1);
        ByteBuffer mask=ByteBuffer.wrap(new byte[]{9,1});mask.position(1);
        require(NativeGame.notes(length,pitch,mask,mask,1).length()==1 && length.position()==1,"positioned buffers");
        for(float bad:new float[]{-1,Float.NaN,Float.POSITIVE_INFINITY})
            expect(IOException.class,()->one(bad,60,(byte)1,(byte)1,1));
        expect(IOException.class,()->one(.2f,Float.NaN,(byte)1,(byte)1,1));
        expect(IOException.class,()->one(2,60,(byte)1,(byte)1,1));
        expect(IOException.class,()->one(.2f,60,(byte)2,(byte)1,1));
        expect(IOException.class,()->one(.2f,60,(byte)1,(byte)-1,1));
        expect(IOException.class,()->NativeGame.notes(FloatBuffer.wrap(new float[]{.1f}),FloatBuffer.allocate(0),ByteBuffer.allocate(1),ByteBuffer.allocate(1),1));
        require(one(.2f,-1,(byte)1,(byte)1,1).length()==0 && one(.2f,128,(byte)1,(byte)1,1).length()==0,"out-of-range pitch filter retained");
    }
    private static JSONArray one(float length,float midi,byte mask,byte presence,double duration) throws Exception {
        return NativeGame.notes(FloatBuffer.wrap(new float[]{length}),FloatBuffer.wrap(new float[]{midi}),
                ByteBuffer.wrap(new byte[]{mask}),ByteBuffer.wrap(new byte[]{presence}),duration);
    }
    private static void manifest(Path original) throws Exception {
        Path directory=Files.createTempDirectory("native-game-contract-");Path path=directory.resolve("manifest.json");
        try {
            byte[] good=Files.readAllBytes(original);Files.write(path,good);
            // No graph files and no JNI need exist for construction or pre-run cancellation.
            try(NativeGame engine=new NativeGame(directory.toFile())) {
                engine.cancel();expect(InterruptedIOException.class,()->engine.predict(new float[]{0},0,2025,null,()->false));
                engine.close();require(engine.isRetired(),"ordinary cancellation confirms empty native retirement");
            }
            NativeGame closed=new NativeGame(directory.toFile());closed.close();closed.close();
            expect(InterruptedIOException.class,()->closed.predict(new float[]{0},0,2025,null,()->false));
            try(NativeGame engine=new NativeGame(directory.toFile())) {
                expect(InterruptedIOException.class,()->engine.predict(new float[]{0},0,2025,null,()->true));
            }
            try(NativeGame engine=new NativeGame(directory.toFile())) {
                expect(IOException.class,()->engine.predict(new float[]{0},0,2025,null,()->false));
                expect(InterruptedIOException.class,()->engine.predict(new float[]{0},0,2025,null,()->false));
            }
            for(String field:new String[]{"id","steps","sampleRate","radius","frameSeconds","boundaryThreshold","presenceThreshold"}) {
                JSONObject changed=new JSONObject(new String(good,"UTF-8"));changed.put(field,field.equals("id")?"different":99);
                Files.write(path,changed.toString().getBytes("UTF-8"));
                expect(IOException.class,()->new NativeGame(directory.toFile()));
            }
            JSONObject fractional=new JSONObject(new String(good,"UTF-8"));fractional.put("steps",8.5);
            Files.write(path,fractional.toString().getBytes("UTF-8"));expect(IOException.class,()->new NativeGame(directory.toFile()));
            JSONObject changed=new JSONObject(new String(good,"UTF-8"));
            changed.getJSONObject("files").getJSONObject("segmenter.onnx").put("sha256",String.join("",Collections.nCopies(64,"a")));
            Files.write(path,changed.toString().getBytes("UTF-8"));expect(IOException.class,()->new NativeGame(directory.toFile()));
            Files.write(path,new byte[262145]);expect(IOException.class,()->new NativeGame(directory.toFile()));
        }finally{Files.deleteIfExists(path);Files.deleteIfExists(directory);}
    }
    private static AutoCloseable owned(NativeGame engine,AutoCloseable resource)throws Exception {
        Method method=NativeGame.class.getDeclaredMethod("owned",AutoCloseable.class);method.setAccessible(true);
        return (AutoCloseable)method.invoke(engine,resource);
    }
    private static void retirement(Path manifest)throws Exception {
        Path directory=Files.createTempDirectory("native-game-retirement-");Path copy=directory.resolve("manifest.json");Files.copy(manifest,copy);
        try {
            // The same owner wrapper surrounds tensors, results and SessionOptions;
            // session/RunOptions/manual result closes call its retire helper directly.
            for(boolean fatal:new boolean[]{false,true}) {
                NativeGame engine=new NativeGame(directory.toFile());AtomicInteger closed=new AtomicInteger();
                try {
                    try(AutoCloseable first=owned(engine,()->closed.incrementAndGet());
                        AutoCloseable second=owned(engine,()->{closed.incrementAndGet();if(fatal)throw new AssertionError("controlled destructor error");throw new IOException("controlled destructor failure");});
                        AutoCloseable third=owned(engine,()->closed.incrementAndGet())) { }
                    throw new AssertionError("Destructor failure was swallowed");
                }catch(Throwable failure){require(fatal?failure instanceof AssertionError:failure instanceof IOException,"original destructor failure propagates");}
                engine.close();require(closed.get()==3,"all native owners attempt close after a destructor fails");
                require(!engine.isRetired(),"failed tensor/result/options destructor never confirms retirement");
                engine.close();require(!engine.isRetired(),"idempotent close cannot erase failed-retirement evidence");
            }
            NativeGame engine=new NativeGame(directory.toFile());CountDownLatch entered=new CountDownLatch(1),allowed=new CountDownLatch(1);
            ExecutorService pool=Executors.newFixedThreadPool(2);
            AutoCloseable resource=owned(engine,()->{entered.countDown();if(!allowed.await(5,TimeUnit.SECONDS))throw new IOException("destructor barrier timed out");});
            try {
                Future<?> cleanup=pool.submit(()->{try{resource.close();}catch(Exception error){throw new RuntimeException(error);}});
                require(entered.await(2,TimeUnit.SECONDS),"tracked destructor entered");
                pool.submit(engine::cancel).get(1,TimeUnit.SECONDS);
                allowed.countDown();cleanup.get(2,TimeUnit.SECONDS);engine.close();
                require(engine.isRetired(),"normal destructor and cancellation confirm retirement");
            }finally{allowed.countDown();pool.shutdownNow();engine.close();}
        }finally{Files.deleteIfExists(copy);Files.deleteIfExists(directory);}
    }
    private static void infer(String[] args) throws Exception {
        Path input=Paths.get(args[2]),output=Paths.get(args[3]);long bytes=Files.size(input);
        if(bytes<4 || bytes>4L*NativeGame.MAX_SAMPLES || bytes%4!=0)throw new IOException("Invalid PCM fixture length");
        FloatBuffer values=ByteBuffer.wrap(Files.readAllBytes(input)).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer();
        long seed=args.length==6?Long.parseUnsignedLong(args[4]):2025;
        int language=args.length==6?Integer.parseInt(args[5]):0;
        float[] pcm=new float[values.remaining()];values.get(pcm);long started=System.nanoTime();JSONArray notes;
        try(NativeGame engine=new NativeGame(new File(args[1]))){notes=engine.predict(pcm,language,seed,null,()->false);}
        JSONObject result=new JSONObject().put("notes",notes).put("samples",pcm.length).put("seed",seed).put("language",language)
                .put("steps",NativeGame.STEPS).put("wallSeconds",(System.nanoTime()-started)/1e9)
                .put("scope","Host execution of production engine; not an Android or speedup claim");
        Files.write(output,(result.toString(2)+"\n").getBytes("UTF-8"),StandardOpenOption.CREATE_NEW);
        System.out.println("NativeGame host result written; "+notes.length()+" notes.");
    }
    private static void expect(Class<? extends Throwable> type,Action action) throws Exception {
        try{action.run();throw new AssertionError("Expected "+type.getSimpleName());}
        catch(Exception error){if(!type.isInstance(error))throw error;}
    }
    private static void require(boolean condition,String message){if(!condition)throw new AssertionError(message);}
}
