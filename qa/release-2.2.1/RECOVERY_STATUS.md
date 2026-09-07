# 2.2.1 recovery status

The release is **not published**. Application source is unchanged from `0527d778e1456ff607373a4c9ec546500b0153e5`.

- 145 Node and 33 Python checks passed locally; current numeric equivalence and 18 fresh role cases passed.
- Production run [34162369481](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34162369481) passed its verify job, including Chromium, full model inference, candidate APK and native checks. Its Android job hit the runner's 1,200-second outer limit; it did not produce a final lifecycle result.
- The diagnostic logs show native loading and later Activity reopening, followed by continuing native allocation/progress messages. These observations do not substitute for a passing test receipt.
- Tests have been corrected to background their later long-running fixtures, retain their original per-phase assertions and limits, stream phase/job snapshots, and use a compatible bounded outer budget. A same-payload diagnostic probe compiles the tests and checks every application ZIP payload byte after temporary re-signing. Its key is ephemeral and cannot update the user's installed app.
- The locally built original-signed APK was verified at **1,171,728,522 bytes**, SHA-256 **47feff4738179a0d89fc2eeeb33791e90e5a25e93bbc1232f2341ca6e2ef1652**. The original signer is **7187d6aa935d5b7d2d656cb87913af95fe1ca3a4b1653036d1d8d890e2016c6b**.
- The local executor disconnected with `409 environment_offline`. The APK, signing identity and remaining local build work cannot currently be accessed. No private key was uploaded. This branch preserves the completed source and evidence.

Next steps: inspect the native recovery probe; fix any actual failure; update the main workflow's Android job budget to cover the corrected runner; obtain a successful complete release-candidate run; reconnect the local workspace, refresh the current six gates, package and transfer the original-signed APK using the verified candidate index; publish and verify the release assets. Physical phone/full-song and Tesla testing remain unverified.

## Latest remote checkpoint

Probe [34166156881](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34166156881), test commit `d5558c7f1eaee20b7dcd9a50805dc9b1462d8539`, passed provenance, Java/instrumentation compilation, direct re-sign, exact application payload comparison, matching ephemeral app/test certificates and 16 KiB alignment. Emulator startup was underway at the last check; this is not yet a lifecycle pass.

The workspace was retried after those checks and still returned `409 environment_offline`. Reconnection is required to retrieve the original-signed APK and complete its release transfer. Current original application source, all prior successful evidence, publisher fix and revised test infrastructure are preserved on this branch. Do not apply the prepared final-release documentation or claim publication until the remaining gates and signed transfer succeed.
