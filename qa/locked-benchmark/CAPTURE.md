# Capture actual analyzer and compiler outputs

`capture-app.cjs` executes the existing `MusicAnalyzer.analyze` and
`ShowCompiler.generate` in Chromium, with production workers and model bytes.
It accepts a real WAV whose complete file SHA-256 is supplied in advance. The
result is raw engineering evidence. It is **not** a complete 231-metric
benchmark, an approved corpus, an authenticated human review, or a qualified
release. `production_ready` always remains false.

Use Node 20 or later and the repository's pinned Playwright installation with
its Chromium browser. `PLAYWRIGHT_EXECUTABLE_PATH` may select an existing
compatible Chromium binary. No dependencies are installed by the collector.

## Lock an exact application snapshot

The application root must contain its complete `web/` distribution, including
all production model files. A distribution extracted from an independently
verified candidate APK is suitable. This command records actual file bytes;
review and retain the lock before collecting formal measurements:

```bash
node qa/locked-benchmark/capture-app.cjs inventory \
  --app-root /absolute/candidate-source \
  --output /private/capture/web-lock.json
```

The command prints the canonical `web_manifest_sha256`. The capture verifies
every inventory file before and after execution, and checks the application's
own analysis asset manifest. It rejects symlinks and extra or missing files.
Generating a fresh lock does not establish that its declared Git commit was
reviewed: release orchestration must independently bind that lock to the
verified candidate. The capture reports declared Git identities and measured
web bytes without treating either as proof of successful GitHub CI.

Create an identity JSON object with **exactly** these fields, using actual
values: `source_commit`, `source_tree_sha`, `web_manifest_sha256`,
`pipeline_version`, `preprocessing_version`, `track_id`, `run_id`, and
`report_side` (`baseline` or `candidate`). Corresponding baseline/candidate
attempts must use the same stable `run_id` in separate output directories.
Do not use an audio title or other personal information as an opaque ID.

Create a separate explicit configuration JSON object containing
`analysis_options` and `show_settings`. `analysis_options.analysisQuality`
must select `precision` or `balanced`. `show_settings.seed` must be a uint32
and `show_settings.stepMs` must be 15 or 20. Other options are passed unchanged
to the application; inspect `effective_analysis_options` and
`effective_show_settings` in the output to see what it used. The harness
supplies the source-audio cache identity and project ID. It forbids caller
overrides of native execution, cache keys, or identity fingerprints.
The analysis options record is the exact public API argument object; internal
defaults remain defined by the locked production source. The show-settings
record is the compiler's normalized result. Pipeline/preprocessing labels
are caller declarations, with their actual source/model bytes retained in
the inventory lock; this tool does not infer an approved runtime profile.

```bash
node qa/locked-benchmark/capture-app.cjs capture \
  --app-root /absolute/candidate-source \
  --wav /private/approved-audio/input.wav \
  --audio-sha256 ACTUAL_PREAPPROVED_WAV_SHA256 \
  --web-manifest /private/capture/web-lock.json \
  --identity /private/capture/candidate-identity.json \
  --configuration /private/capture/analysis-configuration.json \
  --output-dir /private/capture/candidate-pair-01
```

The output directory must not exist, and its parent must exist. The collector
creates it with private permissions and never overwrites an earlier attempt.
`--timeout-seconds` bounds browser execution (default 3600, maximum 14400).
The accepted WAV encodings are mono/stereo RIFF PCM16/24/32 and float32 with
consistent headers, exactly 44.1 kHz sample rate, a duration of 1 second to
4 hours, and at most 2 GiB. The complete production pipeline requires this
decoded rate; this runner does not run the app importer or resample audio.
Use approved, declared preprocessing before locking any converted audio.
Resampling changes sample data and must not be described as lossless.

## Scope and outputs

The harness loads the actual analyzer/compiler scripts without the app's UI
or 3D preview. A fresh browser and loopback origin give empty application
storage and disabled HTTP caching. This is **only cold application state**:
it does not reset OS page caches or establish thermal equivalence. It does
not implement warm/resumed experiments or Android native model bridges.
External page requests are blocked, and any such request fails capture.

`capture.json` contains input identities, complete configuration, actual
browser-call timings, actual engine/resource reports, requested source hashes,
and hashes of all saved artifacts. Monotonic stdout phase events identify
analysis and compilation start/end for an external process monitor. A monitor
wrapping the whole CLI must label its interval as including validation,
browser startup, compilation, serialization and teardown; that interval is not
the analyzer-only performance target. Energy, CPU utilization and thermal
measurements are not invented when the application cannot observe them.

The runner saves the original `analysis.json`, `show.json`, `compiled.json`,
`progress.json`, exact frame/header bytes and `lightshow.fseq`. When emitted,
the original `show.perceptualValidation` JSON is also saved unchanged in
`perceptual-validation.json` for the synchronization projector. `show.json`
retains the full synchronization and perceptual-validation sidecars, including
omitted/invalid event counts and model-based timing assumptions. Actual frame
dimensions, header dimensions and the compiler's frame digest must agree.

The following canonical JSON projections exclude the analyzer engine's
operational timings. Their hashes describe observed outputs; repeatability
across actual executions still needs verification. They become approved
baseline goldens only after the corpus/acceptance procedure:

| Output category | Actual application fields |
| --- | --- |
| Semantic timeline | `music.semanticTimeline` |
| Rhythm map | Emitted beat, meter, phrase and optional rhythm hierarchy fields |
| Vocal map | `music.vocals`, plus emitted vocal semantics and semantic links |
| Bass map | `music.bassNotes` and `music.bassAnalysis` |
| Drum map | `music.percussionAnalysis`, only if emitted |
| Section map | `music.sections`, plus emitted `recurrenceAnalysis`, `recurrenceEvidence` and `recurrenceSidecar` |
| Salience map | `music.musicSalience` |
| Choreography plan | Actual choreography, movements, sections and effective settings |
| FSEQ characteristics | Header fields, frame dimensions and actual byte digests |
| Validation report | Actual `show.validation` |

Missing categories remain listed in `missing_output_categories` with no hash.
The runner never creates a drum map from generic onsets or invents normalized
scores. Estimated percussion, accompaniment-derived bass and unverified
physical behavior retain their original provenance. An empty emitted result
is preserved as the application's result, not presented as accurate detection.

Formal qualification still needs approved corpus annotations, a controlled
runtime/profile, real paired execution, metric adapters, required external
telemetry, reviewed output differentials and authenticated blinded review.
Physical phone/Tesla observations remain optional.

## Verification

`python3 tests/test_locked_app_capture.py` runs the Node protocol tests, including
wrong audio/source locks, malformed WAV data, path/range boundaries, absent
output evidence, forbidden identity overrides, and failure receipts. The
existing `verify_v2.py` discovers this Python wrapper automatically. Actual
model execution is a separate, explicitly selected engineering smoke or
approved benchmark collection; the unit fixtures are never a release corpus.

## Recorded engineering smoke scope

A development smoke used the complete verified candidate web distribution at
`f2a1c65f35efbfd43b0bd7832bde3f42ea7abe79`, the actual 64-second bundled demo,
Balanced/WASM models and Chromium 153. Analysis took 563.093 seconds and
compilation took 0.288 seconds, producing 3,200 valid 200-channel frames at
20 ms. Every analysis stage executed without a restored checkpoint. This
single uncontrolled host observation establishes execution, not a speedup,
statistical comparison or production runtime guarantee.

The retained original capture records the earlier collector revision that
executed the models. Subsequent reviewed changes corrected input validation,
failure metadata and output-field projections without changing the app or
repeating inference. The final projections recover all ten emitted output
categories from those hash-verified raw results, including explicitly
estimated original-mix percussion.

The original perceptual sidecar contains 135 accepted events with no invalid
or omitted events. That event count does **not** imply complete metric
coverage. The reviewed synchronization projector observes only ten command
timing metrics for bass/vocals and leaves 101 synchronization metrics
unobserved under either explicitly selected timing basis. No predicted
perceptual headline metric is observed, and no physical measurement is
claimed. Missing measurements remain missing.
