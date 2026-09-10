package com.cyberbasslord.lightforge;

/** Host-only contract for bounded, privacy-safe native inference profiling. */
public final class NativeInferenceProfileTest {
    public static void main(String[] args) {
        NativeInferenceProfile profile = new NativeInferenceProfile();
        profile.captureStartMemory();
        profile.addGateWait(1000000L); profile.addEngineInit(2000000L); profile.addPreflight(3000000L);
        profile.addBufferInit(4000000L); profile.addRuntimeInit(5000000L); profile.addRead(6000000L);
        profile.addEncode(7000000L); profile.addWrite(8000000L); profile.addFlush(9000000L);
        profile.addOutputCommit(10000000L); profile.noteDirectBufferBytes(123456L);
        for (int i = 0; i < 30; i++) {
            String graph = "graph-" + i;
            profile.addModelPrepare(graph, 1000000L); profile.addSessionInit(graph, 2000000L);
            profile.addTensorBind(graph, 3000000L); profile.addRun(graph, 4000000L);
            profile.addPack(graph, 5000000L); profile.addScatter(graph, 6000000L); profile.addDecode(graph, 7000000L);
        }
        NativeInferenceProfile.Snapshot first = profile.finish("completed");
        NativeInferenceProfile.Snapshot second = profile.finish("failed");
        require(first.recordCount() == NativeInferenceProfile.MAX_GRAPH_RECORDS + 1, "bounded summary plus 27 graph records");
        require(second.recordCount() == first.recordCount() && first.record(0).equals(second.record(0)), "finish is immutable");
        String summary = first.record(0);
        require(summary.contains("schema=native-inference-profile-v1") && summary.contains("outcome=completed") &&
            summary.contains("directBufferBytes=123456") && summary.contains("graphRecords=27") && summary.contains("droppedGraphRecords=3"), "summary fields");
        for (int i = 1; i < first.recordCount(); i++) {
            String record = first.record(i);
            require(record.startsWith("schema=native-inference-graph-v1 graph=graph-") && record.contains("runCount=1 runMs=4") &&
                record.indexOf('"') < 0 && record.indexOf('\n') < 0, "bounded graph record " + i);
        }
        System.out.println("NativeInferenceProfile: bounded summary, graph aggregation and immutable completion checks passed.");
    }
    private static void require(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
}
