# Performance quality gate

`tools/performance_quality_gate.py` compares paired baseline and candidate
analysis reports. It is a fail-closed release gate: a faster run is never
evidence that the musical interpretation, choreography, synchronization, or
resource behavior remained acceptable.

```sh
python3 tools/performance_quality_gate.py \
  --baseline artifacts/benchmark-baseline.json \
  --candidate artifacts/benchmark-candidate.json \
  --policy qa/performance-gate-policy.json \
  --output artifacts/performance-quality-report.json
```

## Policy modes

| Mode | Intended use | Release result |
| --- | --- | --- |
| Omitted or `legacy` | Existing, explicitly declared metric sets. | Comparable only; `production_ready` is always false. |
| `template` | Checked-in redacted corpus configuration. | Always fails with `unconfigured_locked_corpus`; it needs only its declared template metrics. |
| `release` | A reviewed private locked corpus and immutable complete metric contract. | Can produce `PASS_TARGET` and `production_ready: true`. |

The checked-in policy is deliberately `template` mode. It must not be edited
locally to turn a synthetic corpus into a production claim.

A real release policy pins the corpus identity, omits custom `metrics`, and
binds the compiled contract into its policy digest:

```json
{
  "schema_version": 3,
  "required_tracks": ["private-track-a", "private-track-b"],
  "release_profile": {
    "mode": "release",
    "metric_contract": "lightforge-release-metrics-v1",
    "locked_corpus": {
      "corpus_id": "licensed-locked-corpus-2026q3",
      "manifest_sha256": "<lower-case sha256>"
    },
    "human_perceptual_review": {
      "required_for_major_pipeline_changes": true,
      "minimum_reviewers": 3,
      "required_attributes": [
        "musical_synchronization", "vocal_synchronization",
        "bass_synchronization", "beat_precision", "visual_coherence",
        "phrase_coherence", "contrast", "anticipation", "payoff",
        "repetitiveness", "climax_quality", "overall_musicality"
      ]
    }
  },
  "minimum_pairs_per_track": 5,
  "bootstrap": {"method": "paired-percentile-v1", "seed": "committed-seed", "confidence": 0.99, "resamples": 20000},
  "runtime_target": {"metric": "performance.total_wall_clock_seconds", "target_reduction_percent": 75, "scope": "each_required_track"}
}
```

The gate rejects a release policy that supplies its own metric rules, changes
the contract name, has an unpinned corpus, has fewer than three reviewers, or
omits any required blinded-review attribute. Its output includes the complete
effective metric contract and SHA-256 so a result remains auditable even when
the real corpus is private.

## Locked evidence

Both reports use schema version 3 and have the same suite identity:

```json
{
  "schema_version": 3,
  "suite": {
    "corpus_id": "licensed-locked-corpus-2026q3",
    "corpus_manifest_sha256": "...",
    "protocol_id": "performance-quality-release-v1",
    "policy_sha256": "..."
  },
  "runs": [{
    "track_id": "private-track-a",
    "pair_id": "cold-batch-001",
    "run_id": "candidate-private-track-a-001",
    "metrics": {"performance": {}, "resources": {}, "quality": {}},
    "provenance": {},
    "condition": {"cache_mode": "cold", "pair_order": "baseline-first"}
  }]
}
```

Each `pair_id` identifies one baseline/candidate pair for one track. The gate
requires the same track set, enough repeated pairs, equal corpus and audio
identity, analysis configuration, preprocessing and model versions,
hardware/runtime/accelerator, seed, thermal profile, and cache mode. Pipeline
source version may differ because it is the candidate under test.

Every required metric leaf is a finite number. A metric can be declared only
as explicit non-applicable evidence when its release rule permits it:

```json
{
  "status": "not_applicable",
  "reason": "no licensed annotation exists for this track",
  "evidence_id": "annotation-coverage-2026q3"
}
```

The same evidence must apply to every paired run on both sides. Tracks cannot
silently switch a metric from numeric to non-applicable, and event-specific
metrics require the committed corpus to make them applicable on at least one
track. Hardware-unavailable accelerator/energy/thermal observations may use
explicit evidence rather than fabricated zeroes.

## Immutable release metric contract

`lightforge-release-metrics-v1` requires all of the following families. The
metric names are emitted under `metric_contract.rules` in every release result.

- Performance: total and per-stage wall time (decode, feature generation,
  separation, rhythm/tempo/beat/downbeat, vocal/drum/bass/structure,
  choreography/collision/vehicle/FSEQ/validation), initialization, inference,
  pre/post-processing, waiting, cache hit/miss behavior, and checkpoint/resume
  overhead.
- Resources: CPU time and utilization, accelerator utilization and memory,
  RAM, allocation pressure, disk I/O, temporary storage, and energy/thermal
  observations where the locked hardware exposes them.
- Rhythm: tempo, beat/downbeat F1 and positional error, meter, bar boundary,
  and phrase boundary accuracy.
- Vocals: region precision/recall/F1, singing/speech classification, note
  onset/offset, pitch, phrase boundaries, acoustic syllable/articulation timing,
  stress, and lead/backing role accuracy where ground truth exists.
- Drums: precision, recall, and F1 for kick, snare, clap, hat, crash, tom/fill,
  and other percussion, plus onset timing error.
- Bass: event and note-onset precision/recall/F1, pitch, duration, timing,
  sub-bass recall, and kick+bass coincidence.
- Structure: section boundaries and similarity, structural-event recall,
  recurrence precision/recall, motif identity, repeated-section matching, and
  semantic classification.
- Choreography: important/high-salience and role coverage, downbeat/phrase and
  motif coherence/evolution, density, negative space, dynamic contrast,
  section/climax differentiation, entropy/redundancy/monotony, collision loss,
  feasibility, overuse, duration violations, and conflicts.
- Synchronization: separate command and predicted perceptual absolute-error
  median/P90/P95/P99/maximum for vocals, bass, kick, snare, percussion, beat,
  downbeat, section transition, climax, mechanical actuators, and lighting.

No rule is synthesized from a candidate report. The complete fixed rules and
tolerances are hashed into `policy_sha256` before collection begins.

## Blinded human perceptual review

Every release candidate declares a top-level change classification. A `major`
pipeline change must include `human_perceptual_review` with exactly these
fields: schema version 1, protocol `blinded-ab-v1`, `pass`, `review_id`, and
at least three blinded opaque reviewer IDs. Each reviewer rates every required
attribute as `candidate_preferred`, `baseline_preferred`, `equivalent`, or
`inconclusive`.

Missing, malformed, unblinded, incomplete, inconclusive, failed, or
baseline-preferred major review evidence blocks the release. Reviewer IDs and
ratings are structural evidence only; do not place comments, names, lyrics,
or other private material in the report.

## Classification

For non-neutral metrics, paired effects are normalized so positive means a
candidate improvement. A deterministic SHA-seeded paired percentile bootstrap
computes the committed 99% confidence interval:

- `improved`: lower confidence bound is greater than zero.
- `statistically_equivalent`: the complete interval is inside the committed
  equivalence tolerance.
- `regressed`: the interval is worse than tolerance, or any pair crosses its
  committed hard-regression floor.
- `inconclusive`: evidence does not establish either outcome.
- `observed`: a required neutral resource/entropy observation with no implied
  better direction.

Critical metrics may only be improved or statistically equivalent. `PASS_TARGET`
also requires the lower 99% confidence bound of the paired runtime reduction
to meet 75% for every required track. `PASS_PARTIAL` never makes the build
production-ready. `FAIL` means evidence, quality, review, or comparability is
insufficient.

## Tooling verification

The production verification workflow runs the gate, benchmark-contract,
locked-runner, and differential-analysis Python suites in addition to the
engine tests. Those are contract tests only. A runtime or production-readiness
claim still requires a real locked corpus, paired reports, valid review evidence
when required, and an actual gate result.
