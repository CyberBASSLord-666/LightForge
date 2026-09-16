# LightForge 2.2.5

Android version code: **20205**. Install the original-signed release APK over the existing app to retain private projects.

## Changes

- Repair completed-project preview restoration and retain foreground-only restore handling, background-analysis recovery and durable saving.
- Update and pin the model-export toolchain, CI actions and host test dependencies; retain original model identities and numerical comparison checks.
- Add bounded timing, resource and synchronization diagnostics with explicit missing-data and measurement-scope reporting.
- Strengthen source-bound verification, supervised capture cleanup, sealed Android evidence and exact-candidate signing transfer.
- Use the owner-approved automated-verification publication policy for this version. External corpus benchmarks, human perceptual review and energy/thermal measurements are optional; their absence remains explicit in the public verification report.
- Keep physical phone and Tesla observations optional and explicitly unverified when absent.

## Verification and limits

All nine source-bound host and Android verification gates passed in [production run 35038907453](https://github.com/CyberBASSLord-666/LightForge/actions/runs/35038907453) for source `9ad78719179a6502adab50a92216ddc74d5dd261`. Coverage includes completed-project preview restoration, background analysis and durable saving, cancellation and resume, and diagnostic export and recovery. Android results are from an emulator.

Publication also requires sealed verification evidence, original-key signature validation, unchanged application payload and a matching uploaded-APK digest. The accompanying `release-verification.json` records the published artifact and the scope of its evidence.

Comparative performance and musical quality are **unverified**. This release does not claim a 75% analysis-time reduction, completed blinded perceptual review, measured energy/thermal behavior or physical phone/Tesla validation. Diagnostic timings and unit tests are not substitutes for those measurements. The strict optional performance-quality workflow retains its existing acceptance requirements.

## History

See [CHANGELOG.md](CHANGELOG.md) and [published releases](https://github.com/CyberBASSLord-666/LightForge/releases) for earlier versions. Historical release assets and verification reports remain unchanged.
