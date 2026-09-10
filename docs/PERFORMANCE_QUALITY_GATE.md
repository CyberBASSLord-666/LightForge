# Performance quality gate

`tools/performance_quality_gate.py` is the release gate for a measured
baseline-versus-candidate analysis optimization. It is intentionally
fail-closed: a faster median is not evidence when one paired run lost a vocal
accent, changed a model, used a different accelerator, or ran a warm cache.

Run it after the locked corpus runner has produced two reports:

```sh
python3 tools/performance_quality_gate.py \
  --baseline baseline.json \
  --candidate candidate.json \
  --policy qa/performance-gate-policy.json \
  --output quality-gate-report.json
```

## Evidence contract

Both inputs use schema version 3 and contain the same immutable suite identity:

```json
{
  "schema_version": 3,
  "suite": {
    "corpus_id": "licensed-locked-corpus-2026q3",
    "corpus_manifest_sha256": "...",
    "protocol_id": "performance-quality-v3",
    "policy_sha256": "..."
  },
  "runs": [{
    "track_id": "vocal-rock",
    "pair_id": "cold-batch-001",
    "run_id": "candidate-vocal-rock-001",
    "metrics": {"performance": {}, "quality": {}},
    "provenance": {},
    "condition": {"cache_mode": "cold", "pair_order": "baseline-first"}
  }]
}
```

`pair_id` identifies a baseline/candidate benchmark pair for one track.
`run_id` must be unique within an artifact. The default policy requires five
pairs per locked track, exact track-set equality, finite values for every
required metric, and a policy digest created before the reports are collected.
Audio stays outside the repository; the manifest stores only licensed track
identities and hashes.

For every matched pair the gate requires equality of corpus and audio identity,
analysis configuration, preprocessing and model versions, hardware/runtime and
accelerator, random seed, thermal profile, and cache mode. Pipeline source
version is intentionally allowed to differ because it is the candidate under
test.

## Classification

For each metric the paired effect is normalized so positive means candidate
improvement. A deterministic SHA-seeded paired percentile bootstrap computes a
99% confidence interval for the mean effect. The fixed policy tolerance is
applied before results are examined:

- `improved`: the lower confidence bound is greater than zero.
- `statistically_equivalent`: the entire interval is inside the committed
  equivalence interval.
- `regressed`: the interval is worse than tolerance, or any pair crosses its
  committed hard-regression floor.
- `inconclusive`: insufficient evidence for either result.

Critical metrics may only be `improved` or `statistically_equivalent`.
`regressed` and `inconclusive` both block release. The built-in critical set
covers vocal alignment, beat/downbeat accuracy, bass events, structural recall,
high-salience coverage, perceptual synchronization, actuator feasibility, and
high-salience collision loss.

`PASS_TARGET` additionally requires the lower 99% confidence bound of the
paired runtime reduction to meet 75% for **each** required track. `PASS_PARTIAL`
means quality evidence passed but the speed target was not proven; it is not
production-ready. `FAIL` means evidence or quality is invalid. The committed
policy begins with `__configure_locked_corpus__`, so it fails until the licensed
reference corpus is configured in a reviewed commit.

## Release verification coverage

The production verification workflow runs `npm test`, which invokes
`tools/verify_v2.py`. In addition to the engine, worker, telemetry, and
semantic-timeline Node suites, that runner explicitly executes the four
hyphenated Python suites that normal `unittest` discovery cannot import:

- `tests/performance-quality-gate.test.py`
- `tests/analysis-benchmark-contract.test.py`
- `tests/locked-benchmark-runner.test.py`
- `tests/differential-analysis.test.py`

Their combined output is retained as
`qa/release-<version>/quality-tool-tests.log`, and the verification receipt
lists the exact selected suites. This is a contract/self-test check only; it
does not turn the redacted corpus template into release evidence or claim a
runtime improvement. A real production performance claim still requires the
locked corpus, paired reports, and the fail-closed gate above.
