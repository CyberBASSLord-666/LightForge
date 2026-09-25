# Session-reuse lifecycle execution evidence

On September 25, 2026, the isolated host-only candidate passed 50 controlled
Java lifecycle cases for each of CPU/ALL and deterministic heavy-only CUDA
configuration snapshots. Both exact generated snapshots also compiled against
the real SHA-256-pinned ONNX Runtime 1.25.1 API. The first execution used local
OpenJDK 17.0.20; the preserved repeat used the repository-pinned Temurin
17.0.20.1 toolchain. Each execution completed all 100 cases.

This is mock-boundary evidence. The executed snapshots replace only model
preparation with a fault hook and use Java ORT resource controls with synthetic
tensor outputs. No model or native inference executes. Exact generated
snapshots compile separately against real ORT, never the mock classpath.
All JNI/CUDA lifecycle, numerical-equivalence, timing, Android, musical-quality,
75% target and release approvals remain false.

The cases cover all five constructor positions, all twelve graph-call failure
positions, failed and throwing destructors, retained-resource cleanup,
cross-thread cancellation/close, listener and cancellation callback reentry,
invalid clocks, wrong owner, paused idle destruction, nested cleanup and
unexpected drain failures. The Java controls assert that active sessions are
not destroyed, detached RunOptions are not terminated, ordinary owners get
one retirement attempt and failed destruction is never reported as retired.
Reflection-induced map iteration/clear faults leave ownership explicitly
unconfirmed; they do not claim recovery from arbitrary JNI failures.

No generator or application source change was required. Production NativeGame
remains SHA-256 `a1bb68a4930b5acd74f7fdc2d1d105f1d7f5c9974f11514872f47672b8736369`.
The unchanged candidate generator remains SHA-256
`2b0e886b605e3a039049e77183c39e45dfa3c1192c4ac15a86a3fb1743568613`.

`pinned-temurin/receipt.json` records actual source/dependency hashes, generated
candidate and fixture hashes, runtime identities and all result bindings.
Per-case JSON and complete compile/run logs are retained for both toolchains.
The condensed receipts retain hashes of generated snapshots and compiled class
inventories; source snapshots and classes can be reproduced by the bound
generator and checked-in controls. Binaries, model files and dependencies are
not included here.

Reproduction instructions and precise fixture limitations are in
`tools/game_benchmark/session_reuse_lifecycle/README.md`. Focused Python checks
also passed: two lifecycle harness checks, including the executed matrix, and
eight existing candidate-generation checks. These results advance the host
ownership experiment; actual default/reuse model equivalence remains a
separate required gate.
