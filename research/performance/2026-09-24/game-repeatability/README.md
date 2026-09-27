# GAME CUDA repeatability screen — September 24, 2026

The default CUDA configuration varied between two otherwise identical captured
runs. Requesting deterministic computation produced exact results in this bounded
screen and is a candidate for a fresh full qualification. No musical-quality,
complete-analysis speedup or release approval is established.

The fixed order was A1 captured, B1 captured, A2 captured, B2 captured, B plain,
B profiled, each in a fresh JVM. A used the original heavy-only CUDA configuration.
B added only `options.setDeterministicCompute(true)` immediately before CUDA
registration for encoder, segmenter and estimator. Both original conversion
graphs remained on CPU. Source commit
`8590ac4a67de4340857a96ffe38bae53d7d902b8`, original Float32 models, input,
eight steps, seeds, thresholds and runtime remained bound to the evidence.

| Comparison | Observed result |
| --- | --- |
| A1 / A2 | Only estimator scores differ: 10 of 22 values; maximum absolute difference `1.1444091796875e-5`, RMS `3.98432134908366e-6`. |
| B1 / B2 | All 16 tensors and unrounded notes match exactly. |
| B1 / B profiled | All 16 tensors and unrounded notes match exactly. |
| B plain / B1 | Unrounded notes match exactly; plain tensors are unobserved. |

All six runs produced 21 notes with identical boundaries. The default repeats
have 10 pitch differences. Changing configuration also changes some encoder
outputs and pitches; deterministic execution does not imply CPU equivalence.
Two matching repeats do not prove universal determinism, and this screen does
not establish that instrumentation caused the previous observer mismatch.

[Independent audit](independent-audit.json) verifies 183 archive members and CRCs,
180 artifact hashes, all 53 recorded input/source/runtime bindings, the exact
six-arm matrix and source insertion, six run receipts, 80 captured tensors,
five provider traces, ten mapped native-library bindings, and the final closed
log/exit guard. Every quality, measured-performance and release flag stays false.

The [complete receipt](screen-receipt.json.gz) is preserved without modification:
127,127 decompressed bytes, SHA256
`08ac226729ce9c83f66fa083db6bde7490d589c44a9799e067f00e70d90c943a`.
The full ZIP is preserved in 23 digest-bound parts under [raw/](raw/manifest.json):
16,860,558 bytes, SHA256
`e0c8d239a91286aa8c7247efe4e99d2b43f2ea3bc9f61517146c96dd437cb50a`.
All parts were independently checked to reconstruct that exact archive.
Use `reconstruct_archive.py` with a new destination to recover it.

The original [Colab cell](game_repeatability.py), [embedded driver](game_repeatability_driver.py),
[export cell](export_game_repeatability.py), [plan](plan.json),
[installed API inspection](deterministic-api.txt) and [closed-log guard](driver-exit.json)
remain available for review. Do not combine these six runs with another
qualification or relabel the earlier rejected run as passed.
