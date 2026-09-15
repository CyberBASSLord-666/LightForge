# Application timing observations

The analysis workers and compiler now emit real, cumulative clock observations for 17 previously missing timing scopes. `tools/project_performance_timings.py` maps captured observations to the existing 26 performance metric IDs. It does not produce a complete qualified profiler diagnostic or certify the performance gate.

Run the projector against a completed capture receipt:

```bash
python3 tools/project_performance_timings.py --capture capture.json --output performance-timings.json
```

The tool records the exact input digest, source lock, served file hashes and the capture's existing source declaration. Git commit/tree declarations remain caller-declared until independent release orchestration binds them to the inventory. Output creation does not overwrite an existing file.

## Producer scopes

| Metric suffix | Measured execution boundary |
|---|---|
| `audio_decode_seconds` | Analysis-time PCM parsing/downmix and numeric normalization, including cached full-rate voice reads after IO completes. |
| `resample_normalize_seconds` | Actual WAV, vocal, bass and stem-output FIR kernels; copies and empty kernels do not become measured resampling. |
| `feature_generation_seconds` | DSP features, rhythm mel model frontend, vocal features and bass kernels. Rhythm frontend time also appears in inference. Separator encoding is preprocessing. |
| `tempo_inference_seconds` | Global/local period estimates and final interval/BPM estimation. |
| `beat_tracking_seconds` | Passage construction and actual manual/transformer/CRNN beat decoding and annotation. |
| `downbeat_tracking_seconds` | Meter scoring, phase selection and downbeat selection. |
| `drum_analysis_seconds` | Only the enabled percussion estimator. Estimated percussion provenance remains unchanged. |
| `structural_analysis_seconds` | Section, recurrence and phrase/impact construction; selected optional recurrence evidence capture and sidecar construction. Validation and IO are separate. |
| `model_initialization_seconds` | Every executed WASM session creation, including lazy and repeated initialization. |
| `model_inference_seconds` | Every executed WASM model run, including frontend, ensemble and GAME diffusion/subgraph calls. |
| `preprocessing_seconds` | Selected input layout, reflection, peak checks, tensor preparation and separator encoding kernels. |
| `postprocessing_seconds` | Selected output conversion, stitching, score reduction, fusion and PCM serialization kernels. |
| `choreography_planning_seconds` | Setup, semantic, movement and light candidate/diagnostic planning, excluding measured allocation and realization. |
| `collision_resolution_seconds` | Light allocation, conflict resolution and rescue/fallback attempts that actually execute. |
| `vehicle_realization_seconds` | Movement/light frame painting, interior mapping and manual cues. No physical observation is involved. |
| `validation_seconds` | Compiler synchronization, choreography quality, perceptual and format validators, including actual repeated validation. |
| `fseq_generation_seconds` | Header serialization in the normal compiler worker. `ShowEngine.fseq()` additionally measures payload copying only when that function actually executes. |

Worker observations remain in `music.engine.stages[stage].profile`. Compiler observations are returned separately as `generated.profile` and captured as `compiler-profile.json`; they are excluded from deterministic show metadata, saved compiled checksums and FSEQ payloads. The existing telemetry accumulator keeps complete named totals beyond its 96-row raw history cap. Identical canonical names use sequential disjoint intervals; nested scopes use different metric names and are explicitly described.

The five new Node suites are listed in `tools/verify_v2.py`; the new Python projection suite is discovered by its existing Python test glob. The compiler's new use of the existing telemetry module makes `web/analysis/telemetry.js` part of the common browser-source inventory. Analysis asset hashes must be regenerated from the actual integrated source; the asset entry population is unchanged.

## Availability and qualification boundaries

- A missing, skipped, disabled or unsupported operation does not create a zero-duration observation. A real measured zero remains valid.
- Invalid clocks and incomplete named summaries remain unavailable. A valid earlier completed span survives a later unrelated clock failure; the whole-stage wall measurement does not.
- If one contributing named interval is unavailable, valid subtotals are retained as partial and excluded from aggregate metric values. Missing/old instrumented stages, omitted summary names and unknown runtime coverage likewise prevent a complete aggregate.
- A native-to-WASM retry discards the failed attempt's detailed stage profiles in the current analyzer. The projector retains final-attempt subtotals as partial, including scheduler/cache observations; the outer capture analysis interval still measures the whole analyzer call.
- Native session/inference/subphase timings are not reconstructed from bridge waits. Native and unknown-runtime aggregates remain partial where their subphases are not connected.
- The capture starts from decoded WAV. These PCM probes do not measure compressed-media import.
- `checkpoint_resume_overhead_seconds` stays unavailable: a cache hit alone does not establish interrupted-parent lineage or the actual recovery boundary.
- The current capture invokes compiler header creation and transfers existing frames. It does not invoke full application FSEQ payload export; header timing remains partial for the full metric. Node artifact concatenation is not substituted for application export.
- Preprocessing/postprocessing are explicitly selected kernel scopes, not proof that every validation, allocation, cleanup, IO or persistence operation has been exhaustively timed. Admission wait is similarly one selected synchronization scope.
- The original baseline has no new probes. A future paired comparison must establish the same approved measurement scopes on both source-bound implementations; this change does not manufacture baseline observations or a 75% improvement result.

Inclusive stage durations overlap named inner probes. Never sum all 26 metrics to reconstruct total elapsed time. Acceptance policy, controlled corpus runs, complete resource observations, statistical comparison, authenticated human review, original signing and publication remain separate release work. Physical phone/Tesla observation is not introduced as a requirement.
