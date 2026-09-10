# Differential analysis

`tools/differential_analysis.py` produces the Phase 17 review artifact that explains the behavioral difference between a baseline and candidate. It is deliberately separate from `performance_quality_gate.py`: the gate decides whether a release may proceed; the differential report makes every material changed event reviewable.

Run it with committed, privacy-safe report artifacts:

```sh
python3 tools/differential_analysis.py \
  --baseline artifacts/baseline-differential.json \
  --candidate artifacts/candidate-differential.json \
  --output artifacts/differential-report.json
```

The command exits `0` only for a comparable report. It exits `2` and writes an `INVALID_INPUT` or `INCOMPARABLE` JSON result for non-finite numbers, unknown fields, invalid references, duplicate identifiers, or mismatched immutable identities. It never emits a partial comparison.

## Input contract

Both inputs must be strict JSON objects with this exact top-level shape:

```json
{
  "schema_version": 1,
  "identity": {
    "audio_sha256": "<64 lower-case hex characters>",
    "analysis_configuration_sha256": "<64 lower-case hex characters>",
    "model_manifest_sha256": "<64 lower-case hex characters>",
    "vehicle_profile_sha256": "<64 lower-case hex characters>",
    "fseq_configuration_sha256": "<64 lower-case hex characters>",
    "implementation_id": "opaque-candidate-id"
  },
  "semantic_events": [],
  "choreography_commands": [],
  "collision_resolutions": [],
  "fseq_timing": []
}
```

The first five identity hashes must match exactly. `implementation_id` is intentionally allowed to differ. This makes a pipeline change reviewable while preventing an invalid claim that two different audio inputs, model sets, configurations, or vehicle/FSEQ profiles are equivalent.

Identifiers are opaque tokens (`A–Z`, `a–z`, digits, `.`, `_`, `:`, `-`) and must be unique within their collection. Do not use track titles, lyrics, transcript text, paths, URLs, raw audio, FSEQ bytes, user names, or credentials. The validator rejects every unrecognized field so a new sensitive field cannot silently enter the artifacts.

### Semantic events

Each event is:

```json
{
  "id": "evt-vocal-0001",
  "timestamp_seconds": 12.34,
  "duration_seconds": 0.18,
  "event_type": "vocal.syllable",
  "source": "lead_vocal",
  "confidence": 0.93,
  "salience": 0.91,
  "tier": "primary",
  "section_id": "section-03",
  "recurrence_id": "motif-a",
  "structural_importance": 0.72
}
```

The required fields are everything through `tier`; the last three are optional. `confidence`, `salience`, and `structural_importance` are finite values in `[0, 1]`; `tier` is one of `micro`, `secondary`, `primary`, `phrase`, `structural`, or `climax`. Persistent event IDs are mandatory: do not derive them from a volatile array index. `section_boundary` and `*.section_boundary` event types receive a dedicated boundary diff.

### Choreography, collisions, and FSEQ timing

Each choreography command has a stable logical command ID and references a semantic event:

```json
{
  "id": "cmd-vocal-0001",
  "event_id": "evt-vocal-0001",
  "timestamp_seconds": 12.32,
  "duration_seconds": 0.20,
  "output_id": "left-signature",
  "command_type": "pulse",
  "value": 1.0,
  "perceptual_timestamp_seconds": 12.34,
  "salience": 0.91
}
```

`value`, `perceptual_timestamp_seconds`, and command-level `salience` are optional. When no command salience is supplied, the referenced semantic event salience is used for high-salience review.

Every collision resolution has `id`, `event_id`, `status`, and `salience`; optional `preferred_output_id`, `realized_output_id`, and `reason` remain opaque tokens. Status is one of `resolved`, `rerouted`, `suppressed`, or `unresolved`. The latter two count as collision loss.

Every FSEQ timing record has `id`, `command_id`, `intended_perceptual_timestamp_seconds`, `command_timestamp_seconds`, `realized_perceptual_timestamp_seconds`, and a non-negative `frame_index`. It references a choreography command. This allows the report to distinguish command-time movement from the predicted perceptual response rather than pretending all actuators behave like LEDs.

## Output and release review

For equivalent artifacts, the deterministic output includes:

- semantic events added, removed, changed, timestamp-shifted, and confidence-changed;
- section-boundary differences and salience-rank changes;
- choreography commands added, removed, changed, timestamp-shifted, and actuator assignment changes;
- collision-resolution changes plus total/high-salience loss rates;
- FSEQ rows added, removed, changed, and timing deltas with command versus predicted-perceptual error deltas;
- `release_review_items`, which always flags a removed or shifted high-salience event. It also flags high-salience command loss, semantic reclassification/demotion, unresolved high-salience collisions, and any increase in high-salience collision loss.

The default high-salience threshold is `0.70`; set `--high-salience-threshold` only in a reviewed policy/configuration change. The tool does not decide quality equivalence. Feed its review items and FSEQ timing distributions into the quality gate and structured human A/B review.

Run its unit tests with:

```sh
python3 tests/differential-analysis.test.py
```
