# Complete-source Deux research collector

This is an unqualified research harness. It collects all original Deux model
passages for a complete public source and hands their unchanged two-stem bytes
to the real production overlap, checkpoint and stem-cache consumer. It changes
no application files, models, diffusion settings, protected policies or release
requests. A full inference collection has **not** been run merely because the
collector compiles or its synthetic tests pass.

For the original public `web/demo/glass-castle.wav`, the plan is twelve complete
13-second contexts at `-66150 + i * 220500`, for `i=0..11`. The production consumer
emits eleven five-second chunks followed by nine seconds, exactly 2,822,400
source-clock samples. Original zero padding is retained. Each model prediction
produces 573,300 Float32 samples of vocals followed by the same number of
accompaniment samples. All 27 original graphs and 335 graph calls per passage
are required. No saved first passage substitutes for a new complete run.

The experiment executes four sequential fresh JVMs: CPU/ALL plain and profiled,
then CUDA/BASIC plain and profiled. Each JVM uses one unchanged `NativeDeux`
object across all passages; the original engine retains buffers and verified
model cache, and still opens/closes graph sessions per prediction. CUDA uses the
previously qualified options with TF32 disabled and the recorded `:4096:8`
cuBLAS workspace setting. It retains the original deterministic-compute default;
neither that setting nor cuBLAS configuration guarantees universal determinism.
Both modes retain original service profiling. Only the profiled twin adds ORT
operator traces and CUDA loaded-library inspection.

The fresh-process group is killed and reaped after exit, timeout or interruption.
SIGTERM raises through the same cleanup path and records an interrupted receipt.
The per-run timeout is bounded to 1,200 seconds per planned passage. Evidence
directories must be new; partial failures are retained rather than overwritten.

## Input and execution

Create an input provenance JSON with these fields; the digest must be computed
over the actual entire WAV, not its PCM payload:

```json
{
  "schema": "lightforge.deux-source-input.v1",
  "sampleRate": 44100,
  "sourceSamples": 2822400,
  "audioSha256": "33f07d502ba19832b62b97d8fb4a11354e81310264bd885d7a06438228773650",
  "sourceKind": "public-mixture",
  "derivation": "Complete original public web/demo/glass-castle.wav; no crop or preprocessing."
}
```

The collector accepts only declared public-mixture or synthetic stereo PCM16 WAV
inputs, bounded to 64 seconds. It rejects any fully silent scheduled context
before execution because the original consumer would skip its inference.
Independent Python PCM decoding and the unchanged native PCM reader must agree
exactly for every padded context. Replay separately checks the unchanged
production JavaScript reader against the same stereo hashes.

First run compilation and loaded-runtime discovery only, using a new directory:

```sh
python3 tools/benchmark_deux_source_cuda.py \
  --models ORIGINAL_DEUX_MODELS --audio web/demo/glass-castle.wav \
  --input-provenance PUBLIC_INPUT.json --toolchain PINNED_TOOLCHAIN \
  --output NEW_READINESS_DIRECTORY --check-readiness
```

`--cpu-only --check-readiness` needs no CUDA runtime or GPU and compiles both CPU
snapshots. Full readiness compiles all four snapshots and requires the pinned
GPU package and an available CUDA device. It executes no model graph and cannot
prove CUDA kernel placement. Remove `--check-readiness` with another new output
directory to run the actual bounded experiment. `--cpu-only` without readiness
collects only the two CPU runs and does not satisfy CUDA replay prerequisites.

The original pinned assets are supplied separately; neither models nor runtime
binaries should be committed as collector evidence. Source files, exact runtime
pins, every model hash, input source, compiled snapshots and resulting artifacts
are hashed. The observed Java 17 launchers, compiler modules, JVM/core libraries,
release metadata and security configuration are bound as well. These files are
rechecked after inference and after all comparisons. Java option injection and
native `LD_PRELOAD` injection must be absent.

## Evidence and acceptance boundaries

The top receipt has schema `lightforge.deux-source-cuda-experiment.v1`.
Each run lives in `cpu_all_plain`, `cpu_all_profiled`, `cuda_basic_plain` or
`cuda_basic_profiled`, with a run receipt and `passage-000` through `passage-011`.
Each passage retains `stems.f32`, `profile.txt`, a source-bound receipt and,
for profiled runs, all 27 completed trace files. `snapshots/` retains exact Java
sources, compiled classes and logs. CPU-only runs are explicitly incomplete for
the CPU/CUDA comparison.

Every same-provider plain/profiled passage must have identical complete Float32
bytes. Signed zero differences still fail the observer check. The collector
independently validates complete trace topology and requires substantive CUDA
arithmetic in every original graph. Raw cross-provider differences retain
numerical diagnostics with no tolerance and no quality approval. No timing
ratio is calculated even if every byte agrees. Recorded whole-run wall time
includes diagnostic source proofs and evidence writes; it is not full analyzer
latency. Per-passage wall time covers the original `predict` call.

After an independently verified complete CPU/CUDA collection, run:

```sh
node tools/deux_benchmark/replay_source.cjs \
  COMPLETED_EVIDENCE_DIRECTORY web/demo/glass-castle.wav NEW_REPLAY_DIRECTORY
```

Replay consumes every measured capture through unchanged production overlap and
checkpoint code, verifies interrupted and checkpoint-only recovery, and writes
both 22.05 kHz stems plus complete 44.1 kHz voice through the actual stem-cache
writer and verified readers. Its in-memory filesystem and fixed diagnostic clock
do not test physical OPFS durability or measure analysis time. The original
consumer label says Android CPU; the actual CPU/CUDA capture identity remains
separate and source-bound, with distinct cache namespaces.

The subsequent vocal stage must infer on **each arm's own complete separated
voice**. The earlier mixture GAME experiment cannot substitute for that input.
This collector and replay alone do not execute full vocal classification,
detail/fusion, bass, show generation, transport or complete analysis. Quality,
performance, Android/physical-device, release and 75% target flags stay false.
