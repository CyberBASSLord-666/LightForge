# LightForge 2.2.4

Release candidate: an Android emulator ANR during preview teardown requires a fresh run after the preview suspension and harness synchronization fixes. Current Android and signed-package gates must pass before publication. Physical-phone and Tesla validation remain unperformed.

This update targets the two long-run failure modes in the supplied diagnostics: renderer memory growth during Balanced MDX/GAME work and a native Studio crash that can leave a partial job. It keeps the learned weights, sample clock, model geometry and quality settings unchanged.

## Changes

- Explicitly suspend preview animation and GPU redraw work while the native Activity or page is paused; resume once without duplicating animation loops or changing graphical quality.
- Bound the Balanced separator's WebAssembly lifetime to one passage, reuse its frontend spectrum buffer, and retry a complete polarity pair in one runtime so a renderer cannot retain every long-song model allocation.
- Add an optional native Android path for Balanced MDX. It streams only the exact 12.6 MiB Float32 spectrum in bounded bridge chunks, validates the pinned model geometry/checksum, uses the same ONNX graph and decoder, and falls back to the verified WebAssembly path on any compatibility or output error.
- Apply the native retry guard to both native separators. A confirmed Android native crash disables that runtime identity for the next Resume instead of retrying the same instruction path; the compatibility path remains quality-preserving and uses the same models.
- Reset GAME model sessions periodically, release preview WebViews before renderer teardown, and expose durable checkpoint commits immediately after each rhythm, passage and stage write.
- Treat prior passage progress as resumable even when a renderer disappears between a browser checkpoint and its Java-side status update. Completed work is still checked against audio, settings, release and execution identity before reuse.

## Validation scope

The preceding candidate passed host, Chromium pipeline and package checks. Android Studio completed under screen-off/Doze and reconnected, but closing the reopened Activity triggered a graphics-thread ANR before Balanced inference. The current preview follow-up has focused lifecycle regressions and requires fresh full CI, Android execution and signed-package receipts. Fresh Studio outputs are bit-identical across the two compared native runtime versions on the reference passage.

Balanced native MDX passed three decoded-audio comparisons and an actual paired singing-note comparison with 16 sung notes. The initial absolute-only and revised relative spectral checks failed on a few coefficients; those records are retained and are not relabeled as passing spectral parity. See `qa/release-2.2.4/NUMERICAL_QUALIFICATION.md` for the revised output-domain contract and its scope. Android screen-off execution, sustained-phone memory/thermals and the supplied Samsung crash require their separate checks.

---

# LightForge 2.2.3

Release candidate: validation and original-certificate signing must finish before publication.

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
