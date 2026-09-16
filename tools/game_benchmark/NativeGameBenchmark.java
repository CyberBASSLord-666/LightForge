/* Private-input host benchmark for unchanged GAME graphs. Not an Android bridge. */
import ai.onnxruntime.*;
import org.json.*;
import java.io.*;
import java.nio.*;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;

public final class NativeGameBenchmark implements AutoCloseable {
    static final int RATE = 44100, STEPS = 8;
    static final String[] GRAPHS = {"encoder", "dur2bd", "segmenter", "bd2dur", "estimator"};
    final OrtEnvironment env = OrtEnvironment.getEnvironment();
    final Map<String, OrtSession> sessions = new LinkedHashMap<>();
    final JSONArray stages = new JSONArray(), initialization = new JSONArray();
    final Path output;
    final boolean capture;

    NativeGameBenchmark(Path models, Path output, int threads, boolean capture) throws Exception {
        this.output = output;
        this.capture = capture;
        if (!"1.25.1".equals(env.getVersion())) throw new IOException("Requires ORT 1.25.1");
        try {
            for (String name : GRAPHS) {
                long start = System.nanoTime();
                try (OrtSession.SessionOptions options = new OrtSession.SessionOptions()) {
                    options.setIntraOpNumThreads(threads);
                    options.setInterOpNumThreads(1);
                    options.setExecutionMode(OrtSession.SessionOptions.ExecutionMode.SEQUENTIAL);
                    options.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT);
                    options.setCPUArenaAllocator(false);
                    options.setMemoryPatternOptimization(false);
                    options.addConfigEntry("session.intra_op.allow_spinning", "0");
                    sessions.put(name, env.createSession(models.resolve(name + ".onnx").toString(), options));
                }
                initialization.put(new JSONObject().put("graph", name).put("seconds", elapsed(start)));
            }
        } catch (Exception error) { close(); throw error; }
    }

    static float[] noise(int count, long seed) {
        float[] values = new float[count]; int x = (int) seed;
        for (int i = 0; i < count; i++) {
            x ^= x << 13; x ^= x >>> 17; x ^= x << 5;
            values[i] = (float) ((Integer.toUnsignedLong(x) + .5) / 4294967296.0);
        }
        return values;
    }

    OnnxTensor floats(float[] values, long... dims) throws Exception {
        FloatBuffer data = ByteBuffer.allocateDirect(Math.multiplyExact(values.length, 4)).order(ByteOrder.nativeOrder()).asFloatBuffer();
        data.put(values).flip(); return OnnxTensor.createTensor(env, data, dims);
    }
    OnnxTensor longs(long value, long... dims) throws Exception {
        LongBuffer data = ByteBuffer.allocateDirect(8).order(ByteOrder.nativeOrder()).asLongBuffer();
        data.put(value).flip(); return OnnxTensor.createTensor(env, data, dims);
    }
    static OnnxTensor tensor(OrtSession.Result values, String key) {
        return (OnnxTensor) values.get(key).orElseThrow(() -> new IllegalArgumentException("Missing " + key));
    }
    static Map<String, OnnxTensor> feeds(Object... pairs) {
        Map<String, OnnxTensor> values = new LinkedHashMap<>();
        for (int i = 0; i < pairs.length; i += 2) values.put((String) pairs[i], (OnnxTensor) pairs[i + 1]);
        return values;
    }
    OrtSession.Result run(String graph, String label, Map<String, OnnxTensor> feeds) throws Exception {
        long start = System.nanoTime(); OrtSession.Result result = sessions.get(graph).run(feeds);
        double seconds = elapsed(start);
        try {
            JSONArray outputs = new JSONArray();
            if (capture) for (Map.Entry<String, OnnxValue> entry : result) {
                OnnxTensor value = (OnnxTensor) entry.getValue(); TensorInfo info = value.getInfo();
                ByteBuffer raw = value.getByteBuffer(); byte[] bytes = new byte[raw.remaining()]; raw.get(bytes);
                if (ByteOrder.nativeOrder() != ByteOrder.LITTLE_ENDIAN) throw new IOException("Capture requires little-endian host");
                String file = label + "-" + entry.getKey() + ".bin"; Files.write(output.resolve(file), bytes, StandardOpenOption.CREATE_NEW);
                outputs.put(new JSONObject().put("name", entry.getKey()).put("type", type(info.type))
                    .put("dims", new JSONArray(info.getShape())).put("file", file).put("bytes", bytes.length).put("sha256", hash(bytes)));
            }
            stages.put(new JSONObject().put("graph", graph).put("label", label).put("seconds", seconds).put("outputs", outputs));
            System.err.println(label + " " + seconds + " seconds");
            return result;
        } catch (Exception error) { result.close(); throw error; }
    }
    JSONArray infer(float[] pcm, int language, long seed) throws Exception {
        float duration = (float) (pcm.length / (double) RATE);
        try (OnnxTensor waveform = floats(pcm, 1, pcm.length);
             OnnxTensor encoderDuration = floats(new float[]{duration}, 1);
             OnnxTensor durations = floats(new float[]{duration}, 1, 1);
             OnnxTensor lang = longs(language, 1);
             OnnxTensor threshold = floats(new float[]{.2f});
             OnnxTensor radius = longs(2);
             OrtSession.Result encoded = run("encoder", "encoder", feeds("waveform", waveform, "duration", encoderDuration));
             OrtSession.Result known = run("dur2bd", "dur2bd", feeds("durations", durations, "maskT", tensor(encoded, "maskT")))) {
            OrtSession.Result previous = null;
            try {
                OnnxTensor maskT = tensor(encoded, "maskT"); long[] dims = maskT.getInfo().getShape();
                int count = Math.toIntExact(maskT.getInfo().getNumElements());
                for (int k = 0; k < STEPS; k++) {
                    try (OnnxTensor time = floats(new float[]{k / (float) STEPS}, 1);
                         OnnxTensor random = floats(noise(count, (seed + k * 2654435761L) & 0xffffffffL), dims)) {
                        OrtSession.Result next = run("segmenter", "segmenter-" + k,
                            feeds("x_seg", tensor(encoded, "x_seg"), "maskT", maskT,
                                "known_boundaries", tensor(known, "boundaries"),
                                "prev_boundaries", tensor(previous == null ? known : previous, "boundaries"),
                                "language", lang, "threshold", threshold, "radius", radius, "t", time, "random_uniform", random));
                        if (previous != null) previous.close(); previous = next;
                    }
                }
                try (OrtSession.Result timing = run("bd2dur", "bd2dur", feeds("boundaries", tensor(previous, "boundaries"), "maskT", maskT));
                     OrtSession.Result estimated = run("estimator", "estimator", feeds("x_est", tensor(encoded, "x_est"),
                         "boundaries", tensor(previous, "boundaries"), "maskT", maskT, "maskN", tensor(timing, "maskN"), "threshold", threshold))) {
                    FloatBuffer lengths = tensor(timing, "durations").getFloatBuffer();
                    FloatBuffer pitches = tensor(estimated, "scores").getFloatBuffer();
                    ByteBuffer mask = tensor(timing, "maskN").getByteBuffer(), present = tensor(estimated, "presence").getByteBuffer();
                    if (tensor(timing, "maskN").getInfo().type != OnnxJavaType.BOOL || tensor(estimated, "presence").getInfo().type != OnnxJavaType.BOOL)
                        throw new IOException("Unexpected note mask type");
                    JSONArray notes = new JSONArray(); double start = 0;
                    for (int i = 0; i < lengths.remaining(); i++) {
                        double length = lengths.get(i), end = start + length, midi = pitches.get(i);
                        if (!Double.isFinite(length) || length < 0 || !Double.isFinite(midi)) throw new IOException("Invalid note output");
                        if (mask.get(i) != 0 && present.get(i) != 0 && length >= .06 && midi >= 0 && midi <= 127)
                            notes.put(new JSONObject().put("start", start).put("end", end).put("midi", midi));
                        start = end;
                    }
                    return notes;
                }
            } finally { if (previous != null) previous.close(); }
        }
    }
    static String type(OnnxJavaType type) throws IOException {
        switch (type) {
            case FLOAT: return "float32"; case DOUBLE: return "float64"; case BOOL: return "bool";
            case INT64: return "int64"; case INT32: return "int32";
            default: throw new IOException("Unsupported capture type: " + type);
        }
    }
    static double elapsed(long start) { return (System.nanoTime() - start) / 1e9; }
    static String hash(byte[] bytes) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }
    static String fileHash(Path path) throws Exception {
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        try (InputStream in = Files.newInputStream(path)) { byte[] b = new byte[262144]; int n; while ((n = in.read(b)) >= 0) md.update(b, 0, n); }
        return HexFormat.of().formatHex(md.digest());
    }
    static JSONObject verifyModels(Path models) throws Exception {
        JSONObject manifest = new JSONObject(Files.readString(models.resolve("manifest.json")));
        if (!"game-large-1.0.3-lightforge-1".equals(manifest.getString("id")) || manifest.getInt("steps") != 8 || manifest.getInt("sampleRate") != RATE)
            throw new IOException("Unexpected GAME manifest");
        JSONObject files = new JSONObject();
        for (String name : GRAPHS) {
            String file = name + ".onnx"; Path path = models.resolve(file); JSONObject expected = manifest.getJSONObject("files").getJSONObject(file);
            String sha = fileHash(path);
            if (Files.size(path) != expected.getLong("bytes") || !sha.equals(expected.getString("sha256"))) throw new IOException("Model checksum mismatch: " + name);
            files.put(file, expected);
        }
        return files;
    }
    public void close() { for (OrtSession session : sessions.values()) try { session.close(); } catch (Exception ignored) {} sessions.clear(); }
    public static void main(String[] args) throws Exception {
        if (args.length == 4 && "noise".equals(args[0])) {
            float[] values = noise(Integer.parseInt(args[1]), Long.parseUnsignedLong(args[2]));
            ByteBuffer bytes = ByteBuffer.allocate(values.length * 4).order(ByteOrder.LITTLE_ENDIAN); for (float v : values) bytes.putFloat(v);
            Files.write(Path.of(args[3]), bytes.array(), StandardOpenOption.CREATE_NEW); return;
        }
        if (args.length != 7) throw new IllegalArgumentException("models-directory pcm-f32le output-directory seed language threads capture(true|false)");
        Path models = Path.of(args[0]), input = Path.of(args[1]), output = Path.of(args[2]);
        long seed = Long.parseUnsignedLong(args[3]); int language = Integer.parseInt(args[4]), threads = Integer.parseInt(args[5]);
        if (Long.compareUnsigned(seed, 0xffffffffL) > 0 || language < 0 || language > 4 || threads < 1 || threads > 64 || !Set.of("true", "false").contains(args[6])) throw new IllegalArgumentException("Invalid benchmark settings");
        long inputBytes = Files.size(input); if (inputBytes < 4 || inputBytes % 4 != 0 || inputBytes > 16L * RATE * 4) throw new IOException("Expected one nonempty <=16-second mono Float32 passage");
        if (Files.exists(output)) throw new IOException("Output directory must not exist"); Files.createDirectories(output);
        JSONObject graphs = verifyModels(models); byte[] bytes = Files.readAllBytes(input); FloatBuffer raw = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer();
        float[] pcm = new float[raw.remaining()]; raw.get(pcm); for (float v : pcm) if (!Float.isFinite(v)) throw new IOException("Invalid PCM");
        long start = System.nanoTime();
        try (NativeGameBenchmark benchmark = new NativeGameBenchmark(models, output, threads, Boolean.parseBoolean(args[6]))) {
            JSONArray notes = benchmark.infer(pcm, language, seed); double total = elapsed(start), inference = 0;
            for (Object stage : benchmark.stages) inference += ((JSONObject) stage).getDouble("seconds");
            JSONObject report = new JSONObject().put("schema", "lightforge-game-benchmark-1").put("runtime", "onnxruntime-java-" + benchmark.env.getVersion())
                .put("sampleRate", RATE).put("samples", pcm.length).put("pcmSHA256", hash(bytes)).put("modelFiles", graphs)
                .put("seed", seed).put("language", language).put("steps", STEPS).put("requestedThreads", threads)
                .put("effectiveThreads", JSONObject.NULL).put("threadObservation", "Requested intra-op setting; effective worker count was not observed")
                .put("capture", benchmark.capture)
                .put("initialization", benchmark.initialization).put("stages", benchmark.stages).put("notes", notes)
                .put("inferenceSeconds", inference).put("wallSeconds", total).put("wallIncludesCapture", benchmark.capture)
                .put("scope", "Host prototype; no Android integration, physical-device speed claim, or musical-quality attestation");
            Files.writeString(output.resolve("receipt.json"), report.toString(2) + "\n", StandardOpenOption.CREATE_NEW);
            System.out.println(new JSONObject().put("receipt", output.resolve("receipt.json")).put("inferenceSeconds", inference).put("notes", notes.length()));
        }
    }
}
