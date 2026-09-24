# GAME session reuse: isolated host candidate

Status: **generated design, not executed or qualified**. No model quality,
timing, 75% target, Android lifecycle equivalence or release approval follows
from this proposal. The full-source baseline harness remains unchanged.
Current focused tests inspect source generation, bindings and required ownership
guards only. They do not execute Java, CUDA or native cancellation/destructors.

The original `NativeGame.predict` creates five graph sessions and retires all
five after every passage. Retaining the Java engine object does not retain those
sessions. The next bounded question is whether the same five successful sessions
can serve the complete original passage sequence without changing outputs.

`tools/game_benchmark/session_reuse_candidate.py` creates an isolated Java
snapshot from the SHA-256-pinned production engine. It uses the existing
qualified CPU/ALL or deterministic heavy-only CUDA option generator. All five
Float32 graphs, eight diffusion steps, context, seeds, tensors, note filtering
and JNI result ownership code remain unchanged. Model files are still verified
on every passage; this candidate isolates session reuse and does not also remove
model hashing. No application file is edited.

The generated constructor rejects Android contexts. A single owner thread may
process one declared source of at most 64 seconds. Every call must follow that
source's exact 12-second core, 2-second halo, language, sample count and seed.
Successful calls retain the five complete sessions. Each call still creates,
detaches and retires a fresh `RunOptions`; all tensors and results retain their
original per-call ownership. A partial session set, invalid call, inference
failure, cancellation or close makes the engine terminal. There is no reset of
the cancelled/closed flags. A new source or retry requires a fresh engine/process.

## Worker-only cancellation limitation

The production nonblocking `cancel()`/`close()` contract cannot safely be reused
unchanged when an idle engine owns persistent sessions: no active prediction
would remain to retire those resources. This candidate requests termination
immediately under the original lifecycle lock, then releases that lock and waits
on the serialized predictor monitor to drain retained sessions. Native
destructors never hold the lifecycle lock. Reentrant cancellation from the
active owner's listener leaves destruction to the active prediction's `finally`.
Every retained session gets a close attempt even if another destructor fails;
failed retirement permanently prevents `isRetired()` from returning true.

Retirement also requires an explicit lifecycle-protected resource state. An idle
engine with cached sessions remains unretired after `close()` sets its flag and
through every destructor; only a fully completed successful drain can mark the
resources retired. Unexpected drain exceptions leave retirement unconfirmed.
`isRetired()` does not inspect the session map under the lifecycle lock. A
separate drain-in-progress flag also prevents reentrant cleanup from attempting
to destroy the same resources twice.

Java's synchronized predictor is reentrant, so owner-thread callbacks are
explicitly forbidden from starting nested predictions. The guard runs before
the nested call claims `running`, changes a RunOptions owner, or enters a
cleanup scope. Reentry marks the engine cancelled and requests termination;
the outer prediction alone retains cleanup ownership. This applies to listener
and cancellation callbacks, including nested calls with invalid inputs.

**`cancel()` and `close()` may block in this candidate. It is unacceptable for
the Android app or UI/lifecycle threads.** This is only a separate bounded CLI
worker experiment. The parent process must retain its timeout and process-group
termination guard. Any app proposal would require a separately reviewed
nonblocking retirement owner, race tests and the complete existing lifecycle
gate; successful host inference cannot satisfy that gate.

## Qualification required before timing

1. Compile and inspect both generated snapshots. Preserve the original source,
   qualified option source, candidate source and generated diff hashes.
2. Use a new worker/harness and schema; do not silently substitute this generator
   into the baseline collector. Run default and reuse **within each
   provider**, on identical complete PCM and the original full passage plan.
3. Run fresh-process plain, captured and profiled modes for each combination.
   Require exact unrounded plain/capture notes and exact capture/profile tensors
   and notes, then compare default/reuse raw tensors and unrounded notes for each
   passage. Keep numerical mismatches as diagnostics; do not introduce a new
   tolerance or admit timing because production output rounds the difference.
4. Preserve all 16 tensors per passage, five graph traces, model-call counts,
   provider placement, loaded-library inventory and before/after source, model,
   runtime and PCM bindings. Profiling sessions now live across passages: the
   old collector's assumption of five closed trace files **after every passage
   is invalid**. A new observer must partition full-session trace events by
   source-bound passage markers and verify totals, without changing inference.
5. Fault-test initial/partial session creation, invalid input, inference failure,
   per-call `RunOptions` retirement failure, session retirement failure,
   cross-thread cancellation, reentrant listener cancellation, idle cancellation
   and final close. Pause an idle destructor and query retirement concurrently;
   inject failed and unexpectedly throwing drains; attempt nested predictions
   from both listener and cancellation callbacks. Assert the outer RunOptions
   remains owned until outer cleanup and each session is drained once. Assert
   every owner is retired or retirement is explicitly
   unconfirmed, no retired object is reused, and a fresh engine restores the
   original empty state. Source-level tests alone do not prove JNI behavior.
6. Only after within-provider observer and default/reuse equivalence gates pass
   may a separate repeated timing protocol be proposed. Complete-source GAME
   time is still not full vocal-stage or whole-analysis time. Keep broader
   musical quality, end-to-end overhead and the 75% target unapproved.

Example generation, with output in a new scratch directory:

```sh
python3 tools/game_benchmark/session_reuse_candidate.py \
  --variant cuda_basic --source-samples 2822400 --language 0 \
  --output /tmp/lightforge-game-session-reuse-cuda
```

The command only writes the isolated snapshot, a diff from the already-qualified
provider variant and a `GENERATED_NOT_QUALIFIED` metadata receipt. It does not
compile, run, time, upload, modify a baseline, or publish an application.
