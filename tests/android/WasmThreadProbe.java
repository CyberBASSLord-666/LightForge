package com.cyberbasslord.lightforge;

import android.app.ActivityManager;
import android.app.Instrumentation;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.SystemClock;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import androidx.webkit.Profile;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.lang.reflect.Field;
import java.security.MessageDigest;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONArray;
import org.json.JSONObject;

/** Separate diagnostic APK, using the real app WebView and packaged production engines. */
public final class WasmThreadProbe extends Instrumentation {
    private static final String ORIGIN = "https://appassets.androidplatform.net";
    private static final String PCM_SHA = "5cfb46f063a2263e56c54d176841e0f6b1cfb69feb894896ef6875c697e3de22";
    private MainActivity activity;
    private WebView web;
    private String mode, phase = "setup";
    private long began, lastStatus;
    private final JSONArray memory = new JSONArray();
    private volatile JSONObject workerHeaders;

    private void check(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
    private byte[] read(InputStream source) throws Exception {
        try (InputStream input = source; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] block = new byte[8192]; int count;
            while ((count = input.read(block)) >= 0) output.write(block, 0, count);
            return output.toByteArray();
        }
    }
    private String sha(InputStream source) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = source) { byte[] block = new byte[65536]; int count; while ((count = input.read(block)) >= 0) digest.update(block, 0, count); }
        StringBuilder text = new StringBuilder();
        for (byte value : digest.digest()) text.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
        return text.toString();
    }
    private String evaluate(String script) throws Exception {
        AtomicReference<String> value = new AtomicReference<>(); CountDownLatch done = new CountDownLatch(1);
        runOnMainSync(() -> web.evaluateJavascript(script, result -> { value.set(result); done.countDown(); }));
        check(done.await(20, TimeUnit.SECONDS), "WebView evaluation timed out during " + phase); return value.get();
    }
    private void sampleMemory() throws Exception {
        ActivityManager.MemoryInfo info = new ActivityManager.MemoryInfo();
        ((ActivityManager) getTargetContext().getSystemService(Context.ACTIVITY_SERVICE)).getMemoryInfo(info);
        JSONObject sample = new JSONObject().put("phase", phase).put("elapsedSeconds", (SystemClock.elapsedRealtime() - began) / 1000.0)
            .put("totalBytes", info.totalMem).put("availableBytes", info.availMem).put("thresholdBytes", info.threshold).put("lowMemory", info.lowMemory);
        memory.put(sample);
        long now = SystemClock.elapsedRealtime();
        if (now - lastStatus >= 15000) { lastStatus = now; Bundle status = new Bundle(); status.putString("stream", "WASM_THREAD_PROGRESS " + sample + "\n"); sendStatus(0, status); }
        check(!info.lowMemory, "Android entered low-memory state during qualification");
    }
    private JSONObject awaitObject(String expression, long milliseconds) throws Exception {
        long until = SystemClock.elapsedRealtime() + milliseconds;
        while (SystemClock.elapsedRealtime() < until) {
            sampleMemory(); String value = evaluate(expression);
            if (value != null && !"null".equals(value)) return new JSONObject(value);
            SystemClock.sleep(500);
        }
        throw new AssertionError("Missing bounded diagnostic result during " + phase);
    }
    private JSONObject storage(boolean create) throws Exception {
        evaluate("window.__wtStorage=null; (async()=>{try{"
            + "const token='lightforge-default-profile-wasm-thread-proof-v1'; const root=await navigator.storage.getDirectory();"
            + "const file=await root.getFileHandle('wasm-thread-retention.txt',{create:" + create + "});"
            + (create ? "const stream=await file.createWritable();await stream.write(token);await stream.close();" : "")
            + "const opfs=await(await file.getFile()).text();const db=await new Promise((resolve,reject)=>{const r=indexedDB.open('lightforge-wasm-thread-retention',1);r.onupgradeneeded=()=>r.result.createObjectStore('proof');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});"
            + (create ? "await new Promise((resolve,reject)=>{const tx=db.transaction('proof','readwrite');tx.objectStore('proof').put(token,'token');tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});" : "")
            + "const indexed=await new Promise((resolve,reject)=>{const r=db.transaction('proof').objectStore('proof').get('token');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});db.close();"
            + "window.__wtStorage={passed:opfs===token&&indexed===token,opfs,indexedDB:indexed,retained:" + !create + "};"
            + "}catch(error){window.__wtStorage={passed:false,error:String(error.stack||error)};}})()");
        JSONObject result = awaitObject("window.__wtStorage || null", 30000);
        check(result.optBoolean("passed"), "Default-profile data was not retained: " + result); return result;
    }
    private JSONObject worker(String workerMode, int threads) throws Exception {
        phase = workerMode;
        JSONObject request = new JSONObject().put("mode", workerMode).put("expectedThreads", threads).put("fixtureSha256", PCM_SHA).put("nonce", mode + "-" + began);
        evaluate("(() => { window.__wtReports=window.__wtReports||{};window.__wtCancel=null; const worker=new Worker('/analysis/__wasm_thread_probe__.js');window.__wtWorker=worker;"
            + "worker.onmessage=event=>{const value=event.data;if(value.type==='wasm-thread-result')window.__wtReports['" + workerMode + "']=value.result;"
            + "else if(value.type==='wasm-thread-active'){window.__wtCancel={active:value.result,terminated:false};setTimeout(()=>{worker.terminate();window.__wtWorker=null;window.__wtCancel.terminated=true;},25);}};"
            + "worker.onerror=event=>{window.__wtReports['" + workerMode + "']={passed:false,error:String(event.message)};};worker.postMessage(" + request + ");})()");
        if ("cancel".equals(workerMode)) {
            JSONObject cancellation = awaitObject("window.__wtCancel && window.__wtCancel.terminated ? window.__wtCancel : null", 8 * 60 * 1000);
            SystemClock.sleep(1000);
            check("true".equals(evaluate("!window.__wtReports.cancel && !window.__wtWorker")), "A terminated neural worker completed or remained owned");
            JSONObject active = cancellation.getJSONObject("active");
            check(active.getInt("effectiveThreads") == 4 && active.getJSONArray("pthreadWorkers").length() == 3 && "encoder".equals(active.getString("graph")), "Cancellation lacked a loaded threaded runtime and active encoder call");
            String key = active.getString("checkpointKey"); check(key.matches("[a-f0-9]{64}"), "Cancellation checkpoint identity is invalid");
            evaluate("window.__wtCancelCleanup=null;(async()=>{try{const store=await LightForgeAnalysisStore.open('" + key + "',{sourceId:'wasm-thread-probe'});const absent=await store.read('game-0-0')===null;await LightForgeAnalysisStore.discard('" + key + "');window.__wtCancelCleanup={passed:absent,checkpointAbsent:absent,namespaceRemoved:true};}catch(error){window.__wtCancelCleanup={passed:false,error:String(error)};}})()");
            JSONObject cleanup = awaitObject("window.__wtCancelCleanup || null", 30000);
            check(cleanup.optBoolean("passed"), "Cancelled inference left a completed passage or failed cleanup");
            cancellation.put("passed", true).put("noCompletionAfterTermination", true).put("cleanup", cleanup);
            return cancellation;
        }
        JSONObject result = awaitObject("window.__wtReports['" + workerMode + "'] || null", 8 * 60 * 1000);
        evaluate("window.__wtWorker.terminate();window.__wtWorker=null;"); result.put("parentWorkerTerminated", true);
        check(result.optBoolean("passed") && result.optBoolean("identityExact") && result.optBoolean("checkpointNamespaceRemoved"), "Worker proof failed: " + result);
        check(result.getInt("effectiveThreads") == threads, "Effective runtime thread count differs");
        return result;
    }
    private JSONObject profile() throws Exception {
        AtomicReference<JSONObject> result = new AtomicReference<>(); AtomicReference<Throwable> error = new AtomicReference<>();
        runOnMainSync(() -> { try {
            boolean supported = WebViewFeature.isFeatureSupported(WebViewFeature.MULTI_PROFILE);
            boolean allowlist = WebViewFeature.isFeatureSupported(WebViewFeature.CROSS_ORIGIN_ISOLATED_ALLOWLIST);
            JSONObject value = new JSONObject().put("supported", supported).put("allowlistSupported", allowlist)
                .put("configureResult", WebViewIsolation.configure(web)).put("defaultName", Profile.DEFAULT_PROFILE_NAME);
            if (supported) { Profile profile = WebViewCompat.getProfile(web); value.put("name", profile.getName()); if (allowlist) value.put("allowlist", new JSONArray(profile.getCrossOriginIsolatedAllowlist())); }
            result.set(value);
        } catch (Throwable failure) { error.set(failure); } });
        check(error.get() == null, "Public profile API failed: " + error.get()); return result.get();
    }
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); mode = arguments == null ? "" : arguments.getString("mode", ""); start(); }
    @Override public void onStart() {
        began = SystemClock.elapsedRealtime(); JSONObject receipt = new JSONObject(); boolean passed = false;
        try {
            check("stock".equals(mode) || "modern".equals(mode), "Expected stock or modern phase");
            byte[] script = read(getContext().getAssets().open("wasm-thread-probe.js"));
            byte[] pcm = read(getContext().getAssets().open("falcon-mdx-3s.float32le"));
            check(pcm.length == 529200 && PCM_SHA.equals(sha(new ByteArrayInputStream(pcm))), "Diagnostic PCM differs from the pinned three-second separated fixture");
            activity = (MainActivity) startActivitySync(new Intent(getTargetContext(), MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK));
            Field field = MainActivity.class.getDeclaredField("web"); field.setAccessible(true); web = (WebView) field.get(activity); check(web != null, "Actual Activity WebView missing");
            long until = SystemClock.elapsedRealtime() + 45000;
            while (SystemClock.elapsedRealtime() < until && !"true".equals(evaluate("location.origin==='" + ORIGIN + "' && document.readyState!=='loading'"))) SystemClock.sleep(200);
            check("true".equals(evaluate("location.origin==='" + ORIGIN + "' && document.readyState!=='loading'")), "Production document did not load");
            runOnMainSync(() -> {
                WebViewClient production = web.getWebViewClient();
                web.setWebViewClient(new WebViewClient() {
                    @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                        String path = request.getUrl().getPath();
                        if (WebViewIsolation.isTrustedOrigin(request.getUrl())) {
                            if ("/analysis/__wasm_thread_probe__.js".equals(path)) {
                                WebResourceResponse response = AppResources.response(200, "OK", "application/javascript", new ByteArrayInputStream(script), script.length, null);
                                workerHeaders = new JSONObject(response.getResponseHeaders()); return response;
                            }
                            if ("/analysis/__wasm_thread_pcm__.f32".equals(path)) return AppResources.response(200, "OK", "application/octet-stream", new ByteArrayInputStream(pcm), pcm.length, null);
                        }
                        return production.shouldInterceptRequest(view, request);
                    }
                    @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) { return production.shouldOverrideUrlLoading(view, request); }
                });
            });
            JSONObject predicates = new JSONObject();
            for (String value : new String[]{ORIGIN, ORIGIN + "/index.html?x=1", "http://appassets.androidplatform.net", "https://example.com", "https://user@appassets.androidplatform.net", "https://appassets.androidplatform.net:443", "https://appassets.androidplatform.net.evil.example"}) {
                boolean actual = WebViewIsolation.isTrustedOrigin(Uri.parse(value)); predicates.put(value, actual); check(actual == (value.equals(ORIGIN) || value.startsWith(ORIGIN + "/")), "Trusted-origin predicate admitted an unexpected authority");
            }
            check(!WebViewIsolation.isTrustedOrigin(null), "Null origin was trusted"); predicates.put("null", false); receipt.put("originPredicates", predicates);
            JSONObject document = new JSONObject(evaluate("({location:location.href,crossOriginIsolated:crossOriginIsolated===true,sharedArrayBuffer:typeof SharedArrayBuffer==='function',hardwareConcurrency:navigator.hardwareConcurrency,secureContext:isSecureContext,userAgent:navigator.userAgent})"));
            JSONObject profile = profile(); receipt.put("document", document).put("profile", profile);
            PackageInfo provider = WebView.getCurrentWebViewPackage(); check(provider != null, "Current provider missing");
            receipt.put("webViewPackage", provider.packageName).put("webViewVersion", provider.versionName);
            if ("stock".equals(mode)) {
                check(provider.versionName.startsWith("124."), "Stock fallback phase did not use WebView124");
                check(!profile.getBoolean("allowlistSupported") && !profile.getBoolean("configureResult") && !document.getBoolean("crossOriginIsolated"), "Unsupported provider failed to retain conservative fallback");
                receipt.put("storage", storage(true)).put("tiny", worker("tiny", 1));
            } else {
                check("com.android.webview".equals(provider.packageName) && "155.0.8051.0".equals(provider.versionName), "Modern phase did not use the verified official provider");
                check(profile.getBoolean("allowlistSupported") && profile.getBoolean("configureResult") && profile.getString("defaultName").equals(profile.getString("name")), "Actual default profile was not configured through the public API");
                check(profile.getJSONArray("allowlist").length() == 1 && ORIGIN.equals(profile.getJSONArray("allowlist").getString(0)), "Isolation allowlist is not the exact trusted app origin");
                check(document.getBoolean("crossOriginIsolated") && document.getBoolean("sharedArrayBuffer") && document.getInt("hardwareConcurrency") >= 8, "Document did not obtain actual shared-memory isolation/eight-core capability");
                receipt.put("storage", storage(false)).put("tiny", worker("tiny", 4));
                JSONObject reference = worker("reference", 1); receipt.put("reference", reference);
                JSONObject candidate = worker("candidate", 4); receipt.put("candidate", candidate);
                for (String key : new String[]{"rawOutputsSha256", "checkpointJson", "checkpointSha256", "transcriptionJson", "fixtureSha256"}) check(reference.getString(key).equals(candidate.getString(key)), "Serial/threaded musical output differs: " + key);
                check(reference.getJSONArray("records").length() == 12 && candidate.getJSONArray("records").length() == 12 && reference.getBoolean("freshCheckpointMiss") && candidate.getBoolean("freshCheckpointMiss"), "Exact comparison did not execute all twelve fresh graph calls per mode");
                receipt.put("exact", true).put("cancel", worker("cancel", 4)).put("restart", worker("restart", 4)).put("storageAfterLifecycle", storage(false));
            }
            check(workerHeaders != null && "isolate-and-credentialless".equals(workerHeaders.optString("Document-Isolation-Policy")), "Production response transport did not supply the required DIP header");
            receipt.put("workerResponseHeaders", workerHeaders).put("fixtureSha256", PCM_SHA).put("probeScriptSha256", sha(new ByteArrayInputStream(script)));
            JSONObject sources = new JSONObject();
            for (String name : new String[]{"analysis/worker.js", "analysis/game.js", "analysis/work-store.js", "analysis/vendor/ort.wasm.min.js", "analysis/vendor/ort-wasm-simd-threaded.mjs", "analysis/vendor/ort-wasm-simd-threaded.wasm", "analysis/models/game/manifest.json", "analysis/models/game/encoder.onnx", "analysis/models/game/dur2bd.onnx", "analysis/models/game/segmenter.onnx", "analysis/models/game/bd2dur.onnx", "analysis/models/game/estimator.onnx"}) sources.put("web/" + name, sha(getTargetContext().getAssets().open(name)));
            receipt.put("sourceHashes", sources).put("androidSdk", Build.VERSION.SDK_INT).put("device", Build.MODEL).put("supportedAbis", new JSONArray(Build.SUPPORTED_ABIS)); passed = true;
        } catch (Throwable error) { try { receipt.put("error", android.util.Log.getStackTraceString(error)); } catch (Exception ignored) {} }
        finally {
            try { if (web != null) evaluate("window.__wtWorker && window.__wtWorker.terminate();window.__wtWorker=null;"); } catch (Exception ignored) {}
            if (activity != null) runOnMainSync(() -> activity.finishAndRemoveTask());
        }
        try { receipt.put("passed", passed).put("diagnosticOnly", true).put("mode", mode).put("memory", memory)
            .put("scope", "Actual app default-profile WebView on an API35 emulator. Public provider-gated isolation, OPFS/IndexedDB retention, loaded ORT pthreads, and unchanged GAME on a fixed three-second MDX-separated Falcon excerpt. Candidate uses the actual packaged thread selector called directly; reference forces one thread. This is not a complete production voice-stage dispatch and does not qualify classifier handoff. Every raw tensor and unrounded checkpoint is compared exactly. Timings include tensor hashing/storage and are not whole-song or physical-phone measurements. Cancellation terminates the owning worker after encoder call entry; a fresh threaded runtime verifies restart."); } catch (Exception ignored) {}
        Bundle output = new Bundle(); output.putString("stream", "WASM_THREAD_RESULT " + receipt + "\n" + (passed ? "WASM_THREAD_PASS\n" : "WASM_THREAD_FAIL\n")); finish(passed ? -1 : 1, output);
    }
}
