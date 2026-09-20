# LightForge 2.3.2

Android version code: **20302**. Install the original-signed release APK over the existing app to retain private projects.

## Changes

- Run singing transcription through Android's native ONNX Runtime CPU backend using the original five GAME models. Preserve Float32 precision, all eight diffusion steps, language, deterministic seeds, context and final note stitching.
- Reuse native Deux graph-session allocations while preserving the original 27 models and all 335 inference calls. Controlled host passage tests showed approximately 11–17% lower wall time with byte-identical outputs and approximately 1.6% higher median peak memory; Android and whole-analysis gains are not measured.
- Keep native transcription input bounded, separate execution-specific checkpoints, and require confirmed native cleanup before compatibility fallback. Stop safely if resource retirement cannot be confirmed.
- Reclaim identifiable orphaned transcription cache files after process restart without following symlinks or removing unrelated files. Audio processing remains on the device.

## Verification and limits

The source-bound production workflow covers host regression, actual bundled-model execution, browser persistence and rendering, and Android emulator lifecycle and diagnostic scenarios. Publication requires a successful run for the exact source, sealed evidence, the original signing certificate, unchanged candidate payload and a matching uploaded-APK digest. The accompanying `release-verification.json` identifies the qualifying source, run and artifact.

The production-engine comparisons exercise the complete 64-second public demo (98 final notes) and licensed Falcon mixture excerpt (five final notes), including native checkpoint replay. Final notes match the shared WASM pipeline on these inputs; small raw Float32 differences are retained in the evidence. Android instrumentation exercises native completion, ownership, cancellation and retirement. These tests do not establish general transcription quality or physical-device performance.

The owner-approved 2.3.2 / 20302 publication policy makes external corpus benchmarks, human perceptual review and hardware energy/thermal observations optional for this version. The 75% whole-analysis target, general comparative musical quality, blinded perceptual review and physical phone/Tesla behavior remain **unverified**. The separate strict performance-quality workflow retains its existing acceptance requirements.

## History

See [CHANGELOG.md](CHANGELOG.md) and [published releases](https://github.com/CyberBASSLord-666/LightForge/releases) for earlier versions. Historical release assets and verification reports remain unchanged.
