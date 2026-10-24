# Pinned 1.25.1 attention research

[Findings and limits](SUMMARY.md) describe diagnostic and single-graph experiments,
not a qualified release optimization. The best tested rewrite preserves exact
output bytes for the tested representative input and reduces the graph median by
8.7%; it has not passed complete-passage, independent-input, memory-budget or
Android qualification. Whole-context FlashAttention changed output bytes and
remains rejected. None of these reproduction scripts selects or upgrades to a
newer runtime; every inference script requires ONNX Runtime **1.25.1**.

## What is retained

- `receipts/`: original numerical values, per-run timings, hashes and scope notes.
  The aggregate profile receipt replaces its original workspace path with the raw
  trace's filename. No other measured values were altered.
- `scripts/`: authored graph transformations and probes, adjusted only to use
  portable input/output paths. The synthetic retile screen also now asserts the
  pinned runtime before running.
- `requirements.txt`: current reproduction dependencies. ONNX was upgraded from
  the historical 1.20.1 to 1.22.0 for security; ONNX Runtime remains 1.25.1.
  Historical receipts were produced with ONNX 1.20.1 and have not been rerun or
  rewritten. New graph generation needs fresh numerical qualification.
- `evidence-index.json`: retained receipt/source hashes, original snapshot hashes,
  documented archival edits and explicit output-hash coverage. Some original
  probes recorded in-memory byte comparisons without recording output hashes;
  those missing hashes have not been backfilled or inferred.

No model binaries, audio, captured tensors, runtime packages, copied upstream
kernel implementations or large raw profile traces are included. Generated files
belong in the ignored `build/attention-research` directory, never alongside the
committed evidence. Reproduction produces new receipts there and does not overwrite
historical receipts.

## Reproduction

Run from the repository root in an isolated Python environment. Python 3.12 was
used for these probes. Install `requirements.txt` through the project's normal
approved dependency workflow. The source models must be the manifest-verified
2.4.0 Float32 graphs under `web/analysis/models/deux`; the original block-00 hash
and input hash are recorded in [the summary](SUMMARY.md). The scripts do not
retrieve model files or runtime upgrades.

Paths can be overridden using `LIGHTFORGE_DEUX_MODELS_DIR`,
`LIGHTFORGE_ATTENTION_WORK_DIR` and `LIGHTFORGE_ATTENTION_DEMO_WAV`. The default
audio is `web/demo/glass-castle.wav`.

```bash
# Captures the representative temporal input and a diagnostic operator profile.
python research/inference-2.4.1/attention/scripts/profile_125.py

# Exact tiled nonflash MHA candidate and its interleaved graph-only screen.
python research/inference-2.4.1/attention/scripts/fuse_tiled_mha.py
python research/inference-2.4.1/attention/scripts/screen_tiled_mha.py

# Rejected shape, QKV and whole-context MHA experiments.
python research/inference-2.4.1/attention/scripts/static_125.py
python research/inference-2.4.1/attention/scripts/split_qkv.py
python research/inference-2.4.1/attention/scripts/screen_qkv.py
python research/inference-2.4.1/attention/scripts/fuse_mha.py
python research/inference-2.4.1/attention/scripts/screen_mha.py

# Rejected query-retile experiments; these use synthetic regression inputs.
python research/inference-2.4.1/attention/scripts/retile.py \
  web/analysis/models/deux/block-00-time.onnx \
  build/attention-research/block-00-time-q128.onnx --tile 128
python research/inference-2.4.1/attention/scripts/retile.py \
  web/analysis/models/deux/block-00-time.onnx \
  build/attention-research/block-00-time-q256.onnx --tile 256
python research/inference-2.4.1/attention/scripts/screen.py
```

The first command executes inference and writes a raw profile and temporary ONNX
file; it is not merely a parser. The tiled screen's cgroup accounting targets the
Linux research environment and expects cgroup v2 counters. Serialize these probes
with other timed work. Keep the original tested Float32 model and full 1301-frame
context; do not infer speedup from comparisons between unrelated host runs.

Graph-level exactness does not prove complete PCM parity. Any proposed production
change still requires paired complete-passage JVM measurements with explicit
candidate provenance, complete finite byte parity, independent input coverage,
memory limits and cancellation/retirement verification. Existing release gates
and the owner's release hold remain in force.

## Source provenance and licensing

All runtime behavior described here was checked against Microsoft's **v1.25.1**
source tag, matching the runtime used in these receipts:

- [Float32 CPU MultiHeadAttention and flash selection](https://github.com/microsoft/onnxruntime/blob/v1.25.1/onnxruntime/contrib_ops/cpu/bert/multihead_attention.cc)
- [Nonflash head-parallel attention computation](https://github.com/microsoft/onnxruntime/blob/v1.25.1/onnxruntime/contrib_ops/cpu/bert/attention_cpu_base.h)
- [Attention Softmax helpers](https://github.com/microsoft/onnxruntime/blob/v1.25.1/onnxruntime/contrib_ops/cpu/bert/attention_helper.h)
- [MLAS FlashAttention arithmetic and scratch layout](https://github.com/microsoft/onnxruntime/blob/v1.25.1/onnxruntime/core/mlas/lib/flashattn.cpp)
- [Standalone CreateOp/InvokeOp context and pool inheritance](https://github.com/microsoft/onnxruntime/blob/v1.25.1/onnxruntime/core/session/standalone_op_invoker.cc)
- [Public custom-op C API](https://github.com/microsoft/onnxruntime/blob/v1.25.1/include/onnxruntime/core/session/onnxruntime_c_api.h)
- [Nested parallel-section restriction](https://github.com/microsoft/onnxruntime/blob/v1.25.1/include/onnxruntime/core/platform/EigenNonBlockingThreadPool.h)
- [Split copy implementation](https://github.com/microsoft/onnxruntime/blob/v1.25.1/onnxruntime/core/providers/cpu/tensor/split.cc)

ONNX Runtime is distributed under its [MIT license](https://github.com/microsoft/onnxruntime/blob/v1.25.1/LICENSE),
with [third-party notices](https://github.com/microsoft/onnxruntime/blob/v1.25.1/ThirdPartyNotices.txt).
Individual thread-pool sources also contain upstream Apache-2.0 attribution; their
notices must be preserved if code is ever copied. This folder references those
implementations but does not vendor or compile them. The local runtime notice is
[onnxruntime-native-LICENSE.txt](../../../web/licenses/onnxruntime-native-LICENSE.txt).

The model is [becruily/mel-band-roformer-deux](https://huggingface.co/becruily/mel-band-roformer-deux/tree/2da74427d682a3df47a774378fc24d7a1a0cdaad),
checkpoint revision `2da74427d682a3df47a774378fc24d7a1a0cdaad`. Model weights and their
converted derivatives retain **CC BY-NC 4.0**, as recorded in the existing
[model notice](../../../web/analysis/models/deux/NOTICE.txt). Architecture code is
pinned to [Music-Source-Separation-Training commit 0e5f1159fc5ea87fc13b957584e178b4977e5dd3](https://github.com/ZFTurbo/Music-Source-Separation-Training/tree/0e5f1159fc5ea87fc13b957584e178b4977e5dd3)
under MIT; this does not replace the separate weight license. No model or code
author endorsement is implied. These research transformations and measurements
do not change licensing or authorize redistribution beyond the existing terms.
