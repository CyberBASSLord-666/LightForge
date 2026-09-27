# First free Colab T4 experiment

Executed September 20, 2026. All eight diagnostic passes completed on an actual
Colab Tesla T4 (15,360 MiB reported VRAM, driver 580.82.07). The host CPU exposed
two Intel Xeon cores at 2.00 GHz. No paid upgrade was selected.

**Outcome: GPU execution works; numerical quality and the 75% complete-analysis
target remain unproven.** The final receipt is
`NUMERICAL_EQUIVALENCE_UNPROVEN`. Repeated performance measurements were correctly
withheld by the existing experiment; no acceptance rule was changed.

## What ran

- Frozen experiment source: `1c7a7d2d3bc0a9eab94bbcb8266710ea7f8ded0b`.
- Original 27 Deux graphs, all 335 model calls, both complete Float32 output
  stems, and one 13-second passage of the public `glass-castle.wav` demo.
- Original model bytes recovered from the public 2.3.1 APK and verified against
  the source manifest. No private audio, credentials or signing identity was used.
- Java 17, ONNX Runtime 1.25.1, isolated CUDA 12.9, cuDNN 9.10.2 and cuBLAS
  12.9.1; TF32 disabled. Native library versions and hashes were observed.
- All four unprofiled/profiled output pairs matched byte-for-byte. Bound source,
  models, audio, runtime files and compiled snapshots passed the final recheck.
- Every graph executed substantive CUDA arithmetic. CPU fallback remained:
  10,232 CPU kernel events in the CUDA trace. This is not complete GPU residency.

## Raw diagnostic observations

These are single unprofiled passage observations, **not qualified repeated
benchmark results**. They exclude the complete song, GAME/vocal stages,
network/queue overhead, JVM startup/result inspection and Android integration.
No speedup ratio is accepted.

| Execution path | Passage seconds |
| --- | ---: |
| Current CPU, ALL graph optimization | 135.619 |
| Current CPU, BASIC graph optimization | 140.362 |
| GPU runtime package on CPU, BASIC | 141.188 |
| GPU runtime package on CUDA, BASIC | 20.395 |

The CPU BASIC result matched the GPU-package CPU BASIC result exactly. Comparing
that matched CPU control with CUDA gave maximum absolute difference
`4.470348358154297e-7` and RMSE `4.312747619637911e-8` across all 1,146,600 samples.
Different Float32 bits alone do not establish audible degradation or quality
equivalence. CPU ALL versus BASIC also differed, independently of CUDA.
The direct current-production CPU ALL versus CUDA comparison had maximum
absolute difference `3.725290298461914e-7` and RMSE `4.367128794262616e-8`.
This extra comparison is retained in the summary without altering the primary
receipt. An independent review rechecked every output hash, all four graph
trace summaries and the bound source/model/runtime evidence.

## Evidence and reproduction

- [Readable qualification summary](qualification-summary.json)
- [Unmodified full qualification receipt, gzip](qualification-receipt.json.gz)
- [Setup receipt](setup-receipt.json) and [readiness receipt](readiness-receipt.json)
- [Open the pinned notebook in Colab](https://colab.research.google.com/github/CyberBASSLord-666/LightForge/blob/a4d448192a1ac9dc5b12732de3eb3b4dd1fd8796/notebooks/LightForge_Colab_Kaggle_GPU_Qualification.ipynb)

The decompressed primary receipt SHA-256 is
`83bc446d518375e18cc47a17ff732e1a7320cdece4c5cc874ca0208b7f82190c`.
The downloaded complete evidence ZIP is 50,821,544 bytes with SHA-256
`657e0089895f377d34deb77a5a25c9d3a51dbee0dbe503e283993285484163c4`.
It contains raw complete outputs, per-graph traces, source snapshots and logs;
the ZIP itself is not included in this Git directory.

## Next experiment

Keep this receipt intact. Test the captured CPU and CUDA stems through the
original Deux consumer, resampling, actual classifier, vocal detail, eight-step
GAME transcription and fusion. Use a separately bound Deux driver; do not
mislabel its output as MDX evidence or borrow another model's tolerance.
Historical same-model CPU runtime bounds can provide diagnostic context, but
cannot automatically approve CUDA.

After numerical and downstream quality qualification, measure repeated complete
separation and vocal stages, then the full transfer-inclusive companion path.
Colab is now a working research runtime; this test does not establish a reliable
always-on app backend. The application and release candidate remain unchanged.
