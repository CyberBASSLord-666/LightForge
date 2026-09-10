# Preserved readiness diagnostic failure — not release eligible

Focused diagnostic run [34420755126](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34420755126) used probe source `19951891b878984937fd34dce3696f2a64609684`. Both the background lifecycle and diagnostics receipts failed. The downloaded artifact ZIP was checksum-verified before extraction: SHA-256 `1ae53530c1cb3b4175d66a48df7191867d5d787dc174f86fee88cdfefebf4e08`.

## APK identity and limited purpose

The preserved `diagnostic-input/provenance.json` identifies input CI run `34417512894`, input production source `222fe9956f91579b34d80b1cad2f993b52b5fbb4`, and no production-source difference in `android/`, `web/` or `version.json` at the probe head. It records **127 unchanged non-signature APK ZIP entries** and a new temporary diagnostic signer. The input payload inventory and APK receipt are retained alongside it. The diagnostic APK has SHA-256 `8653d55aa394179d267cc75402bb8eeb016483d5296c190929c5c3b472bd1e98`, is `update_compatible: false`, and was explicitly marked `diagnostic_only: true` / `release_eligible: false`. This run and APK cannot substitute for a passing production release workflow or the original-signed update.

## Background lifecycle observation

Studio native separation, neural analysis and choreography completed with the Activity destroyed, screen off and Doze active; the project was durably saved (recorded job elapsed time **311.445 seconds**). The subsequent reopened-preview readiness wait exceeded its unchanged 45-second deadline before the visual-state callback stage. The last completed state probe, at **32.98 seconds**, showed `composing`, `backgroundApplying` and `backgroundSyncPending` true; `previewModelReady` false; and two preview frames while the preview was visible and unpaused. Bootstrap inventory was ready, the document was complete, and no context loss was reported. The final probe stage was `waiting-for-javascript-response`. These observations do not prove which pending work caused the timeout.

The completed-project reconnection assertion, Balanced execution, cancellation/Resume and timeout cleanup were not reached. The background receipt's broad `scope` describes the intended suite; only its one completed `checks` entry is passing evidence from this run.

## Diagnostic export observation

The original diagnostic verification log records six completed native-side checks: no broad storage permission, extraction of an intentionally generated native SIGILL tombstone, compatibility-guard persistence, uncaught-worker crash history across restart, two readable unique Downloads reports, and the selected-URI export helper. It then fails in `verifyJavascriptExport` with `JavaScript callback timed out`. The outer failed diagnostic receipt retains an empty `checks` list; it is preserved unchanged rather than rewritten from the partial log. This does not verify the JavaScript Guide export or the remaining renderer-recovery flow.

No LightForge ANR or out-of-memory failure was identified in the captured diagnostics. Both original last-ANR reports say no ANR since boot. The full captured logcats also contain boot-time Google Play services ANRs; those earlier events are not evidence of a contemporaneous cause for the LightForge callback timeouts. The logcats remain in the source artifact and are not rewritten into a causal explanation here.

## Exact preserved files

The original files below are copied byte-for-byte. Earlier ANR, readiness-timeout and numerical failure directories remain unchanged. None of these failed records is promoted to a current passing gate.

| Original file | SHA-256 |
| --- | --- |
| `android-background-verification.json` | `4e067842c462e31c6f1307b155412be7afc98468b26bea37e73f6ed65b9a1b25` |
| `android-background.log` | `ce345924f0c897e8cc8cb679ce4b7ce0deb11de8cf006739f5cd8088c30dd6ac` |
| `android-background-progress.json` | `6b46974e14dbb2685b77e853988cc8f03d7b3172365e39410063269974499d73` |
| `android-diagnostics-verification.json` | `bab799daca8e8fd092d376f99f09dcb610ed2a0631180e100c7e871b5e44f5c9` |
| `android-diagnostics-verify.log` | `9be88dc3b406077ebe6dccc2cd938ecab7c27bacbf4bb8ec02d7506b97599327` |
| `android-last-anr.txt` | `42cf4931006fd0ff42d3522af31f9346431b409aa22a793ecc16b5aedeed28a1` |
| `android-diagnostics-last-anr.txt` | `42cf4931006fd0ff42d3522af31f9346431b409aa22a793ecc16b5aedeed28a1` |
| `diagnostic-input/provenance.json` | `ac3d098035e92fa0f26d7f5ccd949c187294323f17f7c1b7e84594a440173b79` |
| `diagnostic-input/input-payloads.json` | `f3e2c33d153886beaa64e5b5965c5f71055be504e94cc4e311be7c70e5217e7a` |
| `diagnostic-input/LightForge-2.2.4.apk.json` | `61bf5b3cf057e70282f5b9fae0278c18597844b3ad8da69eb3c48b3ab299d8d4` |
| `diagnostic-input/LightForge-2.2.4.apk.sha256` | `7aebd70ac973a0f20f598983af37f3d93866ea5248b22af7a40413acdabb3722` |
