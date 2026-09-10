package com.cyberbasslord.lightforge;

import java.util.LinkedHashMap;
import java.util.LinkedHashSet;

/**
 * Bounded, allocation-light timing evidence for one native Deux passage.
 *
 * This class deliberately contains no audio, model path, job id, exception text or Android
 * dependency. It is an observer only: callers pass already-measured durations and emit one
 * immutable summary plus at most one record for each of the 27 known Deux graphs.
 */
final class NativeInferenceProfile {
    static final int MAX_GRAPH_RECORDS = 27;
    private static final long NANOS_PER_MILLISECOND = 1000000L;
    private static final long UNSET = -1L;
    private final long startedNanos = System.nanoTime();
    private final LinkedHashMap<String, Graph> graphs = new LinkedHashMap<String, Graph>();
    // Bound rejected-name bookkeeping as tightly as emitted graph records. This makes a rejected
    // graph count once even though a caller may attempt several timing dimensions for it.
    private final LinkedHashSet<String> rejectedGraphs = new LinkedHashSet<String>();
    private long finishedNanos = UNSET;
    private long gateWaitNanos, engineInitNanos, preflightNanos, bufferInitNanos, runtimeInitNanos;
    private long readNanos, encodeNanos, writeNanos, flushNanos, outputCommitNanos, directBufferBytes;
    private long memoryStartUsed = UNSET, memoryStartLimit = UNSET, memoryEndUsed = UNSET, memoryEndLimit = UNSET;
    private int droppedGraphs;
    private String outcome = "running";
    private Snapshot snapshot;

    static long started() { return System.nanoTime(); }
    static long elapsed(long startedNanos) { return Math.max(0L, System.nanoTime() - startedNanos); }

    synchronized void captureStartMemory() {
        if (memoryStartUsed != UNSET) return;
        Runtime runtime = Runtime.getRuntime();
        memoryStartUsed = Math.max(0L, runtime.totalMemory() - runtime.freeMemory());
        memoryStartLimit = Math.max(0L, runtime.maxMemory());
    }

    synchronized void addGateWait(long nanos) { gateWaitNanos += nonnegative(nanos); }
    synchronized void addEngineInit(long nanos) { engineInitNanos += nonnegative(nanos); }
    synchronized void addPreflight(long nanos) { preflightNanos += nonnegative(nanos); }
    synchronized void addBufferInit(long nanos) { bufferInitNanos += nonnegative(nanos); }
    synchronized void addRuntimeInit(long nanos) { runtimeInitNanos += nonnegative(nanos); }
    synchronized void addRead(long nanos) { readNanos += nonnegative(nanos); }
    synchronized void addEncode(long nanos) { encodeNanos += nonnegative(nanos); }
    synchronized void addWrite(long nanos) { writeNanos += nonnegative(nanos); }
    synchronized void addFlush(long nanos) { flushNanos += nonnegative(nanos); }
    synchronized void addOutputCommit(long nanos) { outputCommitNanos += nonnegative(nanos); }
    synchronized void noteDirectBufferBytes(long bytes) { directBufferBytes = Math.max(directBufferBytes, nonnegative(bytes)); }

    synchronized void addModelPrepare(String graph, long nanos) { Graph item = graph(graph); if (item != null) { item.modelPrepareNanos += nonnegative(nanos); item.modelPrepareCount++; } }
    synchronized void addSessionInit(String graph, long nanos) { Graph item = graph(graph); if (item != null) { item.sessionInitNanos += nonnegative(nanos); item.sessionCount++; } }
    synchronized void addTensorBind(String graph, long nanos) { Graph item = graph(graph); if (item != null) { item.tensorBindNanos += nonnegative(nanos); item.tensorBindCount++; } }
    synchronized void addRun(String graph, long nanos) { Graph item = graph(graph); if (item != null) { item.runNanos += nonnegative(nanos); item.runCount++; } }
    synchronized void addPack(String graph, long nanos) { Graph item = graph(graph); if (item != null) { item.packNanos += nonnegative(nanos); item.packCount++; } }
    synchronized void addScatter(String graph, long nanos) { Graph item = graph(graph); if (item != null) { item.scatterNanos += nonnegative(nanos); item.scatterCount++; } }
    synchronized void addDecode(String graph, long nanos) { Graph item = graph(graph); if (item != null) { item.decodeNanos += nonnegative(nanos); item.decodeCount++; } }

    /** Idempotent so failure/cancellation cleanup cannot mutate an already completed receipt. */
    synchronized Snapshot finish(String requestedOutcome) {
        if (snapshot != null) return snapshot;
        outcome = safeOutcome(requestedOutcome);
        finishedNanos = System.nanoTime();
        Runtime runtime = Runtime.getRuntime();
        memoryEndUsed = Math.max(0L, runtime.totalMemory() - runtime.freeMemory());
        memoryEndLimit = Math.max(0L, runtime.maxMemory());
        String[] records = new String[1 + graphs.size()];
        records[0] = summaryRecord();
        int index = 1;
        for (Graph graph : graphs.values()) records[index++] = graphRecord(graph);
        snapshot = new Snapshot(records);
        return snapshot;
    }

    private Graph graph(String name) {
        if (snapshot != null) return null;
        if (name == null || !name.matches("[a-z0-9-]{1,40}")) { noteRejected(name); return null; }
        Graph existing = graphs.get(name);
        if (existing != null) return existing;
        if (graphs.size() >= MAX_GRAPH_RECORDS) { noteRejected(name); return null; }
        Graph created = new Graph(name); graphs.put(name, created); return created;
    }

    private void noteRejected(String name) {
        // Invalid/null names are represented by one fixed marker, and this cap prevents a caller
        // from turning diagnostics into unbounded retained strings.
        String key = name == null || !name.matches("[a-z0-9-]{1,40}") ? "invalid" : name;
        if (rejectedGraphs.size() < MAX_GRAPH_RECORDS && rejectedGraphs.add(key)) droppedGraphs++;
    }

    private String summaryRecord() {
        return "schema=native-inference-profile-v1" +
            " outcome=" + outcome +
            " totalMs=" + milliseconds(finishedNanos - startedNanos) +
            " gateWaitMs=" + milliseconds(gateWaitNanos) +
            " engineInitMs=" + milliseconds(engineInitNanos) +
            " preflightMs=" + milliseconds(preflightNanos) +
            " bufferInitMs=" + milliseconds(bufferInitNanos) +
            " runtimeInitMs=" + milliseconds(runtimeInitNanos) +
            " readMs=" + milliseconds(readNanos) +
            " encodeMs=" + milliseconds(encodeNanos) +
            " writeMs=" + milliseconds(writeNanos) +
            " flushMs=" + milliseconds(flushNanos) +
            " outputCommitMs=" + milliseconds(outputCommitNanos) +
            " directBufferBytes=" + directBufferBytes +
            " heapStartUsedBytes=" + value(memoryStartUsed) +
            " heapStartLimitBytes=" + value(memoryStartLimit) +
            " heapEndUsedBytes=" + value(memoryEndUsed) +
            " heapEndLimitBytes=" + value(memoryEndLimit) +
            " graphRecords=" + graphs.size() +
            " droppedGraphRecords=" + droppedGraphs;
    }

    private static String graphRecord(Graph graph) {
        return "schema=native-inference-graph-v1" +
            " graph=" + graph.name +
            " modelPrepareCount=" + graph.modelPrepareCount + " modelPrepareMs=" + milliseconds(graph.modelPrepareNanos) +
            " sessionCount=" + graph.sessionCount + " sessionInitMs=" + milliseconds(graph.sessionInitNanos) +
            " tensorBindCount=" + graph.tensorBindCount + " tensorBindMs=" + milliseconds(graph.tensorBindNanos) +
            " runCount=" + graph.runCount + " runMs=" + milliseconds(graph.runNanos) +
            " packCount=" + graph.packCount + " packMs=" + milliseconds(graph.packNanos) +
            " scatterCount=" + graph.scatterCount + " scatterMs=" + milliseconds(graph.scatterNanos) +
            " decodeCount=" + graph.decodeCount + " decodeMs=" + milliseconds(graph.decodeNanos);
    }

    private static long nonnegative(long value) { return Math.max(0L, value); }
    private static long milliseconds(long nanos) { return nonnegative(nanos) / NANOS_PER_MILLISECOND; }
    private static long value(long number) { return number == UNSET ? 0L : number; }
    private static String safeOutcome(String value) { return value != null && value.matches("(?:completed|failed|cancelled|released)") ? value : "unknown"; }

    static final class Snapshot {
        private final String[] records;
        Snapshot(String[] records) { this.records = records.clone(); }
        int recordCount() { return records.length; }
        String record(int index) { return records[index]; }
        String[] records() { return records.clone(); }
    }

    private static final class Graph {
        final String name;
        long modelPrepareNanos, sessionInitNanos, tensorBindNanos, runNanos, packNanos, scatterNanos, decodeNanos;
        int modelPrepareCount, sessionCount, tensorBindCount, runCount, packCount, scatterCount, decodeCount;
        Graph(String name) { this.name = name; }
    }
}
