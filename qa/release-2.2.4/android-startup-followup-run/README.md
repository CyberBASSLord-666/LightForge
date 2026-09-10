# Startup follow-up: background failed, diagnostics passed

Focused Android run [34422870517](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34422870517) used source `a011934731bbdb8d59b913634f6efde07f656e6d`. This is diagnostic-only evidence, not a successful release workflow.

| Result | Observed scope |
| --- | --- |
| Background lifecycle: **failed** | Native Studio separation, neural analysis and choreography completed under screen-off/Doze and saved the project (279.414 seconds recorded job time). Reopening exceeded the unchanged 45-second readiness deadline. Completed-project reconnection, Balanced execution, Cancel/Resume and timeout cleanup were not verified. |
| Diagnostics: **passed, 8 checks** | Android API 35 emulator checks cover storage permissions, intentional native SIGILL tombstone extraction, compatibility-guard persistence, uncaught-worker crash history, repeated readable Downloads reports, selected-URI export, actual Guide JavaScript export, and detached/repeated renderer recovery. This does not establish neural inference, physical-phone performance or a complete background lifecycle. |

At the final 45.005-second readiness probe, `loadingProject`, `backgroundApplying` and `backgroundSyncPending` were true; `composing` was false. The preview model was ready, visible and unpaused after five rendered frames. No context loss was reported. The probe alone did not establish the cause; a later deterministic production-worker reproduction is recorded below. The failed background receipt and passing diagnostics receipt retain their distinct original results; neither is rewritten to summarize the other.

A subsequent deterministic reproduction with the unchanged production worker confirmed a fixture error: the Android fixture compiled a project with five settings, while the UI merged 27 complete settings during reopening. The worker's `inputDigest` correctly rejected the different settings; the next polling retry reproduced `loadingProject: true` with `composing: false`. The correction changes only the fixture to read the complete actual UI settings before applying the same five overrides. Its Java compilation passed; a fresh Android run is still required. Production validation, model execution and this run's original failed receipt are unchanged.

The preserved provenance records exactly three reviewed web replacements (`web/app.js`, preview source and generated renderer) over the earlier CI APK; 124 other non-signature entries retain identical metadata and raw/uncompressed bytes. The patch manifest, input and patched inventories are preserved. The tested APK has SHA-256 `b11642686ee62271b7bbfac88ee256ee5af1106bafeeef1ad1d03061391d4402`, a new temporary signing certificate, `update_compatible: false`, `diagnostic_only: true` and `release_eligible: false`. The eight-check diagnostics pass cannot authorize this APK for release or substitute for all seven current production gates.

Original files are copied byte-for-byte from final artifact **10131880266**, ZIP SHA-256 `f3d7b1a84a483ea99a53fbc67a275f495f3fc7d22dc3fa47d206f413bc710120`. Earlier artifact **10131856655**, ZIP SHA-256 `f24ff6a9986926d2dff11ebea7b9dff080b0bfec23f7c30987dbf79f68b8c55b`, contains identical overlapping background/provenance records. Both downloads were checksum-verified before preservation. All older history remains unchanged.

| Original file | SHA-256 |
| --- | --- |
| `android-background-verification.json` | `0537cbeaa8b06379f28180eb96c21ac6bcccebbb5f39871c8c360abb99ce28ab` |
| `android-background.log` | `45c395d1f8932d616a12b65073f7ab498efd9ed647c60d22c90e29c94f33670e` |
| `android-background-progress.json` | `7b2f9b6be587ab89ad963c46b7a6200c4cc7cbd51b5b1b0526f5374bd67006fd` |
| `android-last-anr.txt` | `42cf4931006fd0ff42d3522af31f9346431b409aa22a793ecc16b5aedeed28a1` |
| `android-diagnostics-verification.json` | `3983b89de56bf0a5f49cf88fa0f3dc10b2d4db8672990cc871803df2d43ed10e` |
| `android-diagnostics-verify.log` | `6d4072638ffc58e506271d1d62d56cee87f62cb11ea69c6982316c1c93a8f43d` |
| `android-diagnostics-crash.log` | `728b073f484ba96eee9f377dce7fb6eb357d3508a1c4a6b87f25fdfc5e148d68` |
| `android-diagnostics-native-crash.log` | `d750b2ad0e7a359b82900285aecdd30e98b5c57ec779599417c6f061b597f564` |
| `android-diagnostics-cleanup.log` | `a26162371788f60769004fd6c6c959806a1953614d9a9215ae95ca873af44f23` |
| `diagnostic-input/LightForge-2.2.4.apk.json` | `61bf5b3cf057e70282f5b9fae0278c18597844b3ad8da69eb3c48b3ab299d8d4` |
| `diagnostic-input/LightForge-2.2.4.apk.sha256` | `7aebd70ac973a0f20f598983af37f3d93866ea5248b22af7a40413acdabb3722` |
| `diagnostic-input/input-payloads.json` | `c8b7c28d5a48eb3d956d6b8a19e121cf2e7e33d1c2af037a2b0f6e6ceaf5317f` |
| `diagnostic-input/patched-payloads.json` | `cb121af80a5ae95990b5417397385bd9c21544485a4e1b36e48ae47720231174` |
| `diagnostic-input/provenance.json` | `36fc9437b8b9fba091933cf992a7b4e09ad913e26ea84bbcd454f5ec47f845f2` |
| `diagnostic-input/reviewed-web-patch.json` | `edf75f5e2be8f70f82dfa1eb9f7e2574f308788480d73298a6be607ca9cee701` |
