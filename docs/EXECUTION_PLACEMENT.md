# Inference execution placement

Device, hybrid and remote execution are all research options. This does **not**
mean LightForge currently has a remote execution service or a verified accelerated
replacement. The current original-model device pipeline remains the production
baseline. A replacement still needs applicable source-bound quality, production,
Android and release verification.

## Decision order

1. Preserve or improve the complete analysis and choreography output contract.
2. Measure end-to-end wall-clock change; the 75% reduction goal is not evidence
   of an achieved speedup or a new prerequisite for every publication.
3. Evaluate cancellation, checkpoint recovery, failures and fallback tradeoffs.
   A complete on-device fallback is an option, not a fixed architecture rule.
4. Define private-audio transfer, retention, credentials, request-size and cost
   controls before operating a service. Research authorization is not permission
   to upload private audio or incur unbounded service costs.
5. Verify Android lifecycle behavior and the final APK through the existing
   production workflow.

Model-only throughput is diagnostic evidence, not the acceptance metric. The
comparison includes decode, transfer, queueing, model startup, inference,
postprocessing, retries and recovery. A remote GPU is not faster if upload or
queue latency makes the full workflow slower.

## Candidate classes

| Placement | Research scope | Questions to verify |
| --- | --- | --- |
| Device | CPU, NNAPI, GPU, WebGPU/WebNN or another packaged runtime | Hardware support, memory use, output equivalence and runtime/model identity. |
| Hybrid | Local feature/decode stages plus selected remote heavy stages | Transfer latency, consent, service identity, failure recovery and cost. |
| Remote | Hosted heavy-model execution | Full-pipeline latency, quality, result provenance, privacy, availability and cost. |

No API key, bearer token or service credential may be bundled in JavaScript,
the APK, a repository file, diagnostic output or an exported project. Remote
execution needs an approved credential mechanism and destination-specific audio
consent. Do not infer consent, retention permission or training permission from
a candidate descriptor. Never include private audio or credentials in lint inputs.

## Development-only evidence lint

Despite its historical filename, `tools/execution_candidate_gate.py` is **not a
release admission gate**. No protected production or publication workflow invokes
it. It checks the internal consistency of caller-supplied JSON declarations:

- a `lightforge.execution-candidate.v1` descriptor;
- a schema 4 candidate benchmark whose run-level implementation source, pipeline
  version and model-set declarations match the descriptor;
- a schema 4 quality report whose declared candidate-benchmark digest matches
  that benchmark's canonical evidence projection.

The model-set digest is SHA-256 of sorted, compact UTF-8 JSON plus a newline.
The candidate-benchmark evidence digest follows `performance_quality_gate.py`:
sorted, compact UTF-8 JSON, excluding only
`human_perceptual_review.attestation`, with no trailing newline. File digests
also record the exact input bytes. These hashes detect mismatches; they do not
authenticate the contents or prove that an implementation, model or measurement
exists. The parser rejects duplicate object keys, NaN, Infinity and overflowing
JSON numbers, including those in otherwise unused fields.

```sh
python3 tools/execution_candidate_gate.py \
  --candidate candidate.json \
  --candidate-benchmark candidate-benchmark.json \
  --quality-report quality-report.json \
  --output execution-evidence-lint.json
```

Successful output uses schema `lightforge.execution-evidence-lint.v1` and status
`LINT_PASS`, with `releaseAuthorized: false`, `authorityVerified: false` and
`evidenceTrust: "caller-supplied-unverified"`. Runtime summaries appear only under
`performanceDeclarations`, with `declared` field prefixes. Unmeasured summaries
remain null. Failed syntax, type or binding checks produce `LINT_FAIL` and a
nonzero exit status. An existing output is never overwritten.

Even a fabricated `PASS_TARGET`, `production_ready: true` report with a matching
digest and `externally_attested: true` cannot grant release authorization here.
The linter neither recomputes `performance_quality_gate.py` nor verifies its
signatures, policy, corpus, review authority or claimed results. Test fixtures
with performance percentages are synthetic parser/binding tests, not measured
speedups. Failed or below-target quality declarations may pass this **lint**;
that does not make the candidate acceptable for production.

No threshold, fallback, TLS-version or retention policy is invented by this tool.
Its privacy and operation fields are declarations, not evidence that consent,
transport protection, retention, request bounds or retry behavior are enforced.
Approved policy and implementation review must decide those requirements before
deployment. Protected-main verification, Android testing, original signing
identity and package-integrity controls remain unchanged; this linter adds no
publication prerequisite and satisfies none of those controls.
