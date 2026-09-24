# Complete public-source GAME diagnostic

These scripts extend the retained single-passage GAME experiment to the entire
64-second public `glass-castle.wav` mixture. They do not change application code,
model files, diffusion steps, release policy or the original signing identity.
This is GAME-only research; the fixture is not separated vocals. No speed ratio,
75% target result, general musical-quality approval or publication decision is
produced by this workflow.

## Frozen collector

- Source: `3797783e703738d28af1df9b722f5f4e886b99f2`
- Tree: `47fa69218b35ff8e1644e123ee8170983a884f8b`
- `tools/benchmark_game_source_cuda.py` SHA-256:
  `a75b75aecca793622f2eb8874fd1aef1ac133146b90387b3c36c276adc927959`

The orchestration script can be committed later than this collector. Its actual
executed bytes and digest are copied into the evidence. It checks the collector's
immutable Git commit, tree and harness digest before compiling or running it.

## Fresh setup and execution

`colab_setup.py` downloads the notebook frozen at
`3d525cd16ae7688777a2ca677db7fecbf76c4e9e`, verifies its complete byte hash, and
executes unchanged setup cells 2, 4, 6, 8, 10, 12, 14, 16 and 18. It does not run
any old diagnostic cells. It refuses an existing setup directory. If those exact
reviewed cells have already completed in a fresh runtime, pass their actual
`RUN` directory directly to `colab_run.py`; do not repeat setup.

Run the following with the actual fresh setup path:

```sh
python colab_run.py \
  --setup-run /content/lightforge-game-gpu-qualification/evidence/20260924T041844Z-771ac084 \
  --source-commit 3797783e703738d28af1df9b722f5f4e886b99f2 \
  --source-tree 47fa69218b35ff8e1644e123ee8170983a884f8b \
  --harness-sha256 a75b75aecca793622f2eb8874fd1aef1ac133146b90387b3c36c276adc927959
```

The wrapper validates the new setup's actual receipts and public asset/runtime
hashes. It does not reuse earlier runs' setup receipt hashes. It installs the
hash-pinned Node 22.19.0 binary, retains every source sample, and independently
compares the complete Float32 mixture against two consecutive 32-second reads
through the actual production WavReader and JavaScript averaging. Each read
respects the unchanged 40-second production bound. A separate explicitly synthetic schedule-only probe
checks the original six 12-second cores, 2-second halos and passage seeds.

Six readiness snapshots compile before inference. Then six fresh JVM runs cover
CPU/ALL and the previously qualified deterministic heavy-only CUDA settings,
each plain, captured and profiled. Each JVM uses one NativeGame object across
six passages, while the original engine still creates and retires graph sessions
for every prediction. This does **not** test persistent session optimization.
The current experiment rejects any wholly silent passage before execution.

Successful collector observer and integrity checks permit a separate replay of
both arms through unchanged production stitching and checkpoint resume. Replay
exit code 0 means exact final transcription; 2 means different final
transcriptions; 1 means invalid replay. A valid result with differences remains
a diagnostic. Raw tensor and unrounded-note differences are retained, with no
new tolerance or quality approval.

On interruption, the wrapper first sends SIGINT so the collector can retire its
separate-session JVM in its own cleanup. After a bounded wait, fallback cleanup
is restricted to descendants actually observed under that launch, checking PID
start times before signaling them. Completed and failed evidence use separate
new directories and are never overwritten.

## Export

After `driver-receipt.json` records completion or failure, run:

```sh
python colab_export.py --run /content/lightforge-game-gpu-qualification/evidence/ACTUAL-RUN --download
```

The explicit export allowlist includes this public fixture's PCM, exact text
source snapshots, compiled research classes, receipts, raw tensor bytes and
provider traces. It excludes APKs, original model binaries, runtime libraries,
credentials and private audio. `archive-manifest.json` inventories the bytes and
SHA-256 of every member except itself. The exporter verifies ZIP CRCs and prints
the final archive size and SHA-256. Failed runs remain marked failed.

No experiment result is asserted by this README. Read an independently verified
run receipt before drawing conclusions.
