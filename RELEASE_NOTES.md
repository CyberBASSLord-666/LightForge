# LightForge 2.2.0 — Work beyond the screen

Version code **20200**, using the original LightForge signing identity. Install the complete APK over your existing app without uninstalling.

## Background creation

- Create runs in its own Android foreground service, including the neural analysis and full choreography/compiled-frame save. Switching apps, locking the screen or dismissing the Studio Activity does not cancel the job.
- The ongoing notification reports progress and offers Cancel. Completion is durably saved before the service stops, and reopening the app restores the current job or completed show.
- **Continue in background** leaves the Studio while work continues. **Allow screen-off processing** opens Android's user-controlled battery exemption for long jobs. Notification settings, battery settings and memory/core information are available in Guide.
- Cancellation and failure preserve the previous saved show. Finished analysis is checkpointed before choreography and can be reused on Retry when the original saved inputs match exactly. Mid-analysis interruption restarts that pass.
- Android 15 media-processing time limits, Force stop, reboot and OEM memory/battery policy remain effective. The app handles timeout/interruption and releases its worker, service and wake lock instead of claiming unlimited execution.

## Verification and scope

The release requires Node/Python regressions, browser UI, real public model inference, unchanged-source numeric model evidence, native project/format tests and an Android emulator lifecycle check. The emulator check exercises real background inference with the Activity destroyed, screen off and a user-equivalent battery exemption, plus notification cancellation and the timeout callback. Emulator results do not certify physical Samsung battery management, thermals or Tesla timing.

Models, precision settings and the offline boundary are unchanged from 2.1. Model licenses retain their noncommercial restrictions. No root access, microphone, overlay, accessibility or Internet permission is added. File-picking dialogs still require the app's UI.

# Included from 2.1 — Studio cockpit and neural singing



## Music intelligence

- Studio mode upgrades vocal/instrumental separation to **Mel-Band RoFormer Deux**. The complete model runs offline with its full 13-second attention context, both trained source heads and original checkpoint values evaluated as Float32. Sequential stages and bounded reads control memory without dropping layers or quantizing weights.
- **GAME Large 1.0.3** supplies learned sung-note boundaries and pitch. Its eight-step diffusion uses reproducible noise. Singing/speech evidence and actual separated-waveform expression gate the notes; speech and unsupported regions cannot become confident sung gestures.
- A short, quiet singing passage can use agreement between GAME and independently measured source pitch when the general singing classifier is weak. This remains explicitly uncertain evidence and cannot bypass speech, source-energy or minimum-duration guards.
- A full-resolution 44.1 kHz Float32 voice cache retains the original soundtrack clock for transcription. Context overlap and note continuation handling avoid inserting attacks merely at chunk seams. Playback, manual edits and export remain on the original audio clock.
- Balanced mode retains the lighter MDX separator and compact Beat This rhythm model. Both modes include GAME. Model failures are visible; the app never silently substitutes a weaker analysis.
- Bass notes continue to follow low-register harmonics in separated accompaniment. This is not isolated bass-source recognition, lyrics or word alignment.

- Closely spaced bass notes cannot create negative hold lengths. Shared fallback lamps are deduplicated; unschedulable entrances remain visible in synchronization review.
- Full-resolution cache encoding reuses one 64 KiB scratch buffer while preserving exact Float32 sample bytes.

## Studio interface

- Tesla-inspired monochrome surfaces, restrained red actions, tracked typography and a Model 3 vehicle header.
- **Compose / Music / Outputs / Review** workspaces consolidate the existing editor, with keyboard-operable tabs and preserved controls, shortcuts, Undo/Redo and project persistence.
- A zoomable source-time score brings voice notes, bass notes and explicit musical edits together. The audio clock drives its playhead; timing corrections are reflected in the displayed targets.
- Responsive layouts retain the 3D vehicle, playback, layer listening, output inspection, cue editor and export at phone, tablet and desktop widths. Motion and offscreen drawing remain bounded.

## Measured improvement and release scope

On the same six short MUSDB mixtures used for the previous separator comparison, vocal SI-SDR increased from **10.042 to 11.475 dB** on average. All six improved; the difficult Falcon excerpt increased from **3.058 to 7.044 dB**. Vocal RMS-envelope correlation increased from **0.9204 to 0.9740**. These are source-separation measurements on a small reference set, with possible training overlap; they do not establish universal model or choreography superiority.

The existing WebAssembly runtime executed the staged Deux graphs on the actual mixture with an exact source sample count. Conversion error is measured against the original PyTorch model separately from reference-song quality. Production browser inference, cache cancellation, musical editing, exact-byte export, migration, native storage/format checks and signed-asset inventory have distinct gates. See `VALIDATION.md` and `qa/release-2.1.0/` for their precise scope.

Studio quality substantially increases package size, working memory and processing time. Several GB of working memory are needed; phone performance depends on the device and WebView. Private analysis caches use approximately 21.2 MB per minute. The APK bundles all models and has no Internet permission.

Deux weights retain CC BY-NC 4.0, and original/modified GAME weights retain CC BY-NC-SA 4.0, with attribution and modification notices. This remains a personal, noncommercial app. Architecture code licenses do not replace model-weight licenses.

Physical Android install/long-track performance and the user's Tesla have not been tested in this workspace. Source-clock and FSEQ checks cannot certify physical lamp latency, motor travel or all phone configurations.

---

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
