# LightForge 2.0.0 — Precision Studio

Version code **20000**. Install the update-compatible APK over the existing app; do not uninstall first. It uses the original LightForge signing certificate.

## Musical control

- **Precision Studio** turns a detected voice phrase, articulation, voice note or bass note into an editable musical cue. Add cues at the playhead, name them, set millisecond-resolution start/end times, loop the passage, and choose Accent, Hold or Ignore.
- Musical edits are stored separately from model evidence. They survive save/reopen and backup export, participate in Undo/Redo, and stay with their own project. Voice and bass edits can overlap each other; conflicting edits within the same part are rejected.
- Separate **Voice correction** and **Bass correction** shift automatic events by up to two seconds in either direction. User-entered cue times stay on the original soundtrack clock; the whole-show offset applies afterward.
- Held bass gestures release in time for later entrances on the same lamp. If a preferred lamp is muted, the composer uses suitable enabled alternatives for voice and bass.
- Explicit held cues can span an arrangement-section boundary. Ignoring a region preserves interpretation outside that region. Other musical layers continue to shape the show.

## Review the actual result

The synchronization review compares selected musical targets with the **final exported lamp commands**, after individual output edits and mutes. It shows matched targets separately for voice and bass, frame-placement error, and seekable moments where a cue was suppressed or the lamp was already active. The same review is included in `Review/Validation.json` inside the exported ZIP.

These numbers describe translation into commands, not the accuracy of the detector, lyric/word alignment, or measured vehicle response. They are not an overall musical-quality score. Intentionally sparse choreography may leave some targets unmatched.

## Reliable upgrades and builds

Existing 1.4, 1.5 and 1.6 snapshots reopen with their exact checked frame payload. Recreate an arrangement when you want the new routing and synchronization review. Re-analysis is unnecessary for an existing complete 1.6 analysis. Changed or corrupted snapshots are still rejected; the upgrade path only accepts known default additions.

The build now checks consistent runtime version metadata and prevents accidental creation of an incompatible signing identity. Fresh development signing requires an explicit opt-in and is identified as incompatible with the original install. The production packager checks source-bound test receipts, the APK's exact bundled bytes, package version, checksum and original update certificate.

## Verification and limits

The repository includes Node engine and worker tests, actual-app DOM integration, native JVM storage/audio/export validation, and Chromium CI checks with responsive screenshots. `VALIDATION.md` explains their scope. CI uses a temporary signing key solely for build verification; its package is not the install-over update.

The bundled Beat This!, UVR MDX-Net and Frame-MN10 models and analysis code are unchanged from the verified 1.6 release. This release improves musical control, composition and verification; it does not claim a newly trained model or an unmeasured increase in vocal detection accuracy. All inference remains offline with no account or model setup.

No physical Android phone or Tesla test is claimed. Source separation and musical-event timing remain estimates; Tesla controls physical lamp/motor response and Dance cadence.
