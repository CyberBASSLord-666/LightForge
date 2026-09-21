# GPU qualification continuation

Development research. No complete-analysis speedup, CUDA quality approval,
Android result or publication authorization is established here.

## Observed downstream result and evidence retention

The September 20 continuation executed the captured production CPU/ALL and
CUDA/BASIC Deux outputs through the original consumer and actual downstream
models. The unchanged comparison returned `EXCERPT_SENSITIVITY_PASS`.

The consumer retained the original 64-second source clock, emitted its first
five-second chunk, and stopped when it requested the uncaptured second passage.
Both measured stems then passed through centered resampling, Frame-MN10,
vocal-detail extraction, eight-step GAME and fusion as a bounded excerpt.
This does not preserve full-song downstream context or test overlapping passages.

Observed results, retained in the execution/review conversation:

- Both arms executed Frame-MN10 once and all GAME graphs: encoder once,
  duration/boundary conversions once each, segmenter eight times, estimator once.
- Both produced 25 final notes, one phrase and 4.72 seconds of fused-note coverage.
  Entire serialized transcription and fused-vocals objects matched.
- Raw, unrounded GAME pitches differed by at most `1.14440918e-5` semitones;
  raw timing matched. These differences were not discarded by the experiment.
- Independent review reran the unchanged comparator and checked all bound
  sources, assets, raw inputs, outputs and final integrity checks.
- The completed downstream receipt had SHA-256
  `0bb18b68ae6f330a9f6e405d91760a0e32459792936873823a3c59b96ed502fd`.

**Retention limitation:** a stalled browser file transfer was followed by a
workspace reset before these new receipts and outputs were committed. The full
files are currently unavailable. The observations and digest above are a
recovered execution note, not a reconstructed receipt or independently
re-verifiable retained result. The test source was recovered from recorded
edits. Repeat the experiment and preserve its complete evidence before using it
as an approval input. A repeat is a new run, not the original evidence.

The [earlier Colab report](../2026-09-20/colab-t4/README.md), full qualification
receipt and reusable notebook were already committed and remain available.
Attempts to persist its raw ZIP failed; that local ZIP was also lost in the
reset. A digest alone cannot recover its waveform or trace bytes.

## Singing-model GPU experiment

The new [GAME harness](../../../tools/game_benchmark/GPU_QUALIFICATION.md)
executes copied production `NativeGame.java` with four controls. Each control
has plain, captured and captured/profiled executions. It checks all five graphs,
12 inference calls, eight diffusion steps and 16 captured tensors. Production
application code and existing admission/publication rules are unchanged.

Before the reset, eight focused tests and compilation of all 12 snapshots passed.
Six real CPU control passes completed on the first 14-second GAME window of
the public demo mixture. CPU/ALL and BASIC produced 21 notes with identical
boundaries and maximum pitch difference `0.00000762939453125` semitones.
Both observer triples and the final integrity check passed. That receipt had
SHA-256 `253a5212d04a990f6e023e1e9019e7021e7d87894bc1038b957381e49c051ab2`;
its complete contents were also lost. It is not recreated from these observations.

GPU GAME execution has not completed. Colab requires renewed sign-in after the
session reset. The next GPU run must record actual heavy-kernel placement,
all output differences, model/runtime/source hashes and diagnostic wall times.
It must retain CPU fallback and any failures. GAME-only timing does not measure
the complete vocal stage, network overhead or the 75% complete-analysis target.

## Reproduction

```sh
node tools/compare_deux_downstream.cjs \
  --evidence PATH_TO_DEUX_QUALIFICATION_DIRECTORY \
  --audio web/demo/glass-castle.wav \
  --output NEW_DOWNSTREAM_DIRECTORY

python3 tools/benchmark_game_accelerator.py \
  --models PATH_TO_ORIGINAL_GAME_MODELS \
  --input PUBLIC_PASSAGE_FLOAT32LE \
  --input-provenance INPUT_PROVENANCE_JSON \
  --toolchain PINNED_TOOLCHAIN_DIRECTORY \
  --output NEW_GAME_EVIDENCE_DIRECTORY
```

The downstream driver requires both complete, hash-bound captured Deux outputs;
the compressed receipt alone is insufficient. Use the pinned public notebook to
obtain a new complete capture if the original archive cannot be recovered.
