This directory contains the current-release harnesses for LightForge 2.2.5. No 2.2.4 passing result has been copied into a current gate.

The existing seven packaging gates remain required: regression, browser, native, analysis-browser, analysis, Android background, and Android diagnostics. The version-driven production workflow already invokes the four browser/source-clock scripts and `verify-analysis.py` here. `tools/verify_v2.py` now includes the actual GAME pool component suite.

The analysis gate binds:

- A fresh 932,143-sample source-clock run across four overlapping passages, including seam impulses and the final odd sample.
- Every current analysis asset, with model weights, configuration, and WebAssembly runtime bytes checked against the published 2.2.4 evidence.
- Exact MDX FFT spectrum/decoded-PCM comparisons on three real inputs and deterministic edge-value stress input.
- The published 2.2.4 NativeDeux, transform, runtime and source-test bindings, unchanged in this release.
- Exact fresh/restored role-cache composition, current source bindings, retained output JSON, and the complete recovery-test run.
- Actual Android execution of the production GAME pool adapter, with exact raw graph outputs, all eight transcription steps, actual parent/child overlap, checkpoint equality, cancellation, guarded restart, and five fresh admissions satisfying the 6 GiB available-memory policy.

`proof-inputs.json` points to the original proof schemas for the shipping FFT, role-cache and Android GAME changes. Missing or failed inputs block the release. The Android adapter validates the collector's concrete raw schema and the retained files under `qa/speedup-exact/game-pool/android/`; until a successful artifact arrives, the analysis gate remains pending. Separate-process host scheduling exploration cannot satisfy it.

The eight-thread native experiment is **not shipping** and remains **unqualified for the target ARM runtime**. Its successful x86_64 measurements, candidate source snapshots, architecture review, and release decision are retained without rebinding their original production paths to the restored native implementation. No actual Deux divergence was demonstrated; the target dispatch, prepacking, and front/head kernels were not qualified under the user's exact-output requirement.

The old 2.2.4 model/runtime measurements and failed MDX spectral comparisons remain historical and are hash-bound without relabeling their execution as current. The unchanged MDX bridge is not subjected to a new cross-runtime claim. The FFT receipt's invalidated timing status remains visible; exact numerical comparisons do not convert overlapping timings into controlled performance evidence.

Run the current source-clock test with `node qa/release-2.2.5/test-source-clock.cjs`, then `python3 qa/release-2.2.5/verify-analysis.py` after qualification inputs arrive. Both replace stale success with a failing result when verification fails. Full-browser and Android lifecycle execution remain independent mandatory gates.

No physical-phone throughput, new corpus-accuracy benchmark, or Tesla timing claim follows from this scaffold.
