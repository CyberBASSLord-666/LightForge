# Isolated Android inference diagnostic

This is a development companion for measuring the corrected `NativeDeux` on a
physical Android device. The current **version 2 / probe-2** artifact is
`build/inference-device-probe/run-jipwai4p/LightForge-inference-probe.apk`
(113,915,300 bytes), SHA-256
`79dba57cc55d0fc61e42aa245f0f94c7a1d826aa184bb6be08026ff931712429`.
Its source-receipt SHA-256 is
`b9b5991ab8746e96ef28675f23d6309ce5f985003df4d6f12ee4d5360d52d83b`.
The [new artifact archive](../../research/inference-device-regression-20260928/device-probe-v2-79dba57cc55d/README.md)
retains the build/source receipts, hashes for all 15 compiled source files and
75 classes, build log and independent APK verification. Signature, version,
16 KiB alignment, assets, pinned runtime and current-source binding passed.
This artifact record contains no version 2 phone run or production release.

Version 2 has a different development signer from the old companion. Preserve
the old companion's exported receipts, then remove **only LightForge inference
probe — DEVELOPMENT** before installing it. Do not uninstall installed
LightForge; version 2 cannot update either application's existing signing identity.

The historical **version 1** diagnostic APK was built, structurally
verified, installed and run. [Run01's archived findings](../../research/inference-device-regression-20260928/device-probe-4a25e06032a3-run01.md)
record four completed passages before operator cancellation during passage five.
One exact-output pair had 24.56% lower candidate arm wall time, confounded by
model-file preparation charged to the baseline. This does not isolate a scheduling
gain or establish sustained qualification. A completed probe is evidence for
review, not production release approval.

That historical build is `build/inference-device-probe/run-w6e3elh2/LightForge-inference-probe.apk`
(113,898,916 bytes), SHA-256
`a68ab0690f0ade0153fd7edb21e4b86c86cbe0eccbceb98d339162d1dd71d274`.
Its companion receipt confirms APK signature, ZIP integrity, and alignment
checks, a separate development signer, `releaseArtifact: false`, and
`executionPerformed: false`. That field records the builder's actions, not the
later phone run. Build checks do not establish runtime behavior or performance.
Its frozen source receipt remains historical; current production changes are not
covered by this APK or run01. The archived analysis passes frozen-artifact binding
and fails the current-source binding gate.

The companion uses application ID
`com.cyberbasslord.lightforge.inferenceprobe`. It does not update, launch, stop,
instrument, or access the private files of installed LightForge. It reads the
installed application's public packaged model assets after checking its package,
version code `20401`, current signing certificate, and model manifest. Its cache,
receipts, logs, fixture, and policy files belong to the companion's separate UID.
The APK requests no permissions, including no Internet, audio, or storage
permission. There is no user-audio import or production-policy override.

## Building later

Review the sources and freeze the production inference changes first. From the
repository root, an explicitly requested isolated build is:

```sh
python qa/inference-device-probe/build_probe.py --build
```

The existing JDK 17, Android SDK 35, and pinned ONNX Runtime 1.25.1 files are
required in the sibling `toolchain` directory, or at `--toolchain PATH`. The
builder does not download dependencies. Running without `--build` refuses to
compile. It does not call `build.sh`, any release-packaging script, an installer,
ADB, or inference. The release signer constant is read as source data only.

Each build uses a new `build/inference-device-probe/run-*` directory and a newly
generated, temporary development signing key. The key is deleted after signing,
and the release certificate is explicitly rejected. Outputs are
`LightForge-inference-probe.apk`, `.apk.json`, and `.apk.sha256`. Subsequent
builds are intentionally not signer-compatible updates to an earlier probe;
export its receipts before removing the old companion to install another one.
Installed LightForge is unaffected by removing the companion.

The builder freezes Java sources before compilation and records every emitted
class's source file and SHA-256. No precompiled production classes are used.
The embedded source receipt binds those sources, the builder and manifest,
compiler/platform identity, pinned runtime files, expected installed package,
model manifest, and exact fixture. A separate receipt binds the final signed
APK and its development certificate. Model binaries are not included. The
existing four-ABI runtime is included unchanged; runtime licenses and third-party
notices are bundled. APK ZIP integrity, runtime/asset hashes, package identity,
absence of permissions, signing, and 16 KiB alignment are checked.

This is a normal UI-installable development APK, not an instrumentation APK.
`android:testOnly=true` is deliberately absent: Android documents that such APKs
can only be installed through ADB. Installation is a separate, visible action;
this builder never performs it.

## What a run measures

The visible **Run 35-passage diagnostic** button creates one real
`NativeDeux(Android Context)` and retains it for 35 complete predictions. It
passes the actual remaining count `35..1` to the production admission policy.
Each new run starts with an empty companion-only policy/model cache. Repeating
a run in the same app process can retain runtime allocator/library state; that
is not a fresh-process measurement. A run may remain on the baseline if the
real device's memory, cores, runtime behavior, paired measurements, or payback
rule reject the candidate. The probe does not seed a successful policy.

The `ContextWrapper` returns itself from `getApplicationContext()`, returns
installed LightForge's asset manager from `getAssets()`, and gives `NativeDeux`
the companion's unique cache directory. Other calls delegate to the real
companion context, preserving Android memory/system-service observations.
The only cross-package call is `createPackageContext(packageName, 0)` for
resources: no `CONTEXT_INCLUDE_CODE`, `CONTEXT_IGNORE_SECURITY`, class loading,
reflection, hidden APIs, or target app lifecycle calls are used. Android package
visibility is declared for that one package.

The bundled test is the existing licensed 6.803-second Falcon excerpt converted
to PCM16. The unchanged production reader pads it to the model's complete
13-second context. Start samples `-66150, 0, 22050, 44100, 88200` repeat seven
times. These are explicit repeated-fixture benchmark jobs, not an actual
35-passage song or independent musical-quality samples. Same-input complete
baseline/candidate comparisons and admission remain the production policy's
responsibility. An output hash alone does not establish parity with a different
input or runtime.

Each passage records its actual production profile and policy evidence, total
prediction wall/process CPU time, complete output SHA-256, size, finite-float
check, and device/memory/power/thermal observations at its boundaries. Baseline
and candidate have different call counts: read the profile instead of assuming
335 calls for every selected geometry. Output PCM is deleted after validation;
no audio appears in exported JSON. The receipt includes device model/OS/ABI but
no serial, Android ID, user files, VIN, or private paths.

Receipts are atomically checkpointed in companion-private storage before and
after each passage. **Export JSON receipt** uses Android's document picker and
exports only the captured receipt after the run stops. If Android kills the
process, the prior incomplete receipt remains visibly incomplete. Dated
receipts are retained; export the latest before starting a new run if it is
needed. An unrecoverable native crash can prevent a final checkpoint and is
never converted into a pass.

Expect tens of minutes, sustained CPU/memory use, and roughly 1 GB of temporary
disk space. The run requires declared model bytes plus 128 MiB of available
cache storage. A 90-minute watchdog or severe Android thermal status requests
cancellation. Keep the activity visible: leaving it cancels; rotation retains
the runner. **Cancel and retire inference** calls production cancellation and
waits for the worker to return. There is no forced thread termination. Cache
deletion happens only afterward. Unexpected native/resource failures preserve
the cache and mark cleanup unconfirmed; process death leaves its evidence
incomplete. Watchdog cancellation cannot force an unresponsive native kernel
to return at an exact deadline.

## Limits and review gates

- Cross-package asset access and the installed package/model identity checks
  succeeded during run01 on the observed phone. This does not establish support
  on other devices. Missing package/resources or any identity mismatch fail
  visibly before inference. No weaker fallback is used.
- This validates the corrected engine and its real Android admission policy in
  a separate process. It does not validate LightForge's foreground service,
  lifecycle, wakelock, audio import, output assembly, sequencing, or full-song
  thermal behavior. Existing production instrumentation has a different scope.
- Thirty-five jobs may include substantial qualification overhead; inspect
  admission, every paired result, ordinary calls, calibration cost, and total
  elapsed time. A complete run is not automatically a useful speedup.
- Run01's four full outputs and one matching pair do not establish a completed
  35-passage run, controlled scheduling improvement or net benefit. Cancellation
  returned the coordinator and engine close but conservatively marked native
  cleanup unconfirmed and retained the cache. Source corrections require new
  evidence; APK build success alone cannot supply it.

## Fixture attribution and source references

The Easton Ellises — **Falcon 69**, MUSDB18 test excerpt, C't Remix Comp.,
[CC BY-NC-SA 3.0](https://creativecommons.org/licenses/by-nc-sa/3.0/).
This companion is for noncommercial diagnosis. The original Float32 excerpt is
converted to stereo PCM16 by scaling by 32768, nearest/ties-to-even rounding,
and signed-16-bit clipping. Provenance and the conversion are embedded in the
APK. The original checksum is
`effbbe3e3c0df821bf3cfa6535360b18339ded8041992373b41f8344998dba99`;
converted WAVE checksum is
`0d0bf21401ad0dbb8a49aae581a16f9a00cadca41e116b5a4dc27eaaa3625648`.
See `qa/release-1.6.0/musdb-fixture-provenance.json` for the source archive,
archive hash, and member path. The source archive is
[MUSDB18-7-STEMS](https://github.com/sigsep/sigsep-mus-db/releases/download/v0.4.0/MUSDB18-7-STEMS.zip).
The audio is never included in a production release by this builder.

Primary Android references checked for this design:

- [Context.createPackageContext](https://developer.android.com/reference/android/content/Context#createPackageContext(java.lang.String,int))
  documents resources-only access without `CONTEXT_INCLUDE_CODE` and the code
  loading security distinction.
- [Package visibility declarations](https://developer.android.com/training/package-visibility/declaring)
  documents the specific-package `<queries>` declaration.
- [createPackageContext security](https://developer.android.com/privacy-and-security/risks/create-package-context)
  describes the risk from combining code loading with ignored security checks;
  neither flag is used here.
- [Application manifest](https://developer.android.com/guide/topics/manifest/application-element#testOnly)
  documents the ADB-only `testOnly` install restriction.
- [Storage Access Framework](https://developer.android.com/training/data-storage/shared/documents-files)
  documents user-selected document creation without broad storage permission.
- [ONNX Runtime 1.25.1](https://github.com/microsoft/onnxruntime/tree/v1.25.1)
  is pinned by `android/native-runtime.json`; no newer runtime is invoked or
  substituted by this probe.
