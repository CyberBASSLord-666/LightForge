# Validation and evidence scope

A repository test, an APK build, a published release and a performance claim are
different results. Each must identify the source and evidence it actually covers.
This page is an index, not a replacement for source-bound receipts.

## Published 2.4.1 record

The [LightForge 2.4.1 release](https://github.com/CyberBASSLord-666/LightForge/releases/tag/v2.4.1)
uses Android version code **20401** and qualified source
`1f43cfa5609ef8df28ebad3d947ad8c0510ec9e3`. Full source-bound host, actual-model,
browser and Android emulator verification passed in
[production run 36403187315](https://github.com/CyberBASSLord-666/LightForge/actions/runs/36403187315).
[Publication run 36409699982](https://github.com/CyberBASSLord-666/LightForge/actions/runs/36409699982)
verified the exact qualified payload and original signing certificate. The
public release contains the signed APK, checksum, notes and verification report.

Final production host qualification reduced median complete-passage time by
32.6%, from 65.3 to
44.0 seconds. Every measured pair improved by 28–36%, all eight full outputs
were byte-identical, and every resource guard passed. Earlier failed attempts
remain in the [investigation record](research/inference-2.4.1/README.md).

This release adds device-local scheduling calibration and durable
job/route measurements. [The calibration contract](docs/NATIVE_EXECUTION_CALIBRATION.md)
requires repeated timing wins and unchanged finite output before selecting a
candidate. Its current-release model gate executes reference, freshly calibrated
and cached full passages, checks all original production calls, and verifies
cancelled calibration cannot commit a partial result. Fresh/cached execution,
forced four/eight-worker paths, real JNI cancellation and interrupt retirement,
and exact recovery have passed on the final production source.

[GAME option screening](research/inference-2.4.1/game-options-screen.json)
rejected numerical differences and inconsistent performance; production GAME
settings remain unchanged. The admitted host result does not establish physical
phone or whole-analysis speed. Physical phone and Tesla observations remain
unverified; later source changes require their own release verification.

## Historical published 2.4.0 record

The [LightForge 2.4.0 release](https://github.com/CyberBASSLord-666/LightForge/releases/tag/v2.4.0)
uses Android version code **20400** and qualified source
`1ca3b8f6a70c84e5ec72e1599fc4e90088aee2f1`.
Its full source-bound host, actual-model, browser and Android emulator checks
passed in [production run 36354221023](https://github.com/CyberBASSLord-666/LightForge/actions/runs/36354221023).
The public release contains the original-signed APK, checksum, release notes and
verification report for that exact qualified application payload.

The [recorded vocal frontend host benchmark](docs/VOCAL_FRONTEND_OPTIMIZATION.md)
measured about **27% less median frontend processing time**, with byte-identical
Float32 feature values for the exercised inputs. It excludes resampling, model
inference and total analysis time. A 75% whole-analysis reduction, general
musical-quality non-regression and physical phone/Tesla behavior remain
unverified under the version-specific automated-verification-only policy.

The vehicle research is recorded in [the hardware evidence review](docs/VEHICLE_HARDWARE_EVIDENCE.md);
it distinguishes VIN-confirmed traits from configuration and estimated optics.

## Historical published 2.3.2 record

LightForge **2.3.2 / Android version code 20302** was published on
**September 27, 2026**. Its qualified application source is
`c38be4e7f1079a4897d8340875d4da2fe8d4cd57`; full host/Android verification
passed in [production run 35493931933](https://github.com/CyberBASSLord-666/LightForge/actions/runs/35493931933).
The [public release](https://github.com/CyberBASSLord-666/LightForge/releases/tag/v2.3.2)
contains the original-signed APK, checksum, notes and verification report.
[Publication run 36289930324](https://github.com/CyberBASSLord-666/LightForge/actions/runs/36289930324)
verified the exact qualified payload and original signing certificate.

Coverage includes native GAME/WASM output and checkpoint comparisons,
completed-project preview restoration, background analysis and durable saving,
cancellation/resume, and diagnostic recovery. Android results are emulator
observations, not physical-phone or Tesla tests.

The version-scoped `automated_verification_only` policy did not require an
external corpus, human perceptual review or energy/thermal observations. Their
absence remains disclosed. It did **not** establish comparative musical quality,
zero regression across arbitrary songs or a 75% runtime reduction. The strict
optional performance-quality workflow was not weakened.

## Current source versus release evidence

[version.json](version.json) describes the source identity. Commits after a
release may retain that version while development continues; they are not covered
by the released APK's receipt. Read the exact source SHA and run in each record.

| Evidence | What it establishes | What it does not establish |
| --- | --- | --- |
| Repository hygiene | Current documentation links, layout and prohibited tracked clutter | App behavior, model accuracy or APK qualification |
| Node/Python regression | Tested software contracts on the test host | Android lifecycle or general musical accuracy |
| Native/model comparison | The explicitly paired inputs, source, graphs and numerical/runtime checks | Universal parity or representative device performance |
| Browser/preview tests | Browser execution, adapters, persistence and tested rendering paths | Physical car behavior or real Android services |
| Android emulator tests | Packaged app and the instrumented lifecycle/diagnostic scenarios | Physical phone thermal behavior or Tesla latency |
| Signed release verification | Exact APK integrity, original certificate and source-bound publication gates | Unmeasured comparative or physical claims |
| Strict benchmark qualification | Only the locked corpus, paired conditions and accepted statistical/human evidence | Unrepresented songs, hardware or settings |

[Production verification](.github/workflows/verify-v2.yml) is the executable
source for current gate ordering. [BUILD.md](BUILD.md) describes reproduction.
Generated current-run reports are not new golden references. Source/model
changes require fresh evidence or the existing explicit immutable-retention
protocol; changing an old hash or timestamp is not verification.

## Historical evidence retained in place

Versioned `qa/` directories contain both historical evidence and helpers still
imported by current tests. Do not delete them merely because a filename contains
an earlier version. Preserve failed probes alongside later passes; do not
relabel old results to support a changed release.

The 2.2.4 [numerical qualification](qa/release-2.2.4/NUMERICAL_QUALIFICATION.md)
and retained failed Android probes document their original limits. The 2.2.1
[Deux runtime comparison](qa/release-2.2.1/DEUX_RUNTIME.md) is a short host excerpt,
not a phone/full-song benchmark. Earlier reports remain in their original
versioned folders and Git history. Historical prose has been removed from this
landing page rather than duplicated as current instructions.

## Unverified claims and optional observations

The [implementation map](docs/ARCHITECTURE_AND_PRODUCTION_READINESS.md) distinguishes
enabled behavior, optional inputs and missing detector/scheduler capabilities.
The [strict gate](docs/PERFORMANCE_QUALITY_GATE.md),
[benchmark contract](docs/ANALYSIS_BENCHMARK_CONTRACT.md) and
[locked runner](docs/LOCKED_BENCHMARK_RUNNER.md) define comparative qualification.
A template, synthetic test, cache hit or single timing observation is not a
substitute for that evidence.

Physical observations are optional for the applicable publication policy, but
claims about phone performance, energy/thermal behavior, actual Tesla playback,
actuator travel and perceptual synchronization still require those observations.
See [physical-validation attestation](docs/PHYSICAL_VALIDATION_ATTESTATION.md).
Software timing correction and FSEQ frame resolution are not physical latency
calibration.
