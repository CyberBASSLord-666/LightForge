# Physical-device probe run01 — historical, incomplete

The first phone run produced one exact-output, complete-passage comparison with
**24.56% lower candidate wall time**, confounded by unequal model-file preparation.
It does not isolate a scheduling improvement. It did not admit ordinary accelerated
passages: the frozen policy latched `baseline`, reason `payback-unavailable`,
after that first comparison. The operator cancelled during the fifth passage;
four of the planned 35 completed. This is neither sustained qualification nor
measured end-to-end improvement.

## Evidence identity

The filename prefix identifies source-receipt SHA256 `4a25e06032a3…`, not the
current worktree or a production release. The original `device-probe-build.json`
and `device-probe-sources.json` remain unchanged.

| Artifact | SHA256 |
| --- | --- |
| [Raw exported receipt](device-probe-4a25e06032a3-run01.raw.json), 179,428 bytes | `3635d132c18e2dc87a99b7f94ead8ca3a537769bbee23f221d8c4afd17743276` |
| [Historical-binding analysis](device-probe-4a25e06032a3-run01.analysis.json), 30,080 bytes | `d71366d303c6998ee065856b84d8f8b042a0837e528e77837836c73e0d3e497a` |
| Installed diagnostic companion APK | `a68ab0690f0ade0153fd7edb21e4b86c86cbe0eccbceb98d339162d1dd71d274` |

The analyzer verified the retained APK, 15 frozen Java sources, 67 compiled
classes and their JAR, runtime, fixture and model-manifest identity. Historical
integrity passed without errors or warnings. Its explicit current-source gate
failed because `NativeDeux`, `NativeInferenceProfile` and `NativePassagePolicy`
had changed. Historical evidence does not qualify those changes.
Those integrity flags do not mean the timing comparison is free of confounds.

## Observations

| Measurement | Result |
| --- | ---: |
| Entire cancelled run | 320.225 s |
| Pair ordinal / workers / order | 0 / 4 / baseline first |
| Complete baseline arm | 64.104899455 s |
| Complete candidate arm | 48.358257794 s |
| Observed arm wall-time reduction, cache-confounded | 24.563866% |
| Pair extra cost | 48.372028159 s |
| Cumulative policy extra cost | 53.221545032 s |
| Reported accrued projected savings | 0 s |

Both paired arms reported finite, bitwise-identical full outputs, full geometry
and fresh sessions. All four completed production profiles retained 27 sessions,
335 graph calls and 12 baseline temporal session attempts; none reported ordinary
four-worker or eight-worker sessions. Candidate probe graphs are separate from
those production totals. Extra cost is already included in prediction wall time.

Passage 0's baseline graph records sum to **6,807 ms of model preparation**.
Its profile reports 27 cache misses and 921,547,393 miss bytes, including
nomination preflight: screening had already prepared two graphs, while the
baseline prepared the remaining 25. The candidate then reused prepared files;
this follows from the frozen serial execution and verified-cache code, because
the candidate's separate graph profile was not exported. Later completed
baseline passages report 27 hits, no misses and zero summed graph preparation
milliseconds, but use different inputs and cannot supply a matched substitute
baseline. Fresh sessions do not equalize file-cache state. No adjusted
scheduling percentage can be established from this run.

The frozen 0/4/8 policy's first-pair arithmetic projected 24 accelerated passages:
377.919399864 s savings versus 265.997879328 s charged/projected extra work plus
a 217.956658147 s margin. The 106.035137611 s shortfall explains
`payback-unavailable`. These are source-reconstructed projections, not observed
future costs, net savings or proof of a later policy's behavior.

Cancellation recorded `OrtException`, `inferenceCoordinatorFinished=true` and
`engineCloseReturned=true`, while conservatively leaving
`nativeResourceCleanupConfirmed=false` and `temporaryCacheRemoved=false`.
The temporary cache was retained. This receipt does not establish successful
cleanup; subsequent cancellation-source corrections require fresh evidence.

Boundary thermal status rose from light to moderate; battery temperature rose
from 29.6°C to 30.8°C. Boundary samples do not establish continuous thermal
conditions or CPU temperature. Each completed fixture start occurred once, so
repeat-start consistency was not tested. One baseline-first pair does not
establish alternating-order qualification, cold filesystem caches, full-song
quality, production-service lifecycle or release readiness.

## Privacy review

The exact raw bytes are retained after review. They contain a random diagnostic
run UUID, timestamps, device model/OS, resource and battery snapshots, public
fixture provenance, hashes and bounded numeric/enum profile records. No account,
credential, contact, VIN, device serial/Android ID, user-selected audio, private
filesystem path or free-text exception message was found. The analysis omits
the raw run UUID and absolute timestamps.
