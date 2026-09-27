# Original GAME CUDA research diagnostic

`tools/benchmark_game_accelerator.py` executes a copied production
`NativeGame.java`, retaining all five original Float32 graphs, all eight
segmenter steps, thresholds, noise, validation and resource retirement. It does
not edit the app. The existing Colab CUDA 12 / cuDNN 9 stack and pinned ORT 1.25.1
CPU/GPU JARs can be reused.

```sh
python3 tools/benchmark_game_accelerator.py \
  --models /absolute/original-game-models \
  --input /absolute/passage.f32 \
  --input-provenance /absolute/passage-provenance.json \
  --toolchain /absolute/toolchain \
  --output /absolute/new-game-gpu-evidence
```

Use `--check-readiness` to verify inputs and runtime discovery before graph
execution, or `--cpu-control-only` to run just the two CPU optimization controls.
The flags may be combined. `--gpu-runtime` optionally locates the already pinned
GPU JAR. Output directories must be new. This command does not download assets,
submit jobs, upload audio, or select a paid GPU.

For the explicit alternative provider policy, add `--cuda-heavy-only`. This
requests CUDA only for `encoder`, `segmenter` and `estimator`; the original
`dur2bd` and `bd2dur` graphs execute on CPU. The receipt binds the flag and each
control's requested provider for every graph. Traces must confirm CPU-only
conversion graphs and substantive CUDA arithmetic in all three heavy graphs.
The three CPU controls, four-control/twelve-pass design, models, inputs, eight
segmenter steps, unrounded comparisons and quality gates are unchanged. This
flag cannot be combined with `--cpu-control-only`.

The flag addresses the September 24 T4 diagnostic failure: the original
all-graphs CUDA request reached `dur2bd`, where CUDA `ReduceSum` rejected a
`[1, 1400, 0]` intermediate with `keepdims=false`. That run stopped after nine
CPU control passes and remains `BLOCKED_OR_REJECTED`. CPU conversion preserves
the original graph computation; it does not synthesize boundaries, pad the
input, rewrite the graph or catch an inference failure and switch providers.
The default still requests CUDA for all five graphs so the failed experiment
remains reproducible. Use a new evidence directory and rerun all twelve passes
for the alternative policy; do not combine partial old runs with new runs.

The optional research candidate `--cuda-heavy-only --cuda-deterministic` adds
`options.setDeterministicCompute(true)` immediately before CUDA registration
inside the existing heavy-graph selector. It leaves the three CPU controls and
the CPU conversion graphs unchanged. The flag requires `--cuda-heavy-only` and
cannot be combined with `--cpu-control-only`. Omitting it preserves both the
default and heavy-only generated snapshots. The receipt records
`cudaDeterministicCompute` and the requested scope. ORT documents this setting
as enabling deterministic GPU computation where possible, with a likely
performance cost; it does not guarantee that every GPU kernel is deterministic
([ORT Java SessionOptions documentation](https://onnxruntime.ai/docs/api/java/ai/onnxruntime/OrtSession.SessionOptions.html#setDeterministicCompute(boolean))).

A bounded, predeclared six-run repeatability screen motivates this candidate;
that screen is not qualification. A fresh complete four-control/twelve-pass run
in a new evidence directory is required, with the same exact observer, source,
model, input, native-library and placement gates. Do not combine the screen or
partial prior runs with that evidence. No model, precision, math, passage,
window, seed or comparison tolerance changes accompany the flag. Musical
quality, numerical equivalence, performance and the 75% target remain unproven.

The input is one original `game.js` passage: a 12-second core with up to two
seconds of real source context on either side, truncated only at the actual
source boundaries. Preserve the full source sample clock and original per-window
seed. Supply mono Float32 little-endian samples at 44.1 kHz without normalization.
The required provenance JSON is:

```json
{
  "schema": "lightforge.game-passage-input.v1",
  "pcmSHA256": "SHA256 of exact passage.f32 bytes",
  "sourceSHA256": "SHA256 of the full source file or full source PCM",
  "sourceSamples": 2646000,
  "passageIndex": 0,
  "firstSample": 0,
  "lastSample": 617400,
  "sampleRate": 44100,
  "seed": 2025,
  "language": 0,
  "derivation": "Describe the identified full source, decoding/stem derivation and slicing."
}
```

The sample numbers illustrate the first 14-second window of a 60-second source.
The full source is bounded to ten minutes for this research tool. Its declared
origin is not independently proven by the provenance file; retain the source
derivation and upstream receipts separately. Prefer the shipped public demo.
For stage-isolation comparisons, use **the same exact vocal PCM** for CPU and
CUDA. A later combined Deux+GAME experiment must separately compare each
pipeline's own derived PCM.

Each of the four controls (CPU/ALL, CPU/BASIC, GPU-package CPU/BASIC and
CUDA/BASIC) runs in three fresh JVMs:

1. Plain: the production source with only the specified provider/optimization
   change; the CPU/ALL snapshot is byte-identical to production.
2. Captured: retain every output of all 12 graph calls (16 tensors), including
   all eight segmenter outputs, and the final unrounded notes.
3. Captured and profiled: additionally record provider placement and actual
   loaded CUDA libraries.

Plain/captured runs must have identical final unrounded notes. Captured/profiled
runs must have identical raw tensors and notes. Raw intermediate tensors are
not observed in the plain run; the receipt states this limitation. No observer
can establish its own absence. GPU placement requires substantial CUDA arithmetic
in encoder, segmenter and estimator; the two tiny duration/boundary conversion
graphs may remain on CPU. All fallback events remain visible.

`NUMERICAL_EQUIVALENCE_UNPROVEN` is a completed diagnostic with observed tensor
or note differences, not an assertion of audible degradation. Differences and
all raw outputs are retained without an inferred tolerance. The original
`compare.py` is reused, including its strict stage sequence and file integrity
checks. Downstream transcription/stitching and musical-quality validation remain
separate work; do not relabel existing WASM/native replay evidence as CUDA proof.

All elapsed times are single diagnostic observations. There is no repeated timing
mode or accepted speed ratio. The command always leaves measured performance,
full-vocal-stage speed, 75% target, Android speed, musical quality and publication
approval false. It excludes classification, vocal detail, fusion, queueing and
network transfer. Cold passage wall time includes model hash verification,
session initialization, inference, validation and resource retirement.

All five sessions coexist during each production passage, so model-file sizes
alone do not predict VRAM. CUDA arena/workspace allocations and intermediate
tensors add memory. The original Java tensor validation reads outputs on the
host; cross-graph device residency has not been optimized. CUDA graphs are
disabled, Float16/quantization are absent, TF32 is disabled, and the stack is
hash-bound. These are the first controlled provider settings, not a claim of
optimal performance or universal determinism.
