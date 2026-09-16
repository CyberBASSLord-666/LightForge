# Analysis renderer recovery

Android can reclaim the service-owned WebView during a long analysis even while
the foreground service remains alive. Previously this stopped the service and
required the user to resume the job. The service now attempts a bounded automatic
resume when Android reports a reclaimed renderer and the job has saved progress.

The replacement uses the same durable job and frozen request. Source audio,
project state, settings, execution identity and checkpoint integrity are checked
before restarting. Partial worker caches still pass the normal cache validation;
a status flag alone does not establish that a cached passage is usable.

The first attempt waits at least 10 seconds. A second attempt waits at least 30
seconds and requires progress beyond the previous failure. The retry counter is
durable and capped at two. Each attempt waits for native executors to retire and
for Android to stop reporting low memory, with a 120-second limit. Recovery does
not extend the original six-hour background processing deadline.

Callbacks carry both job and renderer ownership, so an old renderer cannot write
progress, commit a result or switch the new renderer's execution path. Cancelling
or stopping the service invalidates pending recovery and retires its workers.
Renderer crashes, changed source or settings, unavailable valid progress and
exhausted recovery limits retain the existing interrupted-job workflow.

## Verification

`AnalysisRendererRecoveryTest` exercises durable policy, request integrity,
checkpoint handling and cancellation using the production storage classes.
`tests/verify_native_release.py` includes it in the native host gate. The Android
lifecycle instrumentation terminates a live analysis renderer and checks that the
service replaces it in the background, retains the frozen request and rejects
stale callbacks before the resumed job completes.

The host checks and Android emulator scenario have different scopes. Neither
establishes that every manufacturer memory-management policy can be recovered
from. An entire application-process termination still requires the existing
durable interrupted-job recovery path.

This change reduces the need for manual intervention after an eligible renderer
loss. It does not change model precision, model graphs, passage sizes, transcription
steps or choreography settings, and it does not establish a model speedup.
