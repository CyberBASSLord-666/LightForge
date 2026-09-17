# Build, verify and release LightForge

The repository contains the Android/WebView app, retained runtime assets, model
converters and tests. Builds use SDK command-line tools, not Gradle. Build-time
downloads are required for pinned dependencies and generated graphs; the
installed app operates offline.

[version.json](version.json) is authoritative for the source release identity.
Use [GitHub Releases](https://github.com/CyberBASSLord-666/LightForge/releases) to
identify published APKs, not a version label or an Actions artifact.

## Reproduce a build

Use Linux x86_64, Bash, Python 3.12.14 and Node 22 or newer. Allow at least 16 GB of
free build space and 8 GB RAM; actual resource use depends on the conversion and
verification workload. The generated offline models alone are approximately
1.2 GiB before APK compression.

Run from the repository root:

```bash
set -euo pipefail
npm ci --ignore-scripts --no-audit --no-fund
python3 tools/bootstrap_toolchain.py
python3 tools/bootstrap_native_runtime.py
python3 -m venv ../model-build
../model-build/bin/pip install pip==26.2.1 setuptools==83.0.0
../model-build/bin/pip install torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu
../model-build/bin/pip install -r tools/model-requirements.txt
../model-build/bin/python tools/prepare_game.py
../model-build/bin/python tools/prepare_deux.py
python3 tools/repository_hygiene.py
npm test
LIGHTFORGE_SIGNING_DIR=/absolute/path/to/original-private-signing bash build.sh
VERSION="$(python3 -c 'import json; print(json.load(open("version.json"))["name"])')"
python3 tests/verify_native_release.py --release "$VERSION"
```

The signing directory must contain the original `lightforge-release.jks` and
`keystore-password.txt`, outside the checkout. The build rejects a missing or
incompatible update identity. Do not generate a replacement key or uninstall an
existing app to work around a signing error. The certificate and version-change
procedure are documented once in [VERSIONING.md](VERSIONING.md).

For an isolated development installation only:

```bash
LIGHTFORGE_ALLOW_NEW_SIGNING=1 \
  LIGHTFORGE_SIGNING_DIR=/absolute/private/lightforge-development-signing \
  bash build.sh
```

A development APK cannot update the original installation. The build produces
`dist/LightForge-<version>.apk`, an `.apk.json` receipt and an `.apk.sha256` file.
The receipt's `update_compatible` must be `true` for an original-key update.
Building locally does not satisfy all publication gates.

## Test layers

Repository maintenance checks are fast and need only Python and Git:

```bash
python3 tools/repository_hygiene.py
python3 tests/test_repository_hygiene.py
```

After installing the dependencies and reproducing the model assets:

```bash
python3 tools/sync_version.py --check
python3 tools/verify_analysis_assets.py
npm test
VERSION="$(python3 -c 'import json; print(json.load(open("version.json"))["name"])')"
node "qa/release-$VERSION/test-source-clock.cjs"
npx playwright install --with-deps chromium
node "qa/release-$VERSION/browser.cjs"
node "qa/release-$VERSION/background-ui.cjs"
LIGHTFORGE_RESTORE_QA_OUTPUT="qa/release-$VERSION" node qa/restore-preview/browser.cjs
```

The actual-model browser test also needs the licensed reference excerpts. Follow
the pinned download/hash and fixture-preparation steps in
[production verification](.github/workflows/verify-v2.yml), then run
`node "qa/release-$VERSION/analysis-browser.cjs"`. Do not replace licensed fixtures
with arbitrary music while retaining the original evidence labels.

The same workflow is authoritative for the complete order of native comparison,
profile, APK, instrumentation and emulator checks. Browser adapters and host JVM
checks cannot substitute for Android lifecycle tests. The instrumentation builder
uses an ephemeral identity and refuses the original release certificate. Do not
distribute test instrumentation as the application.

`npm test` writes current-release diagnostic receipts. These are generated
outputs, not proof of publication. Immutable retained evidence is accepted only
by its existing source/model-bound protocol; never edit receipt hashes merely to
make a changed build pass. See [VALIDATION.md](VALIDATION.md).

## Toolchain and renderer

[tools/bootstrap_toolchain.py](tools/bootstrap_toolchain.py) pins the SDK/JDK
inputs; [android/native-runtime.json](android/native-runtime.json) pins ONNX
Runtime and its native libraries. [tools/model-requirements.txt](tools/model-requirements.txt)
and the npm lockfiles pin conversion and test dependencies. Development npm
packages do not enter the APK.

Supported overrides are `LIGHTFORGE_TOOLCHAIN_DIR`, `LIGHTFORGE_JAVA_HOME`,
`ANDROID_SDK_ROOT` and `LIGHTFORGE_SIGNING_DIR`. When using the supplied toolchain
on hosted CI, avoid runner-provided SDK environment variables overriding it.
Package and API settings are in [android/AndroidManifest.xml](android/AndroidManifest.xml)
and [build.sh](build.sh); supported ABIs are in the native-runtime manifest.

Edit renderer source in `web/preview/src/`, not only its generated bundle:

```bash
mkdir -p ../toolchain/graphics
cp web/preview/src/package.json web/preview/src/package-lock.json ../toolchain/graphics/
npm ci --prefix ../toolchain/graphics
node tools/build_preview.mjs
```

Model and asset provenance are in [ASSETS.md](ASSETS.md). Generated graphs,
installed toolchains, build outputs, credentials and personal audio stay out of
Git. The canonical retained assets do not need historical transfer reconstruction.

## Publication controls

Do not republish or overwrite a released version to deliver changed application
bytes. Update the version deliberately, produce a new successful source-bound
verification run and qualify that exact candidate under the applicable policy.

For **2.2.5 / 20205, 2.3.0 / 20300 and 2.3.1 / 20301**, the owner-approved
`automated_verification_only` policy makes external corpus benchmarks, human perceptual review and hardware
energy/thermal observations optional. The 2.3.0 and 2.3.1 declarations follow
the owner's explicit requests to develop and continue these improvements and
publish when ready without user-supplied measurements. This exception is
version-scoped; it is not a blanket policy for future releases or a `PASS_TARGET` result. The separate
strict [performance-quality gate](docs/PERFORMANCE_QUALITY_GATE.md) retains its
thresholds. Physical phone/Tesla observations may be absent, but corresponding
claims must remain explicitly unverified.

The release path retains these controls:

1. Use the exact reviewed source and a successful full `verify-v2.yml` run.
   Preserve protected-main/deployment rules and the complete same-session sealed
   evidence. Historical receipts and earlier successful runs cannot qualify
   different application bytes.
2. Prepare the signing index through
   [prepare-release.yml](.github/workflows/prepare-release.yml). Keep the candidate
   artifact, source identity and evidence bound together.
3. Sign the exact qualified candidate outside Git with the original private
   identity. `tools/apk_delta.py make candidate.apk signed.apk signed-apk.delta.json`
   records the public-byte delta; the catalog alternative is
   `tools/apk_delta.py make --from-catalog candidate-index.json signed.apk signed-apk.delta.json`.
   A delta contains neither a key nor permission to sign another APK.
4. Submit the versioned request under `releases/v<version>/` using the current
   publisher schema and matching declaration/evidence. Do not copy an old
   request unchanged or alter its historical run identity. The
   [published 2.2.5 request](releases/v2.2.5/request.json) is historical reference,
   not a template that authorizes another version.
5. [publish-release.yml](.github/workflows/publish-release.yml) reconstructs and
   verifies the original-signed APK, unchanged payload, manifest, alignment,
   evidence and uploaded digest. Completion means a public, non-draft release
   with the APK, checksum, release notes and verification report—not just a green
   build or an Actions artifact.

[Release-quality setup](docs/RELEASE_QUALITY_SETUP.md) documents strict optional
benchmark authority and protected inputs. [Physical-validation attestation](docs/PHYSICAL_VALIDATION_ATTESTATION.md)
describes optional observations. Neither setup instructions nor unit-test
success are measurements.
