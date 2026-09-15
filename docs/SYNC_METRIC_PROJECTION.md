# Project observed realization timing

`tools/project_sync_metrics.py` reads the original `perceptualValidation`
sidecar emitted by the existing show compiler. It projects up to 111 fields
from the compiled release metric contract: five absolute-error percentiles
for eleven event classes, separately for command and perceptual timing, plus
the aggregate perceptual p95. It does not run a detector or establish musical
accuracy against corpus annotations.

First capture the actual application with
[`qa/locked-benchmark/capture-app.cjs`](../qa/locked-benchmark/CAPTURE.md).
Use its verbatim `perceptual-validation.json` sidecar and the SHA-256 recorded
in `capture.json`'s artifact inventory. Then run:

```bash
python3 tools/project_sync_metrics.py \
  --report /private/capture/perceptual-validation.json \
  --expected-sha256 ACTUAL_SIDECAR_SHA256 \
  --source-commit ACTUAL_CANDIDATE_COMMIT \
  --run-id SAME_BASELINE_CANDIDATE_PAIR_ID \
  --perceptual-basis predicted \
  --output /private/capture/new-sync-projection.json
```

The source commit and pair identity are declarations that release orchestration
must independently bind to the verified candidate and original capture. The
required digest binds the exact input bytes; it does not authenticate their
producer. Retain the capture receipt and its artifact inventory with the
projection. Use the same stable pair ID for corresponding baseline/candidate
attempts, stored separately.

`--perceptual-basis` is mandatory. `predicted` selects the producer's
`predictedPerceptual` distributions and preserves their `estimated` state in
every metric's provenance. `measured` selects only `perceptual` distributions;
absent measurements stay absent. Predictions never replace measurements.
The current release contract permits model-predicted perceptual timing as a
separate domain; physical phone/Tesla observations remain optional.

The original event inventory must be complete and valid. Truncated events,
omitted classes, inconsistent counts, invalid percentiles, unsupported producer
bounds, duplicate JSON keys and digest mismatches fail closed. A class with no
observed timing pairs remains in `unobserved_metrics`, with no numeric value.
An unavailable domain is neither zero nor an annotation-authorized N/A.

The output records its exact report digest, selected basis, matched-pair counts
and each emitted metric's state. It always states `release_qualified: false`,
`physical_validation_established: false`, `detector_accuracy_established: false`
and `human_review_established: false`. Even a complete 111-field projection
does not establish the remaining timing, resource or quality requirements.
Existing output files are never overwritten.

Use [`PROCESS_RESOURCE_COLLECTION.md`](PROCESS_RESOURCE_COLLECTION.md) for
external workload counters. Its whole-command window includes capture setup
and teardown, so it must not be substituted for analyzer-only time. Neither
collector assembles a complete production diagnostic or passes the quality
gate by itself. Approved annotations, stage instrumentation, metric adapters,
controlled paired executions, output comparisons and authenticated human review
remain necessary.

Verification: `python3 -m unittest discover -s tests -p
'test_sync_metric_projection.py'`. These tests execute the unchanged JavaScript
producer on explicit unit fixtures, including incomplete and absent evidence;
the fixtures are not a qualification corpus.
