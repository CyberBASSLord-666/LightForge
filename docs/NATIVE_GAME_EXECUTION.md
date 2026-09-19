# Native GAME execution and Deux allocation changes

This documents the **2.3.2 candidate**, not a published release or a production
qualification receipt. Publication still requires the current protected checks
and a version-specific, exact-source release request.

## What changes

Android can run GAME singing transcription through the pinned ONNX Runtime
1.25.1 CPU backend. The optional adapter retains the original five hash-verified
Float32 graphs (`encoder`, `dur2bd`, `segmenter`, `bd2dur`, `estimator`), eight
diffusion steps, language input, thresholds and deterministic xorshift noise.
It does not quantize, specialize, replace or retrain the models.

The shared JavaScript pipeline still owns the 44.1 kHz PCM clock, 12-second core
windows, two-second context on each side, and per-passage seed
`(2025 + passageIndex * 104729) >>> 0`. Passages remain at most 16 seconds.
Android returns unrounded passage-local notes. Their finite values, pitch range,
time bounds, duration and order are validated before checkpointing and the
unchanged continuation handling, clipping, sorting and rounding logic. Audio
remains on the device; this change does not add a remote processing service.

Separately, native Deux enables the CPU arena and memory-pattern optimization
within each graph session. The existing graph-by-graph session lifetime, original
27 graphs, Float32 processing, 13-second context and all 335 inference calls
remain unchanged. Its native cache profile advances to
`native-deux-onnxruntime-android-1.25.1-v2` so older execution evidence is not
silently reused under the changed allocation configuration.

## Fallback and recovery boundaries

Without an admitted native GAME callback, the existing WASM implementation is
used. Native GAME uses profile
`native-game-onnxruntime-android-1.25.1-v1`. Execution identities distinguish
GAME alone, native Deux plus GAME, native MDX plus GAME, separator-only native
execution, and all-WASM execution; combined profiles preserve that same order.
Completed work is reusable only under its verified matching implementation and
execution identity.

If an admitted native GAME passage becomes unavailable or fails validation,
the worker invalidates GAME and dependent voice/bass/recurrence checkpoints.
Native cancellation and resource retirement must be confirmed, and the full
attempted execution identity must be durably recorded, before the analyzer
restarts under the separate all-WASM namespace. A failed cache fence, failed
lineage write or unconfirmed native retirement stops the attempt instead of
mixing native and WASM evidence. Cancellation is not a fallback success.

## Observed evidence and limits

| Observation | What it establishes | What it does not establish |
| --- | --- | --- |
| Public 64-second demo: 98 identical final stitched notes; licensed vocal excerpt: 11 identical final stitched notes | Exact final transcription equality for those exercised inputs and production window/seed plans | General musical quality, lyric alignment, complete-analysis equivalence or physical-device behavior |
| Small raw pitch/feature Float32 differences across native and WASM backends | Raw numerical equality is not claimed, even when the shared final rounding yields identical notes | Automatic quality approval or permission to discard numerical differences |
| Three measured paired Deux host passage comparisons: approximately 11.8%, 11.0% and 17.3% lower wall time; approximately 1.6% higher median peak RSS | A measured host allocation tradeoff for the tested unchanged passage computation | Android speed, whole-song/app latency, battery use, thermal behavior or a 75% speedup |
| Earlier GAME prototype graph-inference timing observations | Feasibility evidence for moving the unchanged graph work to the native backend | A repeated production-engine or whole-application performance benchmark |

The Deux comparison checks complete finite output equality; the GAME comparison
keeps raw numerical differences separate from final-note equality. Neither the
small fixture set nor the prototype timings establish the project's 75%
performance target. Android integration tests and host graph execution are also
not measurements on the user's phone or Tesla.

See the [GAME comparison harness](../tools/game_benchmark/README.md) and
[native execution benchmark](NATIVE_EXECUTION_BENCHMARK.md) for source, model,
input and timing scopes. Their outputs are evidence inputs, not signing authority
or release approval. No receipt or independent sign-off is created by this page.

## Publication remains separate

The [build and release process](../BUILD.md), current full production and Android
verification, exact-candidate integrity checks and original signing identity
remain required. This execution change does not weaken protected rules, replace
an already published version, or make an ephemeral CI signature publishable.
External-measurement exceptions apply only where the source-bound approved
release policy explicitly permits them; this document creates no new exception
or additional performance publication prerequisite. **2.3.2 is not yet released.**
