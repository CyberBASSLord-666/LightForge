# Analysis renderer recovery

Android can reclaim the service-owned WebView during a long analysis even while
the foreground service remains alive. Previously this stopped the service and
required the user to resume the job. The service now attempts a bounded automatic
resume when Android reports a reclaimed renderer and the job has saved progress.

The replacement uses the same durable job and frozen request. Source audio,
project state, settings, execution identity and checkpoint integrity are checked
before restarting. Partial worker caches still pass the normal cache validation;
a status flag alone does not establish that a cached passage is usable.

Source hashing runs under the project monitor without holding the job monitor,
so cancellation can still update the job. The final commit rechecks the frozen
request and the identity, size and timestamps of the hashed files while holding
the job and project monitors in that order. Supported project edits publish files
by replacement, so even a replacement with unchanged size and modification time
is rejected. An unavailable file identity stops automatic recovery. This does not
claim protection against arbitrary external writers deliberately preserving all
file metadata.

The first attempt waits at least 10 seconds. A second attempt waits at least 30
seconds and requires progress beyond the previous failure. The retry counter is
durable and capped at two. Each attempt waits for native executors to retire and
for Android to stop reporting low memory, with a 120-second limit. Recovery does
not extend the original six-hour background processing deadline.

Closing a native passage preserves queued work long enough to observe cancellation
and run its cleanup. Retirement requires executor termination after that cleanup;
releasing the inference gate alone does not admit a replacement.

Callbacks carry both job and renderer ownership, so an old renderer cannot write
progress, commit a result or switch the new renderer's execution path. Cancelling
or stopping the service invalidates pending recovery and retires its workers.
Renderer crashes, changed source or settings, unavailable valid progress and
exhausted recovery limits retain the existing interrupted-job workflow.

## Verification

`AnalysisRendererRecoveryTest` exercises durable policy, request integrity,
checkpoint handling and cancellation using the production storage classes.
It also forces source replacements, request edits and cancellation between
validation and commit. `NativePassageLifecycleTest` exercises queued and active
cancellation, cleanup and same-job replacement using the real task and executor
with a controlled native boundary.
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
