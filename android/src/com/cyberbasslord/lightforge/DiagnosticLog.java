package com.cyberbasslord.lightforge;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;
import java.util.regex.Pattern;

/** Bounded, process-persistent diagnostic journal. Has no Android dependencies. */
public final class DiagnosticLog {
    public static final int SEGMENT_BYTES = 256 * 1024, SEGMENT_COUNT = 4;
    private static final int MESSAGE_CHARS = 8192;
    private static final Pattern QUOTED = Pattern.compile("\"[^\"\\r\\n]*\"|'[^'\\r\\n]*'");
    private static final Pattern SECRET = Pattern.compile("(?i)\\b(?:authorization|bearer|password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|cookie)\\b\\s*[:=]?\\s*[^\\s,;]+(?:\\s+[^\\s,;]+)?");
    private static final Pattern NAMED = Pattern.compile("(?i)\\b(?:project(?:[_ -]?(?:name|title))?|song|title|filename|file_name|lyrics)\\s*[:=]\\s*[^\\r\\n;]+(?:;|$)");
    private static final Pattern URI = Pattern.compile("(?i)\\b(?:https?|file|content|data)://?[^\\s<>]+|\\bdata:[^\\s<>]+");
    private static final Pattern PATH = Pattern.compile("(?<![A-Za-z0-9])(?:/[A-Za-z0-9._~%+ -]+){2,}|[A-Za-z]:\\\\[^\\r\\n,;]+");
    private static final Pattern EMAIL = Pattern.compile("[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}");
    private static final Pattern MEDIA = Pattern.compile("(?i)(?:[\\p{L}\\p{N}_() .-]+)\\.(?:mp3|wav|flac|m4a|aac|ogg|opus|mp4|aiff|zip|fseq)\\b");
    private static final Pattern OPAQUE = Pattern.compile("\\b(?:[a-fA-F0-9]{8}-[a-fA-F0-9-]{27,}|(?:sk|ghp|github_pat)[_-][A-Za-z0-9_-]+|[A-Za-z0-9_+/-]{48,}={0,2})\\b");
    private final File directory;
    private final int segmentBytes, segmentCount;
    private boolean prepared;

    public DiagnosticLog(File directory) { this(directory, SEGMENT_BYTES, SEGMENT_COUNT); }
    DiagnosticLog(File directory, int segmentBytes, int segmentCount) {
        if (segmentBytes < 1024 || segmentCount < 2 || segmentCount > 8) throw new IllegalArgumentException("Invalid journal limits.");
        this.directory = directory; this.segmentBytes = segmentBytes; this.segmentCount = segmentCount;
    }
    private File file(int index) { return new File(directory, "trace-" + index + ".log"); }

    /** Deliberately excludes media contents, paths, account identifiers and credentials. */
    public static String sanitize(String value) {
        if (value == null) return "";
        boolean shortened = value.length() > MESSAGE_CHARS;
        String text = value.substring(0, Math.min(value.length(), MESSAGE_CHARS));
        text = text.replaceAll("[\\p{Cntrl}&&[^\\r\\n\\t]]", "?");
        text = SECRET.matcher(text).replaceAll("[credential redacted]");
        text = NAMED.matcher(text).replaceAll("[private name redacted]");
        text = URI.matcher(text).replaceAll("[URI redacted]");
        text = PATH.matcher(text).replaceAll("[path redacted]");
        text = EMAIL.matcher(text).replaceAll("[email redacted]");
        text = MEDIA.matcher(text).replaceAll("[media filename redacted]");
        text = OPAQUE.matcher(text).replaceAll("[identifier redacted]");
        text = QUOTED.matcher(text).replaceAll("[quoted value redacted]");
        return text + (shortened ? " [truncated]" : "");
    }

    public static String throwable(Throwable error) {
        if (error == null) return "No exception detail.";
        StringBuilder out = new StringBuilder();
        try {
            Throwable current = error;
            for (int cause = 0; current != null && cause < 4 && out.length() < MESSAGE_CHARS; cause++) {
                if (cause != 0) out.append("\nCaused by: ");
                out.append(current.getClass().getName()).append(": ").append(sanitize(current.getMessage()));
                StackTraceElement[] frames = current.getStackTrace();
                for (int i = 0; i < Math.min(frames.length, 32) && out.length() < MESSAGE_CHARS; i++) out.append("\n  at ").append(frames[i]);
                if (frames.length > 32) out.append("\n  [additional frames omitted]");
                Throwable next = current.getCause();
                if (next == current) break;
                current = next;
            }
        } catch (Throwable ignored) { out.append(" [exception detail unavailable]"); }
        return sanitize(out.toString());
    }

    public synchronized void append(String level, String source, String message) throws IOException {
        append(level, source, message, false);
    }
    public synchronized void append(String level, String source, String message, boolean sync) throws IOException {
        prepare();
        String severity = level == null ? "INFO" : level.toUpperCase(Locale.ROOT);
        if (!severity.matches("DEBUG|INFO|WARN|ERROR|FATAL")) severity = "INFO";
        String origin = source != null && source.matches("[A-Za-z0-9_.-]{1,48}") ? source : "app";
        SimpleDateFormat date = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US);
        date.setTimeZone(TimeZone.getTimeZone("UTC"));
        String body = sanitize(message).replace("\r", "\\r").replace("\n", "\\n");
        String prefix = date.format(new Date()) + " " + severity + " " + origin + " ";
        byte[] bytes = (prefix + body + "\n").getBytes(StandardCharsets.UTF_8);
        int limit = Math.min(32 * 1024, segmentBytes / 2);
        if (bytes.length > limit) {
            // Truncate characters, not arbitrary UTF-8 byte boundaries.
            while ((prefix + body + " [truncated]\n").getBytes(StandardCharsets.UTF_8).length > limit) body = body.substring(0, Math.max(0, body.length() * 3 / 4));
            bytes = (prefix + body + " [truncated]\n").getBytes(StandardCharsets.UTF_8);
        }
        if (file(0).length() + bytes.length > segmentBytes) rotate();
        try (FileOutputStream output = new FileOutputStream(file(0), true)) {
            output.write(bytes);
            if (sync) output.getFD().sync();
        }
    }

    private void prepare() throws IOException {
        if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("Diagnostic storage is unavailable.");
        if (prepared) return;
        for (int i = 0; i < segmentCount; i++) {
            File current = file(i);
            if (Files.isSymbolicLink(current.toPath())) throw new IOException("Unexpected diagnostic storage link.");
            if (!current.exists()) continue;
            if (!current.isFile()) throw new IOException("Unexpected diagnostic storage entry.");
            byte[] clean = recovered(current);
            // Valid history is read-only on restart. A crash during repair must never truncate
            // the last crash's evidence; sync a sibling file and atomically replace only on success.
            if (current.length() == clean.length && java.util.Arrays.equals(clean, Files.readAllBytes(current.toPath()))) continue;
            File temporary = new File(directory, ".trace-" + i + ".repair");
            if (Files.isSymbolicLink(temporary.toPath())) throw new IOException("Unexpected diagnostic repair link.");
            boolean moved = false;
            try {
                try (FileOutputStream out = new FileOutputStream(temporary)) { out.write(clean); out.getFD().sync(); }
                Files.move(temporary.toPath(), current.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
                moved = true;
            } finally {
                if (!moved && temporary.isFile()) temporary.delete();
            }
        }
        prepared = true;
    }

    private byte[] recovered(File current) throws IOException {
        byte[] bytes;
        long length = current.length();
        int count = (int)Math.min(length, segmentBytes);
        try (RandomAccessFile input = new RandomAccessFile(current, "r")) {
            input.seek(Math.max(0, length - count));
            bytes = new byte[count]; input.readFully(bytes);
        }
        int start = 0, end = bytes.length;
        if (length > count) { while (start < end && bytes[start] != '\n') start++; start = Math.min(end, start + 1); }
        while (end > start && bytes[end - 1] != '\n') end--;
        if (end <= start) return new byte[0];
        // Old or damaged journal data is sanitized again before it can be exported.
        String text = new String(bytes, start, end - start, StandardCharsets.UTF_8);
        StringBuilder out = new StringBuilder();
        for (String line : text.split("\n")) {
            String clean = sanitize(line).replace("\r", "\\r").replace('\ufffd', '?');
            out.append(clean).append('\n');
        }
        byte[] result = out.toString().getBytes(StandardCharsets.UTF_8);
        if (result.length <= segmentBytes) return result;
        // Redaction can increase short lines; keep only complete newest records within the bound.
        int offset = result.length - segmentBytes;
        while (offset < result.length && result[offset] != '\n') offset++;
        return java.util.Arrays.copyOfRange(result, Math.min(result.length, offset + 1), result.length);
    }

    private void rotate() throws IOException {
        if (file(segmentCount - 1).exists() && !file(segmentCount - 1).delete()) throw new IOException("Could not rotate diagnostic history.");
        for (int i = segmentCount - 2; i >= 0; i--) {
            File old = file(i);
            if (old.exists() && !old.renameTo(file(i + 1))) throw new IOException("Could not rotate diagnostic history.");
        }
    }

    /** Snapshot is bounded to SEGMENT_COUNT * SEGMENT_BYTES; caller supplies a worker thread. */
    public synchronized void snapshot(OutputStream output) throws IOException {
        prepare();
        for (int i = segmentCount - 1; i >= 0; i--) if (file(i).isFile()) output.write(recovered(file(i)));
    }
}
