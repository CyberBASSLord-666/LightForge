# LightForge 2.4.0 — timing, musical continuity and vehicle preview

An offline Android update for the configured North American 2025 Model 3 Long
Range RWD. Install the original-signed release APK over your existing app to
retain projects. A source version or candidate build is not publication; use
GitHub Releases for the qualified downloadable APK.

## Changes

- Preserve measured vocal and bass attacks and held spans across arrangement
  boundaries, with stronger observed transients selected ahead of weaker nearby
  candidates. Overlapping activity and sustained notes remain audible in their
  visual roles instead of creating false silence.
- Allocate requested left/right pairs together. Intentional alternating accents,
  manual edits and disabled fixtures remain available; an occupied lane no longer
  creates an accidental one-sided version of a paired gesture.
- Use one frame-clock rule for raw FSEQ commands and preview state. Sample the
  playback clock at rendering submission so the model does not display a queued,
  older audio position after playback or a seek.
- Improve lamp diffusion and ground illumination, including the combined
  headlamp group and independent white reverse illumination. Preserve linked
  channels, body-fixed rear fascia lamps and trunk-mounted lamps.
- Record primary-source vehicle identity, dimensions and hardware references
  without publishing the owner's VIN. The profile distinguishes verified facts,
  owner configuration and estimated physical properties.
- Check every profile address against Tesla's official xLights layout and run
  production FSEQ exports through its validator. An external readback using
  xLights' actual C++ FSEQ reader reproduced every tested payload byte. No xLights
  desktop engine or GPL implementation is bundled in the application.

## Measured performance scope

The vocal classifier's JavaScript feature frontend caches unchanged overlapping
PCM windows and fixed FFT coefficients. Across all ten original windows of the
64-second bundled public demo, seven alternating measured rounds reduced median
frontend time from **421 ms to 308 ms (27%)** on the test host. Every one of the
1,280,000 Float32 feature values was byte-identical after every warmup and trial.
The explicit retained cache is bounded to 1,152,000 bytes. This measurement
excludes resampling, model inference and the complete analysis job.

The read-only choreography diagnostic scanner also avoids per-frame string
allocation. Paired host cases retained identical complete reports and FSEQ
bytes; median stage reductions ranged from 11% to 56% across the recorded and
synthetic configurations. Timing samples and their variability are retained in
`research/core-refactor-2.4.0/performance/`.

Original model weights, Float32 precision, inference steps, contexts, thresholds
and model-call counts are preserved. The **75% total-analysis speedup remains an
aspirational objective, not an achieved or mandatory release claim**. The neural
separation path remains the dominant known cost. These bounded stage timings do
not establish phone performance, total-job acceleration or general music quality.

## Accuracy and verification

The VIN confirms the model year, body, factory and single-motor configuration;
parts and service references identify assemblies. They do not by themselves
measure lamp response, photometry, exact FSEQ-to-sub-lens routing or motor travel.
The preview remains a source-backed command simulation with estimated physical
appearance and motion. It is not a certified digital twin of the owner's car.

New and existing timing, symmetry, DSP, command mapping, preview lifecycle,
project persistence, export, release-policy and native regression checks are
required. Publication requires a fresh successful source-bound full production
and Android run, original update certificate, unchanged qualified APK payload,
and final public-asset integrity verification. Older receipts are not relabelled
as current evidence.

The owner-approved automated-verification policy for this version makes physical
phone/car observations and external human/corpus reviews optional. It does not
create a strict performance-quality PASS_TARGET result. Comparative quality across
arbitrary music, physical synchronization, thermal behavior and energy use remain
unverified.

Bundled model license restrictions remain: Deux CC BY-NC 4.0 and GAME
CC BY-NC-SA 4.0. LightForge is not an official Tesla product.
