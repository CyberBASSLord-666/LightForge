# Cold-session diagnostic — September 24, 2026

The next justified experiment is a persistent GPU worker that reuses verified
models and qualified sessions across passages. The retained cold traces show
substantial setup outside model calls after CUDA arithmetic is enabled. They do
not quantify the savings from persistence or prove that device transfers are the
remaining bottleneck.

This is a read-only analysis of the two complete archives retained at commit
`d1c6a853fb5ee6df7cb4fa6f751988c66b5158a8`. Both archives were reconstructed
from every checked part, then passed their unchanged independent verifiers in
new scratch directories. No inference or application modification was performed.
Exact archive, receipt and per-trace bindings are in [analysis.json](analysis.json);
the new verifier-run provenance is in [verification-provenance.json](verification-provenance.json).

## What the original cold profiles contain

Values below are seconds, rounded to three decimals for display. JSON retains
integer microseconds and nanoseconds. Each row is one profiled passage in a fresh
JVM, not a repeated timing estimate. All control runs remain diagnostic only.

| GAME control | Passage wall | ORT model loading | ORT session initialization | ORT model_run |
| --- | ---: | ---: | ---: | ---: |
| CPU ALL | 31.509 | 0.390 | 2.923 | 26.184 |
| CPU BASIC | 36.044 | 0.483 | 3.294 | 29.739 |
| GPU-package CPU BASIC | 35.622 | 0.396 | 4.030 | 29.191 |
| Deterministic CUDA BASIC | 10.952 | 0.361 | 3.216 | 1.468 |

GAME has five original graphs and twelve model calls, including all eight
segmenter steps. CUDA's segmenter model calls total 0.900 seconds, encoder 0.442
and estimator 0.124; the two conversion graphs remain on CPU. The Java capture
timer totals 1.471 seconds around model calls, consistent with the 1.468 seconds
of ORT host spans. The larger passage wall also includes verification, loading,
native runtime/provider setup, capture and retirement. Its remaining difference
is not a measured pool of removable overhead.

| Deux control | Passage wall | ORT model loading | ORT session initialization | ORT model_run |
| --- | ---: | ---: | ---: | ---: |
| CPU ALL | 135.372 | 0.662 | 1.759 | 125.199 |
| CPU BASIC | 138.522 | 0.663 | 1.662 | 128.730 |
| GPU-package CPU BASIC | 139.871 | 0.656 | 1.643 | 130.668 |
| CUDA BASIC | 18.618 | 0.667 | 1.828 | 6.065 |

Deux has 27 original graphs and all 335 model calls. Its separate Java stage
profile places 3.267 seconds in cache preflight, 5.719 in model initialization,
6.378 in inference, 0.285 in packing, 0.486 in scattering and 0.945 in decode plus
output handling for the CUDA pass. Java model initialization includes preparation
and session construction around ORT; it is **not** additional to the ORT columns.
Per-graph Java session-construction fields sum to 5.700 seconds after millisecond
truncation. This is materially broader than the 1.828 seconds named
`session_initialization` inside ORT.

## Why session reuse comes first

The frozen GAME source verifies all five files and creates/retires all five
sessions for each prediction. The frozen Deux source opens and closes each graph
session during every passage. Its engine already retains a verified-file set
and working buffers across predictions, so the cold preflight cost must not be
assumed to recur in an existing reused engine. The retained benchmark creates a
fresh engine; a worker experiment must distinguish engine reuse from session
reuse instead of assigning both effects to a single change.

An isolated research worker should therefore preserve the original graphs,
Float32 precision, batches, seeds, context, step counts, provider choices and
deterministic GAME setting while testing these configurations in order:

1. A long-lived process using unchanged per-passage session lifetimes, to expose
   process/engine reuse separately.
2. The same worker with bounded session retention, with explicit GPU-memory,
   cancellation, failure recovery and resource-retirement checks. Retaining all
   Deux sessions simultaneously is not yet shown to fit the T4 memory budget.
3. Only after those costs are measured, a separately qualified device-buffer
   experiment if transfer/synchronization evidence warrants it.

The worker must verify source/model/runtime identities before accepting work,
keep loaded artifacts immutable, and retain end-of-run identity checks. Reuse is
not a reason to remove integrity checks. Compare original and proposed outputs
within each provider before interpreting any new uninstrumented cold/warm timing.
Keep CUDA/CPU musical qualification and complete end-to-end timing as separate,
still-open gates.

## What cannot be inferred about device residency

GAME has 18 explicit `MemcpyFromHost` and 18 `MemcpyToHost` events, whose host
durations total 0.005548 seconds. Deux has 312 explicit `MemcpyFromHost` events
totaling 0.004270 seconds and no explicit `MemcpyToHost` nodes in these traces.
Those small numbers do not measure total transfer cost: Deux binds host input
and output buffers in Java, so transfers and synchronization can occur outside
the listed graph nodes.

For example, Deux CUDA's `model_run` spans sum to 6.065 seconds while nested
`SequentialExecutor::Execute` spans sum to 1.548. The 4.517-second difference is
an observation about instrumentation boundaries, not proof of copy time or
recoverable GPU time. A device timeline or explicit synchronized boundary
measurement would be needed to attribute it. Host kernel-event rankings alone
also cannot identify the GPU's arithmetic bottleneck.

Every graph trace has its own timestamp origin. We sum matching named durations
as diagnostic counters; we do not merge them into a global critical path.
`model_run`, executor and kernel events nest. Java timers enclose ORT timers.
Adding those levels would double-count work. Instrumented and single-pass cold
observations do not establish a steady-state ratio, a 75% complete-analysis
reduction, or general quality equivalence.

## Reproduce without inference

Reconstruct the adjacent `game-deterministic` and `deux-t4` archives into a new
directory with their existing `reconstruct_archive.py` scripts. Run both existing
`verify_evidence.py` scripts against their manifest sizes/digests, using separate
new verification destinations. Then:

```sh
python3 analyze_archives.py --archive-directory /path/to/reconstructed --output /path/to/new-analysis.json
```

Name the input ZIPs `game-deterministic.zip` and `deux-t4.zip`. The analyzer
refuses an existing output, checks exact archive and primary-receipt pins, checks
all member CRCs, verifies every consumed trace/profile against its receipt, and
recomputes all named host totals from the original events. The result is
descriptive evidence only; all performance and quality approval flags remain false.
