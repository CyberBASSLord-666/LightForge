package com.cyberbasslord.lightforge;

import java.io.File;
import java.io.DataOutputStream;
import java.io.FileOutputStream;
import java.io.FileInputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Full-passage same-runtime proof that enabling the observer preserves native Deux output.
 *
 * The approved historical digest is recorded for reproducibility only. The pass condition is
 * an unprofiled/profiled pair made in this JVM, against fixed predeclared numerical limits.
 */
public final class NativeInferenceProfileEquivalenceTest {
    static final int SAMPLES_PER_STEM = 573300;
    private static final String SESSION_PATTERN = "[0-9a-f]{32,128}";
    private static final byte[] PROFILE_RECORD_MAGIC = "lightforge.native-inference-profile-records.v1\0".getBytes(StandardCharsets.US_ASCII);

    public static void main(String[] args) throws Exception {
        if (args.length != 8) throw new IllegalArgumentException("Expected modelDirectory audio unprofiledOutput profiledOutput profileRecords startSample approvedHistoricalSha256 evidenceSession.");
        File model = new File(args[0]), audio = new File(args[1]);
        File unprofiledOutput = new File(args[2]), profiledOutput = new File(args[3]);
        File profileRecords = new File(args[4]);
        long start = Long.parseLong(args[5]); String approvedHistorical = args[6], evidenceSession = args[7];
        require(approvedHistorical.matches("[0-9a-f]{64}"), "Approved historical digest is invalid");
        require(evidenceSession.equals("-") || evidenceSession.matches(SESSION_PATTERN), "Evidence session is invalid");

        try (NativeDeux runner = new NativeDeux(model)) {
            runner.predict(audio, start, unprofiledOutput, null, () -> false, null);
        }
        NativeInferenceProfile profile = new NativeInferenceProfile(); profile.captureStartMemory();
        try (NativeDeux runner = new NativeDeux(model)) {
            runner.predict(audio, start, profiledOutput, null, () -> false, null, profile);
        }
        NativeInferenceProfile.Snapshot snapshot = profile.finish("completed");
        ProfileTopology topology = validateProfile(snapshot);
        writeCanonicalProfileRecords(profileRecords, snapshot);
        long expectedBytes = NativeInferenceProfileOutputComparison.expectedBytes(SAMPLES_PER_STEM);
        require(unprofiledOutput.length() == expectedBytes, "Unprofiled prediction output is incomplete");
        require(profiledOutput.length() == expectedBytes, "Profiled prediction output is incomplete");
        String unprofiledSha = sha256(unprofiledOutput), profiledSha = sha256(profiledOutput);
        NativeInferenceProfileOutputComparison.StemComparison[] comparison = NativeInferenceProfileOutputComparison.compare(unprofiledOutput, profiledOutput, SAMPLES_PER_STEM);
        require(NativeInferenceProfileOutputComparison.withinPredeclaredLimits(comparison), "Profiled predictor differs from same-run unprofiled output beyond predeclared numerical limits");
        boolean byteIdentical = unprofiledSha.equals(profiledSha);
        require(byteIdentical, "Profiled predictor differs from same-run unprofiled output bytes");
        System.out.println("{\"evidenceSession\":" + (evidenceSession.equals("-") ? "null" : "\"" + evidenceSession + "\"") +
            ",\"historicalApprovedSha256\":\"" + approvedHistorical + "\"" +
            ",\"unprofiledOutputSha256\":\"" + unprofiledSha + "\"" +
            ",\"profiledOutputSha256\":\"" + profiledSha + "\"" +
            ",\"unprofiledOutputBytes\":" + unprofiledOutput.length() +
            ",\"profiledOutputBytes\":" + profiledOutput.length() +
            ",\"byteIdentical\":" + byteIdentical +
            ",\"unprofiledMatchesHistorical\":" + unprofiledSha.equals(approvedHistorical) +
            ",\"profiledMatchesHistorical\":" + profiledSha.equals(approvedHistorical) +
            ",\"criteria\":{\"stems\":" + NativeInferenceProfileOutputComparison.STEM_COUNT +
            ",\"samples_per_stem\":" + SAMPLES_PER_STEM + ",\"output_bytes\":" + expectedBytes +
            ",\"finite_required\":true,\"byte_identity_required\":" + NativeInferenceProfileOutputComparison.BYTE_IDENTITY_REQUIRED +
            ",\"max_absolute_error\":" + NativeInferenceProfileOutputComparison.MAX_ABSOLUTE_ERROR +
            ",\"rmse\":" + NativeInferenceProfileOutputComparison.MAX_RMSE + ",\"relative_rmse\":" + NativeInferenceProfileOutputComparison.MAX_RELATIVE_RMSE + "}" +
            ",\"profile\":{\"record_sha256\":\"" + sha256(profileRecords) + "\"" +
            ",\"record_bytes\":" + profileRecords.length() + ",\"records\":" + snapshot.recordCount() +
            ",\"stage_records\":" + countRecords(snapshot, "schema=native-inference-stage-v1") +
            ",\"graph_records\":" + countRecords(snapshot, "schema=native-inference-graph-v2") +
            ",\"topology\":" + topology.json() + "}" +
            ",\"comparison\":" + NativeInferenceProfileOutputComparison.json(comparison) + "}");
    }

    private static ProfileTopology validateProfile(NativeInferenceProfile.Snapshot snapshot) {
        require(snapshot.recordCount() <= NativeInferenceProfile.MAX_RECORDS, "Profile receipt exceeded its bounded topology");
        String summary = snapshot.record(0);
        require(summary.contains("schema=native-inference-profile-v2") && summary.contains("outcome=completed") &&
            summary.contains("graphRecords=27") && summary.contains("droppedGraphRecords=0") &&
            summary.contains("cacheTelemetry=observed") && summary.contains("cacheModelHits=27") &&
            summary.contains("cacheModelMisses=0") && summary.contains("acceleratorTelemetry=unavailable") &&
            !summary.contains("directBufferBytes=0"), "Profile summary is incomplete");
        java.util.Set<String> expectedGraphs = new java.util.HashSet<String>(); expectedGraphs.add("front");
        for (int block = 0; block < 12; block++) {
            String prefix = "block-" + (block < 10 ? "0" : "") + block;
            expectedGraphs.add(prefix + "-time"); expectedGraphs.add(prefix + "-frequency");
        }
        expectedGraphs.add("head-0"); expectedGraphs.add("head-1");
        java.util.Set<String> actualGraphs = new java.util.HashSet<String>(), actualStages = new java.util.HashSet<String>();
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
        java.util.Set<String> expectedStages = new java.util.HashSet<String>();
        for (String stage : new String[]{"inference-gate-wait", "cache-preflight", "buffer-init", "runtime-setup", "pcm-read", "feature-encode", "model-init", "tensor-bind", "inference", "pack", "scatter", "decode", "output-write", "output-flush", "output-commit"}) expectedStages.add(stage);
        require(actualStages.equals(expectedStages), "Profile stage inventory differs from the full production passage");
        return new ProfileTopology(actualStages, actualGraphs);
    }

    private static int countRecords(NativeInferenceProfile.Snapshot snapshot, String prefix) {
        int count = 0; for (int index = 1; index < snapshot.recordCount(); index++) if (snapshot.record(index).startsWith(prefix)) count++;
        return count;
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
    private static void writeCanonicalProfileRecords(File output, NativeInferenceProfile.Snapshot snapshot) throws Exception {
        File parent = output.getAbsoluteFile().getParentFile();
        if (parent != null && !parent.isDirectory() && !parent.mkdirs()) throw new java.io.IOException("Cannot create profile record directory");
        try (DataOutputStream stream = new DataOutputStream(new FileOutputStream(output))) {
            stream.write(PROFILE_RECORD_MAGIC); stream.writeInt(snapshot.recordCount());
            for (String record : snapshot.records()) {
                require(record.indexOf('\n') < 0 && record.indexOf('\r') < 0, "Profile record is not canonical");
                byte[] bytes = record.getBytes(StandardCharsets.UTF_8);
                stream.writeInt(bytes.length); stream.write(bytes);
            }
            stream.flush();
        }
    }
    private static final class ProfileTopology {
        final List<String> stages, graphs;
        ProfileTopology(java.util.Set<String> stages, java.util.Set<String> graphs) {
            this.stages = new ArrayList<String>(stages); this.graphs = new ArrayList<String>(graphs);
            Collections.sort(this.stages); Collections.sort(this.graphs);
        }
        String json() { return "{\"summary_schema\":\"native-inference-profile-v2\",\"stage_schema\":\"native-inference-stage-v1\",\"graph_schema\":\"native-inference-graph-v2\",\"stages\":" + names(stages) + ",\"graphs\":" + names(graphs) + "}"; }
        private static String names(List<String> names) {
            StringBuilder result = new StringBuilder("[");
            for (int index = 0; index < names.size(); index++) { if (index > 0) result.append(','); result.append('\"').append(names.get(index)).append('\"'); }
            return result.append(']').toString();
        }
    }
    private static void require(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
}
