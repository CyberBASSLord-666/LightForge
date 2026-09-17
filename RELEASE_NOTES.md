# LightForge 2.3.1

Android version code: **20301**. Install the original-signed release APK over the existing app to retain private projects.

## Changes

- Preserve repeated bass attacks at the same pitch instead of collapsing them into one long held note. The detector requires a measured low-band dip followed by a rapid restart in the note's own harmonics, and it keeps the original audio clock and accompaniment-mixture labels.
- Rebuild bass phrases, strengths and semantic events from the recovered note boundaries. Smooth tremolo, continuous sub-bass, broadband noise and kick-only fixtures remain guarded against invented rearticulations.
- Add a reproducible WASM inference experiment that binds the original GAME graphs, checks every intermediate tensor and unrounded note, and measures fresh alternating runs. The tested batch-one specialization preserved exact output but was slower and remains disabled.
- Retain original model weights, Float32 precision, source clocks, passage context, thread settings and all eight GAME transcription steps.

## Verification and limits

The source-bound production workflow covers host regression, actual bundled-model execution, browser persistence and rendering, and Android emulator lifecycle and diagnostic scenarios. Publication requires a successful run for the exact source, sealed evidence, the original signing certificate, unchanged candidate payload and a matching uploaded-APK digest. The accompanying `release-verification.json` identifies the qualifying source, run and artifact.

Controlled fixtures recovered five repeated 55 Hz and 110 Hz notes that the previous detector merged into one, while the stated negative controls remained stable. These fixtures do not establish general detection accuracy or listener preference. Host inference observations are not measurements of the user's phone or a complete song.

The owner-approved publication policy makes external corpus benchmarks, human perceptual review and hardware energy/thermal observations optional. The 75% whole-analysis target, general comparative musical quality, blinded perceptual review and physical phone/Tesla behavior remain **unverified**. The separate strict performance-quality workflow retains its existing acceptance requirements.

## History

See [CHANGELOG.md](CHANGELOG.md) and [published releases](https://github.com/CyberBASSLord-666/LightForge/releases) for earlier versions. Historical release assets and verification reports remain unchanged.
