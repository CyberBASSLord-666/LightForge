# Path to a 75% reduction in complete analysis time

Status: development research, September 24, 2026. No 75% speedup, GPU quality
qualification, Android speed result or release authorization is established by
this document. The 2.3.2 release candidate remains separate and unchanged.

## Decision

Prioritize running the original Deux and GAME models on a private GPU companion,
starting with NVIDIA CUDA and strict Float32 settings. Keep Android native CPU
execution as the standalone path. A hosted instance can run the same worker when
local hardware is unavailable, but it must include queue and network costs in its
results and must not receive private audio without the user's explicit selection.

This is the strongest hypothesis to test, not a measured fourfold result. A
faster replacement model remains a separate future candidate requiring its own
quality evidence; it is not necessary for the first experiment.

## Why actual inference is the priority

An aggregate of 18 complete native Deux passage records in previously supplied
phone diagnostics contains 2,962.231 seconds of passage wall time:

| Component | Seconds | Share of passage wall time |
| --- | ---: | ---: |
| Graph inference | 2,848.964 | 96.176% |
| Model initialization | 53.340 | 1.801% |
| Everything else | 59.927 | 2.023% |

All 486 model-cache lookups hit; none missed. Time-axis blocks account for
67.111% of graph inference and frequency-axis blocks for 30.873%. These are
partial-workload diagnostic aggregates, not a fresh complete-song benchmark.
Private log contents and audio identifiers are not committed here. The recorded
CPU clock is per-thread, so its ratio to wall time does not establish aggregate
core utilization.

Removing every model initialization would save only 1.8% of separation time in
those observations. CPU arena/memory-pattern reuse already showed about 12.1%
lower median host passage wall time across three paired runs, with exact complete
outputs. Earlier GAME native inference captures were about 2.4 times as fast as
WASM, but they do not establish complete-stage or phone speed. Those improvements
are useful and insufficient evidence for the requested total reduction.

## Complete-analysis budget

The user-provided planning baseline is 8,454 seconds, including 5,893 seconds of
separation and 2,515 seconds of vocals. The remaining 46 seconds includes rounding
and unattributed time: the separately stated rhythm and bass numbers sum to 45.
The original clean full-run receipt for this exact triplet has not been recovered;
resumed diagnostic totals must not be substituted for it.

For complete separation-stage acceleration S, complete vocal-stage acceleration
V and added overhead H (GAME-only inference acceleration is not V):

`candidate_seconds = 46 + 5893 / S + 2515 / V + H`

The exact 75% reduction target is 2,113.5 seconds (about 35.2 minutes). Both major
stages need 4.067 times acceleration with zero added overhead, or 4.317 times
with 120 seconds added. Accelerating separation alone, even to zero time, saves
at most 69.7%; accelerating vocals alone saves at most 29.7%.

| Hypothetical scenario | Complete time | Reduction | Within target? |
| --- | ---: | ---: | --- |
| Both major stages 4x, no extra overhead | 35.80 min | 74.59% | No |
| Both major stages 5x, plus 120 seconds | 30.79 min | 78.15% | Yes |
| Separation 6x, vocals 3x, plus 120 seconds | 33.11 min | 76.50% | Yes |

These rows are feasibility arithmetic, not measured results. Aim for at least
5x on both expensive stages to leave overhead margin, then decide from full
phone-to-worker-to-saved-project measurements rather than model-call timing.

## Experiment order

1. Profile the current complete production passage with original model hashes,
   all 27 Deux graphs and 335 calls. Compare instrumented and uninstrumented
   complete outputs so the diagnostic cannot silently change computation.
2. On an actual GPU, compare production CPU/ALL, CPU/BASIC, GPU-build CPU/BASIC,
   and CUDA/BASIC. These controls separate graph-optimization, runtime-build and
   execution-provider differences. Retain raw complete Float32 output comparisons.
3. Confirm observed operator placement. Merely configuring CUDA does not prove
   the expensive work ran there. Host trace durations are not GPU-device kernel
   times, and profiling overhead is not a speed measurement.
4. Qualify numerical behavior before accepting a candidate. Exact output bytes
   are a conservative automatic acceptance criterion for an execution-only
   experiment. A mismatch is not proof of audible regression; it requires the
   existing source-bound numerical and musical-quality evaluation and cannot be
   relabeled a pass by inventing a tolerance.
5. Benchmark repeated fresh processes, alternating order, explicit warmups and
   controlled cache state. Run the complete shared pipeline over the public demo
   and licensed fixtures, then the locked representative corpus. Preserve full
   stems, unrounded notes, final semantics and choreography for comparison.
6. If the provider qualifies, test persistent sessions and device-resident
   intermediates as separate optimizations. Keep original windows, overlap,
   contexts, batching, precision, seeds and all eight GAME diffusion steps.
7. Measure the integrated path, including upload, queue, cold start, inference,
   result transfer/verification, checkpoint persistence and resume. Count failed
   attempts and recovery costs; never compare a warm resumed run with a cold one.

The observer's off/on output check remains exact: instrumentation must not alter
the result. Cross-provider equality is a separate question. If CPU and CUDA
outputs differ, the experiment retains every arm's diagnostic timing, complete
outputs and raw numerical deltas, reports `NUMERICAL_EQUIVALENCE_UNPROVEN`, and
withholds repeated benchmark ratios. This is a conservative first experiment,
not a permanent veto on GPU research. Advance that source-bound candidate through
the existing locked-corpus numerical, downstream and musical-quality evaluation,
including its canonical candidate-output differential and bound review. Set any
approved comparison rules before collecting that qualification evidence; do not
borrow another model's tolerance or tune a threshold to the observed GPU error.

## Precision and platform constraints

- CUDA enables TF32 by default. Set `use_tf32=0`; keep FP16, BF16 and quantization
  disabled. Float32 on GPU can still differ from CPU due to reduction order.
- ORT documents approximate attention/GELU optimizations. Begin with BASIC
  graph optimization; qualify aggressive fusions independently.
- Pin ORT, CUDA, cuDNN, driver and GPU architecture. Record determinism settings
  and the actual provider for each operator. Do not silently fall back to CPU.
- GPU I/O binding can avoid host/device transfers between graphs. The existing
  CPU Deux implementation already uses direct inputs and pinned output buffers;
  I/O binding is not a new unexplored CPU optimization.
- XNNPACK has limited operator and matrix-shape support; inspect coverage before
  assuming it speeds up the attention blocks. Avoid competing full thread pools.
- NNAPI is deprecated on current Android. QNN's supported types/operators and
  Float32-to-Float16 behavior need verification on the exact SoC and build; do not
  assume an advertised NPU rate applies to these unchanged Float32 graphs.

## Companion design boundary

Use one worker for both separation and transcription so intermediate results
need not cross the network between the expensive stages. Preserve the shared
window plan, clock and postprocessing. Transport original Float32 bytes with
lossless byte compression, or prove decoder equality; a lossy conversion would
change the qualification input. Return only the validated results needed by the
unchanged downstream consumer, with complete test outputs retained for evidence.

Pair the app with a user-selected worker, authenticate and encrypt transport,
bind each job to input/model/runtime/source/configuration hashes, bound uploads
and queue size, and acknowledge cancellation and resource cleanup. Use a distinct
execution/cache identity and verify checkpoint compatibility. Keep credentials
out of the APK and repository. Do not enable remote processing by default or send
private audio during these experiments. Any app/network changes belong in a
separate reviewed implementation after the worker has demonstrated an advantage.

## Completing the vocal-stage experiment

The new Deux harness measures one complete 13-second separation passage. It
does not run GAME or measure the vocal stage. Reuse the recovered, hash-verified
five GAME graphs and configuration with the host-capable production
`android/src/com/cyberbasslord/lightforge/NativeGame.java`. Add experimental CUDA
session configuration in a copied source snapshot; preserve Float32, all eight
diffusion steps, thresholds, noise and the original passage schedule.

The prior raw-capture tools in `tools/game_benchmark/compare.py` and
`NativeGameBenchmark.java` cover encoder tensors, boundary/duration conversions,
each segmenter step, estimator scores/presence and unrounded notes.
`process_capture.cjs` checks the original 12-second core plus two-second halo,
stitching and resume. `tests/NativeGameTest.java` exercises the actual production
engine, but its final-note output alone cannot establish raw tensor equality.
Any new capture instrumentation needs its own observer-equivalence check.

Require observed GPU execution of the encoder, segmenter and estimator's heavy
work. Do not require tiny duration/boundary conversion graphs to contain GPU
matrix multiplication merely to satisfy a misplaced coverage rule. Finally run
the complete vocal stage in `web/analysis/worker.js`: classification, source-detail
extraction, full-rate GAME, detail fusion, optional semantics and saved voice.
Only that full stage can establish the V factor in the analysis budget.

## Available execution and next evidence

The [September 21 continuation](../research/performance/2026-09-21/README.md)
adds an original-consumer Deux downstream test and a source-bound GAME CUDA
harness. The five-second downstream comparison passed during execution, but
its detailed uncommitted evidence was lost in a workspace reset; this observation
is not a retained approval input. The test source is preserved for a fresh run.
The GAME harness has retained six-pass CPU evidence and a pinned Colab/Kaggle
notebook. Colab sign-in was restored September 24. The first GAME CUDA attempt
failed in a small duration conversion graph. An explicit research option keeps
both original conversion graphs on CPU while still requiring substantive CUDA
arithmetic in encoder, segmenter and estimator. All twelve passes then executed,
but the exact observer gate rejected estimator pitch differences. The remaining
fifteen captured tensors matched; this is not musical-quality approval.
The [complete rejected evidence and audit](../research/performance/2026-09-24/game-heavy-only/README.md)
are retained in the research branch. Repeatability and a separately bound
deterministic-compute setting are the next diagnostic; no tolerance was relaxed.

The first free Colab T4 experiment has now completed all eight diagnostic passes.
All 27 graphs executed CUDA arithmetic; the full source/model/audio integrity
recheck passed. Numerical equivalence remains unproven, so repeated timing was
withheld. See the [source-bound results and notebook](../research/performance/2026-09-20/colab-t4/README.md).
Use this free notebook path for the next public-demo quality experiment; Kaggle
can import the same notebook as an alternative. Neither service is being used
as an always-on app server.

The current research environment has an eight-core CPU quota and 20 GiB memory,
but no GPU device. Current Hugging Face Jobs pricing documentation permits any
account with a positive credit balance; a Pro subscription is not required. The
earlier account-plan check did not establish ineligibility. Available credit and
execution access have not been verified. Original models and the public demo have been recovered
from the published 2.3.1 APK and independently checked against their manifests.
The local operator profiler completed a fresh public-demo passage with all 27
graphs and 335 calls. Instrumented and uninstrumented outputs were byte-identical
(SHA-256 `b5db5b5f8bcc576e1af22b0a9fca837dc9e809195ada006af1581458283578b7`).
Observed host kernel-event durations were distributed as follows:

| Operator | Calls | Share of summed kernel-event durations |
| --- | ---: | ---: |
| MatMul | 13,344 | 60.14% |
| Transpose | 2,831 | 8.54% |
| Mul | 9,122 | 6.44% |
| Softmax | 3,912 | 4.59% |
| Other operators | — | 20.29% |

The uninstrumented passage took 51.99 seconds and the instrumented passage
54.17 seconds. This single diagnostic pair measures neither an optimization's
speedup nor repeatable production throughput. Instrumentation has overhead,
and host-event sums are not device-kernel or complete-analysis wall time.
The distribution supports testing whole graphs on the GPU, including layout
and elementwise work; MatMul-only offload leaves substantial work behind.

The CPU optimization controls also completed all 27 graphs and 335 calls per
run. Both profiled twins matched their respective unprofiled outputs exactly.
CPU/ALL versus CPU/BASIC differed by at most `3.5762786865234375e-7` in Float32
sample amplitude (RMSE `3.061769232727322e-8`); this is a numerical observation,
not an audible-quality finding or an accepted tolerance. The tool retained all
outputs and reported numerical equivalence unproven without performance ratios.

A real CUDA result still requires a suitable GPU runner. No paid job,
private-audio upload or hosted deployment has been started.

## Running the prepared experiment

Use the existing bootstrap scripts for the pinned JDK, Android compilation and
CPU ORT dependencies. The GPU tool additionally requires Linux, an accessible
NVIDIA GPU, CUDA 12.x, cuDNN 9.x and the pinned `onnxruntime_gpu-1.25.1.jar`.
Its official Maven URL, byte count and SHA-256 are in `GPU_RUNTIME` in
`tools/benchmark_deux_accelerator.py`; the tool checks the entire binary before
execution. It records actually mapped GPU library versions/hashes rather than
treating a driver version as a CUDA runtime version. The receipt explicitly
records that ORT deterministic compute retains its runtime default; the cuBLAS
workspace setting alone does not guarantee deterministic kernels.

Use already verified original model files and a public 44.1 kHz stereo PCM16 WAV.
Every output directory must be new. These commands illustrate the same interface
used for the local diagnostic:

```sh
python3 tools/profile_deux_operators.py \
  --models /path/original-deux-models --audio /path/public-demo.wav \
  --output /path/new-operator-profile

python3 tools/benchmark_deux_accelerator.py --cpu-control-only \
  --models /path/original-deux-models --audio /path/public-demo.wav \
  --output /path/new-cpu-controls

python3 tools/benchmark_deux_accelerator.py --check-readiness \
  --models /path/original-deux-models --audio /path/public-demo.wav \
  --output /path/new-cuda-readiness

python3 tools/benchmark_deux_accelerator.py \
  --models /path/original-deux-models --audio /path/public-demo.wav \
  --output /path/new-cuda-qualification
```

Readiness checks do not execute graphs or approve a candidate. A numerical
difference returns a nonzero status with retained evidence; missing CUDA cannot
silently become a CPU acceleration result. The full experiment runs all four
diagnostic arms before applying its conservative exact-output timing criterion.
After qualification it can run warmups and at least three alternating measured
rounds, excluding profiled runs from ratios. No result from this passage tool
grants a whole-song, Android, musical-quality or `PASS_TARGET` conclusion.

## Primary references

- [ORT CUDA configuration](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)
- [ORT graph optimizations](https://onnxruntime.ai/docs/performance/model-optimizations/graph-optimizations.html)
- [ORT I/O binding](https://onnxruntime.ai/docs/performance/tune-performance/iobinding.html)
- [ORT profiling](https://onnxruntime.ai/docs/performance/tune-performance/profiling-tools.html)
- [cuBLAS reproducibility](https://docs.nvidia.com/cuda/cublas/index.html#results-reproducibility)
- [ORT XNNPACK coverage](https://onnxruntime.ai/docs/execution-providers/Xnnpack-ExecutionProvider.html)
- [Android NNAPI deprecation](https://developer.android.com/ndk/guides/neuralnetworks)
- [ORT QNN support](https://onnxruntime.ai/docs/execution-providers/QNN-ExecutionProvider.html)
- [Hugging Face Jobs access and pricing](https://huggingface.co/docs/hub/en/jobs-pricing)

These documents were checked September 20, 2026. Current online documentation
can describe newer releases; qualification must inspect the pinned runtime and
actual traces rather than assume every documented option exists in ORT 1.25.1.
