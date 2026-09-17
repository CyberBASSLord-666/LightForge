# LightForge 2.3.0

Android version code: **20300**. Install the original-signed release APK over the existing app to retain private projects.

## Changes

- Recognize sustained tonal changes alongside dynamics and spectral colour, so harmonic changes at similar loudness can guide section transitions. Supported irregular phrase endings take priority over the four-bar fallback. Silence boundaries and the original beat clock remain intact.
- Recommend musical expression for new projects: validated vocal articulation, held notes, phrase releases and recurring musical material influence the arrangement. Existing projects retain their stored settings. Compatible completed analyses can enable expression immediately without running separation or transcription again; Undo restores the prior arrangement.
- Preserve selected, supported vocal and bass attacks when semantic density control simplifies decorative lighting. No lyric recognition, isolated drum detector or verse/chorus classifier is claimed.
- Recover eligible reclaimed background renderers from validated saved progress automatically, with bounded retries and cancellation fences. This reduces manual recovery; it is separate from inference speed.
- Add repeatable full-passage inference comparisons with unchanged model assets, exact PCM checks and separate inference, initialization, CPU and memory observations.
- Retain original model weights, Float32 precision, source clocks, passage context and all eight GAME transcription steps.

## Verification and limits

The source-bound production workflow covers host regression, actual bundled-model execution, browser persistence and rendering, and Android emulator lifecycle and diagnostic scenarios. Publication requires a successful run for the exact source, sealed evidence, the original signing certificate, unchanged candidate payload and a matching uploaded-APK digest. The accompanying `release-verification.json` identifies the qualifying source, run and artifact.

Controlled musical fixtures and the supplied project can demonstrate specific structural and composition changes; they do not establish general detection accuracy or listener preference. Host inference observations are not measurements of the user's phone or a complete song.

The owner-approved publication policy makes external corpus benchmarks, human perceptual review and hardware energy/thermal observations optional. The 75% whole-analysis target, general comparative musical quality, blinded perceptual review and physical phone/Tesla behavior remain **unverified**. The separate strict performance-quality workflow retains its existing acceptance requirements.

## History

See [CHANGELOG.md](CHANGELOG.md) and [published releases](https://github.com/CyberBASSLord-666/LightForge/releases) for earlier versions. Historical release assets and verification reports remain unchanged.
