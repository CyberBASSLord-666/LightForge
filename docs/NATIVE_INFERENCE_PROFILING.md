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
Heap values are Java-heap observations only, marked `unavailable` (including
the value field) if the runtime cannot read them. Direct-buffer and cache
values use the same rule. The CPU-only Deux path always reports
`acceleratorTelemetry=unavailable`; it does not invent GPU/NPU utilization or
accelerator-memory numbers. Cache counters are observed from the verified
preflight model inventory and remain unavailable if that stage was not reached.

Records are created in memory and emitted once through `AppDiagnostics` after a
passage completes, fails, is cancelled, or is released before completion. They
are never emitted per ORT batch. The normal diagnostic redaction and bounded
journal still apply.

The profiling path is guarded by a full-passage host equivalence test. With the
collector enabled, the production predictor must reproduce the approved
1.25.1-runtime output SHA-256 for the fixed `startSample=-66150` fixture and
must produce one summary, 15 host-observable stages, and exactly 27 graph
records. This is an output-equivalence gate, not a performance claim or a
substitute for device profiling.

Do not use a profile to justify session pooling, lower precision, reduced
context, or any model change. Those changes require separate baseline/candidate
quality evidence and the performance-quality gate. This contract change does
not enable model/session reuse, change model selection, alter batch sizes, or
change the inference/output data path.
