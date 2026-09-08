package com.cyberbasslord.lightforge;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.*;
import java.util.concurrent.*;

/** Uses the production journal; no Android mock methods or duplicated logger implementation. */
public final class DiagnosticLogTest {
    private static int checks;
    private static void check(boolean condition, String message) {
        checks++; if (!condition) throw new AssertionError(message);
    }
    private static String snapshot(DiagnosticLog log) throws Exception {
        ByteArrayOutputStream out = new ByteArrayOutputStream(); log.snapshot(out);
        return new String(out.toByteArray(), StandardCharsets.UTF_8);
    }
    private static File directory(File base, String name) throws Exception {
        File result = new File(base, name); if (!result.mkdirs() && !result.isDirectory()) throw new IOException("Cannot create test fixture."); return result;
    }
    public static void main(String[] args) throws Exception {
        File base = args.length == 0 ? Files.createTempDirectory("lightforge-diagnostics-").toFile() : new File(args[0]);
        base.mkdirs();
        File durable = directory(base, "durable");
        DiagnosticLog first = new DiagnosticLog(durable, 4096, 3);
        first.append("INFO", "analysis", "Started operation 17.");
        first.append("ERROR", "native", DiagnosticLog.throwable(new IOException("Native inference failed", new IllegalStateException("Invalid tensor shape"))), true);
        File validLog = new File(durable, "trace-0.log");
        validLog.setLastModified(1600000000000L); long beforeRestart = validLog.lastModified();
        DiagnosticLog restarted = new DiagnosticLog(durable, 4096, 3);
        snapshot(restarted);
        check(validLog.lastModified() == beforeRestart, "Restart does not rewrite already-valid crash history.");
        restarted.append("INFO", "session", "Reopened after failure.");
        String recovered = snapshot(restarted);
        check(recovered.contains("Started operation 17.") && recovered.contains("Reopened after failure."), "Previous session evidence survives a new store instance.");
        check(recovered.contains("IOException") && recovered.contains("Caused by:") && recovered.contains("DiagnosticLogTest.java:"), "Exception class, cause and useful source frames survive.");
        check(recovered.indexOf("Started operation") < recovered.indexOf("Reopened after failure"), "Journal retains chronological ordering.");

        File rotation = directory(base, "rotation"); DiagnosticLog rotating = new DiagnosticLog(rotation, 2048, 3);
        for (int n = 0; n < 200; n++) rotating.append("DEBUG", "progress", "Record " + n + ": " + String.join("", Collections.nCopies(50, "x")));
        String tail = snapshot(rotating); long total = 0; int files = 0;
        for (File file : Objects.requireNonNull(rotation.listFiles())) {
            files++; total += file.length(); check(file.length() <= 2048, "Every rotating file respects its byte cap.");
        }
        check(files <= 3 && total <= 6144, "Journal disk footprint stays bounded.");
        check(tail.contains("Record 199:") && !tail.contains("Record 0:"), "Rotation retains the newest evidence and evicts oldest events.");
        check(tail.indexOf("Record 198:") < tail.indexOf("Record 199:"), "Rotated segments export oldest to newest.");

        File concurrent = directory(base, "concurrent"); DiagnosticLog shared = new DiagnosticLog(concurrent, 256 * 1024, 4);
        ExecutorService pool = Executors.newFixedThreadPool(8); List<Future<?>> tasks = new ArrayList<>();
        for (int worker = 0; worker < 8; worker++) {
            final int id = worker;
            tasks.add(pool.submit(() -> {
                for (int n = 0; n < 100; n++) try { shared.append("INFO", "worker", "thread=" + id + " item=" + n); }
                catch (IOException error) { throw new RuntimeException(error); }
            }));
        }
        for (Future<?> task : tasks) task.get(10, TimeUnit.SECONDS); pool.shutdown();
        String simultaneous = snapshot(shared); String[] lines = simultaneous.trim().split("\n");
        check(lines.length == 800, "Concurrent writers lose or interleave no records.");
        Set<String> seen = new HashSet<>();
        for (String line : lines) {
            check(line.matches("[0-9TZ:.\\-]+ INFO worker thread=[0-7] item=[0-9]{1,2}"), "Concurrent record is complete and parseable.");
            seen.add(line.substring(line.indexOf("thread=")));
        }
        check(seen.size() == 800, "All concurrent sequence identities remain distinct.");

        String unsafe = "Failed content://provider/private/My%20Secret%20Song.wav and https://service.example/x?secret=hunter2\n" +
            "Path /storage/emulated/0/Music/My Private Song.wav email sean@example.com\n" +
            "authorization=Bearer confidential-token\napi_key=sk_do_not_export_this_key\n" +
            "projectName=Very Private Project;\nUser value \"Private Display Name\"\n" +
            "song.mp3 75e4fb58-9975-471e-9b9a-2f4e9bd34da1\n";
        String safe = DiagnosticLog.sanitize(unsafe);
        for (String privateValue : new String[]{"provider", "service.example", "hunter2", "storage/emulated", "Private Song", "sean@example.com", "confidential-token", "sk_do_not", "Very Private Project", "Private Display Name", "song.mp3", "75e4fb58"}) check(!safe.contains(privateValue), "Redacted " + privateValue);
        check(DiagnosticLog.sanitize("Invalid tensor shape; passage=3 elapsedMs=7410").equals("Invalid tensor shape; passage=3 elapsedMs=7410"), "Sanitization retains technical diagnosis.");
        shared.append("ERROR", "privacy", unsafe);
        String saved = snapshot(new DiagnosticLog(concurrent, 256 * 1024, 4));
        check(!saved.contains("confidential-token") && !saved.contains("Private Display Name"), "Only sanitized messages reach persistent storage and export.");
        check(!new String(Files.readAllBytes(new File(concurrent, "trace-0.log").toPath()), StandardCharsets.UTF_8).contains("sk_do_not"), "Credentials are absent from the on-disk journal.");

        File damaged = directory(base, "damaged");
        byte[] bytes = "old-complete\napi_key=must-never-escape\n".getBytes(StandardCharsets.UTF_8);
        try (OutputStream out = new FileOutputStream(new File(damaged, "trace-0.log"))) {
            out.write(bytes); out.write(new byte[]{(byte)0xC3, (byte)0x28, 0, '\n'}); out.write("partial-write-without-newline".getBytes(StandardCharsets.UTF_8));
        }
        DiagnosticLog repaired = new DiagnosticLog(damaged, 2048, 3); repaired.append("INFO", "session", "Recovered journal.");
        String repair = snapshot(repaired);
        check(repair.contains("old-complete") && repair.contains("Recovered journal."), "Complete records survive damaged-file recovery.");
        check(!repair.contains("partial-write") && !repair.contains("must-never-escape"), "Torn record is discarded and preexisting data is sanitized.");
        check(repair.indexOf('\u0000') < 0 && repair.indexOf('\ufffd') < 0, "Invalid UTF-8 and control bytes cannot corrupt the exported text.");

        File failedRepair = directory(base, "failed-repair");
        File original = new File(failedRepair, "trace-0.log");
        byte[] priorEvidence = "complete-prior-crash\nincomplete-tail".getBytes(StandardCharsets.UTF_8);
        Files.write(original.toPath(), priorEvidence);
        File blockedRepair = directory(failedRepair, ".trace-0.repair");
        Files.write(new File(blockedRepair, "blocker").toPath(), new byte[]{1});
        boolean repairFailed = false;
        try { new DiagnosticLog(failedRepair, 2048, 3).append("INFO", "test", "Repair cannot write."); }
        catch (IOException expected) { repairFailed = true; }
        check(repairFailed && Arrays.equals(Files.readAllBytes(original.toPath()), priorEvidence), "A failed repair leaves original crash evidence byte-for-byte intact.");

        File oversized = directory(base, "oversized");
        try (OutputStream out = new FileOutputStream(new File(oversized, "trace-0.log"))) {
            for (int n = 0; n < 4000; n++) out.write(("legacy item " + n + "\n").getBytes(StandardCharsets.UTF_8));
        }
        DiagnosticLog bounded = new DiagnosticLog(oversized, 2048, 3); bounded.append("WARN", "recovery", "Continuing after oversized history.");
        String boundedText = snapshot(bounded);
        check(boundedText.contains("legacy item 3999") && boundedText.contains("Continuing after oversized history."), "Oversized damaged journal retains its latest complete events.");
        check(new File(oversized, "trace-0.log").length() <= 2048, "Damaged journal is repaired to its bound before append.");
        bounded.append("WARN", "unicode", String.join("", Collections.nCopies(10000, "💡")));
        check(snapshot(bounded).contains("[truncated]"), "Oversized multi-byte messages remain bounded and valid UTF-8.");

        File injection = directory(base, "injection"); DiagnosticLog protectedLog = new DiagnosticLog(injection, 2048, 3);
        protectedLog.append("FATAL\nforged", "user supplied secret", "line 1\nforged FATAL line 2");
        String protectedText = snapshot(protectedLog);
        check(protectedText.trim().split("\n").length == 1 && protectedText.contains(" INFO app "), "Untrusted source, level and newlines cannot forge journal records.");
        File blocked = new File(base, "blocked"); Files.write(blocked.toPath(), new byte[]{1});
        boolean failedCleanly = false;
        try { new DiagnosticLog(blocked).append("INFO", "test", "Cannot persist."); } catch (IOException expected) { failedCleanly = true; }
        check(failedCleanly, "Unavailable storage produces a recoverable I/O error.");
        System.out.println("PASS: " + checks + " diagnostic checks: restart durability, cause stacks, bounded rotation, concurrent records, privacy, torn writes, invalid UTF-8, oversized history, Unicode limits and storage failure.");
    }
}
