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
    "inference-gate-wait", "cache-preflight", "buffer-init", "runtime-setup",
    "pcm-read", "feature-encode", "model-init", "tensor-bind", "inference",
    "pack", "scatter", "decode", "output-write", "output-flush", "output-commit",
))
NATIVE_GRAPHS = frozenset(("front", "head-0", "head-1")) | frozenset(
    f"block-{index:02d}-{axis}" for index in range(12) for axis in ("time", "frequency")
)
SUMMARY_METRICS = (
    "wallMs", "instrumentedCpuMs", "waitWallMs", "waitCpuMs", "engineInitWallMs",
    "preflightWallMs", "bufferInitWallMs", "runtimeInitWallMs", "preprocessWallMs",
    "preprocessCpuMs", "modelInitWallMs", "modelInitCpuMs", "inferenceWallMs",
    "inferenceCpuMs", "postprocessWallMs", "postprocessCpuMs", "cacheModelHits",
    "cacheModelMisses", "cacheHitBytes", "cacheMissBytes", "directBufferBytes",
)
GRAPH_METRICS = ("runCount", "runWallMs", "runCpuMs", "sessionInitWallMs", "packWallMs", "scatterWallMs")
TELEMETRY = ("cpuTelemetry", "memoryTelemetry", "acceleratorTelemetry", "directBufferTelemetry", "cacheTelemetry")


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
        allowed = {"available", "unavailable", "java-heap", "observed"}
        telemetry[key] = dict(Counter(row[key] if row.get(key) in allowed else "missing-or-unknown" for row in fields))
    return {
        "count": len(profiles), "summary_lines": [row["line"] for row in profiles],
        "outcomes": dict(Counter(row.get("outcome") if row.get("outcome") in {"completed", "released", "failed", "cancelled", "interrupted"} else "unknown" for row in fields)),
        "metrics": {key: aggregate(fields, key) for key in SUMMARY_METRICS},
        "telemetry": telemetry,
        "stages": {name: {key: aggregate(rows, key) for key in ("samples", "wallMs", "cpuMs")} for name, rows in sorted(stage_rows.items())},
        "graphs": {name: {key: aggregate(rows, key) for key in GRAPH_METRICS} for name, rows in sorted(graph_rows.items())},
    }


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
    snapshot_text = header.partition("CURRENT ANALYSIS JOB")[2].partition("ANDROID PREVIOUS PROCESS EXITS")[0]
    snapshot_fields = dict(FIELD.findall(snapshot_text.replace("\n", " ")))
    snapshot = {"scope": "reported-current-attempt-unbound-to-trace"}
    for key in ("elapsedMs", "completedStages", "restoredStages", "progress"):
        snapshot[key] = number(snapshot_fields.get(key))
    snapshot["state"] = snapshot_fields.get("state") if snapshot_fields.get("state") in ("queued", "running", "completed", "interrupted", "failed", "cancelled") else None
    snapshot["analysisQuality"] = snapshot_fields.get("analysisQuality") if snapshot_fields.get("analysisQuality") in ("precision", "balanced", "fast", "studio") else None
    attempts, current, pending_profile = [], None, None
    gaps, preview_intervals, preview_pending = [], [], {}
    orphan_profiles, renderer_events, runtime_versions = [], [], set()

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
                pending_profile = {"line": event["line"], "fields": fields, "stages": [], "graphs": []}
                current["profiles"].append(pending_profile)
            elif schema in ("native-inference-stage-v1", "native-inference-graph-v2"):
                if pending_profile is None:
                    orphan_profiles.append(event["line"])
                else:
                    pending_profile["stages" if schema == "native-inference-stage-v1" else "graphs"].append(fields)

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
                   "absolute_timestamps_omitted": True, "unassociated_profile_detail_lines": orphan_profiles},
        "current_environment": _environment(header.partition("CURRENT ANALYSIS JOB")[0]),
        "current_job_snapshot": snapshot, "observed_native_runtime_versions": sorted(runtime_versions),
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
