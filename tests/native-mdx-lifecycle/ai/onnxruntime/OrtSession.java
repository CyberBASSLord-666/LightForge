package ai.onnxruntime;
import java.util.*;
public final class OrtSession implements AutoCloseable {
    public static final class SessionOptions implements AutoCloseable {
        public enum ExecutionMode { SEQUENTIAL } public enum OptLevel { ALL_OPT }
        public void setIntraOpNumThreads(int count){} public void setInterOpNumThreads(int count){}
        public void setExecutionMode(ExecutionMode mode){} public void setOptimizationLevel(OptLevel level){}
        public void setCPUArenaAllocator(boolean value){} public void setMemoryPatternOptimization(boolean value){}
        public void addConfigEntry(String key,String value){} public void close(){}
    }
    public static final class RunOptions implements AutoCloseable {
        volatile boolean terminated,closed;
        public void setTerminate(boolean value)throws OrtException{if(closed)throw new AssertionError("Terminate after RunOptions close");terminated=value;Control.terminations++;if(value)Control.runAllowed.countDown();}
        public void close(){closed=true;}
    }
    public static final class Result implements AutoCloseable { public void close(){} }
    public Result run(Map<String,OnnxTensor> input,Set<String> names,Map<String,OnnxTensor> output,RunOptions options)throws OrtException{
        Control.running=true;Control.runs++;Control.runEntered.countDown();
        try{if(Control.blockRun)Control.await(Control.runAllowed);if(options.terminated)throw new OrtException("Terminated");
            OnnxTensor x=input.get("input"),y=output.get("output");for(int i=0;i<x.values.capacity();i++)y.values.put(i,x.values.get(i));return new Result();
        }finally{Control.running=false;}
    }
    public void close(){Control.beforeClose.run();if(Control.running)Control.closedDuringRun=true;Control.closes++;}
}
