package com.cyberbasslord.lightforge;

import java.io.File;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

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
}
