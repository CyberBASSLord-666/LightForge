# Deux runtime verification

The model checkpoint, Float32 weights, complete 13-second attention context,
13-second input window, 10-second usable region, and 5-second overlapping advance
are preserved. The new graphs process independent bands and frames in bounded
batches; they do not shorten the attention window or approximate the weights.
The browser adapter keeps one ONNX session live and processes mask heads in
128-frame batches. Android can supply the native predictor while retaining the
same source-clock scheduler, overlapping crossfades, and passage checkpoints.

| Comparison on this Linux development machine | WASM | Native Java CPU |
| --- | ---: | ---: |
| Same 300,032-sample PCM16 input, four threads | 127.25 s | 61.11 s |
| Peak process RSS | 1,920.96 MiB | 720.56 MiB |

These measurements describe one 6.8-second excerpt on a development machine.
They are not full-song or physical-phone performance measurements. Refer to
`deux-native-java.json` for the actual Java implementation's Float32 error
against the exact same PCM16 input and model weights.

The Float32 source excerpt also passed an independent WASM comparison against
the historical combined-graph output: both separated stems were bit-identical,
with zero maximum or RMS sample error. That result is recorded in
`deux-bounded-wasm.json`. The PCM16 oracle is recorded separately in
`deux-bounded-pcm16-wasm.json`; the two inputs must not be treated as identical.

`tests/deux-2.2.1.test.cjs` covers native delegation, exact sample counts and
overlap positions, completed-passage reuse, interruption recovery, malformed
results, a failed checkpoint commit, silent input, and closing the separator.
The separate source-clock test exercises the production STFT and ISTFT with
neutral masks, including overlapping joins and an odd final sample count.

## Reproduction

Prepare the pinned graphs with `tools/prepare_deux.py`. Prepare the licensed
source excerpts with `qa/release-1.6.0/prepare-musdb-fixtures.py`, then run
`tools/prepare_deux_fixture.py` to produce the exact PCM16 file and its license
and source provenance. Fixtures are QA inputs and are excluded from the APK.

Run the actual shipped browser separator and save its PCM oracle:

```sh
node tools/benchmark_deux_runtime.cjs \
  --threads 4 \
  --fixture qa/release-2.2.1/fixtures/falcon-mix-pcm16.wav \
  --output build/deux-pcm16-wasm.json \
  --pcm build/falcon-pcm16-wasm
```

Use `tests/NativeDeuxTest.java` for the production Java runtime comparison. Its
predictor reads the PCM16 source at sample offset `-66150`; compare the returned
stem samples `[66150, 366182)` with the two WASM `.f32` files. Preserve these
offsets: the extra samples are the model's source context, not output delay.

`tools/benchmark_deux_native.py` is an optional Python ONNX Runtime CPU proxy
for development. It is not the Android implementation and its timings must not
be substituted for the Java or device receipts.
