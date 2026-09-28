# Pinned ORT 1.25.1 attention research

Status: research only; no production graph, weight, manifest, dependency, precision, context, or runtime changes were made by this investigation. No ORT 1.30 runtime was invoked during this phase. Exact finite output bytes are the admission criterion; failed candidates were not reclassified by changing tolerance.

## Scope and input

The source is the manifest-verified 2.4.0 temporal graph `block-00-time.onnx`, SHA-256 `688feca1115d610e9bc9d15ac9dac6e33c4cf0a03966d9effe8974d2674ae924`. Its representative input is the first temporal block's bands 24–27 from a 13-second passage beginning 15 seconds into the demo audio, shape `[4,1301,256]`. The front-end input capture used the original front graph with a Python FFT preparation; it is a representative graph-level probe, not a Java end-to-end PCM qualification. Input bytes SHA-256: `2c2ee19d11fc269d5e0d7298a1b65bc661bf6fe9d980fe8bf67f04df2cbde7b5`. Original temporal output SHA-256: `721014fd26d883050283fb00d7b40470c72798cf93749fb12598c210e43425bc`.

All timed screens used the pinned Python ORT 1.25.1 runtime, CPU provider, intra-op 4, inter-op 1, ALL_OPT, and intra-op spinning disabled. This machine's speed varied substantially; measurements from different screens must not be compared as paired evidence. Only a same-input paired JVM full-passage evaluation can qualify production performance.

## Findings

| Candidate | Local output result | Screening result | Decision |
|---|---|---|---|
| Query tiles 128 | Exact across the tested normal/silent/sparse inputs | Essentially neutral versus 64-query tiles | Reject as a useful gain |
| Query tiles 256 | Exact across the tested inputs | About 32% slower than 64-query tiles | Reject |
| Static batch override 4 | Different finite output bytes | Slower; introduced Gemm/FusedMatMul and other transforms | Reject |
| Three separate Q/K/V projections | Exact real-input graph output | 124.95 → 150.00 ms median | Reject |
| Whole-context nonflash MHA | Exact real-input graph output | 423.04 → 524.40 ms median; isolated RSS 293 → 630 MiB | Reject |
| Whole-context flash MHA | Different finite bytes; maxAbs 1.43e-6, RMSE 1.32e-7 | Exploratory 423.04 → 263.88 ms; isolated RSS 277 MiB | Reject under exact criterion |
| Original 21 query tiles, nonflash MHA per tile | Exact for every tested real-input run | 154.47 → 140.96 ms median (8.7%); CPU 0.506 → 0.442 s (12.6%) | Worth further qualification; not production-qualified |

The tiled MHA screen ran eight interleaved warmed pairs in one process. Every adjacent pair improved, by approximately 1.5–20%. All measured CPU throttling and memory reclaim deltas were zero. Cumulative process peak RSS was 461 MiB with both sessions resident, which is not a per-variant memory comparison. The rewrite preserves every original learned initializer byte, every original query Slice (64 rows, final 21), full 1301-frame K/V context, head count 8 and scale 0.125. It selects the nonflash CPU branch explicitly through rank-4 K/V inputs. Candidate SHA-256: `76886d77c2448a66518290ee47bba8e6f71ed5b4b221f85599376fcd221c9d4d`.

The tiled MHA improvement alone is likely a modest full-passage gain because it affects temporal attention only. It must not displace stronger original-graph scheduling candidates without a comparative full-passage trial. No all-layer, independent-audio, Android, memory-budget, cancellation, or release qualification has been performed for this rewrite.

## Operator diagnosis

The ORT 1.25 temporal profile identifies matrix products as the main cost (about 62% in the aggregate diagnostic profile); QKV projection was the largest individual operation. One contended run inflated the aggregate Split share to 7.5%; the final warmed run had about 2.5% Split cost. Do not claim that removing Split alone saves 7.5% consistently. RMSNorm/rotary encoding and layout copies exist but are not enough to justify a 75% speedup claim.

Pinned ORT 1.25.1 already includes a Float32 CPU FlashAttention path in `MultiHeadAttention`. A runtime upgrade is unnecessary to experiment with it. Its arithmetic ordering is different: the source multiplies unnormalized exponential scores by V and divides afterward, rather than normalizing Softmax before the V multiplication. The measured byte differences are therefore unsurprising and remain disqualifying under the current criterion. Its L2-dependent dispatch also requires platform-specific review before any future use.

The nonflash MHA source parallelizes across heads and calls single-thread GEMM inside those head jobs. This motivated the small exact tiled-MHA result while keeping the original bounded score matrices.

## Further custom-op feasibility, not implemented

The thin `CreateOp`/`InvokeOp` approach cannot safely combine an outer `KernelContext_ParallelFor` with internally threaded MatMul: InvokeOp inherits the parent pool, and the pinned thread-pool source explicitly says nested parallelism is unsupported. A safe public-API prototype could instead use one shared tiny child session with intra-op 1, containing the original MatMul→Mul→Softmax→MatMul order, while the parent pool assigns disjoint heads to four worker callbacks. That would retain Float32 math and full context, pin query/K/V views and output tiles, and avoid nested use of the same pool. Child session/OrtValue retirement, callback error propagation, bounded scratch and cancellation need implementation and testing. No custom runtime library or Android custom build was undertaken.

## Evidence files

Compact receipts are under `receipts/`; portable reproduction scripts are under
`scripts/`. See [reproduction and source provenance](README.md). Measurements
are retained without workspace paths; the large raw profile is intentionally
not included.


- `profile-125-summary.json` (aggregate profile receipt; raw trace omitted)
- `screen.json` (query retile)
- `static-125-summary.json`
- `qkv-screen.json`
- `mha-screen.json`
- `tiled-mha-screen.json`
- Rewrite/probe scripts beside the receipts

Official pinned source files were retrieved from the Microsoft ONNX Runtime `v1.25.1` tag. The relevant implementations are `contrib_ops/cpu/bert/multihead_attention.cc`, `attention_cpu_base.h`, `attention_helper.h`, `core/mlas/lib/flashattn.cpp`, `core/session/standalone_op_invoker.cc`, and `include/onnxruntime/core/platform/EigenNonBlockingThreadPool.h`.
