# Analysis benchmark and diagnostic contract

`tools/analysis_benchmark_contract.py` is the versioned, dependency-free
contract for evidence emitted by LightForge analysis jobs. It is intentionally
separate from the choreography engine: collecting a metric must never change an
audio feature, event timestamp, model, or FSEQ output.

For the live WebView cache/checkpoint implementation and its recovery rules, see
[`ANALYSIS_CACHE_RECOVERY.md`](ANALYSIS_CACHE_RECOVERY.md). The Python contract
and OPFS implementation deliberately share the same fail-closed principles,
but the contract is not a substitute for exercising the production cache path.

It provides four things that release evidence needs:

1. A canonical content address for analysis caches.
2. Atomic, checksummed JSON checkpoints with identity validation.
3. Per-stage timing, resource, cache, checkpoint, and provenance telemetry.
4. Fail-closed corpus binding and baseline/candidate comparability checks.

The contract is designed for the native Android runner, WebView workers, desktop
parity harnesses, and CI to emit the same JSON. It has no model dependency and
does not contain audio or source paths.

## Identity boundaries

Analysis cache keys are constructed from exactly the inputs that affect the
analysis result:

```python
identity = analysis_cache_identity(
    audio_sha256=audio_hash,
    model_versions={"deux": deux_sha, "game": game_version},
    analysis_configuration=analysis_settings,
    preprocessing_version="pcm-44100-v2",
    pipeline_version="7.0.0",
)
stem_key = content_address("stems", identity)
```

Do not put UI theme, preview resolution, or choreography-only settings in a stem,
rhythm, vocal, drum, bass, or structure identity. Those settings have their own
cache domain. A vehicle profile change should normally invalidate only vehicle
realization, FSEQ, and validation caches.

The cache format is content-addressed, written to a temporary file, fsynced, and
atomically replaced. Reuse verifies the key, payload digest, and expected
identity. Invalid or stale records raise `CacheCorruptionError`; callers must
recompute rather than silently using a mismatched result.

## Required diagnostic shape

Each completed, cancelled, or failed analysis attempt emits one report with:

```json
{
  "schema_version": 1,
  "run_id": "stable-run-id",
  "track_id": "locked-corpus-track-id",
  "provenance": {
    "workload": {
      "corpus_id": "locked-corpus-id",
      "corpus_manifest_sha256": "...",
      "audio": {
        "content_sha256": "...",
        "duration_seconds": 180.0,
        "canonical_sample_rate": 44100,
        "channels": 2
      },
      "analysis_configuration": {}
    },
    "implementation": {
      "pipeline_version": "...",
      "preprocessing_version": "...",
      "model_versions": {"deux": "..."}
    },
    "environment": {
      "hardware_fingerprint": "opaque-stable-device-id",
      "runtime_backend": "onnxruntime-android-cpu",
      "runtime_version": "...",
      "accelerator": {"provider": "cpu", "threads": 4},
      "random_seed": 42,
      "thermal_profile": "controlled-cold"
    }
  },
  "execution": {"wall_clock_seconds": 0, "cpu_seconds": 0},
  "stages": [],
  "metrics": {},
  "outputs": {},
  "warnings": []
}
```

Every stage records its actual wall and CPU time plus any separately measured
preprocessing, initialization, inference, postprocessing, or waiting time. It
also records peak RSS/accelerator allocation when available, I/O bytes,
temporary-storage use, a cache hit/miss/disabled status, and checkpoint write or
reuse status. Process high-water RSS is explicitly labelled as such; it is not
misrepresented as a precise per-stage allocation delta.

Suggested stable stage IDs are:

- `audio_decode`
- `resample_normalize`
- `shared_features`
- `source_separation`
- `rhythm_analysis`
- `vocal_analysis`
- `drum_analysis`
- `bass_analysis`
- `melody_analysis`
- `structure_analysis`
- `semantic_timeline`
- `choreography_planning`
- `collision_resolution`
- `vehicle_realization`
- `fseq_generation`
- `perceptual_validation`

These IDs are additive. A legacy pipeline can report only the stages it owns,
but a production benchmark policy should make all required stages mandatory.

## Locked corpus and comparable runs

A private, version-controlled corpus manifest contains only identifiers,
cryptographic audio identities, durations, tags, and golden artifact hashes; it
does not store copyrighted audio. `corpus_manifest_sha256(manifest)` binds every
diagnostic to that exact manifest. `validate_against_corpus(report, manifest)`
rejects an unknown track, an audio hash mismatch, or a stale manifest identity.

`ensure_comparable(baseline, candidate)` blocks a performance claim if either
side differs in:

- corpus or audio identity;
- analysis configuration or preprocessing version;
- model versions;
- hardware, runtime, or accelerator configuration;
- random seed; or
- thermal profile.

The pipeline source version is intentionally allowed to change: it is normally
the candidate under test. A model version is not allowed to change in a
performance-only comparison.

`benchmark_run(diagnostic)` projects a validated diagnostic into the existing
`performance_quality_gate.py` run shape without breaking that gate's readers.
It includes provenance and a diagnostic digest for future fail-closed gate
integration.

## Runtime integration pattern

The code below is for a host benchmark or bridge adapter. The Android/Web
implementation should collect equivalent values from its native and worker
timers; it must not run a second analysis solely to populate diagnostics.

```python
recorder = AnalysisRunRecorder(track_id, provenance)
with recorder.stage("source_separation", cache_status="miss", cache_key=stem_key) as stage:
    # Run the production separator exactly once.
    stage.timing("model_initialization_seconds", model_init_seconds)
    stage.timing("inference_seconds", inference_seconds)
    stage.resource("read_bytes", bytes_read)
    stage.checkpoint("written", stem_key)

report = recorder.finalize(metrics=quality_and_performance_metrics, outputs=output_digests)
```

The temporary cache is disposable. Saved project analysis, curated goldens, and
exported FSEQ remain separate durable products. Diagnostic data must never
include a private file path, audio payload, access token, API key, password,
authorization value, or raw exception string that could expose one.

## Host resource counters

Host adapters may attach `execution.resource_counters` using
`lightforge-resource-counters-v1`. This closes the diagnostic projection's
previous inability to bind CPU utilization, energy, temperature rise, and
accelerator utilization. It does not collect those measurements or make
unsupported browser observations available.

The object has `schema_version: 1`,
`protocol: "lightforge-resource-counters-v1"`, and a positive
`elapsed_seconds` exactly matching `execution.wall_clock_seconds`. It contains
only the domains actually observed:

| Domain | Raw observation | Derived resource metric |
| --- | --- | --- |
| `cpu` | `logical_cpu_count`, the measured logical CPU capacity | `cpu_utilization_percent`: execution CPU seconds / wall seconds / logical CPU count × 100 |
| `energy` | Opaque `counter_id`, integer `start_microjoules` and `end_microjoules` from one cumulative counter | `energy_joules`: observed counter difference / 1,000,000 |
| `thermal` | Opaque `sensor_id` and `samples`, each containing `elapsed_seconds` and `celsius` | `thermal_delta_celsius`: highest observed temperature minus the first observation |
| `accelerator` | Opaque `counter_id`, integer `start_busy_nanoseconds` and `end_busy_nanoseconds` from one cumulative busy-time counter | `accelerator_utilization_percent`: observed busy seconds / wall seconds × 100 |

Temperature samples must be strictly ordered, begin at zero, and end at the
execution window boundary. The initial sample is included in the maximum, so a
run that only cools has zero measured temperature rise. Counter resets, wraps,
invalid values, out-of-window samples, and utilization above measured capacity
are rejected. A collector must recollect an ambiguous counter window; it must
not infer the number of wraps or invent a zero. Integer counter differences
are computed before conversion to floating point.

These are private host observations reduced to opaque counter identities and
numeric samples. Do not put sensor paths, device serial numbers, credentials,
or URLs into them. The source counter and CPU-capacity definitions must match
between paired runs. The profiler receipt retains the raw observations, and
each reported metric must equal its derived value. Missing domains remain
unobserved and continue to block the release gate when required.

A collector must measure the complete production workload with a consistent
resource scope and synchronized boundaries. `AnalysisRunRecorder` measures
its own Python process CPU; it does not silently include browser, worker, or
native child processes. Whole-application benchmarking therefore needs an
adapter that accounts for those processes and supplies the corresponding
execution record. The current browser resource projection and CI parity
fixtures are supplementary observations, not such a collector. An approved
benchmark host or external measurement feed can supply energy and temperature;
physical phone or Tesla observations are not required.

## Browser resource diagnostics

The WebView analyzer additionally emits a bounded, source-validated
measurement projection described in
[`RESOURCE_DIAGNOSTICS.md`](RESOURCE_DIAGNOSTICS.md). It is intentionally not
an automatic quality-gate metric: browser CPU utilisation, GPU utilisation and
many allocator values are unavailable or only partially instrumented. The
adapter may carry exact finite values such as measured stage wall time,
scheduler wait and observed OPFS bytes into a benchmark record, but must retain
the contract's explicit availability state and must not replace unavailable
values with zero. This supplementary evidence cannot establish equivalence,
the 75% reduction target, or production readiness without paired locked-corpus
results.

## Completed app-run observations

The production background runner can record one `analysisRunObservation` only
after a **fresh** analysis and choreography compilation have both succeeded,
as part of the ordinary atomic completed-project commit. Before a new fresh
analysis begins, the Android job bridge atomically clears any prior observation
and refreshes its conflict-protection source hash. A failed, cancelled,
interrupted, malformed, or compile-failed fresh run therefore leaves no stale
observation. A cached/reused analysis does not manufacture a fresh observation.

The schema is an exact static allowlist of bounded primitive fields:
aggregate analysis/choreography/total timing; allowlisted stage timing;
restoration counts; fixed analysis/separation family labels; a fixed runtime
kind; and resource-summary availability. It never copies audio bytes or
hashes, project/track IDs, names, lyrics, paths/URLs, cache keys, raw model IDs,
backend strings, device/build IDs, timestamps, exceptions, settings, event
data, credentials, or diagnostics. All durations and counters are bounded and
rounded. A restored stage is explicitly unavailable with
`restored-stage-zero-cost`; unavailable clocks are never converted to zero.

The observation is out of analysis cache identity, semantic music, planner
input, FSEQ compilation, validation score inputs, golden outputs, and
quality-gate receipts/provenance. Project-backup export also removes it before
freezing the editable JSON, so it cannot perturb exported-project byte
comparisons. Observation construction is fail-closed: invalid data is not
persisted and cannot alter analysis or choreography.

`validate_completed_app_run_observation()` and
`observed_app_run_time_projection()` accept this supplemental object. The
projection is marked `not_comparable`, exposes no raw runtime/model profile,
keeps unavailable values null, and cannot change `metrics.performance` or a
benchmark pass result. It must not be used to establish a baseline/candidate
speed claim, quality equivalence, the 75% target, or production readiness.
