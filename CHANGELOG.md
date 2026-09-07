# LightForge 2.0.0 — Precision Studio

- Editable voice/bass musical cues, isolated part timing and same-clock passage looping.
- Collision-aware bass holds and enabled-lamp fallback routing for musical roles.
- Final-frame synchronization review, retained in export validation.
- Exact 1.4–1.6 snapshot upgrades, project-isolated corrections and Undo/Redo.
- Runtime version source, compatible-signing guard, portable test dependencies and full CI.
- Original bundled models retained; no unmeasured detection-accuracy claim.

# 1.6.0 — separated voice and musical expression

- Added offline stereo vocal separation with quality-first polarity refinement and overlapping reconstruction.
- Run singing/speech classification on isolated voice; measure vocal articulation, pauses, estimated pitches and holds.
- Track bass harmonics in separated accompaniment, preserving independent rhythm/structure analysis.
- Added vocal articulation/held-note light gestures, phrase-limited movement and manual voice/instrumental guides.
- Added actual voice/accompaniment audition from bounded Float32 audio caches, voice detail and focus presets.
- Preserve checked 1.4/1.5 saved arrangements with narrow default-only settings migration.
- Compare actual source estimates with licensed multitrack references; retain uncertainty and device/vehicle limits.

# LightForge 1.5.0

Version code 10500; same package and private update signing identity.

- Independent offline singing evidence and pitched bass-note analysis, including
  held notes and note-specific timing rather than bass-band drum hits alone.
- Singing/bass emphasis controls, sustained light phrasing, legal release fades,
  sparse contours and responsive cabin color; percussion and melody stay involved.
- Vocal and bass phrase arrivals inform physically constrained movement planning.
- Seekable analysis lanes, estimated music-at-playhead indicators and honest
  uncertain/instrumental fallback states.
- Exact 1.4 saved-frame migration with checksum verification and retained edits.

---

# LightForge 1.4.0

Version code 10400; same package and update signing identity. See `RELEASE_NOTES.md` for installation and the complete current change list.

- Real full/compact Beat This! transformer analysis, repeated sections and groove evidence.
- Phrase motifs, independent movement frequency, corrected rhythm and retained patterns.
- Cancellable background composition, compressed exact frame snapshots and streaming native export.
- A/B editing, Undo/Redo, loops, beat seeking, collection filtering and vehicle notes.
- Adaptive 3D rendering with unchanged command interpretation.
- Durable export/import recovery, transactional saves and previous-version restore.

---

# LightForge 1.3.0

Install over the existing app to keep private projects. Version code is 10300;
the package ID and private signing identity are unchanged.

## Musical understanding and composition

- Enhanced the existing offline BeatNet analysis with local tempo, meter, finer PCM attack timing, phrase boundaries, prominent musical impacts and active audio ranges.
- Added a dedicated light planner that builds patterns around musical structure, downbeats, attacks and section energy instead of relying only on a repeating beat pattern.
- Added a dedicated movement planner that selects musical arrivals and begins preparation early enough for each part's approximate travel time.
- Reserved time for valid final returns and retained all per-part actuation budgets, unsupported-command restrictions and manual-cue validation.
- Preserved individual output settings, manually edited cues and the existing common-format import, conversion, preview and export workflows.

The neural model still runs entirely on the device with no account, download
or remote AI service. Its trained weights are unchanged; the improvements are
in decoding, signal analysis and choreography planning. Tesla controls motor
speed and Dance stroke cadence. The planner cannot guarantee that each
physical stroke lands on a beat. Tests and the remaining physical calibration
limits are described in `VALIDATION.md`.

---

# LightForge 1.2.0

Install over the existing app to keep private projects. Version code is 10200;
the package ID and private signing identity are unchanged.

## Individual lights and movement tracks

- Added a catalog of every documented custom-show output applicable to the North American 2025 Model 3 Long Range RWD: 20 exterior groups, six RGB zones and eight moving parts.
- Added per-output enable switches, timed light/RGB cues, independent closure command tracks, cue editing and restoration of automatic choreography. All settings persist with projects and backups.
- Added isolated output inspection driven by the same command decoder used for the saved show; inspection does not edit the arrangement.
- Exposed supported fade durations, RGB colors and Open/Close/Idle/Stop/Dance commands. Mirrors use Fold/Unfold and do not offer the unsupported Dance command.
- Added visible return cues for incremental movement editing, and preparatory Open cues for a first trunk/charge Dance when timing allows.
- Added independent manual-cue validation, state-aware closure prerequisites and per-part command budgets in both the engine and native export checks. Unsupported fog channels remain zero.

## Highland lamp corrections

- Removed invented lower-front fog lights and the duplicate headlight signature strip.
- Bound front headlamp and indicator outputs to the model's real optical surfaces; expanded shared-channel coverage and the brake-light group.
- Kept rear fascia lamps fixed, tail/plate lights attached to the trunk and fender repeaters on the body. Body reflectors stay unlit.
- Restricted display RGB to the front screen; the rear screen has no public custom-show channel.
- Made outer-beam ramping an explicit optional capability, disabled until verified on the vehicle.

The catalog represents public Tesla control groups, not every individual LED
or electrical lamp. Tesla does not publish a Highland per-lens FSEQ diagram;
headlamp sub-lens, rear-stop and parking-marker allocations need an in-car
comparison. Motor travel, dance cadence, optics and hardware latency remain
estimates. No phone or car test is claimed. See `VALIDATION.md` for evidence.

---

# LightForge 1.1.0

Install over 1.0.0 or 1.0.1 to keep existing projects. Version code is 10100;
the package ID and private signing identity are unchanged.

## Highland 3D preview

- Replaced the projected-polygon drawing with a real WebGL 2 renderer using bundled Three.js 0.180.0 and a licensed 179,692-triangle Highland Model 3 asset.
- Added black reflective materials, environment lighting, soft ground shadows, lamp bloom and separate Studio/Night lighting stages.
- Added smooth camera transitions, touch orbit/zoom and a cabin roof cutaway; the preview can be enlarged.
- Bound the vehicle lamps and moving components to the existing exported-command state. Seeking, fades, shared lamps, six interior zones and the live output monitor continue to use the show engine.
- Included the original licensed model, attribution, geometry preparation scripts, renderer source and dependency lock in the private source backup.

## Interface polish

- Refreshed the studio with graphite panels, mint accents, larger controls, clearer contrast and a compact track-first phone layout.
- Added tactile control feedback, playback accents, overlay transitions and success feedback. Reduced-motion settings disable decorative animation.
- Improved keyboard camera/style navigation, accessible seek and progress announcements, and modal focus handling.

Audio analysis, native import/conversion, project storage and export generation
retain their existing behavior. Native asset handling adds MIME types for the
new graphics assets. The model is a Highland-generation artistic visualization;
exact trim details, motor motion, optics and vehicle latency remain estimates.
See `VALIDATION.md` for current checks and historical regression evidence.

---

# LightForge 1.0.1

Install this update over 1.0.0. The package and signing identity are unchanged; existing projects remain in the app. Do not uninstall first.

## Audio creation and playback

- Corrected the WebView double seek that skipped the first 44 bytes of a PCM range and caused “Audio data ended unexpectedly.” The same corrected stream supports preview playback and seeking.
- WAV range reads now verify positions and byte lengths before inference. Transport faults are distinguished from genuinely incomplete saved audio.
- Missing or damaged derived analysis WAVs can be regenerated from the intact saved soundtrack without deleting music, settings or section edits.
- Common MP3, M4A/AAC, FLAC, OGG/Opus and supported WebM/MKA imports use Android's real decoders. PCM WAV supports 8/16/24/32-bit integer and 32-bit float. Decoder-buffer fragments are preserved; multichannel downmix honors channel layouts and rejects incomplete tails.
- Every supported import is automatically converted to 44.1 kHz, 16-bit stereo PCM WAV for export. FSEQ and WAV retain matching names and validated structure.
- Extremely long recordings whose stereo WAV exceeds 2 GiB use a labeled 22.05 kHz mono preview to avoid WebView's 32-bit length limitation. The original normalized stereo audio remains the export source.

## Preview

- Replaced the static top-down drawing with a perspective vehicle, front/rear/driver/cabin views, drag-to-orbit, enlargement and a live lamp monitor.
- Lamp values come from the exported sequence, with exact command-time evaluation, documented fades, Model 3 shared outputs and six interior RGB groups.
- Windows, mirrors, trunk and charge-port position now animate from commands; seek and rewind reconstruct the same state. Charge-port Dance changes LED colors without inventing door oscillation.
- Corrected premature fade onset, fixed rear channel assignments and articulated trunk-mounted lamps. The separate rear fascia lamps stay fixed.
- Panel travel and light spill are explicitly visual estimates. Tesla controls actual motor strokes, hardware response and lamp optics.

See VALIDATION.md for the reproduced fault, regression coverage and remaining Android-device verification limits.
