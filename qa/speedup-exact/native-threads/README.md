# Native Studio CPU qualification

The production change raises Deux's intra-op thread budget to eight when Java reports at least eight available cores. Devices reporting one through seven cores keep the original budget, including the four-thread cap on five-to-seven-core systems. MDX, model weights, 13-second context, independent batches, graph options, transforms, output heads, cancellation and native job ownership are unchanged.

| Available cores | Previous threads | Updated threads |
|---|---:|---:|
| 1–4 | Core count | Core count |
| 5–7 | 4 | 4 |
| 8 or more | 4 | 8 |

Fourteen explicit cases also verify defensive zero, negative and very large inputs. They run through the existing no-argument `NativeDeuxTest` invocation in `tests/verify_native_release.py`, which binds the current production/test sources into its native release receipt.

The actual original and updated production classes were compiled separately and run on two independent recordings using pinned ONNX Runtime 1.25.1. Candidate source was not patched to force eight threads. The available-core policy selected it normally on the qualified host. Every complete output byte matched: two 573,300-sample stems per recording, 4,586,400 bytes per prediction, zero absolute error and zero RMSE.

| Full-context fixture | Original 4 threads | Updated 8 threads | Less elapsed time | Full output |
|---|---:|---:|---:|---|
| Glass Castle start | 53.51 s | 44.51 s | 16.82% | Byte-identical |
| Independent Falcon mixture | 54.57 s | 43.19 s | 20.84% | Byte-identical |

These are controlled Linux/JVM host measurements. They do not establish Android/ARM64 bit identity, sustained phone throughput or a whole-analysis speed ratio. Heterogeneous mobile CPUs contain cores of different speeds. Sampled peak RSS varied; no memory-saving claim follows from these runs.

`verification.json` binds the current sources, unchanged transform, original reference sources, runtime, both original audio assets, verifier and all 27 model files. It records the exact native-format input and output hashes, elapsed times, sampled RSS, output lengths and byte comparisons. The Falcon research asset is float32 WAVE; the verifier prepares the same deterministic PCM16 fixture for both predictors because that is the existing native input contract. Production audio conversion is unchanged.

`independent-review.json` records a separate audit of source scope, all source/model hashes, candidate bytecode, logs, finite sample values and both complete byte comparisons. Preserved inference logs match their receipt hashes. Raw predictions remain in the verifier's work directory and can be regenerated.

To reproduce, run `python3 qa/speedup-exact/native-threads/verify.py` on a host exposing at least eight Java processors with the pinned project toolchain and model/fixture files. The verifier uses its own scratch work directory and rejects any source or model mismatch. Keep its CPU window free of other inference benchmarks. It runs original/current order for the first fixture and current/original order for the second.

Earlier exploration rejected retaining all 27 sessions, larger independent batches and concurrent Deux instances as useful release changes. In particular, two simultaneous two-thread instances preserved raw passages and the unchanged five-second crossfades, but improved throughput only 6.2% while adding approximately 653 MB of peak RSS. That scheduling change was not implemented.
