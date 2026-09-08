package com.cyberbasslord.lightforge;

import android.app.ActivityManager;
import android.app.ApplicationExitInfo;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.content.pm.PackageInfo;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Debug;
import android.os.Environment;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.provider.MediaStore;
import android.provider.DocumentsContract;
import android.provider.OpenableColumns;
import android.util.JsonReader;
import android.util.JsonToken;
import android.webkit.WebView;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;
import java.util.UUID;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

/** App-local crash and operation evidence. No logcat, network, media, or broad storage access. */
public final class AppDiagnostics {
    private static final AtomicLong dropped = new AtomicLong(), writeFailures = new AtomicLong();
    private static final AtomicBoolean handlingFatal = new AtomicBoolean();
    private static volatile Context application;
    private static volatile DiagnosticLog journal;
    private static volatile Thread writerThread;
    private static final ThreadPoolExecutor writer = new ThreadPoolExecutor(1, 1, 0, TimeUnit.SECONDS,
        new ArrayBlockingQueue<Runnable>(256), runnable -> {
            Thread thread = new Thread(runnable, "LightForge-diagnostics");
            thread.setDaemon(true); thread.setPriority(Thread.MIN_PRIORITY); writerThread = thread; return thread;
        }, new ThreadPoolExecutor.AbortPolicy());

    private AppDiagnostics() {}

    /** Initialization installs the fatal handler immediately; disk work runs on the journal worker. */
    public static synchronized void initialize(Context context) {
        if (journal != null || context == null) return;
        try {
            Context app = context.getApplicationContext();
            application = app != null ? app : context;
            journal = new DiagnosticLog(new File(application.getFilesDir(), "diagnostics"));
            final Thread.UncaughtExceptionHandler prior = Thread.getDefaultUncaughtExceptionHandler();
            Thread.setDefaultUncaughtExceptionHandler((thread, error) -> {
                try {
                    if (handlingFatal.compareAndSet(false, true)) {
                        String details = "Uncaught exception; thread=" + (thread == Looper.getMainLooper().getThread() ? "main" : "worker") + "\n" + DiagnosticLog.throwable(error);
                        if (thread == writerThread) append("FATAL", "uncaught", details, true);
                        else {
                            // A fatal record must not sit behind hundreds of routine fsyncs.
                            // Existing disk history stays intact; queued work is expendable as the process exits.
                            int discarded = 0; Runnable pending;
                            while ((pending = writer.getQueue().poll()) != null) {
                                if (pending instanceof Future<?>) ((Future<?>)pending).cancel(false);
                                discarded++;
                            }
                            dropped.addAndGet(discarded);
                            final String fatalDetails = details + "\nPending events discarded at crash: " + discarded;
                            FutureTask<Void> fatal = new FutureTask<>(() -> { append("FATAL", "uncaught", fatalDetails, true); return null; });
                            if (enqueue(fatal, true)) try { fatal.get(600, TimeUnit.MILLISECONDS); } catch (Throwable ignored) {}
                        }
                    }
                } catch (Throwable ignored) {
                    // Error reporting must never hide the original crash or recurse on memory pressure.
                } finally {
                    if (prior != null) prior.uncaughtException(thread, error);
                    else { android.os.Process.killProcess(android.os.Process.myPid()); System.exit(10); }
                }
            });
            enqueue(() -> {
                append("INFO", "session", "Session started; uptimeMs=" + SystemClock.elapsedRealtime(), false);
                append("INFO", "environment", environment(application), false);
                append("INFO", "previous-exit", previousExits(application, false), false);
            }, false);
        } catch (Throwable ignored) { writeFailures.incrementAndGet(); }
    }

    /** Messages must be technical descriptions, never project metadata or audio/transcript contents. */
    public static void log(Context context, String level, String source, String message) {
        try {
            initialize(context);
            final String safe = DiagnosticLog.sanitize(message);
            enqueue(() -> append(level, source, safe, false), "ERROR".equalsIgnoreCase(level) || "FATAL".equalsIgnoreCase(level));
        } catch (Throwable ignored) { writeFailures.incrementAndGet(); }
    }

    public static void record(Context context, String source, Throwable error) {
        try {
            initialize(context);
            final String safe = DiagnosticLog.throwable(error);
            enqueue(() -> {
                append("ERROR", source, safe, true);
                append("INFO", "error-memory", memory(application), false);
            }, true);
        } catch (Throwable ignored) { writeFailures.incrementAndGet(); }
    }

    /** Explicit memory snapshots at expensive stage boundaries are cheap to enqueue. */
    public static void sample(Context context, String source) {
        try { initialize(context); enqueue(() -> append("INFO", source, memory(application), false), false); }
        catch (Throwable ignored) { writeFailures.incrementAndGet(); }
    }

    private static boolean enqueue(Runnable work, boolean important) {
        try { writer.execute(work); return true; }
        catch (RejectedExecutionException full) {
            if (important) {
                Runnable removed = writer.getQueue().poll();
                if (removed != null) { if (removed instanceof Future<?>) ((Future<?>)removed).cancel(false); dropped.incrementAndGet(); }
                try { writer.execute(work); return true; } catch (Throwable ignored) {}
            }
            dropped.incrementAndGet(); return false;
        } catch (Throwable ignored) { writeFailures.incrementAndGet(); return false; }
    }

    private static void append(String level, String source, String message, boolean sync) {
        try {
            DiagnosticLog current = journal;
            if (current != null) current.append(level, source, message, sync);
        } catch (Throwable ignored) { writeFailures.incrementAndGet(); }
    }

    /** Waits only on a worker thread. Returns false on saturation, interruption or deadline. */
    public static boolean flush(long timeoutMillis) {
        if (Thread.currentThread() == writerThread) return true;
        if (Looper.getMainLooper() != null && Thread.currentThread() == Looper.getMainLooper().getThread()) return false;
        FutureTask<Void> marker = new FutureTask<>(() -> null);
        if (!enqueue(marker, false)) return false;
        try { marker.get(Math.max(1, Math.min(timeoutMillis, 5000)), TimeUnit.MILLISECONDS); return true; }
        catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); return false; }
        catch (Exception unavailable) { return false; }
    }

    private static void requireWorker() throws IOException {
        if (Looper.getMainLooper() != null && Looper.myLooper() == Looper.getMainLooper()) throw new IOException("Diagnostic export must run in the background.");
    }

    private static String fileName() {
        SimpleDateFormat format = new SimpleDateFormat("yyyyMMdd-HHmmss-SSS", Locale.US); format.setTimeZone(TimeZone.getTimeZone("UTC"));
        return "LightForge-diagnostics-" + format.format(new Date()) + "-" + UUID.randomUUID().toString().substring(0, 8) + ".txt";
    }

    /** Providers may adjust extensions, resolve collisions, or accept a user-edited name. */
    private static String savedName(ContentResolver resolver, Uri uri) throws IOException {
        try (Cursor cursor = resolver.query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
            if (cursor != null && cursor.moveToFirst()) {
                String actual = cursor.getString(0);
                if (actual != null && !actual.trim().isEmpty()) return actual;
            }
        }
        throw new IOException("Android could not confirm the saved diagnostic filename.");
    }

    /** API 29+: direct public Downloads export. API 26–28: launch ACTION_CREATE_DOCUMENT using returned name. */
    public static JSONObject export(Context context) throws Exception {
        requireWorker(); initialize(context);
        String name = fileName();
        if (Build.VERSION.SDK_INT < 29) return new JSONObject().put("requiresPicker", true).put("name", name).put("mimeType", "text/plain");
        byte[] bytes = report();
        ContentResolver resolver = context.getContentResolver();
        ContentValues values = new ContentValues();
        values.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
        values.put(MediaStore.MediaColumns.MIME_TYPE, "text/plain");
        values.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/LightForge");
        values.put(MediaStore.MediaColumns.IS_PENDING, 1);
        Uri uri = null; boolean committed = false;
        try {
            uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
            if (uri == null) throw new IOException("Android could not create the diagnostic log in Downloads.");
            try (OutputStream out = resolver.openOutputStream(uri, "w")) {
                if (out == null) throw new IOException("Android could not open the diagnostic log.");
                out.write(bytes); out.flush();
            }
            ContentValues ready = new ContentValues(); ready.put(MediaStore.MediaColumns.IS_PENDING, 0);
            if (resolver.update(uri, ready, null, null) != 1) throw new IOException("Android could not finish saving the diagnostic log.");
            JSONObject result = new JSONObject().put("name", savedName(resolver, uri)).put("location", "Downloads/LightForge").put("uri", uri.toString()).put("bytes", bytes.length);
            committed = true;
            log(context, "INFO", "diagnostics-export", "Diagnostic report saved; bytes=" + bytes.length);
            return result;
        } finally {
            if (!committed && uri != null) try { resolver.delete(uri, null, null); } catch (Exception ignored) {}
        }
    }

    /** Writes only to the explicit system save-picker grant; no storage permission is required. */
    public static JSONObject exportTo(Context context, Uri uri, String suggestedName) throws Exception {
        requireWorker(); initialize(context);
        if (uri == null || !"content".equals(uri.getScheme())) throw new IOException("Choose a document destination for the diagnostic log.");
        byte[] bytes = report();
        boolean committed = false;
        try {
            try (OutputStream out = context.getContentResolver().openOutputStream(uri, "wt")) {
                if (out == null) throw new IOException("Android could not open the chosen diagnostic log.");
                out.write(bytes); out.flush();
            }
            JSONObject result = new JSONObject().put("name", savedName(context.getContentResolver(), uri)).put("location", "Selected document location").put("uri", uri.toString()).put("bytes", bytes.length);
            committed = true; return result;
        } finally {
            if (!committed) try { DocumentsContract.deleteDocument(context.getContentResolver(), uri); } catch (Exception ignored) {}
        }
    }

    private static byte[] report() throws Exception {
        DiagnosticLog current = journal;
        if (current == null) throw new IOException("Diagnostic history could not be initialized.");
        boolean drained = flush(5000);
        ByteArrayOutputStream bytes = new ByteArrayOutputStream(DiagnosticLog.SEGMENT_BYTES);
        String header = "LIGHTFORGE DIAGNOSTIC REPORT\nFormat: 1 (UTF-8)\nCreated UTC: " + new Date().toInstant() +
            "\nContains technical events, sanitized stack traces and Android exit evidence.\n" +
            "Excludes audio, transcripts, project names, credentials and private paths.\n" +
            "Logs survive app restarts and cache clearing; clear app data/uninstall removes history.\n" +
            "History bound: " + (DiagnosticLog.SEGMENT_BYTES * DiagnosticLog.SEGMENT_COUNT) + " bytes; oldest entries rotate.\n" +
            "Queue drained: " + drained + "; dropped events: " + dropped.get() + "; write failures: " + writeFailures.get() +
            "\n\nCURRENT ENVIRONMENT\n" + environment(application) + "\n\nCURRENT ANALYSIS JOB\n" + jobSnapshot(application) +
            "\n\nANDROID PREVIOUS PROCESS EXITS\n" + previousExits(application, true) + "\n\nPERSISTENT EVENT TRACE (oldest to newest)\n";
        bytes.write(header.getBytes(StandardCharsets.UTF_8));
        current.snapshot(bytes);
        bytes.write("\nEND OF DIAGNOSTIC REPORT\n".getBytes(StandardCharsets.UTF_8));
        return bytes.toByteArray();
    }

    private static String environment(Context context) {
        StringBuilder out = new StringBuilder();
        try {
            PackageInfo info = context.getPackageManager().getPackageInfo(context.getPackageName(), 0);
            long versionCode = Build.VERSION.SDK_INT >= 28 ? info.getLongVersionCode() : info.versionCode;
            out.append("app=").append(context.getPackageName()).append(" version=").append(info.versionName).append(" code=").append(versionCode);
            out.append("\nmanufacturer=").append(Build.MANUFACTURER).append(" model=").append(Build.MODEL).append(" sdk=").append(Build.VERSION.SDK_INT).append(" android=").append(Build.VERSION.RELEASE);
            out.append("\nabi=").append(java.util.Arrays.toString(Build.SUPPORTED_ABIS)).append(" cpuCores=").append(Runtime.getRuntime().availableProcessors());
            PackageInfo webview = WebView.getCurrentWebViewPackage();
            out.append("\nwebview=").append(webview == null ? "unavailable" : webview.packageName + " " + webview.versionName);
            PowerManager power = (PowerManager)context.getSystemService(Context.POWER_SERVICE);
            if (power != null) out.append("\nscreenInteractive=").append(power.isInteractive()).append(" deviceIdle=").append(power.isDeviceIdleMode()).append(" batteryExempt=").append(power.isIgnoringBatteryOptimizations(context.getPackageName()));
            ActivityManager activity = (ActivityManager)context.getSystemService(Context.ACTIVITY_SERVICE);
            if (activity != null && Build.VERSION.SDK_INT >= 28) out.append(" backgroundRestricted=").append(activity.isBackgroundRestricted());
        } catch (Throwable error) { out.append("\nSome environment details unavailable: ").append(error.getClass().getSimpleName()); }
        out.append('\n').append(memory(context));
        return DiagnosticLog.sanitize(out.toString());
    }

    private static String memory(Context context) {
        StringBuilder out = new StringBuilder();
        try {
            Runtime runtime = Runtime.getRuntime();
            out.append("heapUsedBytes=").append(runtime.totalMemory() - runtime.freeMemory()).append(" heapLimitBytes=").append(runtime.maxMemory());
            out.append(" nativeHeapBytes=").append(Debug.getNativeHeapAllocatedSize());
            Debug.MemoryInfo process = new Debug.MemoryInfo(); Debug.getMemoryInfo(process);
            out.append(" processPssKiB=").append(process.getTotalPss());
            if (context != null) {
                ActivityManager manager = (ActivityManager)context.getSystemService(Context.ACTIVITY_SERVICE);
                if (manager != null) {
                    ActivityManager.MemoryInfo system = new ActivityManager.MemoryInfo(); manager.getMemoryInfo(system);
                    out.append(" deviceAvailableBytes=").append(system.availMem).append(" deviceTotalBytes=").append(system.totalMem).append(" lowMemory=").append(system.lowMemory).append(" lowMemoryThresholdBytes=").append(system.threshold);
                }
                out.append(" appStorageFreeBytes=").append(context.getFilesDir().getUsableSpace());
            }
        } catch (Throwable error) { out.append(" memory details unavailable: ").append(error.getClass().getSimpleName()); }
        return out.toString();
    }

    private static String reason(int value) {
        switch (value) {
            case 1: return "EXIT_SELF"; case 2: return "SIGNALED"; case 3: return "LOW_MEMORY";
            case 4: return "CRASH_JAVA"; case 5: return "CRASH_NATIVE"; case 6: return "ANR";
            case 7: return "INITIALIZATION_FAILURE"; case 8: return "PERMISSION_CHANGE";
            case 9: return "EXCESSIVE_RESOURCE_USAGE"; case 10: return "USER_REQUESTED";
            case 11: return "USER_STOPPED"; case 12: return "DEPENDENCY_DIED";
            case 13: return "OTHER"; case 14: return "FREEZER"; case 15: return "PACKAGE_STATE_CHANGE";
            case 16: return "PACKAGE_UPDATED"; default: return "UNKNOWN";
        }
    }

    private static String jobSnapshot(Context context) {
        StringBuilder out = new StringBuilder();
        try {
            JSONObject job = AnalysisJobStore.status(context.getFilesDir());
            if (job == null) return "No saved analysis job.";
            String id = job.optString("id");
            if (id.matches("[a-fA-F0-9-]{36}")) out.append("jobRef=").append(id.substring(0, 8)).append('\n');
            for (String key : new String[]{"state", "stage", "lastStage", "analysisStage"}) {
                if (job.has(key)) out.append(key).append('=').append(DiagnosticLog.sanitize(job.optString(key))).append('\n');
            }
            for (String key : new String[]{"progress", "passageIndex", "passageCount", "passagesCompleted", "restoredPassages", "completedStages", "restoredStages", "elapsedMs", "createdAt", "updatedAt", "progressAt", "checkpointAt", "stoppedAt"}) {
                double number = job.optDouble(key, Double.NaN);
                if (Double.isFinite(number)) out.append(key).append('=').append(number).append('\n');
            }
            for (String key : new String[]{"hasCheckpoint", "resumeAvailable"}) if (job.has(key)) out.append(key).append('=').append(job.optBoolean(key)).append('\n');
            // Streaming plus a hard input budget avoids allocating large analysis/music JSON during a crash report.
            File request = new File(AnalysisJobStore.directory(context.getFilesDir()), "request.json");
            if (request.isFile()) try (InputStream file = new FileInputStream(request);
                InputStream limited = new FilterInputStream(file) {
                    int remaining = 256 * 1024;
                    @Override public int read() throws IOException { if (remaining <= 0) throw new IOException("Diagnostic request budget reached."); int value = super.read(); if (value >= 0) remaining--; return value; }
                    @Override public int read(byte[] buffer, int offset, int count) throws IOException { if (remaining <= 0) throw new IOException("Diagnostic request budget reached."); int result = in.read(buffer, offset, Math.min(count, remaining)); if (result > 0) remaining -= result; return result; }
                };
                JsonReader reader = new JsonReader(new InputStreamReader(limited, StandardCharsets.UTF_8))) {
                boolean gotDuration = false, gotQuality = false;
                reader.beginObject();
                while (reader.hasNext() && !(gotDuration && gotQuality)) {
                    String field = reader.nextName();
                    if ("duration".equals(field) && reader.peek() == JsonToken.NUMBER) {
                        double duration = reader.nextDouble();
                        if (Double.isFinite(duration) && duration >= 0 && duration <= 14400) out.append("durationSeconds=").append(duration).append('\n');
                        gotDuration = true;
                    } else if ("settings".equals(field) && reader.peek() == JsonToken.BEGIN_OBJECT) {
                        reader.beginObject();
                        while (reader.hasNext()) {
                            String setting = reader.nextName();
                            if ("analysisQuality".equals(setting) && reader.peek() == JsonToken.STRING) {
                                String quality = reader.nextString();
                                out.append("analysisQuality=").append("balanced".equals(quality) ? "balanced" : "precision").append('\n'); gotQuality = true;
                            } else reader.skipValue();
                        }
                        reader.endObject();
                    } else reader.skipValue();
                }
            } catch (Exception bounded) { out.append("Some request fields unavailable within diagnostic read budget.\n"); }
        } catch (Throwable unavailable) { out.append("Analysis job snapshot unavailable: ").append(unavailable.getClass().getSimpleName()); }
        return out.toString();
    }

    private static String previousExits(Context context, boolean includeTrace) {
        if (Build.VERSION.SDK_INT < 30) return "Detailed process-exit history requires Android 11 or later. Java crash history remains in the event trace.";
        StringBuilder out = new StringBuilder();
        try {
            ActivityManager manager = (ActivityManager)context.getSystemService(Context.ACTIVITY_SERVICE);
            if (manager == null) return "Android process-exit service unavailable.";
            List<ApplicationExitInfo> exits = manager.getHistoricalProcessExitReasons(context.getPackageName(), 0, 8);
            if (exits.isEmpty()) return "Android has no retained process-exit records for this app.";
            int traces = 0;
            for (ApplicationExitInfo exit : exits) {
                out.append("timestampMs=").append(exit.getTimestamp()).append(" reason=").append(reason(exit.getReason())).append("(").append(exit.getReason()).append(") status=").append(exit.getStatus());
                out.append(" importance=").append(exit.getImportance()).append(" pssKiB=").append(exit.getPss()).append(" rssKiB=").append(exit.getRss());
                out.append(" process=").append(context.getPackageName().equals(exit.getProcessName()) ? "main" : "app-related");
                out.append(" description=").append(DiagnosticLog.sanitize(exit.getDescription())).append('\n');
                if (includeTrace && traces < 2 && (exit.getReason() == ApplicationExitInfo.REASON_ANR || exit.getReason() == ApplicationExitInfo.REASON_CRASH_NATIVE)) {
                    try (InputStream input = exit.getTraceInputStream()) {
                        if (input == null) { out.append("  No retained stack trace.\n"); continue; }
                        traces++;
                        if (Build.VERSION.SDK_INT >= 31 && exit.getReason() == ApplicationExitInfo.REASON_CRASH_NATIVE) {
                            // Android exposes native tombstones as protobuf, not UTF-8 stack dumps.
                            out.append(NativeCrashTrace.read(input));
                            continue;
                        }
                        // ANR traces can include user data; retain only frame lines, never headers or dumps.
                        byte[] raw = new byte[64 * 1024]; int count = 0, read;
                        while (count < raw.length && (read = input.read(raw, count, raw.length - count)) > 0) count += read;
                        String[] lines = new String(raw, 0, count, StandardCharsets.UTF_8).split("\n"); int kept = 0;
                        for (String line : lines) {
                            String trimmed = line.trim();
                            if ((trimmed.startsWith("at ") || trimmed.startsWith("native: #") || trimmed.matches("#[0-9]+ .*")) && kept++ < 80) out.append("  ").append(DiagnosticLog.sanitize(trimmed)).append('\n');
                        }
                        if (kept == 0) out.append("  No readable stack frames retained.\n");
                        out.append("  Trace limited to 64 KiB input / 80 sanitized frames.\n");
                    } catch (Throwable unavailable) { out.append("  Stack trace unavailable: ").append(unavailable.getClass().getSimpleName()).append('\n'); }
                }
            }
        } catch (Throwable unavailable) { out.append("Android exit history unavailable: ").append(unavailable.getClass().getSimpleName()); }
        return out.toString();
    }
}
