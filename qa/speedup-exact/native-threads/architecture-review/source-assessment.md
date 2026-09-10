# ONNX Runtime 1.25.1 CPU thread-count assessment

Recommendation: keep the shipping NativeDeux thread budget at four for the strict unchanged-output release until the proposed eight-thread path receives actual ARM64 qualification. Preserve the successful x86 tests as candidate evidence. This assessment does **not** demonstrate a difference in Deux output on ARM64; it identifies why host fixture equality is insufficient to guarantee it.

## Concrete runtime behavior

The standard MLAS SGEMM scheduler partitions output rows or columns according to the pool size. It does not directly split the inner K reduction across threads. However, the unpacked SGEMM operation receives each partition’s local M/N, selects a special ARM64 GEMV kernel when local M is one, and changes K panel length based on local N. Changing the thread count can therefore change a kernel or accumulation grouping indirectly. The packed-weight operation instead uses a fixed K-panel size. [Pinned SGEMM source](https://github.com/microsoft/onnxruntime/blob/v1.25.1/onnxruntime/core/mlas/lib/sgemm.cpp).

For example, an unpacked, single-batch M16/N256/K1024 operation receives local N64 with four threads and N32 with eight; the corresponding K panels are 256 and 512. The ARM64 NEON kernel computes a panel sum and combines it with existing output, so those groupings can differ in binary32. A small scalar reproduction is saved in `grouping-counterexample.json`; it is explicitly an illustrative source-derived counterexample, not ARM64 execution or a Deux tensor. [ARM64 NEON kernel](https://github.com/microsoft/onnxruntime/blob/v1.25.1/onnxruntime/core/mlas/lib/aarch64/SgemmKernelNeon.S).

ReduceMean/ReduceSum also contain pool-size-dependent choices between fast and fallback reduction algorithms. This generic risk is **not reached by the inventoried Deux graphs**, which contain no ReduceMean. The block ReduceL2 operations reduce the final 256-feature axis as complete rows. [Reduction dispatch](https://github.com/microsoft/onnxruntime/blob/v1.25.1/onnxruntime/core/providers/cpu/reduction/reduction_ops.cc), [aggregator implementations](https://github.com/microsoft/onnxruntime/blob/v1.25.1/onnxruntime/core/providers/cpu/reduction/reduction_ops.h).

Standard float32 Softmax distributes whole rows while retaining the complete within-row maximum, exponential sum and normalization. LayerNormalization similarly dispatches a whole normalization row per task. Neither examined path changes within-row accumulation merely by changing the pool size. [Softmax computation](https://github.com/microsoft/onnxruntime/blob/v1.25.1/onnxruntime/core/mlas/lib/compute.cpp), [LayerNormalization implementation](https://github.com/microsoft/onnxruntime/blob/v1.25.1/onnxruntime/core/providers/cpu/nn/layer_norm_impl.cc).

`session.dynamic_block_base` is disabled by default and is not configured by NativeDeux. When enabled it changes how iterations are assigned to workers; this alone is not proof that arithmetic order changes. For the complete-row jobs above, within-row arithmetic remains inside each task. [Configuration definition](https://github.com/microsoft/onnxruntime/blob/v1.25.1/include/onnxruntime/core/session/onnxruntime_session_options_config_keys.h), [thread-pool scheduler](https://github.com/microsoft/onnxruntime/blob/v1.25.1/onnxruntime/core/common/threadpool.cc).

## Actual Deux reachability

The extracted time-attention matrices use 32 independent GEMMs; frequency attention uses 1024. In the standard MLAS implementation, threads per GEMM is the ceiling of target threads divided by batch size. These operations therefore use one thread per GEMM under both four and eight total threads. This avoids the per-matrix partition change described above.

The constant two-dimensional projection matrices are eligible for float32 B prepacking. With normal successful prepacking, their K panel length is fixed. Front and head graphs likewise contain constant-weight projections and ReduceL2 rather than ReduceMean. Thus this inspection has **not established an actual Deux-specific rounding change**. [MatMul prepacking and execution](https://github.com/microsoft/onnxruntime/blob/v1.25.1/onnxruntime/core/providers/cpu/math/matmul.cc).

The optimized executed graph, exact ARM64 kernel dispatch and build configuration still require qualification. The pinned runtime can optionally dispatch ARM SME hardware to KleidiAI when built with that feature; the generic NEON source alone does not cover that alternative. [ARM platform dispatch](https://github.com/microsoft/onnxruntime/blob/v1.25.1/onnxruntime/core/mlas/lib/platform.cpp).

## Evidence limits

Both existing x86 full-context fixtures are exactly equal across four/eight threads and approximately 17–21% shorter in elapsed time. This remains valid evidence for that host and those inputs. It does not establish ARM64 output equality or long-song speed on a heterogeneous phone CPU. The recommended release decision preserves that distinction without describing an unobserved quality defect as a confirmed failure.

All retrieved files are official Microsoft sources at tag `v1.25.1`; download URLs and file hashes are recorded in `downloads.json`. Actual graph inventories provided by the parent are in `deux-all-operators.json`, `deux-block-operators.json` and `deux-block-shapes.json`. No production files were changed by this assessment.
