# Isolated device probe rebuilt from `9435489` inference source

The diagnostic companion was built with the pinned JDK 17, Android SDK 35,
ONNX Runtime 1.25.1, verified original model manifest, and exact Falcon fixture.
The 15 emitted Java sources in the embedded source receipt match Git commit
`9435489` and the build-time checkout. Later research-only commits did not
change these inputs. The current `NativeDeux.java` SHA-256 is
`869a482938c63eab530cc410d9054a0813eddab3b7d70454b06c57af6a28f771`.

The APK has SHA-256 `647c6e69fed382193e8400845a206bd41fa8bffa11b4490907995ed195aa99d1`
and is 113,915,300 bytes. It is an isolated `com.cyberbasslord.lightforge.inferenceprobe`
version 2 package, signed by a temporary development certificate with SHA-256
`3b4e0984a0af5a1efb073de867b71aafabdc773c42f93fe073ad8640d701a102`.
Independent verification found one signer, valid v2/v3 signatures, 16 KiB
alignment, valid ZIP entries, and no requested permissions. The release signer
was not used. The APK was not installed or run by this build.

`LightForge-inference-probe.apk.json` is the builder's signed-APK receipt;
`source-receipt.json` is the exact embedded receipt. `verification.json` records
independent source, class, fixture, manifest, package and signature checks.
`archive.json` inventories the bounded receipts and frozen builder source. The
APK, original model graphs, Falcon audio, compiled binaries and temporary
signing key are excluded from Git. The APK is intended only for staged device
diagnosis; it is not a production release or evidence of phone acceleration.
