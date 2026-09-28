# Native separation scheduling

The 2.4.1 native Deux implementation retains all 27 original Float32
graphs, trained weights, 60 bands and the complete 13-second context. Temporal
bands are independent: the optimized path runs one band per call, with four or
eight concurrent calls sharing a CPU session. Frequency, front and mask-head
geometry remains unchanged. A complete parallel passage has 875 graph calls;
the reference four-band path has 335. Neither count means less model work.

The final production implementation passed the owner's pre-build improvement
requirement: the source-bound host comparison measured 32.6% lower median
complete-passage time with identical outputs. Fresh production and Android
release verification remains required. Host results do not establish physical
Android performance or a whole-song speedup.

## Device admission

The reference uses up to four intra-operator threads, sequential graph execution
and disabled spinning. Concurrent temporal calls use one intra-operator thread
and private input/output buffers. Only one model graph is resident at a time.
Each completed temporal worker slot immediately receives the next independent
band. The coordinator alone packs inputs and scatters completed outputs; it
never overwrites a band that another worker still needs. Pinned tensors are
bound once per slot for each temporal graph and reused only after its native
call has returned.
Front and mask-head scheduling stays at the reference configuration. Frequency
scheduling retains its independent, exact-output admission check.

Temporal calibration compares the complete first temporal graph over all 60
real input bands. It leaves the original activations unchanged. Every eligible
configuration receives three alternating reference/candidate pairs, each with
a warmup. Warmup and measured results must be finite and match the reference
raw Float32 digest of the complete activation tensor. Trials use a bounded
working copy so the original input stays unchanged. Each measured call follows
the production packing, inference and scattering path, including tensor binding
and worker setup and retirement. Complete output validation happens after its
timer stops; input restoration and hashing cannot create an apparent inference
gain. These extra calibration costs remain in the separate calibration total.
A candidate must reduce median
time by at least 10%, with at least 5% improvement in every pair. These local
admission thresholds do not by themselves qualify the release.
The temporary working tensor occupies 79,933,440 bytes, remains within the
reserved memory margin, and contributes to observed peak direct-buffer usage.
It is released from the runner's references when temporal calibration finishes.

The candidate shortlist is bounded by available processors and native memory
headroom, using Android's system memory observation rather than Java heap free
space. Memory is checked again before cached parallel execution. Temporary
memory pressure retains the reference path without permanently recording a
low-memory observation as a completed calibration. If a completed four-worker
shortlist later gains enough headroom for eight workers, a later passage tests
the expanded shortlist. The prior measured decision remains available until
that replacement completes.

All workers retire before their tensors, shared session or process inference
gate are released. Cancellation terminates their shared runtime RunOptions;
interrupts are restored after native retirement. Output is committed only after
the complete original two-stem reconstruction succeeds.

## Persistence and evidence

Both graph-family decisions must complete before an atomic bounded policy file
is committed. The cache identity binds the model manifest, runtime and scheduler
revision, OS build, device family/ABI and available processor count. Only the
identity digest, allowlisted configurations and numerical evidence are stored.
No audio, notes, job identifier or raw device identity enters this file.

Invalid, outdated, corrupt, truncated or incomplete records cannot enable an
optimization. Calibration overhead is recorded separately from production
inference. Parallel graph-call elapsed times overlap and are labeled aggregate
call time. Parallel inference wall/process CPU time is measured once around
each complete temporal pipeline, including its overlapping coordinator copies.
Those copies remain visible as nested observations and are not added again to
instrumented CPU totals. Worker thread CPU is a separate observation. The
inference count remains the actual number of graph calls.

The analysis execution identity is
`native-deux-onnxruntime-android-1.25.1-v3`. Prior execution evidence is not
silently relabeled. Runtime 1.25.1 and original model assets remain pinned.

## Verification

Pure policy checks cover complete alternating trials, exact finite outputs,
weak timing, memory eligibility, family-specific configurations and persistence.
Actual-model verification covers the complete reference output, fresh and cached
calibration, forced host fixtures for both parallel geometries, cancellation,
interrupt retirement and subsequent recovery. Fixture selection exercises the
production runner independently of host device admission; it is not a device
performance result.

Release performance qualification separately compares the final production
source against its reference path in repeated full-passage runs. It must retain
complete finite outputs and publish time, CPU and peak memory observations.
Every compared host JVM receives the same seven-CPU affinity, leaving at least
one CPU of cgroup quota for platform work, and records its observed CPU affinity
and processor count. The host fixture explicitly exercises eight worker slots
on those seven CPUs; it does not assert that device admission would choose eight
workers on a seven-core phone. Android admission remains separate and requires
eight reported processors for that choice. Failed attempts remain preserved;
a passing median cannot hide a weak measured pair or a resource-guard failure.
Physical phone energy, thermal behavior and speed remain unmeasured without
corresponding device observations.
