# LightForge

An offline Android studio that turns local music into editable Tesla light shows.
The vehicle profile targets the **2025 Model 3 Long Range RWD, North America**.
Models, audio tools, vehicle geometry and required notices are bundled in the APK;
there is no account, API key, backend or runtime model download.

## Install

Download the original-signed APK from [LightForge 2.4.3](https://github.com/CyberBASSLord-666/LightForge/releases/tag/v2.4.3).
**Install over the existing app; do not uninstall first.** A matching update
preserves private projects. Development and CI APKs use a different identity and
must not be substituted for the published update.

Android 8 or newer and a current Android System WebView are required. Analysis is
memory- and storage-intensive and may take substantially longer than the song.
The source version is maintained in [version.json](version.json); a version in
source or a successful build is not, by itself, a published release.

## Create, edit and export

Choose **Choose music**, select an unprotected local audio file, select a style
and analysis mode, then use **Create my light show**. Studio prioritizes the full
Deux separation path; Balanced is an explicit lighter MDX alternative. Both
include learned rhythm and sung-note analysis. Model outputs remain estimates,
not lyric alignment or guaranteed musical accuracy.

The **Compose / Music / Outputs / Review** workspaces provide arrangements,
voice/bass cues, individual output controls, timing corrections and a preview of
the compiled show. **My shows** keeps independent, automatically saved projects.
**Export USB-ready show** writes the soundtrack, validated FSEQ and an editable
project backup. Keep exported backups before moving devices or clearing app data.

See the [user guide](docs/USER_GUIDE.md) for background processing, editing,
backup/restore, USB layout and troubleshooting.

## Background processing and diagnostics

Analysis runs in an Android foreground service. Allow notifications and use
**Allow screen-off processing** when Android offers the battery exemption.
System limits and manufacturer battery restrictions still apply. After an
interruption, **Resume analysis** can reuse matching, verified checkpoints;
clearing cache does not replace the saved show as the export source of truth.

Use **Guide → Export diagnostic log** after reproducing a problem. Reports stay
local until exported and contain no attached music or saved-show payload. Review
reports before sharing publicly; never commit personal audio, diagnostics or
signing credentials to this repository.

Native scheduling uses complete-passage qualification, bounded extra work and
sustained checks using useful baseline passages. Same-input qualification requires
finite, byte-identical outputs and repeated timing wins; later unmatched-input
controls are regression guards, not paired speedup measurements. Durable
diagnostics preserve both kinds of evidence. See
[the calibration contract](docs/NATIVE_EXECUTION_CALIBRATION.md).

## Verification and limitations

The 2.4.3 build uses Android version code **20403**. Its qualification replays
the original 2.4.2 registered
[bounded host experiment](https://github.com/CyberBASSLord-666/LightForge/actions/runs/40085980189)
that measured **18.8% lower median complete-passage time** (66.459 to 53.952 seconds),
with all eight complete outputs byte-identical. It compared forced four-worker
execution with a three-thread baseline on the same three assigned CPUs of a
four-CPU-capacity host, using one original passage. The replay binds fresh
candidate source/classes and session evidence; it is not another timing result.
The 18.8% result is not an additional gain over published 2.4.1: its historical
32.6% result and the earlier experimental 43.6% result used different conditions.

[Validation](VALIDATION.md) records the immutable evidence and its scope. A host
experiment does not qualify an APK. For a published download, check the version,
qualified source, original signing certificate and payload hashes in the
[published verification report](https://github.com/CyberBASSLord-666/LightForge/releases/download/v2.4.3/release-verification.json)
against the [2.4.3 release](https://github.com/CyberBASSLord-666/LightForge/releases/tag/v2.4.3).
A retained report for an older version does not qualify newer source bytes.

**Comparative musical quality, a 75% analysis-time reduction, whole-song
acceleration and physical phone/Tesla performance remain unestablished.**
The historical [vocal frontend benchmark](docs/VOCAL_FRONTEND_OPTIMIZATION.md)
measured about 27% less frontend processing time, excluding model inference and
complete analysis. Current-source [throughput observations](research/throughput-20261026/README.md)
cover bounded native GAME session reuse, PCM conversion and WAV decoding; they
retain the slower rejected case and do not establish a whole-analysis speedup.
Phone thermal/battery behavior and actual vehicle timing
require their own observations. The retained [phone regression record](research/inference-device-regression-20260928/README.md)
explains why host gains are not device-performance evidence. Old receipts must
not be relabelled as current results.

## Development

[BUILD.md](BUILD.md) is the build and release entry point. For a smaller fresh
checkout that does not download retired transfer history:

```bash
git clone --depth 1 --single-branch https://github.com/CyberBASSLord-666/LightForge.git
cd LightForge
python3 tools/repository_hygiene.py
```

The build uses Android SDK command-line tools rather than a Gradle app module.
Required retained assets stay in the repository; GAME and Deux graphs are
reproduced from pinned inputs. No model, precision or quality downgrade is a
repository-cleanup technique.

| Document | Purpose |
| --- | --- |
| [Documentation index](docs/README.md) | Guides and focused engineering contracts |
| [Build and release](BUILD.md) | Reproduction, tests and gated publication |
| [Architecture](ARCHITECTURE.md) | Module ownership and dependency boundaries |
| [Validation](VALIDATION.md) | Evidence scope and unresolved claims |
| [Assets](ASSETS.md) | Model reproduction and licensing |
| [Versioning](VERSIONING.md) | Source identity and original update certificate |
| [Maintenance](REPOSITORY.md) | Repository layout, cleanup policy and history |
| [Changelog](CHANGELOG.md) | Version history |

This repository is public. Public visibility does not grant a license to all
included material. Preserve third-party notices and model-weight restrictions;
several bundled models are restricted to noncommercial use. LightForge is not
an official Tesla product.
