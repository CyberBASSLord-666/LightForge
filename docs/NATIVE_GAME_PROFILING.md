# Native GAME passage profiling

Native GAME emits one `native-game-profile-v1` diagnostic record after each
native call has reached its terminal state. A call processes one passage or an
eligible pair of equal-length passages. The same record contributes to the
job's durable native summary under route `native-game-v1`, independently of
verbose trace rotation. It contains no audio, inferred notes, seed, source
filename or job identifier.

The observer does not alter the five pinned Float32 graphs, eight diffusion
steps, inputs, thresholds, tensor operations or thread configuration. A paired
call loads five sessions once and runs the two original passages sequentially,
with independent tensors, boundaries and seeds. All engine-owned sessions and
RunOptions retire before either result becomes available. Cancellation and
unconfirmed native retirement retain
the existing gate and crash-lease rules.

| Field | Measurement scope |
| --- | --- |
| `wallMs` | Worker call, from before PCM reading through terminal state publication; excludes bridge upload before worker submission |
| `batchPassages` | One for unary execution, two for an eligible pair; five session initializations serve 12 or 24 original graph calls respectively |
| `readWallMs`, `waitWallMs` | PCM read/validation and process inference-gate wait |
| `engineInitWallMs` | Manifest validation and engine construction |
| `modelPrepareWallMs` | Complete cache integrity scan, plus extraction/verification when models are absent |
| `runtimeInitWallMs` | ONNX Runtime environment lookup/loading |
| `modelInitWallMs`, `sessionInitCount` | Session/options creation and options retirement, separately from model preparation |
| `inferenceWallMs`, `inferenceCount` | Sum of native `OrtSession.run` intervals, including a failed or cancelled attempted call |
| `inferenceProcessCpuMs` | Process CPU accumulated during those kernel intervals, including ORT workers and other app threads |
| `cleanupWallMs` | Final session/RunOptions retirement; intermediate tensor/result retirement is outside this field |
| Per-graph `InitWallMs`, `RunCount`, `RunWallMs`, `RunProcessCpuMs` | Fixed entries for encoder, dur2bd, segmenter, bd2dur and estimator |

Process CPU comes from Android's elapsed process CPU clock, in millisecond
resolution. The host proof can use the JVM process CPU clock. Unsupported,
failing or regressing clocks report `unavailable`. Process CPU can exceed wall
time when multiple cores work concurrently; it is not isolated engine CPU or
GPU/NPU utilization. A worker-thread CPU estimate is deliberately unavailable.
Provider identity reports the configured CPU execution backend, not accelerator
utilization. Untouched timing categories remain `unavailable`, rather than
appearing to have zero cost.

The fixed topology keeps the final record below the diagnostic message limit.
Per-kernel log writes are unnecessary: timings are accumulated in memory, and
the terminal record is immutable. Fatal native process termination can prevent
the final record; the existing crash lease and process-exit diagnostics remain
the evidence for that failure.

`tests/test_native_game_profile.py` exercises independent clocks, eight-step
aggregation, missing/regressing CPU telemetry, bounded graph names and immutable
receipts. The production task lifecycle proof additionally checks one durable
summary per retired call and excludes private inputs. These observer tests
are not model-output equivalence or an inference performance benchmark.

No engine-owned native resources remain resident between calls. Pairing shares
setup only within one bounded call. The [host comparison](../research/throughput-20261026/README.md)
retains both the slower mixed-length experiment and the equal-length result;
the app schedules only the latter geometry. These measurements do not establish
phone memory, thermal behavior or complete-analysis speed.

The [host option screen](../research/inference-2.4.1/game-options-screen.json)
tested dynamic scheduling and arena/memory patterns independently. Dynamic
variants changed raw Float32 outputs and unrounded notes and were rejected.
Arena/memory patterns preserved all tested outputs but did not show consistent
improvement. No tested GAME option became a production default.
