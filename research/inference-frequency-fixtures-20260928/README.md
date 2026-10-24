# Independent original-output fixture checks

The current four-worker and eight-worker B16 candidates both reproduced the
committed original full Float32 output on two licensed MUSDB inputs. Each run
covered all 27 original graphs, 15 stages and 1,727 native calls, including the
five-frame frequency tail. Every output contained 1,146,600 finite floats
(4,586,400 bytes).

| Fixture | Start sample | Four-worker output | Eight-worker output |
| --- | ---: | --- | --- |
| Falcon | -66,150 | Exact original output | Exact original output |
| Stella | 0 | Exact original output | Exact original output |

Original output SHA-256 values:

- Falcon: `e376591b6b588fc10a9661a6fb298d6acd020be7a3cb12528891908083ded835`
- Stella: `1e3f2b6d3081adaae9855eced53a69f5b3babc381b965ccff977038383f204c3`

The unchanged [Falcon receipt](falcon/receipt.json) and
[Stella receipt](stella/receipt.json) retain input conversion provenance,
original reference bindings, graph/runtime hashes, complete profiles, source
bindings, class hashes, host observations and both successful subprocess exits.
Each directory also retains the exact original compile/process logs and frozen
source text, including the diagnostics host stub. The original reference is
`research/inference-2.4.1/separator-divergent-inputs.json`; its digest is bound in
both receipts. Baseline inference was not repeated in these fixture runs.

[Archive verification](archive-verification.json) confirms both receipts passed,
source hashes matched before/after execution and at archive time, all 51
compiled class hashes matched each receipt, and all four actual output files
matched their recorded original hashes and lengths. The archive contains 48
byte-identical original text files. Audio, PCM, compiled classes, dependencies
and model binaries are omitted. No inference was performed while archiving.

These are independent-input host correctness checks. Their single observations
do not measure a controlled speedup, sustained automatic-policy benefit,
physical-phone improvement, or production release readiness.
