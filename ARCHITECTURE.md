# LightForge 2.2.1 — Architecture

Quality bars for modularity and API boundaries. Repo: private `CyberBASSLord-666/LightForge` — on GitHub `main`, `android/` and `web/` live at **repo root**; some local/private trees nest the same layout under `app/lightforge/`. Current application and release contracts are described below.

## Shape

Offline Android shell, native CPU Studio separation and bundled WebView studio. No network permission, remote inference or Gradle app module graph; models and runtimes ship inside the APK.

| Location | Responsibility |
| --- | --- |
| `android/` | I/O, projects, decode/export, foreground-job ownership and bounded native CPU separation |
| `web/analysis/` | Source-clock scheduling, recoverable model stages, musical analysis v6 and browser WASM inference |
| `web/engine/` | Pure choreography and validated FSEQ frames; independently Node-testable |
| `web/preview/` | Highland WebGL preview consuming `stateAt` |
| `web/app.js` and UI modules | Studio orchestration, capability adapters, editing and progress |

Script load order is the dependency graph: generated version → analysis → vehicle-profile → planners → show-engine → ShowCompiler client → preview → app → UI plugins.

## Layer contracts (quality bars)

### 1. Dependency direction (hard)

| Layer | May depend on | Must not depend on |
| --- | --- | --- |
| `android/` | SDK, files, WebView, pinned native ONNX Runtime and declared Deux model assets | engine planners, vehicle choreography, Three.js |
| `web/engine/` | `vehicle-profile` + music analysis object | DOM, `window.Android`, preview, OPFS UI |
| `web/analysis/` | bundled models/ORT, OPFS checkpoints/stems, injected native-predictor capability | ShowEngine, vehicle-profile, FSEQ, direct Activity bridge ownership |
| `web/preview/` | `ShowEngine.stateAt` + profile capabilities | planners, MusicAnalyzer, ProjectStore |
| UI (`app.js`, studio plugins) | all public facades above | direct FSEQ byte painting, native file paths |

**Bar:** a change that forces engine code to call DOM/Android, or analysis to import planners, fails review.

### 2. Native ↔ Web bridge (versioned surface)

`MainActivity.Bridge` as `window.Android` owns interactive UI capabilities. The service runner has a separate `AnalysisService.JobBridge` as `window.BackgroundJob`; it is bound to its creating job and native task. Both surfaces remain **capability-thin**:

- Bootstrap / projects: `getBootstrap`, `saveProject`, `deleteProject`, `renameProject`, `duplicateProject`, `restorePreviousProject`, `pickProjectBackup`
- Import: `pickAudio`, `loadDemo`, `cancelWork`
- Export stream: `beginExport` → `appendExport` → `finishExport` / `shareExport` / pending resume-discard
- Background controls: `startAnalysis`, `getAnalysisStatus`, `cancelAnalysis`, `continueInBackground`, `getDeviceCapabilities`, `openBackgroundSettings`
- Misc: `openExternal`

Native → Web: `window.onNativeEvent(type, payload)` plus a few lifecycle hooks (`pausePreview`, `handleNativeBack`).

`BackgroundJob` exposes progress/checkpoint/completion/failure and `nativeDeuxStart` / `nativeDeuxStatus` / `nativeDeuxCancel` / `nativeDeuxRelease`. Starting a passage returns a token immediately; computation runs on a native executor, and the runner polls bounded status. A completed result is fetched from the private, same-origin `/background/native/<token>.bin` route as streamed Float32 audio. The route checks the creating job/task and exact result length; it does not expose arbitrary device files or place model/audio payloads in bridge strings. The analyzer receives an injected predictor callback, and workers exchange small request/progress/result messages with it.

**Bars:**

- No new `@JavascriptInterface` that returns large binary blobs or project trees; stream or file-URL patterns only (see `WebViewFileTransport` / asset origins).
- Event types are a closed enum; unknown types must no-op safely in `onNativeEvent`.
- Bridge methods stay synchronous-return / fire-and-forget as today — long work stays on the native worker thread and reports via events.
- Browser fallback (`indexedDB` / `localStorage`) must keep the same project JSON shape so UI logic does not fork semantics.

### 3. Analysis → engine music object (schema bar)

`MusicAnalyzer.analyze` (analysis **version 6**) owns rhythm + structure + separated voice/bass detail. `ShowEngine.generate(music, settings)` consumes that object.

**Bars:**

- Bump `analysisVersion` for a breaking musical-schema or interpretation change and document it in `web/analysis/README.md`. Version 2.2.1 retains **analysis v6**: original event, pitch, duration, uncertainty and source-clock meanings are unchanged. Optional runtime, per-stage duration and checkpoint/reuse telemetry are additive provenance; consumers must tolerate their absence in saved v6 projects.
- Engine must keep a documented compatibility path for older saved analysis; UI triggers re-analyze, never silently reinterpret.
- Stereo separator must never receive the mono analysis proxy (already documented — treat as invariant test).
- Analysis must not invent lyrics/word timings; confidence fields stay relative evidence.

### 4. Engine public API (stability bar)

Stable facade on `ShowEngine`: `generate`, `validate`, `fseq` / `fseqHeader`, `preparePreview` / `invalidatePreview`, `stateAt`, `getCapabilities`, `normalizeSettings`. Composition off-main-thread via `ShowCompiler` (`engine/client.js` + worker) with abort ownership per job.

**Bars:**

- Vehicle truth lives only in `vehicle-profile.js` (34 controls / 53 addresses / command budgets). Planners and UI read capabilities; they do not hardcode channel maps.
- `validate` + export path remain authoritative for Tesla legality; preview estimates must stay labeled estimated.
- Identical `(music, settings, seed)` ⇒ identical frames (determinism is a product contract).
- Engine modules stay Node-testable without a browser (`tests/engine*.cjs`).

### 5. Preview / graphics bar

Bundled `preview/vehicle-preview.js` is generated; edit `preview/src/` + rebuild tool. Preview renders `stateAt` output only — no second choreography path.

**Bar:** graphics changes must not alter exported FSEQ bytes or command semantics.

### 6. UI modularity bar (1.6 debt → next)

`web/app.js` remains the orchestration hub for state, bridge adaptation, save/generate/export and preview ticks. Keep new model execution and persistence logic in their focused owners rather than expanding this hub.

**Bars going forward:**

- New studio features land in focused modules (pattern of `channel-studio.js`, `music-insights.js`, `studio-tools.js`) and talk to app state via small helpers/events (`lightforge:changed` / `lightforge:saved`), not by growing unstructured globals.
- Do not grow `MainActivity` with feature logic belonging in Web or `ProjectStore`.
- Project JSON (`projectJson` provenance: app / planner / profile / analysis / frame SHA) is the persistence contract — additive fields only with migration notes.

### 7. Performance / resource budgets (architecture-level)

- Models stay APK-bundled; no runtime downloads.
- Stem cache is replaceable OPFS, excluded from backups; eviction must not invalidate saved frames/export.
- History/undo memory caps in UI (~64 MB / depth) stay intentional — do not unbounded-clone full frame buffers.
- Android Studio now uses pinned native ONNX Runtime CPU libraries. The measured host comparison on one 6.8-second excerpt was 61.11 seconds / 720.56 MiB peak process RSS, against 127.25 seconds / 1,920.96 MiB for bounded WASM on identical PCM16 audio and four threads. This justifies the native execution boundary; it is not a phone or full-song performance guarantee.
- Preserve learned Float32 weights, both trained heads and full 13-second context. Batches divide independent bands/frames without truncating attention; no model layer, precision setting or quality mode is silently substituted.
- A fresh worker owns each rhythm/separation/voice/bass stage. Terminating the worker releases its WASM heap before the next stage. Native direct buffers are explicitly released after separation and before voice/GAME, including a separation checkpoint hit.
- Native prediction uses a process-wide fair serialization gate. Cancel/Resume cannot overlap heavy inference allocations from two job executors. Cancellation reaches the active ORT run, and session/buffer cleanup completes before the old prediction relinquishes the gate. No synchronous UI wait is used for the computation.
- Analysis checkpoints are temporary, checksummed OPFS work, separate from saved music/frames and excluded from backups. Storage admission accounts for remaining passages plus final stems; unavailable or invalid checkpoints require recomputation rather than changing musical quality.

## Current assessment (staff)

**Strengths:** clear physical split (native host vs pure engine vs analysis vs preview); strong written contracts in `web/engine/README.md` and `web/analysis/README.md`; abortable workers; offline/reproducible build story.

**Risks / watchlist:**

1. `app.js` remains a large orchestration hub; execution and recovery belong in focused modules.
2. Preserve job/task ownership across Activity and service turnover; late callbacks from a cancelled job must never control its replacement.
3. Analysis v6 remains distinct from composer settings (`vocalFocus`, guides); keep guides as overlays and execution telemetry separate from model evidence.
4. Bundled neural models dominate package size. Native ABI assets and converted graphs require exact inventories; preview assets stay isolated from engine tests.

## Related docs

Build and validation scope are described in `BUILD.md` and `VALIDATION.md`; engine and analysis contracts remain detailed in `web/engine/README.md` and `web/analysis/README.md`.


## 2.0 additions

`engine/music-cues.js` validates additive settings (`musicCues`, `vocalOffsetMs`, `bassOffsetMs`) and creates a corrected working interpretation without changing saved model evidence. The 2.0 release retained analysis version 5. Version 2.1 introduces analysis version 6 for Deux/GAME while preserving compiled legacy arrangements.

`engine/sync-review.js` inspects the final frame payload after output-level overrides. Its coverage denominator is selected role targets, not all detected notes, and it makes no inference-accuracy or vehicle-latency claim. The review is frozen inside compiled metadata and export validation.

`precision-studio.js` owns its UI and commits edits through the existing serialized `commitChannelSettings` transaction. Failed edits leave the previous show intact. Fresh imports reset musical cues and part corrections.

`web/version.js` is generated from `version.json`. Known zero/empty 2.0 defaults can be stripped only to reproduce a legacy input checksum; payload and metadata checks remain mandatory.

## Analysis and cockpit (2.1, extended in 2.2.1)

`analysis/worker.js` selects Deux for Studio or MDX for Balanced. The analyzer now starts separate workers for rhythm, separation, voice and bass, releasing each stage before its successor. Android injects native CPU prediction for Studio; browser Studio retains bounded WASM. Balanced remains an explicit user choice. `stem-cache.js` retains both half-rate listening stems and the original-clock 44.1 kHz mono Float32 voice. `game.js` runs the five GAME Large graphs, deterministic diffusion, context ownership and continuation-aware stitching. Its fusion preserves measured vocal expression, requires supported singing phrases, and replaces acoustic pitch-note estimates with neural notes. Bass remains independent harmonic tracking in accompaniment.

`separator-deux.js` retains ownership of source windows, normalized overlap-add, dual-source delivery and passage checkpoints. Its browser path implements STFT/ISTFT, bounded full-context transformer computation and source-head scattering. The Android callback delegates the same complete model window to `NativeDeux` / `NativeDeuxTransform`, then returns both source estimates to the same scheduler. Numerical equivalence and runtime metadata make the execution path reviewable. `tools/prepare_deux.py` and `tools/prepare_game.py` reproduce licensed, pinned models; `verify_analysis_assets.py` rejects stale or incomplete runtime inventories at build time.

`cockpit.js` moves existing live controls into four accessible workspaces without changing their IDs or handlers. It renders the source-time note/edit score using the actual audio playhead and declared part offsets. `cockpit.css` supplies the monochrome/red responsive design. Project state, native bridge, original audio exports, hardware routing and legacy frame integrity remain managed by their existing production owners.

## Release publication

The CI candidate uses an ephemeral certificate. A trusted local signing step preserves the original installation identity. `tools/apk_delta.py` transfers only public signature/ZIP bytes and references SHA-256-pinned candidate regions; no signing secrets enter Actions. `publish_github_release.py` requires successful CI, unchanged Android/WebView sources, all required current source-bound gates, exact asset bytes, package version, alignment and the original certificate before creating a draft release. It verifies GitHub's uploaded APK digest before publishing.

## Background execution and recovery (2.2.1)

`AnalysisService` owns a dedicated application-context WebView. Its minimal `web/background/runner.html` runs the production MusicAnalyzer and ShowCompiler workers; it contains no preview, animation loop or playback element. `AppResources` supplies the same isolated asset and bounded WAV transport used by MainActivity, restricted to the current project for the service.

`AnalysisJobStore` serializes a single job and its frozen saved inputs using fsynced temporary files and atomic replacement. Active job ownership rejects stale callbacks, concurrent starts and UI saves. Completed overall analysis is checkpointed before composition; 2.2.1 also commits independent passage and stage checkpoints during analysis. Native identity hashes original/derived audio, analysis settings and app version; the worker namespace additionally binds the pipeline and execution path. Rename/choreography-only edits do not change that identity. A completed checkpoint requires matching SHA-256, source duration, supported v5/v6 structure and complete model/role fields; malformed saved music is marked for analysis when generation is explicitly requested. Reading legacy compiled arrangements remains unchanged. Final publication compares the original project SHA-256, commits through ProjectStore's recoverable save transaction and records the job ID in the project. Recovery recognizes the narrow crash window between project commit and terminal job-state persistence.

`work-store.js` verifies individual JSON and Float32 records before reuse. Completed separation can restore without a model run when its stem files remain valid. Missing/damaged stems invalidate downstream voice and bass results while keeping usable expensive passages available for reconstruction. Interrupted, incomplete or corrupt passages are recomputed; matching completed work is reused. Browser sessions without a durable audio fingerprint use transient checkpoint namespaces and do not promise persistent Resume. Cached work is replaceable and may expire; saved arrangements and the original export soundtrack remain authoritative.

The UI polls persisted status while visible and also receives package-private broadcasts. It never owns the native generation promise. Completion reloads the saved result without first autosaving stale UI state. Progress is monotonic; native progress persistence/notifications are limited to roughly one update per second during model inference, with durable-checkpoint notices admitted immediately. A small allowlist carries passage/completed/reused counts and stage identity without permitting metadata to change job ownership. Elapsed time and last advancing update are shown separately; they are not an ETA. Native status polling alone cannot keep the analyzer watchdog alive when computation has stopped advancing. Cancellation is acknowledged before the UI offers another job.

Android 15+ uses the mediaProcessing foreground-service type. Older supported versions use dataSync for local file processing. An ongoing notification, bounded PARTIAL_WAKE_LOCK and explicit IMPORTANT renderer policy protect active work without keeping the display lit. On completion, cancellation, failure, renderer loss and timeout, the native task is closed, the WebView and wake lock are released, and the service stops. Native asynchronous teardown stays serialized with a rapid replacement job. START_NOT_STICKY prevents reboot/kill retry loops. Android/OEM execution policy remains authoritative.

The notification and battery-exemption settings are user-controlled. No Internet, overlay, accessibility, root, storage-wide or microphone permission is introduced. The test instrumentation APK is separately built and must use the ephemeral CI certificate; it is never signed with the private update key or shipped as a release asset.
