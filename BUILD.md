# Building LightForge

The project builds a private, release-signed Android APK without Gradle or an external backend. The native shell uses Android SDK APIs and packages the local web application, analysis code and model as APK assets.

## Prerequisites

- Linux x86_64 with Bash and Python 3.12 or newer for the supplied bootstrap.
- Approximately 1 GB of free disk space for the pinned JDK and Android SDK tools, plus the project and generated APK.
- Network access to Google Android SDK downloads and Eclipse Adoptium's GitHub release during the first bootstrap. Building afterward uses the locally installed dependencies.

From this directory:

```bash
python3 tools/bootstrap_toolchain.py
bash build.sh
```

The output is `dist/LightForge-1.6.0.apk`. Its SHA-256 checksum and build validation receipt are alongside it. The bootstrap pins and verifies SHA-256 checksums for Android build-tools 35.0.0, the Android 35 platform revision 2 and Eclipse Temurin JDK 17.0.20.1+1. They are stored in `../toolchain` by default. The downloaded SDK and JDK contain their applicable license notices.

To use an existing installation, supply the correct locations:

```bash
ANDROID_SDK_ROOT=/path/to/android-sdk \
LIGHTFORGE_JAVA_HOME=/path/to/jdk17 \
bash build.sh
```

`build.sh` expects SDK `build-tools/35.0.0` and `platforms/android-35/android.jar`. `LIGHTFORGE_TOOLCHAIN_DIR` changes the bootstrap/default toolchain directory. `LIGHTFORGE_SIGNING_DIR` changes the signing directory.

## Build settings

| Setting | Value |
| --- | --- |
| Application ID | `com.cyberbasslord.lightforge` |
| Display name | LightForge |
| Version name | 1.6.0 |
| Version code | 10600 |
| Minimum Android version | Android 8.0 / API 26 |
| Target and compile SDK | Android 15 / API 35 |
| Java language target | Java 8, compiled with JDK 17 |
| Native ABIs | None; Java and bundled browser assets |
| APK signature schemes | v2 and v3 verified for API 26+ |

The build stages web assets while excluding development dependency/cache folders, compiles resources with AAPT2, compiles Java with `javac`, produces DEX with D8, packages assets, aligns the APK, then signs it. After signing it verifies the APK signature and alignment, checks every ZIP entry's CRC, and confirms the required manifest, resources, DEX and application entry page exist. It then publishes the final APK in one atomic replacement to avoid incomplete downloadable files.

## Rebuild the graphics bundle after editing it

The checked-in `web/preview/vehicle-preview.js` is already bundled. A normal
Android APK rebuild needs no npm installation. To edit the renderer source and
regenerate that file, install Node.js with npm, then run from `app/lightforge`:

```bash
mkdir -p ../toolchain/graphics
cp web/preview/src/package.json web/preview/src/package-lock.json ../toolchain/graphics/
npm ci --prefix ../toolchain/graphics
node tools/build_preview.mjs
bash build.sh
```

The npm lock pins Three.js 0.180.0 and the build dependencies. `npm ci` downloads
them during this development step; the installed app still runs offline.
The full renderer source is in `web/preview/src/`, and the pinned manifests are
kept there so an extracted private backup can reproduce the bundle. Do not
edit only the generated minified file.

The original licensed Highland GLB, geometry scripts and provenance are in
`research/model-source/`. See its `REBUILD.md` to regenerate the normalized
model. The original model and all derived build inputs are included in the
private source archive. Geometry preparation uses Python and NumPy; it is
optional when using the supplied bundled model.

## Keep the signing identity

The first build creates `signing/lightforge-release.jks` and `signing/keystore-password.txt`. Preserve both in the private source backup. Subsequent builds reuse them so Android can install updates over the existing app. Do not recreate the key for an app already installed on the phone. The build deliberately stops if only one half of the existing signing identity is present.

These are private personal signing credentials. This project has no public publishing workflow. If the source is ever shared, exclude `signing/` and have the recipient generate their own identity; their APK will then require a separate installation or removal of the original.

## Validation and runtime limits

The build produces `build/signature-verification.txt` and `build/apk-badging.txt` for inspection. These checks establish package integrity, declared compatibility and a valid Android signature; they do not replace an on-device runtime test. This workspace has no `/dev/kvm`, so accelerated Android emulator testing is unavailable. Browser-level application tests and export validation are separate from native device testing.

With a local Android SDK and a personally connected device, an optional local test is:

```bash
adb install -r dist/LightForge-1.6.0.apk
adb shell am start -n com.cyberbasslord.lightforge/.MainActivity
```

No remote device access is required for the build.

## Package a verified private release

After completing the current validation recorded in `VALIDATION.md`, run:

```bash
python3 tools/package_release.py
```

The packager requires the current source-bound receipts listed in
`tools/package_release.py`, all with explicit passing results and no errors.
Every recorded source hash must still match the implementation. Refresh a
receipt by rerunning its checks; changing only its version or hashes is invalid.

Historical release evidence is retained separately. The packager verifies the
APK update signature and exact bundled source bytes, then atomically writes
`LightForge-1.6.0.apk` and `LightForge-1.6.0-Private-Source.zip` to `output/`.
Generated music/FSEQ fixtures, discarded candidate model weights, JVM classes
and npm dependencies are excluded; their reproducible generators, primary
provenance and reports remain available.

## Primary documentation

- [Android AAPT2](https://developer.android.com/tools/aapt2)
- [Android D8](https://developer.android.com/tools/d8)
- [APK alignment](https://developer.android.com/tools/zipalign)
- [APK signing and verification](https://developer.android.com/tools/apksigner)
- [Eclipse Temurin releases](https://adoptium.net/temurin/releases/)

## Device-test status

The current release receipt records APK integrity, channel coverage, command
validation and browser checks separately from historical regression evidence. Native Android
installation and launch were not confirmed because the earlier emulator did not
finish booting. The app has not been tested here on the user's phone or car.
See `VALIDATION.md` for coverage and remaining limits.

## Release identity and verification

`version.json` is the build version source. Native UI and export metadata read the installed package version. To verify and package the signed release after running its tests, run `python3 tools/package_release.py`. The packager requires every current receipt to pass and its source hashes to match, verifies that the APK contains the current web assets, checks the update signing certificate and ZIP CRCs, and retains earlier release receipts explicitly as history. The included transformer graphs are ready to use; upstream references and conversion scripts are in `research/upstream/beat_this/`.

Current verification entry points:

```bash
node --test tests/engine.test.cjs tests/engine-manual.test.cjs tests/preview-engine.test.cjs tests/light-planner.test.cjs
node tests/movement-planner.test.cjs
node tests/composer-1.6.test.cjs
node tests/role-composer-1.6.test.cjs
node --test tests/bass-notes.test.cjs
python3 tests/verify_native_release.py --release 1.6.0
node qa/release-1.6.0/test-runtime.cjs
node qa/release-1.6.0/test-studio16.cjs
node qa/release-1.6.0/test-preview.cjs
node qa/release-1.6.0/test-real-music-export.cjs
```

Browser QA scripts use Playwright and a Chromium executable path from the build workspace; adjust those paths when reproducing on another machine. Analysis evaluation scripts and fixture provenance are included under `qa/release-1.6.0/`. These are desktop/JVM tests, not Android instrumentation tests.
