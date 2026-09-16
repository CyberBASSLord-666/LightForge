# LightForge architecture

LightForge is an offline Android host around a WebView studio, bundled inference
runtimes and a deterministic show compiler. The source is at the repository root.
The installed app has no Internet permission; build-time dependency downloads
are a separate concern.

## Ownership and data flow

Local audio → native decode/source clock → staged musical analysis → semantic
and salience data → light/movement planning → validated FSEQ → preview/export.
Saved frames and original soundtrack remain the durable show. Disposable analysis
caches and preview state must never become the export source of truth.

| Location | Owns |
| --- | --- |
| `android/src/` | Import/decode, projects, foreground jobs, transport, native inference, diagnostics and export |
| `web/analysis/` | Rhythm, separation, voice/bass evidence, source-clock checkpoints and bounded model execution |
| `web/background/` | Service-runner integration and injected native predictor capabilities |
| `web/engine/` | Vehicle capabilities, planners, deterministic frame compilation and sequence validation |
| `web/preview/src/` | Renderer source; the built preview consumes compiled engine state |
| `web/app.js` and studio modules | UI orchestration, user edits, playback, progress and public bridge adaptation |
| `tools/` | Reproducible assets/toolchains, regression gates, package integrity and release tooling |
| `tests/` and `qa/` | Component contracts, current release harnesses and explicitly versioned historical evidence |

The [analysis contract](web/analysis/README.md), [engine contract](web/engine/README.md)
and [implementation/evidence map](docs/ARCHITECTURE_AND_PRODUCTION_READINESS.md)
contain the detailed schemas, capability boundaries and remaining gaps.

## Dependency boundaries

The engine stays independent of DOM, Android and preview ownership. Analysis
produces musical evidence and may receive a native-predictor capability; it does
not write vehicle channels or import choreography planners. The preview reads
`ShowEngine.stateAt` and profile capabilities; it must not invent a second
choreography implementation. UI modules use the public facades rather than
painting FSEQ bytes or handling native file paths directly.

Native bridges remain capability-thin. Activity interaction uses `window.Android`;
service-owned work uses `window.BackgroundJob`. Long operations run off the UI
thread and return bounded progress/results. Large binary payloads use validated
stream/file transports rather than bridge strings. Job/task identity must fence
late callbacks after cancellation, replacement or Activity turnover.

`MusicAnalyzer.analyze` supplies analysis-v6 data to `ShowEngine.generate`.
Additive telemetry must tolerate absence in older saved projects and must not
reinterpret musical evidence. Breaking schema/interpretation changes require an
explicit version and compatibility path. Stereo separation must receive original
stereo audio, not the mono analysis proxy. Acoustic vocal events are not invented
lyrics or word timestamps.

## Determinism, persistence and vehicle truth

For identical music, normalized settings and seed, compilation must produce
identical frames. The vehicle profile is the capability and command authority;
planners and UI must not duplicate channel maps. `validate` and native export
checks remain authoritative for sequence legality. A visual preview or a valid
FSEQ cannot establish real vehicle response time or brightness.

Legacy projects preserve their checked frame payloads and creation identity.
Recreation is explicit. Cache records are checksum-bound to source, settings and
execution lineage; invalid or incomplete work is recomputed without changing
quality settings. Saved projects, revisions and exports remain separate from
replaceable OPFS stems/features/checkpoints.

## Resource and recovery invariants

Models and runtimes remain bundled. Studio and Balanced are explicit modes;
fallback retains the selected model's quality contract rather than silently
switching modes. Preserve trained weights, Float32 calculations, separation
context, polarity passes and GAME transcription steps. Optimization requires
measurement and applicable equivalence checks, not reduced resolution.

Stage workers bound WebAssembly lifetimes. Native predictions share a serialized
execution gate; cancellation must retire sessions/buffers before another heavy
job allocates them. Checkpoint reuse still requires content and execution-lineage
validation. Origin/document admission remains capacity-one safety coordination,
not evidence of a parallel resource-aware analysis scheduler.

Background execution belongs to the foreground service, not the Activity.
Reopening must reconnect to the current job or restore the saved completed show.
Android lifecycle verification, preview first-frame restoration and diagnostic
export are separate from desktop tests. An open development PR is not an enabled
capability in `main` merely because it is described in a plan.

## Maintenance boundaries and remaining debt

`web/app.js` and `MainActivity` remain large orchestration surfaces. New features
belong in focused owners; do not grow unstructured globals or move analysis into
the UI. Keep cache/recovery lineage, stale-callback fencing and partial-failure
paths covered by regression tests. Bundled model size is intentional functional
content, not a candidate for deletion during repository cleanup.

The implementation map distinguishes automatic detectors from optional evidence
inputs and missing capabilities. Strict comparative quality, a 75% end-to-end
speedup and physical Tesla timing require their own evidence. Unmet roadmap work
must remain visible rather than being erased by a documentation refresh.

[BUILD.md](BUILD.md) owns reproduction/publication instructions;
[VALIDATION.md](VALIDATION.md) owns evidence scope;
[REPOSITORY.md](REPOSITORY.md) owns checkout hygiene and historical recovery.
