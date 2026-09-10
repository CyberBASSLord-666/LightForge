# Native GAME exact parity investigation

Native ORT 1.20.1 does not reproduce the released WASM 1.20.1 encoder and pitch estimator byte for byte, even when both graphs receive precisely the same production tensor bytes. Changing the native estimator's graph optimization level to BASIC or DISABLED does not fix this. No production files were modified.

Reference capture: 253,440 samples from the existing actual separated demo vocal fixture, language 0, seed 2025. The unmodified production GAME adapter ran all eight diffusion steps with one WASM thread. The fixture manifest preserves twelve invocations, their typed input/output dimensions, binary bytes, and SHA256. Each native graph received the captured WASM inputs independently; differences in an upstream native graph cannot explain the estimator differences in this experiment.

| Graph/configuration | Exact outputs | Raw differences |
|---|---|---|
| Encoder, native ALL/1 | maskT only | x_seg 132,666 of 146,944 values; max abs 3.933906555175781e-6. x_est 135,818 of 146,944 values; max abs 5.364418029785156e-6. |
| dur2bd, native ALL/1 | All | None |
| Eight segmenter calls, native ALL/1 | All eight boundary arrays | None at the graph output |
| bd2dur, native ALL/1 | Durations and maskN | None |
| Estimator, native ALL/1 | presence only | 13 of 18 scores; max abs 0.000408172607421875 MIDI |
| Estimator, native BASIC/1 | presence only | 9 of 18 scores; max abs 0.000682830810546875 MIDI |
| Estimator, native DISABLED/1 | presence only | 9 of 18 scores; max abs 0.001102447509765625 MIDI |

The controlled native ALL/1 segmenter calls took 0.7202–0.7853 seconds each on this x86 host. These are isolated graph timings, excluding bridge and Android execution. They are not a phone or end-to-end speedup claim.

## Interpretation and source evidence

The mismatch is not solely a runtime version mismatch, and graph optimization differences are not its sole cause: same-version and disabled-optimization probes still fail. The exact first arithmetic node responsible was not localized.

ORT's pinned source contains an architectural mechanism consistent with these findings: `MlasMultiplyAddFloat32x4` uses `_mm_fmadd_ps` for native FMA3 but separate `wasm_f32x4_mul` and `wasm_f32x4_add` for WASM SIMD. Native platform initialization selects FMA3/AVX512 GEMM, convolution and nonlinear kernels according to CPUID. Thus matching ORT version or disabling graph graph optimization does not make the native mathematical kernels identical to the WebAssembly kernels.

Primary source files inspected through GitHub:
- https://github.com/microsoft/onnxruntime/blob/v1.20.1/onnxruntime/core/mlas/lib/mlasi.h
- https://github.com/microsoft/onnxruntime/blob/v1.20.1/onnxruntime/core/mlas/lib/platform.cpp
- https://github.com/microsoft/onnxruntime/blob/v1.20.1/onnxruntime/core/mlas/lib/sgemm.cpp

Native GAME as a whole is rejected under the user's exact-output requirement. A native-segmenter-only hybrid preserves the visible categorical graph outputs on this one fixture, but the different arithmetic can still move a near-threshold decision on other inputs; one exact boolean fixture is not a proof of universally identical decisions. Do not release a hybrid based on this experiment alone. No tolerance was relaxed, no score was rounded to claim parity, and no inference step was removed.

A conservative alternative worth pursuing is independent passage parallelism using the same single-thread WASM kernels, fixed per-passage seeds, original core/halo geometry, and ordered reconciliation. It requires explicit memory bounds and exact multi-passage tests. This investigation did not implement or qualify that alternative.

## Reproduction

`compare.py` loads Python ORT from the local `python-1.20.1` package directory and checks captured file SHA256 before every tensor read. Run with `--level all --threads 1` for all graphs, or `--level basic --threads 1 --graphs estimator` / `--level disabled --threads 1 --graphs estimator`. `native-1.20.1-*/report.json` contains the measured values, hashes and scope. `binding.json` binds the released source and model files and the reference capture manifest.
