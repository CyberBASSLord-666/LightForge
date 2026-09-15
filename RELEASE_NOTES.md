# LightForge 2.2.5 — release candidate

LightForge 2.2.5 / Android version code 20205 contains the current merged work. Full automated candidate verification has passed. Original-key APK signing and compatibility verification have passed; protected performance/quality qualification and publication remain pending. Physical phone and Tesla observations are optional.

## Candidate changes

- Build a validated music timeline with confidence, source provenance and deterministic salience rankings on the original audio clock. Bass tracking retains its accompaniment-source provenance.
- Accept explicitly supplied percussion evidence and provide experimental, opt-in mix-based kick/snare/hat estimates with confidence and salience caps.
- Add opt-in rhythm hierarchy, acoustic vocal expression and recurrence metadata. Explicit semantic, vocal and motif planning settings consume validated matching evidence and retain the applicable base plan when that evidence is missing, stale or invalid.
- Rescue fully suppressed high-salience impact and movement-arrival light accents on available compatible outputs without moving accepted cues. An additional opt-in semantic allocation mode supports explicit fallback groups while retaining collision and output constraints.
- Attach read-only choreography and perceptual reports covering density, repetition, output use, collision losses and event realization. Estimated response timing and measured timing remain distinct.
- Support explicitly enabled local vehicle timing calibration with recorded provenance and bounded values. Unconfigured profiles keep their existing schedule and label travel assumptions as unverified planning estimates.
- Enforce 15 ms or 20 ms FSEQ frame intervals consistently through generation, validation and export.
- Serialize heavy analysis jobs, preserve matching resumable stages and strengthen checkpoint, stem and shared-feature integrity checks. Reject stale or corrupt cached work and rebuild affected results from valid inputs.
- Harden native buffer cleanup, cancellation and compatibility fallback so subsequent runs cannot reuse invalid resources or stale checkpoints from failed or retiring work.
- Restore completed projects in the foreground using fresh session-bound verification.
- Load losslessly precomputed HDR studio lighting when the full vehicle preview starts or recovers its graphics context. This removes runtime lighting convolution while retaining the original lighting appearance and first-frame acknowledgement checks.
- Record bounded preview startup timings and isolate the disposable Android verification emulator from unrelated system downloads. Existing lifecycle, frame-commit and readiness checks retain their original deadlines.
- Preserve explicit unverified status when physical phone or Tesla observations are absent.

## Release verification and signing

- Validate CPU utilization, energy, temperature rise and accelerator utilization against same-run raw counters. Missing measurements remain unobserved; invalid or mismatched paired counters fail validation.
- Enroll the owner's public policy-authority key and provide a private local policy/corpus signing helper. The Android update signer, policy authority and authenticated human-review verifier remain separate identities.
- Transfer the exact verified candidate in bounded parts for original-key signing. Verify every non-signature APK payload and reconstruct the signed APK from a digest-bound public delta.
- Isolate release reconstruction from privileged publication, and verify source-bound CI evidence and uploaded release-asset digests.
- Retain the required protected performance/quality gate, including genuine paired measurements and blinded human review. Passing its unit tests is not release qualification.

## Candidate status

The latest published update remains [LightForge 2.2.4](https://github.com/CyberBASSLord-666/LightForge/releases/tag/v2.2.4). The complete [main verification run 34939857731](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34939857731) passed for commit `f2a1c65f35efbfd43b0bd7832bde3f42ea7abe79`, including the host/browser/model/APK job, all ten Android lifecycle checks and all eight Android diagnostic/export/recovery checks. Completed-project reconnection passed with the existing first-frame and hardware-frame requirements and unchanged deadlines.

Four full-vehicle WebGL comparisons of the preview lighting were pixel-identical, and actual graphics-context recovery passed. The verified candidate was transferred for private original-key signing in [run 34944128303](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34944128303). The APK is now signed with the original certificate and has a verified `update_compatible: true` receipt. All 148 non-signature payload entries match the CI candidate, and the signed-APK delta reconstructs its exact SHA-256 digest, `67a4de0619b786bbf9ca956bdb778c775ac233db2a8123cf8c13868bce653b39`. The genuine protected performance/quality comparison is still required before publication. These results establish their stated test coverage only; no physical-device or vehicle behavior is claimed.

## Published LightForge 2.2.4 release notes

### Changes

- Run Balanced MDX separation through a guarded native Android CPU path, retaining both polarity passes and the existing waveform decoder. Compatibility fallback uses the same model and retries a complete pair in one runtime.
- Bound WebAssembly model lifetimes between passages and stages, reuse large transform buffers, and release native resources before voice/GAME processing. GAME retains all eight transcription steps.
- Update native ONNX Runtime to pinned 1.25.1. A confirmed native crash selects compatibility processing on the next Resume; completed matching work remains reusable.
- Save passage/stage checkpoints promptly and report partial progress accurately. Cancellation retires native work through a shared execution gate before another separator allocates its models.
- Restore completed projects once across competing startup events. Suspend paused preview animation and defer empty-scene rendering until the model and view are ready, preserving the tested final graphics.
- Improve native crash reports and renderer recovery while retaining local-only diagnostics and user-controlled export.

### Verification and limits

All seven release verification gates passed in the complete [production run](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34424617050). Android 15 emulator checks completed Studio and two-pass native Balanced analysis with the Activity destroyed and screen off under Doze, reopened completed shows, cancelled live work, resumed a saved passage and verified timeout cleanup. All eight diagnostic/export/recovery checks also passed. The original 45-second readiness deadline was retained.

Three fixed native/WASM decoded-audio comparisons and a separate actual vocal/GAME comparison passed; the latter preserved 16 sung notes. Internal spectral comparisons failed on a small number of coefficients and remain disclosed in the [numerical protocol](https://github.com/CyberBASSLord-666/LightForge/blob/57e6ee996bd8f9d135e89334585efe90d8667b68/qa/release-2.2.4/NUMERICAL_QUALIFICATION.md). These results do not establish exact spectral parity or general accuracy across songs.

Cold preview startup remains variable: a separate diagnostic run missed the 45-second deadline and reached the same readiness conditions about six seconds later. The original failed records are retained. No physical Samsung crash reproduction, sustained-phone speed/thermal result or Tesla timing validation is claimed. Long songs and compatibility processing can still take substantial time and memory.

---

# Historical LightForge 2.2.3 development notes


Unpublished development precursor. The following notes retain its original scope; its runtime and diagnostic changes are included in 2.2.4.

This update addresses a native crash during Studio separation startup. A device diagnostic report records a native illegal-instruction exit immediately after the first passage starts. ONNX Runtime 1.23.2 has upstream reports of ARM CPU instruction-detection errors matching this class of failure. The report does not identify the exact failing function, so physical-device confirmation remains necessary.

## Changes

- Native Android ONNX Runtime is updated to checksum-pinned 1.25.1, including corrected SME2 capability detection.
- Studio uses the same complete model weights, passage context and numerical settings.
- A confirmed native-analysis crash activates compatibility processing on the next Resume for that app/runtime version. This uses the bundled WASM engine and the same Studio models. It may take longer. App/runtime upgrades permit native processing again.
- Saved rhythm work and completed passages remain available; no cache or project deletion is required by the update.
- Exported diagnostic logs now decode Android's binary native crash records, showing the signal, crashing library, relative instruction offset and available function names. Private paths, raw memory, audio and project contents remain excluded.
- Durable phase logs distinguish native library initialization, graph creation and the first graph execution.

## Validation

The matched development-host comparison produced bit-identical vocal and accompaniment samples with native runtime 1.23.2 and 1.25.1. This checks one reference passage, not general phone performance. Android lifecycle, native crash recovery and release packaging results are recorded in the source-bound verification files before publication.

Physical Samsung/Android 17 execution and Tesla timing remain unverified. Force-stop and device power restrictions still apply. Compatibility processing can require substantial time and memory.

## Installation and troubleshooting

The published update must retain the original LightForge signing certificate so it can install over the existing app without uninstalling. If a failure persists, use Guide → Export diagnostic log and attach the text file from Downloads/LightForge. Native exit traces depend on what Android retains.

## Upstream evidence

- [ONNX Runtime 1.23.2 Android ARM64 illegal-instruction report](https://github.com/microsoft/onnxruntime/issues/27282)
- [SME versus SME2 detection issue](https://github.com/microsoft/onnxruntime/issues/26377)
- [Updated native CPU dispatch](https://github.com/microsoft/onnxruntime/blob/v1.25.1/onnxruntime/core/mlas/lib/kai_ukernel_interface.cpp)
- [Android native exit trace format](https://developer.android.com/reference/android/app/ApplicationExitInfo#getTraceInputStream())

The bundled model licenses continue to permit noncommercial use only where specified in their notices.
