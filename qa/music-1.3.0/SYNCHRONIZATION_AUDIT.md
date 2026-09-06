# LightForge 1.3.0 synchronization baseline audit

Baseline engine/DSP version: 1.2.0. Audit date: 2026-09-06. These are pre-change diagnostics, not the acceptance result for 1.3.0. Production files were not modified by this audit.

## Source and input evidence

Tesla primary specification reviewed directly: https://github.com/teslamotors/light-show . Relevant sections are Boolean Light Channels, Ramping Light Channels, Closures Command Limitations, Closure Movement Durations, and Light Channel Mapping Details.

The bundled 64-second WAV is valid 44.1 kHz stereo PCM16. Sample.wav is valid 238.039979-second 48 kHz stereo PCM16. It was resampled to 44.1 kHz stereo PCM16 for the worker baseline; this is a test conversion, not an assertion about Android decoder behavior. Glass Castle.wav has the same PCM prefix as Sample.wav, but its data stops after 121.749104 seconds while the header still declares 238.039979 seconds. Thus it cannot serve as a complete audio reference. Exact metadata, payload lengths and SHA-256 are recorded in audio-metadata.json.

A frozen copy of 1.2.0 DSP, worker, model/runtime assets and engine was taken before production edits. The original code hashes are in baseline-original-source-sha256.json; baseline-diagnostics.json also hashes the instrumented snapshot used by its harness. capture-baseline.cjs uses headless Chrome and the real packaged ONNX model. Its temporary root is /tmp/lightforge-1.2.0-baseline. The snapshot's worker additionally exposes its already-computed analysis arrays for the audit; the original uninstrumented worker hash is recorded in baseline-original-source-sha256.json. Regenerating these baselines requires the old release source, not the newly updated engine.

## Measured baseline

| Measure | Bundled 64-second excerpt | Complete 238-second song |
|---|---:|---:|
| Beat estimate | 93.01 BPM | 93.07 BPM |
| Beat events | 99 | 369 |
| Detected band onsets | 1,728 | 6,260 |
| Movement events | 63 | 70 |
| Exterior active fraction | 84.72% | 84.20% |
| Boolean attacks erased by cleanup | 117 / 1,298 | 414 / 4,751 |
| Window Dance, each window | 18 s | 27 s |
| Trunk Dance | 14 s | 28 s |
| Charge port rainbow | 22.42 s | 28 s |

Boolean cleanup counts include every boolean channel, including four aliases for the shared park/marker output. They are not counts of independent physical lamps. Its pre/post instrumentation shows that adding ON frames across short gaps erases the next onset. The complete song is already close to the recommended 30-second Dance time and uses six window/trunk actuations. More command count is not the primary missing quality; more deliberate musical selection is.

The old renderer's estimated physical motions and distances to inferred neural beats are not independent timing ground truth. The receipt labels its timing distances as proxies. Neither the phone nor the vehicle was available for measurement.

## Confirmed implementation issues

1. **True rest is not respected.** The engine drops the dense `energy` timeline and blends section-average energy at 68% with waveform energy at 32%. Eighth-note generation blindly interpolates between consecutive retained beats, including multi-second gaps. A controlled 20–28-second rest inside a loud section still triggers 21 exterior frames at 23.76–24.16 seconds. RGB's nonzero base gain also continues through the rest.
2. **Ending attacks are overwritten.** An unconditional 2.15-second closing ramp replaces actual headlamp events. In a controlled 10-second pulse track the genuine 9-second beat sends command 77 (ramp off) on the inner lamp rather than the expected instant-on accent.
3. **Phrasing assumes 4/4.** The beat decoder estimates 3 or 4 beats per bar, but engine normalization drops `meter`. Exterior pattern slots, downbeat fallback and cabin color progression hard-code groups of four. Beat indices also lose the pickup/downbeat phase relationship.
4. **Overlay resolution weakens rhythms.** Later raw frame writes override earlier effects. Boolean cleanup merges gaps under 100 ms after planning, removing 8.7–9.0% of intended boolean attack transitions on the measured inputs. Reserve visible gaps when scheduling priority cues, or deliberately merge low-priority accents at the cue-planning stage; do not erase strong beats as a final blind repair.
5. **Dance selection is driven strongly by duration fractions.** End-biased anchors can favor the designated finale regardless of whether the best musical peak happened earlier. Mirror cycles are spread at approximate fractions of track duration. The local energy function can rate silence as loud. Existing command limits and preparation intervals largely validate; the musical target choice needs work.
6. **Beat timestamps start on a 20 ms feature clock.** The 15 ms export setting cannot by itself create more accurate musical observations. Fine onset timing should use a finer PCM envelope clock and preserve the original audio origin without deleting leading silence.
7. **Onset density is not musical salience.** Baseline produces approximately 26–27 band onsets per second. That is valid spectral detection output, but it needs cross-band clustering, local thresholds and sparse allocation before becoming choreography.

## Official limitations that the improved composer must retain

Tesla documents 15 ms minimum boolean ON time and recommends 100 ms ON/OFF aesthetically. Ramp durations are 500, 1,000 or 2,000 ms; reversing early is permitted. Allow 50 ms extra to guarantee completion.

Approximate travel is 14 s trunk opening, 4 s trunk closing/windows, and 2 s mirrors/charge port. Open, Close and Dance count per closure: six windows/trunk, 20 mirrors, three charge port. Mirrors cannot Dance. Other closures except windows need to be open before Dance. Idle permits unfinished Open/Close travel; Stop interrupts. Dance persists while commanded.

Recommended Dance is roughly 30 s per closure per show. Charge Dance flashes rainbow LEDs; its door closes automatically 120 s after opening.

Inference for this implementation: align command boundaries or estimated arrival with music. The documented interface does not provide Dance frequency/phase control. Treat each physical oscillation and exact vehicle latency as unverified.

## Recommended independent acceptance checks

- Create PCM click fixtures with known non-grid onset times, leading silence, a long breakdown, tempo changes, and 3/4 with a pickup. Compare detected times to the known PCM event origins before testing quantized FSEQ events.
- Assert selected, accepted accent events retain their intended quantized attack within half a frame. Report deliberately skipped cues separately; do not calculate accuracy only over successfully matched events while ignoring misses.
- Assert there are no newly invented eighths across long beat gaps, and no automatic exterior/RGB output in sustained true-silence interiors after any stated fade tail.
- Verify strong final transients survive the outro, unless a selected fade-ending mode explicitly reserves that period.
- Compare 3/4 and pickup fixtures to their supplied downbeats; scene changes and alternating sides should follow bars, not simply event index modulo four.
- Validate all new automatic movement tracks both with the engine's stateful validator and Tesla's official FSEQ validator. Measure prepared arrival before trunk Dance, total Dance seconds, independent counts, minimum motion visibility, no overlap, available return travel, disabled outputs, manual-track precedence, and offset behavior.
- Compare generated shows for identical inputs/seeds to ensure reproducibility. Use musical density, contrast and meaningful peak selection as quality criteria rather than rewarding maximum transitions.
- Keep the output claims limited to command timing and estimated travel until actual phone playback latency and vehicle travel are measured.
