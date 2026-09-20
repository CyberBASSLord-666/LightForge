# GAME backend feasibility benchmark

This development-only harness evaluates a native Java backend against the shipped
`web/analysis/game.js` adapter. It does not change the application pipeline or
enable a native transcription backend. It uses the same five hash-verified GAME
graphs, Float32 weights/input, 44.1 kHz clock, eight diffusion steps, seeded
xorshift noise, language, thresholds and note filtering. The Java adapter returns
unrounded passage-local notes; production context stitching remains in `game.js`.

Supply one already-selected **mono Float32 little-endian passage**, at most
16 seconds (the production 12-second core plus two-second left/right context).
Do not shorten production contexts to manufacture a speed improvement. Choose the
same exact input file and seed for both backends. Benchmark files can contain
private audio and reconstructed features: keep every output directory outside
the repository and do not upload them with a public release.

The Java runtime is pinned to ORT 1.25.1, already used by Android. The reference
uses the repository's actual bundled ORT-Web version; its receipt records that
version rather than implying the backends run the same runtime build. This
prototype needs JDK 17 and the repository's existing `org.json` test dependency.

`benchmark_wasm_batch.py` separately tests whether fixing only GAME's symbolic
batch dimension `B` to the production value of one improves the shipped WASM
backend. It first inspects all five original ONNX graphs and binds their hashes
and symbolic dimensions, then runs one alternating warmup pair and at least
three measured pairs in fresh processes. Every graph output is checked finite
and hashed on every run; the first pair also compares every raw tensor byte and
unrounded note. The candidate keeps time and note dimensions dynamic.

```sh
python3 tools/game_benchmark/benchmark_wasm_batch.py \
  --models web/analysis/models/game \
  --input ../passage.f32 \
  --output ../game-wasm-batch-comparison
```

A result is useful only when exact output parity passes. Timing remains a host
observation; a slower or inconsistent candidate must not be enabled in the app.

## Production-context native feasibility

`benchmark_native_process.py` goes beyond a manually selected passage: it uses
the production 12-second cores, two-second context, per-passage seeds, and the
actual `game.js.process()` checkpoint/stitching path. Supply the complete source
as mono Float32 little-endian PCM at 44.1 kHz (up to ten minutes for this development
harness). Do not trim, repeat, or pad it to obtain a favorable timing result.

```sh
python3 tools/game_benchmark/benchmark_native_process.py \
  --input /private/complete-source.f32 \
  --models /private/original-game-models \
  --input-provenance /private/source-provenance.json \
  --output /private/new-native-process-comparison
node --test tools/game_benchmark/tests/process_capture.test.cjs
python3 -m unittest discover -s tools/game_benchmark/tests -p 'test_*.py'
```

This records one captured WASM/native pair per passage, retains every raw tensor
and numerical difference, and replays the captured unrounded notes through the
unchanged production validator, continuation handling, clipping, sorting and
rounding. The derived passage plan must first be accepted by the actual adapter;
missing passages, altered seeds, mismatched PCM/model hashes or invalid checkpoint
notes fail. Sources, runtime dependencies, inputs and partial completed passages
are hash-bound so an interrupted run cannot look like a complete song result.

Raw parity and final-transcription equality are **separate observations**. A
numeric difference never becomes automatic quality approval just because notes
round identically. Conversely, this diagnostic does not redefine all cross-runtime
Float32 differences as musical errors. It leaves full-analysis quality, Android
integration and performance-target approval explicitly false. Source separation,
vocal fusion, show generation and native task lifecycle still need their own checks.
Both runners time `session.run`; their broader wall-time scopes differ, so this
tool does not report a comparable whole-pipeline wall-time speedup. Distinct source
passages are not repeated timing pairs or a statistical performance experiment.

Add `--production-engine` to compile and execute the actual Android
`NativeGame.java` engine (on the host JVM) instead of the historical prototype.
This mode retains WASM raw tensors, both unrounded note lists and numeric note
differences. It does **not** claim native raw-tensor parity: the production engine
has no tensor-capture observer. It then exercises the actual optional `nativeInfer`
adapter with the verified PCM windows, validates native checkpoint identity/resume,
and compares final transcription payloads, excluding only the explicitly checked
native-runtime provenance field. No production model or rounding rule is modified.

For an independently source-bound verification artifact that retains JSON receipts
but not audio, rederive note stitching and native checkpoint restore with:

```sh
node tools/game_benchmark/process_capture.cjs --production-receipts \
  /private/evidence/capture-input.json /private/new-receipt-replay.json
```

This second mode clearly reports `receipt-only-checkpoint-replay` and
`freshNativeCallbackInputsRevalidated: false`: it does not reobserve the audio,
JNI inference, or native callback PCM. Fresh capture remains required to establish
those bindings. These are evidence tools, not standalone publication authority.

```sh
mkdir -p ../game-benchmark/classes
javac -cp "$ORT_JAR:$JSON_JAR" -d ../game-benchmark/classes tools/game_benchmark/NativeGameBenchmark.java
java -cp "../game-benchmark/classes:$ORT_JAR:$JSON_JAR" NativeGameBenchmark web/analysis/models/game ../passage.f32 ../game-benchmark/native 2025 0 4 true
node tools/game_benchmark/capture_web.cjs web/analysis/models/game ../passage.f32 ../game-benchmark/web 2025 0 4 true
python3 tools/game_benchmark/compare.py ../game-benchmark/web ../game-benchmark/native --output ../game-benchmark/comparison.json
```

Output directories must be new. Both runners verify all model hashes before
inference. Captured receipts bind the PCM digest, sample count, graph inventory,
seed, language and steps. Each graph output—including all eight segmentation
steps—is saved with its original type, shape and byte digest. The comparator
validates the complete stage sequence, expected outputs, shapes, file digests
and finite floats. Exit code 0 means all output bytes and unrounded notes match;
exit code 2 means a numerical or shape difference. Numeric differences are
reported, never converted into an automatic quality approval. Matching rounded
notes alone is insufficient.

Run capture first. Only if numerical quality has been independently resolved,
repeat both runners with `false` to avoid capture I/O while timing. Compare
alternating, otherwise-idle runs on the same machine, with the same requested thread count
and fresh sessions. Receipts separate initialization and graph inference; total
wall time explicitly states whether it includes tensor capture. Node WASM versus
Linux Java is a host experiment, not a measured Android WebView acceleration.
Receipts distinguish requested thread configuration from effective workers:
effective worker counts are null because this harness does not independently
observe native pools or WASM worker fallback. The WASM runtime's reported option
is recorded separately and is not proof of its effective worker count.
Final rollout would additionally require Android task ownership/cancellation,
bounded session retirement, original PCM/context/checkpoint semantics, crash
fallback and release regression coverage.

The deterministic noise generator can be checked without loading models:

```sh
java -cp "../game-benchmark/classes:$ORT_JAR:$JSON_JAR" NativeGameBenchmark noise 10000 2025 ../game-benchmark/noise.bin
```

This writes the same Float32 byte sequence as `LightForgeGAME.noise(10000,2025)`.
The harness follows the official [Java session and result ownership API](https://onnxruntime.ai/docs/get-started/with-java.html),
[typed tensor buffers](https://onnxruntime.ai/docs/api/java/ai/onnxruntime/OnnxTensor.html),
and [ORT-Web runtime settings](https://onnxruntime.ai/docs/tutorials/web/env-flags-and-session-options.html).
