This directory contains the current-release harnesses for LightForge 2.2.5. No 2.2.4 passing result has been copied into a current gate.

The existing seven packaging gates remain required: regression, browser, native, analysis-browser, analysis, Android background, and Android diagnostics. The version-driven production workflow already invokes the four browser/source-clock scripts and `verify-analysis.py` here. `tools/verify_v2.py` now includes the actual GAME pool component suite.

The analysis gate binds:

- A fresh 932,143-sample source-clock run across four overlapping passages, including seam impulses and the final odd sample.
- Every current analysis asset, with model weights, configuration, and WebAssembly runtime bytes checked against the published 2.2.4 evidence.
- Exact MDX FFT spectrum/decoded-PCM comparisons on three real inputs and deterministic edge-value stress input.
- The final production native thread policy on two real inputs, with complete output hashes and retained execution logs.
- Exact fresh/restored role-cache composition, current source bindings, retained output JSON, and the complete recovery-test run.
- Actual Android execution of the production GAME pool adapter, once the qualification artifact and final receipt adapter are available.

`proof-inputs.json` points to the original proof schemas. Missing or failed inputs block the release. The current `analysis-verification.json` is explicitly pending; it is not a passing receipt. The Android GAME adapter currently fails closed while its on-device artifact schema is pending. Separate-process host scheduling exploration cannot satisfy it.

The old 2.2.4 model/runtime measurements and failed MDX spectral comparisons remain historical and are hash-bound without relabeling their execution as current. The unchanged MDX bridge is not subjected to a new cross-runtime claim. The FFT receipt's invalidated timing status remains visible; exact numerical comparisons do not convert overlapping timings into controlled performance evidence.

Run the current source-clock test with `node qa/release-2.2.5/test-source-clock.cjs`, then `python3 qa/release-2.2.5/verify-analysis.py` after qualification inputs arrive. Both replace stale success with a failing result when verification fails. Full-browser and Android lifecycle execution remain independent mandatory gates.

No physical-phone throughput, new corpus-accuracy benchmark, or Tesla timing claim follows from this scaffold.
