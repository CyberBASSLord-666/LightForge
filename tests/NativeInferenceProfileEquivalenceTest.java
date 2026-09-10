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
        require(snapshot.recordCount() == NativeInferenceProfile.MAX_GRAPH_RECORDS + 1, "Expected summary plus each Deux graph");
        String summary = snapshot.record(0);
        require(summary.contains("schema=native-inference-profile-v1") && summary.contains("outcome=completed") &&
            summary.contains("graphRecords=27") && summary.contains("droppedGraphRecords=0") &&
            !summary.contains("directBufferBytes=0"), "Profile summary is incomplete");
        Set<String> expectedGraphs = new HashSet<String>(); expectedGraphs.add("front");
        for (int block = 0; block < 12; block++) {
            String prefix = "block-" + (block < 10 ? "0" : "") + block;
            expectedGraphs.add(prefix + "-time"); expectedGraphs.add(prefix + "-frequency");
        }
        expectedGraphs.add("head-0"); expectedGraphs.add("head-1");
        Set<String> actualGraphs = new HashSet<String>();
        for (int index = 1; index < snapshot.recordCount(); index++) {
            String record = snapshot.record(index);
            require(record.startsWith("schema=native-inference-graph-v1 graph=") && !record.contains("runCount=0"), "Graph timing is incomplete");
            int startGraph = record.indexOf("graph=") + 6, endGraph = record.indexOf(' ', startGraph);
            actualGraphs.add(record.substring(startGraph, endGraph));
        }
        require(actualGraphs.equals(expectedGraphs), "Profile graph inventory differs from production Deux topology");
        System.out.println("{\"outputSha256\":\"" + actual + "\",\"outputBytes\":" + output.length() +
            ",\"profileRecords\":" + snapshot.recordCount() + ",\"graphRecords\":" + actualGraphs.size() + "}");
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
