# Version and signing identity

`version.json` is authoritative for the release name and Android version code. Read the current values there; this document intentionally does not duplicate them.

After intentionally changing a release version, update `package.json` and its lockfile, then run `python3 tools/sync_version.py`. This generates `web/version.js`, which the application, compiler and engine read. Builds and tests use `--check` to reject stale generated metadata.

The original update certificate is:

`7187d6aa935d5b7d2d656cb87913af95fe1ca3a4b1653036d1d8d890e2016c6b`

Keep the existing keystore and password together outside Git. Production builds require this identity. `LIGHTFORGE_ALLOW_NEW_SIGNING=1` explicitly permits an isolated development identity; it cannot update the installed app. CI uses this option for its candidate artifact. Only an exact locally re-signed candidate that passes the original-certificate publication gate can become a release.

Compiled snapshot `engineVersion` describes the version that originally created its frames. Opening a legacy arrangement does not rewrite that identity. `settingsMigration` records a checksum-verified default-only upgrade, and `provenance.app` records the current app.
