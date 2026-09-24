# Complete-source GAME CUDA diagnostic replay

`benchmark_game_source_cuda.py` captures the original GAME model over the complete
declared source, bounded to 64 seconds. It uses CPU/ALL and the separately
qualified heavy-only deterministic CUDA/BASIC research configuration. All five
original float32 graphs, eight steps, thresholds, source clock, 12-second cores,
2-second context, and passage seeds stay fixed. One `NativeGame` object serves
each full-source run; its original per-prediction session retirement is unchanged.

After the six plain/captured/profiled processes complete, the collector writes
an immutable experiment receipt and a separate `replay-manifest.json`. Replay it
from the **same source checkout**:

```sh
node tools/game_benchmark/replay_cuda_source.cjs \
  /path/to/evidence/replay-manifest.json /path/to/complete-source.f32 \
  /path/to/new-comparison.json
```

The output path must not exist. Exit 0 means the final production transcription
objects match exactly; 2 retains a valid diagnostic comparison whose objects
differ; 1 rejects incomplete, altered, or invalid evidence. None approves quality,
timing, an Android implementation, the 75% target, or a release.

The new `lightforge-game-cuda-source-input-1` handoff is separate from the existing
CPU/WASM schemas. It binds the complete little-endian float32 PCM, original model
manifest, collector/production/replay source hashes, canonical passage plan,
both captured aggregates, profiled aggregates, execution identities, generated
source snapshots, and the final collector receipt. Every passage must occur once,
in order, with its exact source window, seed, and PCM digest. The replay independently
checks captured and profiled tensor sizes, shapes, types, hashes and finite float
values; exact plain/captured notes and captured/profiled notes/tensor bytes must
agree. It also rechecks the collector's bound artifacts after replay. Raw CPU/CUDA
tensor equivalence remains a separate collector diagnostic.

For each arm, the wrapper calls the actual exported `processNativeRecords` with
the complete PCM and captured unrounded notes. The unchanged production adapter
checks each callback input, validates notes, clips cores, joins carried sustains,
preserves rearticulations, sorts and rounds the result, writes checkpoints, and
resumes without further callbacks. A separate call to actual `processRecords`
checks that checkpoint-only replay produces the same object. Captured notes and
the returned production objects are preserved in the comparison; exact unrounded
note/boundary differences are reported without inventing a tolerance.

The production native adapter's object contains the hardcoded runtime label
`onnxruntime-android-cpu`. The wrapper **preserves** that field and explicitly labels
it as a replay adapter label. Separate `researchExecutionIdentity` fields describe
the original Java CPU/ALL or GPU-package heavy-only deterministic CUDA/BASIC
collector arm. Bound provider-placement results come from the collector; replay
neither runs CUDA nor independently reclassifies its profiler operators.

The existing exported callback helper assumes every planned passage invokes
inference. This schema therefore rejects any passage whose peak is at or below
the production silence threshold (`1e-5`); it does not fabricate inference or
callback counts. A future silence-aware replay needs a separately reviewed
contract. A complete public mixture is still not separated-vocal quality evidence.
Separation, full vocal fusion, transfer, show generation, complete analysis timing,
and Android lifecycle behavior remain outside this diagnostic.

Focused synthetic tests exercise real callback/stitch/resume code without model
inference:

```sh
node --test tools/game_benchmark/tests/replay_cuda_source.test.cjs
```
