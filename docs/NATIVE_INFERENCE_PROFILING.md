# Native Deux inference profiling

`NativeInferenceProfile` is a measurement-only receipt for one 13-second native
Deux passage. It does not receive audio, paths, job identifiers, model names
beyond the fixed graph identifiers, or exception text.

The receipt contains one `native-inference-profile-v1` summary and at most 27
`native-inference-graph-v1` records: `front`, 12 time blocks, 12 frequency
blocks, and two heads. Each graph aggregates model preparation, session setup,
tensor binding, ORT run, packing, scattering, and decoding time. The summary
adds queue wait, engine construction, cache preflight, direct-buffer allocation,
PCM read/encode, output write/fsync/commit, and bounded heap snapshots.

Records are created in memory and emitted once through `AppDiagnostics` after a
passage completes, fails, is cancelled, or is released before completion. They
are never emitted per ORT batch. The normal diagnostic redaction and bounded
journal still apply.

The profiling path is guarded by a full-passage host equivalence test. With the
collector enabled, the production predictor must reproduce the approved
1.25.1-runtime output SHA-256 for the fixed `startSample=-66150` fixture and
must produce exactly 28 receipt records. This is an output-equivalence gate,
not a performance claim or a substitute for device profiling.

Do not reuse a profile to justify session pooling, lower precision, reduced
context, or any model change. Those changes require separate baseline/candidate
quality evidence and the performance-quality gate.

This change does not claim a runtime reduction or enable model/session reuse.
It only makes the short-lived decoded PCM window eligible for collection after
the unchanged encoder consumes it, reducing avoidable retained memory pressure.
