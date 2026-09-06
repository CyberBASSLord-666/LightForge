# Repository completion and maintenance

This completion preserves the existing `main` branch and repository-root app layout. Compared with the verified LightForge 1.6.0 backup, the repository already had 859 identical files and two updated maintenance documents; 39 source assets and evidence files were missing. Those missing files are restored here. Current development history and documentation are retained.

The backup contained 904 entries. All 900 non-secret source files are preserved: the original README, BUILD and VALIDATION documents are kept under `archive/v1.6.0/` while their current root versions remain available for maintenance. The signing keystore, its password, and two obsolete archive wrapper documents are excluded. The private archive SHA-256 is `8d23b72254c0de148526386c4a5f4d6121e221340fdb377a42156f4677a7d2cb`.

## Verify and build

The initial transfer carries eight large source assets as 8 MiB pieces. The release workflow restores them to their normal paths, verifies the preserved snapshot, and commits only those restored paths to `main` without force-pushing. If working from the initial transfer before restoration completes:

```bash
python3 migration/restore.py --only source
python3 verify_snapshot.py
```

Once restored, all model weights, WebAssembly, demo audio, geometry and retained QA data are present. Follow [BUILD.md](BUILD.md) from the repository root. Installed toolchains and reproducible build caches are not included. Some historical test harnesses reference the original development workspace; adapt those environment paths when reproducing them. Historical QA is not evidence of new tests against future code changes.

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
