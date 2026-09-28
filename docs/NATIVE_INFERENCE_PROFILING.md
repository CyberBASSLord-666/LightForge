# Native Deux inference profiling

`NativeInferenceProfile` is an observational receipt for one 13-second native
Deux passage. It never receives audio, paths, job identifiers, exception text,
model paths, or model payloads.

The bounded `v2` receipt contains one summary, at most 16 named stage records,
and at most 27 graph records: `front`, 12 time blocks, 12 frequency blocks, and
two heads. The named stages cover inference-gate wait, engine construction,
cache preflight, direct-buffer setup, runtime setup, PCM read, feature encode,
model/session initialization, tensor binding, ORT inference, packing,
scattering, decode, write, flush, and atomic output commit. Graph records
retain the same detail per fixed graph.

Every stage and graph reports wall time when that stage ran; an absent stage is
`unavailable`, not zero. Per-thread CPU time is reported only when Android's or
the host JVM's actual thread CPU clock is already available; otherwise a stage
record says `cpuTelemetry=unavailable` and `cpuMs=unavailable`, while a graph
record marks the corresponding per-operation `*CpuMs` fields unavailable. The collector
does not enable a process-wide host CPU-time switch merely to fill a report.
The legacy `*CpuMs` fields are explicitly labeled `cpuScope=calling-thread`.
`inferenceThreadCpuMs` is the same calling-thread measurement;
`inferenceProcessCpuMs` uses Android `Process.getElapsedCpuTime()` (or the host
operating-system bean's real process CPU clock). Concurrent calls contribute
actual graph-call counts and aggregate call durations. A wave contributes one
coordinator measurement after its workers retire. The temporal refill pipeline
instead contributes one interval per temporal graph, starting before initial
packing and ending after every worker retires. Its
`inferenceWorkScope=run-and-pipeline-coordination` explicitly includes packing,
refill, scattering and coordination as well as concurrent native execution.
Reusable tensors are bound before that interval. Both routes label inference
wall time `critical-path`; graph-call wall time is labeled `aggregate-call`.

Worker thread CPU is reported separately as `inferenceWorkerThreadCpuMs`; it
does not replace the coordinator's `inferenceThreadCpuMs`. Overlapping per-call
process CPU is discarded. Pipeline copies retain graph and stage wall/caller CPU
measurements, labeled `nested-in-inference-pipeline`. A stage that also includes
ordinary frequency/head copies is labeled `mixed-nested-and-sequential-intervals`.
Nested copy process CPU is unavailable because other native workers run during
those intervals. The parent pipeline process CPU includes that concurrent work
once. `instrumentedCpuMs` subtracts explicitly nested copy caller CPU from the
stage CPU sum and declares `instrumentedCpuScope=nonoverlapping-calling-thread`.
Missing clocks, missing parent intervals, or nested CPU exceeding observed
parent CPU make this total unavailable. Stage durations must not be summed as
nonoverlapping intervals when their scope marks nesting. Process CPU includes ORT workers
and every other app thread, so it is useful for scheduling diagnosis but is not
an isolated model CPU utilization measurement. A missing clock or any missing
sample keeps the complete process metric unavailable. Production inference and
session-init counts are explicit. Scheduler probes, when observed, have separate
summary-only `schedulerCalibrationWallMs` and `schedulerCalibrationCount`; they
never inflate production graph-call counts or add stage records.
Heap values are Java-heap observations only, marked `unavailable` (including
the value field) if the runtime cannot read them. Direct-buffer and cache
values use the same rule. The CPU-only Deux path always reports
`acceleratorTelemetry=unavailable`; it does not invent GPU/NPU utilization or
accelerator-memory numbers. Cache counters are observed from the verified
preflight model inventory and remain unavailable if that stage was not reached.

Records are created in memory and emitted once through `AppDiagnostics` after a
passage completes, fails, is cancelled, or is released before completion. They
are never emitted per ORT batch. The normal diagnostic redaction and bounded
journal still apply. `AppDiagnostics` also binds each summary to the passage's
owning job and accumulates fixed numeric fields in `DiagnosticJobSummary`, so
trace rotation cannot remove already-recorded whole-job stage and native totals.
See [diagnostic evidence](DIAGNOSTIC_EVIDENCE.md) for retention and recovery scope.

The profiling path is guarded by a full-passage host observer-equivalence test.
In one fresh JVM/runtime it runs the fixed `startSample=-66150` passage first
without the collector and then with it. Both `2 × 573300` float32-LE outputs
must be complete, finite and byte-identical: the predeclared maximum absolute
error, RMSE and relative RMSE are all exactly zero. Any measurable difference,
nonfinite sample, incomplete output, unknown profile record or changed topology
fails closed. The proof also records a SHA-256 over a canonical serialization of
all profile records plus the fixed one-summary/15-stage/27-graph topology.

The prior approved 1.25.1 output SHA-256 is retained only as reproducibility
context. It is not a cross-run profile pass criterion, because the same pinned
runtime can legitimately produce flaky cross-run bytes under different host
scheduling. The ordinary immutable native-runtime comparison remains a separate
unprofiled quality binding.

CI creates one `LIGHTFORGE_EVIDENCE_SESSION` nonce for the verification run.
The paired receipt records it and `verify-analysis.py` requires an exact match;
a stale/wrong session fails. Outside session mode, only a fresh null-session v2
receipt with current source, test, model, input and runtime hashes is accepted;
a session-bound receipt is rejected. This is an output-equivalence gate, not a
performance claim or a substitute for device profiling.

Do not use a profile to justify session pooling, lower precision, reduced
context, or any model change. Those changes require separate baseline/candidate
quality evidence and the performance-quality gate. Profiling itself does not select a model, change precision or alter tensors.
The independently qualified parallel temporal path changes batch geometry and
execution scheduling; its observed 875 calls must not be labeled as the
reference path's 335 calls. See the [execution contract](NATIVE_EXECUTION_CALIBRATION.md).
