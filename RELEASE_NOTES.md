# LightForge 2.2.4

LightForge 2.2.4 improves long-running analysis and recovery while preserving the bundled models, source timing and quality settings. The signed update uses the original LightForge certificate: install it over the existing app without uninstalling to retain private projects.

## Changes

- Run Balanced MDX separation through a guarded native Android CPU path, retaining both polarity passes and the existing waveform decoder. Compatibility fallback uses the same model and retries a complete pair in one runtime.
- Bound WebAssembly model lifetimes between passages and stages, reuse large transform buffers, and release native resources before voice/GAME processing. GAME retains all eight transcription steps.
- Update native ONNX Runtime to pinned 1.25.1. A confirmed native crash selects compatibility processing on the next Resume; completed matching work remains reusable.
- Save passage/stage checkpoints promptly and report partial progress accurately. Cancellation retires native work through a shared execution gate before another separator allocates its models.
- Restore completed projects once across competing startup events. Suspend paused preview animation and defer empty-scene rendering until the model and view are ready, preserving the tested final graphics.
- Improve native crash reports and renderer recovery while retaining local-only diagnostics and user-controlled export.

## Verification and limits

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
