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
  --release-policy-attestation /secure/release-policy-attestation.json \
  --output artifacts/performance-quality-report.json \
  --require-production-ready
```

## Policy modes

| Mode | Intended use | Release result |
| --- | --- | --- |
| Omitted or `legacy` | Existing, explicitly declared metric sets. | Comparable only; `production_ready` is always false. |
| `template` | Checked-in redacted corpus configuration. | Always fails with `unconfigured_locked_corpus`; it needs only its declared template metrics. |
| `release` | A reviewed private locked corpus and immutable complete metric contract. | Can produce `PASS_TARGET` and `production_ready: true` only with a source-pinned authority's detached policy/corpus signature. |

The checked-in policy is deliberately `template` mode. It must not be edited
locally to turn a synthetic corpus into a production claim.
Use `--require-production-ready` only for protected release execution: it
returns nonzero for a merely comparable or `PASS_TARGET` result that lacks
all production authority, corpus, telemetry, and review requirements. The
release workflow always uses this strict mode.

## Trusted release authority

A release policy, corpus manifest, verifier key, and review signature carried
next to candidate data are not a trust boundary: a candidate could create all
four. A matching SHA-256 supplied by that same party is not a trust boundary
either. Release mode therefore requires `--release-policy-attestation`, an
external detached Ed25519 receipt over the canonical policy SHA-256 and
locked-corpus-manifest SHA-256. The receipt is verified only with a public key
in the gate source's `RELEASE_POLICY_AUTHORITY_KEYS` registry. The gate never
obtains a policy-authority key from a policy, manifest, artifact, CLI argument,
or environment variable.

The checked-in registry intentionally starts empty. That makes an otherwise
valid release report fail closed with `release_policy_authority_unconfigured`
until a reviewed trusted-source release adds the approved authority public key
and digest. The private signing key remains outside this repository and outside
CI artifacts. A candidate can name an authority only through the policy's
auditable reference; that reference must exactly match the source-pinned ID,
protocol, algorithm, and public-key digest. A fabricated authority ID, policy
digest, or receipt cannot produce `production_ready: true`.

The official dispatch runs only from protected `main` and the protected
`lightforge-release-quality` GitHub Environment. That environment supplies
three protected values: `LIGHTFORGE_RELEASE_POLICY_JSON`,
`LIGHTFORGE_RELEASE_CORPUS_MANIFEST_JSON`, and
`LIGHTFORGE_RELEASE_POLICY_ATTESTATION_JSON`. Candidate and baseline artifacts
supply only their `benchmark.json` evidence. The workflow never accepts a
policy, manifest, authority key, or authority receipt from a candidate artifact
or dispatch input. The protected receipt is useful only because the verifier
key is independently pinned in reviewed gate source. Do not store a private
signing key or HMAC secret in the policy, repository, manifest, artifact, or
environment policy bundle.

A real release policy pins the corpus identity, omits custom `metrics`, and
binds the compiled contract into its policy digest:

```json
{
  "schema_version": 4,
  "required_tracks": ["private-track-a", "private-track-b"],
  "release_profile": {
    "mode": "release",
    "metric_contract": "lightforge-release-metrics-v4",
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
    "policy_authority": {
      "authority_id": "approved-release-policy-authority",
      "protocol": "lightforge-release-policy-authority-v1",
      "algorithm": "ed25519",
      "verification_key_sha256": "<sha256-of-source-pinned-public-key>"
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

The protected authority receipt is a separate JSON object, never embedded in
the candidate policy. Its exact fields are canonicalized before signing:

```json
{
  "schema_version": 1,
  "protocol": "lightforge-release-policy-authority-v1",
  "authority_id": "approved-release-policy-authority",
  "algorithm": "ed25519",
  "verification_key_sha256": "<source-pinned-key-digest>",
  "policy_sha256": "<canonical-policy-digest>",
  "corpus_manifest_sha256": "<locked-corpus-digest>",
  "signed_payload_sha256": "<canonical-envelope-digest>",
  "signature_base64": "<canonical-base64-64-byte-ed25519-signature>"
}
```

The signature binds the exact policy and corpus together. Replaying it after
either changes, changing the named authority or key digest, supplying a
malformed signature, or running without an Ed25519 verifier produces a
machine-readable `FAIL`. The legacy `--trusted-release-policy-sha256` option is
accepted only as a deprecated audit hint and never authorizes production.

The gate rejects a release policy that supplies its own metric rules, changes
the contract name, has an unpinned corpus/runtime profile, has fewer than five
pairs, uses less than 99% confidence or 20,000 resamples, targets any metric
other than total wall-clock time, or changes the target from exactly 75%.
Those floors are enforced by the full comparison, not only by documentation.
Its output includes the effective metric contract, corpus diagnostics, and
SHA-256 bindings so a result remains auditable even when the real corpus is
private.

## Locked evidence

Both reports use schema version 4 and have the same suite identity:

```json
{
  "schema_version": 4,
  "suite": {
    "corpus_id": "licensed-locked-corpus-2026q3",
    "corpus_manifest_sha256": "...",
    "protocol_id": "performance-quality-release-v1",
    "policy_sha256": "...",
    "cache_protocol": "lightforge-cache-condition-v2"
  },
  "runs": [{
    "track_id": "private-track-a",
    "pair_id": "cold-batch-001",
    "run_id": "candidate-private-track-a-001",
    "metrics": {"performance": {}, "resources": {}, "quality": {}},
    "provenance": {},
    "condition": {
      "cache_mode": "cold",
      "cache_protocol": "lightforge-cache-condition-v2",
      "cache_setup": {
        "schema_version": 1,
        "protocol": "lightforge-cache-setup-v1",
        "mode": "cold",
        "setup_id": "release-cold-reset-2026q3",
        "pair_order": "counterbalanced",
        "thermal_cycle_id": "release-cold-cycle-2026q3-a"
      },
      "cache_setup_sha256": "...",
      "cache_evidence": {
        "schema_version": 2,
        "protocol": "lightforge-cache-condition-v2",
        "mode": "cold",
        "stages": [{"stage_id": "source_separation", "attempt": 1, "stage_status": "completed", "cache_status": "miss", "checkpoint_status": "written", "recovery_from_attempt": null}],
        "cache_hits": 0,
        "cache_misses": 1,
        "checkpoint_reuses": 0,
        "recovery_stages": 0,
        "interrupted_stage_attempts": 0
      },
      "cache_evidence_sha256": "..."
    }
  }]
}
```

Each `pair_id` identifies one baseline/candidate pair for one track. The gate
requires the same track set, enough repeated pairs, equal corpus/audio identity
including duration, canonical sample rate, and channels; analysis
configuration; preprocessing and model versions; hardware/runtime/accelerator;
seed; thermal profile; cache mode; protocol; and controlled cache setup digest.
Observed cache evidence is independently validated but is not cross-side equal:
a correct cache optimization may legitimately change it. Pipeline source version
may differ because it is the candidate under test.

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
distinct audio identities, pin each track's duration, canonical sample rate,
and channels, use exactly the committed coverage requirement and golden-artifact
requirement lists, cover every required tag family, and provide all ten golden
SHA-256 values for every track. `locked_corpus` diagnostics in
the gate result expose only hashes, counts, and coverage status.

Baseline output hashes must exactly reproduce those locked goldens. Candidate
output hashes are present for every repeated run and must be deterministic per
track. A legitimate candidate change requires a canonical
`candidate_output_differential` that exactly lists the changed hashes and
rationale hashes. The mandatory external blinded-review signature covers that
differential and the full candidate benchmark evidence, so a musical
improvement can be reviewed without allowing an unexplained behavioral change.

## Immutable release metric contract

`lightforge-release-metrics-v4` requires all of the following families. The
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

All performance and resource values in a release report are reconciled against
`profiler_measurement_evidence` derived from execution/stage telemetry.
Unmeasured values are omitted rather than converted to zero; because release
metrics are required, missing instrumentation blocks release evidence.

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
source/pipeline identity hash, policy SHA-256, corpus-manifest SHA-256, and
canonical baseline/candidate benchmark-evidence SHA-256 values. The benchmark
projection excludes only the review signature itself to avoid a circular hash;
it retains every run, metric, provenance field, change declaration, review
rating, and diagnostic/output digest. Candidate runs must contain the same
source SHA-256 and pipeline version. Editing either report after review—such
as changing a wall-clock value—therefore invalidates the attestation. A
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

For the manually dispatched GitHub workflow, provide the artifact name and
exact successful source run ID for both baseline and candidate. The workflow
has `actions: read` explicitly and downloads each artifact from that run ID in
this LightForge repository only; it never guesses the current run or accepts a
cross-repository artifact. Dispatchers must record source run URLs from the
approved locked-benchmark workflow in the release evidence. The comparison runs
only from protected `main`, requires the protected
`lightforge-release-quality` environment, and rejects an absent protected
policy/corpus/authority receipt before comparison. Candidate artifacts contain
only `benchmark.json`; the policy, locked manifest, and detached authority
receipt are materialized from the protected environment and the receipt is
passed through `--release-policy-attestation`. The gate verifies it against a
public key compiled into reviewed source, not against a candidate-owned key.
This prevents a candidate-supplied policy, corpus, verifier key, digest, or
self-signed authority receipt from becoming a release authority.
All action references are full immutable commit SHAs and have a static
regression test.

The release bootstrap remains exactly 20,000 or more resamples at 99% or more
confidence. The implementation memoizes only byte-identical deterministic
series within one process; it never lowers the resample count, alters a seed,
or substitutes a cheaper statistical test.
