# Deux separation performance investigation

## Status

This is an investigation and diagnostic change, not an accepted runtime
optimization. The experimental overlap-spectrum reuse path is **off by default**
and can only be requested with
`options.experimentalDeuxSpectrumReuse === true`. It must not be enabled by
default until the paired actual-model gate records exact final PCM identity,
recovery identity, repeatable fresh-process measurements, and a passing quality
gate on the locked corpus.

The current full-analyzer evidence identifies the right bottleneck:

| Fresh-process full analyzer evidence | Seconds | Share of 400.3 s |
| --- | ---: | ---: |
| Deux source separation | 359.37 | 89.8% |
| Voice analysis | 36.08 | 9.0% |
| Remaining analysis | 4.85 | 1.2% |

This evidence is not a speedup claim. It motivates the subspan profiler below.
The run used a fresh analyzer process, but its kernel file-cache and thermal
state were not recorded; it is not evidence of a controlled cold-I/O comparison.

## What is measured

`LightForgeDeux.createPerformanceProfile()` records bounded aggregate spans
without changing model selection, graph order, tensor shapes, context, overlap,
sample rate, or inference precision.

| Span family | What it isolates |
| --- | --- |
| `manifest.load` | Manifest fetch and parse |
| `passage.read`, `passage.peak` | PCM I/O and silence scan |
| `transform.encode`, `transform.decode` | FFT/STFT and inverse transform |
| `session.create`, `session.release`, `session.run` | Model initialization, teardown, and awaited graph execution |
| `tensor.*.pack/copy/scatter`, `mask.allocate` | JavaScript allocation and layout transfer |
| `checkpoint.*`, `passage.stitch`, `chunk.emit` | Recovery I/O, overlap-add, and stem delivery |

The profile reports wall-clock time. CPU time, allocator pressure, and
accelerator utilization are explicitly marked unavailable where a browser worker
does not expose a portable counter; it never substitutes guessed values. The
profile is attached to the precision separator result as
`performanceProfile` and includes deterministic counters such as session
creates/runs and encoded/reused STFT frames.

## Experimental exact preprocessing reuse

Adjacent Deux passages advance by 220,500 samples, exactly 500 STFT hops. The
transform’s local reflection means only this mapping is safe:

| Previous passage frames | Next passage frames | Treatment |
| --- | --- | --- |
| 503–1297 | 3–797 | Reuse the same complex Float32 spectra |
| 0–502 and 1298–1300 | 0–2 and 798–1300 | Recompute |

That retains all 13-second context and recomputes 506 of 1,301 frames. It never
reuses reflection-boundary frames, skips no graph, and remains disabled after a
checkpoint restore, silent passage, native predictor, interruption, nonadjacent
passage, or final passage.

Persistent graph-session caching is deliberately not enabled. The current
lifecycle creates/releases 27 graph sessions per passage; retaining them without
measured memory and exact-output evidence risks a much larger memory footprint.
Likewise, `TypedArray.slice()` inputs remain copies until ONNX Runtime Web
ownership/retention behavior is demonstrated safe under the same gate.

## Reproduction and acceptance

Fast deterministic geometry and gate tests:

```sh
node --test tests/deux-preprocess-reuse.test.cjs \
  tests/deux-preprocess-comparison.test.cjs \
  tests/deux-2.2.1.test.cjs
```

Run each fresh Node process separately on a licensed fixture longer than two
passages. Process isolation resets the JavaScript runtime and model sessions,
but does not reset the host kernel's file cache; that state must be reported as
uncontrolled rather than relabeled as a cold-I/O condition:

```sh
node tools/benchmark_deux_runtime.cjs \
  --fixture path/to/licensed-long.wav --total-samples 661501 \
  --threads 4 --spectrum-reuse off --output build/deux-cold-baseline.json

node tools/benchmark_deux_runtime.cjs \
  --fixture path/to/licensed-long.wav --total-samples 661501 \
  --threads 4 --spectrum-reuse on --output build/deux-cold-candidate.json
```

`661501` is intentionally odd and requires a fixture at least that long.
The paired gate runs separate fresh-process baseline and candidate invocations
of the same full shipped model with both settings, requires finite stems and
byte identity for both roles, binds the benchmark/source/model/ORT/session
configuration, and optionally injects a post-checkpoint interruption followed
by resume:

```sh
node tools/compare_deux_preprocess_reuse.cjs \
  --fixture path/to/licensed-long.wav --total-samples 661501 \
  --threads 4 --verify-recovery on \
  --output build/deux-preprocess-paired.json
```

The comparison rejects a different source, model manifest/checkpoint, fixture,
thread count, sample count, even final length, insufficient passage count,
missing cache use, nonfinite output, a single changed PCM byte, or a recovery
that fails to restore a completed checkpoint. Recovery runs require at least
three passages, so one post-restore local passage can establish the cache and a
later passage can exercise it. Its one-pair timing value is diagnostic only; it
is not sufficient to declare a quality-preserving speedup.

`Deux preprocessing actual-model evidence` is the CI entry point for this
receipt. It reproduces the 27 shipped float32 graphs, prepares the checksummed
licensed fixture, and builds an exact odd-length multi-passage WAV by copying
verified float32 stereo PCM from three distinct licensed MUSDB mix excerpts. It
does not resample, mix, add silence, or use generated audio. The job runs both
arms and a controlled recovery in one Ubuntu job, then uploads comparator,
source-provenance and runner-conditions receipts. It also records the exact CI
checkout commit/tree/blob identities and validates the explicit Deux runtime
subset: separator/DSP/WAV/ORT assets and every `models/deux/**` file, including
the exact 27 graph inventory. The receipt names the omitted GAME assets rather
than claiming a global asset attestation; the production gate still verifies all
73 assets. It proves only actual-model PCM/recovery equivalence for this
experiment. It does not turn an uncontrolled filesystem-cache state, one pair,
or a single fixture into a target-speed or locked-corpus quality-gate pass.
