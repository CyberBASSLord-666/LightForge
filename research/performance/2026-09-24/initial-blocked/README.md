# Initial GAME T4 diagnostic: conversion graph failure

Executed September 24, 2026 on free Colab Tesla T4. Source
`d9b42bb79145cfe81367fd70e2ca0ff7f4d52c12`, original Float32 models,
all eight diffusion steps, and the public demo's first 14-second mixture
passage. This is not separated-vocal or complete-analysis evidence.

**Status remains `BLOCKED_OR_REJECTED`: nine CPU passes completed; the first
CUDA pass failed in `dur2bd`.** ONNX Runtime CUDA `ReduceSum` rejected an
empty `[1,1400,0]` intermediate with `keepdims=false`. No CUDA result,
terminal integrity recheck, musical-quality approval or speedup is claimed.

The independent partial audit verified the archive, completed run receipts,
96 captured tensors, six observer comparisons, 15 CPU traces and source
snapshots. CPU/BASIC and GPU-package CPU/BASIC were byte-identical. CPU/ALL
versus BASIC produced 21 notes with identical boundaries and an observed
maximum pitch difference of `7.62939453125e-6` MIDI units. This is not an
accepted tolerance. See [partial-audit.json](partial-audit.json) and the
[unmodified CUDA failure log](cuda-failure.log).

The follow-up research option `--cuda-heavy-only` statically keeps original
`dur2bd`/`bd2dur` graphs on CPU while still requiring substantive CUDA
arithmetic in encoder, segmenter and estimator. The original failed mode is
preserved. A fresh twelve-pass experiment is required; these partial runs
must not be combined with new results.

## Full evidence preservation

The downloaded ZIP is 23,374,358 bytes, SHA-256
`154d5bd74232be0833ba7131fa3917ccaeb00ddae59ba97cff9b0f1f2de765aa`.
It contains only source snapshots, public-fixture PCM, outputs, receipts and
logs. It excludes model weights, the APK, private audio and credentials.
Persistent file saves failed twice, so the exact archive is retained in
this research branch as ordered binary parts under `raw/`.

Run `python3 reconstruct_archive.py NEW_OUTPUT.zip` from this directory to
verify every part and reconstruct the exact ZIP. Existing outputs are refused.
The [part manifest](raw/manifest.json) binds all part lengths and digests.
