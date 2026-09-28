package com.cyberbasslord.lightforge;

import java.util.LinkedHashMap;
import java.util.Map;

public final class NativeGameProfileTest {
    private static int checks;
    private static final class Clock implements NativeGameProfile.Clock {
        long wall,cpu;
        public long wallNanos(){return wall;}
        public long processCpuNanos(){return cpu;}
        void advance(long wallMs,long cpuMs){wall+=wallMs*1000000;cpu+=cpuMs*1000000;}
    }
    private static void require(boolean value,String detail){checks++;if(!value)throw new AssertionError(detail);}
    private static Map<String,String> fields(String text){
        Map<String,String> result=new LinkedHashMap<>();
        for(String field:text.split(" ")){String[] pair=field.split("=",-1);require(pair.length==2,"one bounded key/value pair");require(result.put(pair[0],pair[1])==null,"unique field");}
        return result;
    }
    public static void main(String[] args){
        Clock clock=new Clock();NativeGameProfile profile=new NativeGameProfile(4,clock);
        NativeGameProfile.Stamp start=profile.started();clock.advance(10,20);profile.addSessionInit("segmenter",start);
        for(int i=0;i<8;i++){start=profile.started();clock.advance(10,25);profile.addInference("segmenter",start);}
        start=profile.started();clock.advance(3,1);profile.addPrepare(start);
        start=profile.started();clock.advance(4,0);profile.addWait(start);
        profile.cache(true);profile.cache(false);
        NativeGameProfile.Snapshot snapshot=profile.finish("completed");Map<String,String> record=fields(snapshot.summary());
        require("97".equals(record.get("wallMs")),"whole passage wall time");
        require("10".equals(record.get("modelInitWallMs")),"session initialization excludes kernels");
        require("80".equals(record.get("inferenceWallMs")),"kernel wall sum");
        require("200".equals(record.get("inferenceProcessCpuMs")),"process CPU includes parallel workers without clamping to wall");
        require("unavailable".equals(record.get("inferenceThreadCpuMs")),"never invent a thread CPU clock");
        require("8".equals(record.get("inferenceCount"))&&"8".equals(record.get("segmenterRunCount")),"all eight steps counted");
        require("1".equals(record.get("sessionInitCount")),"session counts are independent of inference");
        require("process-all-app-threads".equals(record.get("cpuScope")),"CPU scope explicit");
        require("unavailable".equals(record.get("encoderRunWallMs")),"unexecuted graph is unavailable, not zero duration");
        require("native-game-v1".equals(record.get("route"))&&"onnxruntime-1.25.1".equals(record.get("runtime")),"route/runtime identity");
        require("cpu".equals(record.get("provider"))&&"float32".equals(record.get("precision"))&&"8".equals(record.get("steps")),"execution identity");
        require(snapshot.summary().length()<4096,"one bounded log record");
        clock.advance(20,20);profile.addInference("segmenter",start);profile.cache(true);
        require(profile.finish("failed")==snapshot,"immutable idempotent final receipt");
        require("1".equals(fields(snapshot.summary()).get("cacheModelHits")),"late work cannot mutate receipt");
        Clock unavailable=new Clock();unavailable.cpu=-1;
        NativeGameProfile absent=new NativeGameProfile(4,unavailable);start=absent.started();unavailable.wall=3000000;absent.addInference("encoder",start);
        Map<String,String> absentRecord=fields(absent.finish("private file path / song title").summary());
        require("unknown".equals(absentRecord.get("outcome")),"arbitrary outcome text is not retained");
        require("unavailable".equals(absentRecord.get("inferenceProcessCpuMs")),"missing CPU clock is not fabricated");
        require("4".equals(absentRecord.get("intraOpThreads")),"production thread limit");
        require("unavailable".equals(absentRecord.get("cacheModelHits")),"unobserved cache is not a hit");
        Clock regressing=new Clock();regressing.cpu=10000000;NativeGameProfile rollback=new NativeGameProfile(1,regressing);
        start=rollback.started();regressing.cpu=0;regressing.wall=1000000;rollback.addInference("encoder",start);
        require("unavailable".equals(fields(rollback.finish("cancelled").summary()).get("inferenceProcessCpuMs")),"invalid CPU deltas are unavailable");
        NativeGameProfile bounded=new NativeGameProfile(1,new Clock());
        try{new NativeGameProfile(100,new Clock());throw new AssertionError("invalid thread identity accepted");}
        catch(IllegalArgumentException expected){checks++;}
        try{bounded.addInference("private path",bounded.started());throw new AssertionError("unbounded graph accepted");}
        catch(IllegalArgumentException expected){checks++;}
        System.out.println("PASS: "+checks+" bounded GAME profile checks");
    }
}
