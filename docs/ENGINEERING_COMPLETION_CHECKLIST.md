# Comprehensive engineering completion checklist

Assessment refreshed: **2026-10-23**. Integration baseline: PR56 head
`da5881ddcd2ecb39470ea1febd7fc1dc7cbe90c1`, followed by the current candidate's
reliability, input-integrity, accessibility and verification-workflow changes.
Final candidate verification is still in progress; this snapshot does not assign
a completed aggregate test count or a final qualified source identity.
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

- Original pinned model preparation from upstream is now unblocked. The current
  analysis-asset inventory passed `tools/verify_analysis_assets.py`; no released
  APK was used to supply these model files. Asset integrity is not numerical or
  end-to-end qualification.
- The pinned host toolchain and native-test dependencies are available. Fresh
  native comparisons and final aggregate checks are pending; historical results
  and focused regression passes do not fill those gaps.
- Fresh advisory checks returned no known vulnerabilities for both npm
  lockfiles and the installed model-build Python environment. This does not
  cover every research tree, native library or Android system component, or
  establish numerical parity after research dependency changes.
- The current cloud runner exposes nine allowed CPUs but does not expose
  `/sys/fs/cgroup/cpu.max`. The new read-only eligibility preflight correctly
  refuses inference timing qualification rather than inventing quota or
  resource observations. [BUILD](../BUILD.md) now documents the supported
  controlled-runner path and fresh pre-build evidence generation. A configured
  runner may be selected only by a protected main push for release eligibility;
  manual dispatch remains diagnostic. No eligible configured runner is verified
  for this candidate, so setup and the qualifying main-push run remain pending.
- Fresh browser execution remains blocked by the available environment:
  Chromium startup encounters IPC restrictions, the permitted alternate
  launcher cannot start, and the separate cloud browser cannot reach the
  isolated loopback QA server. Focused DOM tests are not rendered browser
  evidence. Current packaged Android qualification is also outstanding.
- GitHub inspection found no open standalone issues and only draft
  [PR56](https://github.com/CyberBASSLord-666/LightForge/pull/56), with no submitted
  reviews or inline review threads. Its latest recorded exact-head workflows
  failed before production steps ran; the recorded failure reports an account
  billing lock and Android was skipped. The account's present billing state is
  not established by that historical attempt. No new release was published.

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
| Inference quality preservation | Implemented original Deux weights, Float32, complete context/graphs and exact-output comparison. PR56 has retained host evidence, not current end-to-end qualification. | Regenerate complete source-bound original-model evidence for the final candidate; preserve all graphs, output, model settings and failed probes. |
| Meaningful inference improvement | Historical PR56 four-worker host passage reduction is 43.6%; published 2.4.1 host result is 32.6%. Neither establishes complete-song or phone benefit. | Measure repeated full passages and complete analysis including calibration cost, fallback and cache state. Do not substitute isolated frontend timing for neural or whole-job improvement. |
| Release-hold integrity | Version-independent source-bound hold remains enforced. The workflow now explicitly generates fresh inference timing evidence before packaging, purges prior current receipts and replays the existing verifier. Its read-only preflight rejects this runner's missing cgroup observations. Historical receipts remain unchanged. | Run on an eligible controlled host and retain passing exact-source evidence with unchanged numerical, resource and timing requirements. A runner label, version bump or successful preflight cannot bypass the hold. |
| Original Deux qualification | Model preparation and complete manifest integrity checks are now unblocked using pinned upstream assets. Fresh final-candidate numerical and performance qualification is not established. | Complete original-model comparisons and the controlled timing prerequisite; preserve all original weights, graphs, precision and context. No reduced model or fabricated receipt. |
| Native runtime checks | Production host, lifecycle and model-comparison harnesses and pinned dependencies are available. Fresh comparisons are in progress; newly generated records remain separate from historical release evidence. | Finish exact-source comparisons and preserve source/model/runtime bindings; scoped host checks do not replace packaged Android qualification. |
| MDX numerical comparison | The existing protocol distinguishes mandatory decoded-waveform tolerances from separately recorded internal spectral diagnostics. | Run official inputs and downstream gates; preserve failed diagnostics and existing mandatory thresholds. |
| Foreground/background analysis | Foreground service, checkpointed stages, cancellation and saving are implemented. Current changes suspend completed-preview watchdog budgets while the Activity is hidden or unfocused and reject stale callbacks after resume. Historical emulator evidence does not qualify these changes. | Fresh packaged Android tests: screen-off/background completion, Activity recreation, process interruption, cancel/resume, low-memory paths and durable result save. |
| Completed-project preview | Current source preserves saved arrangements when loading fails, fences superseded opens, and defers legacy Android draw-listener removal until after drawing. Current rendered first-frame verification remains blocked. | Restore completed and legacy projects; assert first rendered frame, transport/seek, repeated opening, cancellation and current compiled sequence agreement, including API 26-28 and focus loss/resume. |
| Browser and UI execution | Current cloud Chromium/alternate-launcher restrictions and isolated QA-server access prevent fresh rendered coverage. Focused DOM tests cover narrower behavior only. | Use a supported reachable browser environment, then run current browser, background UI, restore and real-model integration harnesses. Do not label never-run stages passed or bypass environment restrictions. |
| Physical phone | No fresh physical-phone observations were produced for this assessment. Earlier connector errors are historical, not a current connection diagnosis. | Use only supported, authorized connection routes when available. Physical testing is optional under the applicable version-scoped publication policy, but physical performance claims need observations. |
| APK/update identity | Original-signing and exact-payload publication controls implemented. No new final APK is qualified by this ledger. | Deliberate new version, full exact-source verification, original certificate outside Git, update-compatible install identity, alignment and checksum verification. Never replace the key or uninstall to evade incompatibility. |
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
| Repository/PR integration | October 23 GitHub inspection found only draft PR56 open and no standalone open issues. Its last remote head is `da5881d`; the current local candidate adds further changes. No submitted PR reviews or inline review threads were present. PR43 is not an open integration task. | Review the actual final diff and source-bound evidence, verify any published head and its exact-head CI, and retain the draft/release hold until qualification. Preserve required history, model notices and failed evidence. |

## Next safe engineering steps

1. Complete final aggregate checks and preserve every blocked, failed and
   never-run stage above. Record results against the final candidate rather
   than freezing intermediate test counts.
2. With original assets now available, finish original-model comparisons and
   official MDX inputs/downstream checks; investigate retained spectral
   diagnostic discrepancies without weakening mandatory thresholds.
3. Run the fresh timing prerequisite on an eligible controlled host, then use
   supported browser and packaged Android environments for their remaining
   gates. Missing cgroup observations and denied browser operations remain
   blockers, not permission to fabricate evidence or bypass restrictions.
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
