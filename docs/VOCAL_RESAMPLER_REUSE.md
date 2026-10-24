# Exact vocal resampler reuse

Vocal analysis retains one ten-second passage of source Float32 bits and
resampled output. Each passage still performs the same 22.05 kHz reader request,
including the original halo and zero padding. Reuse requires matching absolute
integer output coordinates and every source Float32 bit contributing to all 64
taps of the overlapping output interval. This preserves global rational phase,
coefficient values, summation order, Float32 rounding, irregular final passages,
and short-source padding. Changed input, including a signed-zero change, rejects
the entire candidate overlap. Non-Float32 input bypasses reuse.

The cache owns source and output snapshots so caller mutation cannot invalidate
its evidence. It belongs to a single analyze call and is cleared in the existing
finally path on success, cancellation and failure, before model release.
Reader/resampler errors also clear it. It retains at most 1,522,264 array bytes
(one source halo and one output window); this is not peak application memory.
Oversized windows are processed normally without retaining a cache. The existing
mel cache is separate and unchanged.

Diagnostics count vocal.resampler.reusedSamples and
vocal.resampler.computedSamples through the existing telemetry interface.
VocalResampler.retainedBytes exposes current retained array bytes for focused
tests and benchmarks.

## Verification and scope

The committed focused tests compare resampling output against a frozen project
reference, including rational phases, padding, source mutation, typed-array
subviews and cleanup paths. The model-verification tool runs both production
analyzers through the retained Frame-MN10 model and compares model inputs, raw
outputs, source reads and final results. It captures source, runtime, model and
fixture identities before execution and refuses a receipt if they change.

Newly generated benchmark and comparison records remain local and are not
included in this source-only public update. Reproduction requires the original
pinned model/runtime and fixture. Host observations cannot establish Android,
complete-song, musical-quality or release qualification. Mandatory broader
pipeline, native, browser and release checks remain in force.

Reproduce into a new receipt:

```sh
node --test tests/vocal-resampler-reuse.test.cjs tests/vocal-frontend-reuse.test.cjs
node --expose-gc tools/benchmark_vocal_resampler.cjs --output /tmp/resampler-new.json
node tools/verify_vocal_resampler_model.cjs --output /tmp/resampler-model-new.json
```

The frozen oracle is this project's own code and exists only for verification.
No new dependency, reduced-quality model, source read skipping, concurrent
inference or phase approximation is introduced.
