package com.cyberbasslord.lightforge;

import android.app.AlertDialog;
import android.app.ActivityManager;
import android.app.ApplicationExitInfo;
import android.app.Instrumentation;
import android.content.ContentResolver;
import android.content.ContentUris;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Process;
import android.os.SystemClock;
import android.provider.MediaStore;
import android.system.Os;
import android.system.OsConstants;
import android.view.ViewGroup;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONArray;
import org.json.JSONObject;
import org.json.JSONTokener;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.FileInputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Separate same-signed test APK; exercises the production app and Android Downloads provider. */
public final class DiagnosticsInstrumentation extends Instrumentation {
    private final JSONArray checks = new JSONArray();
    private final Set<Uri> created = new HashSet<>();
    private MainActivity activity;
    private String mode, marker;
    private int nativeCrashPid;

    private void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private void status(String message) {
        Bundle result = new Bundle();
        result.putString("stream", message + "\n");
        sendStatus(0, result);
    }

    private void pass(String message) {
        checks.put(message);
        status(message);
    }

    private Object field(Object instance, String name) throws Exception {
        Field value = instance.getClass().getDeclaredField(name);
        value.setAccessible(true);
        return value.get(instance);
    }

    private void main(Runnable action) throws Exception {
        AtomicReference<Throwable> failure = new AtomicReference<>();
        runOnMainSync(() -> {
            try { action.run(); } catch (Throwable error) { failure.set(error); }
        });
        if (failure.get() != null) throw new AssertionError("Main-thread action failed", failure.get());
    }

    private Object javascript(String script) throws Exception {
        WebView web = (WebView) field(activity, "web");
        check(web != null, "Preview WebView is unavailable");
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<String> value = new AtomicReference<>();
        main(() -> web.evaluateJavascript(script, result -> { value.set(result); latch.countDown(); }));
        check(latch.await(15, TimeUnit.SECONDS), "JavaScript callback timed out");
        return new JSONTokener(value.get()).nextValue();
    }

    private void launch() throws Exception {
        activity = (MainActivity) startActivitySync(new Intent(getTargetContext(), MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        waitForIdleSync();
        long deadline = SystemClock.elapsedRealtime() + 45000;
        while (SystemClock.elapsedRealtime() < deadline) {
            if (Boolean.TRUE.equals(javascript("Boolean(window.LightForgeApp && window.LightForgeDiagnostics && document.querySelector('#guide [data-export-diagnostics]'))"))) return;
            SystemClock.sleep(100);
        }
        throw new AssertionError("Production diagnostic UI did not load");
    }

    private void verifyNoStoragePermission() throws Exception {
        PackageInfo info = getTargetContext().getPackageManager().getPackageInfo(
                getTargetContext().getPackageName(), PackageManager.GET_PERMISSIONS);
        if (info.requestedPermissions != null) {
            for (String permission : info.requestedPermissions) {
                check(!permission.equals("android.permission.READ_EXTERNAL_STORAGE")
                                && !permission.equals("android.permission.WRITE_EXTERNAL_STORAGE")
                                && !permission.equals("android.permission.MANAGE_EXTERNAL_STORAGE"),
                        "Diagnostic export added broad storage access: " + permission);
            }
        }
        check(getTargetContext().checkSelfPermission("android.permission.WRITE_EXTERNAL_STORAGE")
                != PackageManager.PERMISSION_GRANTED, "Storage permission unexpectedly granted");
        pass("Production app requests no broad storage permission and exports without a storage grant.");
    }

    private String report(JSONObject result) throws Exception {
        check(!result.optBoolean("requiresPicker"), "API 35 unexpectedly requested a document picker");
        Uri uri = Uri.parse(result.getString("uri"));
        created.add(uri);
        check("content".equals(uri.getScheme()) && "media".equals(uri.getAuthority()),
                "Export was not saved through Android MediaStore");
        String name = result.getString("name");
        check(name.startsWith("LightForge-diagnostics-") && name.endsWith(".txt"), "Unexpected export filename: " + name);
        check("Downloads/LightForge".equals(result.getString("location")),
                "Modern diagnostic export must identify its containing folder: " + result.optString("location"));
        ContentResolver resolver = getTargetContext().getContentResolver();
        try (Cursor cursor = resolver.query(uri, new String[]{MediaStore.Downloads.DISPLAY_NAME,
                MediaStore.Downloads.RELATIVE_PATH, MediaStore.Downloads.MIME_TYPE,
                MediaStore.Downloads.IS_PENDING, MediaStore.Downloads.SIZE}, null, null, null)) {
            check(cursor != null && cursor.moveToFirst(), "Export missing from Downloads provider");
            check(name.equals(cursor.getString(0)), "Export metadata filename does not match its file: expected="
                    + name + "; actual=" + cursor.getString(0));
            check("Download/LightForge/".equals(cursor.getString(1)), "Log is not in Downloads/LightForge: " + cursor.getString(1));
            check("text/plain".equals(cursor.getString(2)), "Diagnostic log is not readable plain text");
            check(cursor.getInt(3) == 0, "Diagnostic export left an unfinished pending file");
            check(cursor.getLong(4) == result.getLong("bytes"), "Export byte count does not match Downloads");
        }
        return readReport(uri, result.getLong("bytes"));
    }

    private String readReport(Uri uri, long expectedBytes) throws Exception {
        try (InputStream in = getTargetContext().getContentResolver().openInputStream(uri);
             ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            check(in != null, "Export cannot be reopened");
            byte[] bytes = new byte[8192];
            int count;
            while ((count = in.read(bytes)) != -1) {
                check(out.size() + count <= 2 * 1024 * 1024, "Export exceeds its bounded report size");
                out.write(bytes, 0, count);
            }
            check(out.size() == expectedBytes, "Written report is incomplete: expected=" + expectedBytes + "; actual=" + out.size());
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    private void verifyPrivateDataAbsent(String report) {
        for (String secret : new String[]{"private-performance.wav", "content://private.music/", "do-not-export-this-password", "hidden-relative-project.wav"}) {
            check(!report.contains(secret), "Report leaked a private test value");
        }
        check(!report.contains("/data/user/0/com.cyberbasslord.lightforge/"), "Report leaked the private data path");
    }

    private Set<Uri> downloads() throws Exception {
        Set<Uri> result = new HashSet<>();
        Uri collection = MediaStore.Downloads.EXTERNAL_CONTENT_URI;
        try (Cursor cursor = getTargetContext().getContentResolver().query(collection,
                new String[]{MediaStore.Downloads._ID}, MediaStore.Downloads.RELATIVE_PATH + "=? AND "
                        + MediaStore.Downloads.DISPLAY_NAME + " LIKE ?",
                new String[]{"Download/LightForge/", "LightForge-diagnostics-%.txt"}, null)) {
            check(cursor != null, "Cannot query the app's Downloads exports");
            while (cursor.moveToNext()) result.add(ContentUris.withAppendedId(collection, cursor.getLong(0)));
        }
        return result;
    }

    private void seedAndCrash() throws Exception {
        AppDiagnostics.initialize(getTargetContext());
        AppDiagnostics.log(getTargetContext(), "INFO", "diagnostic-probe", marker + "-durable-before-crash");
        AppDiagnostics.record(getTargetContext(), "diagnostic-probe",
                new IOException(marker + "-recorded-error content://private.music/private-performance.wav",
                        new IllegalStateException("password=do-not-export-this-password")));
        check(AppDiagnostics.flush(10000), "Could not flush the pre-crash journal");
        File fixture = new File(getTargetContext().getCacheDir(), "diagnostic-cache-probe.tmp");
        try (FileOutputStream output = new FileOutputStream(fixture)) { output.write(42); }
        check(fixture.delete(), "Could not clear the test's temporary cache fixture");
        status("DIAGNOSTICS_EXPECTED_UNCAUGHT_CRASH " + marker + " pid=" + Process.myPid());
        new Thread(() -> { throw new IllegalStateException(marker + "-uncaught-worker-crash"); },
                "LightForge-diagnostic-crash-probe").start();
        SystemClock.sleep(15000);
        throw new AssertionError("The intentionally uncaught exception did not terminate the process");
    }

    private File nativeGuardFile() {
        return new File(getTargetContext().getFilesDir(), "diagnostics/native-runtime-guard.bin");
    }

    private File nativeProbeBackup() {
        return new File(getTargetContext().getFilesDir(), "diagnostics/.native-probe-" + marker + ".bin");
    }

    private NativeRuntimeGuard nativeGuard() throws Exception {
        Context context = getTargetContext();
        return new NativeRuntimeGuard(new File(context.getFilesDir(), "diagnostics"),
                context.getPackageManager().getPackageInfo(context.getPackageName(), 0).versionCode
                        + "-" + NativeDeux.RUNTIME_VERSION);
    }

    /** The same-signed test temporarily owns the production marker; restore prior state afterwards. */
    private void prepareNativeProbe() throws Exception {
        File guard = nativeGuardFile(), backup = nativeProbeBackup();
        long beganAt = System.currentTimeMillis();
        check(!backup.exists(), "Native probe backup already exists for this marker");
        byte[] prior = null;
        if (guard.exists()) {
            check(guard.isFile() && guard.length() <= 1024, "Prior guard fixture exceeds its bound");
            prior = new byte[(int)guard.length()];
            try (DataInputStream input = new DataInputStream(new FileInputStream(guard))) { input.readFully(prior); }
        }
        check(guard.getParentFile().isDirectory() || guard.getParentFile().mkdirs(), "Could not prepare native probe directory");
        try (FileOutputStream file = new FileOutputStream(backup); DataOutputStream output = new DataOutputStream(file)) {
            output.writeInt(Process.myPid());
            output.writeLong(beganAt);
            output.writeInt(prior == null ? -1 : prior.length);
            if (prior != null) output.write(prior);
            output.flush(); file.getFD().sync();
        }
        check(!guard.exists() || guard.delete(), "Could not isolate the native probe marker");
        nativeGuard().begin(Process.myPid(), beganAt);
    }

    private void restoreNativeProbe() throws Exception {
        File backup = nativeProbeBackup();
        if (!backup.exists()) return;
        check(backup.length() >= 16 && backup.length() <= 1040, "Native probe backup exceeds its bound");
        int owner, size;
        long beganAt;
        byte[] prior;
        try (DataInputStream input = new DataInputStream(new FileInputStream(backup))) {
            owner = input.readInt(); beganAt = input.readLong(); size = input.readInt();
            check(owner > 0 && beganAt > 0 && size >= -1 && size <= 1024, "Native probe backup is invalid");
            prior = size < 0 ? null : new byte[size];
            if (prior != null) input.readFully(prior);
            check(input.read() == -1, "Native probe backup has trailing data");
        }
        NativeRuntimeGuard.State current = nativeGuard().state();
        check(current == null || (current.pid == owner && current.beganAt == beganAt),
                "Another native execution owns the guard; refusing to replace it");
        File guard = nativeGuardFile();
        if (prior == null) check(!guard.exists() || guard.delete(), "Native probe guard could not be removed");
        else {
            File temporary = new File(guard.getParentFile(), ".native-probe-restore-" + marker);
            try {
                try (FileOutputStream output = new FileOutputStream(temporary)) {
                    output.write(prior); output.flush(); output.getFD().sync();
                }
                java.nio.file.Files.move(temporary.toPath(), guard.toPath(),
                        java.nio.file.StandardCopyOption.ATOMIC_MOVE, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            } finally { temporary.delete(); }
        }
        check(backup.delete(), "Native probe backup could not be removed");
    }

    private void seedAndNativeCrash() throws Exception {
        AppDiagnostics.initialize(getTargetContext());
        AppDiagnostics.log(getTargetContext(), "INFO", "diagnostic-native-probe", marker + "-durable-before-native-crash");
        check(AppDiagnostics.flush(10000), "Could not flush the native pre-crash journal");
        prepareNativeProbe();
        status("DIAGNOSTICS_EXPECTED_NATIVE_CRASH " + marker + " pid=" + Process.myPid());
        // Deliberate signal in the disposable CI target process; no unsafe JNI or user device calls.
        Os.kill(Process.myPid(), OsConstants.SIGILL);
        SystemClock.sleep(15000);
        throw new AssertionError("The intentional SIGILL did not terminate the process");
    }

    private void verifyNativeTombstoneAndRecovery() throws Exception {
        check(Build.VERSION.SDK_INT >= 31, "Native tombstone export requires Android API 31+");
        check(nativeCrashPid > 0 && nativeCrashPid != Process.myPid(), "Native crash PID is not from a previous process");
        NativeRuntimeGuard.State before = nativeGuard().state();
        check(before != null && before.pid == nativeCrashPid && !before.disabled,
                "The native execution lease did not survive the intentional crash");
        ActivityManager manager = (ActivityManager)getTargetContext().getSystemService(Context.ACTIVITY_SERVICE);
        check(manager != null, "Android process-exit service is unavailable");
        ApplicationExitInfo retained = null;
        long deadline = SystemClock.elapsedRealtime() + 45000;
        while (retained == null && SystemClock.elapsedRealtime() < deadline) {
            for (ApplicationExitInfo exit : manager.getHistoricalProcessExitReasons(
                    getTargetContext().getPackageName(), nativeCrashPid, 32)) {
                if (exit.getPid() != nativeCrashPid || exit.getReason() != ApplicationExitInfo.REASON_CRASH_NATIVE) continue;
                try (InputStream trace = exit.getTraceInputStream()) {
                    if (trace != null && trace.read() >= 0) { retained = exit; break; }
                } catch (IOException pending) { /* debuggerd may still be publishing the tombstone */ }
            }
            if (retained == null) SystemClock.sleep(200);
        }
        check(retained != null, "Android did not retain the exact SIGILL process's native tombstone");
        String saved = report(AppDiagnostics.export(getTargetContext()));
        check(saved.contains(marker + "-durable-before-native-crash"), "Native pre-crash history was lost");
        String exitHeader = "timestampMs=" + retained.getTimestamp() + " reason=CRASH_NATIVE(5)";
        int start = saved.indexOf(exitHeader);
        check(start >= 0, "Export lacks the exact native crash's exit record");
        int end = saved.indexOf("\ntimestampMs=", start);
        if (end < 0) end = saved.indexOf("\n\nPERSISTENT EVENT TRACE", start);
        check(end > start, "Native exit export boundary is missing");
        String nativeTrace = saved.substring(start, end);
        check(nativeTrace.contains("signal=4 (SIGILL)"), "Real binary tombstone signal was not decoded");
        check(java.util.regex.Pattern.compile("(?m)^  #00 rel_pc=0x[0-9a-f]+ (?:[A-Za-z0-9_.+-]+\\.so|app_process(?:32|64)?|linker(?:64)?)")
                        .matcher(nativeTrace).find(), "Real native tombstone has no decoded first frame and native module");
        verifyPrivateDataAbsent(saved);
        pass("An intentional SIGILL in a previous target process exports its actual Android native tombstone as decoded signal 4 and crashing-thread module/relative-PC frames.");
        try (NativePassageTask task = new NativePassageTask(getTargetContext(),
                new File(getTargetContext().getCacheDir(), "unused-native-probe.wav"), UUID.randomUUID().toString())) {
            JSONObject availability = new JSONObject(task.availability());
            check(!availability.getBoolean("available") && "previous-native-crash".equals(availability.optString("reason")),
                    "Production native availability did not select compatibility after the real crash");
        }
        NativeRuntimeGuard.State disabled = nativeGuard().state();
        check(disabled != null && disabled.disabled && disabled.pid == nativeCrashPid,
                "Compatibility selection was not saved for the crashed native runtime");
        try (NativePassageTask task = new NativePassageTask(getTargetContext(),
                new File(getTargetContext().getCacheDir(), "unused-native-probe.wav"), UUID.randomUUID().toString())) {
            check(!new JSONObject(task.availability()).getBoolean("available"), "A new task repeated the known-crashing native runtime");
        }
        restoreNativeProbe();
        pass("Production native availability reconciles the real crash with the durable execution lease and persists compatibility selection across new task instances, without loading JNI; prior guard state is restored after the test.");
    }

    private void verifyNativeExport() throws Exception {
        AppDiagnostics.initialize(getTargetContext());
        JSONObject first = AppDiagnostics.export(getTargetContext());
        String saved = report(first);
        check(saved.contains(marker + "-durable-before-crash"), "Previous-process log history was lost");
        check(saved.contains(marker + "-recorded-error"), "Recorded exception was lost");
        check(saved.contains(marker + "-uncaught-worker-crash"), "Uncaught crash was not persisted");
        check(saved.contains("java.lang.IllegalStateException") && saved.contains("DiagnosticsInstrumentation"),
                "Export is missing the exception type or stack trace");
        verifyPrivateDataAbsent(saved);
        pass("Real uncaught worker crash, exception cause/stack, and prior-session history survive process restart and removal of a cache fixture.");
        JSONObject second = AppDiagnostics.export(getTargetContext());
        report(second);
        check(!first.getString("name").equals(second.getString("name"))
                && !first.getString("uri").equals(second.getString("uri")), "Repeated exports overwrite the previous report");
        try (android.content.res.AssetFileDescriptor earlier = getTargetContext().getContentResolver()
                .openAssetFileDescriptor(Uri.parse(first.getString("uri")), "r")) {
            check(earlier != null, "Earlier export disappeared after a second export");
        }
        pass("Two unique complete UTF-8 .txt logs are visible in Downloads/LightForge and can be read back through MediaStore.");
    }

    private void verifySelectedDocumentExport() throws Exception {
        ContentResolver resolver = getTargetContext().getContentResolver();
        ContentValues values = new ContentValues();
        values.put(MediaStore.Downloads.DISPLAY_NAME, "Custom diagnostic report " + marker + ".txt");
        values.put(MediaStore.Downloads.MIME_TYPE, "text/plain");
        values.put(MediaStore.Downloads.RELATIVE_PATH, "Download/LightForge-test/");
        Uri selected = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
        check(selected != null, "Could not create the selected-document fixture");
        created.add(selected);
        String actualName;
        try (Cursor cursor = resolver.query(selected, new String[]{MediaStore.Downloads.DISPLAY_NAME}, null, null, null)) {
            check(cursor != null && cursor.moveToFirst(), "Selected document metadata is unavailable");
            actualName = cursor.getString(0);
        }
        // The user/provider can choose a name different from ACTION_CREATE_DOCUMENT's suggestion.
        String suggested = "LightForge-diagnostics-20000101-000000-000-1234abcd.txt";
        JSONObject exported = AppDiagnostics.exportTo(getTargetContext(), selected, suggested);
        check(selected.toString().equals(exported.getString("uri")), "Selected-document export changed the destination URI");
        check(actualName.equals(exported.getString("name")),
                "Selected-document export reported its suggestion instead of provider filename: expected="
                        + actualName + "; actual=" + exported.optString("name"));
        check(!suggested.equals(exported.getString("name")), "Custom filename was replaced with the suggested filename");
        check("Selected document location".equals(exported.getString("location")),
                "Selected-document export invented a destination folder: " + exported.optString("location"));
        String saved = readReport(selected, exported.getLong("bytes"));
        check(saved.contains(marker + "-uncaught-worker-crash"), "Selected document is missing the saved crash trace");
        verifyPrivateDataAbsent(saved);
        pass("Selected-URI export helper writes a readable report and returns the provider's custom filename without inventing a destination folder (API 35 helper coverage; no legacy picker UI claim).");
    }

    private void verifyJavascriptExport() throws Exception {
        launch();
        javascript("window.__diagnosticProbeEvents=[];window.__diagnosticProbeOriginal=window.onNativeEvent;"
                + "window.onNativeEvent=function(type,payload){if(type==='diagnosticExported'||type==='diagnosticExportFailed')window.__diagnosticProbeEvents.push({type,payload});return window.__diagnosticProbeOriginal(type,payload);};"
                + "window.__diagnosticProbeError=false;window.__diagnosticProbeRejection=false;"
                + "window.addEventListener('error',function(event){if(String(event.message).includes(" + JSONObject.quote(marker + "-javascript-error") + "))window.__diagnosticProbeError=true;});"
                + "window.addEventListener('unhandledrejection',function(event){if(String(event.reason && event.reason.message).includes(" + JSONObject.quote(marker + "-unhandled-rejection") + "))window.__diagnosticProbeRejection=true;});"
                + "window.LightForgeApp.nav('guide');true");
        // WebView.evaluateJavascript executes an unspecified Chromium script with
        // muted errors. Failures created by that host evaluation can be sanitized
        // or omitted from unhandledrejection. A real document script exercises
        // the same error delivery as the app's own scripts without changing them.
        String failures = "setTimeout(function(){throw new Error("
                + JSONObject.quote(marker + "-javascript-error content://private.music/private-performance.wav") + ");},0);"
                + "Promise.reject(new Error(" + JSONObject.quote(marker + "-unhandled-rejection hidden-relative-project.wav") + "));";
        javascript("(function(){var fixture=document.createElement('script');fixture.textContent="
                + JSONObject.quote(failures) + ";document.head.appendChild(fixture);fixture.remove();return true;})()");
        long captureDeadline = SystemClock.elapsedRealtime() + 10000;
        boolean captured = false;
        while (SystemClock.elapsedRealtime() < captureDeadline) {
            if (Boolean.TRUE.equals(javascript("window.__diagnosticProbeError && window.__diagnosticProbeRejection && !document.getElementById('diagnosticRecovery').hidden"))) { captured = true; break; }
            SystemClock.sleep(100);
        }
        if (!captured) {
            status("DIAGNOSTICS_BROWSER_STATE " + javascript("JSON.stringify({errorDelivered:window.__diagnosticProbeError,rejectionDelivered:window.__diagnosticProbeRejection,recoveryHidden:document.getElementById('diagnosticRecovery').hidden,report:window.LightForgeDiagnostics.report().slice(-65536)})"));
            throw new AssertionError("Both JavaScript failures were not delivered or diagnostic recovery was not offered; see DIAGNOSTICS_BROWSER_STATE");
        }
        javascript("document.querySelector('#guide [data-export-diagnostics]').click();true");
        long deadline = SystemClock.elapsedRealtime() + 30000;
        JSONObject event = null;
        while (SystemClock.elapsedRealtime() < deadline) {
            Object value = javascript("window.__diagnosticProbeEvents.length ? JSON.stringify(window.__diagnosticProbeEvents[0]) : null");
            if (value instanceof String) { event = new JSONObject((String) value); break; }
            SystemClock.sleep(100);
        }
        check(event != null && "diagnosticExported".equals(event.optString("type")), "Diagnostic UI export failed: " + event);
        Object payload = event.get("payload");
        JSONObject result = payload instanceof JSONObject ? (JSONObject) payload : new JSONObject(String.valueOf(payload));
        String saved = report(result);
        check(saved.contains(marker + "-javascript-error") && saved.contains(marker + "-unhandled-rejection"),
                "JavaScript error or unhandled-rejection trace missing from exported file");
        verifyPrivateDataAbsent(saved);
        check(Boolean.TRUE.equals(javascript("Array.from(document.querySelectorAll('#guide [data-diagnostic-status]')).some(function(el){return !el.hidden && /saved/i.test(el.textContent);})")),
                "Successful native export was not shown in the Guide");
        pass("Production Guide button exports captured JavaScript errors and unhandled rejections through the bridge and reports successful saving.");
    }

    private void verifyDetachedRendererRecovery() throws Exception {
        Set<Uri> before = downloads();
        WebView web = (WebView) field(activity, "web");
        AtomicReference<WebViewClient> client = new AtomicReference<>();
        RenderProcessGoneDetail detail = new RenderProcessGoneDetail() {
            @Override public boolean didCrash() { return true; }
            @Override public int rendererPriorityAtExit() { return WebView.RENDERER_PRIORITY_IMPORTANT; }
        };
        main(() -> {
            client.set(web.getWebViewClient());
            check(web.getParent() instanceof ViewGroup, "Preview was not attached before the test");
            ((ViewGroup) web.getParent()).removeView(web);
            check(web.getParent() == null, "Preview did not detach");
            check(client.get().onRenderProcessGone(web, detail), "Renderer crash callback was not handled");
            check(client.get().onRenderProcessGone(web, detail), "Repeated stale renderer callback was not handled");
        });
        check(field(activity, "web") == null, "Dead renderer remains the active preview");
        AlertDialog dialog = (AlertDialog) field(activity, "previewRecoveryDialog");
        check(dialog != null, "Native recovery dialog missing after renderer loss");
        main(() -> {
            check(dialog.isShowing(), "Native recovery dialog is hidden");
            check(dialog.getButton(AlertDialog.BUTTON_NEUTRAL) != null, "Native recovery has no log export button");
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).performClick();
        });
        Uri exported = null;
        boolean complete = false;
        long deadline = SystemClock.elapsedRealtime() + 30000;
        while (SystemClock.elapsedRealtime() < deadline) {
            Set<Uri> after = downloads();
            after.removeAll(before);
            if (!after.isEmpty()) {
                check(after.size() == 1, "Recovery click produced duplicate diagnostic files");
                exported = after.iterator().next();
                created.add(exported);
                try (Cursor cursor = getTargetContext().getContentResolver().query(exported,
                        new String[]{MediaStore.Downloads.IS_PENDING}, null, null, null)) {
                    if (cursor != null && cursor.moveToFirst() && cursor.getInt(0) == 0) { complete = true; break; }
                }
            }
            SystemClock.sleep(100);
        }
        check(exported != null && complete, "Native renderer recovery could not finish exporting diagnostics");
        String text;
        try (InputStream in = getTargetContext().getContentResolver().openInputStream(exported);
             ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int count;
            while ((count = in.read(buffer)) != -1) {
                check(out.size() + count <= 2 * 1024 * 1024, "Recovery export is unbounded");
                out.write(buffer, 0, count);
            }
            text = new String(out.toByteArray(), StandardCharsets.UTF_8);
        }
        check(text.contains("preview-renderer") && text.contains("Preview renderer crashed"),
                "Native fallback report lacks renderer crash details");
        verifyPrivateDataAbsent(text);
        main(() -> check(dialog.isShowing(), "Saving diagnostics dismissed the recovery choices"));
        pass("Already-detached and repeated stale renderer callbacks do not crash; the native recovery dialog exports the crash log with no live WebView.");
    }

    @Override public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        mode = arguments == null ? "verify" : arguments.getString("mode", "verify");
        marker = arguments == null ? "missing" : arguments.getString("marker", "missing");
        nativeCrashPid = arguments == null ? 0 : Integer.parseInt(arguments.getString("nativePid", "0"));
        start();
    }

    @Override public void onStart() {
        JSONObject receipt = new JSONObject();
        Bundle output = new Bundle();
        boolean passed = false;
        try {
            check(Build.VERSION.SDK_INT >= 29, "This diagnostic Downloads test requires Android API 29+");
            check(marker.matches("probe[0-9]{10,20}"), "Invalid unique test marker");
            if ("crash".equals(mode)) { seedAndCrash(); return; }
            if ("native-crash".equals(mode)) { seedAndNativeCrash(); return; }
            check("verify".equals(mode) || "cleanup".equals(mode), "Unsupported diagnostic test mode");
            if ("cleanup".equals(mode)) {
                restoreNativeProbe();
                pass("Native diagnostic probe cleanup completed.");
            } else {
                verifyNoStoragePermission();
                verifyNativeTombstoneAndRecovery();
                verifyNativeExport();
                verifySelectedDocumentExport();
                verifyJavascriptExport();
                verifyDetachedRendererRecovery();
            }
            receipt.put("passed", true).put("checks", checks).put("androidSdk", Build.VERSION.SDK_INT)
                    .put("device", Build.MODEL).put("pid", Process.myPid()).put("marker", marker)
                    .put("mode", mode).put("nativeCrashPid", nativeCrashPid);
            passed = true;
        } catch (Throwable error) {
            try { receipt.put("passed", false).put("checks", checks).put("error", error.toString()); } catch (Exception ignored) { }
            java.io.StringWriter trace = new java.io.StringWriter();
            error.printStackTrace(new java.io.PrintWriter(trace));
            status(trace.toString());
        } finally {
            // Also runs after ordinary test failures. SIGILL itself bypasses finally; the Python
            // driver always invokes the cleanup mode in a fresh process for that case.
            if (marker != null && marker.matches("probe[0-9]{10,20}")) {
                try { restoreNativeProbe(); }
                catch (Exception error) {
                    passed = false;
                    try { receipt.put("passed", false).put("cleanupError", error.toString()); } catch (Exception ignored) { }
                }
            }
            // Remove only files this instrumentation created; leave app projects and history intact.
            for (Uri uri : created) {
                try { getTargetContext().getContentResolver().delete(uri, null, null); } catch (Exception ignored) { }
            }
            if (activity != null) {
                try { main(() -> activity.finishAndRemoveTask()); } catch (Exception ignored) { }
            }
        }
        output.putString("stream", "DIAGNOSTICS_ANDROID_RESULT " + receipt + "\n"
                + (passed ? "DIAGNOSTICS_ANDROID_PASS\n" : "DIAGNOSTICS_ANDROID_FAIL\n"));
        finish(passed ? -1 : 0, output);
    }
}
