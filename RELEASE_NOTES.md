# LightForge 2.4.1 — measured native inference

Final production host measurements show **32.6% lower median native passage
time**, from 65.3 to 44.0 seconds, with byte-identical complete outputs.

An offline Android update focused on the native neural-inference bottleneck.
Install the original-signed release APK over the existing app to retain projects.
The qualified download is published through GitHub Releases after the complete
source-bound production and Android gates pass.

## Changes

- Run independent temporal bands concurrently using private buffers and the
  original graph, assigning the next band as each worker slot finishes. Measure
  temporal and frequency scheduling on the actual device.
  A candidate must produce identical finite Float32 tensors and win all three
  alternating timing pairs, including at least 10% lower median trial time.
  Otherwise retain the existing configuration.
- Cache the complete decision against model, runtime, OS and device identity.
  The first uncached Studio passage pays the calibration cost; later passages
  and jobs reuse it. Cache corruption or identity changes trigger fresh checks.
- Preserve original model graphs, weights, Float32 precision, full context and
  all production inference work. The full parallel path executes 875 one-band/other
  calls versus the reference's 335 batched/other calls. Keep one native session resident at a time,
  cancellation, confirmed retirement and crash-lease ownership.
- Retain bounded summaries for three recent jobs independently of trace rotation.
  Include final saving, stage durations, recovery gaps, native route totals and
  separate calibration overhead. Report calling-thread and process CPU honestly.
- Add native GAME session and graph timings. Its experimental tuning options
  failed numerical or consistent-performance checks and remain disabled.

## Performance and verification scope

Temporal admission compares all 60 bands of a real graph; frequency admission
compares a real frequency batch. Neither threshold measures total analysis time.
The release prerequisite used one excluded warmup pair and three alternating
measured pairs. Reductions were 28.1%, 28.8%, and 36.2%. All eight complete outputs
were finite and byte-identical. Median process CPU increased 5.7%, and peak RSS
increased from 817 to 1,032 MiB; device memory admission bounds parallel execution.
Both variants used the same seven host CPUs, leaving one CPU of quota for
platform work. The eight-worker fixture is a host execution test, separate from
Android's device-local admission.

The 75% speedup remains an aspirational objective. These measurements do not
establish sustained device performance; phone thermal behavior, battery use and
whole-song acceleration remain unmeasured. Earlier failed and mixed attempts
remain in the [investigation record](research/inference-2.4.1/DEUX_PARALLEL_B1.md).

The release requires fresh full-model reference/calibrated/cached output
comparison, original graph-call coverage, policy persistence and cancellation
checks, plus the existing browser, model, storage, export and Android lifecycle
gates. No older release receipt can qualify changed application bytes.

ONNX Runtime remains pinned to 1.25.1. A newer-runtime experiment was excluded
after an unapproved telemetry connection. No model or runtime download is
introduced in the application.

The 2.4.0 musical continuity, bilateral gestures, source-clock and vehicle-preview
work is retained. The preview remains a source-backed command simulation with
estimated physical appearance and motion, not a certified digital twin.

The version-scoped automated-verification policy keeps physical phone/car and
external perceptual/corpus observations optional without establishing their
unmeasured claims. Original update signing and exact qualified payload integrity
remain mandatory.

Bundled model restrictions remain: Deux CC BY-NC 4.0 and GAME CC BY-NC-SA 4.0.
LightForge is not an official Tesla product.
