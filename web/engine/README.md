# LightForge choreography engine

`vehicle-profile.js` defines the public controls for the North American 2025 Model 3 Highland profile. Load it, `light-planner.js` and `movement-planner.js` before `show-engine.js` in a browser. The engine also loads its modules directly in CommonJS tests. `show-engine.js` is an offline browser script. It exposes `ShowEngine` on `window` (or `globalThis` in a worker) and supports CommonJS for the test runner. It requires no network, package downloads, API keys, or server.

```js
const show = ShowEngine.generate(musicAnalysis, {
  style: 'festival',
  dance: 'expressive',
  stepMs: 20,
  sensitivity: 0.8,
  intensity: 0.85,
  movementDensity: 0.7,
  tempoScale: 1,
  meterOverride: null,
  downbeatAnchor: null,
  palette: 'aurora',
  beatDivision: 'auto',
  offsetMs: 0,
  seed: 666,
  enabled: { windows: true, mirrors: true, trunk: true, charge: true, interior: true },
  outputEnabled: { "license-plate": true },
  manualCues: [],
  outerBeamRamping: false
});
const sequenceBytes = ShowEngine.fseq(show, 'lightshow.wav');
const preview = ShowEngine.stateAt(show, 67.7);
```

## Input and output

The music object contains `duration` in seconds, `bpm`, `beatConfidence` from 0 to 1, sorted or unsorted `beats` and `downbeats` in seconds, `onsets` with `{time, strength, band}` (`bass`, `mid`, or `high`), `sections` with `{start, end, energy, label}`, and a normalized `waveform`. Malformed event entries are discarded; missing beat data produces an explicit warning and a regular fallback grid. Truly silent waveform input produces an all-zero sequence and no movements.

Analysis version 2 additionally supplies `meter`, `meterConfidence`, per-beat
`beatDetails` (`time`, `confidence`, `localBpm`, `barPosition`), `energy` with an
`energyStep`, `activityRanges` (`start`, `end`), `phrases` (`start`, `end`,
`energy`, `kind`, `confidence`, `accentTime`) and `impacts` (`time`, `strength`,
`kind`). These descriptors let the planners follow variable beat spacing,
bar accents, measured silences and musical landmarks. Older analysis retains
a compatibility path; the application can refresh it from saved audio.

Analysis version 3 adds section and phrase `recurrenceGroup`, `similarity`, and `repetitionIndex` from acoustic similarity; these are musical recurrence estimates, not guaranteed chorus labels. A confident `groove` description (`feel`, `subdivisionRatio`, `confidence`) places subdivision accents on observed swing timing.

The show contains flat `Uint8Array frames`, `frameCount`, `channels: 200`, `channelCount: 200`, `stepMs`, `duration`, `audioDuration`, `sections`, `movements`, `settings`, `stats`, and `validation`. `generate()` throws actionable errors for unrepresentable audio durations, unsupported frame intervals, memory allocation failure, or an invalid generated result.

`validate(show, music?)` returns `{valid, errors, warnings, stats}` and independently reads frame values to check closure use, channel validity, physical timing, and the end state. Supply `music` when checking audio duration alignment. Generated shows also attach `validation.synchronization`: its collision report keeps raw candidate rejections separate from logical high-salience rescue/unresolved counts, and `calibrationProvenance` records only an explicit user timing configuration (or that none was assumed).

`fseq(show, audioFilename)` validates again and emits FSEQ v2.0, uncompressed, with 200 channels and the media filename metadata. Its duration rounds audio up by less than one frame. Audio conversion and ZIP creation belong to the native/export integration: use 44.1 kHz PCM WAV and put a matching basename pair inside the top-level case-sensitive `LightShow` directory.

`fseqHeader(show, audioFilename)` performs the same validation and returns only the FSEQ header. Stream that header followed by `show.frames` to avoid allocating a second full-size sequence.

`preparePreview(show)` compiles sparse lamp-transition tracks and closure timelines into cloneable `show.previewIndex`. Generation calls it inside the composition worker; restoration rebuilds it from verified saved bytes. `stateAt` uses binary lookup per physical lamp, with no five-second frame replay on every render. If code changes frame bytes directly, call `invalidatePreview(show)` before viewing them.

`stateAt(show, time)` reads the actual exported frame bytes and returns raw channel values, 30 physical exterior output brightness values in channel order (each 0–1), six RGB triplets in screen/right-rear/right-front/center-front/left-front/left-rear order, closure commands/poses, and the current section. `time` is the exact clamped playback time; `frameTime` is the current FSEQ frame boundary. Fade evaluation is continuous between command frames, including interrupted/reversed ramps. Model 3 combined channels 4–6 use the channel-4 ramp duration and OR'd targets; side-marker/aux outputs are OR'd. Unsupported front and North American rear fog stay dark. The display RGB triplet drives only the front display; no public rear-display address exists.

`closures` includes the supported eight parts; `closureState` exposes the same objects under `mirrorL`, `mirrorR`, `windowFL`, `windowRL`, `windowFR`, `windowRR`, `trunk`, and `charge`. Each reports raw/current command, actual continuing motion status, normalized `openFraction`, mirror `foldedFraction`, and `estimated: true`. Initial windows/trunk/charge are closed and mirrors unfolded. Open/Close continue through Idle, Stop freezes the reached position, interrupted movements begin from the current position, and Dance stops at its command end. Seek and playback produce the same pose. Charge Dance animates rainbow LED color while its door stays open; the two-minute automatic charge-door close is modeled.

Physical positions are **estimates**. The default 4-second window, 14/4-second trunk-open/close, and 2-second mirror/charge values are retained as unverified conservative planning envelopes for compatibility; they are not Tesla latency measurements. Tesla does not publish Dance endpoints or cadence. The visualization uses illustrative window travel between 18–86% open and trunk travel between 68–100% open independently of song tempo. Actual motor speed, travel, thermal limits, lamp photometry, optical diffusion, and charge-rainbow cadence can differ on the vehicle. A non-default calibration is explicitly labeled as user-supplied configuration; preview accuracy remains command timing and channel assignment, not a claim of physical vehicle calibration.

## Settings

| Setting | Values |
| --- | --- |
| `stepMs` | 20 recommended, or 15 |
| `style` | `festival`, `cinematic`, `pulse` |
| `dance` | `expressive`, `balanced`, `off` |
| `sensitivity`, `intensity` | 0–1 |
| `movementDensity` | 0–1; default 0.7; zero disables automatic movement and preserves manual tracks |
| `tempoScale` | 0.5, 1, 2; derives half/double local beat spacing from recorded analysis |
| `meterOverride` | 3, 4, or null for analysis meter |
| `downbeatAnchor` | Seconds, or null; snaps the bar phase to the nearest derived beat without moving audio |
| `beatDivision` | `auto`, `quarter`, `eighth` |
| `palette` | `aurora`, `neon`, `fire`, `ice`, `monochrome` |
| `offsetMs` | −2000 to +2000; positive delays musical cues |
| `seed` | Nonnegative 32-bit integer; identical input and seed reproduce identical frames |
| `enabled` | Boolean `windows`, `mirrors`, `trunk`, `charge`, `interior` |
| `outputEnabled` | Available output ID → boolean; false masks automatic and manual cues |
| `manualCues` | Timed per-output cues, described below |
| `outerBeamRamping` | False by default; allow documented outer-beam ramp codes only after vehicle confirmation |
| `vehicleTimingCalibration` | Optional explicit, local timing-calibration record; absent by default and never assumes Tesla latency |
| `sectionOverrides` | Section index → `{style, intensity, seed}` |
| `semanticChoreography` | `true` enables the separately validated semantic scheduling strategy; false by default |
| `motifEvolution` | `true` only with `semanticChoreography:true` and a valid recurrence sidecar; false by default |

Automatic beat division uses the detected local beat spacing when available;
manual quarter/eighth choices remain available. Lamp effects retain meaningful
durations and gaps; the frame interval is timing resolution, not a target strobe
frequency. Styles and intensity can be overridden per detected section without
changing music analysis.

### Optional vehicle timing calibration

By default, no latency correction is assumed: command timestamps retain the
existing deterministic FSEQ schedule. The profile records closure travel values
as **unverified planning envelopes**, not Tesla measurements. A calibration can
only be enabled deliberately, identifies its local evidence record, accepts
bounded non-negative values, and can only lengthen the built-in travel envelope.
That guarantees it cannot silently make a motion less conservative.

```js
vehicleTimingCalibration: {
  version: 1,
  enabled: true,
  calibrationId: 'local-rig-2026-09',
  outputs: {
    mirrorL: { commandLatencyMs: 120 },
    windowFL: { activationLatencyMs: 80, openTravelMs: 4200, closeTravelMs: 4100 }
  }
}
```

Supported per-output metadata includes command, activation and deactivation
latencies plus minimum useful/repeat durations. Closure entries may also set
open/close travel times, but only at or above their built-in envelope. Light
and RGB latency values are retained as evidence metadata until a validated
output-specific realization path consumes them; they do not silently retime
lighting. Dance endpoints and cadence remain vehicle-controlled and are not
claimed to be calibrated by this setting.

## Musical light planning

`light-planner.js` exposes `LightPlanner.compose()` and its shared musical
context helper. The planner creates channel events before the engine paints
them into FSEQ frames. Patterns follow bar position, phrase changes, local
tempo, energy and measured attacks. Instrument-band accents and selected
musical impacts layer with the arrangement while the event resolver prevents
conflicting writes from turning a fade into an accidental flash.

The physical output contract remains authoritative: aliases stay linked,
unavailable lamps stay dark and ramping uses supported Tesla command bytes.
A 500 ms fade is a 500 ms fade even when the chosen frame interval is 15 ms.
Patterns may vary with the seed; identical inputs and seed remain reproducible.

## Musical movement planning

`movement-planner.js` exposes `MovementPlanner.plan(music, settings, profile)`.
It returns command `events`, complementary light `accents`, selected musical
`targets` and `diagnostics`. Each event identifies its channels, output ID,
start/end seconds, canonical command value, readable label and planning
intent. Targets record the music time, offset-adjusted command target, source,
salience score and confidence; preparation/estimated-arrival fields explain
the relevant motor lead time. Diagnostics report per-output command counts,
Dance seconds, skipped opportunities and travel assumptions.

The planner ranks phrase accents, impacts, section entrances and bar arrivals
using measured energy and changes in energy. It prepares slow parts ahead of
the selected arrival: approximately 4 seconds for windows, 2 seconds for
mirrors/charge port and 14 seconds to open or 4 seconds to close the trunk,
with a settling allowance of at least 0.3 seconds. Dance passages end within
their active musical range and leave enough time for a valid return. Expressive
mode can stagger secondary window entrances on actual detected beats and use
an ensemble response at the strongest selected passage. Mirrors use timed
Fold/Unfold pairs and never Dance. Charge uses one Open/Dance/Close color
episode, below the automatic two-minute closure timeout.

This is arrival and passage scheduling, not control over an individual Dance
stroke. Tesla determines the physical oscillation cadence. Time offsets apply
to musical targets once; motor travel allowances are not scaled by BPM. Manual
closure tracks and disabled outputs are excluded from automatic planning so
recomposition cannot overwrite individual edits.

Rhythm corrections derive a new grid from the saved analysis without another neural inference run. The source music object remains unchanged. Half/double tempo preserves local tempo changes; subdivision groove is reset when the beat scale changes because its original estimate referred to the original grid. `show.choreography.rhythm` exposes the resulting beats, downbeats, meter, BPM, groove and correction provenance for the UI.

Each generated section exposes a resolved `seed`, `variant`, `locked` flag and `motifGroup`. Repeated analyzed sections share motif and palette identity. To preserve a section during New variation, store its **resolved** `show.sections[i].seed` in `settings.sectionOverrides[i].seed`. This locks motif variation, not timings against later analysis or rhythm corrections. All three styles, including quiet cinematic passages, respond to variation. Manual cues and output masks still take precedence.

A recurrence sidecar remains inert by default. Set both `semanticChoreography:true` and `motifEvolution:true`, then supply `semanticTimeline`, `recurrenceEvidence`, and `recurrenceSidecar` built by `LightForgeRecurrence`. The bridge first validates the exact timeline/evidence bindings and applies only mapped repeated-section metadata: a shared motif identity plus deterministic per-instance seed/variant and a bounded intensity adjustment. It does not create motifs, change event timestamps, move accepted cues, or bypass collision and vehicle validation. A user-supplied per-section seed keeps that section unchanged; a supplied per-section intensity remains authoritative.

## Manual output cues

`ShowEngine.getCapabilities()` returns the vehicle profile. Its 34 available
controls use 53 byte addresses: 20 exterior output groups, six RGB zones and
eight closures. The three fog channels are cataloged as unavailable. Multiple
aliases in one output are shared hardware controls, not separate lamps.

```js
manualCues: [
  {id: 'tail-cue', outputId: 'left-tail', start: 10, end: 11, value: 255},
  {id: 'dash-cue', outputId: 'rgb-dash', start: 12, end: 14, rgb: [64, 220, 180]}
]
```

Times use seconds and must lie within the music duration. RGB values are three
integer bytes. Other values use canonical Tesla command bytes: closures use
Idle 0, Open 63, Dance 127, Close 191 and Stop 255; boolean lights use 0/255.
Ramping lamps additionally use Off 26/51/77 and On 178/204/230 for
500/1000/2000 ms transitions. Mirrors reject Dance. Overlapping cues on one
output are rejected; different outputs can overlap.

Light/RGB cues replace generated bytes only within their cue interval. The
first manual cue for a closure replaces that closure's whole automatic track.
That track must satisfy its command budget, preparation requirements and
final-state rules: windows, trunk and charge port closed; mirrors unfolded. An output disabled in `outputEnabled` remains
zero after automatic generation and manual overlays. Shared aliases are written
together. The final frame remains all zero, including cues that end exactly at
the music duration. Preview inspection builds a separate sequence and does not
modify the arrangement exported by `fseq()`.

## Vehicle behavior and constraints

This profile targets the 2025 Model 3 Long Range RWD. It uses exterior channels 1–30 excluding the three unavailable fog addresses, the two mirrors, four windows, power trunk, charge-port controls, and interior RGB channels 176–193. It leaves Model X door controls, presenting handles, Cybertruck pixels, and other unsupported channels off. The North American rear-fog output stays off.

Model 3 channels 7/9/11, 8/10/12, and 17/18/19/20 are synchronized because the vehicle combines their outputs. Real fade commands are used on inner beams, signatures, shared channel 4–6 groups, and front turns. Outer beams default to full on/off because Tesla does not document the Highland-specific optical classification. `outerBeamRamping` enables optional reflector-style ramps after vehicle verification. Boolean rear lamps receive only full on/off commands. Exterior fade command bytes are 178/204/230 for 500/1000/2000 ms on and 26/51/77 for corresponding off ramps. These channels do not support arbitrary steady brightness; interior RGB does.

Each window and trunk stays within six counted commands, each mirror within
twenty, and charge within three. The planner also limits total Dance time to
30 seconds per component and spaces separate episodes with recovery time.
Expressive/Balanced modes use different episode counts and recovery allowances;
these are composition choices, not extra vehicle capabilities. Short or quiet
tracks receive fewer movements when full preparation, performance and return
cannot fit. Windows, trunk and charge finish closed; mirrors finish open. The
final frame clears all channels.

The vehicle controls closure motion cadence. An on-screen schematic or successful file validation is not a physical vehicle test. Ambient conditions and the installed hardware can change actual movement or lighting behavior.

## Sources and verification

The channel and movement behavior comes from [Tesla's official light-show guide](https://github.com/teslamotors/light-show), its [xLights project configuration](https://github.com/teslamotors/light-show/blob/master/xlights/tesla_xlights_show_folder.zip), and the [official validator](https://github.com/teslamotors/light-show/blob/master/validator.py), reviewed September 6, 2026. Downloaded source evidence and the candidate-address audit are in `research/hardware-1.2.0/`.

Run `node --test tests/engine.test.cjs` from the app directory. The suite covers an independent FSEQ binary decoder, a tempo/duration/frame-interval matrix, every closure's preparation time and actuation budget, shared-channel behavior, all three fade durations, preview ramps, six-zone RGB, feature switches, offset timing, silent and malformed input, deterministic regeneration, corrupted data, and the exact four-hour limit. A portable Glass Castle music fixture is included. An export generated from the trained music-analysis output also passed Tesla's unmodified Python validator.

Run `node --test tests/preview-engine.test.cjs` for independent hand-authored command timelines covering exact ramp boundaries at 15/20 ms, interrupted ramps, physical combined outputs, unsupported parts, persistent Idle, immediate Stop, partial motion reversal, mirror initialization, moving Dance, charge rainbow/auto-close, deterministic seeking, and comparison against independently decoded export bytes/RGB.

Run `node --test tests/engine.test.cjs tests/preview-engine.test.cjs tests/engine-manual.test.cjs` for the combined engine regression suite. Current 1.4.0 composer evidence is under `qa/release-1.4.0/`; run `node tests/composer-1.4.test.cjs` and `node tests/movement-planner.test.cjs` for the new checks. Historical 1.3.0 planner and integration evidence remains under `qa/music-1.3.0/`; the final release record identifies the executed checks and tested source hashes. `qa/hardware-1.2.0/commands-verification.json` retains the earlier host engine/native checks and official validator results as historical evidence. Hardware sub-lens placements remain estimates: source address coverage is not an in-car physical mapping test.
