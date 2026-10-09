# Comprehensive engineering completion checklist

Assessment date: **2026-10-06**. Integration baseline: `de831259`; follow-up fixes and retained evidence are in this branch.
This ledger covers the complete requested product, not only the inference PR.
**The project is not fully complete or qualified for a new production release.**
Later changes and verification must update the applicable rows; this document is
not a release receipt or permission to bypass an existing gate.

## Reading the status

- **Implemented:** a production code path exists; this alone is not validation.
- **Verified, scoped:** retained evidence covers the named source and scenario.
- **Unverified:** implementation or historical evidence exists, but the current
  candidate or the requested broader claim has not passed its required checks.
- **Blocked:** a specific required verification cannot currently complete.
- **Missing:** requested functionality is absent, or only an optional input
  contract exists. A sidecar schema is not an automatic detector.

Published 2.4.1 evidence is indexed in [VALIDATION](../VALIDATION.md). Its
successful checks do not qualify changed application bytes. The current source
still uses version 2.4.1 during development; a source version is not publication.

## Verification publication scope

This public update contains source, tests, workflow changes and project
documentation. Newly generated optional research records, diagnostic logs and
result snapshots are excluded from publication and retained locally. Do not
interpret their absence as a successful release check. Reproduce verification
using [BUILD](../BUILD.md); the mandatory original-model, browser, Android and
release checks remain necessary for the applicable claims.

## Critical acceptance ledger

| Area | Current state and evidence | Required completion / acceptance |
| --- | --- | --- |
| Inference quality preservation | Implemented original Deux weights, Float32, complete context/graphs and exact-output comparison. PR56 has retained host evidence, not current end-to-end qualification. | Regenerate complete source-bound original-model evidence for the final candidate; preserve all graphs, output, model settings and failed probes. |
| Meaningful inference improvement | Historical PR56 four-worker host passage reduction is 43.6%; published 2.4.1 host result is 32.6%. Neither establishes complete-song or phone benefit. | Measure repeated full passages and complete analysis including calibration cost, fallback and cache state. Do not substitute isolated frontend timing for neural or whole-job improvement. |
| Release-hold integrity | Implemented version-independent hold and expanded source-binding regressions in this integration. Historical receipt remains unchanged; current qualification is separate. | Gate must reject stale/missing evidence for every performance-affecting source and the exact frozen build payload. Version bump must never bypass it. |
| Original Deux qualification | Blocked in current environment: fresh generated model preparation encounters download/proxy restrictions. | Obtain the pinned original assets through an authorized supported route, verify hashes, and rerun complete original-model checks. No reduced model or fabricated receipt. |
| Native runtime checks | Production host, lifecycle and model-comparison harnesses are implemented. Detailed newly generated records are retained locally. | Run exact-source comparisons and preserve source/model/runtime bindings; scoped host checks do not replace packaged Android qualification. |
| MDX numerical comparison | The existing protocol distinguishes mandatory decoded-waveform tolerances from separately recorded internal spectral diagnostics. | Run official inputs and downstream gates; preserve failed diagnostics and existing mandatory thresholds. |
| Foreground/background analysis | Implemented foreground service, checkpointed stages, cancellation and saving; historical emulator evidence exists. | Fresh packaged Android tests: screen-off/background completion, Activity recreation, process interruption, cancel/resume, low-memory paths and durable result save. |
| Completed-project preview | Implemented restoration and historical first-frame tests; current browser verification is blocked by browser IPC failure. | Restore completed and legacy projects; assert first rendered frame, transport/seek, repeated opening, cancellation and current compiled sequence agreement. |
| Browser and UI execution | Browser IPC presently blocks fresh interactive/browser coverage; focused DOM tests are narrower evidence. | Restore supported browser execution, then run current browser, background UI, restore and real-model integration harnesses. Do not label never-run stages passed. |
| Physical phone | Android connector currently reports internal errors. Physical observations remain unverified. | Retry only through supported connection routes when available. Physical testing is optional under the applicable publication policy, but physical performance claims need observations. |
| APK/update identity | Original-signing and exact-payload publication controls implemented. No new final APK is qualified by this ledger. | Deliberate new version, full exact-source verification, original certificate outside Git, update-compatible install identity, alignment and checksum verification. Never replace the key or uninstall to evade incompatibility. |
| Release publication | Current comprehensive work is not a completed release. | Follow [BUILD](../BUILD.md); verify expected remote commit, full CI, qualified signed APK and public release assets. Obtain any required publication authority; do not overwrite an existing version. |

## Music intelligence and choreography ledger

| Requested capability | Current implementation boundary | Remaining acceptance |
| --- | --- | --- |
| Shared audio representation | Original-clock PCM readers and a reusable rhythm DSP FeatureStore exist. [Typed rhythm/recurrence transform identities](FEATURE_TRANSFORM_CONTRACTS.md), per-record bounds and scoped allocation/copy observations are implemented; host tests cover exact restoration, corrupt descriptors and interrupted publication. No universal cross-analyzer STFT/mel broker. | Broader compatible frontend reuse, live-memory measurements and Android cancellation qualification remain unverified. Never share incompatible frontends. |
| Vocal resampler reuse | Implemented bounded, bit-validated overlap reuse; model weights, precision and sampling coordinates remain unchanged. | Reproduce the [resampler checks](VOCAL_RESAMPLER_REUSE.md), including actual-model and full-pipeline comparison; do not infer device or complete-analysis speedup. |
| Multi-stem separation | Deux/MDX provide combined vocals and accompaniment; typed routing accepts external semantic roles. | Automatic isolated bass/drums/harmonic and lead/backing outputs are missing. Pin actual model weights, licenses, conversion and reference parity before integration. |
| Hierarchical rhythm | Beat This! and optional validated rhythm hierarchy exist. | Corpus evaluation for tempo variation, half/double-time, swing, pickup and irregular meter. An estimated grid is not annotation truth. |
| Vocal understanding | Frame-MN10 singing/speech, GAME sung notes, acoustic expression and pitch/phrase evidence enabled. | Lead/backing separation, reliable rap distinctions and word/phoneme/lyric alignment remain missing or unproven. Acoustic articulation must not be labelled recognized syllables. |
| Drum intelligence | Dedicated percussion schema exists; low-trust mix estimates are experimental and off by default. | Dedicated automatic classed model missing. Evaluate actual supported classes, onset P/R/F1, non-drum false positives and all requested drum subclasses. |
| Bass intelligence | Harmonic notes/phrases from vocal-separated accompaniment, including repeated-note refinement. | It is not isolated bass. Evaluate pitch, attack/release, sustained/sub-bass and kick interference against licensed annotations. |
| Musical structure | Tonal novelty, measured phrase boundaries, recurrence and motifs enabled. | Conventional intro/verse/chorus/build/drop labels and genre-general accuracy are unproven. Evaluate boundaries and recurrence rather than inventing labels. |
| Unified semantic timeline | Validated events, provenance, salience and linked evidence implemented. | Preserve confidence/uncertainty, original clock, input bounds and migration; verify all new detector routes reach this layer without writing vehicle channels directly. |
| Hierarchical choreography | Deterministic planners, vocal expression, motif evolution and important vocal/bass attack protection enabled for new projects. | Evaluate musical coverage, negative space, repetition/evolution, call/response and differentiated climax on representative music; compare final FSEQ, not proposed events only. |
| Density and collisions | Density control/accounting exists; semantic collision allocation remains separately opt-in. | Report unresolved high-salience losses honestly; preserve legal fallback groups, silence and actuator budgets. Low collision count alone is not musical correctness. |
| Vehicle timing | Software command/arrival intent and optional explicit calibration exist. | Physical latency, photometry and closure travel are unmeasured. Do not invent faster actuators to make preview look synchronized. |
| Analysis scheduler | Capacity-one heavy-pipeline admission and Web Locks are implemented. | Resource-aware parallel DAG missing. Measure memory and cancellation retirement before adding concurrency; retain existing safe capacity until proven. |
| Strict quality/performance gate | Fail-closed tooling and owner public authority exist; checked-in locked corpus policy is still a template. | Licensed locked corpus, complete paired metrics, required protected attestations/reviews and statistical evidence remain absent. Publication exceptions do not create PASS_TARGET. |
| 75% total-runtime objective | Not established. Current guidance treats it as an objective, subordinate to quality. | Measure complete paired cold/warm jobs on locked conditions. Never extrapolate a stage percentage to total analysis or claim universal zero regression. |

## Product, export and maintenance ledger

| Area | Existing capability / current work | Remaining acceptance |
| --- | --- | --- |
| Audio import | Android codec-dependent import and 44.1 kHz stereo PCM16 soundtrack conversion. | Truncated/malformed audio, supported codecs, long/odd-duration files and source-clock fidelity. Analysis stems must not replace export soundtrack. |
| Projects and recovery | Independent projects, saved frames, backup/restore and cache lineage; interrupted storage/transfer handling repaired in this integration. | Fresh failure-injection and Android tests; cancellation and clear-cache must preserve saved shows. Legacy opens must not silently recompose. |
| Editor and UX | Compose/Music/Outputs/Review, cue edits, Undo/Redo and individual output controls exist. | Rendered mobile/foldable review, accessibility, repeated clicks/navigation, meaningful failure/progress messages and reliable preview. DOM tests are not visual review. |
| Vehicle model | Source-backed Highland profile, black appearance option and official catalog research exist. | [Hardware evidence](VEHICLE_HARDWARE_EVIDENCE.md) explicitly limits lens mapping/travel. Do not invent unsupported lamps or movement commands; retain correct trunk/body-fixed geometry. |
| FSEQ/USB export | Validated 200-channel uncompressed FSEQ v2, 15/20 ms, soundtrack and project ZIP with CRC/size checks. | Fresh final-candidate round-trip, duration/movement budgets, filename/root layout, edited project and cache-independent export checks. |
| Diagnostics | Bounded local diagnostic export and durable job summaries implemented. | Recover after process failure; avoid personal audio, credentials and project payload leakage; disclose incomplete observations. |
| Dependencies | Exact pins, fresh npm audits, coordinated EfficientAT research upgrades and attention ONNX remediation documented in [dependency security](DEPENDENCY_SECURITY.md). | Research model-output parity and complete installed/transitive/native dependency audits remain unverified; do not imply all security alerts are cleared. |
| Artifact security | Archive credential/symlink rejection and repository hygiene strengthened. | Final packaging/provenance regression and rendered bundle binding must pass; keep signing secrets and personal files outside artifacts. |
| Repository/PR integration | PR56 work under integration; PR43 scope is larger than its description. | Review actual ancestry/diff and evidence; do not infer an empty PR from connector metadata. Preserve required history, model notices and failed evidence. |

## Next safe engineering steps

1. Complete final aggregate checks and preserve every blocked/failed stage above.
2. Qualify original Deux and complete official MDX inputs/downstream checks;
   investigate the retained spectral diagnostic discrepancies.
3. Restore browser execution and run packaged Android verification.
4. Keep bass decimation caching deferred: profiling found only about 9–12 ms
   of duplicate work before cache overhead, while immutable-reader identity is
   not yet a generic API guarantee. Preserve globally ranked articulation and
   existing pass order; do not add memory/identity complexity without benefit.
5. Extend the [typed rhythm transform contract](FEATURE_TRANSFORM_CONTRACTS.md) only with measured, compatible uses before expanding FeatureStore.
   Vocal, bass and rhythm use different rates/windows/frontends; similar names
   do not make their data interchangeable.
6. Build a dedicated-percussion reference/conversion/evaluation path behind an
   explicit experimental flag. Do not enable new detectors on synthetic-only
   evidence or describe external evidence import as completed inference.

Model expansion requires actual pinned weights and reviewed distribution terms,
reference/conversion equivalence, appropriately licensed annotated audio,
resource measurements and detector/choreography evaluation. These are separate
requirements from engineering an adapter. Physical observations remain necessary
only for physical claims, not a blanket substitute for the user's approved
publication policy.
