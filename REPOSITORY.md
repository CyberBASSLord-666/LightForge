# Repository maintenance

Current verified source is LightForge 2.2.4, Android version code 20204. All seven release verification gates passed in the complete [production run](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34424617050) on `57e6ee996bd8f9d135e89334585efe90d8667b68`, including offline model execution, Android screen-off/Resume and crash-report export. The original-signed APK build retains the update identity. [LightForge 2.2.4](https://github.com/CyberBASSLord-666/LightForge/releases/tag/v2.2.4) is the published update; the publication workflow verifies every uploaded asset digest before exposing the release. Use [BUILD.md](BUILD.md) for the build pipeline and [VALIDATION.md](VALIDATION.md) for exact evidence and limits.

Current sources, model converters, manifests, tests, workflows and maintenance documents live at the repository root. Version 2.2.4 adds guarded native Balanced MDX, bounded model lifetimes, prompt checkpoint reporting and preview/startup recovery, retaining the model weights, sample clock and quality settings. Current verification belongs in `qa/release-2.2.4/`. The 2.2.3 precursor and earlier releases retain their historical identities; failed 2.2.4 probes remain separately archived. The diagnostic observer source is supplemental and is not part of the verified release. Native dependencies are pinned in `android/native-runtime.json`. `verify_snapshot.py` checks the historical preserved snapshot; current application changes must pass the current release gates.

## Historical 1.6 restoration


This completion preserves the existing `main` branch and repository-root app layout. Compared with the verified LightForge 1.6.0 backup, the repository already had 859 identical files and two updated maintenance documents; 39 source assets and evidence files were missing. Those missing files are restored here. Current development history and documentation are retained.

The backup contained 904 entries. All 900 non-secret source files are preserved: the original README, BUILD and VALIDATION documents are kept under `archive/v1.6.0/` while their current root versions remain available for maintenance. The signing keystore, its password, and two obsolete archive wrapper documents are excluded. The private archive SHA-256 is `8d23b72254c0de148526386c4a5f4d6121e221340fdb377a42156f4677a7d2cb`.

## Verify and build

The initial transfer carried eight large source assets as 8 MiB pieces. The completed migration restored them to their normal paths, verified the preserved snapshot, and committed only those restored paths to `main` without force-pushing. Its one-time publishing workflow is retained at `archive/v1.6.0/publish-workflow.yml`; the active release pipeline is now `publish-release.yml`. If working from the initial transfer before restoration completes:

```bash
python3 migration/restore.py --only source
python3 verify_snapshot.py
```

Once restored, all original 1.6 model weights, WebAssembly, demo audio, geometry and retained QA data are present. The newer GAME/Deux graphs are reproduced as described in BUILD.md. Follow [BUILD.md](BUILD.md) from the repository root. Installed toolchains and reproducible build caches are not included. Some historical test harnesses reference the original development workspace; adapt those environment paths when reproducing them. Historical QA is not evidence of new tests against future code changes.

`SOURCE_MANIFEST.json` records the 900 preserved original source files and their hashes. It intentionally does not claim that newer maintenance documents are identical to the original archive. After future source edits, rerun affected checks; never change evidence hashes merely to pass release packaging.

## Original signed APK

The [v1.6.0 release](https://github.com/CyberBASSLord-666/LightForge/releases/tag/v1.6.0) contains the original verified signed APK, SHA-256 `9767c40847534f7438a42a5c6821bfffd0434ddbdc231c86538f80f7f7cdba57`. It is reassembled from the saved bytes, not rebuilt or re-signed. The existing `v1.6.0-qa` release is retained separately; its APK has a different hash and is not overwritten. See [release instructions](releases/v1.6.0/README.md).

## Preserve the signing identity

Restore `lightforge-release.jks` and `keystore-password.txt` from the separate private backup into a directory outside the checkout. Build with:

```bash
LIGHTFORGE_SIGNING_DIR=/absolute/path/to/private-signing bash build.sh
```

The original certificate SHA-256 is `7187d6aa935d5b7d2d656cb87913af95fe1ca3a4b1653036d1d8d890e2016c6b`. A new signing key cannot update the installed app. Keep the private source ZIP outside Git because it contains these credentials.

This repository and its music/assets remain private. Existing third-party notices and rights remain in effect. No physical phone or vehicle testing is claimed by this migration.
