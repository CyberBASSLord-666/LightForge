# GAME audit — exploratory, no app edits

Current adapter keeps GAME Large 1.0.3 float32 weights, 12-second cores with 2-second context, deterministic xorshift noise, all eight diffusion steps, original 44.1 kHz source timing, threshold 0.2, and resets five WASM sessions every four passages. Current numerical interface is unchanged by this audit.

Observed architecture:
- Five models total 393,801,657 bytes; model loading is significant but not dominant in repeated inference.
- Every segmenter neural matrix/conv depends on current diffusion state: all 164 MatMul and 64 Conv nodes. There is no large x_seg-only neural tower to cache. The 64 nodes classified invariant are mostly scalar/shape work; shape-dependency analysis overestimates some dynamic dependence but does not identify a heavy safe cache.
- Returning early when boundaries repeat is invalid: time/noise inputs continue to change and all eight author steps must remain.
- Small JS tensor/noise allocations and note fusion are not the measured dominant cost.
- Four-passage model resets bound allocations; removing them without a long-song heap trace would risk the previous renderer-kill failure.

Raw-output hashes are retained for every graph execution. Every inference uses the same actual 253,440-sample separated-vocal excerpt (5.746 s, sixteen nonempty notes), not silence.

Exploratory CPU measurements overlapped native benchmarking, so do not use their speed ratios as final evidence. The numerical comparisons remain valid.

Exploratory results:
- 1 vs 4 threads: every raw output byte and unrounded note identical.
- 8 vs 4 threads: encoder floats and estimator scores differ; all boundary arrays, durations, note count and final app-rounded MIDI values identical on this fixture. Maximum unrounded MIDI difference 7.62939453125e-6. This fails strict raw-bit parity but is not demonstrated accuracy loss.
- CPU arena+memory pattern: all outputs identical, no convincing speed improvement; do not change the existing memory policy for a noise-level benchmark.
- Exact shape overrides: encoder float outputs and final estimator floats differ; no meaningful speed improvement. Rejected.

Need before release:
1. Controlled no-contention per-graph 1/2/4/8 timing, preserving source/model/runtime hashes.
2. Actual Android worker runtime telemetry: crossOriginIsolated, SharedArrayBuffer availability, hardwareConcurrency and selected/effective WASM threads. Headers alone do not establish effective parallel execution.
3. For any selected candidate, compare each graph output, all eight boundaries and unrounded scores across nonempty real vocals, speech/bleed, quiet singing and at least a five-passage seam/reset fixture. Preserve final fused notes/accents/envelope/contour exactly.
4. Physical phone latency/peak memory and long-song bounded-memory traces, holding models, all context/overlap, sample rate, thresholds and step count fixed.
