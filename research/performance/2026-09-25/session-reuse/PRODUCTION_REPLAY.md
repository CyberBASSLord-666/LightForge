# CPU session reuse: production consumer replay

`replay_production.cjs` is a separate research adapter. It requires a completed
`verify_session_reuse_evidence.py` report with exact CPU default/reuse parity,
then reruns a verifier taken from an explicitly supplied immutable Git commit.
A stale report cannot authorize changed evidence. The verifier commit may be a
later correction; it never relabels the earlier execution source or changes the
run's archived files. The archived original verifier is still checked against
the original execution commit along with the other execution source files.

The adapter checks all 96 captured default/reuse tensor pairs again, keeps
unrounded notes exact, and loads the Git-verified archived
`tools/game_benchmark/process_capture.cjs` and unchanged production `game.js`.
For each arm, it replays all six actual PCM windows through the native callback,
checks the production checkpoint resume, and restores the captured checkpoints
through a separately created production adapter. The final native transcriptions
must be identical between both arms and both restore paths.

```sh
node research/performance/2026-09-25/session-reuse/replay_production.cjs \
  --repo /absolute/path/to/LightForge-performance-lab \
  --source-commit EXACT_40_CHARACTER_EXECUTION_COMMIT \
  --source-tree EXACT_EXECUTION_TREE \
  --verifier-source-commit EXACT_40_CHARACTER_VERIFIER_COMMIT \
  --run-directory /absolute/path/to/completed-session-reuse-run \
  --verification /absolute/path/to/independent-audit/verification.json \
  --output /absolute/path/to/new-production-replay
```

The output directory must be new and outside the input run. `replay.json` binds
the prior and fresh verifier report digests, separate execution and verification
commits/trees, exact verifier file digest,
production helper hashes, input PCM digest, captured passage receipt digests,
adapter digest, and final transcriptions. The independent verifier output and
its log and exact Git-sourced verifier file are retained beside it. Both audit
reports must identify that verifier's exact SHA-256. Failure leaves a rejected diagnostic report;
existing evidence is never edited.

This step executes **no model inference**. Its input is the public 64-second
mixture fixture, not separated vocals. Production runtime labels remain intact
as data and do not establish Android execution. The result does not qualify
CUDA, Android lifecycle behavior, musical quality, separation, vocal fusion,
show generation, complete-analysis timing, a 75% speedup, or publication.

Focused tests use synthetic notes and PCM only:

```sh
node --test research/performance/2026-09-25/session-reuse/replay_production.test.cjs
```
