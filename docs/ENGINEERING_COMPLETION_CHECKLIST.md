# Comprehensive engineering completion checklist

Assessment refreshed: **2026-10-23, 18:57 UTC**. Reliability, input-integrity,
accessibility and verification changes are published to draft PR56 at
`84707a6a2e0333e5f97880a686bbe9ac2754664a`, including the original-model diagnostic workflow, strict UI error
capture and experimental read-only host observations. The captured resize
repair and dependency-setup recovery below are pending publication. Frozen-source local aggregate and scoped native checks
passed as detailed below; they are not a qualified release source identity.
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

## Current verification snapshot

- Frozen-source `npm test` passed: **793 Node tests**, **759 Python tests run
  (755 passed, 4 skipped)**, five quality-tool suites and all **85 analysis
  assets**. The aggregate's 933 source hashes matched the inspected candidate.
  This is engine/worker/DOM/archive/tooling coverage, not rendered browser or
  packaged Android qualification.
- Original pinned model preparation from upstream succeeded; no released APK
  supplied the model files. Fresh original-model Deux profile, scheduler,
  cancellation and recovery checks passed with complete finite, byte-identical
  outputs. All 27 source and 27 model bindings in the retained frozen profile
  receipt matched. These Linux/JVM checks do not establish controlled speed,
  whole-song, Android/ARM64 or thermal performance.
- Fresh GAME native/WASM comparisons produced identical final transcription
  and checkpoint-resume results for the public demo (98 notes) and Falcon
  mixture (5 notes). MDX decoded-waveform and paired downstream gates passed;
  **`spectral_diagnostic_passed` remains false** and is retained, not waived or
  relabelled exact spectral parity. GAME, MDX and downstream source/model
  bindings matched current bytes. Local records remain separate from sealed
  CI release evidence.
- Fresh advisory checks returned no known vulnerabilities for both npm
  lockfiles and the installed model-build Python environment. This does not
  cover every research tree, native library or Android system component, or
  establish numerical parity after research dependency changes.
- The local cloud exposes nine allowed CPUs but no `/sys/fs/cgroup/cpu.max`.
  GitHub production [run 39999491816](https://github.com/CyberBASSLord-666/LightForge/actions/runs/39999491816)
  now starts and fails the strict runner preflight with **Eight allowed CPUs
  are required**. Billing no longer prevents this new-head job from starting.
  No controlled speed proof exists. [BUILD](../BUILD.md) documents the supported
  controlled-runner path and fresh pre-build evidence generation. Only a
  protected main push can select the configured runner for release eligibility;
  manual dispatch is diagnostic. No eligible configured runner is verified.
- Local rendered browser execution remains blocked by environment-specific
  Chromium IPC/launcher restrictions and isolated loopback access. Supported
  GitHub [run 40002479708](https://github.com/CyberBASSLord-666/LightForge/actions/runs/40002479708)
  passed all four supplemental suites at exact head
  `4ab3ae8addc989cef5179347b7cef889d39428a2`: actual cold-restore WebGL,
  current application flows, background-progress/recovery UI and Highland
  optics/clock/graphics recovery. The downloaded diagnostic archive matches
  its GitHub SHA-256; 53 unique source bindings in the application, background
  and optics receipts match this head. All 36 supplemental PNGs were reviewed: no confirmed blocking layout or
  optics defect was found, but an application error banner in
  the Guide/My shows screenshots prevented a blanket clean claim. Follow-up
  [run 40006034916](https://github.com/CyberBASSLord-666/LightForge/actions/runs/40006034916)
  correctly failed its new diagnostic check on a ResizeObserver notification
  loop. The Music pitch lane synchronously changed the observed ancestor
  height. A narrow coalesced-animation-frame repair passes local tests; the
  pre-fix negative control fails. Hosted repair confirmation remains pending.
  The wide score screenshot was captured while its canvas was offscreen; settled visible-element captures in the follow-up run are crisp at all four
  widths, establishing this softness as capture timing, not a product defect. These are supplemental checks, not the actual-model browser pipeline,
  physical Android/Tesla observations or sealed production qualification.
- The strict inference replay verifier now treats each output head as eleven
  128-frame chunks, independently of candidate frequency-block batching.
  It accepts the original 1,727-call candidate geometry and rejects the previous
  erroneous 1,869-call geometry. Independent negative controls cover missing,
  extra and redistributed head calls. Performance thresholds, original model
  work, source identity and resource requirements are unchanged.
- Exact-head GitHub [hygiene](https://github.com/CyberBASSLord-666/LightForge/actions/runs/40003841187)
  and [quality-gate tooling](https://github.com/CyberBASSLord-666/LightForge/actions/runs/40003841078)
  checks passed. A tooling pass is not a locked-corpus quality result. GitHub
  inspection found no open standalone issues and only draft
  [PR56](https://github.com/CyberBASSLord-666/LightForge/pull/56), with no submitted
  reviews or inline review threads. No new release was published.

## Additional diagnostic coverage and follow-up

- An unprivileged supplemental workflow reproduces original model assets and
  licensed reference audio, runs the unchanged actual-model browser harness
  with a bounded external deadline, and retains only explicit diagnostic files.
  It does not sign/package an APK or create sealed production evidence.
  Its first [run 40006035003](https://github.com/CyberBASSLord-666/LightForge/actions/runs/40006035003)
  reproduced and rechecked all 85 model assets, then timed out downloading
  official ffmpeg dependencies before fixture or browser execution. Decoder
  setup is now separately bounded, reuses an available executable, and omits
  optional packages; exact archive and waveform provenance remain mandatory.
- [Experimental host qualification](EXPERIMENTAL_HOST_QUALIFICATION.md) describes
  a separately identified four-worker/three-CPU experiment and read-only host
  observation. Independent review and falsification tests passed, but no real
  performance measurements have run. The production verifier still rejects
  this lane. Local hidden cgroup ancestry remains ineligible; a hosted
  diagnostic in run 40006034916 observed four allowed CPUs, the global
  namespace and full cgroup mount, but rejected an unspecified strict
  control/counter condition. No exact cause is inferred. Safe reason codes
  will distinguish the failed observation in the next run; validators and
  eligibility requirements remain unchanged.
- Application browser QA now retains bounded, sanitized error reports and
  fails on unexpected handled errors or a recovery banner, even if an error
  has fallen out of the application log. Visible score captures verify backing
  dimensions before screenshots. These checks exposed the real Music
  resize-loop error rather than accepting the previous green page-error test.

## Verification publication scope

This source update contains source, tests, workflow changes and project
documentation. Newly generated local research records, diagnostic logs and
result snapshots are not part of this source update. The production workflow
separately retains run/attempt-scoped diagnostics, including failed inference
observations; those archives are not release authority. Do not interpret absent
records as successful checks. Reproduce verification using [BUILD](../BUILD.md);
the mandatory original-model, browser, Android and release checks remain
necessary for the applicable claims.

## Critical acceptance ledger

| Area | Current state and evidence | Required completion / acceptance |
| --- | --- | --- |
| Inference quality preservation | Fresh original-model Linux/JVM profile and scheduler/cancellation/recovery comparisons passed with finite, byte-identical complete outputs; source/model bindings matched. This is not end-to-end release qualification. | Preserve all graphs, precision, context, output and failed probes; rerun applicable source-bound checks after changes and complete browser/packaged Android qualification. |
| Meaningful inference improvement | Historical PR56 four-worker host passage reduction is 43.6%; published 2.4.1 host result is 32.6%. Neither establishes complete-song or phone benefit. | Measure repeated full passages and complete analysis including calibration cost, fallback and cache state. Do not substitute isolated frontend timing for neural or whole-job improvement. |
| Release-hold integrity | Version-independent source-bound hold remains enforced. The workflow now explicitly generates fresh inference timing evidence before packaging, purges prior current receipts and replays the existing verifier. Its read-only preflight rejects missing cgroup observations or insufficient allowed CPUs. Historical receipts remain unchanged. | Run on an eligible controlled host and retain passing exact-source evidence with unchanged numerical, resource and timing requirements. A runner label, version bump or successful preflight cannot bypass the hold. |
| Original Deux qualification | Pinned upstream assets and all 85 manifest entries verified. Fresh original-model host numerical, observer, scheduler and cancellation/recovery checks passed. Controlled timing qualification remains absent. | Complete the controlled timing prerequisite and remaining platform/full-pipeline checks; preserve all original weights, graphs, precision and context. No reduced model or fabricated receipt. |
| Native runtime checks | Fresh Deux checks and GAME native/WASM final-output/checkpoint comparisons passed. GAME produced 98 demo notes and 5 Falcon notes with identical final output; unrounded intermediate differences remain recorded. | Preserve source/model/runtime bindings; host comparisons do not establish packaged Android, corpus accuracy, physical-device performance or whole-job speedup. |
| MDX numerical comparison | Mandatory decoded-waveform comparisons on three fixed inputs and the paired downstream gate passed with current source/model bindings. Internal spectral diagnostic remains false. | Preserve failed spectral diagnostics and existing mandatory thresholds; do not claim bit-identical MDX spectra, full-song accuracy or Android parity from these scoped passes. |
| Foreground/background analysis | Foreground service, checkpointed stages, cancellation and saving are implemented. Current changes suspend completed-preview watchdog budgets while the Activity is hidden or unfocused and reject stale callbacks after resume. Historical emulator evidence does not qualify these changes. | Fresh packaged Android tests: screen-off/background completion, Activity recreation, process interruption, cancel/resume, low-memory paths and durable result save. |
| Completed-project preview | Current source preserves saved arrangements when loading fails, fences superseded opens, and defers legacy Android draw-listener removal until after drawing. The four supplemental browser suites passed at head 4ab3ae8; screenshot review, actual-model browser and packaged Android qualification remain distinct requirements. | Restore completed and legacy projects; assert first rendered frame, transport/seek, repeated opening, cancellation and current compiled sequence agreement, including API 26-28 and focus loss/resume. |
| Browser and UI execution | All four supplemental browser suites passed in run 40002479708, with exact-source artifact bindings checked. Fail-closed diagnostic capture identified a real Music ResizeObserver loop. The reviewed resize repair passes local tests and awaits hosted confirmation. Local browser restrictions are environment-specific. No actual-model browser or packaged Android pass is inferred. | Complete and inspect actual browser diagnostics; separately run the real-model browser pipeline under the production evidence contract. DOM or supplemental diagnostics cannot replace sealed release evidence. |
| Physical phone | No fresh physical-phone observations were produced for this assessment. Earlier connector errors are historical, not a current connection diagnosis. | Use only supported, authorized connection routes when available. Physical testing is optional under the applicable version-scoped publication policy, but physical performance claims need observations. |
| APK/update identity | Original-signing and exact-payload publication controls implemented; the available original private identity was checked locally against the documented public certificate. No new final APK is qualified by this ledger. | Deliberate new version, full exact-source verification, original certificate outside Git, update-compatible install identity, alignment and checksum verification. Never replace the key or uninstall to evade incompatibility. |
| Release publication | Latest published release remains 2.4.1; the current candidate still uses 2.4.1/20401 for development. No new final APK or release is qualified. | Follow [BUILD](../BUILD.md); deliberately choose a new version, establish its applicable publication authority/policy, and verify expected remote commit, full CI, qualified signed APK and public release assets. Existing version-scoped exceptions do not automatically authorize a future version. Do not overwrite a released version. |

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
| Dependencies | Exact pins are retained. October 23 advisory checks found no known vulnerabilities in both npm lockfiles and the installed model-build Python environment. Earlier coordinated research changes remain documented in [dependency security](DEPENDENCY_SECURITY.md). | Research model-output parity and comprehensive research/native/system-component audits remain unverified. A clean advisory result for the checked environments is not universal security clearance. |
| Artifact security | Archive credential/symlink rejection and repository hygiene strengthened. | Final packaging/provenance regression and rendered bundle binding must pass; keep signing secrets and personal files outside artifacts. |
| Repository/PR integration | Only draft PR56 is open, with no standalone open issues or submitted PR reviews/inline threads. Published head `a5063c5` has passing hygiene/quality-tool and four-suite supplemental browser CI, and a strict production CPU-preflight failure. PR43 is not an open integration task. | Verify publication of the narrow inference replay correction and retain the draft/release hold until complete qualification. Preserve required history, model notices and failed evidence. |

## Next safe engineering steps

1. Confirm the reviewed Music resize repair and separated decoder setup
   on GitHub; inspect the more specific host diagnostic. Run the remaining
   actual-model browser diagnostics without presenting supplemental results
   as sealed production or packaged Android evidence.
2. Keep the passed aggregate and scoped native comparisons bound to their exact
   inputs. Investigate retained MDX spectral discrepancies without weakening
   mandatory thresholds; rerun affected comparisons after source/model changes.
3. Obtain fresh timing qualification on an eligible, already-authorized
   controlled host; complete the actual-model browser and packaged Android
   gates. Then establish the deliberate new version and original-signing
   publication identity. Missing observations and denied operations are not
   permission to fabricate evidence, replace keys or bypass restrictions.
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
