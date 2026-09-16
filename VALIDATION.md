# Validation and evidence scope

A repository test, an APK build, a published release and a performance claim are
different results. Each must identify the source and evidence it actually covers.
This page is an index, not a replacement for source-bound receipts.

## Published 2.2.5 record

LightForge **2.2.5 / Android version code 20205** was published on
**September 16, 2026**. Its immutable release source is
`9ad78719179a6502adab50a92216ddc74d5dd261`; all nine host/Android verification
gates passed in [production run 35038907453](https://github.com/CyberBASSLord-666/LightForge/actions/runs/35038907453).
The [public release](https://github.com/CyberBASSLord-666/LightForge/releases/tag/v2.2.5)
contains the original-signed APK, checksum, notes and verification report.

Coverage includes completed-project preview restoration, background analysis and
durable saving, cancellation/resume, and diagnostic export/recovery. Android
results are emulator observations, not physical-phone or Tesla tests. Original
signing identity, unchanged application payload and uploaded-APK digest are
separate publication checks.

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
