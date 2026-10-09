package com.cyberbasslord.lightforge;

import java.io.File;
import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.zip.CRC32;

/** Exercise actual persistence, process restart and trace rotation with deterministic clocks. */
public final class DiagnosticJobSummaryTest {
    private static final String ID = "11111111-1111-4111-8111-111111111111";
    private static int checks;
    private static void require(boolean value, String message) { checks++; if (!value) throw new AssertionError(message); }
    private static void observe(DiagnosticJobSummary store, String state, String stage, long wall, long mono) throws Exception {
        store.observe(ID, 1000, wall, mono, state, stage, 4, 0, 177, "precision");
    }
    public static void main(String[] args) throws Exception {
        File root = Files.createTempDirectory("lightforge-summary-").toFile();
        File directory = new File(root, "diagnostics");
        DiagnosticJobSummary store = new DiagnosticJobSummary(directory);
        observe(store, "queued", "", 1000, 100);
        observe(store, "running", "rhythm", 1020, 120);
        observe(store, "running", "separation", 2020, 1120);
        store.profile(ID, "native-deux-v1", "outcome=completed wallMs=800 modelInitWallMs=50 inferenceWallMs=700 inferenceCount=10 sessionInitCount=27 inferenceCpuMs=600 inferenceProcessCpuMs=1300 cacheModelHits=27 temporalConfig=cpu-i6-j1-d4-sequential frequencyConfig=cpu-i4-j1-d0-sequential");
        store.profile(ID, "native-deux-v1", "outcome=failed wallMs=400 modelInitWallMs=20 inferenceWallMs=300 inferenceCount=4 sessionInitCount=7 inferenceThreadCpuMs=250 inferenceProcessCpuMs=unavailable");
        observe(store, "running", "voice", 4020, 3120);
        store.profile(ID, "native-game-v1", "outcome=completed wallMs=900 inferenceWallMs=880 inferenceProcessCpuMs=1760");
        observe(store, "running", "save", 5020, 4120);
        observe(store, "completed", "save", 5220, 4320);
        String report = store.snapshot();
        require(report.contains("lifecycleElapsedMs=4220"), "final save is included in total elapsed");
        require(report.contains("stage=rhythm observedWallMs=1000") && report.contains("stage=separation observedWallMs=2000") &&
            report.contains("stage=voice observedWallMs=1000") && report.contains("stage=save observedWallMs=200"), "original stage boundaries are accumulated");
        require(report.contains("durationMs=177000 analysisQuality=precision"), "safe workload identity survives without parsing request audio");
        require(report.contains("lastTemporalConfig=cpu-i6-j1-d4-sequential lastFrequencyConfig=cpu-i4-j1-d0-sequential"), "last observed scheduling identity survives passage failures without a new observation");
        require(report.contains("route=native-deux-v1 passages=2 completed=1 cancelled=0 otherOutcomes=1") &&
            report.contains("modelInitWallMs=70 modelInitWallMsMeasuredPassages=2") &&
            report.contains("inferenceWallMs=1000 inferenceWallMsMeasuredPassages=2") &&
            report.contains("inferenceCount=14 inferenceCountMeasuredPassages=2") &&
            report.contains("sessionInitCount=34 sessionInitCountMeasuredPassages=2"), "attempts and model/inference sums retain failed work");
        require(report.contains("inferenceThreadCpuMs=850 inferenceThreadCpuMsMeasuredPassages=2") &&
            report.contains("inferenceProcessCpuMs=1300 inferenceProcessCpuMsMeasuredPassages=1"), "thread/process scopes and partial measurement counts remain distinct");
        require(report.contains("route=native-game-v1 passages=1") && report.contains("inferenceThreadCpuMs=unavailable"), "native GAME route cannot masquerade as missing/zero CPU");
        observe(store, "completed", "save", 100000, 100000);
        require(report.equals(store.snapshot()), "reopening or duplicate terminal status cannot inflate finished elapsed");
        DiagnosticLog log = new DiagnosticLog(directory, 1024, 2);
        for (int i = 0; i < 100; i++) log.append("INFO", "native-phase", "graph execution " + i + " repeated routine detail repeated routine detail repeated routine detail");
        ByteArrayOutputStream trace = new ByteArrayOutputStream(); log.snapshot(trace);
        require(trace.size() <= 2048 && !trace.toString("UTF-8").contains("graph execution 0 "), "fixture genuinely rotates away early trace");
        require(report.equals(new DiagnosticJobSummary(directory).snapshot()), "compact summary survives trace rotation and restart exactly");
        Files.write(new File(directory, ".job-summary.tmp").toPath(), new byte[]{1, 2, 3});
        require(report.equals(new DiagnosticJobSummary(directory).snapshot()), "torn uncommitted replacement never hides last complete receipt");
        String unknown = "22222222-2222-4222-8222-222222222222";
        store.profile(unknown, "native-deux-v1", "outcome=completed wallMs=999999");
        store.profile(ID, "song-private.wav", "outcome=completed wallMs=999999");
        require(report.equals(store.snapshot()), "unowned job and unknown route cannot contaminate current totals");

        DiagnosticJobSummary negativeClock = new DiagnosticJobSummary(new File(root, "negative-clock"));
        observe(negativeClock, "running", "rhythm", 1000, -5000);
        observe(negativeClock, "completed", "rhythm", 1300, -4700);
        require(negativeClock.snapshot().contains("stage=rhythm observedWallMs=300"), "monotonic clocks may have a negative origin");

        File restartDirectory = new File(root, "restart");
        DiagnosticJobSummary before = new DiagnosticJobSummary(restartDirectory);
        observe(before, "running", "rhythm", 1000, 100);
        observe(before, "running", "separation", 2000, 1100);
        DiagnosticJobSummary after = new DiagnosticJobSummary(restartDirectory);
        after.observe(ID, 1000, 502000, 50, "running", "separation", 1, 0, Double.NaN, "");
        observe(after, "running", "save", 502100, 150);
        observe(after, "completed", "save", 502200, 250);
        String restarted = after.snapshot();
        require(restarted.contains("recoveryGaps=1") && restarted.contains("stage=separation observedWallMs=100"), "restart downtime never becomes inference time");
        require(restarted.contains("durationMs=177000 analysisQuality=precision"), "missing later metadata never erases workload identity");
        require(restarted.contains("lifecycleElapsedMs=501200"), "lifecycle wall clock honestly includes interrupted time");

        File parallelDirectory = new File(root, "parallel-configurations");
        DiagnosticJobSummary parallel = new DiagnosticJobSummary(parallelDirectory);
        observe(parallel, "running", "separation", 1000, 100);
        parallel.profile(ID, "native-deux-v1", "outcome=completed temporalConfig=cpu-i1-j1-d0-sequential-w4-b1 frequencyConfig=cpu-i4-j1-d0-sequential");
        require(new DiagnosticJobSummary(parallelDirectory).snapshot().contains(
            "lastTemporalConfig=cpu-i1-j1-d0-sequential-w4-b1 lastFrequencyConfig=cpu-i4-j1-d0-sequential"),
            "four-worker temporal scheduling survives durable persistence");
        parallel.profile(ID, "native-deux-v1", "outcome=completed temporalConfig=cpu-i1-j1-d0-sequential-w8-b1");
        for (String invalid : new String[]{"cpu-i1-j1-d0-sequential-w16-b1", "cpu-i1-j1-d0-sequential-w8-b4",
                "cpu-i2-j1-d0-sequential-w8-b1", "cpu-i1-j1-d4-sequential-w8-b1"})
            parallel.profile(ID, "native-deux-v1", "outcome=failed temporalConfig=" + invalid + " frequencyConfig=cpu-i1-j1-d0-sequential-w8-b1");
        require(new DiagnosticJobSummary(parallelDirectory).snapshot().contains(
            "lastTemporalConfig=cpu-i1-j1-d0-sequential-w8-b1 lastFrequencyConfig=cpu-i4-j1-d0-sequential"),
            "unsupported worker geometry and frequency parallelism cannot replace the last observed valid configuration");
        checkPolicyPersistence(root);
        checkLegacyMigration(root, 0x4c464a31, 11);
        checkLegacyMigration(root, 0x4c464a32, 15);
        checkFrequencyCounts(root);
        checkFormatCorruption(root);

        for (int i = 2; i <= 6; i++) {
            String id = i + "1111111-1111-4111-8111-111111111111";
            store.observe(id, 10000 + i, 10000 + i, i * 1000, "running", "private-song-name", 0, 0, 12, "private-user");
            store.profile(id, "native-deux-v1", "outcome=/private/path wallMs=-1 inferenceWallMs=not-a-number temporalConfig=private frequencyConfig=cpu-i1000-j1-d4-sequential token=secret lyrics=private title=private VEHICLE_PRIVATE_123");
        }
        String bounded = new DiagnosticJobSummary(directory).snapshot();
        require(bounded.split("jobRef=", -1).length - 1 == DiagnosticJobSummary.MAX_JOBS, "recent job retention is strictly bounded");
        require(new File(directory, "job-summary.bin").length() < DiagnosticJobSummary.MAX_BYTES, "persistent bytes are bounded");
        byte[] payload = Files.readAllBytes(new File(directory, "job-summary.bin").toPath());
        String raw = new String(payload, StandardCharsets.ISO_8859_1);
        require(!raw.contains(ID) && !raw.contains("private") && !raw.contains("VEHICLE_PRIVATE_123") && !raw.contains("secret") &&
            !bounded.contains("private") && !bounded.contains("secret") && !bounded.contains("VEHICLE_PRIVATE_123"), "storage and exports contain only hashed IDs, enums and numeric values");
        require(bounded.contains("stage=other") && bounded.contains("analysisQuality=unavailable"), "unknown strings become fixed safe enums");
        require(bounded.contains("wallMs=unavailable"), "invalid numeric values cannot become fabricated zeros");
        payload[payload.length - 1] ^= 1;
        Files.write(new File(directory, "job-summary.bin").toPath(), payload);
        String corrupt = new DiagnosticJobSummary(directory).snapshot();
        require(corrupt.contains("recovery=invalid-prior-summary-discarded") && !corrupt.contains("jobRef="), "checksum failure cannot export invented receipt values");
        System.out.println("PASS: " + checks + " durable summary checks; stage/save clocks, scope, restarts, privacy and trace-independent bounded persistence.");
    }
    private static void checkPolicyPersistence(File root) throws Exception {
        File directory = new File(root, "passage-policy");
        DiagnosticJobSummary store = new DiagnosticJobSummary(directory);
        for (int job = 1; job <= DiagnosticJobSummary.MAX_JOBS; job++) {
            String id = job + "1111111-1111-4111-8111-111111111111";
            store.observe(id, 1000, 1000, 100, "running", "separation", 0, 0, 177, "precision");
            NativeInferenceProfile profile = new NativeInferenceProfile();
            profile.notePassagePolicy(NativeInferenceProfileTest.controlEvidence());
            profile.noteSchedulerConfiguration("temporal", "cpu-i4-j1-d0-sequential");
            profile.addSessionInit("block-00-time", 1000000L);
            profile.noteSchedulerConfiguration("temporal", "cpu-i1-j1-d0-sequential-w4-b1");
            profile.addSessionInit("block-01-time", 1000000L);
            profile.noteSchedulerConfiguration("temporal", "cpu-i1-j1-d0-sequential-w8-b1");
            profile.addSessionInit("block-02-time", 1000000L);
            profile.addSessionInit("block-00-frequency", 1000000L);
            profile.noteSchedulerConfiguration("frequency", "cpu-i4-j1-d0-sequential");
            profile.addSessionInit("block-01-frequency", 1000000L);
            profile.noteSchedulerConfiguration("frequency", "cpu-i1-j1-d0-sequential-w4-b16");
            profile.addSessionInit("block-02-frequency", 1000000L);
            profile.noteSchedulerConfiguration("frequency", "cpu-i1-j1-d0-sequential-w8-b16");
            profile.addSessionInit("block-03-frequency", 1000000L);
            store.profile(id, "native-deux-v1", profile.finish("completed").record(0));
        }
        String report = store.snapshot();
        require(report.split("schema=native-passage-policy-v1", -1).length - 1 == 3 &&
            report.split("schema=native-passage-pair-v1", -1).length - 1 == 12 &&
            report.split("schema=native-passage-control-v1", -1).length - 1 == 3 &&
            report.contains("comparisonScope=unmatched-inputs"),
            "all three retained jobs preserve qualification, recheck and distinct latest unmatched control evidence");
        require(report.contains("temporalBaselineSessionCount=1 temporalBaselineSessionCountMeasuredPassages=1") &&
            report.contains("temporalFourWorkerSessionCount=1 temporalFourWorkerSessionCountMeasuredPassages=1") &&
            report.contains("temporalEightWorkerSessionCount=1 temporalEightWorkerSessionCountMeasuredPassages=1"),
            "mixed session counts reach the durable job summary independently of last configuration");
        for (String metric : new String[]{"frequencyBaselineSessionCount", "frequencyFourWorkerSessionCount",
                "frequencyEightWorkerSessionCount", "frequencyUnobservedSessionCount"})
            require(report.contains(metric + "=1 " + metric + "MeasuredPassages=1"),
                "each observed frequency session configuration reaches durable totals: " + metric);
        require(report.contains("lastFrequencyConfig=cpu-i1-j1-d0-sequential-w8-b16"),
            "last frequency scheduling configuration retains its distinct sixteen-frame geometry");
        DiagnosticLog log = new DiagnosticLog(directory, 1024, 2);
        log.append("INFO", "native-scheduler", "original qualification evidence");
        for (int i = 0; i < 200; i++) log.append("INFO", "native-phase", "repeated graph telemetry " + i);
        ByteArrayOutputStream trace = new ByteArrayOutputStream(); log.snapshot(trace);
        require(!trace.toString("UTF-8").contains("original qualification evidence"), "policy fixture actually rotates early trace");
        require(report.equals(new DiagnosticJobSummary(directory).snapshot()), "policy evidence survives rotation and process restart exactly");
        require(new File(directory, "job-summary.bin").length() < DiagnosticJobSummary.MAX_BYTES,
            "three complete policy histories and route totals fit the existing storage bound");
        store.profile(ID, "native-deux-v1", "outcome=failed passagePolicy=schema=native-passage-policy-v1,title=private-song-name");
        String retained = new DiagnosticJobSummary(directory).snapshot();
        require(retained.split("schema=native-passage-policy-v1", -1).length - 1 == 3 && !retained.contains("private-song-name"),
            "invalid later policy cannot replace complete durable evidence or introduce private text");
        store.profile(ID, "native-game-v1", "outcome=completed passagePolicy=" +
            NativeInferenceProfile.encodePassagePolicy(NativeInferenceProfileTest.policyEvidence()));
        require(store.snapshot().split("schema=native-passage-policy-v1", -1).length - 1 == 3,
            "other native routes cannot claim Deux qualification evidence");
    }
    private static byte[] fixture(int format, int metrics, int invalidMetric, boolean invalidSamples) throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream(); DataOutputStream out = new DataOutputStream(bytes);
        out.writeLong(0); out.writeInt(format); out.writeInt(1);
        out.writeUTF(DiagnosticJobSummary.reference(ID)); out.writeLong(1000); out.writeLong(2000); out.writeLong(1000);
        out.writeLong(177000); out.writeInt(1); out.writeInt(4); out.writeInt(8);
        out.writeLong(0); out.writeInt(4); out.writeInt(0);
        for (int i = 0; i < 10; i++) out.writeLong(i == 3 ? 900 : i == 8 ? 100 : 0);
        for (int route = 0; route < 3; route++) {
            out.writeLong(route == 0 ? 1 : 0); out.writeLong(route == 0 ? 1 : 0); out.writeLong(0); out.writeLong(0);
            out.writeUTF(route == 0 ? "cpu-i4-j1-d0-sequential" : "unavailable");
            out.writeUTF(route == 0 ? "cpu-i4-j1-d0-sequential" : "unavailable");
            for (int metric = 0; metric < metrics; metric++) {
                long value = route == 0 ? metric == 0 ? 800 : metric == 11 ? 12 : 0 : 0;
                long samples = route == 0 && (metric == 0 || metric >= 11) ? 1 : 0;
                if (route == 0 && metric == invalidMetric) { if (invalidSamples) samples = 2; else value = -1; }
                out.writeLong(value); out.writeLong(samples);
            }
            if (format != 0x4c464a31) out.writeUTF(route == 0 ?
                NativeInferenceProfile.encodePassagePolicy(NativeInferenceProfileTest.controlEvidence()) : "");
        }
        out.flush(); byte[] payload = bytes.toByteArray(); checksum(payload); return payload;
    }
    private static void checksum(byte[] payload) {
        CRC32 crc = new CRC32(); crc.update(payload, 8, payload.length - 8);
        long checksum = crc.getValue(); for (int i = 7; i >= 0; i--) { payload[i] = (byte)checksum; checksum >>>= 8; }
    }
    private static void checkLegacyMigration(File root, int format, int metrics) throws Exception {
        File directory = new File(root, "legacy-summary-" + metrics); require(directory.mkdir(), "legacy fixture directory created");
        Files.write(new File(directory, "job-summary.bin").toPath(), fixture(format, metrics, -1, false));
        DiagnosticJobSummary store = new DiagnosticJobSummary(directory);
        String legacy = store.snapshot();
        require(legacy.contains("recovery=normal") && legacy.contains("wallMs=800 wallMsMeasuredPassages=1") &&
            legacy.contains("temporalBaselineSessionCount=" + (metrics == 11 ? "unavailable" : "12")),
            "previous binary receipt preserves existing temporal counts and timings");
        for (String metric : new String[]{"frequencyBaselineSessionCount", "frequencyFourWorkerSessionCount",
                "frequencyEightWorkerSessionCount", "frequencyUnobservedSessionCount"})
            require(legacy.contains(metric + "=unavailable " + metric + "MeasuredPassages=0"),
                "old binary format cannot invent missing frequency measurements: " + metric);
        require((metrics == 15) == legacy.contains("schema=native-passage-control-v1"),
            "v2 policy payload is read after exactly fifteen metrics; v1 does not invent it");
        store.profile(ID, "native-deux-v1", "outcome=completed wallMs=100 temporalBaselineSessionCount=12 temporalFourWorkerSessionCount=0 temporalEightWorkerSessionCount=0 temporalUnobservedSessionCount=0 frequencyBaselineSessionCount=3 frequencyFourWorkerSessionCount=4 frequencyEightWorkerSessionCount=5 frequencyUnobservedSessionCount=0");
        String migrated = new DiagnosticJobSummary(directory).snapshot();
        require(migrated.contains("passages=2 completed=2") && migrated.contains("wallMs=900 wallMsMeasuredPassages=2") &&
            migrated.contains("temporalBaselineSessionCount=" + (metrics == 11 ? "12 temporalBaselineSessionCountMeasuredPassages=1" : "24 temporalBaselineSessionCountMeasuredPassages=2")) &&
            migrated.contains("frequencyBaselineSessionCount=3 frequencyBaselineSessionCountMeasuredPassages=1") &&
            migrated.contains("frequencyFourWorkerSessionCount=4 frequencyFourWorkerSessionCountMeasuredPassages=1") &&
            migrated.contains("frequencyEightWorkerSessionCount=5 frequencyEightWorkerSessionCountMeasuredPassages=1") &&
            migrated.contains("frequencyUnobservedSessionCount=0 frequencyUnobservedSessionCountMeasuredPassages=1"),
            "atomic format upgrade preserves legacy sums and accurately scopes new measurement coverage");
        try (java.io.DataInputStream in = new java.io.DataInputStream(new java.io.FileInputStream(new File(directory, "job-summary.bin")))) {
            in.readLong(); require(in.readInt() == 0x4c464a33, "a successful mutation atomically writes binary v3");
        }
        require(migrated.startsWith("schema=diagnostic-job-summary-v2 "), "additive export fields preserve the text schema");
    }
    private static void checkFrequencyCounts(File root) throws Exception {
        File directory = new File(root, "frequency-counts"); DiagnosticJobSummary store = new DiagnosticJobSummary(directory);
        observe(store, "running", "separation", 1000, 100);
        store.profile(ID, "native-deux-v1", "outcome=completed frequencyConfig=cpu-i1-j1-d0-sequential-w4-b16 frequencyBaselineSessionCount=1 frequencyFourWorkerSessionCount=11 frequencyEightWorkerSessionCount=0 frequencyUnobservedSessionCount=0");
        store.profile(ID, "native-deux-v1", "outcome=cancelled frequencyConfig=cpu-i1-j1-d0-sequential-w8-b16 frequencyBaselineSessionCount=0 frequencyFourWorkerSessionCount=0 frequencyEightWorkerSessionCount=2 frequencyUnobservedSessionCount=1");
        store.profile(ID, "native-deux-v1", "outcome=failed frequencyConfig=cpu-i1-j1-d0-sequential-w8-b1 temporalConfig=cpu-i1-j1-d0-sequential-w4-b16 frequencyBaselineSessionCount=unavailable frequencyFourWorkerSessionCount=-1 frequencyEightWorkerSessionCount=9223372036854775807 frequencyUnobservedSessionCount=private");
        String report = new DiagnosticJobSummary(directory).snapshot();
        require(report.contains("passages=3 completed=1 cancelled=1 otherOutcomes=1") &&
            report.contains("frequencyBaselineSessionCount=1 frequencyBaselineSessionCountMeasuredPassages=2") &&
            report.contains("frequencyFourWorkerSessionCount=11 frequencyFourWorkerSessionCountMeasuredPassages=2") &&
            report.contains("frequencyEightWorkerSessionCount=2 frequencyEightWorkerSessionCountMeasuredPassages=2") &&
            report.contains("frequencyUnobservedSessionCount=1 frequencyUnobservedSessionCountMeasuredPassages=2"),
            "mixed frequency totals retain cancellation work while invalid/missing values remain partial");
        require(report.contains("lastTemporalConfig=unavailable lastFrequencyConfig=cpu-i1-j1-d0-sequential-w8-b16"),
            "frequency b16 and temporal b1 identities cannot masquerade as each other");
    }
    private static void checkFormatCorruption(File root) throws Exception {
        byte[][] invalid = {fixture(0x4c464a33, 19, 15, false), fixture(0x4c464a33, 19, 18, true),
            fixture(0x4c464a34, 19, -1, false), fixture(0x4c464a33, 15, -1, false)};
        for (int i = 0; i < invalid.length; i++) {
            File directory = new File(root, "format-corrupt-" + i); require(directory.mkdir(), "corrupt fixture directory created");
            Files.write(new File(directory, "job-summary.bin").toPath(), invalid[i]);
            String report = new DiagnosticJobSummary(directory).snapshot();
            require(report.contains("recovery=invalid-prior-summary-discarded") && !report.contains("jobRef="),
                "CRC-valid invalid metric/count/version/length cannot export invented frequency evidence");
        }
    }
}
