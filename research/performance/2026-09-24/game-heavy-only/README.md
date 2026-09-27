# GAME T4 heavy-only CUDA diagnostic

Executed September 24, 2026 on free Colab Tesla T4, driver 580.82.07,
15,360 MiB reported GPU memory. All twelve passes executed, and all bound
inputs passed the final recheck. **The exact observer gate rejected the run:
`OBSERVER_COMPARISON_INVALID`.** No quality approval or speedup is established.

## Configuration and observed execution

Execution source is `8590ac4a67de4340857a96ffe38bae53d7d902b8`, tree
`c841bf18f91d3d04dd6daf7e886e2aa473ab8c70`. The input derivation remains the
unchanged, retained `d9b42bb79145cfe81367fd70e2ca0ff7f4d52c12` evidence;
[source-handoff.json](source-handoff.json) binds these separately.

The explicit `--cuda-heavy-only` option retains the five original Float32
graphs, input samples, eight diffusion steps, thresholds and application
computation. It requests CUDA for encoder, segmenter and estimator, and CPU
for original `dur2bd`/`bd2dur` conversion graphs. It does not catch an error
and substitute an answer. The [earlier all-graphs CUDA attempt](../initial-blocked/README.md)
remains preserved as a failed experiment.

Traces establish substantive CUDA arithmetic in all three heavy graphs and
CPU-only execution in both conversion graphs. The CUDA trace also contains
2,804 CPU kernel events; this is not full GPU residency. The independent
audit checked the complete archive, source/handoff, 281 bound artifacts,
twelve run receipts, 128 captured tensor files, four placement summaries
and ten actual native-library bindings.

## Why the gate rejected it

All six CPU observer comparisons passed exactly. Both CUDA observer pairs
failed their exact unrounded-note check. CUDA captured versus profiled
outputs differ only in `estimator/scores`: nine of 22 Float32 values differ,
maximum absolute difference `1.1444091796875e-5`, RMS difference
`4.3797340186084705e-6`. The other fifteen captured tensors match exactly.

All CUDA modes produced 21 notes with identical boundaries. Plain versus
captured has twelve pitch differences, maximum `1.9073486328125e-5` MIDI
units; captured versus profiled has nine, maximum `1.1444091796875e-5`.
These are observed differences, not accepted tolerances or a finding of
audible degradation. The three single runs do not distinguish ordinary
run-to-run variability from an observer-associated effect.

Single cold-passage wall observations, not admitted benchmark results:

| Path | Plain seconds |
| --- | ---: |
| CPU / ALL | 31.198 |
| CPU / BASIC | 35.422 |
| GPU package / CPU / BASIC | 33.691 |
| GPU package / CUDA / BASIC, CPU conversions | 10.868 |

No speed ratio is accepted. The experiment covers the public demo's first
14-second **mixture** passage, not separated vocals, the complete vocal
stage, a whole song, transfer overhead or Android performance.

## Evidence and continuation

- [Independent rejected-run diagnostic](rejected-run-diagnostic.json)
- [Unmodified primary receipt, gzip](qualification-receipt.json.gz)
- [Retry procedure](colab_retry.py), [export](colab_export.py), and
  [strict qualification verifier](verify_evidence.py). The verifier correctly
  rejects this archive; the independent diagnostic does not override it.

The complete archive is 30,318,690 bytes, SHA-256
`9c14e097c11c83d736aaf1ef4843a1a66bf7be9a08f9f18780440923be74425b`.
Persistent file saves failed, so all original bytes are retained as ordered
parts in `raw/`. Run `python3 reconstruct_archive.py NEW_OUTPUT.zip` here
to verify every part and reconstruct the exact archive. It contains public
fixture data, outputs, traces, logs and source snapshots; no private audio
or credentials.

Next, compare repeated unchanged CUDA runs and a separately identified
deterministic-compute setting. The installed, hash-pinned ORT 1.25.1 Java
JAR exposes `setDeterministicCompute(boolean)`, also documented in the
[official Java API](https://onnxruntime.ai/docs/api/java/ai/onnxruntime/OrtSession.SessionOptions.html).
This is an available setting to investigate, not a guarantee of universal
determinism. Preserve the rejected evidence, retain the exact observer gate,
and require a fresh complete qualification before advancing a new candidate.
