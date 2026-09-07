# LightForge 2.2.1 — Native Studio processing and recoverable progress

Version code **20201**. This signed update retains the original LightForge signing identity. Install `LightForge-2.2.1.apk` over the existing app **without uninstalling**.

## Analysis execution

- Android Studio separation uses **ONNX Runtime 1.23.2 native CPU inference** instead of placing its transformer workload in the WebView's WebAssembly runtime. The browser retains its own bounded WebAssembly implementation.
- The original learned Deux weights, full 13-second context, complete attention, both source heads and Float32 computation are retained. Independent bands and frames are processed in bounded batches, with reusable buffers. No layers or quality setting are silently dropped.
- Rhythm, separation, voice and bass analysis use separate worker lifetimes so one stage's WebAssembly heap does not remain resident throughout the next stage. GAME Large and the existing rhythm models remain bundled.
- Native separation can be cancelled through the foreground service. Its output remains on the original soundtrack sample clock. No network service, model download or new device permission is required.

## Resume and progress

- Completed separation passages, transcription work and analysis stages are saved locally with integrity checks. **Resume analysis** reuses matching completed work; the passage interrupted before its checkpoint finished may run again.
- Checkpoint identities include source audio, analysis settings, execution path and app version. Rename and choreography-only changes preserve matching audio analysis; changed or damaged work is not accepted as a finished result.
- Finished overall analysis can resume directly into choreography. Cancellation, Android interruption and storage errors leave the previous saved show intact. Android background-time limits and manufacturer battery/memory controls still apply.
- The progress panel shows elapsed time, current passage, completed work and reuse counts. A delayed-update message distinguishes a quiet model step from newly reported progress without inventing an ETA. The background notification includes an elapsed-time chronometer.

## Measured execution improvement

On the same **6.803-second stereo PCM16 excerpt**, with four threads on one Linux development machine:

| Measurement | Bounded WASM | Native Java CPU |
| --- | ---: | ---: |
| Separation time | 127.25 s | 61.11 s |
| Peak process resident memory | 1,920.96 MiB | 720.56 MiB |

Native execution was **2.08× faster**, with **62.49% lower peak process RSS** in this comparison. The native output retained exact source sample counts and agreed with the same-input WASM reference within measured Float32 error. These are host measurements on one short excerpt, not physical-phone measurements or a full-song forecast. Studio remains computationally expensive and can take much longer than the music's playback duration. See [runtime evidence](qa/release-2.2.1/DEUX_RUNTIME.md) and [validation scope](VALIDATION.md).

## Verification

Source-bound native/WASM numerical equivalence and source-clock checks pass. Fresh downstream inference on 18 fixed original-model estimates retains singing in 12 positive cases and produces zero vocal events in six instrumental cases; this is not 18 newly separated native-runtime songs. Browser editing, responsive layout, full model inference and cancellation have passed against unchanged web sources. The refreshed local regression run passed 145 Node and 39 Python checks against the current sources.

The [current-source Android 15 probe](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34169529496) passed real native Studio completion with the Activity destroyed, display off and Doze active, then reopened the saved show. It also passed cancellation during a later passage, immediate Resume with verified saved-passage reuse, resource cleanup and the Android timeout callback. The Activity detaches its preview WebView before destruction, addressing a focus-event ANR found during earlier testing. **All six source-bound release gates pass**, including the [complete production CI run](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34169530104) and its independent Android lifecycle job. The signed package passes exact asset inventory, version, alignment, checksum and original-certificate verification.

This update targets the slow execution and repeated-work failure mode reported in 2.2.0. It does not promise a fixed completion time or claim resolution on an untested phone. Sustained runtime, memory, storage, thermals and long-song completion remain device/workload dependent. Physical phone and Tesla testing remain unverified. Model licenses retain their noncommercial restrictions.

Earlier features and release history are retained in [CHANGELOG.md](CHANGELOG.md).
