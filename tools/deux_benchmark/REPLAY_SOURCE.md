# Complete-source Deux consumer replay

`replay_source.cjs` connects a completed, source-bound native Deux CPU/CUDA
capture to the original production consumer. It never loads an inference model.
The admitted input is the pinned public 64-second stereo WAV and all twelve
original, complete 13-second passage captures for every run in the selected
completed scope. A paired CPU/CUDA scope requires four runs: CPU plain, CPU
profiled, CUDA plain and CUDA profiled. An explicitly completed CPU-only scope
requires exactly CPU plain and CPU profiled; it cannot contain a CUDA result or
cross-provider comparison. Missing or malformed captures fail closed. The
original Java execution evidence and provider placement remain the
collector's responsibility; this tool additionally byte-compares every retained
plain/profiled passage and rechecks the completed artifact inventory.

```sh
node tools/deux_benchmark/replay_source.cjs \
  /path/to/completed-collector-output \
  /path/to/glass-castle.wav \
  /path/to/new-replay-output
```

The destination must not exist. In the paired scope, exit `0` means all three
final CPU/CUDA stem PCM streams are byte-identical; exit `2` means a complete,
valid diagnostic found differences. For CPU-only scope, exit `0` means its
consumer and checkpoint checks completed; cross-provider comparison is `null`
and `gpuCaptureConsumed` is `false`. Exit `1` means validation or execution
failed. Neither success code
approves quality, speed, Android integration or publication. A failed replay does
not write a completed receipt.

## Original consumer and recovery

The tool loads these files without editing or rewriting their arithmetic:

- `separator-deux.js`: actual passage scheduling, native callback, overlapping
  cores, complementary crossfades, chunk clock and checkpoint restoration.
- `wav-reader.js`: original stereo input decoding, including each boundary's
  original zero padding. Each native/Java decoded-input hash must match it.
- `work-store.js`: actual checksummed, identity-bound binary checkpoint files.
- `stem-cache.js`: actual transaction, Float32 encoding, centered half-rate FIR,
  completion hashes, fresh verification and reader APIs.

Every arm runs through four consumer scenarios: fresh completion; interruption
before the seventh callback; restart from the six committed binary checkpoint
files followed by the remaining six captures; and restart from all twelve saved
checkpoints with no native callbacks. Restart creates a new JavaScript realm
and new file handles from committed file bytes. It cannot reuse an earlier
checkpoint object or pending overlap buffer. Both recovery scenarios must
reproduce all fresh chunk and WAV bytes exactly. An interrupted cache must lack
a completed stem marker.

The storage adapter is an in-memory implementation of the File System Access
operations the original modules use, with atomic visibility on close. It does
not establish physical OPFS durability, storage quota behavior or Android
lifecycle correctness. The replay environment supplies a fixed zero clock for
reproducible cache metadata. Its production `analysisSeconds` is deliberately
unmeasured and must never be used for timing comparisons.

Each CPU/CUDA arm uses a separate source-bound research cache identity. The
unchanged production result still says `onnxruntime-android-cpu`; the report
explicitly identifies that as the adapter's label and records the actual
collector runtime/provider separately.

## Retained boundary for the next stage

For each arm, the output includes a complete `voice-full.wav` (44.1 kHz
Float32), `vocals.wav` and `accompaniment.wav` (22.05 kHz Float32), together with
their production completion descriptors, complete sample counts, full-voice PCM
hash, input passage hashes and checkpoint hashes. All written WAVs are reopened,
checked as regular files, size-checked and SHA-256 checked before the final
receipt attests its relative output-file inventory. A fresh instance of the
production cache must open and verify all three WAVs. Its fullVoice reader and
both half-rate stem readers must return their exact stored PCM bytes.

The next vocal experiment must use **that arm's own verified separated voice**
for full-context classification, detail extraction, fresh GAME inference and
fusion. Existing GAME captures inferred on the original mixture cannot supply
those outputs. This replay performs none of those next-stage operations and
does not measure end-to-end analysis or the 75% target.

## Focused verification

```sh
node --test tools/deux_benchmark/tests/replay_source.test.cjs
```

The tests use explicitly synthetic model outputs, including adjacent passages
that disagree. They cover the full twelve-passage clock and odd final chunk,
real binary-checkpoint interruption/restart, missing captures, silence,
nonfinite output, rejected checkpoint corruption, rejected completed-cache
corruption and untoleranced descriptive deltas. They are consumer correctness
tests and provide no inference-quality or performance evidence.
