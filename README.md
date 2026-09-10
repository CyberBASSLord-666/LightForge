# LightForge 2.2.4 — bounded long-run analysis

Current source is the **2.2.4 release candidate**. The verification/build job and new original-signed build pass; focused Android diagnostics pass all eight checks on a temporary test APK. A deterministic production-worker reproduction traced the remaining reopened-project timeout to an incomplete Android test fixture: its five saved settings differed from the 27 settings restored by the UI, so checksum validation correctly rejected it. The fixture now starts from the complete UI settings, retaining its same five overrides; compilation passes, and fresh Android verification is pending. Publication remains blocked on the complete lifecycle and final package gates. [2.2.2](https://github.com/CyberBASSLord-666/LightForge/releases/tag/v2.2.2) remains the latest published update.

This candidate bounds long Balanced runs, adds guarded native MDX execution, saves stage checkpoints promptly and preserves renderer recovery. Native initialization and inference share a cancellation-safe execution gate with Studio; failures retire native memory before the same-model WebAssembly fallback. Models, both denoise passes, GAME transcription steps and the original sample clock remain intact. No measured phone speedup is claimed before device testing.

LightForge turns music on your phone into an editable Tesla light show for a **2025 Model 3 Long Range RWD, North America**. It bundles its neural models, graphics and audio tools and works entirely offline.

**Native Studio analysis remains recoverable:** Studio separation uses native CPU inference on Android, while completed passages and analysis stages can be reused after interruption. Elapsed time, passage progress and resumed-work counts make long operations visible. The learned weights, full 13-second separation context, both source heads and Studio quality remain intact; failures do not silently switch to Balanced. Processing time and memory still depend on the song and device.

**The Studio cockpit includes:** a Tesla-inspired monochrome interface, source-time score, keyboard-accessible Compose/Music/Outputs/Review workspaces, Deux source separation and GAME Large singing-note transcription. Precision Studio retains editable voice/bass gestures, independent timing offsets and review against final exported lamp commands. See [release notes](RELEASE_NOTES.md), [build instructions](BUILD.md) and [validation scope](VALIDATION.md).

## Install the update

Install [LightForge-2.2.2.apk](https://github.com/CyberBASSLord-666/LightForge/releases/download/v2.2.2/LightForge-2.2.2.apk) over your existing app. **Do not uninstall first.** The release gate requires the original signing identity so the update preserves private projects. CI builds use a temporary identity and are not the update APK.

Android 8+ and a current Android System WebView are required. The app targets Android 15. No account, API key, subscription, server or model download is needed. Create runs in an Android foreground service, so you can switch apps or turn off the display. Studio uses native ONNX Runtime CPU inference with bounded batches and model buffers; it can still take longer than the song and needs substantial free memory and temporary storage. Balanced remains an explicit lighter choice. Separated listening audio needs about 21.2 MB per minute of music; recoverable passage checkpoints need additional temporary space.

## Background analysis

**Create my light show** now runs both analysis and choreography independently of the Studio screen. Use **Continue in background**, switch to another app, lock the screen, or dismiss Studio from Recents. The progress panel shows elapsed time, current passage, completed/reused work and when a model step has stopped reporting updates. Elapsed time is not a completion estimate. A notification shows progress, an elapsed-time chronometer and **Cancel**; completed shows are saved before the service stops. Reopening LightForge reconnects to the current job or opens the completed show.

Allow notifications when Android asks. For long screen-off jobs, choose **Allow screen-off processing** or **Guide → Allow background battery use** and approve Android's battery exemption. Manufacturer-specific sleeping-app restrictions may also need unrestricted battery use in the app's Android settings. These are system-controlled choices; the app does not grant itself permissions.

Your last saved show is preserved on cancellation, low-memory renderer loss, process interruption or failure. **Resume analysis** checks completed separation passages, transcription work and analysis stages before continuing. The interrupted passage may run again; completed matching work is reused. Source audio, analysis settings, execution path and app version identify checkpoints. Renaming a show or changing choreography alone does not discard matching analysis. Damaged checkpoints are rejected and recomputed. A completed overall analysis checkpoint skips directly to choreography. Android's Stop/Force stop, reboot and media-processing time limits still apply (normally six background hours per 24-hour allowance on Android 15+). No automatic reboot launch or endless restart loop is used.

Import and export document pickers still require returning to the app. Background analysis does not grant root, unrestricted access to other apps, hidden recording, vehicle API access or unverified GPU acceleration. All model quality settings and the offline privacy boundary are preserved.

## Troubleshooting logs

Version 2.2.2 adds **Guide → Export diagnostic log**. Reproduce the problem, reopen LightForge if it closed, and export the `.txt` report to **Downloads/LightForge**. On Android 8–9, choose Downloads in the system save dialog. Send that file with a short description of what you were doing and approximately when the failure happened. A native recovery action also makes reporting available when the preview engine cannot render the normal interface.

The report gathers recent app events, Java/JavaScript error stacks, analysis stages and interruptions, renderer failures, device/WebView versions, memory/storage context, and available Android process-exit information. Logs stay on the device until you choose to export them; there is no automatic upload. Reports exclude audio, model data and saved-show contents and redact common sensitive values. Diagnostic text can still contain details useful for troubleshooting, so review a report before sharing it publicly.

Logs are bounded and rotated. A killed process cannot reliably write its own final event; available Android exit information and the last saved trace help reconstruct that case. Exported reports remain in Downloads even if app cache is later cleared. Clearing Android app storage or uninstalling removes private projects, so export show backups before doing either.

## Precision Studio

After creating a show, open the **Review** workspace to refine synchronization.

1. Listen with Full song, Voice or Instruments and pause near the moment you want.
2. Open **Edit musical cues**, choose Voice or Bass, and add at the playhead or start from a detected event.
3. Set start/end times. Use **Accent** for a short gesture, **Hold** for a sustained gesture, or **Ignore this part** to remove automatic role cues in that range. Optional pitch and labels remain user-authored information.
4. Loop the passage, save the cue and inspect the resulting lights. Undo/Redo includes these edits.
5. Use **Correct timing for a musical part** if automatic vocal or bass estimates consistently arrive early or late. Negative corrections move estimates earlier; your entered cue times do not move.

The original model analysis is preserved. Edits on different parts may overlap; same-part overlaps are rejected with an actionable message. New songs start without another project's cues or part corrections. Output switches and individual lamp cues retain final ownership.

**Review synchronization** compares selected targets with final exported lamp commands, including the effects of individual output edits. It reports matched targets, frame error and seekable exceptions. It does not measure vocal-detection accuracy, lyric alignment, perceptual quality or physical vehicle latency. The report is included in the show ZIP.

Saved 1.4–1.6 arrangements reopen with their exact frame payloads. Recreate to use the new routing/review; a complete 1.6 analysis can be reused without rerunning its models.

## Make a show

Choose **Choose music**, select an unprotected local audio file, pick a style,
and tap **Create my light show**. Common WAV, MP3, M4A/AAC, FLAC and OGG/Opus files
are supported through Android's installed media decoders. DRM-protected
streaming downloads are not ordinary importable audio files.

The native importer actually decodes the music and prepares a stereo 16-bit
44.1 kHz PCM WAV. A separate mono 22.05 kHz analysis file keeps neural inference
efficient. Sample-rate conversion uses a streaming 48-tap polyphase sinc filter.
Existing 44.1 kHz stereo PCM16 WAV samples are preserved byte for byte.

**Festival**, **Cinematic** and **Pulse** have different visual patterns. Tune
light intensity, choose Expressive/Balanced/Lights only movement, and enable or
disable individual moving parts. Fine tune adds:

- 20 ms timing, Tesla's recommended default, or 15 ms finer timing.
- Sensitive onset detection, quarter/eighth/automatic rhythm and tempo override.
- A light-timing offset and interior palettes for the fitted accent lights.
- Individual section style/intensity edits, retained motifs, Undo/Redo and reset.
- First-downbeat correction, 3/4 or 4/4 meter and half/double-tempo interpretation.
- Independent movement frequency, passage looping, beat seeking and A/B arrangements.
- Studio (Deux separation, full rhythm transformer) or Balanced (MDX separation, compact rhythm transformer); both include GAME Large.
- Full song, Voice first, and Bass first emphasis presets.
- Full song / Voice / Instruments listening, detected phrase and held-note inspection.
- Editable Voice and Instrumental passage guides, with looping, Restore and Undo/Redo.

The separator isolates a combined lead/backing vocal waveform. A trained sound-event network then distinguishes singing and speech; acoustic detail follows entrances, syllabic accents, pauses and estimated pitches. The arrangement gives these events distinct gestures and supported fades. Instruments continue to supply rhythm, bass, colour and structure. No lyrics or word transcription are fabricated.

The composer uses detected beats, downbeats, local tempo, phrases, musical
impacts and active audio ranges to build an arrangement. Stronger sections
receive more assertive patterns; quieter passages retain space and longer
transitions. Light timing follows the analyzed music and is quantized to the
selected 15 or 20 ms export frame interval. The finer frame interval improves
command placement; it cannot make a lamp ramp or motor travel faster.

Movements are planned against musical arrivals. A trunk that needs about
14 seconds to open must begin before the chosen entrance; windows and mirrors
have their own travel allowances. When there is too little time to prepare,
perform and return a movement, the planner omits it. Dance runs use musically
selected windows while respecting per-part command budgets and final return
positions. Tesla controls the cadence of a Dance stroke, so individual strokes
cannot be locked to every drum hit through the FSEQ format.

The 3D preview uses a detailed Highland-generation Model 3 asset with about 180,000
triangles, finished in black. A bundled Three.js WebGL 2 renderer adds reflective
paint, studio lighting, soft shadows and lamp glow. Switch between Studio and
Night stages, choose a front, rear, driver-side or cabin cutaway camera, drag to
orbit, pinch to zoom and expand the preview. Camera changes ease into place. Auto quality adapts resolution and shadows to measured performance; High, Balanced and Battery can also be selected. All modes retain the same lamp commands, glow and estimated movement state. Offscreen previews stop rendering.

The soundtrack clock drives the exported light commands, documented fades,
shared Model 3 lamp outputs and six interior RGB zones. Windows, mirrors, trunk
and charge-port position animate from the sequence. Seeking reconstructs the
same state as continuous playback. Charge-port Dance shows rainbow LED activity.
The live output monitor remains available for lamps obscured by the camera.
The front display has its own RGB output; the rear display has no documented
custom-show channel and is not driven by the preview.

The refreshed interface adds larger controls, clearer contrast, keyboard camera
and style navigation, accessible seek/progress feedback and restrained playback
and button animation. Decorative animation respects the device's reduced-motion
setting. Visual controls do not alter the saved choreography.

Exterior timing follows the actual FSEQ bytes. Some headlamp sub-lens, rear
brake-surface and parking-marker assignments remain estimates because Tesla
has not published a Highland-specific per-lens channel diagram. Panel positions
and projected light spill are also visual estimates; Tesla does not publish exact motor dance
cadence, travel endpoints, lamp optics or hardware latency. The app labels
movement as estimated rather than claiming a guaranteed physical simulation.
The model represents the Highland body generation used by the 2025 car. It is
an artistic asset, not a Tesla-certified replica of every Long Range RWD detail.

The bundled **Glass Castle demo excerpt** is a 64-second portion of the user's
supplied recording, included for this private app. It is not a separate licensed
stock-music asset for redistribution.

## Improve and explore the musical composition

After creating a show, **Music intelligence → Built around the music** shows
beats per bar, detected phrases and planned movement arrivals. Expand
**Planned movement moments** and tap a time to inspect that arrival in the
preview. Motor travel is estimated; vehicle-defined Dance strokes are not
individually synchronized to drum hits.

**New variation ↻** creates another light arrangement from the existing analysis
and preserves your custom cues and output switches. Undo restores the previous
variation. **Re-analyze music** applies the improved analysis to an older project
without replacing its audio or manual edits. The main Create/Recreate button also
updates an earlier analysis when needed. New imports use the new analysis by
default. All processing remains on the device, with bundled trained music models.

## Follow singing and bass notes

**Singing emphasis** and **Bass-note emphasis** control how strongly these parts
shape the arrangement. The recommended starting values are 85% and 90%.
Singing uses a stereo separator, trained singing/speech evidence, GAME Large neural note transcription and measured waveform expression. Bass uses sustained low-register
harmonics in the separated accompaniment. General low-frequency transients
continue to inform the drum rhythm. Lead and backing singers remain combined;
this does not produce lyrics or exact word timings.

Sung articulations receive alternating lamp gestures and legal fades; held notes
shape sustained gestures and cabin colour. Bass-note entrances get independent
accents and holds. Percussion, melody, recurring patterns and section energy
continue on supporting lanes. Slow moving parts use suitable phrase entrances
and cadences within their travel, recovery and command limits.

The colored **Singing** and **Bass notes** lanes show what the analyzer found.
Drag to a moment or use **Next phrase** / **Next note** to listen and inspect it.
No confident singing means the show continues with its instrumental arrangement.
Higher emphasis does not make an uncertain estimate more accurate.

Existing saved arrangements reopen with their original frames. Select
**Analyze singing & bass** or **Re-analyze music** once to add this detail to an
older project; manual edits and output switches are kept. Undo can return to the
previous arrangement within the current editing session. Changing emphasis on
an analyzed project recomposes the show without rerunning the audio models.

## Edit individual outputs and movements

Open **Lights & dance editor** beneath the preview. The vehicle catalog
contains **34 available controls**: 20 exterior lamp groups, six RGB zones and
eight moving parts. Shared Model 3 channels appear as a single control with
all their addresses shown. Tesla's 56 candidate addresses are audited; three
fog-light addresses are unavailable on this North American Highland profile,
leaving 53 active byte addresses. The headlight matrix has no documented
individual-pixel custom-show addresses.

Choose an output to see its supported commands, coverage note and channel
addresses. **Inspect in preview** isolates it without changing the saved show.
Include or mute an output, or add timed cues using the current playhead.
Light and RGB cues overlay the generated show within their time range; adding
manual cues to a moving part replaces that part's automatic movement track.
Restore automatic control to remove that part's manual cues. Cues, output
switches and the optional outer-beam setting are saved with each project.

Light commands expose the documented on/off and 500, 1000 or 2000 ms fades
where supported; they are not arbitrary steady dimmer values. Outer-beam ramps
are off by default because Highland support needs vehicle confirmation. RGB
zones allow direct color selection. Movement commands include Open, Close,
Idle and Stop, plus Dance where supported. Mirror Dance is unavailable; use
Fold and Unfold. Charge-port Dance cycles its LED colors while the port is open.
Trunk and charge-port Dance need an earlier Open command and enough opening
time. When an opening, folding or dance cue needs a final return, the editor
adds a visible, editable Return closed or Return unfolded cue near the end.
A first trunk/charge Dance can also add its preparatory Open when enough time
is available before it. A completed track returns parts to their normal finish
position. The engine checks these prerequisites and per-part command
budgets before accepting edits or exporting a show. An output disabled with
**Include in this show** is zero in the final sequence, including custom cues.

The preview uses the model's actual lamp surfaces, including the headlamp
signature and front indicators, fixed fender repeaters, trunk-mounted tail and
plate lights, rear fascia reverse lamps and high-mounted brake light. It does
not add separate front fog lights, color the rear display or illuminate body
reflectors as lamps. Detailed physical channel assignments still need comparison
on the user's vehicle; see the individual output notes and `VALIDATION.md`.

## Multiple projects

**My shows** keeps separate projects in the app's private storage. Each retains
its soundtrack, analysis, creative settings, section edits and individual cues. Reopen a project
to edit it without analyzing the same song again, unless a rhythm-analysis
setting has changed. Rename, duplicate and delete projects from the collection.
A duplicate is independent, so it can hold a different arrangement of the same
song. Saving is automatic.

An exported native show ZIP is also a project backup: it includes the matched
audio and `Review/LightForge_Project.json`. Use **Restore backup** in My shows
to bring it back into LightForge. Restoring creates a new project, rebuilds the
analysis audio, preserves the saved creative settings, and reopens a matching checked frame snapshot. Backups without a usable compiled snapshot require recreation with the installed engine. Only LightForge exports that contain its project
JSON can restore all editing information.

Uninstalling the app removes its private projects. Export ZIP backups of work
you want to keep before uninstalling or moving to another phone.

## Export and run on the car

Tap **Export USB-ready show** and use Android's Save dialog to choose a location.
The native exporter verifies the actual FSEQ bytes against the soundtrack,
checks movement budgets, creates the ZIP, then reads every ZIP entry to check
its size and CRC before presenting the Save dialog.

The playback paths are exactly:

| Path | Contents |
|---|---|
| `LightShow/lightshow.fseq` | FSEQ 2.0, uncompressed, 200 channels |
| `LightShow/lightshow.wav` | Stereo 44.1 kHz 16-bit PCM audio |
| `Review/LightForge_Project.json` | Editable project backup |
| `Review/Validation.json` | Choreography and native byte checks |
| `START_HERE.txt` | Installation instructions |

Extract the ZIP. Put `LightShow` directly at the top level of an exFAT/FAT32
USB drive without a top-level `TeslaCam` folder or map/vehicle update files.
Connect it to the data-capable USB-A port in the glovebox, then select the
custom show in **Toybox → Light Show → Schedule Show** and follow the car's
prompts. The folder must not be nested inside another folder.

## What the car can perform

The engine uses the Model 3's supported exterior channels, coordinated shared
outputs, fade commands, interior RGB/display colors, windows, mirrors, powered
trunk and charge port. Optional lamps depend on the hardware fitted to the car.
It does not send Model X door commands, powered-frunk commands, presenting
door-handle commands, unsupported pixels or unrelated vehicle commands.

Fades use Tesla's documented 500, 1,000 and 2,000 ms ramp commands on compatible
channels. Most other exterior lamps are on/off; arbitrary steady brightness
values do not create real dimming on those lamps. The planner respects command
counts, approximate opening/closing travel, end states and a dance allowance
below 30 seconds per dancing component. The charge-port Dance command produces
rainbow LED activity rather than physical oscillation.

Tesla determines the speed and travel of each Dance stroke. No custom FSEQ
parameter can increase those values. Actual response depends on the vehicle,
software, temperature and actuator state. Generated shows have not been
physically tested on the user's car.

## Free neural analysis, accurately described

The app bundles a real pretrained **BeatNet** convolutional/recurrent network
and **ONNX Runtime WebAssembly**. It detects beat and downbeat activations, then
uses a local dynamic-programming decoder. The upgraded analysis adds local
tempo and meter interpretation, finer PCM attack timing, energy transitions,
phrases, prominent impacts and active audio ranges. The light and movement
planners use this information to choose and schedule their cues. These signal
analysis and choreography steps are not additional trained AI models; the
bundled BeatNet weights are unchanged.

BeatNet was selected as a compact, free, practical phone model. This app does
not claim it universally outperforms every larger or newer research system.
Tempo interpretation can be ambiguous for half-time/double-time, sparse music,
rubato or changing meter; the preview and override controls let you inspect
and adjust it. Confidence is an app heuristic, not a calibrated probability.
Silence is detected rather than assigned fabricated musical beats.

Analysis streams audio in small chunks and is cancellable. Files can extend
to Tesla's four-hour limit, although long recordings naturally require more
storage and processing time. Keep the app open during analysis and export.

## Privacy and source

The installed app has no Internet permission. Music and project data stay in
private app storage. All model, JavaScript, font and WebAssembly assets are
bundled. Export and optional sharing use Android's document picker and share
sheet under the user's control. Opening the official guide launches the user's
browser; it does not upload music.

This is independent personal software, not an official Tesla or xLights app.
It implements a focused mobile music-to-show workflow, rather than claiming
complete desktop xLights feature parity or `.xsq` project compatibility.

See `BUILD.md` to reproduce the APK. **Keep the private `signing/` folder from
the source backup**: its keystore and password are required to sign compatible
updates without uninstalling the app and losing private projects. Do not
publish that signing material.

## References and licenses

- [Tesla's official light-show guide](https://github.com/teslamotors/light-show).
- [Tesla's sequence validator](https://github.com/teslamotors/light-show/blob/master/validator.py).
- [BeatNet repository](https://github.com/mjhydri/BeatNet) and
  [ISMIR 2021 paper](https://arxiv.org/abs/2108.03576).
- [ONNX Runtime web documentation](https://onnxruntime.ai/docs/tutorials/web/).
- [Three.js](https://threejs.org/) (MIT), bundled version 0.180.0.
- [Highland model listing](https://sketchfab.com/3d-models/tesla-model-3-2024-36c52f3f89f6439c90310f14e8ff33f2):
  “2024 Tesla Model 3” by RBLXSupercars, published by brandonleong28,
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

`web/analysis/README.md` records model provenance, pinned upstream revisions,
conversion details and licenses. BeatNet is CC BY 4.0, ONNX Runtime is MIT,
the bundled Madmom-derived filter coefficients carry their upstream notice,
and Inter is SIL Open Font License. License texts accompany their assets.
Reproducible verification and conversion code are included in the source.
`web/preview/models/CREDITS.md` credits the vehicle model and records its
modifications. `research/model-source/` includes the original licensed GLB,
download evidence, geometry conversion scripts and verification receipts.
The renderer source and pinned npm dependency lock are in `web/preview/src/`.

## Verification and device status

[VALIDATION.md](VALIDATION.md) separates the seven current 2.2.2 release gates from historical numerical measurements. The complete [production verification run, attempt 2](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34179649874/attempts/2) passed the actual offline pipeline, APK build, Android screen-off/Resume and diagnostic export checks. The [focused Android diagnostics run](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34179649940) also passed crash persistence, the Guide export action and renderer recovery on the same source.

| Check | Current 2.2.2 status |
|---|---|
| Version synchronization | 2.2.2 / 20202 synchronized |
| Diagnostic retention, redaction and Downloads export | Passed: host regressions and Android 15 crash/restart, readable unique `.txt` files, Guide export and native recovery export |
| Node/Python regressions and native compilation | Passed: 155 Node tests, 54 Python tests and 22 native host checks |
| Browser UI, complete model pipeline and cancellation | Passed: responsive Chromium UI, actual bundled models, persistence, export and cancellation |
| Android renderer recovery, screen-off analysis and partial Resume | Passed on Android 15; saved-passage reuse, cancellation and timeout cleanup verified |
| Numerical kernel evidence | Retained with exact kernel/model hashes and a fixed review of diagnostic adapter changes; source-clock regression rerun |
| Original-signed update package | Passed: original update certificate, exact asset inventory, native ABIs, alignment and checksum |
| Physical phone performance, long songs, thermals and battery management | Unverified |
| Physical Tesla timing and movement | Unverified |

On one 6.803-second PCM16 excerpt with four threads on a Linux development machine, native Java CPU separation took **61.11 seconds**, compared with **127.25 seconds** for bounded WASM. Peak process RSS was **720.56 MiB** versus **1,920.96 MiB**: 2.08× faster and 62.49% lower measured peak memory. Both paths retained the original model, source sample count and measured Float32 equivalence. These are short-excerpt host measurements, not a phone or full-song guarantee. See [the runtime evidence](qa/release-2.2.1/DEUX_RUNTIME.md).

Browser tests exercise the browser path; Android must separately exercise native inference. A small emulator fixture does not establish that every full song will complete on every phone.

## Update from an earlier release

The signed update is `LightForge-2.2.2.apk`, version code 20202. Install it over the existing LightForge app; the release gate requires the original package ID and signing identity. **Do not uninstall first**, because uninstalling removes
private projects. Saved music and projects remain compatible; sequences are
regenerated with the current vehicle profile when edited or restored.

Version 1.3.0 improves musical analysis, structure-aware lighting and movement
arrival planning. It preserves the 1.2.0 individual output and movement editor,
audited Tesla channel catalog, corrected Highland lamp rig and unsupported-fog
rejection. It retains the 1.1.0 detailed 3D model and UI, the 1.0.1
audio transport correction, damaged-analysis repair, common-format imports and
automatic **44.1 kHz, 16-bit stereo PCM WAV** export conversion. The WAV and FSEQ
keep matching `lightshow` basenames.

Extremely long tracks whose full stereo WAV exceeds 2 GiB use the smaller
22.05 kHz mono analysis WAV for in-app playback. This avoids WebView's 32-bit
stream length limit. The preview labels this mode; exported audio remains the
original normalized 44.1 kHz stereo PCM16 file. Ordinary songs preview in
full stereo.

## Project durability in 1.4

Newly composed projects store compressed, checksummed frames and model/planner/profile provenance. Saved compiled arrangements reopen without silently rerunning a newer composer. Existing projects without frame snapshots are composed once from their earlier analysis. Use Re-analyze to adopt the new transformer. Large comparison/undo snapshots retain compressed frames rather than keeping multiple dense sequences in memory.

Native autosaves publish project and collection metadata together and retain one previous revision. The collection menu can restore it. Interrupted imports remain staged; a prepared export can be resumed after Android restarts the app or the Save dialog is cancelled. Export ZIPs include the exact editable project used for that export. A/B alternatives are session scoped; duplicate a project to retain another branch permanently.

## Existing projects and separated-audio cache

Install over the existing app. Saved 1.4/1.5 arrangements retain their checked frame payload. Re-analyze once to create isolated voice and instrument audio and the new vocal detail; editing emphasis or passage guides afterward does not rerun the neural models.

The listening layers are replaceable private analysis caches; project backups retain original audio, settings, detected events and compiled frames. Cache cleanup or a restored backup may require re-analysis to hear isolated layers again. Cached layers never replace the original full-quality soundtrack in the exported show.
