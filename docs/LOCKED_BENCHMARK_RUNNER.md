# Locked benchmark corpus runner

`tools/locked_benchmark_runner.py` turns strict per-attempt diagnostics from
`analysis_benchmark_contract.py` into a deterministic, paired input for
`performance_quality_gate.py`. It is a measurement and evidence tool only: it
does not decode audio, run a model, alter analysis, or change an FSEQ.

The checked-in [locked-corpus-manifest.template.json](../qa/locked-corpus-manifest.template.json)
is deliberately redacted. It contains synthetic SHA-256 values, generic
scenario labels, and no audio, source path, URL, lyric, artist, or song title.
It cannot be used as a release corpus.

## Create the real locked manifest

Keep the actual corpus audio in the approved private test store, not in this
repository. Create a private manifest from the template and replace every
synthetic audio identity, duration, tag set, and golden-artifact digest. Then:

1. Remove `"template": true`.
2. Set `"release_ready": true` only once the manifest and goldens are frozen.
3. Version the manifest and record its canonical SHA-256 in release evidence.
4. Create a reviewed `release_profile` in the gate policy with exactly its
   `track_id`s in `required_tracks`, the manifest's exact corpus ID/SHA-256,
   and `lightforge-release-metrics-v2`; do not leave the fail-closed template
   placeholder in place.

The production manifest must contain at least 16 distinct audio identities,
every immutable coverage tag family, and approved golden hashes for semantic
timeline, rhythm, vocals, bass, drums, sections, salience, choreography, FSEQ
characteristics, and perceptual validation. The template lists those required
artifact categories, but is intentionally not a substitute for them.

Validate the redacted template structurally without promoting it to a release
corpus:

```bash
python3 tools/locked_benchmark_runner.py validate-manifest \
  --manifest qa/locked-corpus-manifest.template.json \
  --allow-template
```

Validate a real manifest:

```bash
python3 tools/locked_benchmark_runner.py validate-manifest \
  --manifest /secure/locked-corpus-manifest.json
```

## Capture and validate runs

Each production analysis attempt emits one strict diagnostic through
`AnalysisRunRecorder`. It binds the audio content hash, corpus-manifest hash,
model versions, preprocessing version, analysis configuration, runtime,
accelerator, seed, thermal profile, stage timings, cache behavior, and output
hashes. The runner validates every report with both
`validate_diagnostic()` and `validate_against_corpus()`.

For a release comparison, gather the policy's minimum number of independently
recorded *pairs* per locked track under a controlled, equivalent operating
condition. Baseline and candidate are paired by a stable `pair_id`, not by
timestamp proximity or array position:

```bash
python3 tools/locked_benchmark_runner.py validate-reports \
  --manifest /secure/locked-corpus-manifest.json \
  --reports /secure/baseline-diagnostics
```

The default is fail-closed: every manifest track must be present. The
`--allow-incomplete-corpus` option exists only for bring-up validation; it
cannot be used by `aggregate` and therefore cannot create a release gate input.

The runner rejects:

- template or non-release-ready manifests;
- reports for an unknown track, stale manifest, mismatched content hash, or
  invalid diagnostic contract;
- duplicate `(track_id, run_id)` measurements or duplicated report content;
- missing locked tracks;
- mixed hardware/runtime/accelerator/model/preprocessing/configuration/seed or
  thermal conditions inside one aggregate; and
- fewer than the configured repeated runs per track.

This prevents a fast warm-cache run, a different device, or a different model
from silently being counted as evidence for a candidate.

## Pairing and controlled condition

The gate's schema requires a `suite` identity, stable cross-side `pair_id`, and
per-run `condition.cache_mode`. `aggregate` derives the pair ID from the
diagnostic `run_id` by default. Therefore the benchmark harness should assign
the same opaque run ID to the corresponding baseline and candidate attempt,
for example `vocal-rock-pair-001`. A run ID need not be a wall-clock timestamp.

If an existing harness cannot do that, provide a sidecar mapping to each
aggregate command:

```json
{
  "schema_version": 1,
  "pairs": [
    {"track_id": "vocal-rock", "run_id": "candidate-attempt-a", "pair_id": "vocal-rock-pair-001"}
  ]
}
```

The mapping must cover exactly the supplied diagnostics and may not map two
runs of the same track to one pair. The baseline and candidate mappings must
resolve to the same pair IDs. Run cold-cache and warm-cache protocols as
separate suites; never label both as the same `cache_mode`.

## Build the quality-gate inputs

Aggregate baseline and candidate diagnostics separately with the same committed
policy, protocol ID, and cache mode. The output has the gate's schema-3
`suite` and paired `runs` fields, while retaining contract provenance and
deterministic per-track, per-stage timing and cache summaries for
investigation.

```bash
python3 tools/locked_benchmark_runner.py aggregate \
  --manifest /secure/locked-corpus-manifest.json \
  --reports /secure/baseline-diagnostics \
  --policy qa/performance-gate-policy.json \
  --protocol-id locked-corpus-cold-v1 \
  --cache-mode cold \
  --report-side baseline \
  --output artifacts/benchmark-baseline.json

python3 tools/locked_benchmark_runner.py aggregate \
  --manifest /secure/locked-corpus-manifest.json \
  --reports /secure/candidate-diagnostics \
  --policy qa/performance-gate-policy.json \
  --protocol-id locked-corpus-cold-v1 \
  --cache-mode cold \
  --report-side candidate \
  --output artifacts/benchmark-candidate.json

python3 tools/performance_quality_gate.py \
  --baseline artifacts/benchmark-baseline.json \
  --candidate artifacts/benchmark-candidate.json \
  --locked-corpus-manifest /secure/locked-corpus-manifest.json \
  --policy qa/performance-gate-policy.json \
  --output artifacts/performance-quality-report.json
```

That checked-in `qa/performance-gate-policy.json` is template-only. A release
comparison instead uses the protected release policy, manifest, and detached
policy-authority receipt through `--release-policy-attestation`; see
`PERFORMANCE_QUALITY_GATE.md` for the protected-environment invocation. The
receipt is verified against a source-pinned authority public key, not a key in
candidate data. Passing a policy or manifest from the candidate artifact cannot
produce a production-ready result.

For every release candidate, make the candidate declaration and externally
attested blinded review part of the aggregate itself. The baseline aggregate
must use `--report-side baseline` and cannot carry candidate review fields.

```bash
python3 tools/locked_benchmark_runner.py aggregate \
  --manifest /secure/locked-corpus-manifest.json \
  --reports /secure/candidate-diagnostics \
  --policy /secure/performance-gate-release-policy.json \
  --protocol-id locked-corpus-cold-v1 \
  --cache-mode cold \
  --report-side candidate \
  --change-classification major \
  --change-id semantic-pipeline-rework \
  --human-perceptual-review /secure/blinded-review.json \
  --output artifacts/benchmark-candidate.json
```

The runner preserves this JSON without inventing reviewer results; the quality
gate validates it. Candidate diagnostics must share a pinned `source_sha256`
and pipeline version; the runner emits that as `candidate_identity`. The review
file must contain the gate's structured ratings plus an
`external-review-attestation-v2` Ed25519 detached signature bound to that
identity, the policy, the corpus, and canonical baseline/candidate benchmark
evidence projections. The projection excludes only the review signature to
avoid a circular hash, so post-review changes to metrics, provenance, or
diagnostic/output hashes invalidate the release. Policy pins the verifier's
public key and its SHA-256; a bare `blinded: true` boolean or arbitrary receipt
hash is not sufficient. Do not include private signing material, names,
comments, lyrics, screenshots, or other private material.

For the manually dispatched GitHub quality-gate workflow, package only the
candidate `benchmark.json` evidence. The workflow downloads it by its exact run
ID from this LightForge repository only, but it obtains the release policy,
locked manifest, and independent detached policy-authority receipt from the
protected `lightforge-release-quality` environment on protected `main`. The
gate resolves the receipt's public verifier key only from reviewed source. A
candidate artifact must never supply the policy, corpus manifest, authority
key, or authority receipt because it could then create a self-signed release
claim.

`aggregate` writes atomically and sorts reports by track, run ID, and
diagnostic digest, so a reordered directory traversal produces byte-equivalent
JSON. It refuses to aggregate when `policy.required_tracks` does not exactly
match the locked manifest or when its local minimum is lower than
`policy.minimum_pairs_per_track`. In release mode it also refuses a policy
whose pinned corpus ID/SHA-256 does not exactly match the manifest, a manifest
without full coverage/golden/annotation evidence, an ambiguous report side, or
a candidate without source identity and review evidence. The aggregate carries
the validated redacted release-corpus diagnostic projection and the suite embeds
the canonical hash of the committed policy before a candidate result is
compared.

The authoritative gate comparability fields come from each run's provenance
and condition:

| Gate comparison | Contract source |
| --- | --- |
| corpus/audio workload | `provenance.workload` |
| analysis configuration, preprocessing, model versions | `provenance.workload` and `provenance.implementation` |
| hardware, runtime, accelerator, seed, thermal profile | `provenance.environment` |
| cold/warm/resume condition | runner-supplied `condition.cache_mode` |

The aggregate additionally exposes a readable `environment` summary with
canonical model/configuration digests. It is not a substitute for per-run
provenance. Source pipeline version is required to be constant within a
baseline or candidate aggregate, but is intentionally not compared across the
two sides: source changes are normally what is under test. Model and analysis
configuration changes remain comparability blockers.

The runner records raw paired runs rather than declaring a quality result.
`performance_quality_gate.py` remains the authoritative paired
baseline-versus-candidate classifier. A `PASS_TARGET` still requires every
required track's paired runtime lower confidence bound to reach the configured
reduction and no critical quality regression or inconclusive critical result.
A real corpus measurement is required before claiming either.

## Canonical GitHub producer

For release evidence, do not upload a hand-built `benchmark.json` from an
arbitrary successful workflow. Dispatch
`.github/workflows/performance-quality-gate.yml` on protected `main` with
the benchmark inputs. Its protected `benchmark` job downloads the exact
diagnostic artifact by run ID, invokes this locked runner with the private
release manifest and policy, and uploads one named `benchmark.json` artifact.

The diagnostic artifact must put contract diagnostics below `reports/`. A
candidate artifact must additionally put its externally attested review at
`human-perceptual-review.json` at the artifact root. Use
`benchmark_report_side=baseline` for baseline aggregation. For a candidate,
use `benchmark_report_side=candidate` and provide its change classification
and change ID; the job fails closed if the review attachment is absent.

The subsequent release comparison resolves each requested benchmark name to
one Actions artifact ID, records the API SHA-256 digest and size in
provenance, and downloads by that ID. Publication re-fetches that run and
artifact ID and rejects a different workflow, run, name, digest, size, source
commit, or protected-main branch. Existing benchmark artifacts from before
this producer are intentionally not release-authoritative; regenerate them
through the canonical protected job.

## Output and privacy boundaries

The aggregate contains only track IDs, opaque hashes, durations already bound
by the diagnostic contract, metrics, and provenance needed for comparison. It
does not retain input filenames or source paths. Do not add audio payloads,
lyrics, credentials, API keys, raw exception messages, or personally
identifying data to manifests or diagnostics; the shared contract rejects
sensitive diagnostic keys.
