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

