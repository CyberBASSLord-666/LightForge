# LightForge 2.1.0 — Architecture

Quality bars for modularity and API boundaries. Repo: private `CyberBASSLord-666/LightForge` — on GitHub `main`, `android/` and `web/` live at **repo root**; some local/private trees nest the same layout under `app/lightforge/`. Docs only — no code moves in this landing.

## Shape

Offline Android shell + bundled WebView studio. No network permission, no remote inference, no Gradle app module graph — assets ship inside the APK.

```
android/          native host: I/O, projects, decode, export ZIP, WebView bridge
web/analysis/     on-device music intelligence (WASM/ONNX) → analysis v5
web/engine/       pure choreography → validated FSEQ frames (CommonJS-testable)
web/preview/      Highland WebGL preview (consumes stateAt only)
web/app.js + UI   studio orchestration, bridge adapter, editing UX
```

Script load order is the dependency graph: analysis → vehicle-profile → planners → show-engine → ShowCompiler client → preview → app → UI plugins.

## Layer contracts (quality bars)

### 1. Dependency direction (hard)

| Layer | May depend on | Must not depend on |
| --- | --- | --- |
| `android/` | SDK, files, WebView | engine planners, analysis models, Three.js |
| `web/engine/` | `vehicle-profile` + music analysis object | DOM, `window.Android`, preview, OPFS UI |
| `web/analysis/` | bundled models/ORT, OPFS stem cache | ShowEngine, vehicle-profile, FSEQ |
| `web/preview/` | `ShowEngine.stateAt` + profile capabilities | planners, MusicAnalyzer, ProjectStore |
| UI (`app.js`, studio plugins) | all public facades above | direct FSEQ byte painting, native file paths |

**Bar:** a change that forces engine code to call DOM/Android, or analysis to import planners, fails review.

### 2. Native ↔ Web bridge (versioned surface)

`MainActivity.Bridge` as `window.Android` is the only native RPC. Keep it **capability-thin**:

- Bootstrap / projects: `getBootstrap`, `saveProject`, `deleteProject`, `renameProject`, `duplicateProject`, `restorePreviousProject`, `pickProjectBackup`
- Import: `pickAudio`, `loadDemo`, `cancelWork`
- Export stream: `beginExport` → `appendExport` → `finishExport` / `shareExport` / pending resume-discard
- Misc: `openExternal`

Native → Web: `window.onNativeEvent(type, payload)` plus a few lifecycle hooks (`pausePreview`, `handleNativeBack`).

**Bars:**

- No new `@JavascriptInterface` that returns large binary blobs or project trees; stream or file-URL patterns only (see `WebViewFileTransport` / asset origins).
- Event types are a closed enum; unknown types must no-op safely in `onNativeEvent`.
- Bridge methods stay synchronous-return / fire-and-forget as today — long work stays on the native worker thread and reports via events.
- Browser fallback (`indexedDB` / `localStorage`) must keep the same project JSON shape so UI logic does not fork semantics.

### 3. Analysis → engine music object (schema bar)

`MusicAnalyzer.analyze` (v1.6.0 / analysis **version 5**) owns rhythm + structure + separated voice/bass detail. `ShowEngine.generate(music, settings)` consumes that object.

**Bars:**

- Bump `analysisVersion` (and document in `web/analysis/README.md`) for any field add/remove/semantics change.
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

`web/app.js` (~62 KB) is the orchestration hub (state, bridge, save, generate, export, preview tick). Acceptable for 1.6 shipping, **not** the long-term boundary.

**Bars going forward:**

- New studio features land in focused modules (pattern of `channel-studio.js`, `music-insights.js`, `studio-tools.js`) and talk to app state via small helpers/events (`lightforge:changed` / `lightforge:saved`), not by growing unstructured globals.
- Do not grow `MainActivity` with feature logic belonging in Web or `ProjectStore`.
- Project JSON (`projectJson` provenance: app / planner / profile / analysis / frame SHA) is the persistence contract — additive fields only with migration notes.

### 7. Performance / resource budgets (architecture-level)

- Models stay APK-bundled; no runtime downloads.
- Stem cache is replaceable OPFS, excluded from backups; eviction must not invalidate saved frames/export.
- History/undo memory caps in UI (~64 MB / depth) stay intentional — do not unbounded-clone full frame buffers.
- Keep WebView-only (no ABI `.so`) unless a measured need forces native ML — that would be a major architecture change requiring Lead + CoS.

## Current assessment (staff)

**Strengths:** clear physical split (native host vs pure engine vs analysis vs preview); strong written contracts in `web/engine/README.md` and `web/analysis/README.md`; abortable workers; offline/reproducible build story.

**Risks / watchlist:**

1. `app.js` god-object — highest modularity risk for 1.7+.
2. Bridge surface is workable but undocumented as a single contract file — this doc + eventual `BRIDGE.md` excerpt should be the source of truth (held until after QA smoke).
3. Analysis v5 richness increases coupling to composer settings (`vocalFocus`, guides); keep guides as overlays, never rewrite model outputs.
4. Preview bundle size dominates asset weight — isolate from engine/tests forever.

## Related docs

Coordinate wording with LF Docs if touching `BUILD.md` / `VALIDATION.md`. Engine and analysis contracts remain detailed in `web/engine/README.md` and `web/analysis/README.md`.


## 2.0 additions

`engine/music-cues.js` validates additive settings (`musicCues`, `vocalOffsetMs`, `bassOffsetMs`) and creates a corrected working interpretation without changing saved model evidence. The 2.0 release retained analysis version 5. Version 2.1 introduces analysis version 6 for Deux/GAME while preserving compiled legacy arrangements.

`engine/sync-review.js` inspects the final frame payload after output-level overrides. Its coverage denominator is selected role targets, not all detected notes, and it makes no inference-accuracy or vehicle-latency claim. The review is frozen inside compiled metadata and export validation.

`precision-studio.js` owns its UI and commits edits through the existing serialized `commitChannelSettings` transaction. Failed edits leave the previous show intact. Fresh imports reset musical cues and part corrections.

`web/version.js` is generated from `version.json`. Known zero/empty 2.0 defaults can be stripped only to reproduce a legacy input checksum; payload and metadata checks remain mandatory.

## 2.1 analysis and cockpit

`analysis/worker.js` selects Deux for Studio or MDX for Balanced, then releases separation sessions before Frame-MN10. `stem-cache.js` retains both half-rate listening stems and the original-clock 44.1 kHz mono Float32 voice. `game.js` runs the five GAME Large graphs, deterministic diffusion, context ownership and continuation-aware stitching. Its fusion preserves measured vocal expression, requires supported singing phrases, and replaces acoustic pitch-note estimates with neural notes. Bass remains independent harmonic tracking in accompaniment.

`separator-deux.js` implements source-clock STFT/ISTFT, sequential full-context transformer stages, dual source-head scattering and normalized chunk overlap-add. `tools/prepare_deux.py` and `tools/prepare_game.py` reproduce licensed, pinned models; `verify_analysis_assets.py` rejects stale or incomplete runtime inventories at build time.

`cockpit.js` moves existing live controls into four accessible workspaces without changing their IDs or handlers. It renders the source-time note/edit score using the actual audio playhead and declared part offsets. `cockpit.css` supplies the monochrome/red responsive design. Project state, native bridge, original audio exports, hardware routing and legacy frame integrity remain managed by their existing production owners.
