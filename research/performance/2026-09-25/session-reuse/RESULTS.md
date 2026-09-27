# GAME session reuse — September 25, 2026

**CPU diagnostic passed.** On the complete public 64-second mixture, retaining
the five model sessions preserved all captured tensors and unrounded notes.
The unchanged production consumer produced the same 98 final notes and exact
checkpoint restoration. No GPU, timing, general musical-quality, Android or
75% complete-analysis claim is established.

| Check | Verified result |
| --- | --- |
| Original input | 2,822,400 float32 samples at 44.1 kHz; six original windows/seeds |
| Execution matrix | Six fresh JVMs: CPU ALL × default/reuse × plain/captured/profiled |
| Observer comparisons | All 24 passed exactly |
| Default versus reuse | All 96 tensor pairs byte-identical; all unrounded notes identical |
| Model calls | 72 in each profiled arm; original five graphs and eight diffusion steps |
| Session lifetimes | 30 default versus five retained sessions |
| Production consumer | 98 identical final notes; native callback and checkpoint restores match |
| Retirement | Both complete host arms reported final retirement; lifecycle fault tests remain mock-boundary tests |

Execution commit: `ae7ed37ad7539b71ea84f783470c174f1297346e`, tree
`4809b69ac830a454832b9414f0dd949e29301011`.
The separate verifier and production replay are frozen at
`85bca325b65f93790a17bfd9142dad80162384b2`, tree
`b703f823fb7da8f36eb4461c4f139ddda0df2038`.
The original float32 model files, configuration, source, complete public input,
runtime dependencies and complete installed JDK inventory were rechecked after
execution. Application source was not modified for this experiment.

## Audit correction and preserved evidence

The execution checkpoint's auditor required `lib/jli/libjli.so`, but the exact
pinned Temurin archive installs `lib/libjli.so`. After collection completed, one
path was corrected in a later verification commit. The execution snapshot,
compiled candidates, raw outputs and receipts remain unchanged. Both directory
and independently extracted ZIP audits passed with that corrected verifier.
The [actual-input regression](audit-regression/20260925-original-layout.json)
accepted the correct layout and rejected missing or misplaced library bindings;
all 679 original evidence files remained unchanged during that regression.

The [archive manifest](cpu-full-source/raw/manifest.json) binds 115 parts to an
85,922,917-byte ZIP, SHA-256
`8acc142f2a232568a6bceaaca1c7b9d83a3c844b5bb28677a7af3f1c1f7f6c38`.
All 680 ZIP members passed CRC, complete inventory and source checks. The archive
retains every raw tensor, profile, class, generated source/diff, log and receipt.
It contains the public fixture only; model/runtime binaries are represented by
their checked pins and final rehash attestations.

- [Independent archive verification](cpu-full-source/verification.json)
- [Production consumer and checkpoint replay](cpu-full-source/production-replay.json)
- [Driver completion](cpu-full-source/driver-receipt.json)
- [Runtime and input bindings](cpu-full-source/runtime-input-bindings.json)
- [Controlled lifecycle tests](lifecycle/README.md)

Reconstruct with `cpu-full-source/reconstruct_archive.py NEW_OUTPUT.zip`.
Re-audit using `tools/game_benchmark/verify_session_reuse_evidence.py` from the
verification commit, the exact archive size/digest above, the execution commit
and tree above, `--variants cpu_all`, and a new output directory. Production
replay commands and its separate verifier identity are documented in
[PRODUCTION_REPLAY.md](PRODUCTION_REPLAY.md).

## Remaining boundary

This host candidate has blocking cancellation/close and rejects Android contexts.
Controlled Java faults and successful native execution do not qualify Android
lifecycle behavior or injected native destructor failures. The input was a
mixture, not a separated vocal stem. Captured-note replay excludes inference,
source separation, vocal fusion and complete analysis timing.

The next numerical controls are the complete separated-vocal path and the same
default/reuse comparison on CUDA. A separate repeated timing protocol is still
needed after those gates. Cold constructor costs cannot all be projected onto
later passages: process/provider startup and already-cached verification must
be separated from recurring session construction. No application or release
publication is authorized by these research results.

An earlier local comparison lost its unpreserved output when the workspace
expired during an interrupted sign-in wait; no result from it is claimed here.
This evidence comes from the fresh, completed `game-session-reuse-cpu-20260925-02`
run. Colab's Google sign-in endpoint returned HTTP 502 on the subsequent retry;
no new GPU execution took place in this run.
