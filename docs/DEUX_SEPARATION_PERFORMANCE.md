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

### Resumable exactness evidence (default off)

The optional resumable mode is deliberately an **exactness-only** receipt for a
full, otherwise unmodified comparison that cannot fit in a short-lived worker.
It is not a shortcut for timing the experimental path. Enable it explicitly
with a durable state directory and the two CI-produced immutable source
receipts:

```sh
node tools/compare_deux_preprocess_reuse.cjs \
  --fixture path/to/licensed-long.wav --fixture-provenance path/to/provenance.json \
  --total-samples 661501 --threads 4 --verify-recovery on \
  --evidence-mode resumable-exactness --state-dir build/deux-exactness-state \
  --checkout-identities build/deux-checkout-identities.json \
  --asset-inventory build/deux-asset-manifest.json \
  --output build/deux-exactness-paired.json
```

Each arm writes its report and both raw Float32 PCM files to a uniquely named
staging directory. Only after all three are complete does an atomic rename make
the arm visible, followed by an atomic `complete.json` record containing the
report and PCM hashes. A later invocation rejects an incomplete arm, any
changed report/PCM byte, and any change to the comparator, benchmark runner,
separator, shipped-model/analysis manifests, fixture/provenance, checkout
commit/tree/blob identities, full Deux 27-graph inventory, passage geometry,
thread count, or recovery point. It then rereads raw PCM from every resumed and
new arm before checking baseline/candidate and candidate/recovery byte parity.

The receipt always records `performanceAcceptance.accepted: false` and
`observedWallClockReductionPercent: null` in this mode, including when no arm
happened to be resumed. It is therefore valid only as a durable quality/recovery
proof. The CI workflow uploads the state artifact on every terminal path; a
manual dispatch may supply the exact earlier `resume_run_id` to restore it.
Automatic PR runs always start a fresh state, and cross-tree state is rejected.

### Governed uninterrupted timing mode

Timing acceptance is a separate procedure, not a resumed exactness run. It
must run baseline, candidate, and recovery as three fresh full-model arms in
one uninterrupted parent process on a governed runner, with no `--state-dir`
and no restored arm. Before use, calibrate the worker budget from a completed
full arm and reserve setup time plus three P95 arms and margin. The runner must
record exact hardware/runtime/CPU policy, cache state, and measurable thermal
or energy conditions; otherwise those fields remain unavailable and cannot
support acceptance.

Only repeated, order-balanced baseline/candidate measurements on the locked
corpus under those equivalent conditions can contribute to the release quality
gate. Every timing candidate still requires fresh full-resolution PCM and
recovery parity, differential review, and the existing no-regression rules.
The short-lived GitHub-hosted exactness workflow is intentionally not a
75-percent-speedup or locked-corpus performance claim.

`Deux preprocessing actual-model evidence` is the CI entry point for this
receipt. It reproduces the 27 shipped float32 graphs, prepares the checksummed
licensed fixture, and builds an exact odd-length multi-passage WAV by copying
verified float32 stereo PCM from three distinct licensed MUSDB mix excerpts. It
does not resample, mix, add silence, or use generated audio. The job records
only full actual-model PCM/recovery exactness, then uploads the comparator,
source-provenance, runner-conditions, and resumable state artifacts. It also
records the exact CI checkout commit/tree/blob identities and validates the
explicit Deux runtime subset: separator/DSP/WAV/ORT assets and every
`models/deux/**` file, including the exact 27 graph inventory. The receipt
names the omitted GAME assets rather than claiming a global asset attestation;
the production gate still verifies all 73 assets. The receipts bind only the
exact checkout commit/tree/blob identities recorded by that run. They are not
reusable evidence for a later cache-combined tree; that candidate must rebuild
every source-bound receipt from its own checkout.
