# Corrected fixture: background still failed, diagnostics passed

Focused run [34424613238](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34424613238), job `102707075798`, used corrected-fixture source `57e6ee996bd8f9d135e89334585efe90d8667b68`. Background lifecycle **failed**; the separate Android diagnostics suite **passed all eight checks**. These diagnostic-only results do not constitute release eligibility.

Studio native separation, neural analysis and choreography completed under screen-off/Doze and durably saved the project (recorded job elapsed time **311.944 seconds**). Reopening still exceeded the unchanged **45-second** readiness deadline. The retained last completed JavaScript state sample is from **21.23 seconds**, not the deadline: composition and background application/synchronization were pending; project loading was false; the preview model was not ready and had rendered zero frames. The probe was then waiting for another JavaScript response. This stale snapshot cannot establish the state throughout the remainder of the wait. Reconnection, Balanced execution, Cancel/Resume and timeout cleanup were not verified.

The [portable settings proof](../fixture-settings/README.md) independently reproduces the earlier five-versus-27-settings digest mismatch using the actual app and composition worker, then verifies the complete-settings case preserves the input/frame hashes and clears pending state. Its sources and outcomes are bound in `fixture-settings/verification.json`. It is hosted component evidence without audio inference, GPU rendering or Android performance coverage. The corrected real Android run still fails, so the demonstrated settings bug does not fully explain or resolve the remaining reconnection failure.

The eight passing diagnostics checks retain their API 35 emulator scope: storage permission behavior, intentional native tombstone extraction, compatibility selection, worker-crash persistence, repeated readable Downloads reports, selected-URI export, actual Guide JavaScript export and detached/repeated renderer recovery. They do not certify background lifecycle completion or physical-device performance.

All **127 non-signature payload contents** match the preceding patched APK for production source `a011934731bbdb8d59b913634f6efde07f656e6d`; relative to the older base, provenance records 124 unchanged entries and three exact reviewed web replacements. The newly temporary-signed diagnostic APK SHA-256 is `31bfc009bf3f3490833178909db6fe8d2af71d6ff38b730160d060b58826f82e`; `update_compatible` and `release_eligible` remain false. This APK cannot replace the original-signed release artifact.

The original files below are copied byte-for-byte from final artifact **10132473889**, verified ZIP SHA-256 `6853b50265a562813bb4ff191492795ac33834261fa6bb778270f16f2eaf4cae`. `artifact-metadata.json` is also preserved exactly. Older history remains unchanged; no failed record is rewritten as passing.

| Original file | SHA-256 |
| --- | --- |
| `android-background-progress.json` | `af0027a85e6867e54f44b012864dfc1ab6f1ac8e3ae1d14f79d54df17108e8ba` |
| `android-background-verification.json` | `1ac855571c9fbcfd13279d94eb6dc78e62a2e5fb321c5a188964590ea5af46f5` |
| `android-background.log` | `e97278882211af119fb88b63651956178a2c9db486c33d6e47e3522ee02087b3` |
| `android-diagnostics-cleanup.log` | `9d0e795c020d29db77e3012246bc3d685f58a3f3c66852cab3433bef858c1038` |
| `android-diagnostics-crash.log` | `f12a981274c3cbc49f9537c4e85577aabcc7fd2c67a815870e808fcfd297ff80` |
| `android-diagnostics-native-crash.log` | `5ff1812f485e94e3c1b73b67bf98f29632345aef76caa6f4071309c61ae2ead3` |
| `android-diagnostics-verification.json` | `9901de0c59d695fefbe10f7e8655b976bb99a3945876967cd8cf2c3640921ed4` |
| `android-diagnostics-verify.log` | `d1f5a55fd59c8ceb76b7471f57417929e98212202c8150e044ef5a3ab9c334d3` |
| `android-last-anr.txt` | `42cf4931006fd0ff42d3522af31f9346431b409aa22a793ecc16b5aedeed28a1` |
| `artifact-metadata.json` | `3bf971e0bc2f4f25e26c9c43a2765799f02f038a54c43aa6f904db3a0a490c8e` |
| `diagnostic-input/LightForge-2.2.4.apk.json` | `61bf5b3cf057e70282f5b9fae0278c18597844b3ad8da69eb3c48b3ab299d8d4` |
| `diagnostic-input/LightForge-2.2.4.apk.sha256` | `7aebd70ac973a0f20f598983af37f3d93866ea5248b22af7a40413acdabb3722` |
| `diagnostic-input/input-payloads.json` | `c8b7c28d5a48eb3d956d6b8a19e121cf2e7e33d1c2af037a2b0f6e6ceaf5317f` |
| `diagnostic-input/patched-payloads.json` | `af1089434e8181dc10e0b50dacb7308c5d6a2d8d88d90d27e64d97a4c91d3780` |
| `diagnostic-input/provenance.json` | `25ea3d4bce4a4d8437761f04ba74737ef1c591f9c1e93a0c72b7b54e00e1fe24` |
| `diagnostic-input/reviewed-web-patch.json` | `edf75f5e2be8f70f82dfa1eb9f7e2574f308788480d73298a6be607ca9cee701` |
