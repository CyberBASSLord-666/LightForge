# Performance quality gate report states

The gate report separates whether a metric was measured from what the measured
evidence says. A release review must not treat a missing value, a partial
corpus, or an insufficient number of paired runs as a neutral result.

Every row in `comparisons` includes:

- `status` — release-facing state or measured classification;
- `measurement_status` — `measured`, `unmeasured`, or
  `insufficient_corpus`;
- `reason` — a stable explanation when the metric was not measured;
- observed, measured, and policy-required pair counts; and
- a confidence interval only when the metric was actually measured.

Measured metric states are `improved`, `statistically_equivalent`,
`regressed`, and `inconclusive`. A row is `unmeasured` when a corpus is a
placeholder or incomplete, no pairs match, or a required value is absent from a
matched pair. It is `insufficient_corpus` when all values exist but the locked
corpus has fewer paired repetitions than the policy requires.

`corpus_status` is one of:

- `placeholder` — the policy still contains
  `__configure_locked_corpus__`;
- `incomplete` — required tracks are missing or the report contains tracks
  outside the configured locked set; or
- `complete` — each configured track is present on both sides.

For `placeholder`, `incomplete`, or insufficient pair evidence, `runtime`
contains a non-numeric reduction (`paired_reduction_percent: null`) and
`target_met: false`. This deliberately prevents a partial track result from
being presented as a release performance percentage.

`production_ready` is true only for `PASS_TARGET` with a complete locked corpus
and complete required measurements. A release report can therefore expose raw
diagnostic context without accidentally asserting that unmeasured or partial
evidence is production-ready.
