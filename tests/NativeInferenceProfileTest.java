package com.cyberbasslord.lightforge;

/** Host-only contract for bounded, privacy-safe native inference profiling. */
public final class NativeInferenceProfileTest {
    public static void main(String[] args) {
        NativeInferenceProfile profile = new NativeInferenceProfile();
        profile.captureStartMemory();
        NativeInferenceProfile.Measurement measured = NativeInferenceProfile.measurement(1000000L, 500000L);
        profile.addGateWait(measured); profile.addEngineInit(measured); profile.addPreflight(measured);
        profile.addBufferInit(measured); profile.addRuntimeInit(measured); profile.addRead(measured);
        profile.addEncode(measured); profile.addWrite(measured); profile.addFlush(measured);
        profile.addOutputCommit(measured); profile.noteDirectBufferBytes(123456L);
        profile.noteCacheModelHit(10L); profile.noteCacheModelHit(20L); profile.noteCacheModelMiss(30L);
        for (int i = 0; i < 30; i++) {
            String graph = "graph-" + i;
            profile.addModelPrepare(graph, measured); profile.addSessionInit(graph, measured);
            profile.addTensorBind(graph, measured); profile.addRun(graph, measured);
            profile.addPack(graph, measured); profile.addScatter(graph, measured); profile.addDecode(graph, measured);
        }
        NativeInferenceProfile.Snapshot first = profile.finish("completed");
        NativeInferenceProfile.Snapshot second = profile.finish("failed");
        require(first.recordCount() <= NativeInferenceProfile.MAX_RECORDS, "bounded summary, stages and graphs");
        require(second.recordCount() == first.recordCount() && first.record(0).equals(second.record(0)), "finish is immutable");
        String summary = first.record(0);
        require(summary.contains("schema=native-inference-profile-v2") && summary.contains("outcome=completed") &&
            summary.contains("cpuTelemetry=available") && summary.contains("memoryTelemetry=java-heap") &&
            summary.contains("acceleratorTelemetry=unavailable") && summary.contains("directBufferBytes=123456") &&
            summary.contains("cacheTelemetry=observed") && summary.contains("cacheModelHits=2") &&
            summary.contains("cacheModelMisses=1") && summary.contains("cacheHitBytes=30") && summary.contains("cacheMissBytes=30") &&
            summary.contains("graphRecords=27") && summary.contains("droppedGraphRecords=3"), "summary fields");
        int stages = 0, graphs = 0;
        for (int i = 1; i < first.recordCount(); i++) {
            String record = first.record(i);
            require(record.indexOf('"') < 0 && record.indexOf('\n') < 0, "safe bounded record " + i);
            if (record.startsWith("schema=native-inference-stage-v1")) {
                stages++;
                require(record.contains("wallMs=") && record.contains("cpuTelemetry=available") && record.contains("cpuMs=") &&
                    record.contains("heapTelemetry=java-heap"), "stage telemetry " + i);
            } else {
                graphs++;
                require(record.startsWith("schema=native-inference-graph-v2 graph=graph-") && record.contains("runCount=1 runWallMs=1") &&
                    record.contains("runCpuMs=0") && record.contains("heapTelemetry=java-heap"), "graph telemetry " + i);
            }
        }
        require(stages == NativeInferenceProfile.MAX_STAGE_RECORDS && graphs == NativeInferenceProfile.MAX_GRAPH_RECORDS,
            "fixed stage and graph inventory");

        NativeInferenceProfile unavailable = new NativeInferenceProfile();
        unavailable.addGateWait(1000000L);
        NativeInferenceProfile.Snapshot unavailableSnapshot = unavailable.finish("completed");
        String unavailableSummary = unavailableSnapshot.record(0);
        require(unavailableSummary.contains("cpuTelemetry=unavailable") && unavailableSummary.contains("instrumentedCpuMs=unavailable") &&
            unavailableSummary.contains("acceleratorTelemetry=unavailable") && unavailableSummary.contains("directBufferTelemetry=unavailable") &&
            unavailableSummary.contains("directBufferBytes=unavailable") && unavailableSummary.contains("cacheTelemetry=unavailable") &&
            unavailableSummary.contains("cacheModelHits=unavailable") && unavailableSummary.contains("cacheModelMisses=unavailable") &&
            unavailableSummary.contains("heapStartUsedBytes=unavailable"),
            "unavailable telemetry is explicit rather than fabricated");
        require(unavailableSnapshot.record(1).contains("cpuTelemetry=unavailable") &&
            unavailableSnapshot.record(1).contains("cpuMs=unavailable"), "stage CPU unavailability is explicit");
        String emptySummary = new NativeInferenceProfile().finish("cancelled").record(0);
        require(emptySummary.contains("cpuTelemetry=unavailable") && emptySummary.contains("instrumentedCpuMs=unavailable") &&
            emptySummary.contains("waitWallMs=unavailable") && emptySummary.contains("preprocessWallMs=unavailable") &&
            emptySummary.contains("cacheModelHits=unavailable"), "empty profile does not fabricate zero-valued telemetry");
        NativeInferenceProfile partial = new NativeInferenceProfile();
        partial.addModelPrepare("front", measured);
        String partialGraph = partial.finish("failed").record(2);
        require(partialGraph.contains("modelPrepareCount=1") && partialGraph.contains("modelPrepareWallMs=1") &&
            partialGraph.contains("sessionInitCount=0") && partialGraph.contains("sessionInitWallMs=unavailable") &&
            partialGraph.contains("sessionInitCpuMs=unavailable"), "unexecuted graph metrics are unavailable rather than zero");
        System.out.println("NativeInferenceProfile: bounded stage/graph telemetry, cache evidence and unavailable-metric checks passed.");
    }
    private static void require(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
}
