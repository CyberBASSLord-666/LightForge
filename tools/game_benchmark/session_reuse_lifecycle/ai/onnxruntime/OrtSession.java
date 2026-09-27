package ai.onnxruntime;
import java.util.*;
public final class OrtSession extends Control.Resource {
    private final String graph;
    OrtSession(String graph){super("session");this.graph=graph;}
    public static final class SessionOptions extends Control.Resource {
        public enum ExecutionMode { SEQUENTIAL } public enum OptLevel { ALL_OPT,BASIC_OPT }
        public SessionOptions(){super("sessionOptions");}
        public void setIntraOpNumThreads(int value){} public void setInterOpNumThreads(int value){}
        public void setExecutionMode(ExecutionMode value){} public void setOptimizationLevel(OptLevel value){}
        public void setCPUArenaAllocator(boolean value){} public void setMemoryPatternOptimization(boolean value){}
        public void setDeterministicCompute(boolean value){} public void addConfigEntry(String key,String value){}
        public void addCUDA(ai.onnxruntime.providers.OrtCUDAProviderOptions value){value.usable();}
    }
    public static final class RunOptions extends Control.Resource {
        public volatile boolean terminated;
        public RunOptions(){super("runOptions");}
        public void setTerminate(boolean value)throws OrtException{usable();terminated=value;Control.terminations++;if(value)Control.runAllowed.countDown();}
        @Override public void close()throws Exception{Control.beforeRunClose.call();super.close();}
    }
    public static final class Result extends Control.Resource {
        private final Map<String,OnnxValue> values=new LinkedHashMap<>();
        Result(){super("result");}
        Result put(String name,OnnxTensor value){values.put(name,value);return this;}
        public Optional<OnnxValue> get(String name){usable();return Optional.ofNullable(values.get(name));}
        @Override public void close()throws Exception {
            usable();Throwable first=null;
            for(OnnxValue value:values.values())try{value.close();}catch(Throwable error){if(first==null)first=error;}
            try{super.close();}catch(Throwable error){if(first==null)first=error;}
            if(first instanceof Exception)throw (Exception)first;
            if(first instanceof Error)throw (Error)first;
        }
    }
    public Result run(Map<String,OnnxTensor> input,RunOptions options)throws Exception {
        usable();options.usable();for(OnnxTensor value:input.values())value.usable();
        Control.runCalls++;Control.running++;Control.runEntered.countDown();
        try {
            Control.beforeRun.call();if(Control.blockRun)Control.await(Control.runAllowed);
            if(options.terminated)throw new OrtException("Cooperatively terminated");
            if(Control.runCalls==Control.failRunCall)throw new OrtException("Injected inference failure");
            Result result=new Result();
            if(graph.equals("encoder"))return result.put("maskT",OnnxTensor.bools(new byte[]{1},1,1))
                .put("x_seg",OnnxTensor.floats(new float[256],1,1,256)).put("x_est",OnnxTensor.floats(new float[256],1,1,256));
            if(graph.equals("dur2bd")||graph.equals("segmenter"))return result.put("boundaries",OnnxTensor.bools(new byte[]{1},1,1));
            if(graph.equals("bd2dur"))return result.put("durations",OnnxTensor.floats(new float[]{.1f},1,1)).put("maskN",OnnxTensor.bools(new byte[]{1},1,1));
            if(graph.equals("estimator"))return result.put("scores",OnnxTensor.floats(new float[]{60},1,1)).put("presence",OnnxTensor.bools(new byte[]{1},1,1));
            throw new AssertionError("Unknown graph");
        } finally {Control.running--;}
    }
    @Override public void close()throws Exception {
        Control.check(Control.running==0,"Session destroyed during active inference");
        Control.beforeSessionClose.call();super.close();
    }
}
