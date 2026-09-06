# Versioning

How LightForge versions the app, tags builds, and keeps CI free of secrets.

## Source of truth

[`version.json`](version.json) at the repo root is the **only** version source of truth (SSoT).

| Field | Meaning | Example (`1.6.0`) |
| --- | --- | --- |
| `name` | Semver string `MAJOR.MINOR.PATCH` | `"1.6.0"` |
| `code` | Integer `MAJOR*10000 + MINOR*100 + PATCH` | `10600` |

`build.sh` and packaging read these fields. Native UI and export metadata use the **installed package** version (derived from the same values at build time). Do not hardcode a second version in docs or scripts without updating `version.json` first.

Current on `main`:

```json
{"name":"1.6.0","code":10600}
```

## Bumping a version

1. Edit `version.json` (`name` and matching `code`).
2. Rebuild (`bash build.sh`) so the APK and receipts pick up the new values.
3. Refresh validation / package receipts as required by [`VALIDATION.md`](VALIDATION.md) and [`BUILD.md`](BUILD.md) before calling a ship build done.
4. Update user-facing notes (`CHANGELOG.md`, `RELEASE_NOTES.md`) in the same change set when shipping.

Do not invent a parallel version in `BUILD.md` tables or QA folder names without matching `version.json`. Doc tables that show version are **current values**, not a second SSoT.

## Git tags

| Tag | Meaning |
| --- | --- |
| `vX.Y.Z-qa` | QA / candidate build for the matching `version.json` |
| `vX.Y.Z` | Ship tag for the matching `version.json` |

Tag only after the intended APK (and required receipts for ship) exist for that version. Do not move or reuse a ship tag.

## CI (no secrets)

Minimal CI for green `main`:

- Run the in-tree unit / verification entry points (see [`BUILD.md`](BUILD.md) / [`VALIDATION.md`](VALIDATION.md)).
- Build with `tools/bootstrap_toolchain.py` + `bash build.sh`.
- For signing in CI, use an **ephemeral** `LIGHTFORGE_SIGNING_DIR` (throwaway keystore for package integrity only).

**Never** commit keystores, passwords, private keys, or tokens. **Never** put secret values in this doc, CI YAML, or the repo. Personal install-over identity stays local under private `signing/` only — see [`ASSETS.md`](ASSETS.md) and [`BUILD.md`](BUILD.md).

When CI uses the bootstrap toolchain, unset `ANDROID_SDK_ROOT` / `ANDROID_HOME` so `build.sh` picks the pinned SDK (build-tools 35.0.0, `android-35`, Temurin JDK 17) rather than a host install.

## Related docs

- [`BUILD.md`](BUILD.md) — how to build and package
- [`VALIDATION.md`](VALIDATION.md) — what was verified and known limits
- [`ASSETS.md`](ASSETS.md) — fat bins and private signing paths (local only)
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — layer contracts (not version policy)
