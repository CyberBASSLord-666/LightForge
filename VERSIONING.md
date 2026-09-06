# Versioning

LightForge uses a single source of truth for release identity and a tag scheme that separates device QA from ship.

## Source of truth

`version.json` at the repo root:

```json
{"name":"1.6.0","code":10600}
```

| Field | Meaning |
| --- | --- |
| `name` | Semver `MAJOR.MINOR.PATCH` (APK `versionName`) |
| `code` | Integer APK `versionCode`: `MAJOR*10000 + MINOR*100 + PATCH` |

Examples: `1.6.0` → `10600`, `1.6.1` → `10601`, `2.0.0` → `20000`.

`build.sh` reads `version.json` and injects both values with aapt2 `--replace-version`. Bump `version.json` before building a candidate APK.

## Tags and releases

| Tag | Purpose |
| --- | --- |
| `vX.Y.Z-qa` | Private prerelease for device QA / install-over (e.g. `v1.6.0-qa`) |
| `vX.Y.Z` | Validated ship release after QA sign-off |

Do not publish shipping APKs from CI. CI may compile and verify with a throwaway keystore only.

## Bump and ship order

1. Bump `version.json` (`name` and `code` together).
2. Build locally with the preserved personal keystore (`bash build.sh`).
3. Validate (see `BUILD.md` / `VALIDATION.md`); run device smoke outside CI.
4. Tag `vX.Y.Z-qa` and attach the APK for install-over QA when needed.
5. After sign-off, tag `vX.Y.Z` for the ship record.

Optional local packaging after receipts pass: `python3 tools/package_release.py` (not run in CI).

## Signing and install-over

- Release signing lives under `signing/` (gitignored). Preserve `lightforge-release.jks` and `keystore-password.txt` for update installs.
- Never commit keystores or passwords. Never put them in GitHub Actions secrets for green-main CI.
- CI uses an ephemeral `LIGHTFORGE_SIGNING_DIR`; that APK is not install-over compatible and must not be published as a release asset.
- Do not rotate the shipping key for an already-installed package.

## CI

Pull requests and pushes to `main` run:

1. **test** — Node unit suite (see `.github/workflows/ci.yml`).
2. **build-ci** — pinned `bootstrap_toolchain.py` then `build.sh` with ephemeral signing.

Out of CI: device/adb smoke, Playwright browser QA, `package_release.py`, and shipping keystore use.
