# Nomination memory and shortlist verification — 2026-09-29

The current source passed seven focused scenarios using the original ONNX Runtime
1.25.1 front and temporal graphs. This archive is a memory, exact-activation and
control-flow check. It is **not performance, phone, complete-passage, or release
qualification**. No APK was built by this harness.

## Actual observations

| Scenario | Temporal trials | Maximum workers | Direct-buffer growth | Outcome |
| --- | ---: | ---: | ---: | --- |
| Four-only headroom | 2 | 4 | 7,993,344 B | Four nominated |
| Eight loses eligibility before its trial | 2 | 4 | 7,993,344 B | Four retained |
| All candidates lose eligibility before four | 1 | 0 | 0 B | Baseline; no candidate allocation |
| Eight loses eligibility at final selection | 3 | 8 | 18,651,136 B | Four retained |
| Caller cancellation after four | 2 | 4 | 7,993,344 B | Failure propagated; no winner |
| Optional deadline after four | 2 | 4 | 7,993,344 B | Baseline; no winner |
| Check IOException after four | 2 | 4 | 7,993,344 B | Failure propagated; no winner |

Every current trial used the same original activation buffer object. Observed JVM
direct-buffer growth was exactly the additional reusable worker input/output
slots, with no second 79,933,440-byte activation. All reconstructed full finite
Float32 front activations had SHA-256
`9c0649696e92e2dd594d5d2d19c70bf7a3efd484a867bd29d9d4d09b26f53d49`.
All complete finite temporal results had SHA-256
`5d77af0a6839ae3eaaccea74eb76a5d4869b7afa7d0679a78240334cf6b11210`.
These are entire activation/result hashes, not sparse samples or quantized values.

The unchanged original demo audio, all 27 model files, runtime/test dependencies,
source snapshots, and compiled-class inventory were bound before execution and
checked again afterward. Only front and block-00-time execute in this narrow
harness; complete-passage output and during-JNI cancellation are separate checks.

## Synthetic controls and limits

Available memory is deliberately supplied through the existing host-only adapter.
The harness retains the production 512 MiB reserve and original 1,536/2,048 MiB
candidate headroom thresholds. It does not manufacture an Android memory reading.

The baseline trial contains an explicit two-second observer delay to make the
winner-selection fixture independent of ordinary benchmark noise. The final
selection scenario instead uses six seconds for baseline and three for four
workers; eight has no injected delay. Observed four/eight boundary spans were
4.618/1.088 seconds in that scenario. These spans include observation work and
exclude temporal session creation, so they are not the production trial clocks.
No timing in this archive supports a speedup claim.

Cancellation, optional deadline, and runtime error are injected through the
cooperative Check callback after actual completed graph trials. The runtime
case is an injected IOException, **not a native OrtSession.Run failure**. The
harness verifies original failure message/cause/suppressed shape, closed
RunOptions, observed worker retirement, and absence of a persisted qualification
cache. Its gate-release field describes the harness-owned gate; it does not
substitute for production ownership or during-JNI cancellation tests.

## Historical negative controls

`historical-negative-control/receipt.json` deliberately remains `passed: false`;
both processes returned exit code 1. The overridden NativeDeux source is the
unchanged file from commit `6a91949a`, SHA-256
`314a395c8bd28c8841d5a2afefdb03779b1929f9beac3b1200dde7d03ee996d6`.
Other inputs use their recorded source bindings. This is a disclosed historical
single-file control, not a historical release rebuild.

Both old-source cases observed an activation-buffer replacement and **87,926,784
bytes** of direct-buffer growth. The difference from the current four-worker
7,993,344-byte observation is exactly **79,933,440 bytes**, the removed activation
copy. The old four-only case nominated four, while the memory-drop case latched
baseline. Raw failures are retained without reclassification.

The old algorithm runs front once and copies its saved activation for each trial;
the new algorithm reconstructs front before each trial. Consequently the new
observer also reports graph-transition/count violations against the old source.
Those violations are not independent evidence of incorrect old tensor geometry
or isolated fallback regressions. The actual allocation/identity observations
are valid for both implementations.

## Reproduction

```bash
python3 tools/verify_deux_nomination.py --output /dev/shm/lightforge-nomination-fresh
```

For the same disclosed negative control, extract the original NativeDeux.java
from commit 6a91949a to a scratch path and pass it with
`--reference-native-deux /absolute/path/NativeDeux.java --cases four-only drop-eight-before`.
Use a new output directory; retained observations are never overwritten.
The historical override preserves actual failures and returns a failing exit code.

The archive contains exact receipts, process/compile logs and frozen UTF-8 source
snapshots. Compiled binaries, model files, audio and private data are excluded.
`archive-inventory.json` lists the bytes and SHA-256 of every other archive file.
