#!/usr/bin/env python3
"""Fail-closed paired performance and musical-quality release gate.

The gate separates unconfigured template/legacy comparisons from a genuine
release profile.  A release profile binds an immutable corpus, the complete
metric contract, paired evidence, and blinded human perceptual review for a
major pipeline change.  It never fills absent measurements with defaults.
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import json
import math
import re
import statistics
import sys
from pathlib import Path


SCHEMA_VERSION = 3
# A release contract is deliberately versioned when its acceptance semantics
# change.  ``v2`` closes the old policy-floor, corpus, and applicability
# loopholes rather than silently reinterpreting a v1 policy collected earlier.
RELEASE_METRIC_CONTRACT_VERSION = "lightforge-release-metrics-v2"
RELEASE_CORPUS_CONTRACT_VERSION = "lightforge-release-corpus-v1"
RELEASE_MINIMUM_PAIRS_PER_TRACK = 5
RELEASE_MINIMUM_BOOTSTRAP_CONFIDENCE = 0.99
RELEASE_MINIMUM_BOOTSTRAP_RESAMPLES = 20_000
RELEASE_RUNTIME_METRIC = "performance.total_wall_clock_seconds"
RELEASE_RUNTIME_TARGET_PERCENT = 75.0
RELEASE_MINIMUM_CORPUS_TRACKS = 16
HUMAN_REVIEW_SCHEMA_VERSION = 1
REVIEW_ATTESTATION_SCHEMA_VERSION = 1
REVIEW_ATTESTATION_PROTOCOL = "external-review-attestation-v1"
HUMAN_REVIEW_ATTRIBUTES = (
    "musical_synchronization",
    "vocal_synchronization",
    "bass_synchronization",
    "beat_precision",
    "visual_coherence",
    "phrase_coherence",
    "contrast",
    "anticipation",
    "payoff",
    "repetitiveness",
    "climax_quality",
    "overall_musicality",
)
_HUMAN_RATINGS = {
    "candidate_preferred",
    "baseline_preferred",
    "equivalent",
    "inconclusive",
}
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ACCELERATOR_NOT_APPLICABLE_METRICS = frozenset(
    {
        "resources.peak_accelerator_memory_bytes",
        "resources.accelerator_utilization_percent",
    }
)
RELEASE_GOLDEN_ARTIFACT_REQUIREMENTS = (
    "semantic_timeline_sha256",
    "rhythm_map_sha256",
    "vocal_map_sha256",
    "bass_map_sha256",
    "drum_map_sha256",
    "section_map_sha256",
    "salience_map_sha256",
    "choreography_plan_sha256",
    "fseq_characteristics_sha256",
    "validation_report_sha256",
)
# Every tag listed below must occur somewhere in the locked corpus.  Combined
# requirements are intentionally expanded into their concrete coverage tags so
# a one-track or one-genre manifest cannot self-attest diversity.
RELEASE_COVERAGE_REQUIREMENTS = {
    "strong-lead-vocals": ("lead-vocal",),
    "layered-backing-vocals": ("backing-vocal", "harmony"),
    "rap-and-spoken-vocals": ("rap", "spoken-vocal"),
    "vocal-chops": ("vocal-chops",),
    "instrumental-and-acoustic": ("instrumental", "acoustic"),
    "rock-metal-punk": ("rock", "metal", "punk"),
    "pop-edm-trance-house-techno": ("pop", "edm", "trance", "house", "techno"),
    "hip-hop-heavy-sub-bass": ("hip-hop", "heavy-sub-bass"),
    "country-and-cinematic-orchestral": ("country", "cinematic", "orchestral"),
    "dense-and-sparse-mixes": ("dense-mix", "sparse-mix"),
    "complex-percussion-and-fills": ("complex-percussion", "fills"),
    "tempo-change-half-double-time-and-irregular-meter": (
        "tempo-change",
        "half-time",
        "double-time",
        "irregular-meter",
    ),
    "repeated-and-structurally-irregular-sections": (
        "repeated-chorus",
        "repeated-motif",
        "structurally-irregular",
    ),
    "long-short-and-difficult-source-material": (
        "long-track",
        "short-track",
        "noisy-source",
        "compressed-master",
        "dynamic-master",
    ),
}
COMPARABILITY_PATHS = (
    "provenance.workload.corpus_id",
    "provenance.workload.corpus_manifest_sha256",
    "provenance.workload.audio.content_sha256",
    "provenance.workload.analysis_configuration",
    "provenance.implementation.preprocessing_version",
    "provenance.implementation.model_versions",
    "provenance.environment.hardware_fingerprint",
    "provenance.environment.runtime_backend",
    "provenance.environment.runtime_version",
    "provenance.environment.accelerator",
    "provenance.environment.random_seed",
    "provenance.environment.thermal_profile",
    "condition.cache_mode",
)


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _metric(
    direction,
    *,
    critical=True,
    tolerance=0.0,
    hard=None,
    bounds=None,
    allow_not_applicable=False,
    minimum_applicable_tracks=0,
):
    rule = {
        "required": True,
        "critical": critical,
        "direction": direction,
        "equivalence_tolerance": tolerance,
        "pair_hard_regression": tolerance if hard is None else hard,
    }
    if bounds is not None:
        rule["bounds"] = list(bounds)
    if allow_not_applicable:
        rule["allow_not_applicable"] = True
        rule["minimum_applicable_tracks"] = minimum_applicable_tracks
    return rule


def _release_metric_rules():
    """Fixed metric/tolerance contract, included in release-policy digests."""
    rules = {}

    def add(name, direction, **kwargs):
        if name in rules:
            raise AssertionError(f"duplicate release metric {name}")
        rules[name] = _metric(direction, **kwargs)

    # End-to-end and per-stage performance evidence.
    for name in (
        "performance.total_wall_clock_seconds",
        "performance.audio_decode_seconds",
        "performance.resample_normalize_seconds",
        "performance.feature_generation_seconds",
        "performance.source_separation_seconds",
        "performance.rhythm_analysis_seconds",
        "performance.tempo_inference_seconds",
        "performance.beat_tracking_seconds",
        "performance.downbeat_tracking_seconds",
        "performance.vocal_analysis_seconds",
        "performance.drum_analysis_seconds",
        "performance.bass_analysis_seconds",
        "performance.structural_analysis_seconds",
        "performance.choreography_planning_seconds",
        "performance.collision_resolution_seconds",
        "performance.vehicle_realization_seconds",
        "performance.fseq_generation_seconds",
        "performance.validation_seconds",
        "performance.model_initialization_seconds",
        "performance.model_inference_seconds",
        "performance.preprocessing_seconds",
        "performance.postprocessing_seconds",
        "performance.synchronization_waiting_seconds",
        "performance.cache_miss_cost_seconds",
        "performance.checkpoint_resume_overhead_seconds",
    ):
        add(name, "lower", critical=False, tolerance=0.0, bounds=(0, 1_000_000_000))
    add("performance.cache_hit_rate", "higher", critical=False, tolerance=0.0, bounds=(0, 1))

    # Resource observations are mandatory evidence. Only memory is a hard
    # release guard; utilisation/thermal numbers are intentionally observed,
    # not treated as automatically better in one direction.
    add("resources.peak_ram_bytes", "lower", critical=True, tolerance=0.0, bounds=(0, 2**63 - 1))
    add(
        "resources.peak_accelerator_memory_bytes",
        "lower",
        critical=True,
        tolerance=0.0,
        bounds=(0, 2**63 - 1),
        allow_not_applicable=True,
        minimum_applicable_tracks=0,
    )
    for name in (
        "resources.cpu_time_seconds",
        "resources.cpu_utilization_percent",
        "resources.accelerator_utilization_percent",
        "resources.allocation_bytes",
        "resources.total_disk_io_bytes",
        "resources.temporary_storage_bytes",
        "resources.energy_joules",
        "resources.thermal_delta_celsius",
    ):
        bounds = (0, 100) if name.endswith("_percent") else (0, 2**63 - 1)
        add(
            name,
            "neutral",
            critical=False,
            tolerance=0.0,
            bounds=bounds,
            # The only hardware exception is an explicitly unavailable
            # accelerator, pinned to the release runtime profile below. Energy
            # and thermal telemetry must be numeric when a release profile
            # claims to measure them; they cannot disappear behind a free-form
            # not-applicable assertion.
            allow_not_applicable=name == "resources.accelerator_utilization_percent",
            minimum_applicable_tracks=0,
        )

    # Rhythm: timing, tempo, meter, bar, and phrase reconstruction.
    for name in (
        "quality.tempo_accuracy",
        "quality.beat_f1",
        "quality.downbeat_f1",
        "quality.meter_accuracy",
        "quality.bar_boundary_accuracy",
        "quality.phrase_boundary_accuracy",
    ):
        add(name, "higher", tolerance=0.002, hard=0.002, bounds=(0, 1))
    for name in ("quality.beat_position_error_ms", "quality.downbeat_position_error_ms"):
        add(name, "lower", tolerance=1.0, hard=1.0, bounds=(0, 10_000))

    # Acoustic vocal understanding. Some tracks legitimately lack a particular
    # annotated voice role, but the locked corpus must make every metric
    # applicable on at least one track rather than fabricate a score.
    for name in (
        "quality.vocal_alignment_f1",
        "quality.vocal_region_precision",
        "quality.vocal_region_recall",
        "quality.vocal_region_f1",
        "quality.singing_speech_classification_accuracy",
        "quality.vocal_note_onset_accuracy",
        "quality.vocal_note_offset_accuracy",
        "quality.vocal_pitch_accuracy",
        "quality.vocal_phrase_boundary_accuracy",
        "quality.vocal_stressed_syllable_accuracy",
        "quality.vocal_lead_backing_role_accuracy",
    ):
        add(name, "higher", tolerance=0.002, hard=0.002, bounds=(0, 1), allow_not_applicable=True, minimum_applicable_tracks=1)
    add(
        "quality.vocal_syllable_articulation_alignment_error_ms",
        "lower",
        tolerance=1.0,
        hard=1.0,
        bounds=(0, 10_000),
        allow_not_applicable=True,
        minimum_applicable_tracks=1,
    )

    # Dedicated percussion classes and timing.
    for drum_class in (
        "kick",
        "snare",
        "clap",
        "hat",
        "crash",
        "tom_fill",
        "other_percussion",
    ):
        for statistic in ("precision", "recall", "f1"):
            add(
                f"quality.drum_{drum_class}_{statistic}",
                "higher",
                tolerance=0.002,
                hard=0.002,
                bounds=(0, 1),
                allow_not_applicable=True,
                minimum_applicable_tracks=1,
            )
    add(
        "quality.drum_onset_timing_error_ms",
        "lower",
        tolerance=1.0,
        hard=1.0,
        bounds=(0, 10_000),
        allow_not_applicable=True,
        minimum_applicable_tracks=1,
    )

    # Bass is explicitly distinct from kick.
    for name in (
        "quality.bass_event_f1",
        "quality.bass_note_onset_precision",
        "quality.bass_note_onset_recall",
        "quality.bass_note_onset_f1",
        "quality.bass_pitch_accuracy",
        "quality.bass_duration_accuracy",
        "quality.sub_bass_event_recall",
        "quality.kick_bass_coincidence_accuracy",
    ):
        add(name, "higher", tolerance=0.002, hard=0.002, bounds=(0, 1), allow_not_applicable=True, minimum_applicable_tracks=1)
    add(
        "quality.bass_timing_error_ms",
        "lower",
        tolerance=1.0,
        hard=1.0,
        bounds=(0, 10_000),
        allow_not_applicable=True,
        minimum_applicable_tracks=1,
    )

    # Structure and recurrence.
    for name in (
        "quality.structural_event_recall",
        "quality.section_boundary_accuracy",
        "quality.section_similarity_consistency",
        "quality.recurrence_precision",
        "quality.recurrence_recall",
        "quality.motif_identity_consistency",
        "quality.repeated_section_matching_accuracy",
        "quality.semantic_event_classification_accuracy",
    ):
        add(name, "higher", tolerance=0.002, hard=0.002, bounds=(0, 1))

    # Choreography hierarchy, density, feasibility, and non-monotony.
    for name in (
        "quality.high_salience_coverage",
        "quality.important_event_recall",
        "quality.structural_event_coverage",
        "quality.vocal_accent_coverage",
        "quality.bass_accent_coverage",
        "quality.percussion_accent_coverage",
        "quality.downbeat_emphasis_consistency",
        "quality.phrase_level_coherence",
        "quality.repeated_motif_consistency",
        "quality.repeated_motif_evolution",
        "quality.density_balance",
        "quality.negative_space_usage",
        "quality.dynamic_contrast",
        "quality.climax_differentiation",
        "quality.section_differentiation",
        "quality.symmetry_consistency",
        "quality.actuator_feasibility",
    ):
        add(name, "higher", tolerance=0.002, hard=0.002, bounds=(0, 1))
    for name in (
        "quality.visual_repetition_monotony",
        "quality.choreography_redundancy_score",
        "quality.collision_loss",
        "quality.high_salience_collision_loss",
        "quality.actuator_overuse",
        "quality.minimum_duration_violation_rate",
        "quality.conflicting_command_rate",
    ):
        add(name, "lower", tolerance=0.0, hard=0.0, bounds=(0, 1))
    add("quality.choreography_entropy", "neutral", critical=False, tolerance=0.0, bounds=(0, 1))

    # Command and predicted perceptual timing are deliberately reported
    # separately for every relevant musical/output class.
    classes = (
        "vocals",
        "bass",
        "kick",
        "snare",
        "percussion",
        "beat",
        "downbeat",
        "section_transition",
        "climax",
        "mechanical_actuator",
        "lighting_output",
    )
    statistics_names = ("median_ms", "p90_ms", "p95_ms", "p99_ms", "max_ms")
    for timing in ("command", "perceptual"):
        for event_class in classes:
            for statistic in statistics_names:
                add(
                    f"quality.sync.{timing}.{event_class}.{statistic}",
                    "lower",
                    tolerance=1.0,
                    hard=1.0,
                    bounds=(0, 10_000),
                    allow_not_applicable=event_class in {"vocals", "bass", "kick", "snare", "percussion"},
                    minimum_applicable_tracks=1 if event_class in {"vocals", "bass", "kick", "snare", "percussion"} else 0,
                )
    # Backward-readable headline stays in the release contract as a direct
    # perceptual aggregate, in addition to the per-class percentiles.
    add("quality.perceptual_sync_p95_ms", "lower", tolerance=1.0, hard=1.0, bounds=(0, 10_000))
    return rules


RELEASE_METRIC_RULES = _release_metric_rules()


def _release_contract_payload():
    return {
        "version": RELEASE_METRIC_CONTRACT_VERSION,
        "rules": RELEASE_METRIC_RULES,
        "human_review_attributes": HUMAN_REVIEW_ATTRIBUTES,
    }


def release_metric_contract():
    """Return the immutable release contract plus its audit digest."""
    payload = _release_contract_payload()
    result = {
        **payload,
        "sha256": hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest(),
    }
    # A caller may safely annotate a returned report without mutating the
    # module-level immutable policy rules used by later comparisons.
    return json.loads(canonical_json(result))


def _is_release_profile(policy):
    profile = policy.get("release_profile") if isinstance(policy, dict) else None
    return isinstance(profile, dict) and profile.get("mode") == "release"


def policy_sha256(policy):
    """Hash committed policy plus immutable release metric rules when enabled."""
    payload = {"policy": policy}
    if _is_release_profile(policy):
        payload["release_metric_contract"] = _release_contract_payload()
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def percentile(values, q):
    values = sorted(float(value) for value in values)
    if not values:
        return None
    position = (len(values) - 1) * q
    lower, upper = math.floor(position), math.ceil(position)
    return values[lower] if lower == upper else values[lower] + (values[upper] - values[lower]) * (position - lower)


def summary(values):
    values = [float(value) for value in values]
    if not values:
        raise ValueError("cannot summarize an empty series")
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p90": percentile(values, 0.90),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "min": min(values),
        "max": max(values),
    }


def _get(value, path):
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _is_finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _require_string(value, path):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path} must be a non-empty string")
    return value


def _require_sha256(value, path, *, reject_placeholder=False):
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{path} must be a lower-case sha256")
    # Repeated-character values are useful in redacted templates but cannot be
    # accepted as immutable release evidence.  A real SHA-256 can theoretically
    # have this shape, but rejecting it is the safe, transparent choice here.
    if reject_placeholder and len(set(value)) == 1:
        raise ValueError(f"{path} must not be a synthetic placeholder sha256")
    return value


def _accelerator_fingerprint(accelerator):
    if not isinstance(accelerator, dict):
        return None
    try:
        return hashlib.sha256(canonical_json(accelerator).encode("utf-8")).hexdigest()
    except (TypeError, ValueError):
        return None


def _validate_locked_runtime_profile(value):
    if not isinstance(value, dict):
        raise ValueError("release profile requires locked_runtime_profile")
    expected = {
        "runtime_profile_id",
        "hardware_fingerprint",
        "runtime_backend",
        "runtime_version",
        "thermal_profile",
        "random_seed",
        "accelerator",
    }
    if set(value) != expected:
        raise ValueError("locked_runtime_profile must contain exactly the pinned runtime identity fields")
    runtime_profile_id = _require_string(
        value.get("runtime_profile_id"),
        "policy.release_profile.locked_runtime_profile.runtime_profile_id",
    )
    hardware_fingerprint = _require_string(
        value.get("hardware_fingerprint"),
        "policy.release_profile.locked_runtime_profile.hardware_fingerprint",
    )
    runtime_backend = _require_string(
        value.get("runtime_backend"),
        "policy.release_profile.locked_runtime_profile.runtime_backend",
    )
    runtime_version = _require_string(
        value.get("runtime_version"),
        "policy.release_profile.locked_runtime_profile.runtime_version",
    )
    thermal_profile = _require_string(
        value.get("thermal_profile"),
        "policy.release_profile.locked_runtime_profile.thermal_profile",
    )
    random_seed = value.get("random_seed")
    if isinstance(random_seed, bool) or not isinstance(random_seed, (int, str)):
        raise ValueError("locked_runtime_profile.random_seed must be an integer or string")
    accelerator = value.get("accelerator")
    if not isinstance(accelerator, dict):
        raise ValueError("locked_runtime_profile.accelerator must be an object")
    available = accelerator.get("available")
    if not isinstance(available, bool):
        raise ValueError("locked_runtime_profile.accelerator.available must be a boolean")
    fingerprint_sha256 = _require_sha256(
        accelerator.get("fingerprint_sha256"),
        "policy.release_profile.locked_runtime_profile.accelerator.fingerprint_sha256",
    )
    if available:
        if set(accelerator) != {"available", "fingerprint_sha256"}:
            raise ValueError("available locked_runtime_profile.accelerator has unsupported fields")
        normalized_accelerator = {
            "available": True,
            "fingerprint_sha256": fingerprint_sha256,
        }
    else:
        if set(accelerator) != {"available", "fingerprint_sha256", "reason", "evidence_id"}:
            raise ValueError("unavailable locked_runtime_profile.accelerator requires reason and evidence_id only")
        reason = accelerator.get("reason")
        evidence_id = accelerator.get("evidence_id")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("locked_runtime_profile.accelerator.reason must be a non-empty string")
        if not isinstance(evidence_id, str) or not _OPAQUE_ID.fullmatch(evidence_id):
            raise ValueError("locked_runtime_profile.accelerator.evidence_id must be an opaque identifier")
        normalized_accelerator = {
            "available": False,
            "fingerprint_sha256": fingerprint_sha256,
            "reason": reason.strip(),
            "evidence_id": evidence_id,
        }
    return {
        "runtime_profile_id": runtime_profile_id,
        "hardware_fingerprint": hardware_fingerprint,
        "runtime_backend": runtime_backend,
        "runtime_version": runtime_version,
        "thermal_profile": thermal_profile,
        "random_seed": random_seed,
        "accelerator": normalized_accelerator,
    }


def _validate_review_attestation_profile(value):
    if not isinstance(value, dict) or set(value) != {
        "protocol",
        "verifier_id",
        "verification_key_sha256",
    }:
        raise ValueError("release profile requires a pinned external review attestation verifier")
    if value.get("protocol") != REVIEW_ATTESTATION_PROTOCOL:
        raise ValueError("release profile review attestation protocol is unsupported")
    verifier_id = value.get("verifier_id")
    if not isinstance(verifier_id, str) or not _OPAQUE_ID.fullmatch(verifier_id):
        raise ValueError("release profile review attestation verifier_id must be opaque")
    return {
        "protocol": REVIEW_ATTESTATION_PROTOCOL,
        "verifier_id": verifier_id,
        "verification_key_sha256": _require_sha256(
            value.get("verification_key_sha256"),
            "policy.release_profile.human_perceptual_review.attestation.verification_key_sha256",
            reject_placeholder=True,
        ),
    }


def _validate_release_profile(value, tracks):
    if value is None:
        return {"mode": "legacy", "configured": False}
    if not isinstance(value, dict):
        raise ValueError("policy.release_profile must be an object")
    mode = value.get("mode")
    if mode not in {"legacy", "template", "release"}:
        raise ValueError("policy.release_profile.mode must be legacy, template, or release")
    if mode in {"legacy", "template"}:
        return {"mode": mode, "configured": False}
    expected_fields = {
        "mode",
        "metric_contract",
        "locked_corpus",
        "locked_runtime_profile",
        "human_perceptual_review",
    }
    if set(value) != expected_fields:
        raise ValueError("release profile must contain exactly the immutable release fields")
    if value.get("metric_contract") != RELEASE_METRIC_CONTRACT_VERSION:
        raise ValueError("release profile must pin the current immutable metric contract")
    locked = value.get("locked_corpus")
    if not isinstance(locked, dict) or set(locked) != {"corpus_id", "manifest_sha256"}:
        raise ValueError("release profile requires locked_corpus")
    corpus_id = _require_string(locked.get("corpus_id"), "policy.release_profile.locked_corpus.corpus_id")
    manifest_sha256 = _require_sha256(
        locked.get("manifest_sha256"),
        "policy.release_profile.locked_corpus.manifest_sha256",
        reject_placeholder=True,
    )
    if "__configure_locked_corpus__" in tracks:
        raise ValueError("release profile cannot use the unconfigured corpus placeholder")
    review = value.get("human_perceptual_review")
    if not isinstance(review, dict) or set(review) != {
        "required_for_every_release_candidate",
        "minimum_reviewers",
        "required_attributes",
        "attestation",
    }:
        raise ValueError("release profile requires human_perceptual_review")
    minimum_reviewers = review.get("minimum_reviewers")
    if not isinstance(minimum_reviewers, int) or isinstance(minimum_reviewers, bool) or minimum_reviewers < 3:
        raise ValueError("release profile human_perceptual_review.minimum_reviewers must be at least three")
    attributes = review.get("required_attributes")
    if not isinstance(attributes, list) or not all(isinstance(item, str) and item for item in attributes):
        raise ValueError("release profile human_perceptual_review.required_attributes must be a string array")
    if len(attributes) != len(set(attributes)) or set(attributes) != set(HUMAN_REVIEW_ATTRIBUTES):
        raise ValueError("release profile human review must declare exactly the mandatory blinded A/B attributes")
    if review.get("required_for_every_release_candidate") is not True:
        raise ValueError("release profile must require human review for every release candidate")
    return {
        "mode": "release",
        "configured": True,
        "metric_contract": RELEASE_METRIC_CONTRACT_VERSION,
        "locked_corpus": {"corpus_id": corpus_id, "manifest_sha256": manifest_sha256},
        "locked_runtime_profile": _validate_locked_runtime_profile(value.get("locked_runtime_profile")),
        "human_review": {
            "minimum_reviewers": minimum_reviewers,
            "required_attributes": tuple(attributes),
            "attestation": _validate_review_attestation_profile(review.get("attestation")),
        },
    }


def _flatten_metrics(prefix, value, output, unavailable):
    if isinstance(value, dict) and value.get("status") == "not_applicable":
        if not prefix:
            raise ValueError("metrics root cannot be not_applicable")
        allowed = {"status", "reason", "evidence_id"}
        if set(value) - allowed:
            raise ValueError(f"{prefix} not_applicable evidence has unsupported fields")
        reason = value.get("reason")
        evidence_id = value.get("evidence_id")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{prefix} not_applicable evidence requires a reason")
        if not isinstance(evidence_id, str) or not _OPAQUE_ID.fullmatch(evidence_id):
            raise ValueError(f"{prefix} not_applicable evidence requires an opaque evidence_id")
        unavailable[prefix] = {"reason": reason.strip(), "evidence_id": evidence_id}
        return
    if isinstance(value, dict):
        if not value:
            raise ValueError(f"{prefix or 'metrics'} must not be empty")
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError("metric keys must be non-empty strings")
            _flatten_metrics(f"{prefix}.{key}" if prefix else key, child, output, unavailable)
    elif _is_finite_number(value):
        output[prefix] = float(value)
    else:
        raise ValueError(f"{prefix or 'metric'} must be a finite numeric leaf or explicit not_applicable evidence")


def _validate_metric_rules(metrics):
    for name, rule in metrics.items():
        if not isinstance(name, str) or not name or not isinstance(rule, dict):
            raise ValueError("every policy metric requires a non-empty name and object rule")
        if rule.get("direction", "higher") not in {"higher", "lower", "neutral"}:
            raise ValueError(f"metric {name} has an invalid direction")
        tolerance = rule.get("equivalence_tolerance", 0)
        hard = rule.get("pair_hard_regression", tolerance)
        if not _is_finite_number(tolerance) or float(tolerance) < 0:
            raise ValueError(f"metric {name} has an invalid equivalence_tolerance")
        if not _is_finite_number(hard) or float(hard) < 0:
            raise ValueError(f"metric {name} has an invalid pair_hard_regression")
        bounds = rule.get("bounds")
        if bounds is not None:
            if not isinstance(bounds, list) or len(bounds) != 2 or not all(_is_finite_number(item) for item in bounds) or float(bounds[0]) > float(bounds[1]):
                raise ValueError(f"metric {name} has invalid bounds")
        if rule.get("allow_not_applicable", False):
            minimum = rule.get("minimum_applicable_tracks")
            if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 0:
                raise ValueError(f"metric {name} allows not_applicable but has an invalid corpus coverage requirement")
        elif "minimum_applicable_tracks" in rule:
            raise ValueError(f"metric {name} has inapplicable minimum_applicable_tracks")


def _validate_policy(policy):
    if not isinstance(policy, dict):
        raise ValueError("policy must be an object")
    tracks = policy.get("required_tracks")
    if not isinstance(tracks, list) or not tracks or not all(isinstance(track, str) and track for track in tracks):
        raise ValueError("policy.required_tracks must be a non-empty string array")
    if len(set(tracks)) != len(tracks):
        raise ValueError("policy.required_tracks must not contain duplicates")
    profile = _validate_release_profile(policy.get("release_profile"), set(tracks))
    if profile["mode"] == "release":
        supplied = policy.get("metrics")
        if supplied not in (None, {}):
            raise ValueError("release policy metrics are immutable and supplied by its pinned metric contract")
        metrics = RELEASE_METRIC_RULES
    else:
        metrics = policy.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            raise ValueError("policy.metrics must be a non-empty object")
    _validate_metric_rules(metrics)
    minimum_pairs = policy.get("minimum_pairs_per_track", 5)
    if not isinstance(minimum_pairs, int) or isinstance(minimum_pairs, bool) or minimum_pairs < 3:
        raise ValueError("policy.minimum_pairs_per_track must be at least three")
    bootstrap = policy.get("bootstrap", {})
    if not isinstance(bootstrap, dict):
        raise ValueError("policy.bootstrap must be an object")
    if bootstrap.get("method", "paired-percentile-v1") != "paired-percentile-v1":
        raise ValueError("policy.bootstrap.method is unsupported")
    confidence = bootstrap.get("confidence", 0.99)
    resamples = bootstrap.get("resamples", 20000)
    _require_string(bootstrap.get("seed", "lightforge-performance-quality-v3"), "policy.bootstrap.seed")
    if not _is_finite_number(confidence) or not 0.5 < float(confidence) < 1.0:
        raise ValueError("policy.bootstrap.confidence must be between 0.5 and 1")
    if not isinstance(resamples, int) or isinstance(resamples, bool) or resamples < 256:
        raise ValueError("policy.bootstrap.resamples must be at least 256")
    runtime = policy.get("runtime_target")
    if not isinstance(runtime, dict):
        raise ValueError("policy.runtime_target must be an object")
    metric = runtime.get("metric")
    if not isinstance(metric, str) or metric not in metrics:
        raise ValueError("runtime_target.metric must be a declared policy metric")
    reduction = runtime.get("target_reduction_percent", 75)
    if not _is_finite_number(reduction) or float(reduction) < 0 or float(reduction) > 100:
        raise ValueError("runtime target reduction must be within 0..100")
    if runtime.get("scope", "each_required_track") != "each_required_track":
        raise ValueError("only each_required_track runtime scope is supported")
    if profile["mode"] == "release":
        # A release policy may make evidence stricter, but it may not relax a
        # committed floor or turn the performance target into a no-op.
        if minimum_pairs < RELEASE_MINIMUM_PAIRS_PER_TRACK:
            raise ValueError(
                f"release policy.minimum_pairs_per_track must be at least {RELEASE_MINIMUM_PAIRS_PER_TRACK}"
            )
        if float(confidence) < RELEASE_MINIMUM_BOOTSTRAP_CONFIDENCE:
            raise ValueError(
                f"release policy.bootstrap.confidence must be at least {RELEASE_MINIMUM_BOOTSTRAP_CONFIDENCE}"
            )
        if resamples < RELEASE_MINIMUM_BOOTSTRAP_RESAMPLES:
            raise ValueError(
                f"release policy.bootstrap.resamples must be at least {RELEASE_MINIMUM_BOOTSTRAP_RESAMPLES}"
            )
        if metric != RELEASE_RUNTIME_METRIC:
            raise ValueError(f"release runtime_target.metric must equal {RELEASE_RUNTIME_METRIC}")
        if float(reduction) != RELEASE_RUNTIME_TARGET_PERCENT:
            raise ValueError(
                f"release runtime_target.target_reduction_percent must equal {RELEASE_RUNTIME_TARGET_PERCENT:g}"
            )
    return metrics, set(tracks), minimum_pairs, bootstrap, runtime, profile


def _validate_suite(report, expected_policy_sha):
    if not isinstance(report, dict) or report.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"report.schema_version must equal {SCHEMA_VERSION}")
    suite = report.get("suite")
    if not isinstance(suite, dict):
        raise ValueError("report.suite must be an object")
    for path in ("corpus_id", "corpus_manifest_sha256", "protocol_id", "policy_sha256"):
        _require_string(suite.get(path), f"report.suite.{path}")
    if suite["policy_sha256"] != expected_policy_sha:
        raise ValueError("report suite policy_sha256 does not match the supplied policy")
    return suite


def locked_corpus_manifest_sha256(manifest):
    """Return the canonical hash that a release policy and suite must pin."""
    return hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()


def _release_evidence_requirements():
    return {
        "metric_contract": RELEASE_METRIC_CONTRACT_VERSION,
        "minimum_paired_runs_per_track": RELEASE_MINIMUM_PAIRS_PER_TRACK,
        "bootstrap": {
            "minimum_confidence": RELEASE_MINIMUM_BOOTSTRAP_CONFIDENCE,
            "minimum_resamples": RELEASE_MINIMUM_BOOTSTRAP_RESAMPLES,
        },
        "runtime_target": {
            "metric": RELEASE_RUNTIME_METRIC,
            "target_reduction_percent": RELEASE_RUNTIME_TARGET_PERCENT,
            "scope": "each_required_track",
        },
        "human_perceptual_review": {
            "protocol": "blinded-ab-v1",
            "minimum_reviewers": 3,
            "required_attributes": list(HUMAN_REVIEW_ATTRIBUTES),
            "attestation_protocol": REVIEW_ATTESTATION_PROTOCOL,
        },
    }


def _corpus_error(reason, **details):
    return {"reason": reason, **details}


def _release_corpus_diagnostics(manifest, profile, required_tracks):
    """Validate the private, hash-pinned release corpus without exposing audio.

    A policy SHA only proves that somebody typed a manifest digest.  The gate
    still receives the locked manifest and independently checks its diversity,
    goldens, annotation evidence, and track identities before that digest can
    support a production claim.
    """
    diagnostics = {
        "required": profile["mode"] == "release",
        "status": "not_required",
        "valid": profile["mode"] != "release",
        "manifest_sha256": None,
        "corpus_id": None,
        "track_count": 0,
        "coverage": [],
        "golden_artifact_requirements": list(RELEASE_GOLDEN_ARTIFACT_REQUIREMENTS),
        "annotation_evidence_count": 0,
    }
    if profile["mode"] != "release":
        return diagnostics, [], {}
    if not isinstance(manifest, dict):
        diagnostics.update({"status": "missing", "valid": False})
        return diagnostics, [_corpus_error("release_locked_corpus_manifest_required")], {}

    blockers = []
    try:
        manifest_sha256 = locked_corpus_manifest_sha256(manifest)
    except (TypeError, ValueError):
        diagnostics.update({"status": "invalid", "valid": False})
        return diagnostics, [_corpus_error("invalid_release_locked_corpus_manifest")], {}
    diagnostics["manifest_sha256"] = manifest_sha256
    diagnostics["corpus_id"] = manifest.get("corpus_id")
    if manifest_sha256 != profile["locked_corpus"]["manifest_sha256"]:
        blockers.append(
            _corpus_error(
                "release_locked_corpus_manifest_digest_mismatch",
                expected=profile["locked_corpus"]["manifest_sha256"],
                actual=manifest_sha256,
            )
        )
    if manifest.get("schema_version") != 1:
        blockers.append(_corpus_error("release_locked_corpus_schema_mismatch"))
    if manifest.get("corpus_id") != profile["locked_corpus"]["corpus_id"]:
        blockers.append(
            _corpus_error(
                "release_locked_corpus_id_mismatch",
                expected=profile["locked_corpus"]["corpus_id"],
                actual=manifest.get("corpus_id"),
            )
        )
    if manifest.get("template") is not False or manifest.get("release_ready") is not True:
        blockers.append(_corpus_error("release_locked_corpus_not_release_ready"))
    if manifest.get("coverage_requirements") != list(RELEASE_COVERAGE_REQUIREMENTS):
        blockers.append(_corpus_error("release_locked_corpus_coverage_contract_mismatch"))
    if manifest.get("golden_artifact_requirements") != list(RELEASE_GOLDEN_ARTIFACT_REQUIREMENTS):
        blockers.append(_corpus_error("release_locked_corpus_golden_contract_mismatch"))
    if manifest.get("release_evidence_requirements") != _release_evidence_requirements():
        blockers.append(_corpus_error("release_locked_corpus_evidence_contract_mismatch"))

    tracks = manifest.get("tracks")
    if not isinstance(tracks, list):
        blockers.append(_corpus_error("release_locked_corpus_tracks_invalid"))
        diagnostics.update({"status": "invalid", "valid": False})
        return diagnostics, blockers, {}
    diagnostics["track_count"] = len(tracks)
    if len(tracks) < RELEASE_MINIMUM_CORPUS_TRACKS:
        blockers.append(
            _corpus_error(
                "release_locked_corpus_too_small",
                actual=len(tracks),
                minimum=RELEASE_MINIMUM_CORPUS_TRACKS,
            )
        )

    track_contract = {}
    audio_ids = set()
    all_tags = set()
    for index, track in enumerate(tracks):
        path = f"tracks[{index}]"
        if not isinstance(track, dict):
            blockers.append(_corpus_error("release_locked_corpus_track_invalid", track_index=index))
            continue
        allowed = {"track_id", "audio", "tags", "golden_artifacts", "metric_applicability"}
        if set(track) - allowed or not {"track_id", "audio", "tags", "golden_artifacts"}.issubset(track):
            blockers.append(_corpus_error("release_locked_corpus_track_shape_invalid", track_index=index))
            continue
        track_id = track.get("track_id")
        if not isinstance(track_id, str) or not _OPAQUE_ID.fullmatch(track_id) or track_id in track_contract:
            blockers.append(_corpus_error("release_locked_corpus_track_id_invalid", track_index=index))
            continue
        audio = track.get("audio")
        if not isinstance(audio, dict) or set(audio) != {"content_sha256", "duration_seconds"}:
            blockers.append(_corpus_error("release_locked_corpus_audio_invalid", track=track_id))
            continue
        try:
            audio_sha = _require_sha256(
                audio.get("content_sha256"),
                f"manifest.{path}.audio.content_sha256",
                reject_placeholder=True,
            )
        except ValueError:
            blockers.append(_corpus_error("release_locked_corpus_audio_hash_invalid", track=track_id))
            continue
        duration = audio.get("duration_seconds")
        if not _is_finite_number(duration) or float(duration) <= 0:
            blockers.append(_corpus_error("release_locked_corpus_audio_duration_invalid", track=track_id))
            continue
        if audio_sha in audio_ids:
            blockers.append(_corpus_error("release_locked_corpus_duplicate_audio", track=track_id))
        audio_ids.add(audio_sha)
        tags = track.get("tags")
        if not isinstance(tags, list) or not tags or not all(
            isinstance(tag, str) and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,127}", tag)
            for tag in tags
        ) or len(tags) != len(set(tags)):
            blockers.append(_corpus_error("release_locked_corpus_tags_invalid", track=track_id))
            continue
        all_tags.update(tags)
        golden = track.get("golden_artifacts")
        if not isinstance(golden, dict) or set(golden) != set(RELEASE_GOLDEN_ARTIFACT_REQUIREMENTS):
            blockers.append(_corpus_error("release_locked_corpus_golden_artifacts_invalid", track=track_id))
            continue
        golden_valid = True
        for name in RELEASE_GOLDEN_ARTIFACT_REQUIREMENTS:
            try:
                _require_sha256(
                    golden.get(name),
                    f"manifest.{path}.golden_artifacts.{name}",
                    reject_placeholder=True,
                )
            except ValueError:
                golden_valid = False
                break
        if not golden_valid:
            blockers.append(_corpus_error("release_locked_corpus_golden_hash_invalid", track=track_id))
            continue
        applicability = track.get("metric_applicability", {})
        if not isinstance(applicability, dict):
            blockers.append(_corpus_error("release_locked_corpus_applicability_invalid", track=track_id))
            continue
        normalized_applicability = {}
        for metric, evidence in applicability.items():
            if (
                metric not in RELEASE_METRIC_RULES
                or metric in _ACCELERATOR_NOT_APPLICABLE_METRICS
                or not RELEASE_METRIC_RULES[metric].get("allow_not_applicable", False)
                or not isinstance(evidence, dict)
                or set(evidence) != {"status", "reason", "evidence_id", "annotation_sha256"}
                or evidence.get("status") != "not_applicable"
                or not isinstance(evidence.get("reason"), str)
                or not evidence["reason"].strip()
                or not isinstance(evidence.get("evidence_id"), str)
                or not _OPAQUE_ID.fullmatch(evidence["evidence_id"])
            ):
                blockers.append(_corpus_error("release_locked_corpus_applicability_invalid", track=track_id, metric=metric))
                continue
            try:
                annotation_sha256 = _require_sha256(
                    evidence.get("annotation_sha256"),
                    f"manifest.{path}.metric_applicability.{metric}.annotation_sha256",
                    reject_placeholder=True,
                )
            except ValueError:
                blockers.append(_corpus_error("release_locked_corpus_annotation_hash_invalid", track=track_id, metric=metric))
                continue
            normalized_applicability[metric] = {
                "reason": evidence["reason"].strip(),
                "evidence_id": evidence["evidence_id"],
                "annotation_sha256": annotation_sha256,
            }
        diagnostics["annotation_evidence_count"] += len(normalized_applicability)
        track_contract[track_id] = {
            "audio_sha256": audio_sha,
            "metric_applicability": normalized_applicability,
            "golden_artifacts": dict(golden),
        }

    expected_track_ids = set(required_tracks)
    actual_track_ids = set(track_contract)
    if actual_track_ids != expected_track_ids:
        blockers.append(
            _corpus_error(
                "release_locked_corpus_track_set_mismatch",
                missing=sorted(expected_track_ids - actual_track_ids),
                unexpected=sorted(actual_track_ids - expected_track_ids),
            )
        )
    for requirement, required_tags in RELEASE_COVERAGE_REQUIREMENTS.items():
        missing_tags = sorted(set(required_tags) - all_tags)
        diagnostics["coverage"].append(
            {
                "requirement": requirement,
                "required_tags": list(required_tags),
                "missing_tags": missing_tags,
                "covered": not missing_tags,
            }
        )
        if missing_tags:
            blockers.append(
                _corpus_error(
                    "release_locked_corpus_coverage_missing",
                    requirement=requirement,
                    missing_tags=missing_tags,
                )
            )
    diagnostics["valid"] = not blockers
    diagnostics["status"] = "valid" if not blockers else "invalid"
    return diagnostics, blockers, track_contract


def validate_locked_corpus_manifest(manifest, policy):
    """Public release-manifest validator used by the runner and release tools."""
    _, required_tracks, _, _, _, profile = _validate_policy(policy)
    if profile["mode"] != "release":
        raise ValueError("locked release corpus validation requires a release policy")
    diagnostics, blockers, _ = _release_corpus_diagnostics(manifest, profile, required_tracks)
    if blockers:
        raise ValueError("; ".join(sorted({blocker["reason"] for blocker in blockers})))
    return diagnostics


def _index_report(report, policy_metrics, expected_policy_sha):
    suite = _validate_suite(report, expected_policy_sha)
    runs = report.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError("report.runs must be a non-empty array")
    indexed, run_ids, issues = {}, set(), []
    for index, run in enumerate(runs):
        if not isinstance(run, dict):
            raise ValueError("every run must be an object")
        track_id = _require_string(run.get("track_id"), f"runs[{index}].track_id")
        pair_id = _require_string(run.get("pair_id"), f"runs[{index}].pair_id")
        run_id = _require_string(run.get("run_id"), f"runs[{index}].run_id")
        if run_id in run_ids:
            issues.append({"run_id": run_id, "reason": "duplicate_run_id"})
        run_ids.add(run_id)
        key = (track_id, pair_id)
        if key in indexed:
            issues.append({"track": track_id, "pair_id": pair_id, "reason": "duplicate_track_pair"})
        metrics = run.get("metrics")
        if not isinstance(metrics, dict):
            raise ValueError(f"runs[{index}].metrics must be an object")
        flattened, unavailable = {}, {}
        _flatten_metrics("", metrics, flattened, unavailable)
        for name, rule in policy_metrics.items():
            if rule.get("required", True) and name not in flattened and name not in unavailable:
                issues.append({"track": track_id, "pair_id": pair_id, "metric": name, "reason": "missing_metric"})
            if name in unavailable and not rule.get("allow_not_applicable", False):
                issues.append({"track": track_id, "pair_id": pair_id, "metric": name, "reason": "not_applicable_not_permitted"})
            if name in flattened and rule.get("bounds") is not None:
                lower, upper = map(float, rule["bounds"])
                if not lower <= flattened[name] <= upper:
                    issues.append({"track": track_id, "pair_id": pair_id, "metric": name, "reason": "metric_out_of_bounds", "value": flattened[name], "bounds": [lower, upper]})
        provenance = run.get("provenance")
        condition = run.get("condition")
        if not isinstance(provenance, dict):
            raise ValueError(f"runs[{index}].provenance must be an object")
        if not isinstance(condition, dict):
            raise ValueError(f"runs[{index}].condition must be an object")
        _require_string(condition.get("cache_mode"), f"runs[{index}].condition.cache_mode")
        indexed[key] = {"run": run, "metrics": flattened, "not_applicable": unavailable}
    return suite, indexed, issues


def _stable_bootstrap(values, *, seed, confidence, resamples):
    """Run the committed number of deterministic bootstrap samples.

    Exact duplicate series are memoized within the process.  This only avoids
    recomputing identical evidence (for example a repeated gate invocation); it
    never changes the seed, sample count, confidence, or metric input.
    """
    return _stable_bootstrap_cached(
        tuple(float(value) for value in values),
        str(seed),
        float(confidence),
        int(resamples),
    )


@functools.lru_cache(maxsize=512)
def _stable_bootstrap_cached(values, seed, confidence, resamples):
    values = list(values)
    if not values:
        return None, None
    if len(values) == 1 or min(values) == max(values):
        return values[0], values[0]
    digest = hashlib.sha256((seed + "|" + canonical_json(values)).encode("utf-8")).digest()
    state = int.from_bytes(digest[:8], "big") or 1
    mask = (1 << 64) - 1
    draws = []
    for _ in range(resamples):
        total = 0.0
        for _ in values:
            state ^= state >> 12
            state ^= (state << 25) & mask
            state ^= state >> 27
            state = (state * 2685821657736338717) & mask
            total += values[state % len(values)]
        draws.append(total / len(values))
    alpha = (1.0 - confidence) / 2.0
    return percentile(draws, alpha), percentile(draws, 1.0 - alpha)


def _compare_pair_provenance(baseline, candidate):
    differences = []
    for path in COMPARABILITY_PATHS:
        before, after = _get(baseline, path), _get(candidate, path)
        if before is None or after is None or canonical_json(before) != canonical_json(after):
            differences.append({"field": path, "baseline": before, "candidate": after})
    return differences


def _classify_effect(deltas, tolerance, hard_floor, bootstrap, seed, direction):
    lower, upper = _stable_bootstrap(
        deltas,
        seed=seed,
        confidence=float(bootstrap.get("confidence", 0.99)),
        resamples=int(bootstrap.get("resamples", 20000)),
    )
    if direction == "neutral":
        return "observed", lower, upper
    if any(delta < -hard_floor for delta in deltas) or upper < -tolerance:
        classification = "regressed"
    elif lower > 0:
        classification = "improved"
    elif lower >= -tolerance and upper <= tolerance:
        classification = "statistically_equivalent"
    else:
        classification = "inconclusive"
    return classification, lower, upper


def _availability(entry, metric):
    if metric in entry["metrics"]:
        return "numeric"
    if metric in entry["not_applicable"]:
        return "not_applicable"
    return "missing"


def _release_run_binding_blockers(indexed, side, profile, track_contract):
    """Bind each run to the release corpus, runtime profile, and annotations."""
    blockers = []
    runtime_profile = profile["locked_runtime_profile"]
    for (track_id, pair_id), entry in sorted(indexed.items()):
        run = entry["run"]
        provenance = run.get("provenance")
        workload = provenance.get("workload") if isinstance(provenance, dict) else None
        environment = provenance.get("environment") if isinstance(provenance, dict) else None
        track = track_contract.get(track_id)
        if track is None:
            blockers.append(
                {
                    "reason": "release_policy_run_track_unbound",
                    "side": side,
                    "track": track_id,
                    "pair_id": pair_id,
                }
            )
            continue
        if not isinstance(workload, dict) or (
            workload.get("corpus_id") != profile["locked_corpus"]["corpus_id"]
            or workload.get("corpus_manifest_sha256") != profile["locked_corpus"]["manifest_sha256"]
        ):
            blockers.append(
                {
                    "reason": "release_policy_run_corpus_mismatch",
                    "side": side,
                    "track": track_id,
                    "pair_id": pair_id,
                }
            )
        audio = workload.get("audio") if isinstance(workload, dict) else None
        if not isinstance(audio, dict) or audio.get("content_sha256") != track["audio_sha256"]:
            blockers.append(
                {
                    "reason": "release_policy_run_audio_mismatch",
                    "side": side,
                    "track": track_id,
                    "pair_id": pair_id,
                }
            )
        observed_runtime = {
            "hardware_fingerprint": environment.get("hardware_fingerprint") if isinstance(environment, dict) else None,
            "runtime_backend": environment.get("runtime_backend") if isinstance(environment, dict) else None,
            "runtime_version": environment.get("runtime_version") if isinstance(environment, dict) else None,
            "thermal_profile": environment.get("thermal_profile") if isinstance(environment, dict) else None,
            "random_seed": environment.get("random_seed") if isinstance(environment, dict) else None,
        }
        expected_runtime = {
            key: runtime_profile[key]
            for key in (
                "hardware_fingerprint",
                "runtime_backend",
                "runtime_version",
                "thermal_profile",
                "random_seed",
            )
        }
        observed_accelerator = environment.get("accelerator") if isinstance(environment, dict) else None
        if (
            observed_runtime != expected_runtime
            or _accelerator_fingerprint(observed_accelerator)
            != runtime_profile["accelerator"]["fingerprint_sha256"]
        ):
            blockers.append(
                {
                    "reason": "release_locked_runtime_profile_mismatch",
                    "side": side,
                    "track": track_id,
                    "pair_id": pair_id,
                }
            )
        for metric, evidence in entry["not_applicable"].items():
            if metric in _ACCELERATOR_NOT_APPLICABLE_METRICS:
                expected = runtime_profile["accelerator"]
                if expected["available"] or evidence != {
                    "reason": expected.get("reason"),
                    "evidence_id": expected.get("evidence_id"),
                }:
                    blockers.append(
                        {
                            "reason": "release_accelerator_not_applicable_unbound",
                            "side": side,
                            "track": track_id,
                            "pair_id": pair_id,
                            "metric": metric,
                        }
                    )
                continue
            expected = track["metric_applicability"].get(metric)
            if expected is None or evidence != {
                "reason": expected["reason"],
                "evidence_id": expected["evidence_id"],
            }:
                blockers.append(
                    {
                        "reason": "release_metric_not_applicable_unbound",
                        "side": side,
                        "track": track_id,
                        "pair_id": pair_id,
                        "metric": metric,
                    }
                )
    return blockers


def _review_evidence(candidate, profile, expected_policy_sha):
    """Validate only structured blinded A/B evidence; never infer a verdict."""
    if profile["mode"] != "release":
        return {"required": False, "status": "not_required"}, []
    blockers = []
    change = candidate.get("change")
    if not isinstance(change, dict):
        return {"required": True, "status": "missing_change_classification"}, [{"reason": "missing_change_classification"}]
    if set(change) != {"classification", "change_id"}:
        return {"required": True, "status": "invalid_change_classification"}, [{"reason": "invalid_change_classification"}]
    classification = change.get("classification")
    change_id = change.get("change_id")
    if classification not in {"minor", "major"} or not isinstance(change_id, str) or not _OPAQUE_ID.fullmatch(change_id):
        return {"required": True, "status": "invalid_change_classification"}, [{"reason": "invalid_change_classification"}]
    # A release candidate cannot self-attest a ``minor`` change to bypass
    # perceptual review.  Classification is retained for audit context only.
    required = True
    review = candidate.get("human_perceptual_review")
    if not isinstance(review, dict):
        return {"required": required, "change_classification": classification, "status": "missing"}, [{"reason": "missing_human_perceptual_review"}]
    if set(review) != {"schema_version", "protocol", "status", "review_id", "reviewers", "attestation"}:
        reasons = [{"reason": "invalid_human_perceptual_review"}]
        if "attestation" not in review:
            reasons.append({"reason": "missing_or_invalid_external_review_attestation"})
        return {"required": required, "change_classification": classification, "status": "invalid", "externally_attested": False}, reasons
    summary_result = {
        "required": required,
        "change_classification": classification,
        "schema_version": review.get("schema_version"),
        "status": review.get("status"),
        "protocol": review.get("protocol"),
        "externally_attested": False,
    }
    if review.get("schema_version") != HUMAN_REVIEW_SCHEMA_VERSION or review.get("protocol") != "blinded-ab-v1":
        blockers.append({"reason": "invalid_human_perceptual_review"})
    status = review.get("status")
    if status not in {"pass", "inconclusive", "fail"}:
        blockers.append({"reason": "invalid_human_perceptual_review_status"})
    elif status != "pass":
        blockers.append({"reason": f"human_perceptual_review_{status}"})
    review_id = review.get("review_id")
    if not isinstance(review_id, str) or not _OPAQUE_ID.fullmatch(review_id):
        blockers.append({"reason": "invalid_human_perceptual_review"})
    reviewers = review.get("reviewers")
    if not isinstance(reviewers, list):
        blockers.append({"reason": "invalid_human_perceptual_review"})
        reviewers = []
    required_attributes = profile["human_review"]["required_attributes"]
    votes = {attribute: {rating: 0 for rating in sorted(_HUMAN_RATINGS)} for attribute in required_attributes}
    seen = set()
    blinded = True
    complete = True
    for reviewer in reviewers:
        if not isinstance(reviewer, dict):
            complete = False
            continue
        if set(reviewer) != {"reviewer_id", "blinded", "ratings"}:
            complete = False
        reviewer_id = reviewer.get("reviewer_id")
        if not isinstance(reviewer_id, str) or not _OPAQUE_ID.fullmatch(reviewer_id) or reviewer_id in seen:
            complete = False
        seen.add(reviewer_id)
        if reviewer.get("blinded") is not True:
            blinded = False
        ratings = reviewer.get("ratings")
        if not isinstance(ratings, dict):
            complete = False
            continue
        if set(ratings) != set(required_attributes):
            complete = False
        for attribute in required_attributes:
            rating = ratings.get(attribute)
            if rating not in _HUMAN_RATINGS:
                complete = False
                continue
            votes[attribute][rating] += 1
    if len(reviewers) < profile["human_review"]["minimum_reviewers"]:
        blockers.append({"reason": "insufficient_human_perceptual_reviewers", "actual": len(reviewers), "minimum": profile["human_review"]["minimum_reviewers"]})
    if not blinded:
        blockers.append({"reason": "unblinded_human_perceptual_review"})
    if not complete:
        blockers.append({"reason": "incomplete_human_perceptual_review"})
    # Strict per-rating acceptance prevents a split or minority baseline vote,
    # or an inconclusive reviewer, from being erased by a top-level self
    # attested ``pass``.  Equivalent is a valid decisive no-regression rating.
    baseline_preferred = [
        attribute
        for attribute, counts in votes.items()
        if counts["baseline_preferred"] > 0
    ]
    if baseline_preferred:
        blockers.append({"reason": "human_perceptual_review_baseline_preferred", "attributes": baseline_preferred})
    inconclusive = [
        attribute
        for attribute, counts in votes.items()
        if counts["inconclusive"] > 0
    ]
    if inconclusive:
        blockers.append({"reason": "human_perceptual_review_inconclusive_rating", "attributes": inconclusive})

    # ``blinded: true`` is a reviewer claim, not an independently verifiable
    # property.  Production status therefore additionally requires a receipt
    # from the verifier pinned in policy.  The receipt binds this exact review,
    # candidate source identity, corpus, and policy rather than just a mutable
    # boolean in the candidate report.
    identity = candidate.get("candidate_identity")
    identity_valid = (
        isinstance(identity, dict)
        and set(identity) == {"source_sha256", "pipeline_version"}
        and isinstance(identity.get("pipeline_version"), str)
        and bool(identity["pipeline_version"])
    )
    if identity_valid:
        try:
            source_sha256 = _require_sha256(
                identity.get("source_sha256"),
                "candidate_identity.source_sha256",
                reject_placeholder=True,
            )
        except ValueError:
            identity_valid = False
            source_sha256 = None
    else:
        source_sha256 = None
    if not identity_valid:
        blockers.append({"reason": "invalid_candidate_identity"})
    else:
        for run in candidate.get("runs", []):
            implementation = _get(run, "provenance.implementation")
            if not isinstance(implementation, dict) or (
                implementation.get("pipeline_version") != identity["pipeline_version"]
                or implementation.get("source_sha256") != source_sha256
            ):
                blockers.append({"reason": "candidate_identity_unbound_to_run"})
                break

    attestation = review.get("attestation")
    profile_attestation = profile["human_review"]["attestation"]
    expected_attestation_fields = {
        "schema_version",
        "protocol",
        "verifier_id",
        "verification_key_sha256",
        "review_sha256",
        "candidate_identity_sha256",
        "policy_sha256",
        "corpus_manifest_sha256",
        "external_receipt_sha256",
    }
    attestation_valid = isinstance(attestation, dict) and set(attestation) == expected_attestation_fields
    if not attestation_valid:
        blockers.append({"reason": "missing_or_invalid_external_review_attestation"})
    else:
        review_payload = {key: value for key, value in review.items() if key != "attestation"}
        expected_review_sha = hashlib.sha256(canonical_json(review_payload).encode("utf-8")).hexdigest()
        expected_identity_sha = (
            hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
            if identity_valid
            else None
        )
        immutable_fields_match = (
            attestation.get("schema_version") == REVIEW_ATTESTATION_SCHEMA_VERSION
            and attestation.get("protocol") == profile_attestation["protocol"]
            and attestation.get("verifier_id") == profile_attestation["verifier_id"]
            and attestation.get("verification_key_sha256") == profile_attestation["verification_key_sha256"]
            and attestation.get("review_sha256") == expected_review_sha
            and attestation.get("candidate_identity_sha256") == expected_identity_sha
            and attestation.get("policy_sha256") == expected_policy_sha
            and attestation.get("corpus_manifest_sha256") == profile["locked_corpus"]["manifest_sha256"]
        )
        try:
            _require_sha256(
                attestation.get("external_receipt_sha256"),
                "human_perceptual_review.attestation.external_receipt_sha256",
                reject_placeholder=True,
            )
        except ValueError:
            immutable_fields_match = False
        if not immutable_fields_match:
            blockers.append({"reason": "external_review_attestation_binding_mismatch"})
        else:
            summary_result["externally_attested"] = True
    summary_result.update(
        {
            "reviewer_count": len(reviewers),
            "blinded": blinded,
            "complete": complete,
            "attribute_votes": votes,
            "baseline_preferred_attributes": baseline_preferred,
            "inconclusive_attributes": inconclusive,
        }
    )
    return summary_result, blockers


def compare(baseline, candidate, policy, *, locked_corpus_manifest=None):
    policy_metrics, required_tracks, minimum_pairs, bootstrap, runtime_target, profile = _validate_policy(policy)
    expected_policy_sha = policy_sha256(policy)
    baseline_suite, baseline_runs, baseline_issues = _index_report(baseline, policy_metrics, expected_policy_sha)
    candidate_suite, candidate_runs, candidate_issues = _index_report(candidate, policy_metrics, expected_policy_sha)
    blockers = [*baseline_issues, *candidate_issues]
    locked_corpus, corpus_blockers, track_contract = _release_corpus_diagnostics(
        locked_corpus_manifest,
        profile,
        required_tracks,
    )
    blockers.extend(corpus_blockers)
    if canonical_json(baseline_suite) != canonical_json(candidate_suite):
        blockers.append({"reason": "incomparable_suite", "baseline": baseline_suite, "candidate": candidate_suite})
    if profile["mode"] == "template" or "__configure_locked_corpus__" in required_tracks:
        blockers.append({"reason": "unconfigured_locked_corpus"})
    if profile["mode"] == "release":
        expected = profile["locked_corpus"]
        for side, suite in (("baseline", baseline_suite), ("candidate", candidate_suite)):
            if suite["corpus_id"] != expected["corpus_id"] or suite["corpus_manifest_sha256"] != expected["manifest_sha256"]:
                blockers.append(
                    {
                        "reason": "release_policy_corpus_mismatch",
                        "side": side,
                        "expected": expected,
                        "actual": {"corpus_id": suite["corpus_id"], "manifest_sha256": suite["corpus_manifest_sha256"]},
                    }
                )
        blockers.extend(
            _release_run_binding_blockers(
                baseline_runs,
                "baseline",
                profile,
                track_contract,
            )
        )
        blockers.extend(
            _release_run_binding_blockers(
                candidate_runs,
                "candidate",
                profile,
                track_contract,
            )
        )
    review_summary, review_blockers = _review_evidence(candidate, profile, expected_policy_sha)
    blockers.extend(review_blockers)

    baseline_tracks = {track for track, _ in baseline_runs}
    candidate_tracks = {track for track, _ in candidate_runs}
    missing_tracks = sorted(required_tracks - (baseline_tracks & candidate_tracks))
    for track in sorted((baseline_tracks | candidate_tracks) - required_tracks):
        blockers.append({"track": track, "reason": "unexpected_track"})
    for track in sorted(baseline_tracks ^ candidate_tracks):
        blockers.append({"track": track, "reason": "track_not_present_in_both_reports"})
    baseline_keys, candidate_keys = set(baseline_runs), set(candidate_runs)
    for track, pair_id in sorted(baseline_keys ^ candidate_keys):
        blockers.append({"track": track, "pair_id": pair_id, "reason": "unpaired_run"})
    paired = sorted(baseline_keys & candidate_keys)
    pairs_by_track = {track: [] for track in required_tracks}
    for key in paired:
        pairs_by_track.setdefault(key[0], []).append(key)
        for difference in _compare_pair_provenance(baseline_runs[key]["run"], candidate_runs[key]["run"]):
            blockers.append({"track": key[0], "pair_id": key[1], "reason": "incomparable_pair_provenance", **difference})
    for track in sorted(required_tracks):
        actual = len(pairs_by_track.get(track, []))
        if actual < minimum_pairs:
            blockers.append({"track": track, "reason": "insufficient_paired_runs", "actual": actual, "minimum": minimum_pairs})

    comparisons, runtime = [], []
    applicability = {
        name: {"applicable_tracks": [], "not_applicable_tracks": [], "not_applicable_evidence": []}
        for name in sorted(policy_metrics)
    }
    for track in sorted(required_tracks & baseline_tracks & candidate_tracks):
        keys = pairs_by_track.get(track, [])
        for metric, rule in sorted(policy_metrics.items()):
            baseline_states = {_availability(baseline_runs[key], metric) for key in keys}
            candidate_states = {_availability(candidate_runs[key], metric) for key in keys}
            if len(baseline_states) != 1 or len(candidate_states) != 1:
                blockers.append({"track": track, "metric": metric, "reason": "inconsistent_metric_applicability"})
                continue
            baseline_state = next(iter(baseline_states), "missing")
            candidate_state = next(iter(candidate_states), "missing")
            if baseline_state != candidate_state:
                blockers.append({"track": track, "metric": metric, "reason": "metric_applicability_changed", "baseline": baseline_state, "candidate": candidate_state})
                continue
            if baseline_state == "not_applicable":
                baseline_evidence = {
                    canonical_json(baseline_runs[key]["not_applicable"][metric])
                    for key in keys
                }
                candidate_evidence = {
                    canonical_json(candidate_runs[key]["not_applicable"][metric])
                    for key in keys
                }
                if len(baseline_evidence) != 1 or baseline_evidence != candidate_evidence:
                    blockers.append({"track": track, "metric": metric, "reason": "not_applicable_evidence_changed"})
                    continue
                evidence = json.loads(next(iter(baseline_evidence)))
                applicability[metric]["not_applicable_tracks"].append(track)
                applicability[metric]["not_applicable_evidence"].append({"track": track, **evidence})
                comparisons.append(
                    {
                        "track": track,
                        "metric": metric,
                        "critical": bool(rule.get("critical", False)),
                        "classification": "not_applicable",
                        "pairs": [],
                    }
                )
                continue
            if baseline_state != "numeric":
                continue
            applicability[metric]["applicable_tracks"].append(track)
            deltas, rows = [], []
            for key in keys:
                before = baseline_runs[key]["metrics"][metric]
                after = candidate_runs[key]["metrics"][metric]
                direction = rule.get("direction", "higher")
                delta = after - before if direction in {"higher", "neutral"} else before - after
                deltas.append(delta)
                rows.append({"pair_id": key[1], "baseline": before, "candidate": after, "effect": delta})
            tolerance = float(rule.get("equivalence_tolerance", 0))
            hard_floor = float(rule.get("pair_hard_regression", tolerance))
            classification, lower, upper = _classify_effect(
                deltas,
                tolerance,
                hard_floor,
                bootstrap,
                f"{bootstrap.get('seed')}|{track}|{metric}",
                rule.get("direction", "higher"),
            )
            row = {
                "track": track,
                "metric": metric,
                "critical": bool(rule.get("critical", False)),
                "classification": classification,
                "equivalence_tolerance": tolerance,
                "pair_hard_regression": hard_floor,
                "paired_effect": summary(deltas),
                "paired_mean_effect_ci": [lower, upper],
                "pairs": rows,
            }
            comparisons.append(row)
            if row["critical"] and classification in {"regressed", "inconclusive"}:
                blockers.append({"reason": f"critical_{classification}", "track": track, "metric": metric, "paired_mean_effect_ci": [lower, upper]})

        runtime_metric = runtime_target["metric"]
        reductions = []
        for key in keys:
            before = baseline_runs[key]["metrics"].get(runtime_metric)
            after = candidate_runs[key]["metrics"].get(runtime_metric)
            if before is None or after is None:
                continue
            if before <= 0:
                blockers.append({"track": track, "pair_id": key[1], "metric": runtime_metric, "reason": "non_positive_baseline_runtime"})
            else:
                reductions.append(100.0 * (before - after) / before)
        if len(reductions) == len(keys) and reductions:
            lower, upper = _stable_bootstrap(
                reductions,
                seed=f"{bootstrap.get('seed')}|{track}|runtime",
                confidence=float(bootstrap.get("confidence", 0.99)),
                resamples=int(bootstrap.get("resamples", 20000)),
            )
            runtime.append(
                {
                    "track": track,
                    "paired_reduction_percent": summary(reductions),
                    "paired_mean_reduction_ci": [lower, upper],
                    "target_reduction_percent": float(runtime_target["target_reduction_percent"]),
                    "target_met": lower >= float(runtime_target["target_reduction_percent"]),
                }
            )

    for metric, rule in sorted(policy_metrics.items()):
        if profile["mode"] != "release" or not rule.get("allow_not_applicable", False):
            continue
        required_coverage = int(rule["minimum_applicable_tracks"])
        actual_coverage = len(applicability[metric]["applicable_tracks"])
        if actual_coverage < required_coverage:
            blockers.append(
                {
                    "reason": "insufficient_metric_applicability_coverage",
                    "metric": metric,
                    "actual_tracks": actual_coverage,
                    "minimum_tracks": required_coverage,
                }
            )

    target_met = bool(runtime) and len(runtime) == len(required_tracks) and all(row["target_met"] for row in runtime)
    status = "FAIL" if missing_tracks or blockers else ("PASS_TARGET" if target_met else "PASS_PARTIAL")
    quality_regression_reasons = {
        "human_perceptual_review_baseline_preferred",
        "human_perceptual_review_fail",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "production_ready": status == "PASS_TARGET" and profile["mode"] == "release",
        "quality_regressions_detected": any(row["classification"] == "regressed" for row in comparisons)
        or any(blocker.get("reason") in quality_regression_reasons for blocker in blockers),
        "missing_required_tracks": missing_tracks,
        "blockers": blockers,
        "comparisons": comparisons,
        "runtime": runtime,
        "metric_applicability": applicability,
        "locked_corpus": locked_corpus,
        "human_perceptual_review": review_summary,
        "release_profile": profile,
        "metric_contract": release_metric_contract() if profile["mode"] == "release" else {"mode": profile["mode"], "configured": False},
        "suite": baseline_suite,
        "policy_sha256": expected_policy_sha,
        "bootstrap": bootstrap,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument(
        "--locked-corpus-manifest",
        help="private hash-pinned release corpus manifest; required by release mode",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args(argv)
    with Path(args.baseline).open(encoding="utf-8") as stream:
        baseline = json.load(stream)
    with Path(args.candidate).open(encoding="utf-8") as stream:
        candidate = json.load(stream)
    with Path(args.policy).open(encoding="utf-8") as stream:
        policy = json.load(stream)
    locked_corpus_manifest = None
    if args.locked_corpus_manifest:
        with Path(args.locked_corpus_manifest).open(encoding="utf-8") as stream:
            locked_corpus_manifest = json.load(stream)
    result = compare(
        baseline,
        candidate,
        policy,
        locked_corpus_manifest=locked_corpus_manifest,
    )
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(f"quality-gate={result['status']} target-tracks={sum(row['target_met'] for row in result['runtime'])}/{len(result['runtime'])}")
    return 0 if result["status"] == "PASS_TARGET" or (args.allow_partial and result["status"] == "PASS_PARTIAL") else 1


if __name__ == "__main__":
    sys.exit(main())
