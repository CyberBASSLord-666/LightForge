# Comprehensive engineering completion checklist

This ledger describes implementation and acceptance boundaries for the **2.4.2 /
Android 20402** source. It is not a release receipt or a statement that every
long-term music-intelligence requirement is complete. Read
[VALIDATION](../VALIDATION.md) for immutable measurements and historical releases;
check the exact version, source, certificate and payload in
[release-verification.json](../release-verification.json) against
[GitHub Releases](https://github.com/CyberBASSLord-666/LightForge/releases) before
claiming publication. A retained older-version report does not qualify new bytes.

## Reading the status

- **Implemented:** a production code path exists; this alone is not validation.
- **Verified, scoped:** retained evidence covers the named source and scenario.
- **Unverified:** implementation or historical evidence exists, but the current
  candidate or the requested broader claim has not passed its required checks.
- **Blocked:** a specific required verification cannot currently complete.
- **Missing:** requested functionality is absent, or only an optional input
  contract exists. A sidecar schema is not an automatic detector.

Published 2.4.1 evidence is indexed in [VALIDATION](../VALIDATION.md). Its
successful checks do not qualify changed application bytes. The source uses
2.4.2; a source version is not publication.
No old receipts are promoted to qualify this new candidate.

## Recorded source and verification evidence

The following is a **historical snapshot at 2026-10-24 12:26 UTC**, not a promise
of later CI success or publication:

- Source includes the reliability/UI/export/background work integrated by
  [PR56](https://github.com/CyberBASSLord-666/LightForge/pull/56), ONNX/release
  provenance remediation in [PR57](https://github.com/CyberBASSLord-666/LightForge/pull/57)
  and Python bootstrap pins in [PR58](https://github.com/CyberBASSLord-666/LightForge/pull/58).
  PR61 head `8285b55` and local `05db18f` share tree
  `38da1ce8b49b8c9252be9606ac9277aa506ea6ec`. Its platform-reader JSON depth/UTF-8
  and backup bounds, immutable sparse regression inputs and explicit consumer
  JDK layout repair leave all 27 registered execution-closure files unchanged.
- Local regression ran **793 Node tests and 976 Python tests (972 passed,
  4 historical skips)**, with quality-tool and asset checks passing. CI selects
  its own supported tests/skips; do not substitute these totals for CI results.
- The registered [producer run 40085980189, attempt 1](https://github.com/CyberBASSLord-666/LightForge/actions/runs/40085980189)
  measured **18.8186% lower median complete-passage time**, 66.459075114 to
  53.952437538 seconds. All three measured pairs improved (18.81855%, 17.51232%,
  19.40812%), and all eight complete outputs were byte-identical. This is forced
  four-worker versus three-thread execution on three child CPUs of a
  four-capacity host for one original passage, not Android, whole-song or an
  additional gain over the historical 32.6%/43.6% comparisons. Source, artifact,
  digest and consumer-admission requirements are recorded in [VALIDATION](../VALIDATION.md).
- [PR CI 40091744623](https://github.com/CyberBASSLord-666/LightForge/actions/runs/40091744623)
  had passed core, model/native and performance admission and reached its
  ephemeral test-APK build. Packaged Android, final main-candidate qualification,
  original-signed payload verification and publication were not established by
  that observation. Later status must be read from exact-source sealed evidence.
- Scoped advisory metadata audits listed no known advisories for 44 production
  package versions and 15 exact research pins. Nineteen historical range/unpinned
  research declarations remained unresolved. Reviewed pins include ONNX 1.23.2,
  pip 26.2.1, setuptools 84.1.0, filelock 4.2.1 and Temurin 17.0.21+9. Fresh
  ONNX export reproduced the original GAME and Deux model files byte for byte.
  Native ORT 1.25.1 and Web ORT 1.20.1, including older embedded ONNX-schema
  components, remain unchanged. The scoped Android fixed-model input-path review
  does not patch those components or provide universal security clearance.

Earlier supplemental browser/model checks, failed decoder/startup attempts,
Music ResizeObserver diagnostics and their exact links remain in the
[October 23 ledger](https://github.com/CyberBASSLord-666/LightForge/blob/8285b55b131f0a1ee718d8c6623b434acc1e255e/docs/ENGINEERING_COMPLETION_CHECKLIST.md)
and retained run artifacts. Their historical setup failures are not current
blocker diagnoses, and their passes do not replace fresh candidate qualification.
The Music resize loop was repaired and subsequent supplemental suites passed;
local browser-launch restrictions are environment-specific. No historical receipt,
failed diagnostic, model hash, policy or timing threshold was rewritten here.

## Verification contract

Fresh source-bound production, actual-model, browser and packaged Android
verification, registered-proof admission, original signing and exact payload
integrity remain mandatory. A successful host experiment or test APK does not
satisfy the remaining gates. The version-scoped automated-verification policy
makes physical/external observations optional for publication, not evidence for
unmeasured claims. In particular, retained MDX spectral diagnostics that failed
must stay failed; downstream/decoded-waveform passes are not exact spectral parity.

## Critical acceptance ledger

| Area | Current state and evidence | Required completion / acceptance |
| --- | --- | --- |
| Inference quality preservation | Fresh original-model Linux/JVM profile and scheduler/cancellation/recovery comparisons passed with finite, byte-identical complete outputs; source/model bindings matched. This is not end-to-end release qualification. | Preserve all graphs, precision, context, output and failed probes; rerun applicable source-bound checks after changes and complete browser/packaged Android qualification. |
| Meaningful inference improvement | Registered bounded-host median reduction is 18.8186%, with complete byte-identical outputs under the conditions above. Historical PR56 43.6% and published 2.4.1 32.6% results are separate comparisons, not additive gains. | Measure complete analysis, calibration overhead and representative physical devices before whole-song or phone claims. Never extrapolate stage timing to total analysis. |
| Release-hold integrity | Fail-closed candidate admission verifies the registered immutable producer proof and its execution closure; host proof is distinct from fresh consumer qualification. | Require exact-source sealed production and packaged Android evidence before publication. A runner label, version bump or host pass cannot bypass remaining gates. |
| Original Deux qualification | Original assets, full-output comparison and the scoped registered host timing proof are documented in VALIDATION. | Verify their identity for each candidate and complete remaining platform/full-pipeline gates; preserve original weights, graphs, precision and context. No reduced model or fabricated receipt. |
| Native runtime checks | Fresh Deux checks and GAME native/WASM final-output/checkpoint comparisons passed. GAME produced 98 demo notes and 5 Falcon notes with identical final output; unrounded intermediate differences remain recorded. | Preserve source/model/runtime bindings; host comparisons do not establish packaged Android, corpus accuracy, physical-device performance or whole-job speedup. |
| MDX numerical comparison | Mandatory decoded-waveform comparisons on three fixed inputs and the paired downstream gate passed with current source/model bindings. Internal spectral diagnostic remains false. | Preserve failed spectral diagnostics and existing mandatory thresholds; do not claim bit-identical MDX spectra, full-song accuracy or Android parity from these scoped passes. |
| Foreground/background analysis | Foreground service, checkpointed stages, cancellation and saving are implemented. Current changes suspend completed-preview watchdog budgets while the Activity is hidden or unfocused and reject stale callbacks after resume. Historical emulator evidence does not qualify these changes. | Fresh packaged Android tests: screen-off/background completion, Activity recreation, process interruption, cancel/resume, low-memory paths and durable result save. |
| Completed-project preview | Current source preserves saved arrangements when loading fails, fences superseded opens, and defers legacy Android draw-listener removal until after drawing. The four supplemental browser suites passed at head 4ab3ae8; screenshot review, actual-model browser and packaged Android qualification remain distinct requirements. | Restore completed and legacy projects; assert first rendered frame, transport/seek, repeated opening, cancellation and current compiled sequence agreement, including API 26-28 and focus loss/resume. |
| Browser and UI execution | All four supplemental browser suites passed in run 40002479708, with exact-source artifact bindings checked. Fail-closed diagnostic capture identified a real Music ResizeObserver loop. The resize repair passed all four hosted suites with clean diagnostics and visually checked Music/Guide/My shows/score captures. Local browser restrictions are environment-specific. No actual-model browser or packaged Android pass is inferred. | Complete and inspect actual browser diagnostics; separately run the real-model browser pipeline under the production evidence contract. DOM or supplemental diagnostics cannot replace sealed release evidence. |
| Physical phone | No fresh physical-phone observations were produced for this assessment. Earlier connector errors are historical, not a current connection diagnosis. | Use only supported, authorized connection routes when available. Physical testing is optional under the applicable version-scoped publication policy, but physical performance claims need observations. |
| APK/update identity | Original-signing and exact-payload publication controls are implemented. Source version is 2.4.2/20402; this ledger does not qualify an APK. | Full exact-source verification, original certificate outside Git, update-compatible install identity, alignment and checksum verification. Never replace the key or uninstall to evade incompatibility. |
| Release publication | Source version 2.4.2/20402 and its publication policy are defined; publication is established only by the matching signed payload, report and GitHub release. | Follow [BUILD](../BUILD.md); verify expected remote source, full CI, qualified signed APK and accessible public assets. Never overwrite a released version or use an older receipt to qualify new bytes. |

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
| Audio import | Android codec-dependent import and 44.1 kHz stereo PCM16 soundtrack conversion exist. Current WAV-reader changes reject malformed RIFF/format boundaries, unsupported extensible subtypes, inconsistent source lengths and invalid sample-read bounds. | Final-candidate malformed-audio and supported-codec tests, long/odd-duration files and source-clock fidelity. Analysis stems must not replace export soundtrack. |
| Projects and recovery | Current source adds duplicate rollback, acknowledged native deletion and transactional browser deletion, immutable settings at asynchronous save boundaries, and ownership checks for late project/analysis callbacks. Failed saved-project reads do not create replacement arrangements. | Complete final failure-injection and packaged Android tests; cancellation and clear-cache must preserve saved shows. Legacy opens must not silently recompose. |
| Editor and UX | Compose/Music/Outputs/Review, cue edits, Undo/Redo and individual output controls exist. The candidate loads the existing keyboard/modal-accessibility layer, restores focus after overlays, and keeps dialog actions reachable on short screens. | Rendered mobile/foldable review, accessibility, repeated clicks/navigation, meaningful failure/progress messages and reliable preview. DOM tests are not visual review. |
| Vehicle model | Source-backed Highland profile, black appearance option and official catalog research exist. | [Hardware evidence](VEHICLE_HARDWARE_EVIDENCE.md) explicitly limits lens mapping/travel. Do not invent unsupported lamps or movement commands; retain correct trunk/body-fixed geometry. |
| FSEQ/USB export | Validated 200-channel uncompressed FSEQ v2, 15/20 ms, soundtrack and project ZIP with CRC/size checks. Current source rejects inconsistent compiled-show metadata, channel counts and durations. Android export-destination grants are retired after completion/failure rather than accumulated indefinitely. | Fresh final-candidate round-trip, duration/movement budgets, filename/root layout, edited project and cache-independent export checks, plus interrupted-save recovery and repeated exports on Android. |
| Diagnostics | Bounded local diagnostic export and durable job summaries implemented. | Recover after process failure; avoid personal audio, credentials and project payload leakage; disclose incomplete observations. |
| Dependencies | Reviewed exporter/bootstrap pins and the scoped October 24 audit are recorded above; [dependency security](DEPENDENCY_SECURITY.md) preserves the remediation history and reproducible model-byte result. | Resolve remaining research declarations and assess transitive/native/system components separately. Research model-output parity and universal security clearance are not established by a clean scoped advisory result. |
| Artifact security | Archive credential/symlink rejection and repository hygiene strengthened. | Final packaging/provenance regression and rendered bundle binding must pass; keep signing secrets and personal files outside artifacts. |
| Repository/PR integration | PR56 reliability work and PR57/58 remediation are integrated. The registered campaign has a retained terminal proof; PR61 supplies bounded project parsing and consumer setup repairs without changing that proof. | Verify the final protected-main source after all source/documentation changes, preserving history, model notices and failed evidence. PR or local passes alone cannot qualify the merged candidate. |

## Next safe engineering steps

1. Verify the final protected-main candidate after all intended source and
   documentation changes. Bind registered host-proof admission and every fresh
   production/model/browser/Android receipt to that candidate. Preserve failed
   observations and the single-attempt campaign identity; do not rerun timing
   merely to obtain a preferable number.
2. Keep numerical comparisons bound to their exact inputs. Investigate retained
   MDX spectral discrepancies without weakening mandatory thresholds; rerun
   affected comparisons when source/model changes require it.
3. Verify original-signing identity, the exact qualified payload, release tag and
   public assets under [BUILD](../BUILD.md). Neither an earlier receipt nor a
   test-APK build establishes publication. Missing observations and denied
   operations never authorize fabricated evidence, replaced keys or bypasses.
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
