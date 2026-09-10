package com.cyberbasslord.lightforge;

import android.app.Instrumentation;
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
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.lang.reflect.Field;
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONObject;

/** Separate diagnostic APK; no hooks, assets, or model changes ship in LightForge. */
public final class AnalysisCpuProbe extends Instrumentation {
    private static final String ORIGIN = "https://appassets.androidplatform.net";
    private static final String PROBE_PATH = "/analysis/__cpu_probe__.js";
    private MainActivity activity;
    private WebView web;
    private volatile Map<String,String> workerHeaders;

    private void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
    private byte[] read(InputStream input) throws Exception {
        try (InputStream source = input; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] block = new byte[8192]; int count;
            while ((count = source.read(block)) >= 0) output.write(block, 0, count);
            return output.toByteArray();
        }
    }
    private String sha(byte[] bytes) throws Exception {
        StringBuilder result = new StringBuilder();
        for (byte value : MessageDigest.getInstance("SHA-256").digest(bytes)) result.append(String.format("%02x", value & 255));
        return result.toString();
    }
    private String evaluate(String script) throws Exception {
        AtomicReference<String> value = new AtomicReference<>();
        CountDownLatch done = new CountDownLatch(1);
        runOnMainSync(() -> web.evaluateJavascript(script, result -> { value.set(result); done.countDown(); }));
        check(done.await(15, TimeUnit.SECONDS), "WebView evaluation timed out");
        return value.get();
    }
    private JSONObject awaitResult() throws Exception {
        long until = SystemClock.elapsedRealtime() + 120000;
        while (SystemClock.elapsedRealtime() < until) {
            String value = evaluate("window.__lightForgeCpuProbe || null");
            if (value != null && !"null".equals(value)) return new JSONObject(value);
            SystemClock.sleep(200);
        }
        throw new AssertionError("CPU capability worker timed out");
    }
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }
    @Override public void onStart() {
        JSONObject receipt = new JSONObject();
        boolean passed = false;
        try {
            byte[] script = read(getContext().getAssets().open("analysis-cpu-worker.js"));
            Intent intent = new Intent(getTargetContext(), MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
            activity = (MainActivity) startActivitySync(intent);
            Field field = MainActivity.class.getDeclaredField("web"); field.setAccessible(true);
            web = (WebView) field.get(activity);
            check(web != null, "Production Activity WebView missing");
            long until = SystemClock.elapsedRealtime() + 45000;
            while (SystemClock.elapsedRealtime() < until && !"true".equals(evaluate("location.origin === '" + ORIGIN + "' && document.readyState !== 'loading'"))) SystemClock.sleep(200);
            check("true".equals(evaluate("location.origin === '" + ORIGIN + "' && document.readyState !== 'loading'")), "Production app document did not load");
            runOnMainSync(() -> {
                WebViewClient production = web.getWebViewClient();
                web.setWebViewClient(new WebViewClient() {
                    @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                        if (ORIGIN.equals(request.getUrl().getScheme() + "://" + request.getUrl().getAuthority()) && PROBE_PATH.equals(request.getUrl().getPath())) {
                            // Obtain the headers through the existing production client.
                            // Only this test URL gets a test body; every imported byte
                            // and every other response remains the production APK's.
                            WebResourceRequest worker = new WebResourceRequest() {
                                public Uri getUrl() { return Uri.parse(ORIGIN + "/analysis/worker.js"); }
                                public boolean isForMainFrame() { return false; }
                                public boolean isRedirect() { return false; }
                                public boolean hasGesture() { return false; }
                                public String getMethod() { return request.getMethod(); }
                                public Map<String,String> getRequestHeaders() { return request.getRequestHeaders(); }
                            };
                            WebResourceResponse original = production.shouldInterceptRequest(view, worker);
                            if (original == null || original.getStatusCode() != 200) return original;
                            workerHeaders = new HashMap<>(original.getResponseHeaders());
                            try { original.getData().close(); } catch (Exception ignored) { }
                            Map<String,String> probeHeaders = new HashMap<>(workerHeaders);
                            probeHeaders.keySet().removeIf(name -> "Content-Length".equalsIgnoreCase(name) || "Content-Range".equalsIgnoreCase(name));
                            probeHeaders.put("Content-Length", Integer.toString(script.length));
                            return new WebResourceResponse(original.getMimeType(), original.getEncoding(), 200, "OK", probeHeaders, new ByteArrayInputStream(script));
                        }
                        return production.shouldInterceptRequest(view, request);
                    }
                    @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                        return production.shouldOverrideUrlLoading(view, request);
                    }
                });
            });
            JSONObject document = new JSONObject(evaluate("({location:location.href,crossOriginIsolated:crossOriginIsolated===true,sharedArrayBuffer:typeof SharedArrayBuffer==='function',hardwareConcurrency:navigator.hardwareConcurrency,secureContext:isSecureContext,userAgent:navigator.userAgent})"));
            evaluate("(() => { const worker = new Worker('" + PROBE_PATH + "'); window.__cpuProbeWorker = worker; worker.onmessage = event => { if(event.data && event.data.type === 'analysis-cpu-probe') window.__lightForgeCpuProbe = event.data.result; }; worker.onerror = event => { window.__lightForgeCpuProbe = {passed:false,error:String(event.message)}; }; worker.postMessage({probe:true}); })()");
            JSONObject worker = awaitResult();
            receipt.put("document", document).put("worker", worker).put("workerResponseHeaders", new JSONObject(workerHeaders == null ? new HashMap<String,String>() : workerHeaders));
            receipt.put("probeScriptSha256", sha(script));
            for (String[] entry : new String[][]{{"workerSourceSha256", "analysis/worker.js"}, {"ortSourceSha256", "analysis/vendor/ort.wasm.min.js"}}) {
                String expected = sha(read(getTargetContext().getAssets().open(entry[1])));
                check(expected.equals(worker.optString(entry[0])), "Worker did not import the original APK asset: " + entry[1]);
            }
            check(worker.optBoolean("passed") && worker.optBoolean("identityExact") && worker.optBoolean("checkpointRemoved"), "Worker evidence failed: " + worker);
            check(workerHeaders != null && "same-origin".equals(workerHeaders.get("Cross-Origin-Opener-Policy")) && "require-corp".equals(workerHeaders.get("Cross-Origin-Embedder-Policy")), "Production isolation header evidence missing");
            check(worker.has("crossOriginIsolated") && worker.has("sharedArrayBuffer") && worker.optInt("hardwareConcurrency") > 0 && worker.optInt("configuredThreads") > 0 && worker.optInt("effectiveThreads") > 0, "CPU capability evidence incomplete");
            PackageInfo webview = WebView.getCurrentWebViewPackage();
            receipt.put("webViewPackage", webview == null ? JSONObject.NULL : webview.packageName).put("webViewVersion", webview == null ? JSONObject.NULL : webview.versionName);
            receipt.put("androidSdk", Build.VERSION.SDK_INT).put("device", Build.MODEL).put("supportedAbis", new org.json.JSONArray(Build.SUPPORTED_ABIS));
            passed = true;
        } catch (Throwable error) {
            try { receipt.put("error", android.util.Log.getStackTraceString(error)); } catch (Exception ignored) { }
        } finally {
            try { if (web != null) evaluate("window.__cpuProbeWorker && window.__cpuProbeWorker.terminate()"); } catch (Exception ignored) { }
            if (activity != null) runOnMainSync(() -> activity.finishAndRemoveTask());
        }
        try { receipt.put("passed", passed).put("diagnosticOnly", true).put("scope", "Actual production Activity WebView, unchanged imported worker and ORT, tiny Identity initialization only; no music analysis, throughput result, or physical-phone claim."); } catch (Exception ignored) { }
        Bundle output = new Bundle();
        output.putString("stream", "ANALYSIS_CPU_RESULT " + receipt + "\n" + (passed ? "ANALYSIS_CPU_PASS\n" : "ANALYSIS_CPU_FAIL\n"));
        finish(passed ? -1 : 1, output);
    }
}
