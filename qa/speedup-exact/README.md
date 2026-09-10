# Analysis speed qualification for 2.2.5

The comparison rule for these changes is exact output bytes. The reference is the published 2.2.4 implementation, with the same models, float32 computation, source windows, overlap, eight GAME diffusion steps, thresholds and passage seeds. Passing a fixed corpus is evidence for those inputs and runtimes; it is not a universal accuracy proof or a physical-phone benchmark.

## Implemented changes

| Change | Evidence | Scope |
| --- | --- | --- |
| MDX forward FFT computes only the 3,072 frequency bins already consumed by the model | `mdx-fft-verification.json`: exact 3,145,728 spectral values and 261,120 decoded samples in each of four real/stress cases | Same 7,680-point transform and consumed arithmetic. The inverse still computes every bin. Current receipt timings overlapped other checks and are explicitly unqualified. The earlier controlled frontend-only probe measured 44% less time; inference was excluded. |
| Rhythm edits reuse independently keyed separation, voice and bass work | `cache/verification.json` is generated against the final source | Native identities hash both decoded WAV files. Sensitivity and BPM still invalidate rhythm. The restored bass checkpoint contributes only bass fields to the current result. This avoids repeated model work after edits, without accelerating a first analysis. |
| GAME processes two independent passages using the existing worker and one child | Actual Android production-adapter qualification is required before release | Both lanes use the same single-thread WASM engine. Admission requires a fresh memory snapshot, a 64-bit process, at least four cores, at least 7 GiB total RAM and 6 GiB available RAM, and no low-memory signal. Results become durable independently and are stitched in source order. Failure disables pooling for that audio/app version and retries retained PCM serially. |

## Retained experiments

`native-threads/` retains the candidate eight-thread Studio experiment. Two real passages were byte-identical on Linux x86_64 and took 16.8% and 20.8% less time. The candidate is not shipping: architecture-specific ARM64 dispatch, prepacking and optimized front/head kernels were not qualified for exact output. Production retains its published four-thread cap.

The maximum-frame-boundary GAME estimator stress reached 2.262 GiB for one 16-second lane, making 4 GiB freshly available RAM insufficient for two lanes. The admission threshold was raised to 6 GiB. This artificial boundary case is a memory stress test, not an additional music-quality comparison. Its process-reported RSS is retained with the original failed external monitor clearly disclosed.

`game-threads-controlled.json` measured unchanged raw graph outputs with one, two and four WASM threads on the host. The Android CPU probe retained under `android-cpu/` observed only one effective thread in WebView 124 on the tested API 35 emulator, despite the production isolation headers. That observation does not describe every WebView version or phone.

The earlier two-process GAME experiment measured 1.80× throughput for two real excerpts. It predates the production child-worker adapter and does not qualify its Android memory, cancellation or timing behavior.

Native GAME execution, including a version-matched runtime, changed low-order encoder and estimator outputs. Eight-thread GAME and graph-shape specialization also changed raw values. These routes were rejected. The original findings remain in `game-native-rejected.md` and its receipt. Larger native Studio batches were exact but slower; parallel native Studio instances provided too little gain for their memory cost and were not adopted.

The 2.2.4 native/WASM MDX spectral differences remain in the historical release evidence. These new exact comparisons do not relabel those differences as passes or change their acceptance protocol.

## Release status

The signed 2.2.5 update is not yet qualified. Android production-pool execution and the complete seven release gates must pass against the final source before publication. Physical ARM64 byte identity, sustained phone thermals and full-song throughput have not been measured here.
