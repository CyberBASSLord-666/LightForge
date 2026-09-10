# Resource diagnostics contract

`web/analysis/resource-diagnostics.js` provides the versioned,
measurement-only resource evidence used by the offline analyzer. It never
changes decoder settings, model choice, event selection, choreography, or FSEQ
frames. The contract is deliberately conservative: an unavailable measurement
is represented as unavailable, never as zero.

The worker attaches one `analysis-stage-resources` record to each stage profile.
`MusicAnalyzer` aggregates validated stage records into
`engine.resourceDiagnostics` (`analysis-pipeline-resources`). The real-browser
receipt projects it at:

```text
analysis.performance.resources.pipeline
```

The projection is source-bound with the analyzer, telemetry, scheduler and
resource-contract assets. It is observation only; it has no runtime threshold,
baseline comparison, or release verdict.

## Recorded domains

| Domain | Evidence | Important limitation |
| --- | --- | --- |
| Wall time | Monotonic per-stage and pipeline wall clocks | Wall time is not CPU time. |
| Scheduler | Measured admission wait and coordination mode at pipeline scope | Stage records mark scheduler unavailable because admission happens before workers start. |
| Cache | Exact observed hit, miss, restore, invalidation, write and corrupt-event counts | Counts describe telemetry calls, not a guessed cache-hit ratio. |
| I/O | Actual OPFS checkpoint/feature-store bytes read and written when those calls are instrumented | The status is `partial`; decoder, model-fetch and stem-cache traffic are not represented as a total. |
| JS heap | `performance.memory` before, after, peak and limit only when the browser exposes a valid before/after pair | This non-standard API is commonly unavailable outside Chromium. |
| Allocation/copy | Byte and operation counters only for explicitly instrumented buffers | It is never an estimate of the JavaScript allocator. |
| CPU | Exposed logical-core count and device-memory class | CPU utilisation remains explicitly unavailable: web APIs do not expose it reliably. |
| Accelerator | WebGPU API exposure only | API exposure is not an adapter selection, model provider, GPU utilisation or acceleration claim. |

Every unavailable field carries a reason and `null` measurement values. A
privacy wrapper or hardened browser getter that throws is recorded as an
explicit `*-observed-error` reason rather than being misreported as a zero or
allowed to interrupt analysis. The legacy stage-profile `runtime.observations`
map similarly reports `available`, `unavailable`, or `observed-error` for its
browser probes while retaining the existing nullable numeric fields. The
contract rejects malformed, mixed-status, non-finite, negative, ambiguous, or
mis-keyed pipeline stage records. It also rejects a partial I/O record without
an explicit coverage label and limitation.

## Instrumentation API

The telemetry wrapper owns the recorder for the current stage. Safe optional
calls are:

```js
telemetry.cache('hit');
telemetry.io('read', exactByteCount, 'opfs-analysis-store');
telemetry.allocation(exactByteCount, operationCount);
telemetry.copy(exactByteCount, operationCount);
```

Only exact, known transfer sizes belong in `io`. Do not serialize audio,
lyrics, paths, cache keys, model URLs, identifiers, or response bodies into
the record. The current OPFS work store receives the recorder explicitly, so
resource observation cannot change checkpoint atomicity, cache identity, or
invalidation semantics.

## Benchmark-gate relationship

The locked performance/quality gate remains the authority for paired,
comparable baseline/candidate results. Resource diagnostics can explain a
measured run and reveal cache or wait effects, but they cannot establish the
75% target or override any music-quality regression. A benchmark adapter may
copy finite resource fields into a diagnostic stage only when its corpus,
hardware, runtime, cache mode and provenance have already passed the existing
contract.

## Compatibility and failure behavior

Historical analyzer records without resource evidence project as
`resources.status = "unavailable"`; this preserves read compatibility without
pretending they were measured. A current real-browser proof requires resource
evidence and verifies all four production stages. Invalid new evidence blocks
receipt publication rather than being silently normalized.
