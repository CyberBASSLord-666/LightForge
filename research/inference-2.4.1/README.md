# Native inference investigation

The owner requires a real, noticeable and repeatable neural-inference improvement
before a new release is built. Instrumentation or speculative adaptive scheduling
alone does not meet that requirement. The final production implementation now
passes that host prerequisite: 32.6% lower median passage time, 28–36% lower in
every measured pair, exact complete outputs, and all resource guards satisfied.
Fresh release verification and original signing remain required. The 75%
objective remains aspirational and is not claimed as achieved.

## Evidence so far

| Experiment | Measured result | Decision |
| --- | --- | --- |
| Six threads, dynamic blocks, temporal/frequency graphs | Three paired full-passage rounds: 6.0% lower median wall time; individual reductions −1.2%, 8.7%, 17.4%; median process CPU increased 13.8% | Insufficient consistency and magnitude; no unconditional production default or release claim |
| Same scheduling on additional Falcon/Stella inputs | Complete finite outputs match the reference bytes | Numerical coverage only; not a performance qualification |
| Eight one-band workers, production wave scheduler | 23.3% lower median full-passage time; individual reductions 25.8%, 1.17%, 27.5%; all complete outputs byte-identical | Failed the 5% minimum for every pair; release held |
| Continuous temporal refill, controlled eight-CPU prototype | Better temporal utilization in both controlled pairs; total passage times mixed against the wave scheduler | Mechanism selected for production qualification; no admitted overall speed claim |
| Continuous refill, final production source, eight-CPU control | About 32% lower median full-passage time; all pairs and outputs passed, but one CPU-throttle ratio reached 5.361%, exceeding the 5% resource ceiling | Failed resource qualification; preserve result and reserve one CPU of quota in the next controlled protocol |
| Continuous refill, final production source, reserved CPU quota | 65.277→44.010 seconds median; paired reductions 28.07%, 28.81%, 36.16%; all eight complete outputs byte-identical; maximum throttle ratio 0.087%, no memory-pressure events | Passed unchanged 15% median / 5% each / 5% throttle limits; host evidence only |
| GAME dynamic scheduling | Raw tensors and unrounded note values changed | Rejected |
| GAME arena and memory patterns | Exact tested outputs, inconsistent time improvement | Rejected |
| Larger attention query tiles | No useful gain in bounded graph screening | Rejected |
| Newer runtime | Experiment blocked after an unapproved telemetry connection | Excluded; pinned 1.25.1 retained |

The exploratory separator screen includes a large single-run improvement that
was not reproduced consistently. Use the paired receipt, not that screening
percentage, when assessing the scheduling candidate. `passed` in the numerical
comparison means byte-identical complete outputs; it does not mean performance
admission.

## Qualification scope

- Continuously refill four or eight independent temporal worker slots, preserving
  all 60 bands and complete context through the original shared CPU session.
  The 875-call geometry remains explicit alongside the 335-call reference.
- Qualify the final production source using equal, observed child CPU affinity
  within the host quota. Keep the failed wave attempt and mixed prototype runs.
- Verify full outputs, memory admission, cancellation, and native retirement on
  the final runner. Operator-level timing cannot substitute for a complete
  passage comparison.

The [parallel execution investigation](DEUX_PARALLEL_B1.md) records the original
prototype, failed production attempt, and subsequent scheduling work.

A qualifying implementation needs repeated complete-passage timing, complete
finite output parity, independent input coverage, bounded memory, and safe
cancellation and native retirement. Cold setup, cached execution and sustained
behavior must be distinguished. Host results cannot be relabeled as physical
Android or whole-song results.

The passing prerequisite does not itself constitute a release. Fresh
production/Android verification and original signing remain mandatory before
publication.

Detailed [pinned-runtime attention research](attention/SUMMARY.md) retains compact
graph-only receipts, rejected candidates, and [reproduction/source provenance](attention/README.md).
The exact tiled-MHA screen is not a full-passage or production qualification.
