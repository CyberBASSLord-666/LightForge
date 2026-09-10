Session-only staging preserves exact inference but does not solve the reported phone memory constraint.

The scratch proxy loaded each unchanged production GAME session only when next used, released the previous session before loading the next, and retained all eight segmenter calls in one session. Production source, model bytes, options, graph invocation order, inputs and arithmetic were unchanged. All 12 graph input/output hashes and all 43 unrounded notes matched the prior normal 16-second run exactly.

Peak RSS declined from 1,636,130,816 to 1,326,026,752 bytes: 19.0%, or about 296 MiB. Two staged normal peaks plus 512 MiB need 3,188,924,416 bytes (2.970 GiB), already above the recovered device snapshots of 1.90/2.25/2.94 GB available. Dense notes were not retested because the ordinary fixture is already insufficient to admit pooling under those conditions.

Releasing sessions does not return the linear WASM heap to the operating system. The staged process remained around 1.1 GiB after segmenter release, then estimator loading raised its high-water mark again. The earlier dense-estimator stress adds a separate activation burden; nothing in this probe establishes that burden disappeared.

The independent RSS watchdog adds a small V8 worker overhead absent in the old baseline, so the observed saving is conservatively biased. Recorded wall times (88.06 seconds historical baseline, 91.71 seconds staged) are not a controlled speed comparison because the root build/inference work could overlap. No production edit or dense follow-on was made.

A fundamentally different experiment would retire the entire model worker between phases, carrying only encoder tensors and boundary arrays forward as exact typed buffers. That would reset the WASM heap, but requires new worker coordination and would still need a plan to avoid two worst-case estimators concurrently. It is not implemented or qualified here.
