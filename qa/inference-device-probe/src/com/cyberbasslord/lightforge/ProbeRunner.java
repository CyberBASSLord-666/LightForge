package com.cyberbasslord.lightforge;

import android.app.ActivityManager;
import android.content.Context;
import android.content.ContextWrapper;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.content.res.AssetManager;
import android.os.BatteryManager;
import android.os.Build;
import android.os.Debug;
import android.os.PowerManager;
import android.os.SystemClock;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.util.UUID;
import java.util.concurrent.*;

/** Test-only coordinator. Production inference classes are compiled without edits. */
final class ProbeRunner {
    private static final int PASSAGES = 35, RECEIPT_LIMIT = 2 * 1024 * 1024;
    private static final long OUTPUT_BYTES = 2L * 573300 * 4;
    private static final long RUN_BUDGET_MS = 90L * 60 * 1000;
    private static final long[] STARTS = {-66150, 0, 22050, 44100, 88200};
    private static ProbeRunner instance;
    static synchronized ProbeRunner get(Context context) {
        if (instance == null) instance = new ProbeRunner(context.getApplicationContext());
        return instance;
    }
    private final Context app;
    private final File receiptDirectory;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final ScheduledExecutorService watch = Executors.newSingleThreadScheduledExecutor();
    private volatile boolean running, cancelled;
    private volatile String message = "Ready. No inference has run.", cancelReason = "";
    private volatile NativeDeux engine;
    private volatile String latest = "";
    private ProbeRunner(Context app) {
        this.app = app; receiptDirectory = new File(app.getFilesDir(), "probe-receipts");
        File previous = new File(receiptDirectory, "latest.json");
        try {
            if (previous.isFile()) {
                latest = new String(read(previous, RECEIPT_LIMIT), StandardCharsets.UTF_8);
                JSONObject value = new JSONObject(latest);
                message = value.optBoolean("terminal") ? "Previous receipt available: " + value.optString("outcome")
                    : "Previous process ended with an incomplete receipt. It is not a pass; export it before starting again.";
            }
        } catch (Exception invalid) { message = "A prior receipt was unreadable. Starting a new run will retain any dated files."; }
    }
    boolean isRunning() { return running; }
    boolean hasReceipt() { return !latest.isEmpty(); }
    String receipt() { return latest; }
    String status() { return message; }
    synchronized void start() {
        if (running) return;
        running = true; cancelled = false; cancelReason = ""; message = "Preparing source-bound diagnostic…";
        worker.execute(this::execute);
    }
    void cancel(String reason) {
        if (!running) return;
        cancelled = true; if (cancelReason.isEmpty()) cancelReason = reason;
        message = "Cancellation requested; waiting for native retirement…";
        NativeDeux current = engine; if (current != null) current.cancel();
    }
    private void check() throws InterruptedIOException { if (cancelled) throw new InterruptedIOException("Probe cancelled"); }

    private void execute() {
        String id = UUID.randomUUID().toString();
        File cache = new File(app.getCacheDir(), "inference-probe-" + id);
        JSONObject report = new JSONObject(); JSONArray passages = new JSONArray();
        long start = SystemClock.elapsedRealtime(), cpuStart = android.os.Process.getElapsedCpuTime();
        String stage = "source-identity"; boolean retired = false, uncertainNativeCleanup = false;
        ScheduledFuture<?> guard = watch.scheduleAtFixedRate(() -> {
            try {
                if (SystemClock.elapsedRealtime() - start >= RUN_BUDGET_MS) cancel("time-budget");
                if (Build.VERSION.SDK_INT >= 29) {
                    PowerManager power = (PowerManager)app.getSystemService(Context.POWER_SERVICE);
                    if (power != null && power.getCurrentThermalStatus() >= PowerManager.THERMAL_STATUS_SEVERE) cancel("thermal-severe");
                }
            } catch (RuntimeException unavailable) { cancel("guard-observation-failed"); }
        }, 0, 5, TimeUnit.SECONDS);
        try {
            report.put("schema", "lightforge.inference-device-probe.v1").put("runId", id)
                .put("scope", "Physical-device standalone companion; corrected Android-context NativeDeux on 35 explicit repeated-fixture benchmark passages. Not installed-app lifecycle, full-song quality, or release approval.")
                .put("plannedPassages", PASSAGES).put("terminal", false).put("outcome", "running")
                .put("startedAtEpochMillis", System.currentTimeMillis()).put("passages", passages)
                .put("freshPolicyCache", true).put("source", new JSONObject(new String(asset(app.getAssets(), "probe/source-receipt.json", RECEIPT_LIMIT), StandardCharsets.UTF_8)))
                .put("before", observations());
            persist(report, id); check();
            JSONObject source = report.getJSONObject("source");
            if (!"1.25.1".equals(source.getString("runtimeVersion")) || !"1.25.1".equals(NativeDeux.RUNTIME_VERSION)) throw new IOException("Runtime identity mismatch");
            JSONObject expected = source.getJSONObject("expectedInstalledPackage");
            String packageName = expected.getString("packageName");
            if (!"com.cyberbasslord.lightforge".equals(packageName)) throw new IOException("Unexpected asset package");
            PackageManager pm = app.getPackageManager();
            PackageInfo installed = pm.getPackageInfo(packageName, Build.VERSION.SDK_INT >= 28 ? PackageManager.GET_SIGNING_CERTIFICATES : PackageManager.GET_SIGNATURES);
            long version = Build.VERSION.SDK_INT >= 28 ? installed.getLongVersionCode() : installed.versionCode;
            Signature[] signatures = Build.VERSION.SDK_INT >= 28
                ? (installed.signingInfo == null ? null : installed.signingInfo.getApkContentsSigners()) : installed.signatures;
            if (signatures == null || signatures.length != 1) throw new IOException("Unexpected signing identity");
            String signer = sha(signatures[0].toByteArray());
            report.put("installedAssetPackage", new JSONObject().put("packageName", packageName).put("versionCode", version)
                .put("versionName", installed.versionName).put("signerSha256", signer));
            if (version != expected.getLong("versionCode") || !signer.equals(expected.getString("signerSha256"))) throw new IOException("Installed package identity mismatch");
            // Resources only: no INCLUDE_CODE, IGNORE_SECURITY, class-loader access or target lifecycle call.
            Context assetsContext = app.createPackageContext(packageName, 0);
            AssetManager installedAssets = assetsContext.getAssets();
            byte[] manifest = asset(installedAssets, "analysis/models/deux/manifest.json", 262144);
            String manifestHash = sha(manifest); report.put("modelManifestSha256", manifestHash);
            if (!manifestHash.equals(source.getString("modelManifestSha256"))) throw new IOException("Model manifest identity mismatch");
            if (!cache.mkdirs()) throw new IOException("Cannot create isolated cache");
            long bytes = 0; JSONObject entries = new JSONObject(new String(manifest, StandardCharsets.UTF_8)).getJSONObject("files");
            for (java.util.Iterator<String> names = entries.keys(); names.hasNext();) bytes = Math.addExact(bytes, entries.getJSONObject(names.next()).getLong("bytes"));
            report.put("declaredModelBytes", bytes).put("cacheAvailableBytesBefore", cache.getUsableSpace());
            if (cache.getUsableSpace() < bytes + 128L * 1024 * 1024) throw new IOException("Insufficient diagnostic cache storage");
            stage = "fixture"; JSONObject fixture = source.getJSONObject("fixture");
            if (!"probe/falcon-mix.wav".equals(fixture.getString("assetPath"))) throw new IOException("Unexpected fixture path");
            byte[] audioBytes = asset(app.getAssets(), fixture.getString("assetPath"), 8 * 1024 * 1024);
            if (!sha(audioBytes).equals(fixture.getString("pcm16Sha256"))) throw new IOException("Fixture identity mismatch");
            File audio = new File(cache, "fixture.wav");
            try (FileOutputStream stream = new FileOutputStream(audio)) { stream.write(audioBytes); stream.getFD().sync(); }
            audioBytes = null;
            Context isolated = new AssetContext(app, installedAssets, cache);
            AppDiagnostics.initialize(app);
            stage = "engine-construction"; check(); engine = new NativeDeux(isolated);
            for (int i = 0; i < PASSAGES; i++) {
                check(); stage = "passage-" + i;
                JSONObject passage = new JSONObject().put("ordinal", i).put("remainingUseful", PASSAGES-i)
                    .put("startSample", STARTS[i % STARTS.length]).put("before", observations()).put("outcome", "running");
                passages.put(passage); persist(report, id);
                NativeInferenceProfile profile = new NativeInferenceProfile(); profile.enableCandidateEvidence(); profile.captureStartMemory();
                File output = new File(cache, "passage-" + i + ".f32");
                final int ordinal = i;
                long at = SystemClock.elapsedRealtimeNanos(), cpu = android.os.Process.getElapsedCpuTime();
                try {
                    engine.predict(audio, STARTS[i % STARTS.length], output,
                        (progress, detail) -> message = "Passage " + (ordinal+1) + "/" + PASSAGES + " — " + Math.round(progress*100) + "%\n" + detail,
                        () -> cancelled, null, profile, PASSAGES-i);
                    passage.put("predictWallNanos", SystemClock.elapsedRealtimeNanos()-at)
                        .put("predictProcessCpuMillis", android.os.Process.getElapsedCpuTime()-cpu)
                        .put("output", validateOutput(output)).put("outcome", "completed");
                } catch (Throwable failure) {
                    // The production runner joins workers before throwing. A native/resource
                    // failure can still mean close failed: preserve its cache for diagnosis.
                    if (!NativeDeux.cleanCancellation(failure)) uncertainNativeCleanup = true;
                    passage.put("predictWallNanos", SystemClock.elapsedRealtimeNanos()-at)
                        .put("predictProcessCpuMillis", android.os.Process.getElapsedCpuTime()-cpu)
                        .put("outcome", cancelled ? "cancelled" : "failed").put("failureClass", failure.getClass().getSimpleName());
                    throw failure;
                } finally {
                    appendCandidateEvidence(passages, passage, profile.candidateEvidence());
                    passage.put("profile", new JSONArray(java.util.Arrays.asList(profile.finish(passage.getString("outcome")).records())))
                        .put("after", observations());
                    if (output.exists() && !output.delete()) passage.put("outputCleanupFailed", true);
                    persist(report, id);
                }
            }
            report.put("outcome", "completed");
        } catch (Throwable failure) {
            try { report.put("outcome", cancelled ? "cancelled" : "failed").put("failureStage", stage)
                .put("failureClass", failure.getClass().getSimpleName()); } catch (Exception ignored) { }
        } finally {
            guard.cancel(false);
            try { NativeDeux current = engine; if (current != null) current.close(); engine = null; retired = true; }
            catch (Throwable failure) { try { report.put("retirementFailureClass", failure.getClass().getSimpleName()).put("outcome", "failed"); } catch (Exception ignored) { } }
            // close is nonblocking; it is called here only after predict returned on this
            // same worker. Failed native resource teardown must not be claimed successful.
            boolean cleanupConfirmed = retired && !uncertainNativeCleanup;
            boolean cleanup = cleanupConfirmed && removeOwned(cache, cache);
            try {
                report.put("terminal", retired).put("inferenceCoordinatorFinished", true).put("engineCloseReturned", retired)
                    .put("nativeResourceCleanupConfirmed", cleanupConfirmed).put("temporaryCacheRemoved", cleanup)
                    .put("completedPassages", countCompleted(passages)).put("elapsedMillis", SystemClock.elapsedRealtime()-start)
                    .put("processCpuMillis", android.os.Process.getElapsedCpuTime()-cpuStart)
                    .put("cancelReason", cancelReason).put("after", observations()).put("finishedAtEpochMillis", System.currentTimeMillis());
                persist(report, id);
                message = "Diagnostic " + report.optString("outcome") + ". " + countCompleted(passages) + "/" + PASSAGES
                    + " passages. Native cleanup confirmed: " + cleanupConfirmed + ". Export the receipt; no release qualification is implied.";
            } catch (Throwable failure) { message = "Receipt persistence failed; previous incomplete evidence remains. No pass is claimed."; }
            running = false;
        }
    }
    private static final class AssetContext extends ContextWrapper {
        private final AssetManager assets; private final File cache;
        AssetContext(Context own, AssetManager assets, File cache) { super(own); this.assets=assets; this.cache=cache; }
        @Override public Context getApplicationContext() { return this; }
        @Override public AssetManager getAssets() { return assets; }
        @Override public File getCacheDir() { return cache; }
    }
    private JSONObject observations() throws Exception {
        JSONObject value = new JSONObject().put("elapsedRealtimeMillis", SystemClock.elapsedRealtime())
            .put("processCpuMillis", android.os.Process.getElapsedCpuTime()).put("sdk", Build.VERSION.SDK_INT)
            .put("manufacturer", Build.MANUFACTURER).put("model", Build.MODEL).put("osRelease", Build.VERSION.RELEASE)
            .put("abis", new JSONArray(java.util.Arrays.asList(Build.SUPPORTED_ABIS)))
            .put("availableProcessors", Runtime.getRuntime().availableProcessors())
            .put("javaHeapUsedBytes", Runtime.getRuntime().totalMemory()-Runtime.getRuntime().freeMemory())
            .put("javaHeapLimitBytes", Runtime.getRuntime().maxMemory()).put("nativeHeapAllocatedBytes", Debug.getNativeHeapAllocatedSize());
        ActivityManager manager = (ActivityManager)app.getSystemService(Context.ACTIVITY_SERVICE);
        if (manager != null) { ActivityManager.MemoryInfo info = new ActivityManager.MemoryInfo(); manager.getMemoryInfo(info);
            value.put("availableMemoryBytes", info.availMem).put("totalMemoryBytes", info.totalMem).put("lowMemory", info.lowMemory).put("memoryThresholdBytes", info.threshold); }
        PowerManager power = (PowerManager)app.getSystemService(Context.POWER_SERVICE);
        if (power != null) { value.put("interactive", power.isInteractive()).put("powerSave", power.isPowerSaveMode()).put("deviceIdle", power.isDeviceIdleMode())
            .put("thermalStatus", Build.VERSION.SDK_INT >= 29 ? power.getCurrentThermalStatus() : JSONObject.NULL); }
        Intent battery = app.registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        if (battery != null) value.put("batteryLevel", battery.getIntExtra(BatteryManager.EXTRA_LEVEL,-1)).put("batteryScale", battery.getIntExtra(BatteryManager.EXTRA_SCALE,-1))
            .put("batteryStatus", battery.getIntExtra(BatteryManager.EXTRA_STATUS,-1)).put("plugged", battery.getIntExtra(BatteryManager.EXTRA_PLUGGED,-1))
            .put("batteryTemperatureTenthsC", battery.getIntExtra(BatteryManager.EXTRA_TEMPERATURE,-1));
        long peak = -1; try (BufferedReader reader = new BufferedReader(new FileReader("/proc/self/status"))) {
            String line; while ((line=reader.readLine())!=null) if (line.startsWith("VmHWM:")) peak=Long.parseLong(line.trim().split("\\s+")[1])*1024;
        } catch (Exception unavailable) { }
        value.put("processPeakRssBytes", peak < 0 ? JSONObject.NULL : peak); return value;
    }
    private JSONObject validateOutput(File file) throws Exception {
        if (file.length()!=OUTPUT_BYTES) throw new IOException("Unexpected complete output size");
        MessageDigest hash=MessageDigest.getInstance("SHA-256"); long floats=0; float max=0;
        byte[] buffer=new byte[32768]; try (InputStream in=new FileInputStream(file)) {
            int n; while ((n=in.read(buffer))!=-1) { check(); if ((n&3)!=0) throw new IOException("Unaligned output"); hash.update(buffer,0,n);
                ByteBuffer values=ByteBuffer.wrap(buffer,0,n).order(ByteOrder.LITTLE_ENDIAN);
                while (values.hasRemaining()) { float f=values.getFloat(); if (!Float.isFinite(f)) throw new IOException("Nonfinite output"); max=Math.max(max,Math.abs(f)); floats++; }
            }
        }
        return new JSONObject().put("sha256",hex(hash.digest())).put("bytes",file.length()).put("floatCount",floats).put("finite",true).put("maxAbs",max);
    }
    private void persist(JSONObject report,String id) throws Exception {
        byte[] bytes=report.toString(2).getBytes(StandardCharsets.UTF_8); if(bytes.length>RECEIPT_LIMIT)throw new IOException("Receipt size bound exceeded");
        if(!receiptDirectory.isDirectory()&&!receiptDirectory.mkdirs())throw new IOException("Cannot create receipt directory");
        atomic(new File(receiptDirectory,id+".json"),bytes); atomic(new File(receiptDirectory,"latest.json"),bytes); latest=new String(bytes,StandardCharsets.UTF_8);
    }
    /** One bounded auxiliary profile per paired passage; never merge it into production totals. */
    static void appendCandidateEvidence(JSONArray passages,JSONObject passage,NativeInferenceProfile.CandidateEvidence evidence)throws Exception {
        if(evidence==null)return;
        int retained=0;
        for(int i=0;i<passages.length();i++)if(passages.getJSONObject(i).has("candidateEvidence"))retained++;
        if(retained>=3||passages.length()>PASSAGES||passage.has("candidateEvidence")||
            passage.getInt("ordinal")!=evidence.ordinal||evidence.ordinal>=PASSAGES)
            throw new IOException("Candidate evidence bounds exceeded");
        passage.put("candidateEvidence",candidateEvidenceJson(evidence));
    }
    static JSONObject candidateEvidenceJson(NativeInferenceProfile.CandidateEvidence evidence)throws Exception {
        if(evidence.profile.recordCount()>NativeInferenceProfile.MAX_RECORDS)throw new IOException("Candidate profile exceeds record bound");
        int graphs=0;
        for(String record:evidence.profile.records()){
            if(record==null||record.length()>8192)throw new IOException("Candidate profile exceeds record length bound");
            if(record.startsWith("schema=native-inference-graph-v2 "))graphs++;
        }
        if(graphs>NativeInferenceProfile.MAX_GRAPH_RECORDS)throw new IOException("Candidate graph bound exceeded");
        return new JSONObject().put("schema","native-passage-candidate-evidence-v1")
            .put("ordinal",evidence.ordinal).put("workers",evidence.workers).put("candidateFirst",evidence.candidateFirst)
            .put("commonPreflightVerifiedModelCount",evidence.commonPreflightVerifiedModelCount)
            .put("profileWallScope","collector-lifetime-not-arm-clock")
            .put("comparisonScope","same-input-paired-attempts")
            .put("modelSetupScope","observed-file-preparation-not-os-cache-equivalence")
            .put("baseline",armEvidenceJson(evidence.baseline)).put("candidate",armEvidenceJson(evidence.candidate))
            .put("profile",new JSONArray(java.util.Arrays.asList(evidence.profile.records())));
    }
    private static Object armEvidenceJson(NativeInferenceProfile.ArmEvidence arm)throws Exception {
        if(arm==null)return JSONObject.NULL;
        NativeInferenceProfile.ModelSetup before=arm.before,after=arm.after;
        return new JSONObject().put("outcome",arm.outcome)
            .put("armWallNanos",arm.armWallNanos<0?JSONObject.NULL:Long.valueOf(arm.armWallNanos))
            .put("modelSetup",new JSONObject().put("verifiedModelsBefore",before.verifiedModels).put("verifiedModelsAfter",after.verifiedModels)
                .put("extractionAttempts",after.extractionAttempts-before.extractionAttempts)
                .put("extractionBytesRead",after.extractionBytesRead-before.extractionBytesRead)
                .put("existingFileChecksumAttempts",after.existingFileChecksumAttempts-before.existingFileChecksumAttempts)
                .put("existingFileChecksumBytesRead",after.existingFileChecksumBytesRead-before.existingFileChecksumBytesRead));
    }
    private static void atomic(File target,byte[] bytes)throws Exception {
        File temporary=new File(target.getParentFile(),target.getName()+".partial");
        try(FileOutputStream out=new FileOutputStream(temporary)){out.write(bytes);out.getFD().sync();}
        Files.move(temporary.toPath(),target.toPath(),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
    }
    private static byte[] asset(AssetManager assets,String path,int max)throws Exception {try(InputStream in=assets.open(path)){return read(in,max);}}
    private static byte[] read(File file,int max)throws Exception {try(InputStream in=new FileInputStream(file)){return read(in,max);}}
    private static byte[] read(InputStream in,int max)throws Exception {ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1){if(out.size()+n>max)throw new IOException("Read bound exceeded");out.write(b,0,n);}return out.toByteArray();}
    private static String sha(byte[] bytes)throws Exception{return hex(MessageDigest.getInstance("SHA-256").digest(bytes));}
    private static String hex(byte[] bytes){StringBuilder out=new StringBuilder();for(byte b:bytes)out.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return out.toString();}
    private static int countCompleted(JSONArray rows){int n=0;for(int i=0;i<rows.length();i++)if("completed".equals(rows.optJSONObject(i).optString("outcome")))n++;return n;}
    private static boolean removeOwned(File root,File file) {
        try {
            if(!file.exists())return true;
            String base=root.getCanonicalPath(),path=file.getCanonicalPath();
            if(!path.equals(base)&&!path.startsWith(base+File.separator))return false;
            boolean okay=true; if(file.isDirectory()){File[] children=file.listFiles();if(children==null)return false;for(File child:children)okay=removeOwned(root,child)&&okay;}
            return file.delete()&&okay;
        } catch(Exception failure){return false;}
    }
}
