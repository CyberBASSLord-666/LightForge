package com.cyberbasslord.lightforge;

import android.app.AlertDialog;
import android.app.Instrumentation;
import android.content.ContentResolver;
import android.content.ContentUris;
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
import java.io.IOException;
import java.io.InputStream;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Separate same-signed test APK; exercises the production app and Android Downloads provider. */
public final class DiagnosticsInstrumentation extends Instrumentation {
    private final JSONArray checks = new JSONArray();
    private final Set<Uri> created = new HashSet<>();
    private MainActivity activity;
    private String mode, marker;

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
        check(name.startsWith("LightForge-diagnostics-") && name.endsWith(".log"), "Unexpected export filename");
        ContentResolver resolver = getTargetContext().getContentResolver();
        try (Cursor cursor = resolver.query(uri, new String[]{MediaStore.Downloads.DISPLAY_NAME,
                MediaStore.Downloads.RELATIVE_PATH, MediaStore.Downloads.MIME_TYPE,
                MediaStore.Downloads.IS_PENDING, MediaStore.Downloads.SIZE}, null, null, null)) {
            check(cursor != null && cursor.moveToFirst(), "Export missing from Downloads provider");
            check(name.equals(cursor.getString(0)), "Export metadata filename does not match its file");
            check("Download/LightForge/".equals(cursor.getString(1)), "Log is not in Downloads/LightForge");
            check("text/plain".equals(cursor.getString(2)), "Diagnostic log is not readable plain text");
            check(cursor.getInt(3) == 0, "Diagnostic export left an unfinished pending file");
            check(cursor.getLong(4) == result.getLong("bytes"), "Export byte count does not match Downloads");
        }
        try (InputStream in = resolver.openInputStream(uri); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            check(in != null, "Export cannot be reopened");
            byte[] bytes = new byte[8192];
            int count;
            while ((count = in.read(bytes)) != -1) {
                check(out.size() + count <= 2 * 1024 * 1024, "Export exceeds its bounded report size");
                out.write(bytes, 0, count);
            }
            check(out.size() == result.getLong("bytes"), "Written report is incomplete");
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
                new String[]{"Download/LightForge/", "LightForge-diagnostics-%.log"}, null)) {
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
        pass("Two unique complete UTF-8 .log files are visible in Downloads/LightForge and can be read back through MediaStore.");
    }

    private void verifyJavascriptExport() throws Exception {
        launch();
        javascript("window.__diagnosticProbeEvents=[];window.__diagnosticProbeOriginal=window.onNativeEvent;"
                + "window.onNativeEvent=function(type,payload){if(type==='diagnosticExported'||type==='diagnosticExportFailed')window.__diagnosticProbeEvents.push({type,payload});return window.__diagnosticProbeOriginal(type,payload);};"
                + "window.LightForgeApp.nav('guide');true");
        javascript("setTimeout(function(){throw new Error(" + JSONObject.quote(marker + "-javascript-error content://private.music/private-performance.wav") + ");},0);"
                + "Promise.reject(new Error(" + JSONObject.quote(marker + "-unhandled-rejection hidden-relative-project.wav") + "));true");
        long captureDeadline = SystemClock.elapsedRealtime() + 10000;
        boolean captured = false;
        while (SystemClock.elapsedRealtime() < captureDeadline) {
            if (Boolean.TRUE.equals(javascript("!document.getElementById('diagnosticRecovery').hidden"))) { captured = true; break; }
            SystemClock.sleep(100);
        }
        check(captured, "Captured JavaScript error did not offer diagnostic recovery");
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
            check("verify".equals(mode), "Unsupported diagnostic test mode");
            verifyNoStoragePermission();
            verifyNativeExport();
            verifyJavascriptExport();
            verifyDetachedRendererRecovery();
            receipt.put("passed", true).put("checks", checks).put("androidSdk", Build.VERSION.SDK_INT)
                    .put("device", Build.MODEL).put("pid", Process.myPid()).put("marker", marker);
            passed = true;
        } catch (Throwable error) {
            try { receipt.put("passed", false).put("checks", checks).put("error", error.toString()); } catch (Exception ignored) { }
            java.io.StringWriter trace = new java.io.StringWriter();
            error.printStackTrace(new java.io.PrintWriter(trace));
            status(trace.toString());
        } finally {
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
