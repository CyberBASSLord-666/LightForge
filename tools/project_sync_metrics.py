#!/usr/bin/env python3
"""Project complete realization timing observations without inventing quality evidence.

The selected perceptual basis is mandatory. Predicted response is kept explicitly
estimated and never becomes a physical measurement or human-review result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

PROTOCOL = "lightforge-sync-metric-projection-v1"
MAX_INPUT_BYTES = 4 * 1024**2
CLASSES = {
    "vocals": "vocals", "bass": "bass", "kick": "kick", "snare": "snare",
    "percussion": "percussion", "beat": "beat", "downbeat": "downbeat",
    "section": "section_transition", "climax": "climax",
    "mechanical": "mechanical_actuator", "lighting": "lighting_output",
}
STATISTICS = {
    "medianMs": "median_ms", "p90Ms": "p90_ms", "p95Ms": "p95_ms",
    "p99Ms": "p99_ms", "maxMs": "max_ms",
}
BASES = {
    "command": ("available", "command timestamp minus intended perceptual target"),
    "predictedPerceptual": ("estimated", "predicted perceptual response minus intended target"),
    "perceptual": ("available", "measured perceptual response minus intended target"),
}


def require(value, message):
    if not value:
        raise ValueError(message)


def integer(value, label):
    require(type(value) is int and value >= 0, label + " must be a non-negative integer")
    return value


def distribution(value, basis, maximum_count):
    require(isinstance(value, dict), "Missing timing distribution")
    require(set(STATISTICS) | {"basis", "count", "state"} <= set(value),
            "Timing distribution omits required producer fields")
    expected_state, expected_basis = BASES[basis]
    require(value.get("basis") == expected_basis, "Timing basis differs from the producer contract")
    count = integer(value.get("count"), "timing count")
    require(count <= maximum_count, "Timing count exceeds available events")
    if value.get("state") == "unavailable":
        require(count == 0 and all(value.get(key) is None for key in STATISTICS),
                "Unavailable timing contains numeric evidence")
        return None
    require(value.get("state") == expected_state and count > 0,
            "Timing state does not establish the selected evidence basis")
    numbers = [value.get(key) for key in STATISTICS]
    require(all(type(v) in (int, float) and 0 <= v <= 10000 and math.isfinite(v) for v in numbers),
            "Timing statistic is missing, non-finite or outside the compiled metric bounds")
    require(numbers == sorted(numbers), "Timing percentiles are not monotonic")
    return {name: float(value[key]) for key, name in STATISTICS.items()}


def project(report, *, perceptual_basis, source_commit, run_id, report_sha256):
    require(perceptual_basis in {"predicted", "measured"}, "Choose predicted or measured explicitly")
    require(isinstance(source_commit, str) and re.fullmatch(r"[0-9a-f]{40}", source_commit), "Invalid source commit")
    require(isinstance(report_sha256, str) and re.fullmatch(r"[0-9a-f]{64}", report_sha256), "Invalid report digest")
    require(isinstance(run_id, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", run_id), "Invalid paired run ID")
    require(isinstance(report, dict) and type(report.get("version")) is int and report["version"] == 1
            and report.get("state") == "available", "Unsupported perceptual report")
    evidence = report.get("eventEvidence")
    require(isinstance(evidence, dict), "Missing event inventory")
    counts = {name: integer(evidence.get(name), name) for name in (
        "suppliedCount", "acceptedCount", "invalidCount", "omittedCount", "omittedClassCount",
        "maximumEvents", "maximumClasses",
    )}
    require(counts["maximumEvents"] == 10000 and counts["maximumClasses"] == 32,
            "Unexpected bounded producer contract")
    require(counts["invalidCount"] == counts["omittedCount"] == counts["omittedClassCount"] == 0,
            "Incomplete or invalid event evidence cannot become a complete metric projection")
    require(counts["acceptedCount"] == counts["suppliedCount"] <= counts["maximumEvents"],
            "Event inventory is inconsistent")
    require(evidence.get("state") in {"available", "unavailable"}, "Invalid event evidence state")
    require("source" in evidence, "Missing producer event evidence source")
    require((evidence["state"] == "available" and isinstance(evidence["source"], str) and evidence["source"] in {
        "options.events", "options.eventEvidence", "show.choreography.perceptualEventEvidence",
    }) or (evidence["state"] == "unavailable" and evidence["source"] is None),
            "Producer event evidence source differs from its availability state")
    require(evidence["state"] == "available" or counts["acceptedCount"] == 0,
            "Unavailable event evidence has accepted rows")
    per_class = report.get("perEventClass")
    require(isinstance(per_class, dict) and set(CLASSES) <= set(per_class)
            and len(per_class) <= counts["maximumClasses"], "Missing producer event classes")
    total = 0
    for name, row in per_class.items():
        require(isinstance(row, dict) and row.get("eventClass") == name, "Class identity mismatch")
        event = row.get("eventEvidence")
        require(isinstance(event, dict), "Missing class event inventory")
        count = integer(event.get("count"), "class event count")
        require(event.get("state") == ("available" if count else "unavailable"), "Class evidence state mismatch")
        total += count
    require(total == counts["acceptedCount"], "Class inventory does not cover all accepted events")
    aggregate = report.get("aggregate")
    require(isinstance(aggregate, dict) and isinstance(aggregate.get("timing"), dict), "Missing aggregate timing")

    metrics, provenance, unobserved = {}, {}, []
    selected = "predictedPerceptual" if perceptual_basis == "predicted" else "perceptual"
    for output_basis, input_basis in (("command", "command"), ("perceptual", selected)):
        class_timing_count = 0
        for input_name, row in per_class.items():
            timings = row.get("timing")
            require(isinstance(timings, dict), "Missing class timing")
            values = distribution(timings.get(input_basis), input_basis, row["eventEvidence"]["count"])
            class_timing_count += timings[input_basis]["count"]
            if input_name not in CLASSES:
                continue
            for statistic in STATISTICS.values():
                name = f"quality.sync.{output_basis}.{CLASSES[input_name]}.{statistic}"
                if values is None:
                    unobserved.append(name)
                else:
                    metrics[name] = values[statistic]
                    provenance[name] = {"basis": input_basis, "state": BASES[input_basis][0],
                                        "matched_timing_pairs": timings[input_basis]["count"]}
        aggregate_values = distribution(aggregate["timing"].get(input_basis), input_basis, total)
        require(aggregate["timing"][input_basis]["count"] == class_timing_count,
                "Aggregate timing count differs from the class inventory")
        if output_basis == "perceptual":
            name = "quality.perceptual_sync_p95_ms"
            if aggregate_values is None:
                unobserved.append(name)
            else:
                metrics[name] = aggregate_values["p95_ms"]
                provenance[name] = {"basis": input_basis, "state": BASES[input_basis][0],
                                    "matched_timing_pairs": class_timing_count}
    return {
        "schema_version": 1, "protocol": PROTOCOL,
        "source": {"commit": source_commit, "paired_run_id": run_id, "report_sha256": report_sha256},
        "perceptual_basis": perceptual_basis,
        "physical_validation_established": False,
        "detector_accuracy_established": False, "human_review_established": False,
        "release_qualified": False,
        "metrics": dict(sorted(metrics.items())), "measurement_provenance": dict(sorted(provenance.items())),
        "unobserved_metrics": sorted(unobserved),
        "source_event_count": total,
        "scope": "Absolute realization timing errors against explicit intended targets; not annotation-backed MIR accuracy or release qualification.",
    }


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key")
        result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--perceptual-basis", required=True, choices=("predicted", "measured"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    require(args.report.is_file() and not args.report.is_symlink(), "Report must be a regular file")
    with args.report.open("rb") as stream:
        raw = stream.read(MAX_INPUT_BYTES + 1)
    require(0 < len(raw) <= MAX_INPUT_BYTES, "Report size outside bounds")
    digest = hashlib.sha256(raw).hexdigest()
    require(digest == args.expected_sha256, "Report digest mismatch")
    report = json.loads(raw, object_pairs_hook=unique_object,
                        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
    output = project(report, perceptual_basis=args.perceptual_basis, source_commit=args.source_commit,
                     run_id=args.run_id, report_sha256=digest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".sync-projection-", dir=args.output.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(output, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        os.link(temporary, args.output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    print(json.dumps({"observed_metrics": len(output["metrics"]),
                      "unobserved_metrics": len(output["unobserved_metrics"]),
                      "perceptual_basis": args.perceptual_basis, "release_qualified": False}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        raise SystemExit("Synchronization projection failed: " + type(exc).__name__) from None
