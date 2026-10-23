package com.cyberbasslord.lightforge;

import java.io.File;
import java.lang.management.ManagementFactory;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Arrays;

/** Measures unchanged production classes through explicit host-only constructors. */
public final class NativeDeuxParallelBenchmark {
    private static final String PORTABLE_PROTOCOL = "portable-four-worker-three-cpu-v1";
    private static long peakRss() throws Exception {
        for (String line : Files.readAllLines(Paths.get("/proc/self/status")))
            if (line.startsWith("VmHWM:")) return Long.parseLong(line.trim().split("\\s+")[1]) * 1024;
        throw new IllegalStateException("Peak resident memory is unavailable.");
    }

    private static long processCpu() {
        java.lang.management.OperatingSystemMXBean bean = ManagementFactory.getOperatingSystemMXBean();
        if (!(bean instanceof com.sun.management.OperatingSystemMXBean))
            throw new IllegalStateException("Process CPU accounting is unavailable.");
        return ((com.sun.management.OperatingSystemMXBean) bean).getProcessCpuTime();
    }

    private static String cpuAffinity() throws Exception {
        for (String line : Files.readAllLines(Paths.get("/proc/self/status")))
            if (line.startsWith("Cpus_allowed_list:")) return line.substring(line.indexOf(':') + 1).trim();
        throw new IllegalStateException("Observed child CPU affinity is unavailable.");
    }

    private static String jsonString(String value) {
        StringBuilder result = new StringBuilder("\"");
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (c == '"' || c == '\\') result.append('\\').append(c);
            else if (c < 32 || c == 127) result.append(String.format("\\u%04x", (int)c));
            else result.append(c);
        }
        return result.append('"').toString();
    }

    private static String resourceIdentity() throws Exception {
        // Read the child's own membership, not an assumed inherited parent
        // membership. A nested/sibling cgroup can throttle independently.
        String membership = new String(Files.readAllBytes(Paths.get("/proc/self/cgroup")), StandardCharsets.UTF_8);
        String namespace = Files.readSymbolicLink(Paths.get("/proc/self/ns/cgroup")).toString();
        if (membership.isEmpty() || membership.length() > 65536 || namespace.length() > 256)
            throw new IllegalStateException("Observed child cgroup identity is unavailable or unbounded.");
        return "{\"procCgroup\":" + jsonString(membership)
            + ",\"cgroupNamespace\":" + jsonString(namespace) + "}";
    }

    private static NativeDeux runner(File models, String variant) throws Exception {
        if (variant.equals("baseline")) return new NativeDeux(models);
        int workers = variant.equals("candidate") ? 8 : variant.equals("candidate4") ? 4 : 0;
        if (workers == 0)
            throw new IllegalArgumentException("Unsupported host execution variant.");
        // Explicit host fixture: eight worker slots run on seven observed CPUs
        // so the shared cgroup retains one CPU of quota for platform work.
        // Android admission is tested separately and still requires eight
        // reported cores before it can choose an eight-worker configuration.
        // The separately declared portable fixture instead exercises four
        // production worker slots on three observed CPUs. Neither fixture
        // claims ordinary Android admission on that constrained host.
        NativeExecutionPolicy.Key key = new NativeExecutionPolicy.Key(
            "original-model-fixture", "1.25.1", "host", "performance-qualification", 8);
        for (NativeExecutionPolicy.Config config : NativeExecutionPolicy.temporalCandidates(key, Long.MAX_VALUE))
            if (config.temporalWorkers == workers && config.timeBatch == 1)
                return new NativeDeux(models, config, null);
        throw new IllegalStateException("The requested production geometry is unavailable.");
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 6 && args.length != 7)
            throw new IllegalArgumentException("models audio output startSample profile variant [protocol]");
        boolean portable = args.length == 7;
        if (portable && (!PORTABLE_PROTOCOL.equals(args[6])
                || !("baseline".equals(args[5]) || "candidate4".equals(args[5]))))
            throw new IllegalArgumentException("Unsupported portable host protocol or variant.");
        String affinity = cpuAffinity();
        int availableProcessors = Runtime.getRuntime().availableProcessors();
        if (availableProcessors != (portable ? 3 : 7))
            throw new IllegalStateException("The host fixture requires its declared observed processor count.");
        String resourceIdentityBefore = portable ? resourceIdentity() : null;
        NativeInferenceProfile profile = new NativeInferenceProfile();
        profile.captureStartMemory();
        long cpu = processCpu(), start = System.nanoTime();
        try (NativeDeux engine = runner(new File(args[0]), args[5])) {
            engine.predict(new File(args[1]), Long.parseLong(args[3]), new File(args[2]), null, () -> false, null, profile);
        }
        long elapsed = System.nanoTime() - start, elapsedCpu = processCpu() - cpu;
        NativeInferenceProfile.Snapshot snapshot = profile.finish("completed");
        Files.write(Paths.get(args[4]), Arrays.asList(snapshot.records()), StandardCharsets.UTF_8);
        if (!affinity.equals(cpuAffinity()) || availableProcessors != Runtime.getRuntime().availableProcessors())
            throw new IllegalStateException("Observed child execution capacity changed during inference.");
        String resourceIdentityAfter = portable ? resourceIdentity() : null;
        if (portable && !resourceIdentityBefore.equals(resourceIdentityAfter))
            throw new IllegalStateException("Observed child cgroup identity changed during inference.");
        System.out.println("{\"wallNanos\":" + elapsed + ",\"processCpuNanos\":" + elapsedCpu
            + ",\"peakRssBytes\":" + peakRss() + ",\"cpuAffinityList\":\"" + affinity
            + "\",\"availableProcessors\":" + availableProcessors
            + (portable ? ",\"protocol\":\"" + PORTABLE_PROTOCOL + "\",\"hostVariant\":\"" + args[5]
                + "\",\"referenceIntraThreads\":" + NativeExecutionPolicy.baseline(availableProcessors).intraThreads
                + ",\"resourceIdentityBefore\":" + resourceIdentityBefore
                + ",\"resourceIdentityAfter\":" + resourceIdentityAfter : "") + "}");
    }
}
