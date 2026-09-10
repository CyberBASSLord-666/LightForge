# Choreography-quality diagnostics

`web/engine/choreography-quality.js` is a deterministic, read-only sidecar for
finished `show` objects. It never changes `show.frames`, planned events, or FSEQ
output. It measures exported signal and explicit-planning characteristics; it
does not claim music-detection accuracy, human preference, or real-vehicle
behavior.

`ShowEngine.generate()` attaches the report at
`show.choreography.quality` immediately after final synchronization review. The
interactive page and the composition Web Worker load the sidecar before
`show-engine.js`; CommonJS callers receive it through the engine dependency.

When an input includes a structurally matching `semanticTimeline` and
`musicSalience`, the engine also writes
`show.choreography.salienceTargets`. It contains only target indices/times plus
matched semantic event IDs, timing deltas, score, and tier—never lyric text or
new musical events. The existing light and movement targets are copied with
those score/tier annotations for final synchronization and tier coverage. This
does not alter planner selection, frames, or FSEQ bytes. Missing, stale, or
malformed semantic/salience input takes the exact legacy synchronization path.

```js
const Quality=require('./web/engine/choreography-quality.js');
const report=Quality.evaluate(show, {
  // A supplied profile gives output and actuator names. VehicleProfile is used
  // automatically when the module is loaded beside the engine.
  profile: VehicleProfile,
  windowMs: 2000,
  hopMs: 1000,
  visualSampleMs: 100,
  minimumNegativeSpaceMs: 250,
  includeWindows: false,
  tierTargets: [
    {time: 42.0, end: 42.4, tier: 'structural', candidateOutputIds: ['left-signature']}
  ]
});
```

The report includes:

- `density`: sampled visual-transition density and active-output fraction over
  overlapping windows. Sampling is explicit so RGB ramps are not misreported as
  hundreds of independent flash commands.
- `negativeSpace`: observed dark runs that exclude closure actuators, plus
  `declared` coverage only when `declaredNegativeSpace` or
  `show.choreography.negativeSpace` explicitly declares an intended interval.
  Observed darkness is never labelled intentional on its own.
- `repetition`: exact sampled-pattern redundancy, adjacent repeat rate, and
  normalized Shannon entropy. These are signal-complexity indicators, not a
  verdict that a show is monotonous.
- `outputOveruse`: per-output sampled transition rate and active fraction. A
  transition-rate violation is reported only if
  `maximumTransitionsPerMinute`/`maxTransitionsPerMinute` explicitly supplies a
  per-output, per-kind, or default limit.
- `actuatorOveruse`: final-FSEQ command-run counts compared with a profile's
  explicit `commandLimit`; no limit is inferred where none exists.
- `minimumDurations`: configured minimum-useful-duration and repeat-interval
  violations. Supply `minimumDurationMs`/`minimumRepeatIntervalMs` by output,
  kind, or `default`, or use explicit vehicle timing calibration metadata.
- `conflictingCommands`: overlaps with different commands in supplied
  `show.lightEvents`/`show.movements` metadata. Final bytes alone cannot reveal
  an overwritten planning command, so this metric is marked unassessed when
  that metadata is absent.
- `hierarchy`: final-frame attack and active coverage for explicitly supplied
  tier-labelled targets. It is realization coverage, not validation that the
  target itself was musically correct.

The default 100 ms visual sampling and four-level RGB quantization are a
diagnostic scale, not export quantization. Change `visualSampleMs` or
`rgbQuantizationLevels` only when comparing like-for-like reports. Keep
`includeWindows` off for long shows unless per-window diagnostic rows are needed;
aggregate metrics are always computed.
