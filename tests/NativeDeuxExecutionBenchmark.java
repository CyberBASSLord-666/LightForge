package com.cyberbasslord.lightforge;
import java.io.File;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.nio.charset.StandardCharsets;
import java.lang.management.ManagementFactory;
import java.util.Arrays;

/** Full production passage; timing excludes JVM startup and result inspection. */
public final class NativeDeuxExecutionBenchmark {
  static long peakRss() {
    try {
      for (String s: Files.readAllLines(Paths.get("/proc/self/status")))
        if (s.startsWith("VmHWM:")) return Long.parseLong(s.trim().split("\\s+")[1])*1024;
    } catch (Exception unavailable) { /* Non-Linux host. */ }
    return -1;
  }
  static long processCpu() {
    java.lang.management.OperatingSystemMXBean bean=ManagementFactory.getOperatingSystemMXBean();
    return bean instanceof com.sun.management.OperatingSystemMXBean ? ((com.sun.management.OperatingSystemMXBean)bean).getProcessCpuTime() : -1;
  }
  public static void main(String[] args) throws Exception {
    if(args.length!=5)throw new IllegalArgumentException("models audio output startSample profile");
    NativeInferenceProfile profile=new NativeInferenceProfile();profile.captureStartMemory();
    long cpu=processCpu(),start=System.nanoTime();
    try(NativeDeux runner=new NativeDeux(new File(args[0]))) {
      runner.predict(new File(args[1]),Long.parseLong(args[3]),new File(args[2]),null,()->false,null,profile);
    }
    long elapsed=System.nanoTime()-start,endCpu=processCpu();
    long elapsedCpu=cpu<0 || endCpu<0 ? -1 : endCpu-cpu;
    NativeInferenceProfile.Snapshot snapshot=profile.finish("completed");
    Files.write(Paths.get(args[4]),Arrays.asList(snapshot.records()),StandardCharsets.UTF_8);
    System.out.println("{\"wallNanos\":"+elapsed+",\"processCpuNanos\":"+elapsedCpu+",\"peakRssBytes\":"+peakRss()+"}");
  }
}
