# Next complete-analysis boundary — September 24, 2026

This handoff is a read-only map of existing implementation and retained evidence.
Inspected source: commit `2c2a1d1693c5a3ef32c9c6ac86c2a195a1e24b35`, tree
`653071d400786cd5262e4f19dbf2bf903467d310`. The files listed below match their
Git blobs at that commit. No next-stage inference or reference reuse was executed.

The complete 64-second GAME experiment exercises the public **mixture**. It does
not supply GAME outputs for either arm's separated vocal waveform. The missing
integrated boundary is complete Deux inference → production overlap and
checkpoints → verified stem cache → the complete vocal stage.

## Existing components

| Purpose | Source | Existing capability and boundary |
| --- | --- | --- |
| Original native Deux CPU/CUDA | `tools/benchmark_deux_accelerator.py`, `tests/NativeDeuxExecutionBenchmark.java`, `android/src/com/cyberbasslord/lightforge/NativeDeux.java` | The qualified harness binds original graphs, runtime, source and complete two-stem output, with exact plain/profiled observer checks. `--start-sample` selects one complete 13-second passage; it does not collect the whole source. |
| Production overlap and checkpoints | `web/analysis/separator-deux.js`; tests in `tests/deux-2.2.1.test.cjs` | `create(...).process(...)` owns passage scheduling, native callbacks, silence handling, checkpoint writes/restoration, complementary crossfades and exact source-clock emission. Preserve this implementation rather than reimplementing its arithmetic. |
| Complete-source WASM separation | `tools/benchmark_deux_runtime.cjs` | Already drives the unchanged separator over a full supplied WAV and retains complete stems. It is WASM-only and does not exercise the native/CUDA capture boundary or checkpoint resume. Its historical PCM comparison limits do not authorize CUDA equivalence. |
| Retained downstream sensitivity | `tools/compare_deux_downstream.cjs` | Replays the original consumer only to the first committed five-second chunk, then runs real Frame-MN10, GAME, detail extraction and fusion on that excerpt. It deliberately stops when the second captured passage is absent. |
| Exact stem cache and resampling | `web/analysis/stem-cache.js`; tests in `tests/stem-cache.test.cjs` | `DownsampleWriter` produces centered 22.05 kHz stems; `FloatWriter` preserves full-resolution voice. Completed-cache hashes and original sample counts are validated before reuse. |
| Complete vocal stage | `web/analysis/worker.js`, `web/analysis/vocal.js`, `web/analysis/vocal-detail.js`, `web/analysis/game.js` | Runs full-context classification, eight-second source-detail chunks, full-rate GAME, detail fusion, optional semantic enrichment and saved voice. GAME must receive each arm's actual complete separated voice, with unchanged windows and seeds. |
| Complete analyzer and measurement | `qa/release-2.3.2/analysis-browser.cjs`, `qa/release-2.3.2/analysis-performance.cjs`, `web/analysis/analyzer.js` | Existing browser verification executes actual workers, models, OPFS, rhythm/separation/voice/bass, optional recurrence and downstream compilation. Its fixed licensed fixture and verification outputs are not a ready CUDA benchmark; a separate research harness must connect real native callbacks and bind actual runtime identity. |

For the public 64-second source, the production Deux plan has **12 passages**:
`startSample = -66150 + i × 220500`, for `i = 0..11`. Every inference retains
573,300 samples per stem: 13-second context, 1.5-second halo, 10-second core and
5-second stride. The consumer emits eleven five-second chunks and a final
nine-second chunk, totaling 2,822,400 samples. Original zero-padding, silence
handling and checkpoint behavior remain part of that contract.

## Retained CPU reference: first passage only

No completed 64-second CPU Deux stems or twelve-passage checkpoint set were
found in the inspected repository. The search covered current retained JSON
records, local stem/Float32 filenames and Git history for those binary names.
This is not a claim about uninspected external storage.

The September 24 `deux-t4` archive was reassembled in memory without inference;
all 68 part hashes and the complete archive hash were checked. Its CPU plain and
profiled first-passage bytes were read and independently verified:

| Binding | Value |
| --- | --- |
| Archive | `research/performance/2026-09-24/deux-t4/raw/manifest.json` |
| Archive bytes / SHA-256 | `50841267` / `87e4e7010c62db52b30ea881d18b62ae3e5c93a415db618ca184ddab6041be47` |
| Public WAV SHA-256 | `33f07d502ba19832b62b97d8fb4a11354e81310264bd885d7a06438228773650` |
| Captured source offset | `-66150` |
| Each complete two-stem output | `4586400` bytes, SHA-256 `b5db5b5f8bcc576e1af22b0a9fca837dc9e809195ada006af1581458283578b7` |
| Original model manifest SHA-256 | `6aebf45e6e7f6fa974f14fe47a252fc01f48da4815f40a1fdf10641a432529a9` |
| ORT CPU 1.25.1 JAR SHA-256 | `749793ebed63743fec853d093da7987a86ea5cd592d54fba898cd3233100c381` |
| Original `NativeDeux.java` SHA-256 | `084fec27d1fad0b10db01a960c614d333bb8c049e712c3fc4524d66e6dc3dd37` |

The archive members are
`20260924T020341Z-deux-a6f78d49/qualification/cpu_all/qualification-0.f32`
and `20260924T020341Z-deux-a6f78d49/qualification/cpu_all_profiled/diagnostic-0.f32`.
All source bindings in its primary receipt match the inspected implementation;
the current 27-graph manifest and CPU runtime host pin match as well. This pair
can support a provenance-preserving retrospective consumer check. It cannot
stand in for the absent eleven passages or a fresh complete-run timing.

Historical `qa/release-2.2.1/deux-native-java.json` covers 300,032 samples of a
different 6.8-second fixture with ORT 1.23.2. The corresponding WASM results and
older PyTorch excerpt references do not provide the missing current reference.
`tools/benchmark_deux_native.py` is a NumPy/ORT proxy limited to ten seconds,
not an original-Java complete-source replacement.

## Execution and timing qualifications

A complete consumer experiment must retain every measured passage, execute the
unchanged overlap/checkpoint path to completion, preserve both stems and
full-resolution voice, and compare a genuine checkpoint resume. A separate
full-vocal run must infer on those actual separated inputs. Preserve exact
observer checks, source/model/runtime/input hashes, unrounded notes and raw
outputs; do not apply a new tolerance to promote observed differences.

Captured-output replay validates consumption and recovery, but excludes model
execution and cannot measure complete analysis. A true measurement must run the
actual full analyzer and count cold start, inference, transport, verification,
checkpoint persistence, failed attempts and recovery under explicit comparable
cache conditions. Existing native adapter output labels say Android CPU; retain
those adapter fields and report actual research CPU/CUDA identity separately.
Use a distinct bound execution/cache profile rather than reusing an Android CPU
identity for CUDA.

The retained Deux cross-provider status remains
`NUMERICAL_EQUIVALENCE_UNPROVEN`. Public-fixture diagnostics, exact downstream
transcription or a completed GAME run do not approve musical quality, an
accepted speed ratio, Android/physical-device performance, publication or the
75% complete-analysis target. Existing locked-corpus and source-bound policy
requirements remain unchanged.
