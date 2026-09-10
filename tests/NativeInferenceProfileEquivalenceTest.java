package com.cyberbasslord.lightforge;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.security.MessageDigest;
import java.util.HashSet;
import java.util.Set;

/** Full-passage host proof that enabled timing observation preserves the approved Deux bytes. */
public final class NativeInferenceProfileEquivalenceTest {
    public static void main(String[] args) throws Exception {
        if (args.length != 5) throw new IllegalArgumentException("Expected modelDirectory audio output startSample expectedSha256.");
        File model = new File(args[0]), audio = new File(args[1]), output = new File(args[2]);
        long start = Long.parseLong(args[3]); String expected = args[4];
        require(expected.matches("[0-9a-f]{64}"), "Expected output digest is invalid");
        NativeInferenceProfile profile = new NativeInferenceProfile(); profile.captureStartMemory();
        try (NativeDeux runner = new NativeDeux(model)) {
            runner.predict(audio, start, output, null, () -> false, null, profile);
        }
        NativeInferenceProfile.Snapshot snapshot = profile.finish("completed");
        require(output.length() == 2L * 573300L * 4L, "Prediction output is incomplete");
        String actual = sha256(output);
        require(expected.equals(actual), "Profiled predictor changed approved output bytes");
        require(snapshot.recordCount() <= NativeInferenceProfile.MAX_RECORDS, "Profile receipt exceeded its bounded topology");
        String summary = snapshot.record(0);
        require(summary.contains("schema=native-inference-profile-v2") && summary.contains("outcome=completed") &&
            summary.contains("graphRecords=27") && summary.contains("droppedGraphRecords=0") &&
            summary.contains("cacheTelemetry=observed") && summary.contains("cacheModelHits=27") &&
            summary.contains("cacheModelMisses=0") && summary.contains("acceleratorTelemetry=unavailable") &&
            !summary.contains("directBufferBytes=0"), "Profile summary is incomplete");
        Set<String> expectedGraphs = new HashSet<String>(); expectedGraphs.add("front");
        for (int block = 0; block < 12; block++) {
            String prefix = "block-" + (block < 10 ? "0" : "") + block;
            expectedGraphs.add(prefix + "-time"); expectedGraphs.add(prefix + "-frequency");
        }
        expectedGraphs.add("head-0"); expectedGraphs.add("head-1");
        Set<String> actualGraphs = new HashSet<String>(), actualStages = new HashSet<String>();
        for (int index = 1; index < snapshot.recordCount(); index++) {
            String record = snapshot.record(index);
            if (record.startsWith("schema=native-inference-stage-v1 stage=")) {
                int startStage = record.indexOf("stage=") + 6, endStage = record.indexOf(' ', startStage);
                actualStages.add(record.substring(startStage, endStage));
                require(record.contains("wallMs=") && record.contains("cpuTelemetry=") && record.contains("heapTelemetry="), "Stage telemetry is incomplete");
            } else {
                require(record.startsWith("schema=native-inference-graph-v2 graph=") && !record.contains("runCount=0") &&
                    record.contains("runWallMs=") && record.contains("runCpuMs=") && record.contains("heapTelemetry="), "Graph timing is incomplete");
                int startGraph = record.indexOf("graph=") + 6, endGraph = record.indexOf(' ', startGraph);
                actualGraphs.add(record.substring(startGraph, endGraph));
            }
        }
        require(actualGraphs.equals(expectedGraphs), "Profile graph inventory differs from production Deux topology");
        Set<String> expectedStages = new HashSet<String>();
        for (String stage : new String[]{"inference-gate-wait", "cache-preflight", "buffer-init", "runtime-setup", "pcm-read", "feature-encode", "model-init", "tensor-bind", "inference", "pack", "scatter", "decode", "output-write", "output-flush", "output-commit"}) expectedStages.add(stage);
        require(actualStages.equals(expectedStages), "Profile stage inventory differs from the full production passage");
        System.out.println("{\"outputSha256\":\"" + actual + "\",\"outputBytes\":" + output.length() +
            ",\"profileRecords\":" + snapshot.recordCount() + ",\"stageRecords\":" + actualStages.size() + ",\"graphRecords\":" + actualGraphs.size() + "}");
    }

    private static String sha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = new FileInputStream(file)) {
            byte[] block = new byte[262144]; int count;
            while ((count = input.read(block)) != -1) digest.update(block, 0, count);
        }
        StringBuilder result = new StringBuilder();
        for (byte value : digest.digest()) result.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
        return result.toString();
    }
    private static void require(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
}
