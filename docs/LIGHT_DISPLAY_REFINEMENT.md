# Musical display refinement

## Implemented scope

Target: existing 2025 Model 3 Long Range RWD North America profile. No new
hardware capability is assumed.

- Source-specific semantic authority: voice/bass candidates cannot inherit a
  nearby unrelated rhythm/drop's score. Instrumental arrangement anchors now
  participate in the semantic strategy when enabled.
- Local two-beat density budgets (bounded 0.3–2.4 seconds) with the previous
  1.2-second fallback for missing/invalid grids or unsupported gaps. Verified
  beat-backbone gestures are exempt from decorative density pruning. Sorted
  role/time indexes replace repeated full-list scans.
- RGB and exterior beat anchors share nearest-frame timing at 15/20 ms;
  inactive gaps reset automatic voice/bass/pitch envelopes.
- Automatic full-cycle fades preserve at least 50 ms settling after each ramp;
  clipped spans that cannot accommodate both ramps are rejected rather than
  pretending to reach full setpoint. Manual partial ramps remain supported.
- Explicit closure travel/response calibration is consumed by preview and
  validation as well as scheduling. Saved preview indexes use trajectory schema
  2. Default trajectories and raw FSEQ command bytes remain unchanged by this
  preview-model correction.

## Reproducible evidence

Run `npm ci --ignore-scripts --no-audit --no-fund`, then `npm test` with the
unchanged manifest-verified analysis assets materialized per `BUILD.md`.
The production gate explicitly includes the four new refinement suites:
`arrangement-hierarchy-refinement`, `semantic-density-refinement`,
`interior-timing-refinement`, and `calibrated-closure-preview`.

For a paired composition comparison:

```sh
node tools/compare_light_display.cjs /path/to/released-source . > comparison.json
```

This uses five unchanged recorded analysis snapshots, three styles and both
15/20 ms clocks (30 paired cases). It does **not** rerun neural inference or
turn those snapshots into new annotated detector benchmarks. The report records
fixture/output/source hashes, validity, hierarchy activation, accepted source
and rhythm/impact output attacks, dark recovery, transitions, and automatic
full-cycle ramp settling. It exits nonzero for invalid candidate output, lost
protected source/rhythm attacks or insufficient full-cycle ramp settling. Baseline source is
`e82b149b37acd990e699ab7512e9a0afd67d92cd` (application source released as 2.4.2).

The paired candidate comparison produced 30/30 valid shows, activated semantic
planning in all 12 previously inactive instrumental cases, and removed or retimed
none of the previously accepted vocal/bass-note or beat/bar/phrase/impact output
attacks. Low-priority mixture bass-onset decorations are not protected bass-note
events and may intentionally be pruned. Full-cycle ramps
missing the 50 ms settling extension fell from 533 to zero across these cases.
This establishes those fixture invariants, not general perceived superiority.

The new RGB tests fail three of four cases on that baseline (one-frame beat
lag, invented pre-first-beat pulse, stale envelope state after silence) and pass
on the candidate. Calibration tests cover travel/latency, interrupted movement,
Dance readiness, final return, delayed flags, cache invalidation and floating
frame-boundary tolerance. An independent default-trajectory comparison matched
18,700 integer-millisecond seeks across 100 deterministic command streams.

## Limits and remaining phases

These are digital scheduling, preview-model and compatibility checks, not
listener preference, physical latency measurements, on-phone performance or a
new APK release. New Studio projects enable Musical Expression (including semantic
choreography) by default. Direct engine calls with omitted flags and historical
saved projects preserve their prior disabled behavior; users can explicitly
toggle Musical Expression. No compatibility default was changed here. Timing calibration must
come from vehicle-specific observation before physical accuracy can be claimed.
No xLights code is bundled; see `XLIGHTS_INTEGRATION.md` for reference/licensing.

Further perceptual work needs paired music/show review and measured vehicle
video: evaluate role-layer brightness/ducking, phrase-normalized bilateral
patterns and recurrence variation without weakening protected source attacks,
manual controls, dark recovery gaps or output-feasibility constraints.

## Integration validation

On main base `e434d38`, the standalone production gate passed: 824 Node/DOM
tests, 990 Python archive cases (20 skipped), all quality-tool suites and the
unchanged analysis-asset manifest. The 32 ignored GAME/DEUX ONNX files were
recovered from the published APK and verified by length/SHA256, not re-exported.
See `qa/light-display-refinement/validation.json` and `comparison.json`.

Broader discovery before the metadata/CI-only base integration passed 903 cases;
the sole failure was the inherited legacy `migration-1.6.test.cjs` hardcoded
Chromium path, reproduced against released source. Installing the pinned official
browser failed because the downloaded archive was truncated/non-ZIP. That
legacy browser check is not claimed as passed. Production checks were not
removed or weakened.

## Actual application settings coverage

`tests/musical-expression.test.cjs` evaluates the shipped `app.js` in a DOM
harness and generates through the real compiler worker. Its instrumental
new-project case uses the actual recommended settings, with the semantic
sidecars normally returned by the analyzer. It verifies hierarchy activation
without invented vocal/bass-note cues, and explicit disable/re-enable/disable
returns exact disabled frames without another neural analysis call. Existing
cases verify historical missing flags remain off, explicit opt-outs, and
undo/redo frame restoration. This is app/worker integration, not a mocked
settings literal or physical audio/light observation.

## Rhythm-backbone review correction

Independent rendered-output review caught a regression that source-role counters
alone missed: the initial candidate removed 20 pulse-style beat-output attacks
in three 20 ms fixtures. Some were incorrectly included in decorative density;
others lost allocation to a mixture onset or optional anticipation fade.

Each selected beat-loop gesture now carries its original rhythm anchor and is
protected only if that identity matches the linked rhythm evidence. Semantic
allocation uses explicit bands: manual/source vocal+bass/actual impact+movement
arrivals, then the verified beat backbone, then optional decorations. Thus an
anticipatory fade yields instead of erasing a beat or being shortened into an
invalid full-cycle ramp. Disabled/unlinked strategy ordering is unchanged.

The expanded 30-case comparison retains every previously accepted checked
source and rhythm/impact output tuple at its original frame. A regression test
covers the actual recorded gaps (including 30.305, 30.445, 64.445 and 192.115
seconds) at both 15 and 20 ms. This does not promise every possible musical
candidate fits the limited physical outputs; collision/silence safety remains.

## Independent rendered-output check

A separate reviewer sampled the command-driven physical-preview model every
20 ms for five recorded-analysis snapshots across three styles. After the
rhythm correction, all 15 cases retained the checked output/kind/frame anchors
(beat/bar/phrase gestures, vocal/bass-note gestures, impacts and movement
arrivals), with zero conflicting commands. Inspection of before/after output
rasters confirmed that reduced decoration did not merely change counters.

A second pass extracted the shipped `app.js` recommended defaults, rather than
substituting a preset. All five Festival cases were valid and retained those
anchors. Total accepted light cues and observed dark-recovery durations were:

| Recorded analysis | Cues before → after | Dark recovery before → after |
| --- | ---: | ---: |
| Demo | 1787 → 1458 | 0 → 1.60 s |
| Sample | 6269 → 5148 | 9.84 → 14.44 s |
| User Glass prefix | 1587 → 1484 | 1.70 → 2.70 s |
| Nightowl | 227 → 190 | 0 → 0 s |
| Falcon | 195 → 181 | 0 → 0.30 s |

Dark recovery uses the existing quality diagnostic: sampled visual-output
inactivity, counting runs of at least 250 ms. It is not a claim that more darkness
is always better. Retained attacks, reduced competing decoration and visual
inspection together support the bounded result. New-UI options were enabled;
recurrence/motif evidence unavailable in these snapshots remained inactive rather
than invented. No audio model was rerun, no actual lamp brightness/latency was
measured, and no listener preference or universal show-quality gain is asserted.
