# Original CPU GAME on actual separated voice

This research workflow follows a completed, independently verified CPU Deux
experiment. It runs the original GAME graphs on that experiment's actual
production `voice-full.wav`, preserving all 2,822,400 Float32 samples, five
graphs, eight diffusion steps, six original passage windows and seeds.

Three fresh JVMs execute the **default** per-passage session lifecycle:
plain, captured and profiled. No session reuse optimization is enabled. The
already qualified session-lifetime observer retains 30 unique session traces
and verifies all 72 original graph calls without moving a shared trace folder.
All twelve observer comparisons must agree, including 96 exact raw
captured/profiled tensor pairs and unrounded notes.

The driver requires an explicit immutable execution commit and tree. Every
executed source file is checked against that commit before use and retained in
the evidence. The original GAME application and model manifest must also match
the qualified application baseline. Model and runtime binaries are external,
pinned and rehashed; their bytes are excluded from exports.

## Upstream prerequisite

Both a completed independent Deux verification report and its original complete
run directory are mandatory. The driver fetches the specified verifier directly
from its immutable Git commit and reruns it before deriving any GAME input.
Failed or partial Deux captures cannot launch this workflow. The final voice
WAV, upstream execution and verifier commits, all three upstream receipts,
runtime bindings and both audit identities remain separately bound.

The source WAV must be the CPU arm's exact verified mono 44.1 kHz Float32 file.
Its PCM is copied byte-for-byte and checked through unchanged production
`WavReader` in two bounded 32-second reads. No resampling or truncation occurs.
The existing non-silent passage requirement is retained: any window with peak
at or below `1e-5` rejects this experiment before model execution.

## Run after freezing source

```sh
python3 research/performance/2026-09-25/game-separated-voice/run_local.py \
  --source-commit EXACT_DOWNSTREAM_EXECUTION_COMMIT \
  --source-tree EXACT_DOWNSTREAM_TREE \
  --upstream-source-commit EXACT_COMPLETED_DEUX_EXECUTION_COMMIT \
  --upstream-verifier-commit EXACT_DEUX_VERIFIER_COMMIT \
  --upstream-run /absolute/path/to/complete-deux-run \
  --upstream-audit /absolute/path/to/deux-audit/verification.json \
  --toolchain /absolute/path/to/pinned-toolchain \
  --models /absolute/path/to/original-game-models \
  --output /absolute/path/to/new-game-separated-voice-run
```

The completed report uses `COMPLETE_CPU_REFERENCE_DIAGNOSTIC`. An independent
audit is still required. It repeats the upstream audit, reconstructs each
generated source transformation and observer comparison, checks lifetime trace
placement, reruns the production input proof, and reproduces the complete
production GAME consumer receipt:

```sh
python3 research/performance/2026-09-25/game-separated-voice/verify_evidence.py \
  --repo /absolute/path/to/LightForge-performance-lab \
  --source-commit EXACT_DOWNSTREAM_EXECUTION_COMMIT \
  --run-directory /absolute/path/to/complete-game-separated-voice-run \
  --upstream-run /absolute/path/to/complete-deux-run \
  --output-dir /absolute/path/to/new-independent-audit
```

The consumer invokes the unchanged native callback with captured real-model
notes, revalidates all original PCM windows, and compares fresh processing,
same-adapter checkpoint resume, and a separately created checkpoint restore.
It preserves production clipping, continuation, stitching, sorting and rounding.
It performs no additional inference and retains the original runtime label as
data, without claiming Android execution.

## Preserve evidence

```sh
python3 research/performance/2026-09-25/game-separated-voice/export_evidence.py \
  --run /absolute/path/to/complete-game-separated-voice-run \
  --output /absolute/path/to/new-game-separated-voice-evidence.zip
```

The ZIP is CRC-checked and reported with its size and SHA-256. Its source-bound
manifest lists every member. The upstream raw evidence is retained separately
and must be reconstructed and supplied again for independent downstream audit;
the downstream archive does not replace or silently duplicate it.

This establishes a CPU reference for future GPU comparison. No general musical
quality, full vocal fusion, show generation, Android lifecycle, complete-analysis
timing, 75% speedup, CUDA execution or publication is approved by this workflow.
