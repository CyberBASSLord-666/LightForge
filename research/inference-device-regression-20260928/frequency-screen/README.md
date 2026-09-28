# Original frequency graph exploration

This isolated host experiment changes independent frame batching and CPU work
scheduling only. It does not modify the original model, production runner,
runtime, precision, 60-band attention context, or 1301-frame coverage. These
results are promising graph-level observations, not Android, complete-passage,
sustained-performance, or release qualification.

The Java harness uses the unchanged `NativeDeuxTransform`, original front graph,
and complete original block-00 temporal B4 execution to capture the first
frequency graph input from the demo at sample 661500. Every frequency arm starts
a fresh JVM and session, reads this identical input, and runs all 1301 frames.
The baseline uses batches of 128 and intra-op 4. Candidates use a shared session
with intra-op 1 and four or eight bounded workers with private pinned buffers.
The original CPU arena, memory pattern, ALL_OPT, sequential execution, and
disabled spinning settings are retained. Each timer includes session creation,
bound tensor work, output copies, complete worker retirement, and session close;
immutable input loading and final output hashing are outside every arm timer.

Two alternating AB/BA pairs were observed per candidate, without warmed-session
timing. Every one of the 24 complete output tensors was finite and bit-identical:
`709a997e152921fa1ecb43ee9945156a1ad24820597b6bfe758a8e549ad8b9b8`.

| Batch / workers | Candidate seconds, two runs | Paired wall reductions | Candidate process peak RSS |
| --- | --- | --- | --- |
| 1 / 4 | 0.850, 0.817 | 41.09%, 41.73% | 258–259 MB |
| 1 / 8 | 0.560, 0.621 | 58.95%, 52.94% | 271–272 MB |
| 16 / 4 | 0.748, 0.801 | 42.36%, 45.74% | 336–339 MB |
| 16 / 8 | 0.538, 0.529 | 60.72%, 62.85% | 405–414 MB |
| 32 / 4 | 0.852, 0.852 | 40.37%, 39.02% | 413–434 MB |
| 32 / 8 | 0.687, 0.640 | 46.97%, 55.18% | 577 MB |

The adjacent baseline arms took 1.295–1.476 seconds and 498–500 MB peak RSS.
RSS is whole-process peak, not an incremental arena allocation. Shared cgroup
throttled time and memory-event counters did not increase across any measured
arm. Children were constrained to seven observed CPUs, reserving one CPU of the
host quota. Raw counters and source, bytecode, input, model, and runtime hashes
are retained in both receipts.

Batch 16 merits full-run qualification. It uses 82 calls per frequency graph,
compared with 1301 for batch 1 and 11 for the baseline. Its slots fit within the
existing temporal worker direct-buffer capacity. This is a design opportunity,
not a production admission: all twelve frequency layers, complete final PCM,
multiple independent inputs, Android resources, cancellation, and actual
sustained wall time still need validation. The memory admission thresholds must
remain unchanged. None of these graph timings may be multiplied into a claimed
whole-show speedup.

Reproduce with the existing pinned toolchain and original restored model assets:

```sh
python3 research/inference-device-regression-20260928/frequency-screen/run_screen.py \
  --output /tmp/frequency-b1-new.json --work /dev/shm/frequency-b1-new \
  --batches 1 --repeats 2
python3 research/inference-device-regression-20260928/frequency-screen/run_screen.py \
  --output /tmp/frequency-b16-b32-new.json --work /dev/shm/frequency-b16-b32-new \
  --batches 16 32 --repeats 2
```

Use new output paths. The harness refuses to overwrite a receipt. It is a
research-only implementation; production worker cancellation and error
aggregation must use the production ownership helpers, not copy this harness.

## First complete four-worker check

`complete-four-smoke/` preserves a subsequent exploratory run through all 27
original graphs using an immutable compiled snapshot of the combined temporal
B1 and frequency B16 runner. Its complete 4,586,400-byte output was finite and
exactly matched the original demo reference SHA-256
`d9cd80a15c19921b2f472233a4a3bb86eec3e39aef66374a9c007b4b9efc5837`.
The profile contains all 27 graphs and 1,727 calls. The observed runner wall time
was 36.591 seconds, but there was no adjacent baseline and this is not a speedup
qualification. Telemetry and verification source were still changing afterward.

The original smoke and compile receipts, profile, logs, all frozen source text,
and hashes of the compiled class closure are archived together. `archive.json`
records independent checks of their linkage, full output size/hash/finiteness,
and graph call geometry. The original compile-only receipt intentionally retains
`passed=false` and `inferencePerformed=false`; the separate smoke receipt records
the subsequent successful inference. The PCM itself is omitted from the archive.
