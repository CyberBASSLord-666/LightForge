# LightForge user guide

Start with the original-signed APK from the [latest published release](https://github.com/CyberBASSLord-666/LightForge/releases/latest).
Install over the existing app to keep private projects. A development or CI APK
is not a compatible update. Export backups before clearing Android app storage,
uninstalling or changing phones.

## Create a show

Select **Choose music**, choose an unprotected local audio file, choose a style
and analysis mode, then select **Create my light show**. WAV, MP3, M4A/AAC, FLAC
and OGG/Opus support depends on Android's installed decoders. Protected streaming
downloads are not ordinary importable files.

The importer prepares the export soundtrack as stereo 44.1 kHz PCM16 WAV and a
separate analysis representation. Already compatible PCM samples are preserved.
Analysis and cached listening layers never replace the original-quality export
soundtrack.

Studio uses full Deux separation and the full rhythm transformer. Balanced uses
MDX separation and the compact rhythm transformer. Both use GAME sung-note
analysis. These modes have different resource costs; they are explicit user
choices, not interchangeable quality settings. Analysis can take much longer
than the song and requires substantial memory and temporary storage.

Festival, Cinematic and Pulse supply different visual styles. Fine tune offers
light intensity, movement frequency, timing offsets, rhythm interpretation,
interior palettes, voice/bass emphasis and individual section edits. The export
frame interval is 15 or 20 ms. Finer command placement does not imply equally
accurate music detection or faster physical movement.

## Musical expression

**Follow musical expression** is recommended for new shows. It gives detected
vocal accents and held notes their own emphasis and lets repeated musical
sections develop related visual patterns. Existing saved shows keep their
original setting. Turn it on to update an older arrangement; when enough music
detail is already saved, the update needs no new separation or transcription.
Older analyses may need **Create** once more. You can turn it off or use **Undo**
to return to the previous arrangement.

## Background analysis and recovery

Use **Continue in background** to switch apps or turn off the display. Allow
notifications; the foreground-service notification reports progress and offers
Cancel. Reopening the app reconnects to the job or opens the saved result. The
elapsed-time display is not an estimate of time remaining.

For screen-off work, use **Allow screen-off processing** or
**Guide → Allow background battery use** when offered. Android and manufacturer
battery restrictions remain system-controlled. Force stop, reboot, process loss
and platform time limits can interrupt a job; no unlimited execution is promised.

**Resume analysis** validates source identity, settings, execution lineage and
completed checkpoints. Matching work can be reused; a damaged or interrupted
passage is recomputed. The last saved show remains available after cancellation
or failure. Import/export document pickers still require returning to the app.

## Review and correct synchronization

Use the Compose, Music, Outputs and Review workspaces to inspect an arrangement.
Listen to Full song, Voice or Instruments and loop the relevant passage. Singing,
speech, pitch, bass and phrase estimates may be wrong; they are not transcribed
lyrics, word alignment or ground truth.

In **Edit musical cues**, choose Voice or Bass and set explicit start/end times.
Accent produces a short gesture, Hold a sustained gesture, and Ignore this part
suppresses automatic role cues over the chosen range. Pitch and labels entered
here are user-authored. Same-part overlaps are rejected; different parts may
coexist. Undo/Redo includes these changes.

**Correct timing for a musical part** shifts automatic estimates. Negative
corrections move them earlier; explicit cue times are not shifted. Individual
output switches and cues keep final ownership.

**Review synchronization** compares selected targets against final lamp commands,
including output edits, and reports seekable exceptions. It does not measure
vocal-detection accuracy, human preference or physical Tesla latency. Its report
is included in the exported ZIP.

## Edit lights and movement

In **Lights & dance editor**, choose an output to inspect its channel addresses,
supported commands and coverage notes. **Inspect in preview** isolates the output
without editing the saved show. Include/mute switches apply to the final sequence.
Light/RGB cues overlay the arrangement within their range. Manual moving-part
cues replace that part's automatic track; restore automatic control to remove
the manual track.

Lamp commands support documented on/off and fixed-duration fades where available,
not arbitrary steady dimming. RGB zones accept colors. Movement needs time to
prepare, travel and return; the editor/compiler checks prerequisites and command
budgets. Mirror Dance is unavailable. A Dance command does not expose control of
each physical stroke's cadence.

The preview visualizes the compiled sequence and estimated movement state on the
Highland Model 3 model. Camera, stage and preview-quality choices do not change
exported commands. Model geometry, lamp glow and travel envelopes are not physical
vehicle calibration. Inspect the actual vehicle in safe conditions before relying
on its behavior; do not operate a light show while driving.

## Projects, backup and cache

**My shows** keeps independent automatically saved projects. Rename, duplicate or
delete them in the collection. Duplicate a project to keep a permanent alternative;
A/B comparison arrangements are session-scoped.

Exported LightForge ZIPs contain the matching soundtrack and editable project.
Use **Restore backup** to create a new project from one. A usable checked frame
snapshot reopens its saved arrangement; a backup without one requires recreation.
A generic FSEQ/audio ZIP without the project JSON cannot restore all editing data.

Opening a saved arrangement does not silently recompose it with newer software.
Recreate/re-analyze deliberately to adopt changed analysis or composition. Cached
Voice/Instruments listening layers are replaceable; clearing cache or restoring a
backup may require regenerating them. They are not the export soundtrack or the
only copy of the saved show.

## Export to USB

Select **Export USB-ready show** and choose a location in Android's Save dialog.
The exporter validates FSEQ bytes against the soundtrack, checks movement budgets,
and verifies ZIP-entry sizes and CRCs before presenting the completed archive.

| Path in the exported ZIP | Purpose |
| --- | --- |
| `LightShow/lightshow.fseq` | Uncompressed FSEQ 2.0, 200 channels |
| `LightShow/lightshow.wav` | Stereo 44.1 kHz PCM16 soundtrack |
| `Review/LightForge_Project.json` | Editable project backup |
| `Review/Validation.json` | Software validation results |
| `START_HERE.txt` | Installation instructions |

Follow `START_HERE.txt`. Extract the ZIP and place `LightShow` directly at the USB
root, not inside an extra enclosing folder. Use a supported exFAT/FAT32 drive and
the vehicle's data-capable USB port. Select the custom show through the vehicle's
Light Show controls. Avoid mixing the show drive with TeslaCam or update files.
The software validation report does not establish physical timing or suitability
of a particular parking location.

## Report a problem

Reproduce the problem, reopen the app if it closed, then select
**Guide → Export diagnostic log**. The report goes to Downloads/LightForge on
supported Android versions; older versions use a system save dialog. Include the
steps, approximate failure time, analysis mode and whether it happened after
screen-off/resume. Do not include private music or projects unless deliberately
sharing them through an appropriate private channel.

Logs include bounded recent events, errors, analysis stages, device/WebView
versions and available exit information. They remain local until exported and
exclude attached audio and saved-show payloads. Review them before public sharing;
redaction is not a reason to assume every diagnostic detail is anonymous. A killed
process may not record its own last event.

[Validation and limits](../VALIDATION.md) explains what the published release
actually demonstrated. [Architecture](../ARCHITECTURE.md) and the
[engineering index](README.md) are for development rather than app setup.
