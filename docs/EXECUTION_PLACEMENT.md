# Inference execution placement

LightForge no longer assumes that every production model must execute on the
phone. Device, hybrid and remote candidates are all eligible, but none is
admitted by architecture preference alone. The current original-model device
pipeline remains the production baseline until a replacement passes the same
source-bound quality and release controls.

## Decision order

1. Preserve or improve the complete analysis and choreography output contract.
2. Demonstrate the target end-to-end wall-clock reduction on the locked corpus.
3. Keep cancellation, checkpoint recovery and a complete device fallback.
4. Bound private-audio transfer, retention, credentials, request size and cost.
5. Verify Android lifecycle behavior and the final APK through the existing
   production workflow.

Model-only throughput is diagnostic evidence, not the acceptance metric. The
comparison includes decode, transfer, queueing, model startup, inference,
postprocessing, retries and recovery. A remote GPU is not faster if upload or
queue latency makes the full workflow slower.

## Candidate classes

| Placement | Intended use | Mandatory boundary |
| --- | --- | --- |
| Device | CPU, NNAPI, GPU, WebGPU/WebNN or another packaged runtime | No source audio leaves the app; model/runtime identity remains source-bound. |
| Hybrid | Local feature/decode stages plus selected remote heavy stages | Explicit consent for each analysis, resumable local fallback, bounded transfer and deletion policy. |
| Remote | Complete hosted heavy-model execution | Same consent and privacy rules as hybrid, plus complete v8 result provenance and local fallback. |

No API key, bearer token or service credential may be bundled in JavaScript,
the APK, a repository file, diagnostic output or an exported project. Remote
execution must use a server-held credential or a short-lived token obtained
through an authenticated broker. User audio may not be retained for training.

## Admission

`tools/execution_candidate_gate.py` is the final placement-specific admission
check after `tools/performance_quality_gate.py`. It accepts only a strict schema
4 report with `PASS_TARGET` and `production_ready: true`, verifies the external
review binding to the exact candidate benchmark file, and checks every benchmark
run against the declared implementation source, pipeline and model-set digest.
It also requires:

- at least 75% measured total-wall-clock reduction;
- the complete `lightforge-analysis-v8` result contract;
- resumable device fallback that preserves completed work;
- bounded, idempotent requests;
- for transferred audio, per-analysis consent, TLS 1.3, no training use,
  retention of no more than 24 hours, and credentials outside the app payload.

The tool emits a deterministic, digest-bound admission receipt and refuses to
overwrite an existing receipt. A candidate cannot qualify itself by supplying a
local `qualityPassed` flag or an unbound benchmark.

This gate does not publish a release, alter the production engine or authorize
audio transfer. Protected-main verification, Android testing, original signing
identity and package-integrity checks remain separate mandatory controls.
