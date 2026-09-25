# Original GAME on T4: deterministic CUDA diagnostic — September 24, 2026

All twelve passes completed and every exact observer comparison passed. CPU/CUDA
numerical equivalence remains unproven: status is
`NUMERICAL_EQUIVALENCE_UNPROVEN`. Musical quality, complete-analysis speedup,
Android performance and publication are not approved.

Source `9ca73bb8681434f6f2dc9ce1a00ce33531a04379` requests deterministic
computation for the three heavy CUDA graphs. The original duration/boundary
conversion graphs execute on CPU. The five original Float32 graphs, input,
eight segmenter steps, thresholds, seeds and application payload are unchanged.
This is the first 14-second window of the public demo mixture, not separated
vocals or a complete song.

The [independent verification](verification.json) checks the exact archive,
source/tree/handoff, all 281 bound artifacts, twelve run receipts, eight observer
comparisons, four cross-control comparisons, provider traces, actual native
library bindings, final file rehash and both closed process logs. All four
plain/captured note comparisons and captured/profiled tensor-plus-note
comparisons match exactly. CPU BASIC and GPU-package CPU BASIC also match.

The [independent numerical check](numerical-analysis.json) confirms CPU ALL
versus deterministic CUDA produces 21 notes with exactly identical
start/end boundaries. Nine unrounded pitches differ by at most
`7.62939453125e-6` MIDI semitones. Three of sixteen captured tensors differ:

| Tensor | Unequal elements | Maximum absolute difference |
| --- | ---: | ---: |
| encoder/x_seg | 335543 / 358400 | 0.000006198883056640625 |
| encoder/x_est | 337340 / 358400 | 0.000004291534423828125 |
| estimator/scores | 10 / 22 | 0.00000762939453125 |

The other thirteen tensors match byte-for-byte. These differences are retained
without fitting a tolerance; they neither approve musical equivalence nor
establish audible degradation. Captured estimator scores include one value
outside the final accepted-note list, hence ten raw score differences and nine
final pitch differences.

Traces confirm substantial CUDA arithmetic for encoder, segmenter and estimator,
with 23,911 CUDA kernel events. There are 2,804 CPU kernel events, including
37 in the intentionally CPU-only conversion graphs. All twelve model calls and
eight segmenter calls remain present. The observed stack is ORT 1.25.1,
CUDA 12.9, cuDNN 9.10.2 and cuBLAS 12.9.1, with TF32 disabled.

Single cold-passage diagnostic times, in seconds:

| Control | Plain | Captured | Profiled |
| --- | ---: | ---: | ---: |
| CPU ALL | 31.246485115 | 31.966680819 | 31.509314689 |
| CPU BASIC | 34.818207549 | 35.853010012 | 36.043606204 |
| GPU-package CPU BASIC | 35.811773567 | 35.204077700 | 35.621627851 |
| Deterministic CUDA BASIC | 10.688814055 | 10.678547137 | 10.951721589 |

These are individual observations, not repeated timing evidence or an accepted
speed ratio. Full vocal analysis, whole-song context, transfer/queue costs,
physical-device performance and the 75% goal remain unmeasured here.

The [unmodified primary receipt](primary-receipt.json.gz) is 276,642 decompressed
bytes, SHA256
`d4a144b779b886a3b675ae0dfbf3e43160d6b5a4a7da9084951c42a016a2dc33`.
The complete archive is preserved in 41 checked [parts](raw/manifest.json):
30,318,186 bytes, SHA256
`7824b02e6f91c36574c27ff9dc7d34d8c0230cd47a88db96c00acf59d4aac66a`.
Use `reconstruct_archive.py` with a new destination, then the pinned
[verifier](verify_evidence.py), to inspect the complete outputs.
The earlier blocked and observer-rejected experiments remain separate evidence.
