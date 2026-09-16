# LightForge

An offline Android studio that turns local music into editable Tesla light shows.
The vehicle profile targets the **2025 Model 3 Long Range RWD, North America**.
Models, audio tools, vehicle geometry and required notices are bundled in the APK;
there is no account, API key, backend or runtime model download.

## Install

Download the original-signed APK from the [latest published release](https://github.com/CyberBASSLord-666/LightForge/releases/latest).
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

## Verification and limitations

[Validation](VALIDATION.md) distinguishes published-release evidence from current
source checks, historical numerical tests and optional physical observations.
The published 2.2.5 release passed its nine source-bound host/Android gates, but
**comparative musical quality, a 75% analysis-time reduction, and physical
phone/Tesla performance are not established by those tests**. See its
[release record](https://github.com/CyberBASSLord-666/LightForge/releases/tag/v2.2.5)
for the signed APK and verification report. Later commits require their own
verification; old receipts must not be relabelled as current results.

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
