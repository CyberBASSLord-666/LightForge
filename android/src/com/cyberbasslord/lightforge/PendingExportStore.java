package com.cyberbasslord.lightforge;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.UUID;
import org.json.JSONObject;

/** One durable, already-verified export, retained until saved or explicitly discarded. */
final class PendingExportStore {
    private static final String MARKER = "pending-export.json";
    private static final long MAX_ZIP_BYTES = 3_000_000_000L;
    private PendingExportStore() {}

    static synchronized JSONObject prepare(File directory, File zip, String name) throws Exception {
        File root = root(directory), file = zip.getCanonicalFile();
        if (!root.equals(file.getParentFile()) || !file.getName().matches("[a-fA-F0-9-]{36}\\.zip")
                || !file.isFile() || file.length() < 22 || file.length() > MAX_ZIP_BYTES)
            throw new IOException("The prepared export is missing or invalid.");
        if (new File(root, MARKER).exists()) throw new IOException("Save or discard the previous prepared export first.");
        // The ZIP stream has closed and its entries passed CRC verification.
        try (RandomAccessFile output = new RandomAccessFile(file, "rw")) { output.getFD().sync(); }
        JSONObject value = new JSONObject().put("version", 1).put("file", file.getName())
                .put("name", name).put("bytes", file.length()).put("createdAt", System.currentTimeMillis());
        write(root, value);
        return value;
    }

    static synchronized JSONObject read(File directory) throws Exception {
        File root = root(directory), marker = new File(root, MARKER);
        if (!marker.isFile()) return null;
        if (marker.length() < 2 || marker.length() > 65536) throw new IOException("Prepared export information is damaged.");
        JSONObject value = new JSONObject(new String(Files.readAllBytes(marker.toPath()), StandardCharsets.UTF_8));
        if (value.optInt("version") != 1) throw new IOException("Unsupported prepared export information.");
        File file = checkedFile(root, value);
        if (!file.isFile() || file.length() < 22 || file.length() > MAX_ZIP_BYTES || file.length() != value.optLong("bytes", -1))
            throw new IOException("The prepared export is incomplete. Create the export again.");
        return value;
    }

    static synchronized File file(File directory, JSONObject value) throws IOException {
        return checkedFile(root(directory), value);
    }

    static synchronized void destination(File directory, String uri) throws Exception {
        JSONObject value = read(directory);
        if (value == null) throw new IOException("The prepared export is no longer available.");
        // Only the Activity consumes this value via ContentResolver. It is never a path.
        if (uri == null || uri.length() > 16384 || !uri.startsWith("content://"))
            throw new IOException("Choose a document storage destination.");
        value.put("destinationUri", uri);
        write(root(directory), value);
    }

    static synchronized void clearDestination(File directory) throws Exception {
        JSONObject value = read(directory);
        if (value != null && value.has("destinationUri")) { value.remove("destinationUri"); write(root(directory), value); }
    }

    static synchronized void discard(File directory) throws Exception {
        File root = root(directory);
        JSONObject value = null;
        // Explicit discard must also release an invalid marker, without ever
        // trusting a damaged stored path. Cleanup below uses a fixed filename set.
        try { value = read(root); } catch (Exception invalid) {}
        // Remove the marker first: a crash during cleanup leaves a disposable orphan.
        File marker = new File(root, MARKER);
        if (marker.exists() && !marker.delete()) throw new IOException("Unable to discard the prepared export.");
        if (value != null) checkedFile(root, value).delete();
        cleanup(root, null);
    }

    /** Startup only; do not run while a new ZIP is being built. */
    static synchronized JSONObject recover(File directory) throws Exception {
        File root = root(directory);
        JSONObject value;
        try { value = read(root); }
        catch (Exception invalid) {
            File marker = new File(root, MARKER);
            if (!marker.delete()) throw new IOException("Unable to clean up an incomplete export.", invalid);
            cleanup(root, null);
            throw invalid;
        }
        cleanup(root, value == null ? null : value.getString("file"));
        return value;
    }

    private static void cleanup(File root, String keep) throws IOException {
        File[] children = root.listFiles(); if (children == null) throw new IOException("Export storage could not be opened.");
        for (File file : children) {
            String name = file.getName();
            if (!name.equals(keep) && (name.matches("[a-fA-F0-9-]{36}\\.(zip|fseq)")
                    || name.matches("pending-export\\.json\\.writing-[a-fA-F0-9-]{36}"))) {
                // Never traverse links or delete an unrelated file in this directory.
                if (!Files.isSymbolicLink(file.toPath()) && !file.isDirectory()) file.delete();
                else if (Files.isSymbolicLink(file.toPath())) Files.deleteIfExists(file.toPath());
            }
        }
    }

    private static File checkedFile(File root, JSONObject value) throws IOException {
        String name = value.optString("file");
        if (!name.matches("[a-fA-F0-9-]{36}\\.zip")) throw new IOException("Invalid prepared export identifier.");
        File file = new File(root, name).getCanonicalFile();
        if (!root.equals(file.getParentFile())) throw new IOException("Invalid prepared export location.");
        return file;
    }

    private static File root(File directory) throws IOException {
        File root = directory.getCanonicalFile();
        if (!root.isDirectory() && !root.mkdirs()) throw new IOException("Export storage could not be created.");
        return root;
    }

    private static void write(File root, JSONObject value) throws Exception {
        byte[] bytes = value.toString().getBytes(StandardCharsets.UTF_8);
        if (bytes.length > 65536) throw new IOException("Prepared export information is too large.");
        File marker = new File(root, MARKER), temporary = new File(root, MARKER + ".writing-" + UUID.randomUUID());
        try {
            try (FileOutputStream output = new FileOutputStream(temporary)) { output.write(bytes); output.getFD().sync(); }
            try { Files.move(temporary.toPath(), marker.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING); }
            catch (java.nio.file.AtomicMoveNotSupportedException unsupported) {
                if (!temporary.renameTo(marker)) throw new IOException("The prepared export could not be saved.");
            }
        } finally { temporary.delete(); }
    }
}
