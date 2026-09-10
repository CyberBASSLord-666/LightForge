# Perceptual validation sidecar

`web/engine/perceptual-validation.js` provides a bounded, read-only report for
the gap between an intended perceptual musical event and an explicitly recorded
output realization.  It does not modify a show, planner, frame buffer, or FSEQ.

It is loaded in the browser and composition worker, but is not enabled by the
default show-generation path.  Call it explicitly after final realization:

```js
const report = PerceptualValidation.evaluate(show, {
  eventEvidence: [
    {
      eventClass: 'vocals',
      targetTime: 42.000,
      commandTime: 41.980,
      predictedPerceptualTime: 42.015,
      status: 'matched',
      salience: 0.92,
      collisionLoss: false
    }
  ],
  syncReview: show.synchronization,
  choreographyQuality: show.choreography.quality
});
```

## Evidence contract

Each event needs an explicit `eventClass` (or `role`/`type`) and target time.
Coverage requires an explicit realization status such as `matched` or
`suppressed`.  Command timing needs an explicit command timestamp.  A physical
perceptual timing metric requires either `measuredPerceptualTime`, or
`perceptualTime` accompanied by `perceptualEvidence: 'measured'`.

`predictedPerceptualTime` is reported separately with `state: "estimated"`.
It is never relabelled as an observed physical response.  An unmarked
`perceptualTime` is deliberately ignored for physical timing metrics.

The report supplies absolute-error percentiles for every event class that has
valid timing pairs: median, P90, P95, P99, and maximum.  It also reports
coverage, high-salience coverage, explicit collision loss, SyncReview's
aggregate collision evidence, and assessed feasibility counts from the
choreography-quality report.

## Unavailable is meaningful

For canonical classes with no evidence, each metric has
`state: "unavailable"`, `null` rates/errors, and a reason.  This includes event
classes LightForge does not currently route directly (for example kick, snare,
beat, downbeat, section, and climax).  The sidecar never converts detector
timestamps, a missing route, a planned command, or a latency estimate into a
claim of detector accuracy or perceptual synchronization.

The event list is bounded to 10,000 accepted rows and at most 32 classes.  The
report includes invalid and omitted counts so truncation cannot be mistaken for
perfect recall.


### Canonical event classes and timestamps

The report canonicalizes LightForge semantic-timeline names before computing coverage: `vocal_note`, `bass_note`, `percussion_kick`, and `percussion_snare` contribute to `vocals`, `bass`, `kick`, and `snare`; other supported percussion subtypes contribute to `percussion`. `lighting` and `mechanical` are both canonical classes, so missing evidence remains visibly unavailable rather than disappearing from the report. Negative target, command, measured, and predicted timestamps are rejected as timing evidence; invalid rows are counted in the report instead of contributing a misleading alignment score.
