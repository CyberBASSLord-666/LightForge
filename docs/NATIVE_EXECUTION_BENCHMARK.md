# Native execution comparison

`tools/benchmark_deux_execution.py` compares two exact `NativeDeux.java` source
snapshots using the same pinned ONNX Runtime binary, original 27 model graphs,
13-second context, source audio and source offset. The current production
transform and timing collector are common to both variants and hash-bound in
the receipt. This isolates execution changes from model or preprocessing changes.

Each run starts a fresh JVM. The default comparison performs a warmup pair,
then three measured pairs in alternating baseline/candidate order. These warmups
exercise the host and filesystem cache; each measured JVM still starts fresh. Warmups are
excluded from timing medians and retained in the output-equivalence check.
Run separate comparisons at different source offsets to cover distinct passages.

```sh
python tools/benchmark_deux_execution.py \
  --baseline-source /path/to/baseline/NativeDeux.java \
  --candidate-source android/src/com/cyberbasslord/lightforge/NativeDeux.java \
  --audio /path/to/source.wav \
  --start-sample -66150 \
  --output /path/to/new-comparison-directory
```

The source WAVE must satisfy the production stereo 44.1 kHz PCM input contract.
Negative offsets use the normal production padding. All 335 graph calls must
execute: one front, 15 batches for each time block, 11 for each frequency block,
and 11 for each output head. Missing graphs, fewer batches, nonfinite output,
incomplete output, or a difference in any output byte fails the comparison.
The scripts do not alter models, precision, thread count, sample rate, attention
context, or batching to obtain a favorable number.

The receipt distinguishes total passage wall time from time measured inside
`OrtSession.run`. Process CPU includes native worker threads; it is not the
collector's main-thread CPU observation. Linux peak RSS is observed through
`VmHWM` over the process lifetime, including JVM startup. Passage wall time and
process CPU bracket prediction and cleanup. Unsupported resource measurements
are `null`, never invented zeros.
The output directory also retains source snapshots, full float outputs and
bounded per-graph profiles. Keep these local or private when using private audio.

A passing comparison proves complete finite output equivalence for its tested
passages. It does not by itself establish an Android speedup, a whole-song
speedup, power or thermal behavior, or the project's 75% performance target.
The release still requires its normal current-source regression and Android
verification. Physical measurements are not required to run this experiment.

## Candidate selection

The production runtime is pinned to ONNX Runtime 1.25.1. Its
[session configuration definitions](https://github.com/microsoft/onnxruntime/blob/v1.25.1/include/onnxruntime/core/session/onnxruntime_session_options_config_keys.h)
support `session.dynamic_block_base`, which lets workers take smaller remaining
blocks as execution progresses. The runtime's
[performance guidance](https://onnxruntime.ai/docs/performance/tune-performance/troubleshooting.html)
describes this as a way to improve load balance and reduce latency variance.
It changes scheduling rather than neural work.

Allocation candidates can reuse memory patterns within one graph and enable
that session's CPU arena. Sessions remain bounded to one graph and close before
the next graph opens. Measure process RSS as well as run time; a faster setting
is not automatically a suitable memory tradeoff on Android.

Newer runtime documentation includes bounded spinning options that are absent
from the pinned 1.25.1 configuration definitions. Setting an unsupported string
would not establish that the requested behavior occurred. The comparison work
therefore does not rely on those options. Enabling legacy spinning also requires
checking process CPU cost, even when wall time improves.
