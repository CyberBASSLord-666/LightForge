# LightForge 2.4.2 — inference, recovery and release integrity

Android version code: **20402**. This update retains the original signing
identity and the application payload qualified by production run
[40095515106, attempt 1](https://github.com/CyberBASSLord-666/LightForge/actions/runs/40095515106),
source `e82b149b37acd990e699ab7512e9a0afd67d92cd`.

## Changes

- Improve native complete-passage scheduling while preserving original model
  graphs, weights, precision and context. Keep device-local selection conditional
  on repeated timing wins and identical finite output, with bounded cached policy,
  cancellation and native resource retirement.
- Repair completed-project reopening and preview restoration, including stale
  callback fencing and suspension of preview watchdog budgets while the Activity
  is hidden or unfocused. Preserve saved arrangements when loading fails.
- Improve background progress, cancellation/recovery, export handling and compact
  layouts. Retain durable saving and diagnostic job summaries.
- Bound project/backup JSON validation and strengthen UTF-8/grammar checks.
  Update ONNX model-export/build-tool dependencies and tighten release provenance
  and tag verification. Exported original model files remain byte-identical.

## Measured performance, not a whole-phone promise

The registered one-passage host comparison measured **18.8186% lower median
complete-passage time**, from **66.459075114 to 53.952437538 seconds**.
All three measured pairs improved, and all eight complete outputs were
byte-identical. This compared forced four-worker execution with a three-thread
baseline on the same three child CPUs of a four-CPU-capacity host.

The immutable producer was
[run 40085980189, attempt 1](https://github.com/CyberBASSLord-666/LightForge/actions/runs/40085980189).
Final candidate admission checked its registered proof and unchanged execution
closure; the benchmark was not rerun to select a favorable outcome.

This is **not** an Android, whole-song, automatic device-selection or eight-worker
performance measurement. It is not an additional gain over the historical 2.4.1
32.6% result or earlier experimental 43.6% result, which used different conditions.
The 75% whole-analysis goal remains unverified.

## Verification and limits

Fresh source-bound regression, browser, background UI, completed-preview recovery,
actual-model and native gates passed for this candidate. Packaged Android emulator
background/lifecycle and diagnostics checks passed with the CI signing identity;
the original release signature and unchanged application payload are verified
separately. The accompanying `release-verification.json` identifies the candidate,
receipts, hashes and scope.

Model comparisons are bounded tests, not a general accuracy guarantee. Mandatory
MDX decoded-waveform/downstream checks passed while retained internal spectral
diagnostics remain failed; exact spectral parity is not claimed. GAME final-output
and checkpoint comparisons passed while intermediate differences remain recorded.

The version-specific publication policy is automated-verification-only. Physical
phone installation, vehicle observation, representative whole-song quality,
thermal behavior, energy use and sustained device performance remain unverified.
The preview is a command simulation with estimated physical appearance and motion,
not a certified digital twin. Security work and advisory audits are scoped; no
claim that all vulnerabilities or all research dependency ranges are resolved is
made.

Install the original-signed APK over the existing app to retain projects. Use the
published APK checksum and verification report to confirm the exact download.

Bundled model restrictions remain: Deux CC BY-NC 4.0 and GAME CC BY-NC-SA 4.0.
LightForge is not an official Tesla product.
