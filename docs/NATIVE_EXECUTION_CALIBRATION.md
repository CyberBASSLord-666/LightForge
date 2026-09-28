# Native separation scheduling

## Published 2.4.1 and current unreleased work

The published 2.4.1 release qualified its final source on the host with **32.6%
lower median complete-passage time** and byte-identical outputs. That historical
[proof](../research/inference-2.4.1/DEUX_PARALLEL_B1.md) remains unchanged. Its
device policy measured warmed executions of the first temporal graph, then
reused the chosen schedule across later layers and passages. It did not qualify
complete cold-session passages or sustained phone behavior.

The subsequent phone run was slower. The [device regression record](../research/inference-device-regression-20260928/README.md)
separates the observed timings from uncontrolled phone conditions and describes
the **unreleased** correction. Neither the earlier host proof nor the correction's
implementation establishes improved phone or whole-song performance. Changed
sources require fresh evidence before another production release.

## Preserved execution

All 27 original Float32 graphs, trained weights, 60 bands, 1,301 frames and the
complete 13-second context remain intact. The reference uses four-band calls,
up to four intra-operator threads, sequential graph execution and disabled
spinning. Parallel temporal execution uses four or eight independent one-band
calls, private pinned buffers, and one intra-operator thread per call. A full
parallel passage has 875 graph calls; the reference has 335. Neither count means
less model work. Front, frequency and mask-head scheduling remain at the reference
configuration in the correction.

Only one graph is resident at a time. Completed worker slots receive the next
independent band; the coordinator alone packs inputs and scatters outputs. Every
worker retires before tensors, sessions, run options, crash lease or inference
gate are released. Cancellation and output publication keep that ownership order.

## Complete-passage admission

A bounded cold-graph screen can nominate one four- or eight-worker candidate;
it cannot authorize accelerated production. New qualification requires three
alternating baseline/candidate pairs at useful native-passage ordinals **0, 4
and 8**. Each arm creates fresh original sessions for all 27 graphs and performs
the complete read, transform, inference and two-stem reconstruction with matching
observer settings. Shared model-cache preflight/buffer preparation precede the
pair. Output hashing follows the timed attempts, and only the baseline result
is published for a paired passage.

Both complete outputs must be finite and byte-identical. Every pair must reduce
candidate time by at least 5%, and the three-pair median by at least 15%. Until
qualification succeeds, ordinary passages use the baseline. A mismatch, failed
comparison or unavailable memory keeps the baseline for the rest of that job.
Core count and current native memory headroom remain admission constraints;
Java heap free space is not a native-memory signal.

Screening, candidate replays, output checks and interrupted probes consume a
**360-second extra-work budget**. The screen has its own 60-second checkpoint.
These limits are checked at existing safe native boundaries; an in-flight native
operation can overrun a checkpoint before retiring. They are not promises of
instantaneous kernel interruption. Necessary baseline work is not abandoned
when an optional probe exhausts its budget.

A conservative payback projection includes remaining qualification, later
rechecks and a 10% margin. It is labeled `projected-not-measured`: a paired rate
does not establish whole-job net savings. The separator first scans verified
checkpoints and non-silent input with one passage live at a time and a bounded
passage bitmap. It passes a checked remaining-useful count; unknown or short
work cannot finance speculative qualification. Normal processing rechecks the
input and checkpoint, so the scan never substitutes for recovery validation.

## Rechecks, persistence and evidence

A qualified candidate receives an eight-passage lease; a successful renewal
receives twelve. Two of the last three ordinary candidate passages exceeding
125% of the paired candidate reference trigger an earlier comparison. That
observation requests a recheck; it does not identify thermal throttling or prove
a regression against a contemporaneous baseline. An unaffordable or failed
recheck returns the job to baseline.

The new `passage-policy-v1.bin` identity binds the original model, runtime,
complete-passage scheduler, OS/device identity digest and processor count.
The old warm-graph decision file cannot authorize this path. Even a valid saved
qualification requires a fresh complete pair before another job uses it.
Invalid or incomplete cached evidence cannot enable acceleration.

[Durable diagnostics](DIAGNOSTIC_EVIDENCE.md) retain the raw qualification/recheck
pairs, output digest, decision, extra-work cost and projected payback. Mixed
temporal session counts supplement the last configuration. Probe observations
stay separate from production graph totals; [profiling scopes](NATIVE_INFERENCE_PROFILING.md)
prevent overlapping worker durations from masquerading as elapsed passage time.
Runtime 1.25.1, model assets, precision, context and output length are unchanged.
Host correctness and scheduling tests do not substitute for fresh performance
qualification or controlled physical-device observations.
