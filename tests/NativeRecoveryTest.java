package com.cyberbasslord.lightforge;

import org.json.JSONObject;
import org.json.JSONArray;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.UUID;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Executes the production storage classes on a host JVM; no simulated Android claims. */
public final class NativeRecoveryTest {
    private static final JSONArray CHECKS = new JSONArray();
    private static final AudioImporter.Progress PROGRESS = new AudioImporter.Progress() {
        public void update(double value, String message) {}
        public void check() throws IOException {}
    };
    interface Operation { void run() throws Exception; }
    static void check(boolean ok, String message) { if (!ok) throw new AssertionError(message); }
    static void pass(String message) { CHECKS.put(message); }
    static void reject(Operation operation, String label) throws Exception {
        try { operation.run(); } catch (Exception expected) { return; }
        throw new AssertionError("Accepted invalid operation: " + label);
    }
    static JSONObject read(File file) throws Exception {
        return new JSONObject(new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8));
    }
    static void write(File file, JSONObject value) throws Exception {
        Files.write(file.toPath(), value.toString().getBytes(StandardCharsets.UTF_8));
    }
    static int projects(File root) {
        File[] files = root.listFiles(); int count = 0;
        if (files != null) for (File file : files) if (!file.getName().startsWith(".")) count++;
        return count;
    }
    static JSONObject state(File directory) throws Exception { return read(new File(directory, "project.json")); }
    static JSONObject changed(File directory, String name, int seed) throws Exception {
        JSONObject state = state(directory).put("name", name);
        state.getJSONObject("settings").put("seed", seed);
        return state;
    }
    static File zip(File root) throws Exception {
        root.mkdirs(); File file = new File(root, UUID.randomUUID() + ".zip");
        try (ZipOutputStream output = new ZipOutputStream(new FileOutputStream(file))) {
            output.putNextEntry(new ZipEntry("START_HERE.txt")); output.write("Verified export fixture".getBytes(StandardCharsets.UTF_8)); output.closeEntry();
        }
        return file;
    }
    public static void main(String[] args) throws Exception {
        File base = new File(args[0]); base.mkdirs();
        if (args.length > 1 && "export-crash".equals(args[1])) {
            File file = zip(base);
            PendingExportStore.prepare(base, file, "Recovered_LightShow.zip");
            PendingExportStore.destination(base, "content://documents/created-for-this-export");
            Runtime.getRuntime().halt(0); // bypass finally/shutdown hooks, as with process death
        }
        File root = new File(base, "projects"); root.mkdirs();
        File audio = new File(base, "source.wav"), mono = new File(base, "source-analysis.wav");
        float[] samples = new float[44100 * 2 * 2];
        for (int i = 0; i < samples.length; i++) samples[i] = (float)(.3 * Math.sin(2 * Math.PI * 220 * (i / 2) / 44100));
        try (WavConverter converter = new WavConverter(audio, mono, 44100)) { converter.accept(samples, samples.length / 2); converter.finish(); }
        final boolean[] hidden = {false};
        JSONObject metadata;
        try (InputStream input = new FileInputStream(audio)) {
            metadata = ProjectStore.importAudio(root, input, "Native test", new AudioImporter.Progress() {
                public void update(double fraction, String message) {}
                public void check() {
                    if (projects(root) == 0) {
                        File[] files = root.listFiles(); if (files != null) for (File file : files) if (file.getName().startsWith(".pending-")) hidden[0] = true;
                    }
                }
            });
        }
        String id = metadata.getString("id"); File directory = new File(root, id);
        check(hidden[0] && projects(root) == 1, "new import must stay hidden until published");
        check(new File(directory, "analysis.wav").isFile() && !new File(directory, "input.media").exists(), "import complete");
        check(state(directory).optInt("version") == 1 && state(directory).getBoolean("needAnalysis"), "fresh import has editable recoverable state");
        pass("Normal PCM import stays staged until audio, analysis and both JSON files are complete.");
        InputStream interrupted = new InputStream() { int count; public int read() throws IOException { if (++count > 4096) throw new IOException("Simulated interrupted provider"); return 0; } };
        reject(() -> ProjectStore.importAudio(root, interrupted, "Broken", PROGRESS), "interrupted source");
        check(root.listFiles().length == 1, "failed import leaves no staged or visible project");
        try (InputStream input = new FileInputStream(audio)) {
            reject(() -> ProjectStore.importAudio(root, input, "Cancelled", new AudioImporter.Progress() {
                public void update(double f, String m) {} public void check() throws IOException { throw new IOException("Cancelled"); }
            }), "cancelled import");
        }
        check(root.listFiles().length == 1, "cancelled import cleaned");
        pass("Interrupted document-provider reads and explicit import cancellation clean all staging.");

        JSONObject first = changed(directory, "First", 1).put("provenance", new JSONObject().put("planner", "1.4.0")).put("compiledSnapshot", new JSONObject().put("seed", 1));
        ProjectStore.save(root, id, first);
        ProjectStore.save(root, id, changed(directory, "Second", 2));
        check(read(new File(directory, "meta.json")).getString("name").equals("Second"), "listing updated with state");
        check(read(new File(directory, ".previous-revision.json")).getJSONObject("project").getString("name").equals("First"), "one prior revision");
        check(state(directory).getJSONObject("provenance").getString("planner").equals("1.4.0"), "extra metadata preserved");
        check(state(directory).getJSONObject("compiledSnapshot").getInt("seed") == 1, "snapshot metadata preserved");
        pass("Autosave commits matching state/metadata, preserves extensible version-1 provenance and retains one prior revision.");

        ProjectStore.restorePrevious(root, id);
        check(state(directory).getString("name").equals("First"), "revision undo");
        ProjectStore.restorePrevious(root, id);
        check(state(directory).getString("name").equals("Second"), "revision redo");
        pass("Restoring the previous saved revision swaps both files and can itself be undone.");

        Files.write(new File(directory, "project.json").toPath(), "{truncated".getBytes(StandardCharsets.UTF_8));
        ProjectStore.recover(root);
        check(state(directory).getString("name").equals("First"), "corrupt state restored from last good");
        check(read(new File(directory, "meta.json")).optLong("recoveredAt") > 0, "recovery surfaced");
        new File(directory, "project.json").delete();
        ProjectStore.recover(root);
        check(state(directory).getString("name").equals("First"), "missing state recovered");
        pass("Corrupted and missing current project files recover the matching last-good revision and record recovery time.");

        JSONObject beforeMeta = read(new File(directory, "meta.json"));
        JSONObject afterMeta = new JSONObject(beforeMeta.toString()).put("name", "After crash");
        JSONObject afterState = changed(directory, "After crash", 8);
        for (int boundary = 0; boundary < 3; boundary++) {
            write(new File(directory, ".rename-meta.json"), afterMeta);
            write(new File(directory, ".rename-project.json"), afterState);
            write(new File(directory, ".rename-journal.json"), new JSONObject().put("version", 2));
            if (boundary >= 1) write(new File(directory, "project.json"), afterState);
            if (boundary >= 2) write(new File(directory, "meta.json"), afterMeta);
            ProjectStore.recover(root);
            check(state(directory).getString("name").equals("After crash") && read(new File(directory, "meta.json")).getString("name").equals("After crash"), "journal boundary " + boundary);
            check(!new File(directory, ".rename-journal.json").exists(), "committed marker removed");
        }
        pass("Durable journal rolls forward at marker-only, state-replaced and both-replaced interruption boundaries.");

        write(new File(directory, ".rename-meta.json"), new JSONObject(afterMeta.toString()).put("name", "Uncommitted"));
        write(new File(directory, ".rename-project.json"), changed(directory, "Uncommitted", 9));
        Files.write(new File(directory, "project.json.writing").toPath(), new byte[]{1});
        ProjectStore.recover(root);
        check(state(directory).getString("name").equals("After crash"), "staged files alone are not committed");
        check(!new File(directory, ".rename-project.json").exists() && !new File(directory, "project.json.writing").exists(), "abandoned writes cleaned");
        pass("Uncommitted stages and legacy temporary writes are cleaned without replacing the approved state.");

        File blocker = new File(directory, ".rename-project.json"); blocker.mkdir();
        Files.write(new File(blocker, "blocker").toPath(), new byte[]{0});
        reject(() -> ProjectStore.save(root, id, changed(directory, "Failed write", 10)), "filesystem replacement failure");
        check(state(directory).getString("name").equals("After crash") && !new File(directory, ".rename-journal.json").exists(), "failed stage leaves original intact");
        new File(blocker, "blocker").delete(); blocker.delete(); ProjectStore.recover(root);
        pass("An actual filesystem failure replacing a staged file leaves current state and metadata unchanged.");

        File orphan = new File(root, ".pending-" + UUID.randomUUID()); orphan.mkdir();
        File victim = new File(base, "keep.txt"); Files.write(victim.toPath(), new byte[]{1});
        Files.createSymbolicLink(new File(orphan, "linked").toPath(), victim.toPath());
        File legacy = new File(root, "legacy-incomplete"); legacy.mkdir(); Files.write(new File(legacy, "input.media").toPath(), new byte[]{0});
        ProjectStore.recover(root);
        check(!orphan.exists() && !legacy.exists() && victim.isFile(), "abandoned cleanup constrained");
        pass("Startup removes abandoned new and pre-1.4 imports without following symbolic links.");

        File exports = new File(base, "exports"); exports.mkdirs();
        Process child = new ProcessBuilder(new File(System.getProperty("java.home"), "bin/java").getPath(), "-cp", System.getProperty("java.class.path"), NativeRecoveryTest.class.getName(), exports.getPath(), "export-crash").inheritIO().start();
        check(child.waitFor() == 0, "crash fixture subprocess");
        JSONObject prepared = PendingExportStore.recover(exports);
        check(prepared.getString("name").equals("Recovered_LightShow.zip"), "prepared export identity survives process death");
        check(prepared.getString("destinationUri").startsWith("content://"), "partial destination survives process death");
        check(PendingExportStore.file(exports, prepared).length() == prepared.getLong("bytes"), "prepared file survives");
        pass("A separate JVM halts without cleanup; the next process recovers exact prepared ZIP, filename and partial destination.");
        File unfinished = new File(exports, UUID.randomUUID() + ".fseq"); Files.write(unfinished.toPath(), new byte[]{1});
        File unfinishedZip = zip(exports); File unrelated = new File(exports, "keep.txt"); Files.write(unrelated.toPath(), new byte[]{2});
        PendingExportStore.recover(exports);
        check(!unfinished.exists() && !unfinishedZip.exists() && unrelated.isFile(), "only abandoned export files cleaned");
        reject(() -> PendingExportStore.prepare(exports, zip(exports), "Second.zip"), "multiple prepared exports");
        reject(() -> PendingExportStore.destination(exports, "file:///outside"), "non-document destination");
        PendingExportStore.clearDestination(exports);
        check(!PendingExportStore.read(exports).has("destinationUri"), "partial destination clears");
        pass("Prepared export recovery retains only one ZIP, cleans interrupted work, rejects non-document destinations and clears retry state.");
        PendingExportStore.discard(exports);
        check(PendingExportStore.read(exports) == null && unrelated.isFile(), "explicit discard clears prepared data only");
        File damaged = zip(exports); PendingExportStore.prepare(exports, damaged, "Bad.zip");
        try (RandomAccessFile file = new RandomAccessFile(damaged, "rw")) { file.setLength(10); }
        reject(() -> PendingExportStore.recover(exports), "truncated prepared ZIP");
        check(PendingExportStore.read(exports) == null && !damaged.exists(), "bad export recovery does not lock future export");
        File corrupt = zip(exports); PendingExportStore.prepare(exports, corrupt, "Corrupt marker.zip");
        Files.write(new File(exports, "pending-export.json").toPath(), "{broken".getBytes(StandardCharsets.UTF_8));
        PendingExportStore.discard(exports);
        check(PendingExportStore.read(exports) == null && !corrupt.exists() && unrelated.isFile(), "explicit discard releases damaged marker without trusting it");
        pass("Explicit discard and truncated-export recovery release the prepared slot without touching unrelated files.");

        System.out.println(new JSONObject().put("passed", true).put("checks", CHECKS).put("scope", "Host JVM executing production Java storage classes; Android document provider, Activity callbacks, device lifecycle and vehicle playback require physical-device verification.").toString(2));
    }
}
