# Performance quality gate

`tools/performance_quality_gate.py` compares paired baseline and candidate
analysis reports. It is a fail-closed release gate: a faster run is never
evidence that the musical interpretation, choreography, synchronization, or
resource behavior remained acceptable.

```sh
python3 tools/performance_quality_gate.py \
  --baseline artifacts/benchmark-baseline.json \
  --candidate artifacts/benchmark-candidate.json \
  --locked-corpus-manifest /secure/locked-corpus-manifest.json \
  --policy qa/performance-gate-policy.json \
  --trusted-release-policy-sha256 "$LIGHTFORGE_RELEASE_POLICY_SHA256" \
  --output artifacts/performance-quality-report.json
```

## Policy modes

| Mode | Intended use | Release result |
| --- | --- | --- |
| Omitted or `legacy` | Existing, explicitly declared metric sets. | Comparable only; `production_ready` is always false. |
| `template` | Checked-in redacted corpus configuration. | Always fails with `unconfigured_locked_corpus`; it needs only its declared template metrics. |
| `release` | A reviewed private locked corpus and immutable complete metric contract. | Can produce `PASS_TARGET` and `production_ready: true` only with a trusted out-of-band policy binding. |

The checked-in policy is deliberately `template` mode. It must not be edited
locally to turn a synthetic corpus into a production claim.

## Trusted release authority

A release policy, corpus manifest, verifier key, and review signature carried
next to candidate data are not a trust boundary: a candidate could create all
four. Therefore release mode also requires
`--trusted-release-policy-sha256`, an out-of-band SHA-256 supplied by the
protected release authority. It must equal the canonical policy hash that the
gate computes; otherwise the gate emits
`release_trusted_policy_binding_required` or
`release_trusted_policy_binding_mismatch` and cannot be production-ready.

The official dispatch runs only from protected `main` and the protected
`lightforge-release-quality` GitHub Environment. That environment supplies
three protected values: `LIGHTFORGE_RELEASE_POLICY_JSON`,
`LIGHTFORGE_RELEASE_CORPUS_MANIFEST_JSON`, and
`LIGHTFORGE_RELEASE_POLICY_SHA256`. Candidate and baseline artifacts supply
only their `benchmark.json` evidence. The workflow never accepts a policy,
manifest, public key, or trusted digest from a candidate artifact or dispatch
input. Do not store a private signing key or HMAC secret in the policy,
repository, manifest, artifact, or environment policy bundle.

A real release policy pins the corpus identity, omits custom `metrics`, and
binds the compiled contract into its policy digest:

```json
{
  "schema_version": 3,
  "required_tracks": ["private-track-a", "private-track-b"],
  "release_profile": {
    "mode": "release",
    "metric_contract": "lightforge-release-metrics-v2",
    "locked_corpus": {
      "corpus_id": "licensed-locked-corpus-2026q3",
      "manifest_sha256": "<lower-case sha256>"
    },
    "locked_runtime_profile": {
      "runtime_profile_id": "approved-host-profile",
      "hardware_fingerprint": "...",
      "runtime_backend": "...",
      "runtime_version": "...",
      "thermal_profile": "...",
      "random_seed": 42,
      "accelerator": {"available": true, "fingerprint_sha256": "<lower-case sha256>"}
    },
    "human_perceptual_review": {
      "required_for_every_release_candidate": true,
      "minimum_reviewers": 3,
      "required_attributes": [
        "musical_synchronization", "vocal_synchronization",
        "bass_synchronization", "beat_precision", "visual_coherence",
        "phrase_coherence", "contrast", "anticipation", "payoff",
        "repetitiveness", "climax_quality", "overall_musicality"
      ],
      "attestation": {
        "protocol": "external-review-attestation-v2",
        "verifier_id": "approved-blind-review-service",
        "algorithm": "ed25519",
        "verification_key_base64": "<canonical-base64-32-byte-public-key>",
        "verification_key_sha256": "<sha256-of-the-decoded-public-key>"
      }
    }
  },
  "minimum_pairs_per_track": 5,
  "bootstrap": {"method": "paired-percentile-v1", "seed": "committed-seed", "confidence": 0.99, "resamples": 20000},
  "runtime_target": {"metric": "performance.total_wall_clock_seconds", "target_reduction_percent": 75, "scope": "each_required_track"}
}
```

The gate rejects a release policy that supplies its own metric rules, changes
the contract name, has an unpinned corpus/runtime profile, has fewer than five
pairs, uses less than 99% confidence or 20,000 resamples, targets any metric
other than total wall-clock time, or changes the target from exactly 75%.
Those floors are enforced by the full comparison, not only by documentation.
Its output includes the effective metric contract, corpus diagnostics, and
SHA-256 bindings so a result remains auditable even when the real corpus is
private.

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
as explicit non-applicable evidence when its release rule permits it and the
same `reason`/`evidence_id` is pre-bound in that track's immutable corpus
manifest annotation record:

```json
{
  "status": "not_applicable",
  "reason": "no licensed annotation exists for this track",
  "evidence_id": "annotation-coverage-2026q3"
}
```

The manifest record additionally pins an annotation SHA-256. The same evidence
must apply to every paired run on both sides. Tracks cannot silently switch a
metric from numeric to non-applicable, and event-specific metrics require the
committed corpus to make them applicable on at least one track. The only
runtime exception is accelerator memory/utilization on a host whose
`locked_runtime_profile.accelerator.available` is false and whose exact runtime
reason/evidence ID matches every affected run. Energy and thermal fields do not
receive a free-form non-applicable exception.

The trusted supplied release manifest must itself be canonical-hash equal to the
policy pin, set `template: false` and `release_ready: true`, contain at least 16
distinct audio identities, use exactly the committed coverage requirement and
golden-artifact requirement lists, cover every required tag family, and provide
all ten golden SHA-256 values for every track. `locked_corpus` diagnostics in
the gate result expose only hashes, counts, and coverage status.

## Immutable release metric contract

`lightforge-release-metrics-v2` requires all of the following families. The
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

Every release candidate, including one classified `minor`, must include
`human_perceptual_review`. It has schema version 1, protocol `blinded-ab-v1`,
status `pass`, a review ID, at least three blinded opaque reviewer IDs, and the
external attestation described below. Each reviewer rates every required
attribute as `candidate_preferred`, `baseline_preferred`, `equivalent`, or
`inconclusive`.

The strict acceptance rule permits only `candidate_preferred` or `equivalent`
ratings. Any baseline-preferred or inconclusive rating, even a single minority
vote, blocks release. An all-equivalent review is an explicit decisive
no-regression judgement; an all-inconclusive review is not.

`blinded: true` alone is not a production proof. The review must carry an
`external-review-attestation-v2` detached Ed25519 signature. Policy pins the
verifier ID, the exact 32-byte public key (canonical base64), and its SHA-256.
The signature covers a canonical payload containing the review hash, candidate
source/pipeline identity hash, policy SHA-256, and corpus-manifest SHA-256.
Candidate runs must contain the same source SHA-256 and pipeline version. A
missing, mismatched, or invalid signature leaves the result `FAIL`; if neither
an available Python Ed25519 backend nor an Ed25519-capable `openssl` is
available, the result fails closed with
`human_review_external_verification_unavailable`. A self-attested boolean or
receipt hash cannot produce `production_ready: true`. Reviewer IDs and ratings
are structural evidence only; do not place comments, names, lyrics, or other
private material in the report.

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

For the manually dispatched GitHub workflow, provide the artifact name, source
repository, and source run ID for both baseline and candidate. The workflow has
`actions: read` explicitly and downloads each artifact from exactly that source;
it never guesses the current run. It runs only from protected `main`, requires
the protected `lightforge-release-quality` environment, and rejects an absent
trusted policy/corpus/digest before comparison. Candidate artifacts contain
only `benchmark.json`; the policy and locked manifest are materialized from the
protected environment and the trusted digest is passed through
`--trusted-release-policy-sha256`. This prevents a candidate-supplied policy,
corpus, verifier key, or self-signed review from becoming a release authority.
All action references are full immutable commit SHAs and have a static
regression test.

The release bootstrap remains exactly 20,000 or more resamples at 99% or more
confidence. The implementation memoizes only byte-identical deterministic
series within one process; it never lowers the resample count, alters a seed,
or substitutes a cheaper statistical test.
