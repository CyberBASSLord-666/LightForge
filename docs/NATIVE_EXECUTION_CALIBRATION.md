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
calls, private pinned buffers, and one intra-operator thread per call. The same
candidate workers now execute frequency graphs in batches of 16 independent
frames instead of the reference batch of 128. All 1,301 frames are evaluated:
each frequency layer has 81 full batches and one final five-frame batch. This
does not shorten the temporal context or remove any model computation.

The combined candidate has 1,727 graph calls per complete passage: 720 temporal,
984 frequency, 22 mask-head calls and one front call. The reference remains at 335 calls;
the earlier temporal-only candidate had 875. More calls describe different
batching, not less model work. Front and mask-head scheduling remain at the
reference configuration. Frequency diagnostics identify the companion geometry
as `cpu-i1-j1-d0-sequential-w4-b16` or `cpu-i1-j1-d0-sequential-w8-b16`.

Only one graph is resident at a time. Completed worker slots receive the next
independent band; the coordinator alone packs inputs and scatters outputs. Every
worker retires before tensors, sessions, run options, crash lease or inference
gate are released. Cancellation and output publication keep that ownership order.
A native `Run` rejection is classified as cancellation only when the caller's
cancellation check confirms it; the original ORT cause is retained. Annotated
native failures and resource-close failures remain errors, not optional probe
failures. The baseline JNI test requires an observed native owner, active run
options, exclusive gate ownership, clean retirement and exact full recovery.

## Complete-passage admission

A bounded cold temporal-graph screen can nominate one four- or eight-worker
candidate; it cannot authorize accelerated production or establish frequency
performance. Complete-passage pairs qualify the combined temporal and frequency
configuration. Host frequency-graph observations do not establish improved phone
performance. New qualification requires three
alternating baseline/candidate pairs at useful native-passage ordinals **0, 1
and 2** (baseline first, candidate first, baseline first). Each arm creates fresh
original sessions for all 27 graphs and performs
the complete read, transform, inference and two-stem reconstruction with matching
observer settings. Shared model-cache preparation precedes both nomination and
pair timers: inventory, checksum and storage checks finish first, then every
missing graph is extracted and verified. Its cost belongs to common preflight;
neither timed arm pays first-use extraction, and subsequent graph preparation
only resolves verified cache files. Buffer preparation is also shared.
Output hashing follows the timed attempts, and only the baseline result
is published for a paired passage.

Both complete outputs must be finite and byte-identical. Every pair must reduce
candidate time by at least 5%, and the three-pair median by at least 15%. Until
qualification succeeds, ordinary passages use the baseline. A mismatch, failed
comparison or unavailable memory keeps the baseline for the rest of that job.
Core count and current native memory headroom remain admission constraints;
Java heap free space is not a native-memory signal.

Screening reuses the existing activation buffer. Before each temporal trial it
recomputes the original front graph from the unchanged spectrum, avoiding a
79,933,440-byte activation copy. That restoration is outside the cold temporal
trial timer and inside the total screening budget. Memory is checked before and
after restoration. An ineligible screening option is skipped; it cannot discard
an independently exact, faster option that still meets a fresh final memory
check. A runtime failure, cancellation, budget abort or retirement failure
discards the nomination. The memory reserves and full-passage qualification
requirements are unchanged.

The [version 2 phone attempts](../research/inference-device-regression-20260928/device-probe-v2-phone-20260929/README.md)
precede this screening correction and do not validate it. They have not
established a phone speedup or removed the production release hold.

Screening, candidate replays, output checks and interrupted probes consume a
**360-second extra-work budget**. The screen has its own 60-second checkpoint.
These limits are checked at existing safe native boundaries; an in-flight native
operation can overrun a checkpoint before retiring. They are not promises of
instantaneous kernel interruption. Necessary baseline work is not abandoned
when an optional probe exhausts its budget.

A conservative payback projection includes remaining qualification, a fresh
cached-policy pair when required, useful baseline control slots and a 10% margin.
Control slots advance the song but earn no projected candidate acceleration.
The projection is labeled `projected-not-measured`: a paired rate
does not establish whole-job net savings. The separator first scans verified
checkpoints and non-silent input with one passage live at a time and a bounded
passage bitmap. It passes a checked remaining-useful count; unknown or short
work cannot finance speculative qualification. Normal processing rechecks the
input and checkpoint, so the scan never substitutes for recovery validation.

## Sustained controls, persistence and evidence

A qualified candidate receives an eight-passage lease, followed by an ordinary
baseline passage that produces useful song output without a replay. Two of the
last three candidate passages exceeding 125% of the paired candidate reference
request an earlier control. Renewal requires the slowest of those three candidate
times to be at most 95% of the faster of the preceding baseline bracket and the
new baseline control. Passing that timing guard and the revised payback check
renews a twelve-passage candidate lease; an incomplete, unaffordable or failed
control returns the job to baseline. The control record's `accepted=true` means
only that its timing inequality passed; the policy header governs admission.

These control inputs differ. Their explicit `comparisonScope=unmatched-inputs`
is a conservative regression guard, not a paired speedup or output-equivalence
measurement, and cannot identify thermal throttling. Initial qualification and
the fresh check for a saved policy still require exact same-input pairs.

The new `passage-policy-v3.bin` uses the
`complete-passage-v3-frequency-b16-useful-controls` execution identity. It binds
the original model, runtime, combined complete-passage scheduler, OS/device
identity digest and processor count. The binary cache schema remains version 2;
the changed execution identity and filename prevent temporal-only qualification
from authorizing the combined candidate.
Old warm-graph and prior passage-policy decisions cannot authorize this path. Even a valid saved
qualification requires a fresh complete pair before another job uses it.
Invalid or incomplete cached evidence cannot enable acceleration. A short job or
failed payback projection can retain complete past evidence for another job, but
cannot bypass that job's fresh pair, memory checks or payback requirement.

[Durable diagnostics](DIAGNOSTIC_EVIDENCE.md) retain the raw qualification/recheck
pairs, the latest unmatched control, output digest, decision, extra-work cost and
projected payback. Mixed
temporal session counts supplement the last configuration. Probe observations
stay separate from production graph totals; [profiling scopes](NATIVE_INFERENCE_PROFILING.md)
prevent overlapping worker durations from masquerading as elapsed passage time.
Runtime 1.25.1, model assets, precision, context and output length are unchanged.
Host correctness and scheduling tests do not substitute for fresh performance
qualification or controlled physical-device observations.
