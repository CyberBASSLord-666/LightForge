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
python3 tools/bootstrap_testdeps.py
python3 -m venv ../model-build
../model-build/bin/pip install pip==26.2.1 setuptools==84.1.0 filelock==4.2.1
../model-build/bin/pip install torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu
../model-build/bin/pip install -r tools/model-requirements.txt
../model-build/bin/python tools/prepare_game.py
../model-build/bin/python tools/prepare_deux.py
python3 tools/repository_hygiene.py
npm test
# Obtain a fresh candidate-specific host admission by the registered-proof
# replay flow below. Do not run a new benchmark or copy an old current receipt.
python3 tools/verify_inference_improvement.py
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

## Bounded host campaign and per-build admission

The normal `verify-v2.yml` path now **replays one immutable, prospectively
registered timing result instead of measuring again for every build**. This is
an explicit policy change, not a claim of fresh timing. Before expensive
preparation, it retrieves only the exact designated producer attempt and proof
artifact. After current model/runtime preparation, the full local verifier
checks recorded evidence and exact measured identity, then creates a fresh
candidate-specific admission bound to the current commit, tree and evidence
session. A stale current receipt is removed before either step. Missing proof
blocks the build; it never starts a replacement measurement.

The new `bounded-four-worker-three-cpu-v1` lane uses the unchanged production
four-worker neural runner against the unchanged three-thread reference, both
forced onto the same three observed child CPUs with at least one additional
CPU-equivalent of real effective capacity reserved. The original full Float32
model/audio, complete outputs, byte identity, resource proof, 15% median and 5%
every-pair thresholds remain unchanged. This is forced host configuration, not
normal production scheduler admission, eight-worker performance, Android
admission or complete-song performance.

The read-only diagnostic selects this lane explicitly:

```sh
python3 tools/inference_qualification_preflight.py \
  --protocol bounded-four-worker-three-cpu-v1
```

Linux x86_64, a complete visible initial/global cgroup-v2 hierarchy, a non-root
process cgroup, consistent applicable ancestor limits/counters, and at least
four effective CPUs are mandatory. `cpu.max=max` means observed unlimited
quota, not missing evidence. Only structurally inapplicable global-root fields
are exempt. Hidden or missing ancestry fails closed. The preflight changes no
host settings and establishes neither campaign authorization nor qualification.
An ordinary replay consumer need not itself be a qualifying timing host; the
recorded producer resource proof is independently replayed instead.

### One prospectively registered producer

A separately published prospective request at
`tools/host-inference-campaigns/<campaignId>.request.json` allocates the one
producer in **LightForge production verification**. Only that file's immutable
first-creation commit on protected main may start the separate producer job.
With no request there is no producer; later registration or cosmetic pushes
cannot allocate another. Manual dispatch cannot allocate a campaign. The
producer's only initial action after read-only eligibility is reviewed
dependency/model preparation and compilation:
`--phase prepare` creates the frozen declaration before zero warmups or timed
pairs. The workflow uploads an immutable declaration artifact and waits
read-only for a registration published through the existing authorized source
path on protected main. Registration must name the exact campaign, producer
run ID/attempt, actual input commit/tree, declaration artifact ID/server digest,
and reviewed execution closure. The already-running designated attempt may
then execute once. `cancel-in-progress: false` protects that already-running
producer from registration publication; it does not protect a queued request
run. GitHub's default single pending slot can replace a queued run on a later
main push. Before creating the request, ensure no older main verification run
is ahead of it. Wait until the designated `host-campaign` job is running before
publishing registration or unrelated pushes. A replaced/missing designated run
holds; it cannot allocate a replacement attempt. No queue setting, credential,
service, repository setting or human approval system is introduced.

**A manual run is not release-eligible**. The campaign producer also never
packages a candidate or runs the Android publication chain, even though it is
started by a protected-main request push. Ordinary main/PR verification
replays a passing proof with exact measured source/class/policy/model/runtime/
audio identity. Protected-main source publication and all same-session core,
actual-model, Android, original signing and publication gates remain required.

Reruns must replay the original terminal result, never warm up or time again.
Failed proof remains failed; unknown, deleted, cancelled, incomplete or expired
producer attempts/artifacts hold. Artifact retention is finite, so expiry can
block an otherwise unchanged build. There is no automatic retry, replacement
campaign, best-result selection or fallback to historical evidence. A source or
policy identity mismatch also holds and requires a separately reviewed policy
decision, not a silent remeasurement.

The bounded producer's prospectively selected pool is fixed to `ubuntu-latest`;
repository variables and dispatch inputs cannot choose another producer pool.
Every actual allocated machine must pass the full strict preflight. Any prior
diagnostic applies only to its observed machine, not blanket eligibility for
the pool, and no passing campaign proof is asserted here. Ordinary verification
retains its existing runner routing: only protected-main pushes may select the
already-authorized `vars.LIGHTFORGE_INFERENCE_RUNNER` label, with `ubuntu-latest`
as the unconfigured default. The existing `inference_runner` dispatch input
selects only a diagnostic proof consumer. Do not use a
privileged persistent host for untrusted code. No runner is provisioned, paid
for or granted access by this workflow, and billing restrictions still require
the authorized account-management route.

The production v3 protocol remains a separate explicit CLI path with its
unchanged eight-CPU, finite-quota requirements; it is not a fallback for the
bounded campaign. Old `lightforge.experimental-portable-parallel-qualification.v1`
receipts remain inadmissible. See
[the host protocol and campaign lifecycle](docs/EXPERIMENTAL_HOST_QUALIFICATION.md)
for the exact scope and fail-closed behavior. Implementing this path is not
authorization to measure: independent review, integrated 2.4.2 source, source
freeze and authorized publication must precede any actual timing.

## Test layers

Repository maintenance checks are fast and need only Python and Git:

```bash
python3 tools/repository_hygiene.py
python3 tests/test_repository_hygiene.py
```

The [supplemental restore workflow](.github/workflows/restore-regression.yml)
reports a status on every PR. It skips browser setup only when complete Git
comparisons of the PR and tested merge show exclusively maintained documentation
or inert metadata for the unchanged current release. Runtime, test, workflow,
version and unknown changes run the full supplemental suite; incomplete scope
also runs it. Manual runs always exercise the suite. This optimization does not
change production verification, benchmark admission or publication gates.

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

Production CI reuses pip's package-download cache through the existing pinned
`setup-python` action. Its key includes the Python/runner identity, model
requirements and verification workflow (including the inline Torch/installer
pins). Installs, both model conversions and every verification gate still run on
cache hits. No installed environment, generated model or verification receipt is
cached. Local pip installs also retain their normal download cache; a warm cache
is only a download optimization, never evidence that the current source passes.
Actual CI time/transfer savings require a successful cold/warm run; none are
claimed from the configuration alone.

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
Git. Pinned SDK/JDK archive downloads use bounded 1 MiB reads, verify the complete
size and SHA-256, and publish atomically from unique temporary files. Interrupted
or concurrent bootstraps cannot publish a partial archive; cached archives are
rechecked before reuse. Managed SDK/JDK installations carry a package identity
receipt and are compared against the verified archive's full file inventory
(bytes, modes and links) before reuse. Existing unmanaged, changed or differently
pinned installations fail closed without replacement: choose a fresh
`LIGHTFORGE_TOOLCHAIN_DIR` and rerun bootstrap. This also applies when upgrading
from older bootstrap versions without installation receipts.

The host build and independent publisher currently pin stable Temurin
**17.0.21+9** ([official vendor release](https://github.com/adoptium/temurin17-binaries/releases/tag/jdk-17.0.21%2B9)).
This refresh concerns the host JDK, not the Android runtime shipped in the APK;
it does not establish per-CVE applicability or universal security remediation.
The canonical retained assets do not need historical transfer reconstruction.

## Publication controls

Do not republish or overwrite a released version to deliver changed application
bytes. Update the version deliberately, produce a new successful source-bound
verification run and qualify that exact candidate under the applicable policy.

For **2.2.5 / 20205, 2.3.0 / 20300, 2.3.1 / 20301, 2.3.2 / 20302, 2.4.0 / 20400 and 2.4.1 / 20401**, the owner-approved
`automated_verification_only` policy makes external corpus benchmarks, human perceptual review and hardware
energy/thermal observations optional. The 2.3.0, 2.3.1, 2.3.2 and 2.4.0 declarations follow
the owner's explicit requests to develop and continue these improvements and
publish when ready without user-supplied measurements. For the 2.4.0 core refactor,
the owner explicitly reaffirmed that a 75% speedup is an aspirational objective.
The [2.4.1 declaration](releases/v2.4.1/quality-gate-declaration.json) follows the
owner's explicit request to implement inference improvements in the next release
and retains fresh production, actual-model and Android verification for the changed source. This exception is
version-scoped; it is not a blanket policy for future releases or a `PASS_TARGET` result. The separate
strict [performance-quality gate](docs/PERFORMANCE_QUALITY_GATE.md) retains its
thresholds. Physical phone/Tesla observations may be absent, but corresponding
claims must remain explicitly unverified.

The draft [2.4.2 / 20402 declaration](releases/v2.4.2/quality-gate-declaration.json)
extends that automated-only scope to this exact next-build candidate under the
owner's continued completion request and removal of external inputs. It does
not qualify the release or waive the later neural-inference hold: real,
noticeable, repeatable improvement and all fresh source-bound production,
actual-model, packaged Android, sealed-evidence and original-signature checks
remain required. No future version is automatically admitted.

`build.sh` additionally requires a passing exact-source inference admission
before preparing assets or compiling an APK. Under the bounded campaign policy,
it replays the original registered three alternating full-passage pairs rather
than implying fresh timing: at least 15% lower median latency, 5% in every pair,
complete byte-identical output and unchanged resource proof remain mandatory.
The current frozen Java/classes, policy, model, runtime and audio must exactly
match measured identity, with a fresh candidate-specific source/session binding.
Historical 2.4.1 and experimental portable receipts remain unchanged and cannot
qualify newer geometry or satisfy the bounded campaign. The current prerequisite
under `research/inference-current/` is separate from the immutable producer proof
and from published release evidence. Changing the version number does not
bypass this release hold.

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
