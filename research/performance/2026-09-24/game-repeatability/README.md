# Bounded GAME CUDA repeatability screen

This procedure follows the preserved twelve-pass heavy-only CUDA run that
failed its exact observer check. It uses its pinned source, original models,
input, runtime and hashes. It does not edit application code or the previous
evidence, relax tolerances, or grant quality, speed or release approval.

The fixed six-run order is A1 captured, B1 captured, A2 captured, B2 captured,
B plain, B profiled. Every run uses a fresh JVM. A is the existing heavy-only
configuration. B adds only `options.setDeterministicCompute(true)` before CUDA
registration inside the heavy-graph selector; CPU conversion graphs remain
unchanged. Both full source snapshots and compiled artifacts are retained.

The driver compares A1/A2, B1/B2 and B1/B-profiled raw tensors and notes;
B-plain/B1 compares unrounded notes. It also retains the A1/B1 difference.
All sixteen captured outputs, profile traces, actual mapped libraries and
before/after file checks remain in evidence. Any process failure or integrity
mismatch is retained. The outer process group is retired on interruption and
the final closed log receives a separate digest.

Within-mode variation demonstrates run variability under that mode. Two
matching repeats do not prove universal determinism. A stable B is only a
candidate for a fresh full qualification, not a passed observer or musical
quality gate. No causal mechanism or timing ratio follows from this screen.

Run `game_repeatability.py` in the already prepared Colab notebook after the
heavy-only experiment has finished; its exact parent hashes are required.
Then run `export_game_repeatability.py` to preserve all evidence. The embedded
driver is also available as `game_repeatability_driver.py` for review.
