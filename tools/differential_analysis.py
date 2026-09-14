#!/usr/bin/env python3
"""Deterministic, privacy-safe differential analysis for LightForge outputs.

The quality gate says whether a candidate may be released.  This companion
tool answers the review question that the gate alone cannot: *what materially
changed?*  It compares deliberately narrow, opaque identifiers instead of raw
audio, lyrics, transcript text, waveform data, or command payloads.

The input schema is intentionally strict.  Unknown fields and non-finite
numbers are rejected, so a report cannot accidentally become a side channel
for user data or allow an incomplete comparison to look healthy.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1
TOOL_ID = "lightforge-differential-analysis/1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_TIERS = frozenset({"micro", "secondary", "primary", "phrase", "structural", "climax"})
_COLLISION_STATUSES = frozenset({"resolved", "rerouted", "suppressed", "unresolved"})
_LOSS_STATUSES = frozenset({"suppressed", "unresolved"})
_IDENTITY_FIELDS = (
    "audio_sha256",
    "analysis_configuration_sha256",
    "model_manifest_sha256",
    "vehicle_profile_sha256",
    "fseq_configuration_sha256",
)


class DifferentialValidationError(ValueError):
    """Input is not safe or complete enough for a differential report."""

    def __init__(self, errors: Iterable[str]):
        self.errors = sorted(set(errors))
        super().__init__("; ".join(self.errors))


class IncomparableReportsError(DifferentialValidationError):
    """Baseline and candidate do not describe the same locked workload."""

    def __init__(self, differences: list[dict[str, str]]):
        self.differences = differences
        super().__init__([f"incomparable_identity:{item['field']}" for item in differences])


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _ensure_object(value: Any, path: str, errors: list[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        errors.append(f"{path} must be an object")
        return {}
    return value


def _ensure_fields(
    value: Any,
    path: str,
    required: Iterable[str],
    optional: Iterable[str],
    errors: list[str],
) -> Mapping[str, Any]:
    value = _ensure_object(value, path, errors)
    allowed = set(required) | set(optional)
    for key in sorted(value, key=lambda item: str(item)):
        if key not in allowed:
            errors.append(f"{path}.{key} is not allowed")
    for key in required:
        if key not in value:
            errors.append(f"{path}.{key} is required")
    return value


def _ensure_token(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        errors.append(f"{path} must be an opaque token")


def _ensure_sha256(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        errors.append(f"{path} must be a lower-case SHA-256 digest")


def _ensure_number(
    value: Any,
    path: str,
    errors: list[str],
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> None:
    if not _is_number(value):
        errors.append(f"{path} must be a finite number")
        return
    numeric = float(value)
    if minimum is not None and numeric < minimum:
        errors.append(f"{path} must be at least {minimum}")
    if maximum is not None and numeric > maximum:
        errors.append(f"{path} must be at most {maximum}")


def _ensure_integer(value: Any, path: str, errors: list[str], *, minimum: int = 0) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        errors.append(f"{path} must be an integer of at least {minimum}")


def _validate_identity(value: Any, errors: list[str]) -> None:
    identity = _ensure_fields(value, "identity", (*_IDENTITY_FIELDS, "implementation_id"), (), errors)
    for field in _IDENTITY_FIELDS:
        _ensure_sha256(identity.get(field), f"identity.{field}", errors)
    _ensure_token(identity.get("implementation_id"), "identity.implementation_id", errors)


def _validate_semantic_events(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("semantic_events must be an array")
        return
    seen: set[str] = set()
    required = ("id", "timestamp_seconds", "duration_seconds", "event_type", "source", "confidence", "salience", "tier")
    optional = ("section_id", "recurrence_id", "structural_importance")
    for index, event in enumerate(value):
        path = f"semantic_events[{index}]"
        event = _ensure_fields(event, path, required, optional, errors)
        event_id = event.get("id")
        _ensure_token(event_id, f"{path}.id", errors)
        if isinstance(event_id, str):
            if event_id in seen:
                errors.append(f"{path}.id is duplicated")
            seen.add(event_id)
        _ensure_number(event.get("timestamp_seconds"), f"{path}.timestamp_seconds", errors, minimum=0)
        _ensure_number(event.get("duration_seconds"), f"{path}.duration_seconds", errors, minimum=0)
        _ensure_token(event.get("event_type"), f"{path}.event_type", errors)
        _ensure_token(event.get("source"), f"{path}.source", errors)
        _ensure_number(event.get("confidence"), f"{path}.confidence", errors, minimum=0, maximum=1)
        _ensure_number(event.get("salience"), f"{path}.salience", errors, minimum=0, maximum=1)
        if event.get("tier") not in _TIERS:
            errors.append(f"{path}.tier must be one of {','.join(sorted(_TIERS))}")
        for field in ("section_id", "recurrence_id"):
            if field in event:
                _ensure_token(event.get(field), f"{path}.{field}", errors)
        if "structural_importance" in event:
            _ensure_number(event.get("structural_importance"), f"{path}.structural_importance", errors, minimum=0, maximum=1)


def _validate_commands(value: Any, event_ids: set[str], errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("choreography_commands must be an array")
        return
    seen: set[str] = set()
    required = ("id", "event_id", "timestamp_seconds", "duration_seconds", "output_id", "command_type")
    optional = ("value", "perceptual_timestamp_seconds", "salience")
    for index, command in enumerate(value):
        path = f"choreography_commands[{index}]"
        command = _ensure_fields(command, path, required, optional, errors)
        command_id = command.get("id")
        _ensure_token(command_id, f"{path}.id", errors)
        if isinstance(command_id, str):
            if command_id in seen:
                errors.append(f"{path}.id is duplicated")
            seen.add(command_id)
        event_id = command.get("event_id")
        _ensure_token(event_id, f"{path}.event_id", errors)
        if isinstance(event_id, str) and event_id not in event_ids:
            errors.append(f"{path}.event_id does not reference a semantic event")
        _ensure_number(command.get("timestamp_seconds"), f"{path}.timestamp_seconds", errors, minimum=0)
        _ensure_number(command.get("duration_seconds"), f"{path}.duration_seconds", errors, minimum=0)
        _ensure_token(command.get("output_id"), f"{path}.output_id", errors)
        _ensure_token(command.get("command_type"), f"{path}.command_type", errors)
        if "value" in command:
            _ensure_number(command.get("value"), f"{path}.value", errors)
        if "perceptual_timestamp_seconds" in command:
            _ensure_number(command.get("perceptual_timestamp_seconds"), f"{path}.perceptual_timestamp_seconds", errors, minimum=0)
        if "salience" in command:
            _ensure_number(command.get("salience"), f"{path}.salience", errors, minimum=0, maximum=1)


def _validate_collisions(value: Any, event_ids: set[str], errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("collision_resolutions must be an array")
        return
    seen: set[str] = set()
    required = ("id", "event_id", "status", "salience")
    optional = ("preferred_output_id", "realized_output_id", "reason")
    for index, collision in enumerate(value):
        path = f"collision_resolutions[{index}]"
        collision = _ensure_fields(collision, path, required, optional, errors)
        collision_id = collision.get("id")
        _ensure_token(collision_id, f"{path}.id", errors)
        if isinstance(collision_id, str):
            if collision_id in seen:
                errors.append(f"{path}.id is duplicated")
            seen.add(collision_id)
        event_id = collision.get("event_id")
        _ensure_token(event_id, f"{path}.event_id", errors)
        if isinstance(event_id, str) and event_id not in event_ids:
            errors.append(f"{path}.event_id does not reference a semantic event")
        if collision.get("status") not in _COLLISION_STATUSES:
            errors.append(f"{path}.status must be one of {','.join(sorted(_COLLISION_STATUSES))}")
        _ensure_number(collision.get("salience"), f"{path}.salience", errors, minimum=0, maximum=1)
        for field in ("preferred_output_id", "realized_output_id", "reason"):
            if field in collision:
                _ensure_token(collision.get(field), f"{path}.{field}", errors)


def _validate_fseq_timing(value: Any, command_ids: set[str], errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("fseq_timing must be an array")
        return
    seen: set[str] = set()
    required = (
        "id",
        "command_id",
        "intended_perceptual_timestamp_seconds",
        "command_timestamp_seconds",
        "realized_perceptual_timestamp_seconds",
        "frame_index",
    )
    for index, timing in enumerate(value):
        path = f"fseq_timing[{index}]"
        timing = _ensure_fields(timing, path, required, (), errors)
        timing_id = timing.get("id")
        _ensure_token(timing_id, f"{path}.id", errors)
        if isinstance(timing_id, str):
            if timing_id in seen:
                errors.append(f"{path}.id is duplicated")
            seen.add(timing_id)
        command_id = timing.get("command_id")
        _ensure_token(command_id, f"{path}.command_id", errors)
        if isinstance(command_id, str) and command_id not in command_ids:
            errors.append(f"{path}.command_id does not reference a choreography command")
        for field in (
            "intended_perceptual_timestamp_seconds",
            "command_timestamp_seconds",
            "realized_perceptual_timestamp_seconds",
        ):
            _ensure_number(timing.get(field), f"{path}.{field}", errors, minimum=0)
        _ensure_integer(timing.get("frame_index"), f"{path}.frame_index", errors)


def validate_report(report: Any) -> None:
    """Validate an input report without attempting a partial comparison."""
    errors: list[str] = []
    report = _ensure_fields(
        report,
        "report",
        ("schema_version", "identity", "semantic_events", "choreography_commands", "collision_resolutions", "fseq_timing"),
        (),
        errors,
    )
    if report.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"report.schema_version must equal {SCHEMA_VERSION}")
    _validate_identity(report.get("identity"), errors)
    semantic = report.get("semantic_events")
    _validate_semantic_events(semantic, errors)
    event_ids = {item.get("id") for item in semantic if isinstance(item, Mapping) and isinstance(item.get("id"), str)} if isinstance(semantic, list) else set()
    commands = report.get("choreography_commands")
    _validate_commands(commands, event_ids, errors)
    command_ids = {item.get("id") for item in commands if isinstance(item, Mapping) and isinstance(item.get("id"), str)} if isinstance(commands, list) else set()
    _validate_collisions(report.get("collision_resolutions"), event_ids, errors)
    _validate_fseq_timing(report.get("fseq_timing"), command_ids, errors)
    if errors:
        raise DifferentialValidationError(errors)


def _index(items: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(item["id"]): item for item in items}


def _as_sorted_records(items: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [dict(item) for item in sorted(items, key=lambda item: str(item["id"]))]


def _change(before: Any, after: Any, field: str) -> dict[str, Any]:
    result: dict[str, Any] = {"baseline": before, "candidate": after}
    if isinstance(before, (int, float)) and isinstance(after, (int, float)) and not isinstance(before, bool) and not isinstance(after, bool):
        delta = float(after) - float(before)
        result["delta"] = delta
        if field.endswith("_seconds"):
            result["delta_milliseconds"] = delta * 1000.0
    return result


def _shared_changes(
    baseline: Mapping[str, Any], candidate: Mapping[str, Any], fields: Iterable[str]
) -> dict[str, Any]:
    return {
        field: _change(baseline.get(field), candidate.get(field), field)
        for field in fields
        if baseline.get(field) != candidate.get(field)
    }


def _is_section_boundary(event: Mapping[str, Any]) -> bool:
    event_type = str(event.get("event_type", ""))
    return event_type == "section_boundary" or event_type.endswith(".section_boundary")


def _event_ranks(events: Mapping[str, Mapping[str, Any]]) -> dict[str, int]:
    ranked = sorted(events.values(), key=lambda event: (-float(event["salience"]), str(event["id"])))
    return {str(event["id"]): rank for rank, event in enumerate(ranked, start=1)}


def _semantic_diff(
    baseline_events: list[Mapping[str, Any]], candidate_events: list[Mapping[str, Any]], threshold: float
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    baseline = _index(baseline_events)
    candidate = _index(candidate_events)
    added_ids = sorted(set(candidate) - set(baseline))
    removed_ids = sorted(set(baseline) - set(candidate))
    shared_ids = sorted(set(baseline) & set(candidate))
    fields = (
        "timestamp_seconds",
        "duration_seconds",
        "event_type",
        "source",
        "confidence",
        "salience",
        "tier",
        "section_id",
        "recurrence_id",
        "structural_importance",
    )
    changed, shifted, confidence_changes, salience_changes = [], [], [], []
    review: list[dict[str, Any]] = []
    for event_id in shared_ids:
        before, after = baseline[event_id], candidate[event_id]
        changes = _shared_changes(before, after, fields)
        if changes:
            changed.append({"id": event_id, "changes": changes})
        if "timestamp_seconds" in changes:
            shift = {
                "id": event_id,
                "event_type": after["event_type"],
                "source": after["source"],
                "baseline_timestamp_seconds": before["timestamp_seconds"],
                "candidate_timestamp_seconds": after["timestamp_seconds"],
                "delta_milliseconds": changes["timestamp_seconds"]["delta_milliseconds"],
            }
            shifted.append(shift)
            if max(float(before["salience"]), float(after["salience"])) >= threshold:
                review.append({"kind": "shifted_high_salience_event", "severity": "release_review", "id": event_id, **shift})
        if "confidence" in changes:
            confidence_changes.append({"id": event_id, **changes["confidence"]})
        if "salience" in changes:
            salience_changes.append({"id": event_id, **changes["salience"]})
            if float(before["salience"]) >= threshold and float(after["salience"]) < threshold:
                review.append(
                    {
                        "kind": "demoted_high_salience_event",
                        "severity": "release_review",
                        "id": event_id,
                        "baseline_salience": before["salience"],
                        "candidate_salience": after["salience"],
                    }
                )
        if (before["event_type"] != after["event_type"] or before["source"] != after["source"]) and max(
            float(before["salience"]), float(after["salience"])
        ) >= threshold:
            review.append(
                {
                    "kind": "reclassified_high_salience_event",
                    "severity": "release_review",
                    "id": event_id,
                    "baseline_event_type": before["event_type"],
                    "candidate_event_type": after["event_type"],
                    "baseline_source": before["source"],
                    "candidate_source": after["source"],
                }
            )
    for event_id in removed_ids:
        before = baseline[event_id]
        if float(before["salience"]) >= threshold:
            review.append(
                {
                    "kind": "removed_high_salience_event",
                    "severity": "release_review",
                    "id": event_id,
                    "event_type": before["event_type"],
                    "source": before["source"],
                    "timestamp_seconds": before["timestamp_seconds"],
                    "salience": before["salience"],
                }
            )
    baseline_ranks, candidate_ranks = _event_ranks(baseline), _event_ranks(candidate)
    rank_changes = [
        {
            "id": event_id,
            "baseline_rank": baseline_ranks[event_id],
            "candidate_rank": candidate_ranks[event_id],
            "rank_delta": candidate_ranks[event_id] - baseline_ranks[event_id],
            "baseline_salience": baseline[event_id]["salience"],
            "candidate_salience": candidate[event_id]["salience"],
        }
        for event_id in shared_ids
        if baseline_ranks[event_id] != candidate_ranks[event_id]
    ]
    section_added = [candidate[event_id] for event_id in added_ids if _is_section_boundary(candidate[event_id])]
    section_removed = [baseline[event_id] for event_id in removed_ids if _is_section_boundary(baseline[event_id])]
    section_changed = [
        item
        for item in changed
        if _is_section_boundary(baseline[item["id"]]) or _is_section_boundary(candidate[item["id"]])
    ]
    return (
        {
            "baseline_count": len(baseline),
            "candidate_count": len(candidate),
            "added": _as_sorted_records(candidate[event_id] for event_id in added_ids),
            "removed": _as_sorted_records(baseline[event_id] for event_id in removed_ids),
            "changed": changed,
            "timestamps_shifted": shifted,
            "confidence_changed": confidence_changes,
            "salience_changed": salience_changes,
            "salience_rank_changes": rank_changes,
            "section_boundaries": {
                "added": _as_sorted_records(section_added),
                "removed": _as_sorted_records(section_removed),
                "changed": section_changed,
            },
        },
        review,
    )


def _command_salience(command: Mapping[str, Any], events: Mapping[str, Mapping[str, Any]]) -> float:
    if "salience" in command:
        return float(command["salience"])
    return float(events[str(command["event_id"])]["salience"])


def _command_diff(
    baseline_commands: list[Mapping[str, Any]],
    candidate_commands: list[Mapping[str, Any]],
    baseline_events: list[Mapping[str, Any]],
    candidate_events: list[Mapping[str, Any]],
    threshold: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    baseline, candidate = _index(baseline_commands), _index(candidate_commands)
    baseline_event_index, candidate_event_index = _index(baseline_events), _index(candidate_events)
    added_ids, removed_ids = sorted(set(candidate) - set(baseline)), sorted(set(baseline) - set(candidate))
    shared_ids = sorted(set(baseline) & set(candidate))
    fields = (
        "event_id",
        "timestamp_seconds",
        "duration_seconds",
        "output_id",
        "command_type",
        "value",
        "perceptual_timestamp_seconds",
        "salience",
    )
    changed, shifted, assignments = [], [], []
    review: list[dict[str, Any]] = []
    for command_id in shared_ids:
        before, after = baseline[command_id], candidate[command_id]
        changes = _shared_changes(before, after, fields)
        if changes:
            changed.append({"id": command_id, "changes": changes})
        if "timestamp_seconds" in changes:
            shift = {
                "id": command_id,
                "baseline_timestamp_seconds": before["timestamp_seconds"],
                "candidate_timestamp_seconds": after["timestamp_seconds"],
                "delta_milliseconds": changes["timestamp_seconds"]["delta_milliseconds"],
            }
            shifted.append(shift)
            if max(_command_salience(before, baseline_event_index), _command_salience(after, candidate_event_index)) >= threshold:
                review.append({"kind": "shifted_high_salience_command", "severity": "release_review", **shift})
        if "output_id" in changes:
            assignments.append(
                {
                    "id": command_id,
                    "event_id": after["event_id"],
                    "baseline_output_id": before["output_id"],
                    "candidate_output_id": after["output_id"],
                }
            )
    for command_id in removed_ids:
        before = baseline[command_id]
        if _command_salience(before, baseline_event_index) >= threshold:
            review.append(
                {
                    "kind": "removed_high_salience_command",
                    "severity": "release_review",
                    "id": command_id,
                    "event_id": before["event_id"],
                    "output_id": before["output_id"],
                }
            )
    return (
        {
            "baseline_count": len(baseline),
            "candidate_count": len(candidate),
            "added": _as_sorted_records(candidate[item] for item in added_ids),
            "removed": _as_sorted_records(baseline[item] for item in removed_ids),
            "changed": changed,
            "timestamps_shifted": shifted,
            "actuator_assignment_changes": assignments,
        },
        review,
    )


def _collision_loss_summary(collisions: list[Mapping[str, Any]], threshold: float) -> dict[str, Any]:
    total = len(collisions)
    losses = [item for item in collisions if item["status"] in _LOSS_STATUSES]
    high = [item for item in collisions if float(item["salience"]) >= threshold]
    high_losses = [item for item in high if item["status"] in _LOSS_STATUSES]
    return {
        "total": total,
        "lost": len(losses),
        "loss_rate": 0.0 if not total else len(losses) / total,
        "high_salience_total": len(high),
        "high_salience_lost": len(high_losses),
        "high_salience_loss_rate": 0.0 if not high else len(high_losses) / len(high),
    }


def _collision_diff(
    baseline_collisions: list[Mapping[str, Any]], candidate_collisions: list[Mapping[str, Any]], threshold: float
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    baseline, candidate = _index(baseline_collisions), _index(candidate_collisions)
    added_ids, removed_ids = sorted(set(candidate) - set(baseline)), sorted(set(baseline) - set(candidate))
    shared_ids = sorted(set(baseline) & set(candidate))
    fields = ("event_id", "status", "preferred_output_id", "realized_output_id", "reason", "salience")
    changed = []
    review: list[dict[str, Any]] = []
    for collision_id in shared_ids:
        before, after = baseline[collision_id], candidate[collision_id]
        changes = _shared_changes(before, after, fields)
        if changes:
            changed.append({"id": collision_id, "changes": changes})
    for collision_id in sorted(candidate):
        collision = candidate[collision_id]
        if collision["status"] in _LOSS_STATUSES and float(collision["salience"]) >= threshold:
            review.append(
                {
                    "kind": "unresolved_high_salience_collision",
                    "severity": "release_review",
                    "id": collision_id,
                    "event_id": collision["event_id"],
                    "status": collision["status"],
                    "salience": collision["salience"],
                }
            )
    baseline_summary = _collision_loss_summary(baseline_collisions, threshold)
    candidate_summary = _collision_loss_summary(candidate_collisions, threshold)
    if candidate_summary["high_salience_loss_rate"] > baseline_summary["high_salience_loss_rate"]:
        review.append(
            {
                "kind": "high_salience_collision_loss_increased",
                "severity": "release_review",
                "baseline_high_salience_loss_rate": baseline_summary["high_salience_loss_rate"],
                "candidate_high_salience_loss_rate": candidate_summary["high_salience_loss_rate"],
            }
        )
    return (
        {
            "baseline_count": len(baseline),
            "candidate_count": len(candidate),
            "added": _as_sorted_records(candidate[item] for item in added_ids),
            "removed": _as_sorted_records(baseline[item] for item in removed_ids),
            "resolution_changes": changed,
            "baseline_loss": baseline_summary,
            "candidate_loss": candidate_summary,
        },
        review,
    )


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * quantile
    lower, upper = math.floor(position), math.ceil(position)
    return values[lower] if lower == upper else values[lower] + (values[upper] - values[lower]) * (position - lower)


def _timing_summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    command_errors = [
        abs(float(row["command_timestamp_seconds"]) - float(row["intended_perceptual_timestamp_seconds"])) * 1000.0
        for row in rows
    ]
    perceptual_errors = [
        abs(float(row["realized_perceptual_timestamp_seconds"]) - float(row["intended_perceptual_timestamp_seconds"])) * 1000.0
        for row in rows
    ]

    def summarize(values: list[float]) -> dict[str, Any]:
        return {
            "count": len(values),
            "median_milliseconds": statistics.median(values) if values else None,
            "p90_milliseconds": _percentile(values, 0.90),
            "p95_milliseconds": _percentile(values, 0.95),
            "p99_milliseconds": _percentile(values, 0.99),
            "maximum_milliseconds": max(values) if values else None,
        }

    return {"command_error": summarize(command_errors), "predicted_perceptual_error": summarize(perceptual_errors)}


def _fseq_diff(baseline_rows: list[Mapping[str, Any]], candidate_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    baseline, candidate = _index(baseline_rows), _index(candidate_rows)
    added_ids, removed_ids = sorted(set(candidate) - set(baseline)), sorted(set(baseline) - set(candidate))
    shared_ids = sorted(set(baseline) & set(candidate))
    fields = (
        "command_id",
        "intended_perceptual_timestamp_seconds",
        "command_timestamp_seconds",
        "realized_perceptual_timestamp_seconds",
        "frame_index",
    )
    changed, timing_differences = [], []
    timing_fields = (
        "intended_perceptual_timestamp_seconds",
        "command_timestamp_seconds",
        "realized_perceptual_timestamp_seconds",
    )
    for row_id in shared_ids:
        before, after = baseline[row_id], candidate[row_id]
        changes = _shared_changes(before, after, fields)
        if changes:
            changed.append({"id": row_id, "changes": changes})
        if any(field in changes for field in timing_fields):
            baseline_command_error = abs(float(before["command_timestamp_seconds"]) - float(before["intended_perceptual_timestamp_seconds"])) * 1000.0
            candidate_command_error = abs(float(after["command_timestamp_seconds"]) - float(after["intended_perceptual_timestamp_seconds"])) * 1000.0
            baseline_perceptual_error = abs(float(before["realized_perceptual_timestamp_seconds"]) - float(before["intended_perceptual_timestamp_seconds"])) * 1000.0
            candidate_perceptual_error = abs(float(after["realized_perceptual_timestamp_seconds"]) - float(after["intended_perceptual_timestamp_seconds"])) * 1000.0
            timing_differences.append(
                {
                    "id": row_id,
                    "command_id": after["command_id"],
                    "intended_timestamp_delta_milliseconds": (
                        float(after["intended_perceptual_timestamp_seconds"])
                        - float(before["intended_perceptual_timestamp_seconds"])
                    )
                    * 1000.0,
                    "command_timestamp_delta_milliseconds": (
                        float(after["command_timestamp_seconds"]) - float(before["command_timestamp_seconds"])
                    )
                    * 1000.0,
                    "realized_perceptual_timestamp_delta_milliseconds": (
                        float(after["realized_perceptual_timestamp_seconds"])
                        - float(before["realized_perceptual_timestamp_seconds"])
                    )
                    * 1000.0,
                    "baseline_command_error_milliseconds": baseline_command_error,
                    "candidate_command_error_milliseconds": candidate_command_error,
                    "command_error_delta_milliseconds": candidate_command_error - baseline_command_error,
                    "baseline_predicted_perceptual_error_milliseconds": baseline_perceptual_error,
                    "candidate_predicted_perceptual_error_milliseconds": candidate_perceptual_error,
                    "predicted_perceptual_error_delta_milliseconds": candidate_perceptual_error - baseline_perceptual_error,
                }
            )
    return {
        "baseline_count": len(baseline),
        "candidate_count": len(candidate),
        "added": _as_sorted_records(candidate[item] for item in added_ids),
        "removed": _as_sorted_records(baseline[item] for item in removed_ids),
        "changed": changed,
        "timing_differences": timing_differences,
        "baseline_timing": _timing_summary(baseline_rows),
        "candidate_timing": _timing_summary(candidate_rows),
    }


def _ensure_comparable(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> None:
    differences = [
        {"field": field, "baseline": str(baseline["identity"][field]), "candidate": str(candidate["identity"][field])}
        for field in _IDENTITY_FIELDS
        if baseline["identity"][field] != candidate["identity"][field]
    ]
    if differences:
        raise IncomparableReportsError(differences)


def compare(baseline: Mapping[str, Any], candidate: Mapping[str, Any], high_salience_threshold: float = 0.70) -> dict[str, Any]:
    """Return a deterministic, machine-readable diff or raise a fail-closed error."""
    _ensure_number(high_salience_threshold, "high_salience_threshold", [], minimum=0, maximum=1)
    if not _is_number(high_salience_threshold) or not 0 <= float(high_salience_threshold) <= 1:
        raise DifferentialValidationError(["high_salience_threshold must be a finite number in [0, 1]"])
    validate_report(baseline)
    validate_report(candidate)
    _ensure_comparable(baseline, candidate)
    threshold = float(high_salience_threshold)
    semantic, semantic_review = _semantic_diff(baseline["semantic_events"], candidate["semantic_events"], threshold)
    choreography, choreography_review = _command_diff(
        baseline["choreography_commands"],
        candidate["choreography_commands"],
        baseline["semantic_events"],
        candidate["semantic_events"],
        threshold,
    )
    collisions, collision_review = _collision_diff(
        baseline["collision_resolutions"], candidate["collision_resolutions"], threshold
    )
    fseq = _fseq_diff(baseline["fseq_timing"], candidate["fseq_timing"])
    review_items = sorted(
        semantic_review + choreography_review + collision_review,
        key=lambda item: (str(item["kind"]), str(item.get("id", ""))),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL_ID,
        "status": "COMPARABLE",
        "high_salience_threshold": threshold,
        "identity": {
            **{field: baseline["identity"][field] for field in _IDENTITY_FIELDS},
            "baseline_implementation_id": baseline["identity"]["implementation_id"],
            "candidate_implementation_id": candidate["identity"]["implementation_id"],
        },
        "summary": {
            "semantic_events_added": len(semantic["added"]),
            "semantic_events_removed": len(semantic["removed"]),
            "semantic_events_changed": len(semantic["changed"]),
            "choreography_commands_added": len(choreography["added"]),
            "choreography_commands_removed": len(choreography["removed"]),
            "choreography_commands_changed": len(choreography["changed"]),
            "collision_resolution_changes": len(collisions["resolution_changes"]),
            "fseq_timing_differences": len(fseq["timing_differences"]),
            "release_review_item_count": len(review_items),
        },
        "semantic_events": semantic,
        "choreography_commands": choreography,
        "collision_resolutions": collisions,
        "fseq_timing": fseq,
        "release_review_items": review_items,
    }


def _reject_non_finite_constant(_: str) -> None:
    raise ValueError("non-finite JSON numeric constant")


def load_report(path: str | Path) -> Mapping[str, Any]:
    """Load JSON without ever accepting JavaScript-style NaN or Infinity."""
    try:
        with Path(path).open(encoding="utf-8") as handle:
            value = json.load(handle, parse_constant=_reject_non_finite_constant)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise DifferentialValidationError(["input must be readable strict JSON with finite numbers"]) from error
    if not isinstance(value, Mapping):
        raise DifferentialValidationError(["report must be an object"])
    return value


def write_report(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _error_report(status: str, errors: Iterable[str], *, differences: list[dict[str, str]] | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL_ID,
        "status": status,
        "errors": sorted(set(errors)),
    }
    if differences:
        report["identity_differences"] = sorted(differences, key=lambda item: item["field"])
    return report


def _threshold_argument(value: str) -> float:
    try:
        threshold = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a finite number in [0, 1]") from error
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise argparse.ArgumentTypeError("must be a finite number in [0, 1]")
    return threshold


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, help="strict JSON baseline artifact")
    parser.add_argument("--candidate", required=True, help="strict JSON candidate artifact")
    parser.add_argument("--output", required=True, help="machine-readable differential report")
    parser.add_argument("--high-salience-threshold", type=_threshold_argument, default=0.70)
    args = parser.parse_args(argv)
    try:
        result = compare(load_report(args.baseline), load_report(args.candidate), args.high_salience_threshold)
    except IncomparableReportsError as error:
        write_report(args.output, _error_report("INCOMPARABLE", error.errors, differences=error.differences))
        print("differential-analysis=INCOMPARABLE", file=sys.stderr)
        return 2
    except DifferentialValidationError as error:
        write_report(args.output, _error_report("INVALID_INPUT", error.errors))
        print("differential-analysis=INVALID_INPUT", file=sys.stderr)
        return 2
    write_report(args.output, result)
    print(f"differential-analysis=COMPARABLE review-items={result['summary']['release_review_item_count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
