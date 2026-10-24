package com.cyberbasslord.lightforge;

import org.json.JSONObject;
import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Small, ordinary validation fixtures only; no stress or crash-reproduction inputs. */
public final class ProjectJsonValidationTest {
    interface Work { void run() throws Exception; }
    static void check(boolean ok, String label) { if (!ok) throw new AssertionError(label); }
    static void reject(Work work, String label) throws Exception {
        try { work.run(); } catch (IOException expected) { return; }
        throw new AssertionError("Accepted invalid JSON: " + label);
    }
    static void write(File file, JSONObject value) throws Exception {
        Files.write(file.toPath(), value.toString().getBytes(StandardCharsets.UTF_8));
    }
    static JSONObject read(File file) throws Exception {
        return new JSONObject(new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8));
    }
    static void readBounded(File file, int bytes) throws Exception {
        Method read = ProjectStore.class.getDeclaredMethod("readObject", File.class, int.class);
        read.setAccessible(true);
        try { read.invoke(null, file, bytes); }
        catch (InvocationTargetException failure) { throw (Exception) failure.getCause(); }
    }
    public static void main(String[] args) throws Exception {
        for (String valid : new String[]{"{}", "{\"a\":[{\"b\":null}],\"number\":-1.2e+3,\"flag\":true}",
                "{\"text\":\"braces {} [], quote \\\" and slash \\\\, Unicode \\u263a\"}"})
            ProjectStore.validateJson(valid, 3);
        ProjectStore.validateJson("{\"a\":[{}]}", 3);
        reject(() -> ProjectStore.validateJson("{\"a\":[{}]}", 2), "small configured depth boundary");
        for (String invalid : new String[]{"", "[]", "null", "{", "{} {}", "{} trailing", "{'a':1}",
                "{a:1}", "{\"a\":1,}", "{\"a\":[1,]}", "{/* comment */\"a\":1}",
                "{\"a\":01}", "{\"a\":NaN}", "{\"a\":\"\\uZZZZ\"}"})
            reject(() -> ProjectStore.validateJson(invalid, 4), invalid);

        File base = new File(args[0]); check(base.mkdirs(), "fresh fixture directory");
        File tiny = new File(base, "tiny.json");
        Files.write(tiny.toPath(), "{}".getBytes(StandardCharsets.UTF_8));
        readBounded(tiny, 2);
        reject(() -> readBounded(tiny, 1), "small byte bound");
        Files.write(tiny.toPath(), new byte[]{'{', '"', 'a', '"', ':', '"', (byte)0xc3, '"', '}'});
        reject(() -> readBounded(tiny, 32), "invalid UTF-8");

        File root = new File(base, "projects"), project = new File(root, "ordinary");
        check(project.mkdirs(), "project directory");
        JSONObject state = new JSONObject("{\"version\":1,\"projectId\":\"ordinary\",\"name\":\"Before\","
                + "\"settings\":{\"custom\":{\"values\":[1,2]}},\"music\":null}");
        write(new File(project, "project.json"), state);
        write(new File(project, "meta.json"), new JSONObject().put("id", "ordinary").put("name", "Before"));
        ProjectStore.save(root, "ordinary", new JSONObject(state.toString()).put("name", "After"));
        JSONObject revision = read(new File(project, ".previous-revision.json"));
        check(revision.getJSONObject("project").getString("name").equals("Before"), "retained previous state");
        ProjectStore.validateJson(revision.toString(), 5);
        reject(() -> ProjectStore.validateJson(revision.toString(), 4), "revision adds one level");
        ProjectStore.restorePrevious(root, "ordinary");
        check(read(new File(project, "project.json")).getString("name").equals("Before"), "undo boundary state");
        Files.write(new File(project, "project.json").toPath(), "{}".getBytes(StandardCharsets.UTF_8));
        ProjectStore.recover(root);
        check(read(new File(project, "project.json")).getString("name").equals("After"), "recover enveloped revision");
        if (ProjectStore.MAX_JSON_DEPTH == 4) {
            File current = new File(project, "project.json"), meta = new File(project, "meta.json"), prior = new File(project, ".previous-revision.json");
            byte[] currentBytes = Files.readAllBytes(current.toPath()), metaBytes = Files.readAllBytes(meta.toPath()), priorBytes = Files.readAllBytes(prior.toPath());
            JSONObject over = read(current);
            over.getJSONObject("settings").getJSONObject("custom").put("values", new org.json.JSONArray().put(new JSONObject().put("value", 1)));
            reject(() -> ProjectStore.save(root, "ordinary", over), "five levels with configured limit four");
            check(Arrays.equals(currentBytes, Files.readAllBytes(current.toPath())), "rejected save preserves project");
            check(Arrays.equals(metaBytes, Files.readAllBytes(meta.toPath())), "rejected save preserves metadata");
            check(Arrays.equals(priorBytes, Files.readAllBytes(prior.toPath())), "rejected save preserves undo");
        }
        File backup = new File(base, "ordinary-invalid.zip");
        try (ZipOutputStream out = new ZipOutputStream(new FileOutputStream(backup))) {
            out.putNextEntry(new ZipEntry("Review/LightForge_Project.json"));
            out.write("{\"version\":1,}".getBytes(StandardCharsets.UTF_8)); out.closeEntry();
            out.putNextEntry(new ZipEntry("LightShow/lightshow.wav")); out.write(new byte[44]); out.closeEntry();
        }
        reject(() -> ProjectStore.restore(root, backup, new AudioImporter.Progress() {
            public void update(double value, String message) {}
            public void check() throws IOException {}
        }), "ordinary malformed backup JSON");
        check(root.list().length == 1, "rejected restore leaves no published or staging project");
        check(read(new File(project, "project.json")).getString("name").equals("After"), "rejected restore preserves existing data");
        System.out.println("PASS: strict ordinary JSON, small byte/depth bounds, UTF-8, save/undo/recovery, and failed restore cleanup; configured depth=" + ProjectStore.MAX_JSON_DEPTH);
    }
}
