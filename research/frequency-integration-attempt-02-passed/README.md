# Successful combined frequency integration attempt 02

Both actual JNI processes completed successfully: the main integration suite
and a separate synchronous baseline cancellation/recovery check. The original
final receipt reports `passed=true` and `inferencePerformed=true`. The preceding
failed attempt remains preserved in `../frequency-integration-attempt-01/`.

The six main-suite outputs (reference, unknown-work, short-work, automatic,
forced-four, recovered-eight) and separate baseline recovery output all passed
independent archive-time checks: 4,586,400 bytes, finite Float32 samples, and
exact original SHA-256
`d9cd80a15c19921b2f472233a4a3bb86eec3e39aef66374a9c007b4b9efc5837`.

Both forced candidate profiles contain all 27 graphs and 1,727 calls: 60 per
temporal graph, 82 per frequency graph, 11 per head, and one front call. Four-
and eight-worker frequency configurations explicitly report B16. Baseline and
baseline recovery profiles retain 335 calls. The automatic passage observed one
complete pair and correctly did not create a fully qualified cache from it.

Actual cancellation proof covers temporal caller cancellation, owner-thread
interruption with its interrupt flag preserved, frequency caller cancellation,
and synchronous baseline cancellation. Records confirm native owner/worker
retirement, inference-gate ownership and release, and no cancelled output
commit. Baseline proof additionally confirms the retained original ORT cause,
closed RunOptions, and no suppressed cleanup failure.

Original receipt and logs are unchanged. Frozen source text, class/dependency
hashes, all seven profiles, and independent archive verification are included.
Profile text is extracted from exact receipt record strings. PCM, class, model,
and dependency binaries are omitted. No inference was rerun for archival;
current strict receipt verifiers also passed.

This is host correctness and cancellation evidence, not an Android improvement,
sustained whole-job speedup, or production release qualification.
