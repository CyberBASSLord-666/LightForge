# LightForge 2.2.4 numerical and browser verification

Release eligibility requires fresh, source-bound results. Historical successful
receipts were not renamed or promoted to this version.

## Scope

- `compare-native-runtime.py`: production Deux inference on Linux/JVM with pinned
  ONNX Runtime 1.23.2 and 1.25.1, one complete 13-second context and two output
  stems. Both results are newly executed against the current production source.
- `test-source-clock.cjs`: production Deux transforms and overlapping chunk
  ownership with neutral masks, including the final odd sample. This is a
  numerical transform/clock test, not neural model inference.
- `compare-native-mdx.py`: actual production `NativeMdxTask` using host Android API
  adapters, compared with the shipped ONNX Runtime Web CPU WASM implementation.
  It exercises model validation, bounded input transfer, real JNI inference,
  both polarity passes, atomic output, production WAV/STFT and waveform decoding.
- `native-mdx-downstream-verification.json`: separately mandatory paired
  downstream voice/model equivalence; its tested input and scope are recorded
  in that receipt. A waveform comparison alone cannot pass the release gate.
- `browser.cjs`, `background-ui.cjs`, `analysis-browser.cjs`: real Chromium UI,
  workers, OPFS, models, composition and cancellation. Android bridges used by
  the UI tests are simulated; physical Android and vehicle coverage is separate.

The three predetermined MDX comparisons are:

| ID | Audio | Input start sample | Input length |
| --- | --- | ---: | ---: |
| `demo-start` | Bundled Glass Castle demo | -3,840 | 261,120 |
| `demo-20s` | Same demo at 20 seconds | 878,160 | 261,120 |
| `falcon-start` | Licensed MUSDB Falcon mixture excerpt | -3,840 | 261,120 |

No gain fitting, time alignment, weight changes, quantization, skipped polarity
passes or altered FFT geometry are used to improve these comparisons.

## Numerical protocol history

The initial exploratory comparator copied normalized-waveform absolute limits
onto unnormalized FFT coefficients. Its absolute spectral comparison failed.
The original comparator, failed receipt and log are retained byte-for-byte in
`initial-mdx-absolute-only/`.

A revised fixed per-coefficient comparison (absolute tolerance `1e-4` plus
relative tolerance `1e-5`) also failed on a small number of coefficients. The
corresponding comparator, numerical helper, failed receipt and log are retained
in `revised-mdx-first-run/`. Those failures are never relabeled as passes.

After reviewing the units and native graph optimizer experiments, the release
contract was explicitly revised to validate the decoded audio consumed by the
remaining pipeline, with a separate mandatory paired downstream model check.
The qualifying run keeps the original native `ALL_OPT` graph settings. The
following normalized-waveform limits are fixed:

| Metric | Maximum |
| --- | ---: |
| Maximum absolute error | `1e-6` |
| Root mean squared error | `1e-7` |
| Relative root mean squared error | `1e-4` |

All spectra must still be complete and finite. Fixed spectral coefficient/RMS
comparisons remain diagnostic results, including their failure counts and
maximum scaled error. `spectral_diagnostic_passed: false` must stay false in the
final receipt and report. A successful decoded-waveform result is not a claim
of exact spectral equality or general model accuracy.

`verify-analysis.py` checks exact receipt digests, all measured source/model
hashes, all three fixed input identities, output sizes, strict waveform limits,
consistent spectral diagnostics, the preserved protocol history, source-clock
results and the separate downstream gate. Missing or failed evidence blocks
release. The complete installed analysis inventory is verified independently.

## Reproduction

Prepare the pinned toolchain and all original model assets with the repository's
bootstrap scripts. Prepare the licensed MUSDB fixtures using the exact archive
hash and `qa/release-1.6.0/prepare-musdb-fixtures.py` before numerical verification.
Then run:

```sh
python3 qa/release-2.2.4/compare-native-runtime.py
node qa/release-2.2.4/test-source-clock.cjs
python3 qa/release-2.2.4/compare-native-mdx.py
node qa/release-2.2.4/verify-mdx-downstream.cjs
```

Run `verify-analysis.py` after the paired downstream harness, and all three
browser scripts separately. The downstream receipt and both retained JSON
model outputs are committed under this QA directory; the verifier recomputes
the complete fixed comparison without requiring scratch files. Fresh measurements have their own timestamps and
runtime timings; a maintainer must review and pin their exact digests in the
verification protocol. Do not automatically replace evidence pins to make a
failed comparison pass. Source changes invalidate measured receipts.

These host tests do not establish ARM64 instruction compatibility, physical
phone performance, every-song transcription accuracy or vehicle timing.
Android lifecycle/diagnostics instrumentation and signed-package checks remain
mandatory, independent release requirements.
