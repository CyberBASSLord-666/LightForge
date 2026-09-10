package com.cyberbasslord.lightforge;

import android.app.ActivityManager;
import android.app.Instrumentation;
import android.content.Context;
import android.content.ContextWrapper;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.os.Build;
import android.os.Bundle;
import android.os.SystemClock;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONArray;
import org.json.JSONObject;

/** Separate diagnostic APK: exact serial/pool GAME outputs in one real app WebView. */
public final class GamePoolProbe extends Instrumentation {
    private static final String ORIGIN = "https://appassets.androidplatform.net";
    private MainActivity activity;
    private WebView web;
    private File files;
    private String projectId, jobId, version;
    private AnalysisService probeService;
    private AnalysisService.JobBridge bridge;
    private final JSONArray memory = new JSONArray();
    private final JSONArray admissions = new JSONArray();
    private long began, lastStatus;
    private String phase = "setup";

    private void check(boolean value, String label) { if (!value) throw new AssertionError(label); }
    private Object field(Object owner, String name) throws Exception {
        Field field = owner.getClass().getDeclaredField(name); field.setAccessible(true); return field.get(owner);
    }
    private void set(Object owner, String name, Object value) throws Exception {
        Field field = owner.getClass().getDeclaredField(name); field.setAccessible(true); field.set(owner, value);
    }
    private byte[] read(InputStream source) throws Exception {
        try (InputStream input = source; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] bytes = new byte[8192]; int count;
            while ((count = input.read(bytes)) >= 0) output.write(bytes, 0, count);
            return output.toByteArray();
        }
    }
    private String sha(byte[] bytes) throws Exception {
        StringBuilder result = new StringBuilder();
        for (byte value : MessageDigest.getInstance("SHA-256").digest(bytes)) result.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
        return result.toString();
    }
    private String evaluate(String script) throws Exception {
        AtomicReference<String> value = new AtomicReference<>(); CountDownLatch done = new CountDownLatch(1);
        runOnMainSync(() -> web.evaluateJavascript(script, result -> { value.set(result); done.countDown(); }));
        check(done.await(20, TimeUnit.SECONDS), "WebView evaluation timed out during " + phase);
        return value.get();
    }
    private ActivityManager.MemoryInfo memory() throws Exception {
        ActivityManager manager = (ActivityManager) getTargetContext().getSystemService(Context.ACTIVITY_SERVICE);
        ActivityManager.MemoryInfo value = new ActivityManager.MemoryInfo(); manager.getMemoryInfo(value);
        JSONObject sample = new JSONObject().put("phase", phase).put("elapsedSeconds", (SystemClock.elapsedRealtime() - began) / 1000.0)
            .put("totalBytes", value.totalMem).put("availableBytes", value.availMem).put("thresholdBytes", value.threshold).put("lowMemory", value.lowMemory);
        memory.put(sample);
        long now = SystemClock.elapsedRealtime();
        if (now - lastStatus >= 15000) {
            lastStatus = now;
            Bundle status = new Bundle(); status.putString("stream", "GAME_POOL_PROGRESS " + sample + "\n"); sendStatus(0, status);
        }
        check(!value.lowMemory, "Android entered low-memory state during the pool qualification");
        return value;
    }
    private void prepareJob() throws Exception {
        JSONObject job = AnalysisJobStore.prepare(files, projectId, version); jobId = job.getString("id");
        // Invoke the actual production JobBridge against the device Context and
        // durable job store. No foreground service/model work is started here.
        probeService = new AnalysisService();
        Method attach = ContextWrapper.class.getDeclaredMethod("attachBaseContext", Context.class); attach.setAccessible(true); attach.invoke(probeService, getTargetContext());
        set(probeService, "jobId", jobId);
        bridge = probeService.new JobBridge(jobId, null, null);
    }
    private JSONObject admission(int expected) throws Exception {
        if (expected == 2) {
            long until = SystemClock.elapsedRealtime() + 45000;
            while (memory().availMem < 4L * 1024 * 1024 * 1024 && SystemClock.elapsedRealtime() < until) SystemClock.sleep(1000);
        }
        JSONObject result = new JSONObject(bridge.gameParallelism(jobId));
        admissions.put(new JSONObject(result.toString()).put("phase", phase));
        check(!result.has("error") && result.getInt("parallelism") == expected, "Fresh production admission did not return " + expected + ": " + result);
        check(AnalysisJobStore.status(files).optBoolean("gameParallelActive") == (expected == 2), "Durable pool lease differs from admitted lane count");
        return result;
    }
    private void releaseLease() throws Exception {
        JSONObject result = new JSONObject(bridge.gameParallelRelease(jobId));
        check(!result.has("error") && !AnalysisJobStore.status(files).optBoolean("gameParallelActive"), "Production pool lease was not released");
    }
    private JSONObject runWorker(String mode, int parallelism) throws Exception {
        phase = mode; memory();
        JSONObject request = new JSONObject().put("mode", mode).put("parallelism", parallelism).put("nonce", Long.toString(began));
        evaluate("(() => { window.__gamePoolReports = window.__gamePoolReports || {}; window.__gamePoolProgress = null; const worker = new Worker('/analysis/__game_pool_probe__.js'); window.__gamePoolWorker = worker; worker.onmessage = event => { const value=event.data; if(value.type==='game-pool-result') window.__gamePoolReports['" + mode + "']=value.result; else if(value.type==='pool-probe-progress') window.__gamePoolProgress=value; }; worker.onerror = event => { window.__gamePoolReports['" + mode + "']={passed:false,error:String(event.message)}; }; worker.postMessage(" + request + "); })()");
        long until = SystemClock.elapsedRealtime() + 11 * 60 * 1000;
        JSONObject report = null;
        while (SystemClock.elapsedRealtime() < until) {
            memory();
            String value = evaluate("window.__gamePoolReports['" + mode + "'] || null");
            if (value != null && !"null".equals(value)) { report = new JSONObject(value); break; }
            SystemClock.sleep(1000);
        }
        evaluate("window.__gamePoolWorker && window.__gamePoolWorker.terminate(); window.__gamePoolWorker=null;");
        check(report != null, "GAME mode exceeded its eleven-minute limit: " + mode);
        check(report.optBoolean("passed"), "GAME mode failed: " + mode + ": " + report);
        check(report.optInt("effectiveThreads") == 1 && report.optBoolean("checkpointNamespaceRemoved"), "GAME runtime threads or checkpoint cleanup differed");
        Bundle status = new Bundle(); status.putString("stream", "GAME_POOL_PHASE " + new JSONObject().put("mode", mode).put("seconds", report.getDouble("seconds")) + "\n"); sendStatus(0, status);
        return report;
    }
    private void verifyPair(JSONObject serial, JSONObject parallel) throws Exception {
        check(serial.getJSONArray("records").length() == 24 && parallel.getJSONArray("records").length() == 24, "Each mode must retain every output from twelve graphs per passage, including all eight segmenter steps");
        check(serial.getString("rawOutputsSha256").equals(parallel.getString("rawOutputsSha256")), "Raw graph output bits differ between serial and parallel GAME");
        check(serial.getString("transcriptionJson").equals(parallel.getString("transcriptionJson")), "Final GAME transcription JSON differs");
        for (String key : new String[]{"game-0-0", "game-0-1"}) {
            JSONObject a = serial.getJSONObject("checkpoints").getJSONObject(key), b = parallel.getJSONObject("checkpoints").getJSONObject(key);
            check(a.getString("json").equals(b.getString("json")) && a.getString("sha256").equals(b.getString("sha256")), "Unrounded durable checkpoint differs: " + key);
        }
        check(serial.getJSONObject("checkpoints").length() == 2 && parallel.getJSONObject("checkpoints").length() == 2
            && serial.getJSONArray("writes").length() == 2 && parallel.getJSONArray("writes").length() == 2, "Each source passage must commit exactly once");
        JSONObject child = parallel.getJSONArray("children").getJSONObject(0);
        check(parallel.getJSONArray("children").length() == 1 && child.getInt("inferRequests") == 1 && child.getInt("results") == 1 && child.getBoolean("terminated"), "Completed child lifecycle evidence missing");
        check(parallel.getBoolean("concurrentGraphCalls") && parallel.getJSONArray("executions").length() == 24, "Actual model-call overlap evidence missing");
        check(serial.getJSONArray("children").length() == 0, "Serial reference created a child");
        check("true".equals(evaluate("(() => { const r=window.__gamePoolReports; const n=r.parallel.transcription.notes; return n.every((v,i)=>!i||v.start>=n[i-1].end-1e-6) && JSON.stringify(r.serial.reads)===JSON.stringify(r.parallel.reads); })()")), "Source PCM reads or final source ordering differ");
    }
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }
    @Override public void onStart() {
        began = SystemClock.elapsedRealtime(); JSONObject receipt = new JSONObject(); boolean passed = false;
        try {
            files = getTargetContext().getFilesDir();
            version = getTargetContext().getPackageManager().getPackageInfo(getTargetContext().getPackageName(), 0).versionName;
            byte[] script = read(getContext().getAssets().open("game-pool-probe.js"));
            activity = (MainActivity) startActivitySync(new Intent(getTargetContext(), MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK));
            web = (WebView) field(activity, "web"); check(web != null, "App WebView missing");
            long until = SystemClock.elapsedRealtime() + 45000;
            while (SystemClock.elapsedRealtime() < until && !"true".equals(evaluate("location.origin==='" + ORIGIN + "' && document.readyState!=='loading'"))) SystemClock.sleep(200);
            check("true".equals(evaluate("location.origin==='" + ORIGIN + "' && document.readyState!=='loading'")), "Production document did not load");
            runOnMainSync(() -> {
                WebViewClient production = web.getWebViewClient();
                web.setWebViewClient(new WebViewClient() {
                    @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                        String path = request.getUrl().getPath();
                        if (ORIGIN.equals(request.getUrl().getScheme() + "://" + request.getUrl().getAuthority()) && ("/analysis/__game_pool_probe__.js".equals(path) || "/analysis/__game_pool_child__.js".equals(path)))
                            return AppResources.response(200, "OK", "application/javascript", new ByteArrayInputStream(script), script.length, null);
                        return production.shouldInterceptRequest(view, request);
                    }
                    @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) { return production.shouldOverrideUrlLoading(view, request); }
                });
            });
            receipt.put("document", new JSONObject(evaluate("({location:location.href,crossOriginIsolated:crossOriginIsolated===true,sharedArrayBuffer:typeof SharedArrayBuffer==='function',hardwareConcurrency:navigator.hardwareConcurrency,userAgent:navigator.userAgent})")));
            JSONObject sourceHashes = new JSONObject();
            for (String name : new String[]{"analysis/game.js", "analysis/game-worker.js", "analysis/wav-reader.js", "analysis/work-store.js", "analysis/vendor/ort.wasm.min.js", "analysis/models/game/manifest.json", "demo/glass-castle.wav"})
                sourceHashes.put("web/" + name, sha(read(getTargetContext().getAssets().open(name))));
            receipt.put("sourceHashes", sourceHashes).put("probeScriptSha256", sha(script));
            JSONObject project;
            try (InputStream source = getTargetContext().getAssets().open("demo/glass-castle.wav")) {
                project = ProjectStore.importAudio(new File(files, "projects"), source, "GAME pool diagnostic", new AudioImporter.Progress() { public void update(double value, String text) {} public void check() {} });
            }
            projectId = project.getString("id"); prepareJob();
            phase = "initial-admission"; admission(2); releaseLease();
            JSONObject serial = runWorker("serial", 1); receipt.put("serial", serial);
            phase = "parallel-admission"; admission(2);
            JSONObject parallel = runWorker("parallel", 2); receipt.put("parallel", parallel); releaseLease();
            verifyPair(serial, parallel); receipt.put("exact", true);
            phase = "cancel-admission"; admission(2);
            JSONObject cancelled = runWorker("cancel", 2); receipt.put("cancel", cancelled);
            check(cancelled.optBoolean("aborted") && cancelled.getJSONObject("cancellation").getBoolean("released")
                && cancelled.getJSONArray("children").getJSONObject(0).getBoolean("terminated") && cancelled.getJSONArray("writes").length() == 0, "Active cancellation left child work or checkpoints");
            AnalysisJobStore.finish(files, jobId, "cancelled", "Diagnostic cancellation"); prepareJob();
            check(!AnalysisJobStore.status(files).optBoolean("gameParallelDisabled"), "Explicit cancellation was incorrectly recorded as a pool crash");
            phase = "interrupted-lease-simulation"; admission(2);
            AnalysisJobStore.recover(files); prepareJob();
            check(AnalysisJobStore.status(files).getBoolean("gameParallelDisabled"), "An interrupted active lease did not disable repeat pooling");
            phase = "guarded-restart-admission"; admission(1);
            JSONObject restart = runWorker("restart", 1); receipt.put("restart", restart);
            check(restart.getJSONArray("records").length() == 12 && restart.getJSONArray("children").length() == 0, "Guarded restart did not execute one full serial passage");
            check("true".equals(evaluate("(() => { const r=window.__gamePoolReports; const first=r.serial.checkpoints['game-0-0'].value.notes; const sort=a=>a.slice().sort((x,y)=>JSON.stringify([x.pcm,x.graph,x.ordinal]).localeCompare(JSON.stringify([y.pcm,y.graph,y.ordinal]))); const pcm=r.restart.reads[0].sha256; return JSON.stringify(first)===JSON.stringify(r.restart.restartedNotes) && JSON.stringify(sort(r.serial.records.filter(x=>x.pcm===pcm)))===JSON.stringify(sort(r.restart.records)); })()")), "Guarded serial restart changed raw outputs or unrounded notes");
            receipt.put("guardedRestartExact", true).put("simulatedInterruptedLease", true).put("childrenVerified", true);
            receipt.put("instrumentedSerialSeconds", serial.getDouble("seconds")).put("instrumentedParallelSeconds", parallel.getDouble("seconds"));
            PackageInfo webview = WebView.getCurrentWebViewPackage();
            receipt.put("webViewVersion", webview == null ? JSONObject.NULL : webview.versionName).put("androidSdk", Build.VERSION.SDK_INT).put("device", Build.MODEL);
            passed = true;
        } catch (Throwable error) {
            try { receipt.put("error", android.util.Log.getStackTraceString(error)); } catch (Exception ignored) {}
        } finally {
            try { if (web != null) evaluate("window.__gamePoolWorker && window.__gamePoolWorker.terminate()"); } catch (Exception ignored) {}
            try { if (jobId != null) AnalysisJobStore.finish(files, jobId, "cancelled", "Diagnostic cleanup"); } catch (Exception ignored) {}
            if (activity != null) runOnMainSync(() -> activity.finishAndRemoveTask());
        }
        try { receipt.put("passed", passed).put("diagnosticOnly", true).put("memory", memory).put("admissions", admissions)
            .put("scope", "API 35 emulator, one actual app WebView and two independent one-thread WASM workers; 24 seconds of real stereo demo averaged to mono. All raw graph-output bytes, unrounded durable checkpoints and final notes compared exactly. Timings include tracing and are not physical-phone performance. Interrupted lease is simulated; explicit cancellation uses the real engine release path."); } catch (Exception ignored) {}
        Bundle output = new Bundle(); output.putString("stream", "GAME_POOL_RESULT " + receipt + "\n" + (passed ? "GAME_POOL_PASS\n" : "GAME_POOL_FAIL\n"));
        finish(passed ? -1 : 1, output);
    }
}
