#!/usr/bin/env python3
"""Summarize retained Android diagnostic observations without qualifying a release."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
import math
from pathlib import Path
import re

MAX_REPORT_BYTES = 16 * 1024 * 1024
EVENT = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+(?:Z|[+-]\d\d:\d\d)) (INFO|WARN|ERROR) ([a-z][a-z0-9-]*) (.*)$")
FIELD = re.compile(r"(?:^|[ ;])([A-Za-z][A-Za-z0-9]*)=([^\s;]+)")
STAGES = frozenset(("rhythm", "separation", "voice", "bass", "recurrence"))
NATIVE_STAGES = frozenset((
    "inference-gate-wait", "engine-init", "cache-preflight", "buffer-init", "runtime-setup",
    "pcm-read", "feature-encode", "model-init", "tensor-bind", "inference",
    "pack", "scatter", "decode", "output-write", "output-flush", "output-commit",
))
NATIVE_GRAPHS = frozenset(("front", "head-0", "head-1")) | frozenset(
    f"block-{index:02d}-{axis}" for index in range(12) for axis in ("time", "frequency")
)
TEMPORAL_SESSION_METRICS = (
    "temporalBaselineSessionCount", "temporalFourWorkerSessionCount",
    "temporalEightWorkerSessionCount", "temporalUnobservedSessionCount",
)
FREQUENCY_SESSION_METRICS = (
    "frequencyBaselineSessionCount", "frequencyFourWorkerSessionCount",
    "frequencyEightWorkerSessionCount", "frequencyUnobservedSessionCount",
)
SUMMARY_METRICS = (
    "wallMs", "instrumentedCpuMs", "waitWallMs", "waitCpuMs", "engineInitWallMs",
    "preflightWallMs", "bufferInitWallMs", "runtimeInitWallMs", "preprocessWallMs",
    "preprocessCpuMs", "modelInitWallMs", "modelInitCpuMs", "inferenceWallMs",
    "inferenceCpuMs", "postprocessWallMs", "postprocessCpuMs", "cacheModelHits",
    "cacheModelMisses", "cacheHitBytes", "cacheMissBytes", "directBufferBytes",
    "inferenceThreadCpuMs", "inferenceProcessCpuMs", "inferenceCount", "sessionInitCount",
    "inferenceWorkerThreadCpuMs", "inferenceWorkerRunCount",
    "schedulerCalibrationWallMs", "schedulerCalibrationCount",
) + TEMPORAL_SESSION_METRICS + FREQUENCY_SESSION_METRICS
GRAPH_METRICS = ("runCount", "runWallMs", "runCpuMs", "runProcessCpuMs", "sessionInitCount", "sessionInitWallMs",
                 "modelPrepareCount", "modelPrepareWallMs", "tensorBindCount", "tensorBindWallMs",
                 "packWallMs", "packCpuMs", "packProcessCpuMs", "scatterWallMs", "scatterCpuMs", "scatterProcessCpuMs")
TELEMETRY = ("cpuTelemetry", "memoryTelemetry", "acceleratorTelemetry", "directBufferTelemetry", "cacheTelemetry", "inferenceWorkerCpuTelemetry")
SUMMARY_SCOPES = {
    "cpuScope": {"calling-thread"}, "processCpuScope": {"all-app-threads"},
    "inferenceWallScope": {"critical-path"},
    "inferenceThreadCpuScope": {"calling-thread", "coordinator"},
    "inferenceWorkerThreadCpuScope": {"sum-run-calling-threads"},
    "inferenceWorkScope": {"run-and-wave-coordination", "run-and-pipeline-coordination"},
    "instrumentedCpuScope": {"nonoverlapping-calling-thread"},
    "temporalConfigCountScope": {"session-init-attempts"},
    "frequencyConfigCountScope": {"session-init-attempts"},
}
COPY_INTERVAL_SCOPES = {"sequential-intervals", "nested-in-inference-pipeline", "mixed-nested-and-sequential-intervals", "unavailable"}
COPY_PROCESS_SCOPES = {"all-app-threads", "unavailable-overlapping-intervals", "unavailable"}
STAGE_SCOPES = {
    "wallScope": {"critical-path"} | COPY_INTERVAL_SCOPES,
    "workScope": {"run-and-wave-coordination", "run-and-pipeline-coordination"},
    "cpuScope": {"calling-thread"}, "processCpuScope": COPY_PROCESS_SCOPES,
}
GRAPH_SCOPES = {
    "graphWallScope": {"aggregate-call", "sequential-intervals"},
    "runCpuScope": {"run-calling-threads", "calling-thread"},
    "runProcessCpuScope": {"unavailable-overlapping-intervals", "all-app-threads"},
    "packWallScope": COPY_INTERVAL_SCOPES, "scatterWallScope": COPY_INTERVAL_SCOPES,
    "packProcessCpuScope": COPY_PROCESS_SCOPES, "scatterProcessCpuScope": COPY_PROCESS_SCOPES,
}
POLICY_REASONS = frozenset((
    "unmeasured", "fresh-pair-required", "nominated", "initial-pair", "qualification-wait",
    "qualification-pair", "slow-passage-recheck", "lease-recheck", "qualified-lease",
    "measured-passage-improvement", "qualification-pending", "invalid-nomination", "unfinished-pair",
    "invalid-plan", "memory-ineligible", "short-job", "probe-budget", "missed-qualification",
    "payback-unavailable", "short-renewal", "invalid-pair", "pair-regression", "invalid-pair-order",
    "median-regression", "invalid-timing", "probe-aborted", "external-baseline", "cancelled",
    "memory-fallback", "thermal-guard", "output-mismatch", "memory-pressure", "screen-budget",
    "screen-no-win", "runtime-rejected", "unknown-work",
    "control-required", "slow-passage-control", "control-accepted", "control-regression",
    "control-incomplete", "unfinished-control",
))
POLICY_SCHEMA = "native-passage-policy-v1"
PAIR_SCHEMA = "native-passage-pair-v1"
CONTROL_SCHEMA = "native-passage-control-v1"
POLICY_SCHEMAS = {POLICY_SCHEMA, PAIR_SCHEMA, CONTROL_SCHEMA}
PAIR_NANOS = ("baselineNanos", "candidateNanos", "extraNanos")
CONTROL_NANOS = ("baselineNanos", "previousBaselineNanos", "candidateMaxNanos")


def _policy_record(raw):
    """Parse only the bounded exporter vocabulary; nanoseconds retain integer precision."""
    tokens = raw.split(" ") if isinstance(raw, str) and len(raw) <= 512 else []
    fields = dict(FIELD.findall(raw)) if tokens else {}
    schema = fields.get("schema")
    if schema not in POLICY_SCHEMAS:
        return {"status": "invalid", "schema": None}
    result = {"status": "observed", "schema": schema}
    valid = bool(tokens) and len(fields) == len(tokens) and all(
        re.fullmatch(r"[A-Za-z][A-Za-z0-9]*=[^\s;=]+", token) for token in tokens)
    enums = ({"state": {"baseline", "qualified", "provisional"}, "workers": {"0", "4", "8"},
              "reason": POLICY_REASONS, "paybackScope": {"projected-not-measured"}}
             if schema == POLICY_SCHEMA else {"role": {"qualification", "recheck"}, "workers": {"4", "8"}}
             if schema == PAIR_SCHEMA else {"comparisonScope": {"unmatched-inputs"}})
    numbers = ({"extraNanos": 2**63 - 1, "extraCapNanos": 360_000_000_000,
                "projectedAccruedSavingsNanos": 2**63 - 1, "qualificationPairs": 3,
                "currentJobPairs": 4096, "activePassages": 4096, "leasePassages": 12}
               if schema == POLICY_SCHEMA else {"index": 2, "ordinal": 4095,
                                                **{key: 2**63 - 1 for key in PAIR_NANOS}}
               if schema == PAIR_SCHEMA else {"ordinal": 4095, "candidateSamples": 3,
                                               **{key: 3_600_000_000_000 for key in CONTROL_NANOS}})
    booleans = (("seeded",) if schema == POLICY_SCHEMA else
                ("candidateFirst", "finite", "exact", "fullGeometry", "coldSessions") if schema == PAIR_SCHEMA else ("accepted",))
    allowed = {"schema"} | set(enums) | set(numbers) | set(booleans)
    if schema == PAIR_SCHEMA:
        allowed.add("outputSha256")
        digest = fields.get("outputSha256", "")
        result["outputSha256"] = digest if re.fullmatch(r"[a-f0-9]{64}", digest) else None
        valid &= result["outputSha256"] is not None
    valid &= set(fields) == allowed
    for key, vocabulary in enums.items():
        result[key] = fields.get(key) if fields.get(key) in vocabulary else None
        valid &= result[key] is not None
    for key, maximum in numbers.items():
        raw_value = fields.get(key, "")
        value = int(raw_value) if re.fullmatch(r"[0-9]{1,19}", raw_value) else None
        good = value is not None and value <= maximum
        if key == "extraCapNanos":
            good &= value == 360_000_000_000
        elif key == "leasePassages":
            good &= value in (8, 12)
        elif schema == CONTROL_SCHEMA and key in CONTROL_NANOS:
            good &= value is not None and value > 0
        elif schema == CONTROL_SCHEMA and key == "candidateSamples":
            good &= value == 3
        result[key] = {"status": "observed" if good else "unavailable", "value": value if good else None}
        valid &= good
    for key in booleans:
        result[key] = fields.get(key) == "true" if fields.get(key) in ("true", "false") else None
        valid &= result[key] is not None
    if schema == PAIR_SCHEMA and result["role"] == "recheck":
        valid &= result["index"]["value"] == 0
    result["status"] = "observed" if valid else "invalid"
    return result


def _passage_policy(records=(), encoded=None, *, source):
    """Snapshots repeat history: neither pairs nor projected savings are additive."""
    result = {"status": "unavailable", "source": source,
              "scope": "controller-evidence-snapshot-not-additional-passages",
              "qualification_status": "not-independently-evaluated", "timing_units": "nanoseconds",
              "payback_scope": "projected-not-measured", "controller": None, "pairs": [], "controls": [],
              "control_scope": "unmatched-input-timing-guard-not-same-input-equality-or-speedup-proof"}
    decoded = None
    if encoded is not None:
        if not isinstance(encoded, str) or len(encoded) > 8 * 513:
            result["status"] = "invalid"
            return result
        decoded = [row.replace(",", " ") for row in encoded.split("|")] if encoded else []
    rows = list(records) if records else decoded or []
    if not rows:
        return result
    if len(rows) > 8:
        result["status"] = "invalid"
        return result
    parsed = [_policy_record(row) for row in rows]
    valid = parsed[0].get("schema") == POLICY_SCHEMA and all(row["status"] == "observed" for row in parsed)
    if decoded is not None and records:
        valid &= rows == decoded
    if parsed[0].get("schema") == POLICY_SCHEMA:
        result["controller"] = parsed[0]
    qualification, rechecks, controls = 0, 0, 0
    for row in parsed[1:]:
        if row.get("schema") == CONTROL_SCHEMA:
            result["controls"].append(row)
            controls += 1
            valid &= controls == 1
            continue
        if row.get("schema") != PAIR_SCHEMA:
            valid = False
            continue
        result["pairs"].append(row)
        valid &= controls == 0
        if row.get("role") == "qualification":
            valid &= rechecks == 0 and qualification < 3 and row["index"]["value"] == qualification
            qualification += 1
        elif row.get("role") == "recheck":
            rechecks += 1
            valid &= rechecks <= 1 and row["index"]["value"] == 0
    if result["controller"] is not None:
        valid &= result["controller"]["qualificationPairs"]["value"] == qualification
    result["status"] = "observed" if valid else "invalid-or-incomplete"
    return result


def _scope_counts(rows, vocabulary):
    """Retain explicit timing semantics without exporting arbitrary diagnostic text."""
    return {key: dict(Counter(row[key] if row.get(key) in allowed else "missing-or-unknown" for row in rows))
            for key, allowed in vocabulary.items()}


def _scheduler_configuration(raw, *, temporal):
    if not isinstance(raw, str):
        return None
    if re.fullmatch(r"cpu-i[1-6]-j1-d(?:0|4)-sequential", raw):
        return raw
    if temporal and re.fullmatch(r"cpu-i1-j1-d0-sequential-w(?:4|8)-b1", raw):
        return raw
    if not temporal and re.fullmatch(r"cpu-i1-j1-d0-sequential-w(?:4|8)-b16", raw):
        return raw
    return None


def number(raw):
    """Keep absent, explicitly unavailable, invalid and observed zero distinct."""
    if raw is None:
        return {"status": "unavailable", "value": None, "reason": "missing"}
    if raw == "unavailable":
        return {"status": "unavailable", "value": None, "reason": "reported-unavailable"}
    try:
        value = float(raw)
    except (ValueError, TypeError, OverflowError):
        value = float("nan")
    if not math.isfinite(value) or value < 0:
        return {"status": "unavailable", "value": None, "reason": "invalid"}
    return {"status": "observed", "value": int(value) if value.is_integer() else value}


def aggregate(rows, key):
    values = [number(row.get(key)) for row in rows]
    observed = [row["value"] for row in values if row["status"] == "observed"]
    missing = Counter(row["reason"] for row in values if row["status"] != "observed")
    total = sum(observed)
    try:
        valid_total = math.isfinite(total)
    except OverflowError:
        valid_total = False
    complete = bool(values) and len(observed) == len(values) and valid_total
    return {
        "status": "observed" if complete else "partial" if observed and valid_total else "unavailable",
        "value": total if complete else None,
        "observed_subtotal": total if observed and valid_total else None,
        "observed_count": len(observed), "population_count": len(values),
        "missing_count": missing["missing"], "unavailable_count": missing["reported-unavailable"],
        "invalid_count": missing["invalid"],
        "min": min(observed) if observed else None, "max": max(observed) if observed else None,
        "mean": total / len(observed) if observed and valid_total else None,
        "overflowed": not valid_total,
    }


def interval(start, end, *, complete=True):
    if start is None or end is None:
        return {"status": "unavailable", "value": None, "reason": "boundary-not-observed"}
    elapsed = round((end - start).total_seconds() * 1000, 3)
    if elapsed < 0:
        return {"status": "unavailable", "value": None, "reason": "clock-moved-backwards"}
    if not complete:
        return {"status": "partial", "value": None, "observed_subtotal": elapsed, "reason": "interval-not-completed"}
    return {"status": "observed", "value": elapsed}


def _integer(fields, key):
    result = number(fields.get(key))
    value = result["value"]
    return value if result["status"] == "observed" and isinstance(value, int) else None


def _environment(header):
    fields = dict(FIELD.findall(header.replace("\n", " ")))
    output = {"scope": "current-report-snapshot-only"}
    # Do not copy arbitrary keys, paths, job references or free-form text.
    for key in ("version", "android", "webview"):
        raw = fields.get(key, "")
        if key == "webview":
            match = re.search(r"^webview=[^\s]+ ([0-9]+(?:\.[0-9]+){1,4})$", header, re.M)
            raw = match[1] if match else ""
        output[key] = raw if re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,4}", raw) else None
    for key in ("code", "sdk", "cpuCores", "heapLimitBytes", "deviceTotalBytes"):
        output[key] = number(fields.get(key))
    for key in ("screenInteractive", "deviceIdle", "batteryExempt", "backgroundRestricted", "lowMemory"):
        output[key] = fields.get(key) == "true" if fields.get(key) in ("true", "false") else None
    return output


def _profile_complete(profile):
    fields = profile["fields"]
    stages, graphs = profile["stages"], profile["graphs"]
    return (
        _integer(fields, "stageRecords") == len(stages)
        and _integer(fields, "graphRecords") == len(graphs)
        and _integer(fields, "droppedStageRecords") == 0
        and _integer(fields, "droppedGraphRecords") == 0
        and len({row.get("stage") for row in stages}) == len(stages)
        and len({row.get("graph") for row in graphs}) == len(graphs)
        and all(row.get("stage") in NATIVE_STAGES for row in stages)
        and all(row.get("graph") in NATIVE_GRAPHS for row in graphs)
    )


def _profile_totals(profiles):
    fields = [profile["fields"] for profile in profiles]
    stage_rows, graph_rows = defaultdict(list), defaultdict(list)
    for profile in profiles:
        for row in profile["stages"]:
            if row.get("stage") in NATIVE_STAGES:
                stage_rows[row["stage"]].append(row)
        for row in profile["graphs"]:
            if row.get("graph") in NATIVE_GRAPHS:
                graph_rows[row["graph"]].append(row)
    telemetry = {}
    for key in TELEMETRY:
        # Values are a fixed vocabulary, never arbitrary report text.
        allowed = {"available", "partial", "unavailable", "java-heap", "observed"}
        telemetry[key] = dict(Counter(row[key] if row.get(key) in allowed else "missing-or-unknown" for row in fields))
    return {
        "count": len(profiles), "summary_lines": [row["line"] for row in profiles],
        "outcomes": dict(Counter(row.get("outcome") if row.get("outcome") in {"completed", "released", "failed", "cancelled", "interrupted"} else "unknown" for row in fields)),
        "metrics": {key: aggregate(fields, key) for key in SUMMARY_METRICS},
        "telemetry": telemetry,
        "measurement_scopes": _scope_counts(fields, SUMMARY_SCOPES),
        "temporal_configuration_count_scope": "session-init-attempts-not-successful-runs",
        "frequency_configuration_count_scope": "session-init-attempts-not-successful-runs",
        "passage_policy_snapshots": [
            {"summary_line": profile["line"], **_passage_policy(
                profile.get("policy_records", ()), profile["fields"].get("passagePolicy"),
                source="retained-profile")}
            for profile in profiles
        ],
        "stages": {name: {**{key: aggregate(rows, key) for key in ("samples", "wallMs", "cpuMs", "processCpuMs")},
                          "measurement_scopes": _scope_counts(rows, STAGE_SCOPES)} for name, rows in sorted(stage_rows.items())},
        "graphs": {name: {**{key: aggregate(rows, key) for key in GRAPH_METRICS},
                          "measurement_scopes": _scope_counts(rows, GRAPH_SCOPES)} for name, rows in sorted(graph_rows.items())},
    }


DURABLE_METRICS = (
    "wallMs", "modelInitWallMs", "inferenceWallMs", "inferenceCount", "sessionInitCount",
    "inferenceThreadCpuMs", "inferenceProcessCpuMs", "cacheModelHits", "cacheModelMisses",
    "schedulerCalibrationWallMs", "schedulerCalibrationCount",
) + TEMPORAL_SESSION_METRICS + FREQUENCY_SESSION_METRICS


def _durable_summaries(header, current_reference):
    section = header.partition("DURABLE ANALYSIS SUMMARIES")[2].partition("ANDROID PREVIOUS PROCESS EXITS")[0]
    schema = re.search(r"^schema=(diagnostic-job-summary-v[12])(?: |$)", section, re.M)
    if schema is None:
        return []
    jobs, current, current_route = [], None, None
    for line in section.splitlines():
        fields = dict(FIELD.findall(line))
        if line.startswith("jobRef="):
            current, current_route = None, None
            if len(jobs) >= 3 or not re.fullmatch(r"[a-f0-9]{16}", fields.get("jobRef", "")):
                continue
            current = {"ordinal": len(jobs) + 1, "matches_current_job": fields["jobRef"] == current_reference,
                       "summary_schema": schema[1],
                       "scope": "durable-observation-not-controlled-benchmark",
                       "state": fields.get("state") if fields.get("state") in {"preparing", "queued", "running", "cancelling", "completed", "failed", "cancelled", "interrupted"} else None,
                       "analysisQuality": fields.get("analysisQuality") if fields.get("analysisQuality") in {"precision", "balanced"} else None,
                       "stages": {}, "native_routes": {}}
            for key in ("lifecycleElapsedMs", "durationMs", "recoveryGaps", "completedStages", "restoredStages"):
                current[key] = number(fields.get(key))
            jobs.append(current)
        elif current is not None and line.startswith(" stage=") and fields.get("stage") in STAGES | {"preparing", "compatibility", "generate", "save", "other"}:
            current_route = None
            current["stages"][fields["stage"]] = {"observed_wall_ms": number(fields.get("observedWallMs")), "clock": "monotonic-observed-intervals-restart-gaps-excluded"}
        elif current is not None and line.startswith(" route="):
            current_route = None
            if fields.get("route") not in {"native-deux-v1", "native-mdx-v1", "native-game-v1"}:
                continue
            route = {key: number(fields.get(key)) for key in ("passages", "completed", "cancelled", "otherOutcomes")}
            route["cpu_scopes"] = {"thread": "calling-thread", "process": "all-app-threads"}
            route["last_scheduling_configuration"] = {
                key: _scheduler_configuration(fields.get(key), temporal=key == "lastTemporalConfig")
                for key in ("lastTemporalConfig", "lastFrequencyConfig")
            }
            route["temporal_configuration_count_scope"] = "session-init-attempts-not-successful-runs"
            route["frequency_configuration_count_scope"] = "session-init-attempts-not-successful-runs"
            route["last_configuration_scope"] = "last-observed-configuration-not-entire-passage-or-job"
            route["_policy_records"] = []
            route["metrics"] = {}
            population = _integer(fields, "passages")
            for key in DURABLE_METRICS:
                measurement, count = number(fields.get(key)), _integer(fields, key + "MeasuredPassages")
                valid = measurement["status"] == "observed" and count is not None and population is not None and 0 < count <= population
                complete = valid and count == population
                route["metrics"][key] = {"status": "observed" if complete else "partial" if valid else "unavailable",
                                          "value": measurement["value"] if complete else None,
                                          "observed_subtotal": measurement["value"] if valid else None,
                                          "observed_count": count, "population_count": population}
            current["native_routes"][fields["route"]] = route
            if schema[1] == "diagnostic-job-summary-v2" and fields["route"] == "native-deux-v1":
                current_route = route
        elif current_route is not None and fields.get("schema") in POLICY_SCHEMAS:
            current_route["_policy_records"].append(line.strip())
    for job in jobs:
        for route in job["native_routes"].values():
            route["passage_policy"] = _passage_policy(route.pop("_policy_records"), source="durable-route-latest-snapshot")
    return jobs


def summarize(report):
    """Return privacy-minimized observations from one retained diagnostic report."""
    if not isinstance(report, str) or not report.startswith("LIGHTFORGE DIAGNOSTIC REPORT\n"):
        raise ValueError("Expected a LightForge diagnostic report")
    if len(report.encode("utf-8")) > MAX_REPORT_BYTES:
        raise ValueError("Diagnostic report exceeds the supported size")
    lines = report.splitlines()
    marker = next((index for index, line in enumerate(lines) if line.startswith("PERSISTENT EVENT TRACE")), None)
    if marker is None:
        raise ValueError("Persistent event trace section is missing")
    events, malformed = [], []
    for index in range(marker + 1, len(lines)):
        raw = lines[index]
        match = EVENT.fullmatch(raw)
        if not match:
            if raw and raw != "END OF DIAGNOSTIC REPORT":
                malformed.append(index + 1)
            continue
        try:
            stamp = datetime.fromisoformat(match[1].replace("Z", "+00:00"))
        except ValueError:
            malformed.append(index + 1)
            continue
        events.append({"time": stamp, "line": index + 1, "tag": match[3], "message": match[4], "fields": dict(FIELD.findall(match[4]))})
    origin = events[0]["time"] if events else None
    offset = lambda stamp: round((stamp - origin).total_seconds() * 1000, 3) if stamp is not None and origin is not None else None
    header = "\n".join(lines[:marker])
    snapshot_text = header.partition("CURRENT ANALYSIS JOB")[2].partition("DURABLE ANALYSIS SUMMARIES")[0].partition("ANDROID PREVIOUS PROCESS EXITS")[0]
    snapshot_fields = dict(FIELD.findall(snapshot_text.replace("\n", " ")))
    snapshot = {"scope": "reported-current-attempt-unbound-to-trace"}
    for key in ("elapsedMs", "completedStages", "restoredStages", "progress"):
        snapshot[key] = number(snapshot_fields.get(key))
    snapshot["state"] = snapshot_fields.get("state") if snapshot_fields.get("state") in ("queued", "running", "completed", "interrupted", "failed", "cancelled") else None
    snapshot["analysisQuality"] = snapshot_fields.get("analysisQuality") if snapshot_fields.get("analysisQuality") in ("precision", "balanced", "fast", "studio") else None
    attempts, current, pending_profile = [], None, None
    gaps, preview_intervals, preview_pending = [], [], {}
    orphan_profiles, orphan_policies, renderer_events, runtime_versions = [], [], [], set()

    def new_attempt(event, explicit):
        attempt = {
            "ordinal": len(attempts) + 1, "first": event, "explicit": explicit, "terminal": None,
            "stages": [], "active_stages": {}, "profiles": [], "native": [], "native_pending": {},
            "voice": [], "voice_by_index": {}, "restored_stages": set(), "restored_voice": None,
            "observed_zero_restored": False, "last": event,
        }
        attempts.append(attempt)
        if len(attempts) > 1:
            previous = attempts[-2]
            if previous["terminal"] and previous["terminal"][1] == "interrupted":
                end = previous["terminal"][0]
                gaps.append({"after_attempt": previous["ordinal"], "next_attempt": attempt["ordinal"],
                             "association": "chronological-next-attempt-not-verified-job-lineage",
                             "lines": [end["line"], event["line"]], "until_next_attempt_ms": interval(end["time"], event["time"]),
                             "scope": "interruption-gap-excluded-from-compute-totals"})
        return attempt

    def end_stage(attempt, stage, event, completed):
        row = attempt["active_stages"].pop(stage, None)
        if row is None:
            row = {"stage": stage, "start": None, "restored": False}
            attempt["stages"].append(row)
        row.update(end=event, completed=completed)

    for event in events:
        tag, message, fields = event["tag"], event["message"], event["fields"]
        is_profile = tag == "native-inference-profile"
        if not is_profile:
            pending_profile = None
        if tag == "native-phase" and message.startswith("runtime-load-start") and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,4}", fields.get("version", "")):
            runtime_versions.add(fields["version"])
        if tag in ("preview-renderer", "analysis-renderer"):
            renderer_events.append({"renderer": tag.removesuffix("-renderer"), "line": event["line"], "offset_ms": offset(event["time"]),
                                    "event": "reclaimed" if "reclaimed" in message else "failure"})
        if tag == "completed-restore-watchdog":
            nonce = fields.get("nonce")
            if message.startswith("completed-restore lease begin") and nonce:
                preview_pending[nonce] = event
            elif message.startswith("visual hardware frame committed") and nonce:
                begin = preview_pending.pop(nonce, None)
                preview_intervals.append({"lines": [begin["line"] if begin else None, event["line"]],
                                          "hardware_frame_ms": interval(begin["time"] if begin else None, event["time"])})
        explicit = ((tag == "background" and message == "Analysis state=queued")
                    or (tag == "analysis-service" and message.startswith("starting job="))
                    or (tag == "background" and message == "Runner started"))
        work = tag in ("analysis-worker", "native-passage", "native-inference-profile", "native-phase", "native-progress", "analysis-progress")
        new_queue = tag == "background" and message == "Analysis state=queued"
        if explicit and (current is None or current["terminal"] or new_queue):
            current = new_attempt(event, True)
        elif work and (current is None or current["terminal"]):
            current = new_attempt(event, False)
        # Diagnostics emitted after terminal shutdown, Activity events and
        # restoration of a preview cannot extend an analysis attempt.
        if current is None or current["terminal"]:
            continue
        if work or tag in ("analysis-finish", "analysis-shutdown", "composition-worker"):
            current["last"] = event
        restored = _integer(fields, "restoredStages")
        if restored == 0:
            current["observed_zero_restored"] = True
        if restored is not None and restored > 0:
            current["restoration_observed"] = True

        if is_profile:
            schema = fields.get("schema")
            if schema == "native-inference-profile-v2":
                pending_profile = {"line": event["line"], "fields": fields, "stages": [], "graphs": [], "policy_records": []}
                current["profiles"].append(pending_profile)
            elif schema in ("native-inference-stage-v1", "native-inference-graph-v2"):
                if pending_profile is None:
                    orphan_profiles.append(event["line"])
                else:
                    pending_profile["stages" if schema == "native-inference-stage-v1" else "graphs"].append(fields)
            elif schema in POLICY_SCHEMAS:
                if pending_profile is None:
                    orphan_policies.append({"line": event["line"], "scope": "unbound-controller-record-not-a-passage",
                                            "record": _policy_record(message)})
                else:
                    pending_profile["policy_records"].append(message)

        if tag == "analysis-worker":
            match = re.fullmatch(r"Stage (started|completed): ([a-z]+)", message)
            if match and match[2] in STAGES:
                stage = match[2]
                current["analysis_stage"] = stage
                if match[1] == "started":
                    if stage in current["active_stages"]:
                        end_stage(current, stage, event, False)
                    row = {"stage": stage, "start": event, "end": None, "completed": False, "restored": False}
                    current["stages"].append(row)
                    current["active_stages"][stage] = row
                else:
                    end_stage(current, stage, event, True)
            elif fields.get("stage") in STAGES:
                current["analysis_stage"] = fields["stage"]
            if fields.get("stage") == "separation":
                current["separation_index"] = _integer(fields, "passageIndex")
                current["separation_count"] = _integer(fields, "passageCount")
            if fields.get("stage") == "voice" and _integer(fields, "passageIndex") is not None:
                index = _integer(fields, "passageIndex")
                if index not in current["voice_by_index"]:
                    row = {"index": index, "count": _integer(fields, "passageCount"), "start": event, "end": None}
                    current["voice"].append(row)
                    current["voice_by_index"][index] = row
        voice_restored = _integer(fields, "restoredPassages")
        if voice_restored is not None:
            if voice_restored > 0:
                current["restoration_observed"] = True
            # UI stages deliberately differ from worker stages (separation can
            # appear as "voice"). Only the worker establishes actual scope.
            if current.get("analysis_stage") == "voice":
                current["restored_voice"] = max(current["restored_voice"] or 0, voice_restored)
        if tag == "analysis-progress":
            for stage in STAGES:
                if f"stage=Completed {stage} work restored" in message:
                    current["restored_stages"].add(stage)
                    current["restoration_observed"] = True
                    if stage in current["active_stages"]:
                        current["active_stages"][stage]["restored"] = True
            index, completed = _integer(fields, "passage"), _integer(fields, "completed")
            if fields.get("checkpoint") == "true" and index is not None and completed is not None and completed >= index:
                row = current["voice_by_index"].get(index)
                if row is not None and row["end"] is None:
                    row["end"] = event
        if tag == "native-passage":
            private_key = fields.get("passage")
            if message.startswith("started;"):
                row = {"start": event, "end": None, "index": current.get("separation_index"), "count": current.get("separation_count"), "elapsed": None}
                current["native"].append(row)
                if private_key:
                    current["native_pending"][private_key] = row
            elif message.startswith("completed;"):
                row = current["native_pending"].pop(private_key, None)
                if row is None:
                    row = {"start": None, "index": current.get("separation_index"), "count": current.get("separation_count")}
                    current["native"].append(row)
                row.update(end=event, elapsed=fields.get("elapsedMs"))
        if tag == "composition-worker" and message == "Composition started":
            row = {"stage": "composition", "start": event, "end": None, "completed": False, "restored": False}
            current["stages"].append(row)
            current["active_stages"]["composition"] = row
        elif tag == "composition-worker" and message == "Composition completed" and "composition" in current["active_stages"]:
            end_stage(current, "composition", event, True)
        if tag in ("analysis-finish", "analysis-shutdown") and fields.get("state") in ("completed", "interrupted", "failed", "cancelled"):
            current["terminal"] = (event, fields["state"])
            for stage in list(current["active_stages"]):
                end_stage(current, stage, event, False)

    output_attempts = []
    for attempt in attempts:
        terminal = attempt["terminal"]
        end = terminal[0] if terminal else attempt["last"]
        resumed = bool(attempt.get("restoration_observed") or (attempt["restored_voice"] or 0) > 0)
        kind = "resumed" if resumed else "historical_partial" if not attempt["explicit"] else "fresh" if attempt["observed_zero_restored"] else "unknown"
        profiles = attempt["profiles"]
        complete = [row for row in profiles if _profile_complete(row) and row["fields"].get("outcome") == "completed"]
        incomplete = [row for row in profiles if not _profile_complete(row)]
        other = [row for row in profiles if _profile_complete(row) and row["fields"].get("outcome") != "completed"]
        stages = []
        for row in attempt["stages"]:
            start, stop = row["start"], row.get("end")
            stages.append({"stage": row["stage"], "lines": [start["line"] if start else None, stop["line"] if stop else None],
                           "completion": "completed" if row["completed"] else "incomplete",
                           "work": "restored" if row["restored"] else "mixed-restored-and-executed" if row["stage"] == "voice" and (attempt["restored_voice"] or 0) > 0 else "not-established",
                           "wall_ms": interval(start["time"] if start else None, stop["time"] if stop else None, complete=row["completed"])})
        passages = {}
        for name, rows in (("native_separation", attempt["native"]), ("voice", attempt["voice"])):
            rendered = []
            for row in rows:
                start, stop = row["start"], row.get("end")
                restored = name == "voice" and attempt["restored_voice"] is not None and row["index"] <= attempt["restored_voice"]
                rendered.append({"index": row.get("index"), "reported_count": row.get("count"),
                                 "lines": [start["line"] if start else None, stop["line"] if stop else None],
                                 "completion": "completed" if stop else "incomplete",
                                 "work": "restored" if restored else "executed" if name == "native_separation" or attempt["restored_voice"] is not None else "not-established",
                                 "wall_ms": interval(start["time"] if start else None, stop["time"] if stop else end["time"], complete=stop is not None),
                                 **({"reported_elapsed_ms": number(row.get("elapsed"))} if name == "native_separation" else {})})
            completed_rows = [row for row in rendered if row["completion"] == "completed"]
            key = "reported_elapsed_ms" if name == "native_separation" else "wall_ms"
            passages[name] = {"records": rendered,
                              "completed_executed_ms": aggregate([{key: row[key]["value"]} for row in completed_rows if row["work"] == "executed"], key),
                              "completed_restored_ms": aggregate([{key: row[key]["value"]} for row in completed_rows if row["work"] == "restored"], key)}
        output_attempts.append({
            "attempt": attempt["ordinal"], "kind": kind,
            "start_boundary": "explicit" if attempt["explicit"] else "not-observed",
            "terminal": terminal[1] if terminal else "not-observed",
            "lines": [attempt["first"]["line"], end["line"]],
            "start_offset_ms": offset(attempt["first"]["time"]), "end_offset_ms": offset(end["time"]),
            "attempt_wall_ms": interval(attempt["first"]["time"], end["time"], complete=attempt["explicit"] and terminal is not None),
            "cold_cache_status": "not-established", "restored_stages": sorted(attempt["restored_stages"]),
            "restored_voice_passages": number(attempt["restored_voice"]), "stages": stages, "passages": passages,
            "native_profiles": {"completed_complete_bundles": _profile_totals(complete),
                                "incomplete_bundles": _profile_totals(incomplete),
                                "other_outcomes_complete_bundles": _profile_totals(other)},
        })
    if attempts and attempts[-1]["terminal"] and attempts[-1]["terminal"][1] == "interrupted":
        gaps.append({"after_attempt": attempts[-1]["ordinal"], "next_attempt": None,
                     "until_next_attempt_ms": interval(None, None), "scope": "next-attempt-not-observed"})
    return {
        "schema": "lightforge.diagnostic-evidence.v1", "qualification_status": "not-evaluated",
        "source": {"line_count": len(lines), "retained_event_count": len(events), "malformed_event_lines": malformed,
                   "absolute_timestamps_omitted": True, "unassociated_profile_detail_lines": orphan_profiles,
                   "unassociated_passage_policy_records": orphan_policies},
        "current_environment": _environment(header.partition("CURRENT ANALYSIS JOB")[0]),
        "current_job_snapshot": snapshot, "observed_native_runtime_versions": sorted(runtime_versions),
        "durable_job_summaries": _durable_summaries(header, snapshot_fields.get("jobRef")),
        "attempts": output_attempts, "interruption_gaps": gaps,
        "renderer_events": renderer_events, "completed_preview_restoration": preview_intervals,
        "full_song_runtime_ms": {"status": "unavailable", "value": None, "reason": "complete-job-lineage-and-workload-not-established"},
        "limitations": [
            "Retained diagnostics are observations, not a controlled benchmark or a quality comparison.",
            "Current environment and job snapshot cannot bind every historical event to the current app version or job.",
            "Fresh means a captured attempt with zero restored-stage observations, not proven cold model or filesystem caches.",
            "Chronologically adjacent attempts are not authenticated parent/resume lineage; private identifiers are omitted.",
            "Inclusive stage, passage and profile timings overlap; never add them together as total analysis time.",
            "Profile bundles with missing detail records or non-completed outcomes are separate from completed complete bundles.",
            "Absent, invalid or unavailable telemetry does not establish zero usage or zero cost.",
            "Temporal and frequency configuration counts are session initialization attempts, including failed initialization; the final configuration cannot describe mixed passages.",
            "Passage policy snapshots repeat controller history; do not add their pair counts, overhead or projected accrued savings across snapshots or to production graph totals.",
            "Policy pair timings use nanoseconds; projected payback is not measured whole-job savings, and reported qualification is not independently re-evaluated here.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.report.open("rb") as stream:
        raw = stream.read(MAX_REPORT_BYTES + 1)
    if len(raw) > MAX_REPORT_BYTES:
        parser.error("Diagnostic report exceeds the supported size")
    result = summarize(raw.decode("utf-8"))
    # Exclusive creation protects the input and existing evidence artifacts.
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
