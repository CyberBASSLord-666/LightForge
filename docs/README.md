# Documentation index

## Start here

| Document | Responsibility |
| --- | --- |
| [User guide](USER_GUIDE.md) | Create, edit, recover, back up and export shows |
| [Build and release](../BUILD.md) | Reproduce the app and qualify an exact candidate |
| [Architecture](../ARCHITECTURE.md) | Source ownership and dependency boundaries |
| [Capability and readiness map](ARCHITECTURE_AND_PRODUCTION_READINESS.md) | Enabled, optional and unproven features |
| [Validation](../VALIDATION.md) | Published evidence and limits on claims |
| [Repository maintenance](../REPOSITORY.md) | Source/artifact policy and hygiene checks |
| [Assets](../ASSETS.md) | Model reproduction, provenance and restrictions |
| [Versioning](../VERSIONING.md) | Version metadata and original signing identity |
| [Release notes](../RELEASE_NOTES.md) / [Changelog](../CHANGELOG.md) | Current release and historical changes |

## Analysis and choreography contracts

| Contract | Scope |
| --- | --- |
| [Cache recovery](ANALYSIS_CACHE_RECOVERY.md) | Checkpoint identity, corruption and reuse |
| [Scheduler](ANALYSIS_SCHEDULER.md) | Resource-aware execution and checkpoint behavior |
| [Rhythm hierarchy](RHYTHM_HIERARCHY.md) | Validated rhythm sidecar and timing hierarchy |
| [Tonal structure and phrasing](MUSICAL_STRUCTURE.md) | Evidence-supported harmonic boundaries and phrase lengths |
| [Vocal semantics](VOCAL_SEMANTIC_ENRICHMENT.md) | Evidence, provenance and vocal interpretation |
| [Vocal choreography](VOCAL_CHOREOGRAPHY.md) | Mapping supported vocal evidence to gestures |
| [Recurrence and motifs](RECURRENCE_MOTIF_SIDECAR.md) | Optional recurrence sidecar and limitations |
| [Collision allocation](SEMANTIC_COLLISION_ALLOCATION.md) | Opt-in collision-aware semantic allocation |
| [Choreography quality](CHOREOGRAPHY_QUALITY.md) | Read-only quality accounting |
| [Perceptual validation](PERCEPTUAL_VALIDATION.md) | Realization checks and limits of software evidence |

## Measurement and qualification

These contracts define how to collect and evaluate evidence. Their presence is
not a successful benchmark. The owner-approved external-input exception applies
to **2.2.5 / 20205**, **2.3.0 / 20300** and **2.3.1 / 20301**; it does not
weaken the separate strict qualification
thresholds or establish comparative quality, speed or physical behavior.

| Contract | Scope |
| --- | --- |
| [Benchmark contract](ANALYSIS_BENCHMARK_CONTRACT.md) | Pair identity, timing and quality requirements |
| [Locked benchmark runner](LOCKED_BENCHMARK_RUNNER.md) | Controlled execution of a licensed corpus |
| [Differential analysis](DIFFERENTIAL_ANALYSIS.md) | Baseline/candidate comparisons |
| [Performance-quality gate](PERFORMANCE_QUALITY_GATE.md) | Strict qualification and acceptance thresholds |
| [Report states](PERFORMANCE_QUALITY_GATE_REPORT_STATES.md) | Meaning of pass, failure and missing evidence |
| [Release-quality setup](RELEASE_QUALITY_SETUP.md) | Protected authority and optional strict inputs |
| [Physical attestation](PHYSICAL_VALIDATION_ATTESTATION.md) | Optional phone/Tesla observations |
| [Timing probes](PERFORMANCE_TIMING_PROBES.md) | Bounded timing observations, not speed claims |
| [Native inference profiling](NATIVE_INFERENCE_PROFILING.md) | Native-call timing and unchanged-output checks |
| [Inference execution placement](EXECUTION_PLACEMENT.md) | Device, hybrid and remote research options; untrusted evidence lint, not admission |
| [Native execution benchmark](NATIVE_EXECUTION_BENCHMARK.md) | Repeated full-passage execution comparisons with exact-output checks |
| [Native GAME and Deux execution](NATIVE_GAME_EXECUTION.md) | 2.3.2 candidate execution, fallback boundaries and limited host evidence |
| [GAME backend experiment](../tools/game_benchmark/README.md) | Development-only stage comparisons before a native transcription rollout |
| [Resource diagnostics](RESOURCE_DIAGNOSTICS.md) | Runtime resource reporting |
| [Process resource collection](PROCESS_RESOURCE_COLLECTION.md) | Explicit process-resource capture |
| [Synchronization metrics](SYNC_METRIC_PROJECTION.md) | Derived timing metrics and unassessed cases |

Historical QA directories remain at their original paths because current tests
reuse selected adapters, fixtures and source-bound records. Use
[VALIDATION.md](../VALIDATION.md) before treating any of them as current evidence.
Retired transfer/checklist documents remain recoverable through Git history,
not duplicated as another current documentation tree.
