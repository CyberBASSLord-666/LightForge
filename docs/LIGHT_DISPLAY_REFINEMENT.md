# Musical display refinement

## Implemented scope

Target: existing 2025 Model 3 Long Range RWD North America profile. No new
hardware capability is assumed.

- Source-specific semantic authority: voice/bass candidates cannot inherit a
  nearby unrelated rhythm/drop's score. Instrumental arrangement anchors now
  participate in the opt-in semantic strategy.
- Local two-beat density budgets (bounded 0.3–2.4 seconds) with the previous
  1.2-second fallback for missing/invalid grids or unsupported gaps. Sorted
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
output attacks, and automatic full-cycle ramp settling. Baseline source is
`e82b149b37acd990e699ab7512e9a0afd67d92cd` (application source released as 2.4.2).

The paired candidate comparison produced 30/30 valid shows, activated semantic
planning in all 12 previously inactive instrumental cases, and removed or retimed
none of the previously accepted vocal/bass output attacks. Full-cycle ramps
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
new APK release. Semantic choreography remains opt-in. Timing calibration must
come from vehicle-specific observation before physical accuracy can be claimed.
No xLights code is bundled; see `XLIGHTS_INTEGRATION.md` for reference/licensing.

Further perceptual work needs paired music/show review and measured vehicle
video: evaluate role-layer brightness/ducking, phrase-normalized bilateral
patterns and recurrence variation without weakening protected source attacks,
manual controls, dark recovery gaps or output-feasibility constraints.

## Integration validation

On main base `e434d38`, the standalone production gate passed: 821 Node/DOM
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
