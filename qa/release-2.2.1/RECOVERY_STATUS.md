# 2.2.1 recovery status

The release is **not published**. Application source remains unchanged from `0527d778e1456ff607373a4c9ec546500b0153e5`; later changes concern testing, publication and documentation.

## Completed evidence

- Source-bound native/WASM numerical equivalence, source-clock reconstruction and 18 fresh downstream role cases pass. The role cases use fixed original-model separation estimates, not 18 newly separated native-runtime songs.
- The refreshed local regression run passed 145 Node and 33 Python checks, including current source bindings for the updated instrumentation and runner.
- Production run [34162369481](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34162369481) passed its verification job, including Chromium, full model inference, candidate APK and native checks. Its Android job hit the runner's 1,200-second outer limit without a final lifecycle result.
- Probe [34166156881](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34166156881) verified provenance, Java/instrumentation compilation, exact application payload preservation after temporary re-signing, matching ephemeral app/test certificates and 16 KiB alignment. Its first real native Studio fixture completed in about 325 seconds with the Activity destroyed, display off and Doze active; reopening recovered the saved show. The second fixture failed before analysis because the test did not establish forced Doze again. This was not a complete cancellation/resume pass.
- The corrected instrumentation waits for actual screen-off/Doze state and retains its assertions. The runner streams progress and preserves partial results within a bounded 3,000-second instrumentation budget. The production Android job now has a compatible 65-minute budget.

## Current recovery and pending work

The executor reconnected with an empty workspace. Current source and retained evidence have been restored from GitHub. The original private signing identity has been recovered from its separate backup. All 73 declared analysis assets were restored from the exact verified CI candidate and checked against their pinned manifests; the new original-signed build is underway. No private signing key is published to GitHub.

Production verification [34168172741](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34168172741) and same-payload Android probe [34168136295](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34168136295) are running. Final status must come from their completed results, not this checkpoint.

The previous original-signed APK was verified at **1,171,728,522 bytes**, SHA-256 **47feff4738179a0d89fc2eeeb33791e90e5a25e93bbc1232f2341ca6e2ef1652**. That scratch artifact was lost when the executor reset; it is historical build evidence and must not be substituted for the rebuilt APK's checksum. The required original certificate remains **7187d6aa935d5b7d2d656cb87913af95fe1ca3a4b1653036d1d8d890e2016c6b**.

Remaining steps are the complete Android cancellation/resume/timeout result, successful final production CI, complete current source-bound gates, original-signed package verification, candidate-index transfer, publication and uploaded-asset verification. Keep release documentation marked pending until those results are confirmed. Physical phone/full-song, thermal/manufacturer battery behavior and Tesla timing remain unverified.
