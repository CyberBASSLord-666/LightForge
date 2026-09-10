package com.cyberbasslord.lightforge;

import java.lang.reflect.Method;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;

/**
 * Bounded, observational timing evidence for one native Deux passage.
 *
 * The collector deliberately has no compile-time Android dependency and never receives audio,
 * paths, job identifiers, exception text or model payloads. It records the fixed production
 * topology only: one summary, at most sixteen named stages, and at most the 27 Deux graphs.
 * CPU time is sampled only when the current runtime exposes a real per-thread clock. Missing
 * CPU/accelerator/cache telemetry is serialized as unavailable, never as a synthetic zero.
 */
final class NativeInferenceProfile {
    static final int MAX_GRAPH_RECORDS = 27;
    static final int MAX_STAGE_RECORDS = 16;
    static final int MAX_RECORDS = 1 + MAX_STAGE_RECORDS + MAX_GRAPH_RECORDS;
    private static final long NANOS_PER_MILLISECOND = 1000000L;
    private static final long UNSET = -1L;
    private static final CpuClock CPU_CLOCK = resolveCpuClock();

    private final long startedNanos = System.nanoTime();
    private final LinkedHashMap<String, Stage> stages = new LinkedHashMap<String, Stage>();
    private final LinkedHashMap<String, Graph> graphs = new LinkedHashMap<String, Graph>();
    private final LinkedHashSet<String> rejectedGraphs = new LinkedHashSet<String>();
    private long finishedNanos = UNSET;
    private long directBufferBytes;
    private long memoryStartUsed = UNSET, memoryStartLimit = UNSET, memoryEndUsed = UNSET, memoryEndLimit = UNSET;
    private long heapObservedPeak = UNSET;
    private int droppedGraphs, droppedStages, cacheHits, cacheMisses;
    private long cacheHitBytes, cacheMissBytes;
    private boolean cacheObserved, directBufferObserved, memoryUnavailable, cpuObserved, cpuUnavailable;
    private String outcome = "running";
    private Snapshot snapshot;

    static Timing started() { return new Timing(System.nanoTime(), CPU_CLOCK.now()); }
    static Measurement elapsed(Timing timing) {
        if (timing == null) return new Measurement(0L, UNSET);
        return new Measurement(Math.max(0L, System.nanoTime() - timing.wallStartedNanos), elapsedCpu(timing.cpuStartedNanos));
    }
    static Measurement measurement(long wallNanos, long cpuNanos) { return new Measurement(Math.max(0L, wallNanos), cpuNanos < 0L ? UNSET : cpuNanos); }
    private static long elapsedCpu(long startedCpuNanos) {
        long now = CPU_CLOCK.now();
        return startedCpuNanos == UNSET || now == UNSET ? UNSET : Math.max(0L, now - startedCpuNanos);
    }

    synchronized void captureStartMemory() {
        if (memoryStartUsed != UNSET || memoryUnavailable) return;
        Heap heap = heap();
        if (heap == null) { memoryUnavailable = true; return; }
        memoryStartUsed = heap.used; memoryStartLimit = heap.limit; noteHeap(heap.used);
    }

    synchronized void addGateWait(long nanos) { addGateWait(measurement(nanos, UNSET)); }
    synchronized void addEngineInit(long nanos) { addEngineInit(measurement(nanos, UNSET)); }
    synchronized void addPreflight(long nanos) { addPreflight(measurement(nanos, UNSET)); }
    synchronized void addBufferInit(long nanos) { addBufferInit(measurement(nanos, UNSET)); }
    synchronized void addRuntimeInit(long nanos) { addRuntimeInit(measurement(nanos, UNSET)); }
    synchronized void addRead(long nanos) { addRead(measurement(nanos, UNSET)); }
    synchronized void addEncode(long nanos) { addEncode(measurement(nanos, UNSET)); }
    synchronized void addWrite(long nanos) { addWrite(measurement(nanos, UNSET)); }
    synchronized void addFlush(long nanos) { addFlush(measurement(nanos, UNSET)); }
    synchronized void addOutputCommit(long nanos) { addOutputCommit(measurement(nanos, UNSET)); }

    synchronized void addGateWait(Measurement timing) { stage("inference-gate-wait", timing); }
    synchronized void addEngineInit(Measurement timing) { stage("engine-init", timing); }
    synchronized void addPreflight(Measurement timing) { stage("cache-preflight", timing); }
    synchronized void addBufferInit(Measurement timing) { stage("buffer-init", timing); }
    synchronized void addRuntimeInit(Measurement timing) { stage("runtime-setup", timing); }
    synchronized void addRead(Measurement timing) { stage("pcm-read", timing); }
    synchronized void addEncode(Measurement timing) { stage("feature-encode", timing); }
    synchronized void addWrite(Measurement timing) { stage("output-write", timing); }
    synchronized void addFlush(Measurement timing) { stage("output-flush", timing); }
    synchronized void addOutputCommit(Measurement timing) { stage("output-commit", timing); }

    synchronized void noteDirectBufferBytes(long bytes) { directBufferObserved = true; directBufferBytes = Math.max(directBufferBytes, nonnegative(bytes)); }
    synchronized void noteCacheModelHit(long bytes) { cacheObserved = true; cacheHits++; cacheHitBytes += nonnegative(bytes); }
    synchronized void noteCacheModelMiss(long bytes) { cacheObserved = true; cacheMisses++; cacheMissBytes += nonnegative(bytes); }

    synchronized void addModelPrepare(String graph, long nanos) { addModelPrepare(graph, measurement(nanos, UNSET)); }
    synchronized void addSessionInit(String graph, long nanos) { addSessionInit(graph, measurement(nanos, UNSET)); }
    synchronized void addTensorBind(String graph, long nanos) { addTensorBind(graph, measurement(nanos, UNSET)); }
    synchronized void addRun(String graph, long nanos) { addRun(graph, measurement(nanos, UNSET)); }
    synchronized void addPack(String graph, long nanos) { addPack(graph, measurement(nanos, UNSET)); }
    synchronized void addScatter(String graph, long nanos) { addScatter(graph, measurement(nanos, UNSET)); }
    synchronized void addDecode(String graph, long nanos) { addDecode(graph, measurement(nanos, UNSET)); }

    synchronized void addModelPrepare(String graph, Measurement timing) { Graph item = graph(graph); if (item != null) item.modelPrepare.add(timing); stage("model-init", timing); }
    synchronized void addSessionInit(String graph, Measurement timing) { Graph item = graph(graph); if (item != null) item.sessionInit.add(timing); stage("model-init", timing); }
    synchronized void addTensorBind(String graph, Measurement timing) { Graph item = graph(graph); if (item != null) item.tensorBind.add(timing); stage("tensor-bind", timing); }
    synchronized void addRun(String graph, Measurement timing) { Graph item = graph(graph); if (item != null) item.run.add(timing); stage("inference", timing); }
    synchronized void addPack(String graph, Measurement timing) { Graph item = graph(graph); if (item != null) item.pack.add(timing); stage("pack", timing); }
    synchronized void addScatter(String graph, Measurement timing) { Graph item = graph(graph); if (item != null) item.scatter.add(timing); stage("scatter", timing); }
    synchronized void addDecode(String graph, Measurement timing) { Graph item = graph(graph); if (item != null) item.decode.add(timing); stage("decode", timing); }

    /** Idempotent so failure/cancellation cleanup cannot mutate an already completed receipt. */
    synchronized Snapshot finish(String requestedOutcome) {
        if (snapshot != null) return snapshot;
        outcome = safeOutcome(requestedOutcome);
        finishedNanos = System.nanoTime();
        Heap heap = heap();
        if (heap == null) memoryUnavailable = true;
        else { memoryEndUsed = heap.used; memoryEndLimit = heap.limit; noteHeap(heap.used); }
        String[] records = new String[1 + stages.size() + graphs.size()];
        records[0] = summaryRecord();
        int index = 1;
        for (Stage stage : stages.values()) records[index++] = stageRecord(stage);
        for (Graph graph : graphs.values()) records[index++] = graphRecord(graph);
        snapshot = new Snapshot(records);
        return snapshot;
    }

    private void stage(String name, Measurement timing) {
        if (snapshot != null) return;
        Stage item = stages.get(name);
        if (item == null) {
            if (name == null || !name.matches("[a-z0-9-]{1,40}") || stages.size() >= MAX_STAGE_RECORDS) { droppedStages++; return; }
            item = new Stage(name); stages.put(name, item);
        }
        item.add(timing); noteCpu(timing);
        // One bounded heap observation per named stage avoids turning high-frequency graph batches
        // into allocator probes while still exposing stage-adjacent memory pressure.
        if (item.heapObserved == UNSET && !memoryUnavailable) {
            Heap heap = heap();
            if (heap == null) memoryUnavailable = true;
            else { item.heapObserved = heap.used; noteHeap(heap.used); }
        }
    }

    private Graph graph(String name) {
        if (snapshot != null) return null;
        if (name == null || !name.matches("[a-z0-9-]{1,40}")) { noteRejected(name); return null; }
        Graph existing = graphs.get(name);
        if (existing != null) return existing;
        if (graphs.size() >= MAX_GRAPH_RECORDS) { noteRejected(name); return null; }
        Graph created = new Graph(name);
        if (!memoryUnavailable) {
            Heap heap = heap();
            if (heap == null) memoryUnavailable = true;
            else { created.heapObserved = heap.used; noteHeap(heap.used); }
        }
        graphs.put(name, created); return created;
    }

    private void noteRejected(String name) {
        String key = name == null || !name.matches("[a-z0-9-]{1,40}") ? "invalid" : name;
        if (rejectedGraphs.size() < MAX_GRAPH_RECORDS && rejectedGraphs.add(key)) droppedGraphs++;
    }
    private void noteCpu(Measurement timing) { if (timing.cpuNanos == UNSET) cpuUnavailable = true; else cpuObserved = true; }
    private void noteHeap(long used) { heapObservedPeak = heapObservedPeak == UNSET ? used : Math.max(heapObservedPeak, used); }

    private String summaryRecord() {
        Stage preprocess = combined("preprocess", "pcm-read", "feature-encode");
        Stage postprocess = combined("postprocess", "decode", "output-write", "output-flush", "output-commit");
        Stage modelInit = stages.get("model-init"), inference = stages.get("inference"), wait = stages.get("inference-gate-wait");
        Stage engineInit = stages.get("engine-init"), preflight = stages.get("cache-preflight");
        Stage bufferInit = stages.get("buffer-init"), runtimeInit = stages.get("runtime-setup");
        return "schema=native-inference-profile-v2" +
            " outcome=" + outcome +
            " wallMs=" + milliseconds(finishedNanos - startedNanos) +
            " cpuTelemetry=" + telemetry(cpuObserved, cpuUnavailable) +
            " instrumentedCpuMs=" + valueOrUnavailable(sumCpu(stages.values()), !cpuObserved || anyCpuUnavailable(stages.values())) +
            " memoryTelemetry=" + (memoryUnavailable ? "unavailable" : "java-heap") +
            " acceleratorTelemetry=unavailable" +
            " waitWallMs=" + wall(wait) + " waitCpuMs=" + cpu(wait) +
            " engineInitWallMs=" + wall(engineInit) +
            " preflightWallMs=" + wall(preflight) +
            " bufferInitWallMs=" + wall(bufferInit) +
            " runtimeInitWallMs=" + wall(runtimeInit) +
            " preprocessWallMs=" + wall(preprocess) + " preprocessCpuMs=" + cpu(preprocess) +
            " modelInitWallMs=" + wall(modelInit) + " modelInitCpuMs=" + cpu(modelInit) +
            " inferenceWallMs=" + wall(inference) + " inferenceCpuMs=" + cpu(inference) +
            " postprocessWallMs=" + wall(postprocess) + " postprocessCpuMs=" + cpu(postprocess) +
            " directBufferTelemetry=" + (directBufferObserved ? "observed" : "unavailable") +
            " directBufferBytes=" + bytesOrUnavailable(directBufferBytes, !directBufferObserved) +
            " heapStartUsedBytes=" + bytesOrUnavailable(memoryStartUsed, memoryStartUsed == UNSET) +
            " heapStartLimitBytes=" + bytesOrUnavailable(memoryStartLimit, memoryStartLimit == UNSET) +
            " heapEndUsedBytes=" + bytesOrUnavailable(memoryEndUsed, memoryEndUsed == UNSET) +
            " heapEndLimitBytes=" + bytesOrUnavailable(memoryEndLimit, memoryEndLimit == UNSET) +
            " heapObservedPeakBytes=" + bytesOrUnavailable(heapObservedPeak, heapObservedPeak == UNSET) +
            " cacheTelemetry=" + (cacheObserved ? "observed" : "unavailable") +
            " cacheModelHits=" + countOrUnavailable(cacheHits, !cacheObserved) +
            " cacheModelMisses=" + countOrUnavailable(cacheMisses, !cacheObserved) +
            " cacheHitBytes=" + bytesOrUnavailable(cacheHitBytes, !cacheObserved) +
            " cacheMissBytes=" + bytesOrUnavailable(cacheMissBytes, !cacheObserved) +
            " stageRecords=" + stages.size() + " graphRecords=" + graphs.size() +
            " droppedStageRecords=" + droppedStages + " droppedGraphRecords=" + droppedGraphs;
    }

    private static String stageRecord(Stage stage) {
        return "schema=native-inference-stage-v1" +
            " stage=" + stage.name + " samples=" + stage.samples +
            " wallMs=" + milliseconds(stage.wallNanos) +
            " cpuTelemetry=" + telemetry(stage.cpuObserved, stage.cpuUnavailable) +
            " cpuMs=" + valueOrUnavailable(stage.cpuNanos, stage.cpuUnavailable || !stage.cpuObserved) +
            " heapTelemetry=" + (stage.heapObserved == UNSET ? "unavailable" : "java-heap") +
            " heapObservedBytes=" + bytesOrUnavailable(stage.heapObserved, stage.heapObserved == UNSET);
    }

    private static String graphRecord(Graph graph) {
        return "schema=native-inference-graph-v2" +
            " graph=" + graph.name +
            " cpuTelemetry=" + telemetry(graph.cpuObserved(), graph.cpuUnavailable()) +
            " heapTelemetry=" + (graph.heapObserved == UNSET ? "unavailable" : "java-heap") +
            " heapObservedBytes=" + bytesOrUnavailable(graph.heapObserved, graph.heapObserved == UNSET) +
            metric("modelPrepare", graph.modelPrepare) + metric("sessionInit", graph.sessionInit) +
            metric("tensorBind", graph.tensorBind) + metric("run", graph.run) +
            metric("pack", graph.pack) + metric("scatter", graph.scatter) + metric("decode", graph.decode);
    }

    private static String metric(String name, Metric value) {
        return " " + name + "Count=" + value.count + " " + name + "WallMs=" + wall(value) +
            " " + name + "CpuMs=" + valueOrUnavailable(value.cpuNanos, value.cpuUnavailable || !value.cpuObserved);
    }
    private Stage combined(String name, String... names) {
        Stage result = null;
        for (String item : names) {
            Stage stage = stages.get(item);
            if (stage != null) {
                if (result == null) result = new Stage(name);
                result.merge(stage);
            }
        }
        return result;
    }
    private static String wall(Stage stage) { return stage == null ? "unavailable" : String.valueOf(milliseconds(stage.wallNanos)); }
    private static String wall(Metric metric) { return metric.count == 0 ? "unavailable" : String.valueOf(milliseconds(metric.wallNanos)); }
    private static String cpu(Stage stage) { return stage == null ? "unavailable" : valueOrUnavailable(stage.cpuNanos, stage.cpuUnavailable || !stage.cpuObserved); }
    private static long sumCpu(Iterable<Stage> values) { long total = 0L; for (Stage value : values) total += value.cpuNanos; return total; }
    private static boolean anyCpuUnavailable(Iterable<Stage> values) { for (Stage value : values) if (value.cpuUnavailable || !value.cpuObserved) return true; return false; }
    private static long nonnegative(long value) { return Math.max(0L, value); }
    private static long milliseconds(long nanos) { return nonnegative(nanos) / NANOS_PER_MILLISECOND; }
    private static String valueOrUnavailable(long nanos, boolean unavailable) { return unavailable ? "unavailable" : String.valueOf(milliseconds(nanos)); }
    private static String bytesOrUnavailable(long value, boolean unavailable) { return unavailable ? "unavailable" : String.valueOf(value); }
    private static String countOrUnavailable(int value, boolean unavailable) { return unavailable ? "unavailable" : String.valueOf(value); }
    private static String telemetry(boolean available, boolean unavailable) { return !available ? "unavailable" : unavailable ? "partial" : "available"; }
    private static String safeOutcome(String value) { return value != null && value.matches("(?:completed|failed|cancelled|released)") ? value : "unknown"; }

    static final class Timing {
        final long wallStartedNanos, cpuStartedNanos;
        Timing(long wallStartedNanos, long cpuStartedNanos) { this.wallStartedNanos = wallStartedNanos; this.cpuStartedNanos = cpuStartedNanos; }
    }
    static final class Measurement {
        final long wallNanos, cpuNanos;
        Measurement(long wallNanos, long cpuNanos) { this.wallNanos = nonnegative(wallNanos); this.cpuNanos = cpuNanos < 0L ? UNSET : cpuNanos; }
    }
    static final class Snapshot {
        private final String[] records;
        Snapshot(String[] records) { this.records = records.clone(); }
        int recordCount() { return records.length; }
        String record(int index) { return records[index]; }
        String[] records() { return records.clone(); }
    }
    private static class Metric {
        long wallNanos, cpuNanos; int count; boolean cpuObserved, cpuUnavailable;
        void add(Measurement timing) { wallNanos += timing.wallNanos; count++; if (timing.cpuNanos == UNSET) cpuUnavailable = true; else { cpuObserved = true; cpuNanos += timing.cpuNanos; } }
    }
    private static final class Stage extends Metric {
        final String name; long heapObserved = UNSET; int samples;
        Stage(String name) { this.name = name; }
        @Override void add(Measurement timing) { super.add(timing); samples++; }
        void merge(Stage other) { wallNanos += other.wallNanos; cpuNanos += other.cpuNanos; count += other.count; samples += other.samples; cpuObserved |= other.cpuObserved; cpuUnavailable |= other.cpuUnavailable; heapObserved = heapObserved == UNSET ? other.heapObserved : other.heapObserved == UNSET ? heapObserved : Math.max(heapObserved, other.heapObserved); }
    }
    private static final class Graph {
        final String name; long heapObserved = UNSET;
        final Metric modelPrepare = new Metric(), sessionInit = new Metric(), tensorBind = new Metric(), run = new Metric(), pack = new Metric(), scatter = new Metric(), decode = new Metric();
        Graph(String name) { this.name = name; }
        boolean cpuObserved() { return modelPrepare.cpuObserved || sessionInit.cpuObserved || tensorBind.cpuObserved || run.cpuObserved || pack.cpuObserved || scatter.cpuObserved || decode.cpuObserved; }
        boolean cpuUnavailable() { return modelPrepare.cpuUnavailable || sessionInit.cpuUnavailable || tensorBind.cpuUnavailable || run.cpuUnavailable || pack.cpuUnavailable || scatter.cpuUnavailable || decode.cpuUnavailable; }
    }
    private static final class Heap { final long used, limit; Heap(long used, long limit) { this.used = used; this.limit = limit; } }
    private Heap heap() {
        try { Runtime runtime = Runtime.getRuntime(); return new Heap(Math.max(0L, runtime.totalMemory() - runtime.freeMemory()), Math.max(0L, runtime.maxMemory())); }
        catch (Throwable ignored) { return null; }
    }
    private interface CpuClock { long now(); }
    private static CpuClock resolveCpuClock() {
        final CpuClock android = androidCpuClock();
        final CpuClock host = hostCpuClock();
        return new CpuClock() { @Override public long now() {
            long value = android.now(); return value == UNSET ? host.now() : value;
        }};
    }
    private static CpuClock androidCpuClock() {
        final Method android = staticMethod("android.os.Debug", "threadCpuTimeNanos");
        if (android != null) return new CpuClock() { @Override public long now() { return invokeLong(android, null); } };
        return unavailableCpuClock();
    }
    private static CpuClock hostCpuClock() {
        try {
            Class<?> management = Class.forName("java.lang.management.ManagementFactory");
            final Object bean = management.getMethod("getThreadMXBean").invoke(null);
            Class<?> type = Class.forName("java.lang.management.ThreadMXBean");
            Object supported = type.getMethod("isCurrentThreadCpuTimeSupported").invoke(bean);
            if (!Boolean.TRUE.equals(supported)) return unavailableCpuClock();
            Method enabled = type.getMethod("isThreadCpuTimeEnabled");
            // Observation must not modify a process-wide JVM switch. If the host disables this
            // clock, report it as unavailable rather than changing inference conditions.
            if (!Boolean.TRUE.equals(enabled.invoke(bean))) return unavailableCpuClock();
            final Method current = type.getMethod("getCurrentThreadCpuTime");
            return new CpuClock() { @Override public long now() { return invokeLong(current, bean); } };
        } catch (Throwable ignored) { return unavailableCpuClock(); }
    }
    private static Method staticMethod(String className, String name) {
        try { return Class.forName(className).getMethod(name); } catch (Throwable ignored) { return null; }
    }
    private static long invokeLong(Method method, Object receiver) {
        try { Object value = method.invoke(receiver); return value instanceof Long && ((Long)value).longValue() >= 0L ? ((Long)value).longValue() : UNSET; }
        catch (Throwable ignored) { return UNSET; }
    }
    private static CpuClock unavailableCpuClock() { return new CpuClock() { @Override public long now() { return UNSET; } }; }
}
