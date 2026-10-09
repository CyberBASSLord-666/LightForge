# Diagnostic companion 2 artifact

This archive records a build and independent artifact inspection of the separate
development companion. It contains no phone execution or production release
qualification. Historical companion 1 and run01 receipts remain unchanged.

| Artifact property | Observed value |
| --- | --- |
| Package | `com.cyberbasslord.lightforge.inferenceprobe` |
| Version | `2` / `probe-2` |
| APK bytes | `113915300` |
| APK SHA-256 | `79dba57cc55d0fc61e42aa245f0f94c7a1d826aa184bb6be08026ff931712429` |
| Embedded source-receipt SHA-256 | `b9b5991ab8746e96ef28675f23d6309ce5f985003df4d6f12ee4d5360d52d83b` |
| Compiled closure | 15 source files, 75 classes |
| Runtime | Original pinned ONNX Runtime 1.25.1, four ABIs |
| Production model graphs in APK | None; the companion validates installed LightForge 20401 and reads its public model assets |

The complete APK remains at
`build/inference-device-probe/run-jipwai4p/LightForge-inference-probe.apk`.
The separately prepared `LightForge-inference-probe-2.apk` copy was checked
byte-identical before upload. This archive does not include either APK.

[build.json](build.json) and [source-receipt.json](source-receipt.json) are exact
copies from the fresh build directory. The source receipt includes every emitted
class's source hash, compiled class hashes, the compiled JAR hash, manifest and
builder identities, runtime pins and exact fixture provenance. The frozen
source tree and compiled classes remain in that build directory.
[build.log](build.log) preserves the builder's completion output.

[verification.json](verification.json), [signature.txt](signature.txt) and
[badging.txt](badging.txt) record independent checks: one nonproduction signer,
APK signature schemes v2/v3, 16 KiB alignment, version 2, no requested Android
permissions, exact asset/runtime/DEX inventories and bytes, class JAR bindings,
and all current source hashes. The frozen policy uses qualification ordinals
0/1/2. Candidate evidence keeps auxiliary profiles separate and explicitly
distinguishes model-file preparation from operating-system cache equivalence.

This signer differs from companion 1, whose temporary signing key was destroyed.
Installation therefore requires preserving the old companion's exports and
replacing only the development companion. Installed LightForge and its private
projects are separate. No installation or phone operation was performed by this
artifact inspection.

Use this directory's new build/source receipts and the new frozen build directory
when analyzing a later export with `--require-current-source`; the analyzer's
default references intentionally remain bound to historical run01.
