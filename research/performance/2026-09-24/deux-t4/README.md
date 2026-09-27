# Original Deux on T4: complete passage diagnostic — September 24, 2026

All eight diagnostic passes completed, all four plain/profiled output comparisons
match byte-for-byte, and every original graph executes substantial CUDA
arithmetic. Cross-provider numerical equivalence remains unproven. The unchanged
experiment correctly returned `NUMERICAL_EQUIVALENCE_UNPROVEN`, exit 1, and
withheld repeated timing, quality approval and publication authorization.

Source `8590ac4a67de4340857a96ffe38bae53d7d902b8`, tree
`c841bf18f91d3d04dd6daf7e886e2aa473ab8c70`, retains the original 27 Float32
graphs and complete 335-call passage. No model conversion, reduced context,
changed batch counts or deterministic-compute override was introduced. All four
controls use the same public 64-second demo input and start sample `-66150` for
the full 573,300-sample-per-stem model passage. This one passage is not a
whole-song or Android benchmark.

The [independent verification](verification.json) checks the confirmed ZIP size,
SHA256 and every member CRC; nine pinned source files; setup/runtime/model
bindings; 193 compiled artifacts; eight complete finite outputs of 1,146,600
Float32 samples each; eight native profiles; and 108 provider trace files. It
recomputes the four observer comparisons and three adjacent control comparisons
using the unchanged source-pinned helpers. CPU BASIC and GPU-package CPU BASIC
outputs match exactly.

| Comparison | Unequal samples / 1,146,600 | Maximum absolute difference | RMS difference |
| --- | ---: | ---: | ---: |
| CPU ALL → CPU BASIC | 911769 | 3.5762786865234375e-7 | 3.061769232727322e-8 |
| CPU BASIC → GPU-package CPU BASIC | 0 | 0 | 0 |
| GPU-package CPU BASIC → CUDA BASIC | 938567 | 4.470348358154297e-7 | 4.312747619637911e-8 |
| CPU ALL → CUDA BASIC | 939514 | 3.725290298461914e-7 | 4.367128794262616e-8 |

The direct CPU ALL/CUDA comparison is an additional independent diagnostic.
A separate [numerical cross-check](numerical-analysis.json) independently confirms
all eight output hashes and all seven recorded comparisons, with per-stem
error statistics retained as descriptive waveform metrics only.
These differences use the retained unrounded Float32 output. No tolerance is
fitted, and different bits alone neither establish audible degradation nor
approve musical equivalence.

CUDA placement is proven by substantial arithmetic in each of the 27 original
graphs: 68,815 CUDA kernel events and 10,232 CPU kernel events remain visible.
The three CPU controls contain CPU events only. Seven actual mapped native
library paths and their hash bindings match the retained stack: ORT 1.25.1,
CUDA 12.9, cuDNN 9.10.2 and cuBLAS 12.9.1, with TF32 disabled. Trace durations
are host-side ORT observations, not GPU device time or speedup measurements.

Single cold-passage diagnostic wall times, in seconds:

| Control | Plain | Profiled |
| --- | ---: | ---: |
| CPU ALL | 132.229729504 | 135.371717036 |
| CPU BASIC | 135.465903695 | 138.522196147 |
| GPU-package CPU BASIC | 137.445499368 | 139.871176984 |
| CUDA BASIC | 18.652717925 | 18.617820012 |

These are individual diagnostic observations. The unchanged exact-output gate
withheld repeated measurement and accepted speed ratios. Complete analysis,
network/queue overhead, physical-device behavior and the 75% goal remain
unproven.

The archive retains input/model/runtime hash bindings and the frozen harness's
final rehash attestation. Their external bytes are not included. The original
APK was hash-checked once before graph extraction; the inference harness does
not rehash the full APK afterward. Process logs are bound by the confirmed ZIP
digest; the continuation wrapper does not produce separate closed-log hashes.

The [unmodified primary receipt](primary-receipt.json.gz) is 570,008 decompressed
bytes, SHA256
`c69c686bfc312cb77443c70fd2ebb957ce668b781f543cf7bd3debafd6e6c025`.
The complete archive is preserved in 68 checked [parts](raw/manifest.json):
50,841,267 bytes, SHA256
`87e4e7010c62db52b30ea881d18b62ae3e5c93a415db618ca184ddab6041be47`.
Use `reconstruct_archive.py` with a new destination, then the retained
[verifier](verify_evidence.py), to inspect all outputs without executing inference.
