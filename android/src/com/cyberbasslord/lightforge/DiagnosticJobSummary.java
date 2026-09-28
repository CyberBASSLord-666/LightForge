package com.cyberbasslord.lightforge;

import java.io.*;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Locale;
import java.util.zip.CRC32;

/** Fixed-schema job receipts, independent of the rotating verbose trace. No Android dependency. */
final class DiagnosticJobSummary {
    static final int MAX_JOBS = 3, MAX_BYTES = 32768;
    private static final int MAGIC = 0x4c464a31;
    private static final String[] STAGES = {"preparing", "compatibility", "rhythm", "separation", "voice", "bass", "recurrence", "generate", "save", "other"};
    private static final String[] STATES = {"preparing", "queued", "running", "cancelling", "completed", "failed", "cancelled", "interrupted", "unknown"};
    private static final String[] ROUTES = {"native-deux-v1", "native-mdx-v1", "native-game-v1"};
    private static final String[] METRICS = {"wallMs", "modelInitWallMs", "inferenceWallMs", "inferenceCount", "sessionInitCount", "inferenceThreadCpuMs", "inferenceProcessCpuMs", "cacheModelHits", "cacheModelMisses", "schedulerCalibrationWallMs", "schedulerCalibrationCount"};
    private static DiagnosticJobSummary shared;
    private final File directory;
    private final ArrayList<Job> jobs = new ArrayList<Job>();
    private boolean loaded, corruptRecovery;

    DiagnosticJobSummary(File directory) { this.directory = directory; }
    static synchronized DiagnosticJobSummary forFiles(File files) {
        File directory = new File(files, "diagnostics");
        if (shared == null || !shared.directory.equals(directory)) shared = new DiagnosticJobSummary(directory);
        return shared;
    }

    /** Call only after the corresponding job mutation has committed successfully. */
    synchronized void observe(String id, long createdAt, long now, long monotonicMs, String state, String stage,
                              int completedStages, int restoredStages, double durationSeconds, String quality) throws IOException {
        load();
        String reference = reference(id);
        if (reference == null) return;
        Job job = find(reference);
        boolean changed = false;
        if (job == null) {
            if (jobs.size() == MAX_JOBS) jobs.remove(0);
            job = new Job(reference, Math.max(0, createdAt)); jobs.add(job); changed = true;
        }
        if (Double.isFinite(durationSeconds) && durationSeconds > 0 && durationSeconds <= 14400) job.durationMs = Math.round(durationSeconds * 1000);
        if ("precision".equals(quality)) job.quality = 1; else if ("balanced".equals(quality)) job.quality = 2;
        int nextState = index(STATES, state), nextStage = index(STAGES, stage);
        if (stage == null || stage.isEmpty()) nextStage = 0;
        boolean previouslyActive = active(job.state);
        // Terminal lifecycle time is immutable; merely reopening a completed project is not work.
        if (!previouslyActive) return;
        if (job.hasMonotonic && previouslyActive) {
            long delta = Math.max(0, monotonicMs - job.lastMonotonic);
            job.stageMs[job.stage] = add(job.stageMs[job.stage], delta);
        } else if (job.lastAt > 0 && previouslyActive) {
            // A fresh process cannot know when its predecessor stopped. The gap is neither
            // inference nor a fabricated stage measurement; lifecycle wall time still includes it.
            job.recoveryGaps++; changed = true;
        }
        changed |= job.state != nextState || job.stage != nextStage;
        job.state = nextState; job.stage = nextStage;
        job.lastMonotonic = job.hasMonotonic ? Math.max(job.lastMonotonic, monotonicMs) : monotonicMs;
        job.hasMonotonic = true;
        job.lastAt = Math.max(job.lastAt, Math.max(0, now));
        job.elapsedMs = Math.max(job.elapsedMs, Math.max(0, now - job.createdAt));
        job.completedStages = Math.max(0, Math.min(1000000, completedStages));
        job.restoredStages = Math.max(0, Math.min(1000000, restoredStages));
        if (changed || !active(nextState) || monotonicMs - job.savedMonotonic >= 30000) {
            save(); job.savedMonotonic = monotonicMs;
        }
    }

    /** One finalized native receipt per passage; unknown routes, jobs and fields are discarded. */
    synchronized void profile(String id, String route, String record) throws IOException {
        load(); int routeIndex = exactIndex(ROUTES, route);
        String reference = reference(id);
        Job job = reference == null ? null : find(reference);
        if (job == null || routeIndex < 0 || record == null || record.length() > 8192) return;
        NativeTotals totals = job.routes[routeIndex]; totals.passages = add(totals.passages, 1);
        String outcome = field(record, "outcome");
        if ("completed".equals(outcome)) totals.completed = add(totals.completed, 1);
        else if ("cancelled".equals(outcome)) totals.cancelled = add(totals.cancelled, 1);
        else totals.other = add(totals.other, 1);
        String temporal = field(record, "temporalConfig"), frequency = field(record, "frequencyConfig");
        if (configuration(temporal, true)) totals.temporalConfig = temporal;
        if (configuration(frequency, false)) totals.frequencyConfig = frequency;
        for (int i = 0; i < METRICS.length; i++) {
            String value = field(record, METRICS[i]);
            // v2 Deux used CpuMs for the calling thread, never the whole process.
            if (i == 5 && value == null) value = field(record, "inferenceCpuMs");
            if (value != null && value.matches("[0-9]{1,18}")) {
                try { totals.values[i] = add(totals.values[i], Long.parseLong(value)); totals.samples[i] = add(totals.samples[i], 1); }
                catch (NumberFormatException ignored) {}
            }
        }
        save();
    }

    synchronized String snapshot() throws IOException {
        load();
        StringBuilder out = new StringBuilder("schema=diagnostic-job-summary-v1 retentionJobs=" + MAX_JOBS + " storageBoundBytes=" + MAX_BYTES +
            " recovery=" + (corruptRecovery ? "invalid-prior-summary-discarded" : "normal") + "\n");
        out.append("Stage durations use observed monotonic intervals; restart gaps are excluded. Lifecycle elapsed uses the job wall clock, includes save and can include interruptions.\n");
        out.append("Native receipts count attempted passages, including retries/failures. Thread CPU is the calling thread; process CPU includes all app threads. Missing metrics remain unavailable.\n");
        if (jobs.isEmpty()) out.append("No job summaries have been recorded by this app version.\n");
        for (Job job : jobs) {
            out.append("jobRef=").append(job.reference).append(" state=").append(STATES[job.state])
                .append(" stage=").append(STAGES[job.stage]).append(" createdAt=").append(job.createdAt)
                .append(" observedAt=").append(job.lastAt).append(" lifecycleElapsedMs=").append(job.elapsedMs)
                .append(" durationMs=").append(job.durationMs < 0 ? "unavailable" : Long.toString(job.durationMs))
                .append(" analysisQuality=").append(job.quality == 1 ? "precision" : job.quality == 2 ? "balanced" : "unavailable")
                .append(" recoveryGaps=").append(job.recoveryGaps).append(" completedStages=").append(job.completedStages)
                .append(" restoredStages=").append(job.restoredStages).append('\n');
            for (int i = 0; i < STAGES.length; i++) if (job.stageMs[i] != 0 || i == job.stage)
                out.append(" stage=").append(STAGES[i]).append(" observedWallMs=").append(job.stageMs[i]).append('\n');
            for (int r = 0; r < ROUTES.length; r++) {
                NativeTotals totals = job.routes[r]; if (totals.passages == 0) continue;
                out.append(" route=").append(ROUTES[r]).append(" passages=").append(totals.passages)
                    .append(" completed=").append(totals.completed).append(" cancelled=").append(totals.cancelled).append(" otherOutcomes=").append(totals.other);
                out.append(" lastTemporalConfig=").append(totals.temporalConfig).append(" lastFrequencyConfig=").append(totals.frequencyConfig);
                for (int i = 0; i < METRICS.length; i++) {
                    out.append(' ').append(METRICS[i]).append('=');
                    if (totals.samples[i] == 0) out.append("unavailable"); else out.append(totals.values[i]);
                    out.append(' ').append(METRICS[i]).append("MeasuredPassages=").append(totals.samples[i]);
                }
                out.append('\n');
            }
        }
        return out.toString();
    }

    private Job find(String reference) { for (Job job : jobs) if (reference.equals(job.reference)) return job; return null; }
    private static boolean active(int state) { return state <= 3; }
    private static int index(String[] values, String value) { int index = exactIndex(values, value); return index < 0 ? values.length - 1 : index; }
    private static int exactIndex(String[] values, String value) { for (int i = 0; i < values.length; i++) if (values[i].equals(value)) return i; return -1; }
    private static long add(long left, long right) { return right > Long.MAX_VALUE - left ? Long.MAX_VALUE : left + right; }
    static String reference(String id) {
        if (id == null || !id.matches("[a-fA-F0-9-]{36}")) return null;
        try {
            byte[] hash = MessageDigest.getInstance("SHA-256").digest(id.getBytes(StandardCharsets.UTF_8));
            StringBuilder value = new StringBuilder();
            for (int i = 0; i < 8; i++) value.append(String.format(Locale.ROOT, "%02x", hash[i] & 255));
            return value.toString();
        } catch (java.security.NoSuchAlgorithmException unavailable) { throw new AssertionError(unavailable); }
    }
    private static String field(String record, String key) {
        for (String token : record.split(" ")) if (token.startsWith(key + "=")) return token.substring(key.length() + 1);
        return null;
    }
    private static boolean configuration(String value, boolean temporal) {
        return value != null && (value.matches("cpu-i[1-6]-j1-d(?:0|4)-sequential") ||
            (temporal && value.matches("cpu-i1-j1-d0-sequential-w(?:4|8)-b1")));
    }
    private static String readConfiguration(DataInputStream in, boolean temporal) throws IOException {
        String value = in.readUTF();
        if (!"unavailable".equals(value) && !configuration(value, temporal)) throw new IOException("Invalid scheduling configuration.");
        return value;
    }
    private File file() { return new File(directory, "job-summary.bin"); }
    private void checkPath(File file) throws IOException {
        if (Files.isSymbolicLink(file.toPath()) || (file.exists() && !file.isFile())) throw new IOException("Unexpected diagnostic summary storage entry.");
    }
    private void load() throws IOException {
        if (loaded) return;
        checkPath(file());
        if (!file().exists()) { loaded = true; return; }
        if (file().length() > MAX_BYTES) { corruptRecovery = true; loaded = true; return; }
        try {
            byte[] bytes = Files.readAllBytes(file().toPath());
            if (bytes.length < 12 || bytes.length > MAX_BYTES) throw new IOException("Invalid summary length.");
            DataInputStream in = new DataInputStream(new ByteArrayInputStream(bytes));
            long checksum = in.readLong(); CRC32 crc = new CRC32(); crc.update(bytes, 8, bytes.length - 8);
            if (checksum != crc.getValue() || in.readInt() != MAGIC) throw new IOException("Invalid summary checksum.");
            int count = in.readInt(); if (count < 0 || count > MAX_JOBS) throw new IOException("Invalid summary count.");
            for (int n = 0; n < count; n++) {
                String reference = in.readUTF(); if (!reference.matches("[a-f0-9]{16}") || find(reference) != null) throw new IOException("Invalid summary reference.");
                Job job = new Job(reference, number(in)); job.lastAt = number(in); job.elapsedMs = number(in);
                job.durationMs = in.readLong(); job.quality = in.readInt();
                if (job.durationMs < -1 || job.durationMs > 14400000 || job.quality < 0 || job.quality > 2) throw new IOException("Invalid workload metadata.");
                job.state = in.readInt(); job.stage = in.readInt();
                if (job.state < 0 || job.state >= STATES.length || job.stage < 0 || job.stage >= STAGES.length) throw new IOException("Invalid summary enum.");
                job.recoveryGaps = number(in); job.completedStages = in.readInt(); job.restoredStages = in.readInt();
                if (job.completedStages < 0 || job.completedStages > 1000000 || job.restoredStages < 0 || job.restoredStages > 1000000) throw new IOException("Invalid stage count.");
                for (int i = 0; i < STAGES.length; i++) job.stageMs[i] = number(in);
                for (NativeTotals totals : job.routes) {
                    totals.passages = number(in); totals.completed = number(in); totals.cancelled = number(in); totals.other = number(in);
                    totals.temporalConfig = readConfiguration(in, true); totals.frequencyConfig = readConfiguration(in, false);
                    for (int i = 0; i < METRICS.length; i++) { totals.values[i] = number(in); totals.samples[i] = number(in); if (totals.samples[i] > totals.passages) throw new IOException("Invalid measurement count."); }
                }
                jobs.add(job);
            }
            if (in.read() != -1) throw new IOException("Unexpected summary payload.");
        } catch (IOException damaged) { jobs.clear(); corruptRecovery = true; }
        loaded = true;
    }
    private static long number(DataInputStream in) throws IOException { long value = in.readLong(); if (value < 0) throw new IOException("Invalid summary metric."); return value; }
    private void save() throws IOException {
        if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("Diagnostic summary storage is unavailable.");
        File temporary = new File(directory, ".job-summary.tmp"); checkPath(file()); checkPath(temporary);
        ByteArrayOutputStream bytes = new ByteArrayOutputStream(); DataOutputStream out = new DataOutputStream(bytes);
        out.writeLong(0); out.writeInt(MAGIC); out.writeInt(jobs.size());
        for (Job job : jobs) {
            out.writeUTF(job.reference); out.writeLong(job.createdAt); out.writeLong(job.lastAt); out.writeLong(job.elapsedMs);
            out.writeLong(job.durationMs); out.writeInt(job.quality);
            out.writeInt(job.state); out.writeInt(job.stage); out.writeLong(job.recoveryGaps); out.writeInt(job.completedStages); out.writeInt(job.restoredStages);
            for (long value : job.stageMs) out.writeLong(value);
            for (NativeTotals totals : job.routes) {
                out.writeLong(totals.passages); out.writeLong(totals.completed); out.writeLong(totals.cancelled); out.writeLong(totals.other);
                out.writeUTF(totals.temporalConfig); out.writeUTF(totals.frequencyConfig);
                for (int i = 0; i < METRICS.length; i++) { out.writeLong(totals.values[i]); out.writeLong(totals.samples[i]); }
            }
        }
        out.flush(); byte[] payload = bytes.toByteArray();
        if (payload.length > MAX_BYTES) throw new IOException("Diagnostic summary exceeded its bound.");
        CRC32 crc = new CRC32(); crc.update(payload, 8, payload.length - 8); long checksum = crc.getValue();
        for (int i = 7; i >= 0; i--) { payload[i] = (byte) checksum; checksum >>>= 8; }
        try {
            try (FileOutputStream output = new FileOutputStream(temporary)) { output.write(payload); output.getFD().sync(); }
            Files.move(temporary.toPath(), file().toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } finally { Files.deleteIfExists(temporary.toPath()); }
    }
    private static final class NativeTotals {
        long passages, completed, cancelled, other;
        String temporalConfig = "unavailable", frequencyConfig = "unavailable";
        final long[] values = new long[METRICS.length], samples = new long[METRICS.length];
    }
    private static final class Job {
        final String reference; final long createdAt;
        long lastAt, elapsedMs, recoveryGaps, durationMs = -1, lastMonotonic, savedMonotonic;
        boolean hasMonotonic;
        int state, stage, completedStages, restoredStages, quality;
        final long[] stageMs = new long[STAGES.length];
        final NativeTotals[] routes = {new NativeTotals(), new NativeTotals(), new NativeTotals()};
        Job(String reference, long createdAt) { this.reference = reference; this.createdAt = createdAt; }
    }
}
