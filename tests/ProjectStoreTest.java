package com.cyberbasslord.lightforge;

import org.json.JSONObject;
import org.json.JSONArray;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.zip.CRC32;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Host tests use the exact Android project store, converter and PCM importer. */
public final class ProjectStoreTest {
    private static final AudioImporter.Progress PROGRESS = new AudioImporter.Progress() {
        public void update(double value, String message) {}
        public void check() throws IOException {}
    };
    interface Work { void run() throws Exception; }
    static void check(boolean ok, String message) { if (!ok) throw new AssertionError(message); }
    static void reject(Work work, String label) throws Exception {
        try { work.run(); } catch (IOException expected) { return; }
        throw new AssertionError("Accepted invalid operation: " + label);
    }
    static JSONObject read(File file) throws Exception {
        return new JSONObject(new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8));
    }
    static void write(File file, JSONObject object) throws Exception {
        Files.write(file.toPath(), object.toString().getBytes(StandardCharsets.UTF_8));
    }
    static void add(ZipOutputStream out, String name, byte[] data) throws Exception {
        ZipEntry e = new ZipEntry(name); CRC32 crc = new CRC32(); crc.update(data);
        e.setMethod(ZipEntry.STORED); e.setSize(data.length); e.setCompressedSize(data.length); e.setCrc(crc.getValue());
        out.putNextEntry(e); out.write(data); out.closeEntry();
    }
    static File archive(File where, File audio, JSONObject state, boolean includeState) throws Exception {
        try (ZipOutputStream zip = new ZipOutputStream(new FileOutputStream(where))) {
            add(zip, "LightShow/lightshow.wav", Files.readAllBytes(audio.toPath()));
            if (includeState) add(zip, "Review/LightForge_Project.json", state.toString().getBytes(StandardCharsets.UTF_8));
            add(zip, "LightShow/lightshow.fseq", "never trust stored sequence".getBytes(StandardCharsets.UTF_8));
            add(zip, "../../outside.txt", "must never be extracted".getBytes(StandardCharsets.UTF_8));
        }
        return where;
    }
    static int directories(File root) { File[] f = root.listFiles(); return f == null ? 0 : f.length; }
    static AudioImporter.Progress cancelledAfter(final int allowed) {
        return new AudioImporter.Progress() { int calls; public void update(double x, String m) {} public void check() throws IOException { if (++calls > allowed) throw new IOException("Cancelled."); } };
    }
    public static void main(String[] args) throws Exception {
        File base = new File(args[0]); base.mkdirs(); File root = new File(base, "projects"); root.mkdirs();
        File original = new File(root, "original"); original.mkdirs();
        float[] samples = new float[88200 * 2];
        for (int i = 0; i < samples.length / 2; i++) { samples[2*i] = (float)(.4*Math.sin(2*Math.PI*220*i/44100)); samples[2*i+1] = (float)(.2*Math.sin(2*Math.PI*330*i/44100)); }
        double duration;
        try (WavConverter c = new WavConverter(new File(original, "audio.wav"), new File(original, "analysis.wav"), 44100)) { c.accept(samples, samples.length/2); duration = c.finish(); }
        JSONObject music = new JSONObject().put("duration", duration).put("bpm", 120)
                .put("beats", new JSONArray().put(.2).put(.7).put(1.2).put(1.7))
                .put("sections", new JSONArray().put(new JSONObject().put("start", 0).put("end", duration).put("label", "Peak").put("energy", .9)));
        JSONObject settings = new JSONObject().put("style", "festival").put("sensitivity", .91).put("stepMs", 10).put("custom", new JSONObject().put("enabled", true));
        JSONObject state = new JSONObject().put("version", 1).put("projectId", "original").put("name", "Original")
                .put("settings", settings).put("music", music).put("needAnalysis", false);
        JSONObject meta = new JSONObject().put("id", "original").put("name", "Original").put("duration", duration).put("createdAt", 1).put("style", "festival");
        write(new File(original, "project.json"), state); write(new File(original, "meta.json"), meta);
        JSONObject copy = ProjectStore.duplicate(root, "original", "  Bigger finale  ", PROGRESS);
        File copied = new File(root, copy.getString("id")); JSONObject copiedState = read(new File(copied, "project.json"));
        check(!copy.getString("id").equals("original"), "duplicate UUID");
        check(copy.getString("name").equals("Bigger finale"), "trimmed name");
        check(copy.getString("audioUrl").endsWith(copy.getString("id") + "/audio.wav"), "new local URL");
        check(copiedState.getString("projectId").equals(copy.getString("id")), "new project identity");
        check(copiedState.getJSONObject("settings").toString().equals(settings.toString()), "duplicate settings preserved");
        check(copiedState.getJSONObject("music").toString().equals(music.toString()), "duplicate neural analysis preserved");
        for (String name : new String[]{"audio.wav", "analysis.wav"}) check(Arrays.equals(Files.readAllBytes(new File(original,name).toPath()),Files.readAllBytes(new File(copied,name).toPath())), "byte exact copy " + name);
        ProjectStore.rename(root, copy.getString("id"), "Night Drive • 2");
        check(read(new File(copied,"meta.json")).getString("name").equals("Night Drive • 2"), "metadata renamed");
        check(read(new File(copied,"project.json")).getString("name").equals("Night Drive • 2"), "editable project renamed");
        check(read(new File(original,"project.json")).getString("name").equals("Original"), "original unchanged");
        reject(() -> ProjectStore.rename(root,"original","  "), "empty name");
        char[] longName = new char[101]; Arrays.fill(longName,'a');
        reject(() -> ProjectStore.rename(root,"original",new String(longName)), "long name");
        reject(() -> ProjectStore.rename(root,"../escape","oops"), "path traversal");
        int before = directories(root);
        reject(() -> ProjectStore.duplicate(root,"original","Cancelled",cancelledAfter(2)), "copy cancellation");
        check(directories(root)==before, "cancelled duplicate cleaned staging");
        JSONObject saved = new JSONObject(state.toString()); saved.getJSONObject("music").put("duration", duration+.01);
        saved.getJSONObject("music").getJSONArray("sections").getJSONObject(0).put("end", duration+.01);
        File backup = archive(new File(base,"backup.zip"),new File(original,"audio.wav"),saved,true);
        JSONObject restored = ProjectStore.restore(root,backup,PROGRESS);
        File restoredDir = new File(root,restored.getString("id")); JSONObject restoredState = read(new File(restoredDir,"project.json"));
        check(restoredState.getJSONObject("settings").toString().equals(settings.toString()), "restored editable settings");
        check(restoredState.getJSONObject("music").getDouble("duration")==duration, "audio duration authoritative");
        check(restoredState.getJSONObject("music").getJSONArray("sections").getJSONObject(0).getDouble("end")==duration, "last section duration corrected");
        check(!restoredState.getBoolean("needAnalysis"), "rounding difference retains valid neural analysis");
        check(new File(restoredDir,"analysis.wav").isFile(), "restored native analysis WAV");
        check(!new File(restoredDir,"lightshow.fseq").exists(), "stored FSEQ ignored");
        check(!new File(base,"outside.txt").exists(), "ZIP paths never used for extraction");
        check(Arrays.equals(Files.readAllBytes(new File(original,"audio.wav").toPath()), Files.readAllBytes(new File(restoredDir,"audio.wav").toPath())), "restored audio bytes preserved");
        before = directories(root);
        File missing = archive(new File(base,"missing.zip"),new File(original,"audio.wav"),state,false);
        reject(() -> ProjectStore.restore(root,missing,PROGRESS), "missing editable project");
        byte[] bytes = Files.readAllBytes(backup.toPath());
        int nameBytes = (bytes[26]&255)|((bytes[27]&255)<<8), extraBytes = (bytes[28]&255)|((bytes[29]&255)<<8);
        bytes[30+nameBytes+extraBytes+100] ^= 1;
        File badCrc = new File(base,"bad-crc.zip"); Files.write(badCrc.toPath(),bytes);
        reject(() -> ProjectStore.restore(root,badCrc,PROGRESS), "actual CRC corruption");
        File truncated = new File(base,"truncated.zip"); Files.write(truncated.toPath(),Arrays.copyOf(bytes,bytes.length-22));
        reject(() -> ProjectStore.restore(root,truncated,PROGRESS), "truncated central directory");
        reject(() -> ProjectStore.restore(root,backup,cancelledAfter(12)), "restore cancellation");
        check(directories(root)==before, "failed restores cleaned staging");
        JSONObject renameMeta = read(new File(copied,"meta.json")).put("name","Recovered rename");
        JSONObject renameState = read(new File(copied,"project.json")).put("name","Recovered rename");
        write(new File(copied,".rename-meta.json"),renameMeta);write(new File(copied,".rename-project.json"),renameState);
        write(new File(copied,".rename-journal.json"),new JSONObject().put("version",1));
        write(new File(copied,"project.json"),renameState); // Simulated crash after only one file committed.
        ProjectStore.recover(root);
        check(read(new File(copied,"meta.json")).getString("name").equals("Recovered rename"), "journal recovers matching metadata");
        check(!new File(copied,".rename-journal.json").exists(), "completed journal removed");
        File orphan = new File(root,".pending-"+java.util.UUID.randomUUID()); orphan.mkdir();
        File victim = new File(base,"keep.txt"); Files.write(victim.toPath(),new byte[]{1,2,3});
        Files.createSymbolicLink(new File(orphan,"link").toPath(),victim.getCanonicalFile().toPath());
        Files.write(new File(orphan,"partial.wav").toPath(),new byte[]{0,0});
        ProjectStore.recover(root);
        check(!orphan.exists() && victim.isFile(), "orphan staging cleanup never follows symbolic links");
        new File(copied,"analysis.wav").delete();
        JSONObject regenerated = ProjectStore.duplicate(root,copy.getString("id"),"Analysis repaired",PROGRESS);
        check(new File(new File(root,regenerated.getString("id")),"analysis.wav").length()>44, "missing analysis audio regenerated");
        System.out.println("PASS: real duplicate, Unicode rename, exact audio copies, editable backup restoration, authoritative duration, regenerated analysis, CRC corruption, truncated ZIP, missing data, cancellation cleanup, traversal rejection and interrupted rename recovery.");
    }
}
