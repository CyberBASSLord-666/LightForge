# Build and verify LightForge 2.1

The repository root contains the complete Android/WebView source, retained assets, model-reproduction tools and tests. No Gradle, backend, account or runtime model download is needed.

## Reproduce the Android update

Requirements: Linux x86_64, Python 3.12+, Node 22+, Bash, and at least 16 GB of free build space and 8 GB of RAM. The offline models add approximately 1.2 GiB before APK compression.

```bash
npm ci --ignore-scripts --no-audit --no-fund
python3 tools/bootstrap_toolchain.py
python3 -m venv ../model-build
../model-build/bin/pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
../model-build/bin/pip install -r tools/model-requirements.txt
../model-build/bin/python tools/prepare_game.py
../model-build/bin/python tools/prepare_deux.py
npm test
LIGHTFORGE_SIGNING_DIR=/absolute/path/to/original-private-signing bash build.sh
python3 tests/verify_native_release.py --release 2.1.0
```

The signing directory must contain the original `lightforge-release.jks` and `keystore-password.txt` from the private source backup. Never commit them. The build rejects missing or incompatible update signing material. For an intentionally separate development installation only:

```bash
LIGHTFORGE_ALLOW_NEW_SIGNING=1 LIGHTFORGE_SIGNING_DIR=/tmp/lightforge-dev-signing bash build.sh
```

That APK cannot update the original installation. Do not uninstall the original app to work around a signing error; recover the correct signing identity.

The build verifies resource and asset ZIP integrity, compiles Java/DEX, aligns the APK, signs it, verifies the certificate and manifest, and atomically publishes:

- `dist/LightForge-2.1.0.apk`
- `dist/LightForge-2.1.0.apk.json`
- `dist/LightForge-2.1.0.apk.sha256`

`update_compatible` in the JSON receipt must be `true` for the original installation.

## Browser and release gates

```bash
npx playwright install --with-deps chromium
node qa/release-2.1.0/browser.cjs
node qa/release-2.1.0/analysis-browser.cjs
node qa/release-2.1.0/test-source-clock.cjs
python3 tools/package_release.py
```

The browser test uses the real UI, WebGL, browser workers, music fixture, persistence and streamed export, with a simulated Android bridge. It retains screenshots at 320, 393, 768 and 1440 pixels. The `.github/workflows/verify-v2.yml` workflow runs Node/Python, browser, APK build and native tests and keeps receipts/screenshots as an Actions artifact. Its signing identity is temporary. The candidate APK is retained as a private Actions artifact for local signing; it cannot update the original app.

Prepare the licensed MUSDB reference excerpts as shown in `.github/workflows/verify-v2.yml` before running the actual model browser test. The packager requires passing, source-bound regression, browser, native, actual model runtime and reference-quality receipts. `qa/release-2.1.0/evaluate-separation.py` reproduces the 18 reference estimates; `evaluate-roles.cjs` runs their role components. The conversion/runtime probes and `verify-analysis.py` bind numeric evidence to exact model/adapter hashes; the complete commands and retained execution captures are documented in `qa/release-2.1.0/README.md`. Fresh model changes require fresh evidence; checked-in receipts are not a bypass. It compares every bundled web asset against the current source, checks APK CRCs and the original certificate, then creates `output/LightForge-2.1.0.apk` and `release-verification.json`. It does not substitute historical model tests for current UI/engine tests. Repository sources are the development handoff; the separate original private backup retains signing credentials.

## Dependencies and overrides

The bootstrap pins SHA-256 checksums for Android build-tools 35.0.0, Android platform 35 revision 2, and Temurin JDK 17.0.20.1+1. `tools/bootstrap_testdeps.py` supplies the pinned host-JVM `org.json` implementation. Development npm dependencies are lockfile-pinned and never enter the APK.

Supported environment variables: `LIGHTFORGE_TOOLCHAIN_DIR`, `LIGHTFORGE_JAVA_HOME`, `ANDROID_SDK_ROOT`, and `LIGHTFORGE_SIGNING_DIR`. Android SDK paths are `build-tools/35.0.0` and `platforms/android-35/android.jar`. Unset runner-injected `ANDROID_SDK_ROOT`/`ANDROID_HOME` when using the supplied toolchain on CI.

Application ID: `com.cyberbasslord.lightforge`; minimum API 26; compile/target API 35; Java language level 8; version code 20100. No native `.so` libraries or Internet permission are included.

## Renderer source

Edit `web/preview/src/`, not only the generated `web/preview/vehicle-preview.js`. To rebuild:

```bash
mkdir -p ../toolchain/graphics
cp web/preview/src/package.json web/preview/src/package-lock.json ../toolchain/graphics/
npm ci --prefix ../toolchain/graphics
node tools/build_preview.mjs
```

Three.js remains pinned at 0.180.0. Model conversion provenance and scripts are under `research/model-source/`; model and library notices remain bundled.

## Physical validation

Host tests do not execute an Android Activity, document provider or media codec, and do not measure vehicle behavior. A device with current Android System WebView is required for final install, playback, long-analysis and USB/car checks. Keep the app open while analyzing or exporting.

## Publish a compatible GitHub release

The production verification workflow retains `lightforge-2.1-ci-candidate` after its build and native gates pass. Download that exact artifact, verify all candidate assets against the checkout, and sign it locally using the original private identity. Refresh native and package receipts after signing.

`tools/apk_delta.py make candidate.apk signed.apk signed-apk.delta.json` produces a small public-byte transfer against the exact candidate hash. `apply` reconstructs the locally signed APK byte-for-byte and rejects a wrong base, corrupt patch or invalid range. It contains no key/password and cannot sign another APK.

Commit the delta and `releases/vX.Y.Z/request.json` with the exact successful CI run, source commit, version and delta SHA-256, plus current release receipts. The publication workflow runs on `main`, verifies all five gates and unchanged app sources, reconstructs the full APK, validates the original certificate/manifest/alignment/assets, then uploads the APK, checksum, notes and verification report. It publishes only after GitHub's stored APK digest matches. Published release tags/assets are never overwritten. A failed draft can be resumed with its explicit release ID and expected draft target in the request; an identical APK is reused, only draft metadata can be replaced, and all uploaded digests are rechecked.

When the connector cannot download the large candidate artifact, `prepare-release.yml` reads a successful pinned run and publishes `verified-candidate-index`. Its ZIP entry offsets, sizes and compressed hashes allow `tools/apk_delta.py make --from-catalog candidate-index.json signed.apk signed-apk.delta.json` without transferring the model payloads locally. Applying the delta still verifies the entire candidate hash and exact final signed-APK hash. The catalog test proves it produces the same delta as indexing the candidate directly.
