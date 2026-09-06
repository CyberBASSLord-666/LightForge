package com.cyberbasslord.lightforge;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.Enumeration;
import java.util.UUID;
import java.util.zip.CRC32;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/** Private editable projects; publishes new projects only after durable, checked writes. */
final class ProjectStore {
    static final long MAX_AUDIO_BYTES = 44L + 14400L * 44100 * 4;
    static final int MAX_PROJECT_BYTES = 64 * 1024 * 1024;
    private static final int MAX_META_BYTES = 65536;
    private static final String ORIGIN = "https://appassets.androidplatform.net/project/";
    private static final String JOURNAL = ".rename-journal.json";
    private static final String PREVIOUS = ".previous-revision.json";
    private static final int MAX_REVISION_BYTES = MAX_PROJECT_BYTES + MAX_META_BYTES + 1024;

    private ProjectStore() {}

    /** A normal import follows the same publish-after-completion path as restore. */
    static synchronized JSONObject importAudio(File projectsRoot, InputStream input, String displayName,
                                                AudioImporter.Progress progress) throws Exception {
        File root = root(projectsRoot);
        String id = UUID.randomUUID().toString();
        File staging = makeStaging(root, id), destination = new File(root, id);
        boolean published = false;
        try {
            if (input == null) throw new IOException("The selected file could not be opened.");
            File source = new File(staging, "input.media");
            try (FileOutputStream output = new FileOutputStream(source)) {
                byte[] buffer = new byte[131072]; int size; long count = 0;
                while ((size = input.read(buffer)) != -1) {
                    progress.check(); count += size;
                    if (count > 4_000_000_000L) throw new IOException("The selected file is too large.");
                    if (staging.getUsableSpace() < 128L * 1024 * 1024)
                        throw new IOException("Free some device storage before importing this track.");
                    output.write(buffer, 0, size);
                }
                output.getFD().sync();
            }
            progress.check();
            File audio = new File(staging, "audio.wav"), analysis = new File(staging, "analysis.wav");
            AudioImporter.convert(source, audio, analysis, mappedProgress(progress, .08, .88, null));
            double duration = playbackDuration(audio);
            String name = displayName == null ? "My track" : displayName.replaceAll("\\p{Cntrl}", " ").trim();
            if (name.isEmpty()) name = "My track";
            if (name.length() > 100) name = name.substring(0, 100).trim();
            JSONObject state = new JSONObject().put("version", 1).put("projectId", id).put("name", name)
                    .put("settings", new JSONObject()).put("music", JSONObject.NULL).put("needAnalysis", true);
            JSONObject meta = metadata(new JSONObject(), id, name, duration, staging, state);
            writeObject(new File(staging, "project.json"), state, MAX_PROJECT_BYTES);
            writeObject(new File(staging, "meta.json"), meta, MAX_META_BYTES);
            if (!source.delete()) throw new IOException("Unable to finish importing the project.");
            progress.check(); publish(staging, destination); published = true;
            progress.update(1, "Music is ready");
            return meta;
        } finally { if (!published) removeTree(staging); }
    }

    /** Commit the editable state and its listing metadata as one recoverable pair. */
    static synchronized JSONObject save(File projectsRoot, String id, JSONObject value) throws Exception {
        File dir = project(root(projectsRoot), id); recoverProject(dir);
        JSONObject state = new JSONObject(value.toString()); validateState(state);
        JSONObject meta = readObject(safeFile(dir, "meta.json"), MAX_META_BYTES);
        String name = validName(state.optString("name", meta.optString("name", "My show")));
        state.put("projectId", id).put("name", name);
        meta.put("name", name).put("hasShow", state.optJSONObject("music") != null && !state.optBoolean("needAnalysis", false))
                .put("updatedAt", System.currentTimeMillis()).put("hasPreviousRevision", true);
        JSONObject settings = state.optJSONObject("settings");
        if (settings != null) meta.put("style", settings.optString("style", "festival"));
        commit(dir, meta, state, true);
        return meta;
    }

    /** Explicit undo of the last durable save; swaps revisions so it can be undone. */
    static synchronized JSONObject restorePrevious(File projectsRoot, String id) throws Exception {
        File dir = project(root(projectsRoot), id); recoverProject(dir);
        JSONObject revision = readObject(safeFile(dir, PREVIOUS), MAX_REVISION_BYTES);
        JSONObject state = revision.getJSONObject("project"), meta = revision.getJSONObject("meta");
        validatePair(dir, meta, state);
        meta.put("updatedAt", System.currentTimeMillis()).put("recoveredAt", System.currentTimeMillis())
                .put("hasPreviousRevision", true);
        commit(dir, meta, state, true);
        return meta;
    }

    static synchronized JSONObject describe(File projectsRoot, String id) throws Exception {
        File dir = project(root(projectsRoot), id); recoverProject(dir, false);
        JSONObject meta = readObject(safeFile(dir, "meta.json"), MAX_META_BYTES);
        meta.put("hasPreviousRevision", new File(dir, PREVIOUS).isFile());
        return meta;
    }

    private static void commit(File dir, JSONObject meta, JSONObject state, boolean retainPrevious) throws Exception {
        validatePair(dir, meta, state);
        // Staging is not a commit. If storage fills before the marker is durable,
        // the current pair remains authoritative and the abandoned stages are discarded.
        writeObject(new File(dir, ".rename-meta.json"), meta, MAX_META_BYTES);
        writeObject(new File(dir, ".rename-project.json"), state, MAX_PROJECT_BYTES);
        if (retainPrevious) {
            JSONObject oldMeta = readObject(safeFile(dir, "meta.json"), MAX_META_BYTES);
            JSONObject oldState = readState(dir, oldMeta.optString("name", "My show"));
            oldState.put("projectId", dir.getName()).put("name", oldMeta.getString("name"));
            writeObject(new File(dir, PREVIOUS), new JSONObject().put("version", 1)
                    .put("savedAt", System.currentTimeMillis()).put("meta", oldMeta).put("project", oldState), MAX_REVISION_BYTES);
        }
        writeObject(new File(dir, JOURNAL), new JSONObject().put("version", 2), 1024);
        recoverProject(dir);
    }

    private static void validatePair(File dir, JSONObject meta, JSONObject state) throws Exception {
        validateState(state);
        if (!dir.getName().equals(meta.optString("id")) || !dir.getName().equals(state.optString("projectId"))
                || !validName(meta.optString("name")).equals(state.optString("name")))
            throw new IOException("The saved project and its information do not match.");
    }

    /**
     * Repair only the disposable analysis copy of an existing project's music.
     * Playback samples and editable project data remain authoritative and untouched.
     * The local resource server calls this before serving analysis.wav, so projects
     * created by earlier builds can recover without asking for another import.
     */
    static synchronized boolean ensureAnalysis(File projectDirectory, AudioImporter.Progress progress) throws Exception {
        final AudioImporter.Progress work = progress != null ? progress : new AudioImporter.Progress() {
            public void update(double fraction, String message) {}
            public void check() throws IOException {}
        };
        File directory = projectDirectory.getCanonicalFile();
        if (!directory.isDirectory()) throw new IOException("This project no longer exists.");
        File playback = safeFile(directory, "audio.wav"), analysis = safeFile(directory, "analysis.wav");
        double duration = playbackDuration(playback);
        long playbackFrames = Math.round(duration * 44100);
        if (analysisValid(analysis, playbackFrames)) return false;
        work.check();
        work.update(0, "Repairing the project's analysis audio");
        String suffix = UUID.randomUUID().toString();
        File temporaryPlayback = new File(directory, ".repair-playback-" + suffix + ".wav");
        File temporaryAnalysis = new File(directory, ".repair-analysis-" + suffix + ".wav");
        try {
            AudioImporter.convert(playback, temporaryPlayback, temporaryAnalysis,
                    mappedProgress(work, 0, .95, "Repairing the project's analysis audio"));
            if (!analysisValid(temporaryAnalysis, playbackFrames))
                throw new IOException("The project's analysis audio could not be rebuilt completely.");
            work.check();
            try { Files.move(temporaryAnalysis.toPath(), analysis.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING); }
            catch (java.nio.file.AtomicMoveNotSupportedException unsupported) {
                if (!temporaryAnalysis.renameTo(analysis)) throw new IOException("The repaired analysis audio could not be saved.");
            }
            work.update(1, "Analysis audio is ready");
            return true;
        } finally {
            temporaryPlayback.delete();
            temporaryAnalysis.delete();
        }
    }

    private static boolean analysisValid(File analysis, long playbackFrames) {
        if (!analysis.isFile() || analysis.length() < 44 || analysis.length() > MAX_AUDIO_BYTES / 2) return false;
        try (RandomAccessFile input = new RandomAccessFile(analysis, "r")) {
            byte[] h = new byte[44]; input.readFully(h);
            if (!canonicalPcmHeader(h, input.length(), 22050, 1)) return false;
            long frames = AudioImporter.u32(h, 40) / 2;
            // Earlier imports resampled source -> 44.1k and source -> 22.05k
            // independently. Their legal rounding can differ by one mono sample.
            return Math.abs(frames - ((playbackFrames + 1) / 2)) <= 1;
        } catch (IOException invalid) { return false; }
    }

    private static boolean canonicalPcmHeader(byte[] h, long length, int rate, int channels) {
        int align = channels * 2;
        long data = AudioImporter.u32(h, 40);
        return "RIFF".equals(new String(h, 0, 4, StandardCharsets.US_ASCII))
                && "WAVE".equals(new String(h, 8, 4, StandardCharsets.US_ASCII))
                && "fmt ".equals(new String(h, 12, 4, StandardCharsets.US_ASCII))
                && "data".equals(new String(h, 36, 4, StandardCharsets.US_ASCII))
                && AudioImporter.u32(h, 4) + 8 == length && AudioImporter.u32(h, 16) == 16
                && AudioImporter.u16(h, 20) == 1 && AudioImporter.u16(h, 22) == channels
                && AudioImporter.u32(h, 24) == rate && AudioImporter.u32(h, 28) == (long)rate * align
                && AudioImporter.u16(h, 32) == align && AudioImporter.u16(h, 34) == 16
                && data + 44 == length && data % align == 0;
    }

    static synchronized JSONObject duplicate(File projectsRoot, String sourceId, String newName,
                                             AudioImporter.Progress progress) throws Exception {
        String name = validName(newName);
        File root = root(projectsRoot), source = project(root, sourceId);
        recoverProject(source);
        JSONObject oldMeta = readObject(safeFile(source, "meta.json"), MAX_META_BYTES);
        File sourceAudio = safeFile(source, "audio.wav");
        double duration = playbackDuration(sourceAudio);
        JSONObject state = readState(source, oldMeta.optString("name", name));
        String id = UUID.randomUUID().toString();
        File staging = makeStaging(root, id), destination = new File(root, id);
        boolean published = false;
        try {
            progress.check();
            ensureAnalysis(source, mappedProgress(progress, 0, .15, null));
            File sourceAnalysis = safeFile(source, "analysis.wav");
            long total = sourceAudio.length() + sourceAnalysis.length();
            AudioImporter.Progress copyProgress = mappedProgress(progress, .15, .85, null);
            copyFile(sourceAudio, new File(staging, "audio.wav"), MAX_AUDIO_BYTES,
                    copyProgress, 0, total);
            copyFile(sourceAnalysis, new File(staging, "analysis.wav"), MAX_AUDIO_BYTES / 2,
                    copyProgress, sourceAudio.length(), total);
            state.put("projectId", id).put("name", name);
            reconcileDuration(state, duration);
            JSONObject meta = metadata(oldMeta, id, name, duration, staging, state);
            writeObject(new File(staging, "project.json"), state, MAX_PROJECT_BYTES);
            writeObject(new File(staging, "meta.json"), meta, MAX_META_BYTES);
            progress.check();
            publish(staging, destination);
            published = true;
            progress.update(1, "Project duplicated");
            return meta;
        } finally {
            if (!published) removeTree(staging);
        }
    }

    static synchronized JSONObject restore(File projectsRoot, File backupZip,
                                           AudioImporter.Progress progress) throws Exception {
        File root = root(projectsRoot);
        if (!backupZip.isFile() || backupZip.length() < 22 || backupZip.length() > 3_000_000_000L)
            throw new IOException("Choose a complete LightForge project backup ZIP under 3 GB.");
        String id = UUID.randomUUID().toString();
        File staging = makeStaging(root, id), destination = new File(root, id);
        boolean published = false;
        try {
            progress.check();
            progress.update(.01, "Checking the project backup");
            File input = new File(staging, "restore-input.wav");
            File saved = new File(staging, "restore-project.json");
            try (ZipFile zip = new ZipFile(backupZip)) {
                ZipEntry audioEntry = null, projectEntry = null;
                Enumeration<? extends ZipEntry> entries = zip.entries();
                int count = 0;
                while (entries.hasMoreElements()) {
                    progress.check();
                    ZipEntry entry = entries.nextElement();
                    if (++count > 10000) throw new IOException("This ZIP contains too many entries to be a LightForge backup.");
                    if ("LightShow/lightshow.wav".equals(entry.getName())) {
                        if (audioEntry != null || entry.isDirectory()) throw new IOException("The backup contains duplicate or invalid playback audio.");
                        audioEntry = entry;
                    } else if ("Review/LightForge_Project.json".equals(entry.getName())) {
                        if (projectEntry != null || entry.isDirectory()) throw new IOException("The backup contains duplicate or invalid project data.");
                        projectEntry = entry;
                    }
                    // Unrecognized entries are never extracted or used as filesystem paths.
                }
                if (audioEntry == null || projectEntry == null)
                    throw new IOException("This ZIP is missing editable project data or music. Export a project backup from LightForge.");
                extractChecked(zip, projectEntry, saved, MAX_PROJECT_BYTES, progress, .02, .03);
                extractChecked(zip, audioEntry, input, MAX_AUDIO_BYTES, progress, .05, .35);
            }
            JSONObject state = readObject(saved, MAX_PROJECT_BYTES);
            validateState(state);
            String name = validName(state.optString("name", "Restored show"));
            progress.check();
            double duration = AudioImporter.convert(input, new File(staging, "audio.wav"),
                    new File(staging, "analysis.wav"), mappedProgress(progress, .42, .5, null));
            if (!Double.isFinite(duration) || duration < 1 || duration > 14400.0001)
                throw new IOException("The backup's audio duration is not supported by Tesla.");
            // Re-read the generated header; playback samples are authoritative.
            duration = playbackDuration(new File(staging, "audio.wav"));
            state.put("projectId", id).put("name", name);
            reconcileDuration(state, duration);
            JSONObject meta = metadata(new JSONObject(), id, name, duration, staging, state);
            meta.put("restoredAt", System.currentTimeMillis());
            writeObject(new File(staging, "project.json"), state, MAX_PROJECT_BYTES);
            writeObject(new File(staging, "meta.json"), meta, MAX_META_BYTES);
            if (!input.delete() || !saved.delete()) throw new IOException("Unable to finish restoring the project.");
            progress.check();
            publish(staging, destination);
            published = true;
            progress.update(1, "Editable project restored");
            return meta;
        } catch (java.util.zip.ZipException error) {
            throw new IOException("The backup ZIP is incomplete or damaged. Download or export it again.", error);
        } finally {
            if (!published) removeTree(staging);
        }
    }

    static synchronized JSONObject rename(File projectsRoot, String id, String newName) throws Exception {
        String name = validName(newName);
        File dir = project(root(projectsRoot), id);
        recoverProject(dir);
        JSONObject meta = readObject(safeFile(dir, "meta.json"), MAX_META_BYTES);
        JSONObject state = readState(dir, meta.optString("name", name));
        meta.put("name", name).put("updatedAt", System.currentTimeMillis());
        state.put("name", name).put("projectId", id);
        meta.put("hasPreviousRevision", true);
        commit(dir, meta, state, true);
        return meta;
    }

    /** Recover durable saves and clean only identifiable abandoned operations. */
    static synchronized void recover(File projectsRoot) throws IOException {
        File root = root(projectsRoot);
        File[] children = root.listFiles();
        if (children == null) throw new IOException("The project folder could not be opened.");
        IOException failed = null;
        for (File child : children) {
            if (child.getName().matches("\\.pending-[a-fA-F0-9-]{36}")
                    && root.equals(child.getCanonicalFile().getParentFile())) {
                removeTree(child);
                continue;
            }
            if (child.getName().matches("[A-Za-z0-9_-]{1,80}") && child.isDirectory()) {
                try {
                    File directory = project(root, child.getName());
                    // Pre-1.4 imports wrote directly into a published directory.
                    // Only that exact incomplete-import signature is disposable.
                    if (new File(directory, "input.media").isFile()
                            && !new File(directory, "meta.json").exists()
                            && !new File(directory, "project.json").exists()) removeTree(directory);
                    else recoverProject(directory);
                }
                catch (Exception error) { failed = new IOException("A saved project needs recovery from its exported backup. Other projects remain available.", error); }
            }
        }
        if (failed != null) throw failed;
    }

    private static void recoverProject(File dir) throws Exception {
        recoverProject(dir, true);
    }

    private static void recoverProject(File dir, boolean inspectState) throws Exception {
        File[] temporary = dir.listFiles();
        if (temporary != null) for (File file : temporary) {
            if (file.getName().matches("\\.repair-(playback|analysis)-[a-fA-F0-9-]{36}\\.wav")
                    || file.getName().matches("(?:project\\.json|meta\\.json|\\.previous-revision\\.json|\\.rename-(?:project|meta|journal)\\.json)\\.writing(?:-[a-fA-F0-9-]{36})?"))
                removeTree(file);
        }
        if (new File(dir, JOURNAL).isFile()) {
            JSONObject marker = readObject(safeFile(dir, JOURNAL), 1024);
            if (marker.optInt("version") != 1 && marker.optInt("version") != 2)
                throw new IOException("Unsupported project recovery data.");
            JSONObject meta = readObject(safeFile(dir, ".rename-meta.json"), MAX_META_BYTES);
            JSONObject state = readObject(safeFile(dir, ".rename-project.json"), MAX_PROJECT_BYTES);
            if (marker.optInt("version") == 2) validatePair(dir, meta, state);
            writeObject(new File(dir, "project.json"), state, MAX_PROJECT_BYTES);
            writeObject(new File(dir, "meta.json"), meta, MAX_META_BYTES);
            if (!new File(dir, JOURNAL).delete()) throw new IOException("Unable to complete the project save.");
        }
        new File(dir, ".rename-meta.json").delete();
        new File(dir, ".rename-project.json").delete();
        if (!inspectState) return;
        try {
            JSONObject meta = readObject(safeFile(dir, "meta.json"), MAX_META_BYTES);
            if (!new File(dir, "project.json").isFile() && new File(dir, PREVIOUS).isFile())
                throw new IOException("The last saved project state is missing.");
            readState(dir, meta.optString("name", "My show"));
        } catch (Exception damaged) {
            File previous = safeFile(dir, PREVIOUS);
            if (!previous.isFile()) throw damaged;
            JSONObject revision = readObject(previous, MAX_REVISION_BYTES);
            JSONObject meta = revision.getJSONObject("meta"), state = revision.getJSONObject("project");
            validatePair(dir, meta, state);
            meta.put("recoveredAt", System.currentTimeMillis()).put("updatedAt", System.currentTimeMillis())
                    .put("hasPreviousRevision", true);
            commit(dir, meta, state, false);
        }
    }

    private static JSONObject metadata(JSONObject previous, String id, String name, double duration,
                                       File directory, JSONObject state) throws Exception {
        JSONObject meta = new JSONObject(previous.toString());
        long now = System.currentTimeMillis();
        meta.put("id", id).put("name", name).put("duration", duration)
                .put("createdAt", now).put("updatedAt", now).put("sampleRate", 44100)
                .put("sizeBytes", new File(directory, "audio.wav").length())
                .put("audioUrl", ORIGIN + id + "/audio.wav")
                .put("analysisUrl", ORIGIN + id + "/analysis.wav")
                .put("projectUrl", ORIGIN + id + "/project.json")
                .put("hasShow", state.optJSONObject("music") != null && !state.optBoolean("needAnalysis", false));
        JSONObject settings = state.optJSONObject("settings");
        if (settings != null) meta.put("style", settings.optString("style", "festival"));
        return meta;
    }

    private static void reconcileDuration(JSONObject state, double duration) throws Exception {
        JSONObject music = state.optJSONObject("music");
        if (music == null) { state.put("needAnalysis", true); return; }
        double oldDuration = music.optDouble("duration", Double.NaN);
        music.put("duration", duration);
        JSONArray sections = music.optJSONArray("sections");
        if (sections != null && sections.length() > 0) {
            JSONObject last = sections.optJSONObject(sections.length() - 1);
            if (last != null) last.put("end", duration);
        }
        // Small rounding differences are expected. A different recording requires a
        // fresh neural pass, while preserving the user's editable controls and analysis.
        if (!Double.isFinite(oldDuration) || Math.abs(oldDuration - duration) > .1)
            state.put("needAnalysis", true);
    }

    private static JSONObject readState(File dir, String name) throws Exception {
        File file = safeFile(dir, "project.json");
        JSONObject state;
        if (file.isFile()) state = readObject(file, MAX_PROJECT_BYTES);
        else state = new JSONObject().put("version", 1).put("name", name)
                .put("settings", new JSONObject()).put("music", JSONObject.NULL).put("needAnalysis", true);
        validateState(state);
        return state;
    }

    private static void validateState(JSONObject state) throws Exception {
        Object version = state.opt("version");
        if (!(version instanceof Number) || ((Number) version).doubleValue() != 1)
            throw new IOException("This project backup version is not supported. Update LightForge before restoring it.");
        if (state.has("settings") && !state.isNull("settings") && state.optJSONObject("settings") == null)
            throw new IOException("The backup's editable show settings are damaged.");
        if (state.has("music") && !state.isNull("music") && state.optJSONObject("music") == null)
            throw new IOException("The backup's music analysis is damaged.");
        if (state.optJSONObject("settings") == null) state.put("settings", new JSONObject());
    }

    private static String validName(String value) throws IOException {
        String name = value == null ? "" : value.trim();
        if (name.length() < 1 || name.length() > 100)
            throw new IOException("Use a project name between 1 and 100 characters.");
        for (int i = 0; i < name.length(); i++) if (Character.isISOControl(name.charAt(i)))
            throw new IOException("Project names cannot contain control characters.");
        return name;
    }

    private static File root(File directory) throws IOException {
        File root = directory.getCanonicalFile();
        if (!root.isDirectory() && !root.mkdirs()) throw new IOException("The project folder could not be created.");
        return root;
    }

    private static File project(File root, String id) throws IOException {
        if (id == null || !id.matches("[A-Za-z0-9_-]{1,80}")) throw new IOException("Invalid project identifier.");
        File file = new File(root, id).getCanonicalFile();
        if (!root.equals(file.getParentFile()) || !file.isDirectory()) throw new IOException("This project no longer exists.");
        return file;
    }

    private static File safeFile(File directory, String name) throws IOException {
        File result = new File(directory, name).getCanonicalFile();
        if (!directory.getCanonicalFile().equals(result.getParentFile())) throw new IOException("The project contains an invalid file link.");
        return result;
    }

    private static File makeStaging(File root, String id) throws IOException {
        File staging = new File(root, ".pending-" + id);
        if (!staging.mkdir()) throw new IOException("Unable to create a project. Check available device storage.");
        return staging;
    }

    private static void publish(File staged, File target) throws IOException {
        if (target.exists()) throw new IOException("A project with this identifier already exists.");
        if (!staged.renameTo(target)) throw new IOException("Unable to save the completed project.");
    }

    private static JSONObject readObject(File file, int maximum) throws Exception {
        if (!file.isFile() || file.length() > maximum) throw new IOException("Project data is missing or too large.");
        try (InputStream input = new FileInputStream(file); ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[65536]; int size; long count = 0;
            while ((size = input.read(buffer)) != -1) {
                count += size;
                if (count > maximum) throw new IOException("Project data is too large.");
                bytes.write(buffer, 0, size);
            }
            try { return new JSONObject(new String(bytes.toByteArray(), StandardCharsets.UTF_8)); }
            catch (org.json.JSONException invalid) {
                throw new IOException("The saved project data is damaged or is not a LightForge project.", invalid);
            }
        }
    }

    private static void writeObject(File target, JSONObject value, int maximum) throws Exception {
        byte[] bytes = value.toString().getBytes(StandardCharsets.UTF_8);
        if (bytes.length > maximum) throw new IOException("Project data is too large to save.");
        File temporary = new File(target.getParentFile(), target.getName() + ".writing-" + UUID.randomUUID());
        try {
            try (FileOutputStream output = new FileOutputStream(temporary)) {
                output.write(bytes); output.getFD().sync();
            }
            try { Files.move(temporary.toPath(), target.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING); }
            catch (java.nio.file.AtomicMoveNotSupportedException unsupported) {
                if (!temporary.renameTo(target)) throw new IOException("Unable to save project data.");
            }
        } finally { temporary.delete(); }
    }

    private static void copyFile(File source, File destination, long maximum,
                                 AudioImporter.Progress progress, long before, long total) throws Exception {
        if (!source.isFile() || source.length() > maximum) throw new IOException("The project's audio is missing or too large.");
        try (InputStream input = new BufferedInputStream(new FileInputStream(source));
             FileOutputStream output = new FileOutputStream(destination)) {
            byte[] buffer = new byte[131072]; int size; long count = 0;
            while ((size = input.read(buffer)) != -1) {
                progress.check(); count += size;
                if (count > maximum) throw new IOException("The project's audio exceeds its size limit.");
                output.write(buffer, 0, size);
                progress.update(.02 + .88 * (before + count) / Math.max(1., total), "Copying project audio");
            }
            output.getFD().sync();
        }
    }

    private static void extractChecked(ZipFile zip, ZipEntry entry, File output, long maximum,
                                       AudioImporter.Progress progress, double start, double span) throws Exception {
        if (entry.getSize() < 1 || entry.getSize() > maximum || entry.getCrc() < 0)
            throw new IOException("A required backup file is empty, too large or invalid.");
        CRC32 crc = new CRC32(); long count = 0;
        try (InputStream input = new BufferedInputStream(zip.getInputStream(entry));
             FileOutputStream destination = new FileOutputStream(output)) {
            byte[] buffer = new byte[131072]; int size;
            while ((size = input.read(buffer)) != -1) {
                progress.check(); count += size;
                if (count > maximum || count > entry.getSize()) throw new IOException("The backup expands beyond its declared size.");
                crc.update(buffer, 0, size); destination.write(buffer, 0, size);
                progress.update(start + span * count / entry.getSize(), "Restoring " + (entry.getName().endsWith(".wav") ? "music" : "editable show settings"));
            }
            destination.getFD().sync();
        }
        if (count != entry.getSize() || crc.getValue() != entry.getCrc())
            throw new IOException("The backup failed its integrity check. Download or export it again.");
    }

    private static AudioImporter.Progress mappedProgress(final AudioImporter.Progress progress,
                                                         final double start, final double span, final String label) {
        return new AudioImporter.Progress() {
            public void update(double fraction, String message) { progress.update(start + span * Math.max(0, Math.min(1, fraction)), label == null ? message : label); }
            public void check() throws IOException { progress.check(); }
        };
    }

    private static double playbackDuration(File audio) throws IOException {
        if (!audio.isFile() || audio.length() < 44 || audio.length() > MAX_AUDIO_BYTES)
            throw new IOException("The project's playback audio is missing or invalid.");
        try (RandomAccessFile input = new RandomAccessFile(audio, "r")) {
            byte[] header = new byte[44]; input.readFully(header);
            if (!canonicalPcmHeader(header, input.length(), 44100, 2))
                throw new IOException("The project's audio is not the expected complete 44.1 kHz stereo WAV.");
            long bytes = AudioImporter.u32(header, 40);
            if (bytes % 4 != 0) throw new IOException("The project's audio sample data is incomplete.");
            double duration = bytes / 176400.;
            if (duration < 1 || duration > 14400) throw new IOException("The project's audio duration is unsupported.");
            return duration;
        }
    }

    private static void removeTree(File file) {
        if (file == null || (!file.exists() && !Files.isSymbolicLink(file.toPath()))) return;
        if (file.isDirectory() && !Files.isSymbolicLink(file.toPath())) {
            File[] children = file.listFiles();
            if (children != null) for (File child : children) removeTree(child);
        }
        file.delete();
    }
}
