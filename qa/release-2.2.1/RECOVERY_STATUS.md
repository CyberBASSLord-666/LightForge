# 2.2.1 recovery status

The release is **not published**. The complete Android recovery probe passes on current source `f80de0d7fd075cf22506c60910e41ea9f625e922`, and the original-signed APK is built. Final production CI and publication remain pending.

## Current completed evidence

- Source-bound native/WASM numerical equivalence, source-clock reconstruction and 18 fresh downstream role cases pass. The role cases use fixed original-model separation estimates, not 18 newly separated native-runtime songs.
- Current local regressions pass **145 Node and 39 Python checks**, including six bounded asset-staging tests. Native host compilation and all **21 storage/audio/format checks** pass.
- The staging check streamed **111 files / 1,524,917,198 bytes** and verified exact hashes, including **73 declared analysis assets**. This is staging evidence, separate from APK signing and runtime behavior.
- Android probe [34169529496](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34169529496), job `101887033168`, **passed** native Studio completion with the Activity destroyed, display off and Doze active; saved-show reopening; cancellation during a later passage; immediate Resume with verified saved-passage reuse; resource cleanup; and the Android timeout callback. Artifact `10035699527` preserves the results. This uses a temporary CI certificate on the verified application payload, not the original private key.
- Production CI [34169530104](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34169530104) passed its verification job. Its dependent Android job is still pending.

## Current signed APK

`LightForge-2.2.1.apk` is **1,171,728,522 bytes**, SHA-256 **9fdbc60afecb6ce278d890f36ad58cb67623a485fd800d9e6c4215c6a7b3dd9f**. It uses the original certificate **7187d6aa935d5b7d2d656cb87913af95fe1ca3a4b1653036d1d8d890e2016c6b**. The private signing identity was recovered from its separate backup and remains outside GitHub.

The earlier lost APK (`47feff…`) and pre-teardown-fix APK (`6f051c…`) are superseded. Their checksums must not be substituted for this build's identity.

## Resolved diagnostic history

The first production attempt hit an insufficient outer instrumentation budget. Probe [34166156881](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34166156881) completed the first native background fixture, then failed to establish Doze for the second fixture. The test now waits for actual screen-off/Doze state while retaining its assertions.

Probe [34168136295](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34168136295) saved one passage and cancelled native work, then hit an Android focus-event ANR during Resume. `MainActivity` now detaches the preview WebView before destruction; instrumentation verifies actual destruction/detachment. A two-second watchdog records diagnostic stacks without extending Android's ANR threshold. The complete passing probe above validates the corrected path on its Android 15 emulator.

## Remaining work

Obtain the successful final production Android result; collect and verify all current source-bound receipts; finish original-signed package verification and candidate-index transfer; publish and verify GitHub's uploaded assets. Keep publication marked pending until those steps succeed. Physical phone/full-song, thermal/manufacturer battery behavior and Tesla timing remain unverified. Studio remains computationally expensive; the short-excerpt host speed/memory measurements are not phone forecasts.
