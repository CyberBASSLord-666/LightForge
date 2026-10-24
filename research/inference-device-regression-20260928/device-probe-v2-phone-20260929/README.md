# Companion v2 phone attempts — September 29, 2026 UTC

Neither attempt establishes phone acceleration or qualifies a production release.
Run01 provides complete evidence of clean thermal cancellation. Run02 shows
baseline fallback after a memory-pressure screening abort, followed by a cancelled
run; only part of its exported receipt was retrieved. Its cancellation reason is
unknown from the retained evidence.

These attempts ran the separate development APK with SHA-256
`79dba57cc55d0fc61e42aa245f0f94c7a1d826aa184bb6be08026ff931712429`.
The [artifact archive](../device-probe-v2-79dba57cc55d/README.md) binds it to source
receipt `b9b5991ab8746e96ef28675f23d6309ce5f985003df4d6f12ee4d5360d52d83b`
and the source snapshot committed in
`6a91949a060f7bb8543266242ca01f4d2904c069`. Later memory-admission changes require
their own validation. These phone attempts cannot validate those newer sources.

## Run01: complete export, clean thermal cancellation

The [raw receipt](run01-thermal-cancelled.raw.json) is 37,629 bytes, SHA-256
`91e2384e9347a7b5dc58d111e05c8cc7311d4470ca19d565e2dde6b1c665b29e`.
[Capture metadata](run01-capture.json) records contiguous retrieval of all 385
numbered lines and agreement with the exported file's byte count.

| Observation | Result |
| --- | --- |
| Completed passages / paired comparisons | 0 / 0 |
| Elapsed time | 20.099 s |
| Cancellation reason | `thermal-severe` |
| Thermal status at boundaries | 0 → 3 |
| Battery temperature at boundaries | 32.4 → 33.1 °C |
| Screening cost charged | 5.299625675 s |
| Selected useful work before cancellation | Baseline; 105 native calls |
| Last graph | `block-04-time` session opened; zero calls executed |
| Coordinator finished / engine close returned | Both true |
| Native cleanup / temporary-cache removal | Both true |

The front graph and blocks 00–03 completed before cancellation. No full baseline
output or candidate comparison completed. Four workers were nominated, but that
nomination alone is not evidence that the candidate was admitted or faster.

The [retained-APK analysis](run01-thermal-cancelled.retained-analysis.json) passed
receipt integrity and current-source binding **when produced against the
6a91949a source snapshot, before later memory-admission edits**. It has no
integrity errors and reports the expected severe-thermal boundary warnings. Its
SHA-256 is `49d5189c2ca8158e59070275538e168ee12d50efb97e119150f225ab0586c6bc`.

That recovery verification hashes the exact retained APK and every permitted
member, including DEX, native libraries, fixture, notices and source receipt.
Original compiled-class/JAR checks, signature validity, alignment and manifest
semantics remain explicitly historical audit checks, not newly performed checks.
The lost temporary build directory was not reconstructed. A future invocation
with `--require-current-source` must fail if the reviewed source pins have changed.

## Run02: partial export, baseline fallback

The [capture envelope](run02-partial-export.capture.json) preserves the exact
successful connector responses for export lines **1–200 and 401–600**. The
reported full export has 1,115 lines; lines **201–400 and 601–1115 are missing**.
Later file-read, screen-state and storage-list operations returned connector
`Internal error` responses. No complete raw report has been synthesized.

The [selected observations](run02-partial-observations.json) retain short fields,
their original line numbers and explicit missing values. They are a partial
evidence summary, not the output of the complete-receipt integrity analyzer.
The capture envelope's hash does not identify the complete exported JSON.

Captured headers report `terminal=true` and `outcome=cancelled`. The separate
[UI observations](ui-observations.json) show **“Diagnostic cancelled. 6/35
passages. Native cleanup confirmed: true”** at **01:33:02.913 UTC**. Earlier UI
observations show passage seven still running at 01:32:17.054 UTC. These polling
timestamps do not establish the exact cancellation time or whole-run duration.
The final JSON cleanup fields and cancellation reason are in missing pages.

| Captured passage | Prediction wall time | Available memory before → after | Thermal status before → after | Battery temperature before → after |
| --- | ---: | --- | --- | --- |
| Ordinal 0 | 52.672343574 s | 2.633 → 2.991 GB | 0 → 2 | 32.5 → 33.7 °C |
| Ordinal 1 | 53.103577532 s | 2.991 GB → unavailable | 2 → unavailable | 33.7 °C → unavailable |
| Unnumbered fragment preceding ordinal 4 | 55.172949666 s | unavailable → 3.303 GB | unavailable → 2 | unavailable → 36.1 °C |
| Ordinal 4 | 58.864255186 s | 3.303 → 3.350 GB | 2 → 2 | 36.1 °C → unavailable |

Memory values in this table use decimal GB and are rounded; the sidecar preserves
the exact byte counts. The unnumbered fragment's ordinal and start sample are
absent, so neither is inferred. The after-boundary for ordinal 4 stops at
`plugged=0`; its battery temperature and peak RSS were not captured.

Every captured profile header reports the original baseline schedule: **335
calls, 27 sessions, 12 baseline temporal sessions and 12 baseline frequency
sessions, with zero parallel worker sessions**. The visible policy snapshots
report `state=baseline`, `workers=0`, `reason=memory-pressure`, zero qualification
pairs and zero projected savings. Ordinal 0 records **2.212013697 s** of charged
screening cost. This does not establish which transient memory observation
triggered the abort. Boundary `lowMemory=false` and rising available-memory
snapshots do not reconstruct the admission-time headroom.

The four retained output summaries each report 4,586,400 finite Float32-output
bytes. They are different fixture starts or an unassigned fragment, not matched
baseline/candidate comparisons. The full repeated-input consistency check cannot
be completed from these fragments. No phone speedup or sustained candidate
execution is demonstrated.

## Preserved limits

- Run02's full-report hash, byte count, embedded source receipt, final memory and
  thermal state, elapsed time, cancellation reason, and final JSON cleanup/cache
  fields remain unavailable. Run01's thermal reason must not be copied to run02.
- The UI confirms six completed passages and native cleanup; this does not fill
  in the missing JSON fields or prove temporary-cache removal for run02.
- All memory and thermal measurements here are boundary observations. Battery
  temperature is not CPU temperature, and no causal claim about throttling follows
  from these samples alone.
- No full-job baseline counterfactual, sustained accelerated run, production
  foreground-service validation or production release approval is present.

[evidence-inventory.json](evidence-inventory.json) identifies the exact retained
files. Preserve the partial capture even if complete retrieval becomes possible;
save later complete exports separately and verify their identity before analysis.
